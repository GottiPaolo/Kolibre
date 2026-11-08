-- @kolibre-nome: Characters per page
-- @kolibre-descrizione: Writes a text file recording how many characters each page holds and where it starts, so we can decide whether reading statistics could be measured in characters instead of pages. It does not change how you read, does not touch KOReader's own statistics, and sends nothing anywhere.
-- @kolibre-versione: 2
--
-- The three lines above are read by the server (backend/app/api/tools.py) to
-- describe this patch in the plugin's menu, from which it installs without a
-- cable. They live inside the file on purpose: a list of metadata kept
-- somewhere else would come unstuck from the code at the first rename.
--
-- **This file is in English, and stays in English** (Paolo, 2026-11-08): a
-- patch is not a menu anyone interacts with, it runs silently in the
-- background, and it must be ONE file for everyone. A translated copy would
-- be a second file with a different checksum -- and the checksum is how a
-- device decides whether to update. Whatever a person reads in their own
-- language is served separately, from novita.json.

--[[--
MISURA, NON RACCOGLIE.

Questa non e' una funzione: e' uno strumento di misura, da installare, far
girare qualche giorno, leggere e poi togliere. Non cambia niente di come
KOReader legge, non tocca le sue statistiche, non manda niente a nessuno:
scrive soltanto un file di testo.

────────────────────────────────────────────────────────────────────────
A CHE DOMANDA RISPONDE
────────────────────────────────────────────────────────────────────────

Le statistiche di KOReader contano PAGINE. Una pagina non e' una quantita'
di libro: cambiando il corpo del carattere le stesse parole diventano piu'
pagine, e il tempo passato su una pagina di cinque righe vale come quello
passato su una pagina piena. Da qui il 135% di un libro letto una volta.

Quello che servirebbe contare sono i CARATTERI e la loro POSIZIONE — «la
pagina dei caratteri 16328-17492» invece de «la pagina 37» — perche' quella
misura e' la stessa sotto qualunque impaginazione.

Prima di progettare una raccolta cosi' bisogna sapere tre cose, e nessuna
si puo' sapere leggendo il codice:

  1. **crengine sa dire dove comincia e dove finisce una pagina**, in modo
     stabile? (`getPageXPointer(page)`)
  2. **quanto costa** chiedere il testo di una pagina e contarne i
     caratteri, su un lettore vero e non su un portatile?
     (`getTextFromXPointers(xp0, xp1)`)
  3. **quanto costa farlo per tutto il libro una volta**, che e' quello che
     serve per avere le posizioni assolute?

E una quarta, che e' una speranza: crengine ha gia' dentro di se' una mappa
di pagine «a caratteri» (`buildSyntheticPageMap(caratteri_per_pagina)`), e
KOReader ne tiene l'API pubblica proprio perche' delle userpatch la usano.
Se quella mappa fa quello che sembra, il lavoro e' molto piu' piccolo.

Due righe del rapporto possono dire «assente», e NON e' un difetto:
`getSyntheticPageMapCharsPerPage` e `hasPageMapDocumentProvided` non
esistono nelle versioni piu' vecchie (non sono in v2023.04 ne' in
v2025.04) mentre ci sono in v2026.03. `buildSyntheticPageMap` invece c'e'
da anni. Tutte le chiamate qui sono protette: una che non esiste scrive
«assente» e si va avanti invece di fermare la misura.

Il modo di verificarlo senza indovinare e' interrogare il KOReader
dockerizzato di sviluppo: il comando sta in
la prova «api_di_koreader».

────────────────────────────────────────────────────────────────────────
COSA SCRIVE
────────────────────────────────────────────────────────────────────────

Un solo file, `kolibre-misura-caratteri.log`, nella cartella dati di
KOReader (la stessa dove sta `settings.reader.lua`). Una riga per evento,
leggibile a occhio:

    APERTO   | Fini e inizi | pagine=312 | mappa=no | sintetica=no | car/pag=0
    PAGINA   | p=37 | car=1164 | da=16328 a=17492 | ms=3.1
    SCANSIONE| p=1-20 | car=23110 | ms=58.4
    TOTALE   | pagine=311 | caratteri=486112 | ms=912.7 | ms/pagina=2.9

«da/a» appare solo dopo che la scansione completa e' finita: prima di
allora la posizione assoluta non si sa ancora.

────────────────────────────────────────────────────────────────────────
COME SI INSTALLA, E COME SI TOGLIE
────────────────────────────────────────────────────────────────────────

Si copia questo file in `koreader/patches/` sul lettore (la cartella va
creata se non c'e'), si riavvia KOReader, si legge normalmente per qualche
giorno. Per toglierla: si cancella il file e si riavvia. KOReader ha anche
un interruttore generale per tutte le patch (Strumenti → altro).

Il nome comincia per `2-` di proposito: e' la priorita' «late», cioe' viene
applicata quando l'interfaccia e' gia' pronta. Se qualcosa in questa patch
si rompe, si rompe DOPO l'avvio, non durante: il lettore parte comunque.

Ogni cosa che questa patch fa sta dentro `pcall`. Una misura che fa crollare
il programma di chi legge non e' una misura, e' un danno.
--]]--

