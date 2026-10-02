import base64
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional

from .. import config, models, database, auth
from ..logging_utils import log_message
from ..calibre import calibre_naming
from ..calibre.library import CalibreLibrary
from ..calibre.functions import string_to_authors
from ..calibre.connection import page_count_fields
from ..calibre.write_queue import CalibreWriteQueue
from ..deps import get_write_queue
from ..services import app_settings, fulltext_index, author_ingest_hook, book_hash_service, book_records, page_counter, opf_metadata, author_stats_service, stats_service
from .libraries import sync_library_registry, _library_stats

router = APIRouter(prefix="/api/kolibre/library-transfer", tags=["library-transfer"])

# Whole-library export/import for the Calibre Desktop plugin
# (plugins/calibre/kolibre_sync/): unlike the rest of the API — which is
# shaped around the web UI's per-field editing flows, or the KOReader
# device's own sync/catalog protocol — the plugin needs to (a) enumerate a
# server library well enough to recreate it locally with Calibre's own
# database API, and (b) push a whole local library (books + selected custom
# columns + optionally a previously-downloaded full-text index) up as a new
# server library in one guided flow. Deliberately additive: every existing
# endpoint used elsewhere (list_books, custom-columns, per-book download,
# create_library, recompute-hashes/pages, fulltext/reindex) is reused as-is
# rather than duplicated.


def _require_library(folder: str) -> str:
    library_path = config.library_path(folder)
    if not os.path.exists(os.path.join(library_path, "metadata.db")):
        raise HTTPException(status_code=404, detail=f"Libreria '{folder}' non trovata sul server")
    return library_path


def _parse_calibre_annotation_timestamp(value):
    """Calibre's own annotation timestamp — confirmed directly against a
    real entry via calibre-debug (db.new_api.all_annotations_for_book):
    ISO8601 with a trailing 'Z', e.g. "2025-01-19T18:10:15.827Z". Same class
    of bug as KOReader's own a.datetime (see devices.py's
    _parse_koreader_datetime): this field existed all along but was never
    read, so every Calibre-viewer highlight's created_at was always "when
    this sync happened to run", not when the highlight was actually made.
    .replace('Z', '+00:00') first since datetime.fromisoformat() only
    accepts a bare 'Z' natively from Python 3.11 onward, and this string
    comes from Calibre Desktop's own (possibly older) bundled Python, not
    this backend's — then normalized to naive UTC to match every other
    created_at in this table (datetime.utcnow(), also naive), so nothing
    downstream trips over comparing aware vs. naive datetimes. Returns None
    for anything missing/malformed."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _apply_calibre_annotations(db: Session, user_id: int, folder: str, book_id: int, annotations: list):
    """
    Upserts highlights read from Calibre Desktop's own built-in viewer (see
    the plugin's book_snapshot.py::calibre_annotations_for_book) into the
    unified Highlight table, keyed on (library, calibre_book_id, annot_id) —
    Calibre's own annotation uuid — so re-running a sync updates an existing
    row instead of duplicating it every time. Never deletes: an annotation
    that disappears from Calibre (edited/removed there) is left alone here,
    same "never destructive" rule already used for device-sourced highlights
    in devices.py's push_device_annotations.
    """
    for annot in annotations or []:
        annot_id = annot.get("annot_id")
        if not annot_id:
            continue
        # Same "device/source is the source of truth for the real creation
        # date" fix as devices.py's push_device_annotations — applied on
        # both insert and update so a highlight synced late (or before this
        # fix existed) self-heals to its real date on its very next sync.
        hl_datetime = _parse_calibre_annotation_timestamp(annot.get("timestamp"))
        existing = (
            db.query(models.Highlight)
            .filter(
                models.Highlight.library == folder,
                models.Highlight.calibre_book_id == book_id,
                models.Highlight.annot_id == annot_id,
            )
            .first()
        )
        if existing:
            existing.text = annot.get("text") or existing.text
            existing.comment = annot.get("comment")
            existing.cfi_start = annot.get("cfi_start")
            existing.cfi_end = annot.get("cfi_end")
            if hl_datetime:
                existing.created_at = hl_datetime
        else:
            db.add(models.Highlight(
                user_id=user_id,
                library=folder,
                calibre_book_id=book_id,
                text=annot.get("text") or "",
                comment=annot.get("comment"),
                cfi_start=annot.get("cfi_start"),
                cfi_end=annot.get("cfi_end"),
                annot_id=annot_id,
                source="calibre",
                **({"created_at": hl_datetime} if hl_datetime else {}),
            ))
    db.commit()


@router.get("")
def list_transferable_libraries(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    folder_name-aware library listing for the plugin: GET /api/kolibre/libraries
    (used by the web UI) is display-name-oriented and doesn't expose the
    on-disk folder_name that every other per-library endpoint (books,
    custom-columns, fulltext, this router) expects as its `library`/`folder`
    parameter — mirrors the same reasoning as devices.py's
    /api/kolibre/devices/libraries (the KOReader-plugin equivalent).
    """
    sync_library_registry(db)
    rows = db.query(models.Library).order_by(models.Library.id).all()
    result = []
    for row in rows:
        stats = _library_stats(row.folder_name)
        result.append({
            "name": row.name,
            "folder_name": row.folder_name,
            "fulltext_enabled": app_settings.is_fulltext_enabled(db, row.folder_name),
            **stats,
        })
    return result


