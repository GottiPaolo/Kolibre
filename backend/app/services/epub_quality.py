"""
Quanto vale un EPUB.

Serve a scegliere, fra due file dello stesso libro, quale tenere. La
domanda non e' filosofica: due EPUB della stessa opera possono essere una
scansione OCR sputata in un unico blocco di testo e un'edizione con
indice, capitoli, stili e copertina — e finche' non si misura la
differenza, un accorpamento automatico e' un tiro di dadi.

I criteri vengono dalla nota di una precedente migrazione di biblioteca,
dove lo stesso problema era gia' stato affrontato su scala molto maggiore
(122.851 EPUB grezzi da ridurre a 45.441 eletti):

    - TOC ben definito
    - struttura HTML complessa e differenziata
    - CSS presente
    - peso del file maggiore (tendenzialmente)
    - integrita'

Il punteggio va da 0 a 100 e NON e' una probabilita' di niente: e' una
somma di indizi, ognuno dei quali puo' sbagliare da solo. Va guardato
insieme al dettaglio, che questa funzione restituisce accanto al totale
proprio perche' nessuno debba fidarsi del numero nudo.

Il "tendenzialmente" del peso e' importante ed e' rispettato: il peso pesa
poco (15 punti su 100) perche' un file grosso puo' esserlo per immagini a
400 dpi di una scansione illeggibile. Conta come conferma, non come prova.
"""

import os
import re
import zipfile
from typing import Optional

# Quanto vale ogni indizio. La somma fa 100.
PESI = {
    "integrita": 20,      # si apre, e dentro c'e' quello che dichiara
    "toc": 25,            # un indice vero, con piu' di due voci
    "struttura": 25,      # capitoli separati, marcatura differenziata
    "css": 15,            # qualcuno ha impaginato invece di sputare testo
    "peso": 15,           # a parita' di tutto, il piu' sostanzioso
}

# Oltre questa dimensione il peso non aggiunge piu' fiducia: un EPUB di
# testo ben fatto sta quasi sempre sotto, e sopra ci sono soprattutto
# scansioni.
PESO_PIENO_BYTE = 2 * 1024 * 1024

# Quante marcature diverse ci si aspetta da un EPUB curato. Sotto le tre
# (tipicamente solo <p> e <div>) siamo davanti a testo riversato.
TAG_STRUTTURALI = ("h1", "h2", "h3", "h4", "section", "blockquote", "em", "strong", "i", "b", "cite")


def _sicuro(v: float) -> int:
    return max(0, min(100, round(v)))


