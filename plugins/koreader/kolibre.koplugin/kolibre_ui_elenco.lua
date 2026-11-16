-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one.

--[[--
Una finestra di Kolibre che mostra un elenco di libri e basta.

**Da zero: che cos'e' e perche' esiste.** Le viste di Kolibre su KOReader
sono tre. La **libreria** cammina delle cartelle vere sul disco, e per quello
eredita dal file browser di KOReader (`kolibre_ui_libreria.lua`). Le altre
due non camminano niente: la **cronologia** e' un elenco che KOReader tiene
in un file, e il **pannello degli ultimi invii** e' un elenco che il
manifesto di Kolibre sa gia' dare. Sono due finestre che si aprono sopra la
libreria, si guardano e si chiudono.

Quelle due sono la stessa finestra con dentro voci diverse: stesso aspetto,
stessi cinque tasti in cima, stesso tasto «indietro» in fondo, stesso modo di
aprire un libro. Scriverle due volte avrebbe voluto dire correggere due volte
ogni difetto — e dimenticarsene una volta su due, che e' il modo normale in
cui due copie smettono di essere uguali. Qui c'e' la finestra; chi la usa
dice soltanto **come si chiama** e **quali voci ci vanno dentro**.

**Che cosa deve dare una sottoclasse.** Tre cose:

  * `chiave` — un nome con cui questa finestra si riconosce da aperta, per
    non impilarne due identiche;
  * `titolo()` — il nome scritto nella barra, sotto i cinque tasti;
  * `voci()` — l'elenco da mostrare, gia' nell'ordine giusto;
  * `vuoto()` — la frase da scrivere quando non c'e' niente da mostrare,
    perche' un elenco bianco sembra un guasto.

**Perche' eredita da `Menu` e non da `FileChooser`.** `FileChooser` serve
alla libreria perche' legge delle cartelle vere dal disco. Un elenco in un
file non e' una cartella: ereditare da `FileChooser` vorrebbe dire portarsi
dietro la lettura delle cartelle, il `self.ui` che dalla v2026.07 serve alle
cartelle preferite, e l'ordinamento che apre i documenti — tutto per non
usarne niente.

**Perche' non e' una classe base anche della libreria.** Perche' non puo'
esserlo: quella **deve** essere un `FileChooser`, e in Lua un oggetto ha un
genitore solo. Il disegno che le tre hanno davvero in comune — le misure, le
righe, la batteria, l'«indietro», le strisciate — sta percio' in
`kolibre_ui_comune.lua`, che sono funzioni che ricevono la vista invece di
una classe da ereditare. Questo file e' il pezzo in piu' che le due finestre
hanno fra loro e la libreria no.
]]

local Menu = require("ui/widget/menu")
local ReaderUI = require("apps/reader/readerui")
local Screen = require("device").screen
local UIManager = require("ui/uimanager")
local lfs = require("libs/libkoreader-lfs")
local Pezzi = require("kolibre_ui_pezzi")
local Comune = require("kolibre_ui_comune")
local Azioni = require("kolibre_ui_azioni")

-- Le finestre aperte in questo momento, per nome.
--
-- **Una tabella e non una variabile per file.** Le finestre sono due e
-- domani potrebbero essere tre: una variabile per file vorrebbe dire
-- ricopiare in ognuno lo stesso meccanismo, e sbagliarlo in quella in cui ci
-- si distrae. La chiave la sceglie la sottoclasse.
local aperte = {}

local Elenco = Menu:extend{
    manifest = nil,          -- KolibreManifest, gia' caricato
    kolibre = nil,           -- il plugin, per la sincronizzazione
    cartella_logo = nil,
    agganciato = false,
    righe_per_schermata = nil,
    chiave = nil,
    -- A tutto schermo e senza cornice, come la vista libreria: PRENDE IL
    -- POSTO della schermata, non ci si appoggia sopra come una finestra.
    covers_fullscreen = true,
    is_borderless = true,
    is_popout = false,
    title = "",
    no_title = false,
}

--- La finestra di quel nome aperta adesso, o `nil`.
function Elenco.apertaDi(chiave) return aperte[chiave] end

--- Le tre cose che una sottoclasse deve dire. Qui rispondono il minimo che
--- non rompe niente: una finestra senza nome, vuota, che lo dichiara.
function Elenco:titolo() return "" end
function Elenco:voci() return {} end
function Elenco:vuoto() return "" end

