"""
Una copertina per i libri che non ne hanno.

Il requisito, 28/09/2026: *"base base, testo con titolo e autore, font
classico su sfondo minimale deterministico e semplice. Giusto per avere una
base."*

Tre scelte che vale la pena dichiarare, perche' sono le uniche interessanti:

**Generata al volo, mai scritta nella biblioteca.** E' un ripiego visivo, non
un dato. Una copertina finta salvata dentro `cover.jpg` diventa
indistinguibile da una vera: il giorno in cui arriva quella giusta bisogna
sapere che si sta sovrascrivendo un segnaposto, e uno scaricamento di
metadati che "trova la copertina" non deve confrontarsi con una nostra. Costa
qualche millisecondo per immagine e li ripaga al primo dubbio.

**Deterministica.** Il colore esce dal titolo con uno SHA-1: lo stesso libro
da' sempre la stessa copertina, in ogni pagina e a ogni ricaricamento. Una
tinta a caso sarebbe stata piu' facile e avrebbe fatto ballare la griglia a
ogni refresh — e una griglia che balla si nota molto piu' di una tinta
mediocre.

**Sobria.** Nessun gradiente, nessuna ombra, nessuna icona: un rettangolo di
colore, il titolo, l'autore, una riga sottile. Una copertina inventata non
deve fingere di essere una copertina; deve solo smettere di essere un buco
grigio.
"""

import hashlib
import io
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

# Le proporzioni di un libro, non quelle di un'immagine qualunque: 2:3 e'
# quello che la griglia si aspetta, e una copertina finta con proporzioni
# diverse si riconosce da lontano proprio per quello.
LARGHEZZA, ALTEZZA = 400, 600

# Le tinte. Scelte scure e desaturate perche' il testo sopra dev'essere
# leggibile senza calcoli di contrasto, e perche' una fila di copertine
# inventate accanto a copertine vere non deve gridare.
_TINTE = [
    (0x3B, 0x3A, 0x36),  # inchiostro
    (0x4A, 0x3C, 0x32),  # cuoio
    (0x2F, 0x3D, 0x3A),  # verde bottiglia
    (0x3A, 0x33, 0x45),  # prugna
    (0x44, 0x35, 0x35),  # mattone
    (0x33, 0x3E, 0x4A),  # blu notte
    (0x3D, 0x42, 0x33),  # oliva
    (0x45, 0x3A, 0x2C),  # tabacco
]

# I font di sistema piu' probabili dentro il container, in ordine di
# preferenza: un serif vero e' il "font classico" chiesto, e il ripiego finale
# e' il font bitmap di PIL — brutto ma sempre presente, e una copertina brutta
# resta meglio di un 500.
_SERIF_CANDIDATI = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/System/Library/Fonts/NewYork.ttf",
)
_SERIF_CORSIVO_CANDIDATI = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf",
)


_CARTELLE_FONT = ("/usr/share/fonts", "/usr/local/share/fonts",
                  "/System/Library/Fonts", os.path.expanduser("~/Library/Fonts"))


@lru_cache(maxsize=4)
def _cerca_serif(corsivo: bool):
    """Un serif qualunque, se i candidati noti non ci sono.

    Serve perche' i percorsi qui sopra dipendono da quali pacchetti di font
    sono finiti nell'immagine, e scoprire che non c'e' nessun TTF solo dalla
    bruttezza della copertina sarebbe un modo pessimo di accorgersene."""
    for radice in _CARTELLE_FONT:
        if not os.path.isdir(radice):
            continue
        for cartella, _sub, file in os.walk(radice):
            for nome in sorted(file):
                minuscolo = nome.lower()
                if not minuscolo.endswith(".ttf") or "serif" not in minuscolo:
                    continue
                if corsivo != ("italic" in minuscolo or "oblique" in minuscolo):
                    continue
                return os.path.join(cartella, nome)
    return None


