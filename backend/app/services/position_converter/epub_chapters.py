"""
Reads one spine chapter's raw XHTML straight out of a real EPUB file on
disk, for the xpointer->CFI converter. Reuses the TOC editor's own OPF/
spine parsing (services/toc_editor.py) rather than re-parsing the EPUB
package format from scratch — same reasoning as reusing CalibreLibrary
everywhere else in this backend instead of hand-rolling metadata.db access.

Deliberately reads the zip directly by the spine's own (OPF-relative)
paths instead of going through toc_editor.get_epub_file_content(), which
resolves hrefs against the NCX's directory instead — a different base
that only matches by coincidence when the NCX and OPF happen to share a
directory (see toc_editor.list_epub_destinations' own docstring on this).
"""

import zipfile
from typing import Optional

from ..toc_editor import _find_opf_path, _find_spine_hrefs


def get_chapter_xhtml(epub_path: str, chapter_index: int) -> Optional[str]:
    """
    chapter_index is 0-based, matching koreader_pos0's DocFragment[N] where
    N = chapter_index + 1. Returns None if the EPUB, its spine, or that
    particular chapter index doesn't exist — callers should treat this the
    same as a 'failed' conversion, never raise.
    """
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            opf_path = _find_opf_path(z)
            hrefs = _find_spine_hrefs(z, opf_path)
            if chapter_index < 0 or chapter_index >= len(hrefs):
                return None
            return z.read(hrefs[chapter_index]).decode("utf-8", errors="ignore")
    except Exception:
        return None


def get_spine_length(epub_path: str) -> Optional[int]:
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            opf_path = _find_opf_path(z)
            return len(_find_spine_hrefs(z, opf_path))
    except Exception:
        return None
