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
local RightContainer = require("ui/widget/container/rightcontainer")
local LineWidget = require("ui/widget/linewidget")
local Device = require("device")
local Screen = Device.screen
local Size = require("ui/size")
local TextBoxWidget = require("ui/widget/textboxwidget")
local TextWidget = require("ui/widget/textwidget")
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
-- **La striscia «indietro» non c'e' piu'** (Paolo, 16/11/2026: «il tasto
-- back e' ancora sopra la barra di navigazione, mentre io vorrei un bottone
-- a fianco dei tasti di navigazione nella barra bassa allineato a
-- sinistra»). Era una striscia sottile sopra la navigazione, e si prendeva
-- il 6,5% dello spazio dell'elenco **prima** che le righe si dividessero
-- quello che restava. Adesso «indietro» e' la freccia che KOReader tiene
-- gia' in fondo a sinistra, nella stessa riga delle frecce delle pagine
-- (vedi `Comune.tastoIndietro`): un comando in piu' che non costa un pixel,
-- e in fondo allo schermo c'e' una striscia sola invece di due.
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

--: Il corpo della data a destra della riga. Piu' piccolo del sottotitolo: e'
--  un'informazione di servizio, e deve potersi ignorare guardando l'elenco.
Pezzi.QUOTA_QUANDO = 0.11

--: Quanto al massimo si prende la colonna della data, in frazione di riga.
--  Oltre, una data lunga («2026-07-12») mangerebbe il titolo invece di
--  starle accanto.
Pezzi.QUOTA_COLONNA_QUANDO = 0.26

--: Sotto questa frazione di riga la colonna del testo non si stringe piu': la
--  data se ne va del tutto. E' la stessa regola verticale applicata di
--  traverso — sotto una certa misura si TOGLIE qualcosa invece di
--  rimpicciolire tutto, perche' un titolo tagliato a meta' non si riconosce.
Pezzi.TESTO_MINIMO = 0.45


--: la lunghezza MINIMA della barra, in frazione della sua lunghezza piena.
--
--  Scelta di Paolo del 15/11/2026. Prima il minimo era «alta quanto e'
--  spessa», cioe' un cerchietto: un libro di sei pagine su una scala che
--  arriva a ottocento diventava un pallino, e un pallino non si legge come
--  «un libro cortissimo», si legge come un guasto. A 0,12 un libro di sei
--  pagine e uno di cento restano diversi fra loro — il secondo e' piu' del
--  doppio — e tutti e due si vedono come barre.
Pezzi.QUOTA_BARRA_MINIMA = 0.12

--: Sotto quale altezza di riga una riga e' «stretta», e si cambia strategia.
--
--  **La regola, nelle parole di Paolo (15/11/2026):** da quattro a otto
--  righe per schermata, e «sotto circa 120 px di riga si toglie qualcosa,
--  non si rimpiccioliscono i caratteri».
--
--  **Perche' e' quella giusta.** I corpi dei caratteri sono frazioni
--  dell'altezza della riga (`QUOTA_TITOLO` e compagnia), quindi da soli
--  seguirebbero la riga fin giu' a niente: a otto righe su un Kindle
--  coricato una riga e' 122 px, e il titolo diventerebbe nove punti. Nove
--  punti su un e-ink da leggere a mezzo metro non sono piccoli: sono
--  illeggibili, e una riga illeggibile non vale lo spazio che occupa.
--  Meglio tre informazioni leggibili che cinque indovinate.
--
--  **E non e' un conto: e' una misura.** Sotto i 120 px i corpi si fermano
--  ai 120 px, e poi la riga si costruisce, SI MISURA, e se non ci sta si
--  toglie il pezzo meno importante e si rimisura. Il conto a mano (titolo
--  x 1,55 + aria + ...) e' una stima: l'altezza vera di un testo disegnato
--  dipende dal font, dagli accenti e dagli arrotondamenti, ed e' sempre un
--  po' diversa da quello che si era previsto. Misurare costa un
--  `getSize()` per riga e non sbaglia mai.
Pezzi.RIGA_STRETTA = 120

--: Quante righe per schermata si possono chiedere. Quattro perche' sotto si
--  vede meno di una pagina di elenco e tanto valeva una copertina grande;
--  otto perche' sopra, anche togliendo pezzi, il titolo non ci sta.
Pezzi.RIGHE_MINIME = 4
Pezzi.RIGHE_MASSIME = 8
Pezzi.RIGHE_PER_DIFETTO = 6

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

