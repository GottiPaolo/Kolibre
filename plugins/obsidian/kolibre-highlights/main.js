'use strict';
// Kolibre — Obsidian plugin.
// Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
// NOTICE files in the Kolibre repository.

var obsidian = require('obsidian');
// Node, non WebCrypto: `crypto.subtle.digest` e' asincrono, e l'impronta
// serve dentro funzioni che compongono testo e devono restare sincrone
// (formatHighlightBlock e' chiamata dentro una map). Modulo di sistema,
// quindi Obsidian lo risolve — a differenza di un percorso relativo, vedi
// il commento sulla lingua qui sotto. Il plugin e' `isDesktopOnly`.
var nodeCrypto = require('crypto');
// ── Lingua ────────────────────────────────────────────────────────────────
//
// Le traduzioni di tutto il testo che questo plugin fa vedere: la scheda
// delle impostazioni, le finestre, i comandi, gli avvisi, **e le etichette
// che il plugin stesso scrive dentro le note generate** ("Evidenziazione",
// "Nota:", i marchietti della provenienza, il titolo di ripiego "Senza
// capitolo").
//
// NON e' l'i18n di Obsidian (che per i plugin non ha un'API pubblica
// stabile): segue la lingua dell'account Kolibre, che e' indipendente dalla
// lingua in cui Obsidian e' impostato — come ogni altra faccia di Kolibre
// (interfaccia web, altri due plugin).
//
// **Perche' sta qui dentro e non in un file suo.** Ci ha provato, in
// `kolibre_lingua.js`, preso con `require('./kolibre_lingua.js')`: il
// 05/11/2026 Obsidian ha rifiutato il plugin con
//
//     Plugin failure: kolibre-highlights
//     Error: Cannot find module './kolibre_lingua.js'
//     Require stack:
//     - electron/js2c/renderer_init
//
// Obsidian non carica `main.js` come lo caricherebbe Node: ne legge il testo
// dal vault e lo valuta a mano, passando alla funzione valutata un `require`
// suo. Quel modulo non ha un file di nascita, quindi `./` non parte dalla
// cartella del plugin ma dal punto da cui Electron sta valutando — ed e'
// quella la riga `electron/js2c/renderer_init` dell'errore. Un plugin con
// piu' sorgenti ha bisogno di un impacchettatore che le unisca prima
// dell'installazione; questo di proposito non ce l'ha (si installa copiando
// la cartella), quindi **la sorgente e' una sola**. Lo tiene fermo
// la prova «caricamento_come_obsidian», che carica il
// plugin imitando Obsidian invece di Node.
//
// Uso: t('obsidian.common.cancel')                          // semplice
//      t('obsidian.error.bad_credentials', { status: 401 }) // {nome} sostituito
//      t('obsidian.import_summary.total', { count: n })     // plurale (sotto)
//
// Le chiavi sono piatte, in inglese, separate da punti, con davanti
// "obsidian." (lo spazio di nomi di questo plugin). `IT` e' la lingua di
// partenza e di riferimento; `EN` porta le stesse chiavi.
//
// Una voce al plurale tiene DUE forme in una stringa sola, separate da
// " | " (spazio barra spazio): "{count} nota | {count} note". t() prende la
// prima quando values.count === 1, la seconda altrimenti (lo zero sta col
// plurale, come si parla). Una voce non plurale non ha " | " e si usa
// com'e'.

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
// L'inglese e' il predefinito e il ripiego (dal 07/10/2026): era l'italiano,
// e il catalogo inglese non lo leggeva nessuno. Resta una costante — far
// seguire la lingua di Obsidian e' un lavoro a parte, segnato nel roadmap.
const ACTIVE_LANG = 'en';

const IT = {
    // ── Etichette scritte nelle note generate (non solo "chrome" del plugin:
    // questo è il testo che l'utente legge davvero, ogni volta che apre una
    // nota importata) ──
    'obsidian.template.default_header': 'Titolo: {{title}}\nAutore: {{author}}',
    'obsidian.source.device': 'Dispositivo',
    'obsidian.source.calibre': 'Calibre',
    'obsidian.source.web': 'Web',
    'obsidian.notice.only_markers_renewed': 'Niente di nuovo. Rinnovato {count} marcatore al formato nuovo. | Niente di nuovo. Rinnovati {count} marcatori al formato nuovo.',
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
    'obsidian.import_summary.carried': 'Aggiornato {count} brano cambiato in Kolibre. | Aggiornati {count} brani cambiati in Kolibre.',
    'obsidian.import_summary.left': '{count} file non ricreato: l\u0027hai cancellato tu e non c\u0027era niente di nuovo da scriverci. | {count} file non ricreati: li hai cancellati tu e non c\u0027era niente di nuovo da scriverci.',
    'obsidian.import_summary.rebuilt_files_heading': 'Rifatti da zero ({count})',
    'obsidian.import_summary.resolved': 'Risolto {count} conflitto come avevi scelto in Kolibre. | Risolti {count} conflitti come avevi scelto in Kolibre.',
    'obsidian.import_summary.renewed': 'Rinnovato {count} marcatore al formato nuovo. | Rinnovati {count} marcatori al formato nuovo.',
    'obsidian.import_summary.blocked': '{count} libro lasciato stare, perche\u0027 bloccato da Kolibre. | {count} libri lasciati stare, perche\u0027 bloccati da Kolibre.',
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
    'obsidian.settings.password_desc': 'Serve solo adesso, per ottenere un token di accesso: NON viene salvata '
        + 'da nessuna parte. Il token non scade e lo puoi revocare quando vuoi dal portale Kolibre '
        + '(Impostazioni ▸ il tuo account).',
    'obsidian.settings.login_success_vecchio_server': '✓ Accesso riuscito, ma questo server è più vecchio e non sa '
        + 'rilasciare un token per le applicazioni: fra sette giorni dovrai riaccedere. Aggiorna Kolibre per non farlo più.',
    'obsidian.token.name': 'Obsidian',
    'obsidian.notice.password_tolta': 'Kolibre: la password non è più conservata nel vault. Ora c\'è un token che non '
        + 'scade e che puoi revocare dal portale.',
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

    // ── Quello che finisce DENTRO le note del vault ──
    //
    // Non erano nel catalogo: erano scritte nel codice, in italiano, e con il
    // plugin in inglese una nota importata portava comunque «Senza titolo» e
    // una data all'italiana. Il conteggio delle chiavi non le vedeva, perche'
    // guarda i cataloghi e non il codice (trovate il 07/11/2026, corrette
    // l'08/11).
    'obsidian.note.untitled': 'Senza titolo',
    'obsidian.note.unknown_author': 'Sconosciuto',
    'obsidian.note.default_filename': 'nota',
    // Il formato della data e' una SCELTA di lingua, quindi sta qui: e' il
    // nome del locale che `toLocaleDateString` deve usare.
    'obsidian.note.date_locale': 'it-IT',
};

