#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Main Kolibre Sync window: a single narrow vertical column showing the
libraries already on the server, with a Download and an Upload action.
Opened from the toolbar/menu action registered in action.py.

## Cosa fa questo plugin, e cosa NON fa piu' (28/09/2026)

Manda libri da Calibre a Kolibre. Due modi: una libreria intera, oppure i
libri selezionati verso una libreria scelta (action.py). Piu' il percorso
inverso, scaricare una libreria del server dentro Calibre, e il bottone che
apre Kolibre nel browser.

Quello che e' stato tolto e' l'**accoppiamento**: legare una libreria locale
a una del server, ricordarsi lo stato dell'ultimo confronto, e presentare un
pannello di differenze bidirezionale da cui approvare caricamenti, download,
aggiornamenti di metadati nei due versi e cancellazioni. Erano 500 righe di
finestra, due moduli interi (`pairing_diff.py`, `pairing_store.py`), tre
dialoghi, una colonna di stato dentro Calibre e un elenco di colonne da
escludere.

Il motivo non e' che funzionasse male: e' che **Kolibre e Calibre Desktop non
co-gestiscono la stessa biblioteca**: il trasferimento e' una migrazione
one-shot, non una co-gestione. Un confronto bidirezionale e' lo strumento di due
sistemi che restano allineati nel tempo, e non e' quello che questi due sono.
Decisione del 28/09/2026: alleggerire molto il plugin.
"""

import os
import shutil
import tempfile
import webbrowser
from datetime import datetime, timezone

from qt.core import (
    QAbstractItemView, QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QSizePolicy, QVBoxLayout, Qt,
)

from calibre.ebooks.metadata import string_to_authors
from calibre.ebooks.metadata.book.base import Metadata
from calibre.gui2 import choose_dir, error_dialog, info_dialog, question_dialog
from calibre.utils.date import parse_date

from .book_snapshot import snapshot_book_for_upload
from .client import KolibreApiError, KolibreClient
from .dialogs import ProgressDialog, SettingsDialog, UploadOptionsDialog
from .lingua import t
from .prefs import display_name, is_configured, prefs
from .workers import DownloadWorker, ListLibrariesWorker, UploadWorker


def _now_iso() -> str:
    """Same format as the server's own last_modified stamps (backend/app/
    calibre/library.py::_now_iso, including the microsecond precision — see
    its docstring for why whole seconds aren't enough) — kept independent
    rather than shared across a Calibre-plugin/FastAPI-backend boundary
    that share no code."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f+00:00')

# Kept in sync by hand with backend/app/calibre/library.py's
# CUSTOM_COLUMN_SQL_TYPE — Kolibre's server only knows how to create a
# custom column value table for these datatypes, and only for non-"multiple"
# columns (is_multiple always 0 server-side). A local column outside this set
# (composite, or a tags-like is_multiple column) can't be faithfully
# represented server-side and is left out of the upload picker entirely.
SUPPORTED_CUSTOM_COLUMN_DATATYPES = {'text', 'enumeration', 'datetime', 'float', 'rating', 'int', 'bool'}


def _all_supported_local_columns(db):
    """
    Every local custom column Kolibre's server schema can faithfully
    represent (see SUPPORTED_CUSTOM_COLUMN_DATATYPES's own docstring) —
    shared by the upload dialog's column picker and the incremental
    "Rileva variazioni" sync (which has no dialog to ask the user which
    columns to include, so it always sends all of them).
    """
    return [
        {'label': meta['label'], 'name': meta['name'], 'datatype': meta['datatype'], 'display': meta.get('display') or {}}
        for _key, meta in db.field_metadata.custom_field_metadata().items()
        if meta['datatype'] in SUPPORTED_CUSTOM_COLUMN_DATATYPES and not meta.get('is_multiple')
    ]


