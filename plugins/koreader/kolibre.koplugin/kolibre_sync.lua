-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one.

--[[--
Il protocollo di sincronizzazione v2: il carico, gli ack, la chiusura.

**Trasloco, non riscrittura** (20/11/2026, revisione A2). Questi corpi
vivevano in main.lua — ~7.500 righe, ~170 metodi — e sono stati SPOSTATI qui
con i loro commenti, che portano date e decisioni. I metodi restano
raggiungibili sul plugin con gli stessi nomi: main.lua tiene una delega per
ciascuno (`function Kolibre:X(...) return KolibreSync.X(self, ...) end`),
quindi i chiamanti — menu', automazioni, gli altri moduli — non sono cambiati.
`self`, qui dentro, e' sempre l'istanza del plugin.

Qui dentro stanno:
  * la camminata della cartella dei libri (`_scanLocalBooks`) con la sua
    cache di sessione — vedi sotto;
  * la cassetta degli attrezzi del layout su disco (sanitizeFilename,
    doveScrivere, ensureDir, cartellaScrivibile, urlEncode), esportata
    perche' la usano anche main.lua e gli altri moduli: UNA definizione,
    non tre copie che divergono;
  * fase 0 del sync (`_buildSyncPayload`, `_diskUsage`, `_patchInstallate`),
    gli ack (`_sendAck`), le rimozioni (`_applyDeletions`), la conferma dei
    download e l'orchestrazione intera (`_syncNowRun`, `syncNow`,
    `syncBooksOnly`) fino alla POST /sync/finish.

────────────────────────────────────────────────────────────────────────
LA CAMMINATA SI FA UNA VOLTA PER SESSIONE (E6, 20/11/2026)
────────────────────────────────────────────────────────────────────────

Il difetto e' documentato nel docstring di `FileSulDispositivo`
(backend/app/models.py): la camminata della cartella si faceva in quattro
posti — inizializza libreria, spinta di tutte le annotazioni, carico della
sincronizzazione, calcolo dell'avanzamento — e OGNI volta il risultato si
buttava. Dentro un momento di automazione due azioni (push_pos_all e
pull_pos_all insieme) rifacevano la stessa camminata due volte di fila, con
un partialMD5 per file, su e-ink.

Adesso chi apre una sessione (`apriSessioneScansione`, chiamata da
`_runAutomationMoment` in main.lua) dichiara: «da qui alla chiusura, la
cartella e' una sola». La prima camminata si fa davvero e resta in
`self._scansione_di_sessione`; le successive la riusano. E' un cambiamento
di PRESTAZIONI, non di logica: fra le due camminate risparmiate nessuno
tocca l'insieme dei file dei libri (le posizioni scrivono sidecar, non
libri), quindi tutti i consumatori vedono lo stesso insieme di prima.
Fuori sessione niente cambia: ogni chiamata cammina, come sempre.
]]

local ConfirmBox  = require("ui/widget/confirmbox")
local InfoMessage = require("ui/widget/infomessage")
local UIManager   = require("ui/uimanager")
local lfs         = require("libs/libkoreader-lfs")
local logger      = require("logger")
local util        = require("util")
local sha2        = require("ffi/sha2")
local t           = require("kolibre_lingua").t
local KolibreFinestre = require("kolibre_finestre")
local KolibreManifest = require("kolibre_manifest")
local KolibrePercorsi = require("kolibre_percorsi")

local KolibreSync = {}

-- La versione dichiarata del plugin vive in main.lua (la legge anche il
-- server: backend/app/api/tools.py) e main.lua la consegna qui all'avvio.
local VERSION = nil
function KolibreSync.impostaVersione(v) VERSION = v end

KolibreSync.EBOOK_EXTENSIONS = { epub = true, pdf = true, mobi = true, azw3 = true, fb2 = true, txt = true }
local EBOOK_EXTENSIONS = KolibreSync.EBOOK_EXTENSIONS

-- ── Local library scan ──

-- Walks self.books_dir (one level of subfolders, matching a typical
-- Author/Title layout, plus files directly in the root) and returns a flat
-- list of {path, format, hash}. Uses KOReader's own util.partialMD5, the
-- exact same hash the server computes server-side for the same file.
-- on_progress(count), if given, is called every few files so the caller can
-- keep the UI honest — this walk can take minutes on a device with many
-- books, and gives no other sign of life.
function KolibreSync._scanLocalBooks(self, on_progress)
    -- E6: dentro una sessione la prima camminata vale per tutte.
    local sessione = self._scansione_di_sessione
    if sessione and sessione.risultato then
        return sessione.risultato
    end
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
    if sessione then
        sessione.risultato = found
    end
    return found