-- ── quando, a parole ────────────────────────────────────────────────────
--
--[[--
L'istante di un libro — l'ultima apertura, la consegna — detto come lo dice
una persona.

**Perche' il tempo PASSATO e non l'ora** (Paolo, 16/11/2026: per la
cronologia «3 hours ago», per gli invii «Delivered at 8:12»). Le due viste
si somigliano come due gocce d'acqua — stessi tasti, stesse righe, stessa
barra — e due scale di tempo diverse costringerebbero a ricordarsi in quale
delle due si e', per leggere un numero. Quindi: **una regola sola**, e il
tempo passato, perche' risponde alla domanda che si fa davanti a questi due
elenchi, che e' «quanto e' recente?» e non «a che ora e' successo?».

**Il prezzo, dichiarato.** «3 ore fa» si calcola al momento del disegno, e la
vista si ridisegna solo quando succede qualcosa: con la finestra aperta mezz'
ora, dira' ancora «3 ore fa» quando sono tre e mezza. E' lo stesso difetto
per cui l'orologio nella barra e' stato rifiutato, ma qui e' innocuo **perche'
la scala e' grossa**: un'ora sbagliata su «3 ore fa» non cambia niente a chi
legge, mentre un orologio fermo sulle 18:40 alle 19:10 e' preciso e falso.
Questa e' anche la ragione per cui non si scrive l'ora esatta: sarebbe
giusta per sempre, e invece inviterebbe a crederci.

**E perche' nessun «Consegnato» davanti.** Nel pannello degli invii la data
e' per forza quella della consegna: lo dice il nome della finestra, scritto
in cima dal 16/11. Ripeterlo su cinquanta righe sarebbe rumore, e in una
colonna stretta sarebbe rumore che mangia la data.

**Un istante che non c'e' non si inventa**: la funzione torna `nil` e la riga
non scrive niente. I libri consegnati prima del novembre 2026 non hanno la
data, e «non lo so» non e' «oggi».

`corto` chiede la forma breve: la usa `Riga` quando quella lunga non entra
nella colonna, misurandola e non indovinandola.
]]
--
-- `adesso` si puo' passare, e serve alla prova: senza, «ieri» non si
-- potrebbe verificare prima di mezzogiorno — il risultato dipende dall'ora
-- in cui le prove girano, e una prova che passa solo di pomeriggio e' una
-- prova che un giorno si rompe da sola.
function Pezzi.quando(istante, corto, adesso)
    if type(istante) ~= "number" or istante <= 0 then return nil end
    adesso = adesso or os.time()
    local passati = adesso - istante
    -- Un istante nel futuro e' un orologio sbagliato da qualche parte (il
    -- server, o il lettore). Si dice «adesso» invece di «-3 ore fa»: una
    -- data che non si capisce e' peggio di una data imprecisa.
    if passati < 60 then return t("koreader.ui.quando_adesso") end
    if passati < 3600 then
        local minuti = math.floor(passati / 60)
        return t("koreader.ui.quando_minuti", { count = minuti })
    end
    if passati < 86400 then
        local ore = math.floor(passati / 3600)
        return t("koreader.ui.quando_ore", { count = ore })
    end

    -- Oltre le ventiquattro ore si contano i GIORNI DI CALENDARIO, non i
    -- multipli di 86400: alle sette del mattino, un libro aperto alle
    -- ventidue di due sere prima e' «l'altro ieri» per chiunque, e sarebbe
    -- «un giorno fa» contando i secondi.
    local function mezzogiorno(quando)
        local d = os.date("*t", quando)
        return os.time({ year = d.year, month = d.month, day = d.day, hour = 12 })
    end
    local giorni = math.floor((mezzogiorno(adesso) - mezzogiorno(istante)) / 86400 + 0.5)
    if giorni <= 1 then return t("koreader.ui.quando_ieri") end
    if giorni == 2 and not corto then return t("koreader.ui.quando_altroieri") end
    if giorni <= 6 then return t("koreader.ui.quando_giorni", { count = giorni }) end
    -- Oltre la settimana, la data e basta: «23 giorni fa» non dice niente a
    -- nessuno, e una data si confronta con quello che uno si ricorda.
    return os.date("%Y-%m-%d", istante)
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

