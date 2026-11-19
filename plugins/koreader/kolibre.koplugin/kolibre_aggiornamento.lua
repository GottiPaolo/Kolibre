-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one.

--[[--
L'auto-aggiornamento del plugin, e le patch installate da qui.

**Trasloco, non riscrittura** (20/11/2026, revisione A2). Questi corpi
vivevano in main.lua e sono stati SPOSTATI qui con i loro commenti, che
portano date e decisioni. I metodi restano raggiungibili sul plugin con gli
stessi nomi: main.lua tiene una delega per ciascuno, quindi i chiamanti non
sono cambiati. `self`, qui dentro, e' sempre l'istanza del plugin.

Qui dentro sta il flusso intero: il controllo della versione e delle patch
(`controllaAggiornamenti`, con il freno sul RIPROPORRE di
kolibre_rinvii.lua), la finestra unica che propone tutto
(`_proponiTuttiGliAggiornamenti`), la sequenza pura che esegue
(`eseguiAggiornamenti` — provata in «riavvio_proposto»), il download col
manifesto e la verifica dei checksum (`_downloadAndInstallUpdate`), il
marcatore che fa riprendere un aggiornamento interrotto
(`_resumePendingUpdate`), e l'installazione/rimozione delle patch con la
loro impronta (`_installaPatch`, `_statoDellaPatch`).

Restano in main.lua, di proposito: `_autoCheckForUpdate` (e' un'azione della
matrice delle automazioni, e il guardiano di «aggiornamento_al_risveglio» la
sorveglia la') e `_patchMenuItems` (e' un menu', cioe' interfaccia, non
flusso).
]]

local ConfirmBox  = require("ui/widget/confirmbox")
local InfoMessage = require("ui/widget/infomessage")
local UIManager   = require("ui/uimanager")
local lfs         = require("libs/libkoreader-lfs")
local logger      = require("logger")
local util        = require("util")
local sha2        = require("ffi/sha2")
local DataStorage = require("datastorage")
local t             = require("kolibre_lingua").t
local lingua_attiva = require("kolibre_lingua").lingua_attiva
-- Quali patch proporre di aggiornare, e quali no: la scelta e' una funzione
-- pura, provabile senza KOReader (vedi la prova «patch_da_aggiornare»).
local KolibrePatch = require("kolibre_patch")
-- Che cosa si e' gia' proposto di aggiornare, e quando: anche questa e' una
-- funzione pura (vedi la prova «aggiornamento_al_risveglio»).
local KolibreRinvii = require("kolibre_rinvii")
local KolibrePercorsi = require("kolibre_percorsi")
-- La cassetta degli attrezzi del layout su disco vive in kolibre_sync.lua:
-- una definizione sola per tutti.
local KolibreSync = require("kolibre_sync")
local ensureDir = KolibreSync.ensureDir
local cartellaScrivibile = KolibreSync.cartellaScrivibile
local urlEncode = KolibreSync.urlEncode

local KolibreAggiornamento = {}

-- La versione dichiarata del plugin vive in main.lua (la legge anche il
-- server: backend/app/api/tools.py) e main.lua la consegna qui all'avvio.
local VERSION = nil
function KolibreAggiornamento.impostaVersione(v) VERSION = v end

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

-- La versione del plugin: solo il controllo, senza nessun messaggio di
-- esito. Torna "nuovo" (e in quel caso ha gia' mostrato la richiesta di
-- aggiornare), "aggiornato", oppure "errore" piu' il motivo.
--
-- Non dice da se' «sei aggiornato» perche' questo e' meta' di un controllo
-- che comprende anche le patch (vedi controllaAggiornamenti): due messaggi
-- di esito di fila sono uno che nasconde l'altro, e il primo si chiude
-- senza averlo letto.
--- C'e' una versione piu' nuova del plugin?
---
--- **Guarda e basta.** Prima questa funzione mostrava anche la finestra, e
--- per questo il controllo doveva tornare subito dopo averla chiamata: con
--- una finestra gia' aperta non si potevano piu' guardare le patch.
--- Separare il guardare dal proporre e' quello che permette di proporre
--- tutto insieme.
---
--- Torna la versione nuova con le sue novita', oppure `nil`. Il secondo
--- valore e' un errore da mostrare, e c'e' solo quando il server non ha
--- risposto: «sei aggiornato» non e' un errore.
function KolibreAggiornamento._versioneNuovaDelPlugin(self)
    local result, err = self.api:request(
        "GET", "/api/tools/plugins/koreader/version?lingua=" .. lingua_attiva())
    if not result or not result.version then return nil, tostring(err) end
    if not _isNewerVersion(result.version, VERSION) then return nil, nil end
    return { versione = result.version, novita = result.novita }, nil
