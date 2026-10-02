import json

from sqlalchemy.orm import Session

from .. import models

PAGE_COUNT_SETTINGS_KEY = "page_count"

DEFAULT_PAGE_COUNT_SETTINGS = {
    "mode": "words",  # "words" or "chars" — only used for non-PDF formats (PDF is always exact)
    "words_per_page": 300,
    "chars_per_page": 1500,
}


def get_setting(db: Session, key: str, default: dict) -> dict:
    row = db.query(models.AppSetting).filter(models.AppSetting.key == key).first()
    if not row:
        return dict(default)
    try:
        return {**default, **json.loads(row.value_json)}
    except (TypeError, ValueError):
        return dict(default)


def set_setting(db: Session, key: str, value: dict) -> None:
    row = db.query(models.AppSetting).filter(models.AppSetting.key == key).first()
    if row:
        row.value_json = json.dumps(value)
    else:
        db.add(models.AppSetting(key=key, value_json=json.dumps(value)))
    db.commit()


def get_page_count_settings(db: Session) -> dict:
    return get_setting(db, PAGE_COUNT_SETTINGS_KEY, DEFAULT_PAGE_COUNT_SETTINGS)


def set_page_count_settings(db: Session, value: dict) -> dict:
    merged = {**DEFAULT_PAGE_COUNT_SETTINGS, **value}
    set_setting(db, PAGE_COUNT_SETTINGS_KEY, merged)
    return merged


# ── Biblioteche grandi ──
#
# Misurato su una biblioteca sintetica da 100.000 libri: `GET /books`
# restituisce tutto in un colpo e ci mette 9,4 secondi, per 66 MB di
# risposta. Il costo e' lineare, circa 70 microsecondi a libro — fino a
# qualche migliaio non si nota, oltre i 10.000 comincia a pesare davvero.
#
# La soglia e' un'impostazione e non una costante perche' dipende dalla
# macchina e dai gusti: un server lento la vorra' piu' bassa, e c'e' chi
# preferisce le pagine anche su una biblioteca piccola (modo "sempre").
LIBRARY_PAGINATION_KEY = "library_pagination"

DEFAULT_LIBRARY_PAGINATION = {
    # "auto" impagina solo oltre la soglia, "always" sempre, "never" mai
    # (e allora una biblioteca enorme torna lenta, ma e' una scelta
    # dichiarata invece di un limite nascosto).
    "mode": "auto",
    "threshold": 10000,
    "page_size": 200,
}


def get_library_pagination(db: Session) -> dict:
    return get_setting(db, LIBRARY_PAGINATION_KEY, DEFAULT_LIBRARY_PAGINATION)


def set_library_pagination(db: Session, value: dict) -> dict:
    merged = {**DEFAULT_LIBRARY_PAGINATION, **value}
    if merged.get("mode") not in ("auto", "always", "never"):
        merged["mode"] = DEFAULT_LIBRARY_PAGINATION["mode"]
    # Limiti di buon senso: una soglia a zero in modo "auto" equivale a
    # "always" ma per sbaglio, e una pagina da un milione non e' una pagina.
    merged["threshold"] = max(1, min(int(merged.get("threshold") or 0) or 10000, 10_000_000))
    merged["page_size"] = max(20, min(int(merged.get("page_size") or 0) or 200, 2000))
    set_setting(db, LIBRARY_PAGINATION_KEY, merged)
    return merged


def pagination_applies(db: Session, total_books: int) -> bool:
    """Se per QUESTA biblioteca, di questa dimensione, si impagina."""
    conf = get_library_pagination(db)
    if conf["mode"] == "never":
        return False
    if conf["mode"] == "always":
        return True
    return total_books > conf["threshold"]


# La pagina Ingest ha una soglia SUA, molto piu' bassa di quella della
# libreria: li' ogni voce e' una scheda con copertina, metadati e quattro
# comandi, non una riga di tabella. Duecento schede sono gia' una pagina
# pesante, e chi svuota una cartella di arretrati ne ha migliaia.
INGEST_PAGINATION_KEY = "ingest_pagination"

DEFAULT_INGEST_PAGINATION = {"mode": "auto", "threshold": 200, "page_size": 100}


def get_ingest_pagination(db: Session) -> dict:
    return get_setting(db, INGEST_PAGINATION_KEY, DEFAULT_INGEST_PAGINATION)


