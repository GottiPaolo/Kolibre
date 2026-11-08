import os
import re
from collections import defaultdict
from datetime import datetime

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import config, models, schemas, database, auth
from ..istanti import quando
from ..calibre.library import CalibreLibrary
from ..logging_utils import log_message
from ..services import capitoli_delle_note, link_condivisibile, widowed_highlights
from ..schemas_risposte import (
    Annotazione, AnnotazioneEsportata, Esito, Evidenziazione, EvidenziazioneOrfana,
    GruppiVedovi, PosizioniDaRitentare, ProposteVedove, VedoveRiparate,
)
from .libraries import NESSUNA_BIBLIOTECA_TUA, resolve_default_library_folder
router = APIRouter(prefix="/api/kolibre/annotations", tags=["annotations"])


def _guess_title_from_path(local_path: str) -> str:
    """Best-effort display title for an OrphanHighlight — no book is known
    yet, so this is just the bare filename with its extension stripped,
    Python port of main.lua's own _guessTitleFromPath (same convention, used
    for the exact same "nothing better to show" situation there). If the
    filename follows the "Title - Author" convention, only the title half is
    kept — mirrors the fix applied to the Lua original, which used to leave
    the author glued onto the guessed title (garbling both the fuzzy match
    AND, here, the display title)."""
    filename = os.path.basename(local_path or "") or "?"
    name, _ext = os.path.splitext(filename)
    name = name or filename
    title_only = re.match(r"^(.+?)\s+-\s+.+$", name)
    return title_only.group(1) if title_only else name


def _serialize(h: models.Highlight, book_meta: dict = None, device_names: dict = None) -> dict:
    meta = (book_meta or {}).get((h.library, h.calibre_book_id), {})
    return {
        "id": h.id,
        "calibre_book_id": h.calibre_book_id,
        "library": h.library,
        "text": h.text,
        "notes": h.comment or "",
        "chapter": h.chapter,
        "page": h.page or 0,
        "cfi_start": h.cfi_start,
        "cfi_end": h.cfi_end,
        "source": h.source,
        "device_id": h.device_id,
        "device_name": (device_names or {}).get(h.device_id),
        "position_status": h.position_status,
        "color": h.color,
        "trashed": h.deleted_at is not None,
        "created_at": quando(h.created_at),
        "updated_at": quando(h.updated_at),
        # The frontend's Annotations page only ever has the ACTIVE library's
        # books loaded (App.vue's books.value), so a highlight on a book from
        # a DIFFERENT library used to render as "Sconosciuto" there — not
        # actually missing, just unrecognizable, which reads as "some
        # annotations disappeared" from the outside. Enriching here (same
        # cross-library book_meta lookup /export already builds) fixes that
        # regardless of which library happens to be active in the sidebar.
        "book_title": meta.get("title"),
        "book_author": meta.get("author"),
        "book_formats": meta.get("formats") or [],
        "is_orphan": False,
    }


def _serialize_orphan(o: models.OrphanHighlight, device_names: dict = None) -> dict:
    """
    Mirrors _serialize's shape as closely as possible so the frontend can
    treat both kinds of row almost identically — deliberately DIFFERENT on
    the fields that don't apply: calibre_book_id/library/cfi_*/position_status
    are always null (there's no book yet), and `id` is a string
    ("orphan-<n>") rather than an int, both so the frontend can branch on
    `is_orphan` and so ids never collide with a real Highlight's (both
    tables auto-increment from 1 independently). `orphan_key` is a stable
    per-(device, local file) identity for the frontend's grouping map —
    plain `library:calibre_book_id` collapses to the same key for every
    orphan (both null), which is exactly the bug this field avoids.
    """
    return {
        "id": f"orphan-{o.id}",
        "calibre_book_id": None,
        "library": None,
        "text": o.text,
        "notes": o.comment or "",
        "chapter": o.chapter,
        "page": o.page or 0,
        "cfi_start": None,
        "cfi_end": None,
        "source": "device",
        "device_id": o.device_id,
        "device_name": (device_names or {}).get(o.device_id),
        "position_status": None,
        "color": o.color,
        "trashed": o.deleted_at is not None,
        "created_at": quando(o.created_at),
        "updated_at": quando(o.updated_at),
        "book_title": _guess_title_from_path(o.local_path),
        "book_author": None,
        "is_orphan": True,
        "orphan_key": f"{o.device_id}:{o.local_path}",
    }


