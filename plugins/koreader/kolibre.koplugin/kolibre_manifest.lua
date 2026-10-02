--[[--
Persistent manifest of the books Kolibre itself delivered to this device.

Why this exists: Kolibre only manages the books IT delivered (server queue or
on-device catalog browser) — everything else on the device is invisible to it.
Before this manifest, the only way to tell the server "here's what I hold" was
a full filesystem walk of the books dir with a partial-MD5 hash per file on
EVERY sync, which is slow on e-ink hardware and conflates Kolibre-managed
books with books the user side-loaded. The manifest gives each managed book a
stable identity ("<library>:<calibre_book_id>:<FORMAT>") independent of its
hash, so a normal sync only needs a cheap lfs existence check per entry, and
the expensive partialMD5 runs at most once per book (backfilled lazily, then
cached here).

Storage: a dedicated LuaSettings file next to KOReader's own settings
(DataStorage:getSettingsDir() .. "/kolibre_manifest.lua") — same mechanism as
G_reader_settings, separate file so it survives plugin reinstalls and never
bloats settings.reader.lua.

Entry value shape: {path, hash (partialMD5, may be nil until backfilled),
title, author, library, calibre_book_id, format, downloaded_at, pages}.
library/calibre_book_id/format are duplicated from the key on purpose: the
missing_books report needs them as separate fields and parsing them back out
of the key would break the day a library folder name contains ":".

Migration compromise (v0.2.0 -> v0.3.0): the first v2 sync finds an empty
manifest, does the one-time legacy filesystem scan, and reports those hashes
in managed_books. The /sync response does NOT echo back which of them the
server adopted (and the device can't know library/calibre_book_id on its
own), so scan-adopted entries are stored under the alternative key
"hash:<partialMD5>" with only {path, hash, format}. These entries exist ONLY
to avoid re-scanning on later syncs and to resolve delete requests by path;
"real" "<library>:<id>:<FORMAT>" entries are born from downloads, where the
server-provided identity is known. Deletes never need the key anyway: the
server sends book_id + expected_path with each remove.

The loaded instance is a process-wide singleton: a koplugin is
re-instantiated for every FileManager/Reader context, and two instances each
holding their own cached copy of the same file would silently clobber each
other's writes.

v0.5.0: two extra tables, "annotation_dirty_paths"/"position_dirty_paths" —
an offline queue of "which books might have unpushed annotation/position
changes", populated cheaply by main.lua's onCloseDocument/onSuspend/
onPageUpdate hooks rather than by scanning books_dir. Deliberately keyed by
absolute file path (not the "<library>:<id>:<FORMAT>" manifest key), so it
also works for a book Kolibre doesn't manage yet (side-loaded, still
readable/annotatable). Deliberately independent of the `dirty` flag above —
that one is scoped to managed_books/download-delete reconciliation only.
]]

local DataStorage = require("datastorage")
local LuaSettings = require("luasettings")

local KolibreManifest = {}
KolibreManifest.__index = KolibreManifest

local _instance = nil

function KolibreManifest.load()
    if _instance then return _instance end
    local settings = LuaSettings:open(DataStorage:getSettingsDir() .. "/kolibre_manifest.lua")
    if type(settings:readSetting("books")) ~= "table" then
        settings:saveSetting("books", {})
        settings:flush()
    end
    _instance = setmetatable({ settings = settings }, KolibreManifest)
    return _instance
end

-- Canonical key for a server-identified book.
function KolibreManifest.bookKey(library, calibre_book_id, format)
    return string.format("%s:%s:%s",
        tostring(library), tostring(calibre_book_id), tostring(format or ""):upper())
end

function KolibreManifest:get(key)
    return self.settings:readSetting("books")[key]
end

-- `no_dirty` skips marking the manifest dirty for changes the server already
-- knows about through another channel (download acks, /pages reports, lazy
-- hash backfills) — a dirty manifest forces the next sync to re-send the full
-- managed_books list, which those changes don't require.
function KolibreManifest:set(key, tbl, no_dirty)
    local books = self.settings:readSetting("books")
    books[key] = tbl
    self.settings:saveSetting("books", books)
    if not no_dirty then
        self.settings:saveSetting("dirty", true)
    end
    self.settings:flush()
end

function KolibreManifest:remove(key)
    local books = self.settings:readSetting("books")
    if books[key] == nil then return end
    books[key] = nil
    self.settings:saveSetting("books", books)
    self.settings:saveSetting("dirty", true)
    self.settings:flush()
end

