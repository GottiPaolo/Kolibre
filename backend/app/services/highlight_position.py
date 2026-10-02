"""
Lazily resolves a KOReader-sourced highlight's crengine xpointer
(koreader_pos0/koreader_pos1) into a real CFI, so it can be opened at the
right spot in Kolibre's own web reader — see services/position_converter/
for the actual xpointer<->CFI algorithm (ported from BookOrbit).

Deliberately mutates the ORM object in place and never raises: originally
called from the hot GET path (annotations.list_annotations) over a bounded
batch — moved to a periodic background loop instead (see main.py's
_backfill_highlight_positions_loop) once a large never-converted backlog
turned out to mean EVERY single page load re-opening and re-parsing up to
25 EPUBs, forever, until the backlog cleared (the complaint: "non c'è
bisogno di caricarle tutte all'apertura che la sovraccarica"). One book's
missing/corrupt EPUB still must never break the rest of the batch.
"""

from .. import config, models
from ..calibre.library import CalibreLibrary
from .position_converter.core import (LUNGHEZZA_MINIMA_PER_CERCARE, parse_chapter_document,
                                      trova_testo_nel_libro, xpointer_range_to_cfi)
from .position_converter.epub_chapters import get_chapter_xhtml, get_spine_length
from .position_converter.xpointer_utils import parse_xpointer
from ..logging_utils import log_message

# Mirrors BookOrbit's own lazy/bounded batch size for this same conversion —
# an EPUB open + chapter parse is real (if modest) work, so a page load with
# many never-before-seen device highlights shouldn't do it for all of them
# at once.
DEVICE_POSITION_CONVERT_BATCH_LIMIT = 25

# I capitoli gia' analizzati dell'ULTIMO libro toccato.
#
# Il ripiego "cerca il testo in tutto il libro" deve leggere e analizzare
# ogni capitolo dell'EPUB, e in un lotto le note dello stesso libro sono
# tante: senza questo, un libro con quaranta note da ritrovare verrebbe
# analizzato quaranta volte. Una voce sola basta perche' il lotto viene
# ordinato per libro (vedi backfill_pending_device_positions) e le note
# dello stesso libro arrivano quindi una dietro l'altra.
_capitoli_in_cache: dict = {"chiave": None, "capitoli": None}


def _capitoli_del_libro(epub_path: str):
    if _capitoli_in_cache["chiave"] == epub_path:
        return _capitoli_in_cache["capitoli"]
    quanti = get_spine_length(epub_path) or 0
    capitoli = []
    for i in range(quanti):
        testo_capitolo = get_chapter_xhtml(epub_path, i)
        if testo_capitolo:
            capitoli.append((i, parse_chapter_document(testo_capitolo)))
    _capitoli_in_cache["chiave"] = epub_path
    _capitoli_in_cache["capitoli"] = capitoli
    return capitoli


def try_resolve_device_highlight_position(highlight) -> None:
    """
    Attempts the conversion for one models.Highlight row, setting
    cfi_start/cfi_end/position_status directly on it — the caller commits.
    Sets position_status='failed' (never retried automatically, see
    annotations.py's own filter) on any failure: unparsable position,
    missing/unreadable EPUB, or a structural/text mismatch the converter
    itself couldn't resolve or repair.
    """
    # Il libro PRIMA della posizione: una nota il cui libro non c'e' piu' e'
    # vedova comunque, anche se il suo xpointer non si sa leggere. Al
    # contrario finiva marcata 'failed' per via del pos0 e non arrivava mai
    # al controllo che conta — visto succedere provando la migrazione.
    try:
        lib = CalibreLibrary(config.library_path(highlight.library))
        libro = lib.get_book(highlight.calibre_book_id)
    except Exception:
        libro = None
    if not libro:
        # Il libro non e' piu' in libreria: la nota e' VEDOVA, non fallita.
        # Distinguerle conta per due motivi. Uno: "failed" significa "ci ho
        # provato e il libro non si presta", e finiva per nascondere il fatto
        # che il 26% delle note di una biblioteca reale puntava a libri
        # cancellati —
        # sembravano conversioni difettose, erano libri assenti. Due: il
        # rimedio e' diverso, "Ritenta conversioni fallite" qui non servirebbe
        # a niente, mentre ricollegare la nota a un libro vivo si (vedi
        # services/widowed_highlights.py).
        highlight.position_status = "libro_assente"
        return

    try:
        epub_path = lib.get_format_file_path(highlight.calibre_book_id, "EPUB")
    except Exception:
        epub_path = None
    if not epub_path:
        # Non-EPUB formats (PDF/MOBI/...) have no chapter XHTML to resolve
        # a crengine xpointer against — this converter only ever applies
        # to EPUB, same as the web reader itself.
        highlight.position_status = "failed"
        return

    # ── Strada normale: l'xpointer dice il capitolo, il testo fa il resto ──
    result = None
    parsed = parse_xpointer(highlight.koreader_pos0)
    if parsed:
        chapter_index = parsed.doc_fragment_index - 1
        xhtml = get_chapter_xhtml(epub_path, chapter_index)
        if xhtml:
            doc = parse_chapter_document(xhtml)
            esito = xpointer_range_to_cfi(
                doc, chapter_index, highlight.koreader_pos0, highlight.koreader_pos1, highlight.text
            )
            if esito.status != "failed":
                result = esito

    # ── Ripiego: cercare il testo in TUTTO il libro ───────────────────────
    #
    # Prima non esisteva, e qui si falliva. Tutta la conversione era
    # subordinata all'xpointer: se non si sapeva leggere, o puntava a un
    # capitolo che in QUESTO file non esiste — un EPUB reimportato, una
    # versione diversa dello stesso libro — si marcava "failed" senza aver
    # mai guardato il testo. Anche quando il testo stava li', intero, due
    # capitoli piu' in la'.
    #
    # Riscontrato in uso, con un esempio che lo dice meglio di qualunque
    # spiegazione: il testo di una nota — una frase che in quel libro c'e',
    # parola per parola — non veniva cercato da nessuno.
    #
    # Si accetta solo se la frase compare UNA volta sola in tutto il libro:
    # e' la differenza fra ritrovare e indovinare (vedi
    # trova_testo_nel_libro).
    if result is None and highlight.text and len(highlight.text.strip()) >= LUNGHEZZA_MINIMA_PER_CERCARE:
        _, ritrovato = trova_testo_nel_libro(_capitoli_del_libro(epub_path), highlight.text)
        if isinstance(ritrovato, str):
            # Motivo testuale: non trovato, ambiguo, troppo corto.
            highlight.position_status = "failed"
            return
        result = ritrovato

    if result is None or result.status == "failed":
        highlight.position_status = "failed"
        return

    highlight.cfi_start = result.cfi_start
    highlight.cfi_end = result.cfi_end
    highlight.position_status = result.status