--- Quanto e' grande un'immagine, letto dall'intestazione del file.
--
-- **Perche' non si chiede a KOReader.** Non c'e' niente che lo dica senza
-- decodificare: `RenderImage` sa solo aprire l'immagine per intero, e un
-- ritratto da Wikipedia su un Kindle sono decine di migliaia di pixel
-- decodificati per sapere due numeri che stanno nei primi venti byte del
-- file. Qui si leggono quei byte e basta: nessuna decodifica, nessuna
-- memoria, e funziona anche su un file rotto (torna `nil` e chi chiama ha
-- un ripiego).
--
-- **A che serve.** A calcolare il fattore che COPRE il riquadro invece di
-- starci dentro — vedi `Pezzi.copertina`.
--
-- Riconosce PNG e JPEG, che sono i due formati che ci arrivano: i nostri
-- PNG di bordo (`risorse/`) e i JPEG che il server manda come miniature
-- (`authors.py` e `books.py` salvano in JPEG, qualunque cosa fosse
-- l'originale). Qualunque altra cosa torna `nil`, cioe' «non lo so», che e'
-- la risposta onesta.
local function leggiGrande(stringa, posizione, quanti)
    local valore = 0
    for i = 0, quanti - 1 do
        local b = stringa:byte(posizione + i)
        if not b then return nil end
        valore = valore * 256 + b
    end
    return valore
end

function Pezzi.misuraImmagine(percorso)
    if type(percorso) ~= "string" or percorso == "" then return nil end
    local ok, larghezza, altezza = pcall(function()
        local f = io.open(percorso, "rb")
        if not f then return nil, nil end
        local testa = f:read(32)
        if not testa or #testa < 24 then f:close(); return nil, nil end

        -- PNG: firma di 8 byte, poi la lunghezza del primo blocco, poi
        -- "IHDR", e dentro IHDR larghezza e altezza come interi di 4 byte
        -- col byte piu' importante davanti. Posizioni fisse: e' il formato
        -- che le fissa, non noi.
        if testa:sub(1, 8) == "\137PNG\r\n\26\n" and testa:sub(13, 16) == "IHDR" then
            f:close()
            return leggiGrande(testa, 17, 4), leggiGrande(testa, 21, 4)
        end

        -- JPEG: niente posizioni fisse. Il file e' una catena di marcatori
        -- `FF xx`, ognuno con la propria lunghezza, e la misura sta in
        -- quello che si chiama SOF — «inizio del fotogramma». Si salta di
        -- marcatore in marcatore finche' non si trova, e si smette
        -- all'inizio dei dati compressi (`DA`), oltre il quale non c'e'
        -- piu' niente da leggere.
        if testa:byte(1) == 0xFF and testa:byte(2) == 0xD8 then
            local posizione = 2
            -- Il tetto ai giri non e' per i file buoni, dove il SOF arriva
            -- entro pochi marcatori: e' perche' un file rotto puo' dare una
            -- lunghezza che non avanza, e un ciclo infinito dentro il
            -- disegno di una riga blocca la vista.
            for _giro = 1, 256 do
                f:seek("set", posizione)
                local due = f:read(2)
                if not due or #due < 2 or due:byte(1) ~= 0xFF then break end
                local marcatore = due:byte(2)
                if marcatore == 0xFF then
                    posizione = posizione + 1          -- byte di riempimento
                elseif marcatore == 0x01 or (marcatore >= 0xD0 and marcatore <= 0xD8) then
                    posizione = posizione + 2          -- marcatori senza corpo
                elseif marcatore == 0xD9 or marcatore == 0xDA then
                    break                              -- fine, o inizio dei dati
                else
                    local lung = leggiGrande(f:read(2) or "", 1, 2)
                    if not lung or lung < 2 then break end
                    -- I SOF sono i marcatori da C0 a CF, tolti i tre che
                    -- hanno quei numeri per ragioni storiche e dicono altro:
                    -- C4 le tabelle di Huffman, C8 un'estensione mai usata,
                    -- CC le tabelle aritmetiche.
                    local e_sof = marcatore >= 0xC0 and marcatore <= 0xCF
                        and marcatore ~= 0xC4 and marcatore ~= 0xC8 and marcatore ~= 0xCC
                    if e_sof then
                        -- Dentro un SOF: 1 byte di precisione, poi
                        -- l'ALTEZZA e poi la larghezza. In quest'ordine —
                        -- scambiarli e' l'errore classico su questo formato.
                        local corpo_sof = f:read(5)
                        if not corpo_sof or #corpo_sof < 5 then break end
                        f:close()
                        return leggiGrande(corpo_sof, 4, 2), leggiGrande(corpo_sof, 2, 2)
                    end
                    posizione = posizione + 2 + lung
                end
            end
        end
        f:close()
        return nil, nil
    end)
    if not ok then return nil end
    if type(larghezza) ~= "number" or type(altezza) ~= "number"
        or larghezza <= 0 or altezza <= 0 then
        return nil
    end
    return larghezza, altezza
end

--- Un'immagine vera se c'e', altrimenti un riquadro col titolo dentro.
--
-- Il riquadro col titolo e' quello che si vede nelle prove d'aspetto, e per
-- la prima demo e' anche tutto quello che c'e': tirare fuori la copertina
-- vera da dentro un EPUB costa secondi per libro su un Kindle, e si fa in un
-- processo a parte (l'idea presa da Project Title, non il suo codice). Fino
-- ad allora il riquadro col titolo dice comunque di che libro si tratta.
--
-- **L'immagine si RITAGLIA, non si stira** (Paolo, 15/11/2026: «mantenendo
-- le proporzioni»). In KOReader `scale_factor` ha tre comportamenti, e
-- nessuno dei due ovvi e' quello giusto:
--
--   * `nil` porta l'immagine esattamente a `width` x `height`, cioe' la
--     **stira**. Era quello che c'era, e una foto quadrata — la forma
--     normale di un ritratto — finiva schiacciata in un riquadro piu' alto
--     che largo: il viso si allunga, e si vede.
--   * `0` la rimpicciolisce finche' ci sta tutta: le proporzioni si
--     salvano, ma restano due bande vuote, e in un elenco di righe uguali
--     le bande si notano piu' della foto.
--   * un numero e' il fattore di scala, e quello che serve e' il fattore
--     che **copre** il riquadro: il MASSIMO fra i due rapporti, mentre lo
--     `0` usa il minimo.
--
-- Il ritaglio poi lo fa KOReader da se': `paintTo` blitta solo
-- `width` x `height` a partire da una posizione centrata, e `getSize` torna
-- il riquadro anche quando l'immagine dentro e' piu' grande (letto in
-- `frontend/ui/widget/imagewidget.lua`, v2025.08). Noi gli diamo soltanto
-- il fattore che lui non calcola.
--
-- **Il pixel di scarto** in `+ 1`: KOReader arrotonda per difetto la misura
-- scalata, e un fattore esatto puo' dare 184 px dove il riquadro ne vuole
-- 185. Un pixel in piu' di scala costa un pixel di ritaglio e togliere un
-- riquadro che non si riempie.
--
-- **Se la misura non si legge** (formato che non conosciamo, file rotto) si
-- ripiega su `0`: con le bande, ma mai stirata. Il ripiego peggiore e' il
-- comportamento vecchio, e non lo rimettiamo per sbaglio.
function Pezzi.copertina(percorso_immagine, titolo, larghezza, altezza)
    if percorso_immagine and util.fileExists(percorso_immagine) then
        local nat_larg, nat_alt = Pezzi.misuraImmagine(percorso_immagine)
        local fattore = 0
        if nat_larg and nat_alt then
            fattore = math.max((larghezza + 1) / nat_larg, (altezza + 1) / nat_alt)
        end
        local ok, immagine = pcall(function()
            return ImageWidget:new{
                file = percorso_immagine,
                width = larghezza, height = altezza,
                scale_factor = fattore,
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

--- Il testo della batteria: simbolo e percentuale. `nil` se non si sa.
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
-- `powerd` che non risponde, qui esce `nil` e la vista resta.
function Pezzi.testoBatteria()
    local ok, testo = pcall(function()
        if not Device:hasBattery() then return nil end
        local powerd = Device:getPowerDevice()
        if not powerd then return nil end
        local carica = powerd:getCapacity()
        if type(carica) ~= "number" then return nil end
        local simbolo = powerd:getBatterySymbol(powerd:isCharged(), powerd:isCharging(), carica)
        return (simbolo or "") .. " " .. tostring(carica) .. "%"
    end)
    if not ok then return nil end
    return testo
end

--- La batteria da mettere DENTRO la barra di navigazione, con le frecce.
--
-- **Perche' non e' piu' una striscia sua** (Paolo, 16/11/2026). Prima la
-- carica era una riga tutta sua in basso a sinistra, e si prendeva il 3,5%
-- dello spazio dell'elenco **prima** che le righe si dividessero quello che
-- restava — era obbligatorio, perche' aggiungerla dopo le avrebbe spinte
-- fuori dallo schermo. In fondo allo schermo c'erano quindi due strisce
-- sottili una sopra l'altra, e dicevano entrambe «stato del dispositivo».
--
-- Dentro la barra di navigazione non costa **un pixel**: quella barra c'era
-- gia' e la sua altezza era gia' contata. Il corpo si chiede uguale
-- all'altezza del testo che le sta accanto, cosi' la barra non cresce.
--
-- Torna un gruppo largo quanto il suo contenuto — **non** quanto lo schermo:
-- va infilato in un gruppo orizzontale che si misura da se', e un pezzo che
-- pretende tutta la larghezza spingerebbe le frecce fuori.
function Pezzi.batteriaCompatta(altezza_testo)
    local testo = Pezzi.testoBatteria()
    if not testo then return nil end
    return HorizontalGroup:new{
        HorizontalSpan:new{ width = Size.padding.large },
        TextWidget:new{
            text = testo,
            face = Font:getFace("cfont", corpo(math.max(10, altezza_testo or 24))),
            fgcolor = MEDIO,
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

    local alt_copertina = math.floor((self.dimen.h - Size.line.thin) * Pezzi.QUOTA_COPERTINA)
    local larg_copertina = math.floor(alt_copertina * Pezzi.PROPORZIONE_COPERTINA)
    local larg_testo = self.dimen.w - larg_copertina - 3 * bordo

    -- **La misura su cui si calcolano i corpi dei caratteri**, che NON e'
    -- sempre l'altezza della riga. Sotto i 120 px si ferma li': vedi
    -- `Pezzi.RIGA_STRETTA` per il perche'. Sopra, e' l'altezza vera, e
    -- questa riga non cambia niente di come era prima.
    local base = math.max(self.dimen.h, Pezzi.RIGA_STRETTA)
    local aria = math.floor(base * Pezzi.QUOTA_ARIA)

    -- ── la data, a destra (Paolo, 16/11/2026) ───────────────────────────
    --
    -- Nella cronologia e' l'ultima apertura, negli ultimi invii la consegna;
    -- il senso lo da' il nome della finestra, non una parola su ogni riga
    -- (vedi `Pezzi.quando`).
    --
    -- **Si misura, non si indovina.** La forma lunga che Paolo ha chiesto —
    -- «the day before yesterday» — su uno schermo stretto non ci sta, e un
    -- testo tagliato a meta' («the day before yes…») e' peggio di una forma
    -- breve. Quindi: si costruisce la lunga, si misura, e se sfora il tetto
    -- della colonna o ruberebbe troppo spazio al titolo si rifa' corta. Se
    -- non entra nemmeno quella, la data non si disegna: e' l'unico pezzo
    -- della riga che si puo' togliere senza perdere di che libro si tratta.
    local quando_widget, larg_quando = nil, 0
    if voce.quando then
        local faccia = Font:getFace("cfont", corpo(base * Pezzi.QUOTA_QUANDO))
        local tetto = math.floor(self.dimen.w * Pezzi.QUOTA_COLONNA_QUANDO)
        local minimo = math.floor(self.dimen.w * Pezzi.TESTO_MINIMO)
        for _i, corto in ipairs({ false, true }) do
            local testo = Pezzi.quando(voce.quando, corto)
            if not testo then break end
            local w = TextWidget:new{ text = testo, face = faccia, fgcolor = MEDIO }
            local larga = w:getSize().w
            if larga <= tetto and larg_testo - larga - bordo >= minimo then
                quando_widget, larg_quando = w, larga
                break
            end
            pcall(function() w:free() end)
        end
        if quando_widget then larg_testo = larg_testo - larg_quando - bordo end
    end
    -- Le due misure che la prova `le_righe_stanno_su_ogni_schermo` guarda:
    -- se la data c'e', e quanto spazio e' rimasto al titolo. Senza, il
    -- controllo che la data non mangi il titolo si potrebbe fare solo a
    -- occhio su una fotografia.
    self.ha_quando = quando_widget ~= nil
    self.larg_testo = larg_testo

    -- I pezzi della colonna, in ordine di disegno, ognuno col suo posto
    -- nella fila per essere sacrificato. `sacrificabile` piu' basso vuol
    -- dire «va via per primo».
    --
    -- **L'ordine, e perche' questo.** Via per prima la barra delle pagine:
    -- e' l'unico pezzo che non dice niente di nuovo — quanto hai letto c'e'
    -- gia' scritto in parole nella riga di stato, la barra lo ripete in
    -- figura. Poi la riga di stato stessa, che e' un'informazione in piu' ma
    -- non serve a riconoscere il libro. L'autore e il titolo restano: sono
    -- quello per cui si guarda un elenco.
    local pezzi = {}
    local function aggiungi(widget, sacrificabile)
        if widget then table.insert(pezzi, { widget = widget, sacrificabile = sacrificabile }) end
    end

    aggiungi(TextWidget:new{
        text = voce.titolo or "",
        face = Font:getFace("cfont", corpo(base * Pezzi.QUOTA_TITOLO)),
        bold = true,
        max_width = larg_testo,
        fgcolor = NERO,
    }, nil)   -- il titolo non si tocca

    -- L'autore sotto il titolo sparisce DENTRO la cartella di un autore:
    -- la', lo dice gia' la cartella, e ripeterlo su ogni riga e' rumore
    -- (decisione di Paolo del 14/11).
    if voce.autore and not self.dentro_autore then
        aggiungi(TextWidget:new{
            text = voce.autore,
            face = Font:getFace("cfont", corpo(base * Pezzi.QUOTA_SOTTOTITOLO)),
            max_width = larg_testo,
            fgcolor = MEDIO,
        }, 3)
    end

    if voce.e_cartella then
        aggiungi(TextWidget:new{
            text = t("koreader.ui.libri_nella_cartella", { count = voce.quanti or 0 }),
            face = Font:getFace("cfont", corpo(base * Pezzi.QUOTA_SOTTOTITOLO)),
            max_width = larg_testo,
            fgcolor = MEDIO,
        }, 2)
    else
        -- **`stato_testo` vince sullo stato di lettura.** Nel pannello degli
        -- ultimi invii la riga sotto il titolo dice quando il libro e'
        -- arrivato, che li' e' il motivo per cui l'elenco esiste; altrove e'
        -- lo stato di lettura. Una riga sola, perche' due si mangerebbero il
        -- titolo sulle schermate strette.
        aggiungi(TextWidget:new{
            text = voce.stato_testo or Pezzi.rigaDiStato(voce.info, voce.stima_pagine),
            face = Font:getFace("cfont", corpo(base * Pezzi.QUOTA_SOTTOTITOLO)),
            max_width = larg_testo,
            fgcolor = MEDIO,
        }, 2)
        local letto = voce.info and voce.info.percent_finished or 0
        if voce.info and voce.info.status == "complete" then letto = 1 end
        aggiungi(Pezzi.barraDellePagine(
            voce.stima_pagine, letto,
            math.floor(larg_testo * 0.72), math.floor(base * Pezzi.QUOTA_BARRA_PAGINE)), 1)
    end

    -- **Costruisci, misura, e se non ci sta togli e rimisura.**
    --
    -- Il ciclo e' limitato dal numero di pezzi sacrificabili (tre), quindi
    -- finisce sempre; e finisce anche quando non ci sta nemmeno il solo
    -- titolo, perche' allora non c'e' piu' niente da togliere e si disegna
    -- quello che c'e'. Un titolo che sfora di qualche pixel e' brutto; una
    -- riga vuota e' un guasto.
    local utile_colonna = self.dimen.h - Size.line.thin
    local colonna
    while true do
        colonna = VerticalGroup:new{ align = "left" }
        for i, pezzo in ipairs(pezzi) do
            if i > 1 then table.insert(colonna, VerticalSpan:new{ width = aria }) end
            table.insert(colonna, pezzo.widget)
        end
        if colonna:getSize().h <= utile_colonna then break end
        -- Il pezzo sacrificabile col numero piu' basso, se c'e'.
        local quale, peggiore = nil, nil
        for i, pezzo in ipairs(pezzi) do
            if pezzo.sacrificabile and (peggiore == nil or pezzo.sacrificabile < peggiore) then
                quale, peggiore = i, pezzo.sacrificabile
            end
        end
        if not quale then break end
        table.remove(pezzi, quale)
    end

    -- **La riga di separazione sta DENTRO l'altezza della riga.**
    -- Era aggiunta sotto un gruppo che riempiva gia' tutta l'altezza, e
    -- quindi ogni riga veniva disegnata un pixel piu' alta del suo posto:
    -- con sei righe, sei pixel che si mangiavano il fondo dell'elenco.
    -- Trovato il 15/11 misurando il disegno invece di guardarlo.
    local utile = utile_colonna
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
    if quando_widget then
        table.insert(riga, HorizontalSpan:new{ width = bordo })
        -- Allineata a destra e centrata in altezza: e' un'informazione di
        -- servizio, e deve stare dove l'occhio la trova sempre nello stesso
        -- posto invece di seguire la lunghezza del titolo.
        table.insert(riga, RightContainer:new{
            dimen = Geom:new{ w = larg_quando, h = utile },
            quando_widget,
        })
    end

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
-- **`QUOTA_PERCORSO`: quanto alta e' la riga del percorso**, in quota della
-- barra dei tasti. La barra CRESCE di questo, e lo dice da `getHeight()`:
-- non si ruba spazio ai tasti e non si lascia che l'elenco finisca sotto.
-- Su un Kindle in piedi (1448 px) la barra passa da 114 a 141 px, e a sei
-- righe una riga perde circa 4 px: il prezzo di sapere dove si e'.
Pezzi.QUOTA_PERCORSO = 0.24

local BarraAlta = InputContainer:extend{
    larghezza = nil,
    altezza = nil,       -- l'altezza della RIGA DEI TASTI, non della barra
    agganciato = false,
    cartella_logo = nil,
    percorso = nil,      -- dove sei: la riga sotto, in grigio. nil = niente riga
    titolo = nil,        -- il nome della finestra: la stessa riga, in nero
    azioni = nil,        -- {casa=, cronologia=, kolibre=, ultimo=, menu=}
    azioni_tenute = nil, -- le stesse chiavi, per la pressione prolungata
}

function BarraAlta:init()
    -- **La misura dichiarata e' il TOTALE, riga di sotto compresa.**
    --
    -- Il difetto che queste righe correggono (16/11/2026, visto da Paolo
    -- sulla prima cattura con il percorso acceso: «la copertina del primo
    -- libro esce dal bordo»). `Menu` impagina la barra e l'elenco in un
    -- `VerticalGroup`, che appoggia ogni pezzo sotto il precedente usando la
    -- sua **misura** (`getSize()`); le misure dell'elenco invece si fanno
    -- sull'**altezza dichiarata** (`getHeight()`). Qui le due rispondevano
    -- numeri diversi — 126 px e 156 px, misurati sul KOReader del Mac —
    -- quindi l'elenco cominciava trenta pixel piu' in su della fine della
    -- barra, e la prima riga ci finiva sotto, tagliata.
    --
    -- **Il riquadro dei TASTI resta quello dei tasti**: quello che non si
    -- fa, per correggere, e' dichiarare meno spazio di quello che si occupa.
    -- Il tocco sulla riga di sotto lo scarta `_qualeTasto` guardando dove
    -- cade il dito: se il riquadro dei comandi coprisse anche quella riga,
    -- un tocco sul nome della cartella aprirebbe uno dei cinque comandi, e
    -- quale dipenderebbe da dove cade il dito dentro il nome.
    local scritta = self.titolo or self.percorso
    local alta_scritta = 0
    if type(scritta) == "string" and scritta ~= "" then
        alta_scritta = math.floor(self.altezza * Pezzi.QUOTA_PERCORSO)
    end
    self.alta_totale = self.altezza + alta_scritta
    self.dimen = Geom:new{ x = 0, y = 0, w = self.larghezza, h = self.alta_totale }
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
    -- `Hold` accanto a `Tap`: la pressione prolungata su un tasto e' un
    -- comando in piu' senza un tasto in piu' (sulla casa apre il pannello
    -- degli ultimi invii). Chi non ha niente da fare sotto il dito non
    -- registra niente: `azioni_tenute` puo' non esserci.
    self.ges_events = {
        Tap = { GestureRange:new{ ges = "tap", range = self.dimen } },
        Hold = { GestureRange:new{ ges = "hold", range = self.dimen } },
    }
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

    -- ── La riga sotto i tasti: il percorso, o il nome della finestra ────
    --
    -- **Dove sei, scritto.** Prima la barra era identica in ogni cartella:
    -- entravi in un autore e l'unica differenza era che l'elenco cambiava.
    -- Decisione di Paolo dell'11-14/11/2026, insieme alle righe per
    -- schermata.
    --
    -- **La stessa riga porta due cose diverse, e si vede quale.** Nella
    -- libreria dice dove sei (`percorso`) ed e' scritta in grigio, piccola,
    -- come una didascalia: cambia a ogni cartella. Nella cronologia e nel
    -- pannello degli invii dice **come si chiama la finestra** (`titolo`) ed
    -- e' nera e piu' grande, perche' un titolo che cambia non e': e' il nome
    -- di quello che stai guardando. Due righe separate non servivano — e'
    -- lo stesso posto che risponde alla stessa domanda, «cos'e' questo».
    --
    -- `max_width` e non una misura libera: su un Kindle i nomi degli autori
    -- sono lunghi, e due di fila di piu'. TextWidget taglia con un segno di
    -- troncamento invece di sfondare la barra.
    local riga_scritta = nil
    if alta_scritta > 0 then
        local e_titolo = self.titolo ~= nil and self.titolo ~= ""
        riga_scritta = CenterContainer:new{
            dimen = Geom:new{ w = self.larghezza, h = alta_scritta },
            TextWidget:new{
                text = scritta,
                face = Font:getFace("cfont",
                    corpo(math.floor(alta_scritta * (e_titolo and 0.72 or 0.62)))),
                bold = e_titolo or nil,
                max_width = self.larghezza - 4 * Size.padding.default,
                fgcolor = e_titolo and NERO or MEDIO,
            },
        }
    end

    local dentro = VerticalGroup:new{
        align = "left",
        CenterContainer:new{
            dimen = Geom:new{ w = self.larghezza, h = self.altezza - Size.line.medium },
            gruppo,
        },
    }
    if riga_scritta then table.insert(dentro, riga_scritta) end
    table.insert(dentro, LineWidget:new{
        background = MEDIO,
        dimen = Geom:new{ w = self.larghezza, h = Size.line.medium },
    })

    self[1] = FrameContainer:new{
        bordersize = 0, padding = 0, margin = 0,
        background = Blitbuffer.COLOR_WHITE,
        width = self.larghezza,
        dentro,
    }
end

--- Quale dei cinque tasti sta sotto il dito, o `nil` se non ce n'e' nessuno.
--
-- **Dalla posizione, non da cinque riquadri toccabili.** Cinque
-- `InputContainer` annidati vorrebbero dire cinque registrazioni di gesti
-- per ogni ridisegno della barra, e la barra si ridisegna a ogni cambio di
-- pagina.
--
-- **E il `nil` e' la riga di sotto.** Il riquadro dei gesti copre tutta la
-- barra, perche' la barra deve dichiarare l'altezza che occupa (vedi
-- `init`); ma sotto la fila dei tasti c'e' il percorso o il titolo, che non
-- e' un comando. Un dito li' dentro non apre niente invece di aprire il
-- comando che gli capita sotto.
function BarraAlta:_qualeTasto(ges)
    local pos = ges and ges.pos
    if not pos or not pos.x then return nil end
    local alto = (self.dimen and self.dimen.y or 0)
    if pos.y and pos.y >= alto + self.altezza then return nil end
    local sinistra = (self.dimen and self.dimen.x or 0)
    return math.min(5, math.max(1,
        math.floor((pos.x - sinistra) / (self.larghezza / 5)) + 1))
end

function BarraAlta:onTap(_, ges)
    local i = self:_qualeTasto(ges)
    if not i then return true end
    local azione = self.azioni and self.azioni[self.centri[i]]
    if azione then azione() end
    return true
end

--- La pressione prolungata su un tasto, per chi ne ha registrata una.
--
-- Si consuma comunque il gesto (`return true`): sotto la barra c'e'
-- l'elenco, e lasciar scendere una pressione lunga partita sui comandi
-- aprirebbe la scheda di un libro che il dito non ha nemmeno toccato.
function BarraAlta:onHold(_, ges)
    local i = self:_qualeTasto(ges)
    if not i then return true end
    local azione = self.azioni_tenute and self.azioni_tenute[self.centri[i]]
    if azione then azione() end
    return true
end

--- L'altezza: Menu la chiede per sapere quanto spazio resta all'elenco.
---
--- **Il TOTALE, compresa la riga del percorso.** `self.altezza` e' solo la
--- riga dei tasti: tornare quella vorrebbe dire che le prime righe
--- dell'elenco finiscono sotto il percorso.
function BarraAlta:getHeight() return self.alta_totale or self.altezza end

--- Cambia il percorso scritto, e dice se e' cambiato qualcosa.
---
--- Si chiama a ogni ridisegno dell'elenco: se il testo e' lo stesso non si
--- ricostruisce niente, perche' ricostruire la barra vuol dire ricaricare
--- tre PNG a ogni cambio di pagina.
function BarraAlta:aggiornaPercorso(testo)
    if self.percorso == testo then return false end
    self.percorso = testo
    self:init()
    return true
end

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
