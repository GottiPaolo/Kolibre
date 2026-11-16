--[[--
Dove sta la copertina di un libro sul dispositivo, e come ci arriva.

**Perche' questo modulo esiste.** Dal 15/11/2026 le copertine servono a DUE
viste: il catalogo (`kolibre_catalog.lua`, che le mostra in una griglia da
quando esiste) e la vista libreria (`kolibre_ui_libreria.lua`, che fino a
ieri mostrava un riquadro grigio col titolo). Due viste che scaricano la
stessa immagine in due posti diversi vorrebbe dire, su un Kindle, il doppio
dei giri di rete e il doppio dello spazio per vedere la stessa cosa. Qui
dentro c'e' **una sola** regola su dove sta il file, e le due viste la
chiedono invece di saperla.

**La cartella e' quella che il catalogo usava gia'** — `cache/kolibre_covers_v2`
— e il nome del file e' lo stesso di prima. Non e' pigrizia: cambiarli
avrebbe buttato via tutte le copertine che sul dispositivo di Paolo ci sono
gia', facendole riscaricare una per una.

────────────────────────────────────────────────────────────────────────
LA CHIAVE: PERCHE' SENZA IL FORMATO
────────────────────────────────────────────────────────────────────────

Nel manifesto un libro e' identificato da **tre** cose —
`biblioteca:id:FORMATO` — perche' lo stesso libro in EPUB e in PDF sono due
file diversi, con due impronte diverse e due posizioni di lettura diverse.

La copertina no: e' **due** cose, `biblioteca:id`. Il motivo non e' una
scelta nostra, e' come e' fatto il server: la rotta e'
`/api/kolibre/books/{id}/cover/thumbnail` e non prende nessun formato —
Calibre tiene UNA copertina per libro (`cover.jpg` nella cartella del
libro), non una per formato. Mettere il formato nella chiave vorrebbe dire
tenere due copie identiche della stessa immagine e scaricarla due volte.

La biblioteca invece ci vuole, ed e' il difetto che si farebbe a tolgierla:
gli id dei libri di Calibre **ripartono da 1 in ogni biblioteca**, quindi
senza il nome della biblioteca il libro #5 di una mostrerebbe la copertina
del libro #5 dell'altra.

────────────────────────────────────────────────────────────────────────
]]

local lfs = require("libs/libkoreader-lfs")
local util = require("util")

local KolibreCopertine = {}

--: Il tetto ai byte di una copertina. La rotta delle miniature il server la
--  ridimensiona a 400x600 al massimo, quindi un file piu' grosso di questo
--  non e' una copertina: e' una risposta d'errore, o un file troncato a
--  meta' da una connessione caduta. Scaricarlo e darlo da decodificare a un
--  Kindle e' il difetto che aveva fatto chiudere il catalogo prima della
--  v0.6.2.
KolibreCopertine.MAX_BYTE = 2 * 1024 * 1024

--: Quante copertine si tengono in cache, e a quante si scende quando si
--  pota. Due numeri e non uno: potare fino al tetto esatto vorrebbe dire
--  ripotare al download successivo, e una potatura e' una camminata della
--  cartella.
KolibreCopertine.MAX_IN_CACHE = 600
KolibreCopertine.DOPO_LA_POTATURA = 500

--: Quante se ne scaricano a ogni sincronizzazione. Venti e' la misura
--  chiesta da Paolo il 15/11, ed e' anche quella giusta: una copertina
--  ridimensionata sono decine di KB, venti sono un paio di MB e qualche
--  secondo — mentre centocinquanta libri tutti insieme sarebbero una
--  sincronizzazione che sembra piantata. Le altre arrivano alla prossima.
KolibreCopertine.PER_SINCRONIZZAZIONE = 20

--- La cartella delle copertine. `nil` se non si riesce a crearla.
--
-- `DataStorage` si passa come argomento e non si richiede qui dentro: e' la
-- stessa strada di `kolibre_percorsi.lua`, e serve a poter provare questo
-- modulo senza avviare KOReader.
function KolibreCopertine.cartella(DataStorage)
    if type(DataStorage) ~= "table" or type(DataStorage.getDataDir) ~= "function" then
        return nil
    end
    local dati = DataStorage:getDataDir()
    if type(dati) ~= "string" or dati == "" then return nil end
    return dati .. "/cache/kolibre_covers_v2"
end

