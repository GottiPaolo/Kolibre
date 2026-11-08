"""
Content-level book identity, independent of filename, folder, container
metadata, or exact byte layout — the generalized fix for what BookHash's
existing `partial_md5` (koreader_hash.py) can't do: that hash samples 12
fixed byte offsets of the raw file, so it only matches a device file that is
BYTE-IDENTICAL to the server's copy. Any independently-produced copy of the
same book (a different EPUB export, rewritten OPF metadata, different zip
compression) has different bytes at those offsets despite being textually
the same book, which is exactly the gap this module closes.

The fingerprint is deliberately a WINDOW of normalized text, not a hash of
the whole book: hashing everything would just move the same fragility up a
layer (a different translator's-note page, a missing final chapter in an
OCR scan, extra front matter would all break an exact whole-text hash too).
Skipping a short prefix (cover/title page, which varies by edition) and
hashing a few thousand characters right after it is the practical middle
ground between "enough content to be unique" and "close enough to the start
to survive most real-world editorial differences near the end of a book".
"""

import hashlib
import os
import re
import unicodedata
from typing import Optional

from .page_counter import _extract_epub_text

SUPPORTED_FINGERPRINT_FORMATS = {"epub", "fb2", "txt"}

# Skip past the cover/title page (varies by edition/converter), then hash a
# window wide enough to be practically unique across a personal library
# without reaching so far into the book that translator's notes, missing
# chapters, or other real editorial differences near the end start to matter.
_SKIP_CHARS = 200
_WINDOW_CHARS = 4000
_MIN_TEXT_CHARS = _SKIP_CHARS + 500  # below this, there's not enough body text to fingerprint reliably

_FB2_BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _fold_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", _fold_accents(text)).strip()


def _extract_fb2_text(fb2_path: str) -> Optional[str]:
    try:
        with open(fb2_path, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    except OSError:
        return None
    match = _FB2_BODY_RE.search(raw)
    body = match.group(1) if match else raw
    return _TAG_RE.sub(" ", body)


def _extract_txt_text(txt_path: str) -> Optional[str]:
    try:
        with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def compute_fingerprint(file_path: str, fmt: str) -> Optional[str]:
    """
    Returns a SHA256 hex digest identifying this book's content, or None if
    the format isn't supported (pdf/mobi/azw3 — no cheap text extraction
    without a real binary-format parser, an explicit and disclosed
    limitation) or there wasn't enough extractable text to fingerprint
    reliably. Never raises — any extraction failure (corrupt file, malformed
    zip/XML) is treated the same as "can't fingerprint this one", mirroring
    partial_md5's own None-on-failure contract.
    """
    fmt = (fmt or "").lower()
    if fmt not in SUPPORTED_FINGERPRINT_FORMATS or not os.path.exists(file_path):
        return None

    try:
        if fmt == "epub":
            raw_text = _extract_epub_text(file_path)
        elif fmt == "fb2":
            raw_text = _extract_fb2_text(file_path)
        else:
            raw_text = _extract_txt_text(file_path)
    except Exception:
        return None

    if not raw_text:
        return None

    normalized = _normalize(raw_text)
    if len(normalized) < _MIN_TEXT_CHARS:
        return None

    window = normalized[_SKIP_CHARS:_SKIP_CHARS + _WINDOW_CHARS]
    return hashlib.sha256(window.encode("utf-8")).hexdigest()
