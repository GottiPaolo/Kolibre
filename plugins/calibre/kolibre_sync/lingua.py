#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Kolibre's own translation layer for this plugin's user-visible text.

Deliberately NOT Qt's own translation mechanism (QTranslator/self.tr()):
that would follow Calibre's own configured UI language, which is independent
of — and may well differ from — whatever language the Kolibre SERVER/account
is set to. Every other Kolibre surface (web UI, the other two plugins)
follows the Kolibre language, so this plugin does too, via this tiny
mechanism instead.

Pure stdlib, no Qt import — this module is also reachable from __init__.py,
which (see that file's own docstring) must not import Qt directly or
transitively, since Calibre's zip plugin loader reads plugin metadata before
the GUI is necessarily ready.

Usage: from .lingua import t
       t('calibre.common.cancel')                 -- plain lookup
       t('calibre.client.contact_failed', reason=x)  -- {name} interpolation
       t('calibre.main.libraries_found', count=n)    -- plural (see below)

Keys are flat, English, dot-separated, prefixed "calibre." (this plugin's
namespace). `it` is the starting/reference language (this plugin's source
language); `en` carries the same keys.

Plural entries hold TWO forms in one catalog string, separated by " | "
(space-bar-space): "{count} libreria | {count} librerie". t() picks the
first form when count == 1, the second otherwise (0 counts as plural, same
as in ordinary speech). A non-plural entry has no " | " and is used as-is.
"""

# ── Lingua attiva ──
#
# PUNTO UNICO in cui si decide quale catalogo usare. Oggi fissato a "it" di
# proposito (valore di partenza, come richiesto) — la propagazione dal server
# (impostazione dell'account Kolibre, letta ad es. subito dopo il login in
# dialogs.py::SettingsDialog, o salvata in prefs.py) si collega QUI,
# sostituendo l'assegnazione sottostante con la lettura di quel valore.
# Nessun altro punto di questo modulo, né alcun chiamante in action.py/
# dialogs.py/main_dialog.py/client.py/workers.py/prefs.py/__init__.py, deve
# sapere come quel valore arriva: tutti passano per lingua.t().
_ACTIVE_LANG = 'it'

_it = {
    # __init__.py (metadata letta dal loader dei plugin Calibre)
    'calibre.plugin.description': (
        'Sincronizza intere librerie (libri, colonne personalizzate, indice '
        'di ricerca full-text) tra Calibre Desktop e un server Kolibre.'
    ),

    # action.py
    'calibre.action.tooltip': 'Sincronizza librerie con il server Kolibre',
    'calibre.action.menu_send_to_library': 'Invia a libreria Kolibre…',
    'calibre.action.menu_send_and_delete': 'Invia a Kolibre ed elimina da qui…',
    'calibre.send_and_delete.confirm_title': 'Invia ed elimina',
    'calibre.send_and_delete.confirm_body':
        '{count} libro verrà inviato alla biblioteca «{library}» e poi ELIMINATO da questa biblioteca Calibre.\n\n'
        'Vengono eliminati solo i libri arrivati davvero sul server: se un invio fallisce, quel libro resta qui.\n\n'
        'Procedere? | '
        '{count} libri verranno inviati alla biblioteca «{library}» e poi ELIMINATI da questa biblioteca Calibre.\n\n'
        'Vengono eliminati solo i libri arrivati davvero sul server: quelli il cui invio fallisce restano qui.\n\n'
        'Procedere?',
    'calibre.send_and_delete.deleted': 'Eliminato da Calibre: {count} libro. | Eliminati da Calibre: {count} libri.',
    'calibre.send_and_delete.delete_failed':
        'Invio riuscito, ma l\'eliminazione da Calibre non è andata a buon fine: {error}',
    'calibre.send_to_library.not_configured': 'Configura prima il plugin da Kolibre Sync → Impostazioni…',
    'calibre.send_to_library.no_selection': 'Seleziona almeno un libro.',
    'calibre.send_to_library.no_format': 'Nessuno dei libri selezionati ha un formato da inviare (solo metadati, non ancora supportato).',
    'calibre.send_to_library.duplicates_title': 'Possibili duplicati',
    'calibre.send_to_library.duplicates_body': (
        '{count} libro selezionato sembra già presente su questa libreria (titolo e autore molto simili):\n\n{names}\n\nInviare comunque? | '
        '{count} libri selezionati sembrano già presenti su questa libreria (titolo e autore molto simili):\n\n{names}\n\nInviare comunque?'
    ),
    'calibre.send_to_library.progress_title': 'Invio a Kolibre',
    'calibre.send_to_library.result': 'Completato: {uploaded} caricati, {failed} falliti su {total}.',
    'calibre.send_to_library.error': 'Errore: {message}',

    # dialogs.py — SettingsDialog
    'calibre.settings.window_title': 'Kolibre Sync — Accesso',
    'calibre.settings.label_host': 'Indirizzo IP / host:',
    'calibre.settings.label_backend_port': 'Porta backend:',
    'calibre.settings.placeholder_frontend_port': 'lascia vuoto per rilevarla automaticamente',
    'calibre.settings.label_frontend_port': 'Porta frontend:',
    'calibre.settings.frontend_hint': (
        'Usata solo da "Apri Kolibre nel browser". Se vuota, il plugin la rileva da solo '
        'chiedendola al server — imposta un valore qui solo se il rilevamento automatico '
        'porta a un indirizzo sbagliato (es. porte mappate diversamente in Docker).'
    ),
    'calibre.settings.label_username': 'Nome utente:',
    'calibre.settings.label_password': 'Password:',
    'calibre.settings.credentials_hint': (
        'Le stesse credenziali del tuo account Kolibre (quelle usate per '
        'accedere all\'interfaccia web). La password non viene salvata: '
        'solo il token di accesso ottenuto dopo il login.'
    ),
    'calibre.settings.login_button': 'Accedi',
    'calibre.settings.missing_host_port': 'Inserisci indirizzo IP e porta backend.',
    'calibre.settings.port_not_number': 'La porta deve essere un numero.',
    'calibre.settings.missing_credentials': 'Inserisci nome utente e password.',
    'calibre.settings.logging_in': 'Accesso in corso…',
    'calibre.settings.bad_credentials': 'Nome utente o password non corretti.',

    # dialogs.py — UploadOptionsDialog
    'calibre.upload.window_title': 'Carica libreria su Kolibre',
    'calibre.upload.label_library_name': 'Nome libreria sul server:',
    'calibre.upload.label_columns': 'Colonne personalizzate da includere:',
    'calibre.upload.no_custom_columns': 'Nessuna colonna personalizzata in questa libreria',
    'calibre.upload.pages_column_none': '(nessuna — usa solo la stima automatica del server)',
    'calibre.upload.label_pages_column': 'Colonna per stima pagine:',
    'calibre.upload.checkbox_no_format': 'Includi anche i libri senza file allegato (solo metadati)',
    'calibre.upload.checkbox_no_format_tooltip': (
        'Non ancora supportato: Kolibre richiede almeno un formato per ogni libro. '
        'I libri "solo metadati" di questa libreria locale vengono quindi sempre esclusi dal caricamento.'
    ),
    'calibre.upload.checkbox_fulltext': 'Includi indice di ricerca full-text esistente',
    'calibre.upload.checkbox_fulltext_tooltip': (
        'Nessun indice Kolibre (fulltext.db) trovato in questa libreria locale — '
        'il server lo ricostruirà automaticamente dopo il caricamento.'
    ),
    'calibre.upload.button': 'Carica',
    'calibre.upload.result': 'Fatto: {uploaded} caricati, {failed} falliti su {total}.',

    # dialogs.py — ProgressDialog
    'calibre.progress.starting': 'Avvio…',
    'calibre.progress.cancelling': 'Annullamento in corso…',

    # dialogs.py — SendToLibraryDialog
    'calibre.send_to_library.header': (
        'Invia {count} libro alla libreria Kolibre: | Invia {count} libri alla libreria Kolibre:'
    ),
    'calibre.send_to_library.send_button': 'Invia',
    'calibre.send_to_library.libraries_available': '{count} libreria disponibile. | {count} librerie disponibili.',
    'calibre.common.no_libraries_found': 'Nessuna libreria trovata sul server — creala prima dalla pagina web.',
    'calibre.send_to_library.contact_failed': 'Impossibile contattare il server: {message}',

    # common (riusate in più file)
    'calibre.common.cancel': 'Annulla',
    'calibre.common.not_configured': '(non configurato)',
    'calibre.common.loading_libraries': 'Caricamento elenco librerie…',
    'calibre.common.interrupted': 'Interrotto: {message}',

    # main_dialog.py — KolibreMainDialog layout
    'calibre.main.update_plugin_button': 'Aggiorna plugin',
    'calibre.main.update_plugin_tooltip': 'Scarica dal server la versione più recente di questo plugin',
    'calibre.main.settings_button': 'Impostazioni…',
    'calibre.main.libraries_label': 'Librerie sul server (Cmd/Ctrl+clic per selezionarne più di una):',
    'calibre.main.refresh_button': 'Aggiorna elenco',
    'calibre.main.download_button': 'Scarica librerie selezionate',
    'calibre.main.open_browser_button': 'Apri Kolibre nel browser',
    'calibre.main.upload_button': 'Carica una libreria locale sul server…',
    'calibre.main.server_connected': 'Server: {server}  ·  connesso come {user}',
    'calibre.main.server_disconnected': 'Server: {server}  ·  non connesso',
    'calibre.main.login_prompt': 'Accedi con le tue credenziali Kolibre per iniziare.',

    # main_dialog.py — update_plugin
    'calibre.main.update_not_configured': 'Configura prima il server e accedi.',
    'calibre.main.update_version_check_failed': 'Impossibile chiedere la versione al server:\n{error}',
    'calibre.main.update_already_current': 'Il plugin è già aggiornato (v{version}).',
    'calibre.main.update_confirm': (
        'Sul server c\'è la versione {available}, qui è installata la {installed}.\n\n'
        'Vuoi aggiornare adesso? Dopo l\'installazione Calibre va riavviata perché '
        'il plugin nuovo entri in funzione.'
    ),
    'calibre.main.update_download_failed': 'Download non riuscito:\n{error}',
    'calibre.main.update_install_failed': 'Installazione non riuscita:\n{error}',
    'calibre.main.update_done': 'Installata la versione {version}.\n\nChiudi e riapri Calibre per usarla.',

    # main_dialog.py — library list
    'calibre.main.login_via_settings_prompt': 'Accedi da "Impostazioni…" per iniziare.',
    'calibre.main.unexpected_type': 'atteso un elenco di librerie, ricevuto {type}',
    'calibre.main.unexpected_response': 'Risposta del server in un formato inatteso: {error}',
    'calibre.main.libraries_found': '{count} libreria trovata sul server. | {count} librerie trovate sul server.',
    'calibre.main.session_expired': 'Sessione scaduta o non valida: accedi di nuovo da "Impostazioni…".',
    'calibre.main.contact_failed': 'Impossibile contattare il server Kolibre: {message}',

    # main_dialog.py — download
    'calibre.main.no_library_selected': 'Seleziona prima una o più librerie dall\'elenco.',
    'calibre.main.download_summary': '{downloaded}/{total} librerie scaricate.',
    'calibre.main.choose_download_dir': 'Scegli dove creare la libreria locale "{name}"',
    'calibre.main.dir_not_empty_title': 'Cartella non vuota',
    'calibre.main.dir_not_empty_body': 'La cartella scelta non è vuota. Calibre creerà comunque una nuova libreria lì. Continuare?',
    'calibre.main.manifest_read_failed': 'Impossibile leggere la libreria "{name}" dal server: {error}',
    'calibre.main.download_progress_title': 'Download di "{name}"',
    'calibre.main.download_applying': 'Download completato — applico la libreria in Calibre…',
    'calibre.main.import_error_log': 'ERRORE durante l\'importazione in Calibre: {error}',
    'calibre.main.completed_with_errors': 'Completato con errori — vedi il log sopra.',
    'calibre.main.download_done': '{count} libro importato. | {count} libri importati.',
    'calibre.main.no_downloadable_format': 'nessun formato scaricabile',

    # main_dialog.py — upload
    'calibre.main.upload_not_configured': 'Configura prima l\'indirizzo del server.',
    'calibre.main.choose_local_library_label': 'Libreria locale da caricare sul server:',
    'calibre.main.open_local_library_failed': 'Impossibile aprire la libreria locale scelta: {error}',
    'calibre.main.empty_library_name': 'Il nome della libreria non può essere vuoto.',
    'calibre.main.no_uploadable_books': 'La libreria scelta non contiene libri con formati da caricare.',
    'calibre.main.create_library_failed': 'Impossibile creare la libreria sul server: {error}',
    'calibre.main.library_not_found_after_create': 'Libreria creata sul server ma non trovata di nuovo nell\'elenco.',
    'calibre.main.column_not_created': (
        'Colonna "{name}" non creata: {error}\n\n'
        'I valori di questa colonna NON verranno caricati per nessun libro.'
    ),
    'calibre.main.upload_progress_title': 'Caricamento di "{name}"',

    # client.py — KolibreApiError, mostrati nei dialoghi sopra
    'calibre.client.no_token': 'Il server non ha restituito un token di accesso valido.',
    'calibre.client.contact_failed': 'Impossibile contattare il server: {reason}',
    'calibre.client.unreachable_timeout': 'Server non raggiungibile (nessuna risposta entro {timeout:g}s): {error}',
    'calibre.client.read_timeout': 'Timeout o errore di rete durante la lettura della risposta: {error}',
    'calibre.client.download_timeout': 'Timeout o errore di rete durante il download: {error}',
    'calibre.client.unknown_version': 'sconosciuta',

    # prefs.py
    'calibre.prefs.default_display_name': 'Utente Kolibre',

    # workers.py — log/progress visibili nella finestra di avanzamento
    'calibre.worker.ok': 'OK  {title}',
    'calibre.worker.download_format_error': 'ERRORE  {title} [{format}]: {error}',
    'calibre.worker.download_skipped': 'SALTATO  {title}: nessun formato scaricabile',
    'calibre.worker.fulltext_label': 'Indice di ricerca full-text…',
    'calibre.worker.fulltext_ok': 'OK  Indice di ricerca full-text',
    'calibre.worker.fulltext_error': 'ERRORE  Indice full-text: {error}',
    'calibre.worker.download_cancelled': 'Download annullato dall\'utente',
    'calibre.worker.upload_error': 'ERRORE  {title}: {error}',
    'calibre.worker.upload_cancelled': 'Caricamento annullato dall\'utente',
    'calibre.worker.fulltext_reindex_label': 'Aggiornamento indice di ricerca full-text…',
    'calibre.worker.pages_override_error': 'ERRORE  Stima pagine mappata (libro #{book_id}): {error}',
}

_en = {
    # __init__.py
    'calibre.plugin.description': (
        'Syncs whole libraries (books, custom columns, full-text search '
        'index) between Calibre Desktop and a Kolibre server.'
    ),

    # action.py
    'calibre.action.tooltip': 'Sync libraries with the Kolibre server',
    'calibre.action.menu_send_to_library': 'Send to Kolibre library…',
    'calibre.action.menu_send_and_delete': 'Send to Kolibre and delete from here…',
    'calibre.send_and_delete.confirm_title': 'Send and delete',
    'calibre.send_and_delete.confirm_body':
        '{count} book will be sent to the “{library}” library and then DELETED from this Calibre library.\n\n'
        'Only books that actually reach the server are deleted: if a send fails, that book stays here.\n\n'
        'Continue? | '
        '{count} books will be sent to the “{library}” library and then DELETED from this Calibre library.\n\n'
        'Only books that actually reach the server are deleted: any whose send fails stay here.\n\n'
        'Continue?',
    'calibre.send_and_delete.deleted': 'Deleted from Calibre: {count} book. | Deleted from Calibre: {count} books.',
    'calibre.send_and_delete.delete_failed':
        'The send succeeded, but deleting from Calibre did not: {error}',
    'calibre.send_to_library.not_configured': 'First set up the plugin from Kolibre Sync → Settings…',
    'calibre.send_to_library.no_selection': 'Select at least one book.',
    'calibre.send_to_library.no_format': 'None of the selected books has a format to send (metadata-only is not yet supported).',
    'calibre.send_to_library.duplicates_title': 'Possible duplicates',
    'calibre.send_to_library.duplicates_body': (
        '{count} selected book seems to already be on this library (very similar title and author):\n\n{names}\n\nSend it anyway? | '
        '{count} selected books seem to already be on this library (very similar title and author):\n\n{names}\n\nSend them anyway?'
    ),
    'calibre.send_to_library.progress_title': 'Sending to Kolibre',
    'calibre.send_to_library.result': 'Done: {uploaded} uploaded, {failed} failed out of {total}.',
    'calibre.send_to_library.error': 'Error: {message}',

    # dialogs.py — SettingsDialog
    'calibre.settings.window_title': 'Kolibre Sync — Sign in',
    'calibre.settings.label_host': 'IP address / host:',
    'calibre.settings.label_backend_port': 'Backend port:',
    'calibre.settings.placeholder_frontend_port': 'leave blank to detect it automatically',
    'calibre.settings.label_frontend_port': 'Frontend port:',
    'calibre.settings.frontend_hint': (
        'Only used by "Open Kolibre in browser". If blank, the plugin detects it '
        'by asking the server — only set a value here if automatic detection '
        'leads to the wrong address (e.g. ports mapped differently in Docker).'
    ),
    'calibre.settings.label_username': 'Username:',
    'calibre.settings.label_password': 'Password:',
    'calibre.settings.credentials_hint': (
        'The same credentials as your Kolibre account (the ones used to '
        'sign in to the web interface). The password is never saved: '
        'only the access token obtained after login is.'
    ),
    'calibre.settings.login_button': 'Sign in',
    'calibre.settings.missing_host_port': 'Enter the IP address and the backend port.',
    'calibre.settings.port_not_number': 'The port must be a number.',
    'calibre.settings.missing_credentials': 'Enter a username and a password.',
    'calibre.settings.logging_in': 'Signing in…',
    'calibre.settings.bad_credentials': 'Wrong username or password.',

    # dialogs.py — UploadOptionsDialog
    'calibre.upload.window_title': 'Upload library to Kolibre',
    'calibre.upload.label_library_name': 'Library name on the server:',
    'calibre.upload.label_columns': 'Custom columns to include:',
    'calibre.upload.no_custom_columns': 'No custom columns in this library',
    'calibre.upload.pages_column_none': "(none — use only the server's automatic estimate)",
    'calibre.upload.label_pages_column': 'Column for page estimate:',
    'calibre.upload.checkbox_no_format': 'Also include books with no attached file (metadata only)',
    'calibre.upload.checkbox_no_format_tooltip': (
        'Not supported yet: Kolibre requires at least one format for every book. '
        '"Metadata only" books in this local library are therefore always excluded from upload.'
    ),
    'calibre.upload.checkbox_fulltext': 'Include existing full-text search index',
    'calibre.upload.checkbox_fulltext_tooltip': (
        'No Kolibre index (fulltext.db) found in this local library — '
        'the server will rebuild it automatically after the upload.'
    ),
    'calibre.upload.button': 'Upload',
    'calibre.upload.result': 'Done: {uploaded} uploaded, {failed} failed out of {total}.',

    # dialogs.py — ProgressDialog
    'calibre.progress.starting': 'Starting…',
    'calibre.progress.cancelling': 'Cancelling…',

    # dialogs.py — SendToLibraryDialog
    'calibre.send_to_library.header': (
        'Send {count} book to the Kolibre library: | Send {count} books to the Kolibre library:'
    ),
    'calibre.send_to_library.send_button': 'Send',
    'calibre.send_to_library.libraries_available': '{count} library available. | {count} libraries available.',
    'calibre.common.no_libraries_found': 'No library found on the server — create one from the web page first.',
    'calibre.send_to_library.contact_failed': 'Could not contact the server: {message}',

    # common
    'calibre.common.cancel': 'Cancel',
    'calibre.common.not_configured': '(not configured)',
    'calibre.common.loading_libraries': 'Loading library list…',
    'calibre.common.interrupted': 'Interrupted: {message}',

    # main_dialog.py — KolibreMainDialog layout
    'calibre.main.update_plugin_button': 'Update plugin',
    'calibre.main.update_plugin_tooltip': "Download the latest version of this plugin from the server",
    'calibre.main.settings_button': 'Settings…',
    'calibre.main.libraries_label': 'Libraries on the server (Cmd/Ctrl+click to select more than one):',
    'calibre.main.refresh_button': 'Refresh list',
    'calibre.main.download_button': 'Download selected libraries',
    'calibre.main.open_browser_button': 'Open Kolibre in browser',
    'calibre.main.upload_button': 'Upload a local library to the server…',
    'calibre.main.server_connected': 'Server: {server}  ·  signed in as {user}',
    'calibre.main.server_disconnected': 'Server: {server}  ·  not connected',
    'calibre.main.login_prompt': 'Sign in with your Kolibre credentials to get started.',

    # main_dialog.py — update_plugin
    'calibre.main.update_not_configured': 'First set up the server and sign in.',
    'calibre.main.update_version_check_failed': 'Could not ask the server for the version:\n{error}',
    'calibre.main.update_already_current': 'The plugin is already up to date (v{version}).',
    'calibre.main.update_confirm': (
        'The server has version {available}, {installed} is installed here.\n\n'
        'Update now? Calibre needs to be restarted after installation '
        'for the new plugin to take effect.'
    ),
    'calibre.main.update_download_failed': 'Download failed:\n{error}',
    'calibre.main.update_install_failed': 'Installation failed:\n{error}',
    'calibre.main.update_done': 'Version {version} installed.\n\nClose and reopen Calibre to use it.',

    # main_dialog.py — library list
    'calibre.main.login_via_settings_prompt': 'Sign in from "Settings…" to get started.',
    'calibre.main.unexpected_type': 'expected a list of libraries, got {type}',
    'calibre.main.unexpected_response': 'Unexpected server response format: {error}',
    'calibre.main.libraries_found': '{count} library found on the server. | {count} libraries found on the server.',
    'calibre.main.session_expired': 'Session expired or invalid: sign in again from "Settings…".',
    'calibre.main.contact_failed': 'Could not contact the Kolibre server: {message}',

    # main_dialog.py — download
    'calibre.main.no_library_selected': 'First select one or more libraries from the list.',
    'calibre.main.download_summary': '{downloaded}/{total} libraries downloaded.',
    'calibre.main.choose_download_dir': 'Choose where to create the local library "{name}"',
    'calibre.main.dir_not_empty_title': 'Folder not empty',
    'calibre.main.dir_not_empty_body': 'The chosen folder is not empty. Calibre will still create a new library there. Continue?',
    'calibre.main.manifest_read_failed': 'Could not read library "{name}" from the server: {error}',
    'calibre.main.download_progress_title': 'Downloading "{name}"',
    'calibre.main.download_applying': 'Download complete — applying the library in Calibre…',
    'calibre.main.import_error_log': 'ERROR importing into Calibre: {error}',
    'calibre.main.completed_with_errors': 'Completed with errors — see the log above.',
    'calibre.main.download_done': '{count} book imported. | {count} books imported.',
    'calibre.main.no_downloadable_format': 'no downloadable format',

    # main_dialog.py — upload
    'calibre.main.upload_not_configured': 'First set up the server address.',
    'calibre.main.choose_local_library_label': 'Local library to upload to the server:',
    'calibre.main.open_local_library_failed': 'Could not open the chosen local library: {error}',
    'calibre.main.empty_library_name': 'The library name cannot be empty.',
    'calibre.main.no_uploadable_books': 'The chosen library has no books with formats to upload.',
    'calibre.main.create_library_failed': 'Could not create the library on the server: {error}',
    'calibre.main.library_not_found_after_create': 'Library created on the server but not found again in the list.',
    'calibre.main.column_not_created': (
        'Column "{name}" not created: {error}\n\n'
        "This column's values will NOT be uploaded for any book."
    ),
    'calibre.main.upload_progress_title': 'Uploading "{name}"',

    # client.py
    'calibre.client.no_token': 'The server did not return a valid access token.',
    'calibre.client.contact_failed': 'Could not contact the server: {reason}',
    'calibre.client.unreachable_timeout': 'Server unreachable (no response within {timeout:g}s): {error}',
    'calibre.client.read_timeout': 'Timeout or network error while reading the response: {error}',
    'calibre.client.download_timeout': 'Timeout or network error during download: {error}',
    'calibre.client.unknown_version': 'unknown',

    # prefs.py
    'calibre.prefs.default_display_name': 'Kolibre user',

    # workers.py
    'calibre.worker.ok': 'OK  {title}',
    'calibre.worker.download_format_error': 'ERROR  {title} [{format}]: {error}',
    'calibre.worker.download_skipped': 'SKIPPED  {title}: no downloadable format',
    'calibre.worker.fulltext_label': 'Full-text search index…',
    'calibre.worker.fulltext_ok': 'OK  Full-text search index',
    'calibre.worker.fulltext_error': 'ERROR  Full-text index: {error}',
    'calibre.worker.download_cancelled': 'Download cancelled by the user',
    'calibre.worker.upload_error': 'ERROR  {title}: {error}',
    'calibre.worker.upload_cancelled': 'Upload cancelled by the user',
    'calibre.worker.fulltext_reindex_label': 'Updating full-text search index…',
    'calibre.worker.pages_override_error': 'ERROR  Mapped page estimate (book #{book_id}): {error}',
}

_catalogs = {'it': _it, 'en': _en}


class _SafeDict(dict):
    """Leaves an unresolved {name} placeholder visibly in place instead of
    raising KeyError — an easier bug to spot on screen than a crashed
    dialog."""

    def __missing__(self, key):
        return '{' + key + '}'


def t(key: str, **values) -> str:
    """
    Looks `key` up in the active language's catalog (falling back to `it`,
    then to the bare key itself, so a missing/mistyped key shows up as
    visibly odd text on screen rather than crashing the plugin). When the
    stored value has two forms separated by " | ", picks the first when
    values['count'] == 1, the second otherwise — then interpolates {name}
    placeholders from `values`.
    """
    catalog = _catalogs.get(_ACTIVE_LANG, _it)
    template = catalog.get(key, _it.get(key, key))

    bar = template.find(' | ')
    if bar != -1:
        singular, plural = template[:bar], template[bar + 3:]
        template = singular if values.get('count') == 1 else plural

    return template.format_map(_SafeDict(values))
