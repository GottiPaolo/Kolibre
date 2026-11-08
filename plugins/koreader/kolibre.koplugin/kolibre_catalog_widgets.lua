--[[--
I riquadri della vista a griglia del catalogo: la copertina (vera o
segnaposto) e la cella toccabile che la contiene. La vista a elenco non passa
di qui — riusa il Menu di KOReader cosi' com'e' (vedi kolibre_catalog.lua),
quindi qui non c'e' nessun ListItem.

**Come si scelgono le dimensioni del testo.** Non da una formula sulla
lunghezza della stringa: si parte dal corpo piu' grande e si scende finche'
il testo, MISURATO, ci sta nello spazio disponibile. E' il metodo di
`coverbrowser.koplugin` di KOReader (il suo FakeCover fa lo stesso con il suo
`sizedec`), ed e' piu' affidabile di una stima, perche' quanto spazio occupi
una riga dipende dal font, dalla lingua e dallo schermo — tre cose che una
formula sul numero di caratteri non conosce.

Costa la costruzione di qualche widget buttato via a ogni cella. Su una
griglia da nove o dodici libri non si misura; se un giorno si misurasse, la
risposta e' una cache per (testo, larghezza, altezza), non il ritorno alla
stima.
]]

local BD = require("ui/bidi")
local Blitbuffer = require("ffi/blitbuffer")
local CenterContainer = require("ui/widget/container/centercontainer")
local Font = require("ui/font")
local FrameContainer = require("ui/widget/container/framecontainer")
local Geom = require("ui/geometry")
local GestureRange = require("ui/gesturerange")
local ImageWidget = require("ui/widget/imagewidget")
local InputContainer = require("ui/widget/container/inputcontainer")
local Screen = require("device").screen
local Size = require("ui/size")
local TextBoxWidget = require("ui/widget/textboxwidget")
local VerticalGroup = require("ui/widget/verticalgroup")
local VerticalSpan = require("ui/widget/verticalspan")
local util = require("util")
local t = require("kolibre_lingua").t

local CatalogWidgets = {}

-- Proporzione di una copertina di libro: piu' alta che larga. Serve a dare
-- alla copertina segnaposto la stessa forma di una vera, cosi' la griglia non
-- balla a seconda di quali copertine sono arrivate.
local PROPORZIONE = 0.68

-- Il testo non arriva mai al bordo del riquadro: è la stessa scelta che fa
-- KOReader nel suo FakeCover, e senza, le lettere toccano la cornice.
local QUOTA_LARGHEZZA_TESTO = 7 / 8

--- Tronca a `massimo` caratteri senza spezzare un carattere UTF-8 a metà.
local function accorcia(testo, massimo)
    testo = tostring(testo or "")
    if #testo <= massimo then return testo end
    return util.fixUtf8(testo:sub(1, massimo - 3), "?") .. "..."
end

--- Un TextBoxWidget al corpo piu' grande che sta in `altezza_max`.
--
-- Scende di un punto per volta da `corpo_max` a `corpo_min` e si ferma al
-- primo che ci sta; se non ci sta nemmeno il minimo, tiene il minimo e lascia
-- che sia l'ellissi di TextBoxWidget a chiudere il discorso. Restituisce il
-- widget e il corpo scelto, perche' chi chiama a volte vuole sapere quanto e'
-- grande il titolo per decidere l'autore.
local function testoCheCiSta(testo, larghezza, altezza_max, corpo_max, corpo_min)
    local corpo = corpo_max
    while corpo > corpo_min do
        local prova = TextBoxWidget:new{
            text = testo,
            face = Font:getFace("cfont", corpo),
            width = larghezza,
            alignment = "center",
        }
        local alta = prova:getSize().h
        prova:free(true)
        if alta <= altezza_max then break end
        corpo = corpo - 1
    end
    return TextBoxWidget:new{
        text = testo,
        face = Font:getFace("cfont", corpo),
        width = larghezza,
        height = altezza_max,
        alignment = "center",
        height_overflow_show_ellipsis = true,
    }, corpo
end

