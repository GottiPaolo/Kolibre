"""
Il registro numerato delle migrazioni dello schema.

**Da dove viene (revisione critica del 19/11/2026, punto A4).** Fino a ieri
le migrazioni vivevano in main.py: tre funzioni per ~500 righe che giravano
TUTTE a ogni avvio, ciascuna nel suo `try` perche' la lezione — imparata due
volte, e scritta nei loro docstring — era che «il primo passo che fallisce
salta tutti quelli dopo». Funzionava, con quattro difetti che crescevano a
ogni colonna aggiunta: ~40 `PRAGMA table_info` a ogni avvio anche quando non
c'era niente da fare; l'ordine delle migrazioni implicito nell'ordine delle
chiamate dentro lifespan; un fallimento che passava in silenzio (loggato e
ingoiato, server su); e gli indici «caldi» che esistevano SOLO attraverso la
migrazione, mai dichiarati sui modelli.

**Come funziona.** Una tabella `schema_version` con una riga sola: il numero
dell'ultima migrazione applicata, piu' `applied_at` per rispondere a «quando
e' successo?» guardando il database di un impianto in difficolta'. La lista
MIGRATIONS qui sotto e' ordinata e numerata 1..N; all'avvio
(`apply_pending`, chiamata da main.py) si applicano solo le voci OLTRE il
numero corrente, in ordine, e il numero avanza dopo ognuna. A regime — con
la versione gia' al corrente — il costo dell'avvio e' una SELECT, non
quaranta PRAGMA e una ventina di CREATE INDEX IF NOT EXISTS.

**Se una migrazione fallisce, il server NON parte.** E' un cambio
deliberato rispetto a ieri. Prima l'avvio ingoiava l'errore e partiva
comunque, con una ragione vera: un backend giu' trascina giu' anche il
frontend (healthcheck del container), quindi un errore magari cosmetico
spegneva tutto. Ma l'esperienza ha mostrato il costo dell'alternativa: uno
schema a meta' non si vede all'avvio — si vede nei giorni dopo, come 500 su
rotte a caso, senza che niente dica il perche'. Meglio un avvio che si
ferma e dice chiaro quale voce e' caduta e cosa sistemare, subito e una
volta sola. Il numero resta a quello dell'ultima voce riuscita, quindi
l'avvio successivo riprende esattamente dalla voce caduta; e siccome ogni
voce e' idempotente anche al proprio interno (controlla prima di alterare),
ripeterla dopo una caduta a meta' e' sicuro.

**Un'installazione nuova NON deve essere diversa da una migrata** (vincolo
posto da Paolo, 19/11/2026). Il modo: su un database appena creato (dopo
create_all) la tabella schema_version non esiste, quindi la versione
corrente e' 0 e TUTTE le migrazioni girano, in ordine. Non e' uno spreco:
e' esattamente quello che queste funzioni hanno sempre fatto — girare tutte,
a ogni avvio, su ogni database, nuovo o vecchio — quindi sono idempotenti
per costruzione e collaudate proprio in questo uso. Su un database nuovo
quasi tutto e' un no-op (create_all ha gia' fatto tabelle e colonne nella
forma finale), ma gli indici «caldi» della voce 1, che sui modelli non sono
dichiarati, nascono cosi' anche sull'installazione nuova, per la stessa
strada di sempre. Dichiararli sui modelli (punto C4 della stessa revisione)
resta un miglioramento separato, NON un prerequisito di questo registro.

**Un database vecchio senza schema_version** e' lo stesso caso: versione 0,
girano tutte, nessun danno. E' il primo avvio di ogni impianto esistente
dopo questo aggiornamento.
"""

import hashlib

from . import database
from .logging_utils import log_message


