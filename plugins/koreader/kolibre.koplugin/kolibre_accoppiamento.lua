-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one.

--[[--
L'accoppiamento fra i libri gia' sul dispositivo e i libri del server.

**Trasloco, non riscrittura** (20/11/2026, revisione A2). Questi corpi
vivevano in main.lua e sono stati SPOSTATI qui con i loro commenti, che
portano date e decisioni. I metodi restano raggiungibili sul plugin con gli
stessi nomi: main.lua tiene una delega per ciascuno, quindi i chiamanti non
sono cambiati. `self`, qui dentro, e' sempre l'istanza del plugin.

Qui dentro sta la catena intera di «cerca libri non accoppiati»: le
congetture dal nome del file (`_guessTitleFromPath`,
`_guessAuthorFromPath`), la lettura del sidecar per decidere se un file si
puo' toccare (`_looksNeverOpened`, `_readLocalReviewReason`),
l'identificazione per contenuto (`_identifyFileByContent`) e per somiglianza
(`_findProbableCatalogMatches`), e i passi con le loro finestre:
`_linkHashMatch` e le conferme sull'impronta, `_searchUnmatched`, lo
scioglimento delle ambiguita', la classificazione, la sovrascrittura in
blocco e l'elenco dei senza-candidato.

Restano in main.lua, di proposito: `initLibrary`/`_runLibraryInit` (il
comando che AVVIA la catena: fa la camminata, il ripescaggio delle copertine
d'autore e il filtro sul manifesto, tutte cose di la') e
`_pushAnnotationsForUnmanagedFiles`/`_tryAutoPairOrphans` (sono il dominio
delle annotazioni, che la catena si limita a chiamare).
]]

local ConfirmBox  = require("ui/widget/confirmbox")
local InfoMessage = require("ui/widget/infomessage")
local Menu        = require("ui/widget/menu")
local UIManager   = require("ui/uimanager")
local DocSettings = require("docsettings")
local t           = require("kolibre_lingua").t
local KolibreFinestre = require("kolibre_finestre")
local KolibreManifest = require("kolibre_manifest")
-- La cassetta degli attrezzi del layout su disco vive in kolibre_sync.lua:
-- una definizione sola per tutti.
local urlEncode = require("kolibre_sync").urlEncode

local KolibreAccoppiamento = {}

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
function KolibreAccoppiamento._guessAuthorFromPath(self, path)
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
function KolibreAccoppiamento._looksNeverOpened(self, file_path)
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
function KolibreAccoppiamento._readLocalReviewReason(self, file_path)
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
function KolibreAccoppiamento._findProbableCatalogMatches(self, query, author)
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
function KolibreAccoppiamento._identifyFileByContent(self, path)
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

-- Links one hash-identical match into the manifest under its real
-- server-provided identity (unlike the legacy "hash:*" migration entries).
function KolibreAccoppiamento._linkHashMatch(self, m, candidate)
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
function KolibreAccoppiamento._confirmHashMatches(self, matched, unmatched)
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
function KolibreAccoppiamento._resolveMultiLibraryHashMatches(self, multi, idx, done)
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

function KolibreAccoppiamento._confirmSingleLibraryHashMatches(self, single, unmatched)
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
            count = #single, list = KolibreFinestre.elenco(names),
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
function KolibreAccoppiamento._searchUnmatched(self, unmatched)
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
function KolibreAccoppiamento._resolveAmbiguousFuzzyMatches(self, ambiguous, idx, resolved, no_candidate, done)
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
function KolibreAccoppiamento._classifyResolvedFuzzyMatches(self, resolved, no_candidate)
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
function KolibreAccoppiamento._confirmOverwriteBatch(self, to_overwrite, flagged_count, no_candidate)
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
            count = #to_overwrite, list = KolibreFinestre.elenco(names), notice = flagged_notice,
        }),
        ok_text = t("koreader.common.overwrite"),
        cancel_text = t("koreader.common.leave_as_is"),
        ok_callback = function() self:_applyOverwriteBatch(to_overwrite, no_candidate) end,
        cancel_callback = function() self:_showNoCandidateMenu(no_candidate) end,
    })
end

function KolibreAccoppiamento._applyOverwriteBatch(self, to_overwrite, no_candidate)
    for idx, e in ipairs(to_overwrite) do
        self:_showProgress(t("koreader.library_init.overwriting_progress", { done = idx, total = #to_overwrite }))
        self:_deleteManagedBook(e.path)
        -- true = muto (20/11/2026, E7): questo giro mostra gia' la sua
        -- barra «Sovrascrivo x di y» qui sopra.
        self:_downloadCatalogBook(e.candidate, e.candidate.library, true)
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
function KolibreAccoppiamento._showNoCandidateMenu(self, no_candidate)
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

function KolibreAccoppiamento._showNoCandidateDialog(self, item)
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

return KolibreAccoppiamento
