--[[--
I pezzi disegnati della UI di Kolibre: la barra in alto coi cinque tasti e
le righe dell'elenco (una cartella d'autore, un libro).

**Perche' non bastano i mattoni di KOReader.** Le righe del suo Menu sono
`MenuItem`, e un `MenuItem` sa disegnare testo: titolo, una scritta a destra,
grassetto. Qui una riga deve mostrare una copertina, due righe di testo di
peso diverso e una barra lunga in proporzione alle pagine del libro. Non e'
un `MenuItem` con piu' campi: e' un altro disegno.

**E perche' non si tocca KOReader per farlo.** `Menu:updateItems` costruisce
i suoi `MenuItem` a mano, senza un punto di estensione. La strada non e'
sostituirgli quella funzione — e' sovrascriverla nella NOSTRA sottoclasse,
che e' quello che `kolibre_catalog.lua` fa gia' per la griglia del catalogo
da ottobre e regge gli aggiornamenti. Vedi `kolibre_ui_libreria.lua`.

**Le misure vengono dallo schermo, mai scritte.** Il Kindle di Paolo e' un
Paperwhite di 10a generazione e nemmeno KOReader sa quanti pixel ha: li
chiede al framebuffer. Qui si fa lo stesso, e le proporzioni sono quelle
decise sulle prove d'aspetto del 15/11 (`prove-aspetto/ui-koreader/`).
]]

local Blitbuffer = require("ffi/blitbuffer")
local CenterContainer = require("ui/widget/container/centercontainer")
local Font = require("ui/font")
local FrameContainer = require("ui/widget/container/framecontainer")
local Geom = require("ui/geometry")
local GestureRange = require("ui/gesturerange")
local HorizontalGroup = require("ui/widget/horizontalgroup")
local HorizontalSpan = require("ui/widget/horizontalspan")
local IconWidget = require("ui/widget/iconwidget")
local ImageWidget = require("ui/widget/imagewidget")
local InputContainer = require("ui/widget/container/inputcontainer")
local LeftContainer = require("ui/widget/container/leftcontainer")
local LineWidget = require("ui/widget/linewidget")
local RightContainer = require("ui/widget/container/rightcontainer")
local Device = require("device")
local Screen = Device.screen
local Size = require("ui/size")
local TextBoxWidget = require("ui/widget/textboxwidget")
local TextWidget = require("ui/widget/textwidget")
local UIManager = require("ui/uimanager")
local VerticalGroup = require("ui/widget/verticalgroup")
local VerticalSpan = require("ui/widget/verticalspan")
local util = require("util")
local t = require("kolibre_lingua").t

local Pezzi = {}

-- ── le proporzioni decise sulle prove d'aspetto ──────────────────────────
--
-- Tutte relative allo schermo: sul 1072x1448 del Paperwhite danno
-- esattamente le misure delle prove, su un altro schermo si adattano.

