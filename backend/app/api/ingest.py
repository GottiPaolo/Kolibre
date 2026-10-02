import base64
import os
import shutil
import threading
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import auth, config, models, schemas, database
from ..logging_utils import log_message
from ..services import duplicates, page_counter, app_settings, book_hash_service, opf_metadata, author_ingest_hook, author_stats_service, stats_service, ingest_import_job
from ..services.library_scanner import EBOOK_EXTENSIONS
from ..services.watcher import stage_ingest_file
from ..calibre import calibre_naming
from ..calibre.library import CalibreLibrary
from ..calibre.connection import page_count_fields
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


def _serialize_ingest_item(item: models.IngestedBook) -> dict:
    """Wire format of a staged ingest item, shared by the list and upload endpoints."""
    return {
        "id": item.id,
        "title": item.title,
        "author": item.author or "Autore Sconosciuto",
        "formats": [item.file_format],
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
        noti = {r[0] for r in db.query(models.IngestedBook.file_path).all()}
        for f in sorted(os.listdir(config.INGEST_DIR)):
            percorso = os.path.abspath(os.path.join(config.INGEST_DIR, f))
            if percorso not in noti:
                stage_ingest_file(db, percorso)


@router.get("")
def list_ingest_books(
    db: Session = Depends(database.get_db),
    limit: int = None,
    offset: int = 0,
):
    """
    Senza `limit` restituisce tutto, come sempre. Con `limit` una pagina —
    {items, total, offset, limit} — nella stessa forma di GET /books.

    Serve al caso vero: una cartella con migliaia di file da rivedere. La
    pagina Ingest disegna una scheda per ogni libro, con copertina e
    metadati, e a qualche migliaio diventa una pagina che non si apre.
    """
    _scan_ingest_folder(db)
    q = (
        db.query(models.IngestedBook)
        .filter(models.IngestedBook.status == "pending")
        .order_by(models.IngestedBook.id)
    )
    if limit is None:
        return [_serialize_ingest_item(item) for item in q.all()]
    totale = q.count()
    items = q.limit(int(limit)).offset(max(0, int(offset))).all()
    return {
        "items": [_serialize_ingest_item(item) for item in items],
        "total": totale,
        "offset": max(0, offset),
        "limit": limit,
    }


@router.post("/import-job")
async def start_ingest_import_job(
    payload: dict,
    request: Request,
    db: Session = Depends(database.get_db),
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
        ids = [
            r[0] for r in db.query(models.IngestedBook.id)
            .filter(models.IngestedBook.status == "pending")
            .order_by(models.IngestedBook.id).all()
        ]
    voci = [(int(i), per_item.get(str(i)) or generale) for i in ids]
    if not voci:
        raise HTTPException(status_code=400, detail="Nessun libro da importare")
    if not ingest_import_job.start(voci, request.app.state.write_queue):
        raise HTTPException(status_code=409, detail="Un'importazione in blocco è già in corso")
    log_message("info", "ingest", f"Importazione in blocco avviata: {len(voci)} libri")
    return {"status": "started", "total": len(voci)}


@router.get("/import-job")
def get_ingest_import_job():
    """Stato dell'importazione in blocco. Interrogabile da qualunque pagina."""
    return ingest_import_job.status()


@router.post("/import-job/stop")
def stop_ingest_import_job():
    """Ferma dopo il libro in corso. Quelli gia' importati restano importati."""
    return {"stopping": ingest_import_job.stop()}


@router.get("/pagination")
def get_ingest_pagination(db: Session = Depends(database.get_db)):
    """Se la pagina Ingest va impaginata, e con che pagina. Conta e basta."""
    _scan_ingest_folder(db)
    totale = (
        db.query(models.IngestedBook)
        .filter(models.IngestedBook.status == "pending")
        .count()
    )
    conf = app_settings.get_ingest_pagination(db)
    return {
        "total": totale,
        "paginated": app_settings.ingest_pagination_applies(db, totale),
        "page_size": conf["page_size"],
        "mode": conf["mode"],
        "threshold": conf["threshold"],
    }


@router.get("/duplicati")
def ingest_duplicati(
    library: str = None,
    db: Session = Depends(database.get_db),
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
    in_attesa = (
        db.query(models.IngestedBook)
        .filter(models.IngestedBook.status == "pending")
        .all()
    )
    if not in_attesa:
        return {"library": folder, "duplicati": {}}

    try:
        libri = CalibreLibrary(config.library_path(folder)).list_books()
    except Exception as exc:
        log_message("warning", "ingest", f"Controllo doppioni saltato per '{folder}': {exc}")
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
            {"id": libro["id"], "title": libro["title"], "author": libro.get("author"),
             "formats": libro.get("formats") or []}
            for libro in candidati
            if duplicates.affinita_titoli(item.title or "", libro.get("title") or "")
            >= duplicates.SOGLIA_AFFINITA
        ]
        if simili:
            duplicati[str(item.id)] = simili[:5]
    return {"library": folder, "duplicati": duplicati}


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
}


@router.get("/{id}/file")
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
    item = db.query(models.IngestedBook).filter(models.IngestedBook.id == id).first()
    if not item or not os.path.exists(item.file_path):
        raise HTTPException(status_code=404, detail="File non trovato in ingest")
    ext = os.path.splitext(item.file_path)[1].lower()
    media_type = _INGEST_MIME_TYPES.get(ext, "application/octet-stream")
    return FileResponse(item.file_path, filename=item.filename, media_type=media_type)


@public_router.get("/{id}/cover", dependencies=[Depends(auth.utente_o_dispositivo)])
def get_ingest_cover(id: int, db: Session = Depends(database.get_db)):
    """
    Serves the cover image extracted at staging time (metadata_parser.py,
    only ever populated for EPUB — see that module for why PDF has none).
    """
    item = db.query(models.IngestedBook).filter(models.IngestedBook.id == id).first()
    if not item or not item.cover_path or not os.path.exists(item.cover_path):
        raise HTTPException(status_code=404, detail="Copertina non disponibile")
    ext = os.path.splitext(item.cover_path)[1].lower()
    media_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}.get(
        ext.lstrip("."), "application/octet-stream"
    )
    return FileResponse(item.cover_path, media_type=media_type)


