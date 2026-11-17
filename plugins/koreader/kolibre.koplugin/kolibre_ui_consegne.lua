-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one.

--[[--
Gli ultimi libri che il server ha mandato su questo dispositivo.

**Da zero: a che domanda risponde.** La libreria e' ordinata per nome, ed e'
giusto cosi': e' un posto in cui si cerca un libro che si sa gia' come si
chiama. Ma ogni tanto la domanda e' un'altra — «cos'e' arrivato?» — e in un
elenco alfabetico non si vede: i libri nuovi sono sparsi fra i vecchi,
ognuno sotto la sua lettera.

**Perche' una finestra e non un ordinamento.** Il 16/11/2026 l'avevo fatto
come un ordinamento da scegliere in un menu. Paolo l'ha corretto: «non
volevo un ordinamento dei libri per data, ma un vero e proprio pannello con
gli ultimi invii dal server, che si apra un po' come la cronologia in una
finestra a se'». La differenza non e' di gusto. Un ordinamento **ti fa
perdere l'elenco che avevi**: per guardare cos'e' arrivato ieri dovevi
scompaginare la libreria, e poi ricordarti di rimetterla a posto. Una
finestra si apre, si guarda e si chiude, e sotto la libreria e' rimasta
dov'era. In piu' qui ogni riga puo' dire **quando** e' arrivata, che in un
elenco ordinato per data e' l'unica cosa che vuoi sapere e che in una
libreria sarebbe rumore.

**Si apre tenendo premuto il tasto della casa** (Paolo, 16/11/2026): non un
sesto tasto in cima, ma la stessa domanda fatta da vicino — la casa dice
«tutta la libreria», tenendola premuta si chiede «e di nuovo, cosa c'e'?».

**Da dove viene la data, e perche' NON da qui** (corretto il 17/11/2026,
dopo una segnalazione di Paolo: «non capisco che ordinamento sta usando»).

La prima versione usava `downloaded_at`, il campo che il plugin si scrive da
se'. Sembrava la cosa ovvia e non lo era: quel campo dice **quando la riga
del manifesto e' stata scritta**, che coincide con la consegna solo quando il
libro e' arrivato davvero scaricandolo. Si scrive anche quando il libro sul
dispositivo **c'era gia'** e Kolibre lo riconosce (`_linkHashMatch`), e la
vecchia migrazione ne adottava in blocco tutti quelli che trovava — tutti
nello stesso secondo. Misurato sul Mac di Paolo: **25 libri su 29 in due soli
istanti**, cioe' un pannello in cui l'ordine fra venticinque righe non
significava niente.

Il server invece lo sa per davvero (`DeviceBook.synced_at`, scritto quando il
download riesce) e lo manda a ogni sincronizzazione, insieme alle stime delle
pagine. Il plugin lo tiene come `consegnato_il`. Sul Kindle di Paolo quelle
date sono sparse su diciannove giorni fra luglio e novembre: la storia vera,
che il manifesto non aveva.

**`downloaded_at` resta come ripiego**, per la finestra fra l'installazione di
questa versione e la prima sincronizzazione — dopo, non serve piu'.

**Un libro senza nessuna delle due date non si butta: va in fondo**, e la sua
riga non scrive niente. Metterlo in cima direbbe una cosa falsa, toglierlo ne
direbbe un'altra. «Non lo so» non e' «oggi».
]]

local BookList = require("ui/widget/booklist")
local lfs = require("libs/libkoreader-lfs")
local DataStorage = require("datastorage")
local Elenco = require("kolibre_ui_elenco")
local KolibreCopertine = require("kolibre_copertine")
local t = require("kolibre_lingua").t

--: Quante voci. Come la cronologia, e per la stessa ragione: oltre una
--  cinquantina di righe l'elenco non si guarda piu', si gira e basta.
local QUANTE = 50

local KolibreConsegne = Elenco:extend{
    chiave = "consegne",
}

function KolibreConsegne.aperta() return Elenco.apertaDi("consegne") end