--- I cinque tasti in cima. La sottoclasse puo' ritoccarne uno e tornare
--- questa stessa tabella, invece di riscriverla tutta.
--
-- `casa` chiude: queste finestre stanno sopra la libreria, e «casa» da qui
-- vuol dire tornarci. `cronologia` non fa niente per difetto — chi e' gia'
-- nella cronologia non ci si riapre sopra — e chi non ci e' lo sovrascrive.
function Elenco:azioniBarra()
    return {
        casa = function() self:onClose() end,
        cronologia = function() end,
        kolibre = function() self:_tastoKolibre() end,
        ultimo = function() self:_ultimoLibro() end,
        menu = function() self:_menuDiKoreader() end,
    }
end

--- Le voci della finestra, con il campo che KOReader pretende.
--
-- **Ogni riga deve avere un `text`, anche se non lo disegniamo noi.** Trovato
-- il 16/11/2026 misurando e non leggendo: toccando il numero di pagina in
-- fondo, `Menu` apre un suo riquadro con «Search» e «Go to letter»
-- (`page_info_text.hold_input`, con `call_hold_input_on_tap`: basta un
-- tocco). Quei due pulsanti chiamano `Menu:goToMenuItemMatching`, che fa
-- `util.fixUtf8(item.text, "?")` su OGNI voce, e `fixUtf8` comincia con
-- `#str`. Le nostre righe hanno `titolo`, `autore`, `path` — un `text` non
-- ce l'avevano, quindi l'errore era «attempt to get length of local 'str' (a
-- nil value)» e la finestra cadeva. Riprodotto sul KOReader del Mac prima di
-- correggere, con una sonda che adesso e' la prova `finestre`.
--
-- La vista libreria non ne soffriva: le sue righe nascono da
-- `FileChooser:genItemTable`, che il `text` lo mette (il nome del file).
--
-- Si scrive il **titolo** e non il nome del file, cosi' la ricerca di
-- KOReader — che da qui in poi non cade piu' — cerca anche la cosa giusta.
function Elenco:_vociDaMostrare()
    local voci = self:voci()
    for _i, voce in ipairs(voci) do
        if type(voce) == "table" and voce.text == nil then
            voce.text = voce.titolo or voce.path or ""
        end
    end
    return voci
end

function Elenco:init()
    self.righe_per_schermata = self.righe_per_schermata or Pezzi.RIGHE_PER_DIFETTO
    -- `items_per_page` e non `perpage`: vedi il commento gemello nella vista
    -- libreria. Scrivendo `perpage`, `Menu` lo ricalcola al primo ridisegno
    -- leggendo `items_per_page`, e le righe tornano quattordici.
    self.items_per_page = self.righe_per_schermata
    self.item_table = self:_vociDaMostrare()
    self.custom_title_bar = Pezzi.BarraAlta:new{
        larghezza = Screen:getWidth(),
        altezza = math.floor(Screen:getHeight() * Pezzi.QUOTA_BARRA),
        agganciato = self.agganciato,
        cartella_logo = self.cartella_logo,
        -- **Il nome della finestra, chiesto da Paolo il 16/11/2026.** Nella
        -- libreria quella riga dice in che cartella sei; qui dice che cosa
        -- stai guardando, ed e' scritta in nero perche' e' un nome e non una
        -- didascalia. Senza, le due finestre erano indistinguibili dalla
        -- libreria a colpo d'occhio: stessi tasti, stesse righe.
        titolo = self:titolo(),
        azioni = self:azioniBarra(),
        -- **Tenendo premuto il logo si apre il menu del plugin** (Paolo,
        -- 16/11/2026), lo stesso primo livello che sta in Strumenti ▸
        -- Kolibre. Da qui dentro e' la via piu' corta per sincronizzare,
        -- sfogliare il catalogo o cambiare un'impostazione, senza passare
        -- dal menu di KOReader.
        azioni_tenute = {
            kolibre = function() Azioni.menuDelPlugin(self) end,
        },
    }
    Menu.init(self)
    -- **Dopo** `Menu.init`: il gruppo delle frecce nasce li' dentro.
    pcall(function() Comune.batteriaNellaBarra(self) end)
    if self.chiave then aperte[self.chiave] = self end
end

function Elenco:_recalculateDimen(no_recalculate_dimen)
    return Comune.misure(self, no_recalculate_dimen,
        self.righe_per_schermata or Pezzi.RIGHE_PER_DIFETTO)
end

function Elenco:updateItems(select_number, no_recalculate_dimen)
    return Comune.ridisegna(self, self.righe_per_schermata or Pezzi.RIGHE_PER_DIFETTO,
        self:vuoto(), select_number, no_recalculate_dimen)
end

--- Stessa ragione della vista libreria: `onCloseWidget` sulla classe `Menu`
--- puo' essere stato riscritto da coverbrowser, e chiudendo la nostra
--- finestra fermerebbe i SUOI lavori. Qui si chiama quello di KOReader.
function Elenco:onCloseWidget()
    if self.chiave and aperte[self.chiave] == self then aperte[self.chiave] = nil end
    return Menu.onCloseWidget(self)
