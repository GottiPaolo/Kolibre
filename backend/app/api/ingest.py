import base64
import json
import os
import shutil
import threading
from datetime import datetime
from typing import List, Union

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import auth, config, models, schemas, database
from ..logging_utils import log_message
from ..schemas_risposte import (
    ArretratiCaricati, DoppioniInArrivo, Esito, ImportazioneAvviata,
    ImportazioneDaFermare, LibroImportato, LibroInArretrato, ModoPaginazione,
    PaginaDiArretrati, SchedeDaIsbn, StatoImportazione,
)
from ..services import duplicates, ingest_folders, ingest_pages, metadata_scraper, page_counter, app_settings, book_hash_service, author_ingest_hook, author_stats_service, stats_service, ingest_import_job, qualita_job
from ..services.library_scanner import EBOOK_EXTENSIONS, formato_ammesso
from ..services.watcher import ACTIVE_INGEST_STATUSES, stage_ingest_file
from ..calibre import calibre_naming
from ..calibre.library import CalibreLibrary
from ..calibre.connection import PAGE_COUNT_COLUMN_LABEL, page_count_fields
from ..calibre.functions import string_to_authors
from ..calibre.write_queue import CalibreWriteQueue
from ..deps import get_write_queue
from .libraries import resolve_folder_name, resolve_default_library_folder

router = APIRouter(prefix="/api/kolibre/ingest", tags=["ingest"])

# Endpoint deliberatamente SENZA autenticazione: sono URL che il
# browser (o il plugin KOReader) carica senza poter allegare un header
# Authorization — <img src>, @font-face, self-update del plugin. Tutto
# il resto di questo modulo passa da `router`, che main.py include con
# la dipendenza di autenticazione. Se aggiungi qui un endpoint, stai
# scegliendo di renderlo pubblico: fallo solo se e' in sola lettura.
public_router = APIRouter(prefix="/api/kolibre/ingest", tags=["ingest"])

# Per-file size cap for web uploads to the ingest folder.
MAX_UPLOAD_SIZE_BYTES = 300 * 1024 * 1024  # 300 MB

# One read buffer per chunk while streaming an upload to disk.
_UPLOAD_CHUNK_BYTES = 1024 * 1024


# ── Chi vede cosa (21/11/2026: la cartella di ingest e' per utente) ──────
#
# L'amministratore vede TUTTO, comprese le righe senza proprietario (NULL:
# quelle di prima della colonna user_id, e i file messi a mano nella radice
# di ingest) — e' il comportamento che la pagina aveva ieri per chiunque.
# Un utente normale vede SOLO le sue: non quelle degli altri e nemmeno le
# NULL, perche' «di nessuno» non vuol dire «di tutti» — una riga non
# attribuita puo' essere il file di un altro, e mostrarla sarebbe la stessa
# area condivisa che questa modifica esiste per chiudere.
def _visible_to(query, current_user: models.User):
    if current_user.is_admin:
        return query
    return query.filter(models.IngestedBook.user_id == current_user.id)


def _owner_usernames(db: Session, items) -> dict:
    """{user_id: username} per le righe passate: il nome si mostra solo
    all'amministratore sulla scheda, ma si risponde sempre — e' un dato
    della riga, non un segreto (per un utente normale e' il suo)."""
    ids = {i.user_id for i in items if i.user_id is not None}
    if not ids:
        return {}
    return dict(db.query(models.User.id, models.User.username).filter(models.User.id.in_(ids)).all())


def _serialize_ingest_item(item: models.IngestedBook, usernames: dict = None) -> dict:
    """Wire format of a staged ingest item, shared by the list and upload endpoints."""
    return {
        "id": item.id,
        # Il proprietario (21/11/2026): NULL = «di prima / radice di
        # ingest», mai dedotto. Vedi _visible_to per chi vede cosa.
        "owner_user_id": item.user_id,
        "owner_username": (usernames or {}).get(item.user_id),
        "title": item.title,
        "author": item.author or "Unknown Author",
        # Una voce senza file (record_only) non ha formati: la scheda la
        # racconta come «solo scheda», non come un file di formato vuoto.
        "formats": [] if item.record_only else [item.file_format],
        "size": item.file_size_bytes or 0,
        "path": item.file_path,
        "date_added": item.detected_at.strftime('%Y-%m-%d'),
        "cover_url": f"/api/kolibre/ingest/{item.id}/cover" if item.cover_path else None,
        "description": item.description or "",
        "tags": item.tags.split(",") if item.tags else [],
        "series": item.series,
        "series_index": item.series_index,
        "language": item.language,
        "isbn": item.isbn,
        # La qualita' del file, misurata in sottofondo appena il file e'
        # arrivato (services/qualita_job.py). `None` finche' non c'e':
        # per un PDF non ci sara' mai, per un EPUB appena arrivato ci mette
        # un attimo. Il JSON intero perche' il pannello dei dettagli legge
        # dimensioni e difetti da li', senza elenchi scritti nel frontend.
        "qualita_punteggio": item.qualita_punteggio,
        "qualita": json.loads(item.qualita_json) if item.qualita_json else None,
        # Le pagine, contate in sottofondo appena il file e' arrivato
        # (services/ingest_pages.py; 22/11/2026). `None` finche' non ci
        # sono, e per sempre per un formato che non si sa leggere.
        "pages": item.pages,
        # La voce senza file (23/11/2026): nata da un ISBN o dal plugin
        # Calibre per un libro solo-record. All'importazione diventa una
        # scheda Calibre senza formati.
        "record_only": item.record_only,
        # Il formato e' fra quelli che Kolibre accetta? (scelta di Paolo,
        # 23/11/2026): un file fuori lista COMPARE in arretrato — cosi' lo
        # si vede e lo si scarta dal sito — ma non si puo' importare. Una
        # scheda senza file e' sempre importabile: non ha formato.
        "supported": True if item.record_only else formato_ammesso(item.file_format),
    }


