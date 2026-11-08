"""SQLite functions/aggregates required by Calibre's ``metadata.db`` schema.

Calibre's real on-disk schema (see ``schema.sql`` in this same package, copied
verbatim from ``calibre/resources/metadata_sqlite.sql``) contains triggers and
views that call SQL functions which are *not* built into SQLite. Calibre
registers Python implementations of these on every connection it opens
(``calibre.library.sqlite.do_connect``). If we open the schema with plain
``sqlite3`` without registering equivalents, statements such as
``INSERT INTO books ...`` fail with ``sqlite3.OperationalError: no such
function: title_sort``.

This module ports Calibre's actual registered implementations (not
reimplementations from memory) so that a database written by this backend
round-trips correctly and can be opened by Calibre Desktop itself.

Functions/aggregates referenced by ``schema.sql`` (grep for their names there)
and where Calibre registers each one:

- ``title_sort(title)``          -> calibre/library/sqlite.py:266
- ``author_to_author_sort(x)``   -> calibre/library/sqlite.py:267-268 (not
                                     called by any trigger/view in schema.sql,
                                     but registered by Calibre under this name
                                     on every connection; included here for
                                     completeness/parity and because our own
                                     backend code needs it to compute
                                     ``author_sort`` values).
- ``uuid4()``                    -> calibre/library/sqlite.py:269
- ``books_list_filter(book_id)`` -> calibre/library/sqlite.py:270-271 (dummy,
                                     referenced by the ``tag_browser_filtered_*``
                                     views in schema.sql)
- ``sortconcat(ndx, value)``     -> calibre/library/sqlite.py:256 (aggregate),
                                     class body at sqlite.py:127-146; used by
                                     the ``meta`` view in schema.sql.
- ``concat(value)``              -> calibre/library/sqlite.py:262 (aggregate),
                                     class body at sqlite.py:105-124; used by
                                     the ``meta`` view in schema.sql (tags,
                                     formats).

The core string algorithms (``title_sort``'s article-moving logic and
``author_to_author_sort``'s name-token reordering) are ported from
``calibre/ebooks/metadata/__init__.py`` (functions ``title_sort`` at line 203
and ``author_to_author_sort`` at line 69), which is what
``calibre/library/sqlite.py`` imports and registers under those names.

All paths above are relative to Calibre's own source tree
(``src/calibre/...`` in the calibre repository).
"""

# Derivato da Calibre (https://calibre-ebook.com), Copyright (C) Kovid Goyal,
# GNU General Public License v3. I punti esatti da cui vengono le singole
# funzioni sono citati nei commenti qui sotto, con file e numero di riga.
#
# È la ragione per cui Kolibre nel suo insieme è AGPL-3.0: vedi NOTICE.
#
# Non sono un'imitazione né una ricostruzione a memoria, e non possono
# diventarlo: il loro criterio di correttezza è produrre lo STESSO identico
# risultato di Calibre, perché da quel risultato dipendono l'ordinamento e i
# nomi delle cartelle sul disco. Una biblioteca Kolibre deve potersi aprire in
# Calibre Desktop senza conversioni.

from __future__ import annotations

import re
import sqlite3
import unicodedata
import uuid
from collections import Counter

# ---------------------------------------------------------------------------
# title_sort
#
# Ported from calibre/ebooks/metadata/__init__.py:146-228
# (get_title_sort_pat + title_sort), which is what
# calibre/library/sqlite.py:266 registers as the SQL function "title_sort".
# ---------------------------------------------------------------------------

# Ported verbatim from calibre/ebooks/metadata/__init__.py:182-200.
QUOTE_PAIRS: dict[str, tuple[str, ...]] = {
    # https://en.wikipedia.org/wiki/Quotation_mark
    '"': ('"',),
    "'": ("'",),
    '“': ('”', '“'),
    '”': ('”', '”'),
    '„': ('”', '“'),
    '‚': ('’', '‘'),
    '’': ('’', '‘'),
    '‘': ('’', '‘'),
    '‹': ('›',),
    '›': ('‹',),
    '《': ('》',),
    '〈': ('〉',),
    '»': ('«', '»'),
    '«': ('«', '»'),
    '「': ('」',),
    '『': ('』',),
}