def add_fraction_read_to_sessions() -> None:
    """
    Aggiunge `fraction_read` alle due tabelle delle sessioni.

    Sta fuori da _ensure_schema_migrations, e non dentro, per una ragione
    imparata a spese: quella funzione e' una sequenza lunga dove il primo
    passo che fallisce salta TUTTI quelli dopo, e l'avvio del server la
    ingoia loggando un avviso. Il risultato e' un database migrato a meta'
    che risponde 500 su ogni statistica, senza che niente lo dica a
    chiaro. Una colonna che serve a una funzione nuova non deve dipendere
    dalla riuscita di migrazioni che non c'entrano.

    Nota del 20/11/2026: oggi questa funzione e' una voce del registro di
    questo modulo. La lezione di cui sopra sopravvive nella regola del
    registro: ogni voce e' separata, e quella che fallisce ferma l'avvio
    dicendo QUALE e' caduta, invece di far saltare in silenzio le altre.
    """
    with database.engine.connect() as conn:
        for tabella in ("reading_sessions", "orphan_reading_sessions"):
            colonne = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({tabella})")}
            if colonne and "fraction_read" not in colonne:
                conn.exec_driver_sql(f"ALTER TABLE {tabella} ADD COLUMN fraction_read FLOAT")
                log_message("info", "system", f"Migrated {tabella}: added missing 'fraction_read' column.")
        conn.commit()


def rebuild_positions_per_user() -> None:
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

    Nota del 20/11/2026: oggi questa funzione e' una voce del registro di
    questo modulo. La lezione di cui sopra sopravvive nella regola del
    registro: ogni voce e' separata, e quella che fallisce ferma l'avvio
    dicendo QUALE e' caduta, invece di far saltare in silenzio le altre.
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
            log_message("info", "system", "reading_positions: added user_id and rebuilt the uniqueness constraint.")

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
            log_message("info", "system", "book_reading_coverage: added user_id and rebuilt the uniqueness constraint.")

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
                        "stats_cache: rebuilt per user (the old rows were aggregated across everyone).")

        conn.commit()


