"""
Real-time filesystem watcher for the ingest/staging folder, replacing the
previous "rescan the whole folder on every GET /api/kolibre/ingest" approach.
Uses watchdog so new files are staged into IngestedBook rows as soon as they
land on disk (e.g. via a Syncthing-synced folder, scp, Finder drag-and-drop),
not only when someone happens to open the Ingest page afterwards.
"""

import os
import threading

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .. import config, models, database
from ..logging_utils import log_message
from . import metadata_parser

# Give a copy-in-progress file a moment to finish writing before we read it.
DEBOUNCE_SECONDS = 2.0


def stage_ingest_file(db, file_path: str) -> bool:
    """
    Parses a file sitting in the ingest folder and inserts an IngestedBook
    staging row for it, unless one already exists for this exact path.
    Shared by the real-time watcher below and by the plain poll-on-request
    fallback in api/ingest.py (which still matters for files already present
    before the watcher started, or if it was ever restarted mid-copy).
    Returns True if a new row was actually created.
    """
    file_path = os.path.abspath(file_path)
    if not os.path.isfile(file_path) or os.path.basename(file_path).startswith('.'):
        return False
    if db.query(models.IngestedBook).filter(models.IngestedBook.file_path == file_path).first():
        return False

    ext = os.path.splitext(file_path)[1].lower()
    filename = os.path.basename(file_path)
    meta = {"title": os.path.splitext(filename)[0], "author": None, "description": "", "tags": []}
    if ext == '.epub':
        meta = metadata_parser.parse_epub_metadata(file_path)
    elif ext == '.pdf':
        meta = metadata_parser.parse_pdf_metadata(file_path)

    item = models.IngestedBook(
        file_path=file_path,
        filename=filename,
        file_format=ext.upper().replace('.', ''),
        file_size_bytes=os.path.getsize(file_path),
        title=meta.get("title") or os.path.splitext(filename)[0],
        author=meta.get("author"),
        description=meta.get("description"),
        tags=",".join(meta.get("tags") or []),
        series=meta.get("series"),
        series_index=meta.get("series_index"),
        language=meta.get("language"),
        isbn=meta.get("isbn"),
    )
    db.add(item)
    # flush (not commit) first: cover_path names the file after the row's own
    # id, so the id needs to exist before the file is written — a plain
    # add()+commit() would still be fine for the id itself (autoincrement is
    # assigned on flush regardless), but flushing explicitly here makes that
    # ordering dependency obvious rather than incidental.
    db.flush()
    cover_bytes = meta.get("cover_bytes")
    if cover_bytes:
        os.makedirs(config.INGEST_COVERS_DIR, exist_ok=True)
        cover_ext = meta.get("cover_ext") or ".jpg"
        cover_path = os.path.join(config.INGEST_COVERS_DIR, f"{item.id}{cover_ext}")
        try:
            with open(cover_path, "wb") as f:
                f.write(cover_bytes)
            item.cover_path = cover_path
        except OSError as e:
            log_message("warning", "ingest", f"Salvataggio copertina in staging fallito per '{filename}': {e}")
    db.commit()
    return True


class _IngestEventHandler(FileSystemEventHandler):
    """
    Debounces filesystem events per-path (a file copy fires multiple
    create/modify events) before handing the path to stage_ingest_file, and
    opens its own DB session since watchdog callbacks run on their own thread,
    not on the asyncio event loop.
    """

    def __init__(self):
        self._pending_timers = {}
        self._lock = threading.Lock()

    def _schedule(self, path: str) -> None:
        with self._lock:
            existing = self._pending_timers.get(path)
            if existing:
                existing.cancel()
            timer = threading.Timer(DEBOUNCE_SECONDS, self._process, args=(path,))
            self._pending_timers[path] = timer
            timer.start()

    def _process(self, path: str) -> None:
        with self._lock:
            self._pending_timers.pop(path, None)
        db = database.SessionLocal()
        try:
            if stage_ingest_file(db, path):
                log_message("info", "ingest", f"Watcher: rilevato nuovo file in ingest '{os.path.basename(path)}'")
        finally:
            db.close()

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._schedule(event.dest_path)


_observer = None


def start_watcher() -> None:
    global _observer
    if _observer is not None:
        return
    os.makedirs(config.INGEST_DIR, exist_ok=True)
    _observer = Observer()
    _observer.schedule(_IngestEventHandler(), config.INGEST_DIR, recursive=False)
    _observer.start()
    log_message("info", "ingest", f"Watcher avviato su {config.INGEST_DIR}")


def stop_watcher() -> None:
    global _observer
    if _observer is not None:
        _observer.stop()
        _observer.join(timeout=5)
        _observer = None