# Ported verbatim from calibre's default tweak
# ``per_language_title_sort_articles`` (resources/default_tweaks.py:223-265).
# This is the table of per-language "leading article" regexes that
# title_sort() moves to the end of the sort string.
PER_LANGUAGE_TITLE_SORT_ARTICLES: dict[str, tuple[str, ...]] = {
    # English
    'eng': (r'A\s+', r'The\s+', r'An\s+'),
    # Esperanto
    'epo': (r'La\s+', r"L'", 'L´'),
    # Spanish
    'spa': (r'El\s+', r'La\s+', r'Lo\s+', r'Los\s+', r'Las\s+', r'Un\s+',
            r'Una\s+', r'Unos\s+', r'Unas\s+'),
    # French
    'fra': (r'Le\s+', r'La\s+', r"L'", r'L´', r'L’', r'Les\s+', r'Un\s+', r'Une\s+',
            r'Des\s+', r'De\s+(La\s+)?', r"D'", r'D´', r'D’'),
    # Polish
    'pol': (),
    # Italian
    'ita': (r'Lo\s+', r'Il\s+', r"L'", r'L´', r'La\s+', r'Gli\s+',
            r'I\s+', r'Le\s+', r'Uno\s+', r'Un\s+', r'Una\s+', r"Un'",
            r'Un´', r'Dei\s+', r'Degli\s+', r'Delle\s+', r'Del\s+',
            r'Della\s+', r'Dello\s+', r"Dell'", r'Dell´'),
    # Portuguese
    'por': (r'A\s+', r'O\s+', r'Os\s+', r'As\s+', r'Um\s+', r'Uns\s+',
            r'Uma\s+', r'Umas\s+'),
    # Romanian
    'ron': (r'Un\s+', r'O\s+', r'Nişte\s+'),
    # German
    'deu': (r'Der\s+', r'Die\s+', r'Das\s+', r'Den\s+', r'Ein\s+',
            r'Eine\s+', r'Einen\s+', r'Dem\s+', r'Des\s+', r'Einem\s+',
            r'Eines\s+'),
    # Dutch
    'nld': (r'De\s+', r'Het\s+', r'Een\s+', r"'n\s+", r"'s\s+", r'Ene\s+',
            r'Ener\s+', r'Enes\s+', r'Den\s+', r'Der\s+', r'Des\s+',
            r"'t\s+"),
    # Swedish
    'swe': (r'En\s+', r'Ett\s+', r'Det\s+', r'Den\s+', r'De\s+'),
    # Turkish
    'tur': (r'Bir\s+',),
    # Afrikaans
    'afr': (r"'n\s+", r'Die\s+'),
    # Greek
    'ell': (r'O\s+', r'I\s+', r'To\s+', r'Ta\s+', r'Tus\s+', r'Tis\s+',
            r"'Enas\s+", r"'Mia\s+", r"'Ena\s+", r"'Enan\s+"),
    # Hungarian
    'hun': (r'A\s+', r'Az\s+', r'Egy\s+'),
}

# Calibre picks the active language via the desktop app's UI language
# (tweaks['default_language_for_title_sort'] or get_lang()) — a concept that
# does not exist in this headless server. As a deviation from upstream (not a
# reimplementation of the algorithm itself, just of *which* article table is
# selected when no explicit language is given), we default to the union of
# English and Italian articles, since this fork's library is bilingual.
_DEFAULT_TITLE_SORT_LANGS = ('eng', 'ita')

_title_sort_pat_cache: dict[str | None, re.Pattern[str]] = {}


