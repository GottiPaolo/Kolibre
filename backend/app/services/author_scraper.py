"""
Author bio/photo enrichment from Wikipedia's REST summary API. Per the
project's own design (random_ideas.md): search Italian Wikipedia first, fall
back to English — this is not a general-purpose multi-language feature yet,
just it->en, matching what the frontend's bio IT/EN toggle already expects.
"""

import io
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote, unquote, urlparse

import httpx
from PIL import Image

from .. import config
from ..logging_utils import log_message

WIKI_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
COMMONS_FILE_URL = "https://commons.wikimedia.org/wiki/Special:FilePath/{filename}?width=400"

# Wikimedia chiede esplicitamente uno User-Agent che identifichi
# l'applicazione e dia un contatto, e limita piu' aggressivamente il traffico
# anonimo o generico (https://meta.wikimedia.org/wiki/User-Agent_policy).
# "Kolibre/1.0" da solo non diceva a nessuno chi fossimo; durante la diagnosi
# di questo stesso problema ci siamo presi due 429 in pochi minuti.
USER_AGENT = "Kolibre/1.0 (https://github.com/GottiPaolo/Kolibre)"
IMAGE_MAX_WIDTH = 300
IMAGE_JPEG_QUALITY = 65

# Qualunque sottodominio *.wikipedia.org è ammesso (l'utente può incollare un
# link in una lingua diversa da it/en) — ma NIENT'ALTRO: questo endpoint fa
# una richiesta HTTP server-side verso un URL fornito dall'utente, quindi
# senza un allowlist di host sarebbe un classico SSRF (vedi la stessa
# motivazione già scritta per set_author_photo_from_url in api/authors.py).
_WIKIPEDIA_HOST_RE = re.compile(r"^([a-z-]+)\.wikipedia\.org$")
_WIKIPEDIA_PATH_RE = re.compile(r"^/wiki/(.+)$")

# Transient-failure statuses worth a short retry (rate limiting, momentary
# server hiccups) — a bulk "scrape every author" run fires many requests in
# quick succession and can trip Wikipedia's rate limiting on a handful of
# them; without a retry, those authors silently got permanently blank bios
# even though the page genuinely exists (e.g. Rudolf Rocker).
_RETRYABLE_STATUSES = {429, 502, 503, 504}
_MAX_ATTEMPTS = 4
_RETRY_DELAY_SECONDS = 1.0
# Tetto all'attesa suggerita da Wikipedia: rispettare Retry-After e' corretto,
# ma un valore assurdo non deve bloccare un giro da centinaia di autori.
_MAX_RETRY_AFTER_SECONDS = 15.0


def _retry_pause(resp, attempt: int) -> float:
    """Quanto aspettare prima del tentativo successivo: quello che dice il
    server se lo dice, altrimenti un'attesa che raddoppia."""
    if resp is not None:
        raw = resp.headers.get("retry-after")
        if raw:
            try:
                return min(float(raw), _MAX_RETRY_AFTER_SECONDS)
            except ValueError:
                pass
    return _RETRY_DELAY_SECONDS * (2 ** (attempt - 1))


# Motivi di fallimento, in ordine di gravita' crescente per il chiamante:
# "not_found" e "disambiguation" sono risposte legittime di Wikipedia (non
# c'e' niente da prendere), "blocked" ed "error" sono nostri problemi e vanno
# ritentati piu' tardi.
FAIL_NOT_FOUND = "not_found"
FAIL_DISAMBIGUATION = "disambiguation"
FAIL_BLOCKED = "blocked"
FAIL_ERROR = "error"


def _fetch_summary(name: str, lang: str):
    return _fetch_summary_by_title(name.replace(" ", "_"), lang)