end

-- **Il controllo degli aggiornamenti, plugin e patch in un colpo solo.**
--
-- Sono due cose che arrivano dalla stessa parte (questo server) e che si
-- guardano per lo stesso motivo, ed erano due voci di menu' in due posti
-- diversi — con il risultato che le patch non le controllava nessuno. Ora e'
-- una voce sola (Strumenti ▸ Controlla aggiornamenti), ed e' anche l'azione
-- che le automazioni possono far scattare da se'.
--
-- **Una finestra sola, anche quando c'e' da aggiornare tutti e due** (Paolo,
-- 08/11/2026). Fino a oggi si proponeva prima il plugin e sulle patch si
-- taceva fino al riavvio; poi le si proponeva, e i riavvii erano due.
--
-- **Il presupposto della regola di prima non reggeva.** Diceva: «un
-- aggiornamento del plugin puo' portarsi dietro una patch nuova, quindi
-- proporne una adesso vuol dire proporne una che fra un minuto sarebbe stata
-- un'altra». Ma le patch le serve il SERVER — `/api/tools/koreader/patches`
-- non sa nemmeno quale versione di plugin stia chiedendo — quindi l'elenco
-- che arriva e' gia' quello giusto, e non cambia dopo il riavvio.
--
-- **Quello che resta vero, e sta scritto qui perche' un giorno servira'**: a
-- installare una patch e' il plugin **in esecuzione**, non quello appena
-- scaricato; i file nuovi stanno sul disco ma il codice in memoria e' il
-- vecchio fino al riavvio. Quindi una versione del plugin che correggesse
-- *il modo in cui le patch si installano* va rilasciata da sola. Non e'
-- teoria: coi dizionari, l'08/11, quello arrivato nella stessa
-- sincronizzazione che aggiornava il plugin l'ha scaricato il codice
-- vecchio, ed e' finito nella cartella sbagliata.
--
-- Torna true se ha messo in mezzo una finestra, perche' a chi lo chiama in
-- automatico serve saperlo.
-- Quanto si tace su una proposta lasciata con «Piu' tardi». Non frena il
-- controllo — quello e' a ogni risveglio — ma la finestra: la stessa
-- versione, o la stessa patch con lo stesso contenuto, non si ripropone
-- prima di domani. Qualcosa di diverso si propone subito.
--
-- **Dichiarate QUI, e non in fondo con le altre costanti dei momenti
-- automatici.** In Lua una `local` esiste solo da dove e' scritta in giu':
-- una costante dichiarata sotto la funzione che la usa non da' nessun
-- errore, si legge come una globale e vale `nil`. Qui sarebbe stato un
-- `saveSetting(nil, ...)` e un'attesa di zero secondi — cioe' il freno che
-- non frena, e nessuno che lo dica. Il guardiano della prova
-- «aggiornamento_al_risveglio» controlla l'ordine delle righe.
local UPDATE_PROPOSAL_DEBOUNCE_SECONDS = 24 * 60 * 60
-- La chiave in cui vive quel rinvio: `{ impronta, at }`, vedi
-- kolibre_rinvii.lua.
local UPDATE_PROPOSAL_SETTING = "kolibre_aggiornamenti_rinviati"

