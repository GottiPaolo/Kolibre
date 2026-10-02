"""
Estimates a book's page count, the same problem the Calibre "Count Pages"
plugin solves (https://github.com/kiwidude68/calibre_plugins/wiki/Count-Pages):
PDF has a real, exact page count; reflowable formats (EPUB and friends) don't,
so we estimate from the extracted text length using a configurable
words-per-page or characters-per-page ratio (the same idea as that plugin's
simpler counting modes — a full rendering/pagination simulation like its most
accurate mode is out of scope here).
"""

import os
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

CONTAINER_NS = {'ns': 'urn:oasis:names:tc:opendocument:xmlns:container'}
OPF_NS = {'opf': 'http://www.idpf.org/2007/opf'}

_TAG_RE = re.compile(r'<[^>]+>')

# When a book has several formats, prefer a reflowable/"adaptable" one (its
# page count adapts to font size / device, closer to how the book is actually
# read) over PDF's fixed layout, even though PDF's count is exact and the
# others are estimates — an explicit product choice, not a fallback of
# convenience.
FORMAT_PREFERENCE = ["EPUB", "AZW3", "MOBI", "FB2", "TXT", "PDF"]


def pick_preferred_format(available_formats: list) -> str:
    for fmt in FORMAT_PREFERENCE:
        if fmt in available_formats:
            return fmt
    return available_formats[0]


def text_stats(file_path: str, fmt: str) -> Optional[dict]:
    """
    Quanti caratteri e quante parole contiene un libro, o None se il file non
    si riesce a leggere.

    Il testo veniva gia' estratto per stimare le pagine, e poi buttato via.
    Serve invece conservarlo: e' con il conteggio caratteri che una frazione
    di libro letta diventa "caratteri letti", cioe' l'unica misura di lettura
    che non dipende dal corpo del carattere scelto sul dispositivo (vedi
    stats_service e il report sulle statistiche di KOReader).

    I PDF non sono qui: il loro testo si estrae in un altro modo e per quelli
    la pagina e' gia' un'unita' reale, non stimata.
    """
    fmt = fmt.upper()
    if not os.path.exists(file_path):
        return None
    if fmt == "EPUB":
        text = _extract_epub_text(file_path)
    elif fmt == "TXT":
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            return None
    else:
        return None
    if text is None:
        return None
    return {"chars": len(text), "words": len(text.split())}


def _pagine_da_testo(text: str, mode: str, words_per_page: int, chars_per_page: int) -> int:
    if mode == "chars":
        return max(1, round(len(text) / max(1, chars_per_page)))
    return max(1, round(len(text.split()) / max(1, words_per_page)))


def count_pages(file_path: str, fmt: str, mode: str, words_per_page: int = 300, chars_per_page: int = 1500) -> Optional[int]:
    """
    Returns an estimated (or, for PDF, exact) page count, or None if the file
    can't be read/parsed.
    """
    fmt = fmt.upper()
    if not os.path.exists(file_path):
        return None
    if fmt == "PDF":
        return _count_pdf_pages(file_path)
    if fmt == "EPUB":
        text = _extract_epub_text(file_path)
        if text is None:
            return None
        return _pagine_da_testo(text, mode, words_per_page, chars_per_page)
    if fmt == "TXT":
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            return None
        return _pagine_da_testo(text, mode, words_per_page, chars_per_page)
    return None


def _count_pdf_pages(pdf_path: str) -> Optional[int]:
    from pypdf import PdfReader
    try:
        return len(PdfReader(pdf_path).pages)
    except Exception:
        return None


_DA_TOGLIERE_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)


def _extract_epub_text(epub_path: str) -> Optional[str]:
    try:
        with zipfile.ZipFile(epub_path, 'r') as z:
            # Il container.xml dentro il suo try: se manca o non e' XML valido,
            # l'eccezione saltava direttamente all'except esterno e la funzione
            # tornava None, senza mai arrivare al ripiego «cerca un .opf
            # qualsiasi» tre righe sotto — cioe' il ripiego era irraggiungibile
            # esattamente nei casi per cui esiste. metadata_parser.py fa la
            # stessa cosa con il try interno, e infatti quei file li legge.
            opf_path = None
            try:
                root = ET.fromstring(z.read("META-INF/container.xml"))
                rootfile = root.find('.//ns:rootfile', CONTAINER_NS)
                opf_path = rootfile.attrib.get('full-path') if rootfile is not None else None
            except (KeyError, ET.ParseError):
                pass
            if not opf_path:
                opf_path = next((n for n in z.namelist() if n.endswith('.opf')), None)
            if not opf_path:
                return None

            opf_dir = os.path.dirname(opf_path)
            opf_root = ET.fromstring(z.read(opf_path))
            manifest = {
                item.attrib.get('id'): item.attrib.get('href')
                for item in opf_root.findall('.//opf:manifest/opf:item', OPF_NS)
            }
            spine = opf_root.findall('.//opf:spine/opf:itemref', OPF_NS)

            text_parts = []
            for itemref in spine:
                href = manifest.get(itemref.attrib.get('idref'))
                if not href:
                    continue
                full_path = os.path.normpath(os.path.join(opf_dir, href)).replace(os.sep, '/') if opf_dir else href
                try:
                    raw = z.read(full_path).decode('utf-8', errors='ignore')
                except KeyError:
                    continue
                # <style> e <script> vanno via ELEMENTO E CONTENUTO: togliere
                # i soli tag lascia dentro le regole CSS, che finiscono contate
                # come testo del libro. Misurato su un volume reale della
                # biblioteca di prova: il 17,6% dei 2.429.895 caratteri
                # estratti erano CSS, quindi un quinto di pagine stimate in
                # piu' — e la stessa distorsione entrava in BookTextStats,
                # cioe' nella conversione «frazione letta → caratteri letti»
                # di tutte le statistiche.
                text_parts.append(_TAG_RE.sub(' ', _DA_TOGLIERE_RE.sub(' ', raw)))
            return ' '.join(text_parts)
    except Exception:
        return None