# La scansione della cartella si fa UNA ALLA VOLTA.
#
# Senza, due richieste che arrivano insieme — e arrivano insieme: aprendo la
# pagina Importa partono sia /ingest sia /ingest/pagination — scansionano
# entrambe, vedono entrambe lo stesso file come nuovo e lo mettono in attesa
# DUE volte. Poi la prima importazione sposta il file e la seconda riga
# fallisce con "file non trovato".
#
# Non e' teoria: importando 800 file ne risultavano 874 in attesa, e 74
# fallivano esattamente cosi'. La corsa c'era anche prima (il controllo era
# per file, senza lock), ma leggere in blocco cio' che e' gia' noto — che e'
# cio' che rende veloce la scansione — allarga la finestra a tutta la
# scansione, quindi il riparo va messo qui.
_scan_lock = threading.Lock()


def _scan_ingest_folder(db: Session) -> None:
    """
    Poll-on-request fallback: stages any file already sitting in the ingest
    folder that the real-time watcher (services/watcher.py, running since app
    startup) hasn't picked up yet — e.g. files copied in before the server was
    first started. New files dropped in while the server is running are staged
    immediately by the watcher; this just catches anything it could have missed.
    """
    if not os.path.exists(config.INGEST_DIR):
        return
    # Un'interrogazione sola per sapere cosa e' gia' noto, invece di una per
    # file. stage_ingest_file comincia comunque chiedendo al database se
    # quel percorso esiste gia': su una cartella con duemila file erano
    # duemila interrogazioni ad OGNI caricamento della pagina, e su
    # ventimila sarebbero ventimila. Qui si chiede una volta e si chiamano
    # solo i file davvero nuovi — che di solito sono zero.
    with _scan_lock:
        # Solo i percorsi con una riga ATTIVA (pending/importing) sono "gia'
        # noti": una riga confirmed e' un'importazione passata, e un file che
        # ricompare allo stesso percorso e' un file nuovo da mettere in
        # attesa (22/11/2026 — vedi ACTIVE_INGEST_STATUSES in watcher.py).
        noti = {
            r[0]
            for r in db.query(models.IngestedBook.file_path)
            .filter(models.IngestedBook.status.in_(ACTIVE_INGEST_STATUSES))
            .all()
        }
        # os.walk e non os.listdir (21/11/2026): dentro ingest ci sono le
        # sottocartelle per utente, e un file li' dentro e' un file da
        # mettere in attesa — col suo proprietario, letto dal percorso da
        # stage_ingest_file. Le cartelle nascoste si saltano (le cartelle
        # di servizio di Syncthing non contengono libri).
        for dirpath, dirnames, filenames in os.walk(config.INGEST_DIR):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))
            for f in sorted(filenames):
                percorso = os.path.abspath(os.path.join(dirpath, f))
                if percorso not in noti:
                    stage_ingest_file(db, percorso)
        # Il ripasso delle pagine (22/11/2026): le righe rimaste senza
        # conteggio — nate prima della colonna, o il cui thread e' morto
        # con un riavvio del server — si contano al primo sguardo. Il
        # servizio scarta da se' i doppioni e i gia' falliti.
        da_contare = (
            db.query(models.IngestedBook.id)
            .filter(
                models.IngestedBook.status == "pending",
                models.IngestedBook.pages.is_(None),
                models.IngestedBook.file_format.in_(ingest_pages.COUNTABLE_FORMATS),
            )
            .all()
        )
        for (item_id,) in da_contare:
            ingest_pages.count_in_background(item_id)