function KolibreAggiornamento.controllaAggiornamenti(self, interattivo)
    if not self:_requireReachable(interattivo) then return false end

    local nuova, errore = self:_versioneNuovaDelPlugin()
    if errore then
        if interattivo then
            UIManager:show(InfoMessage:new{ text = t("koreader.update.check_failed", { error = errore }) })
        end
        return false
    end

    local patch = self:_patchDaAggiornare()
    if nuova == nil and #patch == 0 then
        if interattivo then
            UIManager:show(InfoMessage:new{ text = t("koreader.update.all_up_to_date", { version = VERSION }) })
        end
        return false
    end

    -- **Il freno sul riproporre, e solo in automatico.** Dal menu' si
    -- propone sempre: una richiesta esplicita ha sempre una risposta. In
    -- automatico si tace su quello che si e' gia' proposto e che e' stato
    -- lasciato li', ma non su qualcosa di diverso — vedi kolibre_rinvii.lua.
    --
    -- Il rinvio si salva quando la finestra si MOSTRA, non quando si preme
    -- «Piu' tardi»: una finestra chiusa toccando fuori e' un «dopo» come
    -- l'altro, e distinguere i due modi di non rispondere vorrebbe dire
    -- fidarsi di quale callback scatta. Se invece si preme «Aggiorna tutto»
    -- e l'aggiornamento riesce, l'impronta cambia da se'; se fallisce, si
    -- tace un giorno e il menu' resta.
    if not interattivo then
        local impronta = KolibreRinvii.impronta(nuova, patch)
        local rinvio = G_reader_settings:readSetting(UPDATE_PROPOSAL_SETTING)
        if not KolibreRinvii.deveProporre(
                rinvio, impronta, os.time(), UPDATE_PROPOSAL_DEBOUNCE_SECONDS) then
            return false
        end
        G_reader_settings:saveSetting(
            UPDATE_PROPOSAL_SETTING, KolibreRinvii.rinviato(impronta, os.time()))
    end

    self:_proponiTuttiGliAggiornamenti(nuova, patch)
    return true
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

function KolibreAggiornamento._writeUpdateMarker(self, base_path, new_version, entries)
    local f = io.open(base_path .. UPDATE_MARKER_SUFFIX, "w")
    if not f then return false end
    f:write(tostring(new_version), "\n")
    for _idx, entry in ipairs(entries) do
        f:write(entry.staged_path, "\t", entry.target_path, "\n")
    end
    f:close()
    return true
end

function KolibreAggiornamento._removeUpdateMarker(self, base_path)
    os.remove(base_path .. UPDATE_MARKER_SUFFIX)
end

-- Returns new_version, entries — entries is nil (not just empty) when there
-- is no marker at all, so callers can tell "nothing pending" apart from "a
-- marker exists but listed zero files" (which shouldn't happen, but is
-- treated as done-and-safe-to-clear rather than as an error).
function KolibreAggiornamento._readUpdateMarker(self, base_path)
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
function KolibreAggiornamento._applyStagedRenames(self, entries)
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
function KolibreAggiornamento._resumePendingUpdate(self)
    -- `gsub("//+", "/")`: KOReader compone il percorso del plugin unendo una
    -- cartella che finisce gia' con una barra al nome, e quello che arriva
    -- qui e' «.../plugins//kolibre.koplugin». Il sistema le barre doppie le
    -- ignora, ma un messaggio d'errore che le mostra fa perdere tempo a chi
    -- lo legge — ed e' successo il 15/11.
    local base_path = (self.path or "plugins/kolibre.koplugin"):gsub("//+", "/")
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