def _indirizzo_base(richiesta: Request) -> Optional[str]:
    """L'indirizzo di questa installazione. Le tre regole stanno in
    `link_condivisibile.indirizzo_base`: qui si passano solo i pezzi che
    arrivano dalla richiesta."""
    return link_condivisibile.indirizzo_base(
        host=richiesta.headers.get("host"),
        schema=richiesta.url.scheme,
        porta_del_frontend=config.PUBLIC_FRONTEND_PORT,
        host_inoltrato=richiesta.headers.get("x-forwarded-host"),
        schema_inoltrato=richiesta.headers.get("x-forwarded-proto"),
        scritto_a_mano=config.PUBLIC_BASE_URL,
    )


def _build_book_meta(highlights: list) -> dict:
    """(library, calibre_book_id) -> {"title":..., "author":..., "formats": [...]},
    one CalibreLibrary.list_books() call per library touched, not per highlight."""
    by_library = defaultdict(list)
    for h in highlights:
        by_library[h.library].append(h)

    book_meta = {}
    for library in by_library:
        try:
            lib = CalibreLibrary(config.library_path(library))
            for b in lib.list_books():
                book_meta[(library, b["id"])] = {
                    "title": b["title"],
                    "author": b["author"] or "Unknown Author",
                    # Serve al frontend per aprire il lettore GIUSTO. La
                    # pagina Annotazioni chiedeva sempre l'EPUB, con un
                    # commento che diceva "nessun percorso di sync da
                    # dispositivo produce highlight su un PDF": non e' vero,
                    # devices.py ha un ramo di deduplica apposta per i PDF
                    # (pos0 e' EPUB-only, quindi ricade su pagina+testo) — e
                    # su un libro di solo PDF il lettore EPUB si apriva su
                    # "Impossibile caricare il libro nel web reader".
                    "formats": b.get("formats") or [],
                    # Serve a comporre il link condivisibile di una nota, e
                    # arriva gratis: questo giro di `list_books()` lo stiamo
                    # gia' facendo. `uuid_della_biblioteca` sono tutti gli
                    # uuid di quella biblioteca, perche' per accorciarne uno
                    # bisogna sapere che non ne confonde un altro.
                    "uuid": b.get("uuid"),
                }
            tutti = [b.get("uuid") for b in lib.list_books()]
            for chiave in list(book_meta):
                if chiave[0] == library:
                    book_meta[chiave]["uuid_della_biblioteca"] = tutti
        except Exception:
            continue  # a library that no longer exists on disk shouldn't break this for the others
    return book_meta


def _build_device_names(device_ids, db: Session) -> dict:
    """device_id -> name, one query for every device actually referenced (not per highlight)."""
    device_ids = {d for d in device_ids if d is not None}
    if not device_ids:
        return {}
    rows = db.query(models.Device.id, models.Device.name).filter(models.Device.id.in_(device_ids)).all()
    return {device_id: name for device_id, name in rows}


def _get_owned_orphan(db: Session, id: int, current_user: models.User) -> models.OrphanHighlight:
    o = db.query(models.OrphanHighlight).filter(
        models.OrphanHighlight.id == id, models.OrphanHighlight.user_id == current_user.id
    ).first()
    if not o:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return o