end

-- ── La sessione di scansione (E6) ──
--
-- Vedi la testa del file. `apri` non cammina: segna solo che da adesso il
-- primo risultato va tenuto. `chiudi` butta la cache, cosi' un'azione fuori
-- sessione (un «Verifica libreria» a mano dieci minuti dopo) ricammina.
function KolibreSync.apriSessioneScansione(self)
    self._scansione_di_sessione = { risultato = nil }
end

function KolibreSync.chiudiSessioneScansione(self)
    self._scansione_di_sessione = nil
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

-- Dove scrivere un libro che sta arrivando, e la cartella da creare.
--
-- **Il manifesto ha l'ultima parola.** Se dice che quel libro c'e' gia' e il
-- file e' davvero la', si scrive sopra quello: il percorso calcolato dai
-- metadati serve solo per un libro che il dispositivo non ha. Senza questo
-- controllo bastava che i metadati — o la convenzione del nome — fossero
-- cambiati perche' il file nuovo nascesse ACCANTO al vecchio: due copie dello
-- stesso libro, e nessuno dei due programmi se ne accorgeva. Misurato sul
-- Kindle di Paolo il 05/11/2026: 88 libri su 211 avevano un percorso che non
-- si ricalcolava piu' uguale, e 21 erano gia' in doppia copia.
--
-- La decisione vive in `kolibre_percorsi.lua` perche' la' si puo' provare
-- senza KOReader (la prova «una_sola_copia_del_libro»); qui resta solo il
-- guardare il disco e il creare la cartella.
local function esisteIlFile(percorso)
    return lfs.attributes(percorso, "mode") == "file"
end

local function doveScrivere(manifest, chiave, calcolato, fallback_dir)
    local dove, motivo = KolibrePercorsi.doveMettere(
        manifest:get(chiave), calcolato, esisteIlFile)
    if motivo == "gia_presente" and dove ~= calcolato then
        -- L'unico modo di accorgersi dal registro di un dispositivo che un
        -- libro e' stato riscritto al suo posto invece di essere raddoppiato.
        logger.info("Kolibre: riscrivo", dove, "invece di aggiungere", calcolato)
    end
    return dove, KolibrePercorsi.cartellaDi(dove) or fallback_dir
end

-- lfs.mkdir isn't recursive; build the path one segment at a time.
-- **Era scritta in casa, e sbagliava i percorsi relativi.** Ricomponeva il
-- percorso segmento per segmento mettendo una barra davanti a ognuno, quindi
-- `./dict/kolibre-it` diventava `/./dict/kolibre-it`: creava alla RADICE del
-- filesystem una cartella che poi nessuno apriva, perche' chi scriveva il
-- file usava il percorso relativo. Su un Kindle, dove KOReader dice che i
-- suoi dati stanno in `"."` (vedi `kolibre_percorsi.cartellaDeiDati`), era il
-- caso normale e non un caso limite — ed e' il difetto dei dizionari
-- dell'08/11/2026, riprodotto sul KOReader vero.
--
-- Adesso la fa KOReader. `util.makePath` c'e' in tutte le versioni guardate
-- ed e' gia' una dipendenza del plugin (`kolibre_catalog.lua` la usa da
-- sempre per la cache delle copertine, ed e' il motivo per cui quella
-- cartella non ha mai avuto questo problema). Una funzione in meno scritta
-- da noi e' una classe di difetti in meno: ogni cartella creata da qui passa
-- da una funzione che i percorsi relativi li regge.
local function ensureDir(path)
    if type(path) ~= "string" or path == "" then return false end
    if lfs.attributes(path, "mode") == "directory" then return true end
    return util.makePath(path) and lfs.attributes(path, "mode") == "directory"
end

--- La cartella c'e': ma ci possiamo SCRIVERE?
--
-- Sono due domande diverse e il 15/11/2026 ce l'ha insegnato un
-- aggiornamento fallito sul KOReader di sviluppo con «Permission denied» su
-- un file che nessuno aveva chiesto di vedere
-- (`risorse/icona-cronologia.png.kolibre-new.kolibre-parziale`). La cartella
-- `risorse/` esisteva — l'avevo creata io da fuori dal contenitore — ma
-- apparteneva a un altro utente e non dava la scrittura a KOReader. Quindi
-- `ensureDir` diceva «c'e'» e andava tutto avanti fino a sbattere contro un
-- messaggio che non spiegava niente.
--
-- Il modo portatile di chiederlo in Lua e' provarci: non esiste un «posso
-- scrivere qui» che valga su Kindle, Kobo, Android e desktop insieme. Si
-- crea un file minuscolo e lo si toglie subito.
local function cartellaScrivibile(path)
    local prova = path .. "/.kolibre-prova-scrittura"
    local f = io.open(prova, "w")
    if not f then return false end
    f:close()
    os.remove(prova)
    return true
