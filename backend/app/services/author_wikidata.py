"""
Anagrafica degli autori da Wikidata: genere, nazionalita', nascita, morte,
occupazione.

Perche' Wikidata e non una ricerca per nome: gli omonimi. Cercare "Emile Henry"
su un catalogo restituisce persone diverse e non c'e' modo automatico di
sapere quale sia la giusta. Kolibre pero' ha gia' fatto quella fatica quando
ha trovato la biografia: `wikipedia_url_it/en` punta a UN articolo preciso, e
da un articolo all'elemento Wikidata il passaggio e' meccanico (la proprieta'
`schema:about` del sitelink). Si eredita gratis una disambiguazione gia' fatta.

Perche' SPARQL e non l'API per singola entita': una richiesta ogni autore
significa seicento richieste, cioe' farsi limitare a meta' strada — e' successo
davvero, due volte, durante l'indagine che ha portato a questo file. Con SPARQL
si chiedono venti autori per volta in una richiesta sola.

Copertura misurata sulla biblioteca reale (1.216 libri, 692 autori), 19/09/2026:
  autori con URL Wikipedia    529
  agganciati a Wikidata       511  (97%)
  di cui con genere           99%      nazionalita'  97%
         nascita              97%      morte         72%  (i mancanti sono i viventi)
         occupazione          99%
"""

import time
from datetime import datetime
from typing import Optional

import httpx

from ..logging_utils import log_message
from .author_scraper import USER_AGENT

SPARQL_URL = "https://query.wikidata.org/sparql"

# Venti per volta. Non e' prudenza generica: con 454 autori in una richiesta
# sola l'endpoint risponde 200 e poi tronca il JSON a meta' (misurato: si
# rompeva a 9,6 MB), e con 50 la connessione cadeva a intermittenza.
_CHUNK = 20
_TIMEOUT = 90
# Stessi valori dello scraper Wikipedia: un 429 e' passeggero e va riprovato,
# non subito in faccia al server.
_MAX_ATTEMPTS = 3
_RETRY_BASE_SECONDS = 2.0
_MAX_RETRY_AFTER_SECONDS = 30.0


def _query(urls: list) -> Optional[list]:
    """Risultati del blocco, oppure None se la richiesta NON e' riuscita.

    La distinzione fra None e lista vuota e' quella che conta: vuota significa
    "Wikidata non conosce questi autori", None significa "non lo sappiamo". Il
    chiamante deve trattarle in modo opposto, o un rifiuto momentaneo diventa
    un "gia' interrogato, non c'era nulla" permanente.
    """
    values = " ".join(f"<{u}>" for u in urls)
    query = f"""
SELECT ?art ?item ?genereLabel ?cittLabel ?nascita ?morte ?occLabel WHERE {{
  VALUES ?art {{ {values} }}
  ?art schema:about ?item .
  OPTIONAL {{ ?item wdt:P21 ?genere. }}
  OPTIONAL {{ ?item wdt:P27 ?citt. }}
  OPTIONAL {{ ?item wdt:P569 ?nascita. }}
  OPTIONAL {{ ?item wdt:P570 ?morte. }}
  OPTIONAL {{ ?item wdt:P106 ?occ. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "it,en". }}
}}
"""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = httpx.post(
                SPARQL_URL, timeout=_TIMEOUT,
                headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
                data={"query": query, "format": "json"},
            )
        except Exception as e:
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BASE_SECONDS * attempt)
                continue
            log_message("warning", "authors",
                        f"Wikidata: blocco di {len(urls)} autori non recuperato ({type(e).__name__})")
            return None
        if resp.status_code == 200:
            try:
                return resp.json()["results"]["bindings"]
            except Exception:
                # Risposta troncata: il JSON non si chiude. Non e' un "non
                # trovato", e' una richiesta fallita.
                if attempt < _MAX_ATTEMPTS:
                    time.sleep(_RETRY_BASE_SECONDS * attempt)
                    continue
                log_message("warning", "authors",
                            f"Wikidata: risposta troncata su un blocco di {len(urls)} autori")
                return None
        if resp.status_code in (429, 502, 503, 504) and attempt < _MAX_ATTEMPTS:
            raw = resp.headers.get("retry-after")
            pausa = _RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            if raw:
                try:
                    pausa = min(float(raw), _MAX_RETRY_AFTER_SECONDS)
                except ValueError:
                    pass
            time.sleep(pausa)
            continue
        log_message("warning", "authors",
                    f"Wikidata: HTTP {resp.status_code} su un blocco di {len(urls)} autori"
                    + (" — limite di richieste" if resp.status_code == 429 else ""))
        return None


