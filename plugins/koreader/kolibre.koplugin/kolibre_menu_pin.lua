--[[--
Puts the Kolibre entry near the top of KOReader's Tools menu instead of
leaving it wherever a newly registered plugin lands, which is the end.

How KOReader lets you do this: it reads `<settings_dir>/<prefix>_menu_order.lua`
and merges it over the bundled order table, key by key. So reordering one
entry means writing out the COMPLETE tools list — there is no way to say
"just move this one".

That has a consequence worth stating, because it is the whole reason this
module is more than three lines: the file we write would freeze the menu as
it was the day we wrote it. A KOReader update that adds a tool would never
show it. So the list is rebuilt from the bundled order on EVERY startup and
the file is rewritten if it changed — the file is a cache of a computation,
never a stored preference.

And since the user may have written that file themselves, there are three
cases, not one:

  * the file does not exist          → write ours, marker on the first line
  * the file is ours (marker)        → recompute and rewrite if different
  * the file is the user's           → touch nothing except the position of
                                       our own id, and keep their formatting
                                       choices by rewriting what we parsed

Position: second. High enough to be visible without scrolling, and it does
not claim the first slot, which belongs to whatever KOReader itself puts
there. If the list is shorter than that, our entry goes at the end of it —
`math.min` does that without a special case.

Everything here is best-effort: a menu that comes out in the wrong order is
a cosmetic annoyance, so every step is wrapped and failures are logged and
swallowed. Nothing in this module may stop the plugin from loading.
]]

local DataStorage = require("datastorage")
local dump = require("dump")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")
local util = require("util")

local MENU_ID = "kolibre"
local POSIZIONE = 2
local MARKER = "-- kolibre-menu-pin v1 (generated; delete this file to reset menu order)"

-- Le due liste di menu di KOReader: una per il lettore, una per il gestore
-- di file. La voce va sistemata in entrambe, o compare in alto solo in una.
local LISTE = {
    { prefix = "reader",      modulo = "ui/elements/reader_menu_order" },
    { prefix = "filemanager", modulo = "ui/elements/filemanager_menu_order" },
}

local KolibreMenuPin = { done = false }

--- Nuova lista con la voce Kolibre al posto giusto e in copia singola.
-- Pura: non tocca `tools`, ne restituisce un'altra. Filtrare e reinserire
-- invece di cercare-e-spostare risolve in un passaggio anche il caso di una
-- lista che contiene gia' la voce (da un avvio precedente, o due volte).
local function conLaNostraVoce(tools)
    local lista = {}
    for _, id in ipairs(tools) do
        if id ~= MENU_ID then
            lista[#lista + 1] = id
        end
    end
    table.insert(lista, math.min(POSIZIONE, #lista + 1), MENU_ID)
    return lista
end

--- L'ordine che vogliamo, ricalcolato dal modulo di KOReader.
-- `nil` se quel modulo non ha la forma attesa: meglio non scrivere niente
-- che scrivere una lista di menu vuota.
local function ordineVoluto(modulo)
    local bundled = require(modulo)
    if type(bundled) ~= "table" or type(bundled.tools) ~= "table" then
        return nil
    end
    return conLaNostraVoce(bundled.tools)
end

local function percorso(prefix)
    return DataStorage:getSettingsDir() .. "/" .. prefix .. "_menu_order.lua"
end

local function nostroContenuto(tools)
    return MARKER .. "\nreturn " .. dump({ tools = tools }, nil, true) .. "\n"
end

local function scrivi(path, contenuto, quattro_argomenti)
    local ok, err
    if quattro_argomenti then
        ok, err = util.writeToFile(contenuto, path, true, true)
    else
        ok, err = util.writeToFile(contenuto, path, true)
    end
    if not ok then
        logger.warn("Kolibre: non riesco a scrivere l'ordine del menu", path, err)
    end
end

--- Il file dell'utente: si sposta la nostra voce e basta.
-- Si riscrive l'oggetto che abbiamo letto, non il nostro: cosi' qualunque
-- altra chiave che l'utente abbia messo li' dentro sopravvive.
local function sistemaFileUtente(path, ordine_nostro)
    local letto, suo = pcall(dofile, path)
    if not letto or type(suo) ~= "table" then
        logger.warn("Kolibre: ordine del menu dell'utente illeggibile, lo lascio stare:", path)
        return
    end
    if type(suo.tools) == "table" then
        suo.tools = conLaNostraVoce(suo.tools)
    else
        suo.tools = ordine_nostro
    end
    scrivi(path, dump(suo, nil, true), true)
end

local function sistemaUnaLista(prefix, modulo)
    local ordine = ordineVoluto(modulo)
    if not ordine then return end

    local path = percorso(prefix)

    if not lfs.attributes(path) then
        scrivi(path, nostroContenuto(ordine))
        return
    end

    local esistente = util.readFromFile(path, "r")
    if not esistente then
        logger.warn("Kolibre: ordine del menu illeggibile, lo lascio stare:", path)
        return
    end

    if esistente:sub(1, #MARKER) == MARKER then
        -- Nostro: si riscrive solo se il ricalcolo da' qualcosa di diverso,
        -- cosi' un avvio normale non tocca il disco.
        local contenuto = nostroContenuto(ordine)
        if contenuto ~= esistente then
            scrivi(path, contenuto)
        end
        return
    end

    sistemaFileUtente(path, ordine)
end

--- Una volta per processo, all'avvio del plugin.
function KolibreMenuPin.ensure()
    if KolibreMenuPin.done then return end
    KolibreMenuPin.done = true
    for _, lista in ipairs(LISTE) do
        local ok, err = pcall(sistemaUnaLista, lista.prefix, lista.modulo)
        if not ok then
            logger.warn("Kolibre: non sono riuscito a sistemare il menu", lista.prefix, err)
        end
    end
end

return KolibreMenuPin