--- Il pezzo di nome che identifica una biblioteca, ripulito.
--
-- **Ripulito contro che cosa.** Il nome della biblioteca arriva dal server,
-- e un nome puo' contenere qualunque cosa: uno spazio, un accento, una
-- barra. Una barra dentro un nome di file non e' un carattere: e' un pezzo
-- di percorso, e `Varie/../../qualcosa_5.jpg` scriverebbe fuori dalla
-- cartella della cache. Qui dentro passano solo lettere, cifre, trattino,
-- punto e sottolineatura; tutto il resto diventa un sottolineatura.
--
-- Il punto resta ammesso (ci sono nomi di biblioteca che ce l'hanno) e non
-- e' un buco: un nome fatto di soli punti diventa un PREFISSO del nome del
-- file, non un pezzo di percorso, perche' la barra non sopravvive.
local function chiaveBiblioteca(biblioteca)
    return tostring(biblioteca or ""):gsub("[^%w%-%._]", "_")
end
KolibreCopertine.chiaveBiblioteca = chiaveBiblioteca

--- Il percorso della copertina di un libro. `nil` se la cartella non c'e'.
--
-- Crea la cartella se manca: chi chiama vuole un posto dove scrivere, o un
-- posto dove guardare, e in entrambi i casi una cartella che non esiste e'
-- un `nil`, non un errore.
function KolibreCopertine.percorso(cartella, biblioteca, id)
    if type(cartella) ~= "string" or cartella == "" then return nil end
    if id == nil or tostring(id) == "" then return nil end
    if not util.makePath(cartella) then return nil end
    return cartella .. "/" .. chiaveBiblioteca(biblioteca) .. "_" .. tostring(id) .. ".jpg"
end

--- Il percorso SE il file c'e' davvero, altrimenti `nil`.
--
-- E' la domanda che fa una vista mentre disegna, e deve costare poco:
-- `lfs.attributes` e niente altro. **Mai** un giro di rete da qui — una
-- vista che scarica mentre disegna e' uno schermo fermo.
function KolibreCopertine.inCache(cartella, biblioteca, id)
    local percorso = KolibreCopertine.percorso(cartella, biblioteca, id)
    if percorso and lfs.attributes(percorso, "mode") == "file" then
        return percorso
    end
    return nil
end

--- La copertina di una voce del manifesto, se c'e'.
--
-- Comoda perche' e' quello che hanno in mano le viste: una voce con
-- `library` e `calibre_book_id`. Le voci nate da un accoppiamento per
-- impronta (`hash:<...>`) quei due campi non li hanno — il server non ha
-- ancora detto a quale libro corrispondono — e per loro la risposta e'
-- `nil`, cioe' il riquadro col titolo.
function KolibreCopertine.perVoce(cartella, voce)
    if type(voce) ~= "table" then return nil end
    if not voce.calibre_book_id then return nil end
    return KolibreCopertine.inCache(cartella, voce.library, voce.calibre_book_id)
end

--- L'indirizzo da cui si scarica. SEMPRE la miniatura, mai la rotta piena.
--
-- `/cover` consegna la copertina come sta in Calibre: 1000-2500 px sul lato
-- lungo, cioe' alcuni MB e una decodifica che su un Kindle si vede. La
-- rotta delle miniature la ridimensiona sul server a 400x600 — il lavoro lo
-- fa la macchina che ha corrente e processore.
function KolibreCopertine.indirizzo(biblioteca, id)
    return string.format("/api/kolibre/books/%s/cover/thumbnail?library=%s",
        tostring(id), tostring(biblioteca or ""))
end

--- Le copertine che mancano, per le voci passate, al massimo `quante`.
--
-- Torna un elenco di `{biblioteca, id, percorso}` pronti da scaricare.
-- **Non scarica**: separare «chi manca» da «scaricalo» e' quello che rende
-- provabile la prima meta' senza una rete.
--
-- Salta le voci senza id, quelle che la copertina ce l'hanno gia' e quelle
-- che hanno gia' fallito (`falliti`, una tabella chiave->true tenuta da chi
-- chiama): un libro senza copertina sul server non ce l'ha, e richiederla a
-- ogni sincronizzazione per sempre e' un giro di rete buttato ogni volta.
function KolibreCopertine.daScaricare(cartella, voci, quante, falliti)
    local coda = {}
    if type(cartella) ~= "string" or cartella == "" then return coda end
    quante = quante or KolibreCopertine.PER_SINCRONIZZAZIONE
    falliti = falliti or {}
    -- Ordine stabile: `pairs` su una tabella Lua non ha un ordine, e senza
    -- questo le prime venti sarebbero venti a caso diverse ogni volta — con
    -- il risultato che la ventunesima non arriva mai. Ordinate per chiave,
    -- le venti di oggi sono le prime venti e domani si riparte da li'.
    local chiavi = {}
    for chiave in pairs(voci or {}) do table.insert(chiavi, chiave) end
    table.sort(chiavi)
    for _i, chiave in ipairs(chiavi) do
        if #coda >= quante then break end
        local voce = voci[chiave]
        if type(voce) == "table" and voce.calibre_book_id and not falliti[chiave] then
            local percorso = KolibreCopertine.percorso(cartella, voce.library, voce.calibre_book_id)
            if percorso and lfs.attributes(percorso, "mode") ~= "file" then
                table.insert(coda, {
                    chiave = chiave,
                    biblioteca = voce.library,
                    id = voce.calibre_book_id,
                    percorso = percorso,
                })
            end
        end
    end
    return coda
end

--- Butta le copertine piu' vecchie quando sono troppe.
--
-- Una passata sola, dalla piu' vecchia: non e' un sistema di scadenze ed e'
-- voluto. Le copertine sono roba che si riscarica in un secondo, e il
-- lavoro di tenere conti precisi costerebbe piu' di quello che fa risparmiare.
function KolibreCopertine.pota(cartella)
    if type(cartella) ~= "string" or cartella == "" then return 0 end
    local ok, iteratore, oggetto = pcall(lfs.dir, cartella)
    if not ok or not iteratore then return 0 end
    local file = {}
    for voce in iteratore, oggetto do
        if voce ~= "." and voce ~= ".." then
            local pieno = cartella .. "/" .. voce
            local quando = lfs.attributes(pieno, "modification")
            if quando then table.insert(file, { percorso = pieno, quando = quando }) end
        end
    end
    if #file <= KolibreCopertine.MAX_IN_CACHE then return 0 end
    table.sort(file, function(a, b) return a.quando < b.quando end)
    local buttati = 0
    for i = 1, (#file - KolibreCopertine.DOPO_LA_POTATURA) do
        if os.remove(file[i].percorso) then buttati = buttati + 1 end
    end
    return buttati
end

return KolibreCopertine