def _fetch_summary_by_title(title: str, lang: str) -> tuple:
    """
    None puo' voler dire tre cose molto diverse — pagina inesistente, pagina
    di disambiguazione, oppure "Wikipedia non ci ha risposto". Prima erano
    indistinguibili anche nei log, ed e' il motivo per cui di un autore
    rimasto senza dati non si capiva se mancasse la pagina o fosse solo
    andata storta la richiesta (riscontrato in uso: "non capisco se e' un
    problema di troppe richieste, o altro, dato che comunicano poco i log").
    Ora ogni esito che non sia "pagina assente" lascia una traccia.
    """
    url = WIKI_SUMMARY_URL.format(lang=lang, title=title)
    resp = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = httpx.get(url, timeout=8, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        except httpx.HTTPError as e:
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_retry_pause(None, attempt))
                continue
            log_message("warning", "authors",
                        f"Wikipedia [{lang}] '{title}': rete non raggiungibile dopo {attempt} tentativi ({type(e).__name__})")
            return None, FAIL_ERROR
        if resp.status_code == 404:
            return None, FAIL_NOT_FOUND  # la pagina non esiste: non e' un guasto, non si ritenta
        if resp.status_code != 200:
            if resp.status_code in _RETRYABLE_STATUSES and attempt < _MAX_ATTEMPTS:
                time.sleep(_retry_pause(resp, attempt))
                continue
            log_message("warning", "authors",
                        f"Wikipedia [{lang}] '{title}': HTTP {resp.status_code} dopo {attempt} tentativi"
                        + (" — limite di richieste" if resp.status_code == 429 else ""))
            return None, (FAIL_BLOCKED if resp.status_code == 429 else FAIL_ERROR)
        break
    try:
        data = resp.json()
        if data.get("type") == "disambiguation":
            log_message("info", "authors", f"Wikipedia [{lang}] '{title}': pagina di disambiguazione, ignorata")
            return None, FAIL_DISAMBIGUATION
        return data, None
    except (httpx.HTTPError, ValueError) as e:
        log_message("warning", "authors", f"Wikipedia [{lang}] '{title}': risposta illeggibile ({type(e).__name__})")
        return None, FAIL_ERROR