--: la barra in alto. 0.079 di 1448 fa 114 px, la misura delle prove.
Pezzi.QUOTA_BARRA = 0.079
--: le icone dei quattro tasti normali, dentro la barra.
Pezzi.QUOTA_ICONA = 0.46
--: il logo, che e' il tasto piu' importante e il solo che dice uno stato.
--  **0.77 della barra e' l'ALTEZZA DEL DISEGNO, non quella dell'immagine**:
--  i due PNG hanno un margine bianco intorno, e misurarli per la tela
--  darebbe un marchio alto quanto le icone invece che una volta e mezzo.
--  E' l'errore trovato il 15/11 guardando il riquadro dell'inchiostro, ed e'
--  la ragione per cui `ritagliaMargine` esiste. 0.77 di 114 fa 88 px.
Pezzi.QUOTA_LOGO = 0.77
--: la copertina di una riga, in proporzione all'altezza della riga.
Pezzi.QUOTA_COPERTINA = 0.80
--: la forma di una copertina: piu' alta che larga.
Pezzi.PROPORZIONE_COPERTINA = 0.68
--: la striscia «indietro», in proporzione allo spazio dell'elenco. Sottile
--  e in fondo, per decisione di Paolo del 15/11: era una riga intera in
--  cima, cioe' un sesto dello schermo speso per un comando che si usa una
--  volta per cartella, e messa dove cade l'occhio per primo.
Pezzi.QUOTA_INDIETRO = 0.065
-- ── le misure DENTRO una riga ────────────────────────────────────────────
--
-- Sono altezze del DISEGNO delle lettere, in frazione dell'altezza della
-- riga, e passano tutte da `corpo()` prima di arrivare a `Font:getFace`.
--
-- **Perche' la somma deve stare sotto 1, e con margine.** Un testo disegnato
-- e' piu' alto delle sue lettere: KOReader gli lascia sopra e sotto lo
-- spazio degli accenti e delle code, e quello che ne esce e' circa **1,55
-- volte** l'altezza chiesta (misurato sul KOReader vero del Mac: corpo 44 px
-- -> riga di testo alta 68 px). Quindi il conto di una riga di libro e':
--
--     titolo      0,190 x 1,55 = 0,295
--     aria        0,030
--     autore      0,125 x 1,55 = 0,194
--     aria        0,030
--     stato       0,125 x 1,55 = 0,194
--     aria        0,030
--     barra       0,110
--                 ───────────────────
--                 0,883 dell'altezza della riga
--
-- Il resto e' aria in fondo, ed e' voluta: senza, due righe vicine si
-- toccano e l'elenco diventa un muro. I numeri sono piu' piccoli di quelli
-- del 15/11 (0,22 e 0,15) perche' quelli erano scelti quando il doppio
-- ingrandimento faceva sembrare tutto piu' grande: vedi `corpo()`.
Pezzi.QUOTA_TITOLO = 0.19
Pezzi.QUOTA_SOTTOTITOLO = 0.125
Pezzi.QUOTA_ARIA = 0.03
Pezzi.QUOTA_BARRA_PAGINE = 0.11

--: la riga della batteria, in fondo a sinistra. Sottile: e' un'informazione
--  che si cerca, non che si legge.
Pezzi.QUOTA_STATO = 0.035

--: la lunghezza MINIMA della barra, in frazione della sua lunghezza piena.
--
--  Scelta di Paolo del 15/11/2026. Prima il minimo era «alta quanto e'
--  spessa», cioe' un cerchietto: un libro di sei pagine su una scala che
--  arriva a ottocento diventava un pallino, e un pallino non si legge come
--  «un libro cortissimo», si legge come un guasto. A 0,12 un libro di sei
--  pagine e uno di cento restano diversi fra loro — il secondo e' piu' del
--  doppio — e tutti e due si vedono come barre.
Pezzi.QUOTA_BARRA_MINIMA = 0.12

--: oltre questo numero di pagine la barra e' piena e porta il segno di
--  «fuori scala». 800 e' la scelta di Paolo dell'11/11, da provare su un
--  campione vero. **Sta scritto qui e in nessun altro posto.**
Pezzi.SOGLIA_PAGINE = 800

--- Da PIXEL a «punti» di KOReader: la conversione senza cui i font sfondano.
--
-- **Il difetto che questa funzione corregge** (15/11/2026, sul Mac di Paolo:
-- «le dimensioni e font sono sproporzionati»). `Font:getFace(nome, misura)`
-- non prende una misura in pixel: prende una misura in «punti» e la
-- moltiplica da se' per il fattore dello schermo, `Screen:scaleBySize`
-- (`frontend/ui/font.lua`: `size = Screen:scaleBySize(size)`). Noi gli
-- passavamo una frazione dell'altezza della riga, cioe' gia' dei pixel, e
-- quindi la misura veniva scalata DUE volte.
--
-- Quanto pesa dipende dallo schermo, ed e' per questo che sul Kindle e nel
-- container non si vedeva: li' il fattore e' vicino a 1. Sul Mac di Paolo
-- (finestra 1440x1694) vale **2,4**: un titolo pensato alto 53 px ne veniva
-- 127, e ogni riga si mangiava quella sotto.
--
-- `scaleBySize(1)` non basta per ricavare il fattore: torna un intero
-- arrotondato (2 invece di 2,4). Si chiede mille e si divide per mille.
local function corpo(pixel)
    local fattore = Screen:scaleBySize(1000) / 1000
    return math.max(8, math.floor(pixel / fattore))
end
Pezzi.corpo = corpo

