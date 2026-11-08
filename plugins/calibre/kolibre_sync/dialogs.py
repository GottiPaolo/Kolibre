#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Small, single-purpose dialogs used by the main Kolibre Sync window. Every
dialog here is a single narrow column (QVBoxLayout / QFormLayout, no
side-by-side panes) per the "minimo elegante ... sempre in verticale"
design brief.
"""

import urllib.parse

from qt.core import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, Qt, QVBoxLayout,
)

from calibre.gui2 import error_dialog

from .client import KolibreApiError, KolibreClient
from .lingua import t
from .prefs import normalize_server_url, prefs
from .workers import ListLibrariesWorker


# Splits a normalized "http://host:port" into (host, port) for the settings
# dialog's separate cells — port as '' if the URL genuinely has none (rare;
# every URL this plugin itself ever builds/bakes in always includes one).
def _split_host_port(url: str):
    if not url:
        return '', ''
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ''
    port = str(parsed.port) if parsed.port else ''
    return host, port


class SettingsDialog(QDialog):
    """Server address + login — the plugin's own config, distinct from
    Calibre's generic "Customize plugin" mechanism (see __init__.py's
    is_customizable). Kolibre's library-transfer endpoints require the same
    JWT login as the web UI, so this is a real username/password sign-in
    (verified against the server on Ok), not just a free-text label — an
    earlier version asked for "nome e cognome" instead, which made no sense
    once those endpoints actually started requiring authentication.

    IP/backend port/frontend port are three separate cells rather than one
    "indirizzo server" URL field, reported directly as much clearer to fill
    in and to spot a wrong value in (especially the frontend port, which has
    no other place in the plugin to see or change at all before this)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t('calibre.settings.window_title'))
        self.setMinimumWidth(340)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        host, backend_port = _split_host_port(prefs.get('server_url', ''))
        _, frontend_port = _split_host_port(prefs.get('frontend_url', ''))

        self.host_edit = QLineEdit(host)
        self.host_edit.setPlaceholderText('192.168.1.10')
        form.addRow(t('calibre.settings.label_host'), self.host_edit)

        self.backend_port_edit = QLineEdit(backend_port)
        self.backend_port_edit.setPlaceholderText('8081')
        form.addRow(t('calibre.settings.label_backend_port'), self.backend_port_edit)

        self.frontend_port_edit = QLineEdit(frontend_port)
        self.frontend_port_edit.setPlaceholderText(t('calibre.settings.placeholder_frontend_port'))
        form.addRow(t('calibre.settings.label_frontend_port'), self.frontend_port_edit)

        frontend_hint = QLabel(t('calibre.settings.frontend_hint'))
        frontend_hint.setWordWrap(True)
        frontend_hint.setStyleSheet('color: palette(mid); font-size: 10px;')
        layout.addWidget(frontend_hint)

        self.username_edit = QLineEdit(prefs.get('username', ''))
        form.addRow(t('calibre.settings.label_username'), self.username_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(t('calibre.settings.label_password'), self.password_edit)

        hint = QLabel(t('calibre.settings.credentials_hint'))
        hint.setWordWrap(True)
        hint.setStyleSheet('color: palette(mid); font-size: 10px;')
        layout.addWidget(hint)

        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet('color: palette(mid); font-size: 10px;')
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t('calibre.settings.login_button'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        host = self.host_edit.text().strip()
        backend_port = self.backend_port_edit.text().strip()
        frontend_port = self.frontend_port_edit.text().strip()
        username = self.username_edit.text().strip()
        password = self.password_edit.text()

        if not host or not backend_port:
            error_dialog(self, 'Kolibre Sync', t('calibre.settings.missing_host_port'), show=True)
            return
        if not backend_port.isdigit() or (frontend_port and not frontend_port.isdigit()):
            error_dialog(self, 'Kolibre Sync', t('calibre.settings.port_not_number'), show=True)
            return
        server_url = normalize_server_url(f'{host}:{backend_port}')
        frontend_url = normalize_server_url(f'{host}:{frontend_port}') if frontend_port else ''
        if not username or not password:
            error_dialog(self, 'Kolibre Sync', t('calibre.settings.missing_credentials'), show=True)
            return

        self.status_label.setText(t('calibre.settings.logging_in'))
        client = KolibreClient(server_url)
        try:
            token = client.login(username, password)
        except KolibreApiError as exc:
            self.status_label.setText('')
            message = t('calibre.settings.bad_credentials') if exc.status in (401, 400) else str(exc)
            error_dialog(self, 'Kolibre Sync', message, show=True)
            return

        prefs['server_url'] = server_url
        prefs['frontend_url'] = frontend_url
        prefs['username'] = username
        prefs['auth_token'] = token
        super().accept()


class UploadOptionsDialog(QDialog):
    """
    Opened by the "Carica libreria corrente" button. Lets the user pick a
    name for the new server-side library, which local custom columns to
    carry over, and whether to include the local Kolibre full-text index
    (only offered if one is actually present — see has_local_fulltext_db).
    """

    def __init__(self, suggested_name: str, custom_columns: list, has_local_fulltext_db: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t('calibre.upload.window_title'))
        self.setMinimumWidth(360)
        self.custom_columns = custom_columns

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit(suggested_name)
        form.addRow(t('calibre.upload.label_library_name'), self.name_edit)
        layout.addLayout(form)

        layout.addWidget(QLabel(t('calibre.upload.label_columns')))
        self.columns_list = QListWidget()
        self.columns_list.setMaximumHeight(160)
        if custom_columns:
            for col in custom_columns:
                item = QListWidgetItem(f"{col['name']}  (#{col['label']}, {col['datatype']})")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                item.setData(Qt.ItemDataRole.UserRole, col)
                self.columns_list.addItem(item)
        else:
            placeholder = QListWidgetItem(t('calibre.upload.no_custom_columns'))
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.columns_list.addItem(placeholder)
        layout.addWidget(self.columns_list)

        # Page-count estimate mapping: any existing local int custom column
        # in THIS library (e.g. one a plugin like "Count Pages" already
        # fills in) can be pushed onto the server's own auto-created
        # "pages" column, overriding its own text-based estimate.
        # Deliberately scoped to per-upload, not a persisted global pref:
        # which column (if any) holds a page count is a property of each
        # local library's own custom-column schema, not of the plugin
        # installation — the same reason "colonne personalizzate da
        # includere" above is re-picked from THIS library every time too.
        pages_form = QFormLayout()
        self.pages_column_combo = QComboBox()
        self.pages_column_combo.addItem(t('calibre.upload.pages_column_none'), '')
        for col in custom_columns:
            if col['datatype'] == 'int':
                self.pages_column_combo.addItem(f"{col['name']}  (#{col['label']})", col['label'])
        pages_form.addRow(t('calibre.upload.label_pages_column'), self.pages_column_combo)
        layout.addLayout(pages_form)

        # Calibre supports book entries with metadata but no attached format
        # ("solo metadati") — Kolibre's own data model doesn't yet (every
        # book requires at least one real file, see library_transfer.py).
        # main_dialog.py already skips such books silently before this
        # dialog even opens; this checkbox exists purely as a visible
        # promemoria of that limitation rather than a silent omission, and
        # as the natural place to lift it once Kolibre supports the case.
        self.no_format_checkbox = QCheckBox(t('calibre.upload.checkbox_no_format'))
        self.no_format_checkbox.setChecked(False)
        self.no_format_checkbox.setEnabled(False)
        self.no_format_checkbox.setToolTip(t('calibre.upload.checkbox_no_format_tooltip'))
        layout.addWidget(self.no_format_checkbox)

        self.fulltext_checkbox = QCheckBox(t('calibre.upload.checkbox_fulltext'))
        if has_local_fulltext_db:
            self.fulltext_checkbox.setChecked(True)
        else:
            self.fulltext_checkbox.setChecked(False)
            self.fulltext_checkbox.setEnabled(False)
            self.fulltext_checkbox.setToolTip(t('calibre.upload.checkbox_fulltext_tooltip'))
        layout.addWidget(self.fulltext_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t('calibre.upload.button'))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t('calibre.common.cancel'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_columns(self) -> list:
        selected = []
        for i in range(self.columns_list.count()):
            item = self.columns_list.item(i)
            col = item.data(Qt.ItemDataRole.UserRole)
            if col and item.checkState() == Qt.CheckState.Checked:
                selected.append(col)
        return selected

    def library_name(self) -> str:
        return self.name_edit.text().strip()

    def include_fulltext(self) -> bool:
        return self.fulltext_checkbox.isEnabled() and self.fulltext_checkbox.isChecked()

    def pages_column(self) -> str:
        return self.pages_column_combo.currentData() or ''

    def include_books_without_format(self) -> bool:
        # Mirrors include_fulltext's isEnabled()-gated pattern; always False
        # today since the checkbox is permanently disabled — see its tooltip.
        return self.no_format_checkbox.isEnabled() and self.no_format_checkbox.isChecked()


class ProgressDialog(QDialog):
    """Real-time progress for both download and upload — the bar and log
    are only ever updated from worker signals emitted after real work
    completes, never from a QTimer."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.setModal(True)

        layout = QVBoxLayout(self)

        # Plain default-size QLabel text read as "barely changes" over a long
        # operation (reported directly, with screenshots comparing mid- and
        # end-of-upload: the only visible difference was the bar and a small
        # counter) — bigger and bold so the current phase is unmistakable at
        # a glance, not something to read closely to notice it changed.
        self.status_label = QLabel(t('calibre.progress.starting'))
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet('font-size: 14px; font-weight: 600;')
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(180)
        layout.addWidget(self.log_view)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.rejected.connect(self._on_cancel_clicked)
        layout.addWidget(self.buttons)

        self._cancel_requested_cb = None

    def set_on_cancel(self, callback):
        self._cancel_requested_cb = callback

    def _on_cancel_clicked(self):
        if self._cancel_requested_cb:
            self._cancel_requested_cb()
        cancel_btn = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn:
            cancel_btn.setEnabled(False)
        self.status_label.setText(t('calibre.progress.cancelling'))

    def update_progress(self, done: int, total: int, message: str):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        if message:
            self.status_label.setText(f'{done}/{total} — {message}')
        else:
            self.status_label.setText(f'{done}/{total}')

    def append_log(self, line: str):
        self.log_view.appendPlainText(line)

    def set_finished(self, message: str):
        self.status_label.setText(message)
        # QDialogButtonBox.Close carries RejectRole under the hood, so simply
        # adding it would ALSO re-fire `rejected` (still wired to
        # _on_cancel_clicked) on every click, clobbering this finished
        # message with "Annullamento in corso…" and then crashing once the
        # Cancel button below is gone. Disconnect first so Close only ever
        # does the one thing it's supposed to: close the dialog.
        self.buttons.rejected.disconnect(self._on_cancel_clicked)
        cancel_btn = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn:
            self.buttons.removeButton(cancel_btn)
        close_btn = self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        close_btn.clicked.connect(self.accept)


class SendToLibraryDialog(QDialog):
    """
    Opened by the book context-menu "Invia a libreria Kolibre…" entry
    (action.py::KolibreSyncAction.send_selected_books_to_library) — picks ONE
    destination among the server's existing libraries for the currently
    selected book(s). The library list loads on a background thread
    (ListLibrariesWorker, same as the main window's own "Aggiorna elenco" —
    see its docstring for why that matters), so this dialog opens instantly
    instead of freezing Calibre while it fetches.
    """

    def __init__(self, client: KolibreClient, book_count: int, icon=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Kolibre Sync')
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        if icon is not None and not icon.isNull():
            logo_label = QLabel()
            logo_label.setPixmap(icon.pixmap(32, 32))
            header.addWidget(logo_label)
        header.addWidget(QLabel(t('calibre.send_to_library.header', count=book_count)), stretch=1)
        layout.addLayout(header)

        self.combo = QComboBox()
        self.combo.setEnabled(False)
        layout.addWidget(self.combo)

        self.status_label = QLabel(t('calibre.common.loading_libraries'))
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet('color: palette(mid); font-size: 10px;')
        layout.addWidget(self.status_label)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t('calibre.send_to_library.send_button'))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._worker = ListLibrariesWorker(client, parent=self)
        self._worker.finished_ok.connect(self._on_loaded)
        self._worker.finished_err.connect(self._on_failed)
        self._worker.start()

    def _on_loaded(self, libraries):
        for lib in libraries:
            self.combo.addItem(lib['name'], lib['folder_name'])
        if libraries:
            self.combo.setEnabled(True)
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
            self.status_label.setText(t('calibre.send_to_library.libraries_available', count=len(libraries)))
        else:
            self.status_label.setText(t('calibre.common.no_libraries_found'))

    def _on_failed(self, message, status):
        self.status_label.setText(t('calibre.send_to_library.contact_failed', message=message))

    def selected_folder(self):
        return self.combo.currentData()
