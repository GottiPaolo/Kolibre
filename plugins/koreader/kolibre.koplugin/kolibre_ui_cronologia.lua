-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one.

--[[--
La cronologia di Kolibre: gli ultimi libri aperti, con lo stesso aspetto
della vista libreria.

**Perche' esiste** (Paolo, 16/11/2026). Il tasto «cronologia» della nostra
barra passava la mano alla cronologia di KOReader: una sua schermata, con il
suo aspetto, in mezzo alla nostra. Paolo ha chiesto le copertine anche li',
«con lo stesso aspetto: copertina e barra».

**Perche' una vista nostra e non il widget di KOReader ritoccato.** Erano le
due strade, e la seconda e' quella che il 15/11 ci ha chiuso KOReader:
`coverbrowser` riscrive dei metodi sulla classe `FileChooser`, e la nostra
vista — che ne ereditava — chiamava i suoi. Mettere le mani nel widget della
cronologia di KOReader vorrebbe dire rifare lo stesso errore sapendolo.

**Che cosa resta in questo file.** Soltanto le tre cose per cui questa
finestra e' questa finestra: come si chiama, da dove prende le voci, e cosa
si scrive quando non ce n'e' nessuna. Tutto il resto — la barra, le misure,
le righe, l'«indietro» in fondo, le strisciate, l'apertura di un libro — sta
in `kolibre_ui_elenco.lua`, che ha in comune con il pannello degli ultimi
invii.

────────────────────────────────────────────────────────────────────────
DUE SCELTE CHE VALE LA PENA SPIEGARE
────────────────────────────────────────────────────────────────────────

**1. I libri che non ci sono piu' non si mostrano.** La cronologia di
KOReader li tiene e li disegna sbiaditi; noi li saltiamo. Il motivo e' il
nostro stesso modo di funzionare: in questa vista **il tocco apre**, senza
scheda intermedia (decisione di Paolo del 15/11). Una riga che si tocca e
non apre niente e' una riga che mente, e in un elenco dove tutte le altre
aprono e' peggio di una riga che non c'e'.

**2. Si mostrano TUTTI i libri letti, non solo quelli di Kolibre.** La vista
libreria mostra solo i libri che Kolibre ha consegnato, e li' e' giusto:
quella e' la libreria di Kolibre. Questa invece e' la cronologia del
dispositivo, e nasconderci un libro che Paolo ha letto davvero la renderebbe
una cronologia che dice il falso. Il manifesto serve ad ARRICCHIRE quello
che puo' — titolo vero, autore, copertina, stima delle pagine — e per un
libro che non e' suo la riga mostra il riquadro col titolo, come fa per un
libro di Kolibre la cui copertina non e' ancora arrivata.
]]

local ReadHistory = require("readhistory")
local BookList = require("ui/widget/booklist")
local lfs = require("libs/libkoreader-lfs")
local DataStorage = require("datastorage")
local Elenco = require("kolibre_ui_elenco")
local KolibreCopertine = require("kolibre_copertine")
local t = require("kolibre_lingua").t

--: Quante voci si mostrano. La cronologia di KOReader ne tiene cinquecento
--  (`history_size`), e cinquecento righe su un Kindle sono ottantatre
--  pagine da girare: un elenco che non si usa. Le ultime cinquanta sono
--  quello che uno guarda davvero quando pensa «quel libro di ieri».
local QUANTE = 50

local KolibreCronologia = Elenco:extend{
    chiave = "cronologia",
}

function KolibreCronologia.aperta() return Elenco.apertaDi("cronologia") end

function KolibreCronologia:titolo() return t("koreader.ui.cronologia_titolo") end
function KolibreCronologia:vuoto() return t("koreader.ui.cronologia_vuota") end

--- Le voci della cronologia, arricchite con quello che il manifesto sa.
--
-- `ReadHistory.hist` e' gia' ordinata dalla piu' recente: non si riordina.
-- Di ogni voce di KOReader si usano solo `file` e `text`, che esistono
-- identici nella v2025.08 (il Mac), nella v2026.03 (il container) e nella
-- v2026.07.2 (il Kindle) — verificato sul sorgente delle tre release, non a
-- memoria.
function KolibreCronologia:voci()
    -- `reload` perche' la cronologia la scrive KOReader anche mentre questa
    -- vista non c'e': aprirla e trovarci l'elenco di mezz'ora fa sarebbe un
    -- difetto silenzioso.
    pcall(function() ReadHistory:reload() end)

    local cartella_copertine = KolibreCopertine.cartella(DataStorage)
    local per_percorso = self:_manifestoPerPercorso()

    local voci = {}
    for _i, riga in ipairs(ReadHistory.hist or {}) do
        if #voci >= QUANTE then break end
        local percorso = riga.file
        -- Vedi la scelta 1 in testa al file: un libro che non c'e' piu' non
        -- si mostra, perche' qui il tocco apre.
        if percorso and lfs.attributes(percorso, "mode") == "file" then
            local m = per_percorso[percorso] or {}
            table.insert(voci, {
                path = percorso,
                titolo = m.title or riga.text or percorso:match("([^/]+)$"),
                autore = m.author,
                stima_pagine = m.server_pages,
                info = BookList.getBookInfo(percorso),
                immagine = KolibreCopertine.perVoce(cartella_copertine, m),
                -- **Quando l'hai aperto**, a destra della riga (Paolo,
                -- 16/11/2026). `riga.time` e' il campo che KOReader scrive
                -- in ogni voce di cronologia: verificato sul sorgente di
                -- v2025.08 (il Mac) e v2026.07.2 (il Kindle), non a memoria.
                -- La forma delle parole la decide `Pezzi.quando`, una sola
                -- per questa finestra e per gli ultimi invii.
                quando = riga.time,
            })
        end
    end
    return voci
end

--- I cinque tasti: quelli di sempre, meno «cronologia».
--
-- Siamo GIA' nella cronologia: il tasto non fa niente, e non e' una
-- dimenticanza. Riaprirla sopra se stessa impilerebbe due finestre
-- identiche, e chiuderla farebbe del tasto un «indietro» mascherato —
-- mentre un «indietro» vero c'e' gia', in fondo a sinistra.
--
-- E' quello che `Elenco:azioniBarra` fa gia' per difetto: questa riga c'e'
-- per dire che e' una scelta e non un caso.
KolibreCronologia.azioniBarra = Elenco.azioniBarra

return KolibreCronologia