local function grigio(valore) return Blitbuffer.ColorRGB32(valore, valore, valore, 0xFF) end
local NERO = Blitbuffer.COLOR_BLACK
local MEDIO = grigio(0x88)
local TENUE = grigio(0xCC)

-- ── la riga di stato, a parole ───────────────────────────────────────────

--- «pagina 170 di 500 · 34%», «finito · 150 pagine», «non iniziato»...
--
-- A parole e non con la sola barra, per decisione di Paolo del 14/11: la
-- barra non distingue un libro **non iniziato** da uno di cui **non si sanno
-- le pagine**, e sono due cose diverse. Il primo e' pronto da leggere, il
-- secondo e' un libro di cui il server non ha ancora fatto la stima.
function Pezzi.rigaDiStato(info, stima)
    local letto = info and info.percent_finished
    local pagine_koreader = info and info.pages
    local finito = info and info.status == "complete"

    if finito then
        if stima then return t("koreader.ui.stato_finito_con_pagine", { pagine = stima }) end
        return t("koreader.ui.stato_finito")
    end
    if not letto or letto <= 0 then
        if stima then return t("koreader.ui.stato_non_iniziato_con_pagine", { pagine = stima }) end
        -- Senza stima si dice «pagine non ancora note» e NON «non iniziato»,
        -- anche se e' vero pure quello: fra i due, quello che la riga da
        -- sola non riesce a far capire e' il secondo. Un libro senza barra e
        -- con scritto «non iniziato» sembra un libro di cui si sa tutto; e'
        -- invece un libro che il server non ha ancora misurato. E' la
        -- distinzione per cui questa riga di testo esiste (Paolo, 14/11), ed
        -- e' quello che mostra la prova d'aspetto `09-B-dopo`.
        return t("koreader.ui.pagine_ignote")
    end
    -- Il «pagina N di M» usa il conteggio di KOReader, che e' l'unico vero su
    -- QUESTO dispositivo: e' la pagina che vedi davvero. La stima del server
    -- non entra qui, entra nella lunghezza della barra.
    if pagine_koreader and pagine_koreader > 0 then
        return t("koreader.ui.stato_in_lettura", {
            pagina = math.max(1, math.floor(letto * pagine_koreader + 0.5)),
            pagine = pagine_koreader,
            percento = math.floor(letto * 100 + 0.5),
        })
    end
    return t("koreader.ui.stato_in_lettura_senza_pagine", { percento = math.floor(letto * 100 + 0.5) })
end

-- ── la barra delle pagine ────────────────────────────────────────────────

