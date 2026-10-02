'use strict';

/**
 * Kolibre's own translation layer for this plugin's user-visible text
 * (settings tab, modals, commands, notices, AND the labels this plugin
 * itself writes into the generated highlight notes — "Evidenziazione",
 * "Nota:", the device/calibre/web source badges, the "Senza capitolo"
 * fallback heading).
 *
 * NOT Obsidian's own i18n (there isn't a stable public plugin-facing API for
 * it anyway): this follows the Kolibre SERVER/account's own language, which
 * is independent of whatever language Obsidian itself is set to — every
 * other Kolibre surface (web UI, the other two plugins) follows the Kolibre
 * language, so this plugin does too, via this tiny mechanism instead.
 *
 * Plain CommonJS, required directly from main.js (`require('./kolibre_lingua.js')`)
 * — this plugin ships as a single bundled main.js with no build step of its
 * own, so a second source file only works if main.js can `require` it
 * directly at runtime, which Obsidian's desktop (Electron/Node) plugin
 * context allows (this plugin is already `"isDesktopOnly": true`).
 *
 * Usage: const { t } = require('./kolibre_lingua.js');
 *        t('obsidian.common.cancel')                        // plain lookup
 *        t('obsidian.error.bad_credentials', { status: 401 }) // {name} interpolation
 *        t('obsidian.common.notes_count', { count: n })        // plural (see below)
 *
 * Keys are flat, English, dot-separated, prefixed "obsidian." (this plugin's
 * namespace). `IT` is the starting/reference language (this plugin's source
 * language); `EN` carries the same keys.
 *
 * Plural entries hold TWO forms in one catalog string, separated by " | "
 * (space-bar-space): "{count} nota | {count} note". t() picks the first
 * form when values.count === 1, the second otherwise (0 counts as plural,
 * same as in ordinary speech). A non-plural entry has no " | " and is used
 * as-is.
 */

// ── Lingua attiva ──
//
// PUNTO UNICO in cui si decide quale catalogo usare. Oggi fissato a "it" di
// proposito (valore di partenza, come richiesto) — la propagazione dal
// server (impostazione dell'account Kolibre, leggibile ad es. subito dopo il
// login nella scheda Impostazioni, o salvata insieme a settings.authToken in
// data.json) si collega QUI, sostituendo l'assegnazione sottostante con la
// lettura di quel valore. Nessun altro punto di questo modulo, né alcun
// chiamante in main.js, deve sapere come quel valore arriva: tutti passano
// per kolibre_lingua.t().
const ACTIVE_LANG = 'it';

