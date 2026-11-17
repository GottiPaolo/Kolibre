#!/usr/bin/env python3
"""
Qualità di un EPUB — proposta v2 (14/11/2026), fuori da Kolibre.

Che cosa cambia rispetto al prototipo (qualita_epub.py), dopo EPUBCheck e
la prova con il motore di KOReader sui 1139 libri:

1. Due domande separate. «Si apre in KOReader così com'è?» (`pronto`) e
   «quanto è fatto bene?» (`punteggio`). Un difetto *bloccante* non abbassa
   il punteggio: rende il libro non pronto. Sparisce il -10 ad hoc per lo
   zip impacchettato male.
2. Una tabella di regole (POLITICA): per ogni codice di difetto la
   dimensione, la gravità, se blocca, chi lo sistema e il codice EPUBCheck
   corrispondente. Gravità e blocchi si cambiano lì, non nel codice.
3. Ogni difetto dice dove si trova (`dove`: file, voce, risorsa).
4. Bloccante solo ciò che il motore di KOReader non apre davvero (prova del
   14/11): manca il file `mimetype`, oppure `container.xml` non è alla
   radice. `mimetype` non primo, XML malformato ed errori di schema: KOReader
   li legge, quindi non bloccano (EPUBCheck li dà ERROR o FATAL).
5. Controlli presi da EPUBCheck e rifatti in Python: risorse dichiarate che
   mancano (RSC-001), link interni rotti nel testo (RSC-007, RSC-012), XML
   malformato (RSC-016). Niente validazione di schema (RSC-005).
6. Metadati: un titolo che è il nome di un file o di un programma
   («Microsoft Word - …», «….doc») conta come titolo mancante: KOReader
   mostra quello.

Un punteggio assoluto da 0 a 100 e, separata, la lista dei difetti con
l'indicazione di chi può sistemarli. Si guarda la struttura, non il senso
del testo: niente euristiche sulle parole delle voci d'indice (scelta di
Paolo del 14/11).

Sei dimensioni, ciascuna da 0 a 1:
    integrità      cancello: se il file non si legge, il resto non conta
    indice         30  bersagli validi, ordine di lettura, copertura, presenza
    struttura      25  titoli veri, gerarchia coerente, suddivisione, paragrafi
    pulizia        25  residui di OCR: numeri di pagina, sillabazione, righe spezzate
    presentazione  10  CSS vero, copertina dichiarata
    metadati       10  titolo, autore, lingua, identificativo

**La v2.2 (17/11/2026) cambia quattro cose**, tutte dallo studio
`Progetti_metis/Kolibre - Qualità EPUB/studio-2026-11-17/` (variante P9,
approvata da Paolo). Il perché di ciascuna sta accanto al codice che la fa:

  1. **l'indice si giudica sui buchi EVITABILI**: un tratto senza voci che
     dentro non ha nessun titolo non è un difetto dell'indice ma del testo.
     E si giudica così **solo dove i titoli sono marcati**: un libro con i
     capitoli in testo semplice («I», «libro secondo») li ha, e noi non li
     vediamo;
  2. **la pulizia si combina per prodotto**: un residuo al suo peggio svuota
     la dimensione, invece di essere mediato dagli altri. Con due aggiunte
     perché non punisca la poesia e le forme che non sono prosa;
  3. **le note incollate** contano come collegamenti che mancano: un numero
     di nota rimasto nel testo senza la sua nota è un link che non c'è;
  4. **i pesi** passano da 30/25/20/15/10 a **30/25/25/10/10**.

Il peso del file non entra: dice poco della qualità (un file grosso è spesso
una scansione) e rende il punteggio relativo.

Uso:
    python3 qualita_epub_v2.py file.epub            dettaglio di un libro
    python3 qualita_epub_v2.py cartella/ out.csv    tutti gli EPUB, in un CSV
"""
import csv
import html
import json
import os
import posixpath
import re
import sys
import zipfile
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import unquote
from xml.etree import ElementTree as ET

# Si alza a ogni cambio che cambia i risultati: Kolibre rianalizza i libri
# che hanno una versione più vecchia (standard concordato con kolibre-14, 14/11).
VERSIONE = "2.2"

PESI = {"indice": 30, "struttura": 25, "pulizia": 25, "presentazione": 10, "metadati": 10}

# Sotto queste parole un libro non ha bisogno di un indice articolato.
LIBRO_BREVE = 8000
# Un file con meno parole di così è un divisore (titolo di parte, pagina bianca).
PAROLE_DIVISORE = 60
# Un file con almeno tante parole è un capitolo «vero».
PAROLE_CAPITOLO = 300

# ── Quanto fitto deve essere un indice (v2.1, 16/11/2026) ────────────────
#
# **Il difetto che queste tre righe chiudono.** «Germinale» di Zola prendeva
# 100 su 100 con un indice inservibile: 45 titoli nel testo, 14 voci
# nell'indice, perché lo strumento che l'ha prodotto tiene la prima volta che
# compare ogni nome e butta le ripetizioni. Nessuno dei quattro controlli
# sull'indice lo vedeva — i doppioni qui erano stati tolti, l'ordine era
# perfetto, l'indice piatto non aveva niente di annidato male, e la
# COPERTURA era buona: il tratto più lungo senza una voce era il 17% del
# libro, sotto la soglia del 35%. **Un indice può coprire bene un libro ed
# essere inutile come elenco**, perché poche voci sparse non lasciano buchi
# grandi: la copertura e la grana sono due domande diverse.
#
# **I numeri vengono dal corpus, non dalla testa** (1139 libri, misurati il
# 16/11/2026 prima di scrivere una riga). Il rapporto fra voci d'indice e
# unità navigabili è ≥ 0,90 per l'81% dei libri: un indice fitto è la norma,
# non un ideale. Sotto 0,55 ci sono 93 libri su 1119, e 82 di loro hanno già
# un altro difetto d'indice — cioè questo controllo quasi sempre conferma un
# giudizio che c'era, e in 11 casi dice una cosa che nessuno diceva.
# Fra questi «I demoni» di Dostoevskij, 27 voci per 110 unità, punteggio 100:
# la stessa forma di Germinale.
RAPPORTO_SCARNO = 0.55
# Sotto questo, il difetto è grave: i casi puliti del corpus stanno tutti
# sotto 0,40 (Germinale 0,31, «I demoni» 0,25, «Guerra e pace» 0,08).
RAPPORTO_GRAVE = 0.35
# **Sotto questa misura non si giudica**, e non è prudenza: il rapporto non
# vuol dire niente su pochi pezzi. Sul corpus i due soli falsi allarmi erano
# esattamente questo — un saggio in 2 file con una voce, uno in 3 file con
# una voce. Lo stesso spirito di LIBRO_BREVE qui sopra.
UNITA_MINIME_PER_GIUDICARE = 10

FINE_FRASE = tuple('.!?…»"”’:;)]—–*')

# ── v2.2: i versi non sono paragrafi spezzati ─────────────────────────────
#
# **Il difetto che queste tre soglie chiudono** (studio del 17/11/2026,
# `versi.py`). Il rilevatore dei paragrafi spezzati conta una riga di più di 40
# caratteri che non finisce con la punteggiatura ed è seguita da una riga che
# comincia in minuscolo. **Molti versi sono fatti esattamente così**, e con la
# pulizia combinata per prodotto la poesia crollava: «Antologia di Spoon River»
# da 44 a 25.
#
# **La lunghezza della riga non basta a distinguerli**, e questo è il punto che
# costa due giorni a chi lo rifà da capo: ci sono OCR che fanno un paragrafo
# per ogni riga stampata, e le loro righe sono brevi come i versi (la riga
# spezzata mediana è 56 caratteri, contro i 42-50 della poesia). Nemmeno la
# regolarità delle lunghezze separa i due casi: la metrica di Petrarca è
# regolare quanto una colonna giustificata.
#
# **Quello che separa è COME FINISCE la riga.** La riga stampata si spezza dove
# capita: spesso dopo una parola vuota («del», «the»), spesso con la parola
# tagliata dal trattino, di rado sulla punteggiatura. Il verso finisce dove
# finisce un'unità di senso o di metro. Misurato su 11 libri di poesia e 11 di
# prosa con paragrafi spezzati:
#
#              finisce con punteggiatura   con parola vuota   col trattino
#   poesia              50-77%                  0-3%              0%
#   riga stampata       17-36%                 15-34%           1-30%
#
# La regola non guarda il titolo né il libro, guarda la forma delle righe
# **intorno alla coppia**: funziona anche sui versi citati dentro un libro in
# prosa (il Giobbe di Negri, i versi latini in Colombo).
VERSO_RIGA_MAX = 100       # una riga di verso sta sotto questa lunghezza
VERSO_FINESTRA_MIN = 6     # servono almeno tante righe brevi di fila per giudicare
VERSO_SOGLIA = 0.30        # punteggiatura − parole vuote − 2 × trattini, sulla finestra