def _safe_filename(author_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", author_name.lower()).strip("_")
    return f"{slug or 'author'}.jpg"


def _pick_image_url(*summaries) -> Optional[str]:
    """
    URL dell'immagine migliore fra TUTTE le lingue scaricate, non solo quella
    che ha "vinto".

    Prima era `image_source = it_summary or en_summary`: se la voce italiana
    esisteva ma era senza foto, quella inglese non veniva nemmeno guardata.
    Su 692 autori reali sono 119 senza immagine, e fra i primi controllati
    Colin Ward e Hakim Bey erano esattamente questo caso — foto su
    en.wikipedia, mai cercata perche' it.wikipedia rispondeva.

    Preferisce la MINIATURA all'originale quando e' abbastanza grande: tanto
    l'immagine finisce ridimensionata a IMAGE_MAX_WIDTH, e l'originale puo'
    pesare decine di volte tanto — quella di Telmo Pievani e' 7,1 MB contro
    239 KB, per produrre lo stesso jpeg da 300 px. Su centinaia di autori e'
    la differenza fra qualche decina di MB e qualche GB scaricati per niente,
    ed e' anche cio' che fa scattare il limite di richieste di Wikimedia.
    """
    best_thumb = None
    best_original = None
    for summary in summaries:
        if not summary:
            continue
        thumb = summary.get("thumbnail") or {}
        if not best_thumb and thumb.get("source") and (thumb.get("width") or 0) >= IMAGE_MAX_WIDTH:
            best_thumb = thumb["source"]
        original = summary.get("originalimage") or {}
        if not best_original and original.get("source"):
            best_original = original["source"]
        # Una miniatura troppo piccola e' comunque meglio di niente, ma solo
        # se non c'e' un originale da cui ricavare qualcosa di migliore.
        if not best_thumb and not best_original and thumb.get("source"):
            best_thumb = thumb["source"]
    return best_thumb or best_original


def _wikidata_image_url(summary: Optional[dict]) -> Optional[str]:
    """
    Ultima spiaggia per la foto: la proprieta' P18 ("immagine") dell'elemento
    Wikidata collegato alla voce.

    Perche' puo' esserci qui e non nel sommario: il sommario espone solo
    l'immagine principale DELLA VOCE, e una voce senza foto in apertura non ne
    ha nessuna anche quando l'elemento Wikidata ne indica una.

    Costa una richiesta in piu' e viene fatta SOLO quando altrimenti si
    rinuncerebbe. Onestamente: sui quattro autori senza foto che ho
    controllato a mano durante la diagnosi, Wikidata non ne aggiungeva
    nessuno — sono persone per cui una foto libera non esiste. La tengo
    perche' costa poco e puo' solo aggiungere, e perche' `scrape_detail`
    registrera' da quale fonte e' arrivata ogni immagine: fra qualche
    settimana i dati diranno se merita di restare, invece delle nostre
    impressioni.
    """
    qid = (summary or {}).get("wikibase_item")
    if not qid:
        return None
    try:
        resp = httpx.get(
            WIKIDATA_API_URL, timeout=10, headers={"User-Agent": USER_AGENT},
            params={"action": "wbgetclaims", "entity": qid, "property": "P18", "format": "json"},
        )
        if resp.status_code != 200:
            return None
        claims = resp.json().get("claims", {}).get("P18") or []
        if not claims:
            return None
        filename = claims[0]["mainsnak"]["datavalue"]["value"]
    except Exception:
        return None
    return COMMONS_FILE_URL.format(filename=quote(filename.replace(" ", "_")))


def _cache_author_image(author_name: str, image_url: str) -> Optional[str]:
    resp = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            # upload.wikimedia.org 403s the summary API's own generic "Kolibre/1.0"
            # UA (it's fine for the api.wikipedia.org JSON calls, just not for the
            # media CDN) — a browser-like UA plus a wikipedia.org Referer is what
            # gets through.
            resp = httpx.get(
                image_url, timeout=20, follow_redirects=True,
                headers={
                    "User-Agent": f"Mozilla/5.0 (compatible; {USER_AGENT})",
                    "Referer": "https://it.wikipedia.org/",
                },
            )
        except httpx.HTTPError as e:
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_retry_pause(None, attempt))
                continue
            log_message("warning", "authors",
                        f"Foto di '{author_name}': rete non raggiungibile dopo {attempt} tentativi ({type(e).__name__})")
            return None
        if resp.status_code == 200:
            break
        # Il download dell'immagine non ritentava MAI e non diceva niente: in
        # un giro di massa e' proprio qui che scatta il limite di richieste
        # del CDN di Wikimedia, e l'autore restava con la biografia e senza
        # foto senza che nulla lo segnalasse.
        if resp.status_code in _RETRYABLE_STATUSES and attempt < _MAX_ATTEMPTS:
            time.sleep(_retry_pause(resp, attempt))
            continue
        log_message("warning", "authors",
                    f"Foto di '{author_name}': HTTP {resp.status_code} dopo {attempt} tentativi"
                    + (" — limite di richieste" if resp.status_code == 429 else ""))
        return None

    try:
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        if img.width > IMAGE_MAX_WIDTH:
            ratio = IMAGE_MAX_WIDTH / img.width
            img = img.resize((IMAGE_MAX_WIDTH, max(1, int(img.height * ratio))))
        os.makedirs(config.AUTHORS_DIR, exist_ok=True)
        filename = _safe_filename(author_name)
        img.save(os.path.join(config.AUTHORS_DIR, filename), "JPEG", quality=IMAGE_JPEG_QUALITY)
        return filename
    except Exception as e:
        # Era un `except Exception: return None` muto: un'immagine in un
        # formato che Pillow non digerisce, o un disco pieno, sparivano senza
        # lasciare traccia da nessuna parte.
        log_message("warning", "authors",
                    f"Foto di '{author_name}': elaborazione fallita ({type(e).__name__}: {e})")
        return None


# Esiti possibili di scrape_author, in ordine di "quanto vale riprovare".
STATUS_OK = "ok"              # bio e immagine: non c'e' altro da prendere
STATUS_NO_IMAGE = "no_image"  # voce trovata, nessuna foto da nessuna fonte
STATUS_NO_PAGE = "no_page"    # nessuna voce con quel nome
STATUS_BLOCKED = "blocked"    # rifiutati per limite di richieste
STATUS_ERROR = "error"        # rete o risposta illeggibile