@router.delete("/{id}")
def discard_ingest_item(id: int, db: Session = Depends(database.get_db)):
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
    item = db.query(models.IngestedBook).filter(models.IngestedBook.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Elemento di ingest non trovato")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail="Elemento di ingest già in importazione o non più disponibile")

    if os.path.exists(item.file_path):
        try:
            os.remove(item.file_path)
        except OSError as e:
            log_message("warning", "ingest", f"Rimozione file staging fallita per '{item.file_path}': {e}")
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


def _open_ingest_destination(filename: str):
    """
    Returns an (open binary file handle, absolute path) pair for a new file in
    the ingest folder. Uses exclusive creation ("xb") in a retry loop so two
    concurrent uploads of the same name can't clobber each other: on collision
    the name gets a " (2)", " (3)", ... suffix, mirroring Finder's convention.
    """
    name, ext = os.path.splitext(filename)
    candidate = filename
    counter = 2
    while True:
        dest_path = os.path.join(config.INGEST_DIR, candidate)
        try:
            return open(dest_path, "xb"), dest_path
        except FileExistsError:
            candidate = f"{name} ({counter}){ext}"
            counter += 1


@router.post("/upload")
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
    staged = []
    rejected = []

    for upload in files:
        # Path-traversal hardening: keep only the basename, on both separators.
        original_name = os.path.basename((upload.filename or "").replace("\\", "/"))
        ext = os.path.splitext(original_name)[1].lower()

        if not original_name or original_name.startswith('.'):
            rejected.append({"filename": upload.filename or "(senza nome)", "reason": "Nome file non valido"})
            continue
        if ext not in EBOOK_EXTENSIONS:
            allowed = ", ".join(sorted(e.lstrip('.') for e in EBOOK_EXTENSIONS))
            rejected.append({
                "filename": original_name,
                "reason": f"Estensione '{ext or '(nessuna)'}' non supportata. Formati accettati: {allowed}",
            })
            continue

        out_handle, dest_path = _open_ingest_destination(original_name)
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
                "reason": f"File troppo grande: il limite è {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB per file",
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
            rejected.append({"filename": original_name, "reason": "Staging del file fallito"})
            continue

        log_message("info", "ingest", f"Upload web: file '{os.path.basename(dest_path)}' salvato in ingest")
        staged.append(_serialize_ingest_item(item))

    return {"staged": staged, "rejected": rejected}


@router.post("/import-book")
async def import_book_from_ingest(
    payload: schemas.IngestImportRequest,
    db: Session = Depends(database.get_db),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    # Atomically claim the ingest row before doing anything else: two concurrent
    # imports of the same id (e.g. a double-click, or a retried request) must not
    # both pass the "pending" check and race to move the same source file.
    claimed = (
        db.query(models.IngestedBook)
        .filter(models.IngestedBook.id == payload.id, models.IngestedBook.status == "pending")
        .update({"status": "importing"}, synchronize_session=False)
    )
    db.commit()
    if not claimed:
        raise HTTPException(status_code=409, detail="Elemento di ingest già in importazione o non più disponibile")

    item = db.query(models.IngestedBook).filter(models.IngestedBook.id == payload.id).first()
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
            raise HTTPException(status_code=404, detail="File non trovato in ingest")

        library_name = resolve_folder_name(db, payload.library) if payload.library else resolve_default_library_folder(db)
        if not library_name:
            raise HTTPException(status_code=404, detail="Nessuna libreria configurata. Creane una prima di continuare.")
        library_path = config.library_path(library_name)
        title = payload.title or item.title
        author = payload.author or item.author or "Autore Sconosciuto"

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
                log_message("warning", "ingest", f"Impostazione copertina fallita per '{title}': {e}")
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
            # Best-effort, never load-bearing for the import itself — see
            # opf_metadata.py's own docstring for why ProjectTitle needs this
            # embedded in the file, not just in metadata.db.
            try:
                opf_metadata.embed_page_count(library_path, dest_file, item.file_format, pages)
            except Exception as e:
                log_message("warning", "ingest", f"Embedding pagine nell'OPF fallito per '{dest_file}': {e}")

        book_hash_service.upsert_book_hash(db, library_name, book_id, item.file_format, dest_file)

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
                log_message("warning", "ingest", f"Rollback: cartella libro non rimossa ({dest_file}): {e}")
        if book_id is not None:
            try:
                await write_queue.submit("delete_book", {"book_id": book_id}, library_path)
            except Exception as e:
                log_message("warning", "ingest", f"Rollback: libro Calibre {book_id} non rimosso: {e}")
        item.status = "pending"
        db.commit()
        raise

    author_stats_service.safe_mark_author_pages_dirty(db)
    author_ingest_hook.maybe_trigger_wiki_scrape(string_to_authors(author))
    log_message("info", "ingest", f"Imported book '{title}' into library '{library_name}'")
    return {"status": "ok", "book_id": book_id}