def fetch_for_urls(url_by_author: dict) -> tuple:
    """
    {nome autore: url wikipedia} -> ({nome autore: dati}, {nomi non interrogati}).

    Il secondo insieme e' il punto: sono gli autori i cui blocchi NON sono
    riusciti, e che quindi non vanno marcati come gia' interrogati. Senza
    questa distinzione un singolo 429 — che capita, e capita spesso su
    seicento autori — li escludeva per sempre dai giri successivi.
    """
    autore_per_url = {u: n for n, u in url_by_author.items() if u}
    urls = sorted(autore_per_url)
    out: dict = {}
    non_interrogati: set = set()

    for i in range(0, len(urls), _CHUNK):
        blocco = urls[i:i + _CHUNK]
        bindings = _query(blocco)
        if bindings is None:
            non_interrogati.update(autore_per_url[u] for u in blocco)
            continue
        for b in bindings:
            nome = autore_per_url.get(b["art"]["value"])
            if not nome:
                continue
            d = out.setdefault(nome, {
                "wikidata_qid": b["item"]["value"].rsplit("/", 1)[-1],
                "gender": None, "nationality": set(),
                "birth_date": None, "death_date": None, "occupations": set(),
            })
            if "genereLabel" in b:
                d["gender"] = b["genereLabel"]["value"]
            if "cittLabel" in b:
                d["nationality"].add(b["cittLabel"]["value"])
            if "nascita" in b and not d["birth_date"]:
                d["birth_date"] = b["nascita"]["value"][:10]
            if "morte" in b and not d["death_date"]:
                d["death_date"] = b["morte"]["value"][:10]
            if "occLabel" in b:
                d["occupations"].add(b["occLabel"]["value"])

    # Gli insiemi diventano stringhe ordinate: una colonna di testo basta, e
    # non vale una tabella a parte finche' non serve interrogarle per valore.
    for d in out.values():
        d["nationality"] = "; ".join(sorted(d["nationality"])) or None
        d["occupations"] = "; ".join(sorted(d["occupations"])) or None
    return out, non_interrogati


def apply(row, data: Optional[dict], now: datetime) -> None:
    """
    Riempie l'anagrafica su una riga AuthorMetadata. `data` None significa
    "interrogato, Wikidata non lo conosce": si marca comunque la data, cosi'
    non lo si richiede a ogni giro.

    RIEMPIE SOLO I CAMPI VUOTI, mai sovrascrive. E' la regola che rende
    permanenti le correzioni fatte a mano senza bisogno di marcare i singoli
    campi come "modificati dall'utente": se un valore c'e' gia', per
    definizione qualcuno lo ha messo — un giro precedente o una persona — e in
    entrambi i casi non tocca a questo giro cambiarlo.

    Il prezzo, dichiarato: un dato corretto SU WIKIDATA dopo che noi abbiamo
    gia' preso quello sbagliato non arriva piu' da solo. Per quello c'e' il
    pulsante di ricarica sul singolo autore, che e' un atto esplicito su un
    autore solo; e c'e' sempre la possibilita' di svuotare il campo a mano per
    farlo riprendere al giro dopo.
    """
    row.wikidata_fetched_at = now
    if not data:
        return

    # Persona DIVERSA da quella che avevamo: allora i vecchi valori non sono
    # "dati da rispettare", sono i dati di qualcun altro, e vanno sostituiti
    # per intero. Succede per davvero, ed e' il motivo per cui esiste il
    # pulsante che permette di incollare a mano l'indirizzo Wikipedia giusto:
    # la ricerca per nome aveva preso un omonimo. Tenere il genere o le date
    # del omonimo perche' "il campo non era vuoto" sarebbe il contrario di
    # quello che chiede chi ha appena corretto l'identificazione.
    #
    # Stesso QID invece: si resta alla regola generale, si riempie solo il
    # vuoto. Le correzioni fatte a mano sulla persona GIUSTA restano.
    qid_nuovo = data.get("wikidata_qid")
    persona_diversa = bool(qid_nuovo) and bool(row.wikidata_qid) and row.wikidata_qid != qid_nuovo

    for campo in ("wikidata_qid", "gender", "nationality",
                  "birth_date", "death_date", "occupations"):
        if persona_diversa or not getattr(row, campo, None):
            setattr(row, campo, data.get(campo))