function KolibreManifest:all()
    return self.settings:readSetting("books")
end

function KolibreManifest:count()
    local n = 0
    for _k in pairs(self.settings:readSetting("books")) do n = n + 1 end
    return n
end

-- ── library_token: the server's cheap change-detection token ──
-- Cached from every /sync response; sent back on the next handshake so the
-- server can grant a "light" sync (no managed_books reconciliation).

function KolibreManifest:saveToken(t)
    self.settings:saveSetting("library_token", t)
    self.settings:flush()
end

function KolibreManifest:getToken()
    return self.settings:readSetting("library_token")
end

-- ── dirty flag: "has the manifest changed since the last full managed_books
-- report the server accepted?" — persisted, so it survives a KOReader restart
-- between a local change and the next sync. ──

function KolibreManifest:isDirty()
    return self.settings:readSetting("dirty") and true or false
end

function KolibreManifest:markClean()
    self.settings:saveSetting("dirty", false)
    self.settings:flush()
end

-- ── misc scalar metadata (delete_policy from the last /sync response,
-- last_sync_at, migration_done, ...) ──

function KolibreManifest:setMeta(key, value)
    self.settings:saveSetting(key, value)
    self.settings:flush()
end

function KolibreManifest:getMeta(key)
    return self.settings:readSetting(key)
end

-- ── offline dirty queues: annotations/positions with unpushed local changes
-- (see header comment) — a small private helper shared by both tables so
-- the four public functions per table stay one-liners. ──

local function _dirtySet(self, setting_key)
    local set = self.settings:readSetting(setting_key)
    if type(set) ~= "table" then set = {} end
    return set
end

local function _markDirty(self, setting_key, path)
    if not path then return end
    local set = _dirtySet(self, setting_key)
    set[path] = true
    self.settings:saveSetting(setting_key, set)
    self.settings:flush()
end

local function _dirtyPaths(self, setting_key)
    local set = _dirtySet(self, setting_key)
    local paths = {}
    for path in pairs(set) do table.insert(paths, path) end
    return paths
end

local function _clearDirty(self, setting_key, path)
    local set = _dirtySet(self, setting_key)
    if set[path] == nil then return end
    set[path] = nil
    self.settings:saveSetting(setting_key, set)
    self.settings:flush()
end

local function _clearAllDirty(self, setting_key)
    self.settings:saveSetting(setting_key, {})
    self.settings:flush()
end

function KolibreManifest:markAnnotationsDirty(path) _markDirty(self, "annotation_dirty_paths", path) end
function KolibreManifest:annotationDirtyPaths() return _dirtyPaths(self, "annotation_dirty_paths") end
function KolibreManifest:clearAnnotationDirty(path) _clearDirty(self, "annotation_dirty_paths", path) end
function KolibreManifest:clearAllAnnotationDirty() _clearAllDirty(self, "annotation_dirty_paths") end

-- ── impronta delle annotazioni gia' inviate, per file ──
--
-- Chiudere un libro lo mette in coda, e finora la coda rispediva OGNI VOLTA
-- tutte le sue annotazioni: un libro con 246 note ne rimandava 246, che il
-- server riscriveva identiche a se stesse. Tenendo da parte un'impronta di
-- quello che e' stato mandato l'ultima volta, un libro chiuso e riaperto
-- senza toccare le note non costa piu' niente — ne' rete, ne' lavoro sul
-- server, ne' batteria qui.
--
-- Vive nel manifest e non sul server di proposito: e' una memoria di cosa
-- ho gia' spedito io, non uno stato condiviso da concordare in due.

function KolibreManifest:annotationsDigest(path)
    local d = self.settings:readSetting("annotation_digests")
    return type(d) == "table" and d[path] or nil
end

function KolibreManifest:setAnnotationsDigest(path, digest)
    if not path then return end
    local d = self.settings:readSetting("annotation_digests")
    if type(d) ~= "table" then d = {} end
    if digest == nil then d[path] = nil else d[path] = digest end
    self.settings:saveSetting("annotation_digests", d)
    self.settings:flush()
end

function KolibreManifest:markPositionDirty(path) _markDirty(self, "position_dirty_paths", path) end
function KolibreManifest:positionDirtyPaths() return _dirtyPaths(self, "position_dirty_paths") end
function KolibreManifest:clearPositionDirty(path) _clearDirty(self, "position_dirty_paths", path) end
function KolibreManifest:clearAllPositionDirty() _clearAllDirty(self, "position_dirty_paths") end

return KolibreManifest