--- Scarica e installa il plugin nuovo. Torna `true` solo se e' andata.
---
--- `senza_riavvio` serve a chi aggiorna **anche** le patch nello stesso
--- gesto: la richiesta di riavvio si fa una volta alla fine, su quello che
--- e' davvero riuscito, e non due volte di fila (vedi
--- `_proponiTuttiGliAggiornamenti`).
function KolibreAggiornamento._downloadAndInstallUpdate(self, new_version, senza_riavvio)
    -- `?lingua=`: i file che arrivano devono essere nella stessa lingua di
    -- quelli installati, altrimenti l'aggiornamento riporta il plugin in
    -- inglese. Un server vecchio ignora il parametro e risponde come prima.
    local manifest, err = self.api:request(
        "GET", "/api/tools/plugins/koreader/manifest?lingua=" .. lingua_attiva())
    if not manifest or not manifest.files then
        UIManager:show(InfoMessage:new{ text = t("koreader.update.manifest_failed", { error = tostring(err) }) })
        return false
    end

    -- `gsub("//+", "/")`: KOReader compone il percorso del plugin unendo una
    -- cartella che finisce gia' con una barra al nome, e quello che arriva
    -- qui e' «.../plugins//kolibre.koplugin». Il sistema le barre doppie le
    -- ignora, ma un messaggio d'errore che le mostra fa perdere tempo a chi
    -- lo legge — ed e' successo il 15/11.
    local base_path = (self.path or "plugins/kolibre.koplugin"):gsub("//+", "/")
    local staged = {}
    local failed = nil
    -- Una cartella si controlla una volta sola, non venti: la prova di
    -- scrittura crea e cancella un file, e farlo per ogni file del plugin
    -- sarebbe venti scritture inutili su una scheda SD.
    local cartelle_controllate = {}

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
        -- Stessa lingua del manifest: le impronte da verificare sono quelle.
        remote_path = remote_path .. "?lingua=" .. lingua_attiva()

        local target_path = base_path .. "/" .. rel_path
        local staged_path = target_path .. ".kolibre-new"
        local dir = target_path:match("^(.*)/[^/]+$")
        -- Una cartella nuova DEVE poter nascere qui: il plugin ne ha
        -- guadagnata una il 15/11 (`risorse/`, i disegni della UI) e
        -- l'aggiornamento di chi aveva la versione prima deve crearla da
        -- se'. `ensureDir` lo fa, ma il suo esito non va buttato via: se la
        -- cartella non si puo' creare, o c'e' ma non e' scrivibile, si dice
        -- QUALE cartella e si smette, invece di far fallire il download di
        -- un file con un messaggio che parla di un file temporaneo.
        if dir and not cartelle_controllate[dir] then
            if not ensureDir(dir) then
                failed = { path = rel_path, err = t("koreader.update.dir_failed", { dir = dir }) }
                break
            end
            if not cartellaScrivibile(dir) then
                failed = { path = rel_path, err = t("koreader.update.dir_readonly", { dir = dir }) }
                break
            end
            cartelle_controllate[dir] = true
        end

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
        return false
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
        return false
    end

    self:_removeUpdateMarker(base_path)
    -- Prima qui c'era un avviso che diceva «riavvia KOReader per applicare le
    -- modifiche»: una cosa da fare, lasciata a chi legge, e il plugin nuovo
    -- intanto non girava. Adesso il riavvio si **propone**, come si fa gia'
    -- per le patch dal 03/11 — stessa funzione, cosi' non ci sono due modi
    -- di chiedere la stessa cosa.
    --
    -- Un riavvio **solo** anche quando si aggiorna anche una patch: in quel
    -- caso la richiesta la fa chi ha chiesto tutto, alla fine.
    if not senza_riavvio then
        self:_chiediRiavvio(
            t("koreader.update.done", { version = new_version }),
            t("koreader.update.restart_needed")
        )
    end
    return true
end

-- ── Patch per KOReader, installate dal plugin ──
--
-- **Cos'e' una userpatch.** KOReader, all'avvio, esegue i file Lua che
-- trova nella sua cartella `patches/`. Servono a cambiare il suo
-- comportamento dall'esterno, senza ricompilarlo e senza aspettare che una
-- modifica venga accettata nel suo progetto: e' il meccanismo con cui si
-- aggiunge una misura, o si cambia il modo in cui conta qualcosa.
--
-- **Perche' installarle da qui.** Si installano copiando un file nella
-- cartella giusta, cioe' attaccando il lettore al computer con un cavo.
-- Per una patch che deve girare qualche giorno e poi essere togliata, il
-- cavo e' esattamente il motivo per cui la misura non si fa: due cavi (uno
-- per metterla, uno per toglierla) sono due occasioni per rinunciare. Il
-- plugin il server ce l'ha gia' davanti e lo interroga da sempre per
-- aggiornare se stesso; le patch passano dalla stessa strada.
--
-- **Cosa puo' andare storto, detto chiaro.** Una patch e' codice che gira
-- a ogni avvio, quindi si chiede conferma e si mostra cosa fa prima di
-- installarla. Non puo' pero' impedire a KOReader di partire: lui le
-- esegue dentro `pcall` e, se una fallisce, scrive l'errore e continua
-- (vedi `frontend/userpatch.lua`). E KOReader ha un suo interruttore
-- generale che le disattiva tutte: se e' tirato, qui lo si dice, perche'
-- altrimenti si installerebbe qualcosa che non parte senza capire perche'.

