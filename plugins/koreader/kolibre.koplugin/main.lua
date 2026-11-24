-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one. This plugin extends KOReader (AGPL-3.0)
-- from the inside, which is why the whole project is AGPL.
--
-- **Perche' «next to this one» e non «in the repository», dal 16/11/2026.**
-- Chi installa questo plugin non riceve il repository: riceve uno zip. Da
-- oggi il server ci mette dentro LICENSE e NOTICE mentre lo costruisce
-- (`backend/app/api/tools.py`, `_aggiungi_la_licenza`), quindi i due file
-- stanno davvero accanto a questo — e l'AGPL chiede proprio che l'avviso
-- viaggi con la copia. Non stanno nella cartella del sorgente di proposito:
-- la' finirebbero nell'elenco dell'autoaggiornamento, e ogni dispositivo si
-- scaricherebbe due testi fissi a ogni versione.

--[[--
Kolibre KOReader plugin — server-driven device sync.

Unlike a "browse the catalog from the device" plugin, this one is
deliberately minimal on the device side: the server decides what should be
on the device (queued via the web UI's "Invia a dispositivo"), and this
plugin applies that desired state on each sync.

Since v0.3.0 the sync speaks protocol v2 (session-based, see
backend/scripts/simulate_device.py for the executable wire contract):
  Fase 0  build the handshake payload from the local manifest
          (kolibre_manifest.lua — the persistent list of books Kolibre
          itself delivered; no more full-filesystem MD5 scan per sync),
  Fase 1  POST /sync            -> session_id + sends[]/removes[] + settings,
  Fase 2  download sends[]      -> POST /sync/ack in batches,
  Fase 3  apply removes[] according to the server-driven delete_policy
          ('auto' | 'ask' | 'never') -> ack deleted/declined/missing/error,
  Fase 4  report on-device page counts from statistics.sqlite3 -> POST /pages,
  Fase 5  POST /sync/finish, then annotations as before.

Reading-position sync, annotations, backup, catalog browsing and self-update
are unchanged from v0.2.0. Still untested on real KOReader hardware — treat
new code paths as to-be-verified on device.

v0.7.1: **le finestre di conferma restano dentro lo schermo.** Un ConfirmBox
di KOReader cresce col testo e NON scorre: un elenco piu' alto dello schermo
spinge i bottoni fuori dal bordo, e la domanda diventa senza risposta — la
finestra resta li' e l'unico modo di toglierla e' riavviare. Succedeva
mettendo in coda molti libri, perche' la conferma dei download elencava un
titolo per riga senza alcun limite. Ora gli elenchi si tagliano a quante righe
ci stanno davvero, con in fondo quante ne restano (il totale sta comunque
nella frase che introduce l'elenco, quindi non si perde niente: si perde
l'elenco per esteso, che su sessanta libri non si leggeva comunque). Vale per
tutti e quattro i punti che ne costruivano uno: download, rimozioni,
accoppiamento per impronta e sovrascrittura. Il calcolo sta in
kolibre_finestre.lua, con la sua prova («finestre»).

v0.7.0: **un libro si dice per nome, non per com'e' fatto dentro.** Fino a
qui il plugin diceva al server quale libro intendeva mandando l'impronta
parziale del file, e il server la risolveva all'indietro con tre livelli di
ripiego. Ma l'identita' ce l'abbiamo gia' noi, nell'elenco dei libri che
Kolibre ha consegnato (kolibre_manifest.lua), indicizzato proprio per
(biblioteca, id Calibre, formato): la buttavamo via, e facevamo indovinare al
server una cosa che sapevamo. Quando il file veniva riscritto da una delle due
parti — basta un metadato corretto sul server — l'impronta non combaciava piu'
da nessuna parte e l'annotazione diventava orfana, pur sapendo benissimo a
quale libro apparteneva.

Ora annotazioni, posizione di lettura (in salita e in discesa), conteggio
pagine, elenco dei libri gestiti e riconciliazione portano l'identita'
ACCANTO all'impronta, mai al posto: un server non aggiornato legge l'impronta
e ignora il resto, e un libro che Kolibre non ha consegnato continua a
viaggiare per sola impronta — che li' e' lo strumento giusto, perche' e'
esattamente il lavoro di accoppiare un libro che sta solo sul dispositivo.

E l'impronta di un libro scaricato **si misura**, non si ricopia: prima si
scriveva nel manifesto il numero che il server aveva appena detto, e se quel
numero era stantio il dispositivo lo faceva proprio. Ora si calcola sul file
appena arrivato e si rimanda al server nell'ack, perche' solo il dispositivo
sa che byte sono arrivati davvero.

v0.4.0: annotations now carry the full chapter ancestry (Parte ▸ Capitolo),
not just the leaf title, resolved from the document's cached TOC; the
catalog browser is sectioned (per autore / recenti / cerca) instead of one
flat list with a sort toggle; the backup file list covers more of KOReader's
own settings (history, vocabulary, gestures, shortcuts, collections — never
files that can hold credentials); and a new, deliberately hidden
Impostazioni ▸ Avanzate ▸ "Inizializza libreria" reconciles books already on
the device that Kolibre doesn't yet manage.

v0.4.1: detectBooksDir() now checks KOReader's own user-configurable "Home
folder" setting (home_dir) before falling back to hardcoded per-device
guesses — a device with a custom home folder configured used to be silently
ignored. Backup now looks for settings.reader.lua/history.lua/
defaults.custom.lua under DataStorage:getDataDir() instead of
:getSettingsDir() — they never actually lived under the "settings/"
subdirectory the rest of BACKUP_FILES does, so those three backups were
silently failing (file-not-found, no error surfaced) regardless of device.

v0.4.2: device-init's "no match at all" case now also reports to the server
(match_status "no_candidate"), not just the on-device menu, so it shows up
in the web UI's "Da rivedere" page alongside the already-server-side
"match found but skipped" case; that case now also reports WHY it was
skipped (percent read, highlight count) so the web page can explain it.
New sync Fase 2.5 applies any pending web-queued action (overwrite/delete)
for a "da rivedere" entry and acks it once applied.

v0.5.0: major redesign. "Sincronizza tutto" (renamed from "Sincronizza ora")
now pushes queued annotations/positions and runs a backup as part of the
same action, and asks confirmation for pending downloads too, not just
deletions — a deliberate reversal of this file's own founding principle
("the server decides, the device applies silently"), now that the user
explicitly wants a say over both. It still never scans books_dir: a new
offline queue in kolibre_manifest.lua (annotation_dirty_paths/
position_dirty_paths) tracks which books have unpushed changes, populated by
onCloseDocument/onSuspend/onPageUpdate, and _pushQueuedAnnotations/
_pushQueuedPositions only ever touch what's actually queued.

Chapter-ancestry resolution for annotations moved server-side entirely —
the device no longer reads or walks a book's TOC at all (the old
_resolveFullChapterPath is gone); see backend's new
services/position_converter/chapter_resolver.py, called from
push_device_annotations.

Automazioni is now a real matrix (4 moments — avvio/apertura/chiusura/
spegnimento, "avvio" also covering onResume — × a free multi-select of 7
actions) instead of 4 fixed on/off bundles each hardcoded to its own action
pair. Default unchanged in spirit: only "Scarica posizione libro corrente"
at apertura and "Sincronizza tutto" at chiusura.

"Sfoglia catalogo" opens directly into the catalog view (author/recent/
search are now in-view controls) instead of a 3-item picker submenu, and
gained a cover-grid ("mosaic") view alongside the existing list, toggled
from a new right title-bar icon — kolibre_catalog.lua/
kolibre_catalog_widgets.lua, a trimmed port of the cover-grid catalog widget
of BookOrbit (https://github.com/bookorbit/bookorbit, AGPL-3.0, a separate
project by other authors), the "follow-up" this file used to defer explicitly.

A shared reachability guard (GET /api/devices/me, cached 20s) now runs
before any network action instead of letting each call find out it failed
on its own. The plugin now also pins its own menu position
(kolibre_menu_pin.lua, ported from BookOrbit) instead of leaving KOReader to
place it wherever unlisted tools entries land. "Invia/Scarica posizione
libro corrente" are gated on a book being open again (enabled_func),
reversing the earlier v0.3.x decision to leave them always-tappable.

Backend fix alongside this: push_device_annotations was silently dropping
any annotation whose file had no BookHash row — those rows were only ever
created at ingest time or via a manual recompute-hashes endpoint, never by
rescan_library, which was the actual gap (see backend's new
services/book_hash_service.py). This plugin now also always surfaces the
"non risolte" count on an automatic push when it's non-zero, not just on a
manual one — that silence is exactly how the bug went unnoticed.

v0.5.1: annotations for a book Kolibre can't yet match by hash are no longer
dropped — each item now also carries its local file `path`, so the server
stores them as "orphan" highlights (visible/exportable/editable, just not
book-linked yet — see backend's new OrphanHighlight) instead of only
counting them as "unresolved". The device-init fuzzy title/author search
(_findProbableCatalogMatches) also sends a separate author guess alongside
the title guess when the filename splits on " - " — the old single combined
needle was usually a substring of neither the title nor the author field
alone, which is why a well-formed filename could still fail to fuzzy-match
(see backend's browse_catalog, now accepting a distinct `author` param).
Also reports the flagged file's own hash when parking it in "Da rivedere",
needed for the web UI's new manual pairing action.

v0.5.2: fixes a real fuzzy-match miss found by investigating a book that
stayed stuck on "no_candidate" despite already being in the library under
an unambiguous title. _guessTitleFromPath used to only strip the extension
and turn every "-"/"_" into a space — for a "Title - Author.epub" filename
(Calibre/Kindle's own convention) that mashed the author straight onto the
title guess ("Title   Author"), a string that is a substring of neither the
real title nor the real author, defeating both the AND-tightened match and
its OR-fallback. Now splits off the " - Author" suffix the same way
_guessAuthorFromPath already does, so the title guess is clean again.
Backend's browse_catalog also now compares accent-insensitively (NFKD fold)
since a device-transferred filename losing diacritics ("Munoz" vs
Calibre's "Muñoz") was silently defeating the match on its own.

v0.5.3: "Sincronizza tutto" now shows a real "[====------] 40% - Fase..."
progress bar across every phase (handshake, download, azioni in sospeso,
rimozioni, conteggio pagine, note/posizioni/backup) instead of plain text —
same bar format as the plugin of an earlier, unpublished project of mine,
explicitly matched on request. Downloaded files no longer get "(<calibre_id>)" stuffed
into their on-device filename (_downloadCatalogBook / runDownloads) — that
convention was never load-bearing (only a fallback fuzzy-match heuristic for
files Kolibre never touched reads it back out of a filename, and only for
files it did NOT itself deliver).

v0.5.4: device-init now extracts and pushes annotations for EVERY scanned
file, not just books already managed by the manifest — a file flagged
"flagged_started" or "no_candidate" never had its highlights read before,
so pairing it later (by hand or once fuzzy matching improves) had nothing
to migrate. They're captured now as orphans (see backend's OrphanHighlight)
via the same _extractAnnotationsFromFile already used elsewhere.

v0.5.5: fixes a real gap reported after real-device testing — a manual tap
of "Sincronizza tutto" only ever pushed annotations already in the offline
dirty-queue (onCloseDocument/onSuspend), never a book's pre-existing
highlights if it was never closed/suspended through THIS plugin (an older
plugin install with no dirty-queue yet, or a book paired after already
being highlighted). "Sincronizza tutto" now runs the same exhaustive
books_dir rescan as the standalone "Pusha tutte le annotazioni" action when
(and only when) manually triggered by the user — automatic background syncs
still use the cheap queue-only push, unaffected.

v0.5.6: fixes device-init matching, confirmed against a real device with
410 "no_candidate" flagged books. Three causes, all real: (1) AppleDouble
resource-fork stubs ("._Foo.epub", written by macOS/Finder on USB copy) were
scanned and flagged as missing books — now skipped outright, they're not
books; (2) _guessAuthorFromPath now falls back to the parent folder name
when the filename itself has no " - Author" segment, covering the
<books_dir>/<Author>/<title>.ext layout this plugin's own "author"
folder_layout uses; (3) the backend (browse_catalog) now undoes Calibre's
own title_sort reordering ("Il Titolo" -> "Titolo, Il", written straight to
disk by that layout) before fuzzy-scoring, instead of comparing against it
literally. Together these recovered ~95% of the flagged sample in testing —
the remainder were genuinely different books, not a matching bug.

v0.5.7: v0.5.6's fixes were still filename/folder heuristics — general
enough for that specific naming convention, but not for identity itself.
Device-init now tries a CONTENT fingerprint first (epub/fb2/txt): the file
is uploaded whole to a new /devices/identify-file endpoint, since KOReader
has no way to read inside a zip/EPUB on-device, and the server (which
already has zip/OPF-parsing code for the TOC editor and page counter)
extracts normalized text and matches it against a per-book fingerprint
computed the same way for the whole library (backend's BookHash gained
content_fingerprint alongside the existing byte-level file_hash). This is
invariant to filename, folder, container metadata, and zip compression —
matches two independently-produced copies of the same book regardless of
how either was named or packaged. Falls back to the existing fuzzy
title/author search exactly as before when the format isn't supported
(pdf/mobi/azw3) or no fingerprint match is found — no regression for those.

v0.5.8: fixes real data loss confirmed after a real test — "Sovrascrivi" on
a book already flagged as started deletes the local file AND purges its
KOReader sidecar (_deleteManagedBook), losing highlights/progress for real,
not just in theory. Resolved candidates now carry WHERE they came from
(match_source: "fingerprint" vs "fuzzy"); a fingerprint match — already
authoritative, not a guess — auto-pairs immediately server-side instead of
ever reaching "Da rivedere", since pairing never touches the device file at
all. A confirm dialog now also warns before overwriting a flagged_started
row, and the web UI gained a one-click "Accoppia con questo" (mirroring the
existing "Sovrascrivi con questo") for rows already flagged before this fix.
Also: author-folder ".folder.jpg" covers, previously written only at the
exact moment a NEW book by that author was being downloaded, are now
backfilled for existing folders too during "Verifica libreria" and
"Sincronizza tutto" — a folder that got its first book before the author
had a photo in Kolibre used to never get one, ever.

v0.5.9: TEMPORARY — "Ripara tag pagine per ProjectTitle" (Impostazioni >
Avanzate). Books imported before the server started embedding #pages into
the EPUB's own OPF (see opf_metadata.py) never picked it up retroactively:
recompute-pages fixes the server's master file, but nothing re-downloads an
already-delivered device copy just because its master changed. This asks
the server to re-embed (device-authenticated, since recompute-pages needs
a web session this plugin doesn't have), then re-downloads only the
never-opened affected files — same content, same local path, sidecar never
touched. Remove this menu entry once every library's gone through
recompute-pages at least once.

v0.5.10: fixes a real timeout confirmed on a real device — a large library
manages hundreds of EPUBs, and the server side of "Ripara tag pagine" did a
full zip read+rewrite per book in ONE request, which reliably ran past the
plugin's HTTP timeout. reembed-page-counts is now paginated (offset/limit)
and the plugin calls it in small batches with visible progress instead of
one long silent request. Also new: "Scarica foto autori mancanti"
(TEMPORARY, same menu section) — an on-demand way to run the author-cover
backfill (v0.5.8) by itself, without needing a full "Verifica
libreria"/"Sincronizza tutto" just to pick up photos added to the server
after this device's author folders were already created.

v0.5.11: "Ripara tag pagine" used to skip already-opened books on-device,
borrowing the same safety gate the automatic fuzzy-match bucket uses — but
that gate exists there to guard against a WRONG identity plus a real
delete+purge. Here the book is already known for certain (it's already in
this device's own manifest) and only one <meta> tag gets added to the
OPF's <metadata> block — the spine a reading position/CFI is anchored to
is never touched, and the sidecar is never purged. Reported as an
unnecessary omission on a real device with real progress on the affected
books, and correctly so — now every managed EPUB is refreshed regardless
of whether it's been opened.

v0.5.12: fixes a real gap in author-folder cleanup — deleting the last book
of an author was supposed to remove the now-empty folder too
(_cleanupBookDir), but only ever did when the folder held NOTHING but our
own .folder.jpg: DocSettings:purge() clears what's inside a "<book>.sdr"
sidecar directory but doesn't reliably remove the (now empty) directory
itself, and that leftover .sdr alone counted as "something's still there,
keep the folder" — so the folder almost never actually got removed.
Rewritten to check by EBOOK EXTENSION instead (epub/pdf/mobi/azw3/fb2/txt,
matching _scanLocalBooks' own table) — a leftover .sdr, our own cover, or
AppleDouble "._*" junk no longer block the cleanup, only a real remaining
book does.

v0.5.13: removes the two TEMPORARY maintenance menu entries, "Ripara tag
pagine per ProjectTitle" (v0.5.9-v0.5.11) and "Scarica foto autori
mancanti" (v0.5.10) — repairPageCountMetadata/reembed-page-counts and
repairAuthorFolderCovers are gone along with them (_backfillAuthorFolderCovers
itself stays: it's still called from "Verifica libreria"/"Sincronizza
tutto", that part was never temporary). Any device that never ran these by
hand keeps whatever it already had — an EPUB missing its #pages tag stays
missing it until re-downloaded some other way, and an author folder still
missing its cover stays missing it until its next "Verifica libreria"/
"Sincronizza tutto" (which still runs the same backfill automatically).

v0.5.14: reverses v0.5.5 by an explicit later decision — a manual tap of
"Sincronizza tutto" no longer runs the exhaustive books_dir rescan, it
always uses the cheap queue-only annotation push now, same as an automatic
background sync. The full rescan (for a book highlighted before this
device's dirty-queue existed, or paired after already being highlighted)
is reachable ONLY via the standalone "Pusha tutte le annotazioni" menu
entry — already existed as its own action, now the sole way to trigger it.
Trade-off made consciously: "Sincronizza tutto" stays fast and predictable;
recovering pre-existing highlights on an old/newly-paired book now requires
knowing about and tapping that other entry.

v0.5.15: NEW FUNCTIONALITY, not a bugfix — phase 1 ("foundation") of a
richer catalog-browsing navigator, inspired by BookOrbit's dashboard/catalog
system but adapted to this plugin's server-driven philosophy. Two additions:
(1) new kolibre_capabilities.lua does capability negotiation against a new
GET /api/kolibre/devices/capabilities (device-token auth, same as every
other Kolibre call) so the plugin can detect whether a given server supports
newer catalog features and degrade gracefully (feature hidden, not
disabled-and-tappable) on an older one that 404s the route entirely; caches
per server URL, in-memory only for the KOReader session, and keeps "confirmed
absent" (feature missing from a successfully-fetched capabilities array)
architecturally distinct from "unknown" (the call itself failed) even though
both are treated the same for now — a future phase may want to retry unknown
but should never retry confirmed-absent.
(2) drill-down catalog browsing by author/series/tag, wired into the
EXISTING catalog Menu rather than a new widget: the catalog's gear-icon
dialog (_showCatalogViewDialog) gains "Sfoglia per autore/serie/tag" entries,
gated on the catalogSections capability, that fetch
/api/kolibre/devices/catalog/sections/{authors,series,tags} and render the
{name, count} buckets as a plain list Menu (paginated via a trailing
"Altro…" item, same close-then-reopen idiom used elsewhere in this file
rather than the stock Menu's own item_table-swap API). Tapping a bucket
drills into the existing /catalog endpoint via _openKolibreCatalog's new
`drill` param (now also carrying `series`/`tag`/`author` filters, in
addition to `query`/`sort` it already had), reflected in the catalog title
("— Autore: Victor Hugo"). No dashboard, no offline caching of these
responses, no new settings — all explicitly deferred to a later phase.

v0.6.0: phase 2 of the catalog navigator — the actual dashboard deferred
above, still inspired by BookOrbit but adapted to this plugin's own
primitives rather than porting its bespoke shelf widgets. "Sfoglia catalogo"
is replaced by a new "Catalogo" entry (openCatalogDashboard) opening a small
home screen with three destinations: "Aggiunti di recente" (the existing
catalog view, just sort=recent, unchanged), "Da scoprire" (new, gated on the
new catalogDiscover capability) and "Sfoglia la libreria" (a new Browser
menu: Cerca / Tutti i libri / Non sul device / Serie / Cambia libreria,
mostly wiring existing pieces — _promptCatalogSearch, _openKolibreCatalog,
_browseCatalogSection — behind one entry point instead of a single flat
Menu). Deliberately NOT true horizontal scrolling shelves like BookOrbit's
own dashboard cards: each destination opens its own full KolibreCatalog
mosaic screen, reusing that widget's existing pagination/thumbnail-caching
machinery as-is rather than rewriting it to support mixed sections — safer
on e-ink hardware and on code that's already in production.

"Da scoprire" hits a new GET /api/kolibre/devices/catalog/discover: books
NOT already on this device, preferring same-author/same-tag matches against
what was recently read ON THIS DEVICE, randomly filled out when there aren't
enough matches — server-computed, this file just renders whatever it
returns via the same _catalogItems() list-building browse_catalog already
used. "Non sul device" reuses _openKolibreCatalog with a new
exclude_on_device flag, threaded through its sort/search round-trips
(_showCatalogViewDialog, _promptCatalogSearch) so switching sort or
searching from inside that view doesn't silently drop the filter; NOT
threaded into the author/series/tag section drill-down (out of scope, not
requested).

Also: mosaic cover cards now always show title AND author on two lines
(kolibre_catalog_widgets.lua — the real-cover case used to show title only,
unlike the fake-cover placeholder which already had both); and a fresh
single-book download from the catalog (_downloadCatalogBook) now writes the
author folder's .folder.jpg on first download too (new
_ensureAuthorFolderCover, independent from runDownloads'/
_backfillAuthorFolderCovers' own already-verified cover-writing, which stay
untouched) — previously only a full sync or the maintenance backfill did.

browseCatalog(sort), the old direct "Sfoglia catalogo" entry point, is
removed — nothing calls it anymore now that the main menu opens the
dashboard instead.

v0.6.1: two fixes reported after real use of v0.6.0. (1) the mosaic/grid
cover view was never actually the default — G_reader_settings defaulted to
"list" until the user manually toggled the Vista icon once, so every first
open of the catalog/search/Discover showed a text list instead of the
cover grid this view is supposed to open on; default flipped in
kolibre_catalog.lua (an explicit prior choice, either way, is still
respected). (2) "Libri non accoppiati" never showed local_author for
already-flagged books even after updating the plugin: report_flagged_book
was insert-only, so re-scanning ("Inizializza libreria" reprocesses every
still-unpaired file on every run, not just new ones) created a second,
duplicate row instead of refreshing the stale one — fixed backend-side by
upserting on (device_id, local_path), leaving pending_action untouched.

v0.6.2: CRITICAL fix — v0.6.1's mosaic-by-default change crashed a real
Kindle. Root cause, confirmed by comparing against BookOrbit (a more mature
KOReader library plugin): the cover grid was downloading and decoding
FULL-RESOLUTION Calibre covers (routinely 1000-2500px on the long edge,
whatever size Calibre happens to have) for every visible tile — up to 9 at
once on the default 3x3 grid — with no server-side resize and no size cap
anywhere in the download path. On a memory-constrained e-ink device that's
enough to OOM. Fixed in three layers, all server/client changes together:
(1) new GET /api/kolibre/books/{id}/cover/thumbnail (books.py) resizes to
400x600 max server-side before ever sending bytes, mirroring the resize
pattern this codebase already used for author folder icons
(authors.py's own /photo/thumbnail); kolibre_catalog.lua's
scheduleThumbnailDownloads now requests this route instead of the full
/cover; (2) KolibreApi:downloadTo gained an optional max_bytes cap (used
only for thumbnails, never real book downloads) that aborts mid-transfer
rather than trusting the server response size — belt-and-braces should the
resize itself ever regress; (3) the on-device thumbnail cache
(cache/kolibre_covers) had no eviction at all since it was introduced in
v0.5.0 — a simple oldest-first count cap was added (pruneThumbnailCache) so
it can't grow unbounded over a long browsing history, now that it's cheap
to do since cached files are themselves small. Mosaic stays the default
(v0.6.1's own fix) since the actual crash cause is now addressed, not the
default-view choice itself.

v0.6.3: efficiency follow-up from a general performance pass (not a
correctness bug — v0.6.2 already made every individual thumbnail small and
capped). kolibre_catalog.lua's mosaic grid used to hand
scheduleThumbnailDownloads the ENTIRE catalog result (self.item_table, up
to browse_catalog's own 500-book cap) the moment the screen opened, quietly
queuing hundreds of background downloads regardless of how many pages the
user actually visits — wasted bandwidth/battery on a large library, still
worth fixing even though each individual download is now small and bounded.
updateItems() now requests thumbnails only for the CURRENT grid page,
tracked per-page in thumbnail_requested_pages (reset on view-mode switch)
so scheduleThumbnailDownloads' own progress-repaint calls (updateItems(nil,
true) after every download batch) can never re-queue the same page's
in-flight downloads a second time. Turning to a new page naturally requests
that page's thumbnails the first time it renders, same as before just
scoped to what's actually visible.

v0.6.4: CRITICAL fix — "Aggiunti di recente" kept crashing a real Kindle
even on v0.6.3. Root cause this time confirmed directly from backend access
logs (not guessed): on a 1190-book library, the single
GET .../catalog?library=...&sort=recent request (no page/size — the
Dashboard reused the general, uncapped _openKolibreCatalog) succeeded, and
then NOTHING — no cover/thumbnail request, no error, just silence, followed
by the device reconnecting from scratch a while later (the exact signature
of a crash-and-restart). browse_catalog's own fallback when page/size are
both absent returns up to its 500-book cap in one JSON response; decoding
hundreds of full book records (title, author, tags[], formats[], series,
rating, pubdate...) into Lua tables in a single JSON.decode is plausibly
what exhausted memory — entirely before any image was ever touched, which
is why v0.6.2's cover-resize fix (correct for the bug it targeted) never
helped this one. Fixed: "Aggiunti di recente" now has its own bounded
fetch (_openCatalogRecent, page=1&size=24 — both required together for
browse_catalog's pagination branch to engage, confirmed by reading its own
code) instead of reusing the general uncapped browser, same shape as
_openCatalogDiscover's own already-safe 24-book limit. NOTE: "Tutti i
libri" (_openCatalogBrowserMenu) still calls the general, uncapped
_openKolibreCatalog — on the same 1190-book library that remains a known,
NOT YET fixed risk of the identical failure mode; deliberately left alone
this round pending a decision on scope (bounding an interactive
browser that also handles search/sort/drill-down is a bigger change than
a static dashboard shelf).

Also: thumbnail_cache_dir renamed kolibre_covers -> kolibre_covers_v2, so a
book whose cover was cached full-resolution before v0.6.2 (cached by mere
file-existence check, never re-validated) can no longer be found and
silently reused — every cover now gets freshly (re)fetched through the
resized endpoint at least once per device.

v0.6.5: CRITICAL fix — the exact risk v0.6.4's own changelog flagged as
"NOT YET fixed" turned out to fire on the very next real-device test: "Tutti
i libri" (and every other _openKolibreCatalog caller — "Non sul device",
search, author/series/tag drill-down) still requested the catalog with no
page/size, hitting browse_catalog's unbounded up-to-500-book fallback,
confirmed directly from backend access logs on the same 1190-book library
(GET .../catalog?sort=author with no page/size, 200 OK, then silence, then
reconnect-from-scratch — identical signature to v0.6.4's own root cause).
Fixed properly this time instead of just moving the cap around:
_openKolibreCatalog now always requests page=1&size=60, and the mosaic
grid (kolibre_catalog.lua) grows its item_table on demand as the user pages
past what's already loaded (KolibreCatalog:_ensurePageLoaded, driven by a
fetch_more closure + server_has_more flag the browser passes in; dashboard
shelves like Recent/Discover don't pass these, since those stay single-page
by design). page_num is inflated by one extra "phantom" page whenever more
results remain server-side, purely so the stock Menu widget's own
next-page guard (self.page < self.page_num) lets navigation reach that next
page at all — that's what actually triggers the fetch, right before the
page it applies to is rendered. List-mode pagination is NOT extended the
same way (deliberately out of scope: mosaic is the default and the only
mode used in the crash reports; switching to list mid-browse just shows
whatever has already been loaded via mosaic paging so far — a limitation,
not a regression, since the old code never fetched beyond size=500 either).

v0.6.6: CRITICAL fix, the ACTUAL root cause — v0.6.4/v0.6.5 were chasing the
wrong culprit. A real crash log captured from a desktop KOReader test (the
plugin run from a terminal on macOS, something the physical Kindle can
never surface) gave the first real Lua traceback of this whole
investigation: "kolibre_catalog.lua:278: attempt to call method
'resetTitleBar' (a nil value)". resetTitleBar is NOT a stock KOReader Menu
method — it is a method BookOrbit defines ITSELF in its own
bookorbit_catalog.lua (confirmed by grepping the BookOrbit source: the
definition lives at bookorbit_catalog.lua:413, right alongside the very
mosaic-mode code kolibre_catalog.lua was originally "trimmed" from, v0.5.0).
That trim copied the CALL to this method but never copied its DEFINITION —
an incomplete port that has been in every mosaic-mode render since mosaic
became the default view (v0.6.1), meaning it fired on literally every single
catalog screen open, "Aggiunti di recente" included, since day one. This is
almost certainly what every "crash" reported through v0.6.2-v0.6.5 actually
was: a hard Lua runtime error crashing the whole process, not an out-of-
memory JSON decode — the earlier size-based fixes were real, defensible
hardening (matching how BookOrbit itself paginates for its own tens-of-
thousands-of-books scale target) but were treating a symptom correlation
(a 200 OK immediately followed by silence and a reconnect) that has an
equally-fitting, much simpler explanation once a real traceback exists to
check against. Fixed by simply removing the call: nothing in this file ever
mutates an existing KolibreCatalog instance's title/subtitle after
construction (verified by grep — every re-sort/re-search closes the old
catalog Menu and opens a brand new one), so the title bar built once by
stock Menu.init() never needs resetting, and Menu.mergeTitleBarIntoLayout
(already called at the end of updateItems, unchanged) is all that is needed
to keep it correctly merged into the freshly-rebuilt layout on every render.

Also, by an explicit decision to lean more directly on BookOrbit's own
proven implementation for this feature: replaced v0.6.5's bounded-but-
accumulating fetch_more/server_has_more scheme with a more faithful port of
BookOrbit's actual model (bookorbit_catalog.lua: itemsPerPage/showBookPage/
loadBooks/onNextPage — confirmed by reading that source directly, not
guessed). _openKolibreCatalog's requests are now sized to exactly one grid
screen (KolibreCatalog.mosaicPageSize(), 9 books by default) instead of 60,
and every page turn (onNextPage/onPrevPage/onFirstPage/onLastPage/
onGotoPage, all newly overridden on KolibreCatalog) fetches that one page
fresh and REPLACES item_table wholesale, rather than accumulating an ever-
growing array behind a "phantom page" trick. Simpler than v0.6.5 (no
phantom-page bookkeeping to get wrong) and provably safe regardless of
library size, since a mosaic render can never hold more than one grid's
worth of book records in memory. Scoped to mosaic mode only, same as v0.6.5
— list mode (secondary/legacy here) keeps showing whatever page is already
loaded rather than gaining its own paging, and switching mosaic<->list
re-fetches the current page outright to avoid any stale/out-of-range page
number surviving the round trip. Verified end-to-end with a standalone
Lua simulation (133 mock books, 9/page): full forward walk, full backward
walk, onGotoPage/onFirstPage/onLastPage clamping, and the mosaic<->list
drift-recovery case all pass before this was tested on a real device.

v0.6.7: polish, after v0.6.6 was confirmed on device to fix the crash.
(1) kolibre_catalog_widgets.lua's MosaicItem: title's box height was 62% of
the label area, generous enough that a typical one-line title left visible
empty space BELOW it (TextBoxWidget doesn't vertically center within a
taller-than-needed box) — landing that space squarely BETWEEN title and
author, exactly why the author line read closer to the NEXT grid row than
to its own book ("l'autore è più vicino alla riga sotto che non al libro a
cui si riferisce"). Tightened to 46%, and author now gets an explicit font
size 4pt under the title's own dynamically-computed one (both via the same
"cfont" face) instead of a separately-named smaller preset, so the size
hierarchy holds regardless of how far apart those presets happen to sit on
a given device. Any leftover vertical space now falls outside the title+
author pair, where the CenterContainer wrapping the whole cover+label block
absorbs it as margin around the group instead of a gap inside it.
(2) _openCatalogRecent/_openCatalogDiscover never set a search icon at
all — "Tutti i libri" had one (opens _promptCatalogSearch), the dashboard
shelves didn't. Both now do, wired to the same general catalog search
(searching within a 24-book curated shelf wouldn't mean much; searching the
whole library from wherever you tapped the icon does).
(3) Tapping a book in ANY grid view used to jump straight to a download
confirm box. New Kolibre:_showCatalogBookInfo shows Titolo/Autore/Formato/
Peso first (Peso needs backend/app/api/devices.py's _serialize_catalog_book
to also return the "size" field CalibreLibrary.list_books() already
computes per book, in bytes — a purely additive response field, so an
un-updated plugin against a new server, or vice versa, both keep working:
older plugins ignore the new key, and if "size" is ever missing the panel
just skips that line) with a "Scarica sul dispositivo" button that THEN
opens the same confirm dialog as before. One shared function fed by
_catalogItems, which every grid view already goes through — fixed
everywhere in this one change, no per-view wiring needed.

v0.6.11: root-cause fix for a real backlog confirmed on production data
(686 orphaned highlights across 14 books, some over a year old) — a device
that re-packages EPUBs on transfer
(confirmed: Kindle) can NEVER match its partial-MD5 to the server's own
file, so every highlight from such a book landed in OrphanHighlight on
every single sync, permanently, until someone manually paired it from
Dispositivi ▸ Da rivedere. push_device_annotations now returns which
local_path values just went orphan (`orphan_paths`); after a MANUAL
annotation sync (never a silent background one — this uploads the whole
file, real weight an onSuspend/onClose hook must stay clear of) the plugin
tries one content-fingerprint identification per still-unresolved file
(Kolibre:_tryAutoPairOrphans, reusing the existing _identifyFileByContent/
/identify-file mechanism the device-init scan already relies on) and, on a
match, calls the new POST /api/kolibre/devices/annotations/auto-pair to
register it — same non-destructive effect as the manual "Accoppia" action
(record_device_hash + _migrate_orphan_highlights), just triggered upstream
instead of waiting on a human to notice the review queue.

v0.6.13: il backup non ricarica piu' i file invariati — una sola domanda al
server (GET /devices/backup/state) e si caricano solo quelli il cui hash
parziale o dimensione non coincidono. Prima erano dodici file a OGNI sync,
~700 KB, senza alcun controllo. In piu' il sync cronometra le proprie fasi e
le manda a /sync/finish, che le scrive in device_sync_history.detail_json —
finora sempre NULL, quindi di una sincronizzazione lenta non si sapeva dove
fosse andato il tempo.
v0.6.12: new menu action, "Scarica dizionario italiano sul dispositivo"
(Strumenti) — downloads whichever StarDict dictionary is installed server-
side (Impostazioni → Integrazioni → Dizionari) into KOReader's own
data/dict/, so the device's NATIVE dictionary lookup (long-press a word
while reading) finds it too, not just the Vocabolario "Cerca definizione"
card in the web UI. Same manifest + per-file download + checksum pattern as
the plugin self-update above, since KOReader offers this plugin no
zip-extraction library to unpack a StarDict archive with.
]]

local WidgetContainer = require("ui/widget/container/widgetcontainer")
local InfoMessage      = require("ui/widget/infomessage")
local ConfirmBox       = require("ui/widget/confirmbox")
local ButtonDialog     = require("ui/widget/buttondialog")
local InputDialog      = require("ui/widget/inputdialog")
local Menu             = require("ui/widget/menu")
local MultiInputDialog = require("ui/widget/multiinputdialog")
local UIManager        = require("ui/uimanager")
local Event            = require("ui/event")
local Dispatcher       = require("dispatcher")
local util             = require("util")
local MD5              = require("ffi/MD5")
local logger           = require("logger")
local sha2             = require("ffi/sha2")
local lfs              = require("libs/libkoreader-lfs")
local DataStorage      = require("datastorage")
local Device           = require("device")
local DocSettings      = require("docsettings")
local t                = require("kolibre_lingua").t

local KolibreApi = require("kolibre_api")
local KolibreManifest = require("kolibre_manifest")
local KolibreMenuPin = require("kolibre_menu_pin")
local KolibreCatalog = require("kolibre_catalog")
local KolibreCapabilities = require("kolibre_capabilities")
-- Elenchi e finestre che restano dentro lo schermo: un ConfirmBox non
-- scorre, e un elenco troppo lungo spinge i bottoni fuori dal bordo.
local KolibreFinestre = require("kolibre_finestre")
local KolibrePercorsi = require("kolibre_percorsi")
-- Il registro di KOReader ripulito e accorciato: una funzione pura, provata
-- senza KOReader (vedi la prova «il_registro_si_ripulisce»).
local KolibreDiagnostica = require("kolibre_diagnostica")
local KolibreCopertine = require("kolibre_copertine")
local KolibreAvvio    = require("kolibre_avvio")
local KolibreRimozioni = require("kolibre_rimozioni")
local KolibreRiordino = require("kolibre_riordino")
-- Il protocollo di sync v2 (payload, ack, finish), la camminata della
-- cartella con la cache di sessione (E6) e gli attrezzi del layout su disco:
-- trasloco del 20/11/2026, vedi la testa di quel file.
local KolibreSync = require("kolibre_sync")
-- L'auto-aggiornamento del plugin e le patch (manifesto, download,
-- checksum): stesso trasloco. KolibrePatch e KolibreRinvii, che servivano
-- solo a questo flusso, ora li richiede lui.
local KolibreAggiornamento = require("kolibre_aggiornamento")
-- La catena dell'accoppiamento libri-server (impronte e somiglianza):
-- stesso trasloco.
local KolibreAccoppiamento = require("kolibre_accoppiamento")

-- La misura delle letture in CARATTERI: dove comincia e dove finisce ogni
-- pagina letta, e quanto tempo i popup delle note restano aperti. Vedi la
-- testa di `kolibre_letture.lua` per il perche' il carattere assoluto lo
-- calcoli il server e non noi.
local KolibreLetture = require("kolibre_letture")

local VERSION = "1.0.1"

-- La versione la dichiara questo file (la legge anche il server, vedi
-- backend/app/api/tools.py); i moduli che la usano la ricevono qui.
KolibreSync.impostaVersione(VERSION)
KolibreAggiornamento.impostaVersione(VERSION)

local EBOOK_EXTENSIONS = KolibreSync.EBOOK_EXTENSIONS

-- Set once _resumePendingUpdate has run for this KOReader process (see
-- init()) — a file-level local, not a self field, so it's shared by every
-- Kolibre instance created from this same loaded module.
local _resume_checked_this_session = false

-- Same reasoning, for the "avvio" automation moment: init() runs once per
-- FileManager instance AND once per ReaderUI instance, but a cold-start
-- automation should still fire only once per KOReader process.
local _avvio_automation_run_this_session = false
-- Lo stato del momento «avvio»: quanti tentativi si sono fatti, se e'
-- concluso, e quando e' partito l'ultimo sync completo. Sta in
-- `kolibre_avvio`, che e' un modulo — quindi lo stato e' davvero uno solo
-- anche con due istanze del plugin nello stesso processo, e la regola si
-- prova senza KOReader. Ci sono finite dentro due correzioni dell'08/11:
-- vedi la testa di quel file.
local avvio = KolibreAvvio.condiviso

-- Il registratore delle letture in caratteri, uno per processo.
--
-- **Uno solo, e non uno per istanza**, per la stessa ragione del manifesto:
-- di questo plugin esiste un'istanza nel gestore di file e un'altra dentro
-- il lettore, e lo stato «quale pagina e' aperta e da quando» e' uno. In
-- piu' gli agganci dei popup delle note stanno su classi di KOReader, quindi
-- quando scattano non sanno quale istanza del plugin li ha messi: devono
-- trovare un registratore solo, sempre lo stesso.
local _letture = nil
local _agganci_note_messi = false

local function letture()
    if not _letture then
        _letture = KolibreLetture.new({
            percorso = DataStorage:getDataDir() .. "/kolibre-letture.tsv",
        })
    end
    return _letture
end

--- Gli agganci dei popup delle note, messi una volta per processo.
--
-- KOReader **non emette nessun evento** quando apre o chiude il popup di una
-- nota (cercato in `readerlink.lua` e `footnotewidget.lua` della release
-- installata: niente `Event:new` e niente `broadcastEvent`), quindi
-- l'aggancio diretto e' l'unica strada. I due metodi sono pubblici e
-- verificati su una release vera (v2025.08-146-g8726233), **non su master**:
--
--   * `ReaderLink:showAsFootnotePopup` sa QUALE nota (ha il link) ed e' anche
--     l'unico che puo' dire no — modalita' a pagine fisse, xpointer
--     incoerenti, link che non e' una nota. Si conta solo se ha detto si',
--     altrimenti si misurerebbe un popup che non e' mai apparso.
--   * `FootnoteWidget:onCloseWidget` lo chiama UIManager per qualunque strada
--     il popup si chiuda. Vale piu' dei tre callback che il widget si porta
--     dietro (`close_callback`, `on_tap_close_callback`, `follow_callback`):
--     quelli coprono tre strade e si dimenticherebbe la quarta.
--
-- Se uno dei due metodi non c'e' — una release piu' vecchia, o un nome
-- cambiato domani — non si aggancia niente e non si misurano le note. La
-- lettura non deve rompersi per una misura.
local function mettiGliAgganciDelleNote()
    if _agganci_note_messi then return end
    _agganci_note_messi = true

    local ok_link, ReaderLink = pcall(require, "apps/reader/modules/readerlink")
    if ok_link and type(ReaderLink) == "table" and type(ReaderLink.showAsFootnotePopup) == "function" then
        local vecchia = ReaderLink.showAsFootnotePopup
        function ReaderLink:showAsFootnotePopup(link, neglect_current_location)
            local mostrato = vecchia(self, link, neglect_current_location)
            if mostrato then
                pcall(function()
                    letture():apriNota(
                        link and (link.from_xpointer or link.a_xpointer) or nil,
                        link and link.xpointer or nil)
                end)
            end
            return mostrato
        end
    else
        logger.info("Kolibre: niente misura dei popup delle note (showAsFootnotePopup assente)")
    end

    local ok_widget, FootnoteWidget = pcall(require, "ui/widget/footnotewidget")
    if ok_widget and type(FootnoteWidget) == "table" then
        local vecchia_chiusura = FootnoteWidget.onCloseWidget
        function FootnoteWidget:onCloseWidget()
            pcall(function() letture():chiudiNota(self.html) end)
            if vecchia_chiusura then return vecchia_chiusura(self) end
        end
    else
        logger.info("Kolibre: niente misura dei popup delle note (FootnoteWidget assente)")
    end
end

-- Single regular files backed up as-is (raw upload, one request per file).
-- history/bookmarks/clipboard/docsettings (some of which are directories,
-- not single files) need an archiving step first — a follow-up, not this.
-- Deliberately excludes network.lua, cloudstorage.lua, opds.lua and
-- wallabag.lua — these can hold WiFi/WebDAV/Dropbox/FTP/OPDS credentials in
-- plain text, and backing them up server-side isn't worth that exposure.
--
-- Split by real on-disk location, verified against KOReader's own source
-- (frontend/readcollection.lua, plugins/bookshortcuts.koplugin, and a real
-- settings dir) — NOT all of these live under DataStorage:getSettingsDir()
-- (<home>/settings/), some sit directly in DataStorage:getDataDir() (<home>/)
-- itself. Getting this wrong doesn't error, it just silently backs up
-- nothing for that file (lfs.attributes on the wrong path returns nil,
-- backupNow skips it without a word) — settings.reader.lua/history.lua/
-- defaults.custom.lua were exactly this kind of silently-always-broken
-- backup before this split existed.
local BACKUP_FILES_ROOT = { "settings.reader.lua", "history.lua", "defaults.custom.lua" }
local BACKUP_FILES_SETTINGS = {
    "statistics.sqlite3", "vocabulary_builder.sqlite3",
    "gestures.lua", "hotkeys.lua",
    "collection.lua", "bookshortcuts.lua",
    "filemanager_menu_order.lua", "reader_menu_order.lua",
    "directory_defaults.lua",
}

-- "Resetta a stato di dispositivo" (task #266): sottoinsieme di
-- BACKUP_FILES_ROOT/SETTINGS scelto per lo scenario di SOSTITUZIONE
-- dispositivo (non convivenza) — vedi il piano approvato. Esclude
-- collection.lua/bookshortcuts.lua/directory_defaults.lua/history.lua per
-- rischio di percorsi assoluti non portabili sul device target; include
-- statistics.sqlite3 per intero perché backupNow() lo reintegra da solo nel
-- server subito dopo (stessa pipeline di process_statistics_db). Stessa
-- distinzione ROOT/SETTINGS di sopra: sbagliare cartella non da errore, salta
-- silenziosamente il file (lfs.attributes sulla cartella sbagliata è nil).
local RESTORE_FILES_ROOT = { "settings.reader.lua", "defaults.custom.lua" }
local RESTORE_FILES_SETTINGS = {
    "statistics.sqlite3", "vocabulary_builder.sqlite3",
    "gestures.lua", "hotkeys.lua",
    "filemanager_menu_order.lua", "reader_menu_order.lua",
}

-- Reading-position sync, kosync-style: mirrors the control
-- flow of KOReader's own stock plugins/kosync.koplugin/main.lua (push/pull
-- percentage+progress, GotoPage/GotoXPointer to apply), but talks to our own
-- device-bearer-token endpoints instead of the stock kosync wire protocol —
-- that's a separate, not-yet-built compatibility feature, not this.
local PROGRESS_PUSH_DEBOUNCE_SECONDS = 25
local PAGES_BEFORE_AUTO_PUSH = 20

local function detectBooksDir()
    -- KOReader's own user-configurable "Home folder" (File manager settings
    -- → Home folder) — reported directly: on a Kindle with this set to a
    -- custom path, the plugin never checked it at all and fell through to
    -- the hardcoded /mnt/us/documents guess below instead, silently wrong
    -- for anyone who'd actually customized it. This is the exact setting
    -- KOReader's own file chooser (frontend/ui/widget/filechooser.lua) reads
    -- first, before its own hardcoded per-device default — same priority
    -- order here.
    local home_dir = G_reader_settings:readSetting("home_dir")
    if home_dir and home_dir ~= "" and lfs.attributes(home_dir, "mode") == "directory" then
        return home_dir
    end
    -- I posti in cui i libri stanno per abitudine, quando nessuno ha scelto
    -- una cartella. **Presi dal sorgente di KOReader**, non a memoria: ogni
    -- riga qui sotto e' il `home_dir` che la sua classe di dispositivo
    -- dichiara in `frontend/device/<nome>/device.lua`, letto nella release
    -- che gira davvero (v2026.03). Kindle e PocketBook hanno una
    -- sottocartella per convenzione, il Kobo no: li' i libri stanno dentro
    -- `/mnt/onboard`.
    --
    -- **Il Kobo non e' stato provato su un dispositivo** — non ne abbiamo
    -- uno. Il percorso e' quello giusto secondo il codice di KOReader; se un
    -- giorno qualcuno con un Kobo dice che non trova i libri, il sospetto
    -- numero uno e' questa riga.
    local candidates = {
        "/mnt/us/documents",  -- Kindle      (home_dir /mnt/us)
        "/mnt/onboard",       -- Kobo        (home_dir /mnt/onboard)
        "/sdcard/Books",      -- Android
        "/mnt/ext1/Books",    -- PocketBook  (home_dir /mnt/ext1)
    }
    for _idx, path in ipairs(candidates) do
        if lfs.attributes(path, "mode") == "directory" then return path end
    end
    local lastdir = G_reader_settings:readSetting("lastdir")
    if lastdir and lastdir ~= "" then return lastdir end
    return require("datastorage"):getSettingsDir() .. "/books"
end

local Kolibre = WidgetContainer:extend({
    name = "kolibre",
    is_doc_only = false,
})

-- If the zip was downloaded pre-configured for a specific device (web UI ->
-- "Scarica Plugin" on a device card), gconfig.lua carries the server URL and
-- device token so the plugin self-configures instead of requiring manual
-- entry. `fingerprint` lets a *re-download* (e.g. after regenerating the
-- device's token) safely re-apply, while a plain re-install with the same
-- gconfig.lua won't clobber settings the user has since changed by hand.
function Kolibre:_applyGconfig()
    local config_path = (self.path or "plugins/kolibre.koplugin") .. "/gconfig.lua"
    local ok, gconfig = pcall(dofile, config_path)
    if not ok or type(gconfig) ~= "table" then return end

    local saved_fingerprint = G_reader_settings:readSetting("kolibre_gconfig_fingerprint")
    if gconfig.fingerprint and gconfig.fingerprint == saved_fingerprint then
        return -- already applied this exact provisioning
    end

    if gconfig.server_url and gconfig.server_url ~= "" then
        G_reader_settings:saveSetting("kolibre_server_url", gconfig.server_url)
    end
    if gconfig.device_token and gconfig.device_token ~= "" then
        G_reader_settings:saveSetting("kolibre_device_token", gconfig.device_token)
    end
    G_reader_settings:saveSetting("kolibre_gconfig_fingerprint", gconfig.fingerprint)
end

function Kolibre:init()
    self.ui.menu:registerToMainMenu(self)

    self:_applyGconfig()

    self.server_url    = G_reader_settings:readSetting("kolibre_server_url") or ""
    self.device_token  = G_reader_settings:readSetting("kolibre_device_token") or ""
    self.books_dir      = G_reader_settings:readSetting("kolibre_books_dir") or detectBooksDir()

    self.api = KolibreApi.new({ server_url = self.server_url, device_token = self.device_token })
    self.manifest = KolibreManifest.load() -- process-wide singleton, safe across plugin instances

    -- Gli agganci dei popup delle note stanno su classi di KOReader, quindi
    -- si mettono una volta per processo e non una per istanza del plugin:
    -- metterli due volte vorrebbe dire contare ogni nota due volte.
    mettiGliAgganciDelleNote()

    self.push_timestamp = 0
    self.pull_timestamp = 0
    self.page_update_counter = 0

    -- A koplugin is re-instantiated for every FileManager/Reader context, but
    -- an interrupted self-update only needs resuming once per KOReader
    -- process — _resume_checked_this_session (a file-level upvalue, so it
    -- survives across instances of this same loaded module) makes sure a
    -- stuck update's failure message doesn't get shown once per book opened.
    if not _resume_checked_this_session then
        _resume_checked_this_session = true
        local notice = self:_resumePendingUpdate()
        if notice then
            UIManager:nextTick(function() UIManager:show(InfoMessage:new{ text = notice }) end)
        end
    end

    -- Il momento "all'avvio". Il guardiano resta uno per processo, ma segna
    -- «avviato», non «fatto»: prima segnava fatto anche quando il server non
    -- c'era, e quella riga rendeva il difetto permanente fino al riavvio
    -- successivo.
    --
    -- Non piu' `nextTick`: il primo tentativo ha un ritardo suo (vedi
    -- `_provaAvvioConRitentativi`), che e' comunque abbastanza da non
    -- ritardare questa `init()`.
    if not _avvio_automation_run_this_session then
        _avvio_automation_run_this_session = true
        self:_provaAvvioConRitentativi()
    end

    -- La vista libreria come schermata del gestore di file, se accesa.
    --
    -- **Non piu' «una volta per processo».** Fino al 15/11 si apriva solo la
    -- prima volta: all'avvio e basta. Uscendo da un libro ci si ritrovava
    -- nel gestore di file normale, che e' il «usciti da un libro si torna a
    -- Koreader normale invece che a questa vista» di Paolo. Ora si apre
    -- ogni volta che nasce un gestore di file — e chiudendo un libro
    -- KOReader ne costruisce uno NUOVO (`ReaderUI:onClose` ->
    -- `FileManager:showFiles`), quindi questo `init()` gira di nuovo e la
    -- vista torna da se', senza toccare niente di KOReader.
    --
    -- Le condizioni, e la ragione di ognuna:
    --   * **spenta per difetto**: finche' nessuno l'accende, KOReader resta
    --     quello di sempre (decisione dell'11/11);
    --   * **solo nel gestore file**: di questo plugin esiste un'istanza
    --     anche dentro il lettore, e li' `self.ui.document` c'e'. Senza
    --     questo controllo la libreria si aprirebbe sopra il libro che stai
    --     leggendo;
    --   * **non due una sopra l'altra**: le istanze del plugin sono due, e
    --     chi sa se una vista e' gia' viva e' la vista stessa
    --     (`KolibreUI.aperta()`), che si azzera da se' quando si chiude.
    --
    -- E se in KOReader hai scelto «apri l'ultimo libro», il gestore file non
    -- nasce proprio, quindi questa riga non viene nemmeno eseguita: vince la
    -- tua scelta, che e' quello che si era deciso.
    -- Una riga sul registro quando la voce e' accesa, qualunque cosa
    -- succeda dopo. Senza, «non parte» e' una frase e non un indizio: non si
    -- sa se la voce era spenta, se eravamo dentro un libro o se la vista era
    -- gia' aperta. Su un Kindle il registro e' l'unica cosa che si puo'
    -- leggere a distanza.
    if self:_libreriaAllAvvio() then
        logger.info("Kolibre: interfaccia accesa; documento aperto:",
            tostring(self.ui and self.ui.document ~= nil),
            "vista gia' aperta:", tostring(self:_libreriaGiaAperta()))
    end
    if self:_libreriaAllAvvio() and self.ui and not self.ui.document
            and not self:_libreriaGiaAperta() then
        UIManager:nextTick(function()
            -- Il controllo si rifa' qui: fra l'`init()` e il giro dopo di
            -- UIManager puo' essere successo di tutto, e due viste una
            -- sopra l'altra sono un vicolo cieco per chi le deve chiudere.
            if not self:_libreriaGiaAperta() then
                self:apriLibreria(self:_cartellaDelLibroChiuso())
            end
        end)
    end

    -- **Project: Title perde il numero di pagine** (Paolo, 24/11/2026:
    -- «devo avvisare se project title diventa non piu' compatibile»). Dalla
    -- 0.32.0 il server non scrive piu' niente dentro i file dei libri, e il
    -- numero di pagine che Project: Title mostra lo leggeva proprio dai
    -- metadati che il server ci scriveva. Si dice una volta sola, al primo
    -- avvio con Project: Title acceso, e si scrive subito di averlo detto
    -- (`flush`: su un Kindle le impostazioni in memoria non arrivano sempre
    -- su disco, e un avviso che torna a ogni avvio e' un avviso che si
    -- impara a non leggere).
    if self.ui and not self.ui.document
            and not G_reader_settings:isTrue("kolibre_avviso_project_title") then
        UIManager:nextTick(function()
            local ok_c, Compat = pcall(require, "kolibre_ui_compatibilita")
            local ok_l, loader = pcall(require, "pluginloader")
            if ok_c and ok_l and Compat.projectTitleAcceso(loader) then
                G_reader_settings:saveSetting("kolibre_avviso_project_title", true)
                G_reader_settings:flush()
                UIManager:show(InfoMessage:new{ text = t("koreader.compat.project_title_pagine") })
            end
        end)
    end

    KolibreMenuPin.ensure()
end

function Kolibre:_saveSettings()
    G_reader_settings:saveSetting("kolibre_server_url", self.server_url)
    G_reader_settings:saveSetting("kolibre_device_token", self.device_token)
    G_reader_settings:saveSetting("kolibre_books_dir", self.books_dir)
    self.api = KolibreApi.new({ server_url = self.server_url, device_token = self.device_token })
    -- A URL/token edit must never keep being judged by a probe made against
    -- the OLD server — see _isReachable's cache below.
    self._reachable_checked_at = nil
end

-- Il menu: vedi _vociPrimoLivello qui sotto (la forma della 1.0.0, 24/11/2026).
function Kolibre:addToMainMenu(menu_items)
    menu_items.kolibre = {
        text = t("koreader.menu.title"),
        sorting_hint = "tools",
        sub_item_table_func = function() return self:_vociPrimoLivello() end,
    }
end

--- Le voci del primo livello del menu di Kolibre.
--
-- **Perche' una funzione e non la tabella scritta dentro `addToMainMenu`**
-- (16/11/2026). Dal 16/11 lo stesso elenco serve in due posti: il menu del
-- plugin, e il menu che si apre tenendo premuto il logo dentro la vista
-- libreria (Paolo: «tenendo premuto il logo si apre un menu che coincide
-- con il primo livello di quello del plugin»). Scriverlo due volte
-- vorrebbe dire due elenchi che alla prima voce aggiunta non coincidono
-- piu' — ed e' proprio «coincide» la cosa che Paolo ha chiesto.
--
-- `sub_item_table_func` e non `sub_item_table`: questa lista si rilegge a
-- ogni apertura, quindi una voce che dipende dallo stato (la riga delle
-- informazioni, che porta il numero di versione) non si ferma a quello che
-- era al caricamento del plugin.
function Kolibre:_vociPrimoLivello()
    -- **Il menu della 1.0.0** (piano approvato da Paolo il 24/11/2026):
    -- «ogni azione deve avere il suo posto». In alto la cosa di tutti i
    -- giorni, «Sync»; in Tools le azioni che si fanno ogni tanto; in Global
    -- quelle pesanti su tutta la biblioteca; in Dev quelle per lo sviluppo.
    -- Se ne sono andate «Open the Kolibre library» (la vista accesa c'e'
    -- sempre, vedi il punto 3 del piano), «Books managed by Kolibre», «Run
    -- backup now» e «Backup reminder»: il backup e' gia' una fase della
    -- sincronizzazione completa (kolibre_sync.lua, fase 6), e al posto del
    -- suo promemoria c'e' «Last sync reminder» nelle impostazioni.
    return {
        {
            -- Tenendo premuta una voce, KOReader mostra il suo
            -- `help_text` (verificato in frontend/ui/widget/
            -- touchmenu.lua, che lo fa anche per le voci disattivate).
            -- Qui dentro va l'elenco di cosa viene sincronizzato: e' la
            -- domanda che si fa davanti a un comando che fa sette cose,
            -- e la risposta non sta nel nome.
            text = t("koreader.menu.sync_all"),
            help_text = t("koreader.menu.sync_all_help"),
            icon = "sync",
            keep_menu_open = true,
            callback = function() self:syncNow(true, "manual") end,
        },
        {
            text = t("koreader.menu.tools"),
            sub_item_table_func = function() return self:_toolsMenuItems() end,
        },
        {
            text = t("koreader.menu.global"),
            help_text = t("koreader.menu.global_help"),
            sub_item_table_func = function() return self:_globalMenuItems() end,
        },
        {
            text = t("koreader.menu.dev"),
            sub_item_table_func = function() return self:_devMenuItems() end,
        },
        {
            -- **Una sezione sua** (Paolo, 16/11/2026): li' si dice come si
            -- vede la libreria, nelle impostazioni a quale server parlare.
            text = t("koreader.ui.sezione"),
            help_text = t("koreader.ui.sezione_help"),
            sub_item_table_func = function() return self:_uiMenuItems() end,
        },
        {
            text = t("koreader.menu.settings"),
            sub_item_table_func = function() return self:_settingsMenuItems() end,
        },
    }
end

--- Settings: la connessione, il popup, il promemoria, le informazioni.
function Kolibre:_settingsMenuItems()
    return {
        {
            text = t("koreader.settings.connection"),
            keep_menu_open = true,
            callback = function() self:showSettings() end,
        },
        {
            text = t("koreader.settings.test_connection"),
            keep_menu_open = true,
            callback = function() self:testConnection() end,
        },
        {
            text = t("koreader.settings.sync_popup"),
            help_text = t("koreader.settings.sync_popup_help"),
            checked_func = function() return self:_popupDiSincronizzazione() end,
            callback = function()
                self:_impostaPopupDiSincronizzazione(not self:_popupDiSincronizzazione())
            end,
        },
        {
            text = t("koreader.sync_reminder.menu"),
            help_text = t("koreader.sync_reminder.menu_help"),
            sub_item_table_func = function() return self:_syncReminderMenuItems() end,
        },
        {
            -- La versione della UI accanto a quella del plugin, e non una
            -- voce in piu': sono due numeri che rispondono alla stessa
            -- domanda («cosa ho installato?»).
            text = t("koreader.settings.info", {
                version = VERSION,
                ui = self:_versioneDellaUI(),
            }),
            keep_menu_open = true,
            callback = function() self:showInfo() end,
        },
    }
end

--- Tools: le azioni che si fanno ogni tanto.
--
-- Una funzione e non una tabella fissa: `enabled_func` deve rileggere
-- `self.ui.document` ogni volta che il sottomenu si apre.
function Kolibre:_toolsMenuItems()
    local items = {
        {
            -- Era «Catalog»: per ora cambia solo il nome (la riscrittura e'
            -- il passo dopo la 1.0.0, fuori da questo piano).
            text = t("koreader.menu.catalog"),
            keep_menu_open = true,
            callback = function() self:openCatalogDashboard() end,
        },
        {
            -- La meta' veloce di «Sync»: solo i libri in arrivo e in uscita.
            text = t("koreader.menu.check_new_books"),
            help_text = t("koreader.menu.check_new_books_help"),
            keep_menu_open = true,
            callback = function() self:syncBooksOnly(true, "manual_libri") end,
        },
        {
            -- Plugin e patch nello stesso comando: arrivano dallo stesso
            -- server e si guardano per lo stesso motivo.
            text = t("koreader.update.menu_check"),
            help_text = t("koreader.update.menu_check_help"),
            keep_menu_open = true,
            -- Sotto il segno d'attesa (20/11/2026, E7): si avvolge QUI e non
            -- dentro controllaAggiornamenti, perche' il chiamante automatico
            -- (_autoCheckForUpdate) deve restare muto.
            callback = function()
                self:_runWithWaitingSign(nil, function() self:controllaAggiornamenti(true) end)
            end,
            separator = true,
        },
        {
            text = t("koreader.position.push_current"),
            enabled_func = function() return self.ui.document ~= nil end,
            keep_menu_open = true,
            callback = function() self:pushProgress(true) end,
        },
        {
            text = t("koreader.position.pull_current"),
            enabled_func = function() return self.ui.document ~= nil end,
            keep_menu_open = true,
            callback = function() self:pullProgress(true) end,
            separator = true,
        },
        {
            -- Il sottomenu si costruisce all'apertura perche' deve chiedere
            -- al server cosa esiste e guardare sul disco cosa c'e'.
            text = t("koreader.patches.menu"),
            sub_item_table_func = function() return self:_patchMenuItems() end,
        },
        {
            text = t("koreader.menu.automations"),
            sub_item_table_func = function() return self:_automationMenuItems() end,
        },
    }
    return items
end

--- Global: le azioni pesanti, che passano tutta la biblioteca.
function Kolibre:_globalMenuItems()
    return {
        {
            -- Cammina tutti i libri del dispositivo leggendo i sidecar,
            -- senza aprirli uno per uno.
            text = t("koreader.position.sync_all"),
            keep_menu_open = true,
            callback = function() self:syncAllProgress(true) end,
        },
        {
            -- L'unico modo di rifare la scansione completa delle note:
            -- «Sync» manda solo la coda (vedi la fase 6 di _syncNowRun).
            -- Serve dopo aver accoppiato un libro gia' sottolineato.
            text = t("koreader.annotations.push_all_full"),
            keep_menu_open = true,
            callback = function() self:pushAllAnnotationsFull(true) end,
        },
        {
            text = t("koreader.library_init.menu"),
            keep_menu_open = true,
            callback = function() self:initLibrary() end,
        },
        {
            text = t("koreader.restore.menu"),
            keep_menu_open = true,
            callback = function() self:_startDeviceRestore() end,
        },
    }
end

--- Dev: le azioni per lo sviluppo, che guardano e raccontano.
function Kolibre:_devMenuItems()
    return {
        {
            -- Un'azione che si preme, non una cosa che viaggia dentro la
            -- sincronizzazione: camminare tutta la cartella e aprire ogni
            -- sidecar costa (deciso con Paolo il 05/11/2026). Da deprecare
            -- presto (piano del 24/11).
            text = t("koreader.inventory.menu"),
            keep_menu_open = true,
            callback = function() self:mandaInventario() end,
        },
        {
            text = t("koreader.diagnostica.menu"),
            help_text = t("koreader.diagnostica.menu_help"),
            keep_menu_open = true,
            callback = function() self:mandaIlRegistro() end,
        },
    }
end

-- ── Info dialog ──

function Kolibre:showInfo()
    local policy_labels = {
        auto = t("koreader.info.policy_auto"),
        ask = t("koreader.info.policy_ask"),
        never = t("koreader.info.policy_never"),
    }
    local last_sync = self.manifest:getMeta("last_sync_at")
    local policy = self.manifest:getMeta("delete_policy")
    UIManager:show(InfoMessage:new{
        text = t("koreader.info.body", {
            version = VERSION,
            server = self.server_url ~= "" and self.server_url or t("koreader.common.not_configured"),
            last_sync = last_sync and os.date("%Y-%m-%d %H:%M", last_sync) or t("koreader.info.last_sync_never"),
            count = self.manifest:count(),
            policy = policy and (policy_labels[policy] or tostring(policy)) or t("koreader.info.policy_unknown"),
        }),
    })
end

-- ── Settings dialog ──

function Kolibre:showSettings()
    self.settings_dialog = MultiInputDialog:new{
        title = t("koreader.settings.dialog_title"),
        fields = {
            { description = t("koreader.settings.field_server_url"), text = self.server_url },
            { description = t("koreader.settings.field_device_token"), text = self.device_token },
            { description = t("koreader.settings.field_books_dir"), text = self.books_dir },
        },
        buttons = {{
            {
                text = t("koreader.common.cancel"),
                callback = function() UIManager:close(self.settings_dialog) end,
            },
            {
                text = t("koreader.common.save"),
                callback = function()
                    local f = self.settings_dialog:getFields()
                    self.server_url   = KolibreApi.normalizeServerUrl(f[1]) or ""
                    self.device_token = (f[2] or ""):gsub("^%s+", ""):gsub("%s+$", "")
                    self.books_dir     = (f[3] or ""):gsub("/+$", "")
                    self:_saveSettings()
                    UIManager:close(self.settings_dialog)
                    UIManager:show(InfoMessage:new{ text = t("koreader.settings.saved"), timeout = 2 })
                end,
            },
        }},
    }
    UIManager:show(self.settings_dialog)
    self.settings_dialog:onShowKeyboard()
end

-- ── Test connection (GET /api/devices/me) ──

function Kolibre:testConnection()
    if not self.api:isConfigured() then
        UIManager:show(InfoMessage:new{ text = t("koreader.common.not_configured_message") })
        return
    end
    -- Timeout corto: qui si sta solo chiedendo «ci sei?», e aspettare dieci
    -- secondi la risposta a quella domanda vuol dire dieci secondi di lettore
    -- fermo (vedi KolibreApi.TIMEOUT_CONTROLLO). E il segno d'attesa
    -- (20/11/2026, E7): anche tre secondi a schermo fermo, senza niente che
    -- dica «sto lavorando», sono esattamente la lamentela d'origine.
    self:_runWithWaitingSign(t("koreader.common.contacting_server"), function()
        local result, err = self.api:request("GET", "/api/devices/me", nil, { breve = true })
        if not result then
            UIManager:show(InfoMessage:new{ text = t("koreader.settings.test_failed", { error = tostring(err) }) })
            return
        end
        -- A successful manual probe is exactly the same one _isReachable would
        -- make — warm its cache instead of throwing this result away.
        self._reachable_checked_at, self._reachable_cached, self._reachable_cached_err = os.time(), true, nil
        UIManager:show(InfoMessage:new{ text = t("koreader.settings.test_ok", { name = tostring(result.name) }) })
    end)
end

-- ── Reachability gate ──
--
-- Every network-touching action used to make its own request and only find
-- out it failed afterwards (a confusing partial-progress error, or several
-- of the same "server non raggiungibile" message in a row for one user
-- action with many sub-steps, e.g. "Sincronizza tutto"). This checks once,
-- up front, and lets a caller bail out cleanly instead. Cached briefly so
-- one user action's several sub-calls (again, "Sincronizza tutto") don't
-- each re-probe.
local REACHABILITY_CACHE_SECONDS = 20

function Kolibre:_isReachable()
    local now = os.time()
    if self._reachable_checked_at and now - self._reachable_checked_at < REACHABILITY_CACHE_SECONDS then
        return self._reachable_cached, self._reachable_cached_err
    end
    -- **`breve`: qui si chiede solo «ci sei?».** Con il runtime Lua a thread
    -- singolo, aspettare la risposta e' lettore fermo. Misurato sul KOReader
    -- vero (v2026.03, 04/11/2026) verso una macchina accesa il cui backend
    -- non ha ancora aperto la porta: **10,01 s** con i timeout grandi di
    -- KOReader, **3,00 s** con questi. Il server vero risponde in 0,31 s,
    -- quindi i tre secondi non togliono niente a chi c'e'.
    --
    -- Mancava, e il timeout corto era collegato solo al «Prova connessione»
    -- delle impostazioni — cioe' all'unico punto dove dieci secondi d'attesa
    -- non danno fastidio, perche' l'utente l'ha chiesta e sta guardando.
    -- Qui passano INVECE tutte le azioni, l'avvio compreso: all'avvio senza
    -- server erano dieci secondi di lettore bloccato al primo tentativo, che
    -- e' esattamente il difetto che Paolo ha descritto.
    local result, err = self.api:request("GET", "/api/devices/me", nil, { breve = true })
    self._reachable_checked_at = now
    self._reachable_cached = result ~= nil
    self._reachable_cached_err = err
    return self._reachable_cached, err
end

--- Butta via la risposta ricordata: il prossimo controllo la chiede alla rete.
--
-- **Perche' serve.** La cache dura 20 secondi e i ritentativi dell'avvio
-- distano 15. Quando il fallimento e' **istantaneo** — connessione rifiutata,
-- cioe' macchina accesa e Kolibre che non ha ancora aperto la porta: il caso
-- di Paolo — il tentativo successivo cade dentro la finestra e si sente
-- rispondere dalla memoria, senza chiedere niente a nessuno. Misurato sul
-- dispositivo il 04/11/2026: su quattro tentativi contati, **due** richieste
-- vere.
--
-- **Perche' non si accorcia invece la cache.** I suoi 20 secondi servono a
-- un'altra cosa, e la fanno bene: un «Sincronizza tutto» fa molte
-- sotto-chiamate di fila e non deve chiedere «ci sei?» a ognuna. Accorciarla
-- per far tornare i conti dei ritentativi vorrebbe dire legare due numeri che
-- non hanno niente in comune, e il prossimo che cambiasse l'intervallo
-- riaprirebbe il difetto senza sapere perche'. Chi RIPROVA vuole una risposta
-- fresca per definizione: lo si dice qui, dove si riprova.
function Kolibre:_dimenticaRaggiungibilita()
    self._reachable_checked_at = nil
    self._reachable_cached = nil
    self._reachable_cached_err = nil
end

function Kolibre:_requireReachable(interactive)
    if not self.api:isConfigured() then
        if interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.common.not_configured_message") })
        end
        return false
    end
    local ok, err = self:_isReachable()
    if not ok then
        if interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.common.unreachable", { error = tostring(err) }) })
        end
        return false
    end
    return true
end

-- ── Progress feedback for long synchronous loops ──
-- KOReader's Lua runtime is single-threaded/cooperative: a tight for-loop
-- (hashing many files, downloading many books) gives no feedback and looks
-- like a frozen device unless we actively repaint between steps. These two
-- helpers keep a single reusable InfoMessage alive across a loop instead of
-- stacking dialogs.
-- **Il popup delle sincronizzazioni automatiche**, acceso di default.
--
-- Una sincronizzazione automatica (all'avvio, aprendo un libro, chiudendolo)
-- mostra una barra di avanzamento sopra quello che stai leggendo, e alla
-- fine un riepilogo se e' successo qualcosa. E' utile mentre si prende
-- confidenza con il plugin, ed e' un'interruzione quando la confidenza c'e'.
--
-- Spento, le sincronizzazioni automatiche diventano completamente mute.
-- **Quelle chieste a mano rispondono sempre**, qualunque sia questa
-- impostazione: un comando che non dice niente non si distingue da un
-- comando che non ha funzionato. Resta fuori anche l'avviso sulle note che
-- il server non ha saputo collocare (_reportAnnotationPushResult): non e'
-- un resoconto di routine, e' un problema nei dati.
function Kolibre:_popupDiSincronizzazione()
    local v = G_reader_settings:readSetting("kolibre_popup_sync")
    if v == nil then return true end
    return v
end

function Kolibre:_impostaPopupDiSincronizzazione(valore)
    G_reader_settings:saveSetting("kolibre_popup_sync", valore)
end

function Kolibre:_showProgress(text)
    if self._progress_msg then UIManager:close(self._progress_msg) end
    self._progress_msg = InfoMessage:new{ text = text, timeout = false }
    UIManager:show(self._progress_msg)
    UIManager:forceRePaint()
end

function Kolibre:_closeProgress()
    if self._progress_msg then
        UIManager:close(self._progress_msg)
        self._progress_msg = nil
    end
end

-- Rendered "[====------] 40% - Label..." bar, same exact math/format as the
-- KOReader plugin of an earlier, unpublished project of my own (its
-- syncAll) — reused on purpose, not designed from scratch. `current` is
-- 1-based (the bar shows how far in you are BEFORE this step runs, as it
-- was there), reusing the existing _showProgress InfoMessage-reuse mechanic
-- underneath.
function Kolibre:_showProgressBar(current, total, label)
    local n = math.max(total, 1)
    local filled = math.floor((current - 1) / n * 10)
    self:_showProgress(string.format("[%s%s] %d%% - %s...",
        string.rep("=", filled), string.rep("-", 10 - filled),
        math.floor((current - 1) / n * 100), label))
end

-- -- Il segno d'attesa prima di parlare con la rete (E7, 20/11/2026) --
--
-- La regola di progetto: qualunque operazione che puo' superare il secondo
-- o mostra un'attesa, oppure va in sottofondo. Le due lamentele d'origine
-- («il lettore resta fermo qualche secondo senza dire niente», «un
-- controllo di connessione costa 3 s») sono la stessa malattia: una
-- chiamata di rete sincrona senza nessun segno sullo schermo.
--
-- **Perche' il nextTick, e non solo il messaggio.** Su e-ink un InfoMessage
-- mostrato e subito seguito dal socket che blocca non arriva allo schermo:
-- il disegno non ha avuto il suo giro. `_showProgress` fa gia' un
-- `forceRePaint`, e il `nextTick` lascia comunque respirare la coda degli
-- eventi prima che il socket blocchi: cosi' il messaggio si VEDE davvero.
--
-- **Il pcall non e' prudenza di maniera.** Quello che succede dentro un
-- `nextTick` non e' protetto da niente (lo dice gia' il commento sulla
-- apertura dei libri della vista): un errore li' dentro risale fino in
-- cima e lascerebbe il messaggio d'attesa appeso per sempre.
--
-- **La rientranza.** Un flusso gia' sotto segno (es. «Cambia libreria» che
-- riapre il catalogo) non deve impilare un secondo nextTick: il primo
-- chiuderebbe il segno del secondo prima che giri. Dentro un segno attivo
-- si aggiorna il testo e si esegue subito.
function Kolibre:_runWithWaitingSign(text, fn)
    local label = text or t("koreader.common.contacting_server")
    if self._waiting_sign_active then
        self:_showProgress(label)
        local ok, err = pcall(fn)
        if not ok then
            logger.err("Kolibre: azione fallita sotto il segno d'attesa:", err)
        end
        return
    end
    self._waiting_sign_active = true
    self:_showProgress(label)
    UIManager:nextTick(function()
        local ok, err = pcall(fn)
        self:_closeProgress()
        self._waiting_sign_active = false
        if not ok then
            logger.err("Kolibre: azione fallita sotto il segno d'attesa:", err)
        end
    end)
end

-- ── Local library scan ──
--
-- La camminata vive in kolibre_sync.lua (trasloco del 20/11/2026), con la
-- cache di sessione di E6: dentro una sessione aperta da
-- _runAutomationMoment la cartella si percorre UNA volta e il risultato
-- si riusa. Fuori sessione, ogni chiamata cammina come sempre.
function Kolibre:_scanLocalBooks(...) return KolibreSync._scanLocalBooks(self, ...) end

-- ── On-device book layout ──
--
-- La convenzione del layout su disco e i suoi attrezzi (sanitizeFilename,
-- doveScrivere, ensureDir, cartellaScrivibile) vivono in kolibre_sync.lua
-- dal trasloco del 20/11/2026 (revisione A2): la usa il flusso dei
-- download del sync, e UNA definizione vale piu' di tre copie. Qui gli
-- alias per i chiamanti rimasti (download dal catalogo, dizionari,
-- aggiornamento).
local sanitizeFilename = KolibreSync.sanitizeFilename
local esisteIlFile = KolibreSync.esisteIlFile
local doveScrivere = KolibreSync.doveScrivere
local ensureDir = KolibreSync.ensureDir
local cartellaScrivibile = KolibreSync.cartellaScrivibile

-- One level is always enough here: only ever called on a "<book>.sdr"
-- sidecar directory, which KOReader itself never nests further. Needed
-- because lfs.rmdir (like POSIX rmdir) only removes an EMPTY directory —
-- DocSettings:purge() doesn't always remove the .sdr folder itself, just
-- what's inside it, which used to leave an empty (or near-empty) .sdr
-- behind and block _cleanupBookDir from ever removing the parent folder.
local function _removeDirRecursive(dir)
    local ok, iter, dir_obj = pcall(lfs.dir, dir)
    if not ok or not iter then return end
    for entry in iter, dir_obj do
        if entry ~= "." and entry ~= ".." then
            local full = dir .. "/" .. entry
            if lfs.attributes(full, "mode") == "directory" then
                _removeDirRecursive(full)
            else
                os.remove(full)
            end
        end
    end
    pcall(lfs.rmdir, dir)
end

-- ── OPDS-style catalog browser ("stile BookOrbit") ──
--
-- Unlike the rest of this plugin (server decides what's on the device), this
-- is the device *pulling* on demand: browse/search a library's full catalog
-- and download any book directly. Deliberately simpler than BookOrbit's own
-- cover-grid catalog widget (which monkey-patches Menu's renderer for
-- thumbnails) — this uses a plain text-list Menu, whose built-in pagination
-- (Menu already paginates a long item_table on its own) is enough for a
-- first working version; a cover-grid upgrade is a follow-up, not this.

-- urlEncode vive in kolibre_sync.lua col resto degli attrezzi (trasloco
-- del 20/11/2026): qui l'alias per i chiamanti rimasti.
local urlEncode = KolibreSync.urlEncode

-- Maps a catalog "section" (the bucket-list endpoint, plural, matching the
-- URL path) to the singular filter param name _openKolibreCatalog's `drill`
-- forwards onto the sibling /catalog endpoint, plus the label used in both
-- the section-browser dialog and the drilled-down catalog title. One table
-- instead of three near-identical functions/branches.
local SECTION_INFO = {
    authors = { filter_key = "author", label = t("koreader.catalog.section_author") },
    series  = { filter_key = "series", label = t("koreader.catalog.section_series") },
    tags    = { filter_key = "tag",    label = t("koreader.catalog.section_tag") },
}

-- On-demand sibling of _backfillAuthorFolderCovers (1477-1525): same
-- write_folder_cover/folder_layout gate, same "already there? skip" check,
-- same self-built author-photo URL — but for a SINGLE fresh download
-- instead of a full-library sweep, so a book grabbed straight from the
-- catalog Dashboard/Browser gets its author folder's .folder.jpg on the
-- very first download, not only after the next "Verifica libreria"/
-- "Sincronizza tutto". Deliberately independent from this and from
-- runDownloads' own inline cover-write (which uses a server-supplied
-- folder_cover_url the catalog response doesn't carry) — reusing either
-- verbatim would mean touching already-verified, in-production code paths
-- for no real benefit.
function Kolibre:_ensureAuthorFolderCover(author, target_dir)
    local write_folder_cover = self.write_folder_cover
    if write_folder_cover == nil then write_folder_cover = true end
    if not write_folder_cover or (self.folder_layout or "author") ~= "author" then return end
    if not author or author == "" or target_dir == self.books_dir then return end
    local cover_path = target_dir .. "/.folder.jpg"
    if lfs.attributes(cover_path, "mode") then return end
    self.api:downloadTo("/api/kolibre/authors/" .. urlEncode(author) .. "/photo/thumbnail", cover_path)
end

-- `muto` (20/11/2026, E7): i chiamanti che stanno GIA' sotto un loro segno
-- d'attesa (il giro di sovrascritture dell'inizializzazione libreria, la
-- Fase 2.5 della sincronizzazione quando i popup automatici sono spenti)
-- passano true e questo non tocca lo schermo.
function Kolibre:_downloadCatalogBook(book, library, muto)
    local formats = book.formats or {}
    local fmt = formats[1] or "EPUB"
    local dir_calcolata = self.books_dir
    if (self.folder_layout or "author") == "author" and book.author and book.author ~= "" then
        dir_calcolata = self.books_dir .. "/" .. sanitizeFilename(book.author)
    end

    local title = sanitizeFilename(book.title or string.format("libro_%d", book.id))
    local filename = string.format("%s.%s", title, fmt:lower())
    -- Stessa regola della consegna dal server: se il manifesto dice che quel
    -- libro c'e' gia', si riscrive quello. Qui succede eccome — si scarica
    -- dal catalogo un libro che il dispositivo potrebbe avere sotto un altro
    -- nome, ed e' proprio il caso in cui nascerebbe una seconda copia.
    local chiave = KolibreManifest.bookKey(library, book.id, fmt)
    local local_path, target_dir = doveScrivere(
        self.manifest, chiave, dir_calcolata .. "/" .. filename, self.books_dir)
    ensureDir(target_dir)
    self:_ensureAuthorFolderCover(book.author, target_dir)

    local url = string.format("/api/kolibre/books/%d/download?library=%s&format=%s", book.id, library, fmt)

    -- 20/11/2026 (E7): un libro intero puo' costare decine di secondi, e il
    -- tocco su «Scarica» non mostrava niente fino all'esito. `_showProgress`
    -- e non `_runWithWaitingSign`: chi chiama (la Fase 2.5 della
    -- sincronizzazione) ha bisogno dell'esito SUBITO, quindi niente
    -- nextTick; il forceRePaint dentro _showProgress porta comunque il
    -- messaggio allo schermo prima che il socket blocchi.
    if not muto then
        self:_showProgress(t("koreader.catalog.downloading", { title = book.title or filename }))
    end
    local ok, err = self.api:downloadTo(url, local_path)
    if not muto then self:_closeProgress() end
    if ok then
        -- Device-initiated acquisition: record it in the manifest (Kolibre
        -- now manages this book) and tell the server to start tracking it.
        -- If /books/delivered fails, the dirty manifest makes the next sync's
        -- managed_books report deliver the same information.
        local hash = util.partialMD5(local_path)
        self.manifest:set(chiave, {
            path = local_path,
            hash = hash,
            title = book.title,
            author = book.author,
            library = library,
            calibre_book_id = book.id,
            format = fmt:upper(),
            downloaded_at = os.time(),
            server_pages = book.server_pages,
        })
        local delivered, deliver_err = self.api:request("POST", "/api/kolibre/devices/books/delivered", {
            calibre_book_id = book.id,
            library = library,
            format = fmt,
            path = local_path,
            hash = hash,
        })
        if not delivered then
            logger.warn("Kolibre: /books/delivered fallito:", deliver_err)
        end
        UIManager:show(InfoMessage:new{ text = t("koreader.catalog.downloaded", { filename = filename }), timeout = 3 })
    else
        UIManager:show(InfoMessage:new{ text = t("koreader.catalog.download_failed", { error = tostring(err) }) })
    end
    -- Callers used to all be fire-and-forget statements, so this fell
    -- through returning nil regardless of outcome — syncNow's Fase 2.5
    -- (file_actions "overwrite") needs the real result to decide whether
    -- to ack the action as applied.
    return ok
end

local FILE_SIZE_UNITS = { "B", "KB", "MB", "GB" }

local function formatFileSize(bytes)
    if not bytes or bytes <= 0 then return nil end
    local size = bytes
    local unit_idx = 1
    while size >= 1024 and unit_idx < #FILE_SIZE_UNITS do
        size = size / 1024
        unit_idx = unit_idx + 1
    end
    if unit_idx == 1 then
        return string.format("%d %s", size, FILE_SIZE_UNITS[unit_idx])
    end
    return string.format("%.1f %s", size, FILE_SIZE_UNITS[unit_idx])
end

-- Tapping a catalog book used to jump straight to a download confirm
-- dialog — an info panel now comes first (Titolo/Autore/Formato/Peso)
-- with the download action as its own explicit button, confirm dialog only
-- after that's tapped. One shared function since _catalogItems feeds every
-- grid view (browser, search, drill-down, Recent, Discover) — fixing it
-- here fixes it everywhere at once.
function Kolibre:_showCatalogBookInfo(book, library)
    local lines = {
        t("koreader.catalog.info_title", { title = book.title or "?" }),
        t("koreader.catalog.info_author", { author = book.author or t("koreader.catalog.unknown_author") }),
        t("koreader.catalog.info_format", { format = table.concat(book.formats or {}, "/") }),
    }
    local size_label = formatFileSize(book.size)
    if size_label then
        table.insert(lines, t("koreader.catalog.info_size", { size = size_label }))
    end

    local dialog
    dialog = ButtonDialog:new{
        title = table.concat(lines, "\n"),
        buttons = {
            {{
                text = t("koreader.catalog.download_button"),
                callback = function()
                    UIManager:close(dialog)
                    UIManager:show(ConfirmBox:new{
                        text = t("koreader.catalog.download_confirm", { title = book.title or "?" }),
                        ok_callback = function() self:_downloadCatalogBook(book, library) end,
                    })
                end,
            }},
            {{
                text = t("koreader.common.close"),
                callback = function() UIManager:close(dialog) end,
            }},
        },
    }
    UIManager:show(dialog)
end

function Kolibre:_catalogItems(books, library)
    local items = {}
    for _idx, b in ipairs(books) do
        table.insert(items, {
            text = string.format("%s — %s", b.title or "?", b.author or t("koreader.catalog.unknown_author_item")),
            mandatory = table.concat(b.formats or {}, "/"),
            -- Read directly by kolibre_catalog.lua's mosaic tiles (title/
            -- author/id) instead of re-parsing `text` — list mode doesn't
            -- need it, only mosaic does.
            book = b,
            callback = function()
                self:_showCatalogBookInfo(b, library)
            end,
        })
    end
    return items
end

-- Right title-bar icon: a single dialog with both "Vista" (list/mosaic,
-- persisted) and "Ordina" (author/recent) controls — simpler than trying to
-- fit a third icon into KOReader's two-icon TitleBar, same reasoning
-- BookOrbit's own showBookActions() dialog uses for its own secondary
-- controls. `drill` (see _openKolibreCatalog) is threaded through purely so
-- re-sorting or re-searching from inside a drilled-down view ("Autore:
-- Victor Hugo") doesn't silently drop the filter.
--
-- The three "Sfoglia per..." buttons are gated behind the catalogSections
-- capability (kolibre_capabilities.lua) — hidden outright on a server that
-- doesn't confirm support (old server, unreachable, or genuinely lacking
-- it), never shown disabled. That matches every other capability-style gate
-- in this file: a feature that can't work on this server simply isn't
-- offered, rather than being tappable and failing.
function Kolibre:_showCatalogViewDialog(catalog_menu, library, query, sort, drill, exclude_on_device)
    local dialog
    local view_label = catalog_menu.view_mode == "mosaic" and t("koreader.catalog.view_grid") or t("koreader.catalog.view_list")
    local buttons = {
        {{
            text = view_label,
            callback = function()
                UIManager:close(dialog)
                catalog_menu:setViewMode(catalog_menu.view_mode == "mosaic" and "list" or "mosaic")
            end,
        }},
        {{
            text = t("koreader.catalog.sort_author"),
            enabled = sort ~= "author",
            callback = function()
                UIManager:close(dialog)
                UIManager:close(catalog_menu)
                self:_openKolibreCatalog(library, query, "author", drill, exclude_on_device)
            end,
        }},
        {{
            text = t("koreader.catalog.sort_recent"),
            enabled = sort ~= "recent",
            callback = function()
                UIManager:close(dialog)
                UIManager:close(catalog_menu)
                self:_openKolibreCatalog(library, query, "recent", drill, exclude_on_device)
            end,
        }},
    }

    if KolibreCapabilities:supports(self.api, "catalogSections") then
        for _idx, section in ipairs({ "authors", "series", "tags" }) do
            local info = SECTION_INFO[section]
            table.insert(buttons, {{
                text = t("koreader.catalog.browse_by", { section = info.label:lower() }),
                callback = function()
                    UIManager:close(dialog)
                    UIManager:close(catalog_menu)
                    self:_browseCatalogSection(section, library, sort)
                end,
            }})
        end
    end

    table.insert(buttons, {{
        text = t("koreader.common.close"),
        callback = function() UIManager:close(dialog) end,
    }})

    dialog = ButtonDialog:new{
        title = t("koreader.catalog.label"),
        buttons = buttons,
    }
    UIManager:show(dialog)
end

-- `drill`, when present, is `{ kind = "author"|"series"|"tag", value = name
-- }` — a name-based substring filter drilled into from the bucket lists
-- _browseCatalogSection renders (Sfoglia per autore/serie/tag). Independent
-- of `query` (the free-text search box): both can be set at once, forwarded
-- as separate params, exactly like the backend already treats `q` and
-- `author` as independent filters.
--
-- `exclude_on_device` (new, Browser's "Non sul device" view): forwarded
-- as-is to the sibling /catalog endpoint's own `exclude_on_device` param
-- (devices.py), and threaded through the sort/search round-trips below
-- (_showCatalogViewDialog, _promptCatalogSearch) so re-sorting or
-- re-searching from inside that view doesn't silently drop back to showing
-- books already on the device. NOT threaded into the "Sfoglia per
-- autore/serie/tag" section drill-down — combining the two wasn't asked
-- for and would need its own exclude_on_device support in
-- catalog/sections, which is a different endpoint.
function Kolibre:_openKolibreCatalog(library, query, sort, drill, exclude_on_device)
    -- 20/11/2026 (E7): la prima pagina del catalogo e' una richiesta
    -- sincrona che su una biblioteca grande puo' costare secondi, e il
    -- tocco (da ricerca, drill o «Tutti i libri») non mostrava niente.
    -- Involucro e corpo separati perche' il corpo ha piu' uscite e viene
    -- richiamato da cinque punti diversi: tutti passano da qui.
    self:_runWithWaitingSign(t("koreader.catalog.loading"), function()
        self:_openKolibreCatalogNow(library, query, sort, drill, exclude_on_device)
    end)
end

function Kolibre:_openKolibreCatalogNow(library, query, sort, drill, exclude_on_device)
    sort = sort or "author"

    -- One grid screen's worth per request (see KolibreCatalog.mosaicPageSize)
    -- — faithful port of BookOrbit's own model (bookorbit_catalog.lua:
    -- itemsPerPage/showBookPage/onNextPage): each page turn fetches exactly
    -- one page and REPLACES the mosaic's item_table, never accumulates. This
    -- is what actually keeps browse_catalog's response tiny regardless of
    -- library size — see v0.6.6 changelog for why the earlier bounded-but-
    -- accumulating v0.6.5 scheme was replaced with this simpler one.
    local page_size = KolibreCatalog.mosaicPageSize()

    local function buildPath(server_page, size)
        local path = "/api/kolibre/devices/catalog?library=" .. urlEncode(library)
            .. "&sort=" .. urlEncode(sort)
            .. "&page=" .. tostring(server_page) .. "&size=" .. tostring(size)
        if query and query ~= "" then
            path = path .. "&q=" .. urlEncode(query)
        end
        if drill then
            path = path .. "&" .. drill.kind .. "=" .. urlEncode(drill.value)
        end
        if exclude_on_device then
            path = path .. "&exclude_on_device=true"
        end
        return path
    end

    local result, err = self.api:request("GET", buildPath(1, page_size))
    if not result then
        UIManager:show(InfoMessage:new{ text = t("koreader.catalog.unavailable", { error = tostring(err) }) })
        return
    end

    local title = t("koreader.catalog.title")
    if drill then
        -- SECTION_INFO is keyed by section name (plural, "authors"/"series"/
        -- "tags"), drill.kind is the singular filter param name it maps to
        -- ("author"/"series"/"tag") — reconstructing one from the other
        -- would need irregular-plural handling for no real benefit, so this
        -- is just its own tiny label map.
        local kind_label = ({ author = t("koreader.catalog.section_author"), series = t("koreader.catalog.section_series"), tag = t("koreader.catalog.section_tag") })[drill.kind] or drill.kind
        title = title .. " — " .. kind_label .. ": " .. drill.value
    elseif query and query ~= "" then
        title = title .. " — " .. query
    elseif sort == "recent" then
        title = title .. " — " .. t("koreader.catalog.recent")
    else
        title = title .. " — " .. t("koreader.catalog.title_by_author")
    end
    if exclude_on_device then
        title = title .. " (" .. t("koreader.catalog.not_on_device") .. ")"
    end

    local catalog_menu
    local item_table = self:_catalogItems(result.books or {}, library)
    local total = result.total or 0

    -- Called by KolibreCatalog:_loadCatalogPage on every page turn (never
    -- during the initial open, above). size always equals whatever the
    -- widget's current itemsPerPage is — currently always page_size (mosaic
    -- is the only mode this browser supports paging beyond page 1 in).
    local function loadPage(page, size)
        local page_result, page_err = self.api:request("GET", buildPath(page, size))
        if not page_result then return nil, nil, page_err end
        return self:_catalogItems(page_result.books or {}, library), page_result.total or total, nil
    end

    catalog_menu = KolibreCatalog:new{
        title = title,
        subtitle = t("koreader.common.book_count", { count = total }),
        item_table = item_table,
        page_num = math.max(1, math.ceil(total / page_size)),
        load_page = loadPage,
        is_popout = true,
        is_borderless = false,
        api = self.api,
        library = library,
        -- Il manifesto serve alla potatura delle copertine: senza, una
        -- passeggiata nel catalogo butta quelle dei libri sul dispositivo.
        manifest = self.manifest,
        title_bar_left_icon = "appbar.search",
        onLeftButtonTap = function()
            UIManager:close(catalog_menu)
            self:_promptCatalogSearch(library, sort, drill, exclude_on_device)
        end,
        title_bar_right_icon = "appbar.settings",
        onRightButtonTap = function()
            self:_showCatalogViewDialog(catalog_menu, library, query, sort, drill, exclude_on_device)
        end,
    }
    UIManager:show(catalog_menu)
end

function Kolibre:_promptCatalogSearch(library, sort, drill, exclude_on_device)
    local dialog
    dialog = InputDialog:new{
        title = t("koreader.catalog.search_title"),
        input_hint = t("koreader.catalog.search_hint"),
        buttons = {{
            {
                text = t("koreader.common.cancel"),
                id = "close",
                callback = function() UIManager:close(dialog) end,
            },
            {
                text = t("koreader.common.search"),
                is_enter_default = true,
                callback = function()
                    local q = (dialog:getInputText() or ""):gsub("^%s+", ""):gsub("%s+$", "")
                    UIManager:close(dialog)
                    self:_openKolibreCatalog(library, q ~= "" and q or nil, sort, drill, exclude_on_device)
                end,
            },
        }},
    }
    UIManager:show(dialog)
    dialog:onShowKeyboard()
end

-- One page of a catalog "section" bucket list (authors/series/tags) —
-- {name, count} pairs, e.g. {name = "Victor Hugo", count = 3}. Same manual
-- urlEncode(...) concatenation _openKolibreCatalog already uses for the
-- sibling /catalog endpoint; not worth a shared query-string helper for two
-- call sites in one file.
function Kolibre:_fetchCatalogSectionPage(section, library, page)
    local path = string.format("/api/kolibre/devices/catalog/sections/%s?library=%s&page=%d&size=50",
        section, urlEncode(library), page)
    return self.api:request("GET", path)
end

-- "Sfoglia per autore/serie/tag" — a plain text-list Menu of buckets
-- ("Victor Hugo", mandatory "3"), not the mosaic: these are names+counts,
-- not books, so kolibre_catalog.lua's cover-grid machinery has no role here
-- (matches this file's own OPDS-catalog comment: a plain Menu was enough
-- for a first working version there too). Tapping a bucket drills into the
-- EXISTING catalog Menu filtered to it (_openKolibreCatalog's `drill` param)
-- rather than rendering the books itself.
--
-- Pagination: rather than introduce Menu:switchItemTable-style in-place
-- refresh (unused anywhere else in this file), a trailing "Altro…" item
-- fetches the next page and the whole list is closed/reopened with the
-- appended items — the same close-then-reopen idiom _showCatalogViewDialog
-- already uses for switching sort/filter.
function Kolibre:_browseCatalogSection(section, library, sort)
    local info = SECTION_INFO[section]
    local section_menu
    local items = {}

    local function openBucket(name)
        UIManager:close(section_menu)
        self:_openKolibreCatalog(library, nil, sort, { kind = info.filter_key, value = name })
    end

    local function showItems(total)
        if section_menu then UIManager:close(section_menu) end
        section_menu = Menu:new{
            title = info.label,
            subtitle = total and t("koreader.catalog.section_total", { count = total }) or nil,
            item_table = items,
            is_popout = true,
            is_borderless = false,
        }
        UIManager:show(section_menu)
    end

    local function loadPage(page)
        -- 20/11/2026 (E7): ogni pagina di secchielli e' una richiesta
        -- sincrona — sia l'apertura sia il tocco su «Altro…» — e prima non
        -- mostrava niente. Il corpo resta com'era, solo spostato sotto il
        -- segno (rientro incluso: e' un involucro, non una riscrittura).
        self:_runWithWaitingSign(t("koreader.catalog.loading"), function()
        local result, err = self:_fetchCatalogSectionPage(section, library, page)
        if not result then
            UIManager:show(InfoMessage:new{ text = t("koreader.catalog.section_list_unavailable", { error = tostring(err) }) })
            return
        end

        -- Drop the previous page's trailing "Altro…" placeholder (if any)
        -- before appending the new batch and, possibly, a fresh one.
        if #items > 0 and items[#items].is_more then
            table.remove(items)
        end
        for _idx, bucket in ipairs(result.items or {}) do
            table.insert(items, {
                text = bucket.name or "?",
                mandatory = tostring(bucket.count or 0),
                callback = function() openBucket(bucket.name) end,
            })
        end
        if result.has_next then
            table.insert(items, {
                text = t("koreader.common.more"),
                is_more = true,
                callback = function() loadPage((result.page or page) + 1) end,
            })
        end

        showItems(result.total)
        end)
    end

    loadPage(1)
end

-- Resolves which server library to browse (auto-picks the only one, or
-- shows a picker when there's more than one) and hands it to `on_library`.
-- Reused by openCatalogDashboard, the Browser menu's "Cambia libreria", and
-- the catalog-menu search entry (Wave C) instead of each duplicating it.
function Kolibre:_withCatalogLibrary(on_library)
    -- 20/11/2026 (E7): il controllo di raggiungibilita' (3 s a server
    -- spento) e la richiesta delle biblioteche avvenivano senza nessun
    -- segno: il tocco su «Catalogo» lasciava il lettore imbambolato. Il
    -- controllo sta DENTRO il segno, cosi' anche i suoi 3 s si vedono.
    self:_runWithWaitingSign(t("koreader.catalog.loading"), function()
        if not self:_requireReachable(true) then return end
        local libraries, err = self.api:request("GET", "/api/kolibre/devices/libraries")
        if not libraries or #libraries == 0 then
            UIManager:show(InfoMessage:new{ text = t("koreader.catalog.no_library", { error = tostring(err) }) })
            return
        end
        if #libraries == 1 then
            on_library(libraries[1].library)
            return
        end

        local picker
        local items = {}
        for _idx, lib in ipairs(libraries) do
            table.insert(items, {
                text = lib.name,
                callback = function()
                    UIManager:close(picker)
                    on_library(lib.library)
                end,
            })
        end
        picker = Menu:new{ title = t("koreader.catalog.choose_library"), item_table = items, is_popout = true }
        UIManager:show(picker)
    end)
end

-- "Catalogo" top-level entry (addToMainMenu) — a small home screen instead
-- of jumping straight into the flat catalog Menu (that's now one of three
-- destinations from here, "Sfoglia la libreria" ▸ "Tutti i libri").
-- ── la UI di Kolibre (vedi kolibre_ui_libreria.lua) ──────────────────────

--- L'interfaccia di Kolibre e' accesa?
--
-- **La chiave non si rinomina, il nome sul menu si'.** Il 15/11/2026 la voce
-- e' passata da «Open it on startup» a «Use the Kolibre UI», perche' la
-- vista non si apre piu' solo all'accensione: torna anche ogni volta che si
-- esce da un libro, cioe' PRENDE IL POSTO del gestore di file. Il nome
-- vecchio diceva meno di quello che la voce gia' faceva.
--
-- La chiave dell'impostazione resta `kolibre_libreria_allavvio` apposta:
-- quella e' scritta nelle impostazioni di chi l'ha gia' accesa, e
-- cambiargliela gliela spegnerebbe senza dirglielo.
function Kolibre:_libreriaAllAvvio()
    return G_reader_settings:isTrue("kolibre_libreria_allavvio")
end

--- Accende o spegne l'interfaccia di Kolibre, e **lo scrive subito**.
--
-- **Il `flush` non e' prudenza, e' il difetto del 15/11/2026 sul Kindle.**
-- `saveSetting` scrive in memoria; su disco le impostazioni di KOReader
-- finiscono quando KOReader esce in modo pulito. Su un computer succede
-- quasi sempre. **Su un Kindle quasi mai**: il lettore si addormenta, si
-- riavvia, o il programma viene ucciso, e quella scrittura non arriva mai.
--
-- Effetto: Paolo accende la voce, la vede spuntata, e dopo il riavvio la
-- spunta non c'e' piu' e la vista non parte — senza un errore, senza niente
-- da leggere. E' esattamente quello che ha visto («l'ho attivata la UI»).
--
-- Una riga, e vale per chiunque abbia un lettore che non si spegne mai del
-- tutto.
function Kolibre:_impostaLibreriaAllAvvio(acceso)
    G_reader_settings:saveSetting("kolibre_libreria_allavvio", acceso and true or false)
    G_reader_settings:flush()
end

--- La spunta deve fare qualcosa SUBITO, non al prossimo riavvio.
--
-- Il secondo difetto dello stesso racconto: fino al 15/11 accendere la voce
-- non faceva succedere niente. La vista nasce quando nasce un gestore di
-- file, e quello esiste gia' da prima — quindi bisognava riavviare KOReader
-- oppure entrare e uscire da un libro per vedere qualcosa. Chi accende un
-- interruttore e non vede niente pensa che sia rotto, e ha ragione.
--- Rifa' gli elenchi aperti, dopo una sincronizzazione che ha cambiato i
--- libri che stanno su questo lettore.
--
-- **Da zero: il difetto che chiude** (Paolo, 17/11/2026). La vista libreria e
-- le finestre a elenco (gli ultimi invii, la cronologia, la ricerca) leggono
-- il disco e il manifesto **quando si aprono**. Una sincronizzazione che
-- arriva mentre una di quelle e' aperta scarica libri nuovi e cancella quelli
-- che il server ha tolto, ma l'elenco a schermo e' quello di prima: compare
-- il riepilogo «3 scaricati», e sotto non c'e' nessuno dei tre. Con la
-- libreria divisa in cartelle per autore si vede ancora meglio — **un autore
-- nuovo non compare, e uno rimasto senza libri non sparisce** — perche' la
-- cartella e' la prima cosa che cambia.
--
-- Chi vede un comando riuscire e lo schermo non muoversi pensa che non sia
-- riuscito, e ha ragione a pensarlo: era la stessa ragione per cui il tasto
-- Kolibre di quelle finestre, dal 16/11, rilegge l'elenco dopo aver
-- sincronizzato (`Elenco:_tastoKolibre`). Quella era la sincronizzazione
-- chiesta DA li'; questa e' ogni altra — il menu, l'automatismo, l'avvio.
--
-- **Si chiama solo se qualcosa e' cambiato** (vedi chi la chiama): rileggere
-- per niente vuol dire ridisegnare lo schermo di un lettore a inchiostro, che
-- e' una cosa che si vede e che costa.
--
-- Tutto sotto `pcall` e con i controlli di esistenza: una vista che non si
-- rinfresca e' un fastidio, una sincronizzazione che si schianta alla fine
-- perche' non le e' piaciuta una vista e' un danno.
function Kolibre:ricaricaLeViste()
    local ok, KolibreUI = pcall(require, "kolibre_ui_libreria")
    if ok and type(KolibreUI.aperta) == "function" then
        local vista = KolibreUI.aperta()
        if vista and type(vista.rileggi) == "function" then
            pcall(function() vista:rileggi() end)
        end
    end
    local ok2, Elenco = pcall(require, "kolibre_ui_elenco")
    if ok2 and type(Elenco.tutteAperte) == "function" then
        for _i, vista in ipairs(Elenco.tutteAperte()) do
            if type(vista.rileggi) == "function" then
                pcall(function() vista:rileggi() end)
            end
        end
    end
end

function Kolibre:_applicaSceltaLibreria(acceso)
    if not acceso then
        -- Spenta: si toglie di mezzo adesso, e sotto c'e' il gestore di file
        -- di KOReader, che non e' mai stato chiuso.
        local ok, KolibreUI = pcall(require, "kolibre_ui_libreria")
        if ok and type(KolibreUI.aperta) == "function" then
            local vista = KolibreUI.aperta()
            if vista then pcall(function() vista:chiudi() end) end
        end
        return
    end
    if self.ui and self.ui.document then
        -- Siamo dentro un libro: la vista non si apre sopra quello che stai
        -- leggendo (e' la regola di sempre). Ma va detto, altrimenti sembra
        -- che l'interruttore non abbia fatto niente.
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.accesa_dopo_il_libro") })
        return
    end
    if not self:_libreriaGiaAperta() then self:apriLibreria() end
end

--- Apre la vista «libreria».
--
-- Il modulo si carica QUI e non in testa al file: cosi' un guasto nella UI
-- nuova non impedisce al resto del plugin di partire — sincronizzazione,
-- note e posizioni continuano a funzionare anche se questa schermata si
-- rompe con un aggiornamento di KOReader. E' la ragione per cui l'11/11 si
-- e' deciso un plugin solo invece di due: la separazione serviva a questo, e
-- un `require` pigro la compra senza il costo di un secondo plugin.
--- C'e' gia' una vista libreria aperta?
--
-- La risposta ce l'ha il modulo della vista, non noi: si azzera da se'
-- quando la vista si chiude, in qualunque modo venga chiusa. Qui si chiede
-- con un `pcall` perche' il modulo potrebbe non caricarsi, e in quel caso
-- la risposta onesta e' «no», non un errore che ferma l'avvio.
--- Il numero di versione dell'interfaccia, o un trattino.
--- Le voci della sezione «Interfaccia libreria».
--
-- **Costruite quando il menu si apre** (`sub_item_table_func`) e non una
-- volta per sempre: i segni di spunta e il numero delle righe devono dire
-- com'e' adesso, non com'era all'avvio del lettore.
function Kolibre:_uiMenuItems()
    local voci = {
        {
            text = t("koreader.ui.usa_la_vista"),
            help_text = t("koreader.ui.usa_la_vista_help"),
            checked_func = function() return self:_libreriaAllAvvio() end,
            callback = function()
                local acceso = not self:_libreriaAllAvvio()
                self:_impostaLibreriaAllAvvio(acceso)
                self:_applicaSceltaLibreria(acceso)
            end,
        },
        {
            -- Quante righe per schermata, da 4 a 8 (Paolo, 15/11/2026):
            -- un numero con le freccette (piano del 24/11/2026), invece del
            -- sottomenu di cinque voci. SpinWidget ha la stessa forma, e
            -- chiama `callback(self)` con `.value`, in 2025.08, 2026.03 e
            -- 2026.07 (verificato sul sorgente dei tag il 24/11).
            text_func = function()
                local quante = self:_righeDellaVista()
                return t("koreader.ui.righe_scelte",
                    { count = quante and tostring(quante) or "-" })
            end,
            help_text = t("koreader.ui.righe_help"),
            keep_menu_open = true,
            callback = function(touchmenu_instance)
                local SpinWidget = require("ui/widget/spinwidget")
                UIManager:show(SpinWidget:new{
                    title_text = t("koreader.ui.righe_titolo"),
                    value = self:_righeDellaVista() or 6,
                    value_min = 4,
                    value_max = 8,
                    value_step = 1,
                    ok_text = t("koreader.ui.righe_ok"),
                    callback = function(spin)
                        self:_scegliRigheDellaVista(spin.value)
                        -- Il menu aperto deve dire il numero nuovo: la
                        -- voce si rilegge solo se qualcuno la ridisegna.
                        if touchmenu_instance and touchmenu_instance.updateItems then
                            touchmenu_instance:updateItems()
                        end
                    end,
                })
            end,
            separator = true,
        },
        {
            -- Le due finestre che la vista apre dai suoi tasti, raggiungibili
            -- anche da qui. **Non e' un doppione inutile**: dalla barra della
            -- libreria si arriva al pannello degli invii tenendo premuta la
            -- casa, e una pressione prolungata e' un gesto che non si scopre
            -- da solo. Questa voce e' il posto in cui lo si scopre — e il
            -- testo di aiuto lo dice.
            text = t("koreader.ui.consegne_voce"),
            help_text = t("koreader.ui.consegne_voce_help"),
            callback = function() self:_apriFinestraElenco("kolibre_ui_consegne") end,
        },
        {
            text = t("koreader.ui.cronologia_voce"),
            callback = function() self:_apriFinestraElenco("kolibre_ui_cronologia") end,
        },
    }
    return voci
end

--- Apre una delle finestre di elenco (gli invii, la cronologia).
--
-- Tutto sotto `pcall` e con un messaggio in chiaro se non si apre: un modulo
-- che non si carica — un aggiornamento arrivato a meta' — deve dare un
-- messaggio, non portarsi via il menu di Kolibre mentre si apre.
function Kolibre:_apriFinestraElenco(modulo)
    local ok, Finestra = pcall(require, modulo)
    if not ok then
        logger.err("Kolibre: " .. modulo .. " non si carica:", Finestra)
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.menu_non_disponibile") })
        return
    end
    if type(Finestra.aperta) == "function" and Finestra.aperta() then return end
    local vista
    local costruita, errore = pcall(function()
        vista = Finestra:new{
            manifest = self.manifest,
            kolibre = self,
            agganciato = self.manifest:getMeta("mai_agganciato") and true or false,
            cartella_logo = self.path and (self.path .. "/risorse") or nil,
        }
        UIManager:show(vista)
    end)
    if costruita then return end
    logger.err("Kolibre: " .. modulo .. " non si apre:", errore)
    if vista then pcall(function() UIManager:close(vista) end) end
    UIManager:show(InfoMessage:new{ text = t("koreader.ui.menu_non_disponibile") })
end

-- ── le righe per schermata della vista libreria ──
--
-- **Perche' passano da qui e non dal menu diretto.** Il modulo della vista
-- puo' non caricarsi (un file mancante dopo un aggiornamento a meta'), e un
-- menu che muore mentre si apre porta via tutto il menu di Kolibre. Con
-- `pcall` la voce risponde «-» invece di sparire, come fa gia' la riga della
-- versione.
function Kolibre:_righeDellaVista()
    local ok, KolibreUI = pcall(require, "kolibre_ui_libreria")
    if not ok or type(KolibreUI.righe) ~= "function" then return nil end
    local ok2, quante = pcall(KolibreUI.righe)
    return ok2 and quante or nil
end

function Kolibre:_scegliRigheDellaVista(quante)
    local ok, KolibreUI = pcall(require, "kolibre_ui_libreria")
    if not ok or type(KolibreUI.scegliRighe) ~= "function" then return end
    pcall(KolibreUI.scegliRighe, quante)
    -- **La vista aperta si rifa', non si lascia com'era.** Il numero di
    -- righe si legge all'apertura: senza questo, cambiarlo non si vedrebbe
    -- fino alla prossima volta, e Paolo avrebbe toccato un'impostazione che
    -- sembra non fare niente. Si chiude e si riapre sullo stesso percorso,
    -- cosi' non si perde il posto dov'era.
    local vista = nil
    if type(KolibreUI.aperta) == "function" then
        local ok2, aperta = pcall(KolibreUI.aperta)
        vista = ok2 and aperta or nil
    end
    if vista then
        local dove = vista.path
        pcall(function() vista:chiudi() end)
        pcall(function() self:apriLibreria(dove) end)
    end
end

function Kolibre:_versioneDellaUI()
    local ok, KolibreUI = pcall(require, "kolibre_ui_libreria")
    if not ok or type(KolibreUI.versione) ~= "function" then return "-" end
    local ok2, numero = pcall(KolibreUI.versione)
    return ok2 and tostring(numero) or "-"
end

--- Riporta la vista quando si e' chiusa senza che nessuno lo volesse.
---
--- La chiama la vista stessa (`KolibreUI:onCloseWidget`), al giro dopo la
--- chiusura. Si riapre solo se ha senso: l'interfaccia accesa, nessun libro
--- aperto, il gestore di file di QUESTA istanza ancora vivo (se KOReader sta
--- uscendo, o se il gestore e' stato rifatto, la vista la rifa' lui), e
--- nessuna altra vista gia' aperta.
function Kolibre:riportaLaVista(dove)
    if not self:_libreriaAllAvvio() then return end
    local ReaderUI = require("apps/reader/readerui")
    if ReaderUI.instance then return end
    local FileManager = require("apps/filemanager/filemanager")
    if not FileManager.instance or FileManager.instance ~= self.ui then return end
    if self:_libreriaGiaAperta() then return end
    logger.info("Kolibre: la vista si era chiusa da sola, la riporto")
    self:apriLibreria(dove)
end

--- La cartella del libro appena chiuso, se sta nella libreria, e una volta
--- sola (Paolo, 22/11/2026: «quando esco da un libro devo finire nella
--- cartella dell'autore, non sempre in home»). Il libro lo ricorda
--- `onCloseDocument`, nell'istanza del lettore; qui la legge l'istanza del
--- gestore di file appena nato: lo stato e' quello condiviso del processo.
function Kolibre:_cartellaDelLibroChiuso()
    local file = avvio.ultimo_libro_chiuso
    avvio.ultimo_libro_chiuso = nil
    if type(file) ~= "string" or type(self.books_dir) ~= "string" then return nil end
    local cartella = file:match("^(.*)/[^/]+$")
    local radice = self.books_dir:gsub("/+$", "")
    if not cartella or cartella:sub(1, #radice) ~= radice then return nil end
    return cartella
end

function Kolibre:_libreriaGiaAperta()
    local ok, KolibreUI = pcall(require, "kolibre_ui_libreria")
    if not ok or type(KolibreUI.aperta) ~= "function" then return false end
    return KolibreUI.aperta() ~= nil
end

--- Apre la vista libreria. Se non ci riesce, lo dice e basta.
--
-- **Perche' tutto sta dentro un `pcall`, e non solo il `require`.**
--
-- Questa funzione viene chiamata anche da sola, al nascere del gestore di
-- file, dentro un `UIManager:nextTick`. Quello che succede dentro un
-- `nextTick` non e' protetto da niente: un errore li' dentro risale fino in
-- cima e **chiude KOReader**. E siccome la vista si riapre a ogni avvio
-- finche' l'impostazione e' accesa, un errore diventerebbe un KOReader che
-- muore ogni volta che lo accendi — su un computer si spegne l'impostazione
-- in tre secondi, su un Kindle si va a cercare un cavo.
--
-- Con il `pcall`, il peggio che puo' capitare e' un avviso e il gestore di
-- file di sempre. **Non** si spegne l'impostazione da soli: quella l'ha
-- messa Paolo, e un automatismo puo' proporre, non togliere.
--- Manda al server il registro di KOReader, ripulito.
--
-- **Perche' esiste** (15/11/2026). Sul Kindle la UI «non parte e non da'
-- problemi», e il perche' sta nel `crash.log` di KOReader — che su un
-- Kindle si raggiunge solo con un cavo. Da qui si manda al server di Paolo,
-- e da li' si legge con un browser.
--
-- **Si chiede sempre prima, e si dice che cosa si manda.** Un registro
-- raccoglie tutto quello che KOReader stampa, titoli dei libri e percorsi
-- compresi. Va sul server di casa e non altrove, ma e' roba sua e la
-- decisione e' sua, ogni volta. Niente invio automatico, mai.
--
-- Token e indirizzi li toglie `kolibre_diagnostica` prima che parta.
function Kolibre:mandaIlRegistro()
    local cartella = KolibrePercorsi.cartellaDeiDati(DataStorage, lfs.currentdir())
    local percorso = cartella .. "/crash.log"
    local dimensione = lfs.attributes(percorso, "size")
    if not dimensione then
        UIManager:show(InfoMessage:new{
            text = t("koreader.diagnostica.assente", { percorso = percorso }),
        })
        return
    end
    UIManager:show(ConfirmBox:new{
        text = t("koreader.diagnostica.conferma", {
            kb = math.floor(dimensione / 1024),
            max = math.floor(KolibreDiagnostica.MAX_BYTE / 1024),
        }),
        ok_text = t("koreader.diagnostica.manda"),
        ok_callback = function() self:_mandaIlRegistroDavvero(percorso) end,
    })
end

function Kolibre:_mandaIlRegistroDavvero(percorso)
    -- 20/11/2026 (E7): il registro puo' pesare centinaia di KB e il
    -- caricamento e' sincrono — dopo il «Manda» della conferma lo schermo
    -- restava fermo senza dire niente fino all'esito.
    self:_runWithWaitingSign(t("koreader.diagnostica.invio"), function()
        local grezzo = util.readFromFile(percorso, "rb")
        if not grezzo then
            UIManager:show(InfoMessage:new{ text = t("koreader.diagnostica.illeggibile") })
            return
        end
        local pronto = KolibreDiagnostica.prepara(grezzo, {
            dispositivo = Device and Device.model or "?",
            versione = VERSION,
            quando = os.date("%Y-%m-%d %H:%M:%S"),
        })
        -- Un file di passaggio accanto al registro, e si toglie SEMPRE: anche
        -- quando l'invio fallisce, perche' un file dimenticato nella cartella
        -- dati di KOReader e' esattamente il genere di cosa che dopo un mese
        -- nessuno sa piu' da dove viene.
        local temporaneo = percorso .. ".kolibre-da-mandare"
        local f = io.open(temporaneo, "wb")
        if not f then
            UIManager:show(InfoMessage:new{ text = t("koreader.diagnostica.illeggibile") })
            return
        end
        f:write(pronto)
        f:close()

        local ok, err = self.api:uploadFile("/api/kolibre/devices/diagnostic-log", temporaneo)
        os.remove(temporaneo)
        if ok then
            UIManager:show(InfoMessage:new{
                text = t("koreader.diagnostica.mandato", { kb = math.floor(#pronto / 1024) }),
            })
        else
            UIManager:show(InfoMessage:new{
                text = t("koreader.diagnostica.fallito", { errore = tostring(err) }),
            })
        end
    end)
end

--- Apre la vista libreria. `dove` e' facoltativo.
--
-- **A che serve `dove`.** Quando si cambia il numero di righe per schermata
-- la vista aperta va rifatta, perche' quel numero si legge all'apertura.
-- Rifarla senza dire dove vorrebbe dire riportare Paolo alla radice della
-- libreria: ha toccato un'impostazione e si e' perso la cartella in cui
-- stava. Con `dove` si riapre esattamente li'.
--
-- Il percorso si controlla prima di usarlo: una cartella che nel frattempo
-- non c'e' piu' (una scheda tolta, un libro cancellato dal computer) farebbe
-- nascere una vista su niente, e il ripiego giusto e' la radice.
function Kolibre:apriLibreria(dove)
    local ok, KolibreUI = pcall(require, "kolibre_ui_libreria")
    if not ok then
        logger.err("Kolibre: la vista libreria non si carica:", KolibreUI)
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.menu_non_disponibile") })
        return
    end
    local partenza = self.books_dir
    if dove and dove ~= "" and lfs.attributes(dove, "mode") == "directory" then
        partenza = dove
    end
    local vista
    local costruita, errore = pcall(function()
        vista = KolibreUI:new{
            manifest = self.manifest,
            kolibre = self,
            agganciato = self.manifest:getMeta("mai_agganciato") and true or false,
            cartella_logo = self.path and (self.path .. "/risorse") or nil,
            radice = self.books_dir,
            path = partenza,
            close_callback = function() UIManager:close(vista) end,
        }
        UIManager:show(vista)
    end)
    if not costruita then
        logger.err("Kolibre: la vista libreria non si apre:", errore)
        -- Se e' morta a meta' strada puo' essere rimasta nella pila delle
        -- finestre: una finestra rotta la' dentro impedirebbe a KOReader di
        -- chiudersi (vedi `KolibreUI:onExit`).
        if vista then pcall(function() UIManager:close(vista) end) end
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.menu_non_disponibile") })
        return
    end
    return vista
end

function Kolibre:openCatalogDashboard()
    self:_withCatalogLibrary(function(library)
        self:_showCatalogDashboard(library)
    end)
end

function Kolibre:_showCatalogDashboard(library)
    local dashboard
    local items = {
        {
            text = "📚 " .. t("koreader.catalog.recent"),
            callback = function()
                UIManager:close(dashboard)
                self:_openCatalogRecent(library)
            end,
        },
    }
    if KolibreCapabilities:supports(self.api, "catalogDiscover") then
        table.insert(items, {
            text = "🔎 " .. t("koreader.catalog.discover"),
            callback = function()
                UIManager:close(dashboard)
                self:_openCatalogDiscover(library)
            end,
        })
    end
    table.insert(items, {
        text = "🧭 " .. t("koreader.catalog.browse_library"),
        callback = function()
            UIManager:close(dashboard)
            self:_openCatalogBrowserMenu(library)
        end,
    })
    dashboard = Menu:new{
        title = t("koreader.catalog.title"),
        item_table = items,
        is_popout = true,
        is_borderless = false,
    }
    UIManager:show(dashboard)
end

-- "Aggiunti di recente": a bounded dashboard SHELF, not the general
-- interactive browser — confirmed the real cause of a repeated real crash
-- (backend logs on a 1190-book library showed the single
-- GET .../catalog?sort=recent request succeed, then total silence: no
-- cover/thumbnail requests at all, nothing, followed by the device
-- reconnecting from scratch — the signature of a crash-and-restart. That
-- request had no page/size, so browse_catalog's own fallback returned up
-- to its full 500-book cap as one JSON response — decoding hundreds of
-- full book records (title, author, tags[], formats[], series, rating,
-- pubdate...) into Lua tables in one shot is plausibly what exhausted
-- memory on the Kindle, well before any image was ever touched). Fixed by
-- giving this its own small, explicitly page+size-bounded request instead
-- of reusing the general _openKolibreCatalog (which has no size cap at
-- all) — same fix shape as _openCatalogDiscover below, and the same 24-book
-- "shelf" size. NOTE: "Tutti i libri" (_openCatalogBrowserMenu below) still
-- calls the general uncapped browse — on this same 1190-book library that
-- is a known, not yet fixed, remaining risk of the identical failure mode.
function Kolibre:_openCatalogRecent(library)
    -- 20/11/2026 (E7): rete sincrona al tocco, prima senza nessun segno.
    self:_runWithWaitingSign(t("koreader.catalog.loading"), function()
        self:_openCatalogRecentNow(library)
    end)
end

function Kolibre:_openCatalogRecentNow(library)
    local path = "/api/kolibre/devices/catalog?library=" .. urlEncode(library) .. "&sort=recent&page=1&size=24"
    local result, err = self.api:request("GET", path)
    if not result then
        UIManager:show(InfoMessage:new{ text = t("koreader.catalog.recent_unavailable", { error = tostring(err) }) })
        return
    end

    local item_table = self:_catalogItems(result.books or {}, library)
    local recent_menu
    recent_menu = KolibreCatalog:new{
        title = t("koreader.catalog.recent"),
        subtitle = t("koreader.common.book_count", { count = #(result.books or {}) }),
        item_table = item_table,
        is_popout = true,
        is_borderless = false,
        api = self.api,
        library = library,
        -- Il manifesto serve alla potatura delle copertine: senza, una
        -- passeggiata nel catalogo butta quelle dei libri sul dispositivo.
        manifest = self.manifest,
        -- Stessa icona cerca delle altre viste griglia: dentro una griglia di
        -- libri una funzione cerca serve sempre, e qui mancava — apre la
        -- ricerca generale sul catalogo, non una ricerca ristretta
        -- a questi 24 libri recenti, che non avrebbe molto senso.
        title_bar_left_icon = "appbar.search",
        onLeftButtonTap = function()
            UIManager:close(recent_menu)
            self:_promptCatalogSearch(library, "author", nil)
        end,
    }
    UIManager:show(recent_menu)
end

-- "Da scoprire": server-computed suggestions (GET .../catalog/discover, see
-- devices.py — not on this device, preferring same author/tags as recently
-- read on THIS device, randomly filled out otherwise). Rendered exactly
-- like any other book list (_catalogItems, same shape the sibling /catalog
-- endpoint returns) inside the same KolibreCatalog mosaic widget — no
-- reshuffle button: reopening this same entry from the dashboard already
-- issues a fresh request and gets a new random pick.
function Kolibre:_openCatalogDiscover(library)
    -- 20/11/2026 (E7): come _openCatalogRecent — i suggerimenti li calcola
    -- il server, e il calcolo puo' costare piu' della pagina normale.
    self:_runWithWaitingSign(t("koreader.catalog.loading"), function()
        self:_openCatalogDiscoverNow(library)
    end)
end

function Kolibre:_openCatalogDiscoverNow(library)
    local path = "/api/kolibre/devices/catalog/discover?library=" .. urlEncode(library) .. "&limit=24"
    local result, err = self.api:request("GET", path)
    if not result then
        UIManager:show(InfoMessage:new{ text = t("koreader.catalog.discover_unavailable", { error = tostring(err) }) })
        return
    end

    local item_table = self:_catalogItems(result.books or {}, library)
    local discover_menu
    discover_menu = KolibreCatalog:new{
        title = t("koreader.catalog.discover"),
        subtitle = t("koreader.common.book_count", { count = #(result.books or {}) }),
        item_table = item_table,
        is_popout = true,
        is_borderless = false,
        api = self.api,
        library = library,
        -- Il manifesto serve alla potatura delle copertine: senza, una
        -- passeggiata nel catalogo butta quelle dei libri sul dispositivo.
        manifest = self.manifest,
        title_bar_left_icon = "appbar.search",
        onLeftButtonTap = function()
            UIManager:close(discover_menu)
            self:_promptCatalogSearch(library, "author", nil)
        end,
    }
    UIManager:show(discover_menu)
end

-- "Sfoglia la libreria": the four selections it gathers (scegli
-- libreria, tutti i libri, non sul device, serie) plus search, gathered
-- behind one entry point instead of the old flat catalog Menu being the
-- only destination. Every action here reuses an existing, unchanged
-- function — this is wiring, not new catalog logic.
function Kolibre:_openCatalogBrowserMenu(library)
    local browser
    local items = {
        {
            text = "🔍 " .. t("koreader.common.search"),
            callback = function()
                UIManager:close(browser)
                self:_promptCatalogSearch(library, "author", nil)
            end,
        },
        {
            text = "📖 " .. t("koreader.catalog.all_books"),
            callback = function()
                UIManager:close(browser)
                self:_openKolibreCatalog(library, nil, "author")
            end,
        },
    }
    if KolibreCapabilities:supports(self.api, "catalogDiscover") then
        table.insert(items, {
            text = "📥 " .. t("koreader.catalog.not_on_device_item"),
            callback = function()
                UIManager:close(browser)
                self:_openKolibreCatalog(library, nil, "author", nil, true)
            end,
        })
    end
    if KolibreCapabilities:supports(self.api, "catalogSections") then
        table.insert(items, {
            text = "🗂️ " .. t("koreader.catalog.section_series"),
            callback = function()
                UIManager:close(browser)
                self:_browseCatalogSection("series", library, "author")
            end,
        })
    end
    table.insert(items, {
        text = "📚 " .. t("koreader.catalog.change_library"),
        callback = function()
            UIManager:close(browser)
            self:_withCatalogLibrary(function(new_library)
                self:_openCatalogBrowserMenu(new_library)
            end)
        end,
    })

    browser = Menu:new{
        title = t("koreader.catalog.browse_menu_title"),
        item_table = items,
        is_popout = true,
        is_borderless = false,
    }
    UIManager:show(browser)
end

-- ── Device initialization: «Initialize library» ──
--
-- Il comando unico della 1.0.0 (punto 2 del piano, 24/11/2026): impronta,
-- file esatto al server, riordino. La catena vive in
-- kolibre_accoppiamento.lua e kolibre_riordino.lua, con le loro teste a
-- raccontarla; qui restano le deleghe, initLibrary/_runLibraryInit che la
-- avviano e `_proponiIlRiordino` che la chiude.
function Kolibre:_identifyFileByContent(...) return KolibreAccoppiamento._identifyFileByContent(self, ...) end

-- Backfills ".folder.jpg" for author folders that already exist on the
-- device but never got one — confirmed as a real gap: runDownloads (this
-- file, Fase 2 of a sync) only ever writes it at the moment a NEW book by
-- that author is being downloaded, gated on sends[] (books still pending
-- delivery). A folder that already held other books before the author had
-- a photo in Kolibre (or before this mechanism existed) never gets a second
-- chance — there is no periodic/background pass anywhere that reconciles
-- existing folders against the server's current photos. This piggybacks on
-- a scan callers already paid for (_scanLocalBooks, via _runLibraryInit's
-- "Verifica libreria" and pushAllAnnotationsFull's "Sincronizza tutto" —
-- both manual/interactive, consistent with this plugin's policy of never
-- adding walk cost to automatic background syncs) instead of adding a new
-- full-device walk of its own.
-- Returns {checked, downloaded} — checked = folders missing a cover that
-- were actually queried against the server, downloaded = how many of those
-- the server actually had a photo for (the rest are normal 404s, not
-- errors: the server just doesn't have that author's photo yet).
-- ── le copertine dei libri ──
--
-- **Che cosa fa.** Scarica dal server le copertine dei libri che il
-- dispositivo ha e che una copertina ancora non l'hanno, e le mette nella
-- cache condivisa (`kolibre_copertine.lua`), da cui le leggono sia la vista
-- libreria sia il catalogo.
--
-- **Perche' qui e non quando si disegna.** Perche' una vista che va in rete
-- mentre disegna una riga e' uno schermo fermo, e su un e-ink si vede. La
-- sincronizzazione e' il momento in cui il dispositivo e' gia' in rete e
-- Paolo si aspetta che qualcosa duri un po'.
--
-- **Perche' venti per volta** (`PER_SINCRONIZZAZIONE`): e' la misura chiesta
-- da Paolo il 15/11. Centocinquanta copertine tutte insieme sarebbero una
-- sincronizzazione che sembra piantata; venti sono un paio di MB, e le altre
-- arrivano al giro dopo. Un ordine stabile garantisce che il giro dopo si
-- riparta da dove si era arrivati — vedi `daScaricare`.
--
-- **Perche' dopo la fine della sincronizzazione e non dentro.** Il riepilogo
-- deve comparire quando la sincronizzazione e' finita, non dopo le
-- copertine: queste sono un extra, e un extra non fa aspettare. Girano in
-- rinvii da due, cosi' fra un download e l'altro KOReader resta vivo e
-- risponde ai tocchi.
--
-- **I fallimenti si ricordano solo per questa sessione.** Un libro che il
-- server non ha ancora convertito dara' 404 oggi e una copertina domani:
-- ricordarselo per sempre vorrebbe dire non riprovare mai. Ricordarlo per
-- questa accensione basta a non spendere i venti posti sempre sugli stessi.
-- ── le foto d'autore che mancano ──
--
-- **Il difetto che questa funzione chiude** (trovato il 16/11/2026 leggendo
-- i dati veri, non il codice). Sul Mac di Paolo quattro cartelle d'autore su
-- venticinque mostravano il riquadro grigio col nome invece della foto, e le
-- cause erano QUATTRO, diverse fra loro:
--
--   * **Luciano Battaia**: il server non ha una foto e non ce l'avra' —
--     nessuna voce su Wikipedia con quel nome. Il riquadro col nome e' la
--     risposta giusta, e non c'e' niente da correggere.
--   * **TEMP**: non e' un autore. E' una cartella fatta a mano, e dentro c'e'
--     un EPUB che Kolibre non ha mai consegnato. Niente da correggere qui.
--   * **Émile Armand**: il server ha la foto, ma sotto il nome SENZA
--     l'accento — due righe per la stessa persona. Si corregge sul server,
--     non qui.
--   * **Paul A.M. Dirac**: ed e' questo. Il libro e' stato consegnato il
--     6 settembre alle 15:50; la foto il server l'ha presa il 18 settembre,
--     **dodici giorni dopo**. Alla consegna il 404 era giusto. Il
--     ripescaggio (`_backfillAuthorFolderCovers`) esiste proprio per questo,
--     ma gira **solo** su due comandi a mano: «Verifica libreria» e
--     «Sincronizza tutto». Finche' Paolo non ne tocca uno, una foto arrivata
--     dopo il libro non raggiunge mai il dispositivo.
--
-- **Perche' qui dentro non costa niente.** `_backfillAuthorFolderCovers`
-- parte da una CAMMINATA del dispositivo, e una camminata non si aggiunge a
-- una sincronizzazione automatica — e' la regola di questo plugin. Ma le
-- cartelle degli autori il manifesto le sa gia': sono le cartelle dei libri
-- che ci stanno dentro. Di camminate zero; di domande al disco una per
-- cartella d'autore (venticinque sul Mac di Paolo), cioe' niente.
--
-- Il tetto e' basso di proposito: le cartelle d'autore sono poche e
-- cambiano piano, e questi download non devono mangiare il giro delle
-- copertine.
function Kolibre:_fotoDAutoreCheMancano()
    local mancanti = {}
    local write_folder_cover = self.write_folder_cover
    if write_folder_cover == nil then write_folder_cover = true end
    if not write_folder_cover or (self.folder_layout or "author") ~= "author" then
        return mancanti
    end
    self._foto_autore_fallite = self._foto_autore_fallite or {}

    -- Le cartelle, ricavate dai percorsi del manifesto. In ordine, per la
    -- stessa ragione per cui `daScaricare` ordina: senza, le prime cinque
    -- sarebbero cinque a caso e qualcuna non arriverebbe mai.
    local cartelle = {}
    for _chiave, voce in pairs(self.manifest:all()) do
        if voce.path then
            local dir = voce.path:match("^(.*)/[^/]+$")
            if dir and dir ~= "" and dir ~= self.books_dir then
                cartelle[dir] = true
            end
        end
    end
    local elenco = {}
    for dir in pairs(cartelle) do table.insert(elenco, dir) end
    table.sort(elenco)

    for _i, dir in ipairs(elenco) do
        if #mancanti >= 5 then break end
        local foto = dir .. "/.folder.jpg"
        local autore = dir:match("([^/]+)$")
        if autore and autore ~= "" and not self._foto_autore_fallite[autore]
            and lfs.attributes(foto, "mode") ~= "file" then
            table.insert(mancanti, {
                chiave = "autore:" .. autore,
                percorso = foto,
                indirizzo = "/api/kolibre/authors/" .. urlEncode(autore) .. "/photo/thumbnail",
                autore = autore,
            })
        end
    end
    return mancanti
end

function Kolibre:scaricaLeCopertine()
    local cartella = KolibreCopertine.cartella(DataStorage)
    if not cartella then return end
    self._copertine_fallite = self._copertine_fallite or {}
    -- Le copertine dei libri che stanno sul dispositivo non si buttano: vedi
    -- `pota` per il giro infinito che chiude.
    KolibreCopertine.pota(cartella,
        KolibreCopertine.daProteggere(cartella, self.manifest:all()))
    local coda = KolibreCopertine.daScaricare(
        cartella, self.manifest:all(),
        KolibreCopertine.PER_SINCRONIZZAZIONE, self._copertine_fallite)
    -- Nello stesso giro anche le FOTO D'AUTORE che mancano: vedi
    -- `_fotoDAutoreCheMancano` per il difetto che chiude.
    for _i, foto in ipairs(self:_fotoDAutoreCheMancano()) do
        table.insert(coda, foto)
    end
    if #coda == 0 then return end
    logger.info("Kolibre: immagini da scaricare in questo giro:", #coda)

    local presi, mancati = 0, 0
    local function passo()
        for _i = 1, 2 do
            local voce = table.remove(coda, 1)
            if not voce then break end
            -- `voce.indirizzo` per le foto d'autore, che hanno una rotta
            -- loro; le copertine se lo fanno costruire dal modulo.
            local indirizzo = voce.indirizzo
                or KolibreCopertine.indirizzo(voce.biblioteca, voce.id)
            local ok = self.api:downloadTo(indirizzo, voce.percorso,
                KolibreCopertine.MAX_BYTE)
            if ok then
                presi = presi + 1
            else
                -- Non e' un errore da mostrare: il caso normale e' «il
                -- server non ha una copertina per questo libro».
                mancati = mancati + 1
                if voce.autore then
                    self._foto_autore_fallite = self._foto_autore_fallite or {}
                    self._foto_autore_fallite[voce.autore] = true
                else
                    self._copertine_fallite[voce.chiave] = true
                end
            end
        end
        if #coda > 0 then
            UIManager:scheduleIn(0.05, passo)
        else
            logger.info("Kolibre: copertine prese:", presi, "non disponibili:", mancati)
        end
    end
    UIManager:scheduleIn(0.15, passo)
end

--- La foto dell'autore, nelle cartelle che non ce l'hanno: a ogni Sync.
--
-- **Il buco che chiude** (verificato il 24/11/2026 per il piano 1.0.0). La
-- foto (`.folder.jpg`) si scaricava in due momenti soli: insieme a un libro
-- nuovo — e solo se in quel momento il server la aveva — e con
-- `_backfillAuthorFolderCovers`, che pero' gira solo in «Initialize
-- library» e nella rilettura completa delle note. Un autore arrivato prima
-- che il server avesse la sua foto restava senza, finche' qualcuno non
-- lanciava a mano uno di quei due comandi.
--
-- **Le cartelle si prendono dal manifesto**, non dal disco: camminare la
-- cartella dei libri a ogni Sync costa un'impronta per file, e i libri che
-- Kolibre gestisce sono esattamente quelli nelle cartelle d'autore.
--
-- **Un autore senza foto sul server si riprova una volta a settimana**, non a
-- ogni giro: il 404 e' il caso normale, e chiederlo a ogni sincronizzazione
-- per ogni autore sarebbe rumore sulla rete per niente.
local FOTO_AUTORE_RIPROVA_DOPO = 7 * 86400

function Kolibre:_fotoDegliAutoriMancanti(adesso)
    local write_folder_cover = self.write_folder_cover
    if write_folder_cover == nil then write_folder_cover = true end
    if not write_folder_cover or (self.folder_layout or "author") ~= "author" then
        return { checked = 0, downloaded = 0 }
    end
    adesso = adesso or os.time()
    local tentate = self.manifest:getMeta("foto_autori_tentate")
    if type(tentate) ~= "table" then tentate = {} end
    local cartelle = {}
    for _k, e in pairs(self.manifest:all()) do
        local dir = type(e.path) == "string" and e.path:match("^(.*)/[^/]+$")
        if dir and dir ~= self.books_dir and lfs.attributes(dir, "mode") == "directory" then
            cartelle[dir] = true
        end
    end
    local checked, downloaded = 0, 0
    for dir in pairs(cartelle) do
        local cover_path = dir .. "/.folder.jpg"
        local ultima = tentate[dir]
        if not lfs.attributes(cover_path, "mode")
                and not (ultima and adesso - ultima < FOTO_AUTORE_RIPROVA_DOPO) then
            local author = dir:match("([^/]+)$")
            if author and author ~= "" then
                checked = checked + 1
                if self.api:downloadTo("/api/kolibre/authors/" .. urlEncode(author) .. "/photo/thumbnail", cover_path) then
                    downloaded = downloaded + 1
                    tentate[dir] = nil
                else
                    tentate[dir] = adesso
                end
            end
        end
    end
    self.manifest:setMeta("foto_autori_tentate", tentate)
    return { checked = checked, downloaded = downloaded }
end

function Kolibre:_backfillAuthorFolderCovers(scanned)
    local write_folder_cover = self.write_folder_cover
    if write_folder_cover == nil then write_folder_cover = true end
    if not write_folder_cover or (self.folder_layout or "author") ~= "author" then
        return { checked = 0, downloaded = 0 }
    end

    local author_dirs = {}
    for _idx, b in ipairs(scanned) do
        local dir = b.path:match("^(.*)/[^/]+$")
        if dir and dir ~= self.books_dir and not author_dirs[dir] then
            author_dirs[dir] = true
        end
    end

    local checked, downloaded = 0, 0
    for dir in pairs(author_dirs) do
        local cover_path = dir .. "/.folder.jpg"
        if not lfs.attributes(cover_path, "mode") then
            local author = dir:match("([^/]+)$")
            if author and author ~= "" then
                checked = checked + 1
                -- 404 (server has no cached photo for this author yet) is
                -- the normal case, not an error — downloadTo already just
                -- returns false/err without raising, nothing to report.
                local ok = self.api:downloadTo("/api/kolibre/authors/" .. urlEncode(author) .. "/photo/thumbnail", cover_path)
                if ok then downloaded = downloaded + 1 end
            end
        end
    end
    return { checked = checked, downloaded = downloaded }
end

-- ── L'inventario della cartella dei libri ──
--
-- **Cosa fa, e cosa non fa.** Cammina la cartella dei libri, per ogni file
-- calcola l'impronta e legge il suo sidecar, e manda l'elenco al server.
-- **Non cancella niente, non propone niente, non tocca nessun file.**
--
-- **Perche' serve.** Fino al 05/11/2026 il server sapeva solo quello che
-- *lui* aveva consegnato e quello che il dispositivo non aveva saputo
-- accoppiare. Dei file che ci sono davvero qui sopra non sapeva niente, e per
-- questo non poteva accorgersi della cosa piu' banale: lo stesso libro in due
-- copie. Il difetto che le creava e' chiuso (vedi `doveScrivere`); questo
-- serve a vedere e pulire quelle che ci sono.
--
-- **E resta anche dopo la pulizia.** La camminata non e' lavoro nuovo:
-- `_scanLocalBooks` e' chiamata da quattro posti diversi — inizializza
-- libreria, spinta di tutte le annotazioni, carico della sincronizzazione,
-- calcolo dell'avanzamento — e ognuno butta il risultato. Un inventario che
-- il server conserva trasforma quattro camminate private in un fatto
-- condiviso.
function Kolibre:mandaInventario()
    if not self:_requireReachable(true) then return end
    local scansione = self:_scanLocalBooks(function(count)
        self:_showProgress(t("koreader.inventory.scanning_progress", { count = count }))
    end)
    self:_showProgress(t("koreader.inventory.reading_sidecars"))

    local files = {}
    for _idx, b in ipairs(scansione) do
        local lettura = self:_letturaDalSidecar(b.path)
        table.insert(files, {
            path = b.path,
            hash = b.hash,
            format = b.format,
            size = lfs.attributes(b.path, "size"),
            percent_finished = lettura.percent_finished,
            status = lettura.status,
            status_modified = lettura.status_modified,
            annotations = lettura.annotations,
            pages = lettura.pages,
            last_xpointer = lettura.last_xpointer,
        })
    end

    local esito, err = self.api:request("POST", "/api/kolibre/devices/inventory", { files = files })
    self:_closeProgress()
    if not esito then
        UIManager:show(InfoMessage:new{
            text = t("koreader.inventory.failed", { error = tostring(err) }) })
        return
    end

    -- I numeri si mostrano **tutti**, anche gli zeri: «nessun doppione» e'
    -- la risposta che si spera, e tacerla lascerebbe il dubbio che il
    -- controllo non sia stato fatto.
    local r = esito.riassunto or {}
    local righe = {
        t("koreader.inventory.result_files", { count = r.file_letti or 0 }),
        t("koreader.inventory.result_recognized", { count = r.riconosciuti or 0 }),
        t("koreader.inventory.result_duplicates", {
            count = r.libri_in_piu_copie or 0, copies = r.copie_in_eccesso or 0 }),
        t("koreader.inventory.result_unknown", { count = r.sconosciuti or 0 }),
    }
    if (r.da_salvare or 0) > 0 then
        table.insert(righe, t("koreader.inventory.result_to_save", { count = r.da_salvare }))
    end
    UIManager:show(InfoMessage:new{
        text = t("koreader.inventory.done") .. "\n\n" .. KolibreFinestre.elenco(righe),
    })
end

function Kolibre:initLibrary()
    if not self:_requireReachable(true) then return end
    UIManager:show(ConfirmBox:new{
        text = t("koreader.library_init.confirm"),
        ok_text = t("koreader.common.start"),
        ok_callback = function() self:_runLibraryInit() end,
    })
end

function Kolibre:_runLibraryInit()
    -- Il riepilogo del giro: lo riempiono i tre passi, lo legge
    -- `_proponiIlRiordino` alla fine.
    self._init = { accoppiati = 0 }
    local scanned = self:_scanLocalBooks(function(count)
        self:_showProgress(t("koreader.library_init.scanning_progress", { count = count }))
    end)
    self:_closeProgress()
    self:_backfillAuthorFolderCovers(scanned)

    -- Files Kolibre already manages (present in the manifest under any key)
    -- are excluded up front — sending their hash to /scan-unmatched would
    -- just re-propose linking a book that's already linked.
    local managed_paths = {}
    for _key, entry in pairs(self.manifest:all()) do
        if entry.path then managed_paths[entry.path] = true end
    end
    local candidates = {}
    for _idx, b in ipairs(scanned) do
        if not managed_paths[b.path] then table.insert(candidates, b) end
    end

    if #candidates == 0 then
        -- Niente di nuovo da accoppiare, ma il riordino puo' ancora servire.
        self:_proponiIlRiordino()
        return
    end

    self:_showProgress(t("koreader.library_init.comparing"))
    local items = {}
    for _idx, b in ipairs(candidates) do
        table.insert(items, { hash = b.hash, format = b.format, path = b.path })
    end
    local result, err = self.api:request("POST", "/api/kolibre/devices/scan-unmatched", { items = items })
    self:_closeProgress()
    if not result then
        UIManager:show(InfoMessage:new{ text = t("koreader.library_init.compare_failed", { error = tostring(err) }) })
        return
    end

    self:_confirmHashMatches(result.matched or {}, result.unmatched or {})
end

-- La catena dell'accoppiamento (impronte, somiglianza, sovrascritture,
-- senza-candidato): trasloco del 20/11/2026 (revisione A2), i corpi
-- vivono in kolibre_accoppiamento.lua.
function Kolibre:_linkHashMatch(...) return KolibreAccoppiamento._linkHashMatch(self, ...) end
function Kolibre:_confirmHashMatches(...) return KolibreAccoppiamento._confirmHashMatches(self, ...) end
function Kolibre:_resolveMultiLibraryHashMatches(...) return KolibreAccoppiamento._resolveMultiLibraryHashMatches(self, ...) end
function Kolibre:_confirmSingleLibraryHashMatches(...) return KolibreAccoppiamento._confirmSingleLibraryHashMatches(self, ...) end
function Kolibre:_mandaINonAccoppiati(...) return KolibreAccoppiamento._mandaINonAccoppiati(self, ...) end
function Kolibre:_mandaIFile(...) return KolibreAccoppiamento._mandaIFile(self, ...) end
function Kolibre:_biblioteche(...) return KolibreAccoppiamento._biblioteche(self, ...) end

--- L'ultima tappa di «Initialize library»: il riordino in `Autore/Libro`, e
--- il riepilogo di tutto il giro (`self._init`).
---
--- Si chiede prima, con l'elenco: spostare libri e' la sola cosa del comando
--- che cambia il disco del lettore. Chi dice no si tiene i libri dove sono,
--- e il riepilogo lo dice.
function Kolibre:_proponiIlRiordino()
    local riepilogo = self._init or {}
    local function fine()
        self._init = nil
        local righe = {}
        local function riga(chiave, n)
            if n and n > 0 then table.insert(righe, t(chiave, { count = n })) end
        end
        riga("koreader.library_init.summary_linked", riepilogo.accoppiati)
        riga("koreader.library_init.summary_sent", riepilogo.mandati)
        riga("koreader.library_init.summary_failed", riepilogo.falliti)
        riga("koreader.library_init.summary_not_sent", riepilogo.non_mandati)
        riga("koreader.library_init.summary_no_library", riepilogo.senza_biblioteca)
        riga("koreader.library_init.summary_moved", riepilogo.spostati)
        riga("koreader.library_init.summary_not_moved", riepilogo.non_spostati)
        riga("koreader.library_init.summary_taken", riepilogo.occupati)
        -- La riga che Paolo ha voluto (24/11): metadati fuori dal posto che
        -- l'impostazione di KOReader preferisce.
        riga("koreader.library_init.summary_metadata_elsewhere", riepilogo.fuori_posto)
        if #righe == 0 then table.insert(righe, t("koreader.library_init.nothing_else")) end
        UIManager:show(InfoMessage:new{ text = table.concat(righe, "\n") })
        if (riepilogo.spostati or 0) > 0 or (riepilogo.mandati or 0) > 0 or (riepilogo.accoppiati or 0) > 0 then
            pcall(function() self:ricaricaLeViste() end)
        end
    end

    if (self.folder_layout or "author") ~= "author" then return fine() end
    local aperto = self.ui and self.ui.document and self.ui.document.file or nil
    local da_spostare, occupati = KolibreRiordino.daSpostare(self.manifest, self.books_dir,
        sanitizeFilename, function(p) return lfs.attributes(p, "mode") == "file" or
            lfs.attributes(p, "mode") == "directory" end, aperto)
    riepilogo.occupati = #occupati
    if #da_spostare == 0 then return fine() end

    local nomi = {}
    for _i, m in ipairs(da_spostare) do
        table.insert(nomi, "• " .. (m.a:sub(#self.books_dir + 2)))
    end
    UIManager:show(ConfirmBox:new{
        text = t("koreader.library_init.move_confirm", {
            count = #da_spostare, list = KolibreFinestre.elenco(nomi) }),
        ok_text = t("koreader.library_init.move"),
        cancel_text = t("koreader.common.later"),
        ok_callback = function()
            local k = {
                lfs = lfs, makePath = util.makePath, DocSettings = DocSettings,
                ReadHistory = require("readhistory"), ReadCollection = require("readcollection"),
                preferita = G_reader_settings:readSetting("document_metadata_folder", "doc"),
            }
            local spostati, fuori = 0, 0
            for idx, m in ipairs(da_spostare) do
                self:_showProgressBar(idx, #da_spostare, m.voce.title or m.da)
                local ok, err, fuori_posto = KolibreRiordino.sposta(m.da, m.a, k)
                if ok then
                    spostati = spostati + 1
                    if fuori_posto then fuori = fuori + 1 end
                    m.voce.path = m.a
                    -- Non `no_dirty`: il percorso nuovo arriva al server con
                    -- la prossima sincronizzazione completa.
                    self.manifest:set(m.chiave, m.voce)
                    self:_cleanupBookDir(m.da)
                else
                    logger.warn("Kolibre: riordino, non spostato:", m.da, err)
                end
            end
            self:_closeProgress()
            riepilogo.spostati = spostati
            riepilogo.non_spostati = #da_spostare - spostati
            riepilogo.fuori_posto = fuori
            fine()
        end,
        cancel_callback = function()
            riepilogo.non_spostati = #da_spostare
            fine()
        end,
    })
end
-- ── Annotations ──
--
-- Reads highlights/notes straight from KOReader's own .sdr sidecar files
-- (DocSettings, key "annotations" — verified against KOReader's real
-- frontend/apps/reader/modules/readerannotation.lua, field names: drawer,
-- text, note, color, chapter, pageno, pos0/pos1). Entries with no `drawer`
-- are plain page bookmarks, not highlights, and are skipped. pos0/pos1 are
-- xPointer strings for reflowable docs but tables for PDF — only the string
-- form is forwarded (used server-side as the dedup/update key), so re-syncing
-- an edited PDF highlight currently creates a new row rather than updating
-- the old one; a known limitation, not a bug.
--
-- Discarding plain bookmarks is a confirmed, deliberate choice (reaffirmed
-- on 2026-08-18, prompted by a comparative study of BookOrbit's own
-- separate Bookmark model) — not an unexamined gap. Kolibre only cares
-- about highlighted passages, not bare page markers.
--
-- `a.chapter` (as KOReader itself sets it) is only the innermost/leaf title
-- ("Capitolo II"), which is ambiguous in books structured as nested
-- Parts→Chapters — the Obsidian export (plugins/obsidian/kolibre-highlights)
-- needs the full ancestry to build correctly-nested markdown headings. This
-- used to be rebuilt on-device (walking the doc's cached TOC) but that's
-- real work — opening/parsing a whole book's TOC — for something a battery-
-- and-CPU-constrained e-reader shouldn't have to do at all: the server
-- already opens the same EPUB/PDF for CFI conversion, so v0.5.0 moved the
-- ancestry resolution there entirely (see backend/app/services/
-- position_converter/chapter_resolver.py, called from
-- push_device_annotations). Only the raw leaf title goes over the wire now,
-- as a fallback for whatever the server's own resolution can't handle
-- (MOBI/AZW3/FB2/TXT — no TOC-resolution service exists for those formats).

-- L'identita' del libro: biblioteca, id Calibre, formato — cioe' come Kolibre
-- lo chiama, non come e' fatto dentro.
--
-- **Perche' si manda questa e non solo l'impronta.** Fino al 06/10/2026 il
-- plugin diceva al server quale libro intendeva mandando l'impronta parziale
-- del file, e il server la risolveva all'indietro con tre livelli di ripiego.
-- Ma l'identita' ce l'abbiamo qui, nell'elenco dei libri che Kolibre ci ha
-- consegnato: la buttavamo via e facevamo indovinare al server una cosa che
-- sapevamo. Quando il file veniva riscritto da una delle due parti — un
-- metadato corretto sul server basta — l'impronta non combaciava piu' da
-- nessuna parte e l'annotazione diventava orfana, pur sapendo benissimo a
-- quale libro apparteneva.
--
-- Torna nil per i file che Kolibre non ha consegnato: li' l'identita' non
-- esiste, e l'impronta resta l'unico modo — ed e' il modo giusto, perche' e'
-- esattamente il lavoro di accoppiare un libro che sta solo sul dispositivo.
function Kolibre:_bookIdentity(path)
    local entry = self.manifest:findByPath(path)
    if not entry or not entry.library or not entry.calibre_book_id then return nil end
    return {
        library = entry.library,
        calibre_book_id = entry.calibre_book_id,
        format = entry.format,
    }
end

-- L'indirizzo per CHIEDERE la posizione di lettura. Stessa idea del corpo di
-- una richiesta: il nome del libro se lo si sa, l'impronta comunque.
function Kolibre:_progressPath(hash, format, path)
    local q = {}
    if hash then table.insert(q, "hash=" .. urlEncode(hash)) end
    if format then table.insert(q, "format=" .. urlEncode(format)) end
    local id = path and self:_bookIdentity(path) or nil
    if id then
        table.insert(q, "library=" .. urlEncode(tostring(id.library)))
        table.insert(q, "calibre_book_id=" .. tostring(id.calibre_book_id))
    end
    return "/api/kolibre/devices/progress?" .. table.concat(q, "&")
end

-- Attacca l'identita' a una tabella da spedire, se c'e'. Si aggiunge
-- ACCANTO all'impronta e mai al posto: un server vecchio continua a leggere
-- l'impronta e a non vedere il resto.
function Kolibre:_withIdentity(tbl, path)
    local id = self:_bookIdentity(path)
    if id then
        tbl.library = id.library
        tbl.calibre_book_id = id.calibre_book_id
        tbl.format = tbl.format or id.format
    end
    return tbl
end

-- Quello che il «sidecar» di KOReader dice della lettura di un file.
--
-- **Perche' conta.** KOReader tiene la lettura — quanto hai letto, se l'hai
-- finito, le note — in una cartella accanto al file e col suo nome. Senza
-- questi numeri la domanda «quale delle due copie dello stesso libro
-- cancello» non ha risposta; con questi ce l'ha, e misurata: su un libro vero
-- del Kindle di Paolo le due copie erano 3367 minuti di lettura contro 24.
--
-- Tutto nullo per un file mai aperto, ed e' giusto: non e' un dato mancante,
-- e' un libro che non e' stato letto.
--
-- `pcall` su tutto: questi file li scrive KOReader e li puo' aver scritti una
-- versione diversa da quella in esecuzione. Un sidecar illeggibile non deve
-- far fallire la camminata di duecento file.
function Kolibre:_letturaDalSidecar(file_path)
    if not DocSettings:hasSidecarFile(file_path) then return {} end
    local ok, ds = pcall(function() return DocSettings:open(file_path) end)
    if not ok or not ds then return {} end
    local fuori = {}
    pcall(function()
        fuori.percent_finished = ds:readSetting("percent_finished")
        fuori.pages = ds:readSetting("doc_pages")
        fuori.last_xpointer = ds:readSetting("last_xpointer")
        -- `summary.status` e' la risposta che la persona ha dato alla domanda
        -- «segno questo libro come finito?»: `reading`, `complete`,
        -- `abandoned`. Verificato che esiste su KOReader v2026.03.
        local summary = ds:readSetting("summary")
        if type(summary) == "table" then
            fuori.status = summary.status
            fuori.status_modified = summary.modified
        end
        -- QUANTE, non quali: l'inventario e' una misura, e le annotazioni
        -- viaggiano per conto loro (vedi `_extractAnnotationsFromFile`).
        local annotations = ds:readSetting("annotations")
        fuori.annotations = type(annotations) == "table" and #annotations or 0
    end)
    return fuori
end

function Kolibre:_extractAnnotationsFromFile(file_path, file_hash)
    if not DocSettings:hasSidecarFile(file_path) then return {} end
    local ok, doc_settings = pcall(function() return DocSettings:open(file_path) end)
    if not ok or not doc_settings then return {} end
    local annotations = doc_settings:readSetting("annotations") or {}

    -- L'identita' si cerca una volta sola per file, non una per annotazione.
    local identita = self:_bookIdentity(file_path)

    local out = {}
    for _idx, a in ipairs(annotations) do
        if a.drawer and a.text and a.text ~= "" then
            table.insert(out, {
                hash = file_hash,
                library = identita and identita.library or nil,
                calibre_book_id = identita and identita.calibre_book_id or nil,
                format = identita and identita.format or nil,
                -- Lets the server keep this annotation as an "orphan" (see
                -- OrphanHighlight) instead of silently dropping it when
                -- `hash` doesn't resolve to any known book yet.
                path = file_path,
                text = a.text,
                comment = a.note,
                color = a.color,
                page = a.pageno,
                chapter = a.chapter,
                pos0 = type(a.pos0) == "string" and a.pos0 or nil,
                pos1 = type(a.pos1) == "string" and a.pos1 or nil,
                -- KOReader's own "%Y-%m-%d %H:%M:%S" creation timestamp
                -- (readerannotation.lua stamps this once, when the
                -- highlight is first made — never touched again). Never
                -- forwarded before this: the server had no way to know
                -- when a highlight was ACTUALLY made, only when its row
                -- happened to be inserted, which could be much later than
                -- the real date for a book that stayed unmatched/orphan
                -- for a while — confirmed as a real bug, not hypothetical
                -- (a highlight known to be from 11/02/2025 showed
                -- up dated to whatever day the sync that finally pushed it
                -- ran).
                datetime = type(a.datetime) == "string" and a.datetime or nil,
            })
        end
    end
    return out
end

-- Impronta di CIO' CHE C'E' ORA nelle annotazioni di un file: cambia se una
-- nota viene aggiunta, modificata o cancellata, e non cambia se il libro e'
-- stato solo aperto e richiuso.
--
-- Serve a non rispedire ogni volta tutto. Chiudere un libro lo mette in coda,
-- e la coda rimandava SEMPRE tutte le sue annotazioni: un libro con 246 note
-- ne rimandava 246 ad ogni chiusura, che il server riscriveva identiche a se
-- stesse. Con l'impronta, un libro chiuso senza aver toccato le note non
-- costa piu' niente.
--
-- Le chiavi (pos0, o pagina+testo dove pos0 non c'e' — i PDF non hanno
-- xpointer) sono le stesse su cui il server decide se una nota e' nuova o
-- gia' vista, quindi l'impronta cambia esattamente quando cambierebbe
-- qualcosa dall'altra parte.
function Kolibre:_annotationsDigest(annotations)
    local chiavi = {}
    for _idx, a in ipairs(annotations) do
        table.insert(chiavi, table.concat({
            a.pos0 or "", a.pos1 or "", tostring(a.page or ""),
            a.text or "", a.comment or "", a.color or "",
        }, "\1"))
    end
    -- Ordinate: KOReader puo' restituire le annotazioni in ordine diverso
    -- senza che sia cambiato niente, e un'impronta che cambia per l'ordine
    -- farebbe rispedire tutto lo stesso, cioe' non servirebbe a niente.
    table.sort(chiavi)
    return sha2.sha256(table.concat(chiavi, "\2"))
end

-- Dice al server quali note esistono ANCORA per un file, cosi' che possa
-- accorgersi di quelle cancellate sul dispositivo.
--
-- Finora la sincronizzazione era solo additiva: una nota cancellata sul
-- Kindle restava sul server per sempre, e niente la riconciliava. L'ironia
-- e' che il costo l'avevamo gia' pagato — il plugin manda comunque l'insieme
-- COMPLETO delle note di un libro, e lo usavamo come se fosse un'aggiunta.
-- Si chiama solo dopo un invio riuscito per intero: riconciliare su un invio
-- interrotto a meta' vorrebbe dire cancellare sul server note che non erano
-- sparite, erano solo rimaste nel pacchetto successivo.
function Kolibre:_reconcileDeletions(per_file)
    if not per_file or #per_file == 0 then return end
    local result = self.api:request("POST", "/api/kolibre/devices/annotations/reconcile", { files = per_file })
    if result and (result.deleted or 0) > 0 then
        logger.info("Kolibre: " .. result.deleted .. " annotazioni rimosse anche sul server")
    end
end

-- Used by device-init's "flagged_started"/"no_candidate" branches: a file
-- Kolibre doesn't manage yet (never in the manifest) never had its
-- annotations extracted at all before this — only managed books ever
-- reached _extractAnnotationsFromFile, via _pushQueuedAnnotations or
-- pushAllAnnotationsFull. So a book already read/highlighted on the device
-- before Kolibre could recognize it kept its notes invisible to Kolibre
-- indefinitely, even after later being paired by hand, since there was
-- nothing to migrate at pairing time. The backend already turns an
-- unresolved-hash annotation into an OrphanHighlight (see push_device_
-- annotations/`path` field) instead of dropping it — this just finally
-- feeds that existing mechanism from device-init too, one batched request
-- for the whole list instead of one call per file.
function Kolibre:_pushAnnotationsForUnmanagedFiles(items)
    local all_annotations = {}
    for _idx, item in ipairs(items) do
        for _idx2, a in ipairs(self:_extractAnnotationsFromFile(item.path, item.hash)) do
            table.insert(all_annotations, a)
        end
    end
    if #all_annotations == 0 then return end
    local result = self.api:request("POST", "/api/kolibre/devices/annotations", { annotations = all_annotations })
    self:_reportAnnotationPushResult(result, false)
end

-- Reports created/updated/unresolved for any annotation push, interactive or
-- not — used to always show a "unresolved" count if it's non-zero, even on a
-- silent background push. Before this, an automatic push's result was
-- discarded entirely (only a manual "Sincronizza annotazioni" tap ever
-- showed it), which is exactly how a device silently sending annotations
-- Kolibre could never resolve (see backend's push_device_annotations —
-- unresolved means no matching BookHash row, see book_hash_service.py) went
-- unnoticed for weeks: nothing ever surfaced it.
function Kolibre:_reportAnnotationPushResult(result, interactive)
    if not result then
        if interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.annotations.sync_failed") })
        end
        return
    end
    local unresolved = result.unresolved or 0
    local orphaned = result.orphaned or 0
    if not interactive and unresolved == 0 and orphaned == 0 then return end
    local text = t("koreader.annotations.push_summary", { created = result.created or 0, updated = result.updated or 0 })
    if orphaned > 0 then
        text = text .. t("koreader.annotations.push_summary_orphaned", { count = orphaned })
    end
    if unresolved > 0 then
        text = text .. t("koreader.annotations.push_summary_unresolved", { count = unresolved })
    end
    UIManager:show(InfoMessage:new{ text = text, timeout = interactive and nil or 6 })
end

-- Root-cause follow-up for orphaned highlights, for the case of a book
-- pairable only later: a file whose annotations just landed as OrphanHighlight
-- because its exact hash never matches — permanently, for a device that
-- re-packages the EPUB on transfer (confirmed: Kindle) — gets one
-- content-fingerprint attempt right here, upstream of any human trip
-- through "Da rivedere". Reuses the exact same identify-file mechanism the
-- device-init scan already relies on (_identifyFileByContent), just
-- triggered by a routine annotation sync instead of a full library walk.
-- Non-destructive: like the manual "Accoppia" action, this only records a
-- hash mapping server-side, it never touches the file on the device.
-- Silent unless something was actually resolved.
function Kolibre:_tryAutoPairOrphans(paths)
    if not paths or #paths == 0 then return end
    local migrated, books = 0, 0
    for _idx, path in ipairs(paths) do
        local candidate = self:_identifyFileByContent(path)
        if candidate then
            local hash = util.partialMD5(path)
            if hash then
                local result = self.api:request("POST", "/api/kolibre/devices/annotations/auto-pair", {
                    local_path = path, file_hash = hash,
                    library = candidate.library, calibre_book_id = candidate.id,
                    format = (candidate.formats and candidate.formats[1]) or "EPUB",
                })
                if result then
                    migrated = migrated + (result.migrated_highlights or 0)
                    books = books + 1
                end
            end
        end
    end
    if books > 0 then
        UIManager:show(InfoMessage:new{
            text = t("koreader.library_init.auto_paired", { migrated = migrated, count = books }),
            timeout = 6,
        })
    end
end

-- "Pusha tutte le annotazioni" — the deliberate, explicit "give me
-- everything" escape hatch (Lettura menu, and _syncNowRun's own Fase 6 on a
-- manual "Sincronizza tutto"): walks the whole local library, re-hashing and
-- re-reading every sidecar, unlike _pushQueuedAnnotations below (which only
-- touches what's actually queued). Never called from an AUTOMATIC
-- background sync — re-hashing the whole books_dir on every close/suspend
-- would reintroduce exactly the e-ink-hostile cost kolibre_manifest.lua's
-- own dirty-queue was built to avoid.
function Kolibre:pushAllAnnotationsFull(interactive)
    if not self:_requireReachable(interactive) then return end

    -- Was completely silent before this — a books_dir walk this thorough
    -- (re-hashing every ebook) plus a network round-trip can easily run
    -- several seconds to a minute on a real library with no other sign of
    -- life on screen, which reads as a frozen device. Same _showProgress/
    -- _closeProgress pattern already used by _runLibraryInit for the exact
    -- same walk — a defect reported in use ("azioni costose senza
    -- finestra di progresso").
    local scanned = self:_scanLocalBooks(function(count)
        self:_showProgress(t("koreader.library_init.scanning_progress", { count = count }))
    end)
    self:_backfillAuthorFolderCovers(scanned)

    -- Qui NON si salta niente in base all'impronta: questa e' la via
    -- esplicita "mandami tutto", e chi la sceglie lo fa di solito proprio
    -- perche' sospetta che il server non sia allineato. Le impronte si
    -- aggiornano lo stesso alla fine, cosi' gli invii automatici successivi
    -- ne beneficiano.
    local all_annotations, impronte, chiavi_per_file = {}, {}, {}
    for _idx, b in ipairs(scanned) do
        local ann = self:_extractAnnotationsFromFile(b.path, b.hash)
        if #ann > 0 then
            local chiavi = {}
            for _idx2, a in ipairs(ann) do
                table.insert(all_annotations, a)
                table.insert(chiavi, { pos0 = a.pos0, page = a.page, text = a.text })
            end
            impronte[b.path] = self:_annotationsDigest(ann)
            table.insert(chiavi_per_file,
                self:_withIdentity({ hash = b.hash, path = b.path, keys = chiavi }, b.path))
        end
    end

    if #all_annotations == 0 then
        self:_closeProgress()
        if interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.annotations.nothing_to_sync") })
        end
        return
    end

    local result, sent, total = self:_postAnnotationsBatched(all_annotations, interactive, t("koreader.annotations.sending_to_server"))
    if interactive then self:_closeProgress() end
    if not result and sent > 0 then
        UIManager:show(InfoMessage:new{
            text = t("koreader.annotations.sync_interrupted", { sent = sent, total = total }),
        })
    else
        self:_reportAnnotationPushResult(result, interactive)
        self:_tryAutoPairOrphans(result and result.orphan_paths)
    end
    if result then
        -- A full push makes the whole offline queue moot.
        self.manifest:clearAllAnnotationDirty()
        for path, impronta in pairs(impronte) do
            self.manifest:setAnnotationsDigest(path, impronta)
        end
        self:_reconcileDeletions(chiavi_per_file)
    end
end

-- Sends `all_annotations` to POST /api/kolibre/devices/annotations in
-- batches of ANNOTATIONS_BATCH_SIZE rather than one giant request — real
-- failure mode confirmed against production data: a device with hundreds of
-- highlights (this session: 951 items, ~880KB body) produced a "sync
-- fallito" on a real Kindle even though the server itself, once it
-- receives the full body, processes that same payload in ~11s (measured
-- directly). The unbatched request is exactly the class of bug already
-- fixed once before in this plugin — v0.5.10's "Ripara tag pagine" changelog
-- entry describes the identical shape ("a full ... rewrite per book in ONE
-- request... reliably ran past the plugin's HTTP timeout... now paginated
-- ... in small batches with visible progress") — just never applied here
-- until now. No backend change needed: the endpoint already accepts any
-- list size per call, batching is purely a client-side concern.
--
-- Returns (combined_result, sent_count, total_count). combined_result is a
-- table with created/updated/unresolved/orphaned summed across every
-- batch on full success, or nil if any batch failed — callers use
-- sent_count/total_count to report how far it actually got rather than a
-- bare "failed" when some annotations plausibly did make it through.
local ANNOTATIONS_BATCH_SIZE = 200

function Kolibre:_postAnnotationsBatched(all_annotations, interactive, progress_label)
    local total = #all_annotations
    local combined = { created = 0, updated = 0, unresolved = 0, orphaned = 0, orphan_paths = {} }
    local sent = 0
    local batch_count = math.ceil(total / ANNOTATIONS_BATCH_SIZE)
    local batch_num = 0
    for start_idx = 1, total, ANNOTATIONS_BATCH_SIZE do
        batch_num = batch_num + 1
        local batch = {}
        for i = start_idx, math.min(start_idx + ANNOTATIONS_BATCH_SIZE - 1, total) do
            table.insert(batch, all_annotations[i])
        end
        if interactive then
            self:_showProgress(t("koreader.annotations.batch_progress", {
                label = progress_label, sent = sent, total = total, batch_num = batch_num, batch_count = batch_count,
            }))
        end
        local result = self.api:request("POST", "/api/kolibre/devices/annotations", { annotations = batch })
        if not result then
            return nil, sent, total
        end
        sent = sent + #batch
        combined.created = combined.created + (result.created or 0)
        combined.updated = combined.updated + (result.updated or 0)
        combined.unresolved = combined.unresolved + (result.unresolved or 0)
        combined.orphaned = combined.orphaned + (result.orphaned or 0)
        for _idx, p in ipairs(result.orphan_paths or {}) do
            table.insert(combined.orphan_paths, p)
        end
    end
    return combined, sent, total
end

-- "Sincronizza tutto"/automation's push_annot action: only the books
-- actually queued (marked dirty by onCloseDocument/onSuspend) — no
-- books_dir walk, no re-hashing every ebook on the device. Covers both the
-- just-closed book (freshly queued by the hook that led here) and anything
-- left over from a previous offline session.
function Kolibre:_pushQueuedAnnotations(interactive)
    if not self:_requireReachable(interactive) then return end
    local paths = self.manifest:annotationDirtyPaths()
    if #paths == 0 then return end

    local all_annotations, pushed_paths, invariati = {}, {}, 0
    local impronte, chiavi_per_file = {}, {}
    for _idx, path in ipairs(paths) do
        local hash = util.partialMD5(path)
        if hash then
            local ann = self:_extractAnnotationsFromFile(path, hash)
            local impronta = self:_annotationsDigest(ann)
            if impronta == self.manifest:annotationsDigest(path) then
                -- Il libro e' stato chiuso ma le note sono le stesse
                -- dell'ultimo invio riuscito: non c'e' niente da dire.
                self.manifest:clearAnnotationDirty(path)
                invariati = invariati + 1
            else
                local chiavi = {}
                for _idx2, a in ipairs(ann) do
                    table.insert(all_annotations, a)
                    table.insert(chiavi, { pos0 = a.pos0, page = a.page, text = a.text })
                end
                table.insert(pushed_paths, path)
                impronte[path] = impronta
                table.insert(chiavi_per_file,
                    self:_withIdentity({ hash = hash, path = path, keys = chiavi }, path))
            end
        end
    end

    if #all_annotations == 0 then
        -- Nothing left to send (deleted files, or sidecars with no real
        -- highlights) — still worth clearing, there's nothing to retry.
        for _idx, p in ipairs(pushed_paths) do self.manifest:clearAnnotationDirty(p) end
        if invariati > 0 then
            logger.info("Kolibre: " .. invariati .. " libri senza annotazioni nuove, niente da inviare")
        end
        return
    end

    -- Same reasoning as pushAllAnnotationsFull's own progress dialog — but
    -- gated on `interactive`: both current call sites (the automation
    -- matrix's push_annot action and _syncNowRun's own step) pass false,
    -- meaning this can run silently right after closing/suspending a book,
    -- exactly the "no popup on every book close" e-ink-hostile-cost concern
    -- kolibre_manifest.lua's own dirty-queue was already built around (see
    -- this function's own header comment) — a progress dialog there would
    -- be a regression, not a fix. Batching itself (_postAnnotationsBatched)
    -- still applies unconditionally though — a device back online after a
    -- long offline stretch can queue just as many items as a full push.
    local result, sent, total = self:_postAnnotationsBatched(all_annotations, interactive, t("koreader.annotations.sending_to_server"))
    if interactive and not result and sent > 0 then
        UIManager:show(InfoMessage:new{
            text = t("koreader.annotations.sync_interrupted", { sent = sent, total = total }),
        })
    else
        self:_reportAnnotationPushResult(result, interactive)
        -- Gated on `interactive`: _tryAutoPairOrphans uploads whole files for
        -- content-fingerprint identification (_identifyFileByContent), real
        -- weight this function's own silent background call sites
        -- (onSuspend/onClose hooks, interactive=false) are explicitly meant
        -- to avoid — see this function's header comment. Only a manual
        -- "Sincronizza annotazioni" tap pays that cost, same policy as
        -- _backfillAuthorFolderCovers/pushAllAnnotationsFull already follow.
        if interactive then self:_tryAutoPairOrphans(result and result.orphan_paths) end
    end
    if result then
        for _idx, p in ipairs(pushed_paths) do
            self.manifest:clearAnnotationDirty(p)
            -- L'impronta si registra SOLO ora: se l'invio fosse fallito,
            -- registrarla vorrebbe dire non riprovare mai piu'.
            self.manifest:setAnnotationsDigest(p, impronte[p])
        end
        self:_reconcileDeletions(chiavi_per_file)
    end
    -- On failure the queue is left untouched entirely — retried whole next time.
end

-- ── Backup ──

function Kolibre:backupNow(interactive)
    if not self:_requireReachable(interactive) then return end

    -- Gated on `interactive`, same reasoning as _pushQueuedAnnotations: most
    -- call sites here are silent automatic hooks (onSuspend/onNetworkConnected
    -- etc.) — a progress popup there would be a regression, not a fix. Only
    -- the menu item and the confirm-dialog callback pass true.
    local total = #BACKUP_FILES_ROOT + #BACKUP_FILES_SETTINGS
    local done = 0
    local uploaded, failed, skipped = 0, 0, 0

    -- Una domanda sola al server prima di caricare qualunque cosa: "di questi
    -- file, quali hai gia' identici?". Prima venivano caricati tutti e dodici
    -- a OGNI sincronizzazione, ~700 KB e dodici round-trip, anche quando non
    -- era cambiato niente — e otto di quei dodici (gesti, scorciatoie, ordini
    -- di menu, collezioni) non cambiano praticamente mai.
    --
    -- Il confronto e' su dimensione E MD5 completo, lo stesso che il server
    -- ricalcola dal proprio file: nessuno dei due tiene uno stato che possa
    -- disallinearsi, e se il server perde un file l'hash non torna e quel
    -- file viene ricaricato da solo.
    --
    -- MD5 intero e non util.partialMD5 (che pure e' gia' in casa e costa meno):
    -- il partial campiona alcuni blocchi, ottimo per riconoscere un libro, ma
    -- qui la domanda e' "questo file e' cambiato?" e sbagliarla significa un
    -- backup che smette di aggiornarsi senza dirlo. Su file da qualche
    -- centinaio di KB leggerli per intero costa molto meno che caricarli.
    --
    -- Se la domanda fallisce (server vecchio senza questo endpoint, rete che
    -- cade a meta') si ricade sul comportamento di prima: caricare tutto. Una
    -- diagnosi mancata non deve mai diventare un backup mancato.
    local remote = {}
    local state = self.api:request("GET", "/api/kolibre/devices/backup/state")
    if state and type(state.files) == "table" then
        remote = state.files
    end

    local function backupFrom(dir, files)
        for _idx, fname in ipairs(files) do
            done = done + 1
            if interactive then self:_showProgressBar(done, total, fname) end
            local full_path = dir .. "/" .. fname
            local attr = lfs.attributes(full_path)
            -- statistics.sqlite3 e' il file grosso e l'unico che cambia a
            -- ogni lettura: prima di caricarne 659 KB si prova a mandare le
            -- sole righe nuove. Se non si puo' (server vecchio, deposito
            -- vuoto, conto che non torna) si ricade qui sotto sul file
            -- intero, che e' esattamente il comportamento di prima.
            if attr and attr.mode == "file" and fname == "statistics.sqlite3"
               and self:_uploadStatsIncremental() then
                skipped = skipped + 1
            elseif attr and attr.mode == "file" then
                local known = remote[fname]
                if known and known.size == attr.size and known.hash
                   and known.hash == MD5.sumFile(full_path) then
                    skipped = skipped + 1
                else
                    local ok, err = self.api:uploadFile("/api/kolibre/devices/backup?filename=" .. fname, full_path)
                    if ok then
                        uploaded = uploaded + 1
                    else
                        failed = failed + 1
                        logger.warn("Kolibre: backup fallito per", fname, err)
                    end
                end
            end
        end
    end
    backupFrom(DataStorage:getDataDir(), BACKUP_FILES_ROOT)
    backupFrom(DataStorage:getSettingsDir(), BACKUP_FILES_SETTINGS)
    -- Le letture misurate in caratteri non sono un file di KOReader: non
    -- passano dall'elenco qui sopra, hanno un canale loro. Protette perche'
    -- un invio che fallisce non deve far fallire un backup riuscito.
    pcall(function() self:_uploadLetture() end)
    if interactive then self:_closeProgress() end

    if uploaded > 0 then
        G_reader_settings:saveSetting("kolibre_last_backup_at", os.time())
    end

    if interactive then
        UIManager:show(InfoMessage:new{
            text = t("koreader.backup.summary", { uploaded = uploaded, skipped = skipped, failed = failed }),
        })
    end
    return uploaded, skipped, failed
end

-- ── Resetta a stato di dispositivo (task #266) ──
--
-- Tre conferme, mai applicazione silenziosa: (1) qui, l'utente sceglie il
-- dispositivo sorgente e conferma localmente → POST .../sync/restore-request
-- crea la richiesta lato server in stato pending_admin; (2) un admin la
-- conferma sul frontend web (confirmed_admin); (3) solo allora il prossimo
-- handshake /sync la restituisce in result.restore_request (vedi
-- _syncNowRun sotto) e questo device chiede un'ultima conferma locale prima
-- di scrivere qualunque file. G_reader_settings è lo stato che fa
-- sopravvivere il passo (3) a un riavvio tra l'arrivo della conferma admin e
-- il momento in cui l'utente effettivamente conferma sul device — stesso
-- meccanismo di persistenza semplice già usato per kolibre_last_backup_at,
-- non serve il marker su disco della logica di self-update (qui non c'è
-- nessuno stato "a metà" da recuperare, solo un booleano "c'è una richiesta
-- in attesa" con i suoi dati).
function Kolibre:_startDeviceRestore()
    -- 20/11/2026 (E7): controllo di raggiungibilita' piu' richiesta dei
    -- dispositivi fratelli, tutto sincrono e prima senza nessun segno.
    self:_runWithWaitingSign(nil, function()
        if not self:_requireReachable(true) then return end
        local siblings, err = self.api:request("GET", "/api/kolibre/devices/siblings")
        if not siblings or #siblings == 0 then
            UIManager:show(InfoMessage:new{
                text = t("koreader.restore.no_other_device", { error = tostring(err or t("koreader.restore.none_registered")) }),
            })
            return
        end

        local picker
        local items = {}
        for _idx, dev in ipairs(siblings) do
            table.insert(items, {
                text = dev.name .. " (" .. tostring(dev.model) .. ")",
                callback = function()
                    UIManager:close(picker)
                    self:_confirmDeviceRestoreSource(dev)
                end,
            })
        end
        picker = Menu:new{ title = t("koreader.restore.choose_source"), item_table = items, is_popout = true }
        UIManager:show(picker)
    end)
end

function Kolibre:_confirmDeviceRestoreSource(source_device)
    UIManager:show(ConfirmBox:new{
        text = t("koreader.restore.request_confirm", { device = source_device.name }),
        ok_text = t("koreader.common.request"),
        cancel_text = t("koreader.common.cancel"),
        ok_callback = function()
            local result, err = self.api:request("POST", "/api/kolibre/devices/sync/restore-request", { source_device_id = source_device.id })
            if not result then
                UIManager:show(InfoMessage:new{ text = t("koreader.restore.request_failed", { error = tostring(err) }) })
                return
            end
            UIManager:show(InfoMessage:new{
                text = t("koreader.restore.request_sent"),
            })
        end,
    })
end

-- Chiamata dopo ogni handshake /sync riuscito (vedi _syncNowRun): salva o
-- svuota lo stato locale della richiesta in attesa. Non applica nulla da
-- sola — solo _checkPendingRestoreRequest, su onResume/onNetworkConnected,
-- decide se e quando mostrare il banner.
function Kolibre:_rememberRestoreRequest(restore_request)
    if restore_request then
        G_reader_settings:saveSetting("kolibre_pending_restore_request", restore_request)
    else
        G_reader_settings:delSetting("kolibre_pending_restore_request")
    end
end

function Kolibre:_checkPendingRestoreRequest()
    -- onResume e onNetworkConnected possono scattare entrambi nella stessa
    -- ripresa (vedi onResume's own commento sul debounce di
    -- _autoCheckForUpdate) — questo guard evita di impilare due
    -- ButtonDialog identici invece di introdurre un debounce a tempo, che
    -- qui non avrebbe senso (l'utente deve poter riaprire subito scegliendo
    -- di nuovo "Resetta a stato di dispositivo" se ha appena cliccato
    -- "Più tardi").
    if self._restore_dialog_shown then return end
    local pending = G_reader_settings:readSetting("kolibre_pending_restore_request")
    if not pending then return end

    self._restore_dialog_shown = true
    local dialog
    dialog = ButtonDialog:new{
        title = t("koreader.restore.migration_confirmed_title"),
        text = t("koreader.restore.migration_confirmed_body", { device = tostring(pending.source_device_name) }),
        buttons = {
            {
                {
                    text = t("koreader.common.later"),
                    callback = function()
                        self._restore_dialog_shown = false
                        UIManager:close(dialog)
                    end,
                },
                {
                    text = t("koreader.restore.migrate_now"),
                    callback = function()
                        self._restore_dialog_shown = false
                        UIManager:close(dialog)
                        self:_confirmAndRunDeviceRestore(pending)
                    end,
                },
            },
        },
    }
    UIManager:show(dialog)
end

function Kolibre:_confirmAndRunDeviceRestore(pending)
    UIManager:show(ConfirmBox:new{
        text = t("koreader.restore.overwrite_confirm", { device = tostring(pending.source_device_name) }),
        ok_text = t("koreader.restore.overwrite_and_migrate"),
        cancel_text = t("koreader.common.cancel"),
        ok_callback = function() self:_runDeviceRestore(pending) end,
    })
end

function Kolibre:_runDeviceRestore(pending)
    if not self:_requireReachable(true) then return end

    local applied, missing = {}, {}
    local files = {}
    for _idx, fname in ipairs(RESTORE_FILES_ROOT) do
        table.insert(files, { name = fname, dir = DataStorage:getDataDir() })
    end
    for _idx, fname in ipairs(RESTORE_FILES_SETTINGS) do
        table.insert(files, { name = fname, dir = DataStorage:getSettingsDir() })
    end

    for idx, f in ipairs(files) do
        self:_showProgressBar(idx, #files, f.name)
        local local_path = f.dir .. "/" .. f.name
        local ok, dl_err = self.api:downloadTo(
            "/api/kolibre/devices/sync/restore-request/" .. tostring(pending.source_device_id)
                .. "/file?filename=" .. f.name,
            local_path
        )
        if ok then
            table.insert(applied, f.name)
        else
            table.insert(missing, f.name)
            logger.warn("Kolibre: restore, file non applicato:", f.name, dl_err)
        end
    end

    self.api:request("POST", "/api/kolibre/devices/sync/restore-request/" .. tostring(pending.id) .. "/complete",
        { files_applied = applied })
    -- Reintegra subito statistics.sqlite3 appena ereditato nel database del
    -- server, invece di aspettare il prossimo backup automatico — stessa
    -- pipeline (process_statistics_db) di un backup qualunque, solo con
    -- device_id di QUESTO dispositivo (quello autenticato), non del sorgente.
    self:backupNow(false)
    self:_rememberRestoreRequest(nil)
    self:_closeProgress()

    UIManager:show(InfoMessage:new{
        text = t("koreader.restore.result", { applied = #applied, missing = #missing }),
    })
end

-- ── Self-update e patch ──
--
-- Trasloco del 20/11/2026 (revisione A2): il flusso dell'aggiornamento —
-- versione, manifesto, download coi checksum, marcatore di ripresa — e
-- l'installazione delle patch vivono in kolibre_aggiornamento.lua. Qui
-- restano le deleghe e, piu' sotto, il menu' delle patch
-- (_patchMenuItems), che e' interfaccia e non flusso.
function Kolibre:_versioneNuovaDelPlugin(...) return KolibreAggiornamento._versioneNuovaDelPlugin(self, ...) end
function Kolibre:controllaAggiornamenti(...) return KolibreAggiornamento.controllaAggiornamenti(self, ...) end
function Kolibre:_writeUpdateMarker(...) return KolibreAggiornamento._writeUpdateMarker(self, ...) end
function Kolibre:_removeUpdateMarker(...) return KolibreAggiornamento._removeUpdateMarker(self, ...) end
function Kolibre:_readUpdateMarker(...) return KolibreAggiornamento._readUpdateMarker(self, ...) end
function Kolibre:_applyStagedRenames(...) return KolibreAggiornamento._applyStagedRenames(self, ...) end
function Kolibre:_resumePendingUpdate(...) return KolibreAggiornamento._resumePendingUpdate(self, ...) end
function Kolibre:_downloadAndInstallUpdate(...) return KolibreAggiornamento._downloadAndInstallUpdate(self, ...) end
function Kolibre:_cartellaDellePatch(...) return KolibreAggiornamento._cartellaDellePatch(self, ...) end
function Kolibre:_patchDisattivateDaKOReader(...) return KolibreAggiornamento._patchDisattivateDaKOReader(self, ...) end
function Kolibre:_statoDellaPatch(...) return KolibreAggiornamento._statoDellaPatch(self, ...) end
function Kolibre:_installaPatch(...) return KolibreAggiornamento._installaPatch(self, ...) end
function Kolibre:_rimuoviPatch(...) return KolibreAggiornamento._rimuoviPatch(self, ...) end
function Kolibre:_chiediRiavvio(...) return KolibreAggiornamento._chiediRiavvio(self, ...) end

-- Il sottomenu, costruito quando lo si apre: una voce per patch, con la
-- spunta se e' installata. Una chiamata al server, perche' l'elenco di cosa
-- esiste lo sa solo lui — se non risponde si mostra comunque quello che c'e'
-- installato, che e' l'informazione utile quando si e' fuori casa.
function Kolibre:_patchMenuItems()
    local voci = {}

    -- Se non si sa nemmeno dove installarle, il menu' lo dice e si ferma qui:
    -- aprire un elenco di cose che non si possono mettere da nessuna parte
    -- non serve a niente.
    if not self:_cartellaDellePatch() then
        return { { text = t("koreader.patches.dir_unknown"), enabled = false } }
    end

    if self:_patchDisattivateDaKOReader() then
        table.insert(voci, {
            text = t("koreader.patches.all_disabled"),
            keep_menu_open = true,
            callback = function()
                UIManager:show(InfoMessage:new{ text = t("koreader.patches.all_disabled_explain") })
            end,
        })
        voci[#voci].separator = true
    end

    local elenco = nil
    if self:_requireReachable(false) then
        -- 20/11/2026 (E7): questo codice gira DENTRO sub_item_table_func,
        -- che deve tornare la tabella subito: il nextTick di
        -- _runWithWaitingSign qui non si puo' usare. Si mostra il segno e
        -- si ridisegna (il forceRePaint sta dentro _showProgress) PRIMA
        -- della chiamata, cosi' sull'e-ink il messaggio arriva allo
        -- schermo; e la risposta e' un elenco piccolo per costruzione,
        -- quindi vale il profilo `breve` (3/9 s), non i 10/30 di LARGE.
        self:_showProgress(t("koreader.common.contacting_server"))
        local risposta = self.api:request("GET", "/api/tools/koreader/patches", nil, { breve = true })
        self:_closeProgress()
        elenco = risposta and risposta.patches or nil
    end

    if not elenco then
        table.insert(voci, {
            text = t("koreader.patches.server_unreachable"),
            enabled = false,
        })
        -- Quello che e' installato si sa guardando il disco, e si sa sempre.
        local cartella = self:_cartellaDellePatch()
        if cartella and lfs.attributes(cartella, "mode") == "directory" then
            for nome_file in lfs.dir(cartella) do
                if nome_file:match("^%d%d*%-.*%.lua$") then
                    local patch = { file = nome_file, nome = nome_file }
                    table.insert(voci, {
                        text = nome_file,
                        checked_func = function() return true end,
                        keep_menu_open = true,
                        callback = function()
                            UIManager:show(ConfirmBox:new{
                                text = t("koreader.patches.confirm_remove", { name = nome_file }),
                                ok_text = t("koreader.patches.remove"),
                                ok_callback = function() self:_rimuoviPatch(patch) end,
                            })
                        end,
                    })
                end
            end
        end
        return voci
    end

    if #elenco == 0 then
        table.insert(voci, { text = t("koreader.patches.none_available"), enabled = false })
        return voci
    end

    for _idx, patch in ipairs(elenco) do
        table.insert(voci, {
            text_func = function()
                local stato = self:_statoDellaPatch(patch)
                if stato == "diversa" then
                    return patch.nome .. " — " .. t("koreader.patches.update_available")
                end
                return patch.nome
            end,
            -- La spunta dice una cosa sola e vera: c'e' o non c'e'.
            checked_func = function() return self:_statoDellaPatch(patch) ~= "assente" end,
            help_text = patch.descrizione ~= "" and patch.descrizione or nil,
            keep_menu_open = true,
            callback = function()
                local stato = self:_statoDellaPatch(patch)
                if stato == "uguale" then
                    UIManager:show(ConfirmBox:new{
                        text = t("koreader.patches.confirm_remove", { name = patch.nome }),
                        ok_text = t("koreader.patches.remove"),
                        ok_callback = function() self:_rimuoviPatch(patch) end,
                    })
                    return
                end
                local chiave = stato == "diversa" and "koreader.patches.confirm_update"
                                                  or "koreader.patches.confirm_install"
                UIManager:show(ConfirmBox:new{
                    text = t(chiave, {
                        name = patch.nome,
                        description = patch.descrizione ~= "" and patch.descrizione
                                      or t("koreader.patches.no_description"),
                    }),
                    ok_text = stato == "diversa" and t("koreader.patches.update")
                                                  or t("koreader.patches.install"),
                    ok_callback = function() self:_installaPatch(patch) end,
                })
            end,
        })
    end

    voci[#voci].separator = true
    table.insert(voci, {
        text = t("koreader.patches.where"),
        keep_menu_open = true,
        callback = function()
            UIManager:show(InfoMessage:new{
                text = t("koreader.patches.where_explain", { dir = self:_cartellaDellePatch() }),
            })
        end,
    })
    return voci
end

-- ── Dizionario StarDict sul dispositivo ──
--
-- Scarica il dizionario StarDict installato sul server (Impostazioni →
-- Integrazioni → Dizionari, backend/app/services/stardict_service.py)
-- dentro data/dict/ — la cartella in cui KOReader li cerca davvero,
-- verificata nel suo readerdictionary.lua — così la ricerca nativa
-- (tieni premuto su
-- una parola durante la lettura) lo trova e lo usa da sola — stesso
-- meccanismo manifest + download-per-file del self-update qui sopra, per
-- lo stesso motivo: KOReader non offre a questo plugin alcuna libreria di
-- decompressione zip on-device (vedi il commento di _downloadAndInstallUpdate).
-- Scarica un dizionario dal server e lo installa dove KOReader lo cerca.
--
-- **Chi lo chiede.** Non piu' una voce di menu' sul lettore: lo si manda dal
-- portale (Dispositivi ▸ Manda un dizionario), e il lettore lo prende alla
-- prima sincronizzazione completa. Il motivo e' che la scelta «quale
-- dizionario» si fa davanti a uno schermo vero, una volta, mentre sul
-- lettore era una voce di menu' permanente per un'azione che si fa una volta
-- nella vita del dispositivo.
--
-- `muto` sopprime il progresso e il messaggio di fine, ma **non** quello di
-- errore: un download fallito e' una cosa che vuoi sapere comunque, e in
-- quel caso il dizionario resta in coda sul server e si riprova.
--
-- Torna true solo se ogni file e' arrivato e la sua impronta combacia:
-- e' quello che chi chiama usa per confermare al server, e un dizionario a
-- meta' non va confermato.
function Kolibre:downloadDictionary(lang, interactive, muto)
    if not self:_requireReachable(interactive) then return false end

    local manifest, err = self.api:request("GET", "/api/kolibre/devices/dictionaries/" .. lang .. "/manifest")
    if not manifest or not manifest.files or #manifest.files == 0 then
        if interactive then
            UIManager:show(InfoMessage:new{
                text = t("koreader.dictionary.unavailable"),
            })
        end
        return false
    end

    -- **Il percorso lo decide `kolibre_percorsi`, e la cartella la crea
    -- `util.makePath` di KOReader.** Prima erano `getDataDir()` grezzo e la
    -- nostra `ensureDir`, e su un Kindle non funzionava niente: la' quel
    -- metodo risponde `"."`, e `ensureDir` ricompone il percorso segmento per
    -- segmento mettendo una barra davanti a ognuno — quindi creava
    -- `/./dict/...` alla radice (in sola lettura) mentre `io.open` apriva
    -- `./dict/...` relativa alla cartella di lavoro. Riprodotto sul KOReader
    -- vero l'08/11/2026. In piu' la cartella era `<dati>/dict` e KOReader i
    -- dizionari li cerca in `<dati>/data/dict`.
    --
    -- E il valore di ritorno si **guarda**: senza, una cartella che non si
    -- riusciva a creare si presentava come l'errore di `io.open` del primo
    -- file — cioe' come un problema di rete, che e' il messaggio che si e'
    -- visto sul dispositivo.
    local target_dir = KolibrePercorsi.cartellaDeiDizionari(DataStorage, lang, lfs.currentdir)
    if not target_dir or not util.makePath(target_dir) then
        UIManager:show(InfoMessage:new{
            text = t("koreader.dictionary.no_folder", { dir = tostring(target_dir or "?") }),
        })
        return false
    end

    local failed = nil
    for _idx, file in ipairs(manifest.files) do
        if not muto then self:_showProgressBar(_idx, #manifest.files, file.name) end
        local remote_path = "/api/kolibre/devices/dictionaries/" .. lang .. "/file/" .. urlEncode(file.name)
        local target_path = target_dir .. "/" .. file.name
        local staged_path = target_path .. ".kolibre-new"

        local ok, download_err = self.api:downloadTo(remote_path, staged_path)

        -- Same "HTTP 200 isn't proof the bytes are complete" reasoning as
        -- the plugin self-update above.
        if ok and file.sha256 then
            local actual_size = lfs.attributes(staged_path, "size")
            if file.size and actual_size ~= file.size then
                ok, download_err = false, "checksum_mismatch (size)"
            else
                local content = util.readFromFile(staged_path, "rb")
                if not content or sha2.sha256(content) ~= file.sha256 then
                    ok, download_err = false, "checksum_mismatch (sha256)"
                end
            end
        end

        if not ok then
            os.remove(staged_path)
            failed = { name = file.name, err = download_err }
            break
        end
        if lfs.attributes(target_path, "mode") then os.remove(target_path) end
        os.rename(staged_path, target_path)
    end

    self:_closeProgress()

    if failed then
        UIManager:show(InfoMessage:new{
            text = t("koreader.dictionary.download_failed", { file = tostring(failed.name), error = tostring(failed.err) }),
        })
        return false
    end

    if not muto then
        UIManager:show(InfoMessage:new{
            text = t("koreader.dictionary.done", { name = manifest.display_name or lang }),
        })
    end
    return true
end

-- ── Sync (protocol v2) ──
--
-- Trasloco del 20/11/2026 (revisione A2): il protocollo — fase 0 del
-- payload, gli ack, le rimozioni, l'orchestrazione fino alla POST
-- /sync/finish — vive in kolibre_sync.lua, con la testa di quel file a
-- raccontarlo. Qui restano le deleghe, cosi' i chiamanti continuano a
-- parlare col plugin.
function Kolibre:_sendAck(...) return KolibreSync._sendAck(self, ...) end
function Kolibre:_diskUsage(...) return KolibreSync._diskUsage(self, ...) end
function Kolibre:_patchInstallate(...) return KolibreSync._patchInstallate(self, ...) end
function Kolibre:_buildSyncPayload(...) return KolibreSync._buildSyncPayload(self, ...) end

-- Deletes one managed book from local storage: file, sidecar (DocSettings),
-- reading-history entry, manifest entry, and the per-author folder when the
-- book was the last real thing in it. opts.keep_manifest_entry leaves the
-- manifest untouched (used by the managed-books menu, where the entry must
-- survive so the next sync reports the file as missing).
function Kolibre:_deleteManagedBook(path, opts)
    opts = opts or {}
    if not path then return false, "percorso sconosciuto" end

    if lfs.attributes(path, "mode") == "file" then
        local ok, err = os.remove(path)
        -- Trust disk state over os.remove's return (same rationale as the
        -- self-update rename loop): only a file still present is a failure.
        if not ok and lfs.attributes(path, "mode") == "file" then
            return false, tostring(err or "os.remove fallita")
        end
    end

    -- I metadati del libro se ne vanno come li toglie KOReader stesso quando
    -- cancella un file (FileManager:deleteFile, uguale in 2025.08, 2026.03 e
    -- 2026.07.2): `DocSettings.updateLocation(path)` senza percorso nuovo
    -- (dal 24/11/2026, prima era `purge()`). La differenza: toglie anche la
    -- cache del documento, e sulla 2026.07 conserva l'archivio dei metadati
    -- se l'impostazione lo chiede. E il libro esce dalle collezioni e dalla
    -- cache delle copertine. Tutto sotto pcall: una API che manca non deve
    -- fermare una cancellazione a meta'.
    pcall(function() DocSettings.updateLocation(path) end)
    pcall(function() require("readcollection"):removeItem(path) end)
    pcall(function() require("ui/widget/booklist").resetBookInfoCache(path) end)

    -- Drop from KOReader's reading history, if the module/method exists.
    pcall(function()
        local ReadHistory = require("readhistory")
        if ReadHistory and ReadHistory.removeItemByPath then
            ReadHistory:removeItemByPath(path)
        end
    end)

    if not opts.keep_manifest_entry then
        if opts.manifest_key then
            self.manifest:remove(opts.manifest_key)
        end
        -- Also drop any migration-era "hash:*" entry pointing at this file.
        for k, e in pairs(self.manifest:all()) do
            if e.path == path then self.manifest:remove(k) end
        end
    end

    self:_cleanupBookDir(path)
    return true
end

-- If deleting the book left its folder with no ebook file at all (checked
-- by EXTENSION — epub/pdf/mobi/azw3/fb2/txt, same table _scanLocalBooks
-- uses — not "any leftover entry"), remove the whole folder: our own
-- .folder.jpg cover, any "<book>.sdr" sidecar debris (DocSettings:purge()
-- clears what's INSIDE a sidecar dir but doesn't reliably remove the now-
-- empty dir itself — that alone used to block this from ever firing, a
-- real gap confirmed after a real "delete last book of an author" test),
-- and AppleDouble "._*" junk (same convention as the device-init scan).
-- Anything else unrecognized is left alone and blocks the folder removal —
-- conservative on purpose, never delete something this plugin doesn't
-- understand.
function Kolibre:_cleanupBookDir(path)
    local dir = path:match("^(.*)/[^/]+$")
    if not dir or dir == "" or dir == self.books_dir then return end
    local ok, iter, dir_obj = pcall(lfs.dir, dir)
    if not ok or not iter then return end

    local has_ebook, has_unknown, removable = false, false, {}
    for entry in iter, dir_obj do
        if entry ~= "." and entry ~= ".." then
            local ext = entry:match("%.([%a%d]+)$")
            if entry == ".folder.jpg" or entry:sub(1, 2) == "._" or entry:match("%.sdr$") then
                table.insert(removable, dir .. "/" .. entry)
            elseif ext and EBOOK_EXTENSIONS[ext:lower()] then
                has_ebook = true
            else
                has_unknown = true
            end
        end
    end

    if has_ebook or has_unknown then return end
    for _idx, full in ipairs(removable) do
        if lfs.attributes(full, "mode") == "directory" then
            _removeDirRecursive(full)
        else
            os.remove(full)
        end
    end
    pcall(lfs.rmdir, dir)
end

-- Fase 3 (le rimozioni chieste dal server): il corpo vive in
-- kolibre_sync.lua (trasloco del 20/11/2026, revisione A2).
function Kolibre:_applyDeletions(...) return KolibreSync._applyDeletions(self, ...) end

-- Reads on-device page counts from the statistics plugin's database. Its
-- `book` table stores md5 (KOReader's partialMD5 — the very hash the server
-- resolves books by) and pages. Everything is pcall-guarded: no ljsqlite3,
-- no db, or a schema surprise just means "no page data this sync".
function Kolibre:_readStatisticsPages()
    local ok, SQ3 = pcall(require, "lua-ljsqlite3/init")
    if not ok or not SQ3 then return nil end
    local db_path = DataStorage:getSettingsDir() .. "/statistics.sqlite3"
    if lfs.attributes(db_path, "mode") ~= "file" then return nil end

    local pages_by_hash = nil
    local ok2, err = pcall(function()
        local conn = SQ3.open(db_path)
        local res = conn:exec("SELECT md5, pages FROM book WHERE md5 IS NOT NULL AND pages IS NOT NULL;")
        conn:close()
        pages_by_hash = {}
        if res then
            local md5s = res.md5 or res[1]
            local pages = res.pages or res[2]
            for i = 1, #(md5s or {}) do
                -- tonumber/tostring: ljsqlite3 may hand back int64 cdata.
                local h, p = md5s[i] and tostring(md5s[i]), tonumber(pages[i])
                if h and p and p > 0 then
                    pages_by_hash[h] = p
                end
            end
        end
    end)
    if not ok2 then
        logger.warn("Kolibre: lettura statistics.sqlite3 fallita:", err)
        return nil
    end
    return pages_by_hash
end

-- ── Statistiche in salita: solo le righe nuove ──
--
-- Ogni sincronizzazione caricava statistics.sqlite3 intero: 659 KB misurati
-- su questo Kindle, 10.822 righe dal febbraio 2025, per riportare quello che
-- era successo dall'ultima volta — UNA riga, in una giornata normale.
--
-- Ora si chiede al server fin dove e' arrivato e si mandano solo le righe
-- successive. Sullo stesso file: un giorno 29 byte, una settimana di lettura
-- vera 397. Il file intero resta il ripiego, e ci si torna da soli se il
-- conto non torna — mai una statistica che diverge in silenzio.
--
-- Torna true se le statistiche sono sistemate (niente file da caricare),
-- false per ricadere sul caricamento integrale.
function Kolibre:_uploadStatsIncremental()
    local ok, SQ3 = pcall(require, "lua-ljsqlite3/init")
    if not ok or not SQ3 then return false end
    local db_path = DataStorage:getSettingsDir() .. "/statistics.sqlite3"
    if lfs.attributes(db_path, "mode") ~= "file" then return false end

    local stato = self.api:request("GET", "/api/kolibre/devices/stats/state")
    -- Server vecchio senza l'endpoint, o deposito ancora vuoto: si carica
    -- tutto, che e' anche il modo in cui il primo sync popola il deposito.
    if not stato or not stato.disponibile then return false end

    local da = tonumber(stato.da) or 0
    local payload = nil
    local letto, err = pcall(function()
        local conn = SQ3.open(db_path)
        local tot = conn:exec("SELECT COUNT(*) AS n, COALESCE(SUM(duration), 0) AS d FROM page_stat_data;")
        local righe = conn:exec(string.format(
            "SELECT id_book, page, start_time, duration, total_pages FROM page_stat_data "
            .. "WHERE start_time >= %d ORDER BY start_time ASC;", da))
        -- I libri: solo quelli toccati dalle righe nuove. Il deposito ha gia'
        -- gli altri, e mandarli tutti rimetterebbe in salita meta' del file.
        local libri = conn:exec(string.format(
            "SELECT id, title, authors, notes, last_open, highlights, pages, series, language, md5, "
            .. "total_read_time, total_read_pages FROM book WHERE id IN "
            .. "(SELECT DISTINCT id_book FROM page_stat_data WHERE start_time >= %d);", da))
        conn:close()

        local function col(res, nome, indice)
            if not res then return {} end
            return res[nome] or res[indice] or {}
        end
        local rows = {}
        local ib, pg, st, du, tp = col(righe, "id_book", 1), col(righe, "page", 2),
            col(righe, "start_time", 3), col(righe, "duration", 4), col(righe, "total_pages", 5)
        for i = 1, #ib do
            -- tonumber: ljsqlite3 puo' restituire cdata int64.
            rows[#rows + 1] = { tonumber(ib[i]), tonumber(pg[i]), tonumber(st[i]),
                                tonumber(du[i]), tonumber(tp[i]) }
        end
        local books = {}
        local nomi = { "id", "title", "authors", "notes", "last_open", "highlights",
                       "pages", "series", "language", "md5", "total_read_time", "total_read_pages" }
        local numerici = { id = true, notes = true, last_open = true, highlights = true,
                           pages = true, total_read_time = true, total_read_pages = true }
        local ids = col(libri, "id", 1)
        for i = 1, #ids do
            local libro = {}
            for indice, nome in ipairs(nomi) do
                local valore = col(libri, nome, indice)[i]
                if valore ~= nil then
                    libro[nome] = numerici[nome] and tonumber(valore) or tostring(valore)
                end
            end
            books[#books + 1] = libro
        end
        payload = {
            books = books,
            rows = rows,
            totals = {
                righe = tonumber(col(tot, "n", 1)[1]) or 0,
                somma_durate = tonumber(col(tot, "d", 2)[1]) or 0,
            },
        }
    end)
    if not letto or not payload then
        logger.warn("Kolibre: lettura incrementale statistiche fallita:", err)
        return false
    end

    -- Si manda anche quando non c'e' niente di nuovo: il payload e' una
    -- sessantina di byte e serve a far tornare il conto ogni volta, invece
    -- di accorgersi di un buco fra sei mesi.
    local res = self.api:request("POST", "/api/kolibre/devices/stats/incremental", payload)
    if not res or res.risincronizza then
        if res then logger.info("Kolibre: statistiche da riallineare:", tostring(res.motivo)) end
        return false
    end
    -- Finisce nella cronologia della sincronizzazione: e' il numero che dice
    -- se l'invio incrementale sta davvero lavorando.
    self._ultime_righe_statistiche = tonumber(res.righe_aggiunte) or 0
    return true
end

--- Manda al server le letture misurate in caratteri che non ha ancora.
---
--- Stessa forma dell'invio incrementale delle statistiche, e per le stesse
--- ragioni: il server dice da quale istante ripartire (con una finestra di
--- sovrapposizione), si manda da li' in avanti, e i doppioni li butta lui —
--- una riga rimandata costa pochi byte, una riga saltata non torna piu'.
---
--- **Si pota solo dopo che il server ha confermato**, e solo fino alla
--- filigrana che risponde LUI: il file sul lettore e' la coda, non il
--- deposito, ma buttare una riga che il server non ha davvero vorrebbe dire
--- perdere una lettura per sempre.
---
--- Torna quante righe il server ha aggiunto, o 0 — e non solleva mai: una
--- misura che fa fallire un backup riuscito sarebbe un danno al posto di un
--- miglioramento.
function Kolibre:_uploadLetture()
    local reg = letture()
    if reg:quante() == 0 then return 0 end

    local stato = self.api:request("GET", "/api/kolibre/devices/caratteri/state")
    -- Server piu' vecchio di questo plugin: non c'e' niente da fare e non e'
    -- un guasto. Le righe restano nel file e partiranno quando il server
    -- saprà riceverle.
    if not stato or stato.da == nil then return 0 end

    local righe, saltate = reg:righeDa(tonumber(stato.da) or 0)
    if #righe == 0 then return 0 end

    local vettori = {}
    for indice, r in ipairs(righe) do vettori[indice] = KolibreLetture.vettore(r) end

    local res = self.api:request("POST", "/api/kolibre/devices/caratteri/incremental", {
        formato = KolibreLetture.VERSIONE_FORMATO,
        campi = KolibreLetture.CAMPI,
        righe = vettori,
        illeggibili = saltate,
    })
    if not res or res.filigrana == nil then return 0 end

    local buttate = reg:pota(tonumber(res.filigrana) or 0)
    local aggiunte = tonumber(res.righe_aggiunte) or 0
    if aggiunte > 0 or buttate > 0 then
        logger.info("Kolibre: letture in caratteri:", aggiunte, "aggiunte,", buttate, "potate")
    end
    self._ultime_righe_letture = aggiunte
    return aggiunte
end

-- Fase 4. Reports page counts for managed books whose value is new or
-- changed since the last report; the manifest is updated only after the
-- server accepted the batch, so a failed POST simply retries next sync.
function Kolibre:_reportPages()
    local pages_by_hash = self:_readStatisticsPages()
    if not pages_by_hash then return 0 end

    local report, touched = {}, {}
    for key, entry in pairs(self.manifest:all()) do
        if entry.hash then
            local p = pages_by_hash[entry.hash]
            if p and p ~= entry.pages then
                table.insert(report, {
                    hash = entry.hash,
                    library = entry.library,
                    calibre_book_id = entry.calibre_book_id,
                    format = entry.format,
                    pages = p,
                })
                table.insert(touched, { key = key, entry = entry, pages = p })
            end
        end
    end
    if #report == 0 then return 0 end

    local result, err = self.api:request("POST", "/api/kolibre/devices/pages", { books = report })
    if not result then
        logger.warn("Kolibre: /pages fallito:", err)
        return 0
    end
    for _idx, t in ipairs(touched) do
        t.entry.pages = t.pages
        self.manifest:set(t.key, t.entry, true) -- no_dirty: just reported
    end
    return #report
end

-- L'orchestrazione del sync (handshake, download, rimozioni, finish) e la
-- conferma dei download: trasloco del 20/11/2026 (revisione A2), i corpi
-- vivono in kolibre_sync.lua. interactive, trigger e solo_libri passano
-- invariati.
function Kolibre:syncBooksOnly(...) return KolibreSync.syncBooksOnly(self, ...) end
function Kolibre:syncNow(...) return KolibreSync.syncNow(self, ...) end
function Kolibre:_syncNowRun(...) return KolibreSync._syncNowRun(self, ...) end
function Kolibre:_confirmDownloads(...) return KolibreSync._confirmDownloads(self, ...) end

-- ── Reading-position sync ──
--
-- Control flow mirrors stock kosync.koplugin (verified against KOReader's
-- real source): percentage/progress are read from self.ui.paging or
-- self.ui.rolling depending on the document type, and a pulled position is
-- applied via a GotoPage/GotoXPointer event on self.ui. Self-origin
-- detection (don't prompt to sync to a position this same device just
-- pushed) is done server-side, via the device-token auth already tied to a
-- specific device row — no local device-id bookkeeping needed here.

function Kolibre:_getLastPercent()
    if self.ui.document.info.has_pages then
        return self.ui.paging:getLastPercent()
    else
        return self.ui.rolling:getLastPercent()
    end
end

function Kolibre:_getLastProgress()
    if self.ui.document.info.has_pages then
        return self.ui.paging:getLastProgress()
    else
        return self.ui.rolling:getLastProgress()
    end
end

function Kolibre:_syncToProgress(progress)
    if self.ui.document.info.has_pages then
        self.ui:handleEvent(Event:new("GotoPage", tonumber(progress)))
    else
        self.ui:handleEvent(Event:new("GotoXPointer", progress))
    end
end

function Kolibre:_documentFormat()
    local ext = self.ui.document.file:match("%.([^.]+)$")
    return (ext or "EPUB"):upper()
end

-- Lo stato che KOReader dichiara sul libro aperto: 'reading', 'complete',
-- 'abandoned'.
--
-- Perche' esiste. Quando si arriva in fondo a un libro KOReader chiede
-- «segnarlo come finito?», e la risposta la scrive nel suo sidecar
-- (`summary.status`, piu' `summary.modified` col giorno). Il server invece
-- quel fatto se lo deduceva dalla copertura — propone di segnare un libro
-- come letto quando supera il 90% — cioe' una stima al posto di una
-- dichiarazione, che sbaglia in entrambe le direzioni: un romanzo saltato a
-- meta' e poi finito, un saggio di cui si leggono tre capitoli su dieci.
--
-- Si legge da `self.ui.doc_settings` e NON dal file del sidecar: finche' il
-- libro e' aperto il sidecar su disco e' vecchio (KOReader lo scrive alla
-- chiusura), e il caso che conta e' esattamente quello — si dice «finito» e
-- subito dopo si chiude il libro.
function Kolibre:_statoDelLibro()
    if not self.ui or not self.ui.doc_settings then return nil, nil end
    local ok, summary = pcall(function() return self.ui.doc_settings:readSetting("summary") end)
    if not ok or type(summary) ~= "table" then return nil, nil end
    local stato = summary.status
    if type(stato) ~= "string" or stato == "" then return nil, nil end
    local modificato = type(summary.modified) == "string" and summary.modified or nil
    return stato, modificato
end

function Kolibre:pushProgress(interactive)
    if not self.ui.document then
        if interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.position.no_document_push") })
        end
        return
    end
    if not self:_requireReachable(interactive) then return end
    local now = os.time()
    local stato, stato_modificato = self:_statoDelLibro()
    -- Un cambio di stato passa sempre l'antirimbalzo (24/11/2026): segnare
    -- un libro finito e chiuderlo entro 25 secondi dall'ultimo invio lo
    -- perdeva, perche' la coda salta il libro aperto («ci pensa
    -- pushProgress»).
    if not interactive and now - (self.push_timestamp or 0) < PROGRESS_PUSH_DEBOUNCE_SECONDS
            and stato == self.last_pushed_stato then
        return
    end

    local percent = self:_getLastPercent()
    -- Not dirty: nothing moved since our last successful push (e.g. closing
    -- a book right after opening it, or a suspend right after a resume,
    -- with no page turns in between) — skip the request outright. Manual/
    -- interactive pushes always go through regardless, since the user asked.
    --
    -- Lo stato entra in questo controllo, e non e' un dettaglio: si dichiara
    -- «finito» quando si e' GIA' in fondo al libro, cioe' quando la
    -- percentuale non si muove piu'. Senza questa condizione la spinta
    -- successiva verrebbe saltata come «niente di nuovo» e la dichiarazione
    -- non arriverebbe mai al server — proprio nell'unico momento in cui
    -- esiste.
    if not interactive and self.last_pushed_percent
            and math.abs(self.last_pushed_percent - percent) < 0.0005
            and self.last_pushed_stato == stato then
        return
    end
    self.push_timestamp = now

    local hash = util.partialMD5(self.ui.document.file)
    if not hash then return end
    local ok, err = self.api:request("PUT", "/api/kolibre/devices/progress",
        self:_withIdentity({
            hash = hash,
            format = self:_documentFormat(),
            percentage = percent,
            progress = self:_getLastProgress(),
            stato = stato,
            stato_modificato = stato_modificato,
        }, self.ui.document.file))
    if ok then
        self.last_pushed_percent = percent
        self.last_pushed_stato = stato
        self:_statoInviato(self.ui.document.file, stato)
    end
    if interactive then
        if ok then
            UIManager:show(InfoMessage:new{ text = t("koreader.position.push_sent"), timeout = 2 })
        else
            UIManager:show(InfoMessage:new{ text = t("koreader.position.push_failed", { error = tostring(err) }) })
        end
    end
end

function Kolibre:pullProgress(interactive)
    if not self.ui.document then
        if interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.position.no_document_pull") })
        end
        return
    end
    if not self:_requireReachable(interactive) then return end
    local now = os.time()
    if not interactive and now - (self.pull_timestamp or 0) < PROGRESS_PUSH_DEBOUNCE_SECONDS then
        return
    end
    -- We just pushed our own position moments ago: nothing could plausibly
    -- have changed elsewhere that fast, so skip this round-trip entirely.
    if not interactive and now - (self.push_timestamp or 0) < PROGRESS_PUSH_DEBOUNCE_SECONDS then
        return
    end
    self.pull_timestamp = now

    local hash = util.partialMD5(self.ui.document.file)
    if not hash then return end
    local result, err = self.api:request(
        "GET", self:_progressPath(hash, self:_documentFormat(), self.ui.document.file)
    )
    if not result then
        if interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.position.pull_failed", { error = tostring(err) }) })
        end
        return
    end
    if not result.percentage or result.is_own_device then
        if interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.position.nothing_to_sync") })
        end
        return
    end

    local my_percent = self:_getLastPercent()
    if math.abs((my_percent or 0) - result.percentage) < 0.001 then
        if interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.position.already_synced") })
        end
        return
    end

    local apply = function()
        self:_syncToProgress(result.progress)
        UIManager:show(InfoMessage:new{ text = t("koreader.position.synced"), timeout = 2 })
    end
    if interactive then
        apply()
    else
        UIManager:show(ConfirmBox:new{
            text = t("koreader.position.sync_confirm", {
                percent = math.floor(result.percentage * 100), device = result.device_name or "?",
            }),
            ok_callback = apply,
        })
    end
end

-- ── Reading position: sync ALL books, not just the one currently open ──
--
-- pushProgress/pullProgress above only ever touch the live reader state
-- (self.ui.paging/self.ui.rolling), so they're scoped to whichever book is
-- open right now. But every other book on the device already has its own
-- position cached in its own sidecar — percent_finished + last_xpointer
-- (reflowable formats) or last_page (paged formats, i.e. PDF among the
-- formats this plugin handles) — the exact fields KOReader's own
-- readerrolling.lua/readerpaging.lua save whenever a book is closed.
-- Readable AND writable without opening the book, the same way
-- _extractAnnotationsFromFile already reads annotations from closed books'
-- sidecars. This is what lets "Sincronizza tutte le posizioni" cover the
-- whole library in one pass.
local PAGED_FORMATS = { PDF = true }

-- nil if the book has never been opened locally (no sidecar, or a sidecar
-- with no percent_finished yet) — nothing to push in that case.
function Kolibre:_readLocalProgress(file_path, is_paged)
    if not DocSettings:hasSidecarFile(file_path) then return nil end
    local ok, doc_settings = pcall(function() return DocSettings:open(file_path) end)
    if not ok or not doc_settings then return nil end
    local percent = doc_settings:readSetting("percent_finished")
    if type(percent) ~= "number" then return nil end
    local progress = is_paged and doc_settings:readSetting("last_page") or doc_settings:readSetting("last_xpointer")
    if not progress then return nil end
    -- Lo stato del libro («finito», «in pausa»), come `_statoDelLibro` per il
    -- libro aperto (24/11/2026). Senza, le strade che leggono il sidecar — la
    -- coda delle posizioni, «Sync all positions» — mandavano solo la
    -- percentuale: un libro finito e chiuso senza rete non diventava mai
    -- «finito» sul server.
    local summary = doc_settings:readSetting("summary")
    local stato, stato_modificato = nil, nil
    if type(summary) == "table" and type(summary.status) == "string" and summary.status ~= "" then
        stato = summary.status
        stato_modificato = type(summary.modified) == "string" and summary.modified or nil
    end
    return { percent = percent, progress = progress, stato = stato, stato_modificato = stato_modificato }
end

--- I libri il cui stato e' cambiato fuori da un libro aperto finiscono in
--- coda (24/11/2026).
--
-- Un libro si puo' segnare «finito» anche dal file browser o dalla
-- cronologia di KOReader, senza aprirlo: nessun evento ci avvisa, e il
-- libro non entra nella coda delle posizioni. Qui, prima di mandare la
-- coda, si guardano i sidecar dei libri del manifesto: solo quelli il cui
-- file e' cambiato dall'ultima volta (la data di modifica, che costa un
-- `stat`), e fra quelli si mettono in coda i libri il cui stato non e'
-- quello gia' mandato. Cosi' anche la scelta fatta senza rete parte alla
-- prima coda utile, come ha chiesto Paolo.
function Kolibre:_statiDaMandare()
    local visti = self.manifest:getMeta("sidecar_visti")
    if type(visti) ~= "table" then visti = {} end
    local inviati = self.manifest:getMeta("stati_inviati")
    if type(inviati) ~= "table" then inviati = {} end
    local cambiati = false
    for _k, e in pairs(self.manifest:all()) do
        local path = e.path
        local sidecar = path and DocSettings:findSidecarFile(path)
        local quando = sidecar and lfs.attributes(sidecar, "modification")
        if quando and visti[path] ~= quando then
            visti[path] = quando
            cambiati = true
            local ok, ds = pcall(function() return DocSettings:open(path) end)
            local summary = ok and ds and ds:readSetting("summary")
            local stato = type(summary) == "table" and summary.status or nil
            if type(stato) == "string" and stato ~= "" and inviati[path] ~= stato then
                self.manifest:markPositionDirty(path)
            end
        end
    end
    if cambiati then self.manifest:setMeta("sidecar_visti", visti) end
end

--- Ricorda lo stato mandato, cosi' `_statiDaMandare` non lo rimanda.
function Kolibre:_statoInviato(path, stato)
    if not path or not stato then return end
    local inviati = self.manifest:getMeta("stati_inviati")
    if type(inviati) ~= "table" then inviati = {} end
    if inviati[path] ~= stato then
        inviati[path] = stato
        self.manifest:setMeta("stati_inviati", inviati)
    end
end

-- DocSettings:open() on a book with no sidecar yet returns a fresh, empty
-- one (verified against KOReader's own docsettings.lua) — safe to call even
-- for a book never opened locally, so a position can arrive here before the
-- book itself is ever read on this device (e.g. right after "Inizializza
-- libreria" links it). KOReader's own file-browser progress overlay reads
-- percent_finished the same way, so this makes it show up correctly there
-- too, not just on next open.
function Kolibre:_writeLocalProgress(file_path, is_paged, percent, progress)
    local ok, doc_settings = pcall(function() return DocSettings:open(file_path) end)
    if not ok or not doc_settings then return false end
    doc_settings:saveSetting("percent_finished", percent)
    if is_paged then
        doc_settings:saveSetting("last_page", tonumber(progress))
    else
        doc_settings:saveSetting("last_xpointer", progress)
    end
    doc_settings:flush()
    return true
end

-- ── Un libro alla volta, da chi tiene premuto nella vista ───────────────
--
-- **Perche' esistono queste due funzioni** (Paolo, 16/11/2026: tenendo
-- premuto un libro si apre un menu con «scarica posizione dal server» e
-- «manda posizione al server»). Quelle che c'erano prima non servivano:
-- `pushProgress`/`pullProgress` lavorano sul libro **aperto adesso**
-- (`self.ui.document`), e `syncAllProgress` scandisce tutto il dispositivo e
-- chiede conferma a lotti. Qui il libro e' uno, e' chiuso, e l'ha scelto una
-- persona: nessuna scansione, nessun confronto, nessuna conferma a lotti.
--
-- Non si riscrive niente: i mattoni sono gli stessi che il confronto a lotti
-- usa da sempre — `_readLocalProgress` e `_writeLocalProgress`, che leggono e
-- scrivono il sidecar di un libro chiuso.

--: L'estensione, in maiuscolo, per i casi in cui il manifesto non dice il
--  formato (un libro che il server non ha mai consegnato: la cronologia
--  mostra anche quelli).
local function formatoDaPercorso(path)
    local ext = path and path:match("%.([%a%d]+)$")
    return ext and ext:upper() or nil
end

--- «Manda la posizione di questo libro», oppure «scaricala».
--
-- `verso` e' "manda" o "scarica". Interattiva per forza: l'ha chiesta
-- qualcuno guardando lo schermo, quindi ogni esito si dice — compreso
-- «non c'era niente da mandare», che e' un esito e non un errore.
function Kolibre:posizioneDiUnLibro(path, verso)
    if not path or lfs.attributes(path, "mode") ~= "file" then
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.libro_non_c_e") })
        return
    end
    -- **Il libro aperto non si tocca da qui.** Scrivergli il sidecar sotto il
    -- naso significa farselo sovrascrivere dal lettore quando lo chiude —
    -- e' la stessa ragione per cui `_computeProgressDiff` salta il libro
    -- corrente. Per quello ci sono le due voci di Strumenti, che passano dal
    -- documento vero.
    if self.ui and self.ui.document and self.ui.document.file == path then
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.posizione_libro_aperto") })
        return
    end
    if not self:_requireReachable(true) then return end

    local m = self.manifest:findByPath(path) or {}
    local formato = m.format or formatoDaPercorso(path)
    local is_paged = PAGED_FORMATS[formato] or false
    local hash = util.partialMD5(path)

    if verso == "manda" then
        local locale = self:_readLocalProgress(path, is_paged)
        if not locale then
            -- Un libro mai aperto su questo lettore non ha una posizione, e
            -- mandare uno zero cancellerebbe quella vera di un altro
            -- dispositivo.
            UIManager:show(InfoMessage:new{ text = t("koreader.ui.posizione_niente_da_mandare") })
            return
        end
        local ok, err = self.api:request("PUT", "/api/kolibre/devices/progress",
            self:_withIdentity({
                hash = hash, format = formato,
                percentage = locale.percent, progress = locale.progress,
            }, path))
        if ok then
            UIManager:show(InfoMessage:new{
                text = t("koreader.ui.posizione_mandata", {
                    percento = math.floor((locale.percent or 0) * 100 + 0.5) }),
                timeout = 3 })
        else
            UIManager:show(InfoMessage:new{
                text = t("koreader.ui.posizione_errore", { error = tostring(err) }) })
        end
        return
    end

    local risposta = self.api:request("GET", self:_progressPath(hash, formato, path))
    -- `nil` e' «non ho potuto chiedere», una risposta senza percentuale e'
    -- «il server non ne ha una». Sono due cose diverse e si dicono diverse:
    -- confonderle e' il difetto che il confronto a lotti ha avuto per mesi.
    if risposta == nil then
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.posizione_errore", { error = "-" }) })
        return
    end
    if not risposta.percentage or not risposta.progress then
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.posizione_niente_sul_server") })
        return
    end
    if self:_writeLocalProgress(path, is_paged, risposta.percentage, risposta.progress) then
        UIManager:show(InfoMessage:new{
            text = t("koreader.ui.posizione_scaricata", {
                percento = math.floor(risposta.percentage * 100 + 0.5) }),
            timeout = 3 })
    else
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.posizione_errore", { error = "sidecar" }) })
    end
end

--- «Togli questo libro da questo lettore.»
--
-- **Prima il file, poi il server, anche senza rete** (Paolo, 24/11/2026).
-- Fino alla 0.31.0 l'ordine era l'opposto: si chiedeva al server di non
-- volere piu' il libro (`/books/removed`) e solo dopo il si' si cancellava,
-- perche' un file cancellato a insaputa del server torna alla
-- sincronizzazione dopo. Il prezzo era che senza rete non si eliminava
-- niente. Ora il file si cancella subito e la richiesta va in coda
-- (`kolibre_rimozioni.lua`): parte adesso se c'e' rete, altrimenti all'inizio
-- della prossima sincronizzazione, PRIMA dell'handshake; e finche' non e'
-- partita quel libro non si riscarica.
--
-- L'identita' si prende PRIMA di cancellare: `_deleteManagedBook` toglie la
-- riga del manifesto, ed e' da li' che vengono biblioteca e id.
--
-- `al_termine` serve alla vista per rileggere l'elenco: la riga deve
-- sparire, altrimenti il comando sembra non aver fatto niente.
function Kolibre:toglieQuestoLibro(path, al_termine)
    if not path then return end

    local m = self.manifest:findByPath(path)
    local hash = util.partialMD5(path)
    if not hash and not m then
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.elimina_sconosciuto") })
        return
    end
    local chiave = nil
    for k, e in pairs(self.manifest:all()) do
        if e.path == path then chiave = k break end
    end
    local voce = self:_withIdentity({ hash = hash, format = m and m.format or formatoDaPercorso(path) }, path)
    voce.path = path
    voce.quando = os.time()

    local ok, errore = self:_deleteManagedBook(path, { manifest_key = chiave })
    if not ok then
        UIManager:show(InfoMessage:new{
            text = t("koreader.ui.elimina_file_no", { error = tostring(errore) }) })
        if al_termine then pcall(al_termine) end
        return
    end
    KolibreRimozioni.aggiungi(self.manifest, voce)

    -- La rete si guarda SENZA finestre: se non c'e', non e' un errore —
    -- e' esattamente il caso per cui la coda esiste.
    local restanti = 1
    if self:_requireReachable(false) then
        local _uscite
        _uscite, restanti = KolibreRimozioni.consegna(self.manifest, self.api,
            function(msg) logger.warn(msg) end)
    end
    UIManager:show(InfoMessage:new{
        text = restanti == 0 and t("koreader.ui.elimina_fatto")
            or t("koreader.ui.elimina_in_coda"),
        timeout = 3 })
    if al_termine then pcall(al_termine) end
end

-- Scans the whole device, classifies every OTHER book (the open one, if
-- any, stays with the live push/pull above — writing its sidecar directly
-- here could be clobbered by the reader's own save-on-close right after)
-- into "push" (we have a position the server doesn't, or ours is newer by
-- virtue of the server row being our own last write) or "pull" (another
-- device has a position we don't have locally, or a different one) — never
-- both for the same book, and never guessed silently: each direction gets
-- its own batch confirm before touching anything, exactly like the
-- device-init feature's hash-match/overwrite batches.
-- The scan+compare loop itself, factored out of syncAllProgress (the silent
-- automation variants that also used it went with the 1.0.0 menu).
function Kolibre:_computeProgressDiff(on_progress)
    local scanned = self:_scanLocalBooks(on_progress)
    local current_path = self.ui.document and self.ui.document.file or nil

    local to_push, to_pull = {}, {}
    for idx, b in ipairs(scanned) do
        if on_progress and (idx % 5 == 0 or idx == #scanned) then
            self:_showProgress(t("koreader.position.comparing_progress", { done = idx, total = #scanned }))
        end
        if b.path ~= current_path then
            local is_paged = PAGED_FORMATS[b.format] or false
            local local_pos = self:_readLocalProgress(b.path, is_paged)
            local result = self.api:request(
                "GET", self:_progressPath(b.hash, b.format, b.path)
            )
            -- Una GET FALLITA non e' "il server non ha nessuna posizione".
            -- KolibreApi:request torna nil sia quando la rete cade sia quando
            -- il server risponde male, e il secondo ramo qui sotto era vero
            -- per costruzione in quel caso (`not result` soddisfa entrambe le
            -- condizioni): il libro finiva nella coda di INVIO, e la PUT
            -- successiva sovrascriveva sul server una posizione piu' recente
            -- arrivata da un altro dispositivo.
            --
            -- Su un e-reader con wifi instabile non e' un caso di laboratorio,
            -- ed e' perdita di dato silenziosa: nessun errore a schermo, e con
            -- l'automazione push_pos_all nemmeno una conferma da dare.
            -- Un errore di trasporto deve ESCLUDERE il libro dal confronto.
            if result == nil then
                goto continua
            end

            local server_has_other = result and result.percentage and not result.is_own_device
            if server_has_other and (not local_pos or math.abs(local_pos.percent - result.percentage) >= 0.001) then
                table.insert(to_pull, { book = b, is_paged = is_paged, result = result })
            elseif local_pos and (not result.percentage or result.is_own_device)
                and math.abs(local_pos.percent - (result.percentage or -1)) >= 0.001 then
                table.insert(to_push, { book = b, is_paged = is_paged, local_pos = local_pos })
            end
            ::continua::
        end
    end
    return to_push, to_pull
end

function Kolibre:syncAllProgress(interactive)
    if not self:_requireReachable(interactive) then return end

    local to_push, to_pull = self:_computeProgressDiff(function(count)
        self:_showProgress(t("koreader.library_init.scanning_progress", { count = count }))
    end)
    self:_closeProgress()

    self:_confirmPushAllProgress(to_push, to_pull)
end

-- "Sincronizza tutto"'s own position push: only books actually queued by
-- onCloseDocument/onSuspend/onPageUpdate (kolibre_manifest's
-- position_dirty_paths) — no books_dir walk, unlike syncAllProgress. The
-- currently open book is excluded (pushProgress covers it separately, same
-- convention _computeProgressDiff already uses).
-- Dopo quanti giri di sincronizzazione falliti di fila si smette di
-- ritentare la posizione di UN libro (la rete assente non conta: la ferma
-- _requireReachable prima di arrivare qui — questi sono errori del server
-- su quel libro, tipicamente un hash che non risolve).
local POSITION_PUSH_MAX_FAILURES = 5

function Kolibre:_pushQueuedPositions(interactive)
    if not self:_requireReachable(interactive) then return end
    pcall(function() self:_statiDaMandare() end)
    local paths = self.manifest:positionDirtyPaths()
    if #paths == 0 then return end
    local current_path = self.ui.document and self.ui.document.file or nil

    local pushed = 0
    local gave_up = 0
    for _idx, path in ipairs(paths) do
        if path == current_path then
            self.manifest:clearPositionDirty(path) -- pushProgress covers this one
        else
            local ext = path:match("%.([%a%d]+)$")
            local format = ext and ext:upper() or nil
            local hash = format and util.partialMD5(path)
            local local_pos = hash and self:_readLocalProgress(path, PAGED_FORMATS[format] or false)
            if local_pos then
                local ok = self.api:request("PUT", "/api/kolibre/devices/progress", self:_withIdentity({
                    hash = hash, format = format, percentage = local_pos.percent, progress = local_pos.progress,
                    stato = local_pos.stato, stato_modificato = local_pos.stato_modificato,
                }, path))
                if ok then
                    pushed = pushed + 1
                    self:_statoInviato(path, local_pos.stato)
                    self.manifest:clearPositionDirty(path)
                else
                    -- Fallito: resta in coda, ma NON per sempre (23/11/2026,
                    -- richiesta di Paolo: prima si ritentava in silenzio
                    -- all'infinito). Dopo POSITION_PUSH_MAX_FAILURES
                    -- fallimenti consecutivi si rinuncia e lo si DICE una
                    -- volta; riaprire il libro rimette la posizione in coda
                    -- da zero (markPositionDirty azzera il contatore), e
                    -- «Sincronizza tutto» la manda comunque.
                    if self.manifest:positionPushFailed(path) >= POSITION_PUSH_MAX_FAILURES then
                        self.manifest:clearPositionDirty(path)
                        gave_up = gave_up + 1
                    end
                end
            else
                self.manifest:clearPositionDirty(path) -- file gone or unreadable, nothing to retry
            end
        end
    end
    if gave_up > 0 then
        UIManager:show(InfoMessage:new{
            text = t("koreader.position.push_gave_up", { count = gave_up, tries = POSITION_PUSH_MAX_FAILURES }),
            timeout = 6,
        })
    end
    if interactive and pushed > 0 then
        UIManager:show(InfoMessage:new{ text = t("koreader.position.push_all_done", { count = pushed }), timeout = 3 })
    end
end

function Kolibre:_confirmPushAllProgress(to_push, to_pull)
    if #to_push == 0 then
        self:_confirmPullAllProgress(to_pull)
        return
    end
    UIManager:show(ConfirmBox:new{
        text = t("koreader.position.push_all_confirm", { count = #to_push }),
        ok_text = t("koreader.common.send"),
        cancel_text = t("koreader.common.ignore"),
        ok_callback = function()
            for _idx, e in ipairs(to_push) do
                local ok_s = self.api:request("PUT", "/api/kolibre/devices/progress", self:_withIdentity({
                    hash = e.book.hash, format = e.book.format,
                    percentage = e.local_pos.percent, progress = e.local_pos.progress,
                    stato = e.local_pos.stato, stato_modificato = e.local_pos.stato_modificato,
                }, e.book.path))
                if ok_s then self:_statoInviato(e.book.path, e.local_pos.stato) end
            end
            UIManager:show(InfoMessage:new{ text = t("koreader.position.push_all_done", { count = #to_push }), timeout = 3 })
            self:_confirmPullAllProgress(to_pull)
        end,
        cancel_callback = function() self:_confirmPullAllProgress(to_pull) end,
    })
end

function Kolibre:_confirmPullAllProgress(to_pull)
    if #to_pull == 0 then return end
    UIManager:show(ConfirmBox:new{
        text = t("koreader.position.pull_all_confirm", { count = #to_pull }),
        ok_text = t("koreader.common.download_verb"),
        cancel_text = t("koreader.common.ignore"),
        ok_callback = function()
            for _idx, e in ipairs(to_pull) do
                self:_writeLocalProgress(e.book.path, e.is_paged, e.result.percentage, e.result.progress)
            end
            UIManager:show(InfoMessage:new{ text = t("koreader.position.pull_all_done", { count = #to_pull }), timeout = 3 })
        end,
    })
end

-- ── Automation settings ──
--
-- Everything below governs which lifecycle hooks (§ next section) actually
-- do anything — the hooks themselves are always registered (KOReader calls
-- them unconditionally), but each checks these settings before acting, same
-- pattern as stock kosync's own `self.settings.auto_sync` gate.
--
-- v0.5.0 replaced four fixed on/off moments (each hardcoded to its own fixed
-- action bundle — e.g. "close" always meant "push position + push
-- annotations", nothing else, nothing less) with a real matrix: four
-- moments, each a free multi-select over a shared action vocabulary. Stored
-- as ONE G_reader_settings table (moment id -> array of enabled action ids)
-- instead of four independent booleans, since the old shape had no room for
-- "close" to mean anything other than exactly that one fixed pair.

local SYNC_REMINDER_DAYS_DEFAULT = 7
local SYNC_REMINDER_CHOICES = { 3, 7, 30, 0 } -- 0 = disabled

local FULL_SYNC_DEBOUNCE_SECONDS = 60
-- **Una chiave nuova dalla 0.30.0** (menu della 1.0.0, piano del 24/11/2026).
-- La matrice e' cambiata: meno azioni, e predefiniti diversi (la chiusura
-- di un libro ora manda la posizione invece di sincronizzare tutto). Le
-- scelte salvate sotto la chiave vecchia (`kolibre_automation_actions`)
-- parlavano di azioni che non ci sono piu': invece di tradurle, si riparte
-- per tutti dai predefiniti nuovi. Lasciato andare di proposito.
--
-- **E di nuovo con la 1.0.0** (`kolibre_automations_1_0`): la 0.33.0 ha
-- aggiunto la sessione alla chiusura e Sync alla sospensione, accesi di
-- serie per decisione di Paolo; chi aveva toccato le automazioni fra la
-- 0.30.0 e la 1.0.0 se li sarebbe persi, perche' i predefiniti valgono solo
-- per chi non ha mai salvato niente.
local AUTOMATION_SETTING_KEY = "kolibre_automations_1_0"

-- "avvio" also covers onResume (risveglio) — conceptually both are "the
-- app/device is becoming active again", and the user never named resume as
-- its own separate moment.
local AUTOMATION_MOMENTS = {
    { id = "avvio",       label = t("koreader.automation.moment_startup") },
    { id = "apertura",    label = t("koreader.automation.moment_open") },
    { id = "chiusura",    label = t("koreader.automation.moment_close") },
    { id = "spegnimento", label = t("koreader.automation.moment_shutdown") },
}

-- `scopes`: which moments may offer this action at all — push/pull "current
-- book" position only make sense around apertura/chiusura (spegnimento and
-- avvio have no natural "the book I'm reading" to push/pull without an open
-- document, and _isAutomationActionEnabled/_runAutomationMoment never even
-- get asked about them there).
local AUTOMATION_ACTIONS = {
    { id = "sync_all",      label = t("koreader.menu.sync_all"),               scopes = { avvio = true, spegnimento = true } },
    -- La meta' veloce di «Sync». All'avvio accese tutte e due: se c'e'
    -- «Sync» questa si salta (vedi _runAutomationMoment), e chi spegne
    -- «Sync» resta comunque con i libri nuovi.
    { id = "sync_books",    label = t("koreader.menu.check_new_books"),        scopes = { avvio = true } },
    { id = "check_updates", label = t("koreader.update.menu_check"),           scopes = { avvio = true } },
    { id = "pull_pos_cur",  label = t("koreader.automation.action_pull_pos"),  scopes = { apertura = true } },
    { id = "push_pos_cur",  label = t("koreader.automation.action_push_pos"),  scopes = { chiusura = true } },
    -- I dati della sessione appena chiusa (Paolo, 24/11/2026: «alla chiusura
    -- dovrebbe partire anche sync base, cosi' vengono mandati proprio i dati
    -- di quella sessione»): vedi `_mandaLaSessione`.
    { id = "sync_session",  label = t("koreader.automation.action_session"),   scopes = { chiusura = true } },
}

-- I valori predefiniti (piano del 24/11/2026, e le risposte di Paolo dello
-- stesso giorno): all'avvio e al risveglio tutto acceso; aprendo un libro si
-- scarica la sua posizione; chiudendolo si mandano la posizione e i dati di
-- quella sessione; alla sospensione — che per KOReader e' lo «spegnimento»
-- — Sync. Sul Kindle di Paolo Sync alla sospensione era acceso prima della
-- 0.30.0: 28 sessioni sul server, tutte arrivate in fondo, mediana 1 s,
-- massimo 7,6 s.
local AUTOMATION_DEFAULTS = {
    avvio = { "sync_all", "sync_books", "check_updates" },
    apertura = { "pull_pos_cur" },
    chiusura = { "push_pos_cur", "sync_session" },
    spegnimento = { "sync_all" },
}

--- L'azione si puo' fare in quel momento? Una scelta salvata che nomina
--- un'azione fuori dal suo momento non si esegue.
local function _azioneNelMomento(moment, action_id)
    for _idx, action in ipairs(AUTOMATION_ACTIONS) do
        if action.id == action_id then return action.scopes[moment] == true end
    end
    return false
end


-- Returns the list of enabled action ids for a moment — AUTOMATION_DEFAULTS
-- if the user never touched this moment's settings at all, otherwise
-- whatever was last saved (including an empty list, meaning the user
-- explicitly disabled every default action for that moment).
function Kolibre:_automationActions(moment)
    local all = G_reader_settings:readSetting(AUTOMATION_SETTING_KEY)
    if type(all) ~= "table" or all[moment] == nil then
        return AUTOMATION_DEFAULTS[moment] or {}
    end
    return all[moment]
end

function Kolibre:_isAutomationActionEnabled(moment, action_id)
    if not _azioneNelMomento(moment, action_id) then return false end
    for _idx, id in ipairs(self:_automationActions(moment)) do
        if id == action_id then return true end
    end
    return false
end

function Kolibre:_setAutomationActionEnabled(moment, action_id, enabled)
    local all = G_reader_settings:readSetting(AUTOMATION_SETTING_KEY)
    if type(all) ~= "table" then all = {} end
    local current = all[moment] or self:_automationActions(moment)
    local next_list = {}
    local found = false
    for _idx, id in ipairs(current) do
        if id == action_id then
            found = true
            if enabled then table.insert(next_list, id) end
        else
            table.insert(next_list, id)
        end
    end
    if enabled and not found then table.insert(next_list, action_id) end
    all[moment] = next_list
    G_reader_settings:saveSetting(AUTOMATION_SETTING_KEY, all)
end

function Kolibre:_syncReminderDays()
    local v = G_reader_settings:readSetting("kolibre_sync_reminder_days")
    if v == nil then return SYNC_REMINDER_DAYS_DEFAULT end
    return v
end

function Kolibre:_setSyncReminderDays(days)
    G_reader_settings:saveSetting("kolibre_sync_reminder_days", days)
end

-- **Last sync reminder** (menu della 1.0.0, piano del 24/11/2026): prende il
-- posto del promemoria del backup, che e' una fase della sincronizzazione
-- completa. La domanda giusta non e' «hai fatto il backup?» ma «hai
-- sincronizzato?»: con la sincronizzazione arrivano anche note, posizioni e
-- backup. Si guarda l'ultima sincronizzazione COMPLETA riuscita
-- (`last_sync_at` del manifesto, scritto a fine _syncNowRun).
--
-- Quanto si tace dopo un «no»: almeno quanto il periodo scelto, altrimenti
-- non e' una risposta ma un rinvio di un secondo. E quanto si tace dopo
-- AVERLO CHIESTO: aprire tre libri in dieci minuti e' una occasione sola.
local SYNC_RIFIUTO_SETTING = "kolibre_sync_reminder_declined_at"
local SYNC_CHIESTO_SETTING = "kolibre_sync_reminder_asked_at"
local SYNC_PAUSA_DOPO_AVER_CHIESTO = 6 * 3600

--- Decide se ricordare la sincronizzazione, e dice perche' no.
--
-- Funzione PURA, cosi' la regola si prova senza KOReader (vedi la prova
-- «promemoria_sync»). Torna `true` quando si deve chiedere, altrimenti
-- `false` piu' il motivo — per chi scrive la prova e chi legge il registro.
function Kolibre.decidiPromemoriaSync(stato)
    local giorni = stato.giorni_configurati or 0
    if giorni <= 0 then return false, "promemoria disattivato" end
    if not stato.raggiungibile then return false, "server non raggiungibile" end
    local adesso = stato.adesso or 0
    local chiesto = stato.chiesto_il or 0
    if chiesto > 0 and (adesso - chiesto) < (stato.pausa_dopo_aver_chiesto or SYNC_PAUSA_DOPO_AVER_CHIESTO) then
        return false, "chiesto poco fa"
    end
    local rifiutato = stato.rifiutato_il or 0
    if rifiutato > 0 and (adesso - rifiutato) < giorni * 86400 then
        return false, "rifiutato da meno di " .. tostring(giorni) .. " giorni"
    end
    local ultimo = stato.ultima_sync or 0
    if (adesso - ultimo) / 86400 < giorni then return false, "sincronizzato di recente" end
    return true, "da chiedere"
end

function Kolibre:_checkSyncReminder()
    -- La raggiungibilita' si guarda SENZA finestre (`false`): un «server non
    -- raggiungibile» all'apertura di un libro sarebbe un avviso per una
    -- cosa che nessuno ha chiesto. Senza server la domanda non si fa.
    local da_chiedere = Kolibre.decidiPromemoriaSync({
        giorni_configurati = self:_syncReminderDays(),
        raggiungibile = self:_requireReachable(false),
        adesso = os.time(),
        ultima_sync = self.manifest:getMeta("last_sync_at") or 0,
        rifiutato_il = G_reader_settings:readSetting(SYNC_RIFIUTO_SETTING) or 0,
        chiesto_il = G_reader_settings:readSetting(SYNC_CHIESTO_SETTING) or 0,
    })
    if not da_chiedere then return end

    -- Si registra di aver chiesto PRIMA di mostrare la finestra: chiuderla
    -- col tasto indietro non passa da nessuno dei due callback.
    G_reader_settings:saveSetting(SYNC_CHIESTO_SETTING, os.time())
    UIManager:show(ConfirmBox:new{
        text = t("koreader.sync_reminder.prompt", { days = self:_syncReminderDays() }),
        ok_text = t("koreader.menu.sync_all"),
        ok_callback = function() self:syncNow(true, "manual") end,
        cancel_callback = function()
            G_reader_settings:saveSetting(SYNC_RIFIUTO_SETTING, os.time())
        end,
    })
end

function Kolibre:_syncReminderMenuItems()
    local items = {}
    for _idx, days in ipairs(SYNC_REMINDER_CHOICES) do
        table.insert(items, {
            text = days == 0 and t("koreader.sync_reminder.never") or t("koreader.sync_reminder.days", { days = days }),
            checked_func = function() return self:_syncReminderDays() == days end,
            radio = true,
            callback = function() self:_setSyncReminderDays(days) end,
        })
    end
    return items
end

-- Two-level menu: moment -> checkbox list of actions applicable to that
-- moment (filtered by AUTOMATION_ACTIONS[i].scopes).
function Kolibre:_automationActionItems(moment)
    local items = {}
    for _idx, action in ipairs(AUTOMATION_ACTIONS) do
        if action.scopes[moment] then
            table.insert(items, {
                text = action.label,
                checked_func = function() return self:_isAutomationActionEnabled(moment, action.id) end,
                callback = function()
                    self:_setAutomationActionEnabled(moment, action.id, not self:_isAutomationActionEnabled(moment, action.id))
                end,
            })
        end
    end
    return items
end

function Kolibre:_automationMenuItems()
    local items = {}
    for _idx, m in ipairs(AUTOMATION_MOMENTS) do
        table.insert(items, {
            text = m.label,
            sub_item_table_func = function() return self:_automationActionItems(m.id) end,
        })
    end
    return items
end

-- ── Lifecycle hooks ──
--
-- onSuspend/onResume are broadcast globally by KOReader's core (verified in
-- frontend/device/generic/device.lua) to every registered top-level widget,
-- including this plugin's FileManager-context instance where self.ui.document
-- is nil — pushProgress/pullProgress already guard against that. Same goes
-- for onNetworkConnected (verified in frontend/ui/network/manager.lua and
-- frontend/ui/network/networklistener.lua) — _autoCheckForUpdate() already
-- guards on reachability, so it's equally safe to receive with no document
-- open.

-- ── I ritentativi dell'avvio ────────────────────────────────────────────
--
-- **Il problema** (Paolo, 04/11/2026): all'avvio di KOReader il server non e'
-- subito raggiungibile — la rete del lettore non e' ancora su, o il server di
-- casa si sta avviando. Il momento "avvio" faceva UN tentativo e rinunciava in
-- silenzio, con un guardiano che impediva di riprovare fino al riavvio
-- successivo: le azioni di avvio semplicemente non succedevano.
--
-- **Perche' quattro tentativi a quindici secondi.** Coprono 48 secondi, che e'
-- la finestra in cui un server appena accesso diventa raggiungibile. Il costo
-- e' basso solo grazie al timeout corto del controllo (3 s invece di 10 —
-- vedi `KolibreApi.TIMEOUT_CONTROLLO`): quattro tentativi falliti costano 12
-- secondi di attesa invece di 40, e uno riuscito costa zero.
--
-- **Perche' il primo non parte subito.** Partiva al `nextTick`, cioe' nel
-- momento in cui l'interfaccia si sta ancora costruendo — quello in cui la
-- rete ha MENO probabilita' di esserci, e in cui una barra di avanzamento si
-- sovrappone a un lettore che si sta aprendo.
--
-- **E perche' la rete non si aspetta qui.** Non serve: KOReader emette
-- `NetworkConnected` quando la rete arriva, e aspetta lui — il suo
-- `connectivityCheck` riprova ogni 0,25 s per 45 secondi dopo il ripristino
-- del WiFi. Il plugin ascolta quell'evento (vedi `onNetworkConnected`), e
-- questi ritentativi coprono l'altra meta' del problema: la rete c'e' ma il
-- SERVER non risponde ancora, che l'evento non sa dire.
local AVVIO_TENTATIVI_MAX = 4
local AVVIO_INTERVALLO_SECONDI = 15
local AVVIO_PRIMO_RITARDO_SECONDI = 3

--- Serve ancora riprovare l'avvio, e fra quanto?
--
-- Funzione PURA, come `decidiPromemoriaSync` e per la stessa ragione: e'
-- fatta di conteggi e di secondi, e quelle si sbagliano in silenzio. Torna i
-- secondi da aspettare prima del prossimo tentativo, oppure `nil` e il motivo
-- per cui si smette.
function Kolibre.prossimoTentativoAvvio(stato)
    if stato.riuscito then return nil, "riuscito" end
    local fatti = stato.tentativi_fatti or 0
    local massimo = stato.massimo or AVVIO_TENTATIVI_MAX
    if fatti >= massimo then return nil, "tentativi esauriti" end
    -- Il primo arriva col suo ritardo breve, i successivi con l'intervallo
    -- pieno: all'avvio si vuole dare tempo all'interfaccia di comparire, non
    -- aspettare quindici secondi prima di provarci la prima volta.
    if fatti == 0 then
        return stato.primo_ritardo or AVVIO_PRIMO_RITARDO_SECONDI, "primo tentativo"
    end
    return stato.intervallo or AVVIO_INTERVALLO_SECONDI, "ritentativo"
end

--- Prova il momento "avvio", e riprova se il server non c'era.
--
-- **Lo stato sta nel MODULO, non sull'istanza**, come il guardiano
-- `_avvio_automation_run_this_session` qui sopra e per la stessa ragione: di
-- questo plugin esistono DUE istanze nello stesso processo, una nel gestore
-- file e una nel lettore (lo dice la nota sui ganci di ciclo di vita, piu'
-- sotto). Con lo stato su `self`, i ritentativi girerebbero su un'istanza e
-- `onNetworkConnected` arriverebbe all'altra: nessuna delle due saprebbe che
-- l'altra ha gia' fatto il lavoro, e un lettore che accende il WiFi al
-- secondo venti farebbe partire due sincronizzazioni insieme.
function Kolibre:_provaAvvioConRitentativi()
    if not KolibreAvvio.puoProgrammare(avvio) then return end
    local attesa, motivo = Kolibre.prossimoTentativoAvvio({
        tentativi_fatti = avvio.tentativi,
        riuscito = avvio.concluso,
    })
    if not attesa then
        logger.info("Kolibre: avvio, non si riprova piu' (" .. tostring(motivo) .. ")")
        -- **Non si segna «concluso».** I tentativi sono finiti, ma se la rete
        -- arriva fra dieci minuti `onNetworkConnected` deve poter fare il
        -- momento: e' il caso del lettore che tiene il WiFi spento. Prima qui
        -- si metteva «concluso», e quella riga spegneva anche la terza strada.
        KolibreAvvio.rinuncia(avvio)

        -- **L'unico avviso dell'avvio**, scelto da Paolo l'08/11/2026: non
        -- «aspetto la rete», che su un e-ink sarebbe un ridisegno per una
        -- cosa che spesso si risolve da se', ma «ho smesso di provare» —
        -- l'unico momento in cui la persona ha qualcosa da fare.
        --
        -- Rispetta l'interruttore delle sincronizzazioni automatiche come
        -- tutto il resto: chi le ha zittite ha zittito anche questo, e la
        -- riga nel menu' resta la' per chi la cerca. E si dice **una volta
        -- per ogni volta che si perde la rete**: vedi
        -- `KolibreAvvio.deveAnnunciareRinuncia`.
        if self:_popupDiSincronizzazione() and KolibreAvvio.deveAnnunciareRinuncia(avvio) then
            KolibreAvvio.rinunciaAnnunciata(avvio)
            UIManager:show(InfoMessage:new{ text = t("koreader.sync.gave_up") })
        end
        return
    end
    KolibreAvvio.tentativoInCoda(avvio)
    UIManager:scheduleIn(attesa, function()
        -- Si ricontrolla qui e non solo sopra: fra la programmazione e lo
        -- scatto passano quindici secondi, e in mezzo la rete puo' essere
        -- arrivata — con `onNetworkConnected` che ha gia' fatto il lavoro.
        if avvio.concluso then
            KolibreAvvio.rinuncia(avvio)
            return
        end
        KolibreAvvio.tentativoPartito(avvio)
        -- Senza questa riga il tentativo non chiede niente alla rete quando
        -- il precedente e' fallito di colpo: vedi _dimenticaRaggiungibilita.
        self:_dimenticaRaggiungibilita()
        if self:_runAutomationMoment("avvio") then
            KolibreAvvio.riuscito(avvio)
            self:_checkPendingRestoreRequest()
        else
            self:_provaAvvioConRitentativi()
        end
    end)
end

-- Central dispatcher every hook below calls instead of ad-hoc per-moment
-- logic — one reachability check up front (not one per sub-action; the 20s
-- cache in _requireReachable would make repeats cheap anyway, but this is
-- cleaner), then runs whichever actions are enabled for this moment.
-- Torna `true` se ha potuto lavorare, `false` se il server non c'era: e' il
-- valore su cui i ritentativi dell'avvio decidono se smettere. Prima non
-- tornava niente, e chi lo chiamava non aveva modo di sapere se fosse andata.
function Kolibre:_runAutomationMoment(moment)
    if not self:_requireReachable(false) then return false end
    -- E6 (20/11/2026): dentro un momento la cartella dei libri si percorre
    -- UNA volta sola. Con push_pos_all e pull_pos_all accesi insieme la
    -- stessa camminata (un partialMD5 per file) si faceva due volte di
    -- fila, e fra le due nessuno tocca l'insieme dei file dei libri. Vedi
    -- la testa di kolibre_sync.lua.
    KolibreSync.apriSessioneScansione(self)
    local function has(action_id) return self:_isAutomationActionEnabled(moment, action_id) end
    if has("sync_all") then self:_autoFullSync("auto_" .. moment) end
    -- Solo se non si e' gia' fatto il sync completo: quello comprende questo,
    -- e farli entrambi vorrebbe dire due handshake e due sessioni sul server
    -- per lo stesso lavoro.
    if has("sync_books") and not has("sync_all") then self:_autoBooksSync("auto_" .. moment) end
    if has("push_pos_cur") then self:pushProgress(false) end
    if has("pull_pos_cur") then self:pullProgress(false) end
    if has("sync_session") then self:_mandaLaSessione() end
    if has("check_updates") then self:_autoCheckForUpdate() end
    KolibreSync.chiudiSessioneScansione(self)
    return true
end

--- I dati della sessione di lettura appena chiusa, senza tutto il resto.
--
-- **La variante leggera di Sync** (Paolo, 24/11/2026). Alla chiusura di un
-- libro devono partire i dati di quella sessione: le note e le posizioni
-- in coda, le righe nuove delle statistiche di KOReader e le righe di
-- lettura in caratteri. Non serve l'handshake, ne' i libri in arrivo, ne'
-- il backup dei file: per quelli c'e' Sync all'avvio, al risveglio e alla
-- sospensione.
--
-- **Al giro dopo, non subito.** La chiusura del libro arriva a tutti i
-- plugin, e il plugin delle statistiche di KOReader scrive le righe della
-- sessione nel suo database proprio li': se mandassimo prima di lui,
-- l'ultima pagina letta resterebbe fuori. `nextTick` viene dopo tutti.
--
-- Le statistiche partono solo se il server sa dire fin dove e' arrivato
-- (`_uploadStatsIncremental`): altrimenti il file intero lo manda la
-- prossima Sync, che e' il posto giusto per un caricamento grosso.
function Kolibre:_mandaLaSessione()
    UIManager:nextTick(function()
        if not self:_requireReachable(false) then return end
        pcall(function() self:_pushQueuedAnnotations(false) end)
        pcall(function() self:_pushQueuedPositions(false) end)
        pcall(function() self:_uploadStatsIncremental() end)
        pcall(function() self:_uploadLetture() end)
    end)
end

-- Book delivery (queued downloads/deletions) is device-wide, not tied to a
-- specific document, so it's debounced independently of the position
-- push/pull debounce — no point re-checking the delivery queue more than
-- once a minute even if open/resume fire in quick succession.
function Kolibre:_autoFullSync(trigger)
    local now = os.time()
    -- Il contatore sta in `kolibre_avvio` e non su `self`: di questo plugin
    -- esistono due istanze nello stesso processo, e un antirimbalzo su
    -- `self` non puo' fermare un doppione fra istanze diverse. Misurato
    -- sul Kindle l'08/11/2026: due `auto_avvio` a 39 secondi, con
    -- l'antirimbalzo a 60.
    if not KolibreAvvio.puoSincronizzare(avvio, now, FULL_SYNC_DEBOUNCE_SECONDS) then return end
    KolibreAvvio.sincronizzato(avvio, now)
    self:syncNow(false, trigger)
end

-- Stessa antirimbalzo del sync completo, e lo STESSO contatore: le due cose
-- chiedono al server la stessa coda di consegne, quindi un controllo libri
-- subito dopo un sync completo (avvio e risveglio possono scattare a un
-- minuto di distanza) non ha niente da trovare.
function Kolibre:_autoBooksSync(trigger)
    local now = os.time()
    if not KolibreAvvio.puoSincronizzare(avvio, now, FULL_SYNC_DEBOUNCE_SECONDS) then return end
    KolibreAvvio.sincronizzato(avvio, now)
    self:syncBooksOnly(false, trigger)
end

-- Lo stesso controllo della voce di menu', ma non chiesto da nessuno:
-- silenzioso se non c'e' niente da dire. Chi decide SE farlo e' l'azione
-- "check_updates" delle automazioni.
--
-- **Qui non c'e' piu' nessun freno, e il motivo e' un difetto.** Fino
-- all'08/11/2026 c'era un'attesa di ventiquattr'ore sul CONTROLLARE,
-- scritta nelle impostazioni *prima* di controllare. Il primo risveglio
-- della giornata controllava, non trovava niente perche' sul server non
-- c'era ancora niente, e spendeva la giornata: tutti i risvegli dopo
-- tornavano subito. Lo stesso se il controllo falliva. Paolo aveva acceso
-- l'automazione e continuava a dover controllare a mano.
--
-- Il freno e' passato dal controllare al **riproporre**, e vive in
-- `controllaAggiornamenti` — vedi kolibre_rinvii.lua. Controllare costa due
-- richieste piccole a un server che la sincronizzazione di questo stesso
-- risveglio ha appena contattato, e non ridisegna niente quando non c'e'
-- niente da dire: su e-ink e sulla batteria non si misura.
function Kolibre:_autoCheckForUpdate()
    if not self:_requireReachable(false) then return end
    self:controllaAggiornamenti(false)
end

-- Le patch da aggiornare, l'elenco e la finestra unica: trasloco del
-- 20/11/2026 (revisione A2), i corpi vivono in kolibre_aggiornamento.lua.
function Kolibre:_patchDaAggiornare(...) return KolibreAggiornamento._patchDaAggiornare(self, ...) end
Kolibre.eseguiAggiornamenti = KolibreAggiornamento.eseguiAggiornamenti
function Kolibre:_proponiTuttiGliAggiornamenti(...) return KolibreAggiornamento._proponiTuttiGliAggiornamenti(self, ...) end

-- If the freshly opened document is a Kolibre-managed book, report its real
-- on-device page count when it differs from what the manifest (and therefore
-- the server) last saw. Debounced to at most once per document opening via
-- self._pages_reported_for — onPageUpdate churn never re-triggers it.
function Kolibre:_reportOpenBookPages()
    if not self.ui.document or not self:_requireReachable(false) then return end
    local file = self.ui.document.file
    if not file or self._pages_reported_for == file then return end
    if type(self.ui.document.getPageCount) ~= "function" then return end

    local found, found_key = self.manifest:findByPath(file)
    if not found then return end
    self._pages_reported_for = file

    local ok, pages = pcall(function() return self.ui.document:getPageCount() end)
    pages = ok and tonumber(pages) or nil
    if not pages or pages <= 0 or pages == found.pages then return end

    local hash = found.hash or util.partialMD5(file)
    if not hash then return end
    local result = self.api:request("POST", "/api/kolibre/devices/pages", {
        books = { self:_withIdentity({ hash = hash, pages = pages }, file) },
    })
    if result then
        found.hash = hash
        found.pages = pages
        self.manifest:set(found_key, found, true) -- no_dirty: just reported
    end
end

function Kolibre:onReaderReady()
    self:onDispatcherRegisterActions()
    self:_checkSyncReminder()
    -- La misura delle letture: si apre il libro qui, dove `self.ui.document`
    -- c'e' per certo. La voce del manifesto porta l'impronta del file e, se il
    -- libro e' in biblioteca, biblioteca e id; un libro che il manifesto non
    -- conosce si misura comunque, con la sola impronta.
    if self.ui.document and self.ui.document.file then
        pcall(function()
            letture():apriLibro(self.ui.document, self.manifest:findByPath(self.ui.document.file))
        end)
        self:_segnaLaPaginaCorrente()
    end
    self.last_pushed_percent = nil -- new document: nothing pushed yet, so the first push isn't skipped as "unchanged"
    self.last_pushed_stato = nil   -- idem per lo stato: altrimenti quello del libro precedente farebbe da confronto
    UIManager:nextTick(function() self:_reportOpenBookPages() end)
    self:_runAutomationMoment("apertura")
end

function Kolibre:onCloseDocument()
    -- Always queued, regardless of which automation actions are enabled
    -- right now — a later manual/automatic push (from any moment, or a
    -- future session) must still see accurate state.
    if self.ui.document then
        self.manifest:markAnnotationsDirty(self.ui.document.file)
        self.manifest:markPositionDirty(self.ui.document.file)
        -- Per tornare nella sua cartella: vedi _cartellaDelLibroChiuso.
        avvio.ultimo_libro_chiuso = self.ui.document.file
    end
    -- Niente resta aperto: la pagina su cui si era fermi diventa una riga con
    -- la sua durata, e le note eventualmente aperte si chiudono prima di lei.
    pcall(function() letture():chiudiLibro() end)
    self:_runAutomationMoment("chiusura")
end

--- La pagina su cui si e' fermi adesso, per la misura delle letture.
--
-- Serve in due momenti in cui nessun cambio di pagina scatta: all'apertura
-- del libro, e al risveglio dopo una sospensione. Senza il secondo, il tempo
-- passato sulla pagina su cui ti risvegli non verrebbe misurato fino alla
-- girata successiva — e su un Kindle, che si sospende a ogni pausa, sarebbe
-- la maggior parte del tempo di lettura.
function Kolibre:_segnaLaPaginaCorrente()
    local doc = self.ui and self.ui.document
    if not doc then return end
    pcall(function()
        local pagina = self.last_page
        if type(doc.getCurrentPage) == "function" then
            local ok, p = pcall(doc.getCurrentPage, doc)
            if ok and tonumber(p) then pagina = tonumber(p) end
        end
        if pagina then letture():segnaPagina(doc, pagina) end
    end)
end

function Kolibre:onPageUpdate(page)
    if page == nil or not self.ui.document or page == self.last_page then return end
    self.last_page = page
    -- La misura delle letture, prima di qualunque altra cosa e fuori da ogni
    -- interruttore delle automazioni: quelle decidono se e quando PARLARE col
    -- server, questa e' una misura locale che finisce in un file, e una
    -- lettura non misurata non si recupera.
    pcall(function() letture():segnaPagina(self.ui.document, page) end)
    -- Periodic autosave while reading, independent of the close/suspend
    -- moments themselves — gated on the same action id ("push_pos_cur") a
    -- user would enable at chiusura, since that's what this is proactively
    -- doing every PAGES_BEFORE_AUTO_PUSH pages instead of waiting for close.
    if not self:_isAutomationActionEnabled("chiusura", "push_pos_cur") then return end
    self.page_update_counter = (self.page_update_counter or 0) + 1
    if self.page_update_counter >= PAGES_BEFORE_AUTO_PUSH then
        self.page_update_counter = 0
        self:pushProgress(false)
    end
end

--- In modalita' scorrimento le pagine non "cambiano": cambia la posizione.
--
-- Senza questo aggancio, chi legge a scorrimento continuo non verrebbe
-- misurato affatto: `onPageUpdate` non scatta mai. E' l'unica cosa che la
-- userpatch faceva e che il plugin non faceva gia'.
function Kolibre:onPosUpdate(_posizione)
    if not self.ui.document then return end
    self:_segnaLaPaginaCorrente()
end

function Kolibre:onSuspend()
    if self.ui.document then
        self.manifest:markAnnotationsDirty(self.ui.document.file)
        self.manifest:markPositionDirty(self.ui.document.file)
    end
    -- La pagina aperta si chiude QUI e non al risveglio: un libro lasciato
    -- aperto la notte darebbe altrimenti una pagina da dieci ore. Il libro
    -- invece resta aperto, perche' al risveglio si sta ancora leggendo quello.
    pcall(function() letture():chiudiLaPagina() end)
    self:_runAutomationMoment("spegnimento")
    -- **Il prossimo risveglio e' un avvio nuovo.** Era la riga che mancava:
    -- senza, lo stato «avvio concluso» restava vero per tutta la vita del
    -- processo — e su un Kindle KOReader non si riavvia, si sospende, quindi
    -- erano settimane. Vedi la testa di `kolibre_avvio.lua`.
    KolibreAvvio.sospeso(avvio)
end

function Kolibre:onResume()
    -- Il controllo degli aggiornamenti non si chiama piu' qui: adesso e'
    -- un'azione del momento "avvio", che questa riga esegue gia'.
    --
    -- E il momento si fa **con i ritentativi**, non una volta sola: nell'
    -- istante esatto del risveglio il WiFi non e' ancora su, ed e' il caso
    -- normale su un lettore, non l'eccezione. Prima qui il momento si
    -- eseguiva diretto, senza passare dai ritentativi: un tentativo, nel
    -- momento peggiore, e nessun altro.
    --
    -- La risposta ricordata sulla raggiungibilita' si butta via, come fanno
    -- le altre due strade: quella in memoria e' di prima della sospensione.
    self:_dimenticaRaggiungibilita()
    self:_provaAvvioConRitentativi()
    self:_checkPendingRestoreRequest()
    -- Si riapre la riga della pagina su cui ci si risveglia: la chiusura
    -- l'ha scritta allo spegnimento, e senza questa il tempo di lettura dopo
    -- il risveglio non esisterebbe fino alla girata successiva.
    self:_segnaLaPaginaCorrente()
end

-- Broadcast by KOReader core (frontend/ui/network/manager.lua) whenever wifi
-- comes up, including right after boot if it was already on — confirmed
-- against the real event name/handler convention used by stock plugins
-- (e.g. autosuspend.koplugin's own onNetworkConnected). This is the moment a
-- device that keeps wifi off between syncs actually has a connection to
-- check with, so it's the main trigger for the background update check.
function Kolibre:onNetworkConnected()
    -- La rete che torna non e' uno dei quattro momenti delle automazioni, ma
    -- e' lo stesso momento di "avvio" visto da un'altra parte: un lettore che
    -- tiene il wifi spento fra due sincronizzazioni si sveglia senza rete, e
    -- la rete arriva dopo. Quindi si fa **tutto** il momento "avvio",
    -- rispettando le scelte dell'utente azione per azione — che e' quello che
    -- `_runAutomationMoment` fa gia'.
    --
    -- Fino al 04/11/2026 qui si rifaceva **una sola** delle otto azioni, il
    -- controllo aggiornamenti: il ragionamento era giusto («se ha spento il
    -- controllo all'avvio, qui non si fa») ma applicato a un'azione su otto.
    -- Un lettore acceso senza rete non sincronizzava, non mandava le note e
    -- non faceva il backup fino al riavvio successivo.
    --
    -- Solo se l'avvio non e' ancora riuscito: a rete gia' su il momento
    -- "avvio" l'ha fatto `_provaAvvioConRitentativi`, e rifarlo qui vorrebbe
    -- dire due sincronizzazioni per lo stesso risveglio. Il debounce di
    -- `_autoFullSync` ne fermerebbe comunque una, ma contare su un debounce
    -- per non fare due volte una cosa e' diverso dal non farla due volte.
    if KolibreAvvio.reteDeveProvare(avvio) then
        -- A maggior ragione qui: la risposta ricordata e' stata data pochi
        -- secondi prima, quando la rete non c'era, ed e' proprio quella
        -- sbagliata nel momento in cui la rete e' appena tornata.
        self:_dimenticaRaggiungibilita()
        if self:_runAutomationMoment("avvio") then
            KolibreAvvio.riuscito(avvio)
        end
    end
    self:_checkPendingRestoreRequest()
end

function Kolibre:onDispatcherRegisterActions()
    Dispatcher:registerAction("kolibre_push_progress", {
        category = "none", event = "KolibrePushProgress", title = t("koreader.dispatcher.push_progress"), reader = true,
    })
    Dispatcher:registerAction("kolibre_pull_progress", {
        category = "none", event = "KolibrePullProgress", title = t("koreader.dispatcher.pull_progress"), reader = true,
    })
end

function Kolibre:onKolibrePushProgress() self:pushProgress(true) end
function Kolibre:onKolibrePullProgress() self:pullProgress(true) end

return Kolibre
