--[[--
La vista «libreria» di Kolibre su KOReader: un file browser nostro, che
mostra SOLO i libri che Kolibre ha consegnato a questo dispositivo.

**Che cosa e', da zero.** Al posto del gestore di file di KOReader — che
mostra cartelle e file come un gestore di file qualunque — si apre questa:
le cartelle degli autori con la loro foto e quanti libri hanno dentro, poi i
libri, ognuno con una copertina, il titolo, una riga di stato a parole e una
barra lunga in proporzione alle pagine e riempita in proporzione a quanto
hai letto. Sopra, cinque tasti; sotto, la navigazione di KOReader.

**Come si aggancia, e perche' cosi'.** E' una sottoclasse di `FileChooser`,
il file browser di KOReader. Non una patch, non un plugin che si prende il
nome `coverbrowser` (quello e' di Project Title, che cosi' resta installabile
di fianco). Due cose si ereditano e sarebbero costate settimane a riscriverle:
la **navigazione** fra cartelle e la **lettura del disco**, che e' quella del
file browser normale e quindi non e' piu' lenta di lui.

Due trappole, trovate leggendo il sorgente della v2026.03 e non la
documentazione:
  * il filtro si fa sovrascrivendo `show_file`, **non** passando
    `file_filter`: con l'opzione «mostra file non supportati» accesa,
    `file_filter` viene scavalcato e si vedrebbe tutto il disco;
  * `show_dir` riceve solo il NOME della cartella, non il percorso, quindi
    non puo' decidere se quella cartella contiene libri di Kolibre. Il
    filtro delle cartelle si fa percio' in `genItemTable`, dove i percorsi
    interi ci sono.

**Il disegno delle righe e' nostro.** `Menu:updateItems` costruisce i suoi
`MenuItem` a mano e non ha un punto di estensione; quindi lo si
**sovrascrive nella nostra sottoclasse**, che e' la stessa strada che
`kolibre_catalog.lua` percorre dall'ottobre 2026 per la griglia del catalogo.
Sovrascrivere un metodo nella propria sottoclasse non e' toccare KOReader: il
suo file resta com'e', e se un giorno `Menu` cambia, cambia sotto di noi una
funzione sola, non un plugin intero.

**Niente rete mentre disegna. Mai.** Un controllo verso un server spento
blocca il lettore per tre secondi, perche' KOReader fa una cosa alla volta.
Questa vista legge il manifesto (un file locale) e i sidecar di KOReader
attraverso le sue funzioni. Non chiama il server nemmeno per il logo: quello
mostra l'ultimo stato conosciuto, scritto dall'ultima sincronizzazione.
]]

local BookList = require("ui/widget/booklist")
local FileChooser = require("ui/widget/filechooser")
local FileManager = require("apps/filemanager/filemanager")
local Geom = require("ui/geometry")
local InfoMessage = require("ui/widget/infomessage")
local ReaderUI = require("apps/reader/readerui")
local Screen = require("device").screen
local UIManager = require("ui/uimanager")
local VerticalSpan = require("ui/widget/verticalspan")
local CenterContainer = require("ui/widget/container/centercontainer")
local TextBoxWidget = require("ui/widget/textboxwidget")
local Font = require("ui/font")
local Size = require("ui/size")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")
local Pezzi = require("kolibre_ui_pezzi")
local t = require("kolibre_lingua").t

-- `Menu` e non `FileChooser`: si prende il modulo di KOReader cosi' com'e',
-- per poter chiamare i SUOI metodi anche quando un altro plugin li ha
-- riscritti sulla classe `FileChooser` da cui ereditiamo. Vedi
-- `KolibreUI:_recalculateDimen` e `KolibreUI:onCloseWidget`: il 15/11/2026
-- quella sostituzione, fatta da `coverbrowser`, chiudeva KOReader.
local Menu = require("ui/widget/menu")