def scrape_author(author_name: str) -> dict:
    """
    Oltre ai dati, restituisce `status` e `detail`: sono quelli che permettono
    al giro di massa di non ritentare alla cieca.

    Prima tornava solo campi che potevano essere None, e un None non diceva se
    la voce non esistesse, se non avesse la foto, o se Wikipedia ci avesse
    semplicemente rifiutati. Tre situazioni che vanno trattate in modo
    opposto: la prima non va mai ripetuta, la seconda ogni tanto, la terza
    appena passa la tempesta.

    Una nota sull'ordine: se la voce italiana risponde con una foto, quella
    inglese non viene nemmeno chiesta. E' una richiesta in meno per ogni
    autore gia' completo — su seicento autori e' la differenza fra farsi
    limitare e non farsi limitare.
    """
    result = {
        "bio_it": None, "bio_en": None,
        "wikipedia_url_it": None, "wikipedia_url_en": None,
        "image_cached": None,
        "status": STATUS_NO_PAGE, "detail": None,
    }

    it_summary, it_fail = _fetch_summary(author_name, "it")
    if it_summary:
        result["bio_it"] = it_summary.get("extract")
        result["wikipedia_url_it"] = (it_summary.get("content_urls") or {}).get("desktop", {}).get("page")

    # L'inglese si chiede se l'italiano manca, o se manca la foto: e' l'unica
    # ragione per cui varrebbe la pena di una seconda richiesta.
    en_summary, en_fail = (None, None)
    if not it_summary or not _pick_image_url(it_summary):
        en_summary, en_fail = _fetch_summary(author_name, "en")
        if en_summary:
            result["bio_en"] = en_summary.get("extract")
            result["wikipedia_url_en"] = (en_summary.get("content_urls") or {}).get("desktop", {}).get("page")

    # Se ci hanno rifiutati non possiamo concludere nulla sull'autore: va
    # tenuto da parte e riprovato, non marchiato come "non trovato".
    if FAIL_BLOCKED in (it_fail, en_fail):
        result["status"] = STATUS_BLOCKED
        result["detail"] = "limite di richieste di Wikipedia (429)"
        return result
    if not it_summary and not en_summary:
        if FAIL_ERROR in (it_fail, en_fail):
            result["status"] = STATUS_ERROR
            result["detail"] = "Wikipedia non raggiungibile o risposta illeggibile"
        elif FAIL_DISAMBIGUATION in (it_fail, en_fail):
            result["status"] = STATUS_NO_PAGE
            result["detail"] = "solo una pagina di disambiguazione: serve scegliere la voce a mano"
        else:
            result["status"] = STATUS_NO_PAGE
            result["detail"] = "nessuna voce su Wikipedia con questo nome"
        return result

    image_url = _pick_image_url(it_summary, en_summary)
    source = "voce Wikipedia"
    if not image_url:
        image_url = _wikidata_image_url(it_summary or en_summary)
        source = "Wikidata"
    if not image_url:
        result["status"] = STATUS_NO_IMAGE
        result["detail"] = "voce trovata, ma nessuna foto su Wikipedia ne' su Wikidata"
        return result

    result["image_cached"] = _cache_author_image(author_name, image_url)
    if result["image_cached"]:
        result["status"] = STATUS_OK
        result["detail"] = f"foto da {source}"
    else:
        # L'immagine c'era ma non siamo riusciti a prenderla: e' un guasto
        # nostro, non un'assenza, e come tale va ritentato.
        result["status"] = STATUS_ERROR
        result["detail"] = "foto presente ma scaricamento non riuscito"
    return result