const IT = {
    // ── Etichette scritte nelle note generate (non solo "chrome" del plugin:
    // questo è il testo che l'utente legge davvero, ogni volta che apre una
    // nota importata) ──
    'obsidian.template.default_header': 'Titolo: {{title}}\nAutore: {{author}}',
    'obsidian.source.device': 'Dispositivo',
    'obsidian.source.calibre': 'Calibre',
    'obsidian.source.web': 'Web',
    'obsidian.block.highlight_label': 'Evidenziazione',
    'obsidian.block.note_label': 'Nota:',
    'obsidian.block.no_chapter_heading': 'Senza capitolo',

    // ── Comandi (Command Palette) ──
    'obsidian.command.import': 'Importa evidenziazioni da Kolibre',
    'obsidian.command.reimport_all': 'Reimporta TUTTE le evidenziazioni (sovrascrive i file esistenti)',
    'obsidian.command.check_update': 'Controlla aggiornamenti del plugin',

    // ── Modale di riepilogo importazione ──
    'obsidian.import_summary.title': 'Kolibre — Importazione completata',
    'obsidian.import_summary.total': '{count} evidenziazione importata in totale. | {count} evidenziazioni importate in totale.',
    'obsidian.import_summary.new_files_heading': 'Nuovi file ({count})',
    'obsidian.import_summary.updated_files_heading': 'File aggiornati ({count})',
    'obsidian.import_summary.file_line': '{title} — {count} nota | {title} — {count} note',
    'obsidian.import_summary.file_line_added': '{title} — +{count} nota | {title} — +{count} note',
    'obsidian.import_summary.no_changes': 'Nessuna modifica ai file.',

    // ── Modale di conferma (reimportazione completa) ──
    'obsidian.reimport.title': 'Kolibre — Reimporta tutte le evidenziazioni',
    'obsidian.reimport.message': 'Ogni file di evidenziazioni nella cartella di destinazione verrà ricreato da zero con il '
        + 'formato più recente. Qualsiasi nota o modifica scritta a mano in quei file andrà persa. Procedere?',
    'obsidian.reimport.confirm_button': 'Sovrascrivi tutto',

    // ── Scheda Impostazioni ──
    'obsidian.settings.section_login': 'Accesso',
    'obsidian.settings.server_url_name': 'URL del server',
    'obsidian.settings.server_url_desc': 'Indirizzo del tuo server Kolibre, es. http://192.168.1.100:8081',
    'obsidian.settings.username_name': 'Nome utente',
    'obsidian.settings.password_name': 'Password',
    'obsidian.settings.password_desc': 'Salvata IN CHIARO in questo vault (data.json, lo stesso file del token) per '
        + 'rinnovare da sola l\'accesso quando scade, circa ogni 7 giorni. Se sincronizzi il vault — git, Obsidian Sync, '
        + 'iCloud, Dropbox — la password ci va insieme: lasciala vuota se preferisci riaccedere a mano.',
    'obsidian.settings.login_test_name': 'Accedi / Testa connessione',
    'obsidian.settings.already_logged_in': '✓ Accesso già effettuato.',
    'obsidian.settings.login_prompt': 'Accedi con le tue credenziali Kolibre per iniziare.',
    'obsidian.settings.login_in_progress': 'In corso…',
    'obsidian.settings.login_success': '✓ Accesso riuscito.',
    'obsidian.settings.section_output': 'Output',
    'obsidian.settings.output_folder_name': 'Cartella di destinazione',
    'obsidian.settings.output_folder_desc': 'Percorso relativo alla root del vault. Digita per filtrare le cartelle esistenti.',
    'obsidian.settings.filename_template_name': 'Template nome file',
    'obsidian.settings.filename_template_desc': 'Usa {{title}} e {{author}}. Es: {{title}} → "Titolo del libro.md"',
    'obsidian.settings.section_header_template': 'Intestazione nota libro',
    'obsidian.settings.header_template_desc': 'Testo inserito in cima ad ogni <em>nuovo</em> file creato. Le note esistenti non vengono modificate.<br>'
        + 'Variabili disponibili: <code>{{title}}</code>, <code>{{author}}</code>, <code>{{date}}</code>, '
        + '<code>{{year}}</code>, <code>{{filename}}</code>. Lascia vuoto per nessuna intestazione.',
    'obsidian.settings.header_template_name': 'Template intestazione',
    'obsidian.settings.section_updates': 'Aggiornamenti',
    'obsidian.settings.plugin_version_name': 'Versione del plugin',
    'obsidian.settings.plugin_version_desc': 'Installata: v{version}. Il plugin si aggiorna dal tuo server Kolibre, '
        + 'senza reinstallarlo a mano.',
    'obsidian.settings.check_update_button': 'Controlla aggiornamenti',
    'obsidian.settings.checking_updates': 'Controllo…',
    'obsidian.settings.already_latest': 'Installata: v{version}. È già l\'ultima disponibile.',
    'obsidian.settings.update_found_installing': 'Trovata la v{version}, la installo…',

    // ── Comune ──
    'obsidian.common.cancel': 'Annulla',
    'obsidian.common.close': 'Chiudi',
    'obsidian.common.login': 'Accedi',

    // ── Errori (sollevati come Error, mostrati via Notice o nella scheda Impostazioni) ──
    'obsidian.error.unreachable': 'Impossibile raggiungere {url} — {message}',
    'obsidian.error.bad_credentials': 'Nome utente o password non corretti (HTTP {status}).',
    'obsidian.error.session_expired': 'Sessione scaduta: verifica nome utente e password nelle impostazioni.',
    'obsidian.error.fetch_failed': 'Errore nel recupero delle evidenziazioni (HTTP {status}).',
    'obsidian.error.not_configured': 'Configura prima l\'indirizzo del server.',
    'obsidian.error.server_responded': 'Il server ha risposto {status}.',
    'obsidian.error.invalid_file_list': 'Il server non ha restituito un elenco di file valido.',
    'obsidian.error.file_fetch_failed': '{file}: il server ha risposto {status}.',
    'obsidian.error.incomplete_download': '{file}: scaricato incompleto ({actual} byte invece di {expected}).',
    'obsidian.error.checksum_mismatch': '{file}: il contenuto non corrisponde a quello dichiarato dal server.',

    // ── Notice (avvisi a schermo) ──
    'obsidian.notice.update_already_current': 'Kolibre: il plugin è già aggiornato (v{version}).',
    'obsidian.notice.update_installed_reloading': 'Kolibre: aggiornato alla v{version}, ricarico il plugin…',
    'obsidian.notice.reload_failed': 'Kolibre: v{version} installata, ma il ricaricamento automatico non è riuscito. '
        + 'Riavvia Obsidian per usarla.',
    'obsidian.notice.update_failed': 'Kolibre: aggiornamento non riuscito — {message}',
    'obsidian.notice.not_configured': 'Kolibre: configura il server e accedi dalle impostazioni.',
    'obsidian.notice.importing': 'Kolibre: importazione in corso…',
    'obsidian.notice.full_reimporting': 'Kolibre: reimportazione completa in corso…',
    'obsidian.notice.no_highlights_found': 'Kolibre: nessuna evidenziazione trovata.',
    'obsidian.notice.nothing_new': 'Kolibre: nessuna nuova evidenziazione da aggiungere.',
    'obsidian.notice.generic_error': 'Kolibre errore: {message}',
};

