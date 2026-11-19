--[[--
Le letture misurate in CARATTERI, non in pagine.

**A che domanda risponde.** Una pagina di KOReader non e' una quantita' di
libro: cambiando il corpo del carattere le stesse parole diventano piu'
pagine, e su dati veri un'opera in piu' volumi ha dodici impaginazioni in
cronologia, da 2.687 a 7.342 pagine. Sommare quelle pagine, e sommarle fra
libri diversi, non significa niente. I caratteri si sommano.

**Chi conta, e perche' non siamo noi** (decisione del 19/11/2026, con Paolo).
Questo modulo misura **dove** comincia e dove finisce una pagina — gli
xpointer di crengine, che `getPageXPointer` restituisce subito, senza
estrarre testo — e li manda al server, che il carattere assoluto lo calcola
col suo indice (`services/position_converter/chapter_text_index.py`, che
collassa gli spazi come crengine e salta i marcatori del numero di pagina del
cartaceo). La strada alternativa — il dispositivo scandisce tutto il libro e
dichiara il numero — e' stata scartata per due ragioni misurate:

  1. **Costa.** Per sapere la posizione ASSOLUTA il lettore deve leggere il
     testo di ogni pagina dalla prima: su «La linea d'ombra», 248 pagine,
     sono due secondi e non si vedono; su un libro da 7.342 pagine sono
     oltre un minuto e mezzo di sottofondo **a ogni apertura**.
  2. **Non si verifica piu'.** Un xpointer e' la PROVA; un numero di
     caratteri e' il RISULTATO. Se fra sei mesi si scopre che l'indice del
     server collassa uno spazio in piu', con gli xpointer si ricalcola tutto
     lo storico — con un numero dichiarato dal lettore non si corregge
     niente, e non si sa nemmeno che c'e' da correggere.

Il conteggio di crengine per la pagina si manda **comunque**, perche' costa
una chiamata sola (`getTextFromXPointers` sui due confini che abbiamo gia')
e serve a controllare il server: due misure indipendenti dello stesso tratto
di testo che devono tornare. Se un giorno divergono, lo si sa da dati veri
invece che da un ragionamento.

────────────────────────────────────────────────────────────────────────
PERCHE' QUI E NON IN UNA USERPATCH
────────────────────────────────────────────────────────────────────────

La misura e' nata come userpatch (`patches/2-kolibre-misura-caratteri.lua`),
e quella patch ha fatto il suo lavoro: ha dimostrato su un Kindle vero che le
API di crengine esistono e rispondono. Ma una userpatch si copia a mano, non
si aggiorna, e ce l'ha un lettore solo. Il plugin riceve **gli stessi
eventi** (`onReaderReady`, `onPageUpdate`, `onPosUpdate`), viaggia con
`VERSION`, arriva senza cavo ed e' coperto dalle prove.

La patch **resta installata** finche' questa strada non e' in opera: una
lettura non misurata non si recupera.

────────────────────────────────────────────────────────────────────────
UNA RIGA QUANDO LA PAGINA VIENE LASCIATA
────────────────────────────────────────────────────────────────────────

Come fa KOReader: la durata di una pagina si sa solo quando la si lascia.
Quindi `segnaPagina` chiude la riga precedente e apre quella nuova, e la riga
aperta si chiude anche allo spegnimento e alla chiusura del libro — senza
quei due agganci un libro lasciato aperto la notte darebbe una pagina da
dieci ore. La durata che si scrive e' quella **vera**: tagliarla qui
vorrebbe dire perdere il dato grezzo per sempre, e chi deriva le sessioni
puo' decidere una soglia che qui non sapremmo scegliere.

────────────────────────────────────────────────────────────────────────
I POPUP DELLE NOTE
────────────────────────────────────────────────────────────────────────

Leggere una nota in popup **non gira pagina**: KOReader quel tempo lo somma
alla pagina dove sei fermo, e su un libro con l'apparato di note questo fa
sembrare la lettura piu' lenta di com'e'. Misurato a parte diventa un dato
suo, e i caratteri della nota si sanno perche' il suo html passa dal widget.

Due agganci, su metodi pubblici verificati sulla release installata qui
(v2025.08-146-g8726233) e non su master:
`ReaderLink:showAsFootnotePopup` per l'apertura — che e' anche l'unico posto
che sa QUALE nota, e che puo' rifiutare (modalita' a pagine fisse, xpointer
incoerenti): si conta solo se ha detto di si' — e
`FootnoteWidget:onCloseWidget` per la chiusura, che UIManager chiama per
qualunque strada il popup si chiuda, e quindi vale piu' dei tre callback che
il widget si porta dietro.

**Le note annidate**: toccando un richiamo dentro un popup se ne apre un
altro, e apertura e chiusura possono intrecciarsi. Si tiene una pila e si
chiude l'ultima aperta. Non e' esatto in tutti i casi; e' limitato e
dichiarato, e il caso raro sbaglia di qualche secondo su una nota.

────────────────────────────────────────────────────────────────────────
IL FILE
────────────────────────────────────────────────────────────────────────

Una riga per evento, campi separati da TABULAZIONE — un xpointer non
contiene mai una tabulazione ne' un ritorno a capo, quindi il formato non ha
bisogno di virgolette ne' di fughe. Si scrive in aggiunta e mai si riscrive:
una riga scritta e' scritta anche se la batteria finisce un istante dopo.

Si manda al server con la stessa filigrana delle statistiche
(`/api/kolibre/devices/caratteri/state` da' «da quale istante»), e si pota
solo quello che il server ha confermato di avere: il file non e' il deposito,
e' la coda.
]]

local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")

local KolibreLetture = {}

--: Il numero in testa a ogni riga. Serve a poter cambiare i campi domani
--: senza che un file vecchio diventi illeggibile: chi analizza una riga di
--: una versione che non conosce la salta invece di interpretarla a caso.
KolibreLetture.VERSIONE_FORMATO = 1

KolibreLetture.PAGINA = "p"
KolibreLetture.NOTA = "n"

--: Quante righe al massimo in un invio. Un Kindle che ha letto per un mese
--: senza rete non deve costruire in memoria un corpo di richiesta da
--: megabyte: si manda a lotti e il resto va al giro dopo.
KolibreLetture.MAX_RIGHE_PER_INVIO = 2000

--: I campi, in ordine. L'ordine e' il formato: non si cambia senza alzare
--: VERSIONE_FORMATO.
local CAMPI = {
    "genere", "istante", "durata", "pagina", "totale_pagine",
    "caratteri", "xp_inizio", "xp_fine", "impronta", "biblioteca", "libro",
}

--: L'ordine dei campi, esposto: e' il formato del file **e** l'ordine in cui
--: le righe viaggiano verso il server. Uno solo da ricordare, e dichiarato in
--: due posti che devono combaciare (qui e `services/letture_service.py`).
KolibreLetture.CAMPI = CAMPI

--- Una riga nella forma compatta con cui va al server: un vettore, non un
--- oggetto con i nomi dei campi. Su duemila righe i nomi ripetuti sarebbero
--- centosessanta KB di salita in piu' per dire quello che l'ordine dice
--- gratis.
---
--- **I campi assenti diventano stringa vuota, non nil.** Un nil in mezzo a un
--- vettore Lua e' un buco: `#` diventa indefinito e chi serializza in JSON
--- tronca il vettore o lo trasforma in un oggetto, a seconda di dove sta il
--- buco. Si manda "" e il server lo legge come «assente».
function KolibreLetture.vettore(r)
    local v = {}
    for indice, nome in ipairs(CAMPI) do
        local valore = r[nome]
        v[indice] = (valore == nil) and "" or valore
    end
    return v
end

-- ── Contare i caratteri ─────────────────────────────────────────────────

--- Quanti CARATTERI, non quanti byte.
--
-- KOReader gira su LuaJIT (Lua 5.1), che non ha la libreria utf8: si contano
-- i byte che non sono continuazioni (quelli fuori dall'intervallo 10xxxxxx),
-- che e' esattamente il numero di caratteri di una stringa UTF-8 valida. Su
-- un testo italiano la differenza non e' teorica: ogni accento e ogni
-- virgoletta «» vale due byte e un carattere solo.
function KolibreLetture.contaCaratteri(testo)
    if type(testo) ~= "string" then return 0 end
    local _, n = testo:gsub("[^\128-\191]", "")
    return n
end

--- I caratteri di una nota, dal suo html.
--
-- Si togliono i marcatori e si contano i caratteri di quello che resta. Non
-- e' il conteggio di crengine — e' quello che una persona legge in quel
-- popup, che e' la domanda giusta per «quanto ho letto in nota».
function KolibreLetture.caratteriDiHtml(html)
    if type(html) ~= "string" then return 0 end
    local senza = html:gsub("<[^>]*>", " ")
    -- Il soft-hyphen che crengine aggiunge (0xC2 0xAD) non e' testo letto.
    senza = senza:gsub("\194\173", "")
    senza = senza:gsub("%s+", " ")
    -- Il ritaglio NON e' cosmetico: ogni marcatore diventa uno spazio, quindi
    -- un `<p>ciao</p>` lascerebbe uno spazio davanti e uno dietro e la nota
    -- risulterebbe di sei caratteri invece di quattro. Su mille note e'
    -- un errore sistematico, sempre nello stesso verso.
    senza = senza:gsub("^%s+", ""):gsub("%s+$", "")
    return KolibreLetture.contaCaratteri(senza)
end

-- ── Una riga: scriverla e rileggerla ────────────────────────────────────

local function vuoto(v)
    return v == nil or v == ""
end

--- Da tabella a riga di file. Torna nil se manca l'indispensabile.
function KolibreLetture.formatta(r)
    if type(r) ~= "table" then return nil end
    if r.genere ~= KolibreLetture.PAGINA and r.genere ~= KolibreLetture.NOTA then return nil end
    if type(r.istante) ~= "number" then return nil end
    local pezzi = { tostring(KolibreLetture.VERSIONE_FORMATO) }
    for _indice, nome in ipairs(CAMPI) do
        local v = r[nome]
        if v == nil then
            v = ""
        elseif type(v) == "number" then
            v = string.format("%d", v)
        else
            v = tostring(v)
            -- Un campo che contenesse una tabulazione romperebbe il formato
            -- per tutte le righe che vengono dopo: si rifiuta la riga invece
            -- di scrivere un file che poi non si rilegge.
            if v:find("[\t\n\r]") then return nil end
        end
        pezzi[#pezzi + 1] = v
    end
    return table.concat(pezzi, "\t")
end

--- Da riga di file a tabella. Torna nil per una riga che non si capisce.
function KolibreLetture.analizza(linea)
    if type(linea) ~= "string" or linea == "" then return nil end
    local pezzi = {}
    -- Si cammina a mano invece di usare gmatch con un modello: i campi vuoti
    -- consecutivi (due tabulazioni di fila) con gmatch sparirebbero, e
    -- sparendo sposterebbero tutti i campi dopo di loro.
    local inizio = 1
    while true do
        local taglio = linea:find("\t", inizio, true)
        if not taglio then
            pezzi[#pezzi + 1] = linea:sub(inizio)
            break
        end
        pezzi[#pezzi + 1] = linea:sub(inizio, taglio - 1)
        inizio = taglio + 1
    end
    if tonumber(pezzi[1]) ~= KolibreLetture.VERSIONE_FORMATO then return nil end
    if #pezzi ~= #CAMPI + 1 then return nil end
    local r = {}
    for indice, nome in ipairs(CAMPI) do
        local v = pezzi[indice + 1]
        -- **Un `if`, e non `(v == "") and nil or v`.** Quel modo di scrivere
        -- un ternario in Lua non puo' restituire nil: `true and nil or v`
        -- vale `v`, perche' `and nil` da' nil che e' falso e l'`or` prende il
        -- ramo dopo. I campi vuoti tornavano quindi come stringa vuota, e un
        -- xpointer vuoto che arriva al server come "" invece che come niente
        -- e' un dato finto che nessun controllo vedrebbe.
        if v ~= "" then r[nome] = v end
    end
    if r.genere ~= KolibreLetture.PAGINA and r.genere ~= KolibreLetture.NOTA then return nil end
    for _i, nome in ipairs({ "istante", "durata", "pagina", "totale_pagine", "caratteri", "libro" }) do
        r[nome] = tonumber(r[nome])
    end
    if type(r.istante) ~= "number" then return nil end
    return r
end

-- ── La misura di una pagina ─────────────────────────────────────────────

--- Dove comincia e dove finisce una pagina, e quanti caratteri ha.
--
-- Torna una tabella con `xp_inizio`, `xp_fine`, `caratteri`, oppure nil e il
-- motivo. **Tutto e' protetto**: una misura che fa crollare il programma di
-- chi legge non e' una misura, e' un danno. E una chiamata che non esiste in
-- una versione di KOReader piu' vecchia non deve fermare niente.
function KolibreLetture.misuraPagina(doc, pagina, totale)
    if type(doc) ~= "table" or type(doc.getPageXPointer) ~= "function" then
        return nil, "nessun xpointer: non e' un documento a scorrimento"
    end
    if type(pagina) ~= "number" or pagina < 1 then return nil, "pagina non valida" end
    local ok, xp0 = pcall(doc.getPageXPointer, doc, pagina)
    if not ok or vuoto(xp0) then return nil, "xpointer di inizio vuoto" end
    -- L'ultima pagina non ha un confine destro: non esiste "l'inizio della
    -- pagina dopo". Si dichiara l'inizio e si lascia il resto vuoto, invece
    -- di inventare una fine o di buttare la riga: il tempo passato
    -- sull'ultima pagina di un libro e' un dato che vale.
    if type(totale) == "number" and pagina + 1 > totale then
        return { xp_inizio = xp0 }, nil
    end
    local ok1, xp1 = pcall(doc.getPageXPointer, doc, pagina + 1)
    if not ok1 or vuoto(xp1) then return { xp_inizio = xp0 }, nil end
    local caratteri = nil
    if type(doc.getTextFromXPointers) == "function" then
        local okt, testo = pcall(doc.getTextFromXPointers, doc, xp0, xp1)
        if okt and type(testo) == "string" then
            caratteri = KolibreLetture.contaCaratteri(testo)
        end
    end
    return { xp_inizio = xp0, xp_fine = xp1, caratteri = caratteri }, nil
end

-- ── Lo stato: il libro aperto, la pagina aperta, le note aperte ─────────

function KolibreLetture.new(opts)
    local o = opts or {}
    local self = {
        percorso = o.percorso,
        --: Da dove si prende l'ora. Iniettabile perche' una prova che
        --: dipende dall'orologio vero non e' una prova: non si potrebbe
        --: verificare nessuna durata.
        adesso = o.adesso or os.time,
        libro = nil,
        aperta = nil,
        note = {},
    }
    return setmetatable(self, { __index = KolibreLetture })
end

function KolibreLetture:_scrivi(r)
    local linea = KolibreLetture.formatta(r)
    if not linea or not self.percorso then return false end
    local f = io.open(self.percorso, "a")
    if not f then return false end
    f:write(linea, "\n")
    f:close()
    return true
end

--- Un libro si apre: da qui in poi le righe sono sue.
--
-- `voce` e' quella del manifesto (`findByPath`): porta l'impronta del file e,
-- se il libro e' in biblioteca, biblioteca e id. Un libro che il manifesto
-- non conosce si misura comunque, con la sola impronta: sara' il server a
-- risolverla, o a tenere le righe da parte come fa gia' con le sessioni
-- orfane.
function KolibreLetture:apriLibro(doc, voce)
    -- **Si BUTTA quello che era rimasto aperto, non si scrive** (Paolo,
    -- 19/11/2026: «quando chiudiamo il reader possiamo semplicemente non
    -- salvare quella riga… non la terrei sospesa accorpando i tempi fino alla
    -- riapertura»).
    --
    -- Chiudendo un libro per le vie normali la riga viene scritta subito
    -- (`onCloseDocument`), e allo spegnimento pure: se qui c'e' ancora
    -- qualcosa di aperto, vuol dire che KOReader non e' passato da nessuna
    -- delle due — batteria finita, crollo, processo ucciso. Scriverla
    -- vorrebbe dire inventare una durata che va dall'ultima girata di pagina
    -- a questo riavvio: ore, a volte giorni, e tutte attribuite a una
    -- pagina sola. Meglio perdere l'ultima pagina letta prima di un crollo
    -- che infilare nelle statistiche un numero falso che poi nessuno
    -- distingue da uno vero.
    self:scartaLaPagina()
    self.note = {}
    local totale = nil
    if type(doc) == "table" and type(doc.getPageCount) == "function" then
        local ok, n = pcall(doc.getPageCount, doc)
        if ok then totale = tonumber(n) end
    end
    self.libro = {
        totale_pagine = totale,
        impronta = voce and voce.hash or nil,
        biblioteca = voce and voce.library or nil,
        libro = voce and tonumber(voce.calibre_book_id) or nil,
    }
end

--- La pagina e' cambiata: si chiude quella di prima e si apre questa.
function KolibreLetture:segnaPagina(doc, pagina)
    if not self.libro then return false end
    if type(pagina) ~= "number" then return false end
    if self.aperta and self.aperta.pagina == pagina then return false end
    self:chiudiLaPagina()
    local misura, motivo = KolibreLetture.misuraPagina(doc, pagina, self.libro.totale_pagine)
    if not misura then
        logger.dbg("Kolibre: pagina non misurata:", tostring(motivo))
        -- Senza posizione la riga non serve a niente: il server non saprebbe
        -- dove metterla. Si lascia perdere questa pagina e si va avanti.
        return false
    end
    self.aperta = {
        istante = self.adesso(),
        pagina = pagina,
        xp_inizio = misura.xp_inizio,
        xp_fine = misura.xp_fine,
        caratteri = misura.caratteri,
    }
    return true
end

--- Butta la pagina aperta senza scriverla.
---
--- Serve in un caso solo, e dichiararlo e' il punto: quando ci si accorge che
--- la riga aperta non ha una fine credibile. Vedi `apriLibro`.
function KolibreLetture:scartaLaPagina()
    local c_era = self.aperta ~= nil
    self.aperta = nil
    return c_era
end

--- Scrive la riga della pagina aperta, con la durata vera.
function KolibreLetture:chiudiLaPagina()
    local a = self.aperta
    if not a or not self.libro then return false end
    self.aperta = nil
    local durata = self.adesso() - a.istante
    if durata < 0 then
        -- L'orologio e' andato indietro (fuso cambiato, ora sincronizzata):
        -- una durata negativa non si scrive e non si inventa.
        return false
    end
    return self:_scrivi({
        genere = KolibreLetture.PAGINA,
        istante = a.istante,
        durata = durata,
        pagina = a.pagina,
        totale_pagine = self.libro.totale_pagine,
        caratteri = a.caratteri,
        xp_inizio = a.xp_inizio,
        xp_fine = a.xp_fine,
        impronta = self.libro.impronta,
        biblioteca = self.libro.biblioteca,
        libro = self.libro.libro,
    })
end

--- Si e' aperto il popup di una nota.
--
-- `xp_sorgente` e' dove sta il richiamo NEL TESTO — ed e' quello che conta,
-- perche' colloca l'evento nello stesso spazio di caratteri delle pagine.
-- `xp_bersaglio` dice quale nota e'.
function KolibreLetture:apriNota(xp_sorgente, xp_bersaglio)
    if not self.libro then return false end
    self.note[#self.note + 1] = {
        istante = self.adesso(),
        xp_inizio = xp_sorgente,
        xp_fine = xp_bersaglio,
        pagina = self.aperta and self.aperta.pagina or nil,
    }
    return true
end

--- Il popup si e' chiuso: si chiude l'ultima nota aperta.
function KolibreLetture:chiudiNota(html)
    local n = table.remove(self.note)
    if not n or not self.libro then return false end
    local durata = self.adesso() - n.istante
    if durata < 0 then return false end
    return self:_scrivi({
        genere = KolibreLetture.NOTA,
        istante = n.istante,
        durata = durata,
        pagina = n.pagina,
        totale_pagine = self.libro.totale_pagine,
        caratteri = KolibreLetture.caratteriDiHtml(html),
        xp_inizio = n.xp_inizio,
        xp_fine = n.xp_fine,
        impronta = self.libro.impronta,
        biblioteca = self.libro.biblioteca,
        libro = self.libro.libro,
    })
end

--- Il libro si chiude: niente resta aperto.
function KolibreLetture:chiudiLibro()
    -- Le note prima della pagina: una nota aperta e' DENTRO la pagina su cui
    -- si e' fermi, e chiudere la pagina per prima le lascerebbe senza.
    while #self.note > 0 do self:chiudiNota(nil) end
    self:chiudiLaPagina()
    self.libro = nil
end

-- ── La coda verso il server ─────────────────────────────────────────────

--- Le righe da mandare, dalla filigrana in avanti.
--
-- Si rimanda anche quello che forse il server ha gia': la sovrapposizione
-- costa pochi byte e il doppione lo butta lui, mentre una riga saltata non
-- torna piu'. Le righe illeggibili si contano e si saltano — un file
-- troncato a metta' da una batteria finita non deve bloccare l'invio di tutto
-- il resto.
function KolibreLetture:righeDa(filigrana)
    local righe, saltate = {}, 0
    if not self.percorso or lfs.attributes(self.percorso, "mode") ~= "file" then
        return righe, saltate
    end
    local soglia = tonumber(filigrana) or 0
    local f = io.open(self.percorso, "r")
    if not f then return righe, saltate end
    for linea in f:lines() do
        if #righe >= KolibreLetture.MAX_RIGHE_PER_INVIO then break end
        local r = KolibreLetture.analizza(linea)
        if not r then
            if linea ~= "" then saltate = saltate + 1 end
        elseif r.istante >= soglia then
            righe[#righe + 1] = r
        end
    end
    f:close()
    return righe, saltate
end

--- Butta le righe che il server ha confermato di avere.
--
-- Si riscrive il file solo se c'e' davvero qualcosa da togliere: riscriverlo
-- a ogni sincronizzazione vorrebbe dire, su un lettore, una possibilita' in
-- piu' di perdere tutto per una scrittura interrotta, in cambio di niente.
function KolibreLetture:pota(filigrana)
    local soglia = tonumber(filigrana)
    if not soglia or not self.percorso then return 0 end
    if lfs.attributes(self.percorso, "mode") ~= "file" then return 0 end
    local tenute, buttate = {}, 0
    local f = io.open(self.percorso, "r")
    if not f then return 0 end
    for linea in f:lines() do
        local r = KolibreLetture.analizza(linea)
        if r and r.istante < soglia then
            buttate = buttate + 1
        elseif linea ~= "" then
            tenute[#tenute + 1] = linea
        end
    end
    f:close()
    if buttate == 0 then return 0 end
    local g = io.open(self.percorso .. ".nuovo", "w")
    if not g then return 0 end
    for _i, linea in ipairs(tenute) do g:write(linea, "\n") end
    g:close()
    -- Prima si scrive il nuovo per intero, poi si sostituisce: se la
    -- sostituzione non riesce resta il vecchio, che ha dentro tutto.
    if not os.rename(self.percorso .. ".nuovo", self.percorso) then
        os.remove(self.percorso .. ".nuovo")
        return 0
    end
    return buttate
end

function KolibreLetture:quante()
    local n = 0
    if not self.percorso or lfs.attributes(self.percorso, "mode") ~= "file" then return 0 end
    local f = io.open(self.percorso, "r")
    if not f then return 0 end
    for linea in f:lines() do
        if KolibreLetture.analizza(linea) then n = n + 1 end
    end
    f:close()
    return n
end

return KolibreLetture
