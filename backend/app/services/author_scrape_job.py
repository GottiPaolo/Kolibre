"""
Scaricamento Wikipedia per TUTTI gli autori che non hanno ancora dati, come
lavoro del server invece che come ciclo nel browser.

Prima questo giro non esisteva lato server: era un `for` dentro
AuthorsPage.tsx che faceva una POST /authors/{nome}/refresh per autore. Il
server vedeva N richieste scollegate e non sapeva nemmeno che esistesse una
"ricerca globale". Conseguenze reali, tutte osservate leggendo quel codice:

- bastava ricaricare o chiudere la scheda per interrompere la coda a meta',
  senza ripresa e senza traccia di cosa mancava;
- cambiando pagina il ciclo continuava (una closure async non e' legata al
  ciclo di vita di React) ma lo stato spariva, quindi al ritorno la pagina
  diceva che non stava succedendo niente;
- e siccome la guardia "sto gia' scaricando" viveva nello stato del
  componente, il rimontaggio la azzerava: si poteva lanciare un SECONDO giro
  sugli stessi autori, dimezzando di fatto la pausa di cortesia verso
  Wikipedia.

Qui invece il giro e' uno solo per tutto il server (il lock lo garantisce),
sopravvive a cambio pagina, ricarica e chiusura del browser, e il suo stato
si puo' leggere da qualsiasi scheda.

Lo stato vive in memoria: un riavvio del backend lo perde. E' una scelta, non
una dimenticanza — e' un'operazione che si rilancia in venti secondi, e
`AuthorMetadata.last_scraped_at` fa comunque da memoria vera di cosa e' gia'
stato tentato, quindi un secondo giro dopo un riavvio non riparte da zero.

Stesso schema a thread demone di author_ingest_hook, che fa questo lavoro
per i singoli autori nuovi all'import; la differenza e' che questo e'
esplicito (non passa dall'impostazione "auto_wiki_scrape": se l'utente preme
il pulsante, vuole che parta) e che sa dire a che punto e'.
"""

import threading
import time
from datetime import datetime

from .. import database, models
from ..logging_utils import log_message
from . import author_scraper, author_wikidata

# Stessa pausa che teneva il ciclo nel browser: Wikipedia non va martellata,
# e con qualche centinaio di autori la differenza fra 0 e 250 ms e' qualche
# minuto in piu' su un'operazione che tanto gira in sottofondo.
_PAUSE_BETWEEN_AUTHORS_SECONDS = 0.25

_lock = threading.Lock()
_state = {
    "running": False,
    "total": 0,
    "processed": 0,
    "current": None,
    # Distinti apposta: "errore" (rete, eccezione) e "nessun risultato"
    # (Wikipedia non ha una pagina per quel nome) sono due cose diverse, e
    # il secondo non e' un guasto da segnalare in rosso. Il ciclo nel
    # browser li confondeva — anzi, prima ancora li segnava entrambi come
    # riusciti.
    "failed": [],
    "not_found": [],
    "no_image": [],
    "started_at": None,
    "finished_at": None,
    # Compilati quando il giro si interrompe da solo perche' Wikipedia ci ha
    # rifiutati: servono alla pagina Autori per dire "riprova dopo le 18:40"
    # invece di un generico "non riuscito".
    "stopped_early": False,
    "blocked_until": None,
    "skipped": 0,
}


def status() -> dict:
    """Istantanea dello stato, sicura da leggere mentre il thread lavora."""
    with _lock:
        snapshot = dict(_state)
        snapshot["failed"] = list(_state["failed"])
        snapshot["not_found"] = list(_state["not_found"])
        snapshot["no_image"] = list(_state["no_image"])
        return snapshot


def start(names: list, skipped: int = 0) -> bool:
    """
    Avvia il giro. Torna False se ce n'e' gia' uno in corso — ed e' questo il
    punto: la guardia sta qui, dove nessun rimontaggio di componente e
    nessuna seconda scheda del browser puo' azzerarla.
    """
    with _lock:
        if _state["running"]:
            return False
        _state.update(
            running=True, total=len(names), processed=0, current=None,
            failed=[], not_found=[], no_image=[],
            started_at=datetime.utcnow().isoformat(), finished_at=None,
            stopped_early=False, blocked_until=None, skipped=skipped,
        )
    threading.Thread(target=_run, args=(list(names),), daemon=True).start()
    return True


def _scrape_one(session, name: str) -> str:
    """Esegue e registra un autore. Restituisce l'esito (vedi author_scraper)."""
    scraped = author_scraper.scrape_author(name)
    row = session.query(models.AuthorMetadata).filter(
        models.AuthorMetadata.author_name == name
    ).first()
    if not row:
        row = models.AuthorMetadata(author_name=name)
        session.add(row)
    # Unica regola per dati ed esito, condivisa con l'endpoint del singolo
    # autore e col gancio sull'import: se ognuno scrivesse a modo suo, il
    # giro dopo ripartirebbe con idee diverse a seconda di chi ha scritto
    # per ultimo.
    author_scraper.apply_outcome(row, scraped, datetime.utcnow())
    session.commit()
    return row.scrape_status


# Quanti rifiuti consecutivi bastano per concludere che non e' un caso ma un
# muro. Uno solo sarebbe troppo nervoso (capita un 429 isolato e si rientra
# subito); tre di fila su autori diversi, con i ritentativi interni gia'
# falliti, vogliono dire che continuare fa solo danno — a noi e a Wikipedia.
_BLOCKED_STREAK_TO_STOP = 3