--- La copertina segnaposto: titolo, autore e una riga di stato in un riquadro
--- della stessa forma di una copertina vera.
function CatalogWidgets.buildFakeCover(book, width, height, footer)
    local cornice = Size.border.thin + Size.padding.default
    local inner_w = math.max(1, width - 2 * cornice)
    local inner_h = math.max(1, height - 2 * cornice)
    local testo_w = math.max(1, math.floor(inner_w * QUOTA_LARGHEZZA_TESTO))

    local titolo = BD.auto(accorcia(book and book.title or t("koreader.catalog.untitled"), 60))
    local autore = book and book.author and book.author ~= ""
        and BD.auto(accorcia(book.author, 44)) or nil

    -- La riga di stato ("sto scaricando la copertina", "non c'e'") sta in
    -- fondo e non compete con il titolo: corpo fisso e piccolo, e lo spazio
    -- che le resta viene tolto per primo.
    local piede_h = footer and footer ~= "" and math.floor(inner_h * 0.14) or 0
    local resto_h = math.max(1, inner_h - piede_h)
    local titolo_h = autore and math.floor(resto_h * 0.62) or resto_h
    local autore_h = autore and math.max(1, resto_h - titolo_h) or 0

    -- I due widget passano per una variabile invece di finire dentro
    -- `table.insert` direttamente, e non e' pignoleria: `testoCheCiSta`
    -- restituisce DUE valori, e in Lua una chiamata in ultima posizione fra gli
    -- argomenti si espande a tutti. Scritta `table.insert(contenuto,
    -- testoCheCiSta(...))` diventa la forma a tre argomenti —
    -- `table.insert(lista, posizione, valore)` — che vuole un numero al
    -- secondo posto, e manda giu' KOReader su ogni libro che ha un autore
    -- (crash segnalato il 04/11/2026). La variabile tronca al primo valore.
    local contenuto = VerticalGroup:new{ align = "center" }
    local widget_titolo = testoCheCiSta(titolo, testo_w, titolo_h, 18, 11)
    table.insert(contenuto, widget_titolo)
    if autore then
        local widget_autore = testoCheCiSta(autore, testo_w, autore_h, 13, 9)
        table.insert(contenuto, widget_autore)
    end
    if piede_h > 0 then
        table.insert(contenuto, TextBoxWidget:new{
            text = footer,
            face = Font:getFace("xx_smallinfofont"),
            width = testo_w,
            height = piede_h,
            alignment = "center",
            height_overflow_show_ellipsis = true,
        })
    end

    return CatalogWidgets.riquadro(contenuto, width, height, inner_w, inner_h)
end

--- La cornice comune a copertina vera e segnaposto.
--
-- Esiste perche' i due casi devono avere lo STESSO ingombro: se la copertina
-- vera avesse un bordo e il segnaposto un altro, la griglia cambierebbe passo
-- a seconda di quali copertine sono gia' arrivate dal server — e arrivano una
-- alla volta, quindi si vedrebbe muovere.
function CatalogWidgets.riquadro(contenuto, width, height, inner_w, inner_h)
    return FrameContainer:new{
        width = width,
        height = height,
        margin = 0,
        padding = Size.padding.default,
        bordersize = Size.border.thin,
        background = Blitbuffer.COLOR_WHITE,
        CenterContainer:new{
            dimen = Geom:new{ w = inner_w or width, h = inner_h or height },
            contenuto,
        },
    }
end

--- La copertina vera se il file c'e', altrimenti il segnaposto con il motivo.
function CatalogWidgets.buildCoverWidget(book, width, height, path, state)
    if path then
        local cornice = Size.border.thin + Size.padding.default
        local immagine_w = math.max(1, width - 2 * cornice)
        local immagine_h = math.max(1, height - 2 * cornice)
        return CatalogWidgets.riquadro(ImageWidget:new{
            file = path,
            width = immagine_w,
            height = immagine_h,
            scale_factor = 0,
        }, width, height, immagine_w, immagine_h)
    end

    local motivo
    if state == "loading" then
        motivo = t("koreader.catalog.cover_loading")
    elseif state == "failed" then
        motivo = t("koreader.catalog.cover_failed")
    else
        motivo = t("koreader.catalog.cover_none")
    end
    return CatalogWidgets.buildFakeCover(book, width, height, motivo)
end

-- La cella toccabile della griglia. `dimen`, `entry` e `menu` li passa chi la
-- costruisce (updateMosaicItems, in kolibre_catalog.lua); `entry.callback` e'
-- gia' quello che costruisce _catalogItems — conferma piu' scaricamento —
-- quindi qui non serve nessun altro smistamento.
local MosaicItem = InputContainer:extend{
    entry = nil,
    dimen = nil,
    menu = nil,
}