-- Il nome del file dice a KOReader QUANDO eseguirla: la prima cifra e' la
-- priorita' (2 = dopo che l'interfaccia e' pronta). Non si tocca.
-- Il percorso sta in kolibre_percorsi.lua, con la sua prova: la prima
-- versione di questa funzione chiamava `DataStorage:getPatchesDir()`, che
-- esiste solo su master di KOReader, e su una versione pubblicata faceva
-- crollare il plugin all'apertura del menu'. Vedi quel modulo per il
-- perche', e la prova «percorso_delle_patch» lo riproduce.
function KolibreAggiornamento._cartellaDellePatch(self)
    return KolibrePercorsi.cartellaDellePatch(DataStorage, lfs.currentdir)
end

-- L'interruttore generale delle patch di KOReader. Attenzione: anche questo
-- e' solo su master (`userpatch.arePatchesDisabled`), quindi su una versione
-- pubblicata il file non esiste e questo controllo dira' sempre "non
-- disattivate" — che li' e' la verita', perche' quell'interruttore non c'e'.
function KolibreAggiornamento._patchDisattivateDaKOReader(self)
    local cartella = self:_cartellaDellePatch()
    if not cartella then return false end
    return lfs.attributes(cartella .. "/.patches_disabled", "mode") == "file"
end

-- "assente" | "uguale" | "diversa" — confrontando l'impronta, non la data:
-- una patch ricopiata identica non e' una patch nuova, e una modificata
-- con lo stesso nome lo e'.
function KolibreAggiornamento._statoDellaPatch(self, patch)
    local cartella = self:_cartellaDellePatch()
    if not cartella then return "assente" end
    local percorso = cartella .. "/" .. patch.file
    if lfs.attributes(percorso, "mode") ~= "file" then return "assente" end
    if not patch.sha256 then return "uguale" end
    local contenuto = util.readFromFile(percorso, "rb")
    if not contenuto then return "diversa" end
    return sha2.sha256(contenuto) == patch.sha256 and "uguale" or "diversa"
end

-- `senza_riavvio` serve a chi installa piu' di una patch in fila (il
-- controllo automatico): la richiesta di riavvio va fatta una volta alla
-- fine, non una per patch. Torna true solo se il file nuovo e' al suo posto,
-- cosi' chi chiama sa quante ne sono passate davvero.
function KolibreAggiornamento._installaPatch(self, patch, senza_riavvio)
    local cartella = self:_cartellaDellePatch()
    if not cartella then
        UIManager:show(InfoMessage:new{ text = t("koreader.patches.dir_unknown") })
        return false
    end
    if not ensureDir(cartella) then
        UIManager:show(InfoMessage:new{ text = t("koreader.patches.dir_failed", { dir = cartella }) })
        return false
    end

    local destinazione = cartella .. "/" .. patch.file
    local in_arrivo = destinazione .. ".kolibre-new"
    local indirizzo = "/api/tools/koreader/patches/file/" .. urlEncode(patch.file)

    local ok, errore = self.api:downloadTo(indirizzo, in_arrivo)

    -- Un 200 con il file sul disco non prova che i byte siano tutti: una
    -- connessione che cade a meta' lascia un file corto. Una patch corta e'
    -- un file Lua che non compila, cioe' un errore a ogni avvio: qui il
    -- controllo dell'impronta non e' prudenza, e' l'unica cosa che impedisce
    -- di installare un errore.
    if ok and patch.sha256 then
        local contenuto = util.readFromFile(in_arrivo, "rb")
        if not contenuto or sha2.sha256(contenuto) ~= patch.sha256 then
            ok, errore = false, "checksum_mismatch"
        end
    end

    if not ok then
        os.remove(in_arrivo)
        UIManager:show(InfoMessage:new{
            text = t("koreader.patches.install_failed", { name = patch.nome, error = tostring(errore) }),
        })
        return false
    end

    os.remove(destinazione)
    local rinominato = os.rename(in_arrivo, destinazione)
    if not rinominato then
        os.remove(in_arrivo)
        UIManager:show(InfoMessage:new{
            text = t("koreader.patches.install_failed", { name = patch.nome, error = "rename" }),
        })
        return false
    end

    if not senza_riavvio then
        self:_chiediRiavvio(t("koreader.patches.installed", { name = patch.nome }))
    end
    return true