def get_title_sort_pat(lang: str | None = None) -> re.Pattern[str]:
    """Faithful port of calibre.ebooks.metadata.get_title_sort_pat
    (calibre-master/src/calibre/ebooks/metadata/__init__.py:149-179), with one
    deviation: when ``lang`` is None, Calibre falls back to the desktop app's
    interface language. We fall back to the union of English + Italian
    article lists (see _DEFAULT_TITLE_SORT_LANGS above) since there is no
    "interface language" in a headless server context.
    """
    cached = _title_sort_pat_cache.get(lang)
    if cached is not None:
        return cached

    if lang is not None:
        articles = PER_LANGUAGE_TITLE_SORT_ARTICLES.get(lang)
        if articles is None:
            articles = PER_LANGUAGE_TITLE_SORT_ARTICLES['eng']
    else:
        articles = tuple(
            a
            for code in _DEFAULT_TITLE_SORT_LANGS
            for a in PER_LANGUAGE_TITLE_SORT_ARTICLES.get(code, ())
        )

    if articles:
        joined = '|'.join(articles)
        pat = f'^({joined})'
        try:
            ans = re.compile(pat, re.IGNORECASE)
        except Exception:
            ans = re.compile(r'^(A|The|An)\s+', re.IGNORECASE)
    else:
        ans = re.compile(r'^$')  # matches only the empty string

    _title_sort_pat_cache[lang] = ans
    return ans


def title_sort(title: str, order: str | None = None, lang: str | None = None) -> str:
    """Faithful port of calibre.ebooks.metadata.title_sort
    (calibre-master/src/calibre/ebooks/metadata/__init__.py:203-228).

    Moves a leading article ("The", "A", "An" for English; "Il", "La", "Lo",
    "L'", "I", "Gli", "Le", etc. for Italian — see
    PER_LANGUAGE_TITLE_SORT_ARTICLES) to the end of the title, e.g.
    "The Client" -> "Client, The". Also strips a matching pair of leading and
    trailing quote characters before/after moving the article, exactly as
    Calibre does.

    Registered by Calibre as the 1-argument SQL function ``title_sort`` used
    by the ``books_insert_trg``/``books_update_trg`` triggers and the
    ``tag_browser_series``/``tag_browser_filtered_series`` views in
    schema.sql.
    """
    if order is None:
        order = 'library_order'  # calibre default tweak: title_series_sorting
    title = title.strip()
    if order == 'strictly_alphabetic':
        return title
    if title and title[0] in QUOTE_PAIRS:
        q = title[0]
        title = title[1:]
        if title and title[-1] in QUOTE_PAIRS[q]:
            title = title[:-1]
    match = get_title_sort_pat(lang).search(title)
    if match:
        try:
            prep = match.group(1)
        except IndexError:
            prep = None
        if prep:
            title = title[len(prep):] + ', ' + prep
            if title[0] in QUOTE_PAIRS:
                q = title[0]
                title = title[1:]
                if title and title[-1] in QUOTE_PAIRS[q]:
                    title = title[:-1]
    return title.strip()


# ---------------------------------------------------------------------------
# author_to_author_sort
#
# Core algorithm ported from calibre/ebooks/metadata/__init__.py:46-139
# (remove_bracketed_text + author_to_author_sort). The '|' -> ',' pre-
# processing wrapper is ported from the actual SQL-registered function
# calibre/library/sqlite.py:212-215 (_author_to_author_sort), which is what
# gets bound to the SQL name "author_to_author_sort" at
# calibre/library/sqlite.py:267-268.
# ---------------------------------------------------------------------------

# Defaults ported verbatim from calibre's default tweaks
# (resources/default_tweaks.py:73-84).
AUTHOR_SORT_COPY_METHOD = 'comma'
AUTHOR_NAME_SUFFIXES = ('Jr', 'Sr', 'Inc', 'Ph.D', 'Phd',
                        'MD', 'M.D', 'I', 'II', 'III', 'IV',
                        'Junior', 'Senior')