def _ensure_local_custom_column(db, label, server_columns_by_label):
    """
    Creates a local Calibre custom column matching the server's definition
    if it doesn't exist yet — same effect as _apply_downloaded_library's own
    create-on-download step (main_dialog.py, full-library download), just
    reusable for a single column during incremental sync too, where a new
    column created on Kolibre used to stay invisible in Calibre until the
    entire library was re-downloaded from scratch.
    """
    if label in db.field_metadata.custom_field_metadata():
        return
    col = server_columns_by_label.get(label)
    if not col or col['datatype'] not in SUPPORTED_CUSTOM_COLUMN_DATATYPES:
        return
    try:
        db.create_custom_column(label, col['name'], col['datatype'], False, display=col.get('display') or {})
    except Exception:
        pass  # e.g. a race with another Calibre window creating the same column


def _ensure_server_custom_columns(client, folder_name, columns):
    """
    Mirror of _ensure_local_custom_column, other direction: creates on the
    server any LOCAL Calibre custom column not yet known there. Without
    this, update_book's server-side column lookup (library.py) silently
    drops any "#label" value it doesn't recognize — no error, the column
    just never appears, for every book, forever. upload_current_library
    already had this exact check before sending a brand-new library (see
    its own comment: "Stato Lettura... lost every book's value on a real
    push"), but the incremental "Rileva variazioni" and the temporary
    "Migra dati sync completi" paths never did — so a local column added
    AFTER a library was first paired (e.g. a "StatoLettura" column created
    later in Calibre) never reached the server even after this session's
    other fixes.

    Returns the (column, exception) pairs that failed to create — columns
    already present are skipped silently, not counted as failures.
    """
    try:
        existing_labels = {c['label'] for c in client.list_custom_columns(folder_name)}
    except KolibreApiError:
        existing_labels = set()
    failed = []
    for col in columns:
        if col['label'] in existing_labels:
            continue
        try:
            client.create_custom_column(folder_name, col['label'], col['name'], col['datatype'], col.get('display') or {})
            existing_labels.add(col['label'])
        except KolibreApiError as exc:
            failed.append((col, exc))
    return failed

KOLIBRE_FULLTEXT_DB_FILENAME = 'fulltext.db'


def _build_library_row_widget(lib: dict) -> QLabel:
    """
    One server library, rendered as a small two-line card instead of the
    single plain-text line the list used to show — name in bold on top,
    book count + full-text underneath in muted text. A QLabel with rich-text
    HTML is enough here (no click targets/child widgets needed inside the row
    itself), which keeps this a lot simpler than building a real composite
    QWidget with its own sub-layout for what's still fully static content. A
    transparent background lets QListWidget's own selection highlight show
    through underneath, exactly as if this were still plain item text.
    """
    books_count = lib.get('books_count', 0)
    badge = f"{books_count} libr{'o' if books_count == 1 else 'i'}"
    if lib.get('fulltext_enabled'):
        badge += ' · full-text'
    label = QLabel(
        f"<div style='font-weight:600;'>{lib.get('name', '?')}</div>"
        f"<div style='color:palette(mid); font-size:10px;'>{badge}</div>"
    )
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setContentsMargins(6, 4, 6, 4)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return label


