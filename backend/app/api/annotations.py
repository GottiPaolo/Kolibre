import os
import re
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import config, models, schemas, database, auth
from ..calibre.library import CalibreLibrary
from ..logging_utils import log_message
from ..services import widowed_highlights
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
        "created_at": h.created_at.strftime("%Y-%m-%d %H:%M:%S") if h.created_at else None,
        "updated_at": h.updated_at.strftime("%Y-%m-%d %H:%M:%S") if h.updated_at else None,
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
        "created_at": o.created_at.strftime("%Y-%m-%d %H:%M:%S") if o.created_at else None,
        "updated_at": o.updated_at.strftime("%Y-%m-%d %H:%M:%S") if o.updated_at else None,
        "book_title": _guess_title_from_path(o.local_path),
        "book_author": None,
        "is_orphan": True,
        "orphan_key": f"{o.device_id}:{o.local_path}",
    }


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
                    "author": b["author"] or "Autore Sconosciuto",
                    # Serve al frontend per aprire il lettore GIUSTO. La
                    # pagina Annotazioni chiedeva sempre l'EPUB, con un
                    # commento che diceva "nessun percorso di sync da
                    # dispositivo produce highlight su un PDF": non e' vero,
                    # devices.py ha un ramo di deduplica apposta per i PDF
                    # (pos0 e' EPUB-only, quindi ricade su pagina+testo) — e
                    # su un libro di solo PDF il lettore EPUB si apriva su
                    # "Impossibile caricare il libro nel web reader".
                    "formats": b.get("formats") or [],
                }
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
        raise HTTPException(status_code=404, detail="Annotazione non trovata")
    return o


@router.get("")
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


@router.get("/export")
def export_annotations(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Everything the Obsidian plugin (plugins/obsidian/kolibre-highlights/) needs
    to build/update its per-book notes, in one call: active (non-trashed)
    highlights enriched with the book's real title/author, which Highlight
    itself doesn't store (only calibre_book_id + library) — see
    _build_book_meta (shared with the plain list endpoint above). Includes
    OrphanHighlight rows too (also active-only) — the Obsidian plugin groups
    purely by `library + book_title`, never touches calibre_book_id, so an
    orphan's synthetic `device:<id>` library keeps every device's unmatched
    books in their own note even if two guessed titles happen to collide.
    """
    hls = (
        db.query(models.Highlight)
        .filter(models.Highlight.user_id == current_user.id, models.Highlight.deleted_at.is_(None))
        .order_by(models.Highlight.calibre_book_id, models.Highlight.page)
        .all()
    )
    orphans = (
        db.query(models.OrphanHighlight)
        .filter(models.OrphanHighlight.user_id == current_user.id, models.OrphanHighlight.deleted_at.is_(None))
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
            "book_author": meta.get("author") or "Autore Sconosciuto",
            "library": h.library,
            "chapter": h.chapter,
            "page": h.page,
            "text": h.text,
            "note": h.comment or "",
            "color": h.color,
            "created_at": h.created_at.isoformat() if h.created_at else None,
            # 'web' (Kolibre reader/manual), 'device' (KOReader sync), or
            # 'calibre' (Calibre Desktop's built-in viewer) — see
            # models.Highlight.source's own docstring. device_name is only
            # ever set for source='device', and only if that device is
            # still registered (None if it was deleted since).
            "source": h.source,
            "device_name": device_names.get(h.device_id),
        })
    for o in orphans:
        results.append({
            "id": f"orphan-{o.id}",
            "book_title": _guess_title_from_path(o.local_path) + " (non accoppiato)",
            "book_author": device_names.get(o.device_id) or "Dispositivo sconosciuto",
            "library": f"device:{o.device_id}",
            "chapter": o.chapter,
            "page": o.page,
            "text": o.text,
            "note": o.comment or "",
            "color": o.color,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "source": "device",
            "device_name": device_names.get(o.device_id),
        })
    return results


@router.post("")
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


@router.put("/orphans/{id}")
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


@router.delete("/orphans/{id}")
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


@router.post("/orphans/{id}/restore")
def restore_orphan_annotation(
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    o = _get_owned_orphan(db, id, current_user)
    o.deleted_at = None
    db.commit()
    return _serialize_orphan(o, _build_device_names([o.device_id], db))


@router.post("/retry-failed-positions")
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


@router.get("/widowed")
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


@router.get("/widowed/suggestions")
def suggest_widowed_annotations(
    library: str,
    calibre_book_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Quali libri presenti in biblioteca contengono il testo di queste note."""
    return widowed_highlights.suggest_books(db, library, calibre_book_id, user_id=current_user.id)


@router.post("/widowed/repair")
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
        raise HTTPException(status_code=400, detail="library, calibre_book_id e target_book_id sono obbligatori")
    spostate = widowed_highlights.repair(db, library, int(book_id), target_library, int(target_book_id), user_id=current_user.id)
    db.commit()
    log_message(
        "info", "annotations",
        f"Note vedove ricollegate: {spostate} da {library}/{book_id} a {target_library}/{target_book_id}",
    )
    return {"status": "ok", "moved": spostate}


@router.put("/{id}")
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
        raise HTTPException(status_code=404, detail="Annotazione non trovata")
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
    # Si scrive SOLO su una nota che un'ancora non ce l'ha: una posizione
    # ritrovata per somiglianza non deve mai sovrascrivere quella esatta
    # prodotta dalla conversione.
    if payload.get("cfi_start") and not h.cfi_start:
        h.cfi_start = payload["cfi_start"]
        h.cfi_end = payload.get("cfi_end") or payload["cfi_start"]
        h.position_status = "ritrovata_dal_testo"
    db.commit()
    return _serialize(h, device_names=_build_device_names([h.device_id], db))


@router.delete("/{id}")
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
        raise HTTPException(status_code=404, detail="Annotazione non trovata")
    if permanent:
        db.delete(h)
    else:
        h.deleted_at = datetime.utcnow()
    db.commit()
    return {"status": "ok"}


@router.post("/{id}/restore")
def restore_annotation(
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    h = db.query(models.Highlight).filter(
        models.Highlight.id == id, models.Highlight.user_id == current_user.id
    ).first()
    if not h:
        raise HTTPException(status_code=404, detail="Annotazione non trovata")
    h.deleted_at = None
    db.commit()
    return _serialize(h, device_names=_build_device_names([h.device_id], db))