--- La versione di QUESTA interfaccia, che non e' quella del plugin.
--
-- **Due numeri, e non e' una svista.** `VERSION` in `main.lua` e' il numero
-- che i dispositivi confrontano per decidere se aggiornarsi da soli: alzarlo
-- manda il plugin nuovo sul Kindle. Questo numero qui non lo guarda nessun
-- automatismo: dice soltanto a che punto e' la vista, per noi e per le note.
--
-- **0.0.1 (15/11/2026)**: la prima versione che Paolo ha provato sul
-- KOReader del Mac e ha dichiarato buona. C'e': la barra coi cinque tasti,
-- l'elenco a sei righe con la foto dell'autore o il riquadro col titolo, lo
-- stato di lettura a parole, la barra delle pagine lunga quanto la stima del
-- server e riempita quanto hai letto, la striscia «← Back» in fondo, e il
-- ritorno alla vista quando chiudi un libro.
--
-- **Resta spenta per difetto**: finche' non si accende l'impostazione,
-- KOReader e' quello di sempre. Il Kindle non la vede e non la vedra'
-- finche' Paolo non lo decide.
local UI_VERSION = "0.0.1"

--- Il «gestore di file» che `FileChooser` si aspetta di avere sopra di se'.
--
-- **Il difetto del Kindle, trovato il 15/11/2026 leggendo il suo registro.**
-- La vista non si apriva, e l'errore era:
--
--     la vista libreria non si apre: frontend/ui/widget/filechooser.lua:336:
--       attempt to index field 'ui' (a nil value)
--
-- Il Kindle di Paolo ha **KOReader v2026.07.2**, una versione piu' nuova di
-- tutte quelle su cui avevamo provato (il Mac ha la v2025.08, il container
-- di sviluppo la v2026.03). E nella v2026.07 `FileChooser` ha smesso di
-- chiedere le cartelle preferite a un MODULO e ha cominciato a chiederle
-- **all'oggetto che lo possiede**, `self.ui`:
--
--     v2025.08:  FileManagerShortcuts:hasFolderShortcut(item.path)
--     v2026.07:  self.ui.folder_shortcuts:hasFolderShortcut(item.path, true)
--
-- Due punti, tutti e due sulla strada del disegno normale: la riga 314
-- (il nome di una cartella) e la riga 336 (il sottotitolo). La nostra vista
-- non e' posseduta da nessuno — e' una finestra sua, mostrata sopra il
-- gestore di file — quindi `self.ui` era nil e si fermava li'.
--
-- **Perche' un finto e non il gestore di file vero.** Passargli
-- `FileManager.instance` funzionerebbe oggi, ma vorrebbe dire che da domani
-- ogni `self.ui:qualcosa` che KOReader aggiunge a `FileChooser` agisce
-- sulla finestra che sta SOTTO la nostra, che l'utente non vede. La vista
-- e' autonoma per scelta: risponde alle domande che un gestore di file si
-- sente fare, e non ne gira nessuna a nessuno.
--
-- Le risposte sono «no» e «niente» di proposito: le cartelle preferite di
-- KOReader sono le sue, le nostre righe le disegniamo noi, e il sottotitolo
-- la nostra barra non lo mostra nemmeno.
local function gestoreFileFinto()
    return {
        folder_shortcuts = {
            hasFolderShortcut = function() return false end,
            getShortcutFullName = function() return nil end,
        },
        -- `FileChooser:changeToPath` lo chiama solo quando `self.name` e'
        -- «filemanager», quindi da qui non ci si passa mai. Sta qui perche'
        -- costa una riga e la prossima versione di KOReader potrebbe
        -- togliere quel controllo.
        handleEvent = function() end,
    }
end

-- La vista aperta in questo momento, se c'e'.
--
-- Serve al requisito del 15/11 «chiudendo un libro si torna alla vista»:
-- chiudendo un libro KOReader costruisce un gestore di file NUOVO, quindi
-- il plugin nasce di nuovo e puo' riaprire la vista — ma deve sapere di non
-- aprirne una seconda sopra una gia' aperta. Sta qui dentro, e non in
-- `main.lua`, perche' chi sa se una vista e' viva e' la vista stessa: la
-- azzera da se' quando si chiude, comunque venga chiusa.
local _aperta = nil

local KolibreUI = FileChooser:extend{
    manifest = nil,          -- KolibreManifest, gia' caricato
    kolibre = nil,           -- il plugin, per le impostazioni e l'aggancio
    righe_per_schermata = 6, -- configurabile piu' avanti (richiesta dell'11/11)
    agganciato = false,
    cartella_logo = nil,
    show_path = false,
    file_filter = nil,
    -- A tutto schermo e senza cornice, come il file browser di KOReader:
    -- questa vista PRENDE IL POSTO di quella schermata, non ci si appoggia
    -- sopra come una finestra.
    covers_fullscreen = true,
    is_borderless = true,
    is_popout = false,
}