end

local function urlEncode(str)
    return (str:gsub("[^%w%-%.%_%~]", function(c) return string.format("%%%02X", c:byte()) end))
end

-- Gli attrezzi del layout, esportati: li usano anche main.lua (download dal
-- catalogo, dizionari, copertine) e i moduli dell'aggiornamento e
-- dell'accoppiamento. Una definizione sola.
KolibreSync.sanitizeFilename = sanitizeFilename
KolibreSync.esisteIlFile = esisteIlFile
KolibreSync.doveScrivere = doveScrivere
KolibreSync.ensureDir = ensureDir
KolibreSync.cartellaScrivibile = cartellaScrivibile
KolibreSync.urlEncode = urlEncode

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

function KolibreSync._sendAck(self, session_id, downloads, deletions)
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
function KolibreSync._diskUsage(self)
    if type(util.diskUsage) ~= "function" then return nil end
    local ok, info = pcall(util.diskUsage, self.books_dir)
    if not ok or type(info) ~= "table" or not info.total or info.total <= 0 then
        return nil
    end
    return info
end

-- Le userpatch che questo lettore ha nella sua cartella, per la scheda del
-- dispositivo sul web: nome del file e impronta del contenuto.
--
-- L'impronta e non la versione dichiarata, perche' una patch modificata senza
-- cambiarle nome ne' numero — il caso normale mentre la si sviluppa — deve
-- risultare «da aggiornare», e solo l'impronta lo dice.
--
-- Si leggono solo i file che KOReader eseguirebbe davvero (il nome comincia
-- con la cifra della priorita' e un trattino): elencare un file che non parte
-- farebbe dire al server «installata» di una cosa che non gira.
--
-- Torna sempre una lista, anche vuota: "nessuna patch" e' un'informazione.
-- E' il server a distinguerla da "non riportato", che per lui e' l'assenza
-- del campo.
function KolibreSync._patchInstallate(self)
    local elenco = {}
    local cartella = self:_cartellaDellePatch()
    if not cartella or lfs.attributes(cartella, "mode") ~= "directory" then
        return elenco
    end
    for nome_file in lfs.dir(cartella) do
        if nome_file:match("^%d%d*%-.*%.lua$") then
            local contenuto = util.readFromFile(cartella .. "/" .. nome_file, "rb")
            if contenuto then
                table.insert(elenco, { file = nome_file, sha256 = sha2.sha256(contenuto) })
            end
        end
    end
    return elenco
end

function KolibreSync._buildSyncPayload(self, trigger, allow_migration)
    local payload = {
        protocol = 2,
        plugin_version = VERSION,
        trigger = trigger,
        library_token = self.manifest:getToken(),
    }

    -- Dentro pcall: leggere una cartella puo' fallire (permessi, filesystem
    -- smontato), e una sincronizzazione non deve fermarsi per un'informazione
    -- di contorno.
    local ok_patch, patch = pcall(function() return self:_patchInstallate() end)
    payload.patches = ok_patch and patch or {}

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
                -- L'identita' c'e' sempre, qui: queste voci sono per
                -- definizione libri che Kolibre ha consegnato. L'impronta si
                -- manda lo stesso, per i server non ancora aggiornati.
                table.insert(managed, {
                    hash = entry.hash,
                    library = entry.library,
                    calibre_book_id = entry.calibre_book_id,
                    format = entry.format,
                    path = entry.path,
                    pages = entry.pages,
                })
            end
        end
        payload.managed_books = managed
    end
    if #missing_report > 0 then
        payload.missing_books = missing_report
    end
    return payload, missing_keys, nil
end