def set_ingest_pagination(db: Session, value: dict) -> dict:
    merged = {**DEFAULT_INGEST_PAGINATION, **value}
    if merged.get("mode") not in ("auto", "always", "never"):
        merged["mode"] = DEFAULT_INGEST_PAGINATION["mode"]
    merged["threshold"] = max(1, min(int(merged.get("threshold") or 0) or 200, 1_000_000))
    merged["page_size"] = max(10, min(int(merged.get("page_size") or 0) or 100, 1000))
    set_setting(db, INGEST_PAGINATION_KEY, merged)
    return merged


def ingest_pagination_applies(db: Session, total: int) -> bool:
    conf = get_ingest_pagination(db)
    if conf["mode"] == "never":
        return False
    if conf["mode"] == "always":
        return True
    return total > conf["threshold"]


# La pagina Autori ha anch'essa una soglia sua. Misurato con 20.000 autori:
# 180.219 nodi nel DOM e 12,6 secondi perche' una ricerca si assesti — non va
# in crash, diventa inusabile. I dati arrivano in mezzo secondo: il costo e'
# tutto nel disegnare ventimila schede insieme.
AUTHORS_PAGINATION_KEY = "authors_pagination"

DEFAULT_AUTHORS_PAGINATION = {"mode": "auto", "threshold": 500, "page_size": 200}


def get_authors_pagination(db: Session) -> dict:
    return get_setting(db, AUTHORS_PAGINATION_KEY, DEFAULT_AUTHORS_PAGINATION)


def set_authors_pagination(db: Session, value: dict) -> dict:
    merged = {**DEFAULT_AUTHORS_PAGINATION, **value}
    if merged.get("mode") not in ("auto", "always", "never"):
        merged["mode"] = DEFAULT_AUTHORS_PAGINATION["mode"]
    merged["threshold"] = max(1, min(int(merged.get("threshold") or 0) or 500, 1_000_000))
    merged["page_size"] = max(20, min(int(merged.get("page_size") or 0) or 200, 2000))
    set_setting(db, AUTHORS_PAGINATION_KEY, merged)
    return merged


# ── Tetto all'indice full-text ──
#
# L'indice contiene il testo estratto di ogni libro: su un impianto reale
# pesa 1,9 GB per 1.229 libri, cioe' circa 1,6 MB a libro. A 100.000 libri
# sarebbero 160 GB, a mezzo milione 800. Non e' una crescita che si puo'
# lasciare senza freno su un disco condiviso con le biblioteche stesse.
#
# Il tetto non cancella niente e non spegne la ricerca: ferma
# l'indicizzazione di NUOVI libri quando il file ha raggiunto la
# dimensione dichiarata, e lo dice. Quello che e' gia' indicizzato resta
# cercabile.
FULLTEXT_LIMIT_KEY = "fulltext_limit"

DEFAULT_FULLTEXT_LIMIT = {"max_gb": 10.0}


def get_fulltext_limit_gb(db: Session) -> float:
    return float(get_setting(db, FULLTEXT_LIMIT_KEY, DEFAULT_FULLTEXT_LIMIT)["max_gb"])


def set_fulltext_limit_gb(db: Session, max_gb: float) -> float:
    # 0 = nessun tetto, per chi sa quello che fa e ha il disco per farlo.
    valore = max(0.0, min(float(max_gb), 10_000.0))
    set_setting(db, FULLTEXT_LIMIT_KEY, {"max_gb": valore})
    return valore


def _fulltext_key(folder_name: str) -> str:
    return f"fulltext_enabled_{folder_name}"


def is_fulltext_enabled(db: Session, folder_name: str) -> bool:
    return get_setting(db, _fulltext_key(folder_name), {"enabled": True})["enabled"]


def set_fulltext_enabled(db: Session, folder_name: str, enabled: bool) -> None:
    set_setting(db, _fulltext_key(folder_name), {"enabled": bool(enabled)})


AUTO_WIKI_SCRAPE_KEY = "auto_wiki_scrape"


def is_auto_wiki_scrape_enabled(db: Session) -> bool:
    return get_setting(db, AUTO_WIKI_SCRAPE_KEY, {"enabled": True})["enabled"]


def set_auto_wiki_scrape_enabled(db: Session, enabled: bool) -> bool:
    enabled = bool(enabled)
    set_setting(db, AUTO_WIKI_SCRAPE_KEY, {"enabled": enabled})
    return enabled


