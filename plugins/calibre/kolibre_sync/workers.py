#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Background QThreads for the download/upload flows. Deliberately do ONLY
network I/O here (via client.py) and stage results as plain files/dicts —
every actual Calibre database mutation (gui.library_moved, db.new_api.*)
happens back on the GUI thread once a worker finishes, since Calibre's own
db/GUI objects are not designed to be poked from arbitrary background
threads. This mirrors how calibre's own bulk operations (e.g.
gui2/actions/add.py) split "background fetch" from "GUI-thread apply".

Progress is real: emitted after each book actually finishes downloading or
uploading, never on a timer.
"""

import os

from qt.core import QThread, pyqtSignal

from .client import KolibreApiError
from .lingua import t


class ListLibrariesWorker(QThread):
    """
    A single request, but still run off the GUI thread: main_dialog.py used
    to call client.list_libraries() directly from KolibreMainDialog.__init__,
    which froze the whole of Calibre for as long as the request took to fail
    (up to the client's full timeout) whenever the server was slow or
    unreachable — exactly the "sembra crashato all'apertura" symptom, not a
    real crash. A fail-fast timeout in client.py bounds how long that can
    take, but the request must never block the GUI thread at all, regardless
    of how short the timeout is.
    """
    finished_ok = pyqtSignal(list)
    finished_err = pyqtSignal(str, object)   # message, KolibreApiError.status (may be None)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client

    def run(self):
        try:
            self.finished_ok.emit(self.client.list_libraries())
        except KolibreApiError as exc:
            self.finished_err.emit(str(exc), exc.status)
        except Exception as exc:  # noqa: BLE001 — surfaced, never swallowed
            self.finished_err.emit(str(exc), None)


class DownloadWorker(QThread):
    progress = pyqtSignal(int, int, str)   # done, total, current title
    log = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)          # {"books": [...], "fulltext_path": str|None}
    finished_err = pyqtSignal(str)

    def __init__(self, client, manifest: dict, staging_dir: str, parent=None):
        super().__init__(parent)
        self.client = client
        self.manifest = manifest
        self.staging_dir = staging_dir
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            folder = self.manifest['folder_name']
            books = self.manifest.get('books', [])
            total = len(books)
            # Same reasoning as UploadWorker's _POST_LOOP_STEPS: reserve a
            # slice of the bar for the fulltext step so it doesn't already
            # read 100% while that download is still running.
            has_fulltext = self.manifest.get('fulltext', {}).get('available')
            grand_total = total + (1 if has_fulltext else 0)
            staged = []
            for i, b in enumerate(books):
                if self._cancelled:
                    break
                book_dir = os.path.join(self.staging_dir, f"book_{b['id']}")
                format_paths = {}
                for fmt in b.get('formats', []):
                    dest = os.path.join(book_dir, f"content.{fmt.lower()}")
                    url = f"/api/kolibre/books/{b['id']}/download?format={fmt}&library={folder}"
                    try:
                        self.client.download_to_file(url, dest)
                        format_paths[fmt] = dest
                    except Exception as exc:  # noqa: BLE001 — one format must never abort the whole library
                        self.log.emit(t('calibre.worker.download_format_error', title=b['title'], format=fmt, error=exc))

                cover_path = None
                if b.get('cover_url'):
                    cover_dest = os.path.join(book_dir, 'cover.jpg')
                    try:
                        self.client.download_to_file(b['cover_url'], cover_dest)
                        cover_path = cover_dest
                    except Exception:  # noqa: BLE001 — a missing/slow cover shouldn't skip the book itself
                        pass

                if format_paths:
                    custom_values = {k: v for k, v in b.items() if k.startswith('#')}
                    staged.append({
                        'server_book_id': b['id'],
                        'server_last_modified': b.get('last_modified'),
                        'title': b.get('title') or 'Senza titolo',
                        'author': b.get('author') or 'Autore Sconosciuto',
                        'tags': b.get('tags') or [],
                        'series': b.get('series'),
                        'series_index': b.get('series_index'),
                        'custom_values': custom_values,
                        'format_paths': format_paths,
                        'cover_path': cover_path,
                    })
                    self.log.emit(t('calibre.worker.ok', title=b.get('title')))
                else:
                    self.log.emit(t('calibre.worker.download_skipped', title=b.get('title')))

                self.progress.emit(i + 1, grand_total, b.get('title') or '')

            fulltext_path = None
            if not self._cancelled and has_fulltext:
                self.progress.emit(total, grand_total, t('calibre.worker.fulltext_label'))
                ft_dest = os.path.join(self.staging_dir, 'fulltext.db')
                try:
                    if self.client.try_download_to_file(
                        f"/api/kolibre/library-transfer/{folder}/fulltext-db", ft_dest
                    ):
                        fulltext_path = ft_dest
                        self.log.emit(t('calibre.worker.fulltext_ok'))
                except KolibreApiError as exc:
                    self.log.emit(t('calibre.worker.fulltext_error', error=exc))

            if self._cancelled:
                self.finished_err.emit(t('calibre.worker.download_cancelled'))
            else:
                self.finished_ok.emit({'books': staged, 'fulltext_path': fulltext_path})
        except Exception as exc:  # noqa: BLE001 — surfaced to the user as-is
            self.finished_err.emit(str(exc))


class UploadWorker(QThread):
    progress = pyqtSignal(int, int, str)
    log = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)   # {"uploaded", "failed", "total", "links": [(local_id, server_id), ...]}
    finished_err = pyqtSignal(str)

    def __init__(self, client, folder_name: str, books: list, fulltext_db_path: str = None, parent=None):
        super().__init__(parent)
        self.client = client
        self.folder_name = folder_name
        self.books = books
        self.fulltext_db_path = fulltext_db_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    # After every book is uploaded, the server still does one piece of real
    # (and on a large library, slow) work with no per-book feedback of its
    # own: the full-text reindex. Reported directly: the bar reaching the
    # end right as the LAST book finishes reads as "done", while the dialog
    # then sits there for a while longer — this phase gets its own reserved
    # slice of the bar (added to the total up front) so it visibly keeps
    # moving instead of looking stuck at 100%.
    #
    # Hash + page-count used to be two MORE full-library passes here
    # (recompute_hashes/recompute_pages, both re-scanning every book in the
    # library, not just the ones just uploaded) — this was the real cause
    # behind "sending books feels slow, why does it wait on the checksum":
    # every batch, however small, paid for a full-library rescan twice at
    # the end. The server now computes both inline, per book, the moment
    # each format lands on disk (see upload_library_book in
    # backend/app/api/library_transfer.py, same pattern ingest.py's
    # local-folder import already used) — so both full-library passes are
    # gone from here entirely, not just made faster.
    _POST_LOOP_STEPS = 1

    def run(self):
        try:
            total = len(self.books)
            grand_total = total + self._POST_LOOP_STEPS
            uploaded = failed = 0
            # (server_book_id, pages_estimate) pairs to push AFTER the whole
            # batch finishes uploading. The server now writes its own
            # text-based page estimate for each book inline, during that
            # book's own upload_book call — so a value collected here would
            # get clobbered if sent before that book's upload completes.
            # Applied once, at the end, after every book has its
            # server-computed estimate already in place.
            pages_overrides = []
            # (local_book_id, server_book_id) for every successful upload —
            # lets the caller pair the local<->server library (pairing_store)
            # without a second round-trip just to look ids back up.
            uploaded_links = []
            for i, book in enumerate(self.books):
                if self._cancelled:
                    break
                self.progress.emit(i, grand_total, book['title'])
                metadata = {
                    'title': book['title'],
                    'author': book['author'],
                    'series_index': book.get('series_index'),
                    'identifiers': book.get('identifiers') or {},
                    'publisher': book.get('publisher'),
                    'tags': book.get('tags') or [],
                    'series': book.get('series'),
                    'comments': book.get('comments'),
                    'custom_values': book.get('custom_values') or {},
                    'timestamp': book.get('timestamp'),
                    'rating': book.get('rating'),
                    'pubdate': book.get('pubdate'),
                    'language': book.get('language'),
                    'calibre_annotations': book.get('calibre_annotations') or [],
                }
                try:
                    result = self.client.upload_book(
                        self.folder_name, metadata, book['format_paths'], book.get('cover_path')
                    )
                    server_book_id = result.get('book_id')
                    if book.get('pages_estimate') and server_book_id is not None:
                        pages_overrides.append((server_book_id, book['pages_estimate']))
                    if book.get('local_book_id') is not None and server_book_id is not None:
                        uploaded_links.append((book['local_book_id'], server_book_id))
                    uploaded += 1
                    self.log.emit(t('calibre.worker.ok', title=book['title']))
                except KolibreApiError as exc:
                    failed += 1
                    self.log.emit(t('calibre.worker.upload_error', title=book['title'], error=exc))
                except Exception as exc:  # noqa: BLE001
                    # Deliberately broader than KolibreApiError: a batch of
                    # a hundred-plus books must never abort entirely because
                    # ONE book hit something unexpected (a slow response
                    # timing out mid-read used to escape client.py's own
                    # wrapping and land here unwrapped — now fixed at the
                    # source too, but this loop should be resilient to any
                    # single-item failure regardless of its exact type,
                    # exactly like the per-format loop in DownloadWorker
                    # already needs to be, see the matching fix there).
                    failed += 1
                    self.log.emit(t('calibre.worker.upload_error', title=book['title'], error=exc))
                finally:
                    # db.cover(..., as_path=True) (see main_dialog.py's snapshot
                    # step) returns a PersistentTemporaryFile path that the API
                    # docs explicitly say we own and must delete ourselves.
                    cover_path = book.get('cover_path')
                    if cover_path and os.path.exists(cover_path):
                        try:
                            os.remove(cover_path)
                        except OSError:
                            pass
                self.progress.emit(i + 1, grand_total, book['title'])

            if self._cancelled:
                self.finished_err.emit(t('calibre.worker.upload_cancelled'))
                return

            self.progress.emit(total + 1, grand_total, t('calibre.worker.fulltext_reindex_label'))
            if self.fulltext_db_path:
                try:
                    self.client.upload_fulltext_db(self.folder_name, self.fulltext_db_path)
                    self.log.emit(t('calibre.worker.fulltext_ok'))
                except KolibreApiError as exc:
                    self.log.emit(t('calibre.worker.fulltext_error', error=exc))
            else:
                try:
                    self.client.reindex_fulltext(self.folder_name)
                except KolibreApiError:
                    pass

            # Not a full-library pass — a handful of targeted updates for
            # only the books that had a client-authoritative local estimate
            # (see pages_overrides' own comment above), so it doesn't get
            # its own bar slice.
            for server_book_id, pages_estimate in pages_overrides:
                try:
                    self.client.update_book(server_book_id, self.folder_name, {'#pages': pages_estimate})
                except KolibreApiError as exc:
                    self.log.emit(t('calibre.worker.pages_override_error', book_id=server_book_id, error=exc))

            self.finished_ok.emit({
                'uploaded': uploaded, 'failed': failed, 'total': total, 'links': uploaded_links,
            })
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))