AUTHOR_NAME_PREFIXES = ('Mr', 'Mrs', 'Ms', 'Dr', 'Prof')
AUTHOR_NAME_COPYWORDS = (
    'Agency', 'Corporation', 'Company', 'Co.', 'Council',
    'Committee', 'Inc.', 'Institute', 'National', 'Society', 'Club', 'Team',
    'Software', 'Games', 'Entertainment', 'Media', 'Studios',
)
AUTHOR_USE_SURNAME_PREFIXES = False
AUTHOR_SURNAME_PREFIXES = ('da', 'de', 'di', 'la', 'le', 'van', 'von')


def _remove_bracketed_text(src: str, brackets: dict[str, str] | None = None) -> str:
    """Ported verbatim from calibre.ebooks.metadata.remove_bracketed_text
    (calibre-master/src/calibre/ebooks/metadata/__init__.py:46-66), minus the
    force_unicode() call on the input (we always deal with str already).
    """
    if brackets is None:
        brackets = {'(': ')', '[': ']', '{': '}'}
    counts: Counter = Counter()
    total = 0
    buf: list[str] = []
    rmap = {v: k for k, v in brackets.items()}
    for char in src:
        if char in brackets:
            counts[char] += 1
            total += 1
        elif char in rmap:
            idx = rmap[char]
            if counts[idx] > 0:
                counts[idx] -= 1
                total -= 1
        elif total < 1:
            buf.append(char)
    return ''.join(buf)


def _author_to_author_sort_core(
    author: str,
    method: str | None = None,
    copywords: tuple[str, ...] | None = None,
    use_surname_prefixes: bool | None = None,
    surname_prefixes: tuple[str, ...] | None = None,
    name_prefixes: tuple[str, ...] | None = None,
    name_suffixes: tuple[str, ...] | None = None,
) -> str:
    """Faithful port of calibre.ebooks.metadata.author_to_author_sort
    (calibre-master/src/calibre/ebooks/metadata/__init__.py:69-139).
    """
    if not author:
        return ''

    if method is None:
        method = AUTHOR_SORT_COPY_METHOD
    if method == 'copy':
        return author

    sauthor = _remove_bracketed_text(author).strip()
    if method == 'comma' and ',' in sauthor:
        return author

    tokens = sauthor.split()
    if len(tokens) < 2:
        return author

    ltoks = frozenset(x.lower() for x in tokens)
    copy_words = frozenset(x.lower() for x in (AUTHOR_NAME_COPYWORDS if copywords is None else copywords))
    if ltoks.intersection(copy_words):
        return author

    author_use_surname_prefixes = AUTHOR_USE_SURNAME_PREFIXES if use_surname_prefixes is None else use_surname_prefixes
    author_surname_prefixes = frozenset(
        x.lower() for x in (AUTHOR_SURNAME_PREFIXES if surname_prefixes is None else surname_prefixes)
    )
    if author_use_surname_prefixes:
        if len(tokens) == 2 and tokens[0].lower() in author_surname_prefixes:
            return author

    prefixes = {y.lower() for y in (AUTHOR_NAME_PREFIXES if name_prefixes is None else name_prefixes)}
    prefixes |= {y + '.' for y in prefixes}

    first = 0
    for first in range(len(tokens)):
        if tokens[first].lower() not in prefixes:
            break
    else:
        return author

    suffixes = {y.lower() for y in (AUTHOR_NAME_SUFFIXES if name_suffixes is None else name_suffixes)}
    suffixes |= {y + '.' for y in suffixes}

    last = len(tokens) - 1
    for last in range(len(tokens) - 1, first - 1, -1):
        if tokens[last].lower() not in suffixes:
            break
    else:
        return author

    suffix = ' '.join(tokens[last + 1:])

    if author_use_surname_prefixes:
        if last > first and tokens[last - 1].lower() in author_surname_prefixes:
            tokens[last - 1] += ' ' + tokens[last]
            last -= 1

    atokens = tokens[last:last + 1] + tokens[first:last]
    num_toks = len(atokens)
    if suffix:
        atokens.append(suffix)

    if method != 'nocomma' and num_toks > 1:
        atokens[0] += ','

    return ' '.join(atokens)


