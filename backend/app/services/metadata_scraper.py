"""
Book metadata enrichment: Open Library + Google Books, queried in parallel
and then merged/scored in the same spirit as Calibre's own multi-source
"identify" (parallel plugin queries with a shared wait budget, cross-source
merge keyed on ISBN, relevance scoring) — see calibre's real debug log for
why Amazon/Goodreads/Edelweiss are NOT reproduced here even though Calibre
queries them too: Amazon has no public API (Calibre's own plugin falls back
to scraping Google/Bing search-result pages for it, fragile and a real risk
of the scraping IP getting rate-limited); Goodreads likewise has no public
API (Calibre's Goodreads plugin is a third-party HTML scraper); Edelweiss's
own Calibre plugin, per Calibre's own log line, "currently returns random
books for search queries" — i.e. even Calibre doesn't get real value from
it. Open Library and Google Books are the only sources here that are free,
keyless, AND have a real supported JSON API.
"""

import re
import ssl
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait

import httpx

from ..logging_utils import log_message

# A per-request `timeout=` kwarg on httpx.get only bounds the read/write/pool
# phases reliably — the connect phase (which includes DNS resolution) can
# still hang past it under some network conditions (observed: 20+ seconds to
# a provider that was actually unreachable from this host). An explicit
# httpx.Timeout with its own `connect` bound, PLUS a hard wall-clock deadline
# on the futures below, is what actually guarantees this returns promptly.
_REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=8.0, write=5.0, pool=5.0)
# Raised from 10.0: with the retry below, a source that fails once and
# succeeds on the second attempt needs headroom beyond one full
# _REQUEST_TIMEOUT cycle to actually benefit from that retry.
_HARD_DEADLINE_SECONDS = 15.0

# Observed live on this server's network: connections to these hosts are
# intermittently flaky (TLS handshake timeouts / resets that come and go
# from one attempt to the next, not tied to any request content) — cause
# not fully pinned down (network path, not this app), but a smaller TLS
# ClientHello (capped at TLS 1.2, no HTTP/2 in ALPN — neither provider needs
# h2 anyway) measurably improves the odds of a given attempt succeeding, so
# it costs nothing to always use it. Retrying once (_get_with_retry) is the
# other half of the mitigation: on this kind of intermittent failure, a
# second attempt frequently succeeds where the first one didn't.
_SMALL_CLIENTHELLO_SSL_CONTEXT = ssl.create_default_context()
_SMALL_CLIENTHELLO_SSL_CONTEXT.maximum_version = ssl.TLSVersion.TLSv1_2
_SMALL_CLIENTHELLO_SSL_CONTEXT.set_alpn_protocols(["http/1.1"])

_MAX_TAGS = 8


# Wikimedia CHIEDE un User-Agent che dica chi sei e come contattarti, e i
# suoi servizi rispondono 403 a un client generico (httpx si presenta come
# "python-httpx/x.y"): senza questa riga la ricerca su Wikidata non tornava
# mai niente, e falliva in silenzio perche' il codice logga e restituisce una
# lista vuota. E' anche la cosa giusta da fare verso un servizio gratuito.
_USER_AGENT = "Kolibre/1.0 (self-hosted personal library; https://github.com/kolibre)"


def _get_with_retry(url: str, params: dict, attempts: int = 2, timeout=None) -> httpx.Response:
    last_exc = None
    for attempt in range(attempts):
        try:
            return httpx.get(url, params=params, timeout=timeout or _REQUEST_TIMEOUT,
                             headers={"User-Agent": _USER_AGENT},
                             verify=_SMALL_CLIENTHELLO_SSL_CONTEXT)
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(0.5)
    raise last_exc


def _normalize_isbn(isbn: str | None) -> str | None:
    if not isbn:
        return None
    digits = re.sub(r"[^0-9Xx]", "", isbn).upper()
    return digits or None


def _normalize_title_author_key(title: str | None, author: str | None) -> str:
    return f"{(title or '').strip().lower()}|{(author or '').strip().lower()}"