def _run(names: list) -> None:
    session = database.SessionLocal()
    blocked_streak = 0
    stopped = False
    try:
        for i, name in enumerate(names):
            with _lock:
                _state["current"] = name
            try:
                outcome = _scrape_one(session, name)
            except Exception as e:
                session.rollback()
                outcome = author_scraper.STATUS_ERROR
                log_message("warning", "authors", f"Scraping Wikipedia fallito per '{name}': {e}")

            with _lock:
                if outcome == author_scraper.STATUS_NO_PAGE:
                    _state["not_found"].append(name)
                elif outcome == author_scraper.STATUS_NO_IMAGE:
                    _state["no_image"].append(name)
                elif outcome in (author_scraper.STATUS_ERROR, author_scraper.STATUS_BLOCKED):
                    _state["failed"].append(name)
                _state["processed"] = i + 1

            # Interruttore. Insistere mentre Wikipedia ci sta rifiutando non
            # recupera nessun autore e allunga il blocco: meglio fermarsi,
            # dirlo, e lasciare che il prossimo giro riprenda da dove siamo
            # rimasti — cosa che ora sa fare, perche' ogni autore porta con
            # se' il proprio next_retry_at.
            if outcome == author_scraper.STATUS_BLOCKED:
                blocked_streak += 1
                if blocked_streak >= _BLOCKED_STREAK_TO_STOP:
                    retry_at = datetime.utcnow() + author_scraper.RETRY_AFTER[author_scraper.STATUS_BLOCKED]
                    with _lock:
                        _state["stopped_early"] = True
                        _state["blocked_until"] = retry_at.isoformat()
                    log_message(
                        "warning", "authors",
                        f"Recupero interrotto dopo {i + 1} autori: Wikipedia sta rifiutando le richieste "
                        f"(limite). I restanti {len(names) - i - 1} verranno ripresi al prossimo avvio, "
                        f"non prima delle {retry_at.strftime('%H:%M')} UTC.",
                    )
                    stopped = True
                    break
            else:
                blocked_streak = 0

            if i < len(names) - 1:
                time.sleep(_PAUSE_BETWEEN_AUTHORS_SECONDS)

        # Anagrafica da Wikidata, in coda al giro e in un colpo solo. Qui e'
        # il posto giusto per due ragioni: a questo punto gli URL Wikipedia
        # appena trovati ci sono gia', e una manciata di query SPARQL per
        # tutti gli autori costa incomparabilmente meno che una richiesta per
        # ciascuno — che e' esattamente il modo in cui ci si fa limitare.
        try:
            _fetch_wikidata(session)
        except Exception as e:
            # Non deve far fallire il recupero delle biografie, che e' la
            # parte principale: l'anagrafica si riprende al giro dopo.
            log_message("warning", "authors", f"Anagrafica Wikidata non recuperata: {e}")

        if not stopped:
            with _lock:
                done = _state["processed"]
                failed, missing, noimg = (len(_state["failed"]), len(_state["not_found"]), len(_state["no_image"]))
            log_message(
                "info", "authors",
                f"Recupero Wikipedia completato: {done} autori esaminati, "
                f"{done - failed - missing - noimg} completi, {noimg} senza foto, "
                f"{missing} senza voce, {failed} con errori",
            )
    finally:
        session.close()
        with _lock:
            _state["running"] = False
            _state["current"] = None
            _state["finished_at"] = datetime.utcnow().isoformat()


def _fetch_wikidata(session) -> None:
    """
    Riempie genere, nazionalita', nascita, morte e occupazione per OGNI autore
    che abbia un URL Wikipedia e non sia ancora stato interrogato.

    Deliberatamente NON limitato agli autori esaminati in questo giro. Lo era,
    ed era sbagliato: il giro salta giustamente chi ha gia' biografia e foto,
    quindi su una biblioteca gia' completa non restava nessuno da arricchire e
    l'anagrafica non arrivava mai. Riscontrato in uso il giorno stesso, su un
    impianto reale: "non posso lanciare uno scaricamento perche' risultano come
    gia' presenti".

    Le due cose hanno tempi diversi e non vanno legate: la biografia si scarica
    una volta e basta, l'anagrafica e' una colonna aggiunta dopo e va recuperata
    su tutto il pregresso.
    """
    righe = session.query(models.AuthorMetadata).filter(
        models.AuthorMetadata.wikidata_fetched_at.is_(None),
    ).all()
    url_per_autore = {
        r.author_name: (r.wikipedia_url_it or r.wikipedia_url_en)
        for r in righe
        if r.wikipedia_url_it or r.wikipedia_url_en
    }
    if not url_per_autore:
        return

    dati, non_interrogati = author_wikidata.fetch_for_urls(url_per_autore)
    now = datetime.utcnow()
    for r in righe:
        if r.author_name not in url_per_autore:
            continue
        # Chi stava in un blocco fallito NON viene toccato: resta senza
        # wikidata_fetched_at e il prossimo giro lo riprende. Marcarlo
        # significherebbe trasformare un 429 di passaggio in un'esclusione
        # definitiva — ed e' esattamente quello che succedeva.
        if r.author_name in non_interrogati:
            continue
        author_wikidata.apply(r, dati.get(r.author_name), now)
    session.commit()
    with _lock:
        _state["wikidata_arricchiti"] = len(dati)
    interrogati = len(url_per_autore) - len(non_interrogati)
    log_message("info", "authors",
                f"Anagrafica Wikidata: {len(dati)}/{interrogati} autori arricchiti"
                + (f"; {len(non_interrogati)} non interrogati (richiesta fallita), "
                   f"verranno ripresi al prossimo giro" if non_interrogati else ""))
