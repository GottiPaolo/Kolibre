"""
Auto-scrape Wikipedia bio/photo the first time an author's name appears in
the database, gated by the global "auto_wiki_scrape" AppSetting (frontend:
Impostazioni > Integrazioni). Fired from every code path that can introduce a
brand-new author — ingest import, Calibre plugin upload/update, cross-library
copy, filesystem rescan, manual metadata edit (see call sites in api/ingest.py,
api/library_transfer.py, api/books.py, api/libraries.py).

Runs off the request thread (same daemon-thread pattern as
fulltext_index.reindex_library) so a Wikipedia round-trip never adds latency
to a book upload. `AuthorMetadata.last_scraped_at` is the "already attempted"
marker: it's set unconditionally by both this hook and the manual /refresh
endpoint whenever a scrape actually runs, but NOT by a plain manual bio edit
(PUT /authors/{name}) — so a user typing in a bio by hand doesn't
accidentally suppress a future auto-scrape for that author.
"""

import threading
from datetime import datetime

from .. import database, models
from ..logging_utils import log_message
from . import app_settings, author_scraper, author_wikidata


def maybe_trigger_wiki_scrape(author_names) -> None:
    if isinstance(author_names, str):
        author_names = [author_names]
    names = sorted({n for n in author_names if n})
    if not names:
        return

    db = database.SessionLocal()
    try:
        if not app_settings.is_auto_wiki_scrape_enabled(db):
            return
        already_attempted = {
            row.author_name
            for row in db.query(models.AuthorMetadata.author_name)
            .filter(models.AuthorMetadata.author_name.in_(names))
            .filter(models.AuthorMetadata.last_scraped_at.isnot(None))
            .all()
        }
    finally:
        db.close()

    pending = [n for n in names if n not in already_attempted]
    if not pending:
        return

    def _run():
        session = database.SessionLocal()
        url_per_autore: dict = {}
        try:
            for name in pending:
                # Re-check inside the background thread: two ingests for the
                # same brand-new author racing each other would otherwise
                # both pass the check above and scrape (and log) it twice.
                row = session.query(models.AuthorMetadata).filter(models.AuthorMetadata.author_name == name).first()
                if row and row.last_scraped_at is not None:
                    continue
                scraped = author_scraper.scrape_author(name)
                if not row:
                    row = models.AuthorMetadata(author_name=name)
                    session.add(row)
                author_scraper.apply_outcome(row, scraped, datetime.utcnow())
                session.commit()
                url = row.wikipedia_url_it or row.wikipedia_url_en
                if url:
                    url_per_autore[name] = url

            # Anagrafica da Wikidata per gli autori a cui e' stata trovata una
            # voce Wikipedia. UNA richiesta per tutti, non una per autore:
            # fetch_for_urls interroga a blocchi di venti, e importare venti
            # libri di venti autori nuovi non deve diventare venti query
            # SPARQL.
            #
            # Mancava, e si vedeva: un autore arrivato con un libro importato
            # aveva biografia e ritratto ma il pannello Wikidata vuoto, e
            # restava vuoto finche' qualcuno non lanciava il giro di massa.
            # Riscontrato in uso.
            if url_per_autore:
                dati, _non_interrogati = author_wikidata.fetch_for_urls(url_per_autore)
                adesso = datetime.utcnow()
                for nome_autore in url_per_autore:
                    riga = session.query(models.AuthorMetadata).filter(
                        models.AuthorMetadata.author_name == nome_autore
                    ).first()
                    if riga:
                        author_wikidata.apply(riga, dati.get(nome_autore), adesso)
                session.commit()

            log_message(
                "info", "authors",
                f"Auto-scrape Wikipedia completato per {len(pending)} nuovo/i autore/i "
                f"({len(url_per_autore)} con anagrafica Wikidata)",
            )
        except Exception as e:
            log_message("error", "authors", f"Auto-scrape Wikipedia fallito: {e}")
        finally:
            session.close()

    threading.Thread(target=_run, daemon=True).start()