def _normalize_pubdate(raw: str | None) -> str | None:
    """Google Books gives varying precision ("1983", "2012-10", or
    "2012-10-25") — keep whatever precision is actually available instead
    of always collapsing to just the year, padding to a full date so it's
    a valid value for Calibre's pubdate column."""
    if not raw:
        return None
    if len(raw) >= 10:
        return raw[:10]
    if len(raw) == 7:
        return f"{raw}-01"
    if len(raw) == 4 and raw.isdigit():
        return f"{raw}-01-01"
    return None


# Come e' andata una fonte, per poterlo DIRE invece di lasciare una lista
# vuota a significare tre cose diverse: "non ha trovato niente", "e' a quota
# esaurita" e "non ha risposto in tempo". Erano indistinguibili, ed e' la
# meta' del "fatica spesso a scaricare dati utili" riscontrato in uso:
# Google Books senza chiave API risponde 429 per giorni interi, e finora la
# finestra si limitava a mostrare pochi risultati senza spiegare perche'.
_esito: dict = {}


def _segna(fonte: str, stato: str, dettaglio: str = "") -> None:
    _esito[fonte] = {"stato": stato, "dettaglio": dettaglio}


def _search_open_library(title: str, author: str) -> list:
    try:
        params = {"title": title, "limit": 5}
        if author:
            params["author"] = author
        resp = _get_with_retry("https://openlibrary.org/search.json", params)
        if resp.status_code != 200:
            _segna("Open Library", "errore", f"answered {resp.status_code}")
            return []
        results = []
        for d in resp.json().get("docs", [])[:5]:
            cover_i = d.get("cover_i")
            isbn = (d.get("isbn") or [None])[0]
            identifiers = {"isbn": isbn} if isbn else {}
            olid = (d.get("edition_key") or [None])[0]
            if olid:
                identifiers["openlibrary"] = olid
            year = d.get("first_publish_year")
            results.append({
                "source": "Open Library",
                "title": d.get("title"),
                "author": ", ".join(d.get("author_name") or []),
                "isbn": isbn,  # kept for older callers; identifiers below is the full multi-type set
                "identifiers": identifiers,
                "description": None,
                "tags": (d.get("subject") or [])[:5],
                "publisher": (d.get("publisher") or [None])[0],
                "language": (d.get("language") or [None])[0],
                # Open Library's search API only ever gives year precision.
                "pubdate": f"{year}-01-01" if year else None,
                "pubdate_year": year,
                "cover_url": f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg" if cover_i else None,
            })
        return results
    except Exception as exc:
        # Broader than httpx.HTTPError on purpose: a 200 with a body whose
        # shape changed (Open Library has done this before) throws a plain
        # KeyError/TypeError here, not an httpx error — and that used to
        # propagate all the way up through the ThreadPoolExecutor future and
        # 500 the whole search (crashing Google Books' results too, even
        # when THEY came back fine). One provider misbehaving must only cost
        # that provider's results.
        log_message("warning", "metadata", f"Open Library search failed: {exc}")
        _segna("Open Library", "errore", "unreachable")
        return []