# Memorizzato: caricare il TTF costa dieci volte il disegno (66 ms contro
# 6), e una griglia di libri senza copertina lo chiederebbe a ogni
# immagine. La ricerca a tappeto fra le cartelle di sistema, ancora di piu'.
@lru_cache(maxsize=8)
def _font(candidati, dimensione: int, corsivo: bool = False):
    for percorso in candidati:
        if os.path.exists(percorso):
            try:
                return ImageFont.truetype(percorso, dimensione)
            except OSError:
                continue
    trovato = _cerca_serif(corsivo)
    if trovato:
        try:
            return ImageFont.truetype(trovato, dimensione)
        except OSError:
            pass
    return ImageFont.load_default()


def _tinta(titolo: str):
    impronta = hashlib.sha1((titolo or "").encode("utf-8")).digest()
    return _TINTE[impronta[0] % len(_TINTE)]


def _spezza(disegno, testo: str, font, larghezza_max: int, righe_max: int) -> list:
    """Il testo a capo sulle parole, troncato con i puntini se non ci sta."""
    parole = (testo or "").split()
    righe, corrente = [], ""
    for parola in parole:
        prova = f"{corrente} {parola}".strip()
        if disegno.textlength(prova, font=font) <= larghezza_max or not corrente:
            corrente = prova
        else:
            righe.append(corrente)
            corrente = parola
            if len(righe) == righe_max:
                break
    if corrente and len(righe) < righe_max:
        righe.append(corrente)
    if len(righe) == righe_max and len(" ".join(righe)) < len(testo or ""):
        ultima = righe[-1]
        while ultima and disegno.textlength(ultima + "…", font=font) > larghezza_max:
            ultima = ultima[:-1]
        righe[-1] = ultima + "…"
    return righe


def costruisci(titolo: str, autore: str) -> bytes:
    """La copertina come JPEG. Non tocca il disco: nasce e vive in memoria."""
    sfondo = _tinta(titolo)
    immagine = Image.new("RGB", (LARGHEZZA, ALTEZZA), sfondo)
    disegno = ImageDraw.Draw(immagine)

    margine = 40
    larghezza_testo = LARGHEZZA - 2 * margine
    chiaro = (0xEC, 0xE7, 0xDE)
    tenue = (0xEC, 0xE7, 0xDE, 0xB0)[:3]

    # Una cornice sottile, l'unico ornamento: senza, il testo galleggia.
    disegno.rectangle(
        [margine // 2, margine // 2, LARGHEZZA - margine // 2, ALTEZZA - margine // 2],
        outline=(sfondo[0] + 28, sfondo[1] + 28, sfondo[2] + 28), width=1,
    )

    font_titolo = _font(_SERIF_CANDIDATI, 34)
    font_autore = _font(_SERIF_CORSIVO_CANDIDATI, 22, corsivo=True)

    righe_titolo = _spezza(disegno, titolo or "Senza titolo", font_titolo, larghezza_testo, 5)
    righe_autore = _spezza(disegno, autore or "", font_autore, larghezza_testo, 2)

    # Il blocco di testo sta sopra la meta', non al centro esatto: e' dove
    # sta su una copertina vera, e al centro sembrerebbe una didascalia.
    passo_titolo, passo_autore = 44, 30
    altezza_blocco = len(righe_titolo) * passo_titolo + (24 if righe_autore else 0) + len(righe_autore) * passo_autore
    y = max(margine + 20, (ALTEZZA - altezza_blocco) // 2 - 40)

    for riga in righe_titolo:
        larghezza = disegno.textlength(riga, font=font_titolo)
        disegno.text(((LARGHEZZA - larghezza) / 2, y), riga, font=font_titolo, fill=chiaro)
        y += passo_titolo

    if righe_autore:
        y += 10
        disegno.line([(LARGHEZZA / 2 - 30, y), (LARGHEZZA / 2 + 30, y)], fill=tenue, width=1)
        y += 14
        for riga in righe_autore:
            larghezza = disegno.textlength(riga, font=font_autore)
            disegno.text(((LARGHEZZA - larghezza) / 2, y), riga, font=font_autore, fill=tenue)
            y += passo_autore

    buffer = io.BytesIO()
    immagine.save(buffer, "JPEG", quality=88)
    return buffer.getvalue()
