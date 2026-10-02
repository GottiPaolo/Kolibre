--[[--
Cover and book-item widgets for the Kolibre catalog browser's mosaic (cover
grid) view — a trimmed port of the equivalent widgets in BookOrbit (an
earlier unreleased attempt at the same problem), keeping
only the parts that don't assume BookOrbit's own domain model (read-status
badges, bulk-selection highlighting, per-book progress bars, dashboard
cards — none of which Kolibre's catalog has or needs). `buildFakeCover`/
`buildCoverWidget` render a real cover image or a text placeholder;
`MosaicItem` is the tappable grid cell — list mode reuses stock KOReader
Menu rendering (see kolibre_catalog.lua), so there's no ListItem here.
]]

local BD = require("ui/bidi")
local CenterContainer = require("ui/widget/container/centercontainer")
local Font = require("ui/font")
local FrameContainer = require("ui/widget/container/framecontainer")
local Geom = require("ui/geometry")
local GestureRange = require("ui/gesturerange")
local ImageWidget = require("ui/widget/imagewidget")
local InputContainer = require("ui/widget/container/inputcontainer")
local Blitbuffer = require("ffi/blitbuffer")
local Size = require("ui/size")
local TextBoxWidget = require("ui/widget/textboxwidget")
local VerticalGroup = require("ui/widget/verticalgroup")
local VerticalSpan = require("ui/widget/verticalspan")
local t = require("kolibre_lingua").t

local CatalogWidgets = {}

local SCALE_BY_SIZE = require("device").screen:scaleBySize(1000000) * (1 / 1000000)

local function shortText(text, max_len)
    text = tostring(text or "")
    if #text <= max_len then return text end
    local util = require("util")
    return util.fixUtf8(text:sub(1, max_len - 3), "?") .. "..."
end

