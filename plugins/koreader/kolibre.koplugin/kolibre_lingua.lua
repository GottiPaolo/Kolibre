--[[--
Kolibre's own text layer for this plugin's user-visible strings.

**English only** (Paolo, 24/11/2026: «per ora il plugin e' solo in inglese»,
scelta definitiva). Fino alla 0.28.0 qui c'erano due cataloghi, italiano e
inglese, e il server cuciva la lingua dell'account nel file al momento dello
scarico e dell'aggiornamento (`?lingua=`). Tenere due lingue vuol dire
scrivere e verificare ogni testo due volte per un plugin che si usa in
inglese: il catalogo italiano e' andato, e resta nella storia del
repository per il giorno in cui servisse (Paolo: «in futuro potrei volerlo
riprendere»).

**Per recuperarlo.** L'ultima versione completa, allineata al catalogo
inglese di allora (336 chiavi per lingua, plugin 0.28.0), e' nel commit
`a75d4ab`:

    git show a75d4ab:plugins/koreader/kolibre.koplugin/kolibre_lingua.lua

Il blocco e' `local it = { ... }`. Per rimetterlo servono tre cose: il
catalogo, le chiavi nate dopo la 0.28.0 tradotte (la prova
`chiavi_di_lingua` le elenca, se torna a contare due cataloghi), e la
lingua dell'account cucita dal server (`_RIGA_DELLA_LINGUA` in
`backend/app/api/tools.py`, da cui KOReader e' uscito nel commit
`a3598eb`).

NOT KOReader's `gettext` (require("gettext")): the plugin's strings live
here, in one flat table, and no setting changes them.

Usage: local t = require("kolibre_lingua").t
       t("koreader.menu.catalog")                    -- plain lookup
       t("koreader.catalog.downloaded", {filename=x}) -- {name} interpolation
       t("koreader.common.book_count", {count=n})     -- plural (see below)

Keys are flat, English, dot-separated, prefixed "koreader." (this plugin's
namespace) — e.g. "koreader.sync.failed". A missing key shows up as the bare
key on screen (visibly odd, never a crash); `prove/chiavi_di_lingua.lua`
checks that every key the sources use is in the catalog.

Plural entries hold TWO forms in one string, separated by " | "
(space-bar-space): "{count} book | {count} books". t() picks the first form
when values.count == 1, the second otherwise (0 counts as plural, same as in
ordinary speech). A non-plural entry has no " | " and is used as-is.

A flat Lua table on purpose — this plugin runs on slow, memory-constrained
e-ink readers.
]]

local KolibreLingua = {}

