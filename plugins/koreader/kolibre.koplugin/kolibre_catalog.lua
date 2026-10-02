--[[--
Kolibre catalog browser — cover-grid ("mosaic") view on top of the plain
text-list Menu the catalog already used (kept as-is for "list" mode, see
below). Trimmed port of the mosaic-mode machinery in bookorbit_catalog.lua,
from BookOrbit (https://github.com/bookorbit/bookorbit, AGPL-3.0) — a
separate project by other authors. BookOrbit's version is a much bigger
multi-mode controller (dashboard/book/detail, bulk selection, per-book
progress) Kolibre's catalog has no use for; only the single "book grid" mode
ports here.

Overriding Menu:updateItems (falling back to the stock implementation for
list mode) is the same technique KOReader's own built-in coverbrowser.koplugin
uses for its Mosaic/List file-manager views — not a novel hack.

Thumbnails are downloaded progressively (a few at a time, repainting as they
land) rather than all up front, same reasoning as everywhere else in this
plugin that touches the network from a loop: don't block the UI thread.
]]

local CenterContainer = require("ui/widget/container/centercontainer")
local DataStorage = require("datastorage")
local Font = require("ui/font")
local Geom = require("ui/geometry")
local HorizontalGroup = require("ui/widget/horizontalgroup")
local HorizontalSpan = require("ui/widget/horizontalspan")
local InfoMessage = require("ui/widget/infomessage")
local Menu = require("ui/widget/menu")
local Size = require("ui/size")
local TextBoxWidget = require("ui/widget/textboxwidget")
local UIManager = require("ui/uimanager")
local VerticalSpan = require("ui/widget/verticalspan")
local lfs = require("libs/libkoreader-lfs")
local util = require("util")
local t = require("kolibre_lingua").t

local CatalogWidgets = require("kolibre_catalog_widgets")
local MosaicItem = CatalogWidgets.MosaicItem

local Screen = require("device").screen

local DEFAULT_GRID_COLUMNS = 3
local DEFAULT_GRID_ROWS = 3
local THUMBNAIL_BATCH_SIZE = 2
-- Sanity ceiling on a single thumbnail transfer, NOT the expected size (the
-- server-side resize in books.py caps actual covers at 400x600 JPEG, well
-- under this) — belt-and-braces so a misbehaving response can never balloon
-- into an unbounded decode on a memory-constrained device.
local THUMBNAIL_MAX_BYTES = 3 * 1024 * 1024
-- Simple count cap on the on-device thumbnail cache — every book ever
-- browsed left a file here forever with no eviction at all. Deliberately a
-- plain one-shot oldest-first sweep (not BookOrbit's own time-budgeted
-- incremental heap eviction, bookorbit_catalog_thumbnails.lua) rather than
-- more machinery than this scale needs: thumbnails are now small (server-
-- resized, see THUMBNAIL_MAX_BYTES above), so even a few hundred of them
-- cost little to stat/sort, and this only ever runs once per catalog-screen
-- open, never per-frame.
local MAX_CACHED_THUMBNAILS = 300
local PRUNE_TARGET_THUMBNAILS = 200

local KolibreCatalog = Menu:extend{
    is_borderless = true,
}

-- Books per grid screen for the interactive browser (_openKolibreCatalog,
-- main.lua) — exposed so that caller can size its own server fetch to match
-- exactly, port of BookOrbit's own itemsPerPage()/showBookPage() model: one
-- page turn = one small request for exactly one grid's worth of books,
-- self.item_table replaced wholesale rather than accumulated. See load_page's
-- contract on _loadCatalogPage below.
function KolibreCatalog.mosaicPageSize()
    return DEFAULT_GRID_COLUMNS * DEFAULT_GRID_ROWS
end

-- Saved originals — list mode (and anything this override doesn't touch)
-- falls straight through to stock Menu behavior, exactly like the
-- reachability/annotation-push code elsewhere in this plugin prefers
-- delegating to already-correct existing logic over reimplementing it.
local Menu_recalculateDimen = Menu._recalculateDimen
local Menu_updateItems = Menu.updateItems
local Menu_onNextPage = Menu.onNextPage
local Menu_onPrevPage = Menu.onPrevPage
local Menu_onFirstPage = Menu.onFirstPage
local Menu_onLastPage = Menu.onLastPage
local Menu_onGotoPage = Menu.onGotoPage

function KolibreCatalog:init()
    -- "_v2" (not just "kolibre_covers"): a book whose cover was cached
    -- BEFORE v0.6.2 has a full-resolution image sitting under this exact
    -- filename pattern (<library>_<id>.jpg) — cachedThumbnailPath only
    -- checks file EXISTENCE, so without a new directory a pre-existing
    -- crash-causing file would still be found "already cached" and handed
    -- straight to ImageWidget for decoding, even after upgrading past the
    -- fix that stopped creating NEW ones. Renaming the directory makes every
    -- old file invisible to this version, forcing every cover to be
    -- (re)fetched through the now-resized /cover/thumbnail endpoint — the
    -- old directory itself is simply abandoned (a few KB/book of dead
    -- weight, harmless, not worth the complexity of migrating or deleting
    -- it from here).
    self.thumbnail_cache_dir = DataStorage:getDataDir() .. "/cache/kolibre_covers_v2"
    self.thumbnail_generation = 0
    self.thumbnail_failures = {}
    -- Which grid PAGES have already had their thumbnails requested — see
    -- updateItems' own comment for why this replaces the old
    -- "download every book in the whole result set up front" behavior.
    self.thumbnail_requested_pages = {}
    -- Griglia di copertine per default: la vista voluta è una griglia di
    -- copertine con titolo e autore scritti sotto, non un elenco testuale.
    -- Prima il default silenzioso era "list" finché l'utente non toccava mai
    -- l'icona Vista, quindi ogni prima apertura (catalogo, ricerca, Da
    -- scoprire) mostrava un elenco testuale invece della griglia richiesta.
    -- Una scelta esplicita salvata in precedenza (in un senso o nell'altro)
    -- resta rispettata.
    self.view_mode = G_reader_settings:readSetting("kolibre_catalog_view_mode") == "list" and "list" or "mosaic"
    self.grid_cols = DEFAULT_GRID_COLUMNS
    self.grid_rows = DEFAULT_GRID_ROWS

    Menu.init(self)
    -- No explicit scheduleThumbnailDownloads call here (unlike before): stock
    -- Menu.init() above already calls updateItems() once to build the first
    -- page, which — for mosaic mode — now requests that page's thumbnails
    -- itself. See updateItems' own comment for the full reasoning.
end

function KolibreCatalog:setViewMode(mode)
    if self.view_mode == mode then return end
    self.view_mode = mode
    G_reader_settings:saveSetting("kolibre_catalog_view_mode", mode)
    self.thumbnail_generation = self.thumbnail_generation + 1
    -- A fresh generation invalidates any in-flight download loop (their own
    -- step() checks this), so it's safe/correct to let the current page be
    -- re-requested from scratch too — already-cached thumbnails are still
    -- skipped by scheduleThumbnailDownloads itself either way.
    self.thumbnail_requested_pages = {}
    -- load_page browsers only ever keep ONE page's worth of books in
    -- item_table; list mode's own stock pagination (over just those few
    -- items) can leave self.page pointing at something that isn't a real
    -- server page number once mosaic is re-selected. Re-fetching the current
    -- page number outright is simpler and safer than trying to translate
    -- between the two modes' independent pagination — same reasoning as
    -- _loadCatalogPage's own "replace, don't patch" approach.
    if self.load_page and mode == "mosaic" then
        self:_loadCatalogPage(self.page or 1)
        return
    end
    self:updateItems()
end

-- ── Thumbnails ──

function KolibreCatalog:thumbnailPath(book)
    if not book or not util.makePath(self.thumbnail_cache_dir) then return nil end
    -- Namespaced by library: Calibre book ids restart at 1 in every library,
    -- so without this two different libraries' book #5 would share (and
    -- silently show each other's) cached cover file.
    local library_key = tostring(self.library or ""):gsub("[^%w%-%._]", "_")
    return self.thumbnail_cache_dir .. "/" .. library_key .. "_" .. tostring(book.id) .. ".jpg"
end

function KolibreCatalog:cachedThumbnailPath(book)
    local path = self:thumbnailPath(book)
    if path and lfs.attributes(path, "mode") == "file" then
        return path
    end
    return nil
end

function KolibreCatalog:thumbnailState(book)
    if not book then return "missing" end
    if self:cachedThumbnailPath(book) then return "ready" end
    if self.thumbnail_failures[tostring(book.id)] then return "failed" end
    return "loading"
end

-- One-shot oldest-first sweep — see MAX_CACHED_THUMBNAILS's own comment for
-- why this stays simple instead of porting BookOrbit's incremental scheduler.
function KolibreCatalog:pruneThumbnailCache()
    local ok, iter, dir_obj = pcall(lfs.dir, self.thumbnail_cache_dir)
    if not ok or not iter then return end
    local files = {}
    for entry in iter, dir_obj do
        if entry ~= "." and entry ~= ".." then
            local full = self.thumbnail_cache_dir .. "/" .. entry
            local mtime = lfs.attributes(full, "modification")
            if mtime then
                table.insert(files, { path = full, mtime = mtime })
            end
        end
    end
    if #files <= MAX_CACHED_THUMBNAILS then return end

    table.sort(files, function(a, b) return a.mtime < b.mtime end)
    for i = 1, (#files - PRUNE_TARGET_THUMBNAILS) do
        os.remove(files[i].path)
    end
end

function KolibreCatalog:scheduleThumbnailDownloads(items)
    self:pruneThumbnailCache()

    local queue = {}
    for _idx, entry in ipairs(items or {}) do
        local book = entry.book
        if book and not self:cachedThumbnailPath(book) and not self.thumbnail_failures[tostring(book.id)] then
            table.insert(queue, book)
        end
    end
    if #queue == 0 then return end

    local generation = self.thumbnail_generation
    local function step()
        if generation ~= self.thumbnail_generation then return end
        for _i = 1, THUMBNAIL_BATCH_SIZE do
            local book = table.remove(queue, 1)
            if not book then break end
            local path = self:thumbnailPath(book)
            if path then
                -- /cover/thumbnail (server-resized, 400x600 max — see
                -- books.py), NOT the full /cover route: a real Calibre cover
                -- is routinely 1000-2500px on the long edge, and decoding
                -- several of those at once for this grid is what crashed a
                -- real Kindle before this fix.
                local url = string.format("/api/kolibre/books/%d/cover/thumbnail?library=%s", book.id, self.library or "")
                local ok = self.api:downloadTo(url, path, THUMBNAIL_MAX_BYTES)
                if ok then
                    self.thumbnail_failures[tostring(book.id)] = nil
                else
                    self.thumbnail_failures[tostring(book.id)] = true
                end
            end
        end
        if generation == self.thumbnail_generation then
            self:updateItems(nil, true)
            if #queue > 0 then
                UIManager:scheduleIn(0.05, step)
            end
        end
    end
    UIManager:scheduleIn(0.15, step)
end

-- ── Layout: mosaic mode only, list mode falls through to stock Menu ──

function KolibreCatalog:_recalculateDimen(no_recalculate_dimen)
    if self.view_mode == "mosaic" then
        return self:recalculateMosaicDimen()
    end
    return Menu_recalculateDimen(self, no_recalculate_dimen)
end

-- Fetches exactly ONE grid page (never more, never accumulated) and replaces
-- item_table wholesale — see _openKolibreCatalog (main.lua) for load_page's
-- contract: function(page, size) -> entries, total, err. Faithful port of
-- BookOrbit's own model (bookorbit_catalog.lua: showBookPage/loadBooks/
-- onNextPage — item_table there ALSO only ever holds the current page, full
-- page/page_count driven straight from each response), chosen over an
-- earlier accumulate-and-grow scheme: this is both simpler (no "phantom
-- page" bookkeeping to get wrong) and provably safe, since a mosaic render
-- never holds more than one grid's worth of book records in memory, period.
-- Dashboard shelves (Recent/Discover) never set load_page — those stay a
-- single already-bounded fetch with the OLD client-side-paginated-over-the-
-- whole-set behavior, handled by the start_idx branch in updateItems below.
function KolibreCatalog:_loadCatalogPage(target_page)
    -- Clamped against the LAST KNOWN page_num before ever touching the
    -- network — covers setViewMode's mosaic<->list round trip, where
    -- self.page can drift to a value list mode's own stock pagination
    -- produced for a 9-item item_table, not a real server page number.
    if self.page_num then
        target_page = math.max(1, math.min(target_page, self.page_num))
    end
    local perpage = self.grid_cols * self.grid_rows
    local entries, total, err = self.load_page(target_page, perpage)
    if not entries then
        UIManager:show(InfoMessage:new{ text = t("koreader.catalog.page_load_failed", { error = tostring(err) }) })
        return true
    end
    self.item_table = entries
    self.page = target_page
    self.page_num = math.max(1, math.ceil((total or 0) / perpage))
    if self.page > self.page_num then self.page = self.page_num end
    self.thumbnail_requested_pages = {}
    self:updateItems()
    return true
end

-- All five overrides below gate on view_mode == "mosaic" too, not just
-- load_page: _loadCatalogPage sizes its fetch to grid_cols*grid_rows, which
-- only matches what's actually rendered in mosaic mode. In list mode (a
-- secondary/legacy view here, see _loadCatalogPage's own comment) these fall
-- through to stock behavior over whatever's already in item_table — same
-- pre-existing, documented limitation as before load_page existed.
function KolibreCatalog:onNextPage()
    if self.load_page and self.view_mode == "mosaic" then
        if self.page < self.page_num then return self:_loadCatalogPage(self.page + 1) end
        return true
    end
    return Menu_onNextPage(self)
end

function KolibreCatalog:onPrevPage()
    if self.load_page and self.view_mode == "mosaic" then
        if self.page > 1 then return self:_loadCatalogPage(self.page - 1) end
        return true
    end
    return Menu_onPrevPage(self)
end

function KolibreCatalog:onFirstPage()
    if self.load_page and self.view_mode == "mosaic" then
        if self.page > 1 then return self:_loadCatalogPage(1) end
        return true
    end
    return Menu_onFirstPage(self)
end

function KolibreCatalog:onLastPage()
    if self.load_page and self.view_mode == "mosaic" then
        if self.page < self.page_num then return self:_loadCatalogPage(self.page_num) end
        return true
    end
    return Menu_onLastPage(self)
end

function KolibreCatalog:onGotoPage(page)
    if self.load_page and self.view_mode == "mosaic" then
        if page < 1 or page > self.page_num or page == self.page then return true end
        return self:_loadCatalogPage(page)
    end
    return Menu_onGotoPage(self, page)
end

function KolibreCatalog:recalculateMosaicDimen()
    self.perpage = self.grid_cols * self.grid_rows
    if self.load_page then
        -- page/page_num are driven entirely by construction (main.lua, page
        -- 1) or by _loadCatalogPage (every page turn after) — never
        -- recomputed from item_table's length here, since item_table only
        -- ever holds the current page's own items, not the full result set.
        self.page_num = self.page_num or 1
    else
        self.page_num = math.max(1, math.ceil(#(self.item_table or {}) / self.perpage))
    end
    if self.page > self.page_num then self.page = self.page_num end
    local top_height = self.title_bar and not self.no_title and self.title_bar:getHeight() or 0
    local bottom_height = (self.page_return_arrow and self.page_info_text)
        and math.max(self.page_return_arrow:getSize().h, self.page_info_text:getSize().h) + Size.padding.button
        or 0
    self.available_height = self.inner_dimen.h - top_height - bottom_height
    self.item_margin = Screen:scaleBySize(10)
    self.item_height = math.floor((self.available_height - (self.grid_rows + 1) * self.item_margin) / self.grid_rows)
    self.item_width = math.floor((self.inner_dimen.w - (self.grid_cols + 1) * self.item_margin) / self.grid_cols)
    self.item_dimen = Geom:new{ x = 0, y = 0, w = self.item_width, h = self.item_height }
end

function KolibreCatalog:updateItems(select_number, no_recalculate_dimen)
    if self.view_mode ~= "mosaic" then
        return Menu_updateItems(self, select_number, no_recalculate_dimen)
    end

    local old_dimen = self.dimen and self.dimen:copy()
    self.layout = {}
    self.item_group:clear()
    self.page_info:resetLayout()
    self.return_button:resetLayout()
    self.content_group:resetLayout()
    self:_recalculateDimen(no_recalculate_dimen)

    local items = self.item_table or {}
    -- load_page set: item_table already holds exactly the current page's own
    -- items (see _loadCatalogPage), so slots map 1:1 with no offset. Not set
    -- (dashboard shelves): item_table holds the whole small fetched set,
    -- paginated client-side same as before this file's load_page support.
    local start_idx = self.load_page and 0 or (self.page - 1) * self.perpage
    local selected_number = select_number
    local page_items = {}

    if #items == 0 then
        table.insert(self.item_group, VerticalSpan:new{ width = math.floor(self.available_height * 0.38) })
        table.insert(self.item_group, CenterContainer:new{
            dimen = Geom:new{ w = self.inner_dimen.w, h = Screen:scaleBySize(80) },
            TextBoxWidget:new{
                text = t("koreader.catalog.empty"),
                width = self.inner_dimen.w - 2 * Size.padding.large,
                alignment = "center",
                face = Font:getFace("infofont"),
            },
        })
    else
        for row = 1, self.grid_rows do
            table.insert(self.item_group, VerticalSpan:new{ width = self.item_margin })
            local row_group = HorizontalGroup:new{}
            table.insert(row_group, HorizontalSpan:new{ width = self.item_margin })
            local line_layout = {}
            for col = 1, self.grid_cols do
                local slot = (row - 1) * self.grid_cols + col
                local entry = items[start_idx + slot]
                if entry then
                    entry.idx = start_idx + slot
                    local item = MosaicItem:new{
                        entry = entry,
                        dimen = self.item_dimen:copy(),
                        menu = self,
                    }
                    if entry.idx == self.itemnumber then selected_number = slot end
                    table.insert(row_group, item)
                    table.insert(line_layout, item)
                    table.insert(page_items, entry)
                else
                    table.insert(row_group, CenterContainer:new{
                        dimen = Geom:new{ w = self.item_width, h = self.item_height },
                        HorizontalSpan:new{ width = 0 },
                    })
                end
                table.insert(row_group, HorizontalSpan:new{ width = self.item_margin })
            end
            table.insert(self.item_group, CenterContainer:new{
                dimen = Geom:new{ w = self.inner_dimen.w, h = self.item_height },
                row_group,
            })
            if #line_layout > 0 then table.insert(self.layout, line_layout) end
        end
        table.insert(self.item_group, VerticalSpan:new{ width = self.item_margin })

        -- Only ever request thumbnails for the CURRENT grid page, not the
        -- whole (possibly hundreds-of-books) result set — the old behavior
        -- queued every book in self.item_table up front on open, which for
        -- a large library meant hundreds of pending downloads (and,
        -- combined with the full-resolution cover bug fixed alongside this,
        -- was a real factor in a Kindle crash). thumbnail_requested_pages
        -- guards against re-queuing the same page every time this function
        -- re-runs to repaint download progress (scheduleThumbnailDownloads'
        -- own step() calls updateItems(nil, true) after each batch) — without
        -- it, each repaint would start a second, redundant download loop
        -- for books already mid-download.
        if not self.thumbnail_requested_pages[self.page] then
            self.thumbnail_requested_pages[self.page] = true
            self:scheduleThumbnailDownloads(page_items)
        end
    end

    self:updatePageInfo(selected_number)
    Menu.mergeTitleBarIntoLayout(self)
    UIManager:setDirty(self.show_parent, function()
        local refresh_dimen = old_dimen and old_dimen:combine(self.dimen) or self.dimen
        return "ui", refresh_dimen
    end)
end

return KolibreCatalog