-- ── l'indice del manifesto: il filtro, e i dati delle righe ──────────────

--- Legge il manifesto UNA volta per apertura e ne ricava tre cose.
--
-- Il manifesto e' l'unica verita' del dispositivo su cosa e' di Kolibre.
-- Si legge qui e non riga per riga perche' una riga disegnata non deve
-- costare una scansione: con trecento libri sarebbero trecento scansioni a
-- ogni cambio di pagina.
function KolibreUI:_indicizzaManifesto()
    self.gestiti = {}           -- percorso -> voce del manifesto
    self.cartelle = {}          -- cartella -> quanti libri di Kolibre dentro
    local n = 0
    for _chiave, voce in pairs(self.manifest:all()) do
        if voce.path then
            self.gestiti[voce.path] = voce
            n = n + 1
            -- Si contano anche le cartelle NONNE, non solo quella diretta:
            -- se un giorno i libri stessero in <Autore>/<Titolo>/libro.epub,
            -- il livello autore deve sapere di avere dei libri sotto.
            local dir = voce.path:match("^(.*)/[^/]*$")
            while dir and dir ~= "" do
                self.cartelle[dir] = (self.cartelle[dir] or 0) + 1
                dir = dir:match("^(.*)/[^/]*$")
            end
        end
    end
    self.quanti_gestiti = n
end

--- L'ordine e' il nostro: per nome, e non quello scelto nel file browser.
--
-- **Non e' un capriccio, e' una dipendenza da tagliare.** Cinque dei modi
-- di ordinare di KOReader (per titolo, per autore, per serie...) non
-- guardano il nome del file: chiedono i metadati del libro con
-- `ui.bookinfo:getDocProps(...)`, che se non li trova in cache **apre il
-- documento**. Fatto mentre si disegna un elenco, su un Kindle, vuol dire
-- secondi di schermo fermo per ogni libro — ed e' esattamente la cosa che
-- questa vista ha promesso di non fare mai.
--
-- In piu' `getDocProps` e' un metodo del gestore di file vero, e con il
-- nostro finto (vedi `gestoreFileFinto`) non esiste: la vista morirebbe
-- appena Paolo cambia l'ordinamento del suo file browser, per una ragione
-- che non avrebbe niente a che vedere con quello che stava facendo.
--
-- `strcoll` ordina per nome e non ha un `item_func`: non apre niente.
-- Quando la vista avra' i suoi ordinamenti (per esempio «ultimi
-- scaricati», che il manifesto sa gia' dare) passeranno da qui.
function KolibreUI:getCollate()
    if self.collates and self.collates.strcoll then
        return self.collates.strcoll, "strcoll"
    end
    return FileChooser.getCollate(self)
end

--- Il filtro vero: si vede solo quello che Kolibre ha consegnato.
function KolibreUI:show_file(filename, fullpath)
    if not FileChooser.show_file(self, filename, fullpath) then return false end
    return self.gestiti[fullpath] ~= nil
end

--- Le voci dell'elenco, arricchite con quello che la riga deve disegnare.
--
-- Qui si fanno due cose che la classe di sopra non puo' fare: si buttano le
-- cartelle senza libri di Kolibre (a `show_dir` arriva il solo nome, non il
-- percorso), e si attacca a ogni voce il suo titolo, il suo autore, la sua
-- stima e il suo stato di lettura.
function KolibreUI:genItemTable(dirs, files, path)
    local voci = FileChooser.genItemTable(self, dirs, files, path)
    local tenute = {}
    for _i, voce in ipairs(voci) do
        if voce.is_go_up then
            -- «Indietro» esce dall'elenco e diventa una striscia sua, in
            -- fondo (vedi updateItems). Fuori dall'elenco per due ragioni,
            -- e la seconda e' quella vera: perche' non spenda una riga su
            -- sei, e perche' dentro l'elenco sparirebbe appena si gira
            -- pagina — un comando che c'e' a pagina uno e non a pagina due
            -- e' peggio che non averlo.
            --
            -- Alla radice non c'e' proprio: sopra la libreria di Kolibre non
            -- c'e' un'altra cartella di Kolibre, c'e' il disco.
            if path ~= self.radice then
                voce.titolo = t("koreader.ui.cartella_sopra")
                voce.solo_titolo = true
                self.voce_indietro = voce
            else
                self.voce_indietro = nil
            end
        elseif voce.is_file then
            local m = self.gestiti[voce.path] or {}
            voce.titolo = m.title or voce.text
            voce.autore = m.author
            voce.stima_pagine = m.server_pages
            voce.info = BookList.getBookInfo(voce.path)
            table.insert(tenute, voce)
        elseif self.cartelle[voce.path] then
            voce.e_cartella = true
            voce.titolo = (voce.text or ""):gsub("/$", "")
            voce.quanti = self.cartelle[voce.path]
            -- La foto dell'autore: Kolibre la scrive gia' nella cartella
            -- come `.folder.jpg` a ogni consegna. Se non c'e', la riga mostra
            -- il riquadro col nome, che e' meglio di un buco.
            local foto = voce.path .. "/.folder.jpg"
            if lfs.attributes(foto, "mode") == "file" then voce.immagine = foto end
            table.insert(tenute, voce)
        end
    end
    return tenute