const EN = {
    'obsidian.template.default_header': 'Title: {{title}}\nAuthor: {{author}}',
    'obsidian.source.device': 'Device',
    'obsidian.source.calibre': 'Calibre',
    'obsidian.source.web': 'Web',
    'obsidian.block.highlight_label': 'Highlight',
    'obsidian.block.note_label': 'Note:',
    'obsidian.block.no_chapter_heading': 'No chapter',

    'obsidian.command.import': 'Import highlights from Kolibre',
    'obsidian.command.reimport_all': 'Reimport ALL highlights (overwrites existing files)',
    'obsidian.command.check_update': 'Check for plugin updates',

    'obsidian.import_summary.title': 'Kolibre — Import complete',
    'obsidian.import_summary.total': '{count} highlight imported in total. | {count} highlights imported in total.',
    'obsidian.import_summary.new_files_heading': 'New files ({count})',
    'obsidian.import_summary.updated_files_heading': 'Updated files ({count})',
    'obsidian.import_summary.file_line': '{title} — {count} note | {title} — {count} notes',
    'obsidian.import_summary.file_line_added': '{title} — +{count} note | {title} — +{count} notes',
    'obsidian.import_summary.no_changes': 'No changes to any file.',

    'obsidian.reimport.title': 'Kolibre — Reimport all highlights',
    'obsidian.reimport.message': 'Every highlight file in the destination folder will be rebuilt from scratch with the '
        + 'latest format. Any note or hand-written edit in those files will be lost. Proceed?',
    'obsidian.reimport.confirm_button': 'Overwrite everything',

    'obsidian.settings.section_login': 'Sign in',
    'obsidian.settings.server_url_name': 'Server URL',
    'obsidian.settings.server_url_desc': 'Address of your Kolibre server, e.g. http://192.168.1.100:8081',
    'obsidian.settings.username_name': 'Username',
    'obsidian.settings.password_name': 'Password',
    'obsidian.settings.password_desc': 'Saved IN PLAIN TEXT in this vault (data.json, the same file as the token) so it can '
        + 'renew the sign-in by itself when it expires, roughly every 7 days. If you sync your vault — git, Obsidian Sync, '
        + 'iCloud, Dropbox — the password goes with it: leave it empty if you would rather sign in by hand.',
    'obsidian.settings.login_test_name': 'Sign in / Test connection',
    'obsidian.settings.already_logged_in': '✓ Already signed in.',
    'obsidian.settings.login_prompt': 'Sign in with your Kolibre credentials to get started.',
    'obsidian.settings.login_in_progress': 'Signing in…',
    'obsidian.settings.login_success': '✓ Signed in successfully.',
    'obsidian.settings.section_output': 'Output',
    'obsidian.settings.output_folder_name': 'Destination folder',
    'obsidian.settings.output_folder_desc': 'Path relative to the vault root. Type to filter existing folders.',
    'obsidian.settings.filename_template_name': 'Filename template',
    'obsidian.settings.filename_template_desc': 'Use {{title}} and {{author}}. E.g.: {{title}} → "Book title.md"',
    'obsidian.settings.section_header_template': 'Book note header',
    'obsidian.settings.header_template_desc': 'Text inserted at the top of every <em>new</em> file created. Existing notes are never changed.<br>'
        + 'Available variables: <code>{{title}}</code>, <code>{{author}}</code>, <code>{{date}}</code>, '
        + '<code>{{year}}</code>, <code>{{filename}}</code>. Leave blank for no header.',
    'obsidian.settings.header_template_name': 'Header template',
    'obsidian.settings.section_updates': 'Updates',
    'obsidian.settings.plugin_version_name': 'Plugin version',
    'obsidian.settings.plugin_version_desc': 'Installed: v{version}. The plugin updates itself from your Kolibre server, '
        + 'with no manual reinstall.',
    'obsidian.settings.check_update_button': 'Check for updates',
    'obsidian.settings.checking_updates': 'Checking…',
    'obsidian.settings.already_latest': 'Installed: v{version}. Already the latest available.',
    'obsidian.settings.update_found_installing': 'Found v{version}, installing…',

    'obsidian.common.cancel': 'Cancel',
    'obsidian.common.close': 'Close',
    'obsidian.common.login': 'Sign in',

    'obsidian.error.unreachable': 'Could not reach {url} — {message}',
    'obsidian.error.bad_credentials': 'Wrong username or password (HTTP {status}).',
    'obsidian.error.session_expired': 'Session expired: check your username and password in the settings.',
    'obsidian.error.fetch_failed': 'Error retrieving highlights (HTTP {status}).',
    'obsidian.error.not_configured': 'First set up the server address.',
    'obsidian.error.server_responded': 'The server responded {status}.',
    'obsidian.error.invalid_file_list': 'The server did not return a valid file list.',
    'obsidian.error.file_fetch_failed': '{file}: the server responded {status}.',
    'obsidian.error.incomplete_download': '{file}: incomplete download ({actual} bytes instead of {expected}).',
    'obsidian.error.checksum_mismatch': '{file}: content does not match what the server declared.',

    'obsidian.notice.update_already_current': 'Kolibre: the plugin is already up to date (v{version}).',
    'obsidian.notice.update_installed_reloading': 'Kolibre: updated to v{version}, reloading the plugin…',
    'obsidian.notice.reload_failed': 'Kolibre: v{version} installed, but automatic reload failed. '
        + 'Restart Obsidian to use it.',
    'obsidian.notice.update_failed': 'Kolibre: update failed — {message}',
    'obsidian.notice.not_configured': 'Kolibre: set up the server and sign in from the settings.',
    'obsidian.notice.importing': 'Kolibre: import in progress…',
    'obsidian.notice.full_reimporting': 'Kolibre: full reimport in progress…',
    'obsidian.notice.no_highlights_found': 'Kolibre: no highlights found.',
    'obsidian.notice.nothing_new': 'Kolibre: no new highlights to add.',
    'obsidian.notice.generic_error': 'Kolibre error: {message}',
};

