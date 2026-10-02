import asyncio
import logging
import os
from contextlib import asynccontextmanager

import sqlalchemy as sa
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from . import config, models, database, auth
from .logging_utils import log_message
from .calibre.connection import LibraryDeletedError, LibraryMissingError
from .calibre.library import purge_expired_book_lists
from .calibre.write_queue import CalibreWriteQueue, WriteJob, retry_one_pending, serialize_pending
from .services.watcher import start_watcher, stop_watcher
from .services import stats_service, author_stats_service, highlight_position, widowed_highlights, stardict_service
from .api import auth as auth_router
from .api import users as users_router
from .api import libraries as libraries_router
from .api import ingest as ingest_router
from .api import books as books_router
from .api import interventions as interventions_router
from .api import custom_columns as custom_columns_router
from .api import entities as entities_router
from .api import authors as authors_router
from .api import devices as devices_router
from .api import annotations as annotations_router
from .api import tools as tools_router
from .api import settings as settings_router
from .api import fulltext as fulltext_router
from .api import library_transfer as library_transfer_router
from .api import stats as stats_router
from .api import opds as opds_router
from .api import dictionaries as dictionaries_router
from .api import vocabulary as vocabulary_router

# pypdf logga un avviso per OGNI font CFF Type1 che incontra senza fontTools
# installato ("fontTools is required to fully parse the encoding…"). È
# innocuo — il testo viene estratto lo stesso — ma si ripete per ogni pagina
# di ogni PDF: una riindicizzazione full-text di una libreria vera ne ha
# prodotte migliaia, seppellendo i log del backend e facendolo sembrare
# impazzito (riscontrato in uso). Gli errori veri di pypdf restano visibili.
logging.getLogger("pypdf").setLevel(logging.ERROR)


def _migra_frazione_lettura() -> None:
    """
    Aggiunge `fraction_read` alle due tabelle delle sessioni.

    Sta fuori da _ensure_schema_migrations, e non dentro, per una ragione
    imparata a spese: quella funzione e' una sequenza lunga dove il primo
    passo che fallisce salta TUTTI quelli dopo, e l'avvio del server la
    ingoia loggando un avviso. Il risultato e' un database migrato a meta'
    che risponde 500 su ogni statistica, senza che niente lo dica a
    chiaro. Una colonna che serve a una funzione nuova non deve dipendere
    dalla riuscita di migrazioni che non c'entrano.
    """
    with database.engine.connect() as conn:
        for tabella in ("reading_sessions", "orphan_reading_sessions"):
            colonne = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({tabella})")}
            if colonne and "fraction_read" not in colonne:
                conn.exec_driver_sql(f"ALTER TABLE {tabella} ADD COLUMN fraction_read FLOAT")
                log_message("info", "system", f"Migrated {tabella}: added missing 'fraction_read' column.")
        conn.commit()