# Le parole su cui una riga stampata si spezza e un verso no. Cinque lingue:
# italiano, inglese, francese, spagnolo, tedesco.
PAROLE_VUOTE = set("""
di a da in con su per tra fra il lo la i gli le un uno una del dello della dei degli delle al allo alla ai agli alle
dal dallo dalla dai dagli dalle nel nello nella nei negli nelle sul sullo sulla sui sugli sulle col coi e o ma che se
non come più anche ed od né ci si ne mi ti vi è sono ha hanno era quale quali questo questa questi queste quel quella
the a an of to in on at by for with from and or but that as is was are were his her its their this these which who
le la les un une des du de et à au aux en que qui dans par pour sur ne se son sa ses ce cette est
el los las y en con por para del al que lo su
der die das und in mit von zu den dem des ein eine auf für ist nicht
""".split())
FINE_PUNT = tuple(".,;:!?…»\"”’')]—–")

# **Sotto questo numero di coppie la pulizia non giudica** (scelta di Paolo,
# 17/11/2026). Due paragrafi spezzati veri in un opuscolo di 23 paragrafi fanno
# l'8,7%, cioè portano la pulizia a zero: il residuo c'è, il giudizio è
# sproporzionato («Anarchia e violenza» di Malatesta, da 89 a 66). È lo stesso
# spirito di UNITA_MINIME_PER_GIUDICARE per l'indice, e come là **tace anche il
# difetto**: un difetto che non toglie un punto è un nome senza conseguenze, e
# qui la regola è l'opposta — ogni punto perso ha un nome.
COPPIE_MINIME_PER_GIUDICARE = 10

# Una coppia non è prosa continua quando fra le due righe c'è un oggetto
# (un'equazione come immagine, una tabella), quando la seconda riga è fatta
# solo di un link, o quando sono due voci «termine: definizione» di un
# glossario. Trovate leggendo i libri che scendevano di più: Rovelli
# («…questa diventa» [equazione] «dove ψ…»), le «Omelie» di Colombo (righe
# fatte solo da un link «audio»), il glossario di Rapino.
VOCE_GLOSSARIO = re.compile(r"^[^\s:]{1,30}( [^\s:]{1,20})?: \S")

# ── v2.2: le note incollate ───────────────────────────────────────────────
#
# Un numero di nota rimasto attaccato a una parola nel testo («sublime3») è il
# segno di una nota che **non c'è o non si raggiunge**: il rimando è nel testo,
# la nota no. Letti a mano i 18 libri sopra 1 ogni 1000 parole: 11 avevano note
# vere non collegate, 2 un residuo vero di altro genere, 5 erano falsi allarmi
# — tutti manuali tecnici («Var1», «GNS3», «IPv4», «wlan0»).
#
# Le due correzioni che li distinguono:
#   1. **il codice non è testo**: dentro <pre>, <code>, <tt>, <kbd>, <samp> non
#      si guarda;
#   2. **una parola incollata a un numero tre volte o più è un nome**, non una
#      nota: le note cambiano parola e numero ogni volta, un identificativo no.
#
# E una cosa che il rilevatore fa di proposito: intorno a <a> e <sup> si mette
# uno spazio, quindi una nota **marcata come si deve** non viene contata. Si
# contano solo i numeri rimasti nudi nel testo.
NOTA_INCOLLATA = re.compile(r"^[^\W\d_]{3,}[\.,;:!?»”\")\]]*\d{1,3}[\.,;:]?$")
RIPETIZIONI_IDENTIFICATIVO = 3
TAG_CODICE = ("pre", "code", "tt", "kbd", "samp")
# Note ogni 1000 parole: a 0,3 nessuna penalità, a 2,0 penalità piena.
NOTE_SCALA = (2.0, 0.3)

# ── v2.2: la pulizia si combina per prodotto ──────────────────────────────
#
# Prima era una media pesata, e un residuo al suo peggio veniva diluito dagli
# altri tre: un libro con i paragrafi tutti spezzati prendeva comunque 70 di
# pulizia perché numeri, sillabazione e testatine erano a posto. Per prodotto,
# **ogni residuo toglie la sua quota**, come la copertura fa da sempre con
# l'indice. Il peso è quanto quel residuo può togliere da solo: i paragrafi
# spezzati tutto, i numeri di pagina e la sillabazione metà, le testatine meno.
PULIZIA_PESI = {"num": 0.5, "sill": 0.5, "spez": 1.0, "test": 0.4}

# ── La tabella delle regole ───────────────────────────────────────────────
# codice: (dimensione, gravità 1-3, blocca, chi lo sistema, codice EPUBCheck)
#   gravità   3 grave, 2 media, 1 lieve
#   blocca    True: KOReader non apre il libro così com'è (libro non «pronto»)
#   chi       "auto" uno script, "ia" serve leggere il testo, "no" non si sistema
#   EPUBCheck il controllo corrispondente, «—» se EPUBCheck non lo fa
# Prima di cambiare una riga: la prova va fatta sui libri (KOReader, Calibre),
# e il perché si scrive nella nota Qualità EPUB, «Casistica».
POLITICA = {
    "zip_illeggibile":     ("integrità", 3, True,  "no",   "PKG-003/PKG-004"),
    "crc":                 ("integrità", 3, True,  "no",   "—"),
    "mimetype_assente":    ("integrità", 3, True,  "auto", "PKG-006"),
    "mimetype_non_primo":  ("integrità", 1, False, "auto", "PKG-006/PKG-007"),
    "container":           ("integrità", 3, True,  "auto", "RSC-002"),
    "opf_illeggibile":     ("integrità", 3, True,  "no",   "OPF/RSC-016"),
    "spine_mancanti":      ("integrità", 3, False, "no",   "RSC-001"),
    "spine_vuoto":         ("integrità", 3, True,  "no",   "OPF-033"),
    "risorse_mancanti":    ("integrità", 2, False, "no",   "RSC-001"),
    "xml_malformato":      ("integrità", 1, False, "auto", "RSC-016"),
    "toc_assente":         ("indice", 3, False, "auto", "—"),
    "toc_voci_uguali":     ("indice", 3, False, "auto", "—"),
    "toc_solo_pagina":     ("indice", 1, False, "auto", "—"),
    "toc_bersagli":        ("indice", 2, False, "auto", "RSC-007/RSC-012"),
    "toc_ordine":          ("indice", 2, False, "auto", "NAV-011"),
    "toc_grossolano":      ("indice", 2, False, "auto", "—"),
    "toc_scarno":          ("indice", 2, False, "auto", "—"),
    # Peso zero sul punteggio, di proposito: vedi dov'è segnalato.
    "toc_piatto":          ("indice", 1, False, "auto", "—"),
    "toc_annidamento":     ("indice", 2, False, "auto", "—"),
    "titoli_assenti":      ("struttura", 2, False, "ia",   "—"),
    "gerarchia_invertita": ("struttura", 2, False, "auto", "—"),
    "monolite":            ("struttura", 2, False, "auto", "—"),
    "briciole":            ("struttura", 1, False, "auto", "—"),
    "paragrafi_assenti":   ("struttura", 1, False, "ia",   "—"),
    "righe_a_capo":        ("struttura", 1, False, "ia",   "—"),
    "link_rotti":          ("struttura", 2, False, "auto", "RSC-007/RSC-012"),
    "numeri_pagina":       ("pulizia", 1, False, "auto", "—"),
    "sillabazione":        ("pulizia", 1, False, "ia",   "—"),
    "paragrafi_spezzati":  ("pulizia", 2, False, "ia",   "—"),
    # v2.2: un rimando di nota rimasto nel testo senza la sua nota. Il «chi» lo
    # decide il caso: «auto» se le note ci sono in fondo al libro e basta
    # ricollegarle, «no» se dal file mancano del tutto.
    "note_scollegate":     ("struttura", 2, False, "auto", "—"),
    "testatine":           ("pulizia", 1, False, "auto", "—"),
    "css_assente":         ("presentazione", 1, False, "auto", "—"),
    "copertina":           ("presentazione", 1, False, "auto", "—"),
    "metadati":            ("metadati", 1, False, "auto", "OPF-053/RSC-005"),
}

