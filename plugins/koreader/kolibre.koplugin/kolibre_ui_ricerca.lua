-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one.

--[[--
Cercare un libro per titolo o per autore, fra quelli che Kolibre ha portato
qui.

**Da zero: da dove si entra.** Non da un tasto nuovo. KOReader ha gia' un
riquadro di ricerca nelle sue liste, e si apre **toccando il numero di
pagina** in fondo, in mezzo alle frecce — Paolo lo usava gia' («secondo me la
ricerca c'e' gia'»). Quel riquadro, da solo, fa una cosa diversa dalla
nostra: confronta il testo delle righe e **salta** alla prima che
corrisponde. Utile in un elenco di nomi di file, poco in un elenco di libri.

**Perche' non si e' scritto un riquadro nostro.** `Menu` dichiara un campo,
`search_callback`: quando c'e', il pulsante del riquadro si chiama «Search…»
e chiama **la nostra funzione** invece di saltare. Lo usano gia' il gestore
di file, la cronologia e le raccolte di KOReader per aprirci la loro ricerca.
Quindi la porta d'ingresso resta quella che Paolo conosce, e dietro ci
mettiamo quello che serve a noi: una riga da scrivere, non una finestra da
inventare.

**Perche' una FINESTRA e non un filtro sulla vista.** La libreria e'
organizzata in cartelle per autore: filtrare «quello che si vede adesso»
vorrebbe dire, dalla radice, cercare fra i nomi delle cartelle e non fra i
libri. I libri stanno **dentro**. Questa finestra invece guarda il
manifesto — l'elenco di tutto quello che Kolibre ha consegnato a questo
dispositivo — quindi trova un libro ovunque sia, e lo mostra con la
copertina, come le altre due finestre. Si apre sopra, si chiude, e sotto
c'e' ancora dove eri.

**Che cosa confronta.** Titolo e autore del manifesto, senza distinguere
maiuscole e minuscole. Non il nome del file: e' quello che la ricerca di
KOReader guardava, ed e' il motivo per cui cercare un autore non dava niente
— sul dispositivo l'autore e' il nome di una CARTELLA, non del file.

**L'ordine e' per titolo**, e non per data: qui si cerca un libro che si sa
gia' come si chiama, e in un elenco di risultati l'alfabeto e' l'unico ordine
che non va spiegato.
]]

local BookList = require("ui/widget/booklist")
local lfs = require("libs/libkoreader-lfs")
local DataStorage = require("datastorage")
local Elenco = require("kolibre_ui_elenco")
local KolibreCopertine = require("kolibre_copertine")
local t = require("kolibre_lingua").t

--: Quanti risultati al massimo. Oltre, non e' una ricerca: e' un elenco da
--  rifare con una parola piu' precisa — e la riga in cima lo dice.
local QUANTI = 200

local KolibreRicerca = Elenco:extend{
    chiave = "ricerca",
    --: Il testo cercato. Lo passa chi apre la finestra.
    testo = nil,
}

function KolibreRicerca.aperta() return Elenco.apertaDi("ricerca") end

--- Il nome della finestra dice **che cosa** si e' cercato e **quanti** se ne
--- sono trovati: senza il numero, un elenco corto e uno vuoto si
--- distinguono solo contando le righe.
function KolibreRicerca:titolo()
    return t("koreader.ui.ricerca_titolo", {
        testo = self.testo or "",
        count = #(self.item_table or {}),
    })
end

function KolibreRicerca:vuoto()
    return t("koreader.ui.ricerca_vuota", { testo = self.testo or "" })
end

--- Minuscole, anche sulle lettere accentate.
--
-- `string.lower` conosce solo l'alfabeto inglese: cercando «perche» non
-- troverebbe «Perché». `Utf8Proc` sta in KOReader da sempre, ma si chiede
-- sotto `pcall` — se un giorno non ci fosse, la ricerca diventa meno brava,
-- non si rompe.
local function minuscolo(s)
    if type(s) ~= "string" then return "" end
    local ok, Utf8Proc = pcall(require, "ffi/utf8proc")
    if ok and Utf8Proc and Utf8Proc.lowercase then
        local fatto, risultato = pcall(function() return Utf8Proc.lowercase(s) end)
        if fatto and type(risultato) == "string" then return risultato end
    end
    return s:lower()
end

--- I libri che corrispondono: titolo o autore.
function KolibreRicerca:voci()
    local cercato = minuscolo(self.testo or "")
    if cercato == "" then return {} end
    local cartella_copertine = KolibreCopertine.cartella(DataStorage)

    local trovati = {}
    for _percorso, m in pairs(self:_manifestoPerPercorso()) do
        -- Solo i libri che ci sono ancora: qui il tocco apre, e una riga che
        -- si tocca e non apre niente e' una riga che mente. Stessa regola
        -- della cronologia e degli ultimi invii.
        if m.path and lfs.attributes(m.path, "mode") == "file" then
            local titolo = m.title or m.path:match("([^/]+)$") or ""
            local dentro = minuscolo(titolo):find(cercato, 1, true)
                or (m.author and minuscolo(m.author):find(cercato, 1, true))
            if dentro then table.insert(trovati, m) end
        end
    end
    table.sort(trovati, function(a, b)
        return (a.title or a.path or "") < (b.title or b.path or "")
    end)

    local voci = {}
    for _i, m in ipairs(trovati) do
        if #voci >= QUANTI then break end
        table.insert(voci, {
            path = m.path,
            titolo = m.title or m.path:match("([^/]+)$"),
            autore = m.author,
            stima_pagine = m.server_pages,
            info = BookList.getBookInfo(m.path),
            immagine = KolibreCopertine.perVoce(cartella_copertine, m),
            -- **Qui la data NON si mostra.** In questa finestra le righe
            -- stanno in ordine alfabetico, quindi una data a destra non
            -- spiegherebbe perche' una riga sta dove sta: sarebbe
            -- un'informazione in piu' nel posto in cui le altre due
            -- finestre ne mettono una che serve a leggere l'elenco.
        })
    end
    return voci
end

--- I cinque tasti: quelli di sempre.
KolibreRicerca.azioniBarra = Elenco.azioniBarra

return KolibreRicerca