end

-- ── il disegno ───────────────────────────────────────────────────────────

function KolibreUI:init()
    self:_indicizzaManifesto()
    -- `items_per_page` e non `perpage`: `Menu:_recalculateDimen` ricalcola
    -- `perpage` da capo a ogni ridisegno, leggendo `items_per_page` e, se
    -- manca, l'impostazione di KOReader o il suo predefinito, che e'
    -- QUATTORDICI. Scrivendo `perpage` le righe tornavano quattordici al
    -- primo ridisegno e diventavano alte 46 px: copertine francobollo e
    -- mezzo schermo vuoto. Visto sulla prima cattura dal KOReader vero.
    self.items_per_page = self.righe_per_schermata
    -- La radice della libreria: sopra di lei non si sale, perche' sopra non
    -- c'e' la libreria di Kolibre, c'e' il disco.
    self.radice = self.path
    -- Vedi `gestoreFileFinto`: da KOReader v2026.07 `FileChooser` chiede
    -- delle cose a `self.ui` mentre disegna, e noi non siamo posseduti da
    -- nessuno. `self.ui or` e non `=` secco: se un giorno qualcuno aprisse
    -- la vista passandole un gestore vero, quello deve vincere.
    self.ui = self.ui or gestoreFileFinto()
    self.custom_title_bar = Pezzi.BarraAlta:new{
        larghezza = Screen:getWidth(),
        altezza = math.floor(Screen:getHeight() * Pezzi.QUOTA_BARRA),
        agganciato = self.agganciato,
        cartella_logo = self.cartella_logo,
        azioni = {
            casa = function() self:goHome() end,
            cronologia = function() self:_cronologia() end,
            kolibre = function() self:_tastoKolibre() end,
            ultimo = function() self:_ultimoLibro() end,
            menu = function() self:_menuDiKoreader() end,
        },
    }
    FileChooser.init(self)
    _aperta = self
end

--- La vista aperta adesso, o `nil`. La legge `main.lua` per non
--- aprirne una seconda sopra la prima.
function KolibreUI.aperta() return _aperta end

--- La versione della vista, per le note e per chi la mostra.
function KolibreUI.versione() return UI_VERSION end