@router.get("", responses={200: {"model": list[Annotazione]}})
def list_annotations(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Returns both active and trashed annotations — the frontend filters by `trashed` itself (Cestino tab)."""
    hls = (
        db.query(models.Highlight)
        .filter(models.Highlight.user_id == current_user.id)
        .order_by(models.Highlight.created_at.desc())
        .all()
    )
    orphans = (
        db.query(models.OrphanHighlight)
        .filter(models.OrphanHighlight.user_id == current_user.id)
        .order_by(models.OrphanHighlight.created_at.desc())
        .all()
    )

    # CFI backfill for device highlights (koreader_pos0/1 -> real CFI) used
    # to run right here, inline, bounded per call — moved to a periodic
    # background loop instead (main.py's _backfill_highlight_positions_loop,
    # services/highlight_position.py's own docstring explains why: with a
    # large never-converted backlog, EVERY page load did real EPUB-open-
    # and-parse work for up to 25 highlights, on the hot read path, until
    # the backlog finally cleared — and there is no need to convert them
    # all when a page opens: that only overloads the page).
    book_meta = _build_book_meta(hls)
    device_names = _build_device_names(
        [h.device_id for h in hls] + [o.device_id for o in orphans], db
    )
    return (
        [_serialize(h, book_meta, device_names) for h in hls]
        + [_serialize_orphan(o, device_names) for o in orphans]
    )


def _link_della_nota(h, meta: dict, base: Optional[str]) -> Optional[str]:
    """
    L'indirizzo condivisibile di una nota, o `None` se non si puo' comporre.

    Non si puo' quando manca il nome durevole (una riga che la migrazione non
    ha ancora toccato) o l'uuid del libro (una biblioteca fabbricata a mano).
    In quei casi si dice niente: un link che non apre e' peggio di nessun
    link, perche' finisce scritto in un appunto.
    """
    if not h.id_durevole or not meta.get("uuid"):
        return None
    quanti = link_condivisibile.caratteri_che_bastano(
        meta["uuid"], meta.get("uuid_della_biblioteca") or [])
    percorso = link_condivisibile.percorso_della_nota(
        h.library, meta.get("title"), meta["uuid"], h.id_durevole, quanti)
    return f"{base}{percorso}" if base else percorso


def righe_esportate(db: Session, utente: models.User, base: Optional[str] = None) -> list:
    """
    Le righe dell'esportazione, pronte.

    **Sta in una funzione e non solo dentro la rotta** perche' le legge anche
    la pagina degli Appunti (`api/appunti.py`): per dire in che stato e' il
    vault bisogna sapere quali note ci dovrebbero essere, e quella domanda ha
    una risposta sola. Due giri che la calcolassero per conto loro
    divergerebbero al primo campo aggiunto.

    `base` e' l'indirizzo di questa installazione, quando chi chiama lo
    conosce: serve a scrivere nel campo `link` un indirizzo intero invece del
    solo percorso.

    Dentro ci sono le evidenziazioni attive arricchite col titolo e l'autore
    veri del libro, che `Highlight` non conserva (ha solo `calibre_book_id` e
    la biblioteca). Ci sono **anche le orfane**: il plugin raggruppa per
    biblioteca piu' titolo e non guarda mai l'id di Calibre, quindi la
    biblioteca finta `device:<id>` tiene i file non accoppiati di ogni
    dispositivo nella loro nota anche se due titoli indovinati coincidono.
    """
    hls = (
        db.query(models.Highlight)
        .filter(models.Highlight.user_id == utente.id, models.Highlight.deleted_at.is_(None))
        .order_by(models.Highlight.calibre_book_id, models.Highlight.page)
        .all()
    )
    orphans = (
        db.query(models.OrphanHighlight)
        .filter(models.OrphanHighlight.user_id == utente.id, models.OrphanHighlight.deleted_at.is_(None))
        .order_by(models.OrphanHighlight.local_path, models.OrphanHighlight.page)
        .all()
    )
    book_meta = _build_book_meta(hls)
    device_names = _build_device_names(
        [h.device_id for h in hls] + [o.device_id for o in orphans], db
    )

    results = []
    for h in hls:
        meta = book_meta.get((h.library, h.calibre_book_id), {})
        results.append({
            "id": h.id,
            "book_title": meta.get("title") or f"Libro #{h.calibre_book_id}",
            "book_author": meta.get("author") or "Unknown Author",
            "library": h.library,
            # **L'id del libro dentro quella biblioteca.** Mancava fino al
            # 06/11/2026, e la pagina Appunti ne aveva bisogno per una cosa
            # concreta: le decisioni si scrivono su (biblioteca, id), quindi
            # senza questo campo nessun libro risultava accoppiato e i
            # pulsanti «non mandarlo» e «rifallo da zero» non comparivano
            # per nessuno. Il titolo non basta: due biblioteche possono
            # avere lo stesso titolo, e un titolo cambia.
            "calibre_book_id": h.calibre_book_id,
            "chapter": h.chapter,
            "page": h.page,
            "text": h.text,
            "note": h.comment or "",
            "color": h.color,
            "created_at": quando(h.created_at),
            # 'web' (Kolibre reader/manual), 'device' (KOReader sync), or
            # 'calibre' (Calibre Desktop's built-in viewer) — see
            # models.Highlight.source's own docstring. device_name is only
            # ever set for source='device', and only if that device is
            # still registered (None if it was deleted since).
            "source": h.source,
            "device_name": device_names.get(h.device_id),
            # **Il nome che non cambia**: e' quello che il plugin scrive nel
            # marcatore dentro il file, ed e' il solo modo perche' un blocco
            # resti riconoscibile quando la riga del database viene rifatta
            # (un'orfana accoppiata, due note fuse).
            "id_durevole": h.id_durevole,
            # L'indirizzo che riapre quel punto nel lettore. Paolo ha scelto
            # che vada su **ogni singola evidenziazione**, non in testa al
            # file.
            "link": _link_della_nota(h, meta, base),
        })
    for o in orphans:
        results.append({
            "id": f"orphan-{o.id}",
            "book_title": _guess_title_from_path(o.local_path) + " (not paired)",
            "book_author": device_names.get(o.device_id) or "Unknown device",
            "library": f"device:{o.device_id}",
            # Un file non ancora accoppiato non ha un libro: e' nullo, e la
            # pagina su quelli non offre le azioni che si scrivono sul libro.
            "calibre_book_id": None,
            "chapter": o.chapter,
            "page": o.page,
            "text": o.text,
            "note": o.comment or "",
            "color": o.color,
            "created_at": quando(o.created_at),
            "source": "device",
            "device_name": device_names.get(o.device_id),
            "id_durevole": o.id_durevole,
            # Un'orfana non ha un libro, e il link gerarchico contiene il
            # libro: niente link finche' non viene accoppiata. Si dice,
            # invece di comporre un indirizzo che non apre niente.
            "link": None,
        })
    # `chapter_path`: i livelli del capitolo, separati, pronti da scrivere
    # come titoli annidati. Fino al 05/11/2026 questa risposta mandava solo
    # la stringa `chapter` e il plugin Obsidian si separava i livelli da se',
    # in un centinaio di righe di JavaScript che nessuna prova guardava (nel
    # plugin non si possono eseguire prove). Il lavoro sta qui, si fa una
    # volta, e ha le sue trentasette — vedi
    # `services/capitoli_delle_note.py` e `prove/capitoli_delle_note.py`.
    return capitoli_delle_note.con_i_percorsi(results)


@router.get("/export", responses={200: {"model": list[AnnotazioneEsportata]}})
def export_annotations(
    richiesta: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Tutto quello che serve al plugin Obsidian, in una chiamata. Il corpo
    sta in `righe_esportate`, che legge anche la pagina degli Appunti."""
    return righe_esportate(db, current_user, base=_indirizzo_base(richiesta))


