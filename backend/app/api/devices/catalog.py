"""
Il catalogo sfogliato dal dispositivo.

Il mestiere: far cercare e sfogliare al plugin KOReader la biblioteca
Calibre dell'utente — sezioni, scoperta, ricerca con accenti e articoli
piegati — col token di dispositivo. (Trasloco del 20/11/2026: prima era
tutto in api/devices.py.)

Le rotte:
* GET /api/kolibre/devices/catalog — la ricerca/sfoglio vero e proprio;
* GET .../catalog/sections/{section} — le sezioni pronte (novita',
  da leggere, ...), coi conteggi di `_bucket_counts`;
* GET .../catalog/discover — proposte da scoprire.

Chi le chiama: solo il plugin. La regola trasversale e' tutta nella
ricerca "clemente": accenti piegati (`_fold_accents`), punteggiatura
piegata a spazio, articoli rimessi davanti quando il titolo arriva nella
forma title_sort di Calibre (`_reorder_title_sort_article`), e sotto la
soglia di contenimento scatta il fuzzy vero (`_FUZZY_MATCH_THRESHOLD`) —
i commenti accanto alle costanti raccontano i casi reali che hanno
costretto a ciascun pezzo.
"""

import difflib
import random
import re
import unicodedata

from collections import defaultdict

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ... import config, models, database, auth

from ...calibre.library import CalibreLibrary
from ...calibre.connection import PAGE_COUNT_COLUMN_LABEL
from ...schemas_risposte import CatalogoSfogliato, LibriDaScoprire, SezioneDelCatalogo

from ._shared import (
    sync_router,
)


def _fold_accents(s: str) -> str:
    """
    Lowercased, diacritic-stripped form of s — a Kindle/USB-transferred
    filename very often loses accents ("Garcia") while Calibre's own
    metadata keeps them ("García"), so a plain .lower() substring check
    between the two NEVER matches even when the guessed title/author is
    otherwise exactly right. Confirmed as the second half of a real
    fuzzy-match failure (the first half was _guessTitleFromPath's own bug,
    fixed in main.lua) while investigating why an already-catalogued book
    stayed stuck on "no_candidate".
    """
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


# Below this containment threshold real fuzzy matching kicks in — see
# browse_catalog's own docstring for why substring matching alone (AND/OR,
# accent-folded) isn't enough: a subtitle, a differently-guessed word order,
# or stray punctuation in the device-side filename guess can make an
# otherwise obvious match return zero substring hits. Punctuation is folded
# to spaces (not stripped outright) so "Il generale e il giudice: romanzo"
# and "Il generale e il giudice" still overlap almost entirely token-wise.
_FUZZY_MATCH_THRESHOLD = 0.6


_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)


_WHITESPACE_RE = re.compile(r"\s+")


# Calibre's own title_sort() moves a leading article to the end for
# alphabetical sorting ("Il mare" -> "mare, Il") — and on a device where
# the on-disk filename/folder-title comes straight from that sort field
# (confirmed on a real device: an "author" folder_layout writes
# <Author>/<title_sort>.epub, not the display title), the guessed query
# arrives in that reordered form. Left alone, the comma is just folded to a
# space below and "mare il" vs "il mare" scores under threshold even
# though it's an exact match — reordering here undoes Calibre's own
# transform instead of trying to fuzzy-match around it.
_TITLE_SORT_ARTICLES = (
    "the", "a", "an",
    "lo", "gli", "il", "le", "la", "l'", "i",
    "les", "un", "une", "des",
    "el", "los", "las", "unos", "unas", "una",
    "der", "die", "das", "ein", "eine",
)


_TITLE_SORT_SUFFIX_RE = re.compile(
    r"^(?P<title>.+),\s*(?P<article>%s)$" % "|".join(re.escape(a) for a in _TITLE_SORT_ARTICLES),
    re.IGNORECASE,
)


def _reorder_title_sort_article(title: str) -> str:
    match = _TITLE_SORT_SUFFIX_RE.match((title or "").strip())
    if not match:
        return title or ""
    return f"{match.group('article')} {match.group('title')}"


def _normalize_for_fuzzy(s: str) -> str:
    s = _fold_accents(s or "")
    s = _PUNCTUATION_RE.sub(" ", s)
    return _WHITESPACE_RE.sub(" ", s).strip()


