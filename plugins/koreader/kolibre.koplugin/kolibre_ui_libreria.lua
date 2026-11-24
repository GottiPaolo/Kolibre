--[[--
La vista «libreria» di Kolibre su KOReader: un file browser nostro, che
mostra SOLO i libri che Kolibre ha consegnato a questo dispositivo.

**Che cosa e', da zero.** Al posto del gestore di file di KOReader — che
mostra cartelle e file come un gestore di file qualunque — si apre questa:
le cartelle degli autori con la loro foto e quanti libri hanno dentro, poi i
libri, ognuno con una copertina, il titolo, una riga di stato a parole e una
barra lunga in proporzione alle pagine e riempita in proporzione a quanto
hai letto. Sopra, cinque tasti e la riga che dice dove sei; sotto, la
navigazione di KOReader, con dentro «indietro» a sinistra e la carica della
batteria a destra.

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
local InfoMessage = require("ui/widget/infomessage")
local ReaderUI = require("apps/reader/readerui")
local Screen = require("device").screen
local UIManager = require("ui/uimanager")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")
local Pezzi = require("kolibre_ui_pezzi")
local Comune = require("kolibre_ui_comune")
local DataStorage = require("datastorage")
local KolibreCopertine = require("kolibre_copertine")
local Azioni = require("kolibre_ui_azioni")
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
-- server e riempita quanto hai letto, il tasto «indietro», e il ritorno alla
-- vista quando chiudi un libro.
--
-- **Resta spenta per difetto**: finche' non si accende l'impostazione,
-- KOReader e' quello di sempre. Il Kindle non la vede e non la vedra'
-- finche' Paolo non lo decide.
local UI_VERSION = "0.8.0"

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
--- Quante righe per schermata, come le ha chieste Paolo.
--
-- **Perche' si limita invece di fidarsi.** Il valore sta in
-- `G_reader_settings`, cioe' in un file di testo che si puo' modificare a
-- mano, e arriva anche da un ripristino di backup fatto su un dispositivo
-- diverso. Un 40 li' dentro vorrebbe dire righe di trenta pixel: non un
-- elenco fitto, uno schermo di righe nere. Un 1 vorrebbe dire una riga per
-- schermata. Fuori da 4-8 si riporta dentro, invece di rifiutare: una
-- schermata che funziona vale piu' di un messaggio d'errore.
--
-- La chiave si chiama `kolibre_ui_righe` e non `..._righe_per_schermata`
-- per la stessa ragione per cui `kolibre_libreria_allavvio` non e' stata
-- rinominata quando l'opzione ha cambiato nome: una chiave rinominata e'
-- un'impostazione che si perde in silenzio al primo aggiornamento.
local function righeScelte()
    local scelta = tonumber(G_reader_settings:readSetting("kolibre_ui_righe"))
    if not scelta then return Pezzi.RIGHE_PER_DIFETTO end
    scelta = math.floor(scelta)
    if scelta < Pezzi.RIGHE_MINIME then return Pezzi.RIGHE_MINIME end
    if scelta > Pezzi.RIGHE_MASSIME then return Pezzi.RIGHE_MASSIME end
    return scelta
end

-- **L'ordinamento per data non c'e' piu', e la data non e' andata persa.**
--
-- Il 16/11/2026 ne ho fatto un ordinamento da scegliere in un menu. Paolo
-- l'ha corretto: «non volevo un ordinamento dei libri per data, ma un vero e
-- proprio pannello con gli ultimi invii dal server». Ha ragione, e la
-- differenza non e' di gusto. Un ordinamento ti fa **perdere** l'elenco che
-- avevi: per vedere cos'e' arrivato ieri dovevi scompaginare la libreria, e
-- poi rimetterla a posto. Un pannello e' una finestra che si apre, si
-- guarda e si chiude — e la libreria resta dov'era.
--
-- Gli invii stanno quindi in `kolibre_ui_consegne.lua`, e si aprono tenendo
-- premuto il tasto della casa. Qui l'ordine e' uno solo, per nome, e non
-- c'e' niente da scegliere: una preferenza in meno da ricordarsi.

local _aperta = nil

local KolibreUI = FileChooser:extend{
    manifest = nil,          -- KolibreManifest, gia' caricato
    kolibre = nil,           -- il plugin, per le impostazioni e l'aggancio
    righe_per_schermata = nil, -- la scelta di Paolo: vedi KolibreUI.righe()
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
    -- La cartella delle copertine, una volta sola: `KolibreCopertine.percorso`
    -- crea la cartella se manca, e chiamarlo per ogni riga vorrebbe dire
    -- chiederlo al disco trecento volte a ogni cambio di pagina.
    self.cartella_copertine = KolibreCopertine.cartella(DataStorage)
    self.gestiti = {}           -- percorso -> voce del manifesto
    self.cartelle = {}          -- cartella -> quanti libri di Kolibre dentro
    -- **Si contano i FILE, non le righe del manifesto** (corretto il
    -- 17/11/2026). Lo stesso libro puo' avere due righe — la voce
    -- `hash:<impronta>` che la vecchia migrazione ha adottato, e quella con
    -- l'identita' vera che `_linkHashMatch` ha scritto dopo senza togliere
    -- la prima. Contandole tutte e due, una cartella d'autore diceva «17
    -- libri» avendone quindici, e il totale della libreria era gonfio.
    --
    -- E fra due righe per lo stesso file vince sempre la stessa
    -- (`Comune.miglioreFra`): prima vinceva l'ultima che capitava, e `pairs`
    -- non ha un ordine — cioe' il titolo, l'autore e la copertina di quel
    -- libro potevano cambiare da un'apertura all'altra.
    for _chiave, voce in pairs(self.manifest:all()) do
        if voce.path then
            self.gestiti[voce.path] = Comune.miglioreFra(self.gestiti[voce.path], voce)
        end
    end
    local n = 0
    for percorso in pairs(self.gestiti) do
        n = n + 1
        -- Si contano anche le cartelle NONNE, non solo quella diretta:
        -- se un giorno i libri stessero in <Autore>/<Titolo>/libro.epub,
        -- il livello autore deve sapere di avere dei libri sotto.
        local dir = percorso:match("^(.*)/[^/]*$")
        while dir and dir ~= "" do
            self.cartelle[dir] = (self.cartelle[dir] or 0) + 1
            dir = dir:match("^(.*)/[^/]*$")
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
    -- Azzerato PRIMA del giro: se la voce «vai su» non c'e' affatto — alla
    -- radice del disco KOReader non la mette — quello che resta qui dentro
    -- sarebbe il percorso della cartella di prima, cioe' un tasto
    -- «indietro» acceso che porta altrove.
    self.sopra = nil
    for _i, voce in ipairs(voci) do
        if voce.is_go_up then
            -- **«Indietro» non e' una voce dell'elenco.** Dentro l'elenco
            -- spariva appena si girava pagina — un comando che c'e' a pagina
            -- uno e non a pagina due e' peggio che non averlo — e una
            -- striscia sua sopra la barra costava spazio alle righe. Adesso
            -- e' la freccia in fondo a sinistra, che c'e' sempre e sta
            -- ferma: vedi `Comune.tastoIndietro` e `KolibreUI:onReturn`.
            --
            -- Qui si tiene solo il percorso da cui KOReader lo ricava, che
            -- e' `<cartella>/..`, e si butta la voce.
            self.sopra = (path ~= self.radice) and voce.path or nil
        elseif voce.is_file then
            local m = self.gestiti[voce.path] or {}
            voce.titolo = m.title or voce.text
            voce.autore = m.author
            voce.stima_pagine = m.server_pages
            voce.info = BookList.getBookInfo(voce.path)
            -- La copertina, SE e' gia' sul dispositivo. Qui si guarda un
            -- file e basta: scaricarla la scarica la sincronizzazione
            -- (`main.lua`, `scaricaLeCopertine`), mai il disegno di una
            -- riga. Una vista che va in rete mentre disegna e' uno schermo
            -- fermo, e su un e-ink si vede.
            --
            -- Finche' non c'e', la riga mostra il riquadro col titolo: non
            -- e' un buco, e' quello che dice di che libro si tratta.
            voce.immagine = KolibreCopertine.perVoce(self.cartella_copertine, m)
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
    return self:_ordina(tenute)
end

--- L'ordine delle voci: le cartelle in cima, poi i libri, tutto per nome.
--
-- **Perche' si riordina qui invece di lasciar fare a KOReader.**
-- `FileChooser.genItemTable` ordina leggendo due impostazioni **sue**
-- (`reverse_collate` e `collate_mixed`): con il file browser di Paolo
-- impostato al contrario, questa vista si sarebbe rovesciata insieme a lui,
-- per una ragione che non ha niente a che vedere con quello che stava
-- facendo. E' la stessa regola per cui la vista si calcola le proprie
-- misure invece di ereditarle — ed e' il motivo per cui queste righe sono
-- rimaste anche dopo che l'ordinamento per data se n'e' andato.
--
-- **Le cartelle restano in cima.** Sono dei contenitori, non dei libri:
-- in mezzo all'elenco farebbero inciampare l'occhio a ogni schermata.
function KolibreUI:_ordina(voci)
    local cartelle, libri = {}, {}
    for _i, voce in ipairs(voci) do
        table.insert(voce.e_cartella and cartelle or libri, voce)
    end
    local function perNome(a, b)
        return (a.text or "") < (b.text or "")
    end
    table.sort(cartelle, perNome)
    table.sort(libri, perNome)
    local fuori = {}
    for _i, v in ipairs(cartelle) do table.insert(fuori, v) end
    for _i, v in ipairs(libri) do table.insert(fuori, v) end
    return fuori
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
    -- La scelta si legge QUI e non sulla classe: letta sulla classe sarebbe
    -- quella del primo avvio per sempre, e cambiarla non si vedrebbe mai.
    self.righe_per_schermata = self.righe_per_schermata or righeScelte()
    self.items_per_page = self.righe_per_schermata
    -- **Il riquadro di ricerca di KOReader diventa il nostro** (Paolo,
    -- 17/11/2026): vedi il commento gemello in `kolibre_ui_elenco.lua`. Qui
    -- serve piu' che altrove — la libreria e' divisa in cartelle per autore,
    -- e cercare «quello che si vede adesso» dalla radice vorrebbe dire
    -- cercare fra i nomi delle cartelle. I libri stanno dentro.
    self.search_callback = function(testo) Comune.cerca(self, testo) end
    -- La radice della libreria: sopra di lei non si sale, perche' sopra non
    -- c'e' la libreria di Kolibre, c'e' il disco. **Si puo' passare**
    -- (24/11/2026): la vista si apre anche dentro la cartella di un autore —
    -- uscendo da un suo libro, o rifacendola dopo aver cambiato le righe —
    -- e prima prendeva quella cartella come radice, da cui non si risaliva.
    self.radice = self.radice or self.path
    if self.path ~= self.radice then self.dentro_autore = true end
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
        -- Alla radice si scrive comunque il nome della libreria: una barra
        -- che cresce al primo passo dentro una cartella e si accorcia
        -- tornando indietro e' un salto, non un'informazione.
        percorso = t("koreader.ui.percorso_radice"),
        azioni = {
            casa = function() self:_casa() end,
            cronologia = function() self:_cronologia() end,
            kolibre = function() self:_tastoKolibre() end,
            ultimo = function() self:_ultimoLibro() end,
            menu = function() self:_menuDiKoreader() end,
        },
        -- **La pressione prolungata sulla casa apre gli ultimi invii**
        -- (Paolo, 16/11/2026). Sta sulla casa e non su un sesto tasto
        -- perche' e' la stessa domanda fatta da vicino: la casa dice «tutta
        -- la libreria», tenendola premuta si chiede «e di nuovo, cosa c'e'?».
        --
        -- **E la pressione prolungata sul logo apre il menu del plugin**
        -- (Paolo, 16/11/2026): lo stesso primo livello che sta in Strumenti
        -- ▸ Kolibre, chiesto a `main.lua` e non riscritto qui (vedi
        -- `kolibre_ui_azioni.lua`).
        azioni_tenute = {
            casa = function() self:_consegne() end,
            kolibre = function() Azioni.menuDelPlugin(self) end,
        },
    }
    FileChooser.init(self)
    -- **Dopo** `FileChooser.init`, non prima: il gruppo delle frecce lo
    -- costruisce `Menu.init`, che gira lì dentro. Chiamarla prima vorrebbe
    -- dire infilare la batteria in un gruppo che ancora non esiste.
    pcall(function() self:_batteriaNellaBarra() end)
    -- **E qui, non prima**, il controllo di compatibilità: le misure da
    -- guardare le scrive `FileChooser.init`, e guardarle prima vorrebbe
    -- dire guardarle tutte vuote. Dentro un `pcall` perché una diagnosi che
    -- uccide il paziente non è una diagnosi — vedi
    -- `kolibre_ui_compatibilita.lua` per il perché guarda gli invarianti e
    -- non chi li ha rotti.
    pcall(function() self:_controlloDiCompatibilita() end)
    _aperta = self
end

--- Se un altro plugin ci ha cambiato le misure sotto i piedi, lo dice.
---
--- Una volta per sessione, nel registro sempre e a schermo una sola volta:
--- la vista si ridisegna a ogni cambio di pagina, e un avviso per ridisegno
--- sarebbe un dispositivo inservibile.
function KolibreUI:_controlloDiCompatibilita()
    local ok, Compat = pcall(require, "kolibre_ui_compatibilita")
    if not ok then return end
    local loader
    pcall(function() loader = require("pluginloader") end)
    Compat.controlla(self, function(testo)
        UIManager:show(InfoMessage:new{ text = testo })
    end, loader)
end

--- La vista aperta adesso, o `nil`. La legge `main.lua` per non
--- aprirne una seconda sopra la prima.
--- Infila la batteria nel gruppo delle frecce, in fondo allo schermo.
--
-- **Perche' si MUTA `page_info` invece di costruire un fondo nostro.**
-- Quel gruppo lo costruisce `Menu.init`, e il contenitore che lo tiene
-- appoggiato in fondo allo schermo e' una variabile locale di quel metodo:
-- da fuori non si raggiunge. La tabella `self.page_info` invece e' la
-- stessa che il contenitore ha in mano, quindi infilarci dentro un pezzo si
-- vede, senza riscrivere niente di KOReader — che e' la regola di questa
-- vista da quando coverbrowser ci ha chiuso KOReader.
--
-- **Lo spazio davanti non e' decorazione.** `page_info` e' CENTRATO in
-- fondo allo schermo, e la sua larghezza e' la somma dei suoi pezzi:
-- aggiungendo la batteria solo in coda, il «pagina 2 di 5» si sposterebbe a
-- sinistra di mezza batteria. Uno spazio della stessa larghezza davanti
-- rimette il centro dov'era.
--
-- **Il corpo e' quello del testo delle pagine**, chiesto al widget vero
-- invece di indovinato: cosi' la barra non cresce di un pixel, e quello che
-- l'elenco ha guadagnato togliendo la striscia non se lo riprende la barra.
function KolibreUI:_batteriaNellaBarra()
    return Comune.batteriaNellaBarra(self)
end

--- Le righe scelte, e i limiti: li legge il menu in `main.lua`.
function KolibreUI.righe() return righeScelte() end
function KolibreUI.righeMinime() return Pezzi.RIGHE_MINIME end
function KolibreUI.righeMassime() return Pezzi.RIGHE_MASSIME end

--- Scrive la scelta. `flush` perche' su un Kindle una chiusura pulita e' raro
-- che arrivi, e senza quello l'impostazione si perderebbe allo spegnimento —
-- e' lo stesso difetto corretto il 15/11 su `kolibre_libreria_allavvio`.
function KolibreUI.scegliRighe(quante)
    quante = math.floor(tonumber(quante) or Pezzi.RIGHE_PER_DIFETTO)
    if quante < Pezzi.RIGHE_MINIME then quante = Pezzi.RIGHE_MINIME end
    if quante > Pezzi.RIGHE_MASSIME then quante = Pezzi.RIGHE_MASSIME end
    G_reader_settings:saveSetting("kolibre_ui_righe", quante)
    G_reader_settings:flush()
    return quante
end

--- La vista aperta, o `nil`.
--
-- **Viva davvero, non solo ricordata** (24/11/2026, i «salti» del Kindle).
-- `_aperta` si azzera quando la vista si chiude; ma una vista rimasta nella
-- pila sotto un lettore, e poi buttata via insieme al gestore di file senza
-- che nessuno la chiudesse, resterebbe ricordata per sempre: il plugin la
-- crederebbe aperta e non ne aprirebbe un'altra, e si finirebbe nel file
-- browser di KOReader. Si chiede quindi a UIManager se e' ancora mostrata
-- (`isWidgetShown`, in 2025.08, 2026.03 e 2026.07).
function KolibreUI.aperta()
    if _aperta and not UIManager:isWidgetShown(_aperta) then _aperta = nil end
    return _aperta
end

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
-- Il guardiano e' la prova `la_vista_regge_coverbrowser`.
function KolibreUI:_recalculateDimen(no_recalculate_dimen)
    -- `or righeScelte()` e cintura e bretelle: se un giorno questo metodo
    -- fosse chiamato prima di `init`, un nil qui dentro sarebbe un errore di
    -- aritmetica, cioe' la vista che muore — lo stesso guaio di
    -- `available_height` di cui parla il commento qui sopra.
    return Comune.misure(self, no_recalculate_dimen,
        self.righe_per_schermata or righeScelte())
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
    -- **Se e' accesa, c'e' sempre** (Paolo, 24/11/2026): una chiusura che
    -- nessuno ha voluto — non un libro che si apre, non KOReader che esce,
    -- non la spunta tolta — e sotto resterebbe il file browser di KOReader.
    -- La vista si riapre dov'era, al giro dopo.
    if not self._chiusura_voluta then
        local kolibre, dove = self.kolibre, self.path
        UIManager:nextTick(function()
            if kolibre and type(kolibre.riportaLaVista) == "function" then
                pcall(function() kolibre:riportaLaVista(dove) end)
            end
        end)
    end
    return Menu.onCloseWidget(self)
end

--- Una chiusura voluta: non si riapre da sola.
function KolibreUI:chiudi()
    self._chiusura_voluta = true
    UIManager:close(self)
end

--- **Un libro si sta aprendo: la vista esce dalla pila** (24/11/2026).
--
-- E' la causa dei «salti» che Paolo vedeva sul Kindle uscendo da un libro.
-- KOReader, prima di mostrare un libro, manda `ShowingReader` a tutte le
-- finestre (readerui.lua, in 2025.08, 2026.03 e 2026.07): il gestore di file
-- si chiude, la nostra vista no. Se il libro lo apriva lei, si chiudeva da
-- se'; ma da tutte le altre strade — gli ultimi invii, la cronologia, la
-- ricerca, la cronologia di KOReader, un gesto — restava nella pila sotto il
-- lettore. Chiudendo il libro nasceva un gestore di file nuovo SOPRA di lei,
-- il plugin la credeva aperta e non la rifaceva: davanti c'era il file
-- browser di KOReader. Ora esce da sola, qualunque sia la strada, e alla
-- chiusura del libro si rifa' come sempre.
function KolibreUI:onShowingReader()
    self:chiudi()
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
    self:chiudi()
end

--- Il percorso da scrivere in cima: dove sei, rispetto alla radice.
--
-- **Non il percorso del disco.** `/mnt/us/documents/Luigi Pirandello` non
-- dice niente di piu' di «Luigi Pirandello» e non ci sta nella barra. Si
-- scrive quello che c'e' DENTRO la libreria, e alla radice il suo nome.
--
-- Il separatore e' « ▸ » e non «/»: non e' un percorso da copiare, e' un
-- posto in cui sei.
function KolibreUI:_percorsoDaScrivere()
    local qui = self.path
    local radice = self.radice
    if type(qui) ~= "string" or qui == "" then return nil end
    if type(radice) ~= "string" or radice == "" or qui == radice then
        return t("koreader.ui.percorso_radice")
    end
    local dentro = qui
    if qui:sub(1, #radice) == radice then
        dentro = qui:sub(#radice + 1)
    end
    dentro = dentro:gsub("^/+", ""):gsub("/+$", "")
    if dentro == "" then return t("koreader.ui.percorso_radice") end
    return (dentro:gsub("/", " ▸ "))
end

function KolibreUI:updateItems(select_number, no_recalculate_dimen)
    -- **Il percorso si aggiorna PRIMA di ridisegnare**, perche' la barra
    -- puo' cambiare altezza (la riga del percorso compare o sparisce) e le
    -- misure dell'elenco si fanno su quella. Dopo, l'elenco sarebbe alto
    -- per la barra di prima.
    if self.custom_title_bar and self.custom_title_bar.aggiornaPercorso then
        if self.custom_title_bar:aggiornaPercorso(self:_percorsoDaScrivere()) then
            no_recalculate_dimen = false
        end
    end
    -- Il testo del vuoto dice una cosa precisa e diversa nei due casi: se il
    -- manifesto e' vuoto Kolibre non ha mai consegnato niente a questo
    -- dispositivo; se non lo e', questa cartella e' vuota. Un elenco bianco
    -- senza spiegazione sembrerebbe un guasto, e il motivo non si indovina.
    local vuoto = self.quanti_gestiti == 0 and t("koreader.ui.nessun_libro")
        or t("koreader.ui.cartella_vuota")
    return Comune.ridisegna(self, self.righe_per_schermata or righeScelte(),
        vuoto, select_number, no_recalculate_dimen)
end

-- ── i tocchi ─────────────────────────────────────────────────────────────

--- Tocco su una riga: la cartella si apre, il libro si apre.
--
-- Niente scheda intermedia, per decisione di Paolo del 15/11: e' un file
-- browser, e in un file browser il tocco apre. Quello che oggi non c'e' — la
-- scheda del libro, gli altri comandi — andra' sulla pressione prolungata.
--- «Indietro» non chiude la vista (Paolo, 24/11/2026: se e' accesa c'e'
--- sempre; chi non la vuole toglie la spunta). Il tasto si consuma qui, cosi'
--- non arriva al menu sotto.
function KolibreUI:onClose()
    return true
end

--- La casa: la radice della libreria, non quella di KOReader.
--
-- **`FileChooser:goHome()` qui era sbagliato**, e si vedeva solo su un
-- dispositivo vero: porta alla cartella `home_dir` di KOReader, che su un
-- Kindle e' `/mnt/us` — cioe' fuori dalla libreria di Kolibre, in un posto
-- dove il nostro filtro non ha niente da mostrare. Il tasto casa di questa
-- vista vuol dire «torna in cima alla LIBRERIA», e la radice della libreria
-- la vista ce l'ha gia' in mano da `init`.
function KolibreUI:_casa()
    if self.path ~= self.radice then
        self.dentro_autore = false
        self:changeToPath(self.radice)
    end
end

--- La freccia in fondo a sinistra: sali di una cartella.
--
-- **Il percorso si passa com'e'**, senza togliergli il `/..`. La voce «vai
-- su» di KOReader ha come percorso `<cartella>/..`
-- (`FileChooser:genItemTable`), e `changeToPath` lo risolve con `realpath`,
-- che e' quello che lo fa diventare la cartella di sopra. Togliendogli il
-- `/..` gli si chiedeva di andare nella cartella in cui si era gia': il
-- tasto non faceva niente, ed e' il «il tasto indietro non funziona» di
-- Paolo del 15/11.
function KolibreUI:onReturn()
    if not self.sopra then return true end
    self.dentro_autore = false
    self:changeToPath(self.sopra, self.path)
    return true
end

--- C'e' un posto dove tornare? Alla radice no: sopra la libreria di Kolibre
--- non c'e' un'altra cartella di Kolibre, c'e' il disco.
function KolibreUI:siPuoTornare()
    return self.sopra ~= nil
end

--- Le strisciate: su e giu' girano pagina, e **niente chiude la vista**.
--- Il perche' sta per esteso in `Comune.swipe`.
function KolibreUI:onSwipe(_arg, ges)
    return Comune.swipe(self, ges and ges.direction)
end

function KolibreUI:onMultiSwipe()
    return true
end

function KolibreUI:onRigaToccata(voce)
    if voce.e_cartella then
        self.dentro_autore = true
        return self:changeToPath(voce.path)
    end
    if voce.path then
        self:chiudi()
        ReaderUI:showReader(voce.path)
    end
end

--- Pressione prolungata: per ora dice solo che cos'e' il libro.
--- Tenendo premuto un libro: la scheda, e le cose che si possono fargli.
--
-- **Prima qui c'era solo la scheda** — titolo, autore, biblioteca, pagine —
-- che si leggeva e si chiudeva. Dal 16/11/2026 quelle stesse righe sono il
-- titolo di un menu con le azioni (Paolo: «tenendo premuto un libro si apre
-- un menu»). Non si e' perso niente, e la domanda «su quale libro sto
-- agendo?» ha la risposta scritta sopra i pulsanti — che e' la domanda da
-- farsi prima di premere «elimina».
function KolibreUI:onRigaTenuta(voce)
    Azioni.perUnLibro(self, voce)
end

--- Rilegge l'elenco dopo che e' cambiato qualcosa a un libro.
--
-- `refreshPath` e' di `FileChooser` e rilegge la cartella in cui siamo: e' la
-- cosa giusta qui, perche' un libro cancellato non c'e' piu' sul disco e
-- `genItemTable` riparte da quello che il disco dice.
--
-- **Ma la cartella stessa puo' non esserci piu'**, e questo non e' un caso di
-- scuola: la libreria e' divisa in cartelle per autore, e l'ultimo libro di
-- un autore che si cancella — o che il server toglie da questo lettore —
-- porta via la cartella in cui si sta guardando. `refreshPath` su una
-- cartella che non esiste piu' non da' errore: disegna una cartella **vuota**,
-- cioe' lascia la vista in un posto che non c'e', con l'elenco vuoto e il
-- titolo di un autore che non ha piu' libri. Allora si torna in cima alla
-- libreria, che e' il solo posto che c'e' sempre.
function KolibreUI:rileggi()
    if self.radice and self.path and self.path ~= self.radice
            and lfs.attributes(self.path, "mode") ~= "directory" then
        self.dentro_autore = false
        pcall(function() self:changeToPath(self.radice) end)
        return
    end
    pcall(function() self:refreshPath() end)
end

--- Il tasto «cronologia» apre la NOSTRA cronologia.
--
-- Prima passava la mano a quella di KOReader (`fm.history:onShowHist()`):
-- una sua schermata, col suo aspetto, in mezzo alla nostra. Paolo ha chiesto
-- le copertine anche li', «con lo stesso aspetto: copertina e barra», e dal
-- 16/11/2026 quella vista e' nostra — vedi `kolibre_ui_cronologia.lua`.
--
-- **Non si chiude la libreria.** La cronologia si apre SOPRA, e chiudendola
-- si torna qui: e' lo stesso rapporto che ha un menu con la schermata da cui
-- l'hai aperto, e vale anche se dalla cronologia si apre un libro — chiuso
-- il libro, la libreria e' ancora sotto.
--
-- Sotto `pcall`, e con il ripiego su quella di KOReader: un modulo che non
-- si carica (un aggiornamento a meta') non deve togliere a Paolo la
-- cronologia, deve dargliela come prima.
function KolibreUI:_cronologia()
    local ok, KolibreCronologia = pcall(require, "kolibre_ui_cronologia")
    if ok and type(KolibreCronologia.aperta) == "function" and KolibreCronologia.aperta() then
        return   -- gia' aperta: non se ne impila una seconda
    end
    if ok then
        local vista
        local costruita, errore = pcall(function()
            vista = KolibreCronologia:new{
                manifest = self.manifest,
                kolibre = self.kolibre,
                agganciato = self.agganciato,
                cartella_logo = self.cartella_logo,
                righe_per_schermata = self.righe_per_schermata,
            }
            UIManager:show(vista)
        end)
        if costruita then return end
        logger.err("Kolibre: la cronologia non si apre:", errore)
        if vista then pcall(function() UIManager:close(vista) end) end
    else
        logger.err("Kolibre: la cronologia non si carica:", KolibreCronologia)
    end
    -- Il ripiego: quella di KOReader, che c'e' sempre.
    local fm = FileManager.instance
    if fm and fm.history then
        fm.history:onShowHist()
    else
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.cronologia_non_disponibile") })
    end
end

--- Il pannello degli ultimi invii, tenendo premuto il tasto della casa.
--
-- **Perche' una finestra e non un ordinamento** sta scritto in cima a questo
-- file: un ordinamento ti fa perdere l'elenco che avevi, una finestra la
-- chiudi e la libreria e' ancora li'.
--
-- Si apre SOPRA, come la cronologia, e per le stesse ragioni: chiudendola si
-- torna qui, e anche aprendo un libro da li' — chiuso il libro, la libreria
-- e' ancora sotto.
function KolibreUI:_consegne()
    local ok, Consegne = pcall(require, "kolibre_ui_consegne")
    if not ok then
        logger.err("Kolibre: il pannello degli invii non si carica:", Consegne)
        return
    end
    if type(Consegne.aperta) == "function" and Consegne.aperta() then
        return   -- gia' aperto: non se ne impila un secondo
    end
    local vista
    local costruita, errore = pcall(function()
        vista = Consegne:new{
            manifest = self.manifest,
            kolibre = self.kolibre,
            agganciato = self.agganciato,
            cartella_logo = self.cartella_logo,
            righe_per_schermata = self.righe_per_schermata,
        }
        UIManager:show(vista)
    end)
    if costruita then return end
    logger.err("Kolibre: il pannello degli invii non si apre:", errore)
    if vista then pcall(function() UIManager:close(vista) end) end
end

function KolibreUI:_ultimoLibro()
    local ultimo = G_reader_settings:readSetting("lastfile")
    if ultimo and lfs.attributes(ultimo, "mode") == "file" then
        self:chiudi()
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