# Feed OPDS standard (Atom/XML, Basic Auth) — vedi api/opds.py. Disattivato
# di default: è una superficie di accesso in più (credenziali dell'account
# esposte a qualunque app OPDS di terze parti chiami quell'URL) da attivare
# consapevolmente, a differenza degli altri toggle qui sopra che sono
# comportamenti interni al server. Distinto e indipendente dal protocollo
# JSON già usato dal plugin KOReader (devices.py::browse_catalog/
# catalog_sections), che resta invariato.
OPDS_FEED_KEY = "opds_feed"


def is_opds_feed_enabled(db: Session) -> bool:
    return get_setting(db, OPDS_FEED_KEY, {"enabled": False})["enabled"]


def set_opds_feed_enabled(db: Session, enabled: bool) -> bool:
    enabled = bool(enabled)
    set_setting(db, OPDS_FEED_KEY, {"enabled": enabled})
    return enabled


# Il reader web conta come dispositivo di lettura, oppure no.
#
# SPENTO di default dal 01/10/2026. Prima era acceso —
# scelta di continuita' presa quando l'impostazione e' nata — ma spento e' la
# scelta che ha senso per la maggioranza dei casi, ed e' il motivo per cui
# esiste: il reader web si usa quasi sempre per CONSULTARE — cercare un passaggio,
# rileggere una citazione, controllare un capitolo dal computer — non per
# leggere davvero. Contarlo significa due danni distinti:
#
#   - le statistiche di lettura si sporcano di sessioni da trenta secondi che
#     non sono lettura;
#   - e soprattutto la POSIZIONE del libro viene spostata. Aprire un libro sul
#     computer per controllare una frase a pagina 12 riporta il segnalibro del
#     Kindle indietro di duecento pagine, che e' un danno reale e fastidioso
#     da rimediare.
#
# Le evidenziazioni fatte dal reader web NON sono toccate da questa
# impostazione: quelle sono contenuto creato apposta, non un effetto
# collaterale del consultare.
#
# Cambiare questo valore non tocca chi l'ha gia' scelto: `get_setting` ricade
# sul default solo quando la riga non esiste. Un impianto dove qualcuno aveva
# acceso o spento l'interruttore resta come l'ha lasciato; cambia solo cosa
# trova chi non l'ha mai guardato.
WEB_READER_TRACKING_KEY = "web_reader_tracking"
DEFAULT_WEB_READER_TRACKING = {"enabled": False}


def is_web_reader_tracking_enabled(db: Session) -> bool:
    return get_setting(db, WEB_READER_TRACKING_KEY, DEFAULT_WEB_READER_TRACKING)["enabled"]


def set_web_reader_tracking_enabled(db: Session, enabled: bool) -> bool:
    enabled = bool(enabled)
    set_setting(db, WEB_READER_TRACKING_KEY, {"enabled": enabled})
    return enabled


# ── Soglia del rumore nelle statistiche ──────────────────────────────────

SESSIONI_BREVI_KEY = "stats_soglia_sessione"
DEFAULT_SESSIONI_BREVI = {"seconds": 0}


def get_soglia_sessione(db: Session) -> int:
    """
    Sotto quanti secondi una sessione di lettura non conta.

    Zero, di preimpostazione: nessun filtro. Le aperture di controllo sono
    rumore per chi CONTA le sessioni e irrilevanti per chi somma il tempo,
    e imporre a tutti una soglia che serve solo al primo caso sarebbe
    arbitrario — misurato su dati reali: il 19% delle sessioni sta
    sotto il minuto, ma vale lo 0,5% delle ore, un'ora su 193.

    Regolabile e non fissa a un minuto perche' "quanto dura un'apertura per
    sbaglio" dipende da come si legge, non dal programma.
    """
    return int(get_setting(db, SESSIONI_BREVI_KEY, DEFAULT_SESSIONI_BREVI)["seconds"])


def set_soglia_sessione(db: Session, seconds: int) -> int:
    # Un tetto a un'ora: oltre non si sta piu' togliendo rumore, si sta
    # buttando via letture vere senza accorgersene.
    valore = max(0, min(int(seconds), 3600))
    set_setting(db, SESSIONI_BREVI_KEY, {"seconds": valore})
    return valore