# Un titolo così è il nome di un file o di un programma, non del libro.
TITOLO_FINTO = re.compile(r"(microsoft word|\.docx?\b|\.rtf\b|\.pdf\b|\.html?\b|_ebook\b|^untitled|^sconosciuto$|^unknown$)", re.I)


def _ns(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _lineare(x, peggio, meglio):
    """0 a `peggio`, 1 a `meglio`, lineare in mezzo (funziona in tutte e due le direzioni)."""
    if peggio == meglio:
        return 1.0
    t = (x - peggio) / (meglio - peggio)
    return max(0.0, min(1.0, t))


# ── v2.2: quali coppie di righe sono prosa spezzata per davvero ──────────
#
# Il rilevatore della v2.1 segna una coppia quando la prima riga è lunga, non
# finisce con la punteggiatura, e la seconda comincia in minuscolo. Queste
# funzioni togliono da quell'elenco le coppie che non sono prosa continua: i
# versi (vedi le soglie in testa al file) e tre forme strutturali.


def _fine_riga(t):
    """Come finisce la riga: «punt», «trattino», «vuota» o «altro»."""
    t = t.rstrip()
    if re.search(r"[^\W\d_]-$", t):
        return "trattino"
    if t.endswith(FINE_PUNT):
        return "punt"
    pezzi = t.split()
    ultima = pezzi[-1].lower() if pezzi else ""
    if ultima.endswith(("'", "’")) or ultima in PAROLE_VUOTE:
        return "vuota"
    return "altro"


def _finestra(lung, i, tetto=VERSO_RIGA_MAX, raggio=30):
    """Le righe brevi di fila intorno alla riga `i`, al massimo `raggio` per lato."""
    j0 = i
    while j0 > 0 and lung[j0 - 1] < tetto and i - j0 < raggio:
        j0 -= 1
    j1 = i + 1
    while j1 + 1 < len(lung) and lung[j1 + 1] < tetto and j1 - i < raggio:
        j1 += 1
    return range(j0, j1 + 1)


def _profilo_fine(testi, indici):
    """Le quote dei quattro modi di finire, su quelle righe."""
    tipi = [_fine_riga(testi[j]) for j in indici]
    n = len(tipi) or 1
    return {k: sum(1 for x in tipi if x == k) / n for k in ("punt", "trattino", "vuota", "altro")}


def _non_prosa(testi, solo_link, oggetto_prima, i):
    """
    Perché quella coppia non è prosa continua, o `None`.

    Tre forme viste leggendo i libri che il prodotto faceva scendere di più:
    un oggetto in mezzo (l'equazione di Rovelli), una riga fatta solo da un
    link (le «Omelie» di Colombo), due voci di glossario (Rapino).
    """
    if i + 1 >= len(testi):
        return None
    if oggetto_prima[i + 1]:
        return "oggetto"
    if solo_link[i + 1]:
        return "link"
    if VOCE_GLOSSARIO.match(testi[i]) and VOCE_GLOSSARIO.match(testi[i + 1]):
        return "voci"
    return None


def _coppie_di_prosa(testi, solo_link, oggetto_prima, coppie):
    """
    Delle coppie segnate, quelle che sono davvero prosa spezzata.

    Una coppia esce dall'elenco se è un verso — la finestra di righe brevi
    intorno finisce come finiscono i versi — oppure se non è prosa continua.
    """
    lung = [len(t) for t in testi]
    restano = []
    for i in coppie:
        if lung[i] >= VERSO_RIGA_MAX:
            restano.append(i)
            continue
        idx = [j for j in _finestra(lung, i) if lung[j] < VERSO_RIGA_MAX]
        if len(idx) < VERSO_FINESTRA_MIN:
            restano.append(i)
            continue
        q = _profilo_fine(testi, idx)
        if q["punt"] - q["vuota"] - 2 * q["trattino"] >= VERSO_SOGLIA:
            continue                      # versi
        restano.append(i)
    return [i for i in restano if not _non_prosa(testi, solo_link, oggetto_prima, i)]


# ── Lettura di un documento XHTML ─────────────────────────────────────────

class _Doc(HTMLParser):
    """Raccoglie in un passaggio: parole, titoli, id con la loro posizione, paragrafi."""

    BLOCCHI = {"p", "div", "li", "blockquote", "td", "dd", "dt"}
    # I confini dei blocchi per il flusso delle note: come i BLOCCHI qui
    # sopra, piu' i titoli e i <br>. Una parola non si legge a cavallo di un
    # confine di blocco, e un numero attaccato alla riga di sotto non e' una
    # nota incollata.
    BLOCCHI_NOTE = BLOCCHI | {"h1", "h2", "h3", "h4", "h5", "h6", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parole = 0
        self.id_pos = {}          # id -> parole prima dell'id
        self.titoli = []          # (livello, posizione in parole)
        self.paragrafi = []       # testo dei <p>, per la pulizia
        # v2.2, in parallelo a `paragrafi` (stesso indice): due cose che
        # servono a dire se una coppia di righe è prosa continua o no.
        #   solo_link      il <p> non ha testo fuori dai link (una riga «audio»)
        #   oggetto_prima  fra il <p> precedente e questo c'è un'immagine, una
        #                  formula o una tabella
        self.p_solo_link = []
        self.p_oggetto_prima = []
        self.n_p = 0
        self.parole_in_p = 0
        self.br = 0
        self.style_inline = 0
        self.img = 0
        self.link = []            # href dei <a>: indice fatto a pagina, link rotti
        self.risorse = []         # src delle immagini, per le risorse mancanti
        self.xml_ok = True        # il file è XML ben formato (RSC-016)
        # v2.2: le note incollate. Si contano mentre si legge invece di tenere
        # il testo: su un libro da cinque megabyte tenerlo tutto costa più
        # della misura. `note_radici` conta quante volte ogni parola compare
        # incollata a un numero — serve a riconoscere un identificativo
        # («GNS3» tre volte) da una nota (parola e numero sempre diversi).
        self.note_radici = Counter()
        self.note_parole = 0
        self._n_buf = []
        self._n_skip = 0
        self._in_body = False
        self._p_depth = 0
        self._p_buf = []
        self._skip = 0
        self._in_a = 0
        self._p_fuori_link = False
        self._oggetto = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = dict(attrs)
        if tag == "body":
            self._in_body = True
        if tag in ("script", "style", "head"):
            self._skip += 1
        # v2.2, flusso delle note: il codice non è testo, e intorno a <a> e
        # <sup> si mette uno spazio — così una nota marcata come si deve non
        # viene contata, e si contano solo i numeri rimasti nudi nel testo.
        if tag in TAG_CODICE:
            self._n_skip += 1
        if tag in ("a", "sup"):
            self._n_buf.append(" ")
        if tag in self.BLOCCHI_NOTE:
            self._chiudi_note()
        if "id" in a:
            self.id_pos.setdefault(a["id"], self.parole)
        if tag == "a" and "name" in a:
            self.id_pos.setdefault(a["name"], self.parole)
        if not self._in_body:
            return
        if "style" in a:
            self.style_inline += 1
        if re.fullmatch(r"h[1-6]", tag):
            self.titoli.append((int(tag[1]), self.parole))
        elif tag == "p":
            self.n_p += 1
            self._p_depth += 1
            self._p_buf = []
            self._p_fuori_link = False
        elif tag == "br":
            self.br += 1
        elif tag in ("table", "math", "object"):
            # Non si contano (non sono immagini): servono solo a sapere che fra
            # due righe c'è un oggetto, quindi non sono prosa continua.
            self._oggetto = True
        elif tag in ("img", "image", "svg"):
            self.img += 1
            self._oggetto = True
            src = a.get("src") or a.get("xlink:href") or a.get("href")
            if tag != "svg" and src and not src.startswith(("http:", "https:", "data:")):
                self.risorse.append(src)
        elif tag == "a" and a.get("href") and not a["href"].startswith(("http:", "https:", "mailto:")):
            self.link.append(a["href"])
        if tag == "a":
            self._in_a += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        # **Anche `a`, e non solo `p`** (corretto il 17/11/2026, misurando).
        # Un'ancora autochiudente — `<a id="x"/>`, comunissima negli XHTML
        # degli EPUB — apriva il conto dei link e non lo chiudeva mai: da quel
        # punto in poi `_in_a` restava sopra zero, quindi ogni paragrafo
        # risultava «fatto solo di un link». Su «Introduction to Logic» di
        # Tarski erano 2847 paragrafi su 2858, e la regola che scarta le righe
        # fatte solo da un link buttava via tutte le coppie: 41 residui veri
        # diventavano 0. Trovato confrontando i conti con la copia di studio,
        # non leggendo.
        if tag.lower() in ("p", "a"):
            self.handle_endtag(tag.lower())

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style", "head") and self._skip:
            self._skip -= 1
        if tag in TAG_CODICE and self._n_skip:
            self._n_skip -= 1
        if tag in ("a", "sup"):
            self._n_buf.append(" ")
        if tag in self.BLOCCHI_NOTE:
            self._chiudi_note()
        if tag == "a" and self._in_a:
            self._in_a -= 1
        if tag == "p" and self._p_depth:
            self._p_depth -= 1
            testo = " ".join("".join(self._p_buf).split())
            if testo:
                self.paragrafi.append(testo)
                self.p_solo_link.append(not self._p_fuori_link)
                self.p_oggetto_prima.append(self._oggetto)
                # L'oggetto «vale» per la prima riga che lo segue e poi è
                # consumato: due paragrafi dopo un'immagine sono prosa fra
                # loro.
                self._oggetto = False

    def _chiudi_note(self):
        """
        Chiude un blocco di testo e conta i numeri rimasti incollati.

        Si conta qui e non alla fine perche' il testo non si tiene: si tiene
        il conto. `note_radici` conta per PAROLA, perche' la stessa parola
        incollata a un numero tre volte o piu' e' un identificativo e non una
        nota (vedi RIPETIZIONI_IDENTIFICATIVO).
        """
        testo = " ".join("".join(self._n_buf).split())
        self._n_buf = []
        if not testo:
            return
        for tok in testo.split():
            self.note_parole += 1
            t = tok.strip("«»“”(")
            if NOTA_INCOLLATA.match(t) and not re.search(r"\d{4}", tok):
                radice = re.match(r"[^\W\d_]+", t)
                if radice:
                    self.note_radici[radice.group(0).lower()] += 1

    def close(self):
        # L'ultimo blocco non ha un tag che lo chiuda.
        super().close()
        self._chiudi_note()

    def handle_data(self, data):
        if self._skip or not self._in_body:
            return
        if not self._n_skip:
            self._n_buf.append(data)
        n = len(data.split())
        self.parole += n
        if self._p_depth:
            self.parole_in_p += n
            self._p_buf.append(data)
            if not self._in_a and data.strip():
                self._p_fuori_link = True


def _leggi_doc(z, nome):
    d = _Doc()
    try:
        dati = z.read(nome)
    except Exception:
        return d
    try:
        ET.fromstring(dati)
    except ET.ParseError as e:
        # Le entità HTML (&nbsp; …) non sono un errore per i lettori, ma ET non le conosce:
        # conta come malformato solo un errore che non sia un'entità sconosciuta.
        if "undefined entity" not in str(e):
            d.xml_ok = False
    try:
        d.feed(dati.decode("utf-8", "ignore"))
        d.close()
    except Exception:
        pass
    return d


# ── Indice: NCX (EPUB 2) o nav (EPUB 3) ───────────────────────────────────

def _voci_ncx(z, nome):
    base = posixpath.dirname(nome)
    radice = ET.fromstring(z.read(nome))
    voci = []

    def giu(el, prof):
        for np_ in el:
            if _ns(np_.tag) != "navpoint":
                continue
            cont = next((c for c in np_ if _ns(c.tag) == "content"), None)
            if cont is not None and cont.get("src"):
                voci.append((prof, base, cont.get("src")))
            giu(np_, prof + 1)

    nav_map = next((e for e in radice.iter() if _ns(e.tag) == "navmap"), None)
    if nav_map is not None:
        giu(nav_map, 0)
    return voci


def _voci_nav(z, nome):
    base = posixpath.dirname(nome)
    radice = ET.fromstring(z.read(nome))
    nav = None
    for e in radice.iter():
        if _ns(e.tag) == "nav" and any(k.endswith("type") and "toc" in v for k, v in e.attrib.items()):
            nav = e
            break
    if nav is None:
        return []
    voci = []

    def giu(el, prof):
        for li in el:
            if _ns(li.tag) != "li":
                continue
            a = next((c for c in li.iter() if _ns(c.tag) == "a"), None)
            if a is not None and a.get("href"):
                voci.append((prof, base, a.get("href")))
            for sotto in li:
                if _ns(sotto.tag) == "ol":
                    giu(sotto, prof + 1)

    ol = next((c for c in nav.iter() if _ns(c.tag) == "ol"), None)
    if ol is not None:
        giu(ol, 0)
    return voci


# ── La funzione ───────────────────────────────────────────────────────────

def qualita_epub(percorso):
    difetti = []

    def difetto(codice, testo, dove=None, chi=None, gravita=None):
        # Dimensione, gravità, blocco e chi lo sistema vengono dalla POLITICA.
        # `chi` e `gravita` si passano solo quando dipendono dal libro (un indice
        # si ricava da uno script se ci sono titoli veri, altrimenti serve l'IA).
        dim, grav, blocca, chi_pol, epubcheck = POLITICA[codice]
        difetti.append({"codice": codice, "dimensione": dim, "gravita": gravita or grav, "blocca": blocca,
                        "sistemabile": chi or chi_pol, "epubcheck": epubcheck,
                        "dove": (dove or [])[:10], "testo": testo})

    def senza_punteggio():
        # Il contenuto non si raggiunge: niente punteggio, il libro non è pronto.
        # Stesse chiavi di un risultato normale: chi legge il JSON non deve inciampare.
        return {"versione": VERSIONE, "leggibile": False, "pronto": False, "si_sistema_da_solo": False,
                "punteggio": 0, "dimensioni": {}, "misure": {},
                "difetti": sorted(difetti, key=lambda d: (not d["blocca"], -d["gravita"]))}

    try:
        z = zipfile.ZipFile(percorso)
    except Exception as e:
        difetto("zip_illeggibile", f"Non è uno zip leggibile ({type(e).__name__})")
        return senza_punteggio()

    with z:
        elenco = z.namelist()
        nomi = set(elenco)
        # ── Integrità ──────────────────────────────────────────────────
        try:
            rotto = z.testzip()
        except Exception:
            rotto = "?"
        if rotto:
            difetto("crc", f"File troncato o corrotto: {rotto}", dove=[rotto])
        # KOReader (prova del 14/11) vuole il file «mimetype» e container.xml alla
        # radice; che «mimetype» sia il primo file dello zip non gli importa.
        if "mimetype" not in nomi:
            difetto("mimetype_assente", "Manca il file «mimetype»: KOReader non lo riconosce come EPUB e apre lo zip come archivio")
        elif elenco[0] != "mimetype":
            difetto("mimetype_non_primo", "«mimetype» non è il primo file dello zip, come vuole la norma (i lettori provati lo aprono lo stesso)")
        opf = None
        try:
            cont = ET.fromstring(z.read("META-INF/container.xml"))
            opf = next(e.get("full-path") for e in cont.iter() if _ns(e.tag) == "rootfile")
            radice_opf = ET.fromstring(z.read(opf))
        except Exception:
            container_ok = "META-INF/container.xml" in nomi
            opf = next((n for n in sorted(nomi) if n.lower().endswith(".opf") and "__MACOSX" not in n
                        and not posixpath.basename(n).startswith("._")), None)
            try:
                radice_opf = ET.fromstring(z.read(opf)) if opf else None
            except Exception:
                radice_opf = None
            if not container_ok or radice_opf is not None:
                cartella = sorted({n.split("/")[0] for n in nomi if "/" in n and not n.startswith("__MACOSX")})[:3]
                difetto("container", "Zip impacchettato male (container.xml non alla radice): KOReader non lo apre, "
                        "il libro dentro è intero e si reimpacchetta", dove=cartella)
        if radice_opf is None:
            difetto("opf_illeggibile", "Il file OPF, l'elenco del libro, non si trova o non si legge", dove=[opf] if opf else [])
            return senza_punteggio()
        if rotto:
            return senza_punteggio()

        base = posixpath.dirname(opf)

        def risolvi(b, href):
            return posixpath.normpath(posixpath.join(b, unquote(html.unescape(href))))

        manifest = {}
        for e in radice_opf.iter():
            if _ns(e.tag) == "item" and e.get("href"):
                manifest[e.get("id")] = (risolvi(base, e.get("href")), e.get("media-type") or "", e.get("properties") or "")
        spine = []
        for e in radice_opf.iter():
            if _ns(e.tag) == "itemref" and e.get("idref") in manifest:
                spine.append(manifest[e.get("idref")][0])
        mancanti = [s for s in spine if s not in nomi]
        if mancanti:
            difetto("spine_mancanti", f"{len(mancanti)} file dell'ordine di lettura non ci sono", dove=mancanti)
        spine = [s for s in spine if s in nomi]
        if not spine:
            difetto("spine_vuoto", "Nessun file da leggere: l'ordine di lettura è vuoto o punta a file che non ci sono")
            return senza_punteggio()
        # Risorse dichiarate nel manifest che nello zip non ci sono (RSC-001).
        assenti = sorted(m[0] for m in manifest.values() if m[0] not in nomi and m[0] not in mancanti)
        if assenti:
            difetto("risorse_mancanti", f"{len(assenti)} file dichiarati nell'elenco del libro non ci sono", dove=assenti)

        # ── Lettura dei documenti nell'ordine di lettura ───────────────
        docs = {s: _leggi_doc(z, s) for s in spine}
        inizio = {}
        cum = 0
        for s in spine:
            inizio[s] = cum
            cum += docs[s].parole
        totale = cum or 1

        # ── Indice ─────────────────────────────────────────────────────
        voci = []
        nav = [m for m in manifest.values() if "nav" in m[2].split()]
        # NCX: dal media-type giusto, dall'attributo toc dello spine o dall'estensione
        # (i vecchi EPUB lo dichiarano «text/xml»).
        id_toc = next((e.get("toc") for e in radice_opf.iter() if _ns(e.tag) == "spine" and e.get("toc")), None)
        ncx = [m for m in manifest.values() if m[1] == "application/x-dtbncx+xml"]
        ncx += [manifest[id_toc]] if id_toc in manifest else []
        ncx += [m for m in manifest.values() if m[0].lower().endswith(".ncx")]
        for fonte, lettore in ((nav, _voci_nav), (ncx, _voci_ncx)):
            for m in fonte:
                if voci or m[0] not in nomi:
                    continue
                try:
                    voci = lettore(z, m[0])
                except Exception:
                    voci = []
        # Senza NCX né nav, un indice può esserci lo stesso: una pagina del libro
        # piena di link agli altri file. I lettori non lo vedono come indice, ma si
        # naviga, e uno script ne ricava l'NCX.
        indice_a_pagina = False
        if not voci:
            migliore, n_migliore = None, 0
            for s in spine:
                b = posixpath.dirname(s)
                destinazioni = {risolvi(b, h.partition("#")[0]) for h in docs[s].link if h.partition("#")[0]}
                n_dest = len(destinazioni & set(spine) - {s})
                if n_dest > n_migliore:
                    migliore, n_migliore = s, n_dest
            if migliore and n_migliore >= 5:
                b = posixpath.dirname(migliore)
                voci = [(0, b, h) for h in docs[migliore].link if risolvi(b, h.partition("#")[0]) in docs]
                indice_a_pagina = True
                difetto("toc_solo_pagina",
                        "L'indice è solo una pagina del libro: manca quello del lettore (NCX o nav), si ricava da lì")
        # ── Le unità navigabili, contate qui perché servono a due sezioni ──
        #
        # Stavano dentro «Struttura» e sono state portate su il 16/11/2026,
        # senza cambiare una virgola del calcolo: all'indice servono per
        # sapere quante cose un indice dovrebbe elencare, e alla struttura
        # continuano a servire per la gerarchia. Calcolarle due volte
        # vorrebbe dire due definizioni di «capitolo» che un giorno
        # divergono.
        capitoli = [s for s in spine if docs[s].parole >= PAROLE_CAPITOLO]
        # Un divisore è un file breve con un titolo, seguito da capitoli veri:
        # il frontespizio di una parte.
        primo = [(s, docs[s].titoli[0][0]) for s in spine if docs[s].titoli]
        divisori, invertiti = 0, 0
        for i, (s, liv) in enumerate(primo):
            if docs[s].parole < PAROLE_DIVISORE and i + 1 < len(primo):
                seguenti = [l for t, l in primo[i + 1:i + 4] if docs[t].parole >= PAROLE_CAPITOLO]
                if seguenti:
                    divisori += 1
                    if liv > min(seguenti):
                        invertiti += 1

        pos, rotti = [], 0
        for prof, b, href in voci:
            f, _, ancora = href.partition("#")
            f = risolvi(b, f) if f else None
            if not f or f not in docs:
                rotti += 1
                continue
            if ancora and unquote(ancora) not in docs[f].id_pos:
                rotti += 1
                pos.append((prof, inizio[f], f))
                continue
            pos.append((prof, inizio[f] + (docs[f].id_pos.get(unquote(ancora), 0) if ancora else 0), f))
        n_voci = len(voci)
        breve = totale < LIBRO_BREVE
        stesso_punto = n_voci - len({p_ for _, p_, _ in pos})
        if n_voci >= 3 and stesso_punto >= n_voci / 2:
            difetto("toc_voci_uguali", chi="auto" if sum(len(d.titoli) for d in docs.values()) > 3 else "ia", testo=
                    f"{stesso_punto + 1} voci su {n_voci} puntano allo stesso punto: l'indice c'è ma non porta da nessuna parte")

        if n_voci == 0:
            presenza = 0.0
            difetto("toc_assente", chi="auto" if any(d.titoli for d in docs.values()) else "ia", testo=
                    "Nessun indice")
        elif n_voci < 3 and not breve:
            presenza = 0.3
        else:
            presenza = 1.0
        bersagli = 1 - rotti / n_voci if n_voci else 0.0
        if rotti:
            difetto("toc_bersagli", f"{rotti} voci su {n_voci} puntano a file o ancore che non esistono")
        sequenza = [p for _, p, _ in pos]
        inversioni = sum(1 for a, b in zip(sequenza, sequenza[1:]) if b < a)
        ordine = 1 - inversioni / max(1, len(sequenza) - 1) if len(sequenza) > 1 else (1.0 if sequenza else 0.0)
        if inversioni:
            difetto("toc_ordine", f"{inversioni} voci tornano indietro rispetto all'ordine di lettura")
        # ── Copertura: il tratto più lungo senza una voce d'indice ─────
        #
        # **v2.2: si contano solo i buchi EVITABILI.** Un tratto senza voci
        # che dentro non ha nessun titolo non è un difetto dell'indice: è un
        # difetto del testo, e lo dice già `monolite`. Il caso che l'ha fatta
        # nascere è Bakunin, «Il principio dello Stato»: un saggio continuo
        # senza titoli interni, che l'indice non poteva elencare meglio di
        # così — da 60 a 94.
        #
        # **Ma si giudica così solo dove i titoli sono marcati.** Un libro che
        # ha i capitoli in testo semplice («I», «II», «libro secondo») li ha
        # per davvero, e noi non li vediamo: trattarlo come «buco inevitabile»
        # lo premierebbe per un difetto. Senza questo cancello «Memorie dal
        # sottosuolo» saliva da 41 a 77 e «Utopia» da 42 a 78, tutti e due a
        # torto. Il prezzo, dichiarato: «Il vecchio e il mare», che davvero non
        # ha capitoli, resta basso (43) — senza titoli marcati non si distingue
        # un libro senza capitoli da uno coi capitoli in testo semplice.
        #
        # `titoli_veri` è la stessa misura che la struttura usa per
        # `titoli_assenti`, calcolata qui perché serve prima.
        con_titolo = [s for s in capitoli if docs[s].titoli]
        titoli = len(con_titolo) / len(capitoli) if capitoli else (1.0 if breve else 0.0)
        titoli_veri = titoli >= 0.5
        if sequenza and not breve:
            punti = sorted(set(sequenza)) + [totale]
            sezioni = [punti[0]] + [b - a for a, b in zip(punti, punti[1:])]
            quota_max = max(sezioni) / totale
            # I punti in cui il libro «avrebbe potuto» avere una voce: un
            # titolo h1–h6, o l'inizio di un capitolo. Margine di 50 parole,
            # perché un titolo subito dopo una voce è quella voce.
            unita_pos = sorted({inizio[s] + p_ for s in spine if s in docs for _, p_ in docs[s].titoli}
                               | {inizio[s] for s in capitoli})
            tratti = [(0, punti[0])] + list(zip(punti, punti[1:]))
            evitabili = [b - a for a, b in tratti if any(a + 50 < u < b for u in unita_pos)]
            quota_ev = max(evitabili) / totale if evitabili else 0.0
            # Il buco su cui si giudica: quello evitabile dove i titoli ci
            # sono, altrimenti quello di sempre.
            quota_giudicata = quota_ev if titoli_veri else quota_max
            copertura = _lineare(quota_giudicata, 0.5, 0.2)
            if quota_giudicata > 0.35:
                difetto("toc_grossolano",
                        f"Un tratto pari al {quota_giudicata:.0%} del libro non ha voci d'indice"
                        + (" e dentro ha titoli che l'indice avrebbe potuto elencare" if titoli_veri else ""),
                        gravita=2 if quota_giudicata > 0.6 else 1,
                        chi="auto" if sum(len(d.titoli) for d in docs.values()) > 3 else "ia")
        else:
            quota_max = None
            quota_giudicata = None
            copertura = 1.0 if (sequenza or breve) else 0.0
        # Annidamento: una voce che punta a un divisore (titolo di parte) non può
        # stare dentro una voce che punta a un capitolo intero.
        annidati, su_divisori = 0, 0
        genitori = {}
        for prof, p_, f in pos:
            genitori[prof] = f
            if docs[f].parole < PAROLE_DIVISORE and docs[f].titoli:
                su_divisori += 1
                padre = genitori.get(prof - 1) if prof > 0 else None
                if padre and docs[padre].parole >= PAROLE_CAPITOLO:
                    annidati += 1
        annidamento = 1 - annidati / su_divisori if su_divisori else 1.0
        if annidati:
            difetto("toc_annidamento",
                    f"{annidati} titoli di parte stanno nell'indice dentro un capitolo invece che sopra")
        # ── La grana: quante voci ha l'indice rispetto a quante cose ci sono ──
        #
        # **La domanda che mancava.** La copertura qui sopra chiede «ci sono
        # buchi grandi?»; questa chiede «l'indice elenca le cose che il libro
        # ha?». Sono diverse, e il caso che l'ha fatta nascere lo dimostra:
        # «Germinale» aveva una copertura del 17% (ottima) e 14 voci per 45
        # fra capitoli e parti. Vedi RAPPORTO_SCARNO per i numeri del corpus.
        #
        # Il rapporto si taglia a 1: un indice con più voci delle unità (voci
        # su àncore dentro uno stesso file) non è un difetto, è un indice
        # fitto.
        unita = len(capitoli) + divisori
        giudicabile = bool(sequenza) and not breve and unita >= UNITA_MINIME_PER_GIUDICARE
        if giudicabile:
            rapporto = min(1.0, n_voci / unita)
            # **La scala finisce dove comincia il difetto, non oltre.** Prima
            # saliva fino a 0,75, e il risultato era un libro che perdeva
            # quattro punti senza che nessun difetto lo spiegasse — visto sul
            # corpus: «I principi della matematica», da 100 a 96 con la
            # tabella dei difetti vuota. In una pagina che elenca i difetti,
            # un punteggio che cala in silenzio è peggio di un punteggio
            # generoso. Così **ogni punto perso ha un nome**: sopra
            # RAPPORTO_SCARNO non cambia niente, sotto c'è sempre
            # `toc_scarno` a dire perché.
            granularita = _lineare(rapporto, 0.25, RAPPORTO_SCARNO)
            if rapporto < RAPPORTO_SCARNO:
                difetto("toc_scarno",
                        f"L'indice ha {n_voci} voci per {unita} fra capitoli e parti: "
                        f"elenca meno di un {rapporto:.0%} di quello che c'è nel libro",
                        gravita=2 if rapporto < RAPPORTO_GRAVE else 1)
        else:
            rapporto, granularita = None, 1.0
        # **L'indice piatto su un libro a parti: si dice e non si conta.**
        # Peso zero sul punteggio di proposito. Un indice senza annidamento è
        # legittimo in un libro senza parti, e lo è anche in uno con parti se
        # le voci ci sono tutte — quindi è un indizio da leggere insieme agli
        # altri, non un giudizio. Soglia a due divisori: con uno solo
        # «l'indice dovrebbe avere due livelli» non si sostiene.
        if divisori >= 2 and n_voci and max(p_ for p_, _, _ in pos) == 0:
            difetto("toc_piatto",
                    f"Il libro ha {divisori} parti, ma l'indice è su un livello solo: "
                    "nel menù del lettore i capitoli non stanno sotto la loro parte")
        # Un indice che non copre il libro vale poco, qualunque cosa dicano i suoi link.
        # E uno della grana sbagliata nemmeno: `utile` è quanto l'indice
        # DESCRIVE il libro, e la grana ne pesa poco più di un terzo. Con una
        # grana sana (`granularita` = 1) `utile` è esattamente la copertura di
        # prima, quindi la v2.1 non sposta di un punto i libri con un indice
        # fitto — e sono l'81% del corpus.
        utile = copertura * (0.65 + 0.35 * granularita)
        indice = ((0.1 * presenza + 0.2 * bersagli + 0.15 * ordine + 0.15 * annidamento) * (0.25 + 0.75 * utile)
                  + 0.4 * utile)
        if n_voci == 0:
            indice = 0.0
        elif indice_a_pagina:
            indice *= 0.8

        # ── Struttura ──────────────────────────────────────────────────
        # `titoli` e `con_titolo` sono già stati calcolati sopra: la copertura
        # evitabile ne ha bisogno prima, e una misura calcolata due volte è
        # una misura che prima o poi diverge.
        if capitoli and titoli < 0.5:
            difetto("titoli_assenti",
                    f"Solo {len(con_titolo)} capitoli su {len(capitoli)} hanno un titolo vero (h1–h6)")
        # Salti di livello dentro i capitoli (h1 → h4 senza h2 e h3).
        salti = 0
        tutti = [l for s in spine for l, _ in docs[s].titoli]
        for a, b in zip(tutti, tutti[1:]):
            if b > a + 1:
                salti += 1
        gerarchia = 1.0 if tutti else 0.0   # senza titoli non c'è gerarchia da lodare
        if divisori:
            gerarchia -= invertiti / divisori
        if tutti:
            gerarchia -= 0.3 * min(1.0, salti / max(1, len(tutti)) * 4)
        gerarchia = max(0.0, gerarchia)
        if invertiti:
            difetto("gerarchia_invertita",
                    f"{invertiti} titoli di parte hanno un livello più basso dei capitoli che contengono")
        # Suddivisione: né monolite né briciole.
        quota_file_max = max(docs[s].parole for s in spine) / totale
        briciole = sum(1 for s in spine if docs[s].parole < 30 and not docs[s].titoli and not docs[s].img)
        quota_briciole = briciole / len(spine)
        suddivisione = 1.0
        if not breve and quota_file_max > 0.4:
            suddivisione -= _lineare(quota_file_max, 0.4, 0.9)
            difetto("monolite", f"Un solo file contiene il {quota_file_max:.0%} del testo")
        if quota_briciole > 0.15:
            suddivisione -= 0.5 * _lineare(quota_briciole, 0.15, 0.5)
            difetto("briciole",
                    f"{briciole} file su {len(spine)} sono quasi vuoti, senza titolo né immagini")
        suddivisione = max(0.0, suddivisione)
        parole_p = sum(d.parole_in_p for d in docs.values())
        quota_p = parole_p / totale
        br_ogni_mille = 1000 * sum(d.br for d in docs.values()) / totale
        paragrafi = _lineare(quota_p, 0.3, 0.8) * (1 - 0.5 * _lineare(br_ogni_mille, 5, 30))
        if quota_p < 0.5:
            difetto("paragrafi_assenti", f"Solo il {quota_p:.0%} del testo sta in paragrafi <p>")
        if br_ogni_mille > 10:
            difetto("righe_a_capo",
                    f"{br_ogni_mille:.0f} a capo forzati (<br>) ogni mille parole: righe della pagina stampata")
        # Collegamenti interni (note, rimandi, indici a pagina): file o ancora che
        # non esistono (RSC-007, RSC-012). Chi tocca una nota rotta finisce nel vuoto.
        n_link, link_rotti, dove_link = 0, 0, []
        for s in spine:
            b = posixpath.dirname(s)
            for h in docs[s].link:
                f, _, ancora = h.partition("#")
                bersaglio = risolvi(b, f) if f else s
                n_link += 1
                if bersaglio not in nomi or (ancora and bersaglio in docs
                                             and unquote(ancora) not in docs[bersaglio].id_pos):
                    link_rotti += 1
                    dove_link.append(f"{s} → {h}")
        collegamenti = 1 - link_rotti / n_link if n_link else 1.0
        if link_rotti:
            difetto("link_rotti", f"{link_rotti} link interni su {n_link} puntano a file o ancore che non esistono",
                    dove=dove_link, gravita=2 if link_rotti / n_link > 0.1 else 1)
        # ── v2.2: le note incollate contano come collegamenti che mancano ──
        #
        # Un numero di nota rimasto attaccato a una parola nel testo
        # («sublime3») è un rimando che non porta da nessuna parte: la nota non
        # c'è, o c'è in fondo al libro e non si raggiunge. È un link che manca,
        # quindi entra qui dentro — e **si prende il minimo** fra i due, non la
        # media: due modi diversi di non arrivare da nessuna parte non si
        # compensano.
        #
        # Il conto l'ha fatto il parser mentre leggeva (`note_radici`). Una
        # parola che compare incollata a un numero tre volte o più non è una
        # nota ma un nome: «GNS3» in un manuale di rete, «Var1» in uno di
        # Excel. Era la causa di tutti e cinque i falsi allarmi del campione.
        note_radici = Counter()
        note_parole = 0
        for d in docs.values():
            note_radici.update(d.note_radici)
            note_parole += d.note_parole
        note_incollate = sum(c for c in note_radici.values() if c < RIPETIZIONI_IDENTIFICATIVO)
        note_1k = 1000 * note_incollate / max(1, note_parole)
        s_note = _lineare(note_1k, *NOTE_SCALA)
        collegamenti = min(collegamenti, s_note)
        if note_1k > NOTE_SCALA[1]:
            # «auto» se le note ci sono in fondo al libro e basta ricollegarle,
            # «no» se mancano del tutto (il caso di Chomsky): la differenza la
            # fa l'esistenza di un file di note fra quelli dello spine.
            ci_sono = any(re.search(r"(note|notes|footnote|endnote)", s_, re.I) for s_ in spine)
            difetto("note_scollegate",
                    f"{note_incollate} rimandi di nota sono rimasti nel testo "
                    f"({note_1k:.1f} ogni 1000 parole)"
                    + (": le note ci sono ma non si raggiungono" if ci_sono
                       else ": le note non sono nel file"),
                    gravita=2 if note_1k > 1.0 else 1,
                    chi="auto" if ci_sono else "no")
        struttura = 0.35 * titoli + 0.3 * gerarchia + 0.15 * suddivisione + 0.1 * paragrafi + 0.1 * collegamenti
        malformati = [s for s in spine if not docs[s].xml_ok]
        if malformati:
            difetto("xml_malformato", f"{len(malformati)} file non sono XML ben formato: KOReader li legge, "
                    "altri lettori più severi forse no", dove=malformati)

        # ── Pulizia (su un campione di paragrafi) ──────────────────────
        tutti_p = [p for s in spine for p in docs[s].paragrafi]
        campione = tutti_p[:20000]
        # Le due informazioni in parallelo, nello stesso ordine e tagliate allo
        # stesso punto: servono a dire se una coppia è prosa continua.
        tutti_link = [x for s in spine for x in docs[s].p_solo_link][:20000]
        tutti_ogg = [x for s in spine for x in docs[s].p_oggetto_prima][:20000]
        n = len(campione) or 1
        numeri = sum(1 for p in campione if re.fullmatch(r"[\-–—\s]*\d{1,4}[\-–—\s]*", p))
        parole_c = sum(len(p.split()) for p in campione) or 1
        sillabe = sum(len(re.findall(r"[a-zà-ù]{2,}- [a-zà-ù]{2,}", p)) for p in campione)
        # Le coppie segnate dal rilevatore di sempre…
        segnate = [i for i, (a, b) in enumerate(zip(campione, campione[1:]))
                   if len(a) > 40 and not a.rstrip().endswith(FINE_FRASE) and b[:1].islower()]
        # …e, della v2.2, quelle che sono prosa spezzata per davvero: fuori i
        # versi e le forme che non sono prosa continua. Vedi `_coppie_di_prosa`.
        prosa = _coppie_di_prosa(campione, tutti_link, tutti_ogg, segnate)
        segnate_n = len(segnate)
        spezzati = len(prosa)
        # Testatine: la stessa riga breve (titolo, autore, nome del file) ripetuta
        # molte volte. Non contano dialoghi, numeri di verso, numeri romani, separatori.
        brevi = {}
        for p in campione:
            if 2 <= len(p.split()) <= 8 and p[:1].isalpha():
                brevi[p] = brevi.get(p, 0) + 1
        testate = sum(c for c in brevi.values() if c >= 8)
        q_num = numeri / n
        q_sill = 10000 * sillabe / parole_c
        q_spez = spezzati / n
        q_test = testate / n
        # **Pochi casi non si giudicano**: vedi COPPIE_MINIME_PER_GIUDICARE.
        # Il residuo resta scritto nei numeri (`paragrafi_spezzati` qui sotto
        # tace, come tace il punteggio), ma due casi in un opuscolo non
        # svuotano una dimensione.
        spez_giudicabile = spezzati >= COPPIE_MINIME_PER_GIUDICARE
        sotto = {
            "num": _lineare(q_num, 0.02, 0.0),
            "sill": _lineare(q_sill, 5, 0.5),
            "spez": _lineare(q_spez, 0.08, 0.01) if spez_giudicabile else 1.0,
            "test": _lineare(q_test, 0.03, 0.0),
        }
        # **Per prodotto, non per media** (v2.2): ogni residuo toglie la sua
        # quota, e uno al suo peggio svuota la dimensione. Vedi PULIZIA_PESI.
        pulizia = 1.0
        for chiave, peso in PULIZIA_PESI.items():
            pulizia *= 1 - peso * (1 - sotto[chiave])
        if numeri > 3 and q_num > 0.005:
            difetto("numeri_pagina", f"{numeri} paragrafi sono solo un numero: numeri di pagina")
        if q_sill > 2:
            difetto("sillabazione", f"{sillabe} parole spezzate dal trattino di fine riga")
        if q_spez > 0.03 and spez_giudicabile:
            difetto("paragrafi_spezzati",
                    f"{spezzati} paragrafi finiscono a metà frase e continuano nel successivo"
                    + (f" (su {segnate_n} coppie segnate, le altre sono versi o non sono prosa)"
                       if segnate_n > spezzati else ""))
        if testate:
            difetto("testatine", f"{testate} righe brevi ripetute: testatine o piè di pagina")

        # ── Presentazione ──────────────────────────────────────────────
        css_nomi = [m[0] for m in manifest.values() if m[1] == "text/css" and m[0] in nomi]
        regole = 0
        for c in css_nomi[:5]:
            try:
                regole += z.read(c).decode("utf-8", "ignore").count("{")
            except Exception:
                pass
        css = 0.0 if not css_nomi else _lineare(regole, 0, 15)
        if not css_nomi:
            difetto("css_assente", "Nessun foglio di stile")
        copertina = 0.0
        if any("cover-image" in m[2].split() for m in manifest.values()):
            copertina = 1.0
        else:
            for e in radice_opf.iter():
                if _ns(e.tag) == "meta" and e.get("name") == "cover" and e.get("content") in manifest:
                    copertina = 1.0 if manifest[e.get("content")][1].startswith("image/") else 0.5
        if copertina < 1:
            difetto("copertina", "La copertina non è dichiarata nell'OPF")
        # Immagini richiamate dal testo che nello zip non ci sono: un riquadro vuoto.
        n_img, img_assenti = 0, []
        for s in spine:
            b = posixpath.dirname(s)
            for src in docs[s].risorse:
                n_img += 1
                if risolvi(b, src.partition("#")[0]) not in nomi:
                    img_assenti.append(f"{s} → {src}")
        immagini = 1 - len(img_assenti) / n_img if n_img else 1.0
        if img_assenti:
            difetto("risorse_mancanti", f"{len(img_assenti)} immagini su {n_img} richiamate dal testo non ci sono",
                    dove=img_assenti)
        presentazione = (0.6 * css + 0.4 * copertina) * (0.5 + 0.5 * immagini)

        # ── Metadati ───────────────────────────────────────────────────
        dc = {}
        for e in radice_opf.iter():
            if e.tag.startswith("{http://purl.org/dc/elements/1.1/}") and (e.text or "").strip():
                dc.setdefault(_ns(e.tag), e.text.strip())
        lingua_ok = bool(re.fullmatch(r"[a-z]{2,3}(-[A-Za-z0-9]+)*", dc.get("language", "")))
        # Un titolo che è il nome di un file o di un programma vale come titolo mancante:
        # è quello che KOReader mostra nella lista dei libri.
        titolo = dc.get("title", "")
        titolo_ok = bool(titolo) and not TITOLO_FINTO.search(titolo)
        mancano = [k for k, ok in (("titolo", titolo_ok), ("autore", "creator" in dc),
                                   ("lingua", lingua_ok), ("identificativo", "identifier" in dc)) if not ok]
        metadati = 1 - len(mancano) / 4
        if mancano:
            testo = "Mancano: " + ", ".join(mancano)
            if titolo and not titolo_ok:
                testo += f" (il titolo «{titolo}» è il nome di un file)"
            difetto("metadati", testo, dove=[opf])

        dimensioni = {"indice": indice, "struttura": struttura, "pulizia": pulizia,
                      "presentazione": presentazione, "metadati": metadati}
        # Presentazione e metadati contano in proporzione al cuore (indice, struttura,
        # pulizia): un libro che non si naviga non si salva con una bella copertina.
        cuore = (PESI["indice"] * indice + PESI["struttura"] * struttura + PESI["pulizia"] * pulizia)
        quota_cuore = cuore / (PESI["indice"] + PESI["struttura"] + PESI["pulizia"])
        punteggio = cuore + (PESI["presentazione"] * presentazione + PESI["metadati"] * metadati) * quota_cuore
        # Il punteggio dice com'è fatto il libro; «pronto» dice se KOReader lo apre
        # così com'è. Un libro sano impacchettato male ha un buon punteggio e non è pronto.
        bloccanti = [d for d in difetti if d["blocca"]]
        return {
            "versione": VERSIONE,
            "leggibile": True,
            "pronto": not bloccanti,
            "si_sistema_da_solo": bool(bloccanti) and all(d["sistemabile"] == "auto" for d in bloccanti),
            "punteggio": max(0, round(punteggio)),
            "dimensioni": {k: round(v * 100) for k, v in dimensioni.items()},
            "misure": {
                "parole": totale, "file_spine": len(spine), "voci_toc": n_voci, "voci_rotte": rotti,
                "inversioni_toc": inversioni, "toc_annidati": annidati, "quota_max_senza_voce": None if quota_max is None else round(quota_max, 2),
                "unita_navigabili": unita, "voci_per_unita": None if rapporto is None else round(rapporto, 2),
                "capitoli": len(capitoli), "capitoli_con_titolo": len(con_titolo),
                "divisori": divisori, "divisori_invertiti": invertiti, "salti_livello": salti,
                "quota_file_max": round(quota_file_max, 2), "briciole": briciole,
                "quota_testo_in_p": round(quota_p, 2), "br_ogni_mille": round(br_ogni_mille, 1),
                "numeri_pagina": numeri, "sillabe_ogni_10k": round(q_sill, 1),
                "paragrafi_spezzati": spezzati, "testatine": testate,
                # v2.2: le coppie che il rilevatore ha segnato e quelle che
                # sono rimaste dopo aver tolto versi e forme che non sono
                # prosa. Le due insieme dicono quanto ha lavorato la regola
                # nuova — con «segnate» molto sopra «spezzati» quel libro è
                # poesia o ha oggetti in mezzo.
                "coppie_segnate": segnate_n,
                "note_incollate": note_incollate,
                "note_ogni_mille": round(note_1k, 2),
                "quota_max_evitabile": None if quota_giudicata is None else round(quota_giudicata, 2),
                "regole_css": regole, "copertina": copertina,
                "link_interni": n_link, "link_rotti": link_rotti, "immagini": n_img,
                "immagini_assenti": len(img_assenti), "file_xml_malformati": len(malformati),
            },
            "difetti": sorted(difetti, key=lambda d: (not d["blocca"], -d["gravita"])),
        }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    bersaglio = sys.argv[1]
    if os.path.isfile(bersaglio):
        print(json.dumps(qualita_epub(bersaglio), ensure_ascii=False, indent=2))
        return
    uscita = sys.argv[2] if len(sys.argv) > 2 else "qualita.csv"
    file = sorted(os.path.join(r, f) for r, _, fs in os.walk(bersaglio) for f in fs if f.lower().endswith(".epub"))
    with open(uscita, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "pronto", "punteggio", *PESI, "difetti"])
        for i, f in enumerate(file, 1):
            r = qualita_epub(f)
            dim = r.get("dimensioni", {})
            w.writerow([os.path.relpath(f, bersaglio), int(r["pronto"]), r["punteggio"], *[dim.get(k, "") for k in PESI],
                        "; ".join(d["codice"] for d in r["difetti"])])
            if i % 100 == 0:
                print(f"{i}/{len(file)}", file=sys.stderr)
    print(f"Scritto {uscita}: {len(file)} EPUB")


if __name__ == "__main__":
    main()