function KolibreConsegne:titolo() return t("koreader.ui.consegne_titolo") end
function KolibreConsegne:vuoto() return t("koreader.ui.consegne_vuoto") end

--- Le voci: i libri del manifesto, dal piu' recente.
function KolibreConsegne:voci()
    local cartella_copertine = KolibreCopertine.cartella(DataStorage)
    local tutte = {}
    for _percorso, m in pairs(self:_manifestoPerPercorso()) do
        -- **Solo i libri che ci sono ancora.** Il manifesto ricorda anche
        -- quelli cancellati a mano dal dispositivo, e qui il tocco apre: una
        -- riga che si tocca e non apre niente e' una riga che mente. E' la
        -- stessa regola della cronologia.
        if m.path and lfs.attributes(m.path, "mode") == "file" then
            table.insert(tutte, m)
        end
    end
    -- La data del server se c'e', la nostra altrimenti. Vedi in testa al
    -- file: la seconda e' spesso la data dell'adozione, non della consegna.
    local function consegna(m)
        return m.consegnato_il or m.downloaded_at
    end
    table.sort(tutte, function(a, b)
        local da, db = consegna(a) or -1, consegna(b) or -1
        if da ~= db then return da > db end
        -- A parita' di istante — un invio in blocco arriva tutto nello stesso
        -- secondo — si ordina per titolo: e' l'unico ordine che non cambia
        -- fra un'apertura e l'altra.
        return (a.title or a.path or "") < (b.title or b.path or "")
    end)

    local voci = {}
    for _i, m in ipairs(tutte) do
        if #voci >= QUANTE then break end
        table.insert(voci, {
            path = m.path,
            titolo = m.title or m.path:match("([^/]+)$"),
            autore = m.author,
            stima_pagine = m.server_pages,
            info = BookList.getBookInfo(m.path),
            immagine = KolibreCopertine.perVoce(cartella_copertine, m),
            -- **Quando e' arrivato, a destra della riga** (Paolo,
            -- 16/11/2026). Fino a stamattina stava SOTTO il titolo, al posto
            -- dello stato di lettura; spostandola a destra si guadagnano due
            -- cose: la riga sotto il titolo torna a dire quanto hai letto —
            -- che e' un'informazione in piu' invece di una ripetuta — e la
            -- data sta in colonna, dove la si confronta fra una riga e
            -- l'altra invece di cercarla in mezzo al testo.
            --
            -- Nessun «Consegnato» davanti: in questa finestra la data e' per
            -- forza quella della consegna, e lo dice il nome scritto in cima.
            -- La forma delle parole la decide `Pezzi.quando`, una per tutte e
            -- due le finestre.
            --
            -- Un libro di cui non si sa la data non scrive niente:
            -- `quando` torna `nil` e la colonna resta vuota. «Non lo so»
            -- non e' «oggi».
            quando = consegna(m),
        })
    end
    return voci
end

--- I cinque tasti: quelli di sempre, ma «cronologia» qui funziona davvero —
--- non siamo nella cronologia, e passarci sopra e' un gesto naturale.
function KolibreConsegne:azioniBarra()
    local azioni = Elenco.azioniBarra(self)
    azioni.cronologia = function()
        local ok, Cronologia = pcall(require, "kolibre_ui_cronologia")
        if not ok then return end
        if Cronologia.aperta() then return end
        -- Si chiude questa PRIMA di aprire quella: due finestre di elenchi
        -- impilate vorrebbero dire due «indietro» da premere per tornare
        -- alla libreria, e nessuno si ricorda di averne aperte due.
        self:onClose()
        local UIManager = require("ui/uimanager")
        pcall(function()
            UIManager:show(Cronologia:new{
                manifest = self.manifest,
                kolibre = self.kolibre,
                agganciato = self.agganciato,
                cartella_logo = self.cartella_logo,
                righe_per_schermata = self.righe_per_schermata,
            })
        end)
    end
    return azioni
end

return KolibreConsegne