@router.get("/{folder}/manifest")
def get_library_manifest(
    folder: str,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Everything the plugin's download flow needs in one call: custom column
    definitions, every book's metadata/tags/custom values/format list (same
    shape /api/kolibre/books already returns per book), and whether a
    Kolibre full-text index exists for this library. Per-format file bytes
    and covers are still fetched individually via the existing
    /api/kolibre/books/{id}/download and /cover endpoints — this endpoint is
    just the plan, not the payload.
    """
    library_path = _require_library(folder)
    lib = CalibreLibrary(library_path)
    row = db.query(models.Library).filter(models.Library.folder_name == folder).first()
    display_name = row.name if row else folder

    fulltext_path = os.path.join(library_path, fulltext_index.FULLTEXT_DB_FILENAME)
    fulltext_available = os.path.exists(fulltext_path)

    books = []
    for b in lib.list_books():
        custom_values = {k: v for k, v in b.items() if k.startswith("#")}
        books.append({
            "id": b["id"],
            "title": b["title"],
            "author": b["author"],
            "series": b["series"],
            "series_index": b["series_index"],
            "tags": b["tags"],
            "formats": b["formats"],
            "size": b["size"],
            # Qui, e SOLO qui, resta "solo se c'e' davvero": questo manifest
            # serve al plugin Calibre per scaricare una biblioteca, e una
            # copertina costruita da noi finirebbe scritta dentro la
            # biblioteca Calibre locale come se fosse vera. Il ripiego visivo
            # vale per chi guarda, non per chi copia.
            "cover_url": f"/api/kolibre/books/{b['id']}/cover?library={folder}" if b["cover_path"] else None,
            # Needed by the Calibre plugin's "librerie accoppiate" diff
            # (pairing_diff.py): without this, the plugin has no way to
            # tell a book that changed server-side after the last sync from
            # one that didn't — lib.list_books() already carries it, this
            # explicit field list had just never been extended to include it.
            "last_modified": b["last_modified"],
            # Native rating/pubdate — like last_modified above, list_books()
            # already carries these, they just were never forwarded into the
            # manifest, so a download/update_local never had them to write
            # back into the local Calibre book.
            "rating": b["rating"],
            "pubdate": b["pubdate"],
            **custom_values,
        })

    return {
        "folder_name": folder,
        "display_name": display_name,
        "custom_columns": lib.list_custom_columns(),
        "fulltext": {
            "available": fulltext_available,
            "size_bytes": os.path.getsize(fulltext_path) if fulltext_available else 0,
        },
        "books": books,
        "total_books": len(books),
    }


@router.get("/{folder}/fulltext-db")
def download_library_fulltext_db(
    folder: str,
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    library_path = _require_library(folder)
    fulltext_path = os.path.join(library_path, fulltext_index.FULLTEXT_DB_FILENAME)
    if not os.path.exists(fulltext_path):
        raise HTTPException(status_code=404, detail="Nessun indice full-text per questa libreria")
    return FileResponse(fulltext_path, filename=fulltext_index.FULLTEXT_DB_FILENAME)


@router.post("/{folder}/fulltext-db")
async def upload_library_fulltext_db(
    folder: str,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Raw-bytes upload (no multipart, same pattern as devices.py's
    /api/kolibre/devices/backup) of a fulltext.db previously downloaded from
    THIS server (or another Kolibre server) — accepted only after validating
    it's actually a SQLite db with the expected fts_meta table, so a
    malformed/foreign file can't silently replace a library's working index.
    """
    library_path = _require_library(folder)
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Corpo della richiesta vuoto")

    tmp_path = os.path.join(library_path, f".{fulltext_index.FULLTEXT_DB_FILENAME}.upload.tmp")
    with open(tmp_path, "wb") as f:
        f.write(body)

    try:
        conn = sqlite3.connect(tmp_path)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        os.remove(tmp_path)
        raise HTTPException(status_code=400, detail="Il file caricato non è un database SQLite valido")

    if "fts_meta" not in tables:
        os.remove(tmp_path)
        raise HTTPException(status_code=400, detail="Il database caricato non ha lo schema fulltext atteso da Kolibre")

    final_path = os.path.join(library_path, fulltext_index.FULLTEXT_DB_FILENAME)
    os.replace(tmp_path, final_path)
    app_settings.set_fulltext_enabled(db, folder, True)

    log_message("info", "library-transfer", f"Indice full-text caricato per la libreria '{folder}' ({len(body)} byte)")
    return {"status": "ok", "bytes": len(body)}


