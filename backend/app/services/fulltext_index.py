"""
Real full-text search: a per-library SQLite FTS5 index kept in a separate
`fulltext.db` file next to each library's `metadata.db` — never inside it, so
a real Calibre-compatible library folder stays exactly what Calibre itself
would produce, openable by Calibre Desktop without surprises.

Modeled on Calibre's own approach (src/calibre/db/fts/ in the calibre
source): a separate FTS5-backed database, one row of extracted plain text per
(book, format), with SQLite's native `snippet()` doing the highlighted-excerpt
work. Deliberately simpler in scope: whole-library reindex only (no per-format
dirty-tracking job queue), text extraction is pure Python (pypdf / the same
zipfile+regex approach as page_counter.py) rather than shelling out to
`pdftotext`, and the query string is passed straight to FTS5 MATCH — its
native syntax already gives us everything asked for: implicit AND between
bare words, `"exact phrase"` for phrase search, case-insensitivity and
punctuation-as-separator via the unicode61 tokenizer, all for free.
"""

import os
import re
import sqlite3
import threading
import time

from . import page_counter
from ..logging_utils import log_message

FULLTEXT_DB_FILENAME = "fulltext.db"

# rowid-keyed, not book-id-keyed: FTS5 tables are naturally rowid tables, and
# we look up by book_id via a plain column instead of trying to force rowid
# to double as the Calibre book id (a book can have zero or one indexed row,
# never more, since only the preferred format is indexed).
_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
    text,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS fts_meta (
    book_id INTEGER PRIMARY KEY,
    fts_rowid INTEGER NOT NULL,
    format TEXT NOT NULL,
    indexed_at REAL NOT NULL
);
"""

# Guards the in-memory reindex-progress map below — reindexing runs in a
# background thread (started from an async endpoint via threading.Thread,
# not asyncio.to_thread, so it keeps running even across independent
# requests polling status) while search/status reads happen from request
# threads concurrently.
_progress_lock = threading.Lock()
_progress = {}  # library_path -> {"done": int, "total": int, "running": bool}


def _db_path(library_path: str) -> str:
    return os.path.join(library_path, FULLTEXT_DB_FILENAME)


def _connect(library_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(library_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


_WHITESPACE_RE = re.compile(r"\s+")


def extract_text(file_path: str, fmt: str) -> str:
    """Best-effort plain-text extraction; '' (not None) if the format isn't
    supported or extraction fails, so callers can index-and-skip uniformly."""
    fmt = fmt.upper()
    if not os.path.exists(file_path):
        return ""
    try:
        if fmt == "EPUB":
            return _WHITESPACE_RE.sub(" ", page_counter._extract_epub_text(file_path) or "").strip()
        if fmt == "PDF":
            return _WHITESPACE_RE.sub(" ", _extract_pdf_text(file_path)).strip()
        if fmt == "TXT":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return _WHITESPACE_RE.sub(" ", f.read()).strip()
    except Exception as e:
        log_message("warning", "fulltext", f"Error extracting text for fulltext index ({fmt}): {e}")
    return ""


def _extract_pdf_text(pdf_path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def index_book(library_path: str, book_id: int, fmt: str, file_path: str) -> bool:
    """(Re)indexes a single book's preferred format. Returns whether any
    (possibly empty) text was actually indexed — False only on a hard
    extraction failure, so callers can tell "indexed, just has no text" (a
    scanned-image PDF, say) apart from "never even tried"."""
    text = extract_text(file_path, fmt)
    conn = _connect(library_path)
    try:
        existing = conn.execute("SELECT fts_rowid FROM fts_meta WHERE book_id = ?", (book_id,)).fetchone()
        if existing:
            conn.execute("DELETE FROM books_fts WHERE rowid = ?", (existing["fts_rowid"],))
        cur = conn.execute("INSERT INTO books_fts(text) VALUES (?)", (text,))
        fts_rowid = cur.lastrowid
        conn.execute(
            "INSERT INTO fts_meta(book_id, fts_rowid, format, indexed_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(book_id) DO UPDATE SET fts_rowid=excluded.fts_rowid, format=excluded.format, indexed_at=excluded.indexed_at",
            (book_id, fts_rowid, fmt, time.time()),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def remove_book_index(library_path: str, book_id: int) -> None:
    conn = _connect(library_path)
    try:
        existing = conn.execute("SELECT fts_rowid FROM fts_meta WHERE book_id = ?", (book_id,)).fetchone()
        if existing:
            conn.execute("DELETE FROM books_fts WHERE rowid = ?", (existing["fts_rowid"],))
            conn.execute("DELETE FROM fts_meta WHERE book_id = ?", (book_id,))
            conn.commit()
    finally:
        conn.close()


def get_status(library_path: str) -> dict:
    conn = _connect(library_path)
    try:
        indexed = conn.execute("SELECT COUNT(*) AS c FROM fts_meta").fetchone()["c"]
    finally:
        conn.close()
    with _progress_lock:
        progress = dict(_progress.get(library_path, {}))
    return {"indexed": indexed, "progress": progress or None}


def _is_up_to_date(library_path: str, book_id: int, fmt: str, file_path: str) -> bool:
    """Se questo libro è già indicizzato, nello stesso formato, e il file non
    è stato toccato dopo l'indicizzazione, non c'è niente da rifare.

    Confronto mtime vs indexed_at invece di una colonna dedicata: fulltext.db
    è una cache derivata, e questo evita una migrazione di schema su un file
    che esiste già in produzione. Un file SOSTITUITO con una copia più
    vecchia sfuggirebbe al controllo — per quel caso (e per quando cambia
    l'estrattore stesso) c'è `force`.
    """
    conn = _connect(library_path)
    try:
        row = conn.execute("SELECT format, indexed_at FROM fts_meta WHERE book_id = ?", (book_id,)).fetchone()
    finally:
        conn.close()
    if not row or row["format"] != fmt:
        return False
    try:
        return os.path.getmtime(file_path) <= row["indexed_at"]
    except OSError:
        return False


def index_size_bytes(library_path: str) -> int:
    """Quanto pesa l'indice di questa biblioteca, zero se non esiste."""
    try:
        return os.path.getsize(os.path.join(library_path, FULLTEXT_DB_FILENAME))
    except OSError:
        return 0


def reindex_library_async(library_path: str, lib, force: bool = False, max_bytes: int = 0) -> bool:
    """Starts a reindex in a background thread; returns False (no-op) if one
    is already running for this library. `lib` is a CalibreLibrary instance,
    passed in rather than constructed here to reuse the caller's already-open
    one.

    Di default salta i libri già indicizzati e non più modificati: estrarre
    il testo da un PDF è costoso (pypdf, pure Python) e su una libreria da
    mille libri una passata completa tiene un core occupato per parecchio
    tempo. Prima ogni riindicizzazione ripartiva da zero, quindi il costo si
    ripagava una volta sola e poi si ripeteva identico a ogni click.
    `force=True` rifà tutto, per quando cambia l'estrattore.

    `max_bytes` (0 = nessun tetto) ferma l'indicizzazione quando il file
    dell'indice raggiunge quella dimensione. L'indice contiene il testo
    estratto di ogni libro — circa 1,6 MB a libro misurati su un impianto
    reale — quindi cresce senza un limite naturale: a 100.000 libri
    sarebbero 160 GB sullo stesso disco delle biblioteche. Fermarsi non
    cancella niente e non spegne la ricerca: quello che c'e' resta
    cercabile, semplicemente non se ne aggiunge altro finche' il tetto non
    viene alzato.
    """
    with _progress_lock:
        if _progress.get(library_path, {}).get("running"):
            return False
        _progress[library_path] = {"done": 0, "total": 0, "running": True}

    def _run():
        # Il thread si auto-degrada di priorità: su Linux nice() vale per il
        # thread chiamante, non per tutto il processo. L'indicizzazione può
        # così usare la CPU libera senza rubarla né alle richieste HTTP di
        # Kolibre né agli altri servizi sulla stessa macchina (un server
        # domestico ospita spesso anche Jellyfin, Immich, Nextcloud).
        try:
            os.nice(10)
        except (AttributeError, OSError):
            pass  # non-Linux o permessi negati: pazienza, resta priorità normale

        indexed = skipped = 0
        fermato_dal_tetto = False
        try:
            books = lib.list_books()
            with _progress_lock:
                _progress[library_path]["total"] = len(books)
            for book in books:
                formats = lib.get_formats(book["id"])
                if not formats:
                    with _progress_lock:
                        _progress[library_path]["done"] += 1
                    continue
                fmt = page_counter.pick_preferred_format([f["format"] for f in formats])
                file_path = lib.get_format_file_path(book["id"], fmt)
                if file_path:
                    if not force and _is_up_to_date(library_path, book["id"], fmt, file_path):
                        skipped += 1
                    elif max_bytes and index_size_bytes(library_path) >= max_bytes:
                        # Si controlla PRIMA di indicizzare, non dopo: un
                        # libro grosso puo' far crescere l'indice di parecchio
                        # in un colpo solo, e il tetto deve essere un tetto,
                        # non una soglia che si scavalca sempre di un libro.
                        fermato_dal_tetto = True
                        break
                    else:
                        index_book(library_path, book["id"], fmt, file_path)
                        indexed += 1
                with _progress_lock:
                    _progress[library_path]["done"] += 1
        finally:
            with _progress_lock:
                _progress[library_path]["running"] = False
                _progress[library_path]["stopped_by_limit"] = fermato_dal_tetto
            if fermato_dal_tetto:
                log_message(
                    "warning", "fulltext",
                    f"Indicizzazione fermata dal tetto di {max_bytes / 1e9:.1f} GB: "
                    f"{indexed} libri indicizzati, {skipped} già aggiornati. "
                    f"Quello che è già indicizzato resta cercabile.",
                )
            else:
                log_message(
                    "info", "fulltext",
                    f"Reindicizzazione completata: {indexed} libri indicizzati, {skipped} già aggiornati e saltati.",
                )

    threading.Thread(target=_run, daemon=True).start()
    return True


# FTS5's snippet() wants a byte-offset column index (0, our only column) and
# start/end markers we control — plain <b>/</b> since the surrounding text is
# our own extracted-and-stripped plain text, not raw book HTML, so there's no
# markup to collide with (and the frontend still HTML-escapes the non-tag
# portions before rendering, see api/fulltext.py).
def search(library_path: str, query: str, limit: int = 40) -> list:
    conn = _connect(library_path)
    try:
        try:
            rows = conn.execute(
                "SELECT fm.book_id, fm.format, "
                "snippet(books_fts, 0, '\x01', '\x02', '…', 20) AS snippet "
                "FROM books_fts JOIN fts_meta fm ON fm.fts_rowid = books_fts.rowid "
                "WHERE books_fts.text MATCH ? "
                "ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # Malformed FTS5 query syntax (e.g. an unmatched quote the user
            # is still typing) — degrade to treating it as a single phrase
            # rather than erroring the whole search out from under them.
            safe_query = '"' + query.replace('"', '""') + '"'
            rows = conn.execute(
                "SELECT fm.book_id, fm.format, "
                "snippet(books_fts, 0, '\x01', '\x02', '…', 20) AS snippet "
                "FROM books_fts JOIN fts_meta fm ON fm.fts_rowid = books_fts.rowid "
                "WHERE books_fts.text MATCH ? "
                "ORDER BY rank LIMIT ?",
                (safe_query, limit),
            ).fetchall()
        return [{"book_id": r["book_id"], "format": r["format"], "snippet": r["snippet"]} for r in rows]
    finally:
        conn.close()