--- La barra proporzionale, o `nil` se non si puo' disegnare onestamente.
--
-- **Lunghezza dalla stima del SERVER, riempimento dalla percentuale di
-- KOReader.** La lunghezza dice quanto e' lungo il libro e deve essere
-- confrontabile fra un libro e l'altro, quindi non puo' dipendere dal
-- carattere con cui lo leggi tu; il riempimento dice a che punto sei, e
-- quello invece e' tuo. Se la lunghezza venisse dal conteggio di KOReader la
-- barra cambierebbe lunghezza dopo che apri il libro.
--
-- **Senza stima, nessuna barra.** Mai una barra finta: e' una decisione di
-- Paolo dell'11/11, ed e' il motivo per cui la riga di stato dice a parole
-- «pagine non ancora note».
function Pezzi.barraDellePagine(stima, letto, larghezza_max, altezza)
    if not stima or stima <= 0 then return nil end
    local quota = math.min(stima, Pezzi.SOGLIA_PAGINE) / Pezzi.SOGLIA_PAGINE
    local fuori_scala = stima > Pezzi.SOGLIA_PAGINE
    local segno = fuori_scala and Pezzi.QUOTA_ICONA * altezza or 0
    local larghezza = math.floor((larghezza_max - segno) * quota)
    local minima = math.floor((larghezza_max - segno) * Pezzi.QUOTA_BARRA_MINIMA)
    if larghezza < minima then larghezza = minima end
    -- E comunque mai piu' corta che spessa: sotto quella misura i due angoli
    -- arrotondati si toccano e non c'e' piu' una barra da riempire.
    if larghezza < altezza then larghezza = altezza end

    local dentro = larghezza - 2 * Size.border.thin
    local riempita = math.floor(dentro * math.max(0, math.min(1, letto or 0)))
    local gruppo = HorizontalGroup:new{}
    table.insert(gruppo, FrameContainer:new{
        bordersize = Size.border.thin,
        padding = 0,
        margin = 0,
        radius = math.floor(altezza / 2),
        color = NERO,
        background = Blitbuffer.COLOR_WHITE,
        -- Il pieno sta DENTRO il contorno, allineato a sinistra.
        --
        -- E' un `LineWidget`, cioe' un rettangolo pieno con una sua altezza,
        -- e non un `FrameContainer` con dentro un `HorizontalSpan`: uno
        -- span ha una larghezza e NON un'altezza, quindi il riquadro che lo
        -- conteneva si schiacciava a zero e il riempimento non si disegnava
        -- mai — nemmeno a libro finito. Scoperto il 15/11 disegnando la
        -- barra al 25, 50, 75 e 100 per cento sul KOReader vero: la lunghezza
        -- era giusta, la riga di stato diceva «100%», e la barra era vuota.
        -- A ragionarci sembrava giusto; guardandolo no.
        LeftContainer:new{
            dimen = Geom:new{ w = dentro, h = altezza - 2 * Size.border.thin },
            LineWidget:new{
                background = riempita > 0 and grigio(0x44) or Blitbuffer.COLOR_WHITE,
                dimen = Geom:new{
                    w = math.max(0, riempita),
                    h = altezza - 2 * Size.border.thin,
                },
            },
        },
    })
    if fuori_scala then
        -- Il segno di «potrebbe essere ancora piu' lungo»: la barra e' piena
        -- ma il libro sfora la scala, e senza questo segno un libro da 1200
        -- pagine e uno da 800 sembrerebbero uguali.
        table.insert(gruppo, HorizontalSpan:new{ width = math.floor(Size.span.horizontal_small) })
        table.insert(gruppo, TextWidget:new{
            text = "»",
            face = Font:getFace("cfont", corpo(math.floor(altezza * 1.1))),
            fgcolor = NERO,
        })
    end
    return gruppo
end

-- ── la copertina ─────────────────────────────────────────────────────────

