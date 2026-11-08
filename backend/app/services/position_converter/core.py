"""
Pure conversion core between a KOReader XPointer range and an EPUB CFI
range, over a parsed chapter document. Structure resolves positions, but
the stored highlight text is the truth: every conversion is verified by
extracting the resolved range and comparing normalized text, with
search-based re-anchoring as repair.

Ported from BookOrbit's position-converter.core.ts — forward direction
only (xpointer -> CFI), which is all this project needs (opening a
KOReader-sourced highlight in Kolibre's own epub.js web reader). See
xpointer_utils.py/cfi_utils.py's own docstrings for the same scoping note.
"""

from .cfi_utils import RangePoint, cfi_from_point, join_cfi_indirection, spine_cfi_for_chapter_index
from .chapter_text_index import ChapterTextIndex, normalize_for_search
from .html_dom import parse_html_document
from .xpointer_utils import parse_xpointer, resolve_xpointer_element

CONVERTER_VERSION = 1

# KOReader sidecar text is truncated at 10000 chars; treat near-limit text as a prefix.
_TRUNCATED_TEXT_THRESHOLD = 9990
_EXACT_HINT_TOLERANCE_CP = 2


class ChapterDocument:
    __slots__ = ("root", "index")

    def __init__(self, root, index: ChapterTextIndex):
        self.root = root
        self.index = index


class ConversionResult:
    """status='exact'|'repaired'|'ritrovata_dal_testo' carries cfi_start/cfi_end;
    status='failed' carries reason."""

    __slots__ = ("status", "cfi_start", "cfi_end", "reason")

    def __init__(self, status, cfi_start=None, cfi_end=None, reason=None):
        self.status = status
        self.cfi_start = cfi_start
        self.cfi_end = cfi_end
        self.reason = reason

    def __repr__(self):
        if self.status == "failed":
            return f"ConversionResult(failed, reason={self.reason!r})"
        return f"ConversionResult({self.status}, cfi_start={self.cfi_start!r}, cfi_end={self.cfi_end!r})"


def parse_chapter_document(xhtml: str) -> ChapterDocument:
    root = parse_html_document(xhtml)
    return ChapterDocument(root=root, index=ChapterTextIndex(root))


class _StructuralAnchor:
    __slots__ = ("cp", "resolved")

    def __init__(self, cp, resolved):
        self.cp = cp
        self.resolved = resolved


def _xpointer_anchor(doc: ChapterDocument, pos: str, exclusive_end: bool):
    parsed = parse_xpointer(pos)
    if not parsed:
        return None
    element = resolve_xpointer_element(doc.root, parsed.steps)
    if element is None:
        return None

    direct_runs = doc.index.runs_of_parent(element)
    run = (direct_runs[parsed.text_index - 1] if parsed.text_index is not None and 0 <= parsed.text_index - 1 < len(direct_runs) else None)
    if run is None:
        run = doc.index.first_run_within(element)
    if run is None:
        return None

    if parsed.offset is None:
        cp = run.collapsed_start + run.collapsed_length if exclusive_end else run.collapsed_start
        return _StructuralAnchor(cp, False)

    within_range = parsed.offset <= run.collapsed_length
    return _StructuralAnchor(doc.index.collapsed_for_run_offset(run, parsed.offset), within_range)


def xpointer_range_to_cfi(doc: ChapterDocument, chapter_index: int, pos0: str, pos1, text) -> ConversionResult:
    """
    Converts a KOReader xpointer range to a CFI range. Mirrors BookOrbit's
    own xpointerRangeToCfi exactly (see position-converter.core.ts) — same
    structural-anchor + text-verification/repair logic, same failure
    reasons, just returning cfi_start/cfi_end instead of a single "pos0"
    range-CFI string (Kolibre's Highlight model already has two separate
    columns for this, unlike BookOrbit's single-field pos0).
    """
    p0 = parse_xpointer(pos0)
    if not p0:
        return ConversionResult("failed", reason="unparsable_pos0")
    if p0.doc_fragment_index != chapter_index + 1:
        return ConversionResult("failed", reason="fragment_mismatch")
    p1 = parse_xpointer(pos1) if pos1 else None
    if pos1 and not p1:
        return ConversionResult("failed", reason="unparsable_pos1")
    if p1 and p1.doc_fragment_index != p0.doc_fragment_index:
        return ConversionResult("failed", reason="cross_fragment_range")

    anchor0 = _xpointer_anchor(doc, pos0, False)
    anchor1 = _xpointer_anchor(doc, pos1, True) if pos1 else None

    normalized_text = normalize_for_search(text) if text else ""
    if normalized_text:
        truncated = len(text) >= _TRUNCATED_TEXT_THRESHOLD
        match = doc.index.search_normalized(normalized_text, anchor0.cp if anchor0 else None)
        if match:
            start_cp = match.start_cp
            end_cp = anchor1.cp if (truncated and anchor1) else match.end_cp
            start_agrees = (
                anchor0 is not None
                and anchor0.resolved
                and abs(match.start_cp - anchor0.cp) <= _EXACT_HINT_TOLERANCE_CP
            )
            status = "exact" if (start_agrees and (not truncated or (anchor1.resolved if anchor1 else False))) else "repaired"
        elif anchor0 and anchor1:
            start_cp = anchor0.cp
            end_cp = anchor1.cp
            extracted = doc.index.extract_collapsed(start_cp, end_cp)
            if normalize_for_search(extracted) != normalized_text:
                return ConversionResult("failed", reason="text_mismatch")
            status = "exact"
        else:
            return ConversionResult("failed", reason="text_not_found")
    else:
        if not anchor0 or not anchor1:
            return ConversionResult("failed", reason="unresolvable_structure")
        start_cp = anchor0.cp
        end_cp = anchor1.cp
        status = "exact" if (anchor0.resolved and anchor1.resolved) else "repaired"

    if start_cp is None or end_cp is None or end_cp <= start_cp:
        return ConversionResult("failed", reason="empty_range")

    cfi_start, cfi_end = _collapsed_range_to_cfi_pair(doc, chapter_index, start_cp, end_cp)
    if not cfi_start:
        return ConversionResult("failed", reason="cfi_generation_failed")
    return ConversionResult(status, cfi_start=cfi_start, cfi_end=cfi_end)


