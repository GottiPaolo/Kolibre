"""
On-demand dictionary lookup for Vocabulary Builder entries (see
VocabularyEntry's own docstring in models.py for why this is never
auto-populated on device import).

Two tiers, tried in order:
1. A real, installed, offline StarDict dictionary (stardict_service.py) —
   an actual definition in the word's own language, same format/experience
   KOReader itself offers. Not installed by default (Impostazioni →
   Integrazioni → Dizionari, an explicit user action).
2. Online en.wiktionary.org REST "page/definition" fallback, same
   retry/best-effort shape as author_scraper.py — confirmed live that
   it.wiktionary.org does NOT implement this endpoint (it 501s), while
   en.wiktionary.org documents entries for a word across many languages
   (including Italian) in one response, keyed by language code. This means
   a lookup for an Italian word this way comes back GLOSSED IN ENGLISH
   (English Wiktionary explains foreign words in English, not in that
   word's own language) — the whole reason tier 1 exists.

`definition_source` always records exactly where the answer came from, so
the frontend never presents an online English gloss as if it were the local
Italian dictionary.
"""

import re
import time
from typing import Optional

import httpx

from . import stardict_service

# Local dictionary tried first, when installed — see stardict_service's own
# KNOWN_DICTIONARIES. Only Italian exists today; this stays a single
# constant rather than per-word language detection (nothing in
# VocabularyEntry records the word's language — see models.py) because the
# libraries this runs on are overwhelmingly Italian.
_LOCAL_LOOKUP_LANG = "it"

WIKTIONARY_DEFINITION_URL = "https://en.wiktionary.org/api/rest_v1/page/definition/{word}"

# Same reasoning as author_scraper.py's own constants: a burst of manual
# "Cerca definizione" clicks (or a future bulk action) can trip transient
# rate limiting on a handful of requests without the underlying word being
# genuinely missing.
_RETRYABLE_STATUSES = {429, 502, 503, 504}
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 1.0

# Checked in this order when the response documents the word in more than
# one language section — Italian first (those libraries are mostly Italian),
# English as the universal fallback, then whatever else is present.
_PREFERRED_LANGUAGE_KEYS = ("it", "en")

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
# <style>/<script> go BEFORE tag stripping, element and content together:
# removing only the tags would leave the CSS rules themselves behind as if
# they were part of the definition. Wiktionary really does inline a
# TemplateStyles <style> block inside some definitions (e.g. "concomitant"
# ships ".mw-parser-output .defdate{font-size:smaller}"), which used to be
# stored and shown verbatim after the gloss.
_DROP_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)


def _strip_html(html: str) -> str:
    """Wiktionary's REST definitions are short HTML fragments (mostly
    <a>/<span> wiki-links and usage labels) — plain text is all this feature
    needs, and stripping tags avoids either rendering raw HTML unescaped in
    the frontend or pulling in a full HTML sanitizer for a few links."""
    text = _TAG_RE.sub("", _DROP_RE.sub(" ", html))
    return _WHITESPACE_RE.sub(" ", text).strip()


def _fetch(word: str) -> Optional[dict]:
    url = WIKTIONARY_DEFINITION_URL.format(word=word)
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = httpx.get(url, timeout=8, headers={"User-Agent": "Kolibre/1.0"}, follow_redirects=True)
        except httpx.HTTPError:
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_DELAY_SECONDS * attempt)
                continue
            return None
        if resp.status_code == 404:
            return None  # no such page, not worth retrying
        if resp.status_code != 200:
            if resp.status_code in _RETRYABLE_STATUSES and attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_DELAY_SECONDS * attempt)
                continue
            return None
        break
    try:
        data = resp.json()
        return data if isinstance(data, dict) else None
    except (httpx.HTTPError, ValueError):
        return None


def fetch_definition(word: str) -> Optional[dict]:
    """
    Best-effort single-word lookup. Returns None if nothing was found at all
    anywhere (not in the local dictionary, not on Wiktionary, or a network/
    transient failure that exhausted retries) — callers must treat None as
    "try again later or give up", not as a permanent "no definition exists".

    On success: {"definition": str, "source": str} — `source` names either
    the local dictionary's display name or the online language section that
    answered (e.g. "en.wiktionary.org (it)").
    """
    local = stardict_service.lookup_word(_LOCAL_LOOKUP_LANG, word)
    if local:
        return local

    data = _fetch(word)
    if not data:
        return None

    lang_keys = list(data.keys())
    ordered_keys = [k for k in _PREFERRED_LANGUAGE_KEYS if k in lang_keys]
    ordered_keys += [k for k in lang_keys if k not in ordered_keys]

    for lang in ordered_keys:
        for entry in data.get(lang) or []:
            for defn in entry.get("definitions") or []:
                text = _strip_html(defn.get("definition") or "")
                if text:
                    return {"definition": text, "source": f"en.wiktionary.org ({lang})"}
    return None
