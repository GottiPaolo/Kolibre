--[[--
Il disegno che la vista libreria e la vista cronologia hanno in comune.

**Perche' esiste.** Dal 16/11/2026 le viste di Kolibre sono DUE: la libreria
(un elenco dei libri sul dispositivo, che eredita da `FileChooser` perche'
cammina delle cartelle) e la cronologia (gli ultimi libri aperti, che
cartelle non ha e eredita da `Menu`). Hanno due sorgenti di voci diverse e
due eredita' diverse, ma **lo stesso aspetto**: Paolo l'ha chiesto cosi' —
«con lo stesso aspetto: copertina e barra».

Quell'aspetto e' il calcolo delle misure, lo spezzettamento dell'altezza fra
le righe, il tasto «indietro» e la batteria dentro la barra di navigazione,
e cosa fanno le strisciate. Qui dentro c'e' una volta sola, e le viste la
chiamano.

**Perche' sono funzioni che prendono la vista invece di una classe base.**
Perche' le due viste **non possono** avere una classe base comune: una deve
essere un `FileChooser` (gli serve la lettura delle cartelle di KOReader) e
l'altra un `Menu`. Una funzione che riceve la vista e le scrive dentro
funziona per entrambe senza chiedere a nessuna delle due di cambiare
genitore — e cambiare genitore a `KolibreUI` vorrebbe dire riscrivere la
lettura delle cartelle, cioe' il pezzo che funziona.

**Quello che NON sta qui.** Da dove vengono le voci, cosa succede quando ne
si tocca una, e cosa fanno i cinque tasti: sono le tre cose per cui le due
viste sono due viste diverse.
]]

local CenterContainer = require("ui/widget/container/centercontainer")
local Font = require("ui/font")
local Geom = require("ui/geometry")
local HorizontalSpan = require("ui/widget/horizontalspan")
local Menu = require("ui/widget/menu")
local Screen = require("device").screen
local Size = require("ui/size")
local TextBoxWidget = require("ui/widget/textboxwidget")
local UIManager = require("ui/uimanager")
local logger = require("logger")
local VerticalSpan = require("ui/widget/verticalspan")
local Pezzi = require("kolibre_ui_pezzi")

local Comune = {}