end

--- Uscendo da KOReader, questa finestra si toglie di mezzo.
--
-- KOReader si chiude solo quando la pila delle finestre e' vuota: una
-- finestra che resta li' tiene sospesa la chiusura, ed e' il difetto che
-- Paolo ha segnalato il 15/11 sulla vista libreria.
function Elenco:onExit()
    UIManager:close(self)
end

function Elenco:onClose()
    UIManager:close(self)
    return true
end

--- «Indietro», in fondo a sinistra: qui non c'e' una cartella sopra, quindi
--- vuol dire «chiudi e torna alla libreria». Lo stesso tasto nello stesso
--- posto, con il significato che ha in questa finestra.
function Elenco:onReturn()
    return self:onClose()
end

function Elenco:siPuoTornare() return true end

--- Le strisciate: su e giu' girano pagina, e niente chiude la finestra per
--- sbaglio. Il perche' sta per esteso in `Comune.swipe`.
function Elenco:onSwipe(_arg, ges)
    return Comune.swipe(self, ges and ges.direction)
end

function Elenco:onMultiSwipe()
    return true
end

function Elenco:onRigaToccata(voce)
    if not voce.path then return end
    -- Si chiude PRIMA di aprire il libro: senza, questa finestra resterebbe
    -- nella pila sotto il lettore, e chiudendo il libro si tornerebbe qui
    -- invece che alla libreria.
    self:onClose()
    ReaderUI:showReader(voce.path)
end

--- La pressione prolungata non fa niente, per ora: nella vista libreria apre
--- la scheda del libro, e qui ci andra' la stessa cosa quando la scheda sara'
--- una sola invece di due copie.
--- Tenendo premuto un libro: la scheda, e le cose che si possono fargli.
--
-- Fino al 16/11/2026 qui non succedeva niente, mentre nella libreria usciva
-- la scheda del libro: due finestre identiche che allo stesso gesto si
-- comportavano in modo diverso. Ora il menu e' lo stesso in tutte e tre —
-- vedi `kolibre_ui_azioni.lua`.
function Elenco:onRigaTenuta(voce)
    Azioni.perUnLibro(self, voce)
end

--- Rilegge l'elenco: lo chiama chi ha appena cambiato qualcosa a un libro.
--
-- Senza, togliendo un libro la sua riga resterebbe li' e il comando
-- sembrerebbe non aver fatto niente. Si rilegge tutto invece di togliere la
-- riga: le voci nascono da `voci()`, che e' la verita', e una tabella
-- ritoccata a mano e' una seconda verita' che prima o poi divergera'.
function Elenco:rileggi()
    self.item_table = self:_vociDaMostrare()
    self:updateItems()
end

--- Il tasto Kolibre: sincronizza, e poi rilegge l'elenco.
--
-- Il «poi rilegge» non e' cortesia: una sincronizzazione porta le copertine
-- (venti per volta), e se l'elenco non si rifacesse si vedrebbero ancora i
-- riquadri col titolo su libri la cui copertina e' appena arrivata — cioe'
-- un comando che sembra non aver fatto niente.
function Elenco:_tastoKolibre()
    if not (self.kolibre and self.kolibre.syncNow) then return end
    self.kolibre:syncNow(true, "ui_" .. tostring(self.chiave))
    UIManager:nextTick(function()
        pcall(function()
            self.item_table = self:_vociDaMostrare()
            self:updateItems()
        end)
    end)
end

function Elenco:_ultimoLibro()
    local ultimo = G_reader_settings:readSetting("lastfile")
    if ultimo and lfs.attributes(ultimo, "mode") == "file" then
        self:onClose()
        ReaderUI:showReader(ultimo)
    end
end

function Elenco:_menuDiKoreader()
    local FileManager = require("apps/filemanager/filemanager")
    local fm = FileManager.instance
    if fm and fm.menu then fm.menu:onShowMenu() end
end

--- Il manifesto indicizzato per percorso, che serve a tutte e due le
--- finestre: una per arricchire le voci della cronologia, l'altra perche' il
--- manifesto E' il suo elenco.
--
-- Si legge una volta per apertura e non riga per riga: con trecento libri
-- sarebbero trecento scansioni a ogni cambio di pagina.
function Elenco:_manifestoPerPercorso()
    local per_percorso = {}
    if not self.manifest then return per_percorso end
    local ok = pcall(function()
        for _chiave, voce in pairs(self.manifest:all()) do
            if voce.path then per_percorso[voce.path] = voce end
        end
    end)
    if not ok then return {} end
    return per_percorso
end

return Elenco