-- Fase 3. Applies removes[] according to the server-driven policy and acks
-- each with result 'deleted' | 'missing' | 'declined' | 'error'. Async by
-- design: the 'ask' policy on a manual sync shows ONE cumulative ConfirmBox,
-- so the rest of the sync continues in on_done(deleted, deferred, errors)
-- ("deferred" counts both user-declined and postponed-to-manual removals).
function KolibreSync._applyDeletions(self, session_id, removes, policy, interactive, on_done)
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
            text = t("koreader.sync.removal_confirm", { count = #to_delete, list = KolibreFinestre.elenco(titles) }),
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
function KolibreSync.syncBooksOnly(self, interactive, trigger)
    if interactive == nil then interactive = true end
    if not self:_requireReachable(interactive) then return end
    -- allow_migration sempre falso: la scansione iniziale dei libri gia'
    -- presenti puo' durare minuti, e questo e' il comando "veloce" — quella
    -- resta legata a "Sincronizza tutto", che la chiede esplicitamente.
    self:_syncNowRun(interactive, trigger or (interactive and "manual_libri" or "auto_libri"), false, true)
end

function KolibreSync.syncNow(self, interactive, trigger)
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
-- see _showProgressBar's own comment for why this mirrors that earlier
-- project's syncAll() bar exactly. Kept as one flat sequence (handshake, download,
-- pending actions, removals, page counts, notes/positions/backup) even
-- though the real work is callback-chained rather than a plain for-loop,
-- so each phase just calls _showProgressBar(i, SYNC_STEP_COUNT, label)
-- as it starts.
local SYNC_STEP_COUNT = 6

-- solo_libri: si fermano le fasi 4 e 6 (conteggio pagine, note/posizioni/
-- backup). Vedi syncBooksOnly per il perche'.
function KolibreSync._syncNowRun(self, interactive, trigger, allow_migration, solo_libri)
    -- Quanti passi mostra la barra: quattro nel controllo veloce, che si
    -- ferma dopo le rimozioni. Con il totale fisso a sei sembrerebbe
    -- interrotta a due terzi ogni volta.
    local passi = solo_libri and 4 or SYNC_STEP_COUNT

    -- Una sincronizzazione automatica mostra una barra di avanzamento sopra
    -- la pagina che stai leggendo. Spegnendo il popup (Impostazioni) quelle
    -- automatiche diventano mute; quelle chieste a mano rispondono sempre,
    -- perche' un comando che non dice niente sembra rotto. Il muto e' una
    -- chiusura locale a questa chiamata, non un campo di self: cosi' non puo'
    -- restare acceso per sbaglio e zittire qualcos'altro piu' tardi.
    local muto = (not interactive) and not self:_popupDiSincronizzazione()
    local function barra(current, total, label)
        if muto then return end
        self:_showProgressBar(current, total, label)
    end

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
    barra(1, passi, t("koreader.sync.phase_handshake"))
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
    -- Il primo aggancio riuscito, ricordato per sempre: e' l'unica cosa che
    -- il logo della UI dice, e va saputa senza toccare la rete. Un controllo
    -- verso un server spento blocca il lettore per tre secondi, quindi
    -- disegnare la barra non puo' permettersi di chiedere "ci sei?".
    if not self.manifest:getMeta("mai_agganciato") then
        self.manifest:setMeta("mai_agganciato", true)
    end
    self:_rememberRestoreRequest(result.restore_request)
    -- Le stime del server per i libri che il lettore ha gia'. Si applicano
    -- prima dei download: un libro che arriva in questo giro la sua stima ce
    -- l'ha gia' nella consegna, e riscriverla dopo sarebbe un giro a vuoto.
    self.manifest:applicaStimeDelServer(result.server_pages)
    -- Le date di consegna vere, che il plugin da solo non sa: vedi
    -- `KolibreManifest:applicaConsegneDelServer`.
    self.manifest:applicaConsegneDelServer(result.delivered_at)

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
        barra(3, passi, t("koreader.sync.phase_pending_actions"))
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

        -- I dizionari chiesti dal portale, nella stessa fase delle altre cose
        -- messe in coda da la': sono decine di megabyte, quindi solo nella
        -- sincronizzazione completa e non nel controllo veloce dei libri. La
        -- conferma parte solo a download riuscito e verificato: altrimenti la
        -- voce resta in coda sul server e al prossimo giro si riprova, senza
        -- che nessuno debba accorgersene.
        if not solo_libri then
            for _idx, lang in ipairs(result.dictionaries or {}) do
                if self:downloadDictionary(lang, false, muto) then
                    self.api:request("POST", "/api/kolibre/devices/sync/dictionaries/ack", { lang = lang })
                end
            end
        end

        -- Fase 3 (async: continuation carries fasi 4-5 + summary)
        markPhase("download")
        barra(4, passi, t("koreader.sync.phase_removals"))
        self:_applyDeletions(session_id, result.removes or {}, policy, interactive, function(deleted, deferred, delete_errors)
            -- Fase 4: page counts
            markPhase("rimozioni")
            local pages_sent = 0
            if not solo_libri then
                barra(5, passi, t("koreader.sync.phase_pages"))
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
                barra(6, passi, t("koreader.sync.phase_notes_positions_backup"))
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

            -- **La vista si rifa' da se'** (Paolo, 17/11/2026: dopo una sync
            -- che consegna o toglie libri «la vista si deve ricaricare da
            -- sola, cosi' compaiono o spariscono gli autori»). Prima del
            -- riepilogo, non dopo: il riepilogo e' una finestra che aspetta un
            -- tocco, e dietro quel tocco si deve trovare l'elenco giusto.
            --
            -- La condizione e' «e' cambiato qualcosa sul disco»: i download,
            -- le cancellazioni, e le azioni messe in coda dal sito (che
            -- cancellano o riscrivono un file). Una sincronizzazione che non
            -- ha spostato nessun libro non ha niente da far rileggere.
            if downloaded > 0 or deleted > 0 or #applied_action_ids > 0 then
                pcall(function() self:ricaricaLeViste() end)
            end

            -- Le copertine: dopo la fine, in rinvii, senza far aspettare il
            -- riepilogo. Sotto `pcall` perche' sono un extra, e un extra non
            -- deve poter rovinare una sincronizzazione andata bene.
            pcall(function() self:scaricaLeCopertine() end)

            -- Stay silent on a no-op background sync; anything that actually
            -- happened — or any interactive call — is worth a summary.
            if (interactive or downloaded > 0 or deleted > 0 or failed > 0
                    or deferred > 0 or delete_errors > 0) and not muto then
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
                barra(idx, total_sends, item.title or t("koreader.common.download"))
            else
                barra(2, passi, t("koreader.sync.phase_download_books"))
            end
            local ext = (item.format or "EPUB"):lower()
            local title = sanitizeFilename(item.title or string.format("libro_%d", item.calibre_book_id))
            local filename = string.format("%s.%s", title, ext)

            local dir_calcolata = self.books_dir
            if self.folder_layout == "author" and item.author and item.author ~= "" then
                dir_calcolata = self.books_dir .. "/" .. sanitizeFilename(item.author)
            end
            -- Il percorso si decide **prima** di creare la cartella: se il
            -- libro c'e' gia' altrove si scrive la', e creare anche la
            -- cartella calcolata lascerebbe sul dispositivo una cartella
            -- d'autore vuota per ogni libro riscritto al suo vecchio posto.
            local chiave = KolibreManifest.bookKey(item.library, item.calibre_book_id, item.format)
            local local_path, target_dir = doveScrivere(
                self.manifest, chiave, dir_calcolata .. "/" .. filename, self.books_dir)
            ensureDir(target_dir)

            if write_folder_cover and item.folder_cover_url and target_dir ~= self.books_dir
                    and not folder_covers_done[target_dir] then
                folder_covers_done[target_dir] = true
                local cover_path = target_dir .. "/.folder.jpg"
                if not lfs.attributes(cover_path, "mode") then
                    self.api:downloadTo(item.folder_cover_url, cover_path)
                end
            end

            local ok, dl_err = self.api:downloadTo(item.download_url, local_path)
            if ok then
                downloaded = downloaded + 1
                -- no_dirty: the ack below already tells the server about this
                -- book — no need to force a full managed_books report next sync.
                -- **L'impronta si MISURA, non si ricopia.** Fino al
                -- 06/10/2026 qui si scriveva `hash = item.delivery_hash`,
                -- cioe' il numero che il server aveva appena detto —
                -- un'etichetta ricopiata, non una misura. Se l'etichetta era
                -- sbagliata (succede: 130 impronte archiviate su 8247 non
                -- descrivevano il loro file) il dispositivo la faceva propria
                -- e nessuno dei due si accorgeva di niente, finche' una nota
                -- non diventava orfana. Il percorso di scaricamento dal
                -- catalogo lo faceva gia' bene: ora anche questo.
                local misurata = util.partialMD5(local_path) or item.delivery_hash
                self.manifest:set(chiave, {
                    path = local_path,
                    hash = misurata,
                    title = item.title,
                    author = item.author,
                    library = item.library,
                    calibre_book_id = item.calibre_book_id,
                    format = (item.format or ""):upper(),
                    downloaded_at = os.time(),
                    -- La stima del server, che NON e' `pages`: vedi
                    -- l'intestazione di kolibre_manifest.lua. E' lei che da'
                    -- la lunghezza alla barra nella UI.
                    server_pages = item.server_pages,
                }, true)
                -- L'impronta misurata torna al server nell'ack: e' lui che
                -- deve registrare che cosa ha consegnato DAVVERO.
                table.insert(pending_acks, { book_id = item.book_id, ok = true, path = local_path, hash = misurata })
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
function KolibreSync._confirmDownloads(self, sends, interactive, on_proceed, on_skip)
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
            text = t("koreader.sync.downloads_confirm", { count = #sends, list = KolibreFinestre.elenco(titles) }),
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

return KolibreSync