end

function KolibreAggiornamento._rimuoviPatch(self, patch)
    local cartella = self:_cartellaDellePatch()
    if not cartella then
        UIManager:show(InfoMessage:new{ text = t("koreader.patches.dir_unknown") })
        return
    end
    local percorso = cartella .. "/" .. patch.file
    os.remove(percorso)
    if lfs.attributes(percorso, "mode") == "file" then
        UIManager:show(InfoMessage:new{ text = t("koreader.patches.remove_failed", { name = patch.nome }) })
        return
    end
    self:_chiediRiavvio(t("koreader.patches.removed", { name = patch.nome }))
end

-- Una patch — e dal 08/11/2026 anche il plugin — entra in vigore all'avvio,
-- quindi finche' non si riavvia non e' cambiato NIENTE: e' il genere di cosa
-- che si dimentica e si scambia per "non funziona".
--
-- **Non e' un avviso, e' una proposta.** `UIManager:askForRestart` mostra
-- «Riavvia ora / Piu' tardi» — verificato sul KOReader che gira (v2026.03):
-- il gestore dell'evento `Restart` in `device/generic/device.lua` costruisce
-- una ConfirmBox quando il dispositivo dichiara di saper riavviare, e un
-- avviso semplice quando no. Sul Kindle dichiara di saperlo: il predefinito
-- generico e' «si'» e l'unica classe di dispositivo che lo nega e' Android.
-- Resta comunque il ripiego qui sotto, perche' il metodo che si chiama e'
-- di KOReader e non nostro.
--
-- `spiegazione` e' la riga che dice PERCHE' serve il riavvio: quella delle
-- patch non vale per il plugin, e dirne una sbagliata e' peggio che non
-- dirla.
function KolibreAggiornamento._chiediRiavvio(self, messaggio, spiegazione)
    local testo = messaggio .. "\n" .. (spiegazione or t("koreader.patches.restart_needed"))
    if type(UIManager.askForRestart) == "function" then
        UIManager:askForRestart(testo)
    else
        UIManager:show(InfoMessage:new{ text = testo })
    end
end

-- Le patch installate che sul server sono cambiate.
--
-- Sotto pcall per intero: e' un controllo di contorno dentro un momento in
-- cui la cosa importante e' un'altra (un risveglio, la rete che torna), e un
-- errore qui — una cartella illeggibile, una risposta strana — non deve
-- impedire il resto. Tutta la parte delicata, cioe' cosa proporre e cosa no,
-- sta in kolibre_patch.lua, dove si prova senza KOReader.
function KolibreAggiornamento._patchDaAggiornare(self)
    local ok, da_aggiornare = pcall(function()
        if not self:_cartellaDellePatch() then return {} end
        local risposta = self.api:request("GET", "/api/tools/koreader/patches")
        return KolibrePatch.daAggiornare(
            risposta and risposta.patches or nil,
            function(patch) return self:_statoDellaPatch(patch) end,
            self:_patchDisattivateDaKOReader()
        )
    end)
    if not ok or type(da_aggiornare) ~= "table" then return {} end
    return da_aggiornare
end