--- Un'immagine vera se c'e', altrimenti un riquadro col titolo dentro.
--
-- Il riquadro col titolo e' quello che si vede nelle prove d'aspetto, e per
-- la prima demo e' anche tutto quello che c'e': tirare fuori la copertina
-- vera da dentro un EPUB costa secondi per libro su un Kindle, e si fa in un
-- processo a parte (l'idea presa da Project Title, non il suo codice). Fino
-- ad allora il riquadro col titolo dice comunque di che libro si tratta.
function Pezzi.copertina(percorso_immagine, titolo, larghezza, altezza)
    if percorso_immagine and util.fileExists(percorso_immagine) then
        local ok, immagine = pcall(function()
            return ImageWidget:new{
                file = percorso_immagine,
                width = larghezza, height = altezza,
                scale_factor = nil,   -- riempie il riquadro, come le foto d'autore nel catalogo
            }
        end)
        if ok and immagine then
            return FrameContainer:new{
                bordersize = Size.border.thin, padding = 0, margin = 0, color = MEDIO,
                immagine,
            }
        end
    end
    local larghezza_testo = math.floor(larghezza * 7 / 8)
    return FrameContainer:new{
        bordersize = Size.border.thin, padding = 0, margin = 0, color = MEDIO,
        background = grigio(0xEE),
        CenterContainer:new{
            dimen = Geom:new{ w = larghezza, h = altezza },
            TextBoxWidget:new{
                text = titolo or "",
                face = Font:getFace("cfont", corpo(math.max(12, math.floor(altezza / 10)))),
                width = larghezza_testo,
                alignment = "center",
                height = altezza,
                height_adjust = true,
                height_overflow_show_ellipsis = true,
            },
        },
    }
end

-- ── la riga di stato del dispositivo, in fondo ───────────────────────────

--- La batteria, in basso a sinistra. `nil` se non c'e' niente da dire.
--
-- **Senza timer, e non e' una rinuncia.** `getCapacity()` di KOReader ha
-- gia' una cache di sessanta secondi dentro di se': tocca l'hardware una
-- volta al minuto e basta, per quante volte gliela si chieda. Quindi
-- leggerla a ogni ridisegno non costa niente, e un timer servirebbe solo a
-- svegliare uno schermo e-ink per cambiare due cifre.
--
-- **Niente orologio**, per la ragione opposta: noi ridisegniamo solo quando
-- succede qualcosa, e un'ora ferma sulle 18:40 mentre sono le 19:10 e'
-- peggio che non averla. La batteria cambia piano, l'ora no.
--
-- Tutto dentro `pcall`: su un dispositivo senza batteria, o con un
-- `powerd` che non risponde, questa riga sparisce e la vista resta.
function Pezzi.rigaBatteria(larghezza, altezza)
    if altezza < 8 then return nil end
    local ok, testo = pcall(function()
        if not Device:hasBattery() then return nil end
        local powerd = Device:getPowerDevice()
        if not powerd then return nil end
        local carica = powerd:getCapacity()
        if type(carica) ~= "number" then return nil end
        local simbolo = powerd:getBatterySymbol(powerd:isCharged(), powerd:isCharging(), carica)
        return (simbolo or "") .. " " .. tostring(carica) .. "%"
    end)
    if not ok or not testo then return nil end
    return LeftContainer:new{
        dimen = Geom:new{ w = larghezza, h = altezza },
        HorizontalGroup:new{
            HorizontalSpan:new{ width = Size.padding.default },
            TextWidget:new{
                text = testo,
                face = Font:getFace("cfont", corpo(altezza * 0.74)),
                fgcolor = MEDIO,
            },
        },
    }
end

-- ── una riga dell'elenco ─────────────────────────────────────────────────

--- Una riga: la copertina a sinistra, il resto a destra.
--
-- Serve per tutte e due le cose che l'elenco mostra — una cartella d'autore
-- e un libro — perche' sono la stessa riga con dentro cose diverse: la
-- cartella ha la foto dell'autore e il conto dei libri, il libro ha il
-- riquadro col titolo, la riga di stato e la barra. Due widget separati
-- avrebbero duplicato tutta la misura dello spazio per una differenza che
-- sta in tre righe.
local Riga = InputContainer:extend{
    voce = nil,          -- la voce dell'elenco (vedi kolibre_ui_libreria)
    menu = nil,          -- la vista: riceve i tocchi
    dentro_autore = false,
}

function Riga:init()
    self.dimen = self.dimen:copy()
    self.ges_events = {
        Tap = { GestureRange:new{ ges = "tap", range = self.dimen } },
        Hold = { GestureRange:new{ ges = "hold", range = self.dimen } },
    }

    local voce = self.voce
    local bordo = Size.padding.default

    -- La riga «indietro» e' solo una scritta: non ha una copertina da
    -- mostrare ne' un conto di libri, e disegnarla come le altre le faceva
    -- dire «0 libri», che e' falso e sembra un guasto.
    if voce.solo_titolo then
        -- La riga di separazione va SOPRA e non sotto: questa striscia sta
        -- in fondo, e una riga sotto di lei sarebbe una riga appoggiata al
        -- bordo dello schermo, che non separa niente da niente.
        --
        -- Il corpo del testo non e' una frazione dell'altezza come nelle
        -- righe dei libri: la striscia e' sottile per scelta, e una frazione
        -- darebbe otto punti, cioe' illeggibile. Si prende quasi tutta
        -- l'altezza disponibile, con un minimo.
        local misura = math.max(14, math.floor(self.dimen.h * 0.46))
        self[1] = FrameContainer:new{
            bordersize = 0, padding = 0, margin = 0,
            width = self.dimen.w, height = self.dimen.h,
            VerticalGroup:new{
                align = "left",
                LineWidget:new{
                    background = TENUE,
                    dimen = Geom:new{ w = self.dimen.w, h = Size.line.thin },
                },
                LeftContainer:new{
                    dimen = Geom:new{ w = self.dimen.w, h = self.dimen.h - Size.line.thin },
                    HorizontalGroup:new{
                        HorizontalSpan:new{ width = bordo },
                        TextWidget:new{
                            text = "←  " .. (voce.titolo or ""),
                            face = Font:getFace("cfont", corpo(misura)),
                            fgcolor = MEDIO,
                        },
                    },
                },
            },
        }
        return
    end
    local alt_copertina = math.floor((self.dimen.h - Size.line.thin) * Pezzi.QUOTA_COPERTINA)
    local larg_copertina = math.floor(alt_copertina * Pezzi.PROPORZIONE_COPERTINA)
    local larg_testo = self.dimen.w - larg_copertina - 3 * bordo

    local colonna = VerticalGroup:new{ align = "left" }
    table.insert(colonna, TextWidget:new{
        text = voce.titolo or "",
        face = Font:getFace("cfont", corpo(self.dimen.h * Pezzi.QUOTA_TITOLO)),
        bold = true,
        max_width = larg_testo,
        fgcolor = NERO,
    })

    -- L'autore sotto il titolo sparisce DENTRO la cartella di un autore:
    -- la', lo dice gia' la cartella, e ripeterlo su ogni riga e' rumore
    -- (decisione di Paolo del 14/11).
    if voce.autore and not self.dentro_autore then
        table.insert(colonna, VerticalSpan:new{ width = math.floor(self.dimen.h * Pezzi.QUOTA_ARIA) })
        table.insert(colonna, TextWidget:new{
            text = voce.autore,
            face = Font:getFace("cfont", corpo(self.dimen.h * Pezzi.QUOTA_SOTTOTITOLO)),
            max_width = larg_testo,
            fgcolor = MEDIO,
        })
    end

    if voce.e_cartella then
        table.insert(colonna, VerticalSpan:new{ width = math.floor(self.dimen.h * Pezzi.QUOTA_ARIA) })
        table.insert(colonna, TextWidget:new{
            text = t("koreader.ui.libri_nella_cartella", { count = voce.quanti or 0 }),
            face = Font:getFace("cfont", corpo(self.dimen.h * Pezzi.QUOTA_SOTTOTITOLO)),
            max_width = larg_testo,
            fgcolor = MEDIO,
        })
    else
        table.insert(colonna, VerticalSpan:new{ width = math.floor(self.dimen.h * Pezzi.QUOTA_ARIA) })
        table.insert(colonna, TextWidget:new{
            text = Pezzi.rigaDiStato(voce.info, voce.stima_pagine),
            face = Font:getFace("cfont", corpo(self.dimen.h * Pezzi.QUOTA_SOTTOTITOLO)),
            max_width = larg_testo,
            fgcolor = MEDIO,
        })
        local letto = voce.info and voce.info.percent_finished or 0
        if voce.info and voce.info.status == "complete" then letto = 1 end
        local barra = Pezzi.barraDellePagine(
            voce.stima_pagine, letto,
            math.floor(larg_testo * 0.72), math.floor(self.dimen.h * Pezzi.QUOTA_BARRA_PAGINE))
        if barra then
            table.insert(colonna, VerticalSpan:new{ width = math.floor(self.dimen.h * Pezzi.QUOTA_ARIA) })
            table.insert(colonna, barra)
        end
    end

    -- **La riga di separazione sta DENTRO l'altezza della riga.**
    -- Era aggiunta sotto un gruppo che riempiva gia' tutta l'altezza, e
    -- quindi ogni riga veniva disegnata un pixel piu' alta del suo posto:
    -- con sei righe, sei pixel che si mangiavano il fondo dell'elenco.
    -- Trovato il 15/11 misurando il disegno invece di guardarlo.
    local utile = self.dimen.h - Size.line.thin
    -- Quanto e' alto DAVVERO il testo costruito. La misura la prende la
    -- prova `la_vista_fa_quello_che_deve`: l'altezza del gruppo esterno non
    -- direbbe niente, perche' i contenitori hanno un'altezza fissa e un
    -- contenuto piu' alto gli esce fuori al momento di disegnare senza che
    -- la misura cambi. Era il modo in cui il difetto dei font si nascondeva.
    self.alt_contenuto = colonna:getSize().h

    local riga = HorizontalGroup:new{ align = "center" }
    table.insert(riga, HorizontalSpan:new{ width = bordo })
    table.insert(riga, CenterContainer:new{
        dimen = Geom:new{ w = larg_copertina, h = utile },
        Pezzi.copertina(voce.immagine, voce.titolo, larg_copertina, alt_copertina),
    })
    table.insert(riga, HorizontalSpan:new{ width = bordo })
    table.insert(riga, LeftContainer:new{
        dimen = Geom:new{ w = larg_testo, h = utile },
        colonna,
    })

    self[1] = FrameContainer:new{
        bordersize = 0,
        padding = 0,
        margin = 0,
        width = self.dimen.w,
        height = self.dimen.h,
        -- La riga di separazione sta SOTTO ogni riga e non intorno: una
        -- cornice per riga raddoppierebbe le linee fra una riga e l'altra.
        VerticalGroup:new{
            align = "left",
            riga,
            LineWidget:new{
                background = TENUE,
                dimen = Geom:new{ w = self.dimen.w, h = Size.line.thin },
            },
        },
    }
end

function Riga:onTap()
    if self.menu and self.menu.onRigaToccata then self.menu:onRigaToccata(self.voce) end
    return true
end

function Riga:onHold()
    if self.menu and self.menu.onRigaTenuta then self.menu:onRigaTenuta(self.voce) end
    return true
end

Pezzi.Riga = Riga

-- ── la barra in alto ─────────────────────────────────────────────────────

--- I cinque tasti: casa, cronologia, Kolibre, ultimo libro, menu.
--
-- Entra in `Menu` come `custom_title_bar`, che e' un campo dichiarato di
-- `Menu` (verificato su KOReader v2026.03, frontend/ui/widget/menu.lua:589 e
-- 713): niente patch, niente funzione sostituita. In cambio deve rispondere
-- alle quattro cose che Menu chiede a una barra del titolo — l'altezza, il
-- layout per la navigazione da tastiera, e i due «cambia titolo» — e tre di
-- quelle qui non vogliono dire niente, quindi non fanno niente.
--
-- **Il logo e' il solo tasto che dice uno stato**, e dice una cosa sola:
-- se il dispositivo si e' mai agganciato a Kolibre. Prima, la sagoma; dopo,
-- il logo vero. Nessun controllo della rete per disegnarlo: un controllo
-- verso un server spento blocca il lettore per tre secondi, quindi si mostra
-- sempre l'ultimo stato conosciuto (decisione dell'11/11).
local BarraAlta = InputContainer:extend{
    larghezza = nil,
    altezza = nil,
    agganciato = false,
    cartella_logo = nil,
    azioni = nil,        -- {casa=, cronologia=, kolibre=, ultimo=, menu=}
}