local DataStorage = require("datastorage")
local UIManager = require("ui/uimanager")
local logger = require("logger")
local time = require("ui/time")
local ReaderRolling = require("apps/reader/modules/readerrolling")

local PERCORSO = DataStorage:getDataDir() .. "/kolibre-misura-caratteri.log"

-- La scansione completa si fa a pezzi, non tutta insieme: su un libro di
-- mille pagine un giro unico bloccherebbe lo schermo per secondi, e chi
-- legge non deve nemmeno accorgersi che c'e' una misura in corso.
local PAGINE_PER_GIRO = 20
local PAUSA_FRA_I_GIRI = 0.2    -- secondi
local ATTESA_PRIMA_DI_COMINCIARE = 8  -- secondi dall'apertura del libro

local stato = {}  -- per libro: { offset = {pagina -> carattere iniziale}, finita = bool }

local function scrivi(riga)
    local f = io.open(PERCORSO, "a")
    if not f then return end
    f:write(os.date("%Y-%m-%d %H:%M:%S"), " | ", riga, "\n")
    f:close()
end

-- Quanti CARATTERI, non quanti byte. KOReader gira su LuaJIT (Lua 5.1), che
-- non ha la libreria utf8: si contano i byte che non sono continuazioni
-- (cioe' quelli fuori dall'intervallo 10xxxxxx), che e' esattamente il
-- numero di caratteri di una stringa UTF-8 valida. Su un testo italiano la
-- differenza non e' teorica: ogni accento e ogni virgoletta «» vale due
-- byte e un carattere solo.
local function quanti_caratteri(testo)
    if type(testo) ~= "string" then return 0 end
    local _, n = testo:gsub("[^\128-\191]", "")
    return n
end

-- Il testo di UNA pagina, piu' quanto e' costato averlo.
--
-- Il tempo e' quello dell'orologio monotono di KOReader, in microsecondi,
-- non `os.clock()`: os.clock misura il tempo di CPU, e qui interessa
-- quanto resta FERMO lo schermo di chi legge, che e' tempo reale. La
-- misura grossolana di `time.now()` non basta — una chiamata da tre
-- millisecondi non si vedrebbe — quindi si usa `time.monotonic()`.
--
-- Torna caratteri, microsecondi, errore.
local function misura_pagina(doc, pagina, totale)
    if pagina + 1 > totale then
        -- L'ultima pagina non si puo' delimitare: non esiste "l'inizio
        -- della pagina dopo". Si dichiara e non si inventa.
        return nil, nil, "ultima pagina: nessun confine destro"
    end
    local inizio = time.monotonic()
    local xp0 = doc:getPageXPointer(pagina)
    local xp1 = doc:getPageXPointer(pagina + 1)
    if not xp0 or not xp1 or xp0 == "" or xp1 == "" then
        return nil, nil, "xpointer vuoto"
    end
    -- draw_selection = nil: si chiede il testo, non si disegna niente sullo
    -- schermo di chi legge.
    local testo = doc:getTextFromXPointers(xp0, xp1)
    local us = time.to_us(time.monotonic() - inizio)
    if type(testo) ~= "string" then
        return nil, us, "nessun testo fra i due punti"
    end
    return quanti_caratteri(testo), us, nil
end

-- ── Una riga a ogni cambio pagina ───────────────────────────────────────
local function annota_pagina(self, pagina)
    local doc = self.ui and self.ui.document
    if not doc or not pagina then return end
    if self._kolibre_ultima_pagina == pagina then return end
    self._kolibre_ultima_pagina = pagina

    local totale = doc:getPageCount() or 0
    local caratteri, us, errore = misura_pagina(doc, pagina, totale)
    if errore then
        scrivi(string.format("PAGINA   | p=%d | NON MISURATA: %s", pagina, errore))
        return
    end

    local mio = stato[doc.file]
    local posizione = ""
    if mio and mio.finita and mio.offset[pagina] then
        posizione = string.format(" | da=%d a=%d", mio.offset[pagina],
                                  mio.offset[pagina] + caratteri)
    end
    scrivi(string.format("PAGINA   | p=%d | car=%d%s | ms=%.1f",
                         pagina, caratteri, posizione, us / 1000))