const EN = {
    'obsidian.template.default_header': 'Title: {{title}}\nAuthor: {{author}}',
    'obsidian.source.device': 'Device',
    'obsidian.source.calibre': 'Calibre',
    'obsidian.source.web': 'Web',
    'obsidian.notice.only_markers_renewed': 'Nothing new. Renewed {count} marker to the new format. | Nothing new. Renewed {count} markers to the new format.',
    'obsidian.block.highlight_label': 'Highlight',
    'obsidian.block.note_label': 'Note:',
    'obsidian.block.no_chapter_heading': 'No chapter',

    'obsidian.command.import': 'Import highlights from Kolibre',
    'obsidian.command.reimport_all': 'Reimport ALL highlights (overwrites existing files)',
    'obsidian.command.check_update': 'Check for plugin updates',

    'obsidian.import_summary.title': 'Kolibre — Import complete',
    'obsidian.import_summary.total': '{count} highlight imported in total. | {count} highlights imported in total.',
    'obsidian.import_summary.carried': 'Updated {count} passage that changed in Kolibre. | Updated {count} passages that changed in Kolibre.',
    'obsidian.import_summary.left': '{count} file not recreated: you deleted it and there was nothing new to write in it. | {count} files not recreated: you deleted them and there was nothing new to write in them.',
    'obsidian.import_summary.rebuilt_files_heading': 'Rebuilt from scratch ({count})',
    'obsidian.import_summary.resolved': 'Resolved {count} conflict the way you chose in Kolibre. | Resolved {count} conflicts the way you chose in Kolibre.',
    'obsidian.import_summary.renewed': 'Renewed {count} marker to the new format. | Renewed {count} markers to the new format.',
    'obsidian.import_summary.blocked': 'Left {count} book alone, blocked from Kolibre. | Left {count} books alone, blocked from Kolibre.',
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
    'obsidian.settings.password_desc': 'Only needed right now, to obtain an access token: it is NOT saved anywhere. '
        + 'The token never expires and you can revoke it whenever you like from the Kolibre web app '
        + '(Settings ▸ your account).',
    'obsidian.settings.login_success_vecchio_server': '✓ Signed in, but this server is older and cannot issue an '
        + 'application token: in seven days you will have to sign in again. Update Kolibre to stop that happening.',
    'obsidian.token.name': 'Obsidian',
    'obsidian.notice.password_tolta': 'Kolibre: your password is no longer kept in the vault. There is now a token '
        + 'that never expires and that you can revoke from the web app.',
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

    // ── What ends up INSIDE the vault's notes ──
    // See the Italian catalog for why these are here and not in the code.
    'obsidian.note.untitled': 'Untitled',
    'obsidian.note.unknown_author': 'Unknown',
    'obsidian.note.default_filename': 'note',
    // Day-first, like the Italian one: these dates sit next to a page number
    // in a line of prose, and an unambiguous order reads better there than
    // the American convention.
    'obsidian.note.date_locale': 'en-GB',
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
    const catalog = CATALOGS[ACTIVE_LANG] || EN;
    let template = catalog[key] !== undefined ? catalog[key] : (EN[key] !== undefined ? EN[key] : key);

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

// ── Constants ─────────────────────────────────────────────────────────────

// Il separatore dei livelli di un capitolo. **E' la convenzione di Kolibre,
// non il formato di un lettore**: la compone il server quando risolve
// l'antenatura di una nota sincronizzata aprendo l'EPUB
// (`chapter_resolver.py`), e il lettore web quando si evidenzia nel browser.
// KOReader di suo manda solo il titolo del capitolo piu' interno — che qui
// diventa un percorso di un livello, cioe' esattamente quello che e'.
//
// **Qui serve per due cose sole**, da quando i livelli arrivano gia'
// separati dal server (05/11/2026): ricomporre una chiave di
// raggruppamento, e il ripiego per un server piu' vecchio di questo plugin
// (vedi `livelliDelCapitolo`). Scioglierli e risolverli — togliere il
// titolo del libro messo come radice, far ereditare gli antenati a un
// percorso nudo — era un centinaio di righe qui dentro, e adesso e' in
// `backend/app/services/capitoli_delle_note.py`: un posto dove si puo'
// provare quello che fa, cosa impossibile dentro Obsidian.
const SEPARATOR = ' ▸ ';

// Il numero di pagina scritto dentro un blocco: serve per rimettere una
// nota nuova al suo posto fra quelle che ci sono gia'.
const PAGE_IN_BLOCK_RE = /📄\s*p\.(\d+)/;

const DEFAULT_BOOK_HEADER = t('obsidian.template.default_header');

const DEFAULT_SETTINGS = {
    serverUrl: 'http://localhost:8081',
    username: '',
    // **La password NON si salva piu'** (05/11/2026). Fino a ieri stava qui,
    // nel `data.json` del plugin — cioè dentro il vault, la cartella che la
    // gente sincronizza fra computer e a volte mette in un repository git.
    // Non era una svista: serviva a rinnovare da sé l'accesso quando il
    // token di sessione scadeva dopo sette giorni («ogni tanto mi salta la
    // connessione e devo riaccedere», difetto riscontrato in uso).
    //
    // Adesso l'accesso si fa una volta e in cambio si riceve un **token per
    // l'applicazione** (`kolibre_app_…`), che non scade e si può revocare dal
    // portale. La password serve solo nel momento in cui lo si chiede, e non
    // viene scritta da nessuna parte.
    authToken: '',
    outputFolder: 'Libri',
    filenameTemplate: '{{title}}',
    bookHeaderTemplate: DEFAULT_BOOK_HEADER,
};

// ── Utility ───────────────────────────────────────────────────────────────

function sanitizeFilename(name) {
    return name.replace(/[/\\:*?"<>|#[\]^]/g, '_').trim().slice(0, 200);
}

function applyFilenameTemplate(template, book) {
    return sanitizeFilename(
        template
            .replace(/\{\{\s*title\s*\}\}/gi, book.title || t('obsidian.note.untitled'))
            .replace(/\{\{\s*authors?\s*\}\}/gi, book.author || t('obsidian.note.unknown_author'))
            .trim()
    );
}

/**
 * Apply the book header template, replacing all supported variables.
 * Supported: {{title}}, {{author}}, {{date}}, {{year}}, {{filename}}.
 */
function applyHeaderTemplate(template, bookData, filenameBase) {
    const today = new Date().toLocaleDateString(t('obsidian.note.date_locale'), {
        day: '2-digit', month: '2-digit', year: 'numeric',
    });
    const year = String(new Date().getFullYear());
    return template
        .replace(/\{\{\s*title\s*\}\}/gi, bookData.title || t('obsidian.note.untitled'))
        .replace(/\{\{\s*authors?\s*\}\}/gi, bookData.author || t('obsidian.note.unknown_author'))
        .replace(/\{\{\s*date\s*\}\}/gi, today)
        .replace(/\{\{\s*year\s*\}\}/gi, year)
        .replace(/\{\{\s*filename\s*\}\}/gi, filenameBase || sanitizeFilename(bookData.title || t('obsidian.note.default_filename')));
}

/**
 * I livelli del capitolo di un'evidenziazione, come titoli annidati.
 *
 * Li manda il server, gia' separati e risolti: `chapter_path`. Il server e'
 * il solo posto che puo' farlo bene, perche' risolvere un percorso "nudo"
 * (un livello solo, che deve ereditare i suoi antenati dalla nota che lo
 * precede nel libro) richiede di avere sotto gli occhi TUTTE le
 * evidenziazioni di quel libro in ordine di pagina — e il server le ha
 * sempre, anche quando qui ne arriva una sola. Il perche' e i casi veri
 * stanno in `backend/app/services/capitoli_delle_note.py`.
 *
 * Il ripiego serve per un server piu' vecchio di questo plugin: si scioglie
 * la stringa e basta. Si perdono l'eredita' degli antenati e la rimozione
 * del titolo del libro — la nota viene meno ordinata, non sbagliata — e non
 * si rifa' quel lavoro qui, perche' riscriverlo vorrebbe dire ritrovarsi
 * esattamente con le due copie che si sono appena unite.
 */
function livelliDelCapitolo(hl) {
    if (Array.isArray(hl.chapter_path)) return hl.chapter_path;
    if (!hl.chapter) return [];
    return hl.chapter.split(SEPARATOR).map(s => s.trim()).filter(Boolean);
}

// ── Identita', impronta, confine ──────────────────────────────────────────
//
// **Il marcatore e' un confine, e porta due cose.** In fondo alla parte di
// un blocco scritta da Kolibre sta una riga come
//
//     <!-- kolibre-hl id:n7k2p4m9qt base:6b2138ef69352299 -->
//
// e vuol dire: sopra di me scrive Kolibre, **sotto scrivi tu e io non
// leggo nemmeno**. Il caso piu' frequente — «ho aggiunto un link mio, un
// pensiero, un'ancora» — smette di essere un conflitto, perche' sta sotto
// il confine.
//
// `id:` e' il **nome durevole** della nota (dieci caratteri, vedi
// `backend/app/services/identita_durevole.py`). Prima qui stava il numero
// di riga del database, che si muove: una nota orfana promossa cambia
// numero, due note che si riaccoppiano ne perdono uno, e **un numero
// liberato da una cancellazione viene riusato da SQLite** — cioe' il
// marcatore avrebbe finito per indicare una nota completamente diversa.
// Misurato, non temuto.
//
// `base:` e' l'impronta del brano **come Kolibre l'ha scritto l'ultima
// volta**. E' la terza voce del confronto a tre vie: dalla base, da com'e'
// il brano adesso nel file e da com'e' adesso sul server escono quattro
// casi, e tre si risolvono da se'. Solo «cambiato da tutte due le parti»
// e' un conflitto vero, e lo decidi tu dalla pagina di Kolibre.
//
// L'altra meta' di questo confronto e' in Python
// (`services/appunti_nel_vault.impronta_del_brano`): **le due devono
// normalizzare allo stesso modo**, altrimenti ogni blocco sembrerebbe
// modificato. Gli spazi di qualunque tipo diventano uno spazio solo, si
// tolgono quelli ai bordi, e **non si tocca nient'altro** — una correzione
// di refuso dentro una citazione deve risultare una modifica, perche' lo
// e'. La prova «struttura_delle_note» fissa le stesse coppie (testo,
// impronta) che fissa la prova Python: e' il modo di controllare che le due
// parti si capiscano.
// Il nome accetta lettere, cifre, `_` e `-` e non solo cifre: oltre ai nomi
// durevoli ci passano gli id di ripiego dei libri non accoppiati, che
// arrivano dal server come "orphan-12" (vedi export_annotations). Con `\d+`
// qui il plugin li SCRIVEVA e poi non li RILEGGEVA, e ogni sincronizzazione
// riaggiungeva le stesse note in coda, all'infinito: difetto vero, costato
// un vault pieno di duplicati.
const MARCATORE = /<!--\s*kolibre-hl\s+id:([A-Za-z0-9_-]+)(?:\s+base:([0-9a-f]{16}))?\s*-->/;

// Il marcatore delle versioni fino alla 1.3.1: solo il numero, e attaccato
// ai due punti (`kolibre-hl:7`), cosi' i due non si confondono mai. Si
// legge ancora, e si **riscrive** nel formato nuovo appena si sa a quale
// nome durevole corrisponde quel numero — vedi rinnovaIMarcatori. Senza
// quella riscrittura ogni nota gia' importata sarebbe stata riaggiunta in
// coda al file, cioe' un duplicato per ogni nota del vault.
const MARCATORE_VECCHIO = /<!--\s*kolibre-hl:([A-Za-z0-9_-]+)\s*-->/;

// La riga di metadati di un blocco: comincia con `*` e contiene la data.
// Serve per sapere dove comincia la parte di Kolibre dentro un pezzo di
// file che puo' contenere anche le intestazioni dei capitoli sopra — e il
// titolo di un capitolo le virgolette ce le puo' avere.
const RIGA_META = /^\*.*🗓.*$/gm;

// Dove comincia la nota scritta nel lettore, dentro la parte di Kolibre.
const INIZIO_NOTA = /\n\*✍🏻\s/;

/** Sedici caratteri esadecimali. Vedi il commento qui sopra per il perche'. */
function impronta(testo) {
    const pulito = String(testo == null ? '' : testo).replace(/\s+/g, ' ').trim();
    return nodeCrypto.createHash('sha256').update(pulito, 'utf8').digest('hex').slice(0, 16);
}

/** Il nome durevole di una nota, col numero come ripiego per un server piu' vecchio di questo plugin. */
function nomeDurevole(hl) {
    return hl.id_durevole ? String(hl.id_durevole) : String(hl.id);
}

function marcatoreDi(hl) {
    return `<!-- kolibre-hl id:${nomeDurevole(hl)} base:${impronta(hl.text)} -->`;
}

/**
 * Il marcatore di un pezzo di file, in uno dei due formati, o null.
 * `intero` e' il testo esatto trovato: serve per sostituirlo senza toccare
 * nient'altro.
 */
function leggiIlMarcatore(pezzo) {
    const nuovo = pezzo.match(MARCATORE);
    if (nuovo) return { nome: nuovo[1], base: nuovo[2] || null, vecchio: false, intero: nuovo[0] };
    const vecchio = pezzo.match(MARCATORE_VECCHIO);
    if (vecchio) return { nome: vecchio[1], base: null, vecchio: true, intero: vecchio[0] };
    return null;
}

/**
 * Il brano citato dentro un blocco, **come sta scritto nel file adesso** —
 * cioe' la cosa di cui si calcola l'impronta per sapere se tu l'hai
 * cambiato.
 *
 * Si naviga per confini certi, non a indovinare: si taglia al marcatore
 * (sotto c'e' roba tua), si parte dall'ultima riga di metadati (sopra ci
 * possono essere le intestazioni dei capitoli), si taglia alla riga della
 * nota del lettore (una nota puo' contenere virgolette), e in quello che
 * resta si prende **dalla prima all'ultima virgoletta**: quelle due le
 * scrive Kolibre attorno al brano, quindi un brano che a sua volta contiene
 * virgolette torna intero.
 *
 * `null` se il brano non si riesce a leggere. Chi chiama non deve mai
 * trattare quel null come «cambiato»: vedi imprintaAttuale.
 */
function branoDelBlocco(pezzo) {
    const m = leggiIlMarcatore(pezzo);
    let zona = m ? pezzo.slice(0, pezzo.indexOf(m.intero)) : pezzo;

    const righeMeta = [...zona.matchAll(RIGA_META)];
    if (righeMeta.length) {
        const ultima = righeMeta[righeMeta.length - 1];
        zona = zona.slice(ultima.index + ultima[0].length);
    }

    const nota = zona.search(INIZIO_NOTA);
    if (nota !== -1) zona = zona.slice(0, nota);

    const primo = zona.indexOf('"');
    const ultimo = zona.lastIndexOf('"');
    if (primo === -1 || ultimo <= primo) return null;
    return zona.slice(primo + 1, ultimo);
}

/**
 * L'impronta del brano come sta nel file, da raccontare al server.
 *
 * **Quando il brano non si riesce a leggere si dichiara la base**, cioe'
 * «non l'ho cambiato io». Dire il vero (un'impronta di niente) farebbe
 * risultare il blocco cambiato da te, e se nel frattempo fosse cambiato
 * anche sul server diventerebbe un conflitto da decidere — per un difetto
 * di lettura mio. Nel dubbio non si disturba nessuno: e' la stessa scelta
 * prudente che fa il server per un blocco senza base.
 */
function improntaAttuale(pezzo, base) {
    const brano = branoDelBlocco(pezzo);
    return brano === null ? base : impronta(brano);
}

/**
 * Where a highlight came from, for the metadata line below — 'device' with
 * a still-registered device gets its real name; 'device' with no name
 * (device deleted since) and 'calibre'/'web' get a fixed generic label.
 * Matches backend/app/api/annotations.py::export_annotations's own
 * source/device_name fields.
 */
function formatHighlightSource(hl) {
    if (hl.source === 'device') return `📱 ${hl.device_name || t('obsidian.source.device')}`;
    if (hl.source === 'calibre') return `📚 ${t('obsidian.source.calibre')}`;
    return `🌐 ${t('obsidian.source.web')}`;
}

/**
 * One highlight block, WITHOUT the trailing "***" separator (callers join
 * blocks with that explicitly — keeps this function a pure formatter, and
 * keeps the separator convention in exactly one place: joinBlocks below).
 *
 * If there's no note, the whole "*✍🏻 Nota:*" line (label included) is
 * omitted — never an empty note label.
 */
function formatHighlightBlock(hl) {
    const dt = new Date(hl.created_at);
    const dateStr = isNaN(dt.getTime()) ? '' : dt.toLocaleString(t('obsidian.note.date_locale'), {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
    const pageSegment = hl.page ? `📄 p.${hl.page} · ` : '';
    const sourceSegment = ` · ${formatHighlightSource(hl)}`;
    // Il link alla nota dentro Kolibre, che il server manda insieme a ogni
    // riga (`link` in export_annotations, dal 05/11/2026). Serve a tornare
    // dall'appunto al punto preciso del libro: apre la nota nel lettore web
    // se il libro e' leggibile, la sua scheda altrimenti, e **risponde
    // qualcosa di sensato anche se quella nota non c'e' piu'**. Si omette
    // se il server e' piu' vecchio di questo plugin e non lo manda.
    const linkSegment = hl.link ? ` · [🔗 Kolibre](${hl.link})` : '';
    const text = (hl.text || '').replace(/\r\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();

    let block = `*${t('obsidian.block.highlight_label')} ${pageSegment}🗓 ${dateStr}${sourceSegment}${linkSegment}*\n\n"${text}"\n`;
    if (hl.note && hl.note.trim()) {
        block += `\n*✍🏻 ${t('obsidian.block.note_label')}*\n${hl.note.trim()}\n`;
    }
    block += `\n${marcatoreDi(hl)}`;
    return block;
}

// Every block gets its OWN trailing separator — including the last one in a
// section (right before the next heading) and the very last one in the
// whole file. An earlier version only put "***" BETWEEN blocks, which
// silently dropped the separator exactly where a section had just one
// highlight, or at the end of the file — reported after real use.
function joinBlocks(blocks) {
    return blocks.map(b => `${b}\n\n***`).join('\n\n');
}

// ── Grouping ──────────────────────────────────────────────────────────────

/**
 * Raggruppa le evidenziazioni per libro (biblioteca + titolo), ed e' lo
 * stesso giro per l'aggiornamento e per il reimport completo.
 *
 * **La chiave e' la stessa che usa il server** per risolvere i percorsi dei
 * capitoli (`capitoli_delle_note.con_i_percorsi`): se le due divergessero,
 * i percorsi sarebbero risolti su un raggruppamento e scritti su un altro —
 * e la prima nota nuda di un libro erediterebbe gli antenati di un libro
 * diverso. E' il motivo per cui quel raggruppamento la' esiste.
 */
function groupHighlightsByBook(highlights) {
    const books = {};
    for (const hl of highlights) {
        const key = `${hl.library}::${hl.book_title}`;
        if (!books[key]) {
            books[key] = {
                title: hl.book_title, author: hl.book_author,
                // Servono per far combaciare un file con le istruzioni del
                // server, che parlano di (biblioteca, id del libro).
                library: hl.library, calibre_book_id: hl.calibre_book_id,
                highlights: [],
            };
        }
        books[key].highlights.push(hl);
    }
    return books;
}

/**
 * Groups sorted highlights into sections by chapter path (already resolved
 * by the server, see livelliDelCapitolo) — `resolvedPaths` must be a
 * parallel array, same length/order as `highlights`. Global grouping by
 * exact path, not just adjacency: a chapter revisited later in page order
 * still folds into its original section instead of creating a duplicate.
 */
function groupByChapterPath(highlights, resolvedPaths) {
    const sections = [];
    const keyToIndex = new Map();
    for (let i = 0; i < highlights.length; i++) {
        const path = resolvedPaths[i];
        const key = path.length ? path.join(SEPARATOR) : '__none__';
        if (!keyToIndex.has(key)) {
            keyToIndex.set(key, sections.length);
            sections.push({
                key,
                headings: path.length ? path : [t('obsidian.block.no_chapter_heading')],
                highlights: [],
            });
        }
        sections[keyToIndex.get(key)].highlights.push(highlights[i]);
    }
    return sections;
}

// ── New file ──────────────────────────────────────────────────────────────

function buildNewFile(bookData, settings, filenameBase) {
    const { highlights } = bookData;
    const sorted = [...highlights].sort((a, b) => (a.page || Infinity) - (b.page || Infinity));
    const sections = groupByChapterPath(sorted, sorted.map(livelliDelCapitolo));

    const headerTemplate = (settings && settings.bookHeaderTemplate != null)
        ? settings.bookHeaderTemplate
        : DEFAULT_BOOK_HEADER;

    let md = '';
    if (headerTemplate.trim()) {
        md = applyHeaderTemplate(headerTemplate, bookData, filenameBase);
        if (!md.endsWith('\n\n')) {
            if (!md.endsWith('\n')) md += '\n';
            md += '\n';
        }
    }

    // Prefix-aware: a section whose path shares a leading run with the
    // previously written one only gets the DIVERGING levels re-emitted —
    // the alternative (re-emitting every level for every section, as this
    // used to do) is exactly what produced the same top-level heading
    // repeated once per distinct child, confirmed on a real book with
    // several sub-chapters under the same part.
    let openPath = [];
    for (const section of sections) {
        const path = section.headings;
        let commonLen = 0;
        while (commonLen < path.length && commonLen < openPath.length && path[commonLen] === openPath[commonLen]) {
            commonLen++;
        }
        for (let lvl = commonLen; lvl < path.length; lvl++) {
            md += `${'#'.repeat(lvl + 1)} ${path[lvl]}\n\n`;
        }
        openPath = path;
        md += joinBlocks(section.highlights.map(formatHighlightBlock)) + '\n\n';
    }
    return md.trimEnd() + '\n';
}

// ── Incremental update ────────────────────────────────────────────────────

/**
 * Ogni identita' gia' presente nel file, in uno qualunque dei due formati
 * di marcatore — ed e' tutto il filtro di «cosa c'e' di nuovo», senza
 * tenere da nessuna parte la data dell'ultima sincronizzazione.
 */
function identitaGiaPresenti(fileContent) {
    const nomi = new Set();
    for (const sorgente of [MARCATORE.source, MARCATORE_VECCHIO.source]) {
        const re = new RegExp(sorgente, 'g');
        let m;
        while ((m = re.exec(fileContent)) !== null) nomi.add(m[1]);
    }
    return nomi;
}

/**
 * Vero se questa nota e' gia' nel file, con l'uno o l'altro nome.
 *
 * **E' questo il controllo che impedisce i duplicati**, e guarda tutti due i
 * nomi di proposito: il nome durevole per i blocchi del formato nuovo, il
 * numero per quelli vecchi che la riscrittura non ha ancora toccato (per
 * esempio perche' il server non conosce piu' quel numero). Il ripiego sul
 * numero e' un ponte verso il passato, non una seconda identita': un numero
 * liberato da una cancellazione viene riusato da SQLite, e allora
 * indicherebbe un'altra nota.
 */
function giaPresente(nomi, hl) {
    if (hl.id_durevole && nomi.has(String(hl.id_durevole))) return true;
    return nomi.has(String(hl.id));
}

/**
 * Riscrive i marcatori del formato vecchio (`kolibre-hl:7`) in quello nuovo
 * (`kolibre-hl id:<nome durevole> base:<impronta>`), e **non tocca
 * nient'altro del file**: nemmeno uno spazio.
 *
 * **Perche' esiste.** I marcatori vecchi portano il numero di riga del
 * database, il nuovo porta il nome durevole: sono due nomi diversi per la
 * stessa nota. Un blocco senza nome durevole **non e' raccontabile al
 * server**: l'inventario scarta i blocchi che non hanno quel nome (non si
 * sa di quale nota parlino), quindi quel libro risulterebbe per sempre non
 * in pari nella pagina, e il confronto a tre vie non avrebbe una base da
 * cui partire. Riscrivere il marcatore e' il modo di non chiedere a nessuno
 * di svuotare a mano la cartella delle note.
 *
 * **Non e' questo** che evita il duplicato: quello lo evita `giaPresente`,
 * che riconosce una nota anche dal solo numero. Misurato guastando le due
 * cose: togliendo solo la riscrittura il duplicato non nasce, togliendo
 * tutte due si. Il ripiego sul numero pero' non puo' durare — e' proprio il
 * numero che si muove — ed e' il motivo per cui i marcatori vanno rinnovati
 * adesso che la corrispondenza e' ancora valida.
 *
 * Il numero si traduce in nome durevole con le note che il server ha appena
 * mandato: ogni riga porta tutti due (`id` e `id_durevole`), quindi la
 * corrispondenza e' gia' in mano e non costa una chiamata.
 *
 * **La base che ci scrive e' l'impronta del brano come sta nel file**, non
 * come sta sul server. Vuol dire: «da adesso si misura da qui». Un blocco
 * che avevi gia' corretto a mano non risulta modificato — e se dopo cambia
 * anche sul server, il server vince. L'altra scelta (base dal server)
 * avrebbe reso ogni tua correzione passata un «modificato da te» che non si
 * aggiorna mai piu'. La seconda e' piu' conservativa, la prima e' piu'
 * vicina a quello che hai chiesto: i file che hai li sistemi tu, il plugin
 * riparte da quello che trova.
 *
 * Un marcatore vecchio il cui numero il server non conosce piu' (nota
 * cancellata) resta com'e': non si sa a cosa corrisponda, e inventare un
 * nome sarebbe peggio.
 */
function rinnovaIMarcatori(contenuto, notePerId) {
    const re = new RegExp(MARCATORE_VECCHIO.source, 'g');
    let fuori = '';
    let ultimo = 0;
    let rinnovati = 0;
    let m;
    while ((m = re.exec(contenuto)) !== null) {
        const hl = notePerId.get(String(m[1]));
        fuori += contenuto.slice(ultimo, m.index);
        if (hl && hl.id_durevole) {
            const taglio = contenuto.lastIndexOf('\n***', m.index);
            const pezzo = contenuto.slice(taglio === -1 ? 0 : taglio, m.index + m[0].length);
            const brano = branoDelBlocco(pezzo);
            const base = impronta(brano === null ? hl.text : brano);
            fuori += `<!-- kolibre-hl id:${hl.id_durevole} base:${base} -->`;
            rinnovati++;
        } else {
            fuori += m[0];
        }
        ultimo = m.index + m[0].length;
    }
    fuori += contenuto.slice(ultimo);
    return { contenuto: fuori, rinnovati };
}

/**
 * Merges new highlights into one section's raw text (everything between its
 * heading line and the next heading / EOF), inserting each new block in
 * page order relative to the highlight blocks already there.
 *
 * Blocks are delimited by a "***" line. A block containing a
 * <!-- kolibre-hl:ID --> marker is a real highlight block (page-sortable);
 * any other block is free-form user content. As long as the section is a
 * *pure* sequence of highlight blocks (nothing hand-written mixed in after
 * the first one), new highlights are inserted at their correct page
 * position. If the user has written something of their own in between
 * highlight blocks, that section falls back to appending new highlights at
 * the end instead — reordering around unknown hand-written content risks
 * corrupting it, appending never does. A leading preamble (anything BEFORE
 * the first highlight block) is always left exactly where it is.
 */
function mergeSectionBlocks(existingSectionText, newHighlights) {
    const rawChunks = existingSectionText.split(/\n\*\*\*\n/).map(c => c.trim()).filter(Boolean);
    const parsed = rawChunks.map(raw => {
        const marcatore = leggiIlMarcatore(raw);
        if (!marcatore) return { kind: 'other', raw };
        const pageMatch = raw.match(PAGE_IN_BLOCK_RE);
        return { kind: 'highlight', id: marcatore.nome, page: pageMatch ? parseInt(pageMatch[1], 10) : Infinity, raw };
    });

    let firstHighlightIdx = parsed.findIndex(p => p.kind === 'highlight');
    if (firstHighlightIdx === -1) firstHighlightIdx = parsed.length;
    const preamble = parsed.slice(0, firstHighlightIdx);
    const rest = parsed.slice(firstHighlightIdx);
    const hasInterleavedOther = rest.some(p => p.kind === 'other');

    const newBlocks = newHighlights.map(hl => ({
        kind: 'highlight',
        id: nomeDurevole(hl),
        page: hl.page || Infinity,
        raw: formatHighlightBlock(hl),
    }));

    const merged = hasInterleavedOther
        ? rest.concat(newBlocks) // can't safely reorder around hand-written content — append only
        : rest.concat(newBlocks).sort((a, b) => a.page - b.page); // stable sort (ES2019+): ties keep original relative order

    const allBlocks = preamble.concat(merged);
    return joinBlocks(allBlocks.map(b => b.raw));
}

/** Every markdown heading line in a file, in document order, with its level and line index. */
function parseHeadingLines(fileContent) {
    const lines = fileContent.split('\n');
    const headings = [];
    for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(/^(#+)\s+(.*)$/);
        if (m) headings.push({ level: m[1].length, text: m[2].trimEnd(), lineIndex: i });
    }
    return { lines, headings };
}

/**
 * Finds the line index of the heading matching the FULL ancestor chain in
 * `targetPath` — not just the leaf text. Walks the heading list keeping a
 * stack of open ancestors per level (exactly how buildNewFile itself
 * writes them), so two DIFFERENT chapters that happen to share a leaf
 * label (confirmed on a real book: both "1. La Rivoluzione russa" and
 * "2. Trent'anni dopo" have their own child "I." and "IV.") never get
 * confused with each other. Returns -1 if that exact chain doesn't exist.
 */
function findHeadingByPath(headingList, targetPath) {
    let stack = [];
    for (const h of headingList) {
        stack = stack.slice(0, h.level - 1);
        stack[h.level - 1] = h.text;
        if (h.level === targetPath.length && targetPath.every((t, i) => stack[i] === t)) {
            return h.lineIndex;
        }
    }
    return -1;
}

/** First line index at or after `headingLineIdx + 1` whose heading level is <= `level` (i.e. where that heading's own content ends), or EOF. */
function findSectionEnd(lines, headingLineIdx, level) {
    for (let i = headingLineIdx + 1; i < lines.length; i++) {
        const m = lines[i].match(/^(#+)\s/);
        if (m && m[1].length <= level) return i;
    }
    return lines.length;
}

/**
 * Applies mergeSectionBlocks to the right slice of the WHOLE file for one
 * chapter-path section. Finds the LONGEST already-existing ancestor prefix
 * of `headings` (by full chain, see findHeadingByPath) rather than just
 * looking for the exact leaf: a partial match gets only the missing
 * deeper levels inserted right after that ancestor's own existing content
 * (never blindly appended at EOF when the ancestor already exists — doing
 * that used to recreate the exact "repeated parent heading" bug on every
 * incremental update instead of just on the very first build). No match
 * at all falls back to creating the whole chain fresh at EOF, as before.
 */
function insertSection(fileContent, headings, newHighlights) {
    if (!newHighlights.length) return fileContent;
    const { lines, headings: headingList } = parseHeadingLines(fileContent);

    let matchLevel = 0;
    let matchLineIdx = -1;
    for (let lvl = headings.length; lvl >= 1; lvl--) {
        const idx = findHeadingByPath(headingList, headings.slice(0, lvl));
        if (idx !== -1) {
            matchLevel = lvl;
            matchLineIdx = idx;
            break;
        }
    }

    if (matchLevel === headings.length) {
        const sectionEndIdx = findSectionEnd(lines, matchLineIdx, matchLevel);
        const before = lines.slice(0, matchLineIdx + 1).join('\n');
        const sectionText = lines.slice(matchLineIdx + 1, sectionEndIdx).join('\n');
        const after = lines.slice(sectionEndIdx).join('\n');
        const mergedSection = mergeSectionBlocks(sectionText, newHighlights);
        const content = before + '\n\n' + mergedSection + '\n\n' + (after || '');
        return content.replace(/\n{3,}/g, '\n\n\n').trimEnd() + '\n';
    }

    let addition = '';
    for (let lvl = matchLevel; lvl < headings.length; lvl++) {
        addition += '#'.repeat(lvl + 1) + ' ' + headings[lvl] + '\n\n';
    }
    addition += joinBlocks(newHighlights.map(formatHighlightBlock));

    const insertAt = matchLevel === 0 ? lines.length : findSectionEnd(lines, matchLineIdx, matchLevel);
    const before = lines.slice(0, insertAt).join('\n');
    const after = lines.slice(insertAt).join('\n');
    const content = before.trimEnd() + '\n\n' + addition + '\n\n' + after;
    return content.replace(/\n{3,}/g, '\n\n\n').trimEnd() + '\n';
}


/**
 * Aggiunge a un file che esiste solo le note che non ci sono gia'.
 *
 * `bookData.highlights` deve arrivare **gia' privato delle note da non
 * rimettere** (vedi `noteDaScrivere`): qui non si ricontrolla, perche' lo
 * stesso elenco serve anche a decidere se un file va creato, e due filtri
 * in due posti diversi sono due filtri che un giorno divergono.
 */
function mergeHighlights(existingContent, bookData) {
    // La ripulitura dei duplicati lasciati dal vecchio difetto del marcatore
    // e' stata tolta dopo essere girata su tutto il vault: girava a ogni
    // sync di ogni nota per un lavoro da fare una volta sola.

    // Prima di tutto i marcatori del formato vecchio diventano nuovi: da
    // qui in poi il file parla di nomi durevoli, e il filtro qui sotto
    // riconosce come «gia' importata» una nota che c'e' davvero.
    const notePerId = new Map(bookData.highlights.map(hl => [String(hl.id), hl]));
    const rinnovo = rinnovaIMarcatori(existingContent, notePerId);
    const contenuto = rinnovo.contenuto;

    const presenti = identitaGiaPresenti(contenuto);
    const trulyNew = bookData.highlights.filter(hl => !giaPresente(presenti, hl));
    if (trulyNew.length === 0) {
        // Anche senza niente di nuovo il file puo' essere cambiato: i
        // marcatori rinnovati vanno salvati, altrimenti si rifa' lo stesso
        // lavoro al giro dopo.
        return { content: contenuto, added: 0, rinnovati: rinnovo.rinnovati };
    }

    // **Bastano le nuove.** Prima qui si rimettevano in fila tutte le
    // evidenziazioni del libro, vecchie e nuove, solo per poter risolvere i
    // percorsi: una nuova nota "nuda" deve ereditare i suoi antenati dalla
    // nota che la precede nel libro, e quella poteva essere una gia'
    // importata mesi prima. Adesso ogni riga arriva dal server col suo
    // percorso gia' risolto su tutto il libro, quindi quel giro — e il
    // filtro per id che gli serviva dietro — non serve piu'.
    const sorted = [...trulyNew].sort((a, b) => (a.page || Infinity) - (b.page || Infinity));
    const sections = groupByChapterPath(sorted, sorted.map(livelliDelCapitolo));

    let content = contenuto;
    for (const section of sections) {
        content = insertSection(content, section.headings, section.highlights);
    }
    return { content, added: trulyNew.length, rinnovati: rinnovo.rinnovati };
}

// ── Il racconto, e le istruzioni ──────────────────────────────────────────
//
// **Perche' il plugin racconta.** Il server non puo' guardare nel vault, e
// non puo' scrivere dentro: sincronizza il plugin, quando glielo chiedi tu.
// Allora com'e' che la pagina di Kolibre sa com'e' la situazione? Perche' il
// plugin **racconta**: per ogni blocco dice di quale nota parla e le due
// impronte. Il server se lo scrive con la data e da quello ricava gli stati.
//
// **E' una fotografia, non uno specchio**, e la differenza non e'
// accademica: un registro di «cosa dovrebbe esserci» che non guarda il
// disco e' precisamente la cosa che ha messo 21 libri in doppia copia sul
// Kindle. Un racconto nuovo sostituisce il vecchio, quindi un file che
// cancelli torna «non creato» — che e' la verita'.
//
// **E le istruzioni sono la strada di ritorno.** Quello che scegli nella
// pagina (non mandare questo libro, rifallo da zero, in questo conflitto
// vince Kolibre) non puo' essere eseguito dal server: torna qui nella
// risposta al racconto, e lo esegue il plugin. Finche' non e' passato, la
// pagina lo dice: «in attesa».

/**
 * Cosa raccontare di un file del vault.
 *
 * Un blocco col marcatore del formato vecchio **non si racconta**: non
 * porta il nome durevole, quindi non si sa di quale nota parli, e il server
 * lo scarterebbe. Si conta fra i `muti` e lo rinnova l'importazione.
 *
 * `testo_attuale` si manda **solo** per i blocchi dove le due impronte non
 * corrispondono: serve alla pagina per mostrare i due testi affiancati, e
 * mandare il testo di milleduecento blocchi a ogni sincronizzazione per poi
 * non guardarlo sarebbe sprecato.
 */
function inventarioDelFile(percorso, contenuto) {
    const blocchi = [];
    let muti = 0;
    const re = new RegExp(MARCATORE.source, 'g');
    let m;
    while ((m = re.exec(contenuto)) !== null) {
        const nome = m[1];
        const base = m[2] || null;
        const taglio = contenuto.lastIndexOf('\n***', m.index);
        const pezzo = contenuto.slice(taglio === -1 ? 0 : taglio, m.index + m[0].length);
        const attuale = improntaAttuale(pezzo, base);
        const blocco = { id_durevole: nome, impronta_base: base, impronta_attuale: attuale };
        if (attuale !== base) blocco.testo_attuale = branoDelBlocco(pezzo);
        blocchi.push(blocco);
    }
    const vecchi = new RegExp(MARCATORE_VECCHIO.source, 'g');
    while (vecchi.exec(contenuto) !== null) muti++;
    return { percorso, blocchi, muti };
}

/**
 * Il blocco riscritto con il testo del server, tenendo quello che hai
 * scritto **sotto** il marcatore.
 *
 * Non si riscrive tutto il pezzo: sopra la riga di metadati ci possono
 * stare le intestazioni dei capitoli, e sotto il marcatore ci sei tu. Si
 * sostituisce solo quello che sta in mezzo, che e' esattamente la parte di
 * Kolibre.
 *
 * `null` se il pezzo non ha la forma attesa — e allora non si tocca niente.
 */
function riscriviIlBlocco(pezzo, hl) {
    const m = leggiIlMarcatore(pezzo);
    if (!m) return null;
    const righeMeta = [...pezzo.matchAll(RIGA_META)];
    if (!righeMeta.length) return null;
    const ultima = righeMeta[righeMeta.length - 1];
    const fineMarcatore = pezzo.indexOf(m.intero) + m.intero.length;
    return pezzo.slice(0, ultima.index) + formatHighlightBlock(hl) + pezzo.slice(fineMarcatore);
}

/**
 * Sposta la base del marcatore su quello che c'e' adesso nel file, senza
 * toccare una virgola del testo.
 *
 * E' il «vince il mio»: da quel momento il brano del vault **e'** la base,
 * quindi non risulta piu' cambiato da te e il conflitto non si ripresenta a
 * ogni sincronizzazione. Senza questo, scegliere «tengo il mio» non avrebbe
 * nessun effetto duraturo: la pagina lo richiederebbe ogni volta.
 */
function spostaLaBase(pezzo) {
    const m = leggiIlMarcatore(pezzo);
    if (!m) return null;
    const brano = branoDelBlocco(pezzo);
    if (brano === null) return null;
    return pezzo.replace(m.intero, `<!-- kolibre-hl id:${m.nome} base:${impronta(brano)} -->`);
}

/**
 * Esegue le scelte fatte nella pagina sui conflitti di questo file.
 *
 * Ritorna il contenuto nuovo e i nomi delle note su cui ha davvero agito:
 * sono quelli che il plugin **dichiara** al server, e solo allora
 * l'istruzione si spegne. Una nota che questo file non contiene non viene
 * dichiarata — la dichiarera' il file che la contiene.
 */
function applicaLeScelte(contenuto, scelte, notePerNome) {
    const re = new RegExp(MARCATORE.source, 'g');
    let fuori = '';
    let ultimo = 0;
    const risolti = [];
    let m;
    while ((m = re.exec(contenuto)) !== null) {
        const nome = m[1];
        const scelta = scelte.get(nome);
        if (!scelta) continue;
        const fine = m.index + m[0].length;
        const taglio = contenuto.lastIndexOf('\n***', m.index);
        const inizioPezzo = taglio === -1 ? 0 : taglio;
        // Due blocchi non si possono sovrapporre; se accadesse (un file
        // rimaneggiato in modi imprevisti) si lascia stare il secondo
        // invece di scrivere a caso.
        if (inizioPezzo < ultimo) continue;
        const pezzo = contenuto.slice(inizioPezzo, fine);
        let nuovo = null;
        if (scelta === 'kolibre') {
            const hl = notePerNome.get(nome);
            if (hl) nuovo = riscriviIlBlocco(pezzo, hl);
        } else if (scelta === 'mio') {
            nuovo = spostaLaBase(pezzo);
        }
        if (nuovo === null) continue;
        fuori += contenuto.slice(ultimo, inizioPezzo) + nuovo;
        ultimo = fine;
        // Dichiarata anche se il testo non e' cambiato di una virgola: la
        // scelta e' stata eseguita, e lasciarla accesa la farebbe
        // riproporre all'infinito.
        risolti.push(nome);
    }
    fuori += contenuto.slice(ultimo);
    return { contenuto: fuori, risolti };
}

/**
 * Riporta nel vault i brani cambiati **solo in Kolibre**.
 *
 * E' il terzo dei quattro casi del confronto a tre vie, quello che «si
 * risolve da se'»: la base e quello che c'e' nel file sono uguali (tu non
 * hai toccato niente) e il server ha un brano diverso (una
 * risincronizzazione dal lettore ha allungato l'evidenziazione, o l'hai
 * corretta dal browser). Allora si riscrive quel blocco col testo nuovo e
 * si sposta la base.
 *
 * **Perche' serviva scriverlo.** «Si risolve da se'» non vuol dire che
 * succede da solo: il 05/11/2026 non lo faceva nessuno — il plugin salta le
 * note che trova gia' nel file (e' il filtro che evita i duplicati), e il
 * server diceva che il libro era «in pari». Due pezzi che si aspettavano a
 * vicenda, e in mezzo un brano vecchio che non si aggiornava mai.
 *
 * **Non tocca niente di tuo.** Se il brano nel file non corrisponde alla
 * base, vuol dire che ci hai messo mano: quello e' un conflitto (se e'
 * cambiato anche in Kolibre) o una tua modifica da rispettare, e in nessuno
 * dei due casi si riscrive. Un blocco senza base si lascia stare, perche'
 * non si puo' dire chi ha cambiato cosa.
 */
function riportaIBlocchiCambiati(contenuto, notePerNome) {
    const re = new RegExp(MARCATORE.source, 'g');
    let fuori = '';
    let ultimo = 0;
    const riportati = [];
    let m;
    while ((m = re.exec(contenuto)) !== null) {
        const nome = m[1];
        const base = m[2] || null;
        const hl = notePerNome.get(nome);
        if (!base || !hl) continue;
        if (impronta(hl.text) === base) continue;   // il server non e' cambiato

        const fine = m.index + m[0].length;
        const taglio = contenuto.lastIndexOf('\n***', m.index);
        const inizioPezzo = taglio === -1 ? 0 : taglio;
        if (inizioPezzo < ultimo) continue;
        const pezzo = contenuto.slice(inizioPezzo, fine);
        if (improntaAttuale(pezzo, base) !== base) continue;   // ci hai messo mano tu

        const nuovo = riscriviIlBlocco(pezzo, hl);
        if (nuovo === null) continue;
        fuori += contenuto.slice(ultimo, inizioPezzo) + nuovo;
        ultimo = fine;
        riportati.push(nome);
    }
    fuori += contenuto.slice(ultimo);
    return { contenuto: fuori, riportati };
}

/**
 * Le note di un libro che si possono scrivere, cioe' tutte tranne quelle che
 * **hai togliato tu**.
 *
 * `nonRimettere` arriva dal server nelle istruzioni: sono le note che quel
 * vault ha ricevuto almeno una volta e che adesso non ci sono piu'. Il
 * server le sa perche' tiene un registro delle consegne, che il plugin
 * riempie semplicemente raccontando (vedi models.NotaConsegnata).
 *
 * **Una regola sola copre due casi.** Una nota togliata da dentro un file
 * che resta non si rimette. E un file cancellato non si ricrea, perche'
 * togliendo queste note **non resta niente da scriverci** — e un file senza
 * niente da scrivere non si crea. Se invece fra le note del libro ce n'e'
 * una mai consegnata, il file nasce con dentro solo quella: scelta di Paolo
 * del 06/11/2026, «se dall'ultimo sync non ci sono nuove note da aggiungere
 * sono fatti miei se ho deciso di eliminarlo».
 */
function noteDaScrivere(highlights, nonRimettere) {
    if (!nonRimettere || !nonRimettere.size) return highlights;
    return highlights.filter(hl => !nonRimettere.has(nomeDurevole(hl)));
}

/** La chiave con cui il server e il plugin chiamano lo stesso libro. */
function chiaveDelLibro(library, titolo) {
    return `${library || ''}::${titolo || ''}`;
}

// ── Folder suggestion ─────────────────────────────────────────────────────

class FolderSuggest extends obsidian.AbstractInputSuggest {
    constructor(app, inputEl, onSelect) {
        super(app, inputEl);
        // Hooking selection via the documented onSelect() registration
        // instead of overriding selectSuggestion() directly: AbstractInputSuggest
        // has its OWN internal selectSuggestion implementation (added in the
        // Obsidian API well after this pattern was common in older plugin
        // examples) that setValue()s the input and closes the popup itself —
        // overriding it here silently shadowed that internal wiring, so a
        // click/Enter on a suggestion never actually landed (reported
        // directly: "mostra i suggerimenti ma non mi fa confermare").
        if (onSelect) {
            this.onSelect((folder) => {
                this.setValue(folder);
                this.inputEl.dispatchEvent(new Event('input', { bubbles: true }));
                onSelect(folder);
                this.close();
            });
        }
    }

    getSuggestions(query) {
        const folders = [];
        const lowerQuery = query.toLowerCase();
        const collect = (folder) => {
            for (const child of (folder.children || [])) {
                if (child instanceof obsidian.TFolder) {
                    if (child.path.toLowerCase().includes(lowerQuery)) {
                        folders.push(child.path);
                    }
                    collect(child);
                }
            }
        };
        collect(this.app.vault.getRoot());
        return folders.slice(0, 20);
    }

    renderSuggestion(folder, el) {
        el.createEl('span', { text: folder });
    }
}

// ── Import summary modal ──────────────────────────────────────────────────

class ImportSummaryModal extends obsidian.Modal {
    constructor(app, results) {
        super(app);
        this.results = results;
    }
    onOpen() {
        const { contentEl } = this;
        const { newFiles, updatedFiles, totalAdded } = this.results;
        const rebuiltFiles = this.results.rebuiltFiles || [];
        const renewed = this.results.renewed || 0;
        const carried = this.results.carried || 0;
        const resolved = this.results.resolved || 0;
        const blocked = this.results.blocked || 0;
        const left = this.results.left || 0;
        contentEl.createEl('h2', { text: t('obsidian.import_summary.title') });
        contentEl.createEl('p', { text: t('obsidian.import_summary.total', { count: totalAdded }) });
        if (newFiles.length > 0) {
            contentEl.createEl('h3', { text: t('obsidian.import_summary.new_files_heading', { count: newFiles.length }) });
            const ul = contentEl.createEl('ul');
            for (const f of newFiles) ul.createEl('li', { text: t('obsidian.import_summary.file_line', { title: f.title, count: f.count }) });
        }
        if (updatedFiles.length > 0) {
            contentEl.createEl('h3', { text: t('obsidian.import_summary.updated_files_heading', { count: updatedFiles.length }) });
            const ul = contentEl.createEl('ul');
            for (const f of updatedFiles) ul.createEl('li', { text: t('obsidian.import_summary.file_line_added', { title: f.title, count: f.count }) });
        }
        // I file rifatti da zero stanno in una sezione loro: non sono «+N
        // note», sono file riscritti, e dirlo come un'aggiunta
        // nasconderebbe che quello che c'era dentro quei blocchi non c'e'
        // piu'.
        if (rebuiltFiles.length > 0) {
            contentEl.createEl('h3', { text: t('obsidian.import_summary.rebuilt_files_heading', { count: rebuiltFiles.length }) });
            const ul = contentEl.createEl('ul');
            for (const f of rebuiltFiles) ul.createEl('li', { text: t('obsidian.import_summary.file_line', { title: f.title, count: f.count }) });
        }
        if (newFiles.length === 0 && updatedFiles.length === 0 && rebuiltFiles.length === 0) {
            contentEl.createEl('p', { text: t('obsidian.import_summary.no_changes') });
        }
        // Le righe che spiegano il lavoro che non si vede nei conti dei
        // file: i conflitti eseguiti, i marcatori rinnovati, i libri che si
        // e' lasciati stare perche' bloccati dalla pagina.
        for (const [quanti, chiave] of [
            [carried, 'obsidian.import_summary.carried'],
            [resolved, 'obsidian.import_summary.resolved'],
            [renewed, 'obsidian.import_summary.renewed'],
            [blocked, 'obsidian.import_summary.blocked'],
            [left, 'obsidian.import_summary.left'],
        ]) {
            if (quanti > 0) contentEl.createEl('p', { text: t(chiave, { count: quanti }) });
        }
        const closeBtn = contentEl.createEl('button', { text: t('obsidian.common.close'), cls: 'mod-cta' });
        closeBtn.style.marginTop = '16px';
        closeBtn.onclick = () => this.close();
    }
    onClose() {
        this.contentEl.empty();
    }
}

// ── Confirm modal ─────────────────────────────────────────────────────────

/**
 * Generic yes/no confirmation — used before the destructive full-reimport
 * command (see reimportAllHighlights). onConfirm only ever fires from the
 * "confirm" button; closing the modal any other way (Annulla, Esc, click
 * outside) never calls it.
 */
class ConfirmModal extends obsidian.Modal {
    constructor(app, { title, message, confirmText, onConfirm }) {
        super(app);
        this.title = title;
        this.message = message;
        this.confirmText = confirmText;
        this.onConfirm = onConfirm;
    }
    onOpen() {
        const { contentEl } = this;
        contentEl.createEl('h2', { text: this.title });
        contentEl.createEl('p', { text: this.message });
        const row = contentEl.createEl('div');
        row.style.display = 'flex';
        row.style.justifyContent = 'flex-end';
        row.style.gap = '8px';
        row.style.marginTop = '16px';
        const cancelBtn = row.createEl('button', { text: t('obsidian.common.cancel') });
        cancelBtn.onclick = () => this.close();
        const confirmBtn = row.createEl('button', { text: this.confirmText, cls: 'mod-warning' });
        confirmBtn.onclick = () => {
            this.close();
            this.onConfirm();
        };
    }
    onClose() {
        this.contentEl.empty();
    }
}

// ── Settings tab ──────────────────────────────────────────────────────────

class KolibreSettingTab extends obsidian.PluginSettingTab {
    constructor(app, plugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display() {
        const { containerEl } = this;
        containerEl.empty();
        containerEl.createEl('h2', { text: 'Kolibre Highlights' });

        containerEl.createEl('h3', { text: t('obsidian.settings.section_login') });

        new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.server_url_name'))
            .setDesc(t('obsidian.settings.server_url_desc'))
            .addText(text => text
                .setPlaceholder('http://192.168.1.100:8081')
                .setValue(this.plugin.settings.serverUrl)
                .onChange(async v => {
                    this.plugin.settings.serverUrl = v.trim().replace(/\/$/, '');
                    await this.plugin.saveSettings();
                }));

        new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.username_name'))
            .addText(text => text
                .setValue(this.plugin.settings.username)
                .onChange(async v => {
                    this.plugin.settings.username = v.trim();
                    await this.plugin.saveSettings();
                }));

        new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.password_name'))
            .setDesc(t('obsidian.settings.password_desc'))
            .addText(text => {
                text.inputEl.type = 'password';
                // **Non si salva, e non si rilegge**: vive solo in questa
                // casella finché la finestra è aperta, e serve al pulsante
                // «Accedi» qui sotto per ottenere il token. Chiudendo le
                // impostazioni se ne va.
                text.onChange(v => { this._passwordInCorso = v; });
            });

        const testSetting = new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.login_test_name'))
            .setDesc(this.plugin.settings.authToken
                ? t('obsidian.settings.already_logged_in')
                : t('obsidian.settings.login_prompt'));

        testSetting.addButton(btn => {
            btn.setButtonText(t('obsidian.common.login'));
            btn.onClick(async () => {
                btn.setDisabled(true);
                btn.setButtonText(t('obsidian.settings.login_in_progress'));
                try {
                    const sessione = await this.plugin.login(
                        this.plugin.settings.username, this._passwordInCorso || '');
                    // Si scambia subito la sessione con un token
                    // d'applicazione, cosi' la password non serve piu' a
                    // niente e non la si scrive da nessuna parte.
                    const token = await this.plugin.scambiaConTokenDApplicazione(sessione);
                    this.plugin.settings.authToken = token || sessione;
                    await this.plugin.saveSettings();
                    this._passwordInCorso = '';
                    testSetting.descEl.style.color = 'var(--color-green)';
                    testSetting.setDesc(token
                        ? t('obsidian.settings.login_success')
                        : t('obsidian.settings.login_success_vecchio_server'));
                } catch (err) {
                    testSetting.descEl.style.color = 'var(--color-red)';
                    testSetting.setDesc('✗ ' + err.message);
                } finally {
                    btn.setDisabled(false);
                    btn.setButtonText(t('obsidian.common.login'));
                }
            });
        });

        containerEl.createEl('h3', { text: t('obsidian.settings.section_output') });

        new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.output_folder_name'))
            .setDesc(t('obsidian.settings.output_folder_desc'))
            .addText(text => {
                text.setPlaceholder('Libri')
                    .setValue(this.plugin.settings.outputFolder)
                    .onChange(async v => {
                        this.plugin.settings.outputFolder = v.trim().replace(/^\/|\/$/g, '');
                        await this.plugin.saveSettings();
                    });
                new FolderSuggest(this.app, text.inputEl, async (folder) => {
                    this.plugin.settings.outputFolder = folder.replace(/^\/|\/$/g, '');
                    text.setValue(folder);
                    await this.plugin.saveSettings();
                });
            });

        new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.filename_template_name'))
            .setDesc(t('obsidian.settings.filename_template_desc'))
            .addText(text => text
                .setPlaceholder('{{title}}')
                .setValue(this.plugin.settings.filenameTemplate)
                .onChange(async v => {
                    this.plugin.settings.filenameTemplate = v.trim() || '{{title}}';
                    await this.plugin.saveSettings();
                }));

        containerEl.createEl('h3', { text: t('obsidian.settings.section_header_template') });
        const headerDesc = containerEl.createEl('p', { cls: 'setting-item-description' });
        headerDesc.innerHTML = t('obsidian.settings.header_template_desc');

        const headerSetting = new obsidian.Setting(containerEl).setName(t('obsidian.settings.header_template_name'));
        headerSetting.addTextArea(ta => {
            ta.setPlaceholder(DEFAULT_BOOK_HEADER);
            ta.setValue(this.plugin.settings.bookHeaderTemplate ?? DEFAULT_BOOK_HEADER);
            ta.inputEl.rows = 5;
            ta.inputEl.style.fontFamily = 'var(--font-monospace, monospace)';
            ta.inputEl.style.width = '100%';
            ta.onChange(async v => {
                this.plugin.settings.bookHeaderTemplate = v;
                await this.plugin.saveSettings();
            });
        });

        containerEl.createEl('h3', { text: t('obsidian.settings.section_updates') });

        const aggiornamento = new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.plugin_version_name'))
            .setDesc(t('obsidian.settings.plugin_version_desc', { version: this.plugin.manifest.version }));

        aggiornamento.addButton(btn => {
            btn.setButtonText(t('obsidian.settings.check_update_button'));
            btn.onClick(async () => {
                btn.setDisabled(true);
                btn.setButtonText(t('obsidian.settings.checking_updates'));
                try {
                    const disponibile = await this.plugin.versioneSulServer();
                    if (!this.plugin._versioneMaggiore(disponibile, this.plugin.manifest.version)) {
                        aggiornamento.descEl.style.color = '';
                        aggiornamento.setDesc(t('obsidian.settings.already_latest', { version: this.plugin.manifest.version }));
                        return;
                    }
                    aggiornamento.setDesc(t('obsidian.settings.update_found_installing', { version: disponibile }));
                    // Da qui in poi gira il codice nuovo: questa scheda
                    // viene distrutta insieme al plugin vecchio, e non c'e'
                    // niente di utile da scrivere dopo.
                    await this.plugin.controllaAggiornamenti();
                } catch (err) {
                    aggiornamento.descEl.style.color = 'var(--color-red)';
                    aggiornamento.setDesc('✗ ' + err.message);
                } finally {
                    btn.setDisabled(false);
                    btn.setButtonText(t('obsidian.settings.check_update_button'));
                }
            });
        });
    }
}

// ── Main plugin ───────────────────────────────────────────────────────────

class KolibreHighlightsPlugin extends obsidian.Plugin {

    async onload() {
        await this.loadSettings();
        this.addSettingTab(new KolibreSettingTab(this.app, this));
        this.addCommand({
            id: 'kolibre-import-highlights',
            name: t('obsidian.command.import'),
            callback: () => this.importHighlights(),
        });
        this.addCommand({
            id: 'kolibre-reimport-all',
            name: t('obsidian.command.reimport_all'),
            callback: () => this.reimportAllHighlights(),
        });
        this.addCommand({
            id: 'kolibre-update-plugin',
            name: t('obsidian.command.check_update'),
            callback: () => this.controllaAggiornamenti(),
        });
    }

    async loadSettings() {
        this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
        await this._tolgiLaPasswordDalVault();
    }

    /**
     * Togli la password dal vault, una volta sola, a chi ce l'ha ancora.
     *
     * **Perché non basta smettere di salvarla.** Chi usa il plugin da prima
     * del 05/11/2026 ce l'ha già scritta dentro `data.json`, e quel file sta
     * nel vault — che è la cartella che la gente sincronizza, a volte in un
     * repository git. Una correzione che si limita a non scriverla più
     * lascia il problema esattamente dov'era per tutti quelli che ce
     * l'hanno: il difetto non è l'atto di scrivere, è il segreto che sta lì.
     *
     * Quindi: se c'è una password salvata, la si usa **un'ultima volta** per
     * ottenere un token d'applicazione, e poi la si cancella. Se il giro non
     * riesce (server spento, server più vecchio, password cambiata) la si
     * cancella comunque: tenerla non servirebbe a niente di buono, e il
     * peggio che succede è che si debba riaccedere a mano una volta.
     */
    async _tolgiLaPasswordDalVault() {
        if (!this.settings.password) return;
        const password = this.settings.password;
        delete this.settings.password;
        try {
            const sessione = await this.login(this.settings.username, password);
            const token = await this.scambiaConTokenDApplicazione(sessione);
            if (token) this.settings.authToken = token;
        } catch (_) {
            // Si va avanti comunque: la password se ne va in ogni caso.
        }
        await this.saveSettings();
        new obsidian.Notice(t('obsidian.notice.password_tolta'), 10000);
    }

    async saveSettings() {
        await this.saveData(this.settings);
    }

    // ── HTTP helpers ────────────────────────────────────────────────────

    async login(username, password) {
        const url = `${this.settings.serverUrl}/token`;
        let resp;
        try {
            resp = await obsidian.requestUrl({
                url, method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
                throw: false,
            });
        } catch (err) {
            throw new Error(t('obsidian.error.unreachable', { url, message: err.message }));
        }
        if (resp.status !== 200) {
            throw new Error(t('obsidian.error.bad_credentials', { status: resp.status }));
        }
        return resp.json.access_token;
    }

    /**
     * Scambia una sessione appena aperta con un **token per
     * l'applicazione**: non scade, si revoca dal portale, e permette a
     * questo plugin di non conservare la password.
     *
     * Se il server è più vecchio e non conosce quell'indirizzo si tiene il
     * token di sessione: il plugin continua a funzionare per sette giorni e
     * poi chiederà di riaccedere — che è il comportamento di prima, non un
     * guasto. Meglio così che rifiutarsi di collegarsi a un server che non
     * ha ancora aggiornato.
     */
    async scambiaConTokenDApplicazione(sessione) {
        const resp = await obsidian.requestUrl({
            url: `${this.settings.serverUrl}/api/users/me/tokens`,
            method: 'POST',
            headers: { 'Authorization': `Bearer ${sessione}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ nome: t('obsidian.token.name') }),
            throw: false,
        });
        if (resp.status === 200 && resp.json && resp.json.token) return resp.json.token;
        return null;
    }

    /**
     * Ogni chiamata a Kolibre che ha bisogno del token.
     *
     * **Il riaccesso automatico non c'è più, e non serve.** Fino al
     * 05/11/2026 qui, su un 401, il plugin rifaceva l'accesso con la
     * password salvata: era il rimedio alla scadenza dei sette giorni del
     * token di sessione, e il motivo per cui la password stava nel vault.
     * Con un token d'applicazione non c'è scadenza da compensare, quindi
     * non c'è niente da conservare — e un 401 adesso vuol dire una cosa
     * sola e vera: **quel token è stato revocato**, e va rifatto l'accesso
     * a mano. Riprovare da sé mentirebbe.
     */
    async authenticatedRequest(opts) {
        return obsidian.requestUrl({
            ...opts,
            headers: { ...(opts.headers || {}), 'Authorization': `Bearer ${this.settings.authToken}` },
            throw: false,
        });
    }

    async fetchHighlights() {
        const resp = await this.authenticatedRequest({
            url: `${this.settings.serverUrl}/api/kolibre/annotations/export`,
        });
        if (resp.status === 401) {
            throw new Error(t('obsidian.error.session_expired'));
        }
        if (resp.status !== 200) {
            throw new Error(t('obsidian.error.fetch_failed', { status: resp.status }));
        }
        return resp.json;
    }

    // ── Vault helpers ─────────────────────────────────────────────────────

    async ensureFolder(folderPath) {
        if (!folderPath) return;
        const parts = folderPath.split('/');
        let current = '';
        for (const part of parts) {
            current = current ? `${current}/${part}` : part;
            if (!this.app.vault.getAbstractFileByPath(current)) {
                try { await this.app.vault.createFolder(current); } catch (_) { /* already exists */ }
            }
        }
    }

    // ── Aggiornamento del plugin dal server ──────────────────────────────
    //
    // Stessa idea del plugin KOReader: il server sa quale versione ha in
    // casa e sa servire i file uno per uno, quindi il plugin puo'
    // riscriversi da solo invece di farsi reinstallare a mano ogni volta.
    //
    // Tre cautele, tutte per lo stesso motivo — qui si sta sovrascrivendo
    // il codice che sta girando:
    //
    // 1. si scarica TUTTO prima di scrivere QUALSIASI cosa. Una connessione
    //    che cade a meta' lascerebbe altrimenti un plugin fatto di due
    //    versioni diverse, che e' peggio di uno vecchio;
    // 2. ogni file viene confrontato con l'impronta dichiarata dal server:
    //    un download troncato arriva lo stesso come HTTP 200, e un main.js
    //    tagliato a meta' e' un plugin che non si carica piu';
    // 3. `data.json` non e' nell'elenco del server (vedi il manifest lato
    //    backend): le impostazioni di questo vault, token compreso, non si
    //    toccano.

    /** Confronta "1.2.10" e "1.3.0" come numeri, non come testo. */
    _versioneMaggiore(candidata, corrente) {
        const pezzi = (v) => String(v || '0').split('.').map((n) => parseInt(n, 10) || 0);
        const a = pezzi(candidata);
        const b = pezzi(corrente);
        for (let i = 0; i < Math.max(a.length, b.length); i++) {
            const x = a[i] || 0;
            const y = b[i] || 0;
            if (x !== y) return x > y;
        }
        return false;
    }

    async _impronta(arrayBuffer) {
        const digest = await crypto.subtle.digest('SHA-256', arrayBuffer);
        return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('');
    }

    /**
     * La versione DAVVERO installata, letta dal manifest.json sul disco.
     *
     * Non `this.manifest.version`: Obsidian tiene in memoria i manifest dei
     * plugin e li rilegge all'avvio, non quando un plugin viene spento e
     * riacceso. Dopo un auto-aggiornamento `this.manifest` resta quindi
     * quello VECCHIO — il plugin si ritrovava a credersi la versione di
     * prima, riproporre l'aggiornamento, riscaricarlo, ricaricarsi, e
     * ricominciare. Difetto riscontrato in uso: il plugin si credeva ancora
     * alla 1.0.4 e continuava ad aggiornarsi da solo.
     */
    async versioneInstallata() {
        try {
            const grezzo = await this.app.vault.adapter.read(`${this.manifest.dir}/manifest.json`);
            const v = JSON.parse(grezzo).version;
            if (v) return String(v);
        } catch (err) {
            // Manifest illeggibile: meglio quello in memoria di niente.
        }
        return this.manifest.version;
    }

    /** La versione sul server, o null se non si riesce a chiedere. */
    async versioneSulServer() {
        const url = `${this.settings.serverUrl}/api/tools/plugins/obsidian/version`;
        const resp = await obsidian.requestUrl({ url, throw: false });
        if (resp.status !== 200) throw new Error(t('obsidian.error.server_responded', { status: resp.status }));
        return resp.json && resp.json.version;
    }

    /**
     * Scarica e installa l'ultima versione. Torna la versione installata,
     * o null se non c'era niente da fare.
     */
    async aggiornaPlugin(forza = false) {
        if (!this.settings.serverUrl) throw new Error(t('obsidian.error.not_configured'));
        const base = `${this.settings.serverUrl}/api/tools/plugins/obsidian`;

        // `?lingua=`: i file che arrivano devono essere nella stessa lingua
        // di quelli installati, altrimenti l'aggiornamento riporta il plugin
        // in inglese. Un server vecchio ignora il parametro.
        const manifest = await obsidian.requestUrl({ url: `${base}/manifest?lingua=${ACTIVE_LANG}`, throw: false });
        if (manifest.status !== 200) throw new Error(t('obsidian.error.server_responded', { status: manifest.status }));
        const { version, files, checksums } = manifest.json || {};
        if (!version || !Array.isArray(files) || files.length === 0) {
            throw new Error(t('obsidian.error.invalid_file_list'));
        }
        if (!forza && !this._versioneMaggiore(version, await this.versioneInstallata())) return null;

        const scaricati = [];
        for (const rel of files) {
            const resp = await obsidian.requestUrl({ url: `${base}/file/${rel}?lingua=${ACTIVE_LANG}`, throw: false });
            if (resp.status !== 200) throw new Error(t('obsidian.error.file_fetch_failed', { file: rel, status: resp.status }));
            const dati = resp.arrayBuffer;
            const atteso = (checksums || {})[rel];
            if (atteso) {
                // La lunghezza si controlla sempre, ed e' il controllo che
                // prende il caso reale: una connessione che cade a meta'
                // consegna comunque un HTTP 200 con un corpo corto.
                if (dati.byteLength !== atteso.size) {
                    throw new Error(t('obsidian.error.incomplete_download', { file: rel, actual: dati.byteLength, expected: atteso.size }));
                }
                // L'impronta e' un controllo in piu', non l'unico: se
                // l'ambiente non offre crypto.subtle si rinuncia a questa
                // invece di rinunciare all'aggiornamento.
                if (crypto && crypto.subtle && await this._impronta(dati) !== atteso.sha256) {
                    throw new Error(t('obsidian.error.checksum_mismatch', { file: rel }));
                }
            }
            scaricati.push({ rel, dati });
        }

        // Solo adesso si scrive: da qui in poi non si torna indietro.
        const cartella = this.manifest.dir;
        for (const { rel, dati } of scaricati) {
            await this.app.vault.adapter.writeBinary(`${cartella}/${rel}`, dati);
        }
        return version;
    }

    /**
     * Il giro completo come lo vede l'utente: controlla, aggiorna, e
     * ricarica il plugin. Il ricaricamento e' l'ultima istruzione utile di
     * questa funzione: da li' in poi sta girando il codice NUOVO.
     */
    async controllaAggiornamenti(silenzioso = false) {
        try {
            const versione = await this.aggiornaPlugin();
            if (!versione) {
                if (!silenzioso) {
                    new obsidian.Notice(t('obsidian.notice.update_already_current', { version: await this.versioneInstallata() }));
                }
                return;
            }
            new obsidian.Notice(t('obsidian.notice.update_installed_reloading', { version: versione }), 6000);
            // Nota: dopo il ricaricamento `this.manifest` di Obsidian resta
            // la versione VECCHIA finche' non si riavvia Obsidian. E' per
            // questo che il confronto qui sopra legge il manifest dal disco:
            // altrimenti il plugin si riaggiornerebbe all'infinito.
            // Il ricaricamento ha un try/catch suo: i file NUOVI sono gia'
            // sul disco, quindi se fallisce l'aggiornamento e' comunque
            // riuscito e va detto cosi'. Metterlo insieme al resto farebbe
            // comparire "aggiornamento non riuscito" dopo un aggiornamento
            // perfettamente riuscito, e chi legge riproverebbe a vuoto.
            try {
                const id = this.manifest.id;
                await this.app.plugins.disablePlugin(id);
                await this.app.plugins.enablePlugin(id);
            } catch (err) {
                new obsidian.Notice(t('obsidian.notice.reload_failed', { version: versione }), 10000);
            }
        } catch (err) {
            if (!silenzioso) new obsidian.Notice(t('obsidian.notice.update_failed', { message: err.message }), 8000);
        }
    }

    // ── Core import logic ────────────────────────────────────────────────

    // ── Il racconto al server, e le istruzioni che torna ─────────────────

    /**
     * Legge i file della cartella delle note e compone il racconto.
     *
     * Si guardano **i file sul disco**, non un registro tenuto da parte: e'
     * tutto il senso della fotografia. Un file che hai cancellato non c'e',
     * e il server lo sapra'.
     */
    async raccogliLInventario() {
        const cartella = this.settings.outputFolder || 'Libri';
        const file = this.app.vault.getMarkdownFiles()
            .filter(f => f.path === cartella || f.path.startsWith(`${cartella}/`));
        const fuori = [];
        let muti = 0;
        for (const f of file) {
            const inv = inventarioDelFile(f.path, await this.app.vault.read(f));
            muti += inv.muti;
            if (inv.blocchi.length) fuori.push({ percorso: inv.percorso, blocchi: inv.blocchi });
        }
        return { file: fuori, muti };
    }

    /**
     * Racconta, e torna le istruzioni.
     *
     * **Un racconto che non va a buon fine non ferma l'importazione.** La
     * pagina restera' con la fotografia di prima, che e' un fastidio; non
     * importare le note per quel motivo sarebbe peggio. Si scrive in
     * console e si va avanti.
     */
    async mandaInventario(file, dichiarazioni) {
        const corpo = Object.assign({ file }, dichiarazioni || {});
        try {
            const resp = await this.authenticatedRequest({
                url: `${this.settings.serverUrl}/api/kolibre/appunti/inventario`,
                method: 'POST',
                contentType: 'application/json',
                body: JSON.stringify(corpo),
            });
            if (resp.status !== 200) {
                // 404: un server piu' vecchio di questo plugin, che non ha
                // ancora la pagina degli appunti. Non e' un errore da
                // mostrare, e' una versione.
                if (resp.status !== 404) {
                    console.warn('[Kolibre] Il racconto non e\' stato accettato:', resp.status);
                }
                return null;
            }
            return resp.json;
        } catch (err) {
            console.warn('[Kolibre] Il racconto non e\' partito:', err.message);
            return null;
        }
    }

    /**
     * Il comando «Importa evidenziazioni»: il giro intero.
     *
     * **Due racconti, non uno.** Il primo serve a prendere le istruzioni
     * (il server le manda nella risposta, perche' e' il momento in cui il
     * plugin sta per lavorare). Il secondo, solo se si e' scritto qualcosa,
     * serve a due cose: aggiornare la fotografia — altrimenti la pagina
     * resterebbe a com'era prima della scrittura — e **dichiarare le
     * istruzioni eseguite**, che e' quello che le spegne.
     */
    async importHighlights() {
        if (!this.settings.serverUrl || !this.settings.authToken) {
            new obsidian.Notice(t('obsidian.notice.not_configured'));
            return;
        }

        const notice = new obsidian.Notice(t('obsidian.notice.importing'), 0);
        try {
            const highlights = await this.fetchHighlights();
            if (!highlights || highlights.length === 0) {
                notice.hide();
                new obsidian.Notice(t('obsidian.notice.no_highlights_found'), 5000);
                return;
            }

            const books = groupHighlightsByBook(highlights);
            const folder = this.settings.outputFolder || 'Libri';
            await this.ensureFolder(folder);

            const primo = await this.raccogliLInventario();
            const risposta = await this.mandaInventario(primo.file);
            const istruzioni = (risposta && risposta.istruzioni) || {};
            const daNonMandare = new Set((istruzioni.non_mandare || [])
                .map(x => chiaveDelLibro(x.library, x.titolo)));
            const daRifare = new Map((istruzioni.rifai || [])
                .map(x => [chiaveDelLibro(x.library, x.titolo), x]));
            const scelte = new Map((istruzioni.conflitti || [])
                .map(x => [x.id_durevole, x.scelta]));
            const nonRimettere = new Set(istruzioni.non_rimettere || []);
            const notePerNome = new Map(highlights.map(hl => [nomeDurevole(hl), hl]));

            const newFiles = [];
            const updatedFiles = [];
            const rebuiltFiles = [];
            const rifatti = [];
            const conflittiRisolti = [];
            let totalAdded = 0;
            let totalRinnovati = 0;
            let totalRiportati = 0;
            let bloccati = 0;
            let lasciati = 0;

            for (const bookData of Object.values(books)) {
                const chiave = chiaveDelLibro(bookData.library, bookData.title);
                // «Non mandarlo» vuol dire smetti di aggiornarlo: il file
                // che c'e' resta dov'e', intoccato.
                if (daNonMandare.has(chiave)) { bloccati++; continue; }

                const template = this.settings.filenameTemplate || '{{title}}';
                const basename = applyFilenameTemplate(template, bookData);
                const filename = `${folder}/${basename}.md`;
                const existing = this.app.vault.getAbstractFileByPath(filename);
                const rifacimento = daRifare.get(chiave);
                // Il rifacimento chiesto dalla pagina riscrive il file dalle
                // note del server, tutte: e' il suo senso, e la pagina
                // avverte prima di chiederlo.
                const daScrivere = rifacimento
                    ? bookData.highlights
                    : noteDaScrivere(bookData.highlights, nonRimettere);

                // **Un file che hai cancellato non si ricrea**, se non c'e'
                // niente di nuovo da metterci dentro.
                if (!existing && !rifacimento && daScrivere.length === 0) {
                    lasciati++;
                    continue;
                }

                if (!existing || rifacimento) {
                    const content = buildNewFile({ ...bookData, highlights: daScrivere },
                                                 this.settings, basename);
                    if (existing) {
                        await this.app.vault.modify(existing, content);
                        rebuiltFiles.push({ title: bookData.title, count: daScrivere.length });
                    } else {
                        await this.app.vault.create(filename, content);
                        newFiles.push({ title: bookData.title, count: daScrivere.length });
                        totalAdded += daScrivere.length;
                    }
                    if (rifacimento) {
                        rifatti.push({
                            library: rifacimento.library,
                            calibre_book_id: rifacimento.calibre_book_id,
                        });
                        // Un file riscritto da zero porta il testo del
                        // server in ogni blocco: i conflitti di quelle note
                        // sono chiusi per costruzione, qualunque fosse la
                        // scelta.
                        for (const hl of bookData.highlights) {
                            const nome = nomeDurevole(hl);
                            if (scelte.has(nome)) conflittiRisolti.push(nome);
                        }
                    }
                    continue;
                }

                let contenuto = await this.app.vault.read(existing);
                let cambiato = false;

                if (scelte.size) {
                    const esito = applicaLeScelte(contenuto, scelte, notePerNome);
                    if (esito.risolti.length) {
                        contenuto = esito.contenuto;
                        cambiato = true;
                        conflittiRisolti.push(...esito.risolti);
                    }
                }

                // I brani cambiati solo in Kolibre si riportano senza che
                // nessuno debba decidere niente: e' il caso che si risolve
                // da se'.
                const riporto = riportaIBlocchiCambiati(contenuto, notePerNome);
                if (riporto.riportati.length) {
                    contenuto = riporto.contenuto;
                    cambiato = true;
                    totalRiportati += riporto.riportati.length;
                }

                const { content, added, rinnovati } = mergeHighlights(
                    contenuto, { ...bookData, highlights: daScrivere });
                if (added > 0 || rinnovati > 0) { contenuto = content; cambiato = true; }
                if (cambiato) await this.app.vault.modify(existing, contenuto);
                if (added > 0) {
                    updatedFiles.push({ title: bookData.title, count: added });
                    totalAdded += added;
                }
                totalRinnovati += rinnovati || 0;
            }

            const haScritto = totalAdded > 0 || rebuiltFiles.length > 0
                || totalRinnovati > 0 || conflittiRisolti.length > 0
                || totalRiportati > 0;
            if (haScritto || rifatti.length) {
                const secondo = await this.raccogliLInventario();
                await this.mandaInventario(secondo.file, {
                    rifatti,
                    conflitti_risolti: conflittiRisolti,
                });
            }

            notice.hide();
            if (!haScritto) {
                new obsidian.Notice(t('obsidian.notice.nothing_new'), 5000);
            } else {
                new ImportSummaryModal(this.app, {
                    newFiles, updatedFiles, rebuiltFiles, totalAdded,
                    renewed: totalRinnovati, resolved: conflittiRisolti.length,
                    carried: totalRiportati, blocked: bloccati, left: lasciati,
                }).open();
            }
        } catch (err) {
            notice.hide();
            new obsidian.Notice(t('obsidian.notice.generic_error', { message: err.message }), 10000);
            console.error('[Kolibre] Import error:', err);
        }
    }

    /**
     * Entry point for the destructive command — only ever shows the
     * confirmation, never touches the vault itself. See ConfirmModal and
     * _runFullReimport (the part that actually writes files, only reached
     * from the modal's own confirm button).
     */
    async reimportAllHighlights() {
        if (!this.settings.serverUrl || !this.settings.authToken) {
            new obsidian.Notice(t('obsidian.notice.not_configured'));
            return;
        }
        new ConfirmModal(this.app, {
            title: t('obsidian.reimport.title'),
            message: t('obsidian.reimport.message'),
            confirmText: t('obsidian.reimport.confirm_button'),
            onConfirm: () => this._runFullReimport(),
        }).open();
    }

    /**
     * Unlike importHighlights, always rebuilds each book's file from
     * scratch with buildNewFile() and always vault.modify()/create()s it —
     * mergeHighlights (which preserves hand-written content) is never
     * called here on purpose, that's the whole point of this command. The
     * <!-- kolibre-hl:ID --> markers buildNewFile still writes mean a
     * later regular "Importa evidenziazioni" run keeps working correctly
     * (dedup by marker) on the files this just rewrote.
     */
    async _runFullReimport() {
        const notice = new obsidian.Notice(t('obsidian.notice.full_reimporting'), 0);
        try {
            const highlights = await this.fetchHighlights();
            if (!highlights || highlights.length === 0) {
                notice.hide();
                new obsidian.Notice(t('obsidian.notice.no_highlights_found'), 5000);
                return;
            }

            const books = groupHighlightsByBook(highlights);
            const folder = this.settings.outputFolder || 'Libri';
            await this.ensureFolder(folder);

            // **Anche qui i libri bloccati si lasciano stare.** «Non
            // mandarlo» e' una regola sui dati decisa dalla pagina, non una
            // preferenza di questo comando: un comando che la scavalca
            // riscriverebbe proprio il file che era stato messo al riparo.
            const risposta = await this.mandaInventario((await this.raccogliLInventario()).file);
            const istruzioni = (risposta && risposta.istruzioni) || {};
            const daNonMandare = new Set((istruzioni.non_mandare || [])
                .map(x => chiaveDelLibro(x.library, x.titolo)));

            const newFiles = [];
            const rifatti = [];
            const conflittiRisolti = [];
            let totalAdded = 0;
            let bloccati = 0;

            const daRifare = new Map((istruzioni.rifai || [])
                .map(x => [chiaveDelLibro(x.library, x.titolo), x]));
            const scelte = new Set((istruzioni.conflitti || []).map(x => x.id_durevole));

            for (const bookData of Object.values(books)) {
                const chiave = chiaveDelLibro(bookData.library, bookData.title);
                if (daNonMandare.has(chiave)) { bloccati++; continue; }

                const template = this.settings.filenameTemplate || '{{title}}';
                const basename = applyFilenameTemplate(template, bookData);
                const filename = `${folder}/${basename}.md`;
                const existing = this.app.vault.getAbstractFileByPath(filename);
                const content = buildNewFile(bookData, this.settings, basename);

                if (existing) {
                    await this.app.vault.modify(existing, content);
                } else {
                    await this.app.vault.create(filename, content);
                }
                newFiles.push({ title: bookData.title, count: bookData.highlights.length });
                totalAdded += bookData.highlights.length;

                // Questo comando fa quello che il rifacimento chiesto dalla
                // pagina chiedeva, e di piu': l'istruzione e' eseguita, e i
                // conflitti di quelle note sono chiusi per costruzione.
                const rifacimento = daRifare.get(chiave);
                if (rifacimento) {
                    rifatti.push({ library: rifacimento.library,
                                   calibre_book_id: rifacimento.calibre_book_id });
                }
                for (const hl of bookData.highlights) {
                    const nome = nomeDurevole(hl);
                    if (scelte.has(nome)) conflittiRisolti.push(nome);
                }
            }

            await this.mandaInventario((await this.raccogliLInventario()).file, {
                rifatti, conflitti_risolti: conflittiRisolti,
            });

            notice.hide();
            new ImportSummaryModal(this.app, {
                newFiles, updatedFiles: [], totalAdded,
                resolved: conflittiRisolti.length, blocked: bloccati,
            }).open();
        } catch (err) {
            notice.hide();
            new obsidian.Notice(t('obsidian.notice.generic_error', { message: err.message }), 10000);
            console.error('[Kolibre] Full reimport error:', err);
        }
    }
}

module.exports = KolibreHighlightsPlugin;