def add_missing_columns_and_hot_indexes() -> None:
    """
    create_all() (in main.py's lifespan) only ever creates TABLES that don't
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

        # L'identita' durevole delle note (05/11/2026). La colonna nasce
        # VUOTA e non con un valore predefinito: un `DEFAULT` nell'ALTER
        # TABLE sarebbe lo stesso per tutte le righe, e qui ogni riga vuole
        # un nome suo. A riempirle ci pensa
        # `identita_durevole.assegna_mancanti`, chiamata all'accensione —
        # vedi `lifespan`.
        for tabella in ("highlights", "orphan_highlights"):
            colonne = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({tabella})")}
            if colonne and "id_durevole" not in colonne:
                conn.exec_driver_sql(f"ALTER TABLE {tabella} ADD COLUMN id_durevole VARCHAR")
                # L'indice unico si crea a parte: ALTER TABLE ADD COLUMN in
                # SQLite non accetta UNIQUE. Dopo il riempimento sarebbe
                # troppo tardi per accorgersi di un doppione, quindi si crea
                # prima — su una colonna tutta vuota, dove `NULL` non conta
                # come doppione.
                conn.exec_driver_sql(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{tabella}_id_durevole "
                    f"ON {tabella} (id_durevole)"
                )
                conn.commit()
                log_message("info", "system", f"Migrated {tabella}: added missing 'id_durevole' column.")

        # «Rimanda questo libro da zero» (05/11/2026): un'istruzione per il
        # plugin degli appunti. Nasce nulla, cioe' «niente da rifare», che e'
        # la verita' per ogni libro deciso prima che questa colonna esistesse.
        colonne = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(decisioni_di_appunti)")}
        if colonne and "rifai_dal" not in colonne:
            conn.exec_driver_sql("ALTER TABLE decisioni_di_appunti ADD COLUMN rifai_dal DATETIME")
            conn.commit()
            log_message("info", "system", "Migrated decisioni_di_appunti: added missing 'rifai_dal' column.")

        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(libraries)")}
        if "owner_id" not in existing:
            conn.exec_driver_sql("ALTER TABLE libraries ADD COLUMN owner_id INTEGER")
            log_message("info", "system", "Migrated libraries: added missing 'owner_id' column.")

        # Qualita' degli EPUB (14/11/2026). La tabella `qualita_libri` nasce
        # da create_all; qui servono solo le due colonne sulle righe di
        # ingest, che la tabella ce l'hanno gia'.
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(ingested_books)")}
        for col, ddl in (
            ("qualita_punteggio", "ALTER TABLE ingested_books ADD COLUMN qualita_punteggio INTEGER"),
            ("qualita_json", "ALTER TABLE ingested_books ADD COLUMN qualita_json TEXT"),
        ):
            if col not in existing:
                conn.exec_driver_sql(ddl)
                log_message("info", "system", f"Migrated ingested_books: added missing '{col}' column.")

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
        # Le userpatch riportate dal dispositivo (03/11/2026) — vedi
        # models.Device.patch_installate.
        existing_dev = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(devices)")}
        if "patch_installate" not in existing_dev:
            conn.exec_driver_sql("ALTER TABLE devices ADD COLUMN patch_installate VARCHAR")
            log_message("info", "system", "Migrated devices: added missing 'patch_installate' column.")
        # La coda dei dizionari chiesti dal portale (03/11/2026) — vedi
        # models.Device.dizionari_richiesti.
        if "dizionari_richiesti" not in existing_dev:
            conn.exec_driver_sql("ALTER TABLE devices ADD COLUMN dizionari_richiesti VARCHAR")
            log_message("info", "system", "Migrated devices: added missing 'dizionari_richiesti' column.")

        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(reading_positions)")}
        if "coverage_percent" not in existing:
            conn.exec_driver_sql("ALTER TABLE reading_positions ADD COLUMN coverage_percent FLOAT")
            log_message("info", "system", "Migrated reading_positions: added missing 'coverage_percent' column.")
        # Lo stato che il dispositivo dichiara ('reading'/'complete'/
        # 'abandoned') e il giorno in cui lo ha dichiarato — vedi il commento
        # su models.ReadingPosition.stato_lettura.
        for col, ddl in (
            ("stato_lettura", "ALTER TABLE reading_positions ADD COLUMN stato_lettura VARCHAR"),
            ("stato_dichiarato_il", "ALTER TABLE reading_positions ADD COLUMN stato_dichiarato_il DATETIME"),
        ):
            if col not in existing:
                conn.exec_driver_sql(ddl)
                log_message("info", "system", f"Migrated reading_positions: added missing '{col}' column.")
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


def hash_device_tokens() -> None:
    """
    I token dei dispositivi diventano impronte SHA-256 (20/11/2026,
    revisione critica del 19/11, punto C2/D1).

    **Il problema.** La colonna `devices.device_token` teneva il token in
    chiaro: chi leggeva app.db — o un suo backup — aveva i token funzionanti
    di tutti i lettori. I token d'applicazione la strada giusta ce l'hanno
    dal 05/11 (`token_applicazione.token_hash`); questa voce porta i
    dispositivi sulla stessa.

    **Cosa fa, in due passi idempotenti.**

    1. Rinomina la colonna in `device_token_hash` — il nome che dice il
       vero — e rifa' l'indice unico col nome che create_all darebbe oggi
       (SQLite fa seguire l'indice alla colonna ma non lo rinomina, e il
       vincolo fresh == migrated vale anche per i nomi degli indici). Su un
       database nuovo la colonna nasce gia' col nome giusto e il passo e'
       un no-op.

    2. Trasforma in impronta (`sha256(token).hexdigest()`) ogni valore
       ancora in chiaro. **Il criterio di riconoscimento**: un token in
       chiaro comincia per `kolibre_tok_` (e' cosi' che nasce in
       /register, ed e' il primo controllo di auth.get_current_device: un
       valore senza prefisso non ha mai potuto autenticare); un'impronta
       sono 64 cifre esadecimali e non puo' cominciare cosi' ('k' non e'
       una cifra hex). Quindi rifare girare la voce non doppia-hasha, e i
       valori gia' migrati non si toccano.

    **Nessun riaccoppiamento**: il dispositivo possiede il chiaro e continua
    a mandarlo; sha256(chiaro) ritrova esattamente la riga di prima.
    """
    with database.engine.connect() as conn:
        colonne = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(devices)")}
        if not colonne:
            return
        if "device_token" in colonne and "device_token_hash" not in colonne:
            conn.exec_driver_sql(
                "ALTER TABLE devices RENAME COLUMN device_token TO device_token_hash"
            )
            conn.exec_driver_sql("DROP INDEX IF EXISTS ix_devices_device_token")
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_devices_device_token_hash "
                "ON devices (device_token_hash)"
            )
            log_message("info", "system",
                        "devices: renamed device_token to device_token_hash.")
        if "device_token_hash" in colonne or "device_token" in colonne:
            in_chiaro = conn.exec_driver_sql(
                "SELECT id, device_token_hash FROM devices "
                "WHERE device_token_hash LIKE 'kolibre_tok_%'"
            ).fetchall()
            for device_id, token in in_chiaro:
                conn.exec_driver_sql(
                    "UPDATE devices SET device_token_hash = ? WHERE id = ?",
                    (hashlib.sha256(token.encode("utf-8")).hexdigest(), device_id),
                )
            if in_chiaro:
                log_message("info", "system",
                            f"devices: hashed {len(in_chiaro)} clear-text device token(s).")
        conn.commit()


def drop_device_folder_layout() -> None:
    """
    Toglie la colonna `devices.folder_layout` (20/11/2026, revisione
    critica del 19/11, punto B8).

    **Il contesto.** La colonna diceva al plugin KOReader come disporre i
    libri sul dispositivo: "author" (una cartella per autore) o "flat"
    (tutti i file in una cartella sola). Paolo ha sempre usato solo
    "author" — verificato in sola lettura sul server: TUTTI e 4 i
    dispositivi reali ce l'hanno — e ha deciso di togliere l'opzione a
    tutto tondo: «crea meno confusione». Il valore non e' piu' una scelta,
    e' IL comportamento: il plugin continua a riceverlo, hardcoded
    "author", dalla risposta del sync (la zeppa sta in api/devices/sync.py e
    muore con la rottura d'API di B1).

    **Perche' un DROP COLUMN semplice basta.** SQLite sa fare
    `ALTER TABLE ... DROP COLUMN` dalla 3.35 (il Python 3.11 di Homebrew ne
    porta una ben piu' nuova), purche' la colonna non compaia in indici,
    vincoli UNIQUE/PK o colonne generate — e `folder_layout` non compare in
    nessuno dei tre: era una Column(String) nuda, senza indice (l'unico
    indice di devices e' quello sull'impronta del token). Niente
    ricostruzione della tabella, al contrario della voce 3.

    **Idempotente per controllo preventivo**: su un database che la colonna
    non ce l'ha piu' — o non l'ha mai avuta, come uno nuovo nato da
    create_all col modello di oggi — e' un no-op, ed e' cosi' che regge il
    vincolo fresh == migrated.
    """
    with database.engine.connect() as conn:
        colonne = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(devices)")}
        if "folder_layout" in colonne:
            conn.exec_driver_sql("ALTER TABLE devices DROP COLUMN folder_layout")
            log_message("info", "system",
                        "devices: dropped 'folder_layout' (the option is gone; the plugin "
                        "still receives a hardcoded 'author' until the B1 API break).")
        conn.commit()


def add_exact_chars_to_reading_sessions() -> None:
    """
    Le colonne della misura ESATTA su `reading_sessions` (20/11/2026,
    passo 4 delle statistiche in caratteri — decisione del 19/11 con Paolo).

    **Il contesto.** Dal 19/11 il dispositivo manda una riga per pagina
    visitata (tabella `letture_di_pagina`: xpointer piu' conteggio caratteri)
    e il server la risolve in caratteri assoluti col proprio indice. Le
    sessioni pero' continuavano a stimare i caratteri da `fraction_read`
    (che presume ogni pagina lunga uguale — misurato: la pagina 12 su 248 de
    «La linea d'ombra» e' il 4,8% del libro in pagine e l'1,8% in caratteri).
    Queste quattro colonne portano il dato vero sulla sessione, dove c'e':

      * `chars_read`  — caratteri davvero letti (somma delle righe esatte);
      * `char_start`, `char_end` — inizio e fine in caratteri assoluti;
      * `exact`       — il distintivo binario: 0 stimata, 1 esatta.

    **Ammesse vuote per disegno**: le sessioni vecchie, quelle del lettore
    web e quelle dei dispositivi senza plugin 0.24.0 restano stimate
    (`exact` = 0, il default di ogni riga esistente). Nessun backfill qui:
    il riempimento lo fa `letture_service.derive_reading_sessions`, che e'
    idempotente e rieseguibile su tutto lo storico — e' la migrazione a dare
    il posto, non il valore.

    **Idempotente per controllo preventivo**, come ogni voce additiva: su un
    database nuovo le colonne nascono gia' da create_all col modello di oggi
    e il giro e' un no-op (fresh == migrated).
    """
    with database.engine.connect() as conn:
        colonne = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(reading_sessions)")}
        if not colonne:
            return
        for col, ddl in (
            ("chars_read", "ALTER TABLE reading_sessions ADD COLUMN chars_read INTEGER"),
            ("char_start", "ALTER TABLE reading_sessions ADD COLUMN char_start INTEGER"),
            ("char_end", "ALTER TABLE reading_sessions ADD COLUMN char_end INTEGER"),
            ("exact", "ALTER TABLE reading_sessions ADD COLUMN exact INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in colonne:
                conn.exec_driver_sql(ddl)
                log_message("info", "system",
                            f"reading_sessions: added missing '{col}' column (exact character measure).")
        conn.commit()


def add_owner_to_ingested_books() -> None:
    """
    La colonna `user_id` su `ingested_books` (21/11/2026: la cartella di
    ingest diventa per utente — richiesta di Paolo, voce del 03/11 della
    roadmap).

    **Il contesto.** La cartella di ingest era una sola per tutti e la
    tabella dei file in attesa non aveva un proprietario: con due persone,
    la pagina Ingest mostrava a ciascuno i file degli altri. Da oggi dentro
    `data/ingest` c'e' una sottocartella per utente (`<id>-<username>`,
    creata da sola all'avvio e alla creazione dell'utente — vedi
    services/ingest_folders.py), il watcher attribuisce il proprietario dal
    percorso, e l'upload dal web salva nella cartella di chi carica.

    **Nessun backfill, di proposito.** Le righe esistenti restano NULL:
    sono nate quando il proprietario non si registrava, e attribuirle ora
    sarebbe un'ipotesi — la regola del progetto e' non dedurre mai un dato
    dell'utente. NULL significa «di prima, o dalla radice di ingest», e
    quelle righe le vede (e le lavora) solo l'amministratore, com'era di
    fatto ieri per tutto.

    **Idempotente per controllo preventivo**: su un database nuovo la
    colonna e l'indice nascono gia' da create_all col modello di oggi
    (`index=True` sul modello produce lo stesso nome `ix_ingested_books_
    user_id`), e il giro e' un no-op — fresh == migrated, indice compreso.
    """
    with database.engine.connect() as conn:
        colonne = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(ingested_books)")}
        if not colonne:
            return
        if "user_id" not in colonne:
            conn.exec_driver_sql(
                "ALTER TABLE ingested_books ADD COLUMN user_id INTEGER REFERENCES users(id)"
            )
            log_message("info", "system", "Migrated ingested_books: added missing 'user_id' column.")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_ingested_books_user_id ON ingested_books (user_id)"
        )
        conn.commit()


# ── Come si aggiunge la prossima migrazione ──────────────────────────────
# 1. Scrivi qui sopra una funzione idempotente (controlla prima di alterare;
#    su un database nuovo deve essere un no-op o produrre lo stesso schema
#    che create_all produce gia' — e' il vincolo fresh == migrated).
# 2. Aggiungila IN FONDO alla lista, con il numero successivo e un titolo
#    breve in inglese (finisce nei log e negli errori).
# 3. Mai riordinare, mai togliere, mai modificare una voce gia' spedita: i
#    database in giro ricordano solo un numero, e quel numero promette che
#    tutto cio' che viene prima e' gia' stato fatto cosi' com'era.
MIGRATIONS = [
    # Le prime tre voci sono il trasloco (20/11/2026) delle tre funzioni che
    # main.py chiamava a ogni avvio, nello stesso ordine di allora.
    (1, "additive columns and hot indexes (2025-2026 history)", add_missing_columns_and_hot_indexes),
    (2, "fraction_read on both reading-session tables", add_fraction_read_to_sessions),
    (3, "per-user reading positions, coverage and stats cache", rebuild_positions_per_user),
    (4, "device tokens become SHA-256 fingerprints", hash_device_tokens),
    (5, "drop devices.folder_layout (the option is gone)", drop_device_folder_layout),
    (6, "exact character columns on reading_sessions", add_exact_chars_to_reading_sessions),
    (7, "owner column on ingested_books", add_owner_to_ingested_books),
]


def _ensure_version_table(conn) -> None:
    """La tabella la crea il registro stesso, non create_all: cosi' esiste
    anche sui database nati prima di lei, ed e' il registro l'unico a
    scriverla."""
    conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER NOT NULL,"
        " applied_at DATETIME"
        ")"
    )


def current_version() -> int:
    """La versione corrente dello schema: 0 se la tabella manca o e' vuota
    (database nuovo, oppure vecchio ma di prima del registro — i due casi
    si trattano apposta allo stesso modo, vedi il docstring del modulo)."""
    with database.engine.connect() as conn:
        _ensure_version_table(conn)
        conn.commit()
        row = conn.exec_driver_sql("SELECT version FROM schema_version LIMIT 1").fetchone()
        return row[0] if row else 0


def _set_version(number: int) -> None:
    with database.engine.connect() as conn:
        updated = conn.exec_driver_sql(
            "UPDATE schema_version SET version = ?, applied_at = datetime('now')",
            (number,),
        ).rowcount
        if not updated:
            conn.exec_driver_sql(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
                (number,),
            )
        conn.commit()


def apply_pending() -> None:
    """
    Applica, in ordine, le migrazioni oltre la versione corrente.

    Chiamata da main.py all'avvio, dopo create_all e SENZA rete di
    sicurezza: una voce che fallisce ferma il giro, lascia la versione al
    numero dell'ultima riuscita, logga in modo inequivocabile QUALE voce e'
    caduta e perche', e rilancia l'eccezione — il server non parte su uno
    schema a meta'. Il perche' per esteso sta nel docstring del modulo.
    """
    # La promessa «mai riordinare, mai rinumerare» si controlla qui, una
    # volta per avvio: costa niente e trasforma un errore di distrazione
    # nell'elenco in un messaggio chiaro invece che in un database storto.
    numbers = [number for number, _, _ in MIGRATIONS]
    if numbers != list(range(1, len(MIGRATIONS) + 1)):
        raise RuntimeError(
            f"MIGRATIONS must be numbered 1..{len(MIGRATIONS)} in order, got {numbers}"
        )

    current = current_version()
    latest = numbers[-1] if numbers else 0
    if current > latest:
        # Un database toccato da un build piu' nuovo di questo codice. Non
        # e' questo registro a poterci fare qualcosa: si lascia stare, e lo
        # si dice.
        log_message(
            "warning", "system",
            f"Schema version {current} is newer than this build's latest migration ({latest}): "
            "leaving the schema alone.",
        )
        return

    for number, title, fn in MIGRATIONS:
        if number <= current:
            continue
        try:
            fn()
        except Exception as exc:
            log_message(
                "error", "system",
                f"SCHEMA MIGRATION {number} ('{title}') FAILED: {exc} — the schema stays at "
                f"version {number - 1} and the server will NOT start. Fix the cause and restart: "
                "the registry resumes from this same migration.",
            )
            raise
        _set_version(number)
        log_message("info", "system", f"Schema migration {number} ('{title}') applied.")