def qualita_epub(percorso: str) -> Optional[dict]:
    """
    Il punteggio di un EPUB e il perche'.

    `None` se il file non e' leggibile affatto: non e' zero, e' "non lo so"
    — e sono due cose che un accorpamento automatico deve trattare in modo
    diverso.
    """
    if not os.path.exists(percorso):
        return None

    dettaglio = {}
    try:
        dimensione = os.path.getsize(percorso)
        with zipfile.ZipFile(percorso, "r") as z:
            nomi = z.namelist()

            # ── Integrita' ──────────────────────────────────────────────
            # testzip() rilegge ogni voce e verifica il CRC: e' l'unica
            # prova che il file non sia troncato a meta' download, che e'
            # il difetto piu' comune e il piu' invisibile (l'EPUB si apre
            # lo stesso, e finisce a pagina 80 su 300).
            rotto = z.testzip()
            ha_opf = any(n.endswith(".opf") for n in nomi)
            ha_mimetype = "mimetype" in nomi
            integrita = 0.0
            if rotto is None:
                integrita += 0.6
            if ha_opf:
                integrita += 0.3
            if ha_mimetype:
                integrita += 0.1
            dettaglio["integrita"] = {
                "punteggio": round(integrita * 100),
                "crc_ok": rotto is None,
                "primo_file_rotto": rotto,
                "ha_opf": ha_opf,
            }

            # Un file che non si apre o non ha l'OPF non e' un EPUB scarso:
            # e' un altro problema, e va detto invece che pesato.
            if rotto is not None or not ha_opf:
                return {
                    "punteggio": _sicuro(integrita * PESI["integrita"]),
                    "leggibile": False,
                    "dimensione": dimensione,
                    "dettaglio": dettaglio,
                }

            # ── Indice ─────────────────────────────────────────────────
            # Due formati: toc.ncx (EPUB 2) e il nav con epub:type="toc"
            # (EPUB 3). Si conta quante voci ha davvero: un indice con una
            # voce sola e' un indice finto, e ce ne sono tanti.
            voci_toc = 0
            for n in nomi:
                basso = n.lower()
                if basso.endswith(".ncx"):
                    try:
                        voci_toc = max(voci_toc, z.read(n).decode("utf-8", "ignore").count("<navPoint"))
                    except Exception:
                        pass
                elif basso.endswith((".xhtml", ".html")) and ("nav" in basso or "toc" in basso):
                    try:
                        testo = z.read(n).decode("utf-8", "ignore")
                        if 'epub:type="toc"' in testo or "epub:type='toc'" in testo:
                            voci_toc = max(voci_toc, testo.count("<a "))
                    except Exception:
                        pass
            # Tre voci per meta' punteggio, dodici per il pieno: sotto le
            # tre non e' un indice, sopra le dodici non e' piu' un merito.
            toc = 0.0 if voci_toc < 3 else min(1.0, 0.5 + (voci_toc - 3) / 18)
            dettaglio["toc"] = {"punteggio": round(toc * 100), "voci": voci_toc}

            # ── Struttura ──────────────────────────────────────────────
            # Due cose diverse che insieme dicono "qualcuno l'ha
            # impaginato": i documenti sono piu' d'uno (capitoli separati,
            # non un unico blocco), e la marcatura e' differenziata
            # (titoli, citazioni, corsivi) invece che tutta <p>.
            documenti = [n for n in nomi if n.lower().endswith((".xhtml", ".html", ".htm"))]
            campione = ""
            for n in documenti[:8]:
                try:
                    campione += z.read(n).decode("utf-8", "ignore")[:60_000]
                except Exception:
                    pass
            tag_diversi = sum(1 for t in TAG_STRUTTURALI if re.search(rf"<{t}[\s>]", campione, re.I))
            # Sei documenti per il pieno sul primo mezzo punto, sei tag
            # diversi per il secondo.
            struttura = min(1.0, len(documenti) / 6) * 0.5 + min(1.0, tag_diversi / 6) * 0.5
            dettaglio["struttura"] = {
                "punteggio": round(struttura * 100),
                "documenti": len(documenti),
                "tag_diversi": tag_diversi,
            }

            # ── CSS ────────────────────────────────────────────────────
            fogli = [n for n in nomi if n.lower().endswith(".css")]
            byte_css = 0
            for n in fogli[:5]:
                try:
                    byte_css += len(z.read(n))
                except Exception:
                    pass
            # Un foglio di stile da duecento byte e' un residuo, non una
            # impaginazione: il pieno arriva a quattromila.
            css = 0.0 if not fogli else min(1.0, 0.4 + byte_css / 4000 * 0.6)
            dettaglio["css"] = {"punteggio": round(css * 100), "fogli": len(fogli), "byte": byte_css}

            # ── Peso ───────────────────────────────────────────────────
            peso = min(1.0, dimensione / PESO_PIENO_BYTE)
            dettaglio["peso"] = {"punteggio": round(peso * 100), "byte": dimensione}

        totale = (
            integrita * PESI["integrita"]
            + toc * PESI["toc"]
            + struttura * PESI["struttura"]
            + css * PESI["css"]
            + peso * PESI["peso"]
        )
        return {
            "punteggio": _sicuro(totale),
            "leggibile": True,
            "dimensione": dimensione,
            "dettaglio": dettaglio,
        }
    except Exception:
        # Qualunque cosa, non solo BadZipFile/OSError: `testzip()` alza
        # RuntimeError su uno zip cifrato, e la promessa del docstring e'
        # «None se il file non e' leggibile affatto» — non «None per le due
        # eccezioni a cui avevo pensato». Un solo file cosi' mandava in 500
        # tutta la ricerca doppioni, che e' l'unico chiamante.
        # Non e' un EPUB, o non si legge dal disco. Diverso da un EPUB
        # brutto, e chi decide deve poterlo distinguere.
        return None


def qualita_file(percorso: str, formato: str) -> Optional[dict]:
    """
    Il punteggio di un file qualsiasi.

    Solo gli EPUB si sanno misurare davvero. Per gli altri formati si torna
    `None` — "non lo so" — invece di inventare un numero: e' proprio il
    caso in cui un accorpamento automatico deve fermarsi e chiedere.
    """
    if (formato or "").upper() == "EPUB":
        return qualita_epub(percorso)
    return None