@router.post("/{folder}/books")
async def upload_library_book(
    folder: str,
    metadata: str = Form(...),
    files: List[UploadFile] = File(...),
    cover: Optional[UploadFile] = File(None),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Accepts one book (metadata + format files + optional cover) as a direct
    multipart upload — the missing piece for a remote client (the Calibre
    plugin) to push books into a server library. Unlike
    /api/kolibre/ingest/import-book, which only promotes a file the server's
    OWN filesystem watcher already staged from a local folder, this takes
    the file bytes directly in the request body, since the plugin's source
    library lives on a different machine entirely.

    identifiers/publisher/tags/series(name)/comments are all optional in
    `meta` and, when present, applied via their own write-queue ops
    (set_identifier/set_publisher/set_book_tags/set_book_series/set_comments)
    — these are relations, not plain `books` columns, so they can't just be
    folded into the `fields` dict below the way series_index/custom columns
    are. This closes the same gap ingest.py's import flow still has (a
    plain local-folder import never had a remote-client identifiers problem
    to begin with, so it wasn't the reported bug, but it's the identical fix
    if/when that flow needs it too).
    """
    library_path = _require_library(folder)

    try:
        meta = json.loads(metadata)
    except ValueError:
        raise HTTPException(status_code=400, detail="Il campo 'metadata' non è JSON valido")

    title = (meta.get("title") or "").strip()
    author = (meta.get("author") or "Autore Sconosciuto").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title è obbligatorio")
    if not files:
        raise HTTPException(status_code=400, detail="È richiesto almeno un file di formato")
    # Checked BEFORE insert_book, not after: this used to run only once
    # every upload_file had already been saved, so a request whose files all
    # lacked a recognizable extension still left an orphan `books` row
    # behind (insert_book already committed, nothing here ever rolled it
    # back or cleaned it up).
    if not any(os.path.splitext(f.filename or "")[1].lstrip(".") for f in files):
        raise HTTPException(status_code=400, detail="Nessun file con estensione riconoscibile tra quelli caricati")

    insert_payload = {"title": title, "author": author}
    if meta.get("timestamp"):
        insert_payload["timestamp"] = meta["timestamp"]
    book_id = await write_queue.submit("insert_book", insert_payload, library_path)
    try:
        return await _completa_caricamento(
            folder, library_path, book_id, title, author, meta, files, cover,
            write_queue, db, current_user,
        )
    except Exception:
        # Da qui in poi il libro ESISTE gia' nel catalogo: qualunque cosa
        # vada storta lascerebbe una riga a meta' — senza percorso, quindi
        # senza file raggiungibili — che compare nell'elenco e non si apre.
        # E' successo davvero: un NameError in questa funzione (folder_name
        # invece di folder, introdotto il 22/09 e sopravvissuto perche'
        # nessuna prova copriva questo endpoint) faceva fallire ogni
        # caricamento dal plugin Calibre DOPO l'inserimento, lasciando in
        # catalogo un libro fantasma per ogni tentativo.
        #
        # Meglio niente che mezzo: il libro si toglie e l'errore sale, cosi'
        # il plugin lo riporta e si riprova su un catalogo pulito.
        log_message("error", "library_transfer",
                    f"Caricamento di '{title}' fallito dopo l'inserimento: tolgo il libro {book_id} rimasto a meta'")
        try:
            await write_queue.submit("delete_book", {"book_id": book_id}, library_path)
        except Exception as pulizia:
            log_message("error", "library_transfer",
                        f"Non sono riuscito a togliere il libro {book_id} rimasto a meta': {pulizia}")
        raise


async def _completa_caricamento(
    folder, library_path, book_id, title, author, meta, files, cover,
    write_queue, db, current_user,
):
    """Tutto quello che viene dopo l'inserimento della riga del libro.

    Sta in una funzione a parte solo per avere un punto in cui avvolgere
    l'intero seguito in un try: se qualcosa fallisce qui, il libro appena
    creato va tolto, o resta nel catalogo senza percorso e senza file."""
    # Cartella e nomi file nella forma di Calibre (vedi calibre_naming).
    target_dir_rel = calibre_naming.percorso_per_libro(book_id, title, author)
    target_dir_abs = os.path.join(library_path, target_dir_rel)
    os.makedirs(target_dir_abs, exist_ok=True)

    estensioni = [os.path.splitext(u.filename or "")[1].lstrip(".").upper() for u in files]
    nome_file = calibre_naming.construct_file_name(
        title, calibre_naming.autore_di_cartella(author),
        calibre_naming.lunghezza_estensione([e for e in estensioni if e]),
    )

    saved_formats = []
    format_paths: dict[str, str] = {}
    for uploaded in files:
        ext = os.path.splitext(uploaded.filename or "")[1].lstrip(".").upper()
        if not ext:
            continue
        # Un solo nome per tutti i formati dello stesso libro, come Calibre:
        # e' l'estensione a distinguerli.
        base_name = nome_file
        dest_path = os.path.join(target_dir_abs, f"{base_name}.{ext.lower()}")
        content = await uploaded.read()
        with open(dest_path, "wb") as out:
            out.write(content)
        await write_queue.submit(
            "add_format", {"book_id": book_id, "fmt": ext, "size_bytes": len(content), "name": base_name}, library_path
        )
        saved_formats.append(ext)
        format_paths[ext] = dest_path

    # Hash (device-pairing) + page count computed HERE, server-side, right
    # as each format lands on disk — same as ingest.py's local-folder import
    # already does. Before this, a book pushed by the Calibre plugin got
    # neither until the plugin's own post-batch full-LIBRARY passes
    # (recompute-hashes/recompute-pages) ran, which re-scan every book in
    # the library rather than just the one(s) just uploaded — real wasted
    # wall-clock time on every sync, which from the outside just looks like
    # a plugin stuck "waiting for the checksum".
    for fmt, path in format_paths.items():
        book_hash_service.upsert_book_hash(db, folder, book_id, fmt, path)
    if format_paths:
        page_settings = app_settings.get_page_count_settings(db)
        preferred_fmt = page_counter.pick_preferred_format(list(format_paths.keys()))
        preferred_path = format_paths[preferred_fmt]
        pages = page_counter.count_pages(
            preferred_path, preferred_fmt, page_settings["mode"], page_settings["words_per_page"], page_settings["chars_per_page"]
        )
        stats_service.registra_conteggio_testo(db, folder, book_id, preferred_path, preferred_fmt)
        if pages is not None:
            await write_queue.submit(
                "update_book", {"book_id": book_id, "fields": page_count_fields(pages)}, library_path
            )
            try:
                opf_metadata.embed_page_count(library_path, preferred_path, preferred_fmt, pages)
            except Exception as e:
                log_message("warning", "library_transfer", f"Embedding pagine nell'OPF fallito per '{preferred_path}': {e}")
    db.commit()

    fields = {"path": target_dir_rel}
    if meta.get("series_index") is not None:
        fields["series_index"] = meta["series_index"]
    if meta.get("pubdate"):
        fields["pubdate"] = meta["pubdate"]
    for label, value in (meta.get("custom_values") or {}).items():
        key = label if label.startswith("#") else f"#{label}"
        fields[key] = value
    await write_queue.submit("update_book", {"book_id": book_id, "fields": fields}, library_path)

    identifiers = meta.get("identifiers")
    if isinstance(identifiers, dict) and identifiers:
        for id_type, value in identifiers.items():
            if id_type and value:
                await write_queue.submit(
                    "set_identifier", {"book_id": book_id, "id_type": id_type, "value": value}, library_path
                )
    if meta.get("publisher"):
        await write_queue.submit("set_publisher", {"book_id": book_id, "name": meta["publisher"]}, library_path)
    if meta.get("tags"):
        await write_queue.submit("set_book_tags", {"book_id": book_id, "tags": meta["tags"]}, library_path)
    if meta.get("series"):
        await write_queue.submit(
            "set_book_series", {"book_id": book_id, "series_name": meta["series"]}, library_path
        )
    if meta.get("comments"):
        await write_queue.submit("set_comments", {"book_id": book_id, "text": meta["comments"]}, library_path)
    if meta.get("rating"):
        await write_queue.submit("set_rating", {"book_id": book_id, "stars": meta["rating"]}, library_path)
    if meta.get("language"):
        await write_queue.submit("set_language", {"book_id": book_id, "lang_code": meta["language"]}, library_path)

    if cover is not None:
        cover_bytes = await cover.read()
        if cover_bytes:
            image_b64 = base64.b64encode(cover_bytes).decode("ascii")
            await write_queue.submit("set_cover", {"book_id": book_id, "image_b64": image_b64}, library_path)

    if meta.get("calibre_annotations"):
        _apply_calibre_annotations(db, current_user.id, folder, book_id, meta["calibre_annotations"])

    author_stats_service.safe_mark_author_pages_dirty(db)
    author_ingest_hook.maybe_trigger_wiki_scrape(string_to_authors(author))
    return {"status": "ok", "book_id": book_id, "formats": saved_formats}


@router.post("/{folder}/books/{book_id}/copy-to")
async def copy_book_to_library(
    folder: str,
    book_id: int,
    payload: dict,
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    "Copia nella biblioteca" (context menu) — copies one book from `folder`
    (source) into `payload['target_folder']`, optionally deleting the
    original afterward (`payload['delete_source']`, Calibre's "elimina
    dall'origine" variant). Both libraries live on THIS server, unlike
    upload_library_book above (built for a remote Calibre Desktop plugin) —
    so this reads/writes files directly on disk instead of going through
    HTTP multipart, and reuses CalibreLibrary.list_books()'s already-joined
    identifiers/publisher/tags/series/description rather than re-querying
    each relation by hand.

    Custom column values whose label doesn't exist as a column in the target
    library are silently dropped (same behavior CalibreLibrary.update_book
    already has for any unknown "#label" key) — copying across libraries
    with different custom-column setups is expected, not an error case. This
    is also why the page-count estimate needs no separate recomputation here:
    every Kolibre-managed library always has the "pages" custom column (see
    connection.py's bootstrap_library), so it rides along with the rest of
    the "#..." fields copied below. The per-library BookHash row does NOT
    ride along that way (it's Kolibre's own app.db table, not a Calibre
    column) — computed explicitly below, same as every other book-add path.
    """
    source_path = _require_library(folder)
    target_folder = (payload.get("target_folder") or "").strip()
    if not target_folder:
        raise HTTPException(status_code=400, detail="target_folder è obbligatorio")
    if target_folder == folder:
        raise HTTPException(status_code=400, detail="La libreria di destinazione deve essere diversa dall'origine")
    target_path = _require_library(target_folder)
    delete_source = bool(payload.get("delete_source"))

    source_lib = CalibreLibrary(source_path)
    book = next((b for b in source_lib.list_books() if b["id"] == book_id), None)
    if not book:
        raise HTTPException(status_code=404, detail="Libro non trovato nella libreria di origine")

    title = book["title"]
    author = book["author"] or "Autore Sconosciuto"
    new_book_id = await write_queue.submit("insert_book", {"title": title, "author": author}, target_path)
    # Come sopra: cartella e nomi nella forma di Calibre. L'id e' quello
    # NUOVO, della biblioteca di destinazione.
    target_dir_rel = calibre_naming.percorso_per_libro(new_book_id, title, author)
    target_dir_abs = os.path.join(target_path, target_dir_rel)
    os.makedirs(target_dir_abs, exist_ok=True)
    nome_file = calibre_naming.construct_file_name(
        title, calibre_naming.autore_di_cartella(author),
        calibre_naming.lunghezza_estensione(book["formats"]),
    )

    saved_formats = []
    for fmt in book["formats"]:
        src_file = source_lib.get_format_file_path(book_id, fmt)
        if not src_file:
            continue
        base_name = nome_file
        dest_file = os.path.join(target_dir_abs, f"{base_name}.{fmt.lower()}")
        shutil.copyfile(src_file, dest_file)
        await write_queue.submit(
            "add_format",
            {"book_id": new_book_id, "fmt": fmt, "size_bytes": os.path.getsize(dest_file), "name": base_name},
            target_path,
        )
        book_hash_service.upsert_book_hash(db, target_folder, new_book_id, fmt, dest_file)
        saved_formats.append(fmt)
    db.commit()

    fields = {"path": target_dir_rel}
    if book.get("series_index") is not None:
        fields["series_index"] = book["series_index"]
    for key, value in book.items():
        if key.startswith("#"):
            fields[key] = value
    await write_queue.submit("update_book", {"book_id": new_book_id, "fields": fields}, target_path)

    if book.get("identifiers"):
        for id_type, value in book["identifiers"].items():
            await write_queue.submit(
                "set_identifier", {"book_id": new_book_id, "id_type": id_type, "value": value}, target_path
            )
    if book.get("publisher"):
        await write_queue.submit("set_publisher", {"book_id": new_book_id, "name": book["publisher"]}, target_path)
    if book.get("tags"):
        await write_queue.submit("set_book_tags", {"book_id": new_book_id, "tags": book["tags"]}, target_path)
    if book.get("series"):
        await write_queue.submit(
            "set_book_series", {"book_id": new_book_id, "series_name": book["series"]}, target_path
        )
    if book.get("description"):
        await write_queue.submit("set_comments", {"book_id": new_book_id, "text": book["description"]}, target_path)

    cover_src = book.get("cover_path")
    if cover_src and os.path.exists(cover_src):
        with open(cover_src, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("ascii")
        await write_queue.submit("set_cover", {"book_id": new_book_id, "image_b64": image_b64}, target_path)

    if delete_source:
        await write_queue.submit("delete_book", {"book_id": book_id}, source_path)
        # "Copia ed elimina l'originale" is a MOVE, so the reading history
        # moves with the book instead of being orphaned on an id that no
        # longer resolves — which is what used to happen: progress, sessions
        # and highlights stayed pinned to the source library forever, and no
        # device was ever told to drop its copy. See book_records.
        book_records.release_book(db, folder, book_id, migrate_to=(target_folder, new_book_id))
        db.commit()

    author_stats_service.safe_mark_author_pages_dirty(db)
    author_ingest_hook.maybe_trigger_wiki_scrape(string_to_authors(author))
    log_message(
        "info", "library-transfer",
        f"Copiato libro '{title}' da '{folder}' a '{target_folder}'" + (" (eliminato dall'origine)" if delete_source else ""),
    )
    return {"status": "ok", "book_id": new_book_id, "formats": saved_formats}