def author_to_author_sort(author: str) -> str:
    """Registered by Calibre as the 1-argument SQL function
    ``author_to_author_sort``.

    This is not called by any trigger/view in schema.sql itself, but Calibre
    registers it on every connection it opens
    (calibre-master/src/calibre/library/sqlite.py:267-268), and our own
    backend code needs the same logic to compute ``author_sort`` values when
    inserting/updating authors (schema.sql has no trigger for author_sort —
    Calibre's application layer computes and writes it explicitly).

    Mirrors the exact wrapper Calibre registers under this SQL name,
    ``_author_to_author_sort`` (calibre-master/src/calibre/library/sqlite.py:212-215),
    which replaces '|' with ',' before delegating to the core algorithm
    (author names are stored with '|' as a separator in some Calibre metadata
    formats).
    """
    if not author:
        return ''
    return _author_to_author_sort_core(author.replace('|', ','))


# ---------------------------------------------------------------------------
# string_to_authors / authors_to_string
#
# Ported from calibre/ebooks/metadata/__init__.py:30-43 — NOT SQL functions,
# but the canonical (and only) place Calibre defines what the '&' separator
# actually means for the multi-valued authors field: '&' separates two
# authors, '&&' escapes a literal ampersand INSIDE one name ("Simon &&
# Schuster" is one author called "Simon & Schuster"), and the default
# authors_split_regex tweak additionally normalizes ", and " / ", with "
# (case-insensitive) to '&' when parsing user input.
# ---------------------------------------------------------------------------

_AUTHORS_SPLIT_PAT = re.compile(r'(?i),?\s+(and|with)\s+')


def string_to_authors(raw: str) -> list:
    """One display/input string -> list of author names, Calibre semantics."""
    if not raw:
        return []
    raw = raw.replace('&&', '\uffff')
    raw = _AUTHORS_SPLIT_PAT.sub('&', raw)
    authors = [a.strip().replace('\uffff', '&') for a in raw.split('&')]
    return [a for a in authors if a]


def authors_to_string(authors: list) -> str:
    """List of author names -> one display string, Calibre semantics."""
    if authors is not None:
        return ' & '.join(a.replace('&', '&&') for a in authors if a)
    return ''


# ---------------------------------------------------------------------------
# uuid4
#
# Ported from calibre/library/sqlite.py:269:
#   conn.create_function('uuid4', 0, lambda: str(uuid.uuid4()))
# ---------------------------------------------------------------------------

def make_uuid4() -> str:
    """Registered as the 0-argument SQL function ``uuid4``, called by the
    ``books_insert_trg`` trigger in schema.sql to populate ``books.uuid`` on
    insert.
    """
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# books_list_filter
#
# Ported from calibre/library/sqlite.py:270-271:
#   conn.create_function('books_list_filter', 1, lambda x: 1)
# ---------------------------------------------------------------------------

def _books_list_filter(book_id: int) -> int:
    """Dummy placeholder Calibre itself registers for ``books_list_filter``
    (calibre-master/src/calibre/library/sqlite.py:270-271). The desktop app
    replaces this with a real per-session DynamicFilter
    (calibre-master/src/calibre/library/sqlite.py:92-102, 306-310) driving the
    ``tag_browser_filtered_*`` views in schema.sql (e.g. "books matching the
    current search"). Outside the desktop app there is no such session
    filter, so — exactly like Calibre's own fallback — this always returns 1
    (no book is filtered out).
    """
    return 1


# ---------------------------------------------------------------------------
# sortconcat (aggregate)
#
# Ported verbatim from calibre/library/sqlite.py:127-146 (SortedConcatenate).
# ---------------------------------------------------------------------------

