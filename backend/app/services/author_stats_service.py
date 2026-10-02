"""
Keeps the "Pagine" column on the Autori table (frontend-react's
AuthorsPage.tsx) fast: the total estimated page count per author, summed
across every book by that author in every library on the server, cached in
models.AuthorPagesCache instead of recomputed on every GET
/api/kolibre/authors — see that model's own docstring for the full
reasoning. This module's only job is to (re)compute that cache and write
it; api/authors.py just reads the cache back (falling back to a live
compute + populate on the very first request after this feature deploys,
the same fallback philosophy api/stats.py already uses for StatsCache).

safe_mark_author_pages_dirty is called right after every operation that can
change how many books (and therefore pages) an author has:
  - api/ingest.py::import_book_from_ingest (adds a book)
  - api/library_transfer.py::copy_book_to_library (adds to destination)
  - api/library_transfer.py::upload_library_book (Calibre Desktop plugin
    sync — can add new books; this one can fire hundreds of times in a row
    during a single full-library sync, which is exactly why this is a
    cheap dirty-flag write and NOT a full recompute — see
    models.AuthorPagesCache's own docstring)
  - api/books.py::delete_book (removes a book)
  - api/libraries.py::rescan_library (can add many books at once)
  - api/libraries.py::_recompute_after_import, the background follow-up to
    import_library (a newly-imported library's page counts, and therefore
    its authors' totals, aren't known until that background pass ensures
    the `pages` custom column exists and computes it — see that function's
    own docstring)
  - api/libraries.py::delete_library (removes a whole library)

main.py::lifespan calls the eager refresh_author_pages_cache once at
startup instead (a one-time cost at boot, not a hot path), so a fresh
deploy isn't stuck showing zeros until the first mutation or first page
view. Every other call site above only marks the cache dirty; the actual
recompute happens lazily, at most once, the next time
GET /api/kolibre/authors finds dirty=True (see api/authors.py::list_authors).

safe_mark_author_pages_dirty swallows any exception, so a failure in THIS
bookkeeping can never break the actual book/library operation it's
attached to — worst case the "Pagine" column is stale until the next
successful mutation, next page view, or server restart.
"""
import json
import os
from datetime import datetime

from sqlalchemy.orm import Session

from .. import config, models
from ..calibre.connection import get_connection, PAGE_COUNT_COLUMN_LABEL, DELETED_LIBRARY_MARKER
from ..logging_utils import log_message


def compute_author_total_pages(solo_libreria: str = None) -> dict:
    """
    Same per-library loop api/authors.py::list_authors already runs to
    build its book_count dict, but also joins each library's `pages`
    custom-column value table (custom_column_<id>, one row per book — see
    connection.py's _ensure_page_count_column) and SUMs it per author,
    using the identical cross-library-summing logic as book_count: an
    author can exist (under the same name) in more than one library's own
    `authors` table, and its totals across all of them are added together.

    A library whose metadata.db doesn't have the `pages` custom column yet
    (e.g. a just-imported external Calibre library the background
    recompute pass hasn't reached) simply contributes 0 pages for every
    author found there, rather than failing the whole computation.
    """
    totals: dict = {}
    if not os.path.exists(config.LIBRARIES_DIR):
        return totals

    for folder_name in os.listdir(config.LIBRARIES_DIR):
        # Con un filtro attivo si guarda una biblioteca sola: la pagina
        # Autori puo' mostrare "gli autori di questa biblioteca", e allora
        # anche le pagine devono essere quelle di quella biblioteca.
        if solo_libreria and folder_name != solo_libreria:
            continue
        library_dir = config.library_path(folder_name)
        # Una libreria cestinata ma non ancora svuotata (vedi
        # DELETED_LIBRARY_MARKER) non deve contribuire pagine ai suoi
        # autori — altrimenti un libro tecnicamente "eliminato" continua a
        # gonfiare il totale finché qualcuno non svuota il cestino.
        if os.path.exists(os.path.join(library_dir, DELETED_LIBRARY_MARKER)):
            continue
        db_path = os.path.join(library_dir, "metadata.db")
        if not os.path.exists(db_path):
            continue
        try:
            conn = get_connection(db_path)
            try:
                col = conn.execute(
                    "SELECT id FROM custom_columns WHERE label = ?", (PAGE_COUNT_COLUMN_LABEL,)
                ).fetchone()
                if not col:
                    continue
                col_id = col[0]
                rows = conn.execute(
                    "SELECT a.name AS name, SUM(cc.value) AS total_pages "
                    "FROM authors a "
                    "JOIN books_authors_link bal ON bal.author = a.id "
                    f"LEFT JOIN custom_column_{col_id} cc ON cc.book = bal.book "
                    "GROUP BY a.id"
                ).fetchall()
            finally:
                conn.close()
        except Exception as exc:
            log_message("warning", "authors", f"Calcolo pagine autori fallito per la libreria '{folder_name}': {exc}")
            continue
        for row in rows:
            totals[row["name"]] = totals.get(row["name"], 0) + (row["total_pages"] or 0)

    return totals


def refresh_author_pages_cache(db: Session) -> dict:
    """Recomputes compute_author_total_pages() (the expensive, every-library
    pass) and upserts it into the single-row models.AuthorPagesCache,
    clearing dirty. Commits. Called by api/authors.py::list_authors when the
    cache is missing or dirty, and once eagerly at startup (main.py's
    lifespan) — everywhere else, use mark_author_pages_dirty instead, which
    is the cheap O(1) write meant for mutation call sites."""
    totals = compute_author_total_pages()
    cache = db.query(models.AuthorPagesCache).first()
    if not cache:
        cache = models.AuthorPagesCache(pages_json=json.dumps(totals), dirty=False)
        db.add(cache)
    else:
        cache.pages_json = json.dumps(totals)
        cache.dirty = False
    cache.computed_at = datetime.utcnow()
    db.commit()
    return totals


def mark_author_pages_dirty(db: Session) -> None:
    """
    Cheap invalidation for the mutation call sites listed in this module's
    own docstring: just flips a boolean on the single cache row (creating a
    placeholder row if none exists yet), no library scanning. The real
    recompute is deferred to the next GET /api/kolibre/authors — see
    models.AuthorPagesCache's own docstring for why this is lazy rather
    than eager (upload_library_book's bulk-sync call pattern).
    """
    cache = db.query(models.AuthorPagesCache).first()
    if not cache:
        cache = models.AuthorPagesCache(pages_json="{}", dirty=True)
        db.add(cache)
    else:
        cache.dirty = True
    db.commit()


def safe_mark_author_pages_dirty(db: Session) -> None:
    """Same as mark_author_pages_dirty, but swallows any exception (logging
    a warning instead) — see this module's own docstring for why none of
    its call sites should ever fail or roll back because of this."""
    try:
        mark_author_pages_dirty(db)
    except Exception as exc:
        log_message("warning", "authors", f"Invalidazione cache pagine autori fallita: {exc}")