class KolibreMainDialog(QDialog):
    def __init__(self, gui, icon, do_user_config):
        super().__init__(gui)
        self.gui = gui
        self.do_user_config = do_user_config
        self._worker = None
        self._list_worker = None
        self._current_client = None

        self.setWindowTitle('Kolibre Sync')
        if icon is not None:
            self.setWindowIcon(icon)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.server_label = QLabel()
        self.server_label.setWordWrap(True)
        header.addWidget(self.server_label, stretch=1)
        self.update_btn = QPushButton(t('calibre.main.update_plugin_button'))
        self.update_btn.setToolTip(t('calibre.main.update_plugin_tooltip'))
        self.update_btn.clicked.connect(self.update_plugin)
        header.addWidget(self.update_btn)
        settings_btn = QPushButton(t('calibre.main.settings_button'))
        settings_btn.clicked.connect(self.open_settings)
        header.addWidget(settings_btn)
        layout.addLayout(header)

        layout.addWidget(QLabel(t('calibre.main.libraries_label')))
        self.library_list = QListWidget()
        self.library_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.library_list)

        self.refresh_btn = QPushButton(t('calibre.main.refresh_button'))
        self.refresh_btn.clicked.connect(self.refresh_libraries)
        layout.addWidget(self.refresh_btn)

        self.download_btn = QPushButton(t('calibre.main.download_button'))
        self.download_btn.clicked.connect(self.download_selected_libraries)
        layout.addWidget(self.download_btn)

        self.navigate_btn = QPushButton(t('calibre.main.open_browser_button'))
        self.navigate_btn.clicked.connect(self.apri_kolibre_nel_browser)
        layout.addWidget(self.navigate_btn)

        layout.addSpacing(10)

        self.upload_btn = QPushButton(t('calibre.main.upload_button'))
        self.upload_btn.setDefault(True)
        self.upload_btn.clicked.connect(self.upload_current_library)
        layout.addWidget(self.upload_btn)

        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet('color: palette(mid); font-size: 10px;')
        layout.addWidget(self.status_label)

        self._refresh_server_label()
        if is_configured():
            self.refresh_libraries()
        else:
            self.open_settings(first_run=True)

    # -- config ----------------------------------------------------------

    def _refresh_server_label(self):
        if is_configured():
            self.server_label.setText(t('calibre.main.server_connected', server=prefs.get('server_url'), user=display_name()))
        else:
            self.server_label.setText(t('calibre.main.server_disconnected', server=prefs.get('server_url') or t('calibre.common.not_configured')))

    def open_settings(self, first_run: bool = False):
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh_server_label()
            self.refresh_libraries()
        elif first_run and not is_configured():
            self.status_label.setText(t('calibre.main.login_prompt'))

    def update_plugin(self):
        """
        Aggiorna QUESTO plugin scaricando dal server lo stesso zip che si
        scaricherebbe a mano dalla pagina Integrazioni, e installandolo con
        la strada che Calibre usa per se' stessa (add_plugin, la stessa di
        "Carica plugin da file").

        A differenza di KOReader e Obsidian, qui il riavvio e' obbligatorio
        e non e' una scortesia: Calibre importa il plugin come modulo
        Python all'avvio e quel modulo resta in memoria: finche' non
        riparte, il codice che gira e' ancora quello vecchio, per quanto lo
        zip su disco sia gia' quello nuovo.
        """
        client = self._client()
        if client is None:
            error_dialog(self, 'Kolibre Sync', t('calibre.main.update_not_configured'), show=True)
            return

        # La versione la dichiara la classe del plugin in __init__.py, ed e'
        # la stessa che il server legge da quel file per rispondere: due
        # letture dello stesso numero, non due numeri da tenere allineati.
        from . import KolibreSyncPlugin
        installata = '.'.join(str(n) for n in KolibreSyncPlugin.version)
        try:
            disponibile = client.plugin_version()
        except KolibreApiError as exc:
            error_dialog(self, 'Kolibre Sync', t('calibre.main.update_version_check_failed', error=exc), show=True)
            return

        if disponibile == installata:
            info_dialog(self, 'Kolibre Sync',
                        t('calibre.main.update_already_current', version=installata), show=True)
            return

        if not question_dialog(
            self, 'Kolibre Sync',
            t('calibre.main.update_confirm', available=disponibile, installed=installata),
        ):
            return

        cartella = tempfile.mkdtemp(prefix='kolibre-plugin-')
        zip_path = os.path.join(cartella, 'kolibre_sync.zip')
        try:
            client.download_plugin_zip(zip_path)
            # Import qui e non in cima: e' l'unico punto che ne ha bisogno, e
            # tenerlo locale evita di legare l'avvio del plugin a un modulo
            # della GUI di Calibre.
            from calibre.customize.ui import add_plugin
            add_plugin(zip_path)
        except KolibreApiError as exc:
            error_dialog(self, 'Kolibre Sync', t('calibre.main.update_download_failed', error=exc), show=True)
            return
        except Exception as exc:
            error_dialog(self, 'Kolibre Sync', t('calibre.main.update_install_failed', error=exc), show=True)
            return
        finally:
            shutil.rmtree(cartella, ignore_errors=True)

        info_dialog(self, 'Kolibre Sync',
                    t('calibre.main.update_done', version=disponibile), show=True)

    def _client(self):
        server_url = prefs.get('server_url', '')
        auth_token = prefs.get('auth_token', '')
        if not server_url or not auth_token:
            return None
        return KolibreClient(server_url, auth_token=auth_token)

    # -- library list ------------------------------------------------------

    def refresh_libraries(self):
        client = self._client()
        if client is None:
            self.status_label.setText(t('calibre.main.login_via_settings_prompt'))
            return
        # Runs on a background QThread — this used to be a direct, blocking
        # client.list_libraries() call right here (and even inside __init__,
        # every time the dialog opened), which froze the ENTIRE Calibre GUI
        # for as long as the request took to time out on an unreachable
        # server. That looked exactly like "Calibre è crashato", not like a
        # slow plugin — see ListLibrariesWorker's docstring.
        self.library_list.clear()
        self.status_label.setText(t('calibre.common.loading_libraries'))
        self.refresh_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self._current_client = client
        self._list_worker = ListLibrariesWorker(client, parent=self)
        self._list_worker.finished_ok.connect(self._on_libraries_loaded)
        self._list_worker.finished_err.connect(self._on_libraries_failed)
        self._list_worker.start()

    def _on_libraries_loaded(self, libraries):
        self.refresh_btn.setEnabled(True)
        self.download_btn.setEnabled(True)
        try:
            if not isinstance(libraries, list):
                raise TypeError(t('calibre.main.unexpected_type', type=type(libraries).__name__))
            # Un elenco piatto: le biblioteche non si dividono piu' in
            # "accoppiate" e "non accoppiate" perche' l'accoppiamento non
            # esiste piu'. Il plugin manda libri al server e basta — vedi la
            # nota in cima al file.
            for lib in libraries:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, lib)
                self.library_list.addItem(item)
                row_widget = _build_library_row_widget(lib)
                item.setSizeHint(row_widget.sizeHint())
                self.library_list.setItemWidget(item, row_widget)
        except (TypeError, KeyError, AttributeError) as exc:
            message = t('calibre.main.unexpected_response', error=exc)
            self.status_label.setText(message)
            error_dialog(self, 'Kolibre Sync', message, show=True)
            return
        self.status_label.setText(t('calibre.main.libraries_found', count=len(libraries)))

    def _on_libraries_failed(self, message, status):
        # A connection failure used to only ever land in the small, easily
        # missed status label at the bottom of the window — a user could
        # stare at an empty list with no obvious explanation (exactly what
        # was reported: "non riesce a caricarmi l'elenco di tutte le
        # librerie", with no further detail because nothing loud ever told
        # them why). Every failure now also gets a modal error_dialog so it
        # can't go unnoticed.
        self.refresh_btn.setEnabled(True)
        self.download_btn.setEnabled(True)
        if status == 401:
            text = t('calibre.main.session_expired')
        else:
            text = t('calibre.main.contact_failed', message=message)
        self.status_label.setText(text)
        error_dialog(self, 'Kolibre Sync', text, show=True)

    def _selected_libraries(self):
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.library_list.selectedItems()]

    def apri_kolibre_nel_browser(self):
        client = self._client()
        if client is None:
            return
        # An explicit frontend_url pref (set in Impostazioni, or baked in at
        # download time) always wins over auto-detection — some setups (e.g.
        # Docker port remapping) can't be auto-detected correctly from the
        # backend alone. Only falls through to client.frontend_url()'s own
        # bounded (REACHABILITY_TIMEOUT-capped) network call when unset; a
        # deliberate one-off button click blocking for at most a few seconds
        # is an acceptable trade-off here versus a full worker thread for a
        # single request.
        override = prefs.get('frontend_url')
        webbrowser.open(override if override else client.frontend_url())

    def _download_book_into_current_library(self, client, folder_name, sb, db, server_columns_by_label=None, excluded_columns=None):
        """One book from the server manifest -> a new book in the CURRENT
        (already open) local library. Mirrors _apply_downloaded_library's
        own add_books call, scoped to a single book instead of a whole
        freshly created library. Returns (new_local_id, real_last_modified)
        — see the note on real_last_modified below for why the caller must
        use THIS value, not a wall-clock timestamp taken before any of this
        ran."""
        tmp_dir = tempfile.mkdtemp(prefix='kolibre_sync_book_')
        try:
            format_paths = {}
            for fmt in sb.get('formats', []):
                dest = os.path.join(tmp_dir, f'content.{fmt.lower()}')
                url = f"/api/kolibre/books/{sb['id']}/download?format={fmt}&library={folder_name}"
                client.download_to_file(url, dest)
                format_paths[fmt] = dest
            if not format_paths:
                raise RuntimeError(t('calibre.main.no_downloadable_format'))

            mi = Metadata(sb.get('title') or 'Senza titolo', authors=[sb['author']] if sb.get('author') else [])
            if sb.get('tags'):
                mi.tags = sb['tags']
            if sb.get('series'):
                mi.series = sb['series']
                if sb.get('series_index') is not None:
                    mi.series_index = sb['series_index']
            if sb.get('rating'):
                # Kolibre's own scale is 0-5 stars; Calibre's native field is
                # 0-10 (see book_snapshot.py's own note on this same /2 <-> *2
                # conversion, applied in the opposite direction there).
                mi.rating = float(sb['rating']) * 2
            if sb.get('pubdate'):
                try:
                    mi.pubdate = parse_date(sb['pubdate'])
                except ValueError:
                    pass

            new_ids, _dupes = db.add_books([(mi, format_paths)])
            new_id = new_ids[0]
            for label, value in sb.items():
                if label.startswith('#') and value not in (None, '') and label[1:] not in (excluded_columns or ()):
                    _ensure_local_custom_column(db, label[1:], server_columns_by_label or {})
                    try:
                        db.set_field(label, {new_id: value})
                    except Exception:
                        pass
            if sb.get('cover_url'):
                cover_dest = os.path.join(tmp_dir, 'cover.jpg')
                try:
                    client.download_to_file(sb['cover_url'], cover_dest)
                    with open(cover_dest, 'rb') as f:
                        db.set_cover({new_id: f.read()})
                except Exception:
                    pass
            # add_books/set_field/set_cover each bump Calibre's own
            # last_modified on this row internally, AFTER the mi object
            # above was built — using that stale mi.last_modified (or a
            # wall-clock "now" captured before these calls) as the sync
            # baseline used to under-count it, so the very next diff always
            # saw the local side as "changed" even though nothing had
            # touched it since (reported directly: "ogni sync successiva
            # propone le stesse differenze"). Re-reading it fresh, now that
            # every mutation is done, is the actual fix.
            return new_id, db.get_metadata(new_id).last_modified.isoformat()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _update_local_book_metadata_only(self, local_id, sb, db, server_columns_by_label=None, excluded_columns=None) -> str:
        """
        Pannello "Aggiorna metadati localmente": il server è cambiato dal
        último sync -> aggiorna i metadati core dell'esistente libro locale,
        mantenendo il suo local_id (e quindi tutto ciò che Calibre stesso
        traccia contro di esso — cronologia di lettura, collegamenti a
        dispositivi, ecc.) intatto. Deliberatamente NON tocca mai formati o
        copertina (scelta deliberata: questo pannello è "solo metadati") — a
        differenza della vecchia versione di questa funzione, non scarica
        alcun file, quindi non serve più né `client` né `folder_name`.
        Restituisce il REALE last_modified post-scrittura — vedi la nota
        analoga in _download_book_into_current_library sul perché questo (e
        non un timestamp preso prima di set_metadata) è quello da salvare
        come nuova base di confronto per il prossimo sync.
        """
        mi = db.get_metadata(local_id)
        if sb.get('title'):
            mi.title = sb['title']
        if sb.get('author'):
            mi.authors = string_to_authors(sb['author'])
        if sb.get('tags') is not None:
            mi.tags = sb['tags'] or []
        if sb.get('comments') is not None:
            mi.comments = sb['comments']
        if sb.get('rating'):
            mi.rating = float(sb['rating']) * 2  # see the same conversion note above
        if sb.get('pubdate'):
            try:
                mi.pubdate = parse_date(sb['pubdate'])
            except ValueError:
                pass
        db.set_metadata(local_id, mi)
        for label, value in sb.items():
            if label.startswith('#') and value not in (None, '') and label[1:] not in (excluded_columns or ()):
                _ensure_local_custom_column(db, label[1:], server_columns_by_label or {})
                try:
                    db.set_field(label, {local_id: value})
                except Exception:
                    pass
        return db.get_metadata(local_id).last_modified.isoformat()

    # -- download ----------------------------------------------------------

    def download_selected_libraries(self):
        libs = self._selected_libraries()
        if not libs:
            error_dialog(self, 'Kolibre Sync', t('calibre.main.no_library_selected'), show=True)
            return
        client = self._client()
        if client is None:
            return

        # Sequential, one library at a time: each one needs its own
        # destination-folder prompt and its own call to
        # self.gui.library_moved(...), which makes that freshly-created
        # library the active one in Calibre — there is no notion of
        # "several libraries open at once" in Calibre's own GUI, so after
        # downloading N libraries the LAST one processed ends up active,
        # exactly as if the user had run "Scarica" N times in a row by hand.
        downloaded = 0
        for lib in libs:
            if self._download_one_library(client, lib):
                downloaded += 1
        if len(libs) > 1:
            self.status_label.setText(t('calibre.main.download_summary', downloaded=downloaded, total=len(libs)))

    def _download_one_library(self, client, lib) -> bool:
        """Runs the whole download+apply flow for a single server library.
        Returns True if it completed (even with some per-book errors logged),
        False if the user cancelled/skipped it (e.g. no destination chosen)."""
        dest_dir = choose_dir(
            self, 'kolibre_sync_download_dir',
            t('calibre.main.choose_download_dir', name=lib['name']),
        )
        if not dest_dir:
            return False
        if os.path.exists(dest_dir) and os.listdir(dest_dir):
            if not question_dialog(
                self, t('calibre.main.dir_not_empty_title'),
                t('calibre.main.dir_not_empty_body'),
            ):
                return False

        try:
            manifest = client.get_manifest(lib['folder_name'])
        except KolibreApiError as exc:
            error_dialog(self, 'Kolibre Sync', t('calibre.main.manifest_read_failed', name=lib['name'], error=exc), show=True)
            return False

        staging_dir = tempfile.mkdtemp(prefix='kolibre_sync_dl_')
        progress = ProgressDialog(t('calibre.main.download_progress_title', name=lib['name']), self)
        worker = DownloadWorker(client, manifest, staging_dir, parent=self)
        self._worker = worker

        worker.progress.connect(progress.update_progress)
        worker.log.connect(progress.append_log)
        progress.set_on_cancel(worker.cancel)

        result = {'ok': False}

        def on_ok(payload):
            progress.set_finished(t('calibre.main.download_applying'))
            try:
                self._apply_downloaded_library(dest_dir, manifest, payload, client, lib)
                progress.set_finished(t('calibre.main.download_done', count=len(payload['books'])))
                result['ok'] = True
            except Exception as exc:  # noqa: BLE001
                progress.append_log(t('calibre.main.import_error_log', error=exc))
                progress.set_finished(t('calibre.main.completed_with_errors'))
            finally:
                shutil.rmtree(staging_dir, ignore_errors=True)

        def on_err(message):
            progress.set_finished(t('calibre.common.interrupted', message=message))
            shutil.rmtree(staging_dir, ignore_errors=True)

        worker.finished_ok.connect(on_ok)
        worker.finished_err.connect(on_err)
        worker.start()
        progress.exec()
        return result['ok']

    def _apply_downloaded_library(self, dest_dir: str, manifest: dict, payload: dict, client=None, lib=None):
        """
        Runs on the GUI thread once the network work is done. Lets Calibre
        itself create the library structure (metadata.db, triggers, sort
        columns) via library_moved -> LibraryDatabase, exactly as "File ->
        New Library" would, then uses the real database API (db.new_api) to
        add books/custom columns rather than touching any SQL directly —
        the plugin never writes to metadata.db itself.

        """
        self.gui.library_moved(dest_dir)
        db = self.gui.current_db.new_api

        col_id_to_label = {}
        for col in manifest.get('custom_columns', []):
            if col['datatype'] not in SUPPORTED_CUSTOM_COLUMN_DATATYPES:
                continue
            try:
                db.create_custom_column(col['label'], col['name'], col['datatype'], False, display=col.get('display') or {})
                col_id_to_label[col['label']] = col['label']
            except Exception:
                pass  # column may already exist (e.g. re-download into a non-empty library)

        books_to_add = []
        for staged in payload['books']:
            mi = Metadata(staged['title'], authors=[staged['author']] if staged['author'] else [])
            if staged.get('tags'):
                mi.tags = staged['tags']
            if staged.get('series'):
                mi.series = staged['series']
                if staged.get('series_index') is not None:
                    mi.series_index = staged['series_index']
            books_to_add.append((mi, staged))

        # add_duplicates defaults to True in Cache.add_books (calibre/db/cache.py)
        # — relied on here so every input entry always gets a real book_id and
        # `new_ids` stays 1:1 positionally aligned with `books_to_add` for the
        # zip() below; passing add_duplicates=False would let create_book_entry
        # return None for a detected duplicate and silently misalign the two.
        new_ids, _dupes = db.add_books([
            (mi, {fmt: path for fmt, path in staged['format_paths'].items()})
            for mi, staged in books_to_add
        ])

        for book_id, (mi, staged) in zip(new_ids, books_to_add):
            for label, value in (staged.get('custom_values') or {}).items():
                key = label if label.startswith('#') else f'#{label}'
                if key[1:] in col_id_to_label:
                    try:
                        db.set_field(key, {book_id: value})
                    except Exception:
                        pass
            if staged.get('cover_path'):
                try:
                    with open(staged['cover_path'], 'rb') as f:
                        db.set_cover({book_id: f.read()})
                except Exception:
                    pass

        if payload.get('fulltext_path'):
            try:
                shutil.copyfile(payload['fulltext_path'], os.path.join(dest_dir, KOLIBRE_FULLTEXT_DB_FILENAME))
            except OSError:
                pass


    # -- upload --------------------------------------------------------------

    def _known_local_libraries(self):
        """
        Every local Calibre library this Calibre install actually knows
        about — not just whichever one happens to be open right now.
        Reuses Calibre's own built-in "Choose Library" action's usage-stats
        object (calibre.gui2.actions.choose_library.LibraryUsageStats,
        backed by gprefs['library_usage_stats']) — the exact same list
        behind Calibre's own File -> "Quick switch library" menu — rather
        than re-deriving it by hand. Returns [(display_label, path), ...],
        current library first, skipping any recorded location whose
        metadata.db no longer exists (moved/deleted since Calibre last
        recorded it).
        """
        from calibre.db.legacy import LibraryDatabase

        current_path = self.gui.library_path
        seen = set()
        result = []

        def add(path, label):
            if not path:
                return
            norm = os.path.normcase(os.path.abspath(path))
            if norm in seen or not LibraryDatabase.exists_at(path):
                return
            seen.add(norm)
            result.append((label, path))

        add(current_path, f"{os.path.basename(current_path.rstrip('/'))}  (corrente)")
        try:
            stats = self.gui.iactions['Choose Library'].stats
            for name, loc in stats.locations(self.gui.current_db):
                add(loc, name)
        except (KeyError, AttributeError):
            # The built-in "Choose Library" action is unexpectedly
            # unavailable — fall back to just the current library rather
            # than crashing the upload flow over a nice-to-have.
            pass
        return result

    def upload_current_library(self):
        client = self._client()
        if client is None:
            error_dialog(self, 'Kolibre Sync', t('calibre.main.upload_not_configured'), show=True)
            return

        local_library_path = self.gui.library_path
        known = self._known_local_libraries()
        if len(known) > 1:
            labels = [label for label, _path in known]
            chosen_label, ok = QInputDialog.getItem(
                self, 'Kolibre Sync', t('calibre.main.choose_local_library_label'), labels, 0, False,
            )
            if not ok:
                return
            local_library_path = next(path for label, path in known if label == chosen_label)

        is_current_library = (
            os.path.normcase(os.path.abspath(local_library_path))
            == os.path.normcase(os.path.abspath(self.gui.library_path))
        )
        secondary_db = None
        if is_current_library:
            db = self.gui.current_db.new_api
        else:
            # A non-active library: open it directly via Calibre's own db
            # API — is_second_db=True is the same flag Calibre's content
            # server uses (calibre/srv/library_broker.py) to open a library
            # other than the GUI's currently active one, and read_only=True
            # since this flow only ever reads (we snapshot metadata/format
            # paths below, never write back to the source library). This
            # never touches self.gui.library_moved, so Calibre's active
            # library is left untouched — no "switch library first" needed.
            from calibre.db.legacy import LibraryDatabase
            try:
                secondary_db = LibraryDatabase(local_library_path, is_second_db=True, read_only=True)
            except Exception as exc:  # noqa: BLE001
                error_dialog(self, 'Kolibre Sync', t('calibre.main.open_local_library_failed', error=exc), show=True)
                return
            db = secondary_db.new_api

        try:
            all_columns = _all_supported_local_columns(db)
            has_local_fulltext_db = os.path.exists(os.path.join(local_library_path, KOLIBRE_FULLTEXT_DB_FILENAME))

            # Matches the local Calibre library's own name by default — not
            # some derived "Libreria di <utente>" label, which had nothing
            # to do with how the user already knows/names this library.
            suggested_name = os.path.basename(local_library_path.rstrip('/'))
            dlg = UploadOptionsDialog(suggested_name, all_columns, has_local_fulltext_db, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

            name = dlg.library_name()
            if not name:
                error_dialog(self, 'Kolibre Sync', t('calibre.main.empty_library_name'), show=True)
                return
            selected_columns = dlg.selected_columns()
            include_fulltext = dlg.include_fulltext()
            pages_column = dlg.pages_column()

            # Snapshot every book's metadata + on-disk format paths up
            # front, on the GUI thread — the upload worker then does pure
            # network I/O, never touching any Calibre db object itself
            # (the format/cover files snapshotted here are read straight
            # off disk by the worker later; closing secondary_db below
            # doesn't affect those files, only the db connection).
            book_ids = list(db.all_book_ids())
            books = []
            for book_id in book_ids:
                book = snapshot_book_for_upload(db, book_id, selected_columns, pages_column)
                if book:
                    books.append(book)
        finally:
            if secondary_db is not None:
                secondary_db.close()

        if not books:
            error_dialog(self, 'Kolibre Sync', t('calibre.main.no_uploadable_books'), show=True)
            return

        try:
            client.create_library(name)
        except KolibreApiError as exc:
            error_dialog(self, 'Kolibre Sync', t('calibre.main.create_library_failed', error=exc), show=True)
            return

        try:
            folder_name = next(l['folder_name'] for l in client.list_libraries() if l['name'] == name)
        except (KolibreApiError, StopIteration):
            error_dialog(self, 'Kolibre Sync', t('calibre.main.library_not_found_after_create'), show=True)
            return

        # See _ensure_server_custom_columns' own docstring: without creating
        # each column on the server FIRST, update_book's server-side lookup
        # silently drops any "#label" value it doesn't recognize — no error,
        # just gone for every book. Reported directly the first time this
        # bit: "Stato Lettura" (an enum column) lost every book's value on a
        # real push.
        for col, exc in _ensure_server_custom_columns(client, folder_name, selected_columns):
            info_dialog(
                self, 'Kolibre Sync',
                t('calibre.main.column_not_created', name=col['name'], error=exc),
                show=True,
            )

        fulltext_path = None
        if include_fulltext:
            fulltext_path = os.path.join(local_library_path, KOLIBRE_FULLTEXT_DB_FILENAME)

        progress = ProgressDialog(t('calibre.main.upload_progress_title', name=name), self)
        worker = UploadWorker(client, folder_name, books, fulltext_path, parent=self)
        self._worker = worker
        worker.progress.connect(progress.update_progress)
        worker.log.connect(progress.append_log)
        progress.set_on_cancel(worker.cancel)

        def on_ok(summary):
            progress.set_finished(t('calibre.upload.result', uploaded=summary['uploaded'], failed=summary['failed'], total=summary['total']))
            self.refresh_libraries()

        def on_err(message):
            progress.set_finished(t('calibre.common.interrupted', message=message))
            self.refresh_libraries()

        worker.finished_ok.connect(on_ok)
        worker.finished_err.connect(on_err)
        worker.start()
        progress.exec()