--- Le misure della schermata. Le calcoliamo NOI, e non e' un vezzo.
--
-- **Il difetto che queste righe correggono** (15/11/2026, sul KOReader del
-- Mac di Paolo). All'apertura la vista moriva con
--
--     failed to run lua chunk: kolibre_ui_libreria.lua:227:
--       attempt to perform arithmetic on field 'available_height' (a nil value)
--
-- e «failed to run lua chunk» vuol dire che l'errore e' arrivato in cima
-- senza che nessuno lo prendesse: **KOReader si chiudeva**.
--
-- **La causa.** `coverbrowser.koplugin` non cambia l'aspetto del gestore di
-- file con dei parametri: **riscrive dei metodi sulla CLASSE**, fra cui
-- `_recalculateDimen`. La nostra vista ne era una sottoclasse, quindi
-- chiamava quello di coverbrowser, che calcola le misure che servono a LUI
-- e non scrive `available_height`.
--
-- Il guardiano e' la prova `la_vista_regge_coverbrowser`.
function Comune.misure(vista, no_recalculate_dimen, righe)
    -- **Il corpo del testo dei menu: adesso si legge anche l'impostazione.**
    -- KOReader lo calcola cosi' (`menu.lua:634` della v2026.07.2, letta
    -- sulla release vera): prima un valore messo addosso al widget, poi
    -- **quello che l'utente ha salvato** dal gestore di file (Impostazioni ▸
    -- Dimensione del testo), e solo in mancanza di entrambi il valore
    -- ricavato dal numero di righe. A noi mancava il termine di mezzo:
    -- qualunque cosa Paolo avesse scelto, questa vista non la guardava.
    --
    -- **Che cosa cambia davvero, detto, perche' e' meno di quanto sembra.**
    -- Le NOSTRE righe non prendono il corpo da qui: `Pezzi.Riga` se lo
    -- calcola dall'altezza della riga (`base = max(dimen.h, RIGA_STRETTA)`),
    -- perche' con 4-8 righe per schermata l'altezza e' il vincolo e un corpo
    -- scelto a mano la farebbe sfondare — ed e' la regola che
    -- la prova `le_righe_stanno_su_ogni_schermo` tiene ferma su quattro
    -- geometrie. Quindi l'impostazione governa quello che disegna KOReader
    -- (il testo in fondo, le misure che i suoi metodi ereditati calcolano da
    -- `font_size`), non l'altezza dei titoli.
    --
    -- **E perche' `font_size` si scrive comunque, invece di togliere la
    -- riga.** Perche' dei metodi di `Menu` che noi NON riscriviamo lo
    -- leggono (`setupItemHeights`, `menu.lua:1225`, fa un
    -- `Font:getFace(..., self.font_size)`): lasciarlo nil vorrebbe dire
    -- un'aritmetica su un nil dentro codice di KOReader, che e' esattamente
    -- il modo in cui coverbrowser ci ha chiuso KOReader in faccia
    -- (la prova `la_vista_regge_coverbrowser`).
    local corpo = vista.items_font_size
        or G_reader_settings:readSetting("items_font_size")
        or Menu.getItemFontSize(righe)
    if vista.perpage ~= righe or vista.font_size ~= corpo then
        vista.perpage = righe
        vista.font_size = corpo
        no_recalculate_dimen = false
    end
    -- `and vista.available_height`: anche quando il ricalcolo non e' stato
    -- chiesto, la PRIMA volta le misure non ci sono ancora e senza di loro
    -- non si disegna niente. E' la rete che mancava: il percorso che ci ha
    -- ucciso passava proprio da qui.
    if no_recalculate_dimen and vista.available_height then return end

    local alto = 0
    if vista.title_bar and not vista.no_title then
        alto = vista.title_bar:getHeight()
    end
    local basso = 0
    if vista.page_return_arrow and vista.page_info_text then
        -- Il padding in piu' e' solo per l'occhio, e lo copiamo da KOReader
        -- per non avere una navigazione piu' attaccata al bordo della sua.
        basso = math.max(vista.page_return_arrow:getSize().h,
                         vista.page_info_text:getSize().h) + Size.padding.button
    end

    vista.available_height = vista.inner_dimen.h - alto - basso
    -- `item_dimen` non lo usa il nostro disegno (le righe se la misurano in
    -- `Comune.disegna`), ma lo leggono dei metodi di `Menu` che ereditiamo:
    -- resta scritto perche' non sia nil sotto di loro.
    vista.item_dimen = Geom:new{
        x = 0, y = 0,
        w = vista.inner_dimen.w,
        h = math.floor(vista.available_height / righe),
    }

    vista.page_num = vista:getPageNumber(#vista.item_table)
    if vista.page > vista.page_num then
        vista.page = vista.page_num
    end
end

--- Disegna una schermata di righe. `vuoto` e' il testo da mostrare se non
--- c'e' nessuna voce.
--
-- Torna il numero della riga da evidenziare, che chi chiama passa a
-- `updatePageInfo`.
function Comune.disegna(vista, vuoto, select_number)
    local voci = vista.item_table or {}
    local inizio = (vista.page - 1) * vista.perpage
    local scelta = select_number

    if #voci == 0 then
        -- Un elenco vuoto va SPIEGATO. Un elenco bianco sembra un guasto, e
        -- il motivo per cui e' vuoto chi legge non puo' indovinarlo.
        table.insert(vista.item_group, VerticalSpan:new{ width = math.floor(vista.available_height * 0.35) })
        table.insert(vista.item_group, CenterContainer:new{
            dimen = Geom:new{ w = vista.inner_dimen.w, h = Screen:scaleBySize(90) },
            TextBoxWidget:new{
                text = vuoto or "",
                width = vista.inner_dimen.w - 2 * Size.padding.large,
                alignment = "center",
                face = Font:getFace("infofont"),
            },
        })
        return scelta
    end

    -- **Qui non si riserva niente ne' alla batteria ne' all'«indietro».**
    -- Dal 16/11/2026 stanno tutte e due dentro la barra di navigazione (vedi
    -- `Comune.batteriaNellaBarra` e `Comune.tastoIndietro`), la cui altezza
    -- era gia' contata in `Comune.misure`: quello che le due strisce si
    -- prendevano prima che le righe si dividessero il resto — il 3,5% la
    -- batteria, il 6,5% l'«indietro» — e' tornato all'elenco.
    local alt_riga = math.floor(vista.available_height / vista.perpage)
    local usata = 0
    for posto = 1, vista.perpage do
        local voce = voci[inizio + posto]
        if not voce then break end
        voce.idx = inizio + posto
        if voce.idx == vista.itemnumber then scelta = posto end
        local riga = Pezzi.Riga:new{
            voce = voce,
            menu = vista,
            dentro_autore = vista.dentro_autore,
            dimen = Geom:new{ w = vista.inner_dimen.w, h = alt_riga },
        }
        table.insert(vista.item_group, riga)
        table.insert(vista.layout, { riga })
        usata = usata + alt_riga
    end
    -- Spinta in fondo: l'ultima pagina puo' avere due righe invece di sei, e
    -- quello che sta sotto deve stare dov'e' sempre, non dove finiscono le
    -- righe. Un comando che cambia posto a seconda di quanti libri ci sono
    -- non si impara mai.
    local avanzo = vista.available_height - usata
    if avanzo > 0 then
        table.insert(vista.item_group, VerticalSpan:new{ width = avanzo })
    end
    return scelta
end

--- Il tasto «indietro» in fondo a sinistra, nella riga delle frecce.
--
-- **Da dove salta fuori, e perche' non e' roba nostra.** `Menu` costruisce
-- gia' una freccia in basso a sinistra (`page_return_arrow`), tenuta
-- nascosta finche' chi lo usa non definisce un `onReturn`; sta in un
-- contenitore largo quanto lo schermo e appoggiato in fondo, cioe'
-- **allineata a sinistra nella stessa riga** delle frecce delle pagine. E'
-- esattamente il posto che Paolo ha chiesto il 16/11/2026, e c'era gia':
-- quello che facevamo noi era disegnarci una striscia sopra la barra.
--
-- **Perche' si rifanno le due righe che `updatePageInfo` fa gia'.** Quel
-- metodo decide se la freccia e' accesa guardando `#self.paths`, cioe' la
-- pila di navigazione dei menu di KOReader — che le nostre viste non usano:
-- la libreria cammina delle cartelle vere, la cronologia non cammina
-- affatto. Chiedere alla vista (`siPuoTornare`) e' dirlo per quello che e',
-- invece di tenere aggiornata una pila finta perche' una riga di KOReader la
-- guardi.
--
-- **Sempre visibile, anche quando e' spenta.** Alla radice della libreria
-- non si va da nessuna parte, e la freccia e' grigia; ma resta dov'e'. Un
-- comando che sparisce e ricompare e' un comando che si cerca ogni volta.
function Comune.tastoIndietro(vista)
    local freccia = vista.page_return_arrow
    if not freccia then return end
    local si_puo = true
    if type(vista.siPuoTornare) == "function" then
        local ok, risposta = pcall(function() return vista:siPuoTornare() end)
        si_puo = (ok and risposta) and true or false
    end
    pcall(function()
        freccia:showHide(true)
        freccia:enableDisable(si_puo)
    end)
end

--- Infila la batteria nel gruppo delle frecce, in fondo allo schermo.
--
-- **Perche' si MUTA `page_info` invece di costruire un fondo nostro.** Quel
-- gruppo lo costruisce `Menu.init`, e il contenitore che lo tiene appoggiato
-- in fondo allo schermo e' una variabile locale di quel metodo: da fuori non
-- si raggiunge. La tabella `vista.page_info` invece e' la stessa che il
-- contenitore ha in mano, quindi infilarci dentro un pezzo si vede, senza
-- riscrivere niente di KOReader — che e' la regola di queste viste da quando
-- coverbrowser ci ha chiuso KOReader.
--
-- **Lo spazio davanti non e' decorazione.** `page_info` e' CENTRATO in fondo
-- allo schermo, e la sua larghezza e' la somma dei suoi pezzi: aggiungendo
-- la batteria solo in coda, il «pagina 2 di 5» si sposterebbe a sinistra di
-- mezza batteria. Uno spazio della stessa larghezza davanti rimette il
-- centro dov'era.
--
-- **Il corpo e' quello del testo delle pagine**, chiesto al widget vero
-- invece di indovinato: cosi' la barra non cresce di un pixel, e quello che
-- l'elenco ha guadagnato togliendo la striscia non se lo riprende la barra.
function Comune.batteriaNellaBarra(vista)
    if not vista.page_info then return end
    local alto = 24
    if vista.page_info_text and vista.page_info_text.getSize then
        local ok, misura = pcall(function() return vista.page_info_text:getSize() end)
        if ok and misura and misura.h and misura.h > 0 then
            alto = math.floor(misura.h * 0.60)
        end
    end
    local pezzo = Pezzi.batteriaCompatta(Pezzi.corpo(alto))
    if not pezzo then return end
    local larghezza = pezzo:getSize().w
    table.insert(vista.page_info, 1, HorizontalSpan:new{ width = larghezza })
    table.insert(vista.page_info, pezzo)
    vista.batteria_nella_barra = pezzo
    -- Il TextWidget dentro il gruppo: e' quello a cui si riscrive il testo.
    vista._testo_batteria = pezzo[2]
end

--- Riscrive la percentuale, se la batteria c'e'.
--
-- La carica si rilegge a ogni ridisegno e non costa: `getCapacity()` di
-- KOReader ha gia' una cache di sessanta secondi dentro di se'.
--
-- Se il dispositivo non ha una batteria, `_testo_batteria` non esiste e qui
-- non si fa niente: nessun ramo da ricordarsi, nessun pezzo vuoto disegnato.
function Comune.aggiornaBatteria(vista)
    if not vista._testo_batteria then return end
    local testo = Pezzi.testoBatteria()
    if testo and vista._testo_batteria.setText then
        pcall(function() vista._testo_batteria:setText(testo) end)
    end
end

--- Che cosa fa una strisciata. Torna `true`: il gesto e' sempre consumato.
--
-- **Il difetto che questa funzione corregge** (Paolo, 16/11/2026: «la UI di
-- Kolibre crasha se facciamo uno swiper verso l'alto e forse anche con altre
-- gesture»). Le strisciate le gestiva `Menu`, e il suo `onSwipe` **chiude la
-- finestra** quando si striscia verso il basso; il suo `onMultiSwipe` la
-- chiude per QUALUNQUE strisciata composta — e su un trackpad una strisciata
-- verso l'alto che fa una curva viene letta proprio cosi'. La vista spariva
-- e sotto ricompariva il gestore di file di KOReader: dal posto in cui si
-- guarda, e' una UI che «crasha».
--
-- Misurato sul KOReader del Mac prima di toccare niente: `swipe south`
-- chiusa=true, `multiswipe` chiusa=true, `swipe north` non faceva niente.
--
-- **Cosa fanno adesso.** L'elenco e' verticale, quindi su e giu' girano
-- pagina — come gia' facevano destra e sinistra. Le diagonali rinfrescano
-- lo schermo (su un e-ink serve davvero, ed e' quello che fa KOReader
-- dappertutto). Niente chiude la finestra per sbaglio: si esce dai tasti in
-- cima, che sono li' apposta.
function Comune.swipe(vista, direzione)
    if direzione == "west" or direzione == "north" then
        vista:onNextPage()
    elseif direzione == "east" or direzione == "south" then
        vista:onPrevPage()
    elseif direzione then
        UIManager:setDirty(nil, "full")
    end
    return true
end

--- La cornice di un ridisegno: azzera, ricalcola, disegna, e sporca lo
--- schermo una volta sola alla fine.
--
-- Le due viste hanno lo stesso `updateItems` tranne per il testo del vuoto e
-- per il numero di righe: entrambi arrivano come argomento.
function Comune.ridisegna(vista, righe, vuoto, select_number, no_recalculate_dimen)
    local old_dimen = vista.dimen and vista.dimen:copy()
    vista.layout = {}
    vista.item_group:clear()
    vista.page_info:resetLayout()
    vista.return_button:resetLayout()
    vista.content_group:resetLayout()
    Comune.misure(vista, no_recalculate_dimen, righe)

    local scelta = Comune.disegna(vista, vuoto, select_number)

    Comune.aggiornaBatteria(vista)
    vista:updatePageInfo(scelta)
    -- **Dopo** `updatePageInfo`, non prima: e' lui che decide se la freccia
    -- si vede, e lo decide guardando una pila che le nostre viste non usano.
    Comune.tastoIndietro(vista)
    Menu.mergeTitleBarIntoLayout(vista)
    UIManager:setDirty(vista.show_parent, function()
        local da_rifare = old_dimen and old_dimen:combine(vista.dimen) or vista.dimen
        return "ui", da_rifare
    end)
end

--- Fra due voci che parlano dello stesso file, quale vale.
--
-- **Lo stesso libro puo' avere DUE righe nel manifesto**, e non e' un caso
-- strano: la vecchia migrazione adottava quello che trovava sul dispositivo
-- sotto una chiave `hash:<impronta>`, e quando poi il server riconosceva quel
-- libro, `_linkHashMatch` ne scriveva una seconda con l'identita' vera
-- (`biblioteca:id:formato`) — **senza togliere la prima**. Che e' anche
-- scritto in `_deleteManagedBook`, che cancellando un libro va a caccia
-- proprio delle voci di migrazione rimaste.
--
-- Prima qui vinceva l'ultima che capitava, e `pairs` non ha un ordine: la
-- stessa finestra, riaperta, poteva prendere l'altra riga — con un'altra
-- data, e quindi un altro posto nell'elenco. E' meta' della ragione per cui
-- Paolo il 17/11/2026 non capiva che ordinamento stesse usando il pannello.
--
-- La regola, in ordine: vince chi ha un'identita' vera (la voce di
-- migrazione non ce l'ha), poi chi ha la data del server, poi la piu'
-- recente. Deterministica: due aperture danno lo stesso elenco.
function Comune.miglioreFra(vecchia, nuova)
    if vecchia == nil then return nuova end
    local function punteggio(v)
        return (v.calibre_book_id and 4 or 0)
            + (v.consegnato_il and 2 or 0)
            + (v.downloaded_at and 1 or 0)
    end
    local pv, pn = punteggio(vecchia), punteggio(nuova)
    if pn ~= pv then return pn > pv and nuova or vecchia end
    local qv = vecchia.consegnato_il or vecchia.downloaded_at or 0
    local qn = nuova.consegnato_il or nuova.downloaded_at or 0
    if qn ~= qv then return qn > qv and nuova or vecchia end
    return vecchia
end

--- Apre la finestra dei risultati per il testo cercato.
--
-- **Da dove arriva il testo.** Dal riquadro di ricerca di KOReader, quello
-- che si apre toccando il numero di pagina in fondo: `Menu` lo passa a
-- `search_callback`, che ogni nostra finestra imposta a questa funzione. La
-- porta d'ingresso e' la sua, quello che c'e' dietro e' nostro — vedi
-- `kolibre_ui_ricerca.lua` per il perche' di una finestra invece di un
-- filtro sulla vista.
--
-- **Una sola finestra di risultati per volta.** Cercando di nuovo da dentro
-- i risultati, la vecchia si chiude prima che nasca la nuova: due finestre
-- impilate vorrebbero dire due «indietro» da premere per tornare dove si
-- era, e nessuno si ricorda di averne aperte due.
function Comune.cerca(vista, testo)
    testo = type(testo) == "string" and testo:gsub("^%s+", ""):gsub("%s+$", "") or ""
    -- Il riquadro di KOReader lascia premere «Search…» anche a vuoto: senza
    -- questo controllo si aprirebbe una finestra con dentro tutto.
    if testo == "" then return end

    local ok, Ricerca = pcall(require, "kolibre_ui_ricerca")
    if not ok then
        logger.err("Kolibre: la ricerca non si carica:", Ricerca)
        return
    end
    if type(Ricerca.aperta) == "function" then
        local gia = Ricerca.aperta()
        if gia then pcall(function() UIManager:close(gia) end) end
    end

    local finestra
    local costruita, errore = pcall(function()
        finestra = Ricerca:new{
            testo = testo,
            manifest = vista.manifest,
            kolibre = vista.kolibre,
            agganciato = vista.agganciato,
            cartella_logo = vista.cartella_logo,
            righe_per_schermata = vista.righe_per_schermata,
        }
        UIManager:show(finestra)
    end)
    if costruita then return finestra end
    logger.err("Kolibre: la ricerca non si apre:", errore)
    if finestra then pcall(function() UIManager:close(finestra) end) end
end

return Comune