def backfill_pending_device_positions(db, limit: int = DEVICE_POSITION_CONVERT_BATCH_LIMIT) -> int:
    """
    Background counterpart to the old inline backfill in
    annotations.list_annotations — same selection filter (source='device',
    never attempted), across every user's highlights (not scoped to one
    request), called periodically instead of once per page load. Returns
    how many rows were attempted (not how many succeeded — a 'failed'
    status still counts as attempted and is never retried).
    """
    to_convert = (
        db.query(models.Highlight)
        .filter(
            # Qualunque origine, non solo 'device'.
            #
            # Il filtro era `source == "device"` perche' la conversione
            # nasceva per tradurre gli xpointer di KOReader, che solo i
            # dispositivi mandano. Ma dal 25/09 esiste anche il ripiego sul
            # TESTO, che non ha bisogno di nessun xpointer — e una nota
            # importata da Calibre Desktop senza posizione restava fuori per
            # sempre da un percorso che ormai saprebbe agganciarla.
            #
            # Misurato su un impianto reale: 75 note non erano mai state
            # tentate (71 da Calibre, 4 dal lettore web). Quasi tutte avevano
            # gia' un CFI proprio e quindi non servivano, ma una no — ed era
            # proprio quella segnalata con "riesco facilmente a trovarla
            # nell'ePub".
            models.Highlight.cfi_start.is_(None),
            models.Highlight.position_status.is_(None),
            models.Highlight.deleted_at.is_(None),
        )
        # Ordinato per libro: il ripiego sul testo analizza tutti i capitoli
        # dell'EPUB, e tenendo insieme le note dello stesso libro quel lavoro
        # si fa una volta sola per libro invece che una volta per nota (vedi
        # _capitoli_del_libro).
        .order_by(models.Highlight.library, models.Highlight.calibre_book_id)
        .limit(limit)
        .all()
    )
    for h in to_convert:
        try:
            try_resolve_device_highlight_position(h)
        except Exception as exc:
            # Una nota per volta, e nessuna puo' fermare le altre: il
            # docstring del modulo lo promette («One book's missing/corrupt
            # EPUB still must never break the rest of the batch») ma il try
            # copriva solo l'apertura della biblioteca, non la conversione.
            #
            # E il danno non era di una volta: la selezione e' deterministica
            # (cfi_start IS NULL AND position_status IS NULL, ordinata, limite
            # 25), quindi lo STESSO lotto veniva ripreso ogni cinque minuti,
            # moriva allo stesso punto, e la conversione non avanzava mai
            # piu'. Un capitolo con duemila div annidati basta: RecursionError.
            #
            # 'failed' e' lo stato giusto: il progetto non lo ritenta da solo,
            # ed esiste «Ritenta conversioni fallite» per quando l'EPUB viene
            # sistemato.
            h.position_status = "failed"
            log_message(
                "warning", "highlights",
                f"Conversione posizione fallita per la nota {h.id} "
                f"({h.library}:{h.calibre_book_id}): {type(exc).__name__}: {exc}",
            )
    if to_convert:
        db.commit()
    return len(to_convert)
