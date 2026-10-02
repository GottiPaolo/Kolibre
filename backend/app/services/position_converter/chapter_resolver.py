"""
Resolves a highlight's full chapter ancestry ("Parte ▸ Capitolo") server-side,
so the KOReader plugin no longer needs to read/walk a book's TOC on-device at
all (see plugins/koreader/kolibre.koplugin/main.lua's now-removed
_resolveFullChapterPath — moved here per the "heavy work belongs on the
server" guideline).

resolve_epub_chapter_path mirrors frontend/src/ReaderView.vue's
chapterPathForCfi (exact spine-href match, falling back to the closest
preceding TOC entry in spine order) so a highlight created in the web reader
and one pushed from KOReader resolve to the identical chapter-path
convention. resolve_pdf_chapter_path mirrors the page-based variant
_resolveFullChapterPath used to do on-device (nearest-preceding-page,
running per-level title table), just walking toc_editor.get_pdf_toc instead
of KOReader's own cached toc setting.
"""

import os
import threading
import zipfile
from collections import OrderedDict
from typing import List, NamedTuple, Optional

from .xpointer_utils import parse_xpointer
from ..toc_editor import _find_opf_path, _find_ncx_path, _find_spine_hrefs, get_epub_toc, get_pdf_toc


def _strip_fragment(href: str) -> str:
    return (href or "").split("#")[0]


class _StrutturaEpub(NamedTuple):
    """Spine, cartella dell'NCX e indice, cioe' tutto quello che serve per
    risolvere un capitolo e che non dipende dalla singola nota."""
    hrefs: List[str]
    ncx_dir: str
    entries: List[dict]


# L'invio di annotazioni da KOReader manda tutte le note di un libro insieme —
# 246 in un caso reale — e ognuna faceva riaprire e
# rianalizzare lo stesso EPUB DUE volte (una qui, una dentro get_epub_toc):
# misurati 13 ms e 2 aperture dello zip per nota, cioe' 2,1 s per quel libro
# passati interamente a rileggere lo stesso file.
#
# La chiave comprende dimensione e data del file, non solo il percorso: se il
# server riscrive un EPUB (incorporazione metadati, copertina, conteggio
# pagine) la voce in cache smette da sola di corrispondere, invece di
# continuare a rispondere con lo spine di una versione che non esiste piu'.
# Poche voci bastano: il caso che conta e' "tante note dello stesso libro di
# fila", non "tanti libri diversi".
_CACHE_MAX = 8
_cache: "OrderedDict[tuple, Optional[_StrutturaEpub]]" = OrderedDict()
_cache_lock = threading.Lock()


def _struttura_epub(epub_path: str) -> Optional[_StrutturaEpub]:
    try:
        st = os.stat(epub_path)
        chiave = (epub_path, st.st_size, st.st_mtime_ns)
    except OSError:
        return None

    with _cache_lock:
        if chiave in _cache:
            _cache.move_to_end(chiave)
            return _cache[chiave]

    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            opf_path = _find_opf_path(z)
            hrefs = _find_spine_hrefs(z, opf_path)
            ncx_path = _find_ncx_path(z, opf_path)
            ncx_dir = os.path.dirname(ncx_path) if ncx_path else os.path.dirname(opf_path)
        toc = get_epub_toc(epub_path)
        struttura = _StrutturaEpub(hrefs, ncx_dir, _toc_entries_with_paths(toc)) if toc else None
    except Exception:
        struttura = None

    with _cache_lock:
        _cache[chiave] = struttura
        _cache.move_to_end(chiave)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return struttura


def _toc_entries_with_paths(entries: List[dict]) -> List[dict]:
    """
    toc_editor's TOC readers return a flat [{title, dest, level}] list, not a
    tree — same shape _resolveFullChapterPath's on-device equivalent worked
    from. Rebuilds each entry's own full ancestor path by walking in order
    and keeping a running "last title seen at each level" table, dropping
    deeper levels whenever a shallower one reappears (identical trick to the
    now-removed Lua version, and to how frontend's flattenToc turns nested
    subitems into an ancestor-path list — this just does it from a flat
    level-tagged source instead of real nesting).
    """
    title_by_level = {}
    out = []
    for entry in entries:
        title = (entry.get("title") or "").strip()
        level = entry.get("level") or 0
        if not title:
            out.append({**entry, "path": None})
            continue
        title_by_level[level] = title
        for lvl in list(title_by_level.keys()):
            if lvl > level:
                del title_by_level[lvl]
        path = " ▸ ".join(title_by_level[lvl] for lvl in sorted(title_by_level))
        out.append({**entry, "path": path})
    return out


def resolve_epub_chapter_path(epub_path: str, pos0: str) -> Optional[str]:
    parsed = parse_xpointer(pos0)
    if not parsed:
        return None
    chapter_index = parsed.doc_fragment_index - 1

    struttura = _struttura_epub(epub_path)
    if not struttura:
        return None
    hrefs, ncx_dir, entries = struttura
    if chapter_index < 0 or chapter_index >= len(hrefs):
        return None
    target_href = hrefs[chapter_index]

    # Each TOC entry's own spine index, resolved to the same zip-root-relative
    # base _find_spine_hrefs uses (TOC dest is stored relative to the NCX's
    # own directory, which isn't always the OPF's — see
    # toc_editor.list_epub_destinations' docstring on exactly this mismatch).
    href_to_index = {href: idx for idx, href in enumerate(hrefs)}

    def resolved_href(entry) -> Optional[str]:
        file_part = _strip_fragment(entry.get("dest"))
        if not file_part:
            return None
        return os.path.normpath(os.path.join(ncx_dir, file_part)).replace(os.sep, "/") if ncx_dir else file_part

    match = None
    for entry in entries:
        if entry["path"] and resolved_href(entry) == target_href:
            match = entry
            break

    if not match:
        # No TOC entry for this exact spine document (common: many EPUBs only
        # TOC their top-level chapter files, not every finer subsection) —
        # fall back to the closest TOC entry at or before this section in
        # spine order, same as chapterPathForCfi does client-side.
        best_index = -1
        for entry in entries:
            if not entry["path"]:
                continue
            href = resolved_href(entry)
            idx = href_to_index.get(href) if href else None
            if idx is not None and idx <= chapter_index and idx > best_index:
                match = entry
                best_index = idx

    return match["path"] if match else None


def resolve_pdf_chapter_path(pdf_path: str, page: int) -> Optional[str]:
    if not page:
        return None
    toc = get_pdf_toc(pdf_path)
    if not toc:
        return None

    dated = []
    for entry in toc:
        try:
            entry_page = int(entry.get("dest"))
        except (TypeError, ValueError):
            continue
        if entry.get("title"):
            dated.append({**entry, "_page": entry_page})
    dated.sort(key=lambda e: e["_page"])

    entries = _toc_entries_with_paths(dated)
    match = None
    for entry in entries:
        if entry["_page"] > page:
            break
        if entry["path"]:
            match = entry
    return match["path"] if match else None
