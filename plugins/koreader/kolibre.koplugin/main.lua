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
same bar format as the plugin of KoServer (an earlier project of mine), explicitly
matched on request. Downloaded files no longer get "(<calibre_id>)" stuffed
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
local DocSettings      = require("docsettings")
local t                = require("kolibre_lingua").t

local KolibreApi = require("kolibre_api")
local KolibreManifest = require("kolibre_manifest")
local KolibreMenuPin = require("kolibre_menu_pin")
local KolibreCatalog = require("kolibre_catalog")
local KolibreCapabilities = require("kolibre_capabilities")

local VERSION = "0.6.16"
local EBOOK_EXTENSIONS = { epub = true, pdf = true, mobi = true, azw3 = true, fb2 = true, txt = true }

-- Set once _resumePendingUpdate has run for this KOReader process (see
-- init()) — a file-level local, not a self field, so it's shared by every
-- Kolibre instance created from this same loaded module.
local _resume_checked_this_session = false

-- Same reasoning, for the "avvio" automation moment: init() runs once per
-- FileManager instance AND once per ReaderUI instance, but a cold-start
-- automation should still fire only once per KOReader process.
local _avvio_automation_run_this_session = false

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
    local candidates = {
        "/mnt/us/documents",  -- Kindle
        "/sdcard/Books",      -- Android
        "/mnt/ext1/Books",    -- PocketBook
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

    -- "All'avvio" automation moment — same once-per-process guard as the
    -- resume check above. Deferred with nextTick so it never delays this
    -- init() call itself (both FileManager and ReaderUI construct plenty of
    -- other UI right after this).
    if not _avvio_automation_run_this_session then
        _avvio_automation_run_this_session = true
        UIManager:nextTick(function() self:_runAutomationMoment("avvio") end)
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

-- Menu redesign (v0.6.9, to make the feature itself and its options menu
-- more intuitive to navigate): the previous structure had 7 top-level
-- entries, several of which (Lettura, Backup, Automazioni, and
-- Impostazioni ▸ Avanzate) are one-shot/rare manual
-- actions a user reaches for occasionally, not a daily menu to scan. Only
-- "Sincronizza tutto" and "Catalogo" are genuinely used every day. Flattened
-- to 4 top-level entries: the two daily ones stay put, everything else
-- (manual overrides, backup, automations, diagnostics) is consolidated
-- under one "Strumenti" with separators grouping related actions, and Info
-- moved into the bottom of Impostazioni instead of its own top-level row.
function Kolibre:addToMainMenu(menu_items)
    menu_items.kolibre = {
        text = t("koreader.menu.title"),
        sorting_hint = "tools",
        sub_item_table = {
            {
                -- Renamed from "Sincronizza ora": now also pushes queued
                -- annotations/positions and runs a backup, and asks
                -- confirmation for pending downloads too, not just
                -- deletions — see syncNow/_syncNowRun/_confirmDownloads.
                text = t("koreader.menu.sync_all"),
                icon = "sync",
                keep_menu_open = true,
                callback = function() self:syncNow(true, "manual") end,
            },
            {
                -- La meta' veloce: solo i libri in arrivo e in uscita.
                -- Sta fra le voci di tutti i giorni e non sotto "Strumenti"
                -- perche' e' la domanda che ci si fa piu' spesso accendendo
                -- il lettore — "c'e' qualcosa di nuovo?" — e perche' e'
                -- anche l'automazione predefinita all'avvio: chi la trova
                -- gia' fatta deve poterla rifare a mano senza cercarla.
                text = t("koreader.menu.check_new_books"),
                keep_menu_open = true,
                callback = function() self:syncBooksOnly(true, "manual_libri") end,
            },
            {
                -- Opens the catalog dashboard (Aggiunti di recente / Da
                -- scoprire / Sfoglia la libreria) — see openCatalogDashboard.
                text = t("koreader.menu.catalog"),
                keep_menu_open = true,
                callback = function() self:openCatalogDashboard() end,
            },
            {
                text = t("koreader.menu.tools"),
                sub_item_table_func = function() return self:_toolsMenuItems() end,
            },
            {
                text = t("koreader.menu.settings"),
                sub_item_table = {
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
                        text = t("koreader.settings.check_update"),
                        keep_menu_open = true,
                        callback = function() self:checkForUpdate(true) end,
                    },
                    {
                        text = t("koreader.settings.info", { version = VERSION }),
                        keep_menu_open = true,
                        callback = function() self:showInfo() end,
                    },
                },
            },
        },
    }
end

