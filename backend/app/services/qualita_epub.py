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
    pulizia        20  residui di OCR: numeri di pagina, sillabazione, righe spezzate
    presentazione  15  CSS vero, copertina dichiarata
    metadati       10  titolo, autore, lingua, identificativo

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
from html.parser import HTMLParser
from urllib.parse import unquote
from xml.etree import ElementTree as ET

# Si alza a ogni cambio che cambia i risultati: Kolibre rianalizza i libri
# che hanno una versione più vecchia (standard concordato con kolibre-14, 14/11).
VERSIONE = "2.0"

PESI = {"indice": 30, "struttura": 25, "pulizia": 20, "presentazione": 15, "metadati": 10}

# Sotto queste parole un libro non ha bisogno di un indice articolato.
LIBRO_BREVE = 8000
# Un file con meno parole di così è un divisore (titolo di parte, pagina bianca).
PAROLE_DIVISORE = 60
# Un file con almeno tante parole è un capitolo «vero».
PAROLE_CAPITOLO = 300

FINE_FRASE = tuple('.!?…»"”’:;)]—–*')

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


# ── Lettura di un documento XHTML ─────────────────────────────────────────

class _Doc(HTMLParser):
    """Raccoglie in un passaggio: parole, titoli, id con la loro posizione, paragrafi."""

    BLOCCHI = {"p", "div", "li", "blockquote", "td", "dd", "dt"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parole = 0
        self.id_pos = {}          # id -> parole prima dell'id
        self.titoli = []          # (livello, posizione in parole)
        self.paragrafi = []       # testo dei <p>, per la pulizia
        self.n_p = 0
        self.parole_in_p = 0
        self.br = 0
        self.style_inline = 0
        self.img = 0
        self.link = []            # href dei <a>: indice fatto a pagina, link rotti
        self.risorse = []         # src delle immagini, per le risorse mancanti
        self.xml_ok = True        # il file è XML ben formato (RSC-016)
        self._in_body = False
        self._p_depth = 0
        self._p_buf = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = dict(attrs)
        if tag == "body":
            self._in_body = True
        if tag in ("script", "style", "head"):
            self._skip += 1
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
        elif tag == "br":
            self.br += 1
        elif tag in ("img", "image", "svg"):
            self.img += 1
            src = a.get("src") or a.get("xlink:href") or a.get("href")
            if tag != "svg" and src and not src.startswith(("http:", "https:", "data:")):
                self.risorse.append(src)
        elif tag == "a" and a.get("href") and not a["href"].startswith(("http:", "https:", "mailto:")):
            self.link.append(a["href"])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() == "p":
            self.handle_endtag("p")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style", "head") and self._skip:
            self._skip -= 1
        if tag == "p" and self._p_depth:
            self._p_depth -= 1
            testo = " ".join("".join(self._p_buf).split())
            if testo:
                self.paragrafi.append(testo)

    def handle_data(self, data):
        if self._skip or not self._in_body:
            return
        n = len(data.split())
        self.parole += n
        if self._p_depth:
            self.parole_in_p += n
            self._p_buf.append(data)


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
        # Copertura: la sezione più lunga senza una voce d'indice, in quota del libro.
        if sequenza and not breve:
            punti = sorted(set(sequenza)) + [totale]
            sezioni = [punti[0]] + [b - a for a, b in zip(punti, punti[1:])]
            quota_max = max(sezioni) / totale
            copertura = _lineare(quota_max, 0.5, 0.2)
            if quota_max > 0.35:
                difetto("toc_grossolano", f"Un tratto pari al {quota_max:.0%} del libro non ha voci d'indice",
                        gravita=2 if quota_max > 0.6 else 1,
                        chi="auto" if sum(len(d.titoli) for d in docs.values()) > 3 else "ia")
        else:
            quota_max = None
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
        # Un indice che non copre il libro vale poco, qualunque cosa dicano i suoi link.
        indice = ((0.1 * presenza + 0.2 * bersagli + 0.15 * ordine + 0.15 * annidamento) * (0.25 + 0.75 * copertura)
                  + 0.4 * copertura)
        if n_voci == 0:
            indice = 0.0
        elif indice_a_pagina:
            indice *= 0.8

        # ── Struttura ──────────────────────────────────────────────────
        capitoli = [s for s in spine if docs[s].parole >= PAROLE_CAPITOLO]
        con_titolo = [s for s in capitoli if docs[s].titoli]
        titoli = len(con_titolo) / len(capitoli) if capitoli else (1.0 if breve else 0.0)
        if capitoli and titoli < 0.5:
            difetto("titoli_assenti",
                    f"Solo {len(con_titolo)} capitoli su {len(capitoli)} hanno un titolo vero (h1–h6)")
        # Gerarchia: un divisore (file breve con un titolo) non può avere un livello
        # più basso dei capitoli che lo seguono.
        primo = [(s, docs[s].titoli[0][0]) for s in spine if docs[s].titoli]
        divisori, invertiti = 0, 0
        for i, (s, liv) in enumerate(primo):
            if docs[s].parole < PAROLE_DIVISORE and i + 1 < len(primo):
                seguenti = [l for t, l in primo[i + 1:i + 4] if docs[t].parole >= PAROLE_CAPITOLO]
                if seguenti:
                    divisori += 1
                    if liv > min(seguenti):
                        invertiti += 1
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
        struttura = 0.35 * titoli + 0.3 * gerarchia + 0.15 * suddivisione + 0.1 * paragrafi + 0.1 * collegamenti
        malformati = [s for s in spine if not docs[s].xml_ok]
        if malformati:
            difetto("xml_malformato", f"{len(malformati)} file non sono XML ben formato: KOReader li legge, "
                    "altri lettori più severi forse no", dove=malformati)

        # ── Pulizia (su un campione di paragrafi) ──────────────────────
        tutti_p = [p for s in spine for p in docs[s].paragrafi]
        campione = tutti_p[:20000]
        n = len(campione) or 1
        numeri = sum(1 for p in campione if re.fullmatch(r"[\-–—\s]*\d{1,4}[\-–—\s]*", p))
        parole_c = sum(len(p.split()) for p in campione) or 1
        sillabe = sum(len(re.findall(r"[a-zà-ù]{2,}- [a-zà-ù]{2,}", p)) for p in campione)
        spezzati = 0
        for a, b in zip(campione, campione[1:]):
            if len(a) > 40 and not a.rstrip().endswith(FINE_FRASE) and b[:1].islower():
                spezzati += 1
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
        pulizia = (0.3 * _lineare(q_num, 0.02, 0.0) + 0.25 * _lineare(q_sill, 5, 0.5)
                   + 0.3 * _lineare(q_spez, 0.08, 0.01) + 0.15 * _lineare(q_test, 0.03, 0.0))
        if numeri > 3 and q_num > 0.005:
            difetto("numeri_pagina", f"{numeri} paragrafi sono solo un numero: numeri di pagina")
        if q_sill > 2:
            difetto("sillabazione", f"{sillabe} parole spezzate dal trattino di fine riga")
        if q_spez > 0.03:
            difetto("paragrafi_spezzati",
                    f"{spezzati} paragrafi finiscono a metà frase e continuano nel successivo")
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
                "capitoli": len(capitoli), "capitoli_con_titolo": len(con_titolo),
                "divisori": divisori, "divisori_invertiti": invertiti, "salti_livello": salti,
                "quota_file_max": round(quota_file_max, 2), "briciole": briciole,
                "quota_testo_in_p": round(quota_p, 2), "br_ogni_mille": round(br_ogni_mille, 1),
                "numeri_pagina": numeri, "sillabe_ogni_10k": round(q_sill, 1),
                "paragrafi_spezzati": spezzati, "testatine": testate,
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