function MosaicItem:init()
    self.ges_events = {
        TapSelect = {
            GestureRange:new{ ges = "tap", range = self.dimen },
        },
    }

    local book = self.entry.book

    -- Quanto della cella va alle due righe di testo sotto la copertina. Il
    -- minimo in pixel reali evita che su uno schermo piccolo l'etichetta si
    -- riduca a una fessura illeggibile.
    local etichetta_h = math.max(Screen:scaleBySize(44), math.floor(self.dimen.h * 0.24))
    local cover_w_max = math.max(1, self.dimen.w - 2 * Size.padding.default)
    local cover_h_max = math.max(1, self.dimen.h - etichetta_h - Size.span.vertical_default)
    -- La copertina prende la forma giusta restando dentro entrambi i limiti:
    -- si parte dall'altezza e si ricava la larghezza, poi si ritaglia.
    local cover_h = math.min(cover_h_max, math.floor(cover_w_max / PROPORZIONE))
    local cover_w = math.min(cover_w_max, math.floor(cover_h * PROPORZIONE))

    local contenuto = VerticalGroup:new{ align = "center" }
    -- Anche questo passa per una variabile, per la regola spiegata in
    -- `buildFakeCover`: oggi `buildCoverWidget` restituisce un valore solo, e
    -- il giorno in cui ne restituisse due questa riga cadrebbe senza che
    -- niente qui lo faccia sospettare.
    local widget_copertina = CatalogWidgets.buildCoverWidget(
        book, cover_w, cover_h,
        self.menu:cachedThumbnailPath(book),
        self.menu:thumbnailState(book))
    table.insert(contenuto, widget_copertina)

    -- Titolo e autore su due righe sotto la copertina, come nel segnaposto.
    --
    -- Perche' il titolo si prende MENO della meta': TextBoxWidget allinea in
    -- alto, non centra verticalmente. Dando al titolo lo spazio di due righe
    -- quando ne occupa una — il caso comune — il vuoto restava SOTTO il
    -- titolo, cioe' proprio fra titolo e autore, e l'autore finiva piu'
    -- vicino alla cella sotto che al libro a cui si riferisce. Stringendo il
    -- titolo il vuoto residuo cade dopo l'autore, fuori dal gruppo, dove lo
    -- assorbe il CenterContainer che avvolge tutto distribuendolo sopra e
    -- sotto l'insieme invece di spezzare la coppia.
    local etichetta_w = math.max(1, self.dimen.w - 2 * Size.padding.tiny)
    local autore = book and book.author and book.author ~= "" and accorcia(book.author, 30) or nil
    local titolo_h = autore and math.floor(etichetta_h * 0.46) or etichetta_h
    local autore_h = autore and math.max(1, etichetta_h - titolo_h) or 0

    table.insert(contenuto, VerticalSpan:new{ width = Size.span.vertical_default })
    local widget_titolo, corpo_titolo = testoCheCiSta(
        accorcia(book and book.title or t("koreader.catalog.untitled"), 30),
        etichetta_w, titolo_h, 18, 11)
    table.insert(contenuto, widget_titolo)
    if autore then
        -- L'autore si lega al corpo SCELTO per il titolo, non a un preset suo:
        -- cosi' resta visibilmente piu' piccolo su qualunque dispositivo,
        -- anche dove due preset di font sarebbero finiti quasi uguali.
        local corpo_autore = math.max(9, corpo_titolo - 4)
        table.insert(contenuto, TextBoxWidget:new{
            text = autore,
            face = Font:getFace("cfont", corpo_autore),
            width = etichetta_w,
            height = autore_h,
            alignment = "center",
            height_overflow_show_ellipsis = true,
        })
    end

    self[1] = FrameContainer:new{
        width = self.dimen.w,
        height = self.dimen.h,
        margin = 0,
        padding = 0,
        bordersize = 0,
        CenterContainer:new{
            dimen = Geom:new{ w = self.dimen.w, h = self.dimen.h },
            contenuto,
        },
    }
end

function MosaicItem:onTapSelect()
    if self.entry.callback then self.entry.callback() end
    return true
end

CatalogWidgets.MosaicItem = MosaicItem

return CatalogWidgets