-- Everything that used to be spread across the old top-level "Lettura",
-- "Backup", "Automazioni" and "Impostazioni ▸ Avanzate" entries — manual
-- overrides and one-shot/diagnostic actions, grouped here (not merged flat
-- into a single list) so related actions still read as a set: posizione di
-- lettura, poi annotazioni, poi backup, poi automazioni, poi diagnostica.
-- A function (not a static table) for the same reason _automationMenuItems/
-- _backupReminderMenuItems already are: enabled_func below needs to
-- re-evaluate self.ui.document freshly every time this submenu opens.
function Kolibre:_toolsMenuItems()
    local items = {
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
        },
        {
            -- Unlike the two above (scoped to the open book), this walks
            -- every book on the device using its sidecar directly — no need
            -- to open each one.
            text = t("koreader.position.sync_all"),
            keep_menu_open = true,
            callback = function() self:syncAllProgress(true) end,
        },
    }
    items[#items].separator = true
    table.insert(items, {
        -- The ONLY way to trigger the exhaustive books_dir rescan since
        -- v0.5.14 — "Sincronizza tutto" itself always uses the cheap
        -- queue-only push (see _syncNowRun's own Fase 6 comment). Use this
        -- after pairing a book that was already highlighted, or on a
        -- device whose dirty-queue predates this plugin version —
        -- everyday use should never need it, "Sincronizza tutto" already
        -- covers that.
        text = t("koreader.annotations.push_all_full"),
        keep_menu_open = true,
        callback = function() self:pushAllAnnotationsFull(true) end,
    })
    items[#items].separator = true
    table.insert(items, {
        text = t("koreader.backup.run_now"),
        keep_menu_open = true,
        callback = function() self:backupNow(true) end,
    })
    table.insert(items, {
        text = t("koreader.backup.reminder_menu"),
        sub_item_table_func = function() return self:_backupReminderMenuItems() end,
    })
    items[#items].separator = true
    table.insert(items, {
        -- Un solo dizionario oggi (italiano) — vedi stardict_service.py's
        -- KNOWN_DICTIONARIES; quando ne esisterà più di uno, questa voce
        -- diventa un sub_item_table_func con una riga per lingua.
        text = t("koreader.dictionary.download_menu"),
        keep_menu_open = true,
        callback = function() self:downloadDictionary("it", true) end,
    })
    items[#items].separator = true
    table.insert(items, {
        text = t("koreader.menu.automations"),
        sub_item_table_func = function() return self:_automationMenuItems() end,
    })
    items[#items].separator = true
    table.insert(items, {
        -- Retained from the old "Impostazioni ▸ Avanzate" — a diagnostic
        -- view, not something reached often enough to deserve its own
        -- top-level entry.
        text = t("koreader.managed_books.menu_title"),
        keep_menu_open = true,
        callback = function() self:showManagedBooks() end,
    })
    table.insert(items, {
        text = t("koreader.library_init.menu"),
        keep_menu_open = true,
        callback = function() self:initLibrary() end,
    })
    table.insert(items, {
        text = t("koreader.restore.menu"),
        keep_menu_open = true,
        callback = function() self:_startDeviceRestore() end,
    })
    return items
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

-- ── Managed books list ──
--
-- Shows the manifest (the books Kolibre delivered to this device). Removing
-- a book from here deletes file + sidecar + history locally but deliberately
-- KEEPS the manifest entry and makes NO server call: the next sync's
-- existence pass will find the file gone and report it in missing_books —
-- one honest code path for "this book left the device" instead of a second
-- ad-hoc server notification that could race with a running sync.

function Kolibre:showManagedBooks()
    local books = self.manifest:all()
    local items = {}
    for key, entry in pairs(books) do
        local title = entry.title or (entry.path and entry.path:match("([^/]+)$")) or key
        table.insert(items, {
            text = string.format("%s (%s)", title, entry.format or "?"),
            mandatory = entry.pages and t("koreader.managed_books.pages_count", { count = entry.pages }) or "",
            callback = function() self:_showManagedBookDialog(key, entry, title) end,
        })
    end
    if #items == 0 then
        UIManager:show(InfoMessage:new{ text = t("koreader.managed_books.empty") })
        return
    end
    table.sort(items, function(a, b) return a.text < b.text end)
    self._managed_books_menu = Menu:new{
        title = t("koreader.managed_books.menu_title"),
        subtitle = t("koreader.common.book_count", { count = #items }),
        item_table = items,
        is_popout = true,
        is_borderless = false,
    }
    UIManager:show(self._managed_books_menu)
end

function Kolibre:_showManagedBookDialog(key, entry, title)
    local details = {
        t("koreader.managed_books.detail_title", { value = tostring(title) }),
    }
    if entry.author then table.insert(details, t("koreader.managed_books.detail_author", { value = tostring(entry.author) })) end
    table.insert(details, t("koreader.managed_books.detail_format", { value = tostring(entry.format or "?") }))
    if entry.pages then table.insert(details, t("koreader.managed_books.detail_pages", { value = tostring(entry.pages) })) end
    if entry.downloaded_at then
        table.insert(details, t("koreader.managed_books.detail_downloaded_at", { value = os.date("%Y-%m-%d %H:%M", entry.downloaded_at) }))
    end
    table.insert(details, t("koreader.managed_books.detail_file", { value = tostring(entry.path or "?") }))
    UIManager:show(ConfirmBox:new{
        text = table.concat(details, "\n"),
        ok_text = t("koreader.managed_books.remove_confirm_ok"),
        cancel_text = t("koreader.common.close"),
        ok_callback = function()
            -- keep_manifest_entry: see showManagedBooks — missing_books at
            -- the next sync is what tells the server, not an immediate call.
            local ok, err = self:_deleteManagedBook(entry.path, { keep_manifest_entry = true })
            if ok then
                UIManager:show(InfoMessage:new{
                    text = t("koreader.managed_books.removed_notice"),
                    timeout = 3,
                })
                if self._managed_books_menu then
                    UIManager:close(self._managed_books_menu)
                    self._managed_books_menu = nil
                end
            else
                UIManager:show(InfoMessage:new{ text = t("koreader.managed_books.remove_failed", { error = tostring(err) }) })
            end
        end,
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
    local result, err = self.api:request("GET", "/api/devices/me")
    if not result then
        UIManager:show(InfoMessage:new{ text = t("koreader.settings.test_failed", { error = tostring(err) }) })
        return
    end
    -- A successful manual probe is exactly the same one _isReachable would
    -- make — warm its cache instead of throwing this result away.
    self._reachable_checked_at, self._reachable_cached, self._reachable_cached_err = os.time(), true, nil
    UIManager:show(InfoMessage:new{ text = t("koreader.settings.test_ok", { name = tostring(result.name) }) })
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
    local result, err = self.api:request("GET", "/api/devices/me")
    self._reachable_checked_at = now
    self._reachable_cached = result ~= nil
    self._reachable_cached_err = err
    return self._reachable_cached, err
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
-- KOReader plugin of KoServer, an earlier unreleased project of my own (its
-- syncAll) — reused on purpose, not designed from scratch. `current` is
-- 1-based (the bar shows how far in you are BEFORE this step runs, as in
-- KoServer), reusing
-- the existing _showProgress InfoMessage-reuse mechanic underneath.
function Kolibre:_showProgressBar(current, total, label)
    local n = math.max(total, 1)
    local filled = math.floor((current - 1) / n * 10)
    self:_showProgress(string.format("[%s%s] %d%% - %s...",
        string.rep("=", filled), string.rep("-", 10 - filled),
        math.floor((current - 1) / n * 100), label))
end

-- ── Local library scan ──

-- Walks self.books_dir (one level of subfolders, matching a typical
-- Author/Title layout, plus files directly in the root) and returns a flat
-- list of {path, format, hash}. Uses KOReader's own util.partialMD5, the
-- exact same hash the server computes server-side for the same file.
-- on_progress(count), if given, is called every few files so the caller can
-- keep the UI honest — this walk can take minutes on a device with many
-- books, and gives no other sign of life.
function Kolibre:_scanLocalBooks(on_progress)
    local found = {}
    local scanned = 0

    local function scanDir(dir, depth)
        local ok, iter, dir_obj = pcall(lfs.dir, dir)
        if not ok or not iter then return end
        for entry in iter, dir_obj do
            -- "._Foo.epub" is an AppleDouble resource-fork stub Finder
            -- writes alongside every real file when copying to the device
            -- over USB — zero-byte, not a book, but has an ebook extension
            -- and used to get flagged as an unmatched "no_candidate" like a
            -- real missing book (confirmed: ~43% of one real device's
            -- flagged list was exactly this, not an actual matching gap).
            if entry ~= "." and entry ~= ".." and entry:sub(1, 2) ~= "._" then
                local full_path = dir .. "/" .. entry
                local mode = lfs.attributes(full_path, "mode")
                if mode == "directory" and depth < 2 then
                    scanDir(full_path, depth + 1)
                elseif mode == "file" then
                    local ext = entry:match("%.([%a%d]+)$")
                    if ext and EBOOK_EXTENSIONS[ext:lower()] then
                        local hash = util.partialMD5(full_path)
                        if hash then
                            table.insert(found, { path = full_path, format = ext:upper(), hash = hash })
                        end
                        scanned = scanned + 1
                        if on_progress and scanned % 15 == 0 then
                            on_progress(scanned)
                        end
                    end
                end
            end
        end
    end

    scanDir(self.books_dir, 0)
    return found
end

-- ── On-device book layout ──
--
-- Purely a filesystem convention on the device's own storage — unrelated to
-- the server-side Calibre library, which the server always keeps in its own
-- one-folder-per-book layout. The server tells us which layout to use (and
-- whether to drop a per-author .folder.jpg) via the sync handshake's
-- `settings`, itself set from the device's own settings in the web UI.

local function sanitizeFilename(name)
    if not name or name == "" then return "Sconosciuto" end
    return (name:gsub('[\\/:%*%?"<>|]', "_"))
end

-- lfs.mkdir isn't recursive; build the path one segment at a time.
local function ensureDir(path)
    if lfs.attributes(path, "mode") == "directory" then return true end
    local built = ""
    for segment in path:gmatch("[^/]+") do
        built = built .. "/" .. segment
        if lfs.attributes(built, "mode") ~= "directory" then
            lfs.mkdir(built)
        end
    end
    return lfs.attributes(path, "mode") == "directory"
end

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

local function urlEncode(str)
    return (str:gsub("[^%w%-%.%_%~]", function(c) return string.format("%%%02X", c:byte()) end))
end

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

function Kolibre:_downloadCatalogBook(book, library)
    local formats = book.formats or {}
    local fmt = formats[1] or "EPUB"
    local target_dir = self.books_dir
    if (self.folder_layout or "author") == "author" and book.author and book.author ~= "" then
        target_dir = self.books_dir .. "/" .. sanitizeFilename(book.author)
    end
    ensureDir(target_dir)
    self:_ensureAuthorFolderCover(book.author, target_dir)

    local title = sanitizeFilename(book.title or string.format("libro_%d", book.id))
    local filename = string.format("%s.%s", title, fmt:lower())
    local local_path = target_dir .. "/" .. filename
    local url = string.format("/api/kolibre/books/%d/download?library=%s&format=%s", book.id, library, fmt)

    local ok, err = self.api:downloadTo(url, local_path)
    if ok then
        -- Device-initiated acquisition: record it in the manifest (Kolibre
        -- now manages this book) and tell the server to start tracking it.
        -- If /books/delivered fails, the dirty manifest makes the next sync's
        -- managed_books report deliver the same information.
        local hash = util.partialMD5(local_path)
        self.manifest:set(KolibreManifest.bookKey(library, book.id, fmt), {
            path = local_path,
            hash = hash,
            title = book.title,
            author = book.author,
            library = library,
            calibre_book_id = book.id,
            format = fmt:upper(),
            downloaded_at = os.time(),
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
    end

    loadPage(1)
end

-- Resolves which server library to browse (auto-picks the only one, or
-- shows a picker when there's more than one) and hands it to `on_library`.
-- Reused by openCatalogDashboard, the Browser menu's "Cambia libreria", and
-- the catalog-menu search entry (Wave C) instead of each duplicating it.
function Kolibre:_withCatalogLibrary(on_library)
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
end

-- "Catalogo" top-level entry (addToMainMenu) — a small home screen instead
-- of jumping straight into the flat catalog Menu (that's now one of three
-- destinations from here, "Sfoglia la libreria" ▸ "Tutti i libri").
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

-- ── Device initialization: "cerca libri non accoppiati" ──
--
-- Secondary, rarely-used feature (Impostazioni ▸ Avanzate only, never the
-- main menu) that reconciles books already on the device's storage that
-- Kolibre doesn't yet manage (side-loaded before Kolibre was set up, or
-- moved onto the device by another tool). Every decision below is made
-- automatically — never a per-book prompt — so this stays usable with
-- dozens of unmanaged books instead of turning into a click-marathon:
--   * hash-identical to a server book -> one batch confirm, then adopted
--     into the manifest exactly like the legacy v0.2.0 migration path;
--   * fuzzy title/author match found (via the catalog's own search), file
--     never opened (no annotations, no reading progress in its sidecar) ->
--     one batch confirm to overwrite with the Kolibre copy — safe, since
--     there's no local reading data to lose;
--   * fuzzy match found but the file has progress/annotations -> NEVER
--     touched or auto-linked; silently parked in a server-side "review"
--     list (visible on the web UI) so the user can resolve it later instead of
--     risking corrupting notes tied to a possibly-different text;
--   * no match at all -> listed for one-by-one local deletion, or left
--     alone.

-- Best-effort search query from a bare filename: strips the extension and
-- the "(<id>)" suffix Kolibre's own downloads add (_downloadCatalogBook),
-- since a book Kolibre itself delivered would already be hash-matched and
-- never reach this fallback — this path is for files Kolibre never touched.
--
-- If the filename splits on " - " (Calibre/Kindle's own "Title - Author"
-- convention — same pattern _guessAuthorFromPath below reads the author
-- from), only the portion BEFORE it is the title guess. Confirmed as a real
-- bug, not hypothetical: without this, "Il titolo del libro - Nome
-- Cognome.epub" guessed a title of "Il titolo del libro   Nome
-- Cognome" (hyphen just turned into spaces) — a string that is a
-- substring of neither the real title NOR the real author, so BOTH the
-- catalog's AND-tightened match and its OR-fallback (browse_catalog) failed
-- and the book was flagged "no_candidate" even though it was already in the
-- library under an unambiguous, correctly-spelled title.
local function _guessTitleFromPath(path)
    local filename = path:match("([^/]+)$") or path
    local name = filename:gsub("%.[%a%d]+$", "")
    name = name:gsub("%s*%(%d+%)%s*$", "")
    local title_only = name:match("^(.-)%s+%-%s+.+$")
    name = (title_only and title_only ~= "") and title_only or name:gsub("[_%-]", " ")
    return (name:gsub("^%s+", ""):gsub("%s+$", ""))
end

-- Best-effort AUTHOR guess, separate from the title guess above: a single
-- needle built from the WHOLE filename (title+author mashed together) is
-- usually a substring of neither the title field nor the author field
-- alone, which is why fuzzy matching used to fail even on well-formed
-- filenames. If the filename splits on " - " (Calibre's own "Title -
-- Author" save-to-disk template, also common on Kindle), the segment after
-- it is tried as the author — order is genuinely ambiguous from a filename
-- alone, but the backend's catalog search (browse_catalog's `author` param)
-- already falls back to the old single-field OR match when this guess
-- turns out backwards, so a second attempt at the other order isn't needed.
--
-- If there's no " - " to split on, falls back to the immediate parent
-- folder name — the OTHER common on-device layout (this plugin's own
-- "author" folder_layout, see _syncBook below) is
-- <books_dir>/<Author>/<title_sort>.epub, where the author never appears in
-- the filename at all. Confirmed as a real, dominant cause of "no_candidate"
-- on a real device: without this, EVERY book copied under that layout sent
-- author=nil to browse_catalog, which combined with the query needle missing
-- the author entirely was consistently enough to push otherwise-obvious
-- matches (e.g. "Titolo, Il" / "Nome Cognome") just under the fuzzy threshold.
-- Never returns books_dir's own name (a file sitting loose at the root has
-- no author folder to guess from).
function Kolibre:_guessAuthorFromPath(path)
    local filename = path:match("([^/]+)$") or path
    local name = filename:gsub("%.[%a%d]+$", "")
    name = name:gsub("%s*%(%d+%)%s*$", "")
    local _title, author = name:match("^(.-)%s+%-%s+(.+)$")
    if author and author ~= "" then
        return (author:gsub("^%s+", ""):gsub("%s+$", ""))
    end
    local parent_dir = path:match("^(.*)/[^/]+$")
    if not parent_dir or parent_dir == "" or parent_dir == self.books_dir then return nil end
    local folder_name = parent_dir:match("([^/]+)$")
    if not folder_name or folder_name == "" then return nil end
    return folder_name
end

-- "Never opened" = safe to overwrite outright: no highlights/notes and no
-- reading-progress marker anywhere in the sidecar. Deliberately cautious in
-- the direction of NOT overwriting — summary.status is set to "reading" the
-- moment a book is merely opened once (see KOReader's own readerui.lua), so
-- even a book opened just to peek at it is correctly treated as "started".
function Kolibre:_looksNeverOpened(file_path)
    if not DocSettings:hasSidecarFile(file_path) then return true end
    local ok, doc_settings = pcall(function() return DocSettings:open(file_path) end)
    if not ok or not doc_settings then return true end
    local annotations = doc_settings:readSetting("annotations")
    if type(annotations) == "table" and #annotations > 0 then return false end
    local percent = doc_settings:readSetting("percent_finished")
    if type(percent) == "number" and percent > 0 then return false end
    local summary = doc_settings:readSetting("summary")
    if type(summary) == "table" and summary.status and summary.status ~= "" then return false end
    return true
end

-- Same sidecar fields _looksNeverOpened checks, but returned as actual
-- numbers instead of a boolean — powers the web UI's "Da rivedere" page
-- explanation of WHY a flagged_started entry wasn't touched (e.g. "42%
-- letto, 3 note") instead of just "già iniziato" with no detail.
function Kolibre:_readLocalReviewReason(file_path)
    if not DocSettings:hasSidecarFile(file_path) then return nil, nil end
    local ok, doc_settings = pcall(function() return DocSettings:open(file_path) end)
    if not ok or not doc_settings then return nil, nil end
    local annotations = doc_settings:readSetting("annotations")
    local highlights_count = (type(annotations) == "table") and #annotations or 0
    local percent = doc_settings:readSetting("percent_finished")
    local percent_read = (type(percent) == "number") and percent or nil
    return percent_read, highlights_count
end

-- Searches EVERY library the device can see (catalog's own q= filter,
-- reused as-is) and returns one candidate per library that had a hit — never
-- just the first, since the same title can legitimately exist in more than
-- one library and picking one silently would be exactly the "quale
-- biblioteca?" guess the user must make, not the plugin.
function Kolibre:_findProbableCatalogMatches(query, author)
    if not query or query == "" then return {} end
    local libraries = self.api:request("GET", "/api/kolibre/devices/libraries")
    if not libraries then return {} end
    local found = {}
    for _idx, lib in ipairs(libraries) do
        local path = "/api/kolibre/devices/catalog?library=" .. urlEncode(lib.library) .. "&q=" .. urlEncode(query)
        if author and author ~= "" then
            path = path .. "&author=" .. urlEncode(author)
        end
        local result = self.api:request("GET", path)
        if result and result.books and result.books[1] then
            local b = result.books[1]
            table.insert(found, { id = b.id, title = b.title, author = b.author, formats = b.formats, library = lib.library, source = "fuzzy" })
        end
    end
    return found
end

-- Extensions the server can actually fingerprint (text_fingerprint.py,
-- epub/fb2/txt — zip/XML/plain-text, cheap to parse). pdf/mobi/azw3 need a
-- real binary-format parser the server doesn't have either, an explicit and
-- accepted limit, not a silent gap: those extensions fall straight through
-- to the fuzzy title/author search below, unchanged.
local CONTENT_FINGERPRINT_EXTENSIONS = { epub = true, fb2 = true, txt = true }

-- Authoritative identity check for a device file the filename/folder guess
-- can't reliably place: KOReader has no way to read inside a zip/EPUB
-- itself (confirmed: no such library exists anywhere in this plugin or
-- reusable from KOReader's own bundled Lua libs), so the file is uploaded
-- whole to the server, which already has zip/OPF-parsing code (TOC editor,
-- page counter) and computes a content fingerprint there instead. Returns a
-- candidate in the exact same shape _findProbableCatalogMatches returns
-- (id/title/author/formats/library), or nil if unsupported/no match — the
-- caller falls back to that fuzzy search exactly as before in either case.
function Kolibre:_identifyFileByContent(path)
    local ext = path:match("%.([%a%d]+)$")
    if not ext or not CONTENT_FINGERPRINT_EXTENSIONS[ext:lower()] then return nil end
    local filename = path:match("([^/]+)$") or path
    local url = "/api/kolibre/devices/identify-file?filename=" .. urlEncode(filename)
    local result = self.api:uploadFileForJson(url, path)
    if not result or not result.matched then return nil end
    return {
        id = result.id, title = result.title, author = result.author, formats = result.formats,
        library = result.library, source = "fingerprint",
    }
end

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

function Kolibre:initLibrary()
    if not self:_requireReachable(true) then return end
    UIManager:show(ConfirmBox:new{
        text = t("koreader.library_init.confirm"),
        ok_text = t("koreader.common.start"),
        ok_callback = function() self:_runLibraryInit() end,
    })
end

function Kolibre:_runLibraryInit()
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
        UIManager:show(InfoMessage:new{ text = t("koreader.library_init.nothing_new") })
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

-- Links one hash-identical match into the manifest under its real
-- server-provided identity (unlike the legacy "hash:*" migration entries).
function Kolibre:_linkHashMatch(m, candidate)
    local key = KolibreManifest.bookKey(candidate.library, candidate.calibre_book_id, m.format)
    self.manifest:set(key, {
        path = m.path, hash = m.hash, title = candidate.title, author = candidate.author,
        library = candidate.library, calibre_book_id = candidate.calibre_book_id,
        format = m.format, downloaded_at = os.time(),
    })
end

-- Step 1: hash-identical matches. The exact same file can legitimately be
-- hashed under more than one library (the same book uploaded to two
-- libraries) — /scan-unmatched reports every library that resolved the
-- hash, never picks one on the plugin's behalf. Matches with exactly one
-- candidate get a single BATCH confirm (zero-risk, byte-identical file);
-- matches with more than one candidate need an explicit per-book choice of
-- which library to reference.
function Kolibre:_confirmHashMatches(matched, unmatched)
    local single, multi = {}, {}
    for _idx, m in ipairs(matched) do
        local candidates = m.candidates or {}
        if #candidates > 1 then
            table.insert(multi, m)
        elseif #candidates == 1 then
            table.insert(single, m)
        end
    end
    self:_resolveMultiLibraryHashMatches(multi, 1, function()
        self:_confirmSingleLibraryHashMatches(single, unmatched)
    end)
end

-- One book at a time: "questo file è identico a un libro presente in più
-- biblioteche, quale usiamo?" — never guessed automatically.
function Kolibre:_resolveMultiLibraryHashMatches(multi, idx, done)
    if idx > #multi then
        done()
        return
    end
    local m = multi[idx]
    local items = {}
    for _cidx, c in ipairs(m.candidates) do
        table.insert(items, {
            text = string.format("%s — %s", c.title or "?", c.library),
            callback = function()
                if self._multi_match_menu then UIManager:close(self._multi_match_menu) end
                self:_linkHashMatch(m, c)
                self:_resolveMultiLibraryHashMatches(multi, idx + 1, done)
            end,
        })
    end
    table.insert(items, {
        text = t("koreader.library_init.skip_for_now"),
        callback = function()
            if self._multi_match_menu then UIManager:close(self._multi_match_menu) end
            self:_resolveMultiLibraryHashMatches(multi, idx + 1, done)
        end,
    })
    self._multi_match_menu = Menu:new{
        title = t("koreader.library_init.multi_library_title", { name = m.path:match("([^/]+)$") or m.path }),
        subtitle = t("koreader.library_init.which_library"),
        item_table = items,
        is_popout = true,
        is_borderless = false,
    }
    UIManager:show(self._multi_match_menu)
end

function Kolibre:_confirmSingleLibraryHashMatches(single, unmatched)
    if #single == 0 then
        self:_searchUnmatched(unmatched)
        return
    end
    local names = {}
    for _idx, m in ipairs(single) do
        local c = m.candidates[1]
        table.insert(names, string.format("• %s (%s)", c.title or m.path:match("([^/]+)$") or m.path, c.library))
    end
    UIManager:show(ConfirmBox:new{
        text = t("koreader.library_init.hash_match_confirm", {
            count = #single, list = table.concat(names, "\n"),
        }),
        ok_text = t("koreader.common.link"),
        cancel_text = t("koreader.common.ignore"),
        ok_callback = function()
            for _idx, m in ipairs(single) do
                self:_linkHashMatch(m, m.candidates[1])
            end
            UIManager:show(InfoMessage:new{
                text = t("koreader.library_init.hash_linked", { count = #single }),
                timeout = 4,
            })
            self:_searchUnmatched(unmatched)
        end,
        cancel_callback = function() self:_searchUnmatched(unmatched) end,
    })
end

-- Step 2: for every hash-unmatched file, try a fuzzy title/author match via
-- the catalog's own search (one candidate per library that had a hit — see
-- _findProbableCatalogMatches). Books with more than one candidate need an
-- explicit "quale biblioteca?" choice before anything else can happen to
-- them; everything else proceeds straight to the automatic buckets
-- described in this section's header comment.
function Kolibre:_searchUnmatched(unmatched)
    if #unmatched == 0 then
        UIManager:show(InfoMessage:new{ text = t("koreader.library_init.nothing_else") })
        return
    end

    local resolved, ambiguous, no_candidate = {}, {}, {}

    self:_showProgress(t("koreader.library_init.searching_matches", { total = #unmatched }))
    for idx, item in ipairs(unmatched) do
        if idx % 3 == 0 or idx == #unmatched then
            self:_showProgress(t("koreader.library_init.checking_content", { done = idx, total = #unmatched }))
        end
        -- Content fingerprint first (authoritative, when the format
        -- supports it) — only falls back to the filename/folder-guess
        -- fuzzy search when unsupported or genuinely no match, so a wrong
        -- naming convention can never again silently defeat matching for
        -- epub/fb2/txt the way title_sort reordering did.
        local content_match = self:_identifyFileByContent(item.path)
        local candidates
        if content_match then
            candidates = { content_match }
        else
            candidates = self:_findProbableCatalogMatches(_guessTitleFromPath(item.path), self:_guessAuthorFromPath(item.path))
        end
        if #candidates == 0 then
            table.insert(no_candidate, item)
        elseif #candidates == 1 then
            table.insert(resolved, { item = item, candidate = candidates[1] })
        else
            table.insert(ambiguous, { item = item, candidates = candidates })
        end
    end
    self:_closeProgress()

    self:_resolveAmbiguousFuzzyMatches(ambiguous, 1, resolved, no_candidate, function()
        self:_classifyResolvedFuzzyMatches(resolved, no_candidate)
    end)
end

-- One book at a time: more than one library has a plausible title/author
-- match — ask which one (or "none of these"), never guess silently.
function Kolibre:_resolveAmbiguousFuzzyMatches(ambiguous, idx, resolved, no_candidate, done)
    if idx > #ambiguous then
        done()
        return
    end
    local entry = ambiguous[idx]
    local items = {}
    for _cidx, c in ipairs(entry.candidates) do
        table.insert(items, {
            text = string.format("%s — %s", c.title or "?", c.library),
            callback = function()
                if self._fuzzy_match_menu then UIManager:close(self._fuzzy_match_menu) end
                table.insert(resolved, { item = entry.item, candidate = c })
                self:_resolveAmbiguousFuzzyMatches(ambiguous, idx + 1, resolved, no_candidate, done)
            end,
        })
    end
    table.insert(items, {
        text = t("koreader.common.none_of_these"),
        callback = function()
            if self._fuzzy_match_menu then UIManager:close(self._fuzzy_match_menu) end
            table.insert(no_candidate, entry.item)
            self:_resolveAmbiguousFuzzyMatches(ambiguous, idx + 1, resolved, no_candidate, done)
        end,
    })
    self._fuzzy_match_menu = Menu:new{
        title = t("koreader.library_init.ambiguous_title", { name = entry.item.path:match("([^/]+)$") or entry.item.path }),
        subtitle = t("koreader.library_init.which_library"),
        item_table = items,
        is_popout = true,
        is_borderless = false,
    }
    UIManager:show(self._fuzzy_match_menu)
end

-- Now-unambiguous fuzzy matches (single library candidate, or resolved by
-- the user just above) sorted into the automatic buckets described in this
-- section's header comment.
function Kolibre:_classifyResolvedFuzzyMatches(resolved, no_candidate)
    local to_overwrite = {}
    local flagged_count = 0
    local started_items = {}
    for _idx, r in ipairs(resolved) do
        if self:_looksNeverOpened(r.item.path) then
            table.insert(to_overwrite, { path = r.item.path, candidate = r.candidate })
        else
            local percent_read, highlights_count = self:_readLocalReviewReason(r.item.path)
            local ok = self.api:request("POST", "/api/kolibre/devices/flagged-books", {
                local_path = r.item.path,
                local_title = _guessTitleFromPath(r.item.path),
                -- Indovinato da nome file/cartella, stessa euristica già
                -- usata per interrogare browse_catalog poco sopra (riuso, non
                -- un nuovo calcolo) — distinto da candidate_author sotto, che
                -- è l'autore del libro CANDIDATO sul server, non del file.
                local_author = self:_guessAuthorFromPath(r.item.path),
                match_status = "flagged_started",
                local_percent_read = percent_read,
                local_highlights_count = highlights_count,
                candidate_library = r.candidate.library,
                candidate_calibre_book_id = r.candidate.id,
                candidate_title = r.candidate.title,
                candidate_author = r.candidate.author,
                -- "fingerprint" (from _identifyFileByContent) is an
                -- authoritative identity check, not a guess — the server
                -- uses this to auto-pair (safe: never touches the local
                -- file) instead of parking the book in "Da rivedere" just
                -- because it already has progress. "fuzzy" candidates still
                -- always need human confirmation.
                match_source = r.candidate.source,
                -- Needed by the web UI's manual "Accoppia" action (records
                -- this exact hash against whichever book is picked, even if
                -- it never matches the server's own copy byte-for-byte).
                hash = r.item.hash,
            })
            if ok then flagged_count = flagged_count + 1 end
            table.insert(started_items, r.item)
        end
    end
    -- The whole point of flagging instead of touching the file: it was
    -- already opened, so it may already carry highlights/notes. Capture
    -- those now (as orphans, until paired) instead of only when/if the
    -- user later gets around to pairing it by hand from "Da rivedere".
    self:_pushAnnotationsForUnmanagedFiles(started_items)
    self:_confirmOverwriteBatch(to_overwrite, flagged_count, no_candidate)
end

-- Step 3: never-opened fuzzy matches — batch confirm, then a real overwrite
-- (delete local file, download the Kolibre copy in its place).
function Kolibre:_confirmOverwriteBatch(to_overwrite, flagged_count, no_candidate)
    local flagged_notice = flagged_count > 0
        and t("koreader.library_init.flagged_notice", { count = flagged_count })
        or ""

    if #to_overwrite == 0 then
        if flagged_count > 0 then
            UIManager:show(InfoMessage:new{ text = flagged_notice:gsub("^\n\n", ""), timeout = 5 })
        end
        self:_showNoCandidateMenu(no_candidate)
        return
    end

    local names = {}
    for _idx, e in ipairs(to_overwrite) do
        table.insert(names, string.format("• %s", e.candidate.title or e.path:match("([^/]+)$") or e.path))
    end
    UIManager:show(ConfirmBox:new{
        text = t("koreader.library_init.overwrite_confirm", {
            count = #to_overwrite, list = table.concat(names, "\n"), notice = flagged_notice,
        }),
        ok_text = t("koreader.common.overwrite"),
        cancel_text = t("koreader.common.leave_as_is"),
        ok_callback = function() self:_applyOverwriteBatch(to_overwrite, no_candidate) end,
        cancel_callback = function() self:_showNoCandidateMenu(no_candidate) end,
    })
end

function Kolibre:_applyOverwriteBatch(to_overwrite, no_candidate)
    for idx, e in ipairs(to_overwrite) do
        self:_showProgress(t("koreader.library_init.overwriting_progress", { done = idx, total = #to_overwrite }))
        self:_deleteManagedBook(e.path)
        self:_downloadCatalogBook(e.candidate, e.candidate.library)
    end
    self:_closeProgress()
    self:_showNoCandidateMenu(no_candidate)
end

-- Step 4: no match at all — nothing automatic is safe to do, so this is a
-- plain browsable list (same pattern as showManagedBooks/
-- _showManagedBookDialog) where each book can be deleted locally or left
-- alone, one at a time. ALSO reported to the server (match_status
-- "no_candidate") so it shows up in the web UI's "Da rivedere" page too —
-- this used to be purely on-device: dismiss this menu without acting, and
-- the information was gone for good, invisible from the web.
function Kolibre:_showNoCandidateMenu(no_candidate)
    if #no_candidate == 0 then return end
    for _idx, item in ipairs(no_candidate) do
        self.api:request("POST", "/api/kolibre/devices/flagged-books", {
            local_path = item.path,
            local_title = _guessTitleFromPath(item.path),
            local_author = self:_guessAuthorFromPath(item.path),
            match_status = "no_candidate",
            hash = item.hash,
        })
    end
    -- Same reasoning as the flagged_started branch above: no candidate at
    -- all doesn't mean no highlights — capture them now, as orphans, so
    -- they're not lost regardless of whether/when this file ever gets
    -- matched to a book.
    self:_pushAnnotationsForUnmanagedFiles(no_candidate)
    local items = {}
    for _idx, item in ipairs(no_candidate) do
        table.insert(items, {
            text = item.path:match("([^/]+)$") or item.path,
            callback = function() self:_showNoCandidateDialog(item) end,
        })
    end
    self._no_candidate_menu = Menu:new{
        title = t("koreader.library_init.no_candidate_title"),
        subtitle = t("koreader.common.book_count", { count = #items }),
        item_table = items,
        is_popout = true,
        is_borderless = false,
    }
    UIManager:show(self._no_candidate_menu)
end

function Kolibre:_showNoCandidateDialog(item)
    UIManager:show(ConfirmBox:new{
        text = t("koreader.library_init.no_candidate_detail", { path = item.path }),
        ok_text = t("koreader.library_init.delete_from_device"),
        cancel_text = t("koreader.common.leave_as_is"),
        ok_callback = function()
            self:_deleteManagedBook(item.path)
            if self._no_candidate_menu then
                UIManager:close(self._no_candidate_menu)
                self._no_candidate_menu = nil
            end
            UIManager:show(InfoMessage:new{ text = t("koreader.library_init.deleted_notice"), timeout = 2 })
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

function Kolibre:_extractAnnotationsFromFile(file_path, file_hash)
    if not DocSettings:hasSidecarFile(file_path) then return {} end
    local ok, doc_settings = pcall(function() return DocSettings:open(file_path) end)
    if not ok or not doc_settings then return {} end
    local annotations = doc_settings:readSetting("annotations") or {}

    local out = {}
    for _idx, a in ipairs(annotations) do
        if a.drawer and a.text and a.text ~= "" then
            table.insert(out, {
                hash = file_hash,
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
            table.insert(chiavi_per_file, { hash = b.hash, path = b.path, keys = chiavi })
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
                table.insert(chiavi_per_file, { hash = hash, path = path, keys = chiavi })
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

-- ── Self-update ──
--
-- Checks the server's own copy of this plugin (served straight out of
-- backend/app/api/tools.py, which reads VERSION out of the server's own
-- main.lua) and, if newer, downloads every source file and overwrites this
-- installation in place — no cable, no zip/unzip on-device. KOReader has
-- already loaded this plugin's Lua bytecode into memory for the running
-- session, so the new main.lua only takes effect after a full KOReader
-- restart; we say so explicitly rather than implying it's applied live.

-- "0.1.0" -> {0, 1, 0}, compared component-wise; a version with fewer
-- components than the other is padded with zeros (so "1.2" > "1.1.9").
local function _parseVersion(v)
    local parts = {}
    for n in tostring(v or ""):gmatch("%d+") do
        table.insert(parts, tonumber(n))
    end
    return parts
end

local function _isNewerVersion(remote, local_)
    local r, l = _parseVersion(remote), _parseVersion(local_)
    for i = 1, math.max(#r, #l) do
        local rv, lv = r[i] or 0, l[i] or 0
        if rv ~= lv then return rv > lv end
    end
    return false
end

function Kolibre:checkForUpdate(interactive)
    if not self:_requireReachable(interactive) then return end

    local result, err = self.api:request("GET", "/api/tools/plugins/koreader/version")
    if not result or not result.version then
        if interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.update.check_failed", { error = tostring(err) }) })
        end
        return
    end

    if not _isNewerVersion(result.version, VERSION) then
        if interactive then
            UIManager:show(InfoMessage:new{
                text = t("koreader.update.already_updated", { version = VERSION }),
            })
        end
        return
    end

    UIManager:show(ConfirmBox:new{
        text = t("koreader.update.available", { version = result.version, current = VERSION }),
        ok_callback = function() self:_downloadAndInstallUpdate(result.version) end,
    })
end

-- Marker written just before the rename phase begins and removed only once
-- every rename has been confirmed to have taken effect. If KOReader is
-- killed or the device loses power between the last successful download and
-- the marker being removed (including mid-rename-loop), this file is what
-- lets the NEXT plugin load detect the interrupted update and finish it
-- instead of silently running with a half-old/half-new install forever.
local UPDATE_MARKER_SUFFIX = "/.kolibre_update_pending"

-- main.lua is the one file whose own code decides whether to keep going with
-- an old or a new kolibre_api.lua underneath it, so it's always renamed
-- LAST: every dependency (kolibre_api.lua, _meta.lua, anything future) is
-- swapped in first, and only once that has fully succeeded does main.lua
-- itself flip over. That way, if a crash lands mid-update, the file left
-- "still old" is main.lua — and main.lua's own request/download methods only
-- ever call the small, stable subset of KolibreApi's public interface, so an
-- old main.lua running against an already-updated kolibre_api.lua is far
-- less likely to break than the reverse (a new main.lua calling into methods
-- an old kolibre_api.lua doesn't have yet).
local function _orderRenameEntries(entries)
    local ordered, main_entry = {}, nil
    for _idx, entry in ipairs(entries) do
        if entry.target_path:match("/main%.lua$") then
            main_entry = entry
        else
            table.insert(ordered, entry)
        end
    end
    if main_entry then table.insert(ordered, main_entry) end
    return ordered
end

function Kolibre:_writeUpdateMarker(base_path, new_version, entries)
    local f = io.open(base_path .. UPDATE_MARKER_SUFFIX, "w")
    if not f then return false end
    f:write(tostring(new_version), "\n")
    for _idx, entry in ipairs(entries) do
        f:write(entry.staged_path, "\t", entry.target_path, "\n")
    end
    f:close()
    return true
end

function Kolibre:_removeUpdateMarker(base_path)
    os.remove(base_path .. UPDATE_MARKER_SUFFIX)
end

-- Returns new_version, entries — entries is nil (not just empty) when there
-- is no marker at all, so callers can tell "nothing pending" apart from "a
-- marker exists but listed zero files" (which shouldn't happen, but is
-- treated as done-and-safe-to-clear rather than as an error).
function Kolibre:_readUpdateMarker(base_path)
    local f = io.open(base_path .. UPDATE_MARKER_SUFFIX, "r")
    if not f then return nil, nil end
    local new_version = f:read("*l")
    local entries = {}
    for line in f:lines() do
        local staged_path, target_path = line:match("^(.-)\t(.*)$")
        if staged_path and target_path then
            table.insert(entries, { staged_path = staged_path, target_path = target_path })
        end
    end
    f:close()
    return new_version, entries
end

-- Renames every staged .kolibre-new file into place. An entry whose staged
-- file is already gone is treated as already-applied rather than an error —
-- that's what makes replaying the whole list idempotent/safe to retry from
-- scratch, which is exactly what happens when an interrupted update resumes
-- on the next plugin load. Returns true, nil on full success, or false plus
-- the first entry that could not be completed.
function Kolibre:_applyStagedRenames(entries)
    for _idx, entry in ipairs(entries) do
        if lfs.attributes(entry.staged_path, "mode") == "file" then
            if lfs.attributes(entry.target_path, "mode") then
                os.remove(entry.target_path) -- some filesystems can't rename over an existing file
            end
            os.rename(entry.staged_path, entry.target_path)
            -- os.rename's own return isn't checked above because some
            -- KOReader platforms return true even on a handful of odd
            -- filesystem edge cases; what actually matters is observable
            -- disk state, so we verify it directly instead of trusting the
            -- call's return value alone.
            if lfs.attributes(entry.target_path, "mode") ~= "file"
                    or lfs.attributes(entry.staged_path, "mode") == "file" then
                return false, entry
            end
        elseif not lfs.attributes(entry.target_path, "mode") then
            -- Neither the staged copy nor the live file exists — nothing left
            -- to rename from, and nothing to resume: this entry is stuck.
            return false, entry
        end
    end
    return true, nil
end

-- Called once per KOReader process from init() (see _resume_checked_this_session).
-- Detects an update that was staged but never finished being applied — most
-- realistically because the device lost power or KOReader was killed between
-- writing the marker and clearing it — and finishes it there and then, before
-- anything else in this plugin runs. Returns a user-facing message to show
-- once UI is available, or nil if there was nothing to do.
function Kolibre:_resumePendingUpdate()
    local base_path = self.path or "plugins/kolibre.koplugin"
    local new_version, entries = self:_readUpdateMarker(base_path)
    if not entries then return nil end -- no marker at all: nothing was interrupted

    if #entries == 0 then
        self:_removeUpdateMarker(base_path)
        return nil
    end

    local ok, failed = self:_applyStagedRenames(_orderRenameEntries(entries))
    if ok then
        self:_removeUpdateMarker(base_path)
        return t("koreader.update.resumed", { version = tostring(new_version) })
    end

    -- Marker deliberately left in place: as long as it's there, every future
    -- plugin load keeps retrying, so fixing the underlying issue (e.g. free
    -- some disk space) and just restarting KOReader again is enough to
    -- self-heal without any manual file surgery.
    logger.warn("Kolibre: impossibile completare l'aggiornamento in sospeso, file:", failed and failed.target_path)
    return t("koreader.update.resume_incomplete", {
        version = tostring(new_version), file = tostring(failed and failed.target_path or "?"),
    })
end

function Kolibre:_downloadAndInstallUpdate(new_version)
    local manifest, err = self.api:request("GET", "/api/tools/plugins/koreader/manifest")
    if not manifest or not manifest.files then
        UIManager:show(InfoMessage:new{ text = t("koreader.update.manifest_failed", { error = tostring(err) }) })
        return
    end

    local base_path = self.path or "plugins/kolibre.koplugin"
    local staged = {}
    local failed = nil

    -- Download every file to a .new sibling first — if any download fails
    -- partway through, the existing installation is left completely
    -- untouched rather than mixed old/new, and we only rename into place
    -- once every file has downloaded successfully.
    for _idx, rel_path in ipairs(manifest.files) do
        -- Downloading a whole plugin (a dozen-plus Lua files) with zero
        -- feedback used to look like a frozen device — reported directly
        -- from use ("ho scaricato il nuovo plugin" with no sign anything
        -- was happening). Always shown (this whole flow only ever runs
        -- from an explicit user-confirmed "Aggiorna" tap, never silently).
        self:_showProgressBar(_idx, #manifest.files, rel_path)
        local remote_path = "/api/tools/plugins/koreader/file/"
        for segment in rel_path:gmatch("[^/]+") do
            remote_path = remote_path .. urlEncode(segment) .. "/"
        end
        remote_path = remote_path:gsub("/$", "")

        local target_path = base_path .. "/" .. rel_path
        local staged_path = target_path .. ".kolibre-new"
        local dir = target_path:match("^(.*)/[^/]+$")
        if dir then ensureDir(dir) end

        local ok, download_err = self.api:downloadTo(remote_path, staged_path)

        -- HTTP 200 + a file on disk isn't proof the bytes are complete — a
        -- connection can drop mid-body and still leave a short/garbled file.
        -- When the manifest carries a checksum for this file (older servers
        -- without this field simply won't, and downloads then fall back to
        -- trusting the HTTP status alone, same as before), verify size and
        -- sha256 before ever considering this file good enough to stage.
        if ok then
            local expected = manifest.checksums and manifest.checksums[rel_path]
            if expected then
                local actual_size = lfs.attributes(staged_path, "size")
                if expected.size and actual_size ~= expected.size then
                    ok, download_err = false, "checksum_mismatch (size)"
                elseif expected.sha256 then
                    local content = util.readFromFile(staged_path, "rb")
                    if not content or sha2.sha256(content) ~= expected.sha256 then
                        ok, download_err = false, "checksum_mismatch (sha256)"
                    end
                end
            end
        end

        if not ok then
            os.remove(staged_path)
            failed = { path = rel_path, err = download_err }
            break
        end
        table.insert(staged, { staged_path = staged_path, target_path = target_path })
    end

    self:_closeProgress()

    if failed then
        for _idx, entry in ipairs(staged) do os.remove(entry.staged_path) end
        UIManager:show(InfoMessage:new{
            text = t("koreader.update.file_failed", { file = tostring(failed.path), error = tostring(failed.err) }),
        })
        return
    end

    local ordered = _orderRenameEntries(staged)

    -- Written before any rename happens; if this fails outright (e.g. disk
    -- full), abort now rather than proceed without the safety net that lets
    -- an interrupted rename phase be detected and finished on next launch.
    if not self:_writeUpdateMarker(base_path, new_version, ordered) then
        for _idx, entry in ipairs(ordered) do os.remove(entry.staged_path) end
        UIManager:show(InfoMessage:new{ text = t("koreader.update.stage_failed") })
        return
    end

    local ok, apply_failed = self:_applyStagedRenames(ordered)
    if not ok then
        -- Marker stays: _resumePendingUpdate will retry the remaining
        -- entries the next time this plugin loads, without re-downloading
        -- anything (everything still successfully downloaded is already
        -- sitting in its .kolibre-new staging file).
        UIManager:show(InfoMessage:new{
            text = t("koreader.update.partial", { file = tostring(apply_failed and apply_failed.target_path or "?") }),
        })
        return
    end

    self:_removeUpdateMarker(base_path)
    UIManager:show(InfoMessage:new{
        text = t("koreader.update.done", { version = new_version }),
    })
end

-- ── Dizionario StarDict sul dispositivo ──
--
-- Scarica il dizionario StarDict installato sul server (Impostazioni →
-- Integrazioni → Dizionari, backend/app/services/stardict_service.py)
-- dentro data/dict/, così la ricerca nativa di KOReader (tieni premuto su
-- una parola durante la lettura) lo trova e lo usa da sola — stesso
-- meccanismo manifest + download-per-file del self-update qui sopra, per
-- lo stesso motivo: KOReader non offre a questo plugin alcuna libreria di
-- decompressione zip on-device (vedi il commento di _downloadAndInstallUpdate).
function Kolibre:downloadDictionary(lang, interactive)
    if not self:_requireReachable(interactive) then return end

    local manifest, err = self.api:request("GET", "/api/kolibre/devices/dictionaries/" .. lang .. "/manifest")
    if not manifest or not manifest.files or #manifest.files == 0 then
        if interactive then
            UIManager:show(InfoMessage:new{
                text = t("koreader.dictionary.unavailable"),
            })
        end
        return
    end

    local target_dir = DataStorage:getDataDir() .. "/dict/kolibre-" .. lang
    ensureDir(target_dir)

    local failed = nil
    for _idx, file in ipairs(manifest.files) do
        self:_showProgressBar(_idx, #manifest.files, file.name)
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
        return
    end

    UIManager:show(InfoMessage:new{
        text = t("koreader.dictionary.done"),
    })
end

-- ── Sync (protocol v2) ──
--
-- Session-based, server-driven. The wire contract lives in
-- backend/scripts/simulate_device.py (executable reference) and
-- backend/app/api/devices.py (sync_router). Flow per sync:
--   fase 0: payload from the manifest (existence check per entry, MD5 only
--           when missing from the manifest; managed_books omitted entirely
--           when the manifest is clean and a cached library_token exists),
--   fase 1: POST /sync (handshake, 409 = another session running),
--   fase 2: downloads + batched /sync/ack,
--   fase 3: deletions per server policy + /sync/ack,
--   fase 4: page counts from statistics.sqlite3 -> POST /pages,
--   fase 5: POST /sync/finish, then annotations.
-- Fasi 4-5 run inside the fase-3 continuation because the 'ask' policy shows
-- an async ConfirmBox — nothing after it may run until the user answers.

local ACK_BATCH_SIZE = 5

function Kolibre:_sendAck(session_id, downloads, deletions)
    if #(downloads or {}) == 0 and #(deletions or {}) == 0 then return end
    local result, err = self.api:request("POST", "/api/kolibre/devices/sync/ack", {
        session_id = session_id,
        downloads = downloads or {},
        deletions = deletions or {},
    })
    if not result then
        -- Non-fatal: the local action already happened; an unacked download
        -- just gets re-offered (and re-acked) at a later handshake.
        logger.warn("Kolibre: /sync/ack fallito:", err)
    end
end

-- Fase 0. Returns payload, missing_keys (manifest entries whose file is gone,
-- removed from the manifest once the handshake response implicitly acks the
-- report), migration_items (scan results to adopt into the manifest, or nil).
-- Quanto spazio c'e' sul volume che ospita i libri.
--
-- La scheda del dispositivo su Kolibre ha sempre detto "non riportato dal
-- dispositivo", e diceva il vero: il campo storage_used esisteva sul modello
-- dal primo giorno e nessuno l'ha mai riempito. Si misura il volume di
-- books_dir e non quello di sistema, perche' la domanda vera e' "ci sta un
-- altro libro?".
--
-- Difensivo di proposito: util.diskUsage passa da ffiUtil.df, che su una
-- piattaforma disattenta puo' non esserci o non rispondere. Se non torna
-- niente si manda niente, e il server continua a dire "non riportato" —
-- meglio di un numero inventato.
function Kolibre:_diskUsage()
    if type(util.diskUsage) ~= "function" then return nil end
    local ok, info = pcall(util.diskUsage, self.books_dir)
    if not ok or type(info) ~= "table" or not info.total or info.total <= 0 then
        return nil
    end
    return info
end

function Kolibre:_buildSyncPayload(trigger, allow_migration)
    local payload = {
        protocol = 2,
        plugin_version = VERSION,
        trigger = trigger,
        library_token = self.manifest:getToken(),
    }

    local disco = self:_diskUsage()
    if disco then
        payload.storage_total = math.floor(disco.total)
        payload.storage_used = math.floor(disco.used or (disco.total - (disco.available or 0)))
        payload.storage_available = math.floor(disco.available or 0)
    end

    local books = self.manifest:all()

    -- Soft migration from v0.2.0 (empty manifest, never migrated): do the
    -- legacy full filesystem scan ONCE and report those hashes so the server
    -- adopts whatever it can resolve. See kolibre_manifest.lua's header for
    -- why the adopted entries get "hash:<hash>" keys. Only runs when the
    -- caller has explicit consent (allow_migration) — this walk can be slow
    -- and must never fire silently off the back of a routine "Sincronizza".
    local migration_items = nil
    if allow_migration and next(books) == nil and not self.manifest:getMeta("migration_done") then
        migration_items = self:_scanLocalBooks(function(count)
            self:_showProgress(t("koreader.sync.migration_scanning", { count = count }))
        end)
        self:_closeProgress()
        local managed = {}
        for _idx, b in ipairs(migration_items) do
            table.insert(managed, { hash = b.hash, format = b.format, path = b.path })
        end
        payload.managed_books = managed
        return payload, {}, migration_items
    end

    -- Cheap existence pass (no hashing) over every manifest entry.
    local missing_keys, missing_report = {}, {}
    for key, entry in pairs(books) do
        if not (entry.path and lfs.attributes(entry.path, "mode") == "file") then
            table.insert(missing_keys, key)
            if entry.library and entry.calibre_book_id then
                table.insert(missing_report, {
                    library = entry.library,
                    calibre_book_id = entry.calibre_book_id,
                    format = entry.format,
                })
            end
            -- "hash:*" migration entries have no server identity to report;
            -- they just get dropped from the manifest after the handshake.
        end
    end

    -- managed_books can be omitted (=> server may grant a light sync) only
    -- when we hold a token AND nothing changed locally. A non-empty missing
    -- report forces a full payload too: the server ignores missing_books on
    -- a light sync (it requires managed_books to be absent AND processes
    -- missing only on the non-light path).
    local need_managed = self.manifest:isDirty()
        or self.manifest:getToken() == nil
        or #missing_keys > 0
    if need_managed then
        local managed = {}
        for key, entry in pairs(books) do
            if entry.path and lfs.attributes(entry.path, "mode") == "file" then
                if not entry.hash then
                    -- Lazy backfill: partialMD5 at most once per book, then
                    -- cached in the manifest (no_dirty: this changes nothing
                    -- the server needs re-reported).
                    entry.hash = util.partialMD5(entry.path)
                    if entry.hash then self.manifest:set(key, entry, true) end
                end
                if entry.hash then
                    table.insert(managed, {
                        hash = entry.hash,
                        format = entry.format,
                        path = entry.path,
                        pages = entry.pages,
                    })
                end
            end
        end
        payload.managed_books = managed
    end
    if #missing_report > 0 then
        payload.missing_books = missing_report
    end
    return payload, missing_keys, nil
end

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

    -- Sidecar purge. DocSettings' purge API has shifted across KOReader
    -- releases (purge() on an open instance is the stable form) — pcall so a
    -- missing/renamed method can never abort the deletion loop.
    pcall(function()
        if DocSettings:hasSidecarFile(path) then
            DocSettings:open(path):purge()
        end
    end)

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

-- Fase 3. Applies removes[] according to the server-driven policy and acks
-- each with result 'deleted' | 'missing' | 'declined' | 'error'. Async by
-- design: the 'ask' policy on a manual sync shows ONE cumulative ConfirmBox,
-- so the rest of the sync continues in on_done(deleted, deferred, errors)
-- ("deferred" counts both user-declined and postponed-to-manual removals).
function Kolibre:_applyDeletions(session_id, removes, policy, interactive, on_done)
    if #removes == 0 then
        on_done(0, 0, 0)
        return
    end

    -- Path resolution: manifest entry -> server's expected_path -> nothing.
    local acks, to_delete = {}, {}
    for _idx, item in ipairs(removes) do
        local key = KolibreManifest.bookKey(item.library, item.calibre_book_id, item.format)
        local entry = self.manifest:get(key)
        local path = (entry and entry.path) or item.expected_path
        if path and lfs.attributes(path, "mode") == "file" then
            table.insert(to_delete, {
                book_id = item.book_id,
                key = key,
                path = path,
                title = item.title or (entry and entry.title) or path:match("([^/]+)$"),
            })
        else
            -- Unresolvable or already gone: desired state already reached.
            if entry then self.manifest:remove(key) end
            table.insert(acks, { book_id = item.book_id, result = "missing" })
        end
    end

    local function finishWith(deleted, deferred, errors)
        self:_sendAck(session_id, nil, acks)
        on_done(deleted, deferred, errors)
    end

    local function executeAll()
        local deleted, errors = 0, 0
        local total = #to_delete
        for idx, d in ipairs(to_delete) do
            if total > 1 then
                self:_showProgress(t("koreader.sync.removing_progress", { done = idx, total = total }))
            end
            local ok, err = self:_deleteManagedBook(d.path, { manifest_key = d.key })
            if ok then
                deleted = deleted + 1
                table.insert(acks, { book_id = d.book_id, result = "deleted" })
            else
                errors = errors + 1
                logger.warn("Kolibre: rimozione fallita per", d.path, err)
                table.insert(acks, { book_id = d.book_id, result = "error", error = tostring(err) })
            end
        end
        self:_closeProgress()
        finishWith(deleted, 0, errors)
    end

    if #to_delete == 0 then
        finishWith(0, 0, 0)
    elseif policy == "auto" then
        executeAll()
    elseif interactive then
        -- policy 'ask' on a manual sync: ONE cumulative confirmation for the
        -- whole batch — never one dialog per book.
        local titles = {}
        for _idx, d in ipairs(to_delete) do
            table.insert(titles, "• " .. tostring(d.title))
        end
        UIManager:show(ConfirmBox:new{
            text = t("koreader.sync.removal_confirm", { count = #to_delete, list = table.concat(titles, "\n") }),
            ok_text = t("koreader.common.remove"),
            cancel_text = t("koreader.common.not_now"),
            ok_callback = executeAll,
            cancel_callback = function()
                for _idx, d in ipairs(to_delete) do
                    table.insert(acks, { book_id = d.book_id, result = "declined" })
                end
                finishWith(0, #to_delete, 0)
            end,
        })
    else
        -- policy 'ask' on an automatic sync: never interrupt reading with a
        -- modal. No ack at all for these (they stay pending server-side and
        -- will be offered again), just a discreet heads-up.
        -- Nota: il testo quotava ancora "Sincronizza ora", il nome del menù
        -- prima della v0.5.0 — corretto in traduzione al nome attuale,
        -- "Sincronizza tutto" (vedi anche koreader.sync.downloads_pending,
        -- che già citava il nome giusto).
        UIManager:show(InfoMessage:new{
            text = t("koreader.sync.removal_pending", { count = #to_delete }),
            timeout = 5,
        })
        finishWith(0, #to_delete, 0)
    end
end

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
                table.insert(report, { hash = entry.hash, pages = p })
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

-- interactive defaults to true so a bare self:syncNow() keeps behaving like
-- the menu entry; automatic callers pass (false, "auto_open"/"auto_resume")
-- so the server's history records what fired the sync.
-- Solo i libri: scarica quelli nuovi, applica le rimozioni, e basta.
--
-- Scelto il 28/09/2026 come comportamento predefinito all'avvio.
-- La ragione e' che le due meta' di una sincronizzazione hanno urgenze
-- diverse: sapere che e' arrivato un libro nuovo serve **adesso**, quando
-- accendi il lettore e vuoi vedere cosa c'e' da leggere; mandare annotazioni,
-- posizioni, conteggi e backup puo' benissimo aspettare la chiusura di un
-- libro — e' li' che quei dati nascono, ed e' li' che "Sincronizza tutto"
-- gia' scatta per impostazione predefinita.
--
-- Non e' un sync diverso: e' lo stesso, fermato prima. Handshake, download,
-- azioni in sospeso, rimozioni, chiusura della sessione — e si salta la coda
-- delle pagine, delle note, delle posizioni e il backup, che sono le fasi
-- lente (il backup da solo caricava dodici file, e le statistiche erano 659
-- KB prima di diventare incrementali).
function Kolibre:syncBooksOnly(interactive, trigger)
    if interactive == nil then interactive = true end
    if not self:_requireReachable(interactive) then return end
    -- allow_migration sempre falso: la scansione iniziale dei libri gia'
    -- presenti puo' durare minuti, e questo e' il comando "veloce" — quella
    -- resta legata a "Sincronizza tutto", che la chiede esplicitamente.
    self:_syncNowRun(interactive, trigger or (interactive and "manual_libri" or "auto_libri"), false, true)
end

function Kolibre:syncNow(interactive, trigger)
    if interactive == nil then interactive = true end
    trigger = trigger or (interactive and "manual" or "auto")
    if not self:_requireReachable(interactive) then return end

    -- First-ever sync (empty manifest, migration never run): recognizing
    -- books already on the device means a full local scan, which can take
    -- minutes on a device with many books (see _scanLocalBooks). That must
    -- never fire as a surprise off a routine "Sincronizza ora", and never at
    -- all off an unattended automatic trigger — ask once, explicitly.
    if interactive and next(self.manifest:all()) == nil and not self.manifest:getMeta("migration_done") then
        UIManager:show(ConfirmBox:new{
            text = t("koreader.sync.first_sync_confirm"),
            ok_text = t("koreader.common.continue"),
            cancel_text = t("koreader.sync.skip_for_now"),
            ok_callback = function() self:_syncNowRun(interactive, trigger, true) end,
            cancel_callback = function() self:_syncNowRun(interactive, trigger, false) end,
        })
        return
    end

    self:_syncNowRun(interactive, trigger, false)
end

-- allow_migration: the one-time local scan has explicit consent (or isn't
-- needed at all) — see syncNow above for why this can never be silent.
-- Number of labeled steps shown on the "Sincronizza tutto" progress bar —
-- see _showProgressBar's own comment for why this mirrors KoServer's
-- syncAll() bar exactly. Kept as one flat sequence (handshake, download,
-- pending actions, removals, page counts, notes/positions/backup) even
-- though the real work is callback-chained rather than a plain for-loop,
-- so each phase just calls _showProgressBar(i, SYNC_STEP_COUNT, label)
-- as it starts.
local SYNC_STEP_COUNT = 6

-- solo_libri: si fermano le fasi 4 e 6 (conteggio pagine, note/posizioni/
-- backup). Vedi syncBooksOnly per il perche'.
function Kolibre:_syncNowRun(interactive, trigger, allow_migration, solo_libri)
    -- Quanti passi mostra la barra: quattro nel controllo veloce, che si
    -- ferma dopo le rimozioni. Con il totale fisso a sei sembrerebbe
    -- interrotta a due terzi ogni volta.
    local passi = solo_libri and 4 or SYNC_STEP_COUNT
    if interactive then
        UIManager:show(InfoMessage:new{
            text = solo_libri and t("koreader.sync.checking_new_books")
                              or t("koreader.sync.in_progress"),
            timeout = 1,
        })
    end

    -- Cronometro per fase. Il server ha sempre avuto la colonna detail_json e
    -- non ci scriveva nessuno: di una sincronizzazione lenta non si poteva
    -- sapere DOVE fosse andato il tempo, e ottimizzare senza quel dato vuol
    -- dire tirare a indovinare (provato: due ipotesi su tre erano sbagliate).
    -- os.time() e non os.clock(): quest'ultimo misura tempo di CPU, mentre
    -- qui quasi tutta l'attesa e' rete e disco. La granularita' del secondo
    -- basta per capire quale fase pesa.
    local phases = {}
    local phase_started = os.time()
    local function markPhase(name)
        local now = os.time()
        phases[name] = (phases[name] or 0) + (now - phase_started)
        phase_started = now
    end

    -- Fase 0
    local payload, missing_keys, migration_items = self:_buildSyncPayload(trigger, allow_migration)
    markPhase("preparazione")

    -- Fase 1: handshake
    self:_showProgressBar(1, passi, t("koreader.sync.phase_handshake"))
    local result, err = self.api:request("POST", "/api/kolibre/devices/sync", payload)
    if not result then
        self:_closeProgress()
        if err == 409 then
            if interactive then
                UIManager:show(InfoMessage:new{
                    text = t("koreader.sync.already_running"),
                })
            end
        elseif interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.sync.failed", { error = tostring(err) }) })
        end
        return
    end
    local session_id = result.session_id
    if not session_id then
        self:_closeProgress()
        -- We sent protocol=2; a session-less response means a pre-v2 server.
        if interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.sync.protocol_unsupported") })
        end
        return
    end

    local settings = result.settings or {}
    self.folder_layout = settings.folder_layout or "author" -- cached for the catalog browser's direct downloads too
    local write_folder_cover = settings.write_folder_cover
    if write_folder_cover == nil then write_folder_cover = true end
    self.write_folder_cover = write_folder_cover -- cached for _backfillAuthorFolderCovers, which runs outside a sync handshake
    local policy = settings.delete_policy or "ask"
    self.manifest:setMeta("delete_policy", policy) -- for the Info dialog
    if result.library_token then
        self.manifest:saveToken(result.library_token)
    end
    self:_rememberRestoreRequest(result.restore_request)

    -- The handshake response is the implicit ack of our missing_books report:
    -- those entries can now leave the manifest.
    for _idx, key in ipairs(missing_keys) do
        self.manifest:remove(key)
    end
    -- Migration: adopt the one-time scan results under "hash:*" keys (see
    -- kolibre_manifest.lua header) and never scan again.
    if migration_items then
        for _idx, b in ipairs(migration_items) do
            if b.hash then
                self.manifest:set("hash:" .. b.hash, {
                    path = b.path, hash = b.hash, format = b.format,
                    downloaded_at = os.time(),
                }, true)
            end
        end
        self.manifest:setMeta("migration_done", true)
    end

    -- Fase 2.5-5 continuation, called either after Fase 2's downloads ran
    -- (downloaded/failed from the real loop) or after the user/automation
    -- declined/deferred them (0, 0, no acks sent — same "stays pending
    -- server-side, re-offered next sync" convention _applyDeletions' own
    -- 'ask'-on-automatic branch already uses).
    local function afterDownloads(downloaded, failed)
        -- Fase 2.5: web-UI-queued actions on "Da rivedere" entries (files the
        -- device-init scan found but never registered as a managed book) —
        -- 'delete' or 'overwrite', queued from the web page and applied here
        -- since the device isn't always online for an immediate round-trip.
        -- Reuses the exact same primitives Wave D's own overwrite/delete flow
        -- does (_deleteManagedBook / _downloadCatalogBook).
        self:_showProgressBar(3, passi, t("koreader.sync.phase_pending_actions"))
        local applied_action_ids = {}
        for _idx, fa in ipairs(result.file_actions or {}) do
            local ok = true
            if fa.action == "delete" then
                ok = self:_deleteManagedBook(fa.local_path)
            elseif fa.action == "overwrite" then
                self:_deleteManagedBook(fa.local_path)
                ok = self:_downloadCatalogBook(
                    { id = fa.calibre_book_id, title = fa.title, author = fa.author, formats = { fa.format } },
                    fa.library
                )
            end
            if ok then table.insert(applied_action_ids, fa.id) end
        end
        if #applied_action_ids > 0 then
            self.api:request("POST", "/api/kolibre/devices/sync/file-actions/ack", { ids = applied_action_ids })
        end

        -- Fase 3 (async: continuation carries fasi 4-5 + summary)
        markPhase("download")
        self:_showProgressBar(4, passi, t("koreader.sync.phase_removals"))
        self:_applyDeletions(session_id, result.removes or {}, policy, interactive, function(deleted, deferred, delete_errors)
            -- Fase 4: page counts
            markPhase("rimozioni")
            local pages_sent = 0
            if not solo_libri then
                self:_showProgressBar(5, passi, t("koreader.sync.phase_pages"))
                pages_sent = self:_reportPages()
            end

            -- "Pusha al server annotazioni, posizioni di lettura, statistiche
            -- di lettura (backup in generale)" — the three other things
            -- "Sincronizza tutto" is meant to cover. Since v0.5.14
            -- (explicit decision, reversing v0.5.5): always the cheap
            -- queue-only push here, regardless of trigger — a full
            -- books_dir rescan on every manual tap made "Sincronizza tutto"
            -- itself slow and unpredictable. A book highlighted before this
            -- device's dirty-queue existed, or paired after already being
            -- highlighted, now needs the standalone "Pusha tutte le
            -- annotazioni" menu entry (pushAllAnnotationsFull) — that's the
            -- ONLY place the exhaustive rescan runs anymore.
            markPhase("pagine")
            if not solo_libri then
                self:_showProgressBar(6, passi, t("koreader.sync.phase_notes_positions_backup"))
                self:_pushQueuedAnnotations(false)
                self:_pushQueuedPositions(false)
                if self.ui.document then self:pushProgress(false) end
                markPhase("note_posizioni")
                -- Il backup e' cronometrato a parte apposta: e' la fase che
                -- caricava dodici file a OGNI sync, ed e' quella su cui vogliamo
                -- vedere l'effetto del "non mandare cio' che non e' cambiato".
                local up, skip = self:backupNow(false)
                markPhase("backup")
                phases.backup_caricati = up or 0
                phases.backup_saltati = skip or 0
                if self._ultime_righe_statistiche then
                    phases.statistiche_righe = self._ultime_righe_statistiche
                end
            end

            -- Fase 5: close the session
            self.api:request("POST", "/api/kolibre/devices/sync/finish",
                { session_id = session_id, phases = phases })
            self.manifest:setMeta("last_sync_at", os.time())
            -- Everything worth reporting has been reported (managed_books and/or
            -- acks): from here on the manifest is in sync with the server.
            self.manifest:markClean()
            self:_closeProgress()

            -- Stay silent on a no-op background sync; anything that actually
            -- happened — or any interactive call — is worth a summary.
            if interactive or downloaded > 0 or deleted > 0 or failed > 0
                    or deferred > 0 or delete_errors > 0 then
                -- Il riepilogo dice solo quello che e' stato fatto davvero:
                -- con il controllo veloce, parlare di conteggi pagine
                -- inviati (sempre zero) farebbe sembrare rotta una fase che
                -- e' stata saltata apposta.
                local testo
                if solo_libri then
                    testo = t("koreader.sync.summary_books_only", {
                        downloaded = downloaded, deleted = deleted, deferred = deferred,
                        errors = failed + delete_errors,
                    })
                else
                    testo = t("koreader.sync.summary_full", {
                        downloaded = downloaded, deleted = deleted, deferred = deferred,
                        pages = pages_sent, errors = failed + delete_errors,
                    })
                end
                UIManager:show(InfoMessage:new{ text = testo })
            end
        end)
    end

    -- Fase 2: downloads (layout/naming/.folder.jpg identical to v0.2.0) —
    -- gated on confirmation first (see _confirmDownloads): unlike removes[]
    -- (queued by a human on the web UI already), a plain "server decides,
    -- device applies silently" download used to just happen; the user now
    -- explicitly wants a chance to say no, same as deletions already allow.
    local function runDownloads(sends)
        local downloaded, failed = 0, 0
        local folder_covers_done = {}
        local pending_acks = {}
        local total_sends = #sends
        for idx, item in ipairs(sends) do
            if total_sends > 1 then
                self:_showProgressBar(idx, total_sends, item.title or t("koreader.common.download"))
            else
                self:_showProgressBar(2, passi, t("koreader.sync.phase_download_books"))
            end
            local ext = (item.format or "EPUB"):lower()
            local title = sanitizeFilename(item.title or string.format("libro_%d", item.calibre_book_id))
            local filename = string.format("%s.%s", title, ext)

            local target_dir = self.books_dir
            if self.folder_layout == "author" and item.author and item.author ~= "" then
                target_dir = self.books_dir .. "/" .. sanitizeFilename(item.author)
            end
            ensureDir(target_dir)

            if write_folder_cover and item.folder_cover_url and target_dir ~= self.books_dir
                    and not folder_covers_done[target_dir] then
                folder_covers_done[target_dir] = true
                local cover_path = target_dir .. "/.folder.jpg"
                if not lfs.attributes(cover_path, "mode") then
                    self.api:downloadTo(item.folder_cover_url, cover_path)
                end
            end

            local local_path = target_dir .. "/" .. filename
            local ok, dl_err = self.api:downloadTo(item.download_url, local_path)
            if ok then
                downloaded = downloaded + 1
                -- no_dirty: the ack below already tells the server about this
                -- book — no need to force a full managed_books report next sync.
                self.manifest:set(KolibreManifest.bookKey(item.library, item.calibre_book_id, item.format), {
                    path = local_path,
                    hash = item.delivery_hash,
                    title = item.title,
                    author = item.author,
                    library = item.library,
                    calibre_book_id = item.calibre_book_id,
                    format = (item.format or ""):upper(),
                    downloaded_at = os.time(),
                }, true)
                table.insert(pending_acks, { book_id = item.book_id, ok = true, path = local_path })
            else
                failed = failed + 1
                logger.warn("Kolibre: download fallito per book_id", item.book_id, dl_err)
                -- ok=false ack, keep going: one bad download must not abort the batch.
                table.insert(pending_acks, { book_id = item.book_id, ok = false, error = tostring(dl_err) })
            end
            if #pending_acks >= ACK_BATCH_SIZE then
                self:_sendAck(session_id, pending_acks, nil)
                pending_acks = {}
            end
        end
        self:_sendAck(session_id, pending_acks, nil)
        self:_closeProgress()
        afterDownloads(downloaded, failed)
    end

    self:_confirmDownloads(result.sends or {}, interactive,
        function() runDownloads(result.sends or {}) end,
        function() afterDownloads(0, 0) end)
end

-- Speculative to _applyDeletions (§ below), but simpler: downloads have no
-- server-driven policy (no 'auto'/'never' equivalent for sends[] today) — a
-- non-empty batch always asks, interactively or with a discreet deferred
-- heads-up, never silently applied.
function Kolibre:_confirmDownloads(sends, interactive, on_proceed, on_skip)
    if #sends == 0 then
        on_proceed()
        return
    end
    if interactive then
        local titles = {}
        for _idx, item in ipairs(sends) do
            table.insert(titles, "• " .. tostring(item.title or item.calibre_book_id))
        end
        UIManager:show(ConfirmBox:new{
            text = t("koreader.sync.downloads_confirm", { count = #sends, list = table.concat(titles, "\n") }),
            ok_text = t("koreader.common.download_verb"),
            cancel_text = t("koreader.common.not_now"),
            ok_callback = on_proceed,
            cancel_callback = on_skip,
        })
    else
        -- Same "never interrupt reading with a modal" rule _applyDeletions'
        -- own automatic branch follows: a discreet heads-up, no ack sent, the
        -- books stay pending and are re-offered on the next sync.
        UIManager:show(InfoMessage:new{
            text = t("koreader.sync.downloads_pending", { count = #sends }),
            timeout = 5,
        })
        on_skip()
    end
end

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

function Kolibre:pushProgress(interactive)
    if not self.ui.document then
        if interactive then
            UIManager:show(InfoMessage:new{ text = t("koreader.position.no_document_push") })
        end
        return
    end
    if not self:_requireReachable(interactive) then return end
    local now = os.time()
    if not interactive and now - (self.push_timestamp or 0) < PROGRESS_PUSH_DEBOUNCE_SECONDS then
        return
    end

    local percent = self:_getLastPercent()
    -- Not dirty: nothing moved since our last successful push (e.g. closing
    -- a book right after opening it, or a suspend right after a resume,
    -- with no page turns in between) — skip the request outright. Manual/
    -- interactive pushes always go through regardless, since the user asked.
    if not interactive and self.last_pushed_percent and math.abs(self.last_pushed_percent - percent) < 0.0005 then
        return
    end
    self.push_timestamp = now

    local hash = util.partialMD5(self.ui.document.file)
    if not hash then return end
    local ok, err = self.api:request("PUT", "/api/kolibre/devices/progress", {
        hash = hash,
        format = self:_documentFormat(),
        percentage = percent,
        progress = self:_getLastProgress(),
    })
    if ok then
        self.last_pushed_percent = percent
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
        "GET", string.format("/api/kolibre/devices/progress?hash=%s&format=%s", hash, self:_documentFormat())
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
    return { percent = percent, progress = progress }
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

-- Scans the whole device, classifies every OTHER book (the open one, if
-- any, stays with the live push/pull above — writing its sidecar directly
-- here could be clobbered by the reader's own save-on-close right after)
-- into "push" (we have a position the server doesn't, or ours is newer by
-- virtue of the server row being our own last write) or "pull" (another
-- device has a position we don't have locally, or a different one) — never
-- both for the same book, and never guessed silently: each direction gets
-- its own batch confirm before touching anything, exactly like the
-- device-init feature's hash-match/overwrite batches.
-- The scan+compare loop itself, factored out so the silent automation
-- variants below (_autoPushAllProgress/_autoPullAllProgress) can reuse it
-- without duplicating the comparison logic — syncAllProgress's own
-- behavior/UX is otherwise unchanged.
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
                "GET", string.format("/api/kolibre/devices/progress?hash=%s&format=%s", b.hash, b.format)
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

-- Automation's "push_pos_all"/"pull_pos_all" actions — silent counterparts
-- of syncAllProgress, still a full books_dir scan (the label in the
-- automation checkbox list says so explicitly: these are the only two
-- automation actions that can break the "no full scan in the background"
-- guarantee, and only if a user opts into them there on purpose).
function Kolibre:_autoPushAllProgress()
    if not self:_requireReachable(false) then return end
    local to_push = self:_computeProgressDiff()
    for _idx, e in ipairs(to_push) do
        self.api:request("PUT", "/api/kolibre/devices/progress", {
            hash = e.book.hash, format = e.book.format,
            percentage = e.local_pos.percent, progress = e.local_pos.progress,
        })
    end
end

function Kolibre:_autoPullAllProgress()
    if not self:_requireReachable(false) then return end
    local _to_push, to_pull = self:_computeProgressDiff()
    for _idx, e in ipairs(to_pull) do
        self:_writeLocalProgress(e.book.path, e.is_paged, e.result.percentage, e.result.progress)
    end
    if #to_pull > 0 then
        UIManager:show(InfoMessage:new{ text = t("koreader.position.pull_all_done", { count = #to_pull }), timeout = 4 })
    end
end

-- "Sincronizza tutto"'s own position push: only books actually queued by
-- onCloseDocument/onSuspend/onPageUpdate (kolibre_manifest's
-- position_dirty_paths) — no books_dir walk, unlike push_pos_all above. The
-- currently open book is excluded (pushProgress covers it separately, same
-- convention _computeProgressDiff already uses).
function Kolibre:_pushQueuedPositions(interactive)
    if not self:_requireReachable(interactive) then return end
    local paths = self.manifest:positionDirtyPaths()
    if #paths == 0 then return end
    local current_path = self.ui.document and self.ui.document.file or nil

    local pushed = 0
    for _idx, path in ipairs(paths) do
        if path == current_path then
            self.manifest:clearPositionDirty(path) -- pushProgress covers this one
        else
            local ext = path:match("%.([%a%d]+)$")
            local format = ext and ext:upper() or nil
            local hash = format and util.partialMD5(path)
            local local_pos = hash and self:_readLocalProgress(path, PAGED_FORMATS[format] or false)
            if local_pos then
                local ok = self.api:request("PUT", "/api/kolibre/devices/progress", {
                    hash = hash, format = format, percentage = local_pos.percent, progress = local_pos.progress,
                })
                if ok then
                    pushed = pushed + 1
                    self.manifest:clearPositionDirty(path)
                end
                -- On failure: left in the queue, retried next time.
            else
                self.manifest:clearPositionDirty(path) -- file gone or unreadable, nothing to retry
            end
        end
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
                self.api:request("PUT", "/api/kolibre/devices/progress", {
                    hash = e.book.hash, format = e.book.format,
                    percentage = e.local_pos.percent, progress = e.local_pos.progress,
                })
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

local BACKUP_REMINDER_DAYS_DEFAULT = 7
local BACKUP_REMINDER_CHOICES = { 3, 7, 30, 0 } -- 0 = disabled

local FULL_SYNC_DEBOUNCE_SECONDS = 60
local AUTOMATION_SETTING_KEY = "kolibre_automation_actions"

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
    { id = "sync_all",     label = t("koreader.menu.sync_all"),                        scopes = { avvio = true, apertura = true, chiusura = true, spegnimento = true } },
    -- La meta' veloce di "Sincronizza tutto": vedi syncBooksOnly. Sta subito
    -- sotto perche' la scelta vera e' fra queste due.
    { id = "sync_books",   label = t("koreader.automation.action_sync_books"),         scopes = { avvio = true, apertura = true, chiusura = true, spegnimento = true } },
    { id = "backup",       label = t("koreader.automation.action_backup"),             scopes = { avvio = true, apertura = true, chiusura = true, spegnimento = true } },
    { id = "push_annot",   label = t("koreader.automation.action_push_annot"),         scopes = { avvio = true, apertura = true, chiusura = true, spegnimento = true } },
    { id = "push_pos_cur", label = t("koreader.position.push_current"),               scopes = { apertura = true, chiusura = true } },
    { id = "pull_pos_cur", label = t("koreader.position.pull_current"),               scopes = { apertura = true, chiusura = true } },
    { id = "push_pos_all", label = t("koreader.automation.action_push_pos_all"),       scopes = { avvio = true, apertura = true, chiusura = true, spegnimento = true } },
    { id = "pull_pos_all", label = t("koreader.automation.action_pull_pos_all"),       scopes = { avvio = true, apertura = true, chiusura = true, spegnimento = true } },
}

-- I valori predefiniti, e il ragionamento dietro ciascuno.
--
-- **avvio: controlla i libri nuovi** (scelta del 28/09/2026). Accendendo il
-- lettore la domanda e' una sola — "c'e' qualcosa di nuovo da leggere?" — e
-- merita una risposta subito; mandare note, posizioni e backup all'avvio
-- costerebbe minuti per dati che nessuno sta aspettando in quel momento.
-- **chiusura: sincronizza tutto**, perche' e' li' che quei dati nascono.
-- **apertura: scarica la posizione**, silenzioso se non c'e' niente di nuovo.
--
-- Chi ha gia' toccato le impostazioni di un momento non viene toccato:
-- `_automationActions` usa questi valori solo per i momenti mai configurati.
local AUTOMATION_DEFAULTS = {
    avvio = { "sync_books" }, apertura = { "pull_pos_cur" }, chiusura = { "sync_all" }, spegnimento = {},
}

-- Separate from the automation matrix on purpose: this isn't a reading-sync
-- moment (no book, no progress, no annotations involved), it's its own
-- independent toggle, same as the backup reminder above — a plugin-wide "may
-- this plugin phone home to check its own version" switch.
local UPDATE_CHECK_DEBOUNCE_SECONDS = 24 * 60 * 60 -- at most once/day: update checks are best-effort background noise, not worth a request every reconnect/resume

function Kolibre:_isAutoCheckUpdatesEnabled()
    local v = G_reader_settings:readSetting("kolibre_auto_check_updates")
    if v == nil then return true end
    return v
end

function Kolibre:_setAutoCheckUpdatesEnabled(value)
    G_reader_settings:saveSetting("kolibre_auto_check_updates", value)
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

function Kolibre:_backupReminderDays()
    local v = G_reader_settings:readSetting("kolibre_backup_reminder_days")
    if v == nil then return BACKUP_REMINDER_DAYS_DEFAULT end
    return v
end

function Kolibre:_setBackupReminderDays(days)
    G_reader_settings:saveSetting("kolibre_backup_reminder_days", days)
end

function Kolibre:_checkBackupReminder()
    local days = self:_backupReminderDays()
    if days <= 0 then return end
    local last = G_reader_settings:readSetting("kolibre_last_backup_at") or 0
    local elapsed_days = (os.time() - last) / 86400
    if elapsed_days >= days then
        UIManager:show(ConfirmBox:new{
            text = t("koreader.backup.reminder_prompt", { days = days }),
            ok_callback = function() self:backupNow(true) end,
        })
    end
end

-- Lives under Backup ▸ Promemoria backup in the redesigned menu — it's a
-- backup concern, not a sync automation, so it's no longer mixed into
-- _automationMenuItems.
function Kolibre:_backupReminderMenuItems()
    local reminder_items = {}
    for _idx, days in ipairs(BACKUP_REMINDER_CHOICES) do
        table.insert(reminder_items, {
            text = days == 0 and t("koreader.backup.reminder_never") or t("koreader.backup.reminder_days", { days = days }),
            checked_func = function() return self:_backupReminderDays() == days end,
            callback = function() self:_setBackupReminderDays(days) end,
        })
    end
    return reminder_items
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
    items[#items].separator = true
    table.insert(items, {
        text = t("koreader.automation.auto_check_updates"),
        checked_func = function() return self:_isAutoCheckUpdatesEnabled() end,
        callback = function() self:_setAutoCheckUpdatesEnabled(not self:_isAutoCheckUpdatesEnabled()) end,
    })
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

-- Central dispatcher every hook below calls instead of ad-hoc per-moment
-- logic — one reachability check up front (not one per sub-action; the 20s
-- cache in _requireReachable would make repeats cheap anyway, but this is
-- cleaner), then runs whichever actions are enabled for this moment.
function Kolibre:_runAutomationMoment(moment)
    if not self:_requireReachable(false) then return end
    local function has(action_id) return self:_isAutomationActionEnabled(moment, action_id) end
    if has("sync_all") then self:_autoFullSync("auto_" .. moment) end
    -- Solo se non si e' gia' fatto il sync completo: quello comprende questo,
    -- e farli entrambi vorrebbe dire due handshake e due sessioni sul server
    -- per lo stesso lavoro.
    if has("sync_books") and not has("sync_all") then self:_autoBooksSync("auto_" .. moment) end
    if has("backup") then self:backupNow(false) end
    if has("push_annot") then self:_pushQueuedAnnotations(false) end
    if has("push_pos_cur") then self:pushProgress(false) end
    if has("pull_pos_cur") then self:pullProgress(false) end
    if has("push_pos_all") then self:_autoPushAllProgress() end
    if has("pull_pos_all") then self:_autoPullAllProgress() end
end

-- Book delivery (queued downloads/deletions) is device-wide, not tied to a
-- specific document, so it's debounced independently of the position
-- push/pull debounce — no point re-checking the delivery queue more than
-- once a minute even if open/resume fire in quick succession.
function Kolibre:_autoFullSync(trigger)
    local now = os.time()
    if now - (self.last_full_sync_at or 0) < FULL_SYNC_DEBOUNCE_SECONDS then return end
    self.last_full_sync_at = now
    self:syncNow(false, trigger)
end

-- Stessa antirimbalzo del sync completo, e lo STESSO contatore: le due cose
-- chiedono al server la stessa coda di consegne, quindi un controllo libri
-- subito dopo un sync completo (avvio e risveglio possono scattare a un
-- minuto di distanza) non ha niente da trovare.
function Kolibre:_autoBooksSync(trigger)
    local now = os.time()
    if now - (self.last_full_sync_at or 0) < FULL_SYNC_DEBOUNCE_SECONDS then return end
    self.last_full_sync_at = now
    self:syncBooksOnly(false, trigger)
end

-- Background counterpart of the "Controlla aggiornamenti plugin" menu entry:
-- checkForUpdate(false) already behaves correctly for this (silent unless an
-- update actually exists, in which case it shows the same install
-- confirmation as the manual check) — this just adds the gating (user
-- setting + a once-a-day debounce, persisted so it survives a KOReader
-- restart) needed to call it unattended without hammering the server.
function Kolibre:_autoCheckForUpdate()
    if not self:_isAutoCheckUpdatesEnabled() then return end
    if not self:_requireReachable(false) then return end
    local now = os.time()
    local last = G_reader_settings:readSetting("kolibre_last_update_check_at") or 0
    if now - last < UPDATE_CHECK_DEBOUNCE_SECONDS then return end
    G_reader_settings:saveSetting("kolibre_last_update_check_at", now)
    self:checkForUpdate(false)
end

-- If the freshly opened document is a Kolibre-managed book, report its real
-- on-device page count when it differs from what the manifest (and therefore
-- the server) last saw. Debounced to at most once per document opening via
-- self._pages_reported_for — onPageUpdate churn never re-triggers it.
function Kolibre:_reportOpenBookPages()
    if not self.ui.document or not self:_requireReachable(false) then return end
    local file = self.ui.document.file
    if not file or self._pages_reported_for == file then return end
    if type(self.ui.document.getPageCount) ~= "function" then return end

    local found_key, found = nil, nil
    for key, entry in pairs(self.manifest:all()) do
        if entry.path == file then
            found_key, found = key, entry
            break
        end
    end
    if not found then return end
    self._pages_reported_for = file

    local ok, pages = pcall(function() return self.ui.document:getPageCount() end)
    pages = ok and tonumber(pages) or nil
    if not pages or pages <= 0 or pages == found.pages then return end

    local hash = found.hash or util.partialMD5(file)
    if not hash then return end
    local result = self.api:request("POST", "/api/kolibre/devices/pages", {
        books = { { hash = hash, pages = pages } },
    })
    if result then
        found.hash = hash
        found.pages = pages
        self.manifest:set(found_key, found, true) -- no_dirty: just reported
    end
end

function Kolibre:onReaderReady()
    self:onDispatcherRegisterActions()
    self:_checkBackupReminder()
    self.last_pushed_percent = nil -- new document: nothing pushed yet, so the first push isn't skipped as "unchanged"
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
    end
    self:_runAutomationMoment("chiusura")
end

function Kolibre:onPageUpdate(page)
    if page == nil or not self.ui.document or page == self.last_page then return end
    self.last_page = page
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

function Kolibre:onSuspend()
    if self.ui.document then
        self.manifest:markAnnotationsDirty(self.ui.document.file)
        self.manifest:markPositionDirty(self.ui.document.file)
    end
    self:_runAutomationMoment("spegnimento")
end

function Kolibre:onResume()
    self:_runAutomationMoment("avvio")
    -- Independent of the "avvio" automation moment above (see
    -- UPDATE_CHECK_DEBOUNCE_SECONDS): a device that never disconnects wifi
    -- may not get a fresh NetworkConnected event on every wake, so resume is
    -- checked too — the once-a-day debounce inside _autoCheckForUpdate makes
    -- firing it from both hooks harmless.
    self:_autoCheckForUpdate()
    self:_checkPendingRestoreRequest()
end

-- Broadcast by KOReader core (frontend/ui/network/manager.lua) whenever wifi
-- comes up, including right after boot if it was already on — confirmed
-- against the real event name/handler convention used by stock plugins
-- (e.g. autosuspend.koplugin's own onNetworkConnected). This is the moment a
-- device that keeps wifi off between syncs actually has a connection to
-- check with, so it's the main trigger for the background update check.
function Kolibre:onNetworkConnected()
    self:_autoCheckForUpdate()
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