# ── Il ripiego «feeds» di Google Books (23/11/2026) ──────────────────────
#
# E' COSI' che Calibre scarica i metadati senza chiave (domanda di Paolo):
# non l'API ufficiale (googleapis.com/books/v1, che senza chiave risponde
# 429 in permanenza) ma il vecchio endpoint GData, deprecato da piu' di un
# decennio e tenuto in vita di fatto — Calibre ci si appoggia da sempre, e
# l'altra sua arma e' lo scraping delle pagine di Amazon, che qui NON si
# imita (un inseguimento continuo del loro HTML). Misurato sul campione
# della biblioteca vera: 16/20 ISBN trovati, 11/11 fra gli italiani —
# contro i 3/20 di Open Library.
#
# E' un ripiego DICHIARATO: campi piu' poveri (la descrizione spesso manca)
# e nessuna garanzia di futuro. La chiave API resta la strada solida: con
# la chiave questo codice non viene nemmeno interpellato.
_FEEDS_URL = "https://books.google.com/books/feeds/volumes"
_FEEDS_NS = {"a": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/terms"}


def _google_feeds_entries(query: str, max_results: int = 5) -> list:
    r = _get_with_retry(_FEEDS_URL, {"q": query, "max-results": max_results})
    r.raise_for_status()
    return ET.fromstring(r.content).findall("a:entry", _FEEDS_NS)


def _meta_from_feeds_entry(entry) -> dict:
    autori = [x.text for x in entry.findall("dc:creator", _FEEDS_NS) if x.text]
    isbn = None
    for ident in entry.findall("dc:identifier", _FEEDS_NS):
        v = valid_isbn((ident.text or "").replace("ISBN:", ""))
        if v:
            isbn = v
            if len(v) == 13:
                break  # si preferisce il 13, quando la entry porta entrambi
    thumb = None
    for link in entry.findall("a:link", _FEEDS_NS):
        if "thumbnail" in (link.get("rel") or ""):
            thumb = _https(link.get("href"))
            break
    return {
        "title": entry.findtext("a:title", namespaces=_FEEDS_NS),
        "author": " & ".join(autori) or None,
        "pubdate": _normalize_pubdate(entry.findtext("dc:date", namespaces=_FEEDS_NS)),
        "description": entry.findtext("dc:description", namespaces=_FEEDS_NS),
        "cover_url": thumb,
        "isbn": isbn,
        "tags": [x.text for x in entry.findall("dc:subject", _FEEDS_NS) if x.text][:5],
        "publisher": entry.findtext("dc:publisher", namespaces=_FEEDS_NS),
    }


def _google_feeds_by_isbn(isbn: str):
    """Un ISBN sul vecchio feeds, senza chiave. None se non lo conosce o
    non risponde: mai un motivo per non creare la voce vuota."""
    try:
        entries = _google_feeds_entries(f"isbn:{isbn}", max_results=1)
        if not entries:
            return None
        meta = _meta_from_feeds_entry(entries[0])
        return meta if meta.get("title") else None
    except Exception as e:
        log_message("warning", "metadata", f"Google feeds ISBN lookup failed ({isbn}): {e}")
        return None


def _search_google_feeds(title: str, author: str) -> list:
    """La ricerca titolo+autore sul vecchio feeds, nella stessa forma dei
    candidati dell'API ufficiale: e' il ramo che parte quando la v1
    risponde 429 e una chiave non c'e'."""
    try:
        q = f"intitle:{title}"
        if author:
            q += f" inauthor:{author}"
        results = []
        for entry in _google_feeds_entries(q, max_results=5):
            m = _meta_from_feeds_entry(entry)
            if not m.get("title"):
                continue
            identifiers = {"isbn": m["isbn"]} if m.get("isbn") else {}
            results.append({
                "source": "Google Books",
                "title": m["title"],
                "author": (m.get("author") or "").replace(" & ", ", "),
                "isbn": m.get("isbn"),
                "identifiers": identifiers,
                "description": m.get("description"),
                "tags": m.get("tags") or [],
                "publisher": m.get("publisher"),
                "language": None,
                "pubdate": m.get("pubdate"),
                "cover_url": m.get("cover_url"),
            })
        return results
    except Exception as e:
        log_message("warning", "metadata", f"Google feeds search failed: {e}")
        return []


def _search_google_books(title: str, author: str) -> list:
    try:
        q = f"intitle:{title}"
        if author:
            q += f"+inauthor:{author}"
        params = {"q": q, "maxResults": 5}
        resp = _get_with_retry("https://www.googleapis.com/books/v1/volumes", params)
        if resp.status_code == 429:
            # Il trucco di Calibre (23/11/2026): la quota anonima dell'API
            # ufficiale e' condivisa a livello mondiale ed esaurita in
            # permanenza, quindi sul 429 si ripiega sul vecchio endpoint
            # feeds, che la quota non la conosce. Vedi _FEEDS_URL. (La
            # chiave API personale e' stata provata e poi tolta lo stesso
            # 23/11 su scelta di Paolo: il ripiego basta, da rivalutare
            # in futuro.)
            ripiego = _search_google_feeds(title, author)
            if ripiego:
                _segna("Google Books", "ok", "via the legacy feeds endpoint (no API key)")
                return ripiego
            # Se anche il ripiego non da' niente va detto, invece di far
            # sembrare la fonte vuota.
            _segna("Google Books", "quota",
                   "the anonymous daily quota is used up and the legacy feeds found nothing")
            return []
        if resp.status_code != 200:
            _segna("Google Books", "errore", f"answered {resp.status_code}")
            return []
        if resp.status_code != 200:
            return []
        results = []
        for item in resp.json().get("items", []):
            info = item.get("volumeInfo", {})
            isbn = None
            for ident in info.get("industryIdentifiers", []) or []:
                if ident.get("type") in ("ISBN_13", "ISBN_10"):
                    isbn = ident.get("identifier")
                    break
            identifiers = {"isbn": isbn} if isbn else {}
            if item.get("id"):
                identifiers["google"] = item["id"]
            pubdate = _normalize_pubdate(info.get("publishedDate"))
            results.append({
                "source": "Google Books",
                "title": info.get("title"),
                "author": ", ".join(info.get("authors") or []),
                "isbn": isbn,  # kept for older callers; identifiers below is the full multi-type set
                "identifiers": identifiers,
                "description": info.get("description"),
                "tags": (info.get("categories") or [])[:5],
                "publisher": info.get("publisher"),
                "language": info.get("language"),
                "pubdate": pubdate,
                "pubdate_year": int(pubdate[:4]) if pubdate else None,
                "cover_url": (info.get("imageLinks") or {}).get("thumbnail"),
            })
        return results
    except Exception as exc:
        log_message("warning", "metadata", f"Google Books search failed: {exc}")
        return []


# Wikidata come terza fonte, e la piu' importante delle tre per questa
# biblioteca.
#
# Le altre due interrogano per EDIZIONE e sono entrambe zoppe qui: Open
# Library e' fortemente anglosassone (misurato su dati reali: 9 edizioni
# trovate su 40, prima pubblicazione al 5%) e Google Books senza chiave API
# ha una quota anonima per indirizzo IP che si esaurisce — al 24/09/2026
# risponde 429 anche da qui, quindi una delle due fonti e' di fatto assente.
#
# Wikidata interroga l'OPERA, che e' l'oggetto giusto per le tre cose che
# mancavano davvero: prima pubblicazione (P577), lingua originale (P407) e
# genere (P136). Su queste, misurate sugli autori gia' agganciati, la
# copertura e' 96%, 99% e 71%. E non ha quota.
#
# La query combina la ricerca testuale di MediaWiki (dentro SPARQL, via
# wikibase:mwapi) con il filtro "e' un'opera scritta": senza il filtro la
# ricerca per titolo restituisce anche persone, film e riviste omonime.
_WIKIDATA_SPARQL = """
SELECT ?item ?itemLabel ?pub ?langLabel ?genreLabel
       (GROUP_CONCAT(DISTINCT ?authLabel; separator=", ") AS ?authors) WHERE {
  SERVICE wikibase:mwapi {
    bd:serviceParam wikibase:api "EntitySearch" .
    bd:serviceParam wikibase:endpoint "www.wikidata.org" .
    bd:serviceParam mwapi:search %(titolo)s .
    bd:serviceParam mwapi:language "it" .
    ?item wikibase:apiOutputItem mwapi:item .
  }
  ?item wdt:P31/wdt:P279* wd:Q47461344 .
  OPTIONAL { ?item wdt:P577 ?pub }
  OPTIONAL { ?item wdt:P407 ?lang }
  OPTIONAL { ?item wdt:P136 ?genre }
  OPTIONAL { ?item wdt:P50 ?auth . ?auth rdfs:label ?authLabel . FILTER(LANG(?authLabel) = "it") }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "it,en". }
} GROUP BY ?item ?itemLabel ?pub ?langLabel ?genreLabel LIMIT 10
"""


def _sparql_stringa(valore: str) -> str:
    """Una stringa SPARQL con le virgolette al posto giusto.

    Non e' pignoleria: un titolo con un apice o una virgoletta — "L'errore di
    Cartesio" — romperebbe la query, e un titolo e' testo che arriva dai
    metadati di un libro, cioe' da fuori.
    """
    pulito = (valore or "").replace("\\", "").replace('"', " ").replace("\n", " ")
    return '"' + pulito.strip()[:120] + '"'


def _search_wikidata(title: str, author: str) -> list:
    try:
        resp = _get_with_retry(
            "https://query.wikidata.org/sparql",
            {"query": _WIKIDATA_SPARQL % {"titolo": _sparql_stringa(title)}, "format": "json"},
            # Una query SPARQL ragiona, non serve un file: 8 secondi di
            # lettura (il valore buono per un'API REST) la tagliano a meta'.
            timeout=httpx.Timeout(connect=3.0, read=20.0, write=5.0, pool=5.0),
        )
        if resp.status_code != 200:
            log_message("warning", "metadata",
                        f"Wikidata answered {resp.status_code} for '{title}'")
            _segna("Wikidata", "errore", f"answered {resp.status_code}")
            return []
        risultati = []
        for b in resp.json().get("results", {}).get("bindings", [])[:10]:
            def v(chiave):
                return (b.get(chiave) or {}).get("value") or None
            qid = (v("item") or "").rsplit("/", 1)[-1] or None
            data = v("pub")
            risultati.append({
                "source": "Wikidata",
                "title": v("itemLabel"),
                "author": v("authors") or "",
                "isbn": None,
                "identifiers": {"wikidata": qid} if qid else {},
                "description": None,
                # Il genere di Wikidata e' inserito a mano da volontari e
                # sbaglia ("L'errore di Cartesio" risulta di genere
                # "Neolitico"): va bene come tag proposto, che una persona
                # conferma o no, non come dato da applicare al buio.
                "tags": [v("genreLabel")] if v("genreLabel") else [],
                # Un'OPERA non ha un editore: ce l'hanno le sue edizioni.
                "publisher": None,
                "language": v("langLabel"),
                "pubdate": data[:10] if data else None,
                "pubdate_year": int(data[:4]) if data and data[:4].isdigit() else None,
                # Wikidata ha le immagini (P18) ma sono ritratti dell'autore o
                # frontespizi storici molto piu' spesso che copertine: meglio
                # nessuna copertina che una sbagliata.
                "cover_url": None,
                # Quello che distingue questa fonte dalle altre due: qui i
                # valori sono dell'OPERA, non dell'edizione posseduta. Chi
                # sceglie deve poterlo sapere.
                "livello": "opera",
            })
        return risultati
    except Exception as exc:
        log_message("warning", "metadata", f"Wikidata search failed: {exc}")
        _segna("Wikidata", "errore", "unreachable")
        return []


def _https(url):
    """Le copertine si servono in https o non si vedono.

    Google Books restituisce le miniature con schema `http://`: su una pagina
    servita in https il browser le blocca come contenuto misto, in silenzio —
    l'immagine risulta semplicemente assente, ed e' uno dei motivi per cui la
    finestra dei metadati "non mostra le copertine". Gli stessi URL rispondono
    benissimo in https.
    """
    if isinstance(url, str) and url.startswith("http://"):
        return "https://" + url[len("http://"):]
    return url


def _dedup_key(candidate: dict) -> str:
    isbn = _normalize_isbn(candidate.get("isbn"))
    if isbn:
        return f"isbn:{isbn}"
    return f"ta:{_normalize_title_author_key(candidate.get('title'), candidate.get('author'))}"


def _shortest(group: list, field: str):
    vals = [c[field] for c in group if c.get(field)]
    return min(vals, key=len) if vals else None


def _longest(group: list, field: str):
    vals = [c[field] for c in group if c.get(field)]
    return max(vals, key=len) if vals else None


def _first(group: list, field: str):
    for c in group:
        if c.get(field):
            return c[field]
    return None


def _merge_group(group: list) -> dict:
    """One candidate per unique book instead of one per source — mirrors
    Calibre's ISBNMerge (merge_isbn_results/merge_metadata_results in its
    sources/base.py): title/publisher favor the shortest non-empty value
    ("least cruft" — avoids a subtitle one source tacked on), author/tags
    favor the union/longest (extra info is harmless), pubdate favors the
    earliest (first-edition heuristic), cover prefers Open Library's
    full-size cover over Google's thumbnail-only one."""
    if len(group) == 1:
        result = dict(group[0])
        result["_merged_from"] = 1
        return result

    sources = []
    for c in group:
        if c["source"] not in sources:
            sources.append(c["source"])

    tags = []
    for c in group:
        for t in c.get("tags") or []:
            if t not in tags:
                tags.append(t)

    identifiers = {}
    for c in group:
        identifiers.update(c.get("identifiers") or {})

    pubdates = [c["pubdate"] for c in group if c.get("pubdate")]
    pubdate = min(pubdates) if pubdates else None
    years = [c["pubdate_year"] for c in group if c.get("pubdate_year")]
    pubdate_year = min(years) if years else None

    cover_url = None
    for preferred_source in ("Open Library", "Google Books"):
        cover_url = next((c["cover_url"] for c in group if c["source"] == preferred_source and c.get("cover_url")), None)
        if cover_url:
            break
    if not cover_url:
        cover_url = _first(group, "cover_url")

    return {
        "source": " + ".join(sources),
        "title": _shortest(group, "title") or _first(group, "title"),
        "author": _longest(group, "author") or _first(group, "author"),
        "isbn": _first(group, "isbn"),
        "identifiers": identifiers,
        "description": _longest(group, "description"),
        "tags": tags[:_MAX_TAGS],
        "publisher": _shortest(group, "publisher"),
        "language": _first(group, "language"),
        "pubdate": pubdate,
        "pubdate_year": pubdate_year,
        "cover_url": cover_url,
        "_merged_from": len(sources),
    }


def _score_candidate(candidate: dict, title: str, author: str) -> int:
    score = 0
    cand_title = (candidate.get("title") or "").strip().lower()
    cand_author = (candidate.get("author") or "").strip().lower()
    title_l = (title or "").strip().lower()
    author_l = (author or "").strip().lower()

    if title_l and cand_title:
        if cand_title == title_l:
            score += 3
        elif title_l in cand_title or cand_title in title_l:
            score += 1
    if author_l and cand_author:
        if cand_author == author_l:
            score += 3
        elif author_l in cand_author or cand_author in author_l:
            score += 1

    for field in ("isbn", "publisher", "language", "pubdate", "cover_url", "description"):
        if candidate.get(field):
            score += 1
    if candidate.get("tags"):
        score += 1

    # A candidate multiple independent sources agree on is inherently more
    # trustworthy than one only a single source found — same idea as
    # Calibre's average_source_relevance favoring cross-source consensus.
    score += 3 * (candidate.get("_merged_from", 1) - 1)
    return score


def search_book_metadata(title: str, author: str = "") -> list:
    """
    Best candidates first: Open Library and Google Books queried
    concurrently (not one after the other — a single unreachable/slow
    provider used to stall the whole search even though the OTHER
    provider's data was already sitting there ready), then merged one
    candidate per unique book (by ISBN, or by normalized title+author when
    neither source has one) instead of listing the same book twice, and
    scored so that candidates multiple sources agree on rank above a
    single-source hit.
    """
    # Deliberately NOT a `with ThreadPoolExecutor(...) as pool:` block: its
    # __exit__ calls shutdown(wait=True), which would block on a runaway
    # thread for exactly as long as the timeout below was trying to avoid.
    # shutdown(wait=False) lets this function return promptly even if a
    # thread is still stuck mid-DNS-resolution; that thread finishes (or
    # dies with the process) on its own, harmlessly, in the background.
    _esito.clear()
    for fonte in ("Open Library", "Google Books", "Wikidata"):
        _segna(fonte, "ok")
    pool = ThreadPoolExecutor(max_workers=3)
    try:
        ol_future = pool.submit(_search_open_library, title, author)
        gb_future = pool.submit(_search_google_books, title, author)
        wd_future = pool.submit(_search_wikidata, title, author)
        # A single shared deadline for BOTH sources (via futures.wait)
        # instead of awaiting each future's own timeout in sequence: the
        # old code could wait up to 2x _HARD_DEADLINE_SECONDS in the worst
        # case (each `.result(timeout=...)` call blocks independently), even
        # though both sources were actually running the whole time.
        done, pending = futures_wait({ol_future, gb_future, wd_future}, timeout=_HARD_DEADLINE_SECONDS)
        for futuro, fonte in ((ol_future, "Open Library"), (gb_future, "Google Books"),
                              (wd_future, "Wikidata")):
            if futuro in pending:
                _segna(fonte, "lenta", f"did not answer within {_HARD_DEADLINE_SECONDS:.0f} seconds")
        if pending:
            log_message(
                "info", "metadata",
                f"Ricerca metadati '{title}': not waiting beyond {_HARD_DEADLINE_SECONDS:.0f}s, "
                f"{len(pending)} source(s) still running",
            )
        ol_results = ol_future.result() if ol_future in done else []
        gb_results = gb_future.result() if gb_future in done else []
        wd_results = wd_future.result() if wd_future in done else []
    finally:
        pool.shutdown(wait=False)

    groups: dict[str, list] = {}
    order: list[str] = []
    for c in ol_results + gb_results + wd_results:
        c["cover_url"] = _https(c.get("cover_url"))
        key = _dedup_key(c)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(c)

    merged = [_merge_group(groups[key]) for key in order]
    merged.sort(key=lambda c: _score_candidate(c, title, author), reverse=True)
    for c in merged:
        c.pop("_merged_from", None)
    return merged


def cerca_metadati_con_esito(title: str, author: str = "", limite: int = 5) -> dict:
    """I candidati piu' com'e' andata ogni fonte.

    Serve a distinguere "questo libro non e' in nessun catalogo" da "una
    delle tre fonti oggi non risponde": due situazioni che dall'elenco dei
    risultati sono identiche, e che chiedono cose diverse a chi guarda.
    """
    candidati = search_book_metadata(title, author)
    fonti = [
        {"nome": nome, **dati}
        for nome, dati in _esito.items()
    ]
    return {"candidates": candidati[:limite], "fonti": fonti}


# ── Ricerca per ISBN (22/11/2026: le schede fantasma) ────────────────────
#
# Serve all'importazione per ISBN della pagina Ingest: una o piu' schede
# SENZA file, coi metadati scaricati da Open Library. Solo Open Library, per
# scelta di Paolo: Google Books senza chiave API risponde 429 «quota del
# giorno esaurita» sia da casa sia dal server (misurato il 22/11), e
# Wikidata e' cronicamente oltre i 15 secondi. L'endpoint usato e'
# `api/books` con `jscmd=data`: accetta un LOTTO di ISBN in una chiamata
# sola e torna gli autori gia' risolti in nomi.

# Quanti ISBN per chiamata. Open Library non dichiara un limite; 20 tiene
# l'indirizzo corto e una risposta di dimensione prevedibile.
_ISBN_BATCH_SIZE = 20


def valid_isbn(isbn: str | None) -> str | None:
    """L'ISBN normalizzato (solo cifre, X finale ammessa) se la cifra di
    controllo torna, altrimenti None. Si accettano ISBN-10 e ISBN-13.

    Il controllo non e' pignoleria: l'ISBN diventa un identificatore della
    scheda e il criterio del «ce l'hai gia'» — una stringa qualsiasi li'
    dentro inquinerebbe entrambi. Chi vuole una scheda su cui l'ISBN non
    torna la crea senza ISBN e la compila a mano.
    """
    normalizzato = _normalize_isbn(isbn)
    if not normalizzato:
        return None
    if len(normalizzato) == 13 and normalizzato.isdigit():
        somma = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(normalizzato))
        return normalizzato if somma % 10 == 0 else None
    if len(normalizzato) == 10 and normalizzato[:9].isdigit():
        somma = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(normalizzato))
        return normalizzato if somma % 11 == 0 else None
    return None