function BarraAlta:init()
    self.dimen = Geom:new{ x = 0, y = 0, w = self.larghezza, h = self.altezza }
    local passo = math.floor(self.larghezza / 5)
    local lato = math.floor(self.altezza * Pezzi.QUOTA_ICONA)
    local alt_logo = math.floor(self.altezza * Pezzi.QUOTA_LOGO)

    local tasti = {
        { icona = "home", azione = "casa" },
        -- Nel set di KOReader un orologio non c'e': la sua cronologia vive
        -- dentro un menu e non ha mai avuto bisogno di un simbolo. Provato
        -- con `dogear.reading`, l'orecchia di pagina, che alla misura del
        -- tasto legge come un triangolo e basta. Quindi e' l'unica delle
        -- cinque disegnata da noi (vedi logo/crea_risorse_koreader.py), ed
        -- e' il quadrante che si vede nelle prove d'aspetto.
        { file = "/icona-cronologia.png", azione = "cronologia" },
        { logo = true, azione = "kolibre" },
        { icona = "book.opened", azione = "ultimo" },
        { icona = "appbar.menu", azione = "menu" },
    }

    local gruppo = HorizontalGroup:new{ align = "center" }
    self.ges_events = { Tap = { GestureRange:new{ ges = "tap", range = self.dimen } } }
    self.centri = {}
    for i, tasto in ipairs(tasti) do
        local dentro
        if tasto.file then
            local f = self.cartella_logo .. tasto.file
            if util.fileExists(f) then
                -- `alpha = true`: la seconda rete. I PNG delle risorse si
                -- scrivono gia' su fondo bianco opaco (vedi
                -- `logo/crea_risorse_koreader.py`), e cosi' non serve a
                -- niente; ma se un giorno qualcuno li rigenera trasparenti,
                -- senza questa riga tornerebbero rettangoli neri. KOReader
                -- appiattisce la trasparenza su bianco solo per le SUE
                -- icone (`imagewidget.lua`: `if self.is_icon and not
                -- self.alpha`), non per un'immagine qualunque come questa.
                dentro = ImageWidget:new{
                    file = f, width = lato, height = lato,
                    scale_factor = 0, alpha = true,
                }
            else
                dentro = IconWidget:new{ icon = "appbar.navigation", width = lato, height = lato }
            end
        elseif tasto.logo then
            -- I due PNG sono gia' RITAGLIATI sul disegno (vedi
            -- logo/crea_risorse_koreader.py): quindi `height` e' l'altezza vera e
            -- non quella di una tela con dentro un margine bianco. E' la
            -- correzione del 15/11, ed e' la differenza fra un marchio alto
            -- una volta e mezzo le icone e uno alto quanto loro.
            local file = self.cartella_logo .. (self.agganciato and "/logo-vero.png" or "/logo-sagoma.png")
            if util.fileExists(file) then
                -- **Larghezza E altezza, tutte e due.** Con `scale_factor = 0`
                -- ImageWidget scala al meglio DENTRO il riquadro dato: senza
                -- la larghezza non ha un riquadro, e disegna l'immagine alla
                -- sua misura nativa — un logo di trecento pixel che sfonda
                -- la barra e copre le prime due righe dell'elenco. Visto
                -- sulla prima cattura dal KOReader vero.
                dentro = ImageWidget:new{
                    file = file,
                    width = passo - 2 * Size.padding.default,
                    height = alt_logo,
                    scale_factor = 0,
                    -- Vedi il commento sull'orologio qui sopra.
                    alpha = true,
                }
            else
                dentro = TextWidget:new{ text = "K", face = Font:getFace("cfont", corpo(alt_logo)), bold = true }
            end
        else
            dentro = IconWidget:new{ icon = tasto.icona, width = lato, height = lato }
        end
        table.insert(gruppo, CenterContainer:new{
            dimen = Geom:new{ w = passo, h = self.altezza },
            dentro,
        })
        self.centri[i] = tasto.azione
    end

    self[1] = FrameContainer:new{
        bordersize = 0, padding = 0, margin = 0,
        background = Blitbuffer.COLOR_WHITE,
        width = self.larghezza,
        VerticalGroup:new{
            align = "left",
            CenterContainer:new{
                dimen = Geom:new{ w = self.larghezza, h = self.altezza - Size.line.medium },
                gruppo,
            },
            LineWidget:new{
                background = MEDIO,
                dimen = Geom:new{ w = self.larghezza, h = Size.line.medium },
            },
        },
    }
