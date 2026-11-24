-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one.

--[[--
«Initialize library»: i libri gia' sul lettore che Kolibre non gestisce.

**Il comando unico della 1.0.0** (piano approvato da Paolo il 24/11/2026,
punto 2). Tre passi, sempre gli stessi:

  1. **per impronta**: il file e' identico a un libro del server
     (`/scan-unmatched`) → si accoppia, come sempre (una conferma per tutti,
     e una scelta quando lo stesso file sta in piu' biblioteche);
  2. **il file esatto**: quello che nessuna impronta riconosce va al server
     COSI' COM'E' (`/books/upload`) e diventa un libro nuovo, accoppiato al
     lettore. Se le biblioteche in cui si puo' aggiungere sono piu' d'una, si
     chiede quale;
  3. **il riordino** in `Autore/Libro` (`kolibre_riordino.lua`), chiamato da
     `main.lua` alla fine.

**Cosa se n'e' andato, e perche'.** Fino alla 0.33.0 il passo 2 cercava nel
catalogo un libro SIMILE per titolo e autore, e proponeva di sovrascrivere il
file del lettore con la copia del server; quello che non trovava finiva in
un elenco da cancellare a mano. Paolo: «il server deve essere la parte di
smanetto, non il device». Il lettore non perde piu' niente: il suo file e'
quello buono, e i quasi doppioni che arrivano sul server sono un problema
del server, da trattare dopo.

I metodi restano raggiungibili sul plugin con gli stessi nomi (main.lua tiene
una delega per ciascuno). `self`, qui dentro, e' sempre l'istanza del plugin;
`self._init` e' il riepilogo del giro in corso, aperto da `_runLibraryInit`.
]]

local ConfirmBox  = require("ui/widget/confirmbox")
local InfoMessage = require("ui/widget/infomessage")
local Menu        = require("ui/widget/menu")
local UIManager   = require("ui/uimanager")
local logger      = require("logger")
local t           = require("kolibre_lingua").t
local KolibreFinestre = require("kolibre_finestre")
local KolibreManifest = require("kolibre_manifest")
-- La cassetta degli attrezzi del layout su disco vive in kolibre_sync.lua:
-- una definizione sola per tutti.
local urlEncode = require("kolibre_sync").urlEncode

local KolibreAccoppiamento = {}

-- The content fingerprint only covers text-extractable formats.
local CONTENT_FINGERPRINT_EXTENSIONS = { epub = true, fb2 = true, txt = true }

-- Content-level identity for a device file whose hash the server doesn't
-- know (used by the orphan-highlights auto-pairing, _tryAutoPairOrphans): KOReader has no way to read inside a zip/EPUB
-- itself (confirmed: no such library exists anywhere in this plugin or
-- reusable from KOReader's own bundled Lua libs), so the file is uploaded
-- whole to the server, which already has zip/OPF-parsing code (TOC editor,
-- page counter) and computes a content fingerprint there instead. Returns a
-- candidate (id/title/author/formats/library), or nil if unsupported or no
-- match.
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
    if self._init then self._init.accoppiati = self._init.accoppiati + 1 end
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
        self:_mandaINonAccoppiati(unmatched)
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
            self:_mandaINonAccoppiati(unmatched)
        end,
        cancel_callback = function() self:_mandaINonAccoppiati(unmatched) end,
    })
end

-- ── Passo 2: il file esatto ──────────────────────────────────────────────

--- Le biblioteche in cui chi possiede il lettore puo' aggiungere libri.
--- `/libraries` le elenca tutte quelle visibili, con `can_edit`; un server
--- che il campo non lo manda le offre tutte, e il rifiuto arriva da lui.
function KolibreAccoppiamento._biblioteche(self)
    local elenco = self.api:request("GET", "/api/kolibre/devices/libraries", nil, { breve = true })
    local fuori = {}
    for _i, b in ipairs(type(elenco) == "table" and elenco or {}) do
        if b.library and b.can_edit ~= false then table.insert(fuori, b) end
    end
    return fuori
end

function KolibreAccoppiamento._mandaINonAccoppiati(self, unmatched)
    if #unmatched == 0 then
        self:_proponiIlRiordino()
        return
    end
    local biblioteche = self:_biblioteche()
    if #biblioteche == 0 then
        if self._init then self._init.senza_biblioteca = #unmatched end
        self:_proponiIlRiordino()
        return
    end
    local function conferma(biblioteca)
        local nomi = {}
        for _i, item in ipairs(unmatched) do
            table.insert(nomi, "• " .. (item.path:match("([^/]+)$") or item.path))
        end
        UIManager:show(ConfirmBox:new{
            text = t("koreader.library_init.send_confirm", {
                count = #unmatched, list = KolibreFinestre.elenco(nomi),
                library = biblioteca.name or biblioteca.library,
            }),
            ok_text = t("koreader.library_init.send"),
            cancel_text = t("koreader.common.later"),
            ok_callback = function() self:_mandaIFile(unmatched, biblioteca) end,
            cancel_callback = function()
                if self._init then self._init.non_mandati = #unmatched end
                self:_proponiIlRiordino()
            end,
        })
    end
    if #biblioteche == 1 then
        conferma(biblioteche[1])
        return
    end
    local voci = {}
    for _i, b in ipairs(biblioteche) do
        table.insert(voci, {
            text = b.name or b.library,
            callback = function()
                if self._scelta_biblioteca then UIManager:close(self._scelta_biblioteca) end
                conferma(b)
            end,
        })
    end
    table.insert(voci, {
        text = t("koreader.library_init.skip_for_now"),
        callback = function()
            if self._scelta_biblioteca then UIManager:close(self._scelta_biblioteca) end
            if self._init then self._init.non_mandati = #unmatched end
            self:_proponiIlRiordino()
        end,
    })
    self._scelta_biblioteca = Menu:new{
        title = t("koreader.library_init.send_which_library", { count = #unmatched }),
        item_table = voci,
        is_popout = true,
        is_borderless = false,
    }
    UIManager:show(self._scelta_biblioteca)
end

--- Manda i file, uno alla volta, e accoppia quelli che il server accoglie.
function KolibreAccoppiamento._mandaIFile(self, unmatched, biblioteca)
    local mandati, falliti = 0, 0
    for idx, item in ipairs(unmatched) do
        self:_showProgressBar(idx, #unmatched, item.path:match("([^/]+)$") or item.path)
        local nome = item.path:match("([^/]+)$") or item.path
        local url = "/api/kolibre/devices/books/upload?filename=" .. urlEncode(nome)
            .. "&library=" .. urlEncode(biblioteca.library)
            .. "&path=" .. urlEncode(item.path)
        local r, err = self.api:uploadFileForJson(url, item.path)
        if r and r.calibre_book_id and r.library then
            local formato = (r.format or item.format or ""):upper()
            self.manifest:set(KolibreManifest.bookKey(r.library, r.calibre_book_id, formato), {
                path = item.path, hash = r.hash or item.hash,
                title = r.title, author = r.author,
                library = r.library, calibre_book_id = r.calibre_book_id,
                format = formato, downloaded_at = os.time(),
            })
            mandati = mandati + 1
        else
            falliti = falliti + 1
            logger.warn("Kolibre: invio di un libro non accoppiato fallito:", item.path, err)
        end
    end
    self:_closeProgress()
    if self._init then
        self._init.mandati = mandati
        self._init.falliti = falliti
    end
    self:_proponiIlRiordino()
end

return KolibreAccoppiamento