def _pubdate_from_open_library(raw: str | None) -> str | None:
    """Open Library scrive date umane («October 1, 1988», «1988»): si tiene
    l'anno, che e' l'unica parte sempre affidabile, nel formato pieno che
    la colonna pubdate di Calibre vuole."""
    if not raw:
        return None
    anno = re.search(r"\b(\d{4})\b", raw)
    return f"{anno.group(1)}-01-01" if anno else None


def fetch_metadata_by_isbn(isbns: list) -> dict:
    """I metadati di uno o piu' ISBN: Open Library in lotti, poi — per i
    suoi buchi — il vecchio feeds di Google (il trucco di Calibre).

    L'ordine non e' estetico (23/11/2026, misurato sulla biblioteca vera):
    Open Library conosce 3 ISBN su 20 del campione (2/11 italiani), il
    feeds 16/20 (11/11 italiani), e l'API ufficiale senza chiave risponde
    429 in permanenza. Quindi: prima la fonte libera e documentata, poi il
    ripiego che non promette niente ma trova quasi tutto. (La chiave API
    personale e' stata provata e tolta lo stesso 23/11, scelta di Paolo.)

    Torna {isbn normalizzato: dict | None}: None vuol dire «nessuna fonte
    lo conosce» (il chiamante crea comunque la voce vuota, per scelta di
    Paolo del 22/11). Il dict porta title, author (piu' autori uniti con
    ' & ', come li vuole Calibre), pubdate, description (da Google quando
    c'e': Open Library non la da') e cover_url, quando ci sono.
    """
    esiti = {}
    lista = list(isbns)
    for inizio in range(0, len(lista), _ISBN_BATCH_SIZE):
        lotto = lista[inizio:inizio + _ISBN_BATCH_SIZE]
        chiavi = {f"ISBN:{i}": i for i in lotto}
        try:
            r = _get_with_retry("https://openlibrary.org/api/books",
                                {"bibkeys": ",".join(chiavi), "jscmd": "data", "format": "json"})
            r.raise_for_status()
            dati = r.json()
        except Exception as e:
            log_message("warning", "metadata", f"Open Library ISBN lookup failed: {e}")
            for isbn in lotto:
                esiti[isbn] = None
            continue
        for bibkey, isbn in chiavi.items():
            d = dati.get(bibkey)
            if not isinstance(d, dict) or not d.get("title"):
                esiti[isbn] = None
                continue
            autori = [a.get("name") for a in d.get("authors") or [] if isinstance(a, dict) and a.get("name")]
            cover = d.get("cover") or {}
            esiti[isbn] = {
                "title": d.get("title"),
                "author": " & ".join(autori) or None,
                "pubdate": _pubdate_from_open_library(d.get("publish_date")),
                "description": None,
                "cover_url": _https(cover.get("large") or cover.get("medium") or cover.get("small")),
            }
    # I buchi di Open Library li colma il vecchio feeds, il trucco di
    # Calibre: e' l'unica strada verso Google rimasta senza chiave.
    for isbn in lista:
        if esiti.get(isbn) is None:
            esiti[isbn] = _google_feeds_by_isbn(isbn)
    return esiti


def download_cover(url: str | None):
    """La copertina come bytes, o None: per una scheda senza file la
    copertina e' un di piu', mai un motivo per far fallire la creazione."""
    if not url:
        return None
    try:
        r = _get_with_retry(url, {})
        r.raise_for_status()
        return r.content if r.content else None
    except Exception as e:
        log_message("warning", "metadata", f"Cover download failed ({url}): {e}")
        return None
