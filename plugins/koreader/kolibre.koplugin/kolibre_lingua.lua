--[[--
Kolibre's own translation layer for this plugin's user-visible text.

NOT KOReader's `gettext` (require("gettext")): that follows KOReader's own
language setting, which is independent of — and may well differ from —
whatever language the Kolibre SERVER/account is set to. Every other Kolibre
surface (web UI, the other two plugins) follows the Kolibre language, so this
plugin does too, via its own tiny mechanism instead.

Usage: local t = require("kolibre_lingua").t
       t("koreader.menu.catalog")                    -- plain lookup
       t("koreader.catalog.downloaded", {filename=x}) -- {name} interpolation
       t("koreader.common.book_count", {count=n})     -- plural (see below)

Keys are flat, English, dot-separated, prefixed "koreader." (this plugin's
namespace) — e.g. "koreader.sync.failed". `it` is the starting/reference
language (this plugin's source language); `en` carries the same keys.

Plural entries hold TWO forms in one catalog string, separated by " | "
(space-bar-space): "{count} libro | {count} libri". t() picks the first form
when values.count == 1, the second otherwise (0 counts as plural, same as in
ordinary speech). A non-plural entry has no " | " and is used as-is.

Kept as flat Lua tables (no nested structures, no runtime catalog merging) on
purpose — this plugin runs on slow, memory-constrained e-ink readers; two flat
string-keyed tables loaded once at require-time is the cheapest shape that
works.
]]

local KolibreLingua = {}

-- ── Lingua attiva ──
--
-- PUNTO UNICO in cui si decide quale catalogo usare. Oggi fissato a "it" di
-- proposito (valore di partenza, come richiesto) — la propagazione dal server
-- (impostazione dell'account Kolibre, inoltrata al device nell'handshake di
-- sync o altrove) si collega QUI, sostituendo l'assegnazione sottostante con
-- la lettura di quel valore. Nessun altro punto di questo modulo, né alcun
-- chiamante in main.lua/kolibre_catalog.lua/kolibre_catalog_widgets.lua, deve
-- sapere come quel valore arriva: tutti passano per KolibreLingua.t().
local active_lang = "it"

-- ── Catalogo italiano (lingua di riferimento) ──
local it = {
    -- menu principale
    ["koreader.menu.title"] = "Kolibre",
    ["koreader.menu.sync_all"] = "Sincronizza tutto",
    ["koreader.menu.check_new_books"] = "Controlla libri nuovi",
    ["koreader.menu.catalog"] = "Catalogo",
    ["koreader.menu.tools"] = "Strumenti",
    ["koreader.menu.settings"] = "Impostazioni",
    ["koreader.menu.automations"] = "Automazioni",

    -- impostazioni
    ["koreader.settings.connection"] = "Connessione al server...",
    ["koreader.settings.test_connection"] = "Test connessione",
    ["koreader.settings.check_update"] = "Controlla aggiornamenti plugin",
    ["koreader.settings.info"] = "Info: Kolibre v{version}",
    ["koreader.settings.dialog_title"] = "Kolibre — Impostazioni di sync",
    ["koreader.settings.field_server_url"] = "URL server (es. http://192.168.1.10:8081)",
    ["koreader.settings.field_device_token"] = "Token dispositivo (da Impostazioni → Dispositivi sul server)",
    ["koreader.settings.field_books_dir"] = "Cartella libri locale",
    ["koreader.settings.saved"] = "Impostazioni salvate.",
    ["koreader.settings.test_failed"] = "Connessione fallita: {error}",
    ["koreader.settings.test_ok"] = "Connesso come dispositivo: {name}",

    -- posizione di lettura
    ["koreader.position.push_current"] = "Invia posizione libro corrente",
    ["koreader.position.pull_current"] = "Scarica posizione libro corrente",
    ["koreader.position.sync_all"] = "Sincronizza tutte le posizioni",
    ["koreader.position.no_document_push"] = "Apri un libro per inviare la sua posizione di lettura.",
    ["koreader.position.push_sent"] = "Posizione di lettura inviata.",
    ["koreader.position.push_failed"] = "Invio posizione fallito: {error}",
    ["koreader.position.no_document_pull"] = "Apri un libro per scaricare la sua posizione di lettura.",
    ["koreader.position.pull_failed"] = "Recupero posizione fallito: {error}",
    ["koreader.position.nothing_to_sync"] = "Nessuna posizione da sincronizzare da altri dispositivi.",
    ["koreader.position.already_synced"] = "La posizione è già sincronizzata.",
    ["koreader.position.synced"] = "Posizione sincronizzata.",
    ["koreader.position.sync_confirm"] = "Sincronizzare alla posizione {percent}%, salvata dal dispositivo '{device}'?",
    ["koreader.position.comparing_progress"] = "Confronto posizioni: {done} di {total}…",
    ["koreader.position.pull_all_done"] = "{count} posizione scaricata. | {count} posizioni scaricate.",
    ["koreader.position.push_all_done"] = "{count} posizione inviata. | {count} posizioni inviate.",
    ["koreader.position.push_all_confirm"] = "{count} libro ha una posizione di lettura locale non ancora inviata a Kolibre. Inviarla? | {count} libri hanno una posizione di lettura locale non ancora inviata a Kolibre. Inviarla?",
    ["koreader.position.pull_all_confirm"] = "{count} libro ha una posizione di lettura più recente su un altro dispositivo. Scaricarla? | {count} libri hanno una posizione di lettura più recente su un altro dispositivo. Scaricarla?",

    -- annotazioni
    ["koreader.annotations.push_all_full"] = "Pusha tutte le annotazioni (rilettura completa)",
    ["koreader.annotations.sync_failed"] = "Sync annotazioni fallita.",
    ["koreader.annotations.push_summary"] = "Annotazioni: {created} nuove, {updated} aggiornate.",
    ["koreader.annotations.push_summary_orphaned"] = " {count} importate da libri non ancora accoppiati (Dispositivi ▸ Da rivedere).",
    ["koreader.annotations.push_summary_unresolved"] = " {count} scartate.",
    ["koreader.annotations.nothing_to_sync"] = "Nessuna annotazione da sincronizzare.",
    ["koreader.annotations.sending_to_server"] = "Invio annotazioni al server",
    ["koreader.annotations.sync_interrupted"] = "Sync annotazioni interrotta dopo {sent} di {total} (rete instabile?). Riprova per completare.",
    ["koreader.annotations.batch_progress"] = "{label} ({sent}/{total}, gruppo {batch_num}/{batch_count})…",

    -- backup
    ["koreader.backup.run_now"] = "Esegui backup ora",
    ["koreader.backup.reminder_menu"] = "Promemoria backup",
    ["koreader.backup.summary"] = "Backup completato: {uploaded} file caricati, {skipped} già aggiornati, {failed} falliti.",
    ["koreader.backup.reminder_days"] = "Ogni {days} giorni",
    ["koreader.backup.reminder_never"] = "Mai",
    ["koreader.backup.reminder_prompt"] = "Sono passati più di {days} giorni dall'ultimo backup Kolibre. Eseguirlo ora?",

    -- resetta a stato di dispositivo
    ["koreader.restore.menu"] = "Resetta a stato di dispositivo...",
    ["koreader.restore.no_other_device"] = "Nessun altro dispositivo trovato sul server: {error}",
    ["koreader.restore.none_registered"] = "nessuno registrato",
    ["koreader.restore.choose_source"] = "Scegli il dispositivo sorgente",
    ["koreader.restore.request_confirm"] = "Richiedere il ripristino dello stato locale (statistiche, dizionario, impostazioni reader) dal backup di '{device}'?\n\nServirà anche una conferma da parte di un amministratore sul sito web prima che l'operazione diventi effettiva.",
    ["koreader.restore.request_failed"] = "Richiesta fallita: {error}",
    ["koreader.restore.request_sent"] = "Richiesta inviata. Conferma sul sito web per procedere — al prossimo avvio o sincronizzazione riceverai l'ultima conferma qui sul dispositivo.",
    ["koreader.restore.migration_confirmed_title"] = "Migrazione dati confermata",
    ["koreader.restore.migration_confirmed_body"] = "Migrazione confermata dal server: procedere a migrare i dati dal dispositivo '{device}'?",
    ["koreader.restore.migrate_now"] = "Migra ora",
    ["koreader.restore.overwrite_confirm"] = "Questa operazione SOVRASCRIVE lo stato locale di questo dispositivo (statistiche, dizionario, impostazioni reader) con quello del backup di '{device}'. Procedere?",
    ["koreader.restore.overwrite_and_migrate"] = "Sovrascrivi e migra",
    ["koreader.restore.result"] = "Migrazione completata: {applied} file applicati, {missing} non presenti nel backup sorgente.",

    -- aggiornamento plugin
    ["koreader.update.check_failed"] = "Controllo aggiornamenti fallito: {error}",
    ["koreader.update.already_updated"] = "Kolibre è già aggiornato (v{version}).",
    ["koreader.update.available"] = "È disponibile Kolibre v{version} (versione attuale: v{current}). Scaricare e installare ora?",
    ["koreader.update.resumed"] = "Un aggiornamento Kolibre (v{version}) interrotto in precedenza è stato completato all'avvio.",
    ["koreader.update.resume_incomplete"] = "Aggiornamento Kolibre a v{version} incompleto (file: {file}). Verrà ritentato automaticamente al prossimo avvio di KOReader.",
    ["koreader.update.manifest_failed"] = "Aggiornamento fallito: manifest non disponibile: {error}",
    ["koreader.update.file_failed"] = "Aggiornamento fallito (file {file}): {error}",
    ["koreader.update.stage_failed"] = "Aggiornamento fallito: impossibile preparare l'installazione.",
    ["koreader.update.partial"] = "Aggiornamento parzialmente applicato (errore su {file}). Riavvia KOReader: il completamento verrà ritentato automaticamente.",
    ["koreader.update.done"] = "Kolibre aggiornato a v{version}. Riavvia KOReader per applicare le modifiche.",

    -- dizionario
    ["koreader.dictionary.download_menu"] = "Scarica dizionario italiano sul dispositivo",
    ["koreader.dictionary.unavailable"] = "Dizionario non disponibile sul server — installalo prima da Impostazioni → Integrazioni → Dizionari.",
    ["koreader.dictionary.download_failed"] = "Download dizionario fallito (file {file}): {error}",
    ["koreader.dictionary.done"] = "Dizionario italiano scaricato. Da ora KOReader lo userà anche per la ricerca durante la lettura (tieni premuto su una parola).",

    -- sync (protocollo v2)
    ["koreader.sync.migration_scanning"] = "Riconoscimento libri già presenti: {count} esaminati…",
    ["koreader.sync.removing_progress"] = "Rimozione in corso: {done} di {total}…",
    ["koreader.sync.removal_confirm"] = "Kolibre richiede la rimozione di {count} libri:\n\n{list}\n\nRimuoverli ora?",
    ["koreader.sync.removal_pending"] = "Kolibre: {count} rimozioni in attesa di conferma — apri \"Sincronizza tutto\".",
    ["koreader.sync.downloads_pending"] = "Kolibre: {count} libri in consegna in attesa di conferma — apri \"Sincronizza tutto\".",
    ["koreader.sync.first_sync_confirm"] = "Prima sincronizzazione: Kolibre analizzerà i libri già presenti sul dispositivo per riconoscerli — nessun libro nuovo viene scaricato in questo passaggio. Su librerie grandi può richiedere qualche minuto. Continuare?",
    ["koreader.sync.skip_for_now"] = "Salta per ora",
    ["koreader.sync.checking_new_books"] = "Kolibre: controllo libri nuovi...",
    ["koreader.sync.in_progress"] = "Kolibre: sincronizzazione in corso...",
    ["koreader.sync.phase_handshake"] = "Handshake",
    ["koreader.sync.already_running"] = "Kolibre: un'altra sincronizzazione è già in corso per questo dispositivo. Riprova tra qualche minuto.",
    ["koreader.sync.failed"] = "Sync fallita: {error}",
    ["koreader.sync.protocol_unsupported"] = "Sync fallita: il server non supporta il protocollo v2. Aggiorna il server Kolibre.",
    ["koreader.sync.phase_pending_actions"] = "Azioni in sospeso",
    ["koreader.sync.phase_removals"] = "Rimozioni",
    ["koreader.sync.phase_pages"] = "Conteggio pagine",
    ["koreader.sync.phase_notes_positions_backup"] = "Note, posizioni e backup",
    ["koreader.sync.phase_download_books"] = "Download libri",
    ["koreader.sync.summary_books_only"] = "Libri: {downloaded} scaricati, {deleted} rimossi, {deferred} rimozioni rinviate, {errors} errori.",
    ["koreader.sync.summary_full"] = "Sync completata: {downloaded} scaricati, {deleted} rimossi, {deferred} rimozioni rinviate, {pages} conteggi pagine inviati, {errors} errori.",
    ["koreader.sync.downloads_confirm"] = "Kolibre ha {count} libri pronti per essere scaricati:\n\n{list}\n\nScaricarli ora?",

    -- libri gestiti
    ["koreader.managed_books.menu_title"] = "Libri gestiti da Kolibre",
    ["koreader.managed_books.pages_count"] = "{count} pag.",
    ["koreader.managed_books.empty"] = "Nessun libro gestito da Kolibre su questo dispositivo.",
    ["koreader.managed_books.detail_title"] = "Titolo: {value}",
    ["koreader.managed_books.detail_author"] = "Autore: {value}",
    ["koreader.managed_books.detail_format"] = "Formato: {value}",
    ["koreader.managed_books.detail_pages"] = "Pagine: {value}",
    ["koreader.managed_books.detail_downloaded_at"] = "Scaricato il: {value}",
    ["koreader.managed_books.detail_file"] = "File: {value}",
    ["koreader.managed_books.remove_confirm_ok"] = "Rimuovi da questo dispositivo",
    ["koreader.managed_books.removed_notice"] = "Libro rimosso. Il server verrà informato alla prossima sincronizzazione.",
    ["koreader.managed_books.remove_failed"] = "Rimozione fallita: {error}",

    -- inizializza libreria (cerca libri non accoppiati)
    ["koreader.library_init.menu"] = "Inizializza libreria (cerca libri non accoppiati)",
    ["koreader.library_init.confirm"] = "Verranno esaminati tutti i libri presenti su questo dispositivo per trovare quelli non ancora gestiti da Kolibre. Su librerie molto grandi può richiedere qualche minuto. Procedere?",
    ["koreader.library_init.scanning_progress"] = "Analisi libreria: {count} file esaminati…",
    ["koreader.library_init.nothing_new"] = "Nessun libro nuovo da esaminare: tutti i libri sul dispositivo sono già gestiti da Kolibre.",
    ["koreader.library_init.comparing"] = "Confronto con il server…",
    ["koreader.library_init.compare_failed"] = "Confronto con il server fallito: {error}",
    ["koreader.library_init.skip_for_now"] = "Ignora per ora",
    ["koreader.library_init.multi_library_title"] = "'{name}' è presente in più biblioteche",
    ["koreader.library_init.which_library"] = "A quale biblioteca vuoi fare riferimento?",
    ["koreader.library_init.hash_match_confirm"] = "Trovato {count} libro già presente su Kolibre (stesso file):\n\n{list}\n\nCollegarlo? | Trovati {count} libri già presenti su Kolibre (stesso file):\n\n{list}\n\nCollegarli?",
    ["koreader.library_init.hash_linked"] = "{count} libro collegato. Verrà confermato alla prossima sincronizzazione. | {count} libri collegati. Verranno confermati alla prossima sincronizzazione.",
    ["koreader.library_init.nothing_else"] = "Nessun altro libro da esaminare: la libreria del dispositivo è già in linea con Kolibre.",
    ["koreader.library_init.searching_matches"] = "Ricerca corrispondenze: 0 di {total}…",
    ["koreader.library_init.checking_content"] = "Verifica contenuto: {done} di {total}…",
    ["koreader.library_init.ambiguous_title"] = "'{name}': più corrispondenze possibili",
    ["koreader.library_init.flagged_notice"] = "\n\n{count} libro con note o lettura in corso è stato aggiunto all'elenco \"da rivedere\" su Kolibre, senza alcuna modifica in locale. | \n\n{count} libri con note o lettura in corso sono stati aggiunti all'elenco \"da rivedere\" su Kolibre, senza alcuna modifica in locale.",
    ["koreader.library_init.overwrite_confirm"] = "Trovato {count} libro mai aperto che sembra corrispondere a un libro su Kolibre:\n\n{list}\n\nSovrascriverlo con la versione di Kolibre?{notice} | Trovati {count} libri mai aperti che sembrano corrispondere a un libro su Kolibre:\n\n{list}\n\nSovrascriverli con la versione di Kolibre?{notice}",
    ["koreader.library_init.overwriting_progress"] = "Sovrascrittura: {done} di {total}…",
    ["koreader.library_init.no_candidate_title"] = "Nessuna corrispondenza su Kolibre",
    ["koreader.library_init.no_candidate_detail"] = "File: {path}\n\nNessun libro corrispondente trovato su Kolibre.",
    ["koreader.library_init.delete_from_device"] = "Elimina dal dispositivo",
    ["koreader.library_init.deleted_notice"] = "Eliminato.",
    ["koreader.library_init.auto_paired"] = "{migrated} note ricollegate automaticamente a {count} libro. | {migrated} note ricollegate automaticamente a {count} libri.",

    -- catalogo
    ["koreader.catalog.label"] = "Catalogo",
    ["koreader.catalog.title"] = "Catalogo Kolibre",
    ["koreader.catalog.section_author"] = "Autore",
    ["koreader.catalog.section_series"] = "Serie",
    ["koreader.catalog.section_tag"] = "Tag",
    ["koreader.catalog.downloaded"] = "Scaricato: {filename}",
    ["koreader.catalog.download_failed"] = "Download fallito: {error}",
    ["koreader.catalog.info_title"] = "Titolo: {title}",
    ["koreader.catalog.info_author"] = "Autore: {author}",
    ["koreader.catalog.unknown_author"] = "Sconosciuto",
    ["koreader.catalog.unknown_author_item"] = "Autore sconosciuto",
    ["koreader.catalog.info_format"] = "Formato: {format}",
    ["koreader.catalog.info_size"] = "Peso: {size}",
    ["koreader.catalog.download_button"] = "Scarica sul dispositivo",
    ["koreader.catalog.download_confirm"] = "Scaricare '{title}'?",
    ["koreader.catalog.view_grid"] = "Vista: Griglia",
    ["koreader.catalog.view_list"] = "Vista: Lista",
    ["koreader.catalog.sort_author"] = "Ordina: Per autore",
    ["koreader.catalog.sort_recent"] = "Ordina: Aggiunti di recente",
    ["koreader.catalog.browse_by"] = "Sfoglia per {section}",
    ["koreader.catalog.unavailable"] = "Catalogo non disponibile: {error}",
    ["koreader.catalog.recent"] = "Aggiunti di recente",
    ["koreader.catalog.title_by_author"] = "Per autore",
    ["koreader.catalog.not_on_device"] = "non sul device",
    ["koreader.catalog.search_title"] = "Cerca nel catalogo",
    ["koreader.catalog.search_hint"] = "Titolo o autore...",
    ["koreader.catalog.section_total"] = "{count} totale | {count} totali",
    ["koreader.catalog.section_list_unavailable"] = "Elenco non disponibile: {error}",
    ["koreader.catalog.no_library"] = "Nessuna libreria disponibile: {error}",
    ["koreader.catalog.choose_library"] = "Scegli libreria",
    ["koreader.catalog.discover"] = "Da scoprire",
    ["koreader.catalog.browse_library"] = "Sfoglia la libreria",
    ["koreader.catalog.recent_unavailable"] = "Aggiunti di recente non disponibili: {error}",
    ["koreader.catalog.discover_unavailable"] = "Suggerimenti non disponibili: {error}",
    ["koreader.catalog.all_books"] = "Tutti i libri",
    ["koreader.catalog.not_on_device_item"] = "Non sul device",
    ["koreader.catalog.change_library"] = "Cambia libreria",
    ["koreader.catalog.browse_menu_title"] = "Sfoglia",
    ["koreader.catalog.page_load_failed"] = "Impossibile caricare la pagina: {error}",
    ["koreader.catalog.empty"] = "Nessun libro.",
    ["koreader.catalog.untitled"] = "Senza titolo",
    ["koreader.catalog.cover_loading"] = "Copertina in caricamento",
    ["koreader.catalog.cover_failed"] = "Copertina non disponibile",
    ["koreader.catalog.cover_none"] = "Nessuna copertina",

    -- automazioni
    ["koreader.automation.moment_startup"] = "All'avvio (e al risveglio)",
    ["koreader.automation.moment_open"] = "Apertura di un libro",
    ["koreader.automation.moment_close"] = "Chiusura di un libro",
    ["koreader.automation.moment_shutdown"] = "Spegnimento del dispositivo",
    ["koreader.automation.action_sync_books"] = "Controlla solo libri nuovi",
    ["koreader.automation.action_backup"] = "Carica backup",
    ["koreader.automation.action_push_annot"] = "Pusha annotazioni",
    ["koreader.automation.action_push_pos_all"] = "Invia tutte le posizioni (più lento)",
    ["koreader.automation.action_pull_pos_all"] = "Scarica tutte le posizioni (più lento)",
    ["koreader.automation.auto_check_updates"] = "Controlla aggiornamenti plugin automaticamente",

    -- info dialog (Impostazioni ▸ Info)
    ["koreader.info.policy_auto"] = "automatica (il server rimuove senza chiedere)",
    ["koreader.info.policy_ask"] = "con conferma (un'unica richiesta cumulativa)",
    ["koreader.info.policy_never"] = "mai (il server non richiede rimozioni)",
    ["koreader.info.policy_unknown"] = "(sconosciuta — esegui una sync)",
    ["koreader.info.last_sync_never"] = "mai",
    ["koreader.info.body"] = "Kolibre v{version}\n\nServer: {server}\nUltima sincronizzazione: {last_sync}\nLibri gestiti: {count}\nPolicy di rimozione: {policy}",

    -- dispatcher (azioni assegnabili a gesti/scorciatoie)
    ["koreader.dispatcher.push_progress"] = "Kolibre: invia posizione di lettura",
    ["koreader.dispatcher.pull_progress"] = "Kolibre: scarica posizione di lettura",

    -- lessico comune, riusato in più punti
    ["koreader.common.not_configured"] = "(non configurato)",
    ["koreader.common.not_configured_message"] = "Configura prima URL server e token in Impostazioni sync.",
    ["koreader.common.unreachable"] = "Server non raggiungibile: {error}",
    ["koreader.common.close"] = "Chiudi",
    ["koreader.common.cancel"] = "Annulla",
    ["koreader.common.save"] = "Salva",
    ["koreader.common.search"] = "Cerca",
    ["koreader.common.more"] = "Altro…",
    ["koreader.common.start"] = "Avvia",
    ["koreader.common.link"] = "Collega",
    ["koreader.common.ignore"] = "Ignora",
    ["koreader.common.none_of_these"] = "Nessuna di queste",
    ["koreader.common.overwrite"] = "Sovrascrivi",
    ["koreader.common.leave_as_is"] = "Lascia così",
    ["koreader.common.remove"] = "Rimuovi",
    ["koreader.common.not_now"] = "Non ora",
    ["koreader.common.continue"] = "Continua",
    ["koreader.common.request"] = "Richiedi",
    ["koreader.common.later"] = "Più tardi",
    ["koreader.common.send"] = "Invia",
    ["koreader.common.download"] = "Download",
    ["koreader.common.download_verb"] = "Scarica",
    ["koreader.common.book_count"] = "{count} libro | {count} libri",
}

-- ── Catalogo inglese ──
local en = {
    -- main menu
    ["koreader.menu.title"] = "Kolibre",
    ["koreader.menu.sync_all"] = "Sync everything",
    ["koreader.menu.check_new_books"] = "Check for new books",
    ["koreader.menu.catalog"] = "Catalog",
    ["koreader.menu.tools"] = "Tools",
    ["koreader.menu.settings"] = "Settings",
    ["koreader.menu.automations"] = "Automations",

    -- settings
    ["koreader.settings.connection"] = "Server connection...",
    ["koreader.settings.test_connection"] = "Test connection",
    ["koreader.settings.check_update"] = "Check for plugin updates",
    ["koreader.settings.info"] = "Info: Kolibre v{version}",
    ["koreader.settings.dialog_title"] = "Kolibre — Sync settings",
    ["koreader.settings.field_server_url"] = "Server URL (e.g. http://192.168.1.10:8081)",
    ["koreader.settings.field_device_token"] = "Device token (from Settings → Devices on the server)",
    ["koreader.settings.field_books_dir"] = "Local books folder",
    ["koreader.settings.saved"] = "Settings saved.",
    ["koreader.settings.test_failed"] = "Connection failed: {error}",
    ["koreader.settings.test_ok"] = "Connected as device: {name}",

    -- reading position
    ["koreader.position.push_current"] = "Send current book's position",
    ["koreader.position.pull_current"] = "Download current book's position",
    ["koreader.position.sync_all"] = "Sync all positions",
    ["koreader.position.no_document_push"] = "Open a book to send its reading position.",
    ["koreader.position.push_sent"] = "Reading position sent.",
    ["koreader.position.push_failed"] = "Sending position failed: {error}",
    ["koreader.position.no_document_pull"] = "Open a book to download its reading position.",
    ["koreader.position.pull_failed"] = "Retrieving position failed: {error}",
    ["koreader.position.nothing_to_sync"] = "No position to sync from other devices.",
    ["koreader.position.already_synced"] = "The position is already synced.",
    ["koreader.position.synced"] = "Position synced.",
    ["koreader.position.sync_confirm"] = "Sync to position {percent}%, saved by device '{device}'?",
    ["koreader.position.comparing_progress"] = "Comparing positions: {done} of {total}…",
    ["koreader.position.pull_all_done"] = "{count} position downloaded. | {count} positions downloaded.",
    ["koreader.position.push_all_done"] = "{count} position sent. | {count} positions sent.",
    ["koreader.position.push_all_confirm"] = "{count} book has a local reading position not yet sent to Kolibre. Send it? | {count} books have a local reading position not yet sent to Kolibre. Send them?",
    ["koreader.position.pull_all_confirm"] = "{count} book has a more recent reading position on another device. Download it? | {count} books have a more recent reading position on another device. Download them?",

    -- highlights
    ["koreader.annotations.push_all_full"] = "Push all highlights (full rescan)",
    ["koreader.annotations.sync_failed"] = "Highlights sync failed.",
    ["koreader.annotations.push_summary"] = "Highlights: {created} new, {updated} updated.",
    ["koreader.annotations.push_summary_orphaned"] = " {count} imported from books not yet paired (Devices ▸ To review).",
    ["koreader.annotations.push_summary_unresolved"] = " {count} discarded.",
    ["koreader.annotations.nothing_to_sync"] = "No highlights to sync.",
    ["koreader.annotations.sending_to_server"] = "Sending highlights to the server",
    ["koreader.annotations.sync_interrupted"] = "Highlights sync interrupted after {sent} of {total} (unstable network?). Retry to finish.",
    ["koreader.annotations.batch_progress"] = "{label} ({sent}/{total}, batch {batch_num}/{batch_count})…",

    -- backup
    ["koreader.backup.run_now"] = "Run backup now",
    ["koreader.backup.reminder_menu"] = "Backup reminder",
    ["koreader.backup.summary"] = "Backup complete: {uploaded} files uploaded, {skipped} already up to date, {failed} failed.",
    ["koreader.backup.reminder_days"] = "Every {days} days",
    ["koreader.backup.reminder_never"] = "Never",
    ["koreader.backup.reminder_prompt"] = "More than {days} days have passed since the last Kolibre backup. Run it now?",

    -- reset to another device's state
    ["koreader.restore.menu"] = "Reset to another device's state...",
    ["koreader.restore.no_other_device"] = "No other device found on the server: {error}",
    ["koreader.restore.none_registered"] = "none registered",
    ["koreader.restore.choose_source"] = "Choose the source device",
    ["koreader.restore.request_confirm"] = "Request restoring the local state (statistics, dictionary, reader settings) from '{device}''s backup?\n\nAn administrator will also need to confirm this on the website before it takes effect.",
    ["koreader.restore.request_failed"] = "Request failed: {error}",
    ["koreader.restore.request_sent"] = "Request sent. Confirm it on the website to proceed — at the next startup or sync you'll get the final confirmation here on the device.",
    ["koreader.restore.migration_confirmed_title"] = "Data migration confirmed",
    ["koreader.restore.migration_confirmed_body"] = "Migration confirmed by the server: proceed to migrate data from device '{device}'?",
    ["koreader.restore.migrate_now"] = "Migrate now",
    ["koreader.restore.overwrite_confirm"] = "This operation OVERWRITES this device's local state (statistics, dictionary, reader settings) with the one from '{device}''s backup. Proceed?",
    ["koreader.restore.overwrite_and_migrate"] = "Overwrite and migrate",
    ["koreader.restore.result"] = "Migration complete: {applied} files applied, {missing} not present in the source backup.",

    -- plugin update
    ["koreader.update.check_failed"] = "Update check failed: {error}",
    ["koreader.update.already_updated"] = "Kolibre is already up to date (v{version}).",
    ["koreader.update.available"] = "Kolibre v{version} is available (current version: v{current}). Download and install now?",
    ["koreader.update.resumed"] = "A previously interrupted Kolibre update (v{version}) was completed at startup.",
    ["koreader.update.resume_incomplete"] = "Kolibre update to v{version} incomplete (file: {file}). It will be retried automatically at the next KOReader startup.",
    ["koreader.update.manifest_failed"] = "Update failed: manifest unavailable: {error}",
    ["koreader.update.file_failed"] = "Update failed (file {file}): {error}",
    ["koreader.update.stage_failed"] = "Update failed: could not prepare the installation.",
    ["koreader.update.partial"] = "Update partially applied (error on {file}). Restart KOReader: completion will be retried automatically.",
    ["koreader.update.done"] = "Kolibre updated to v{version}. Restart KOReader to apply the changes.",

    -- dictionary
    ["koreader.dictionary.download_menu"] = "Download Italian dictionary to the device",
    ["koreader.dictionary.unavailable"] = "Dictionary not available on the server — install it first from Settings → Integrations → Dictionaries.",
    ["koreader.dictionary.download_failed"] = "Dictionary download failed (file {file}): {error}",
    ["koreader.dictionary.done"] = "Italian dictionary downloaded. KOReader will now also use it for lookups while reading (long-press a word).",

    -- sync (protocol v2)
    ["koreader.sync.migration_scanning"] = "Recognizing books already present: {count} examined…",
    ["koreader.sync.removing_progress"] = "Removing: {done} of {total}…",
    ["koreader.sync.removal_confirm"] = "Kolibre is requesting the removal of {count} books:\n\n{list}\n\nRemove them now?",
    ["koreader.sync.removal_pending"] = "Kolibre: {count} removals awaiting confirmation — open \"Sync everything\".",
    ["koreader.sync.downloads_pending"] = "Kolibre: {count} books ready for delivery awaiting confirmation — open \"Sync everything\".",
    ["koreader.sync.first_sync_confirm"] = "First sync: Kolibre will analyze the books already on the device to recognize them — no new book is downloaded in this step. On large libraries this can take a few minutes. Continue?",
    ["koreader.sync.skip_for_now"] = "Skip for now",
    ["koreader.sync.checking_new_books"] = "Kolibre: checking for new books...",
    ["koreader.sync.in_progress"] = "Kolibre: syncing...",
    ["koreader.sync.phase_handshake"] = "Handshake",
    ["koreader.sync.already_running"] = "Kolibre: another sync is already running for this device. Try again in a few minutes.",
    ["koreader.sync.failed"] = "Sync failed: {error}",
    ["koreader.sync.protocol_unsupported"] = "Sync failed: the server doesn't support protocol v2. Update the Kolibre server.",
    ["koreader.sync.phase_pending_actions"] = "Pending actions",
    ["koreader.sync.phase_removals"] = "Removals",
    ["koreader.sync.phase_pages"] = "Page count",
    ["koreader.sync.phase_notes_positions_backup"] = "Highlights, positions and backup",
    ["koreader.sync.phase_download_books"] = "Downloading books",
    ["koreader.sync.summary_books_only"] = "Books: {downloaded} downloaded, {deleted} removed, {deferred} removals deferred, {errors} errors.",
    ["koreader.sync.summary_full"] = "Sync complete: {downloaded} downloaded, {deleted} removed, {deferred} removals deferred, {pages} page counts sent, {errors} errors.",
    ["koreader.sync.downloads_confirm"] = "Kolibre has {count} books ready to download:\n\n{list}\n\nDownload them now?",

    -- managed books
    ["koreader.managed_books.menu_title"] = "Books managed by Kolibre",
    ["koreader.managed_books.pages_count"] = "{count} page | {count} pages",
    ["koreader.managed_books.empty"] = "No books are managed by Kolibre on this device.",
    ["koreader.managed_books.detail_title"] = "Title: {value}",
    ["koreader.managed_books.detail_author"] = "Author: {value}",
    ["koreader.managed_books.detail_format"] = "Format: {value}",
    ["koreader.managed_books.detail_pages"] = "Pages: {value}",
    ["koreader.managed_books.detail_downloaded_at"] = "Downloaded on: {value}",
    ["koreader.managed_books.detail_file"] = "File: {value}",
    ["koreader.managed_books.remove_confirm_ok"] = "Remove from this device",
    ["koreader.managed_books.removed_notice"] = "Book removed. The server will be informed at the next sync.",
    ["koreader.managed_books.remove_failed"] = "Removal failed: {error}",

    -- initialize library (find unpaired books)
    ["koreader.library_init.menu"] = "Initialize library (find unpaired books)",
    ["koreader.library_init.confirm"] = "Every book already on this device will be examined to find the ones Kolibre doesn't manage yet. On very large libraries this can take a few minutes. Proceed?",
    ["koreader.library_init.scanning_progress"] = "Scanning library: {count} files examined…",
    ["koreader.library_init.nothing_new"] = "No new books to examine: every book on the device is already managed by Kolibre.",
    ["koreader.library_init.comparing"] = "Comparing with the server…",
    ["koreader.library_init.compare_failed"] = "Comparison with the server failed: {error}",
    ["koreader.library_init.skip_for_now"] = "Skip for now",
    ["koreader.library_init.multi_library_title"] = "'{name}' exists in more than one library",
    ["koreader.library_init.which_library"] = "Which library should it refer to?",
    ["koreader.library_init.hash_match_confirm"] = "Found {count} book already on Kolibre (identical file):\n\n{list}\n\nLink it? | Found {count} books already on Kolibre (identical files):\n\n{list}\n\nLink them?",
    ["koreader.library_init.hash_linked"] = "{count} book linked. It will be confirmed at the next sync. | {count} books linked. They will be confirmed at the next sync.",
    ["koreader.library_init.nothing_else"] = "No other book to examine: the device's library is already in line with Kolibre.",
    ["koreader.library_init.searching_matches"] = "Searching for matches: 0 of {total}…",
    ["koreader.library_init.checking_content"] = "Checking content: {done} of {total}…",
    ["koreader.library_init.ambiguous_title"] = "'{name}': more than one possible match",
    ["koreader.library_init.flagged_notice"] = "\n\n{count} book with notes or reading in progress was added to Kolibre's \"to review\" list, with no local changes. | \n\n{count} books with notes or reading in progress were added to Kolibre's \"to review\" list, with no local changes.",
    ["koreader.library_init.overwrite_confirm"] = "Found {count} never-opened book that seems to match a book on Kolibre:\n\n{list}\n\nOverwrite it with the Kolibre copy?{notice} | Found {count} never-opened books that seem to match books on Kolibre:\n\n{list}\n\nOverwrite them with the Kolibre copies?{notice}",
    ["koreader.library_init.overwriting_progress"] = "Overwriting: {done} of {total}…",
    ["koreader.library_init.no_candidate_title"] = "No match on Kolibre",
    ["koreader.library_init.no_candidate_detail"] = "File: {path}\n\nNo matching book found on Kolibre.",
    ["koreader.library_init.delete_from_device"] = "Delete from the device",
    ["koreader.library_init.deleted_notice"] = "Deleted.",
    ["koreader.library_init.auto_paired"] = "{migrated} highlights automatically re-linked to {count} book. | {migrated} highlights automatically re-linked to {count} books.",

    -- catalog
    ["koreader.catalog.label"] = "Catalog",
    ["koreader.catalog.title"] = "Kolibre Catalog",
    ["koreader.catalog.section_author"] = "Author",
    ["koreader.catalog.section_series"] = "Series",
    ["koreader.catalog.section_tag"] = "Tag",
    ["koreader.catalog.downloaded"] = "Downloaded: {filename}",
    ["koreader.catalog.download_failed"] = "Download failed: {error}",
    ["koreader.catalog.info_title"] = "Title: {title}",
    ["koreader.catalog.info_author"] = "Author: {author}",
    ["koreader.catalog.unknown_author"] = "Unknown",
    ["koreader.catalog.unknown_author_item"] = "Unknown author",
    ["koreader.catalog.info_format"] = "Format: {format}",
    ["koreader.catalog.info_size"] = "Size: {size}",
    ["koreader.catalog.download_button"] = "Download to the device",
    ["koreader.catalog.download_confirm"] = "Download '{title}'?",
    ["koreader.catalog.view_grid"] = "View: Grid",
    ["koreader.catalog.view_list"] = "View: List",
    ["koreader.catalog.sort_author"] = "Sort: By author",
    ["koreader.catalog.sort_recent"] = "Sort: Recently added",
    ["koreader.catalog.browse_by"] = "Browse by {section}",
    ["koreader.catalog.unavailable"] = "Catalog unavailable: {error}",
    ["koreader.catalog.recent"] = "Recently added",
    ["koreader.catalog.title_by_author"] = "By author",
    ["koreader.catalog.not_on_device"] = "not on the device",
    ["koreader.catalog.search_title"] = "Search the catalog",
    ["koreader.catalog.search_hint"] = "Title or author...",
    ["koreader.catalog.section_total"] = "{count} total",
    ["koreader.catalog.section_list_unavailable"] = "List unavailable: {error}",
    ["koreader.catalog.no_library"] = "No library available: {error}",
    ["koreader.catalog.choose_library"] = "Choose library",
    ["koreader.catalog.discover"] = "Discover",
    ["koreader.catalog.browse_library"] = "Browse the library",
    ["koreader.catalog.recent_unavailable"] = "Recently added unavailable: {error}",
    ["koreader.catalog.discover_unavailable"] = "Suggestions unavailable: {error}",
    ["koreader.catalog.all_books"] = "All books",
    ["koreader.catalog.not_on_device_item"] = "Not on the device",
    ["koreader.catalog.change_library"] = "Change library",
    ["koreader.catalog.browse_menu_title"] = "Browse",
    ["koreader.catalog.page_load_failed"] = "Could not load the page: {error}",
    ["koreader.catalog.empty"] = "No books.",
    ["koreader.catalog.untitled"] = "Untitled",
    ["koreader.catalog.cover_loading"] = "Cover loading",
    ["koreader.catalog.cover_failed"] = "Cover unavailable",
    ["koreader.catalog.cover_none"] = "No cover",

    -- automations
    ["koreader.automation.moment_startup"] = "At startup (and on wake)",
    ["koreader.automation.moment_open"] = "Opening a book",
    ["koreader.automation.moment_close"] = "Closing a book",
    ["koreader.automation.moment_shutdown"] = "Shutting down the device",
    ["koreader.automation.action_sync_books"] = "Check only for new books",
    ["koreader.automation.action_backup"] = "Upload backup",
    ["koreader.automation.action_push_annot"] = "Push highlights",
    ["koreader.automation.action_push_pos_all"] = "Send all positions (slower)",
    ["koreader.automation.action_pull_pos_all"] = "Download all positions (slower)",
    ["koreader.automation.auto_check_updates"] = "Check for plugin updates automatically",

    -- info dialog (Settings ▸ Info)
    ["koreader.info.policy_auto"] = "automatic (the server removes without asking)",
    ["koreader.info.policy_ask"] = "with confirmation (a single combined request)",
    ["koreader.info.policy_never"] = "never (the server never requests removals)",
    ["koreader.info.policy_unknown"] = "(unknown — run a sync)",
    ["koreader.info.last_sync_never"] = "never",
    ["koreader.info.body"] = "Kolibre v{version}\n\nServer: {server}\nLast sync: {last_sync}\nManaged books: {count}\nRemoval policy: {policy}",

    -- dispatcher (actions assignable to gestures/shortcuts)
    ["koreader.dispatcher.push_progress"] = "Kolibre: send reading position",
    ["koreader.dispatcher.pull_progress"] = "Kolibre: download reading position",

    -- common vocabulary, reused in several places
    ["koreader.common.not_configured"] = "(not configured)",
    ["koreader.common.not_configured_message"] = "First set up the server URL and token in Sync settings.",
    ["koreader.common.unreachable"] = "Server unreachable: {error}",
    ["koreader.common.close"] = "Close",
    ["koreader.common.cancel"] = "Cancel",
    ["koreader.common.save"] = "Save",
    ["koreader.common.search"] = "Search",
    ["koreader.common.more"] = "More…",
    ["koreader.common.start"] = "Start",
    ["koreader.common.link"] = "Link",
    ["koreader.common.ignore"] = "Ignore",
    ["koreader.common.none_of_these"] = "None of these",
    ["koreader.common.overwrite"] = "Overwrite",
    ["koreader.common.leave_as_is"] = "Leave as is",
    ["koreader.common.remove"] = "Remove",
    ["koreader.common.not_now"] = "Not now",
    ["koreader.common.continue"] = "Continue",
    ["koreader.common.request"] = "Request",
    ["koreader.common.later"] = "Later",
    ["koreader.common.send"] = "Send",
    ["koreader.common.download"] = "Download",
    ["koreader.common.download_verb"] = "Download",
    ["koreader.common.book_count"] = "{count} book | {count} books",
}

local catalogs = { it = it, en = en }

-- Substitutes every "{name}" in `s` for tostring(values[name]). A name with
-- no matching value is left untouched (visible, not silently blanked — an
-- easier bug to spot than text that's just missing).
local function interpolate(s, values)
    if not values then return s end
    return (s:gsub("{(%a[%w_]*)}", function(name)
        local v = values[name]
        if v == nil then return "{" .. name .. "}" end
        return tostring(v)
    end))
end

-- t(key, values): looks `key` up in the active language's catalog (falling
-- back to `it`, then to the bare key itself, so a missing/mistyped key shows
-- up as visibly odd text on screen rather than crashing the plugin). When the
-- stored value has two forms separated by " | ", picks the first when
-- values.count == 1, the second otherwise — then interpolates {name}
-- placeholders from `values` (which may be nil for a plain lookup).
function KolibreLingua.t(key, values)
    local catalog = catalogs[active_lang] or it
    local template = catalog[key] or it[key] or key

    local bar = template:find(" | ", 1, true)
    if bar then
        local singular = template:sub(1, bar - 1)
        local plural = template:sub(bar + 3)
        local count = values and values.count
        template = (count == 1) and singular or plural
    end

    return interpolate(template, values)
end

return KolibreLingua