const CATALOGS = { it: IT, en: EN };

/**
 * t(key, values): looks `key` up in the active language's catalog (falling
 * back to IT, then to the bare key itself, so a missing/mistyped key shows
 * up as visibly odd text on screen rather than throwing). When the stored
 * value has two forms separated by " | ", picks the first when
 * values.count === 1, the second otherwise — then interpolates {name}
 * placeholders from `values` (if given; a key with no `values` at all, like
 * obsidian.template.default_header, is returned completely untouched — this
 * is what keeps its own {{title}}/{{author}} template syntax intact, since
 * those are a DIFFERENT, user-facing template language this plugin's own
 * applyHeaderTemplate() substitutes later, not this module's {name}
 * interpolation).
 */
function t(key, values) {
    const catalog = CATALOGS[ACTIVE_LANG] || IT;
    let template = catalog[key] !== undefined ? catalog[key] : (IT[key] !== undefined ? IT[key] : key);

    const bar = template.indexOf(' | ');
    if (bar !== -1) {
        const singular = template.slice(0, bar);
        const plural = template.slice(bar + 3);
        const count = values ? values.count : undefined;
        template = (count === 1) ? singular : plural;
    }

    if (!values) return template;
    return template.replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, (match, name) => {
        const v = values[name];
        return (v === undefined || v === null) ? match : String(v);
    });
}

module.exports = { t };
