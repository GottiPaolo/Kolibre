--[[--
Finestre che restano dentro lo schermo.

**Il problema.** Le finestre di conferma di KOReader (ConfirmBox) crescono con
il testo e **non scorrono**. Un elenco piu' alto dello schermo spinge i
bottoni fuori dal bordo: la domanda si legge, e non si puo' rispondere. La
finestra resta li', e l'unico modo di toglierla e' riavviare il lettore.

Segnalato da Paolo il 06/10/2026 dopo aver messo in coda molti libri: la
conferma dei download elencava un titolo per riga, senza alcun limite. Da li'
la regola generale che questo modulo serve a rendere applicabile — **una
finestra si costruisce sapendo quanto schermo c'e'**, non sperando che il
contenuto sia corto.

**Come.** L'elenco si taglia a quante righe ci stanno davvero, e in fondo si
dice quante ne restano. Il numero totale sta comunque nella frase che
introduce l'elenco, quindi non si perde nessuna informazione: si perde
l'elenco per esteso, che su sessanta libri non si leggeva comunque.

La misura e' approssimata di proposito. Non si sa quanto sara' alta la frase
introduttiva, ne' quanto andranno a capo i titoli lunghi, ne' che carattere
abbia impostato chi legge: calcolare al pixel una cosa che dipende dal testo
tradotto darebbe una precisione finta. Si tiene per se' piu' di meta' dello
schermo e si sta larghi.

Le due funzioni che fanno i conti non toccano KOReader (prendono le misure
come argomenti), cosi' si possono provare senza un lettore: vedi
`prove/finestre.lua`.
]]

local KolibreFinestre = {}

-- Altezza di una riga di testo in una finestra, in unita' da scalare col DPI.
KolibreFinestre.ALTEZZA_RIGA = 22
-- Quanto dello schermo puo' prendersi l'elenco. Il resto va alla domanda, ai
-- due bottoni e ai margini, che insieme sono sempre piu' di quanto sembri.
KolibreFinestre.QUOTA_ELENCO = 0.45
-- Sotto le tre righe un elenco non e' un elenco; oltre le venticinque,
-- scorrerlo con gli occhi costa piu' che fidarsi del numero totale.
KolibreFinestre.MINIMO = 3
KolibreFinestre.MASSIMO = 25

--- Quante righe di elenco ci stanno, date le misure. Funzione pura.
-- @param altezza_schermo in pixel, gia' scalati
-- @param altezza_riga in pixel, gia' scalati
function KolibreFinestre.righeDisponibili(altezza_schermo, altezza_riga)
    if type(altezza_schermo) ~= "number" or altezza_schermo <= 0 then return KolibreFinestre.MINIMO end
    if type(altezza_riga) ~= "number" or altezza_riga <= 0 then return KolibreFinestre.MINIMO end
    local quante = math.floor((altezza_schermo * KolibreFinestre.QUOTA_ELENCO) / altezza_riga)
    return math.max(KolibreFinestre.MINIMO, math.min(KolibreFinestre.MASSIMO, quante))
end

--- Taglia un elenco a `limite` righe, aggiungendo in fondo quante ne restano.
-- Funzione pura: `etichetta_resto` e' una funzione che riceve quante ne
-- restano e torna la riga da scrivere (cosi' la traduzione sta fuori).
function KolibreFinestre.taglia(voci, limite, etichetta_resto)
    if type(voci) ~= "table" or #voci == 0 then return "" end
    if #voci <= limite then return table.concat(voci, "\n") end
    local mostrate = {}
    for i = 1, limite do table.insert(mostrate, voci[i]) end
    local restano = #voci - limite
    if etichetta_resto then
        -- Le parentesi non sono di troppo: `etichetta_resto` la passa chi
        -- chiama, e una funzione che restituisse due valori si espanderebbe
        -- negli argomenti di `table.insert`, che a tre argomenti vuole una
        -- POSIZIONE numerica al secondo posto. Troncare qui costa niente e
        -- toglie la trappola a tutti i chiamanti futuri (stessa classe del
        -- crash del catalogo, 04/11/2026).
        table.insert(mostrate, (etichetta_resto(restano)))
    end
    return table.concat(mostrate, "\n")
end

--- Quello che si usa davvero: unisce le voci in un elenco che ci sta.
-- `voci` sono stringhe gia' pronte (col loro pallino davanti, se lo vogliono).
function KolibreFinestre.elenco(voci)
    local Screen = require("device").screen
    local t = require("kolibre_lingua").t
    local altezza = nil
    local ok, valore = pcall(function() return Screen:getHeight() end)
    if ok then altezza = valore end
    local riga = nil
    ok, valore = pcall(function() return Screen:scaleBySize(KolibreFinestre.ALTEZZA_RIGA) end)
    if ok then riga = valore end
    local limite = KolibreFinestre.righeDisponibili(altezza, riga)
    return KolibreFinestre.taglia(voci, limite, function(restano)
        return t("koreader.common.and_more", { count = restano, n = restano })
    end)
end

return KolibreFinestre