@router.post("", responses={200: {"model": Evidenziazione}})
def create_annotation(
    payload: schemas.HighlightCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Manual annotation creation. Until the web reader (Fase 7) or KOReader sync
    (Fase 5) exist, this is the only way to actually put something in the
    Annotations page for real end-to-end testing.
    """
    # La biblioteca di ripiego e' la prima che QUESTA persona vede, non una
    # cartella chiamata "default": quel nome non corrisponde a niente sul
    # disco, ed era un residuo di quando la biblioteca era una sola. Una nota
    # salvata su una biblioteca inesistente e' una nota che non si apre piu'.
    biblioteca = payload.library or resolve_default_library_folder(db, current_user)
    if not biblioteca:
        raise HTTPException(status_code=404, detail=NESSUNA_BIBLIOTECA_TUA)
    highlight = models.Highlight(
        user_id=current_user.id,
        library=biblioteca,
        calibre_book_id=payload.calibre_book_id,
        text=payload.text,
        comment=payload.comment,
        chapter=payload.chapter,
        page=payload.page,
        color=payload.color or "yellow",
        cfi_start=payload.cfi_position,
        source="web",
    )
    db.add(highlight)
    db.commit()
    return _serialize(highlight)


@router.put("/orphans/{id}", responses={200: {"model": EvidenziazioneOrfana}})
def update_orphan_annotation(
    id: int,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Mirror of update_annotation for OrphanHighlight rows — same fields
    (notes/color), so the frontend's edit UI works identically before and
    after a highlight gets paired to a real book."""
    o = _get_owned_orphan(db, id, current_user)
    if "notes" in payload:
        o.comment = payload["notes"]
    if "color" in payload:
        o.color = payload["color"]
    db.commit()
    return _serialize_orphan(o, _build_device_names([o.device_id], db))


@router.delete("/orphans/{id}", responses={200: {"model": Esito}})
def delete_orphan_annotation(
    id: int,
    permanent: bool = False,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    o = _get_owned_orphan(db, id, current_user)
    if permanent:
        db.delete(o)
    else:
        o.deleted_at = datetime.utcnow()
    db.commit()
    return {"status": "ok"}


@router.post("/orphans/{id}/restore", responses={200: {"model": EvidenziazioneOrfana}})
def restore_orphan_annotation(
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    o = _get_owned_orphan(db, id, current_user)
    o.deleted_at = None
    db.commit()
    return _serialize_orphan(o, _build_device_names([o.device_id], db))


@router.post("/retry-failed-positions", responses={200: {"model": PosizioniDaRitentare}})
def retry_failed_positions(
    library: str = None,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    "Ritenta conversioni CFI fallite" — position_status='failed' is
    deliberately never retried automatically (see services/highlight_
    position.py's backfill_pending_device_positions, run periodically in
    the background — a missing/corrupt EPUB would otherwise redo the same
    failing work forever). This is the explicit, one-off escape hatch:
    resets position_status back to NULL so those rows re-enter the normal
    background backfill on its next tick — e.g. once the underlying EPUB
    has since been fixed/replaced/re-converted.
    """
    query = db.query(models.Highlight).filter(
        models.Highlight.user_id == current_user.id,
        models.Highlight.position_status == "failed",
    )
    if library:
        query = query.filter(models.Highlight.library == library)
    count = query.update({"position_status": None}, synchronize_session=False)
    db.commit()
    return {"status": "ok", "reset": count}


@router.get("/widowed", responses={200: {"model": GruppiVedovi}})
def list_widowed_annotations(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Note accoppiate a un libro che nella libreria non c'e' piu' — vedi
    services/widowed_highlights.py per come si finisce in quello stato e
    perche' non e' un errore ma una conseguenza voluta a meta'.
    """
    return {"groups": widowed_highlights.find_widowed_groups(db, user_id=current_user.id)}


@router.get("/widowed/suggestions", responses={200: {"model": ProposteVedove}})
def suggest_widowed_annotations(
    library: str,
    calibre_book_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Quali libri presenti in biblioteca contengono il testo di queste note."""
    return widowed_highlights.suggest_books(db, library, calibre_book_id, user_id=current_user.id)


@router.post("/widowed/repair", responses={200: {"model": VedoveRiparate}})
def repair_widowed_annotations(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Riporta le note vedove sul libro indicato."""
    library = payload.get("library")
    book_id = payload.get("calibre_book_id")
    target_library = payload.get("target_library") or library
    target_book_id = payload.get("target_book_id")
    if not library or book_id is None or target_book_id is None:
        raise HTTPException(status_code=400, detail="library, calibre_book_id and target_book_id are required")
    spostate = widowed_highlights.repair(db, library, int(book_id), target_library, int(target_book_id), user_id=current_user.id)
    db.commit()
    log_message(
        "info", "annotations",
        f"Widowed notes reconnected: {spostate} from {library}/{book_id} to {target_library}/{target_book_id}",
    )
    return {"status": "ok", "moved": spostate}


@router.get("/{id}", responses={200: {"model": Evidenziazione}})
def get_annotation(
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Una sola annotazione, con il libro a cui appartiene.

    Serve ai link che riaprono il lettore su un passaggio: l'indirizzo porta
    solo l'id della nota, e tutto il resto — quale libro, quale biblioteca,
    quale formato, dove sta e che testo e' — lo si chiede qui.

    Portare l'id invece della posizione non e' un risparmio di caratteri: e'
    quello che fa invecchiare bene il link. Se l'ancora di quella nota viene
    riparata dopo che il link e' stato scritto, il link punta da solo al punto
    corretto, perche' non porta una coordinata ma un'identita'.

    Esiste anche per un secondo motivo: il lettore, per mostrare le
    evidenziazioni di UN libro, chiamava `GET /annotations` senza parametri e
    si scaricava tutte quelle dell'utente, di tutte le biblioteche, cestino
    compreso, per poi buttarle via lato client.
    """
    h = (
        db.query(models.Highlight)
        .filter(models.Highlight.id == id, models.Highlight.user_id == current_user.id)
        .first()
    )
    if not h:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return _serialize(h, _build_book_meta([h]), _build_device_names([h.device_id], db))


@router.put("/{id}", responses={200: {"model": Evidenziazione}})
def update_annotation(
    id: int,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    h = db.query(models.Highlight).filter(
        models.Highlight.id == id, models.Highlight.user_id == current_user.id
    ).first()
    if not h:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if "notes" in payload:
        h.comment = payload["notes"]
    if "color" in payload:
        h.color = payload["color"]
    # L'ancora ritrovata dal lettore, da non ricercare mai piu'.
    #
    # Quando il lettore apre una nota il cui punto non serve piu', la
    # ritrova cercandone il testo dentro il libro — e finora rifaceva
    # quella ricerca A OGNI APERTURA, perche' il risultato non veniva
    # salvato da nessuna parte. Lo si notava come lentezza: aprendo una
    # nota nel lettore l'ePub veniva caricato MOLTO piu' lentamente del
    # normale, come se un ancoraggio una volta effettuato non venisse
    # ricordato.
    #
    # Ed era proprio cosi'. Ora il lettore rimanda indietro il
    # CFI che ha trovato: si cerca una volta, poi si apre e basta.
    #
    # Chi puo' sovrascrivere chi.
    #
    # La regola era «si scrive SOLO su una nota che un'ancora non ce l'ha»,
    # per impedire che una posizione trovata per somiglianza coprisse quella
    # esatta prodotta dalla conversione. Il principio e' giusto e resta; la
    # regola pero' proteggeva allo stesso modo le ancore ESATTE e quelle
    # ROTTE, e un'ancora rotta diventava percio' incorreggibile per sempre.
    #
    # Il caso reale (04/10/2026): una nota di 659 caratteri con un'ancora che
    # ne copriva 300. Era stata prodotta da una ricerca che non sapeva
    # attraversare i soft hyphen, e si era fermata esattamente sul trattino
    # invisibile dentro «co-struite», a meta' del brano. Risolveva, disegnava
    # un rettangolo, e quindi nessuno la toccava piu'.
    #
    # Ora: una posizione ritrovata dal testo puo' sostituire SOLO un'altra
    # posizione ritrovata dal testo (o una nota che non ne ha). Davanti a
    # 'exact' e 'repaired' — che vengono dalla conversione dell'xpointer, cioe'
    # da dove la nota e' stata presa davvero — non si tocca niente.
    #
    # Il lettore manda un'ancora solo quando il testo e' stato trovato UNA
    # VOLTA SOLA nel libro (vedi ritrovaDalTesto), quindi quello che arriva qui
    # non e' un tentativo fra tanti: e' un riscontro univoco.
    # Il riposizionamento a mano vince su tutto, e su tutto vuol dire anche
    # sulla conversione dell'xpointer.
    #
    # E' il caso di «Estendi»: la persona ha appena selezionato con il dito o
    # col mouse dove arriva davvero quel passaggio. Non esiste fonte piu'
    # attendibile di cosi' — nessun algoritmo che indovina da una struttura o
    # da una somiglianza di testo puo' saperne di piu'. Quindi non passa dalla
    # regola qui sotto, che serve a impedire che una SUPPOSIZIONE copra una
    # conversione riuscita.
    #
    # Lo stato diventa 'manuale', un valore nuovo: i consumatori cercano
    # 'failed', 'libro_assente' o NULL per sapere cosa ha bisogno di
    # attenzione, e una posizione messa a mano non ne ha. Per la stessa
    # ragione il ripasso periodico non la riesaminera' mai.
    if payload.get("cfi_start") and payload.get("riposizionamento_manuale"):
        h.cfi_start = payload["cfi_start"]
        h.cfi_end = payload.get("cfi_end") or payload["cfi_start"]
        h.position_status = "manuale"
        # Estendere o restringere cambia anche IL TESTO della nota: senza
        # questo resterebbe quello di prima, e il ripiego «ritrova dal testo»
        # cercherebbe per sempre un brano diverso da quello evidenziato.
        if payload.get("text"):
            h.text = payload["text"]
        db.commit()
        return _serialize(h, device_names=_build_device_names([h.device_id], db))

    ANCORE_DA_CONVERSIONE = ("exact", "repaired")
    if payload.get("cfi_start") and h.position_status not in ANCORE_DA_CONVERSIONE:
        h.cfi_start = payload["cfi_start"]
        h.cfi_end = payload.get("cfi_end") or payload["cfi_start"]
        h.position_status = "ritrovata_dal_testo"
    db.commit()
    return _serialize(h, device_names=_build_device_names([h.device_id], db))


@router.delete("/{id}", responses={200: {"model": Esito}})
def delete_annotation(
    id: int,
    permanent: bool = False,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    h = db.query(models.Highlight).filter(
        models.Highlight.id == id, models.Highlight.user_id == current_user.id
    ).first()
    if not h:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if permanent:
        db.delete(h)
    else:
        h.deleted_at = datetime.utcnow()
    db.commit()
    return {"status": "ok"}


@router.post("/{id}/restore", responses={200: {"model": Evidenziazione}})
def restore_annotation(
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    h = db.query(models.Highlight).filter(
        models.Highlight.id == id, models.Highlight.user_id == current_user.id
    ).first()
    if not h:
        raise HTTPException(status_code=404, detail="Annotation not found")
    h.deleted_at = None
    db.commit()
    return _serialize(h, device_names=_build_device_names([h.device_id], db))