def scrape_author_from_url(author_name: str, url: str) -> Optional[dict]:
    """
    Scrape bio/photo from an explicit Wikipedia article URL, for when the
    by-name auto-search (scrape_author above) finds the wrong homonym or no
    page at all — the caller picks the exact article instead. Any
    *.wikipedia.org language works (not just it/en); `author_name` is only
    used for the cached image's filename, matching scrape_author's own
    per-author-name cache scheme.

    Returns None if the URL isn't a recognizable Wikipedia article link or
    the page doesn't exist.
    """
    parsed = urlparse(url)
    host_match = _WIKIPEDIA_HOST_RE.match(parsed.hostname or "")
    path_match = _WIKIPEDIA_PATH_RE.match(parsed.path or "")
    if not host_match or not path_match:
        return None

    summary, _fail = _fetch_summary_by_title(unquote(path_match.group(1)), host_match.group(1))
    if not summary:
        return None

    image_cached = None
    image_url = _pick_image_url(summary) or _wikidata_image_url(summary)
    if image_url:
        image_cached = _cache_author_image(author_name, image_url)

    return {
        "bio": summary.get("extract"),
        "wikipedia_url": (summary.get("content_urls") or {}).get("desktop", {}).get("page") or url,
        "image_cached": image_cached,
    }


# Quanto aspettare prima di riprovare, per esito. L'idea e' semplice: non
# ritentare cio' che non puo' cambiare, ritentare presto cio' che e' colpa
# della rete, e riprovare ogni tanto cio' che *potrebbe* cambiare (una foto
# aggiunta a una voce, una voce creata da zero).
RETRY_AFTER = {
    STATUS_OK: None,                       # non c'e' piu' niente da prendere
    STATUS_NO_IMAGE: timedelta(days=30),   # le foto vengono aggiunte, ma non ogni settimana
    STATUS_NO_PAGE: timedelta(days=90),    # una voce puo' nascere; raramente
    STATUS_BLOCKED: timedelta(hours=1),    # e' passeggero
    STATUS_ERROR: timedelta(hours=6),
}


def apply_outcome(row, scraped: dict, now: datetime) -> None:
    """
    Scrive su una riga AuthorMetadata i dati E l'esito. Sta qui, e non nei
    tre chiamanti, perche' la regola "cosa vale la pena riprovare e quando"
    deve essere una sola: l'endpoint del singolo autore, il gancio
    sull'import e il giro di massa devono lasciare il database nello stesso
    stato, o il giro successivo ripartira' con idee diverse a seconda di chi
    ha scritto per ultimo.

    I campi si sovrascrivono solo se il nuovo valore c'e' (`or row.X`): un
    tentativo andato male non deve cancellare una biografia gia' buona, ne'
    una foto gia' scaricata.
    """
    row.bio_it = scraped.get("bio_it") or row.bio_it
    row.bio_en = scraped.get("bio_en") or row.bio_en
    row.wikipedia_url_it = scraped.get("wikipedia_url_it") or row.wikipedia_url_it
    row.wikipedia_url_en = scraped.get("wikipedia_url_en") or row.wikipedia_url_en
    row.image_cached = scraped.get("image_cached") or row.image_cached
    row.last_scraped_at = now

    status = scraped.get("status") or STATUS_ERROR
    # Se la foto c'era gia' da prima, l'esito reale e' "completo" anche se
    # QUESTO giro non ha portato un'immagine nuova.
    if status == STATUS_NO_IMAGE and row.image_cached:
        status = STATUS_OK
    row.scrape_status = status
    row.scrape_detail = scraped.get("detail")

    if status in (STATUS_BLOCKED, STATUS_ERROR):
        row.scrape_attempts = (row.scrape_attempts or 0) + 1
    else:
        row.scrape_attempts = 0

    wait = RETRY_AFTER.get(status)
    if wait is None:
        row.next_retry_at = None
    else:
        # Attesa che raddoppia sui guasti ripetuti, con un tetto a una
        # settimana: se Wikipedia ci rifiuta da giorni, insistere ogni ora
        # peggiora le cose senza aiutare nessuno.
        factor = min(2 ** max(0, (row.scrape_attempts or 1) - 1), 168)
        row.next_retry_at = now + (wait * factor if status in (STATUS_BLOCKED, STATUS_ERROR) else wait)