--- Esegue in fila gli aggiornamenti scelti, e dice com'e' andata.
---
--- **Pura rispetto all'interfaccia**: riceve le funzioni che installano, non
--- sa che cosa siano, e non mostra niente. E' il modo in cui la sequenza che
--- conta — quella in cui ci sono da aggiornare **tutti e due** — si prova
--- senza un dispositivo.
---
--- `elenco` e' una lista di `{ nome, installa }`, gia' nell'ordine giusto.
--- Torna due liste: quelle riuscite e quelle no. Un pezzo che fallisce non
--- ferma gli altri — sono indipendenti, e una patch che non si scarica non
--- e' un motivo per rinunciare al plugin.
function KolibreAggiornamento.eseguiAggiornamenti(elenco)
    local fatte, fallite = {}, {}
    for _idx, voce in ipairs(elenco or {}) do
        local ok = false
        if type(voce.installa) == "function" then ok = voce.installa() and true or false end
        table.insert(ok and fatte or fallite, voce.nome)
    end
    return fatte, fallite
end

--- Una voce dell'elenco: il nome, e sotto cosa cambia.
---
--- Sotto il nome di ognuna e non in un blocco unico in fondo: con piu' cose
--- da aggiornare, un blocco in fondo non si capirebbe a chi si riferisce.
local function _voceDaAggiornare(nome, novita)
    local riga = "• " .. nome
    if type(novita) == "string" and novita ~= "" then
        -- L'etichetta serve perche' sotto un nome, in un elenco, una frase
        -- nuda si legge come una seconda riga del nome. `nil` o vuoto non e'
        -- un errore: la voce compare comunque, senza questa parte.
        riga = riga .. "\n   " .. t("koreader.update.whats_new") .. " " .. novita
    end
    return riga
end

--- **Una finestra sola per tutto quello che c'e' da aggiornare.**
---
--- `nuova` e' la versione nuova del plugin (o `nil`), `patch` l'elenco delle
--- patch da sostituire (eventualmente vuoto). Almeno uno dei due c'e':
--- `controllaAggiornamenti` non chiama questa funzione per niente.
---
--- **Le patch prima, il plugin dopo.** Non e' indifferente: lo scambio dei
--- file del plugin e' la parte delicata, protetta da un marcatore che
--- permette di riprendere un aggiornamento interrotto, e va fatta per
--- ultima — subito prima del riavvio, con meno tempo possibile fra le due.
---
--- **Se un pezzo fallisce, gli altri restano installati.** Ognuno e'
--- indipendente dagli altri: una patch che non si scarica non e' un motivo
--- per rinunciare al plugin, e viceversa. Il riavvio si chiede solo se
--- qualcosa e' davvero cambiato, e dice cosa — compreso quello che non e'
--- andato, perche' chi ha premuto «Aggiorna tutto» deve sapere che «tutto»
--- non e' stato.
function KolibreAggiornamento._proponiTuttiGliAggiornamenti(self, nuova, patch)
    local voci = {}
    if nuova then
        table.insert(voci, _voceDaAggiornare(
            t("koreader.update.plugin_line", { version = nuova.versione, current = VERSION }),
            nuova.novita))
    end
    for _idx, p in ipairs(patch) do
        table.insert(voci, _voceDaAggiornare(p.nome or p.file, p.novita))
    end

    UIManager:show(ConfirmBox:new{
        text = t("koreader.update.available_list", { items = table.concat(voci, "\n") }),
        ok_text = t("koreader.update.update_all"),
        ok_callback = function()
            -- L'ordine e' quello di questa lista: **le patch prima, il
            -- plugin dopo**.
            local da_fare = {}
            for _idx, p in ipairs(patch) do
                table.insert(da_fare, {
                    nome = p.nome or p.file,
                    installa = function() return self:_installaPatch(p, true) end,
                })
            end
            if nuova then
                table.insert(da_fare, {
                    nome = "Kolibre v" .. nuova.versione,
                    installa = function() return self:_downloadAndInstallUpdate(nuova.versione, true) end,
                })
            end

            local fatte, fallite = KolibreAggiornamento.eseguiAggiornamenti(da_fare)
            if #fatte == 0 then return end
            local messaggio = t("koreader.update.updated_list", { names = table.concat(fatte, ", ") })
            if #fallite > 0 then
                messaggio = messaggio .. "\n" ..
                    t("koreader.update.failed_list", { names = table.concat(fallite, ", ") })
            end
            self:_chiediRiavvio(messaggio, t("koreader.update.restart_needed"))
        end,
    })
end

return KolibreAggiornamento