@router.get(
    "",
    responses={200: {"model": Union[list[LibroInArretrato], PaginaDiArretrati]}},
)
def list_ingest_books(
    db: Session = Depends(database.get_db),
    limit: int = None,
    offset: int = 0,
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Senza `limit` restituisce tutto, come sempre. Con `limit` una pagina —
    {items, total, offset, limit} — nella stessa forma di GET /books.

    Serve al caso vero: una cartella con migliaia di file da rivedere. La
    pagina Ingest disegna una scheda per ogni libro, con copertina e
    metadati, e a qualche migliaio diventa una pagina che non si apre.

    Dal 21/11/2026 l'elenco e' per utente: l'amministratore vede tutto
    (comprese le righe senza proprietario), un utente le sue — vedi
    _visible_to.
    """
    _scan_ingest_folder(db)
    q = _visible_to(
        db.query(models.IngestedBook)
        .filter(models.IngestedBook.status == "pending"),
        current_user,
    ).order_by(models.IngestedBook.id)
    if limit is None:
        items = q.all()
        nomi = _owner_usernames(db, items)
        return [_serialize_ingest_item(item, nomi) for item in items]
    totale = q.count()
    items = q.limit(int(limit)).offset(max(0, int(offset))).all()
    nomi = _owner_usernames(db, items)
    return {
        "items": [_serialize_ingest_item(item, nomi) for item in items],
        "total": totale,
        "offset": max(0, offset),
        "limit": limit,
    }


@router.post(
    "/import-job",
    responses={200: {"model": ImportazioneAvviata}},
)
async def start_ingest_import_job(
    payload: dict,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Avvia l'importazione in blocco SUL SERVER. Il browser puo' andarsene.

    Corpo: {ids?: [int], library?: str, per_item?: {"<id>": "<folder>"}}.
    `ids` assente significa "tutte le voci in attesa" — ed e' il motivo per
    cui l'elenco lo costruisce il server: con la pagina impaginata il
    browser conosce solo le voci che sta mostrando.

    La destinazione resta una decisione del client, che e' dove l'utente la
    esprime (la libreria scelta in alto, piu' eventuali eccezioni per
    singolo libro): qui si prende la sua, con la libreria generale come
    ripiego.

    `async def` e non `def`: il lavoro e' un task asyncio, e un endpoint
    sincrono FastAPI lo esegue in un thread a parte, dove un event loop non
    c'e' — asyncio.create_task fallirebbe con "no running event loop".
    """
    generale = payload.get("library")
    per_item = {str(k): v for k, v in (payload.get("per_item") or {}).items()}
    ids = payload.get("ids")
    if ids is None:
        # "Tutte le voci in attesa" significa tutte quelle che QUESTO utente
        # vede (21/11/2026): per l'amministratore e' tutto come ieri, per un
        # utente sono le sue — mai quelle degli altri.
        # I formati fuori lista si saltano QUI: «tutte le voci in attesa»
        # significa tutte le importabili — una voce che esiste solo per
        # essere scartata non deve far fallire il giro (23/11/2026).
        ids = [
            r[0] for r in _visible_to(
                db.query(models.IngestedBook.id, models.IngestedBook.file_format,
                         models.IngestedBook.record_only)
                .filter(models.IngestedBook.status == "pending"),
                current_user,
            ).order_by(models.IngestedBook.id).all()
            if r[2] or formato_ammesso(r[1])
        ]
    else:
        # Ids espliciti: un utente normale puo' nominare solo righe sue. Un
        # 403 e non un filtro silenzioso — un giro che "parte" saltando meta'
        # delle voci chieste sembrerebbe riuscito mentre non lo e'.
        ids = [int(i) for i in ids]
        if not current_user.is_admin and ids:
            visibili = {
                r[0] for r in _visible_to(
                    db.query(models.IngestedBook.id)
                    .filter(models.IngestedBook.id.in_(ids)),
                    current_user,
                ).all()
            }
            if set(ids) - visibili:
                raise HTTPException(status_code=403, detail="Some of these staged items are not yours")
    voci = [(int(i), per_item.get(str(i)) or generale) for i in ids]
    if not voci:
        raise HTTPException(status_code=400, detail="No books to import")
    if not ingest_import_job.start(voci, request.app.state.write_queue):
        raise HTTPException(status_code=409, detail="A bulk import is already running")
    log_message("info", "ingest", f"Bulk import started: {len(voci)} books")
    return {"status": "started", "total": len(voci)}


@router.get(
    "/import-job",
    responses={200: {"model": StatoImportazione}},
)
def get_ingest_import_job():
    """Stato dell'importazione in blocco. Interrogabile da qualunque pagina."""
    return ingest_import_job.status()


@router.post(
    "/import-job/stop",
    responses={200: {"model": ImportazioneDaFermare}},
)
def stop_ingest_import_job():
    """Ferma dopo il libro in corso. Quelli gia' importati restano importati."""
    return {"stopping": ingest_import_job.stop()}


@router.get(
    "/pagination",
    responses={200: {"model": ModoPaginazione}},
)
def get_ingest_pagination(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """Se la pagina Ingest va impaginata, e con che pagina. Conta e basta.

    Conta le righe che QUESTO utente vede (21/11/2026): il totale deve
    corrispondere all'elenco, o la pagina crederebbe di avere pagine vuote.
    """
    _scan_ingest_folder(db)
    totale = _visible_to(
        db.query(models.IngestedBook)
        .filter(models.IngestedBook.status == "pending"),
        current_user,
    ).count()
    conf = app_settings.get_ingest_pagination(db)
    return {
        "total": totale,
        "paginated": app_settings.ingest_pagination_applies(db, totale),
        "page_size": conf["page_size"],
        "mode": conf["mode"],
        "threshold": conf["threshold"],
    }


@router.get(
    "/duplicati",
    responses={200: {"model": DoppioniInArrivo}},
)
def ingest_duplicati(
    library: str = None,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Quali file in attesa somigliano a qualcosa che in biblioteca c'e' gia'.

    **Avvisa, non blocca.** Un doppione vero e un'edizione diversa dello
    stesso titolo si somigliano esattamente allo stesso modo, e da qui non si
    puo' distinguerli: il sistema puo' dire "questo credo di averlo gia'",
    decidere tocca a chi guarda. Vale la regola generale del progetto — mai
    dedurre un dato dell'utente.

    Stesso criterio del motore dei doppioni gia' in casa
    (`services/duplicates.py`): blocco per cognome d'autore, affinita' di
    titolo sopra 0,85, regola dei numeri, parentesi di collana ignorate. Un
    file segnalato qui e un libro che la pagina doppioni raggrupperebbe dopo
    l'importazione sono la stessa cosa, ed e' il punto: accorgersene prima.

    Confronto di METADATI, non di contenuto. L'hash c'e' e sarebbe esatto, ma
    risponde a un'altra domanda — "e' lo stesso FILE" — e due edizioni dello
    stesso libro hanno hash diversi mentre lo stesso libro ricompresso ce
    l'ha uguale: sul secondo caso l'hash aiuta, sul primo no, ed e' il primo
    quello che si vuole vedere prima di importare.
    """
    folder = resolve_folder_name(db, library) if library else resolve_default_library_folder(db)
    # Solo le righe che questo utente vede (21/11/2026): gli avvisi devono
    # combaciare con le schede che ha davanti.
    in_attesa = _visible_to(
        db.query(models.IngestedBook)
        .filter(models.IngestedBook.status == "pending"),
        current_user,
    ).all()
    if not in_attesa:
        return {"library": folder, "duplicati": {}}

    try:
        libri = CalibreLibrary(config.library_path(folder)).list_books()
    except Exception as exc:
        log_message("warning", "ingest", f"Duplicate check skipped for '{folder}': {exc}")
        return {"library": folder, "duplicati": {}}

    # Blocco per cognome d'autore, come il motore dei doppioni: senza,
    # ottocento file in attesa contro cinquemila libri sarebbero quattro
    # milioni di confronti di stringhe.
    per_autore = {}
    for libro in libri:
        per_autore.setdefault(duplicates.chiave_autore(libro.get("author") or ""), []).append(libro)

    duplicati = {}
    for item in in_attesa:
        chiave = duplicates.chiave_autore(item.author or "")
        candidati = per_autore.get(chiave, [])
        # Senza autore non si restringe a nessun blocco: si guarda tutto,
        # perche' un file appena arrivato e' proprio il caso in cui l'autore
        # puo' mancare.
        if not chiave:
            candidati = libri
        simili = [
            # Le pagine del libro gia' in casa (la colonna #pages, quando
            # c'e') viaggiano con l'avviso: accostate a quelle del file in
            # attesa — contate con le stesse impostazioni — sono il metro
            # per scegliere quale copia tenere (22/11/2026).
            {"id": libro["id"], "title": libro["title"], "author": libro.get("author"),
             "formats": libro.get("formats") or [],
             "pages": libro.get(f"#{PAGE_COUNT_COLUMN_LABEL}")}
            for libro in candidati
            if duplicates.affinita_titoli(item.title or "", libro.get("title") or "")
            >= duplicates.SOGLIA_AFFINITA
        ]
        if simili:
            duplicati[str(item.id)] = simili[:5]

    # E la qualita' del libro gia' in casa (22/11/2026, spunto di Paolo:
    # «dovrei poter aprire anche il doppione in libreria e vederne la
    # qualita'») — accostata a quella del file in attesa e' l'altro metro,
    # con le pagine, per decidere se importare il nuovo e sostituire. Una
    # interrogazione sola per tutti i segnalati; chi non e' mai stato
    # misurato (un PDF, o la coda non e' ancora passata) resta None.
    ids_simili = {s["id"] for simili in duplicati.values() for s in simili}
    if ids_simili:
        punteggi = dict(
            db.query(models.QualitaLibro.calibre_book_id, models.QualitaLibro.punteggio)
            .filter(models.QualitaLibro.library == folder,
                    models.QualitaLibro.calibre_book_id.in_(ids_simili),
                    models.QualitaLibro.stato == "ok")
            .all()
        )
        for simili in duplicati.values():
            for s in simili:
                s["qualita_punteggio"] = punteggi.get(s["id"])
    return {"library": folder, "duplicati": duplicati}


@router.post("/isbn", responses={200: {"model": SchedeDaIsbn}})
def stage_books_by_isbn(
    payload: schemas.IsbnImportRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Voci di Ingest SENZA file da uno o piu' ISBN: l'inventario digitale di
    una libreria fisica (richiesta di Paolo del 22/11; il flusso a due
    tempi e' la sua finezza del 23/11 — «non deve essere importata subito:
    si crea una voce in ingest come per gli altri libri e dopo la si
    importa»).

    Ogni ISBN valido diventa una voce in attesa (`record_only`), coi
    metadati e la copertina delle fonti (Open Library, e Google Books con
    la chiave di Paolo per i buchi — vedi fetch_metadata_by_isbn). La voce
    si rivede, si corregge con l'editor dei metadati e SOLO all'importazione
    diventa una scheda Calibre senza formati — la convenzione di Calibre:
    riga in `books`, niente righe in `data`.

    Un ISBN che nessuna fonte conosce crea COMUNQUE la voce, vuota e col
    titolo uguale all'ISBN («se uno vuole forzatamente mettere qualcosa
    puo' farlo»); uno gia' negli identificatori della biblioteca scelta
    viene messo in attesa LO STESSO, con l'avviso del libro che lo occupa
    — come un file doppione: si avvisa, e si decide davanti alla scheda.
    Solo la cifra di controllo sbagliata rifiuta (`non_valido`): l'ISBN
    diventa un identificatore, e una stringa qualsiasi lo inquinerebbe.
    """
    library_name = resolve_folder_name(db, payload.library) if payload.library else resolve_default_library_folder(db)
    if not library_name:
        raise HTTPException(status_code=404, detail="No library is configured. Create one first.")

    # Gli ISBN che la biblioteca scelta ha gia', per l'avviso.
    esistenti = {}
    for libro in CalibreLibrary(config.library_path(library_name)).list_books():
        gia = metadata_scraper.valid_isbn((libro.get("identifiers") or {}).get("isbn"))
        if gia:
            esistenti.setdefault(gia, libro)

    rows = []
    visti = set()
    da_mettere = []
    for grezzo in payload.isbns:
        grezzo = (grezzo or "").strip()
        if not grezzo:
            continue
        isbn = metadata_scraper.valid_isbn(grezzo)
        if not isbn:
            rows.append({"isbn": grezzo, "esito": "non_valido", "staged_id": None,
                         "title": None, "author": None, "cover": False,
                         "existing_book_id": None, "existing_title": None})
            continue
        if isbn in visti:
            rows.append({"isbn": isbn, "esito": "ripetuto", "staged_id": None,
                         "title": None, "author": None, "cover": False,
                         "existing_book_id": None, "existing_title": None})
            continue
        visti.add(isbn)
        occupante = esistenti.get(isbn)
        # La riga della risposta nasce ORA, cosi' gli esiti restano
        # nell'ordine della richiesta; i campi veri li riempie il giro
        # sotto, a voce creata.
        rows.append({"isbn": isbn, "esito": "in_corso", "staged_id": None,
                     "title": None, "author": None, "cover": False,
                     "existing_book_id": occupante["id"] if occupante else None,
                     "existing_title": occupante["title"] if occupante else None})
        da_mettere.append((isbn, rows[-1]))

    trovati = metadata_scraper.fetch_metadata_by_isbn(
        [i for i, _ in da_mettere]) if da_mettere else {}

    for isbn, riga in da_mettere:
        meta = trovati.get(isbn)
        title = (meta or {}).get("title") or isbn
        item = models.IngestedBook(
            # La voce e' di chi la crea, come un file caricato dal web.
            user_id=current_user.id,
            # Nessun file: file_path vuoto e' lo stato dichiarato da
            # record_only — tutto cio' che presuppone un file salta.
            record_only=True,
            file_path="", filename=title, file_format="", file_size_bytes=0,
            title=title,
            author=(meta or {}).get("author"),
            description=(meta or {}).get("description") or "",
            pubdate=(meta or {}).get("pubdate"),
            isbn=isbn,
            status="pending",
        )
        db.add(item)
        db.flush()
        # La copertina vera delle fonti va nella stessa cache delle
        # copertine di staging (il nome e' l'id della riga, come per gli
        # EPUB): all'importazione diventera' la copertina della scheda.
        cover_ok = False
        if meta and meta.get("cover_url"):
            immagine = metadata_scraper.download_cover(meta["cover_url"])
            if immagine:
                os.makedirs(config.INGEST_COVERS_DIR, exist_ok=True)
                cover_path = os.path.join(config.INGEST_COVERS_DIR, f"{item.id}.jpg")
                try:
                    with open(cover_path, "wb") as f:
                        f.write(immagine)
                    item.cover_path = cover_path
                    cover_ok = True
                except OSError as e:
                    log_message("warning", "ingest", f"Saving the cover failed for ISBN {isbn}: {e}")
        riga.update({"esito": "in_attesa" if meta else "in_attesa_vuota",
                     "staged_id": item.id, "title": title,
                     "author": item.author, "cover": cover_ok})
        log_message("info", "ingest",
                    f"Entry from ISBN {isbn} pending: "
                    + ("metadata from the sources" if meta else "empty, to be filled in by hand"))
    db.commit()

    return {"library": library_name, "rows": rows}


# No shared mimetype helper exists elsewhere in the backend — books.py's own
# /{id}/download always answers application/octet-stream regardless of
# format, which is fine for a browser-triggered download but not for the web
# reader here, which needs a real EPUB/PDF Content-Type to behave.
_INGEST_MIME_TYPES = {
    ".epub": "application/epub+zip",
    ".pdf": "application/pdf",
    ".mobi": "application/x-mobipocket-ebook",
    ".azw3": "application/vnd.amazon.ebook",
    ".azw": "application/vnd.amazon.ebook",
    ".fb2": "application/x-fictionbook+xml",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


@router.get("/{id}/file", response_class=FileResponse, responses={200: {"content": {"application/octet-stream": {}}}})
def get_ingest_file(
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Streams the raw staged file itself, for the web reader's pre-import
    preview (App.vue's readIngestBookWeb) — the ingest counterpart of
    books.py's /{id}/download. A staging item has no library/calibre book id
    yet, so unlike that endpoint this one is looked up directly by the
    IngestedBook row's own id, straight off disk from its file_path.
    """
    item = _visible_to(
        db.query(models.IngestedBook).filter(models.IngestedBook.id == id),
        current_user,
    ).first()
    # 404 e non 403 per la riga di un altro (21/11/2026): per un utente
    # normale quella riga non esiste, e dirgli «esiste ma non e' tua»
    # racconterebbe gia' qualcosa che non deve vedere.
    if item and item.record_only:
        # La voce senza file (23/11/2026): non c'e' niente da aprire, e il
        # motivo va detto — un 404 qui sembrerebbe un file sparito.
        raise HTTPException(status_code=409, detail="This is a record-only entry: there is no file to open")
    if not item or not os.path.exists(item.file_path):
        raise HTTPException(status_code=404, detail="File not found in the staging folder")
    ext = os.path.splitext(item.file_path)[1].lower()
    media_type = _INGEST_MIME_TYPES.get(ext, "application/octet-stream")
    return FileResponse(item.file_path, filename=item.filename, media_type=media_type)


@public_router.get("/{id}/cover", response_class=FileResponse, responses={200: {"content": {"image/*": {}}}}, dependencies=[Depends(auth.utente_o_dispositivo)])
def get_ingest_cover(id: int, db: Session = Depends(database.get_db)):
    """
    Serves the cover image extracted at staging time (metadata_parser.py,
    only ever populated for EPUB — see that module for why PDF has none).
    """
    item = db.query(models.IngestedBook).filter(models.IngestedBook.id == id).first()
    if not item or not item.cover_path or not os.path.exists(item.cover_path):
        raise HTTPException(status_code=404, detail="Cover not available")
    ext = os.path.splitext(item.cover_path)[1].lower()
    media_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}.get(
        ext.lstrip("."), "application/octet-stream"
    )
    return FileResponse(item.cover_path, media_type=media_type)


@router.delete(
    "/{id}",
    responses={200: {"model": Esito}},
)
def discard_ingest_item(
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    "Scarta" reale per una riga di staging, singola: a differenza del vecchio
    comportamento solo-frontend (svuotava l'elenco in memoria, ma il file
    restava davvero sul disco e ricompariva al prossimo refetch/riavvio),
    qui il file sorgente E la copertina cache vengono rimossi dal disco e la
    riga viene eliminata: scartare deve eliminare il libro davvero, non
    solo togliere la riga dalla vista. Irreversibile: nessun cestino per lo
    staging, a differenza delle librerie vere (vedi settings.py's cestino
    librerie).
    """
    # Scartare elimina il FILE di qualcuno: la riga di un altro, per un
    # utente normale, non esiste (404, come in get_ingest_file — 21/11/2026).
    item = _visible_to(
        db.query(models.IngestedBook).filter(models.IngestedBook.id == id),
        current_user,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Staged item not found")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail="This staged item is already being imported, or is no longer available")

    if os.path.exists(item.file_path):
        try:
            os.remove(item.file_path)
        except OSError as e:
            log_message("warning", "ingest", f"Removing the staged file failed for '{item.file_path}': {e}")
    if item.cover_path and os.path.exists(item.cover_path):
        try:
            os.remove(item.cover_path)
        except OSError:
            pass

    title = item.title
    db.delete(item)
    db.commit()
    log_message("info", "ingest", f"Scartato dallo staging: '{title}' (file eliminato)")
    return {"status": "ok"}


def _open_ingest_destination(dest_dir: str, filename: str):
    """
    Returns an (open binary file handle, absolute path) pair for a new file in
    the given ingest folder. Uses exclusive creation ("xb") in a retry loop so
    two concurrent uploads of the same name can't clobber each other: on
    collision the name gets a " (2)", " (3)", ... suffix, mirroring Finder's
    convention. `dest_dir` e' la sottocartella dell'utente che carica
    (21/11/2026), non piu' la radice di ingest.
    """
    name, ext = os.path.splitext(filename)
    candidate = filename
    counter = 2
    while True:
        dest_path = os.path.join(dest_dir, candidate)
        try:
            return open(dest_path, "xb"), dest_path
        except FileExistsError:
            candidate = f"{name} ({counter}){ext}"
            counter += 1


@router.post(
    "/upload",
    responses={200: {"model": ArretratiCaricati}},
)
async def upload_ingest_files(
    files: List[UploadFile] = File(...),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Web-upload counterpart of the watched ingest folder: saves each uploaded
    file into config.INGEST_DIR and stages it immediately via stage_ingest_file
    (same routine the filesystem watcher uses), so the caller sees the staged
    records in the response without depending on the watcher's debounce timing.

    Accepted extensions are the ebook formats the rest of the app recognizes
    (services/library_scanner.EBOOK_EXTENSIONS); the watcher itself stages any
    non-hidden file, so this is the stricter, user-facing gate.
    """
    os.makedirs(config.INGEST_DIR, exist_ok=True)
    # Il file caricato dal web finisce nella cartella di chi lo carica
    # (21/11/2026): cosi' il proprietario non e' un'ipotesi, e' il percorso.
    dest_dir = ingest_folders.ensure_user_folder(current_user.id, current_user.username)
    staged = []
    rejected = []

    for upload in files:
        # Path-traversal hardening: keep only the basename, on both separators.
        original_name = os.path.basename((upload.filename or "").replace("\\", "/"))
        ext = os.path.splitext(original_name)[1].lower()

        if not original_name or original_name.startswith('.'):
            rejected.append({"filename": upload.filename or "(no name)", "reason": "Invalid file name"})
            continue
        if ext not in EBOOK_EXTENSIONS:
            allowed = ", ".join(sorted(e.lstrip('.') for e in EBOOK_EXTENSIONS))
            rejected.append({
                "filename": original_name,
                "reason": f"Extension '{ext or '(nessuna)'}' is not supported. Accepted formats: {allowed}",
            })
            continue

        out_handle, dest_path = _open_ingest_destination(dest_dir, original_name)
        size = 0
        too_big = False
        try:
            with out_handle:
                while chunk := await upload.read(_UPLOAD_CHUNK_BYTES):
                    size += len(chunk)
                    if size > MAX_UPLOAD_SIZE_BYTES:
                        too_big = True
                        break
                    out_handle.write(chunk)
        except Exception:
            # Partial write (client disconnect, disk error): don't leave a
            # truncated file behind for the watcher to stage.
            if os.path.exists(dest_path):
                os.remove(dest_path)
            raise
        finally:
            await upload.close()

        if too_big:
            os.remove(dest_path)
            rejected.append({
                "filename": original_name,
                "reason": f"File is too large: the limit is {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB per file",
            })
            continue

        # Stage right away; stage_ingest_file dedupes on file_path, so if the
        # watcher's debounce already staged this exact path (benign race) this
        # is a no-op and we just pick up the existing row.
        stage_ingest_file(db, dest_path)
        item = (
            db.query(models.IngestedBook)
            .filter(models.IngestedBook.file_path == os.path.abspath(dest_path))
            .first()
        )
        if item is None:
            # Shouldn't happen for a regular file we just wrote; clean up so the
            # ingest folder isn't left with an untracked file.
            if os.path.exists(dest_path):
                os.remove(dest_path)
            rejected.append({"filename": original_name, "reason": "Could not stage the file"})
            continue

        log_message("info", "ingest", f"Upload web: file '{os.path.basename(dest_path)}' salvato in ingest")
        staged.append(_serialize_ingest_item(item, {current_user.id: current_user.username}))

    return {"staged": staged, "rejected": rejected}


async def _import_record_only_item(payload, db, write_queue, item):
    """
    La voce SENZA file diventa una scheda Calibre senza formati
    (23/11/2026, scelta di Paolo: il fantasma «si crea una voce in ingest
    come per gli altri libri e dopo la si importa»).

    E' il gemello corto dell'importazione vera qui sotto: niente file da
    spostare, niente pagine, niente impronta, niente qualita' — solo i
    metadati (con gli stessi fallback della richiesta: l'editor rimanda
    solo cio' che l'utente ha toccato), l'ISBN come identificatore e la
    copertina scaricata in staging, che diventa la copertina della scheda.
    La compensazione sul fallimento e' la stessa: si disfa cio' che si era
    fatto e la voce torna in attesa.
    """
    book_id = None
    library_path = None
    try:
        library_name = resolve_folder_name(db, payload.library) if payload.library else resolve_default_library_folder(db)
        if not library_name:
            raise HTTPException(status_code=404, detail="No library is configured. Create one first.")
        library_path = config.library_path(library_name)
        title = payload.title or item.title
        author = payload.author or item.author or "Sconosciuto"

        book_id = await write_queue.submit("insert_book", {"title": title, "author": author}, library_path)
        # Cartella e percorso come per un libro vero: dentro non c'e'
        # (ancora) nessun file, ma e' li' che finiranno copertina e
        # formati futuri.
        rel = calibre_naming.percorso_per_libro(book_id, title, author)
        os.makedirs(os.path.join(library_path, rel), exist_ok=True)
        fields = {"path": rel}
        if item.pubdate:
            fields["pubdate"] = item.pubdate
        await write_queue.submit("update_book", {"book_id": book_id, "fields": fields}, library_path)

        isbn = payload.isbn or item.isbn
        if isbn:
            await write_queue.submit("set_identifiers", {"book_id": book_id, "identifiers": {"isbn": isbn}}, library_path)
        description = payload.description if payload.description is not None else item.description
        if description:
            await write_queue.submit("set_comments", {"book_id": book_id, "text": description}, library_path)
        tags = payload.tags if payload.tags is not None else [t for t in (item.tags or "").split(",") if t]
        if tags:
            await write_queue.submit("set_book_tags", {"book_id": book_id, "tags": tags}, library_path)
        series = payload.series if payload.series is not None else item.series
        if series:
            await write_queue.submit(
                "set_book_series",
                {"book_id": book_id, "series_name": series,
                 "series_index": payload.series_index if payload.series_index is not None else item.series_index},
                library_path,
            )
        language = payload.language if payload.language is not None else item.language
        if language:
            await write_queue.submit("set_language", {"book_id": book_id, "lang_code": language}, library_path)

        if item.cover_path and os.path.exists(item.cover_path):
            try:
                with open(item.cover_path, "rb") as f:
                    image_b64 = base64.b64encode(f.read()).decode("ascii")
                await write_queue.submit("set_cover", {"book_id": book_id, "image_b64": image_b64}, library_path)
            except Exception as e:
                log_message("warning", "ingest", f"Setting the cover failed for '{title}': {e}")
            try:
                os.remove(item.cover_path)
            except OSError:
                pass

        item.status = "confirmed"
        item.processed_at = datetime.utcnow()
        db.commit()
    except Exception:
        if book_id is not None:
            try:
                await write_queue.submit("delete_book", {"book_id": book_id}, library_path)
            except Exception as e:
                log_message("warning", "ingest", f"Rollback: Calibre book {book_id} not removed: {e}")
        item.status = "pending"
        db.commit()
        raise

    author_stats_service.safe_mark_author_pages_dirty(db)
    author_ingest_hook.maybe_trigger_wiki_scrape(string_to_authors(author))
    log_message("info", "ingest", f"Imported record-only entry '{title}' into library '{library_name}'")
    return {"status": "ok", "book_id": book_id}


@router.post(
    "/import-book",
    responses={200: {"model": LibroImportato}},
)
async def import_book_from_ingest(
    payload: schemas.IngestImportRequest,
    db: Session = Depends(database.get_db),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    # Atomically claim the ingest row before doing anything else: two concurrent
    # imports of the same id (e.g. a double-click, or a retried request) must not
    # both pass the "pending" check and race to move the same source file.
    # Il filtro di visibilita' sta DENTRO la stessa update (21/11/2026): un
    # utente normale non puo' reclamare la riga di un altro, e per lui
    # l'esito e' lo stesso 409 di una riga che non c'e' piu'.
    claimed = (
        _visible_to(
            db.query(models.IngestedBook)
            .filter(models.IngestedBook.id == payload.id, models.IngestedBook.status == "pending"),
            current_user,
        )
        .update({"status": "importing"}, synchronize_session=False)
    )
    db.commit()
    if not claimed:
        raise HTTPException(status_code=409, detail="This staged item is already being imported, or is no longer available")

    item = db.query(models.IngestedBook).filter(models.IngestedBook.id == payload.id).first()
    # La voce senza file prende la sua strada corta (23/11/2026): niente
    # file da spostare, niente pagine ne' impronta ne' qualita'. Tutto il
    # resto di questa funzione presuppone un file sul disco.
    if item.record_only:
        return await _import_record_only_item(payload, db, write_queue, item)
    # Il cancello dei formati (scelta di Paolo, 23/11/2026): un file fuori
    # lista sta in arretrato solo per essere visto e scartato. Il rifiuto
    # sta QUI e non solo nel browser; la riga torna "pending" perche' il
    # claim qui sopra l'aveva gia' marcata "importing".
    if not formato_ammesso(item.file_format):
        item.status = "pending"
        db.commit()
        allowed = ", ".join(sorted(e.lstrip(".") for e in EBOOK_EXTENSIONS))
        raise HTTPException(
            status_code=409,
            detail=f"Format '{item.file_format or '(none)'}' is not an accepted format "
                   f"(accepted: {allowed}). This entry can only be discarded.",
        )

    # Compensation state for the `except` below: an import that fails halfway
    # used to leave BOTH a half-built Calibre book (a row with no path and no
    # format — unreachable from every UI, undeletable from the library view)
    # AND a staging row flipped back to "pending" pointing at a file that had
    # already been moved into the library. Retrying then died on a 404 and the
    # ghost stayed forever. We now remember what we did so we can undo it.
    book_id = None
    dest_file = None
    try:
        if not os.path.exists(item.file_path):
            raise HTTPException(status_code=404, detail="File not found in the staging folder")

        library_name = resolve_folder_name(db, payload.library) if payload.library else resolve_default_library_folder(db)
        if not library_name:
            raise HTTPException(status_code=404, detail="No library is configured. Create one first.")
        library_path = config.library_path(library_name)
        title = payload.title or item.title
        author = payload.author or item.author or "Unknown Author"

        book_id = await write_queue.submit("insert_book", {"title": title, "author": author}, library_path)

        # Cartella e nome file come li farebbe Calibre (primo autore,
        # traslitterato e troncato; file "Titolo - Autore.est") — prima erano
        # la stringa autore intera e il nome del file caricato, che e' la
        # differenza che si vede aprendo la cartella.
        target_dir_rel = calibre_naming.percorso_per_libro(book_id, title, author)
        target_dir_abs = os.path.join(library_path, target_dir_rel)
        os.makedirs(target_dir_abs, exist_ok=True)
        nome_file = calibre_naming.construct_file_name(
            title, calibre_naming.autore_di_cartella(author),
            calibre_naming.lunghezza_estensione([item.file_format]),
        )
        dest_file = os.path.join(target_dir_abs, f"{nome_file}.{item.file_format.lower()}")
        # copy2, not move: the staging file stays put until the whole import
        # has committed (removed at the very bottom). Moving first meant a
        # failure anywhere below destroyed the only copy the retry could use.
        shutil.copy2(item.file_path, dest_file)

        await write_queue.submit("update_book", {"book_id": book_id, "fields": {"path": target_dir_rel}}, library_path)
        await write_queue.submit(
            "add_format",
            {
                "book_id": book_id,
                "fmt": item.file_format,
                "size_bytes": os.path.getsize(dest_file),
                "name": os.path.splitext(os.path.basename(dest_file))[0],
            },
            library_path,
        )

        # Editor metadati esteso (frontend): ogni campo, se omesso dal
        # payload, ricade sul valore già presente su IngestedBook (auto-
        # estratto in staging — vedi metadata_parser.py) invece che andare
        # perso, stesso pattern di title/author sopra.
        description = payload.description if payload.description is not None else item.description
        tags = payload.tags if payload.tags is not None else (item.tags.split(",") if item.tags else None)
        series = payload.series if payload.series is not None else item.series
        series_index = payload.series_index if payload.series_index is not None else item.series_index
        language = payload.language if payload.language is not None else item.language
        isbn = payload.isbn if payload.isbn is not None else item.isbn

        if description:
            await write_queue.submit("set_comments", {"book_id": book_id, "text": description}, library_path)
        if tags:
            await write_queue.submit("set_book_tags", {"book_id": book_id, "tags": tags}, library_path)
        if series:
            await write_queue.submit(
                "set_book_series", {"book_id": book_id, "series_name": series, "series_index": series_index},
                library_path,
            )
        if language:
            await write_queue.submit("set_language", {"book_id": book_id, "lang_code": language}, library_path)
        if isbn:
            await write_queue.submit("set_identifiers", {"book_id": book_id, "identifiers": {"isbn": isbn}}, library_path)

        if item.cover_path and os.path.exists(item.cover_path):
            try:
                with open(item.cover_path, "rb") as f:
                    image_b64 = base64.b64encode(f.read()).decode("ascii")
                await write_queue.submit("set_cover", {"book_id": book_id, "image_b64": image_b64}, library_path)
            except Exception as e:
                log_message("warning", "ingest", f"Setting the cover failed for '{title}': {e}")
            # La riga di staging resta (status passa a "confirmed" poco sotto,
            # per audit/duplicate-check — non viene eliminata come su
            # discard), ma il file cover cache non serve più: il libro ha
            # ormai la sua copertina vera nella libreria Calibre.
            try:
                os.remove(item.cover_path)
            except OSError:
                pass

        page_settings = app_settings.get_page_count_settings(db)
        pages = page_counter.count_pages(
            dest_file, item.file_format, page_settings["mode"],
            page_settings["words_per_page"], page_settings["chars_per_page"],
        )
        stats_service.registra_conteggio_testo(db, library_name, book_id, dest_file, item.file_format)
        if pages is not None:
            await write_queue.submit(
                "update_book", {"book_id": book_id, "fields": page_count_fields(pages)}, library_path
            )

        # L'impronta del file come e' arrivato: Kolibre non scrive piu'
        # niente dentro i libri (24/11/2026), e la regola «l'impronta dopo
        # ogni scrittura» sta in un posto solo — vedi `chiudi_i_formati`.
        try:
            book_hash_service.chiudi_i_formati(
                db, library_path, library_name, book_id, {item.file_format: dest_file},
            )
        except Exception as e:
            log_message("warning", "ingest", f"Closing the formats failed for '{dest_file}': {e}")

        # La qualita' segue il libro dentro la biblioteca. Il travaso
        # riesce solo se il file e' ancora quello misurato in ingest; se non
        # lo e', si rimisura quel libro soltanto, subito, invece di
        # aspettare il prossimo giro della coda.
        try:
            if not qualita_job.travasa_da_ingest(db, item, library_name, book_id, dest_file):
                qualita_job.analizza_libro_async(library_name, book_id, dest_file)
        except Exception as e:
            log_message("warning", "qualita", f"Quality not recorded for '{title}': {e}")

        item.status = "confirmed"
        item.processed_at = datetime.utcnow()
        db.commit()

        # Only now that everything above succeeded and committed does the
        # staging copy go away. Best-effort: a leftover file in ingest is
        # harmless (the row is "confirmed", so it won't be offered again),
        # a failed import that already deleted it would not be.
        try:
            os.remove(item.file_path)
        except OSError:
            pass
    except Exception:
        # Undo, in reverse order, whatever we managed to do — so the retry
        # starts from the same state as the first attempt.
        if dest_file and os.path.exists(dest_file):
            try:
                shutil.rmtree(os.path.dirname(dest_file))
            except OSError as e:
                log_message("warning", "ingest", f"Rollback: the book folder was not removed ({dest_file}): {e}")
        if book_id is not None:
            try:
                await write_queue.submit("delete_book", {"book_id": book_id}, library_path)
            except Exception as e:
                log_message("warning", "ingest", f"Rollback: Calibre book {book_id} not removed: {e}")
        item.status = "pending"
        db.commit()
        raise

    author_stats_service.safe_mark_author_pages_dirty(db)
    author_ingest_hook.maybe_trigger_wiki_scrape(string_to_authors(author))
    log_message("info", "ingest", f"Imported book '{title}' into library '{library_name}'")
    return {"status": "ok", "book_id": book_id}