def _fuzzy_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _bucket_counts(all_books: list, section: str) -> dict:
    """
    Name -> book count for one section ('authors'/'series'/'tags') over an
    already-fetched list_books() result — see catalog_sections' own
    docstring for why this stays name-keyed (matching browse_catalog's
    existing author/series/tag filters) instead of Calibre's internal
    integer FKs, which list_books() doesn't expose at this layer anyway.
    """
    counts: dict = defaultdict(int)
    if section == "authors":
        for b in all_books:
            author_str = b.get("author") or ""
            for name in author_str.split(" & "):
                name = name.strip()
                if name:
                    counts[name] += 1
    elif section == "series":
        for b in all_books:
            name = (b.get("series") or "").strip()
            if name:
                counts[name] += 1
    else:  # tags
        for b in all_books:
            for name in b.get("tags") or []:
                name = (name or "").strip()
                if name:
                    counts[name] += 1
    return counts


def _only_books_with_files(books: list) -> list:
    """Il catalogo dei dispositivi mostra solo libri che un lettore puo'
    SCARICARE: una scheda fantasma (soli metadati, nessun formato — le
    schede da ISBN del 22/11/2026, l'inventario di una libreria fisica)
    resta fuori, per scelta di Paolo — e' lo stile dell'OPDS 2 di Calibre,
    che filtra i libri senza formati invece di mostrarli non scaricabili."""
    return [b for b in books if b.get("formats")]