local function longestLineLength(text)
    local longest = 0
    for line in (tostring(text or "") .. "\n"):gmatch("(.-)\n") do
        longest = math.max(longest, #line)
    end
    return math.max(1, longest)
end

local function mosaicLabelFontSize(text, width, height)
    local longest = longestLineLength(text)
    local height_size = math.floor(height * 0.46 / SCALE_BY_SIZE)
    local width_size = math.floor(width / math.max(8, math.min(longest, 16)) * 2.05 / SCALE_BY_SIZE)
    local card_size = math.floor(width * (1 / 9.5) / SCALE_BY_SIZE)
    return math.max(13, math.min(20, height_size, width_size, card_size))
end

function CatalogWidgets.buildFakeCover(book, width, height, footer)
    local inner_w = math.max(1, width - 2 * Size.padding.default - 2 * Size.border.thin)
    local inner_h = math.max(1, height - 2 * Size.padding.default - 2 * Size.border.thin)
    local title_h = math.floor(inner_h * 0.58)
    local author_h = math.floor(inner_h * 0.22)
    local footer_h = math.max(1, inner_h - title_h - author_h)

    local content = VerticalGroup:new{ align = "center" }
    table.insert(content, VerticalSpan:new{ width = Size.span.vertical_default })
    table.insert(content, TextBoxWidget:new{
        text = BD.auto(shortText(book and book.title or t("koreader.catalog.untitled"), 60)),
        width = inner_w,
        height = title_h,
        alignment = "center",
        face = Font:getFace("smallinfofont", 16),
        height_overflow_show_ellipsis = true,
    })
    table.insert(content, TextBoxWidget:new{
        text = book and book.author and BD.auto(shortText(book.author, 44)) or "",
        width = inner_w,
        height = author_h,
        alignment = "center",
        face = Font:getFace("x_smallinfofont"),
        height_overflow_show_ellipsis = true,
    })
    table.insert(content, TextBoxWidget:new{
        text = footer or "",
        width = inner_w,
        height = footer_h,
        alignment = "center",
        face = Font:getFace("xx_smallinfofont"),
        height_overflow_show_ellipsis = true,
    })

    return FrameContainer:new{
        width = width,
        height = height,
        margin = 0,
        padding = Size.padding.default,
        bordersize = Size.border.thin,
        background = Blitbuffer.COLOR_WHITE,
        CenterContainer:new{
            dimen = Geom:new{ w = inner_w, h = inner_h },
            content,
        },
    }
end

function CatalogWidgets.buildCoverWidget(book, width, height, path, state)
    if path then
        return CenterContainer:new{
            dimen = Geom:new{ w = width, h = height },
            FrameContainer:new{
                margin = 0,
                padding = 0,
                bordersize = Size.border.thin,
                ImageWidget:new{
                    file = path,
                    width = width,
                    height = height,
                    scale_factor = 0,
                },
            },
        }
    end

    local footer
    if state == "loading" then
        footer = t("koreader.catalog.cover_loading")
    elseif state == "failed" then
        footer = t("koreader.catalog.cover_failed")
    else
        footer = t("koreader.catalog.cover_none")
    end
    return CatalogWidgets.buildFakeCover(book, width, height, footer)
end

-- A tappable grid cell — dimen/entry/menu are set by the caller (see
-- kolibre_catalog.lua's updateMosaicItems), same construction pattern as
-- every other Menu-item widget in this plugin's own catalog code.
-- `entry.callback` is the same callback _catalogItems already builds
-- (confirmation + download) — no extra dispatch indirection needed.
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
    local label_h = math.max(require("device").screen:scaleBySize(44), math.floor(self.dimen.h * 0.24))
    local max_cover_w = math.max(1, self.dimen.w - 2 * Size.padding.default)
    local available_cover_h = math.max(1, self.dimen.h - label_h - Size.span.vertical_default)
    local cover_h = math.min(available_cover_h, math.floor(max_cover_w / 0.68))
    local cover_w = math.min(max_cover_w, math.floor(cover_h * 0.68))

    local path = self.menu:cachedThumbnailPath(book)
    local state = self.menu:thumbnailState(book)

    local content = VerticalGroup:new{ align = "center" }
    table.insert(content, CatalogWidgets.buildCoverWidget(book, cover_w, cover_h, path, state))

    -- Titolo e autore su due righe distinte sotto la copertina — stesso
    -- schema già usato da buildFakeCover per la copertina segnaposto, qui
    -- allineato anche al caso di copertina reale (prima mostrava solo il
    -- titolo, unico caso disallineato dal resto della UI a due righe).
    --
    -- title_h era il 62% di label_h: per un titolo di una riga (il caso
    -- comune) questo lasciava molto spazio vuoto SOTTO il testo (TextBoxWidget
    -- allinea in alto, non centra verticalmente), spazio che finiva proprio
    -- tra titolo e autore: l'autore si leggeva più vicino alla riga sotto che
    -- non al libro a cui si riferisce". Restringendo title_h il vuoto residuo
    -- (se c'è) resta DOPO l'autore, cioè fuori dal gruppo — lì lo assorbe il
    -- CenterContainer che avvolge l'intero blocco copertina+titolo+autore,
    -- distribuendolo sopra/sotto l'insieme invece che spezzare la coppia.
    local label_w = math.max(1, self.dimen.w - 2 * Size.padding.tiny)
    local has_author = book and book.author and book.author ~= ""
    local title_h = has_author and math.floor(label_h * 0.46) or label_h
    local author_h = has_author and math.max(1, label_h - title_h) or 0

    local title_text = shortText(book and book.title or t("koreader.catalog.untitled"), 30)
    local title_font_size = mosaicLabelFontSize(title_text, label_w, title_h)
    -- Dimensione esplicita e più piccola (non un preset separato) cosicché
    -- il titolo resti visibilmente più grande dell'autore a prescindere da
    -- quanto i due font preset differiscano su un dato dispositivo.
    local author_font_size = math.max(10, title_font_size - 4)

    table.insert(content, VerticalSpan:new{ width = Size.span.vertical_default })
    table.insert(content, TextBoxWidget:new{
        text = title_text,
        width = label_w,
        height = title_h,
        alignment = "center",
        face = Font:getFace("cfont", title_font_size),
        height_overflow_show_ellipsis = true,
    })
    if has_author then
        table.insert(content, TextBoxWidget:new{
            text = shortText(book.author, 30),
            width = label_w,
            height = author_h,
            alignment = "center",
            face = Font:getFace("cfont", author_font_size),
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
            content,
        },
    }
end

function MosaicItem:onTapSelect()
    if self.entry.callback then self.entry.callback() end
    return true
end

CatalogWidgets.MosaicItem = MosaicItem

return CatalogWidgets