--- Le misure della schermata: le calcoliamo NOI, e non e' un vezzo.
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
-- **Che cos'e' `available_height`.** L'altezza che resta per le righe dopo
-- aver tolto la barra in alto e la navigazione in basso: e' da lei che si
-- ricava quanto e' alta una riga. La calcolava `Menu:_recalculateDimen`, il
-- metodo di KOReader che ereditavamo.
--
-- **Perche' era nil.** Perche' quel metodo non era piu' quello di KOReader.
-- `coverbrowser` — il plugin che KOReader porta con se' per mostrare le
-- copertine nel gestore di file, e che Paolo usa in modo «elenco con
-- copertine» — quando non e' in modo classico **sostituisce tre metodi
-- sulla CLASSE `FileChooser`**: `updateItems`, `onCloseWidget` e
-- `_recalculateDimen` (`coverbrowser.koplugin/main.lua`, righe 670-690).
-- La nostra vista e' una sottoclasse di `FileChooser`, e in Lua un metodo
-- non trovato sull'oggetto si cerca sulla classe: quindi chiamavamo il
-- `_recalculateDimen` di coverbrowser, che calcola le misure che servono a
-- LUI (`item_height`, `perpage` preso dal suo `files_per_page`) e non
-- scrive mai `available_height`, che a lui non serve.
--
-- **Non era un difetto di una versione di KOReader.** `menu.lua` e
-- `filechooser.lua` della v2025.08 (il Mac) e della v2026.03 (il container
-- di sviluppo) sono identici in tutto quello che riguarda queste misure,
-- diff alla mano. Sul container non si vedeva perche' li' coverbrowser e'
-- in modo classico, e in modo classico rimette a posto gli originali.
--
-- **Perche' calcolare invece di aggiustare dopo.** Appoggiarsi a un metodo
-- che un altro plugin puo' riscrivere vuol dire avere una vista che
-- funziona o no a seconda di quali plugin sono accesi, e il modo di
-- coverbrowser si cambia da un menu: domani basta un tocco. Queste righe
-- fanno quello che fa `Menu:_recalculateDimen` (la fonte e' il suo
-- sorgente) e sono nostre. In piu' tengono le righe a SEI anche quando
-- coverbrowser ne ha decise dieci per se'.
--
-- Il guardiano e' `plugins/koreader/prove/la_vista_regge_coverbrowser.lua`.
function KolibreUI:_recalculateDimen(no_recalculate_dimen)
    local righe = self.righe_per_schermata
    local corpo = self.items_font_size or Menu.getItemFontSize(righe)
    if self.perpage ~= righe or self.font_size ~= corpo then
        self.perpage = righe
        self.font_size = corpo
        no_recalculate_dimen = false
    end
    -- `and self.available_height`: anche quando il ricalcolo non e' stato
    -- chiesto, la PRIMA volta le misure non ci sono ancora e senza di loro
    -- non si disegna niente. E' la rete che mancava: il percorso che ci ha
    -- ucciso passava proprio da qui.
    if no_recalculate_dimen and self.available_height then return end

    local alto = 0
    if self.title_bar and not self.no_title then
        alto = self.title_bar:getHeight()
    end
    local basso = 0
    if self.page_return_arrow and self.page_info_text then
        -- Il padding in piu' e' solo per l'occhio, e lo copiamo da KOReader
        -- per non avere una navigazione piu' attaccata al bordo della sua.
        basso = math.max(self.page_return_arrow:getSize().h,
                         self.page_info_text:getSize().h) + Size.padding.button
    end

    self.available_height = self.inner_dimen.h - alto - basso
    -- `item_dimen` non lo usa il nostro disegno (le righe se la misurano in
    -- `updateItems`), ma lo leggono dei metodi di `Menu` che ereditiamo:
    -- resta scritto perche' non sia nil sotto di loro.
    self.item_dimen = Geom:new{
        x = 0, y = 0,
        w = self.inner_dimen.w,
        h = math.floor(self.available_height / righe),
    }

    self.page_num = self:getPageNumber(#self.item_table)
    if self.page > self.page_num then
        self.page = self.page_num
    end
end

--- La chiusura: quella di KOReader, non quella di coverbrowser.
--
-- Stessa ragione di `_recalculateDimen`: `onCloseWidget` sulla classe
-- `FileChooser` puo' essere quello di coverbrowser, che chiudendo la nostra
-- vista fermerebbe i SUOI lavori in corso e chiuderebbe il SUO database
-- delle copertine. Non e' un guasto, ma non e' roba nostra da spegnere: la
-- vista non usa niente di coverbrowser, e quindi non ha niente di suo da
-- ripulire.
function KolibreUI:onCloseWidget()
    if _aperta == self then _aperta = nil end
    return Menu.onCloseWidget(self)
end

--- Uscendo da KOReader, la vista si toglie di mezzo.
--
-- **Il difetto che questa funzione corregge** (15/11/2026, Paolo: «tiene
-- sospesa la chiusura di Koreader»).
--
-- KOReader non esce quando glielo chiedi: esce quando non resta **nessuna
-- finestra da mostrare**. Il suo giro principale guarda la pila delle
-- finestre a ogni passaggio, e solo quando la trova vuota scrive «No
-- dialogs left to show» e si ferma (`frontend/ui/uimanager.lua`).
--
-- La voce «esci» del menu manda a tutte le finestre l'evento `Exit`; chi lo
-- raccoglie e' il gestore di file, che chiude il proprio menu e se stesso
-- (`FileManagerMenu:exitOrRestart`) — e basta. La nostra vista, che sta
-- SOPRA al gestore di file, non la chiudeva nessuno: restava nella pila, la
-- pila non si svuotava mai, e KOReader continuava a girare con lo schermo
-- fermo.
--
-- Non serve rispondere anche a `Close` (quello di ⌘Q e della X della
-- finestra): quella strada chiama comunque `UIManager:quit()` subito dopo.
-- Serve questa, che e' l'uscita dal menu.
--
-- `broadcastEvent` consegna a tutte le finestre e non si ferma davanti a un
-- `true` (verificato sul sorgente, v2025.08 e v2026.03): chiuderci qui non
-- toglie a nessun altro il suo turno.
function KolibreUI:onExit()
    UIManager:close(self)
end

function KolibreUI:updateItems(select_number, no_recalculate_dimen)
    local old_dimen = self.dimen and self.dimen:copy()
    self.layout = {}
    self.item_group:clear()
    self.page_info:resetLayout()
    self.return_button:resetLayout()
    self.content_group:resetLayout()
    self:_recalculateDimen(no_recalculate_dimen)

    local voci = self.item_table or {}
    local inizio = (self.page - 1) * self.perpage
    local scelta = select_number

    if #voci == 0 then
        -- Un elenco vuoto qui vuol dire una cosa precisa e va detta: non e'
        -- che la cartella e' vuota, e' che Kolibre non ha consegnato niente
        -- a questo dispositivo. Un elenco bianco sembrerebbe un guasto.
        table.insert(self.item_group, VerticalSpan:new{ width = math.floor(self.available_height * 0.35) })
        table.insert(self.item_group, CenterContainer:new{
            dimen = Geom:new{ w = self.inner_dimen.w, h = Screen:scaleBySize(90) },
            TextBoxWidget:new{
                text = self.quanti_gestiti == 0 and t("koreader.ui.nessun_libro")
                    or t("koreader.ui.cartella_vuota"),
                width = self.inner_dimen.w - 2 * Size.padding.large,
                alignment = "center",
                face = Font:getFace("infofont"),
            },
        })
    else
        local alt_indietro = self.voce_indietro
            and math.floor(self.available_height * Pezzi.QUOTA_INDIETRO) or 0
        -- La batteria si prende il suo posto PRIMA che le righe si
        -- dividano quello che resta, come la striscia «indietro»: se si
        -- aggiungesse dopo, le spingerebbe fuori dallo schermo.
        local batteria = Pezzi.rigaBatteria(self.inner_dimen.w,
            math.floor(self.available_height * Pezzi.QUOTA_STATO))
        local alt_stato = batteria and math.floor(self.available_height * Pezzi.QUOTA_STATO) or 0
        local alt_riga = math.floor((self.available_height - alt_indietro - alt_stato) / self.perpage)
        local usata = 0
        for posto = 1, self.perpage do
            local voce = voci[inizio + posto]
            if not voce then break end
            voce.idx = inizio + posto
            if voce.idx == self.itemnumber then scelta = posto end
            local riga = Pezzi.Riga:new{
                voce = voce,
                menu = self,
                dentro_autore = self.dentro_autore,
                dimen = Geom:new{ w = self.inner_dimen.w, h = alt_riga },
            }
            table.insert(self.item_group, riga)
            table.insert(self.layout, { riga })
            usata = usata + alt_riga
        end
        -- Spinta in fondo: l'ultima pagina puo' avere due righe invece di
        -- sei, e quello che sta sotto deve stare dov'e' sempre, non dove
        -- finiscono le righe. Un comando che cambia posto a seconda di
        -- quanti libri ci sono non si impara mai.
        local avanzo = self.available_height - usata - alt_indietro - alt_stato
        if avanzo > 0 then
            table.insert(self.item_group, VerticalSpan:new{ width = avanzo })
        end
        if self.voce_indietro then
            local striscia = Pezzi.Riga:new{
                voce = self.voce_indietro,
                menu = self,
                dimen = Geom:new{ w = self.inner_dimen.w, h = alt_indietro },
            }
            table.insert(self.item_group, striscia)
            table.insert(self.layout, { striscia })
        end
        if batteria then table.insert(self.item_group, batteria) end
    end

    self:updatePageInfo(scelta)
    Menu.mergeTitleBarIntoLayout(self)
    UIManager:setDirty(self.show_parent, function()
        local da_rifare = old_dimen and old_dimen:combine(self.dimen) or self.dimen
        return "ui", da_rifare
    end)
end

-- ── i tocchi ─────────────────────────────────────────────────────────────

--- Tocco su una riga: la cartella si apre, il libro si apre.
--
-- Niente scheda intermedia, per decisione di Paolo del 15/11: e' un file
-- browser, e in un file browser il tocco apre. Quello che oggi non c'e' — la
-- scheda del libro, gli altri comandi — andra' sulla pressione prolungata.
function KolibreUI:onClose()
    UIManager:close(self)
    return true
end

function KolibreUI:onRigaToccata(voce)
    if voce.is_go_up then
        -- **Il percorso si passa com'e'**, senza togliergli il `/..`.
        --
        -- La voce «vai su» di KOReader ha come percorso `<cartella>/..`
        -- (`FileChooser:genItemTable`), e `changeToPath` lo risolve con
        -- `realpath`, che e' quello che lo fa diventare la cartella di
        -- sopra. Togliendogli il `/..` gli si chiedeva di andare nella
        -- cartella in cui si era gia': il tasto non faceva niente, ed e' il
        -- «il tasto indietro non funziona» di Paolo del 15/11. Questa riga
        -- e' ora la stessa che KOReader usa da se' in
        -- `FileChooser:onMenuSelect`.
        self.dentro_autore = false
        return self:changeToPath(voce.path, self.path)
    end
    if voce.e_cartella then
        self.dentro_autore = true
        return self:changeToPath(voce.path)
    end
    if voce.path then
        self:onClose()
        ReaderUI:showReader(voce.path)
    end
end

--- Pressione prolungata: per ora dice solo che cos'e' il libro.
function KolibreUI:onRigaTenuta(voce)
    if voce.e_cartella or not voce.path then return end
    local m = self.gestiti[voce.path] or {}
    UIManager:show(InfoMessage:new{
        text = t("koreader.ui.scheda_breve", {
            titolo = m.title or voce.text,
            autore = m.author or "-",
            biblioteca = m.library or "-",
            pagine = m.server_pages and tostring(m.server_pages) or t("koreader.ui.pagine_ignote"),
        }),
    })
end

function KolibreUI:_cronologia()
    local fm = FileManager.instance
    if fm and fm.history then
        fm.history:onShowHist()
    else
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.cronologia_non_disponibile") })
    end
end

function KolibreUI:_ultimoLibro()
    local ultimo = G_reader_settings:readSetting("lastfile")
    if ultimo and lfs.attributes(ultimo, "mode") == "file" then
        self:onClose()
        ReaderUI:showReader(ultimo)
    else
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.nessun_ultimo_libro") })
    end
end

--- Il quinto tasto apre il menu di KOReader, come deciso il 15/11.
--
-- Da li' si arriva a tutto il resto, compresa l'uscita verso l'interfaccia
-- normale: per questo non c'e' un tasto «esci» a parte, che sarebbe un
-- secondo modo di fare la stessa cosa.
function KolibreUI:_menuDiKoreader()
    local fm = FileManager.instance
    if fm and fm.menu then
        fm.menu:onShowMenu()
    else
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.menu_non_disponibile") })
    end
end

--- Il tasto di Kolibre: sincronizza, e basta.
--
-- Non e' un controllo della connessione: e' l'azione che il dispositivo fa
-- gia' all'avvio, rifatta a mano. Lo stato del logo si aggiorna dopo, con
-- quello che la sincronizzazione ha scoperto — che e' l'unico modo onesto
-- di saperlo senza bloccare il lettore per tre secondi.
function KolibreUI:_tastoKolibre()
    if not (self.kolibre and self.kolibre.syncNow) then return end
    self.kolibre:syncNow(true, "ui_libreria")
    UIManager:nextTick(function()
        self:aggiornaDopoSincronizzazione()
    end)
end

--- Rilegge il manifesto e lo stato dell'aggancio, e ridisegna.
function KolibreUI:aggiornaDopoSincronizzazione()
    local ok, err = pcall(function()
        self:_indicizzaManifesto()
        local agganciato = self.manifest:getMeta("mai_agganciato") and true or false
        if self.custom_title_bar and self.custom_title_bar.aggiorna then
            self.custom_title_bar:aggiorna(agganciato)
        end
        self:refreshPath()
    end)
    if not ok then logger.warn("Kolibre UI: aggiornamento non riuscito:", err) end
end

return KolibreUI