@sync_router.get(
    "/catalog/sections/{section}",
    responses={200: {"model": SezioneDelCatalogo}},
)
def catalog_sections(
    section: str,
    library: str,
    page: int = 1,
    size: int = 50,
    q: str = None,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Drill-down "buckets" behind browse_catalog's own author/series/tag
    filters (foundation for the catalog navigator, phase 1 — no UI here yet,
    just the data surface it'll page over): every distinct author/series/tag
    name across the library with how many books carry it, so a future
    "browse by author" screen can list authors first and only then ask
    browse_catalog?author=... for one author's books, instead of pulling the
    whole catalog client-side to build that list itself.

    Pure in-Python group-by over list_books() (already fetched for
    browse_catalog, no new SQL/schema) — deliberately NOT keyed by Calibre's
    internal integer FKs, which list_books() never surfaces at this layer;
    staying name-based matches the existing author/series/tag filters on
    browse_catalog, which already match by name too.

    A multi-author book's `author` field is `"Alice & Bob"` (Calibre's own
    authors_to_string join) — split on `" & "` so each author is counted
    once in their own bucket, never as a separate combined "Alice & Bob"
    bucket. A book contributes to every tag it has (3 tags = +1 to 3
    buckets). `series` uses list_books()'s own singular (already `LIMIT 1`)
    series field, skipping books with none.
    """
    if section not in ("authors", "series", "tags"):
        raise HTTPException(status_code=400, detail="section must be 'authors', 'series' or 'tags'")
    if page < 1 or size < 1:
        raise HTTPException(status_code=400, detail="page and size must be >= 1")

    lib = CalibreLibrary(config.library_path(library))
    all_books = _only_books_with_files(lib.list_books())
    counts = _bucket_counts(all_books, section)

    names = sorted(counts.keys())
    if q:
        needle = _fold_accents(q)
        names = [n for n in names if needle in _fold_accents(n)]

    total = len(names)
    start = (page - 1) * size
    page_names = names[start:start + size]
    return {
        "page": page,
        "size": size,
        "total": total,
        "has_next": (page * size) < total,
        "items": [{"name": n, "count": counts[n]} for n in page_names],
    }


def _stima_dal_libro(b: dict):
    """La stima delle pagine dal dizionario di un libro di `list_books`, dove
    le colonne personalizzate stanno sotto `#<etichetta>`. Zero e vuoto
    valgono "non lo so": la UI del lettore non disegna barre finte."""
    valore = b.get("#" + PAGE_COUNT_COLUMN_LABEL)
    return int(valore) if valore else None


def _serialize_catalog_book(b: dict) -> dict:
    """
    Shared shape for every catalog-style response (browse_catalog, and the
    Discover endpoint below) — kept in one place so a field added/renamed
    here never drifts between the two.

    `has_cover` passa per un `bool()`, e non e' pedanteria. Fino al
    05/11/2026 qui usciva il valore grezzo della colonna di Calibre, cioe'
    `0` oppure `1`, mentre lo stesso campo da `/api/kolibre/books` usciva
    `true`/`false` (vedi `books.py`): lo stesso dato con due tipi secondo
    l'indirizzo. Questa risposta la legge un plugin scritto in **Lua**, dove
    **lo zero e' vero** — un `if book.has_cover then` sarebbe entrato anche
    per un libro senza copertina. Nessun client lo leggeva ancora, quindi
    era il momento meno costoso per uniformarlo.
    """
    return {
        "id": b["id"], "title": b["title"], "author": b.get("author"), "formats": b["formats"],
        "series": b.get("series"), "series_index": b.get("series_index"),
        "tags": b.get("tags") or [], "rating": b.get("rating"),
        "pubdate": b.get("pubdate"), "has_cover": bool(b.get("has_cover")),
        "size": b.get("size"),
        # Stesso nome e stesso significato che nella consegna: un libro preso
        # dal catalogo sul dispositivo finisce nel manifesto per la stessa
        # strada, e senza questo campo sarebbe l'unico senza barra.
        "server_pages": _stima_dal_libro(b),
    }


def _device_book_ids_on_device(db: Session, device_id: int, library: str) -> set:
    """calibre_book_id set "currently on this device" for one library —
    every DeviceBook row except status='removed_by_device' (a device can
    have a pending_send/pending_delete/send_failed/delete_declined row that
    is still physically present or about to be, so only an actually-
    confirmed removal should make a book eligible again for Discover/the
    "non sul device" filter)."""
    rows = db.query(models.DeviceBook.calibre_book_id).filter(
        models.DeviceBook.device_id == device_id,
        models.DeviceBook.library == library,
        models.DeviceBook.status != "removed_by_device",
    ).all()
    return {r[0] for r in rows}


@sync_router.get(
    "/catalog/discover",
    responses={200: {"model": LibriDaScoprire}},
)
def catalog_discover(
    library: str,
    limit: int = 12,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    "Da scoprire": books NOT already on this device, preferring ones that
    share an author or a tag with what was recently read ON THIS DEVICE
    (ReadingSession.device_id, same scoping already used elsewhere for
    per-device stats — see stats_service.py's own device_id-only filters,
    no separate user scope needed since device_id already identifies a
    single owner). Falls back to a random pick from the rest of the library
    when there aren't enough (or any) author/tag matches, exactly as
    requested: "stesso autore o stessi tag e poi scelta randomica".
    """
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")

    on_device = _device_book_ids_on_device(db, current_device.id, library)

    recent_rows = db.query(models.ReadingSession.calibre_book_id).filter(
        models.ReadingSession.device_id == current_device.id,
        models.ReadingSession.library == library,
    ).order_by(models.ReadingSession.start_time.desc()).limit(20).all()
    recent_ids = list(dict.fromkeys(r[0] for r in recent_rows))  # dedup, keep recency order

    lib = CalibreLibrary(config.library_path(library))
    all_books = _only_books_with_files(lib.list_books())
    books_by_id = {b["id"]: b for b in all_books}

    recent_authors = set()
    recent_tags = set()
    for cbid in recent_ids:
        rb = books_by_id.get(cbid)
        if not rb:
            continue
        if rb.get("author"):
            recent_authors.add(rb["author"])
        for t in rb.get("tags") or []:
            if t:
                recent_tags.add(t)

    excluded = on_device | set(recent_ids)
    candidates = [b for b in all_books if b["id"] not in excluded]

    matched = [
        b for b in candidates
        if (b.get("author") and b["author"] in recent_authors)
        or any(t in recent_tags for t in (b.get("tags") or []))
    ]
    random.shuffle(matched)
    result = matched[:limit]

    if len(result) < limit:
        chosen_ids = {b["id"] for b in result}
        filler_pool = [b for b in candidates if b["id"] not in chosen_ids]
        random.shuffle(filler_pool)
        result.extend(filler_pool[: limit - len(result)])

    return {"books": [_serialize_catalog_book(b) for b in result]}


@sync_router.get(
    "/catalog",
    responses={200: {"model": CatalogoSfogliato}},
)
def browse_catalog(
    library: str,
    q: str = None,
    author: str = None,
    series: str = None,
    tag: str = None,
    sort: str = "author",
    page: int = None,
    size: int = None,
    exclude_on_device: bool = False,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Catalog browser for the plugin's "Sfoglia catalogo" (stile BookOrbit):
    unlike the server-driven sync queue (Fase 5's core loop), this is the
    device *pulling* whatever it wants, on demand. Returns the full matching
    set (capped) rather than a server-paginated page — KOReader's own Menu
    widget already paginates a long item_table on-device, so there's no need
    to reinvent that here. `sort`: "author" (default) or "recent" (newest
    added first, by Calibre's own `timestamp` column).

    `author`, when given alongside `q`, tightens the fuzzy device-init match
    (main.lua's _findProbableCatalogMatches) from "q anywhere in title OR
    author" to "q in title AND author in author" — plain OR on a single
    needle built by mashing a guessed title and author together (the old
    behavior) is usually a substring of NEITHER field alone, which is why
    filenames that split cleanly into title+author still failed to match.
    Falls back to the original OR-on-q-alone behavior when the AND filter
    finds nothing, so a wrong/noisy author guess never makes matching worse
    than before.

    If BOTH substring passes above come up empty, a real fuzzy pass (edit-
    distance ratio, not containment) runs over the whole catalog as a last
    resort — confirmed as a real gap, not hypothetical: a subtitle, a
    slightly-off title guess from the filename, or reordered
    title/author words all defeat plain substring containment even when a
    human would call the match obvious. This only ever ADDS candidates when
    the substring passes found zero — it never changes/reorders a query that
    already got substring hits, so the interactive "Sfoglia catalogo"
    type-ahead search (short partial words, where a containment check is
    exactly right) is untouched.

    `series`/`tag` (new, for the catalog-navigator foundation work): simple
    independent substring filters (accent-folded, same as `author`) applied
    on top of whatever q/author already selected — deliberately NOT folded
    into the tightening/fuzzy-fallback logic above, which exists only to
    rescue a noisy device-init title/author guess, not to serve every filter
    combination.

    `page`/`size` (new, both optional): when neither is given, behavior is
    byte-for-byte what it always was — up to 500 books, `truncated` if more
    exist. Passing both switches to a real page of the already-filtered/
    sorted list instead of the flat [:500] cap, adding `page`/`has_next` to
    the response. Passing only one of the two falls back to the old
    unpaginated behavior rather than half-implementing pagination.

    `exclude_on_device` (new, for the Browser's "Non sul device" view):
    drops any book already on the CALLING device for this library (see
    `_device_book_ids_on_device`) before sorting/paginating. Default False
    keeps existing behavior byte-for-byte for every caller that doesn't pass
    it — including an un-updated plugin, which never will.
    """
    lib = CalibreLibrary(config.library_path(library))
    all_books = _only_books_with_files(lib.list_books())
    books = all_books
    if q and author:
        q_needle, author_needle = _fold_accents(q), _fold_accents(author)
        tightened = [
            b for b in books
            if q_needle in _fold_accents(b.get("title") or "") and author_needle in _fold_accents(b.get("author") or "")
        ]
        if tightened:
            books = tightened
        elif q:
            needle = _fold_accents(q)
            books = [
                b for b in books
                if needle in _fold_accents(b.get("title") or "") or needle in _fold_accents(b.get("author") or "")
            ]
    elif q:
        needle = _fold_accents(q)
        books = [
            b for b in books
            if needle in _fold_accents(b.get("title") or "") or needle in _fold_accents(b.get("author") or "")
        ]

    if q and not books:
        query_norm = _normalize_for_fuzzy(f"{_reorder_title_sort_article(q)} {author or ''}")
        scored = []
        for b in all_books:
            candidate_title = _reorder_title_sort_article(b.get("title") or "")
            candidate_norm = _normalize_for_fuzzy(f"{candidate_title} {b.get('author') or ''}")
            score = _fuzzy_ratio(query_norm, candidate_norm)
            if score >= _FUZZY_MATCH_THRESHOLD:
                scored.append((score, b))
        if scored:
            scored.sort(key=lambda pair: pair[0], reverse=True)
            books = [b for _, b in scored]

    if series:
        series_needle = _fold_accents(series)
        books = [b for b in books if series_needle in _fold_accents(b.get("series") or "")]
    if tag:
        tag_needle = _fold_accents(tag)
        books = [b for b in books if any(tag_needle in _fold_accents(t) for t in (b.get("tags") or []))]
    if exclude_on_device:
        on_device = _device_book_ids_on_device(db, current_device.id, library)
        books = [b for b in books if b["id"] not in on_device]

    if sort == "recent":
        books.sort(key=lambda b: (b.get("timestamp") or ""), reverse=True)
    else:
        books.sort(key=lambda b: ((b.get("author") or ""), (b.get("title") or "")))
    total = len(books)

    if page is not None and size is not None:
        start = (page - 1) * size
        page_books = books[start:start + size]
    else:
        page_books = books[:500]

    result = {
        "total": total,
        "truncated": total > 500,
        "books": [_serialize_catalog_book(b) for b in page_books],
    }
    if page is not None and size is not None:
        result["page"] = page
        result["has_next"] = (page * size) < total
    return result
