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

# Which language a lookup prefers used to be TWO constants pinned to Italian:
# the local dictionary was only ever asked for "it", and the online language
# sections were ordered ("it", "en"). That was right while Kolibre was one
# person's Italian library and wrong the moment it is published: an English
# reader looking up an English word was served the Italian Wiktionary section
# by preference. Corrected on 2026-11-08; the order now starts from the
# account's interface language.
#
# What has NOT changed, because nothing records it: the language of the WORD.
# Nothing in VocabularyEntry says it (see models.py), so this is still a
# preference and not a detection — the account's language is the best guess
# available, not the truth.

WIKTIONARY_DEFINITION_URL = "https://en.wiktionary.org/api/rest_v1/page/definition/{word}"

# Same reasoning as author_scraper.py's own constants: a burst of manual
# "Cerca definizione" clicks (or a future bulk action) can trip transient
# rate limiting on a handful of requests without the underlying word being
# genuinely missing.
_RETRYABLE_STATUSES = {429, 502, 503, 504}
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 1.0

# The tail of the preference order, after the account's own language:
# English as the universal fallback, then Italian (most of the libraries this
# runs on are Italian, and that stays worth something), then whatever else
# the response happens to document.
_LINGUE_DI_RIPIEGO = ("en", "it")


def lingue_preferite(lingua: Optional[str]) -> tuple:
    """
    L'ordine in cui si guardano le lingue: la tua, poi i ripieghi.

    Pubblica (senza underscore) perche' e' la regola che una prova
    interroga: e' una decisione, non un dettaglio di questo file.
    """
    ordine: list = []
    for voce in (lingua,) + _LINGUE_DI_RIPIEGO:
        if isinstance(voce, str) and voce and voce not in ordine:
            ordine.append(voce)
    return tuple(ordine)


def _definizione_locale(word: str, lingua: Optional[str]) -> Optional[dict]:
    """
    Il dizionario installato sul server, nell'ordine che conta.

    Dopo le lingue preferite si prova **qualunque** altro dizionario
    installato: installarne uno e' una scelta esplicita di chi tiene il
    server, e se ce n'e' uno solo deve rispondere comunque — altrimenti
    cambiare lingua all'interfaccia spegnerebbe in silenzio l'unico
    dizionario che c'e'.
    """
    provate = []
    for codice in lingue_preferite(lingua):
        provate.append(codice)
        trovata = stardict_service.lookup_word(codice, word)
        if trovata:
            return trovata
    for codice in stardict_service.KNOWN_DICTIONARIES:
        if codice in provate or not stardict_service.is_installed(codice):
            continue
        trovata = stardict_service.lookup_word(codice, word)
        if trovata:
            return trovata
    return None

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


def fetch_definition(word: str, lingua: Optional[str] = None) -> Optional[dict]:
    """
    Best-effort single-word lookup. Returns None if nothing was found at all
    anywhere (not in the local dictionary, not on Wiktionary, or a network/
    transient failure that exhausted retries) — callers must treat None as
    "try again later or give up", not as a permanent "no definition exists".

    `lingua` is the account's interface language, and only sets the ORDER in
    which languages are tried (see lingue_preferite): nothing here detects
    the language of the word itself. None means "the account never chose",
    and then English comes first, like everywhere else in Kolibre.

    On success: {"definition": str, "source": str} — `source` names either
    the local dictionary's display name or the online language section that
    answered (e.g. "en.wiktionary.org (it)").
    """
    local = _definizione_locale(word, lingua)
    if local:
        return local

    data = _fetch(word)
    if not data:
        return None

    lang_keys = list(data.keys())
    ordered_keys = [k for k in lingue_preferite(lingua) if k in lang_keys]
    ordered_keys += [k for k in lang_keys if k not in ordered_keys]

    for lang in ordered_keys:
        for entry in data.get(lang) or []:
            for defn in entry.get("definitions") or []:
                text = _strip_html(defn.get("definition") or "")
                if text:
                    return {"definition": text, "source": f"en.wiktionary.org ({lang})"}
    return None
