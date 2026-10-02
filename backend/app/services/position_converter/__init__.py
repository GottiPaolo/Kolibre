"""
Converts a KOReader highlight's crengine xpointer position
(koreader_pos0/koreader_pos1) into a real EPUB CFI Kolibre's own epub.js
web reader can jump to — the same problem BookOrbit's server solves (see
core.py's own docstring for the full rationale and porting notes).

Public entry point: convert_device_highlight_position(). Everything else
in this package is an internal building block ported 1:1 from BookOrbit's
TypeScript (xpointer_utils/cfi_utils/chapter_text_index/core), forward
(xpointer -> CFI) direction only.
"""

from .core import (CONVERTER_VERSION, ChapterDocument, ConversionResult,
                   parse_chapter_document, trova_testo_nel_libro, xpointer_range_to_cfi)

__all__ = [
    "CONVERTER_VERSION",
    "ChapterDocument",
    "ConversionResult",
    "parse_chapter_document",
    "trova_testo_nel_libro",
    "xpointer_range_to_cfi",
    "convert_device_highlight_position",
]


def convert_device_highlight_position(chapter_xhtml: str, chapter_index: int, pos0: str, pos1, text) -> ConversionResult:
    """
    One-shot convenience wrapper: parses the chapter document fresh and
    runs the conversion. Callers converting several highlights from the
    SAME chapter should call parse_chapter_document() once and reuse it
    with xpointer_range_to_cfi() directly instead — parsing is the
    expensive part.
    """
    doc = parse_chapter_document(chapter_xhtml)
    return xpointer_range_to_cfi(doc, chapter_index, pos0, pos1, text)