def _collapsed_range_to_cfi_pair(doc: ChapterDocument, chapter_index: int, start_cp: int, end_cp: int):
    """
    Builds two standalone point CFIs (start, end) from a collapsed cp
    range. Kolibre's Highlight model stores cfi_start/cfi_end as two
    separate point addresses (matching what the web reader's own
    highlight-creation path already stores), unlike BookOrbit's single
    combined range-CFI pos0 field — so both points are built directly
    here rather than through cfi_from_range_points' combined encoding.
    """
    start_point = doc.index.start_point_from_collapsed(start_cp)
    end_point = doc.index.end_point_from_collapsed(end_cp)
    if not start_point or not end_point:
        return None, None
    try:
        spine_prefix = spine_cfi_for_chapter_index(chapter_index)
        cfi_start = join_cfi_indirection(spine_prefix, cfi_from_point(RangePoint(start_point.node, start_point.offset)))
        cfi_end = join_cfi_indirection(spine_prefix, cfi_from_point(RangePoint(end_point.node, end_point.offset)))
        return cfi_start, cfi_end
    except Exception:
        return None, None


# ─────────────────────────────────────────────────────────────────────────
# Ripiego: cercare il testo in TUTTO il libro
# ─────────────────────────────────────────────────────────────────────────

# Sotto questa lunghezza non si cerca nemmeno.
#
# Era 25, ed era troppo: la garanzia contro l'aggancio sbagliato non e' la
# lunghezza, e' l'UNICITA' — una frase accettata solo se compare una volta
# sola nel libro e' sicura che sia lunga venti caratteri o duecento. La
# soglia era una seconda cintura che costava recuperi veri: su dati reali
# teneva fuori due note da 23 caratteri — un titolo citato dentro il testo e
# una cifra con la sua unita' di misura — che nel libro ci sono e che
# l'unicita' avrebbe accettato senza rischio.
#
# Resta un pavimento basso perche' sotto le due parole la ricerca e'
# comunque inutile — "pivot" (5 caratteri) in un libro compare ovunque,
# fallirebbe l'unicita' e avrebbe solo fatto scorrere tutti i capitoli per
# niente.
LUNGHEZZA_MINIMA_PER_CERCARE = 12


def trova_testo_nel_libro(capitoli, testo: str):
    """Cerca il testo di una nota in ogni capitolo, e lo accetta solo se lo
    trova UNA volta sola in tutto il libro.

    Esiste perche' la conversione normale e' tutta subordinata all'xpointer:
    se quello manca, non si sa leggere, o punta a un capitolo che in questo
    file non esiste, si falliva senza aver mai guardato il testo — anche
    quando il testo stava li', intero, a due capitoli di distanza. E' il caso
    da cui nasce questa funzione: il testo di una nota — una frase che in quel
    libro c'e', parola per parola — non veniva cercato da nessuno.

    L'unicita' non e' prudenza eccessiva, e' la differenza fra ritrovare e
    indovinare: una frase che compare in due capitoli non dice a quale delle
    due occorrenze si riferisse la nota, e sceglierne una a caso produce una
    posizione sbagliata che sembra giusta. Meglio nessuna posizione.

    `capitoli` e' una sequenza di (indice, ChapterDocument): il chiamante
    decide quanti caricarne e in che ordine, perche' e' lui a sapere quanto
    puo' permettersi di leggere.

    Torna (indice_capitolo, ConversionResult) oppure (None, motivo).
    """
    normalizzato = normalize_for_search(testo) if testo else ""
    if not normalizzato or len(normalizzato) < LUNGHEZZA_MINIMA_PER_CERCARE:
        return None, "testo_troppo_corto"

    trovati = []
    for indice, doc in capitoli:
        match = doc.index.search_normalized(normalizzato, None)
        if match:
            trovati.append((indice, doc, match))
            # Due bastano a rendere ambiguo: non serve leggere il resto.
            if len(trovati) > 1:
                return None, "testo_ambiguo"

    if not trovati:
        return None, "testo_non_nel_libro"

    indice, doc, match = trovati[0]
    cfi_start, cfi_end = _collapsed_range_to_cfi_pair(doc, indice, match.start_cp, match.end_cp)
    if not cfi_start:
        return None, "cfi_generation_failed"
    # Uno stato SUO, distinto da "repaired": quello significa "la struttura
    # non tornava e il testo ha corretto il tiro, dentro il capitolo giusto";
    # questo significa "del punto originale non si e' salvato niente, la nota
    # e' stata ritrovata cercandola nel libro". Sono due gradi di fiducia
    # diversi, e tenerli distinti permette di contare quante note sono state
    # recuperate cosi' — che e' la misura di quanto serva questo ripiego.
    return indice, ConversionResult("ritrovata_dal_testo", cfi_start=cfi_start, cfi_end=cfi_end)