class SortedConcatenate:
    """Faithful port of calibre.library.sqlite.SortedConcatenate
    (calibre-master/src/calibre/library/sqlite.py:127-146).

    Registered as the 2-argument SQL aggregate ``sortconcat`` (index, value):
    conn.create_aggregate('sortconcat', 2, SortedConcatenate) at
    calibre-master/src/calibre/library/sqlite.py:256. Used by the ``meta``
    view in schema.sql to build the comma-separated, link-order-sorted
    authors list for a book.
    """

    sep = ','

    def __init__(self) -> None:
        self.ans: dict[object, str] = {}

    def step(self, ndx: object, value: str | None) -> None:
        if value is not None:
            self.ans[ndx] = value

    def finalize(self) -> str | None:
        if not self.ans:
            return None
        return self.sep.join(self.ans[k] for k in sorted(self.ans.keys()))


# ---------------------------------------------------------------------------
# concat (aggregate)
#
# Ported verbatim from calibre/library/sqlite.py:105-124 (Concatenate).
# ---------------------------------------------------------------------------

class Concatenate:
    """Faithful port of calibre.library.sqlite.Concatenate
    (calibre-master/src/calibre/library/sqlite.py:105-124).

    Registered as the 1-argument SQL aggregate ``concat``:
    conn.create_aggregate('concat', 1, Concatenate) at
    calibre-master/src/calibre/library/sqlite.py:262. Used by the ``meta``
    view in schema.sql to build comma-separated tag and format lists.
    """

    sep = ','

    def __init__(self) -> None:
        self.ans: list[str] = []

    def step(self, value: str | None) -> None:
        if value is not None:
            self.ans.append(value)

    def finalize(self) -> str | None:
        if not self.ans:
            return None
        return self.sep.join(self.ans)


# ---------------------------------------------------------------------------
# Registration entry point
# ---------------------------------------------------------------------------

def senza_accenti(valore):
    """"Émile Zola" -> "emile zola". None resta None, cosi' un titolo
    mancante non diventa la stringa vuota e non corrisponde a tutto."""
    if valore is None:
        return None
    scomposto = unicodedata.normalize("NFD", str(valore))
    return "".join(c for c in scomposto if not unicodedata.combining(c)).lower()


def register_calibre_functions(conn: sqlite3.Connection) -> None:
    """Register every custom SQL function/aggregate referenced by
    schema.sql's triggers and views onto ``conn``.

    Must be called on every ``sqlite3.Connection`` opened against a
    Calibre-schema ``metadata.db`` before running any INSERT/UPDATE/SELECT
    that touches the affected tables/views — otherwise SQLite raises
    ``no such function: ...`` (schema.sql's triggers fire on every book
    insert/update, and the ``meta``/``tag_browser_*`` views are queried by
    the API layer).

    Mirrors calibre.library.sqlite.do_connect
    (calibre-master/src/calibre/library/sqlite.py:252-274), scoped to the
    functions schema.sql actually references (see grep results cited in this
    module's docstring), plus ``author_to_author_sort`` which Calibre also
    registers unconditionally on every connection.
    """
    conn.create_function('title_sort', 1, title_sort)
    # Non e' di Calibre: serve alla ricerca che ignora gli accenti
    # (list_books_page). Cercando "Emile Zola" si vuole trovare "Émile Zola" —
    # e SQLite da solo non lo sa fare, LIKE ... COLLATE NOCASE tocca solo le
    # maiuscole. Stessa normalizzazione della ricerca lato browser
    # (frontend-react/src/lib/foldAccents.ts) e dell'indice full-text
    # (unicode61 remove_diacritics), cosi' le tre ricerche concordano.
    conn.create_function('kolibre_senza_accenti', 1, senza_accenti)
    conn.create_function('author_to_author_sort', 1, author_to_author_sort)
    conn.create_function('uuid4', 0, make_uuid4)
    conn.create_function('books_list_filter', 1, _books_list_filter)
    conn.create_aggregate('sortconcat', 2, SortedConcatenate)
    conn.create_aggregate('concat', 1, Concatenate)