-- ── The catalog ──
local en = {
    -- main menu
    ["koreader.menu.title"] = "Kolibre",
    ["koreader.menu.sync_all"] = "Sync",
    ["koreader.menu.check_new_books"] = "Check for new books",
    ["koreader.menu.sync_all_help"] = "\"Sync\" does, in this order:\n\n• tells the server what is on this reader: managed books, free space, installed patches;\n• downloads the books the server has queued, asking first;\n• runs the pending actions;\n• removes the books you asked to delete from the web;\n• downloads the dictionaries you sent from the portal;\n• sends the page count of the books you opened;\n• sends new highlights and reading positions;\n• sends the backup, reading statistics included.\n\n\"Check for new books\" stops after the removals.",
    ["koreader.menu.check_new_books_help"] = "The fast half of \"Sync\": only the books coming in and the ones to remove. It sends no highlights, positions or backup — it answers the question \"is there anything new to read?\".",
    ["koreader.menu.catalog"] = "Browse server library",
    ["koreader.menu.tools"] = "Tools",
    ["koreader.menu.global"] = "Global",
    ["koreader.menu.global_help"] = "The heavy actions, the ones that go through the whole library on this device: all positions, all highlights, pairing the books, restoring another device's state.",
    ["koreader.menu.dev"] = "Dev",
    ["koreader.menu.settings"] = "Settings",
    ["koreader.menu.automations"] = "Automations",

    -- settings
    ["koreader.settings.connection"] = "Server connection...",
    ["koreader.settings.test_connection"] = "Test connection",
    ["koreader.settings.sync_popup"] = "Automatic sync popup",
    ["koreader.settings.sync_popup_help"] = "On, an automatic sync shows the progress bar and, if anything happened, a summary. Off, automatic syncs are silent. The ones you ask for from the menu always answer, otherwise a command that says nothing would look broken.",
    ["koreader.settings.info"] = "Info: Kolibre v{version} · UI {ui}",
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
    ["koreader.position.push_gave_up"] = "Kolibre: the position of {count} book could not be sent for {tries} syncs in a row: I am giving up on retrying. Reopen it to queue it again. | Kolibre: the positions of {count} books could not be sent for {tries} syncs in a row: I am giving up on retrying. Reopen them to queue them again.",
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
    ["koreader.backup.summary"] = "Backup complete: {uploaded} files uploaded, {skipped} already up to date, {failed} failed.",
    ["koreader.sync_reminder.menu"] = "Last sync reminder",
    ["koreader.sync_reminder.menu_help"] = "When you open a book and the last full sync is older than this, Kolibre asks whether to sync now. A sync also sends your highlights, positions and the backup.",
    ["koreader.sync_reminder.days"] = "After {days} days",
    ["koreader.sync_reminder.never"] = "Never",
    ["koreader.sync_reminder.prompt"] = "More than {days} days have passed since the last full Kolibre sync. Sync now?",

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
    ["koreader.update.menu_check"] = "Check for updates",
    ["koreader.update.menu_check_help"] = "Asks the server whether a newer version of the plugin exists and whether the patches you installed have changed. For patches it only offers the ones you already have: a patch you never installed is never pushed at you. If both need updating, it offers them together in one window, and asks to restart once at the end.",
    ["koreader.update.all_up_to_date"] = "Everything up to date: plugin v{version}, and the installed patches are the server's.",
    ["koreader.update.available"] = "Kolibre v{version} is available (current version: v{current}). Download and install now?",
    ["koreader.update.available_list"] = "There is something to update:\n\n{items}\n\nDownload and install now?",
    ["koreader.update.plugin_line"] = "Kolibre v{version} (you have v{current})",
    ["koreader.update.update_all"] = "Update all",
    ["koreader.update.updated_list"] = "Updated: {names}.",
    ["koreader.update.failed_list"] = "Failed: {names}. It will be retried at the next check.",
    ["koreader.update.resumed"] = "A previously interrupted Kolibre update (v{version}) was completed at startup.",
    ["koreader.update.resume_incomplete"] = "Kolibre update to v{version} incomplete (file: {file}). It will be retried automatically at the next KOReader startup.",
    ["koreader.update.manifest_failed"] = "Update failed: manifest unavailable: {error}",
    ["koreader.update.file_failed"] = "Update failed (file {file}): {error}",
    ["koreader.update.stage_failed"] = "Update failed: could not prepare the installation.",
    ["koreader.update.dir_failed"] = "Update failed: cannot create the folder {dir}.",
    ["koreader.update.dir_readonly"] = "Update failed: KOReader cannot write in the folder {dir}. Fix its permissions, or delete it: the update will recreate it.",
    ["koreader.update.partial"] = "Update partially applied (error on {file}). Restart KOReader: completion will be retried automatically.",
    ["koreader.update.whats_new"] = "What changes:",
    ["koreader.update.done"] = "Kolibre updated to v{version}.",
    ["koreader.update.restart_needed"] = "The new version takes effect at startup: until you restart KOReader, the previous one is still running.",

    -- KOReader patches, installed from the plugin, no cable needed.
    ["koreader.patches.menu"] = "KOReader patches",
    ["koreader.patches.install"] = "Install",
    ["koreader.patches.update"] = "Update",
    ["koreader.patches.remove"] = "Remove",
    ["koreader.patches.update_available"] = "update available",
    ["koreader.patches.auto_update_available"] = "These installed patches have changed on the server:\n\n{names}\n\nReplace them with the new version?",
    ["koreader.patches.updated_list"] = "Updated: {names}.",
    ["koreader.patches.no_description"] = "This patch does not describe itself.",
    ["koreader.patches.confirm_install"] = "{name}\n\n{description}\n\nA patch is code KOReader runs at every startup, until you remove it. Install it?",
    ["koreader.patches.confirm_update"] = "{name}\n\n{description}\n\nThe server has a different version from the installed one. Replace it?",
    ["koreader.patches.confirm_remove"] = "Remove \"{name}\"? KOReader will stop running it from the next startup.",
    ["koreader.patches.installed"] = "Patch \"{name}\" installed.",
    ["koreader.patches.removed"] = "Patch \"{name}\" removed.",
    ["koreader.patches.restart_needed"] = "Patches take effect at startup: until you restart KOReader, nothing has changed.",
    ["koreader.patches.install_failed"] = "Could not install \"{name}\": {error}. Nothing was installed.",
    ["koreader.patches.remove_failed"] = "Could not remove \"{name}\": the file is still there.",
    ["koreader.patches.dir_failed"] = "Could not create the patches folder ({dir}).",
    ["koreader.patches.dir_unknown"] = "This version of KOReader does not say where it keeps patches, so there is nowhere to install them.",
    ["koreader.patches.none_available"] = "The server has no patches to offer.",
    ["koreader.patches.server_unreachable"] = "Server unreachable: below, only what is already installed.",
    ["koreader.patches.all_disabled"] = "⚠ KOReader has patches disabled",
    ["koreader.patches.all_disabled_explain"] = "KOReader has a master switch that disables ALL patches, and it is currently on: even an installed patch will not run. Turn it back off in KOReader itself (Tools → more tools), not here.",
    ["koreader.patches.where"] = "Where patches live",
    ["koreader.patches.where_explain"] = "Installed patches live in {dir}. You can also remove them there by deleting the file: this menu does the same thing without a cable.",

    -- dictionary
    ["koreader.dictionary.unavailable"] = "Dictionary not available on the server — install it first from Settings → Integrations → Dictionaries, then send it to this reader from its page.",
    ["koreader.dictionary.download_failed"] = "Dictionary download failed (file {file}): {error}",
    ["koreader.dictionary.no_folder"] = "Cannot create the dictionary folder ({dir}). The dictionary stays queued on the server and will be retried.",
    ["koreader.dictionary.done"] = "Dictionary \"{name}\" installed. KOReader will now also use it for lookups while reading (long-press a word).",

    -- sync (protocol v2)
    ["koreader.sync.migration_scanning"] = "Recognizing books already present: {count} examined…",
    ["koreader.sync.removing_progress"] = "Removing: {done} of {total}…",
    ["koreader.sync.removal_confirm"] = "Kolibre is requesting the removal of {count} books:\n\n{list}\n\nRemove them now?",
    ["koreader.sync.removal_pending"] = "Kolibre: {count} removals awaiting confirmation — open \"Sync\".",
    ["koreader.sync.downloads_pending"] = "Kolibre: {count} books ready for delivery awaiting confirmation — open \"Sync\".",
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
    ["koreader.sync.gave_up"] = "Kolibre: the server did not answer. I stopped trying; I will try again at the next wake-up, or as soon as Wi-Fi comes back.",
    ["koreader.sync.summary_full"] = "Sync complete: {downloaded} downloaded, {deleted} removed, {deferred} removals deferred, {pages} page counts sent, {errors} errors.",
    ["koreader.sync.downloads_confirm"] = "Kolibre has {count} books ready to download:\n\n{list}\n\nDownload them now?",

    -- managed books

    -- initialize library (find unpaired books)
    -- ── Books-folder inventory ──
    ["koreader.inventory.menu"] = "Library inventory",
    ["koreader.diagnostica.menu"] = "Send the log to the server",
    ["koreader.diagnostica.menu_help"] = "Sends KOReader's log (crash.log) to the server, to read in the portal. It is what explains why something did not work on this reader. Tokens and addresses are stripped before it leaves; book titles and file paths stay, because they are often the only thing that explains a fault. It never happens on its own: you are always asked.",
    ["koreader.diagnostica.conferma"] = "Send KOReader's log to the server ({kb} KB, at most {max} are sent).\n\nTokens and addresses are stripped. Book titles and file paths stay: they go to your server and nowhere else.",
    ["koreader.diagnostica.manda"] = "Send",
    ["koreader.diagnostica.invio"] = "Sending the log to the server…",
    ["koreader.diagnostica.assente"] = "No log to send: {percorso} is not there.",
    ["koreader.diagnostica.illeggibile"] = "The log could not be read or prepared.",
    ["koreader.diagnostica.mandato"] = "Log sent ({kb} KB). Read it in the portal, on this reader's page.",
    ["koreader.diagnostica.fallito"] = "Sending the log failed: {errore}",
    ["koreader.inventory.scanning_progress"] = "Inventory: {count} files examined…",
    ["koreader.inventory.reading_sidecars"] = "Reading per-book reading data…",
    ["koreader.inventory.failed"] = "Sending the inventory failed: {error}",
    ["koreader.inventory.done"] = "Inventory sent to the server. No file was touched.",
    ["koreader.inventory.result_files"] = "{count} files on the device",
    ["koreader.inventory.result_recognized"] = "{count} recognised as a library book | {count} recognised as library books",
    ["koreader.inventory.result_duplicates"] = "{count} book present in more than one copy ({copies} extra copy) | {count} books present in more than one copy ({copies} extra copies)",
    ["koreader.inventory.result_unknown"] = "{count} file the server doesn't recognise | {count} files the server doesn't recognise",
    ["koreader.inventory.result_to_save"] = "{count} of them has annotations, to bring to safety before deleting anything | {count} of them have annotations, to bring to safety before deleting anything",
    ["koreader.library_init.menu"] = "Initialize library",
    ["koreader.library_init.confirm"] = "Kolibre will look at every book on this device that it doesn't manage yet, in three steps:\n\n• books identical to one on the server are paired with it;\n• the others can be sent to the server as they are, and become new books there;\n• the books Kolibre knows can be moved into Author/Title folders, with their reading progress, highlights, history and collections.\n\nEach step asks first. On a large library the scan can take a few minutes. Proceed?",
    ["koreader.library_init.send_confirm"] = "{count} book on this device is not on the server:\n\n{list}\n\nSend this exact file to «{library}»? It becomes a new book there, paired with this device. Nothing changes on the device. | {count} books on this device are not on the server:\n\n{list}\n\nSend these exact files to «{library}»? They become new books there, paired with this device. Nothing changes on the device.",
    ["koreader.library_init.send"] = "Send",
    ["koreader.library_init.send_which_library"] = "{count} book is not on the server: add it to which library? | {count} books are not on the server: add them to which library?",
    ["koreader.library_init.move_confirm"] = "{count} book is not in its author's folder. Move it?\n\n{list}\n\nReading progress, highlights, history and collections move with it. | {count} books are not in their author's folder. Move them?\n\n{list}\n\nReading progress, highlights, history and collections move with them.",
    ["koreader.library_init.move"] = "Move",
    ["koreader.library_init.summary_linked"] = "{count} book paired with the server. | {count} books paired with the server.",
    ["koreader.library_init.summary_sent"] = "{count} book sent to the server and paired. | {count} books sent to the server and paired.",
    ["koreader.library_init.summary_failed"] = "{count} book could not be sent: it will be offered again next time. | {count} books could not be sent: they will be offered again next time.",
    ["koreader.library_init.summary_not_sent"] = "{count} book not sent, as you chose. | {count} books not sent, as you chose.",
    ["koreader.library_init.summary_no_library"] = "{count} book not sent: there is no library you can add books to. | {count} books not sent: there is no library you can add books to.",
    ["koreader.library_init.summary_moved"] = "{count} book moved into its author's folder. | {count} books moved into their author's folders.",
    ["koreader.library_init.summary_not_moved"] = "{count} book left where it was. | {count} books left where they were.",
    ["koreader.library_init.summary_taken"] = "{count} book not moved: a file with the same name is already in its author's folder. | {count} books not moved: a file with the same name is already in their author's folder.",
    ["koreader.library_init.summary_metadata_elsewhere"] = "{count} book keeps its reading data somewhere other than where KOReader's settings say (Document metadata folder). It is still found and nothing is lost. | {count} books keep their reading data somewhere other than where KOReader's settings say (Document metadata folder). They are still found and nothing is lost.",
    ["koreader.library_init.scanning_progress"] = "Scanning library: {count} files examined…",
    ["koreader.library_init.comparing"] = "Comparing with the server…",
    ["koreader.library_init.compare_failed"] = "Comparison with the server failed: {error}",
    ["koreader.library_init.skip_for_now"] = "Skip for now",
    ["koreader.library_init.multi_library_title"] = "'{name}' exists in more than one library",
    ["koreader.library_init.which_library"] = "Which library should it refer to?",
    ["koreader.library_init.hash_match_confirm"] = "Found {count} book already on Kolibre (identical file):\n\n{list}\n\nLink it? | Found {count} books already on Kolibre (identical files):\n\n{list}\n\nLink them?",
    ["koreader.library_init.hash_linked"] = "{count} book linked. It will be confirmed at the next sync. | {count} books linked. They will be confirmed at the next sync.",
    ["koreader.library_init.nothing_else"] = "No other book to examine: the device's library is already in line with Kolibre.",
    ["koreader.library_init.auto_paired"] = "{migrated} highlights automatically re-linked to {count} book. | {migrated} highlights automatically re-linked to {count} books.",

    -- catalog
    ["koreader.catalog.label"] = "Catalog",
    ["koreader.catalog.title"] = "Kolibre Catalog",
    ["koreader.catalog.section_author"] = "Author",
    ["koreader.catalog.section_series"] = "Series",
    ["koreader.catalog.section_tag"] = "Tag",
    ["koreader.catalog.downloading"] = "Downloading “{title}”…",
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
    ["koreader.catalog.loading"] = "Fetching the catalog from the server…",
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
    -- ── the "library" view: Kolibre's own UI on KOReader ──
    ["koreader.ui.usa_la_vista"] = "Use the Kolibre UI",
    ["koreader.ui.accesa_dopo_il_libro"] = "Kolibre UI turned on: it opens when you close this book.",
    ["koreader.ui.usa_la_vista_help"] = "The Kolibre library takes the place of KOReader's file manager: on startup, and every time you leave a book, in the folder of that book's author. While this is on it is always there: Back does not close it, and if you end up in the file manager it brings you back. Turn it off here and the file manager is back to normal. If KOReader is set to \"open the last book\", on startup that choice wins.",
    ["koreader.ui.righe_scelte"] = "Rows per screen: {count}",
    ["koreader.ui.righe_help"] = "How many books you see at once in the Kolibre library, from 4 to 8. With fewer rows each book gets a large cover you can read from a distance; with more you see more at once and scroll less. Below a certain row height the row does not shrink the type: it drops the page bar instead, and then the status line, because an unreadable title is not worth the space it takes. Changing this redraws the open library right away, on the folder you are in.",
    ["koreader.ui.righe_titolo"] = "Rows per screen",
    ["koreader.ui.righe_ok"] = "Apply",
    ["koreader.ui.nessun_libro"] = "Kolibre has not sent any book to this device yet.",
    ["koreader.ui.cartella_vuota"] = "No Kolibre books in here.",
    ["koreader.ui.percorso_radice"] = "Library",
    ["koreader.ui.libri_nella_cartella"] = "{count} book | {count} books",
    ["koreader.ui.quando_adesso"] = "just now",
    ["koreader.ui.quando_oggi"] = "today",
    ["koreader.ui.quando_minuti"] = "{count} minute ago | {count} minutes ago",
    ["koreader.ui.quando_ore"] = "{count} hour ago | {count} hours ago",
    ["koreader.ui.quando_ieri"] = "yesterday",
    ["koreader.ui.quando_altroieri"] = "the day before yesterday",
    ["koreader.ui.quando_giorni"] = "{count} day ago | {count} days ago",
    ["koreader.ui.ricerca_titolo"] = "\"{testo}\" — {count} book | \"{testo}\" — {count} books",
    ["koreader.ui.ricerca_vuota"] = "No book for \"{testo}\".\n\nThe search looks at the title and the author of the books Kolibre has brought here.",
    ["koreader.ui.azione_manda_posizione"] = "Send your place to the server",
    ["koreader.ui.azione_scarica_posizione"] = "Get your place from the server",
    ["koreader.ui.azione_elimina"] = "Delete from this device",
    ["koreader.ui.azione_non_riuscita"] = "It could not be done: {error}",
    ["koreader.ui.elimina_conferma"] = "'{titolo}' will be deleted from this device.\n\nThe book stays in the library on the server, and Kolibre will not send it back here on its own. Notes and highlights already sent to the server are kept.",
    ["koreader.ui.elimina_fatto"] = "Removed from this device.",
    ["koreader.compat.project_title_pagine"] = "Project: Title is on.\n\nFrom this version Kolibre no longer writes anything inside your books, including the page count that Project: Title reads from them: books sent from now on will show no page count there. Books already on this device keep theirs.\n\nKolibre's own library view (Kolibre → Library UI) shows the length of every book, taken from the server.",
    ["koreader.ui.elimina_file_no"] = "The file could not be deleted: {error}. Nothing was changed, and the server was not told.",
    ["koreader.ui.elimina_in_coda"] = "Removed from this device. The server will be told at the next sync, and will not send the book back.",
    ["koreader.ui.elimina_sconosciuto"] = "Not enough is known about this book to tell the server.",
    ["koreader.ui.libro_non_c_e"] = "This file is gone.",
    ["koreader.ui.posizione_libro_aperto"] = "This book is open right now: send and get its place from Tools, while you read it.",
    ["koreader.ui.posizione_mandata"] = "Sent to the server: {percento}%.",
    ["koreader.ui.posizione_scaricata"] = "Got it from the server: {percento}%. You will find it when you open the book.",
    ["koreader.ui.posizione_niente_da_mandare"] = "This book has never been opened here: there is no place to send.",
    ["koreader.ui.posizione_niente_sul_server"] = "The server has no reading place for this book.",
    ["koreader.ui.posizione_errore"] = "It could not be done: {error}",
    ["koreader.ui.stato_finito"] = "finished",
    ["koreader.ui.stato_finito_con_pagine"] = "finished · {pagine} pages",
    ["koreader.ui.stato_non_iniziato"] = "not started",
    ["koreader.ui.stato_non_iniziato_con_pagine"] = "{pagine} pages · not started",
    ["koreader.ui.stato_in_lettura"] = "page {pagina} of {pagine} · {percento}%",
    ["koreader.ui.stato_in_lettura_senza_pagine"] = "{percento}% read",
    ["koreader.ui.pagine_ignote"] = "page count not known yet",
    ["koreader.ui.scheda_breve"] = "{titolo}\n{autore}\nLibrary: {biblioteca}\nPages (server estimate): {pagine}",
    ["koreader.ui.cronologia_non_disponibile"] = "KOReader's history is not reachable from here.",
    ["koreader.ui.cronologia_vuota"] = "You have not opened any book on this device yet. As soon as you do, you will find it here.",
    ["koreader.ui.cronologia_titolo"] = "History",
    ["koreader.ui.consegne_titolo"] = "Latest from the server",
    ["koreader.ui.consegne_vuoto"] = "The server has not sent any book to this device yet.",
    ["koreader.ui.sezione"] = "Library UI",
    ["koreader.ui.sezione_help"] = "Kolibre's UI in place of KOReader's file manager: whether to turn it on, how many rows to show per screen, and how to open the latest-sends panel and the history.",
    ["koreader.ui.consegne_voce"] = "Latest sends from the server",
    ["koreader.ui.consegne_voce_help"] = "The books the server sent to this device, most recent first, in a window of their own. From the library you can also open it by holding the home button.",
    ["koreader.ui.cronologia_voce"] = "History of opened books",
    ["koreader.ui.menu_non_disponibile"] = "KOReader's menu is not reachable from here.",
    ["koreader.ui.nessun_ultimo_libro"] = "No recently opened book.",
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
    ["koreader.automation.moment_shutdown"] = "Going to sleep or shutting down",
    ["koreader.automation.action_pull_pos"] = "Download this book's position",
    ["koreader.automation.action_push_pos"] = "Send this book's position",
    ["koreader.automation.action_session"] = "Send this reading session (highlights, statistics)",

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
    ["koreader.common.contacting_server"] = "Talking to the server…",
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
    ["koreader.common.and_more"] = "… and one more | … and {count} more",
    ["koreader.common.book_count"] = "{count} book | {count} books",
}


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

-- t(key, values): looks `key` up in the catalog (falling back to the bare
-- key itself, so a missing/mistyped key shows up as visibly odd text on
-- screen rather than crashing the plugin). When the
-- stored value has two forms separated by " | ", picks the first when
-- values.count == 1, the second otherwise — then interpolates {name}
-- placeholders from `values` (which may be nil for a plain lookup).
function KolibreLingua.t(key, values)
    local template = en[key] or key

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
