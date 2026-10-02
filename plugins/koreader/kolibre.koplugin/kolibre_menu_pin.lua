--[[--
Pins the Kolibre menu entry near the top of the Tools menu — "un po' più in
alto, tipo dove si piazzava KoServer" — by maintaining user menu-order
override files, exactly like BookOrbit's own bookorbit_menu_pin.lua (this is
a near-verbatim port of that module, generalized off BookOrbit's own
MARKER/MENU_ID).

KOReader merges <settings_dir>/<prefix>_menu_order.lua over the bundled order
tables per top-level key, so the generated files must carry the complete
tools list. Files created here start with a marker comment and are
regenerated from the bundled order on every startup, so KOReader updates
never drift. A hand-maintained file only ever gets old Kolibre ids replaced
by the current one.

Anchor is a fallback chain, not a single id: KoServer isn't necessarily
installed on every device the user's wording named it as the reference
position for ("un po' più in alto, tipo dove si piazzava KoServer"), but
falling through to the END of the tools list (this module's own
desiredTools would do that if the requested anchor is missing) is the
OPPOSITE of what was asked — so it tries "koserver" first, then "calibre"
(present near the top on every device seen so far — see the real snapshot
in data/backups/1/reader_menu_order.lua), then just position 2 as a last
resort, never the end.
]]

local DataStorage = require("datastorage")
local dump = require("dump")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")
local util = require("util")

local MARKER = "-- kolibre-menu-pin v1 (generated; delete this file to reset menu order)"
local MENU_ID = "kolibre"

local ANCHOR_CHAIN = { "koserver", "calibre" }

local PREFIXES = {
    { prefix = "reader", order_module = "ui/elements/reader_menu_order" },
    { prefix = "filemanager", order_module = "ui/elements/filemanager_menu_order" },
}

local KolibreMenuPin = {
    done = false,
}

local function removeId(tools, menu_id)
    local removed = false
    for i = #tools, 1, -1 do
        if tools[i] == menu_id then
            table.remove(tools, i)
            removed = true
        end
    end
    return removed
end

local function normalizeKolibreIds(tools)
    removeId(tools, MENU_ID)

    local insert_at = nil
    for _idx, anchor in ipairs(ANCHOR_CHAIN) do
        for i, id in ipairs(tools) do
            if id == anchor then
                insert_at = i
                break
            end
        end
        if insert_at then break end
    end
    if not insert_at then
        -- Neither anchor exists on this device — still land near the top,
        -- never at the end (the whole point of this module).
        insert_at = math.min(1, #tools)
    end

    table.insert(tools, insert_at + 1, MENU_ID)
end

local function desiredTools(order_module)
    local bundled = require(order_module)
    if type(bundled) ~= "table" or type(bundled.tools) ~= "table" then
        return nil
    end
    local tools = {}
    for _, id in ipairs(bundled.tools) do
        table.insert(tools, id)
    end
    normalizeKolibreIds(tools)
    return tools
end

local function serializeOurs(tools)
    return MARKER .. "\nreturn " .. dump({ tools = tools }, nil, true) .. "\n"
end

local function isGeneratedByUs(existing)
    return existing:sub(1, #MARKER) == MARKER
end

local function ensureOne(prefix, order_module)
    local tools = desiredTools(order_module)
    if not tools then return end

    local path = DataStorage:getSettingsDir() .. "/" .. prefix .. "_menu_order.lua"

    if not lfs.attributes(path) then
        local ok, err = util.writeToFile(serializeOurs(tools), path, true)
        if not ok then
            logger.warn("Kolibre: cannot write menu order file", path, err)
        end
        return
    end

    local existing = util.readFromFile(path, "r")
    if not existing then
        logger.warn("Kolibre: cannot read menu order file, leaving it alone:", path)
        return
    end

    if isGeneratedByUs(existing) then
        local content = serializeOurs(tools)
        if content ~= existing then
            local ok, err = util.writeToFile(content, path, true)
            if not ok then
                logger.warn("Kolibre: cannot update menu order file", path, err)
            end
        end
        return
    end

    -- Hand-maintained file: replace a stale Kolibre id without touching
    -- anything else the user has customized.
    local parsed, user = pcall(dofile, path)
    if not parsed or type(user) ~= "table" then
        logger.warn("Kolibre: cannot parse user menu order file, leaving it alone:", path)
        return
    end
    if type(user.tools) == "table" then
        normalizeKolibreIds(user.tools)
    else
        user.tools = tools
    end
    local ok, err = util.writeToFile(dump(user, nil, true), path, true, true)
    if not ok then
        logger.warn("Kolibre: cannot update user menu order file", path, err)
    end
end

function KolibreMenuPin.ensure()
    if KolibreMenuPin.done then return end
    KolibreMenuPin.done = true
    for _, entry in ipairs(PREFIXES) do
        local ok, err = pcall(ensureOne, entry.prefix, entry.order_module)
        if not ok then
            logger.warn("Kolibre: menu pin failed for", entry.prefix, err)
        end
    end
end

return KolibreMenuPin