def _migra_posizioni_per_utente() -> None:
    """
    Aggiunge `user_id` a reading_positions e book_reading_coverage, e sposta
    il vincolo di unicita' da (biblioteca, libro) a (utente, biblioteca,
    libro).

    Perche' serve una RICOSTRUZIONE e non un ALTER: SQLite sa aggiungere una
    colonna, non sa cambiare un vincolo di unicita' dichiarato nella CREATE
    TABLE. Lasciando il vincolo vecchio, due persone non potrebbero avere una
    posizione sullo stesso libro — cioe' proprio la cosa che questa migrazione
    esiste per permettere. Quindi: tabella nuova, copia, scambio.

    L'attribuzione non e' un'ipotesi dove si puo' evitare che lo sia. Una
    posizione spinta da un dispositivo appartiene a chi possiede quel
    dispositivo; una copertura appartiene a chi ha le sessioni di lettura su
    quel libro. Solo dove non c'e' nessuno dei due indizi si ricade sul primo
    amministratore — che oggi, con un impianto a utente singolo, e' comunque
    la risposta giusta.

    Sta fuori da _ensure_schema_migrations per la ragione imparata a spese e
    scritta sopra: quella e' una sequenza lunga dove il primo passo che
    fallisce salta tutti quelli dopo.
    """
    with database.engine.connect() as conn:
        primo_admin = conn.exec_driver_sql(
            "SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if not primo_admin:
            primo_admin = conn.exec_driver_sql("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        # Nessun utente: e' un database appena creato, create_all fara' le
        # tabelle gia' nella forma nuova e non c'e' niente da migrare.
        if not primo_admin:
            return
        ripiego = primo_admin[0]

        colonne = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(reading_positions)")}
        if colonne and "user_id" not in colonne:
            conn.exec_driver_sql("""
                CREATE TABLE reading_positions_nuova (
                    id INTEGER NOT NULL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    library VARCHAR NOT NULL DEFAULT 'default',
                    calibre_book_id INTEGER NOT NULL,
                    device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
                    device_name VARCHAR,
                    percentage FLOAT NOT NULL,
                    progress VARCHAR NOT NULL,
                    coverage_percent FLOAT,
                    updated_at DATETIME,
                    UNIQUE (user_id, library, calibre_book_id)
                )
            """)
            conn.exec_driver_sql(f"""
                INSERT INTO reading_positions_nuova
                    (id, user_id, library, calibre_book_id, device_id, device_name,
                     percentage, progress, coverage_percent, updated_at)
                SELECT p.id,
                       COALESCE((SELECT d.user_id FROM devices d WHERE d.id = p.device_id), {ripiego}),
                       p.library, p.calibre_book_id, p.device_id, p.device_name,
                       p.percentage, p.progress, p.coverage_percent, p.updated_at
                FROM reading_positions p
            """)
            conn.exec_driver_sql("DROP TABLE reading_positions")
            conn.exec_driver_sql("ALTER TABLE reading_positions_nuova RENAME TO reading_positions")
            conn.exec_driver_sql("CREATE INDEX ix_reading_positions_user_id ON reading_positions (user_id)")
            log_message("info", "system", "reading_positions: aggiunto user_id e rifatto il vincolo di unicita'.")

        colonne = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(book_reading_coverage)")}
        if colonne and "user_id" not in colonne:
            conn.exec_driver_sql("""
                CREATE TABLE book_reading_coverage_nuova (
                    id INTEGER NOT NULL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    library VARCHAR NOT NULL DEFAULT 'default',
                    calibre_book_id INTEGER NOT NULL,
                    bins BLOB NOT NULL,
                    coverage FLOAT NOT NULL DEFAULT 0.0,
                    updated_at DATETIME,
                    UNIQUE (user_id, library, calibre_book_id)
                )
            """)
            conn.exec_driver_sql(f"""
                INSERT INTO book_reading_coverage_nuova
                    (id, user_id, library, calibre_book_id, bins, coverage, updated_at)
                SELECT c.id,
                       COALESCE((SELECT s.user_id FROM reading_sessions s
                                 WHERE s.library = c.library
                                   AND s.calibre_book_id = c.calibre_book_id
                                 LIMIT 1), {ripiego}),
                       c.library, c.calibre_book_id, c.bins, c.coverage, c.updated_at
                FROM book_reading_coverage c
            """)
            conn.exec_driver_sql("DROP TABLE book_reading_coverage")
            conn.exec_driver_sql("ALTER TABLE book_reading_coverage_nuova RENAME TO book_reading_coverage")
            conn.exec_driver_sql("CREATE INDEX ix_book_reading_coverage_user_id ON book_reading_coverage (user_id)")
            log_message("info", "system", "book_reading_coverage: aggiunto user_id e rifatto il vincolo di unicita'.")

        colonne = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(stats_cache)")}
        if colonne and "user_id" not in colonne:
            # Stessa ricostruzione, stessa ragione: `library` era UNIQUE da
            # sola, quindi due utenti non potrebbero avere la propria cache
            # della stessa biblioteca.
            #
            # Le righe vecchie si buttano invece di attribuirle, ed e' una
            # scelta: erano aggregati calcolati su TUTTE le sessioni insieme,
            # quindi non appartengono a nessuno in particolare. Darle al
            # primo amministratore vorrebbe dire mostrargli numeri gonfiati
            # fino al primo ricalcolo. Meglio nessuna cache: l'endpoint
            # ricade sul calcolo dal vivo, e il ciclo di sfondo la rifa'
            # giusta entro pochi secondi dall'avvio.
            conn.exec_driver_sql("DROP TABLE stats_cache")
            conn.exec_driver_sql("""
                CREATE TABLE stats_cache (
                    id INTEGER NOT NULL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    library VARCHAR NOT NULL,
                    summary_json TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    timeline_json TEXT NOT NULL,
                    computed_at DATETIME,
                    UNIQUE (user_id, library)
                )
            """)
            conn.exec_driver_sql("CREATE INDEX ix_stats_cache_user_id ON stats_cache (user_id)")
            log_message("info", "system",
                        "stats_cache: rifatta per utente (le righe vecchie erano aggregate su tutti).")

        conn.commit()


def _ensure_schema_migrations() -> None:
    """
    create_all() (below, in lifespan) only ever creates TABLES that don't
    exist yet — it never alters an existing one, so a column added to a
    model after app.db was first created (e.g. sync_queue.library, added
    for multi-library device queueing) silently never appears in a real,
    already-running deployment's database. That surfaced as a genuine 500 on
    GET /api/devices ("no such column: sync_queue.library") on a database
    that predated the column. ADD COLUMN is idempotent-checked here so this
    runs safely on every startup, including ones that already have it.
    """
    with database.engine.connect() as conn:
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(sync_queue)")}
        if "library" not in existing:
            conn.exec_driver_sql("ALTER TABLE sync_queue ADD COLUMN library VARCHAR NOT NULL DEFAULT 'default'")
            conn.commit()
            log_message("info", "system", "Migrated sync_queue: added missing 'library' column.")

        # Permessi (28/09/2026). Le colonne nascono con il valore piu'
        # prudente — nessun permesso — e la migrazione qui sotto
        # (_migra_permessi) li assegna guardando chi c'era gia'.
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)")}
        for col, ddl in (
            ("is_founder", "ALTER TABLE users ADD COLUMN is_founder BOOLEAN NOT NULL DEFAULT 0"),
            ("can_create_libraries", "ALTER TABLE users ADD COLUMN can_create_libraries BOOLEAN NOT NULL DEFAULT 0"),
            ("can_create_users", "ALTER TABLE users ADD COLUMN can_create_users BOOLEAN NOT NULL DEFAULT 0"),
            ("can_manage_permissions", "ALTER TABLE users ADD COLUMN can_manage_permissions BOOLEAN NOT NULL DEFAULT 0"),
            ("can_register_devices", "ALTER TABLE users ADD COLUMN can_register_devices BOOLEAN NOT NULL DEFAULT 1"),
            ("can_edit_authors", "ALTER TABLE users ADD COLUMN can_edit_authors BOOLEAN NOT NULL DEFAULT 0"),
        ):
            if col not in existing:
                conn.exec_driver_sql(ddl)
                log_message("info", "system", f"Migrated users: added missing '{col}' column.")

        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(libraries)")}
        if "owner_id" not in existing:
            conn.exec_driver_sql("ALTER TABLE libraries ADD COLUMN owner_id INTEGER")
            log_message("info", "system", "Migrated libraries: added missing 'owner_id' column.")

        # Sync protocol v2 (cantiere A1): device-level plugin/telemetry fields.
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(devices)")}
        device_columns = (
            ("plugin_version", "ALTER TABLE devices ADD COLUMN plugin_version VARCHAR"),
            ("last_seen_at", "ALTER TABLE devices ADD COLUMN last_seen_at DATETIME"),
            ("delete_policy", "ALTER TABLE devices ADD COLUMN delete_policy VARCHAR NOT NULL DEFAULT 'ask'"),
            # Spazio del volume dei libri, dal plugin v0.6.15 (storage_used
            # c'era gia' e nessuno l'aveva mai riempito).
            ("storage_total", "ALTER TABLE devices ADD COLUMN storage_total INTEGER"),
            ("storage_available", "ALTER TABLE devices ADD COLUMN storage_available INTEGER"),
        )
        for col, ddl in device_columns:
            if col not in existing:
                conn.exec_driver_sql(ddl)
                log_message("info", "system", f"Migrated devices: added missing '{col}' column.")

        # Sync protocol v2: device_books becomes the per-device DESIRED state.
        # Pre-existing rows were only ever written as "confirmed on device",
        # so they default to 'synced'.
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(device_books)")}
        device_book_columns = (
            ("status", "ALTER TABLE device_books ADD COLUMN status VARCHAR NOT NULL DEFAULT 'synced'"),
            ("delivery_hash", "ALTER TABLE device_books ADD COLUMN delivery_hash VARCHAR"),
            ("device_path", "ALTER TABLE device_books ADD COLUMN device_path VARCHAR"),
            ("device_pages", "ALTER TABLE device_books ADD COLUMN device_pages INTEGER"),
            ("device_pages_updated_at", "ALTER TABLE device_books ADD COLUMN device_pages_updated_at DATETIME"),
            ("requested_by", "ALTER TABLE device_books ADD COLUMN requested_by VARCHAR"),
            ("last_error", "ALTER TABLE device_books ADD COLUMN last_error VARCHAR"),
            ("updated_at", "ALTER TABLE device_books ADD COLUMN updated_at DATETIME"),
            ("removed_at", "ALTER TABLE device_books ADD COLUMN removed_at DATETIME"),
            ("created_at", "ALTER TABLE device_books ADD COLUMN created_at DATETIME"),
        )
        created_at_added = "created_at" not in existing
        for col, ddl in device_book_columns:
            if col not in existing:
                conn.exec_driver_sql(ddl)
                log_message("info", "system", f"Migrated device_books: added missing '{col}' column.")
        if created_at_added:
            # SQLite's ADD COLUMN can't backfill a dynamic default for rows
            # that already existed — synced_at is the closest real value we
            # have for them (better than leaving "Aggiunto" blank).
            conn.exec_driver_sql("UPDATE device_books SET created_at = synced_at WHERE created_at IS NULL")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_device_books_status ON device_books (status)")
        conn.commit()

        # "Da rivedere" page (Cantiere: pagina dettagliata libri da rivedere):
        # unifies the previously device-local-only "nessun match" case with
        # the already-server-side "match found but skipped" case, plus a
        # web-queued pending action applied by the plugin on its next sync.
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(device_flagged_books)")}
        flagged_book_columns = (
            ("match_status", "ALTER TABLE device_flagged_books ADD COLUMN match_status VARCHAR NOT NULL DEFAULT 'flagged_started'"),
            ("local_percent_read", "ALTER TABLE device_flagged_books ADD COLUMN local_percent_read FLOAT"),
            ("local_highlights_count", "ALTER TABLE device_flagged_books ADD COLUMN local_highlights_count INTEGER"),
            ("pending_action", "ALTER TABLE device_flagged_books ADD COLUMN pending_action VARCHAR"),
            ("pending_action_library", "ALTER TABLE device_flagged_books ADD COLUMN pending_action_library VARCHAR"),
            ("pending_action_calibre_book_id", "ALTER TABLE device_flagged_books ADD COLUMN pending_action_calibre_book_id INTEGER"),
            ("pending_action_format", "ALTER TABLE device_flagged_books ADD COLUMN pending_action_format VARCHAR"),
            # Device-reported hash of the local file, needed by the 'pair'
            # action to record it against the chosen book even when it never
            # matches the server's own copy byte-for-byte.
            ("file_hash", "ALTER TABLE device_flagged_books ADD COLUMN file_hash VARCHAR"),
            # Autore indovinato da nome file/cartella lato plugin KOReader
            # (redesign vista Dispositivo) — righe segnalate da un plugin più
            # vecchio di questo campo restano semplicemente NULL.
            ("local_author", "ALTER TABLE device_flagged_books ADD COLUMN local_author VARCHAR"),
        )
        for col, ddl in flagged_book_columns:
            if col not in existing:
                conn.exec_driver_sql(ddl)
                log_message("info", "system", f"Migrated device_flagged_books: added missing '{col}' column.")
        conn.commit()

        # Distinguishes a hash computed from the server's own file
        # (trustworthy) from one merely recorded from a device's own report
        # (manual/fuzzy "Accoppia" — never independently verified) — see
        # book_hash_service.py. Existing rows predate this distinction and
        # were all computed the trustworthy way, hence DEFAULT 1.
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(book_hashes)")}
        if "verified" not in existing:
            conn.exec_driver_sql("ALTER TABLE book_hashes ADD COLUMN verified BOOLEAN NOT NULL DEFAULT 1")
            log_message("info", "system", "Migrated book_hashes: added missing 'verified' column.")
        if "content_fingerprint" not in existing:
            conn.exec_driver_sql("ALTER TABLE book_hashes ADD COLUMN content_fingerprint VARCHAR")
            log_message("info", "system", "Migrated book_hashes: added missing 'content_fingerprint' column.")
        conn.commit()

        # Real reading-stats pipeline (was dead code before — see
        # stats_service.py): reading_sessions predates the `library` column
        # every other book-identifying table already requires.
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(reading_sessions)")}
        if "library" not in existing:
            conn.exec_driver_sql("ALTER TABLE reading_sessions ADD COLUMN library VARCHAR NOT NULL DEFAULT 'default'")
            log_message("info", "system", "Migrated reading_sessions: added missing 'library' column.")
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(reading_positions)")}
        if "coverage_percent" not in existing:
            conn.exec_driver_sql("ALTER TABLE reading_positions ADD COLUMN coverage_percent FLOAT")
            log_message("info", "system", "Migrated reading_positions: added missing 'coverage_percent' column.")
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(reading_sessions)")}
        if "source" not in existing:
            conn.exec_driver_sql("ALTER TABLE reading_sessions ADD COLUMN source VARCHAR NOT NULL DEFAULT 'koreader'")
            log_message("info", "system", "Migrated reading_sessions: added missing 'source' column.")
        conn.commit()

        # Highlight.source: explicit provenance ('device'/'web'/'calibre'),
        # previously only inferable from device_id/cfi_start being set or not.
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(highlights)")}
        source_added = "source" not in existing
        annot_id_added = "annot_id" not in existing
        if source_added:
            conn.exec_driver_sql("ALTER TABLE highlights ADD COLUMN source VARCHAR NOT NULL DEFAULT 'web'")
            log_message("info", "system", "Migrated highlights: added missing 'source' column.")
        if annot_id_added:
            conn.exec_driver_sql("ALTER TABLE highlights ADD COLUMN annot_id VARCHAR")
            log_message("info", "system", "Migrated highlights: added missing 'annot_id' column.")
        if source_added:
            # Best-effort backfill for rows that already existed: a device_id
            # means it came from KOReader sync; everything else was either
            # web-created or manual, both already defaulting to 'web'.
            conn.exec_driver_sql("UPDATE highlights SET source = 'device' WHERE device_id IS NOT NULL")
        if "position_status" not in existing:
            conn.exec_driver_sql("ALTER TABLE highlights ADD COLUMN position_status VARCHAR")
            log_message("info", "system", "Migrated highlights: added missing 'position_status' column.")
        conn.commit()

        # Chart builder v2 (Statistiche → Grafici personalizzati): optional
        # secondary grouping/series, its bar mode (grouped/stacked), and
        # persisted client-side filters — see SavedChart's own docstring for
        # why filters is a JSON blob while the rest stayed typed columns.
        # Pre-existing rows come back NULL for all three; the API layer
        # (_serialize_chart) and the frontend both already treat NULL the
        # same as "no secondary grouping / grouped mode / no filters".
        # v3 adds sort_by/sort_order (NULL = legacy ordering policy, see
        # SavedChart's own v3 docstring) — metric/filters_json's richer v3
        # shapes reuse the same untyped columns, no migration needed there.
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(saved_charts)")}
        saved_chart_columns = (
            ("group_by_secondary", "ALTER TABLE saved_charts ADD COLUMN group_by_secondary VARCHAR"),
            ("chart_mode", "ALTER TABLE saved_charts ADD COLUMN chart_mode VARCHAR NOT NULL DEFAULT 'grouped'"),
            ("filters_json", "ALTER TABLE saved_charts ADD COLUMN filters_json TEXT"),
            ("sort_by", "ALTER TABLE saved_charts ADD COLUMN sort_by VARCHAR"),
            ("sort_order", "ALTER TABLE saved_charts ADD COLUMN sort_order VARCHAR"),
        )
        for col, ddl in saved_chart_columns:
            if col not in existing:
                conn.exec_driver_sql(ddl)
                log_message("info", "system", f"Migrated saved_charts: added missing '{col}' column.")
        conn.commit()

        # Vocabulary Builder: on-demand dictionary lookup (services/
        # dictionary_service.py) — see VocabularyEntry's own docstring for
        # why these are never auto-populated on import.
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(vocabulary_entries)")}
        vocabulary_columns = (
            ("definition", "ALTER TABLE vocabulary_entries ADD COLUMN definition TEXT"),
            ("definition_source", "ALTER TABLE vocabulary_entries ADD COLUMN definition_source VARCHAR"),
            ("definition_fetched_at", "ALTER TABLE vocabulary_entries ADD COLUMN definition_fetched_at DATETIME"),
        )
        for col, ddl in vocabulary_columns:
            if col not in existing:
                conn.exec_driver_sql(ddl)
                log_message("info", "system", f"Migrated vocabulary_entries: added missing '{col}' column.")
        conn.commit()

        # Ingest page: editor esteso (serie/lingua/isbn) + copertina reale
        # estratta dall'EPUB (vedi services/metadata_parser.py e
        # services/watcher.py::stage_ingest_file).
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(ingested_books)")}
        ingested_book_columns = (
            ("series", "ALTER TABLE ingested_books ADD COLUMN series VARCHAR"),
            ("series_index", "ALTER TABLE ingested_books ADD COLUMN series_index FLOAT"),
            ("language", "ALTER TABLE ingested_books ADD COLUMN language VARCHAR"),
            ("isbn", "ALTER TABLE ingested_books ADD COLUMN isbn VARCHAR"),
        )
        for col, ddl in ingested_book_columns:
            if col not in existing:
                conn.exec_driver_sql(ddl)
                log_message("info", "system", f"Migrated ingested_books: added missing '{col}' column.")
        conn.commit()

        # Esito dello scraping autori, per non ritentare alla cieca — vedi
        # models.AuthorMetadata per cosa significa ciascuno stato.
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(author_metadata)")}
        author_meta_columns = (
            ("scrape_status", "ALTER TABLE author_metadata ADD COLUMN scrape_status VARCHAR"),
            ("scrape_detail", "ALTER TABLE author_metadata ADD COLUMN scrape_detail VARCHAR"),
            ("scrape_attempts", "ALTER TABLE author_metadata ADD COLUMN scrape_attempts INTEGER NOT NULL DEFAULT 0"),
            ("next_retry_at", "ALTER TABLE author_metadata ADD COLUMN next_retry_at DATETIME"),
            # Anagrafica da Wikidata — vedi models.AuthorMetadata.
            ("wikidata_qid", "ALTER TABLE author_metadata ADD COLUMN wikidata_qid VARCHAR"),
            ("gender", "ALTER TABLE author_metadata ADD COLUMN gender VARCHAR"),
            ("nationality", "ALTER TABLE author_metadata ADD COLUMN nationality VARCHAR"),
            ("birth_date", "ALTER TABLE author_metadata ADD COLUMN birth_date VARCHAR"),
            ("death_date", "ALTER TABLE author_metadata ADD COLUMN death_date VARCHAR"),
            ("occupations", "ALTER TABLE author_metadata ADD COLUMN occupations VARCHAR"),
            ("wikidata_fetched_at", "ALTER TABLE author_metadata ADD COLUMN wikidata_fetched_at DATETIME"),
        )
        for col, ddl in author_meta_columns:
            if col not in existing:
                conn.exec_driver_sql(ddl)
                log_message("info", "system", f"Migrated author_metadata: added missing '{col}' column.")
        if "scrape_status" not in existing:
            # Righe gia' esistenti: si deduce l'esito da cio' che contengono,
            # cosi' il primo giro dopo l'aggiornamento non riparte da zero su
            # seicento autori gia' scaricati.
            conn.exec_driver_sql(
                "UPDATE author_metadata SET scrape_status = CASE "
                "  WHEN image_cached IS NOT NULL THEN 'ok' "
                "  WHEN bio_it IS NOT NULL OR bio_en IS NOT NULL THEN 'no_image' "
                "  WHEN last_scraped_at IS NOT NULL THEN 'no_page' "
                "  ELSE NULL END"
            )
        conn.commit()

        # Indici sulle colonne su cui il progetto filtra sempre. Le tabelle
        # sono nate con il solo indice sulla chiave primaria, quindi ogni
        # "quante evidenziazioni ha questo libro?" e ogni finestra temporale
        # delle statistiche facevano una scansione completa: misurato su una
        # libreria da 1.229 libri, il conteggio evidenziazioni per la pagina
        # Dispositivi passa da 717 ms a 8 ms. Costo: qualche centinaio di KB
        # e una scrittura marginalmente piu' lenta, su tabelle che si leggono
        # ordini di grandezza piu' spesso di quanto si scrivano.
        #
        # deleted_at nell'indice delle evidenziazioni perche' la cancellazione
        # e' logica: ogni query utile porta con se' "deleted_at IS NULL", e
        # tenerla dentro rende l'indice copertura sufficiente per il conteggio.
        for ddl in (
            "CREATE INDEX IF NOT EXISTS ix_highlights_book ON highlights (library, calibre_book_id, deleted_at)",
            "CREATE INDEX IF NOT EXISTS ix_reading_sessions_book ON reading_sessions (library, calibre_book_id)",
            "CREATE INDEX IF NOT EXISTS ix_reading_sessions_start ON reading_sessions (start_time)",
            # Le tre tabelle su cui book_hash_service risolve un hash
            # KOReader, in cascata, a ogni annotazione e a ogni posizione
            # che arriva da un dispositivo.
            "CREATE INDEX IF NOT EXISTS ix_book_hashes_file_hash ON book_hashes (file_hash)",
            "CREATE INDEX IF NOT EXISTS ix_book_hash_history_file_hash ON book_hash_history (file_hash)",
            "CREATE INDEX IF NOT EXISTS ix_device_books_delivery_hash ON device_books (device_id, delivery_hash)",
            "CREATE INDEX IF NOT EXISTS ix_reading_positions_book ON reading_positions (library, calibre_book_id)",
            "CREATE INDEX IF NOT EXISTS ix_device_books_book ON device_books (library, calibre_book_id)",
        ):
            conn.exec_driver_sql(ddl)
        conn.commit()



def _marca_note_vedove() -> None:
    """
    Riparazione una tantum, idempotente e a doppio senso: allinea
    Highlight.position_status al fatto che il libro esista o no.

    Senza, il lavoro sulle note vedove non sarebbe retroattivo. Le 266 note
    che su un impianto reale puntano a un libro cancellato sono gia' marcate
    'failed', e il convertitore CFI in background guarda solo le righe con
    position_status NULL: non le riesaminerebbe mai, e resterebbero nel
    mucchio sbagliato — contate fra le "conversioni fallite", che su di loro
    non si possono ritentare, invece che fra le note da ricollegare a un
    libro.

    Vale anche al contrario: una nota marcata 'libro_assente' il cui libro
    e' tornato (reimportato, o ricollegato altrove) torna a NULL e rientra
    nella conversione normale. Cosi' girare questa funzione ad ogni avvio e'
    sempre corretto, invece di essere una cosa da fare una volta e ricordarsi
    di non rifare.
    """
    db = database.SessionLocal()
    try:
        coppie = db.query(
            models.Highlight.library, models.Highlight.calibre_book_id
        ).filter(models.Highlight.deleted_at.is_(None)).distinct().all()
        da_marcare, da_liberare = [], []
        for library, book_id in coppie:
            ids = widowed_highlights.ids_libri_esistenti(library)
            if ids is None:
                # Libreria non leggibile: "non lo so", e non si tocca niente.
                continue
            (da_liberare if book_id in ids else da_marcare).append((library, book_id))

        marcate = liberate = 0
        for library, book_id in da_marcare:
            marcate += db.query(models.Highlight).filter(
                models.Highlight.library == library,
                models.Highlight.calibre_book_id == book_id,
                models.Highlight.deleted_at.is_(None),
                # NON "!= 'libro_assente'" e basta: in SQL un confronto con
                # NULL non e' vero, e' NULL — le note mai tentate (che sono
                # NULL) sarebbero rimaste fuori proprio quelle. Trovato
                # provando la migrazione, non leggendola.
                sa.or_(
                    models.Highlight.position_status.is_(None),
                    models.Highlight.position_status != "libro_assente",
                ),
            ).update({"position_status": "libro_assente"}, synchronize_session=False)
        for library, book_id in da_liberare:
            liberate += db.query(models.Highlight).filter(
                models.Highlight.library == library,
                models.Highlight.calibre_book_id == book_id,
                models.Highlight.deleted_at.is_(None),
                models.Highlight.position_status == "libro_assente",
            ).update({"position_status": None}, synchronize_session=False)
        if marcate or liberate:
            db.commit()
            log_message(
                "info", "annotations",
                f"Note vedove: {marcate} marcate 'libro assente', {liberate} rimesse in conversione",
            )
    finally:
        db.close()


def _persist_pending_write(job: WriteJob, error: Exception) -> None:
    """CalibreWriteQueue.on_permanent_failure callback: durably stores a write
    that failed after exhausting in-process retries, so it can be replayed
    later by `_drain_pending_writes_loop`."""
    db = database.SessionLocal()
    try:
        db.add(models.PendingCalibreWrite(**serialize_pending(job, error)))
        db.commit()
    finally:
        db.close()


async def _drain_pending_writes_loop(write_queue: CalibreWriteQueue) -> None:
    while True:
        await asyncio.sleep(60)
        db = database.SessionLocal()
        try:
            pending = (
                db.query(models.PendingCalibreWrite)
                .filter(models.PendingCalibreWrite.resolved_at.is_(None))
                .all()
            )
            for p in pending:
                try:
                    await retry_one_pending(write_queue, p.op_type, p.payload_json, p.library_path)
                except Exception as exc:
                    # Update the SAME row in place — never insert a new one
                    # for a retry (that turned one stuck write into an
                    # exponentially growing table on every drain cycle).
                    p.attempts += 1
                    p.last_error = str(exc)
                    continue
                db.delete(p)
            db.commit()
        finally:
            db.close()


# Reported after testing a real deployment: the reading-stats
# dashboard recomputed from scratch on every page load (visibly slow with a
# 1000+ book library and a real device's session history), AND a backup
# already sitting on disk from before this feature existed was never
# processed at all (process_statistics_db only ever ran synchronously
# inside the upload request itself). This loop fixes both: it re-parses
# every device's stored statistics.sqlite3 (idempotent, safe to repeat
# every cycle — see reprocess_all_device_backups) and refreshes StatsCache
# for every library, so GET /api/kolibre/stats/* just reads a row instead
# of recomputing. Work-then-sleep (not sleep-then-work like
# _drain_pending_writes_loop above) so the first refresh happens right at
# startup instead of only after the first full interval.
#
# devices.py::upload_device_backup now also triggers an immediate
# refresh_stats_cache right after processing a fresh statistics.sqlite3, so
# a device sync no longer waits for this loop at all — this interval is
# just the safety net catching what a backup-triggered refresh can't: web
# reader ticks (record_live_tick, books.py::put_reading_position) and any
# refresh that failed/was skipped. Since almost all reading data comes from
# device backups (which self-trigger), daily is plenty; no need for a
# tight poll.
STATS_REFRESH_INTERVAL_SECONDS = 86400  # 1 day (safety net; backups self-trigger a refresh)


async def _refresh_stats_loop() -> None:
    while True:
        db = database.SessionLocal()
        try:
            stats_service.reprocess_all_device_backups(db)
            stats_service.refresh_stats_cache(db)
        except Exception as exc:
            log_message("warning", "stats", f"Refresh periodico statistiche fallito: {exc}")
        finally:
            db.close()
        await asyncio.sleep(STATS_REFRESH_INTERVAL_SECONDS)


# Was inline in annotations.list_annotations (bounded per call) — moved here
# once a large backlog meant EVERY page load re-opened and re-parsed EPUBs
# for up to 25 device highlights, on the hot read path, until the backlog
# cleared (the complaint: "non c'è bisogno di caricarle tutte all'apertura
# che la sovraccarica"). Short interval on purpose (unlike stats' daily safety
# net): a freshly-pushed device highlight should get its CFI within a few
# minutes, not sit unresolved until the next day.
HIGHLIGHT_POSITION_BACKFILL_INTERVAL_SECONDS = 300  # 5 minutes


async def _backfill_highlight_positions_loop() -> None:
    while True:
        db = database.SessionLocal()
        try:
            # La cache delle liste libri si libera anche quando il server e'
            # fermo: senza, una biblioteca aperta una volta e mai piu' resta
            # in memoria finche' il processo vive.
            purge_expired_book_lists()
            stardict_service.purge_idle_dictionaries()
            highlight_position.backfill_pending_device_positions(db)
        except Exception as exc:
            log_message("warning", "annotations", f"Backfill periodico posizioni CFI fallito: {exc}")
        finally:
            db.close()
        await asyncio.sleep(HIGHLIGHT_POSITION_BACKFILL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_directories()
    models.Base.metadata.create_all(bind=database.engine)
    # Both migrations are best-effort on purpose. _ensure_schema_migrations is
    # ~60 additive ALTER TABLEs that each already swallow "duplicate column";
    # anything else it raises (a locked db, a column added by a newer build and
    # then rolled back) used to propagate out of lifespan and stop the server
    # from starting at all — and with the backend down the healthcheck keeps
    # the frontend container down too, so a cosmetic migration error took the
    # whole stack offline. A logged failure with a running server is strictly
    # better: the app still works, minus whatever the new column powers.
    try:
        _ensure_schema_migrations()
    except Exception as exc:
        log_message("error", "system", f"Migrazioni schema fallite (il server parte comunque): {exc}")
    try:
        _migra_frazione_lettura()
    except Exception as exc:
        log_message("error", "system", f"Migrazione frazione lettura fallita (il server parte comunque): {exc}")
    try:
        _migra_posizioni_per_utente()
    except Exception as exc:
        log_message("error", "system", f"Migrazione posizioni per utente fallita (il server parte comunque): {exc}")
    # try suo, e non insieme a quella sopra: e' la regola scritta nei
    # docstring di queste funzioni, e metterle nello stesso blocco
    # significherebbe che la prima che fallisce salta la seconda.
    try:
        _marca_note_vedove()
    except Exception as exc:
        log_message("error", "system", f"Marcatura note vedove fallita (il server parte comunque): {exc}")
    log_message("info", "system", "Server startup and database validation.")

    db = database.SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            # Si sovrascrivono con ADMIN_USERNAME/ADMIN_PASSWORD (vedi
            # .env.example). Questo blocco gira solo su un database senza
            # nemmeno un utente: su un impianto gia' avviato non tocca niente.
            admin_username = os.environ.get("ADMIN_USERNAME", "admin")
            admin_password = os.environ.get("ADMIN_PASSWORD", "admin")
            db.add(models.User(
                username=admin_username,
                hashed_password=auth.get_password_hash(admin_password),
                fullname=admin_username,
                is_admin=True,
            ))
            db.commit()
            log_message("info", "auth", f"Default administrator user '{admin_username}' seeded.")

        # ── Permessi: chi possiede cosa, all'accensione ──────────────────
        #
        # Questa migrazione gira su un impianto IN USO (nel caso reale:
        # quattro biblioteche, tre dispositivi, oltre mille annotazioni), e
        # la regola che la guida e' una sola: **nessuno deve perdere
        # l'accesso a qualcosa che ieri vedeva**. Un modello dei permessi
        # che il giorno in cui entra in funzione chiude fuori le persone
        # non e' rigoroso, e' rotto.
        #
        # Quindi: il fondatore e' il primo amministratore, le biblioteche
        # senza proprietario diventano sue, e ogni altro utente riceve su
        # ogni biblioteca esistente il permesso pieno che aveva di fatto.
        # Da domani in avanti i permessi nuovi si danno a mano; quelli che
        # esistevano prima che i permessi esistessero si conservano.
        #
        # Idempotente: gira a ogni avvio e non tocca niente che abbia gia'
        # un proprietario o una riga di permesso.
        if db.query(models.User).count() > 0:
            fondatore = db.query(models.User).filter(models.User.is_founder.is_(True)).first()
            if not fondatore:
                fondatore = (
                    db.query(models.User).filter(models.User.is_admin.is_(True))
                    .order_by(models.User.id).first()
                    or db.query(models.User).order_by(models.User.id).first()
                )
                fondatore.is_founder = True
                log_message("info", "auth", f"Fondatore dell'impianto: '{fondatore.username}'.")
            # I permessi d'account del fondatore sono formali: is_founder
            # gli fa passare ogni controllo comunque. Si scrivono lo stesso
            # perche' l'interfaccia mostra le caselle, e un fondatore con
            # tutte le caselle vuote che pero' puo' fare tutto e' una schermata
            # che mente.
            for campo in ("can_create_libraries", "can_create_users", "can_manage_permissions",
                          "can_register_devices", "can_edit_authors"):
                setattr(fondatore, campo, True)

            senza_proprietario = db.query(models.Library).filter(models.Library.owner_id.is_(None)).all()
            for biblioteca in senza_proprietario:
                biblioteca.owner_id = fondatore.id
            if senza_proprietario:
                log_message(
                    "info", "auth",
                    f"{len(senza_proprietario)} biblioteche assegnate a '{fondatore.username}'.",
                )

            altri = db.query(models.User).filter(models.User.id != fondatore.id).all()
            if altri:
                biblioteche = db.query(models.Library).all()
                esistenti = {
                    (p.user_id, p.library_id)
                    for p in db.query(models.LibraryPermission).all()
                }
                aggiunti = 0
                for utente in altri:
                    for biblioteca in biblioteche:
                        if (utente.id, biblioteca.id) in esistenti or biblioteca.owner_id == utente.id:
                            continue
                        db.add(models.LibraryPermission(
                            user_id=utente.id, library_id=biblioteca.id,
                            can_edit=True, can_share=False, can_manage=False,
                        ))
                        aggiunti += 1
                if aggiunti:
                    log_message("info", "auth", f"{aggiunti} permessi di biblioteca conservati dalla situazione precedente.")
            db.commit()

        # Rete di sicurezza per il controllo `is_admin`, che da oggi chiude
        # davvero la cancellazione di una biblioteca (api/libraries.py).
        #
        # Il flag esiste sul modello da sempre e non lo leggeva nessuno: un
        # impianto avviato prima di questa riga puo' quindi avere utenti
        # tutti a is_admin=False senza che se ne sia mai accorto nessuno —
        # e in quel caso il controllo nuovo non proteggerebbe niente, chiuderebbe
        # fuori l'unica persona che c'e'. Se non esiste NESSUN amministratore,
        # il primo utente registrato lo diventa.
        #
        # Idempotente e conservativa: con un amministratore gia' presente non
        # fa niente, e non toglie mai il flag a nessuno.
        if db.query(models.User).count() > 0 and not db.query(models.User).filter(
            models.User.is_admin.is_(True)
        ).first():
            primo = db.query(models.User).order_by(models.User.id).first()
            primo.is_admin = True
            db.commit()
            log_message(
                "warning", "auth",
                f"Nessun amministratore trovato: promosso il primo utente '{primo.username}'.",
            )
    finally:
        db.close()

    # Populate the per-author "Pagine" total cache once at startup (see
    # models.AuthorPagesCache's own docstring) — otherwise a fresh deploy
    # would show every author at 0 pages until the first book add/remove
    # happened to refresh it (or the next GET /authors finds it dirty).
    # Explicitly caught here, unlike the mutation call sites (which use
    # safe_mark_author_pages_dirty): a failure in this one-time startup
    # convenience call must never take down the whole backend — see the
    # 2026-08-18 incident where a stale reference to a since-renamed
    # function crashed every startup and failed the healthcheck.
    db = database.SessionLocal()
    try:
        author_stats_service.refresh_author_pages_cache(db)
    except Exception as e:
        log_message("warning", "authors", f"Popolamento iniziale cache pagine autori fallito: {e}")
    finally:
        db.close()

    # No library is ever auto-created, on a fresh install or otherwise: the
    # server works fine with zero libraries, and the first one is whatever
    # the user names it via "Aggiungi Libreria" — no privileged folder name.

    write_queue = CalibreWriteQueue(on_permanent_failure=_persist_pending_write)
    write_queue.start()
    app.state.write_queue = write_queue
    drain_task = asyncio.create_task(_drain_pending_writes_loop(write_queue))
    stats_task = asyncio.create_task(_refresh_stats_loop())
    highlight_position_task = asyncio.create_task(_backfill_highlight_positions_loop())

    start_watcher()

    yield

    stop_watcher()
    drain_task.cancel()
    stats_task.cancel()
    highlight_position_task.cancel()
    await write_queue.stop()


app = FastAPI(title="Kolibre Digital Library Server API", version="2.0", lifespan=lifespan)

# allow_origins=["*"] insieme ad allow_credentials=True era la seconda meta'
# del problema di autenticazione: qualunque sito aperto nel browser poteva
# parlare con questo server e leggerne le risposte. Ora la porta e' aperta
# solo a chi sta in casa — localhost, rete privata (RFC1918), nomi .local —
# su qualsiasi porta, perche' quella cambia fra dev (5173) e produzione
# (FRONTEND_PORT). Un'origine diversa si dichiara esplicitamente con
# CORS_ORIGINS="https://x,https://y" nel .env.
_CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
_PRIVATE_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost|127\.0\.0\.1|\[::1\]|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
    r"[A-Za-z0-9-]+\.local"
    r")(:\d+)?$"
)
# L'elenco libri di una libreria da 1.200 titoli e' ~1,4 MB di JSON che il
# backend produce in 7 ms e poi manda per intero sul filo. Compresso sono
# 76 KB, al costo di 6 ms di CPU: su telefono e su Wi-Fi lento e' la
# differenza che si sente. minimum_size evita di comprimere le risposte
# piccole, dove l'overhead non ripaga. Registrato PRIMA del CORS perche' in
# Starlette i middleware si eseguono nell'ordine inverso di aggiunta: cosi'
# il CORS resta il piu' esterno e gli header arrivano anche sugli errori.
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_origin_regex=None if _CORS_ORIGINS else _PRIVATE_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/kolibre/version")
def get_version():
    """
    Versione in esecuzione — nessuna autenticazione richiesta apposta, cosi'
    si puo' controllare con un semplice curl/browser senza login, per capire
    a colpo d'occhio se il server e' allineato all'ultimo tag pushato. Il
    valore arriva da KOLIBRE_VERSION, che si scrive in .env prima del build
    (la propria automazione di deploy lo ricava da `git describe`); se non
    c'e', risponde "dev".
    """
    return {"version": os.environ.get("KOLIBRE_VERSION", "dev")}


@app.exception_handler(LibraryDeletedError)
async def _library_deleted_handler(request: Request, exc: LibraryDeletedError):
    # A request naming a library the user explicitly deleted (see
    # DELETED_LIBRARY_MARKER) should read as "not found", not as a server
    # crash — without this, any route that opens a CalibreLibrary directly
    # (not through one of the soft cross-library lookups that already
    # catch-and-skip) surfaced a bare 500 instead.
    return JSONResponse(status_code=404, content={"detail": "Questa libreria è stata eliminata."})


@app.exception_handler(LibraryMissingError)
async def _library_missing_handler(request: Request, exc: LibraryMissingError):
    # Una biblioteca che non esiste non si crea piu' da sola: si dice che non
    # c'e'. Prima aprirla la faceva NASCERE, vuota e senza che niente lo
    # segnalasse — e' cosi' che su un impianto reale e' ricomparsa una
    # biblioteca fantasma, due mesi dopo averla cancellata.
    #
    # Si logga perche' il nome sbagliato interessa: quasi sempre e' un nome
    # VISUALIZZATO usato al posto del nome cartella, e sapere da quale
    # richiesta arriva e' l'unico modo per trovare il chiamante che sbaglia.
    log_message("warning", "libraries", f"Richiesta una biblioteca che non esiste: {exc}")
    return JSONResponse(status_code=404, content={"detail": "Questa libreria non esiste."})

# Autenticazione applicata QUI, al livello di include, e non endpoint per
# endpoint: e' l'unico punto del progetto da cui si legge in un colpo solo
# chi e' protetto e chi no. Prima era il contrario — la dipendenza andava
# messa a mano su ogni funzione, e ~95 endpoint non ce l'avevano, fra cui
# DELETE /books/{id} e DELETE /libraries/{name}: con il CORS aperto a "*",
# una qualunque pagina web aperta nel browser poteva cancellare una
# libreria intera senza sapere nulla di questo server.
#
# get_current_user_flexible (non get_current_user) perche' accetta anche
# ?token= in query: i download aperti con window.open e i file caricati dal
# web reader non possono allegare un header Authorization.
_AUTH = [Depends(auth.get_current_user_flexible)]

app.include_router(auth_router.router)                                    # POST /token: e' il login stesso
app.include_router(users_router.router, dependencies=_AUTH)
app.include_router(libraries_router.router, dependencies=_AUTH)
app.include_router(ingest_router.router, dependencies=_AUTH)
app.include_router(books_router.router, dependencies=_AUTH)
app.include_router(custom_columns_router.router, dependencies=_AUTH)
app.include_router(entities_router.router, dependencies=_AUTH)
app.include_router(authors_router.router, dependencies=_AUTH)
# device_token_router PRIMA di devices_router.router: condividono il prefisso
# /api/devices, e router ha rotte con parametro (/{device_id}) che
# cattureranno /me se registrate per prime — con l'unico effetto visibile di
# un 401 al plugin, difficilissimo da ricondurre all'ordine di include.
app.include_router(devices_router.device_token_router)                    # token di dispositivo, non JWT utente
app.include_router(devices_router.router, dependencies=_AUTH)
app.include_router(devices_router.sync_router)                            # idem, sotto /api/kolibre/devices
app.include_router(annotations_router.router, dependencies=_AUTH)
app.include_router(tools_router.router, dependencies=_AUTH)
app.include_router(settings_router.router, dependencies=_AUTH)
app.include_router(fulltext_router.router, dependencies=_AUTH)
app.include_router(library_transfer_router.router, dependencies=_AUTH)
app.include_router(stats_router.router, dependencies=_AUTH)
app.include_router(interventions_router.router, dependencies=_AUTH)
app.include_router(dictionaries_router.router, dependencies=_AUTH)
app.include_router(vocabulary_router.router, dependencies=_AUTH)

# OPDS ha gia' la sua autenticazione, HTTP Basic (require_opds_auth): i
# lettori esterni che consumano il feed non sanno nulla del JWT di Kolibre.
app.include_router(opds_router.router)

# Endpoint che il browser o il plugin caricano senza poter allegare un
# header: copertine e foto in <img src>, font in @font-face, self-update
# del plugin KOReader. Tutti in sola lettura — vedi il commento accanto a
# ciascun public_router nel rispettivo modulo.
app.include_router(users_router.public_router)
app.include_router(ingest_router.public_router)
app.include_router(books_router.device_or_user_router)                    # persona O dispositivo
app.include_router(books_router.public_router)
app.include_router(authors_router.public_router)
app.include_router(tools_router.public_router)