end

-- ── La scansione di tutto il libro, a pezzi ─────────────────────────────
local function prosegui_scansione(doc, totale, pagina, accumulato, us_totali)
    if not doc or doc.file == nil then return end
    local mio = stato[doc.file]
    if not mio then return end

    local primo = pagina
    local inizio_giro = time.monotonic()
    local caratteri_giro = 0
    local saltate = 0
    while pagina < primo + PAGINE_PER_GIRO and pagina < totale do
        mio.offset[pagina] = accumulato
        local caratteri, _, errore = misura_pagina(doc, pagina, totale)
        if errore then
            saltate = saltate + 1
        else
            accumulato = accumulato + caratteri
            caratteri_giro = caratteri_giro + caratteri
        end
        pagina = pagina + 1
    end
    local us_giro = time.to_us(time.monotonic() - inizio_giro)
    us_totali = us_totali + us_giro
    scrivi(string.format("SCANSIONE| p=%d-%d | car=%d | saltate=%d | ms=%.1f",
                         primo, pagina - 1, caratteri_giro, saltate, us_giro / 1000))

    if pagina < totale then
        UIManager:scheduleIn(PAUSA_FRA_I_GIRI, function()
            pcall(prosegui_scansione, doc, totale, pagina, accumulato, us_totali)
        end)
    else
        mio.finita = true
        local quante = totale - 1
        scrivi(string.format(
            "TOTALE   | pagine=%d | caratteri=%d | ms=%.1f | ms/pagina=%.2f",
            quante, accumulato, us_totali / 1000,
            quante > 0 and us_totali / 1000 / quante or 0))
    end
end

-- ── All'apertura di un libro ────────────────────────────────────────────
local function annota_apertura(self)
    local doc = self.ui and self.ui.document
    if not doc or not doc.file then return end
    if type(doc.getPageXPointer) ~= "function" then
        -- PDF e compagnia: niente xpointer, niente da misurare qui.
        return
    end

    local titolo = doc.file:match("([^/]+)$") or doc.file
    local totale = doc:getPageCount() or 0

    -- La quarta domanda: crengine ha gia' una mappa a caratteri?
    local function prova(nome)
        if type(doc[nome]) ~= "function" then return "assente" end
        local ok, valore = pcall(function() return doc[nome](doc) end)
        if not ok then return "errore" end
        if valore == nil then return "nil" end
        return tostring(valore)
    end

    scrivi(string.format(
        "APERTO   | %s | pagine=%d | mappa=%s | sintetica=%s | dal_documento=%s | car/pag=%s | etichetta=%s | fonte=%s",
        titolo, totale,
        prova("hasPageMap"), prova("isPageMapSynthetic"),
        prova("hasPageMapDocumentProvided"), prova("getSyntheticPageMapCharsPerPage"),
        prova("getPageMapCurrentPageLabel"), prova("getPageMapSource")))

    if totale < 2 then return end
    if stato[doc.file] then return end  -- gia' misurato in questa sessione
    stato[doc.file] = { offset = {}, finita = false }

    -- Si comincia qualche secondo dopo l'apertura: il momento in cui un
    -- libro si apre e' quello in cui KOReader ha piu' da fare, e una misura
    -- non deve rubargli quel momento.
    UIManager:scheduleIn(ATTESA_PRIMA_DI_COMINCIARE, function()
        pcall(prosegui_scansione, doc, totale, 1, 0, 0)
    end)
end

-- ── I due agganci ───────────────────────────────────────────────────────
local vecchia_pronta = ReaderRolling.onReaderReady
function ReaderRolling:onReaderReady()
    if vecchia_pronta then vecchia_pronta(self) end
    pcall(annota_apertura, self)
end

local vecchia_pagina = ReaderRolling.onPageUpdate
function ReaderRolling:onPageUpdate(nuova_pagina)
    if vecchia_pagina then vecchia_pagina(self, nuova_pagina) end
    pcall(annota_pagina, self, nuova_pagina)
end

-- In modalita' scorrimento le pagine non "cambiano": cambia la posizione.
local vecchia_posizione = ReaderRolling.onPosUpdate
function ReaderRolling:onPosUpdate(nuova_posizione)
    if vecchia_posizione then vecchia_posizione(self, nuova_posizione) end
    pcall(function()
        local doc = self.ui and self.ui.document
        if doc and type(doc.getCurrentPage) == "function" then
            annota_pagina(self, doc:getCurrentPage())
        end
    end)
end

scrivi("PATCH    | caricata")
logger.info("[kolibre] patch di misura dei caratteri caricata; scrive in " .. PERCORSO)