end

function BarraAlta:onTap(_, ges)
    -- Quale dei cinque: dalla posizione, non da cinque riquadri toccabili.
    -- Cinque InputContainer annidati vorrebbero dire cinque registrazioni di
    -- gesti per ogni ridisegno della barra, e la barra si ridisegna a ogni
    -- cambio di pagina.
    local x = ges and ges.pos and ges.pos.x
    if not x then return false end
    local i = math.min(5, math.max(1, math.floor(x / (self.larghezza / 5)) + 1))
    local azione = self.azioni and self.azioni[self.centri[i]]
    if azione then azione() end
    return true
end

--- L'altezza: Menu la chiede per sapere quanto spazio resta all'elenco.
function BarraAlta:getHeight() return self.altezza end

--- Le tre che Menu chiama e che qui non vogliono dire niente. Esistono
--- perche' Menu le chiama senza chiedere permesso, e un `nil` le farebbe
--- morire: non sono segnaposti dimenticati.
function BarraAlta:generateVerticalLayout() return {} end
function BarraAlta:setTitle() end
function BarraAlta:setSubTitle() end
function BarraAlta:setLeftIcon() end
function BarraAlta:resetLayout() end

--- Il logo cambia stato senza ricostruire la barra.
function BarraAlta:aggiorna(agganciato)
    if self.agganciato == agganciato then return false end
    self.agganciato = agganciato
    self:init()
    return true
end

Pezzi.BarraAlta = BarraAlta

return Pezzi
