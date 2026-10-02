import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import config, models
from ..calibre.library import CalibreLibrary
from ..calibre.functions import string_to_authors
from ..calibre.connection import PAGE_COUNT_COLUMN_LABEL, READ_FLAG_COLUMN_LABEL
from ..logging_utils import log_message
from . import book_hash_service
from . import app_settings

# Same threshold the sibling KoServer project's own processor.py uses to
# group KOReader's raw page_stat_data rows into logical reading sessions —
# ported wholesale, not reinvented.
_SESSION_GAP_SECONDS = 900  # 15 minutes

# How far back GET /stats/timeline's cached copy reaches — generous margin
# over the 365-day default any caller is expected to ask for, so the common
# case never needs a live recompute, only a slice of the cached window.
_TIMELINE_CACHE_DAYS = 400

# Qui viveva _COMPLETED_PERCENTAGE_THRESHOLD = 0.98, la soglia su
# ReadingPosition.percentage con cui si decideva se un libro fosse finito.
# Non c'e' piu': "completato" ora vuol dire spuntato a mano nella colonna
# `letto` (vedi compute_summary). Il difetto di quel criterio non era la
# soglia ma la domanda — percentage dice dove sei ARRIVATO, non se hai
# finito, e su una biblioteca vera dava due libri completati su 105 letti.


def record_live_tick(
    db: Session, user_id: int, library: str, calibre_book_id: int,
    device_id, source: str, now: datetime, pages_read_delta: int = 0,
) -> None:
    """
    Live counterpart to process_statistics_db's own batch session-grouping —
    called once per reading-position push (the web reader today, see
    books.py::put_reading_position) instead of once per statistics.sqlite3
    upload: extends the most recent session for this (library,
    calibre_book_id, device_id, source) if it ended less than
    _SESSION_GAP_SECONDS ago, otherwise starts a new one. Same threshold and
    philosophy as the batch path, just applied tick-by-tick instead of to a
    whole file at once — the KOReader batch path is untouched, it still
    grabs the device's own real page_stat_data durations wholesale.
    """
    last = db.query(models.ReadingSession).filter(
        # user_id: l'unico chiamante passa sempre device_id=None e
        # source="web", quindi senza questo filtro il solo discriminante
        # rimasto era il LIBRO. Su una biblioteca condivisa, chi spingeva una
        # posizione entro la finestra si vedeva allungare la sessione
        # dell'ALTRA persona: minuti accreditati a chi non ha letto, e
        # nessuna sessione per chi ha letto davvero.
        models.ReadingSession.user_id == user_id,
        models.ReadingSession.library == library,
        models.ReadingSession.calibre_book_id == calibre_book_id,
        models.ReadingSession.device_id == device_id,
        models.ReadingSession.source == source,
    ).order_by(models.ReadingSession.start_time.desc()).first()

    pages_delta = max(0, pages_read_delta)
    if last:
        end_time = last.start_time + timedelta(seconds=last.duration)
        gap = (now - end_time).total_seconds()
        if gap < 0:
            return  # out-of-order/duplicate tick (clock skew, double-fire) — nothing to do
        if gap < _SESSION_GAP_SECONDS:
            last.duration += int(gap)
            last.pages_read = (last.pages_read or 0) + pages_delta
            db.commit()
            return

    db.add(models.ReadingSession(
        user_id=user_id, library=library, calibre_book_id=calibre_book_id,
        device_id=device_id, source=source, start_time=now,
        duration=0, pages_read=pages_delta,
    ))
    db.commit()


def _resolve_book_identities(db: Session, md5: str) -> list:
    """
    KOReader's statistics.sqlite3 `book.md5` column IS the same
    KOReader-compatible partial-MD5 this app already computes/stores in
    BookHash (services/koreader_hash.py) — no separate id-mapping table
    needed, unlike KoServer's own schema (which keeps its own Book rows
    keyed by md5). Returns every (library, calibre_book_id) this hash
    resolves to — usually one, but the exact same file can legitimately
    exist in more than one library (same precedent as push_reading_progress
    in devices.py, which handles the identical ambiguity for KOSync pushes).
    """
    # BookHash vivo, più il ripiego su BookHashHistory quando il server ha
    # riscritto il file dopo che il dispositivo lo aveva hashato: entrambi in
    # book_hash_service.resolve_book_identities, condiviso con le posizioni
    # di lettura in devices.py (che senza quel ripiego le buttavano via).
    identities = book_hash_service.resolve_book_identities(db, md5)
    if identities:
        return identities
    # Last resort: a human manually confirmed this md5 (see
    # StatsHashPairing's own docstring) — covers the books that were
    # already orphaned before BookHashHistory existed, where there is
    # genuinely nothing left to recover automatically.
    pairing = db.query(models.StatsHashPairing).filter(models.StatsHashPairing.md5 == md5).first()
    if pairing:
        return [(pairing.library, pairing.calibre_book_id)]
    return []


def process_statistics_db(db_path: str, user_id: int, device_id, db: Session) -> dict:
    """
    Parses a KOReader statistics.sqlite3 file (uploaded wholesale as part of
    the device backup — see devices.py's upload_device_backup) into real,
    book-identified reading sessions and updates each resolved book's
    reading-coverage estimate.

    Session-grouping algorithm ported from the sibling KoServer project's
    own processor.py::process_statistics_db (15-minute gap threshold on
    page_stat_data, ordered by start_time) — this function's own PREVIOUS
    version stored KOReader's internal page_stat_data.id_book as if it were
    already a calibre_book_id (never resolved via any hash at all) and never
    grouped anything into sessions (one row per raw page-turn event) — see
    _resolve_book_identities for the fix, which reuses this app's existing
    BookHash table instead of KoServer's separate md5-keyed Book model.

    Returns a small summary dict for the caller to log/report.
    """
    summary = {
        "sessions_added": 0, "positions_updated": 0, "books_seen": 0,
        # Sessions whose local_book_id has NO BookHash match at all (book
        # never ingested/rescanned server-side, or genuinely not in any
        # library) — imported into OrphanReadingSession instead of dropped
        # (mirrors push_device_annotations' OrphanHighlight fallback for the
        # same kind of unresolved-hash gap; found while investigating
        # a "stats only show 2026" report from real use: a device's
        # statistics.sqlite3 can carry years of page_stat_data for books
        # that were never hashed server-side, and every single one of those
        # rows was being discarded with zero trace before this). If the
        # missing library later gets a rescan/recompute-hashes, THIS SAME
        # snapshot's next reprocess (see reprocess_all_device_backups) will
        # resolve them properly into real ReadingSession rows — no
        # watermark here, the whole file is re-walked every time — but the
        # orphan rows created in the meantime are not automatically cleaned
        # up (no pairing/migration flow built yet, same as OrphanHighlight's
        # own deferred pairing story).
        "sessions_skipped_unresolved": 0,
    }
    if not os.path.exists(db_path):
        return summary

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        # authors/series are present in every KOReader statistics.sqlite3
        # schema version we've seen, but queried defensively (checked via
        # PRAGMA first) rather than assumed — a missing column here would
        # otherwise hard-crash the whole ingestion (id/md5/pages/title are
        # load-bearing for the resolved path and always required; these two
        # are only used for the orphan fallback below, so degrading to NULL
        # is strictly better than losing every session in the file).
        book_columns = {row[1] for row in cursor.execute("PRAGMA table_info(book)").fetchall()}
        authors_expr = "authors" if "authors" in book_columns else "NULL"
        series_expr = "series" if "series" in book_columns else "NULL"
        cursor.execute(f"SELECT id, md5, pages, title, {authors_expr}, {series_expr} FROM book WHERE md5 IS NOT NULL")
        local_id_to_md5 = {}
        local_total_pages = {}
        local_id_to_title = {}
        local_id_to_authors = {}
        local_id_to_series = {}
        for local_id, md5, pages, title, authors, series in cursor.fetchall():
            local_id_to_md5[local_id] = md5
            if pages:
                local_total_pages[local_id] = pages
            local_id_to_title[local_id] = title
            local_id_to_authors[local_id] = authors
            local_id_to_series[local_id] = series
        summary["books_seen"] = len(local_id_to_md5)

        # Resolve once per distinct md5 (not per row) — a device's whole
        # library rarely changes between syncs, no need to re-query BookHash
        # for every single page-turn event.
        identities_by_local_id = {
            local_id: _resolve_book_identities(db, md5)
            for local_id, md5 in local_id_to_md5.items()
        }
        # Same "resolve once, not per row" reasoning — see StatsHashDiscard's
        # own docstring for what this set gates below.
        discarded_md5s = {
            r[0] for r in db.query(models.StatsHashDiscard.md5).filter(
                models.StatsHashDiscard.md5.in_(set(local_id_to_md5.values()))
            ).all()
        }

        # `total_pages` e' il totale di pagine di QUEL momento, e KOReader lo
        # registra riga per riga: 1/total_pages e' quindi la frazione di libro
        # di quella pagina, indipendente dal corpo del carattere. Senza questa
        # colonna si sommano pagine che valgono cose diverse — sui dati reali
        # fino a 2,7 volte l'una rispetto all'altra dentro lo stesso libro.
        cursor.execute(
            "SELECT id_book, start_time, duration, page, total_pages "
            "FROM page_stat_data ORDER BY start_time ASC"
        )
        rows = cursor.fetchall()

        sessions_to_add = []
        current_sess = None
        # Mappa della copertura per libro (locale al dispositivo): si
        # riempie mentre si scorrono le righe, e si unisce a quella gia'
        # nota solo alla fine, quando si sa a quale libro della biblioteca
        # corrisponde. Vedi models.BookReadingCoverage.
        mappe = {}
        max_page_reached = {}   # local_book_id -> highest page number seen
        distinct_pages = {}     # local_book_id -> set of distinct page numbers seen

        for local_book_id, start_ts, duration, page_num, total_pages in rows:
            if local_book_id not in local_id_to_md5:
                continue  # book has no md5 in this snapshot — nothing to resolve it to

            # Una pagina su un totale sconosciuto non dice quanto libro sia:
            # meglio non contarla che contarla male.
            frazione = (1.0 / total_pages) if total_pages and total_pages > 0 else 0.0
            _segna_pagina(mappe.setdefault(local_book_id, bytearray(_BINS // 8)), page_num, total_pages)

            if page_num > max_page_reached.get(local_book_id, 0):
                max_page_reached[local_book_id] = page_num
            distinct_pages.setdefault(local_book_id, set()).add(page_num)

            start_dt = datetime.utcfromtimestamp(start_ts)
            if (
                current_sess and current_sess["local_book_id"] == local_book_id
                and (start_dt - current_sess["end_time"]).total_seconds() < _SESSION_GAP_SECONDS
            ):
                current_sess["duration"] += duration
                current_sess["pages_read"] += 1
                current_sess["fraction_read"] += frazione
                current_sess["end_time"] = start_dt + timedelta(seconds=duration)
            else:
                if current_sess:
                    sessions_to_add.append(current_sess)
                current_sess = {
                    "local_book_id": local_book_id,
                    "start_time": start_dt,
                    "duration": duration,
                    "pages_read": 1,
                    "fraction_read": frazione,
                    "end_time": start_dt + timedelta(seconds=duration),
                }
        if current_sess:
            sessions_to_add.append(current_sess)

        # La copertura e' una proprieta' del LIBRO — ma non del libro "come lo
        # vede il dispositivo": lo stesso libro puo' arrivare da PIU' md5 (il
        # file riscritto sul server dopo che il dispositivo l'aveva gia'
        # hashato) e ogni md5 puo' risolvere a piu' righe BookHash, una per
        # formato. Le mappe si uniscono quindi PRIMA, e si scrive una volta
        # sola per libro.
        #
        # Scrivendo una riga per ogni risoluzione, il secondo inserimento
        # sullo stesso libro violava il vincolo di unicita' e mandava in
        # errore l'intero ricalcolo: e' l'"UNIQUE constraint failed" che
        # arrivava all'utente come "Ricalcolo non riuscito".
        per_libro = {}
        for local_book_id, mappa in mappe.items():
            for identita in identities_by_local_id.get(local_book_id, []):
                accumulata = per_libro.get(identita)
                if accumulata is None:
                    per_libro[identita] = bytearray(mappa)
                else:
                    for i in range(len(accumulata)):
                        accumulata[i] |= mappa[i]
        for (library, calibre_book_id), mappa in per_libro.items():
            aggiorna_copertura(db, user_id, library, calibre_book_id, mappa)

        unresolved_titles = set()
        for s in sessions_to_add:
            identities = identities_by_local_id.get(s["local_book_id"], [])
            if not identities:
                md5 = local_id_to_md5[s["local_book_id"]]
                if md5 in discarded_md5s:
                    # A human already decided this hash isn't worth tracking
                    # (see StatsHashDiscard's own docstring) — skip silently,
                    # not even counted as unresolved, so a discarded book
                    # doesn't keep nagging in logs on every future sync.
                    continue
                summary["sessions_skipped_unresolved"] += 1
                unresolved_titles.add(local_id_to_title.get(s["local_book_id"]) or f"id_book={s['local_book_id']}")
                existing_orphan = db.query(models.OrphanReadingSession).filter(
                    models.OrphanReadingSession.device_id == device_id,
                    models.OrphanReadingSession.md5 == md5,
                    models.OrphanReadingSession.start_time == s["start_time"],
                ).first()
                if not existing_orphan:
                    db.add(models.OrphanReadingSession(
                        user_id=user_id, device_id=device_id, md5=md5,
                        title=local_id_to_title.get(s["local_book_id"]),
                        authors=local_id_to_authors.get(s["local_book_id"]),
                        series=local_id_to_series.get(s["local_book_id"]),
                        start_time=s["start_time"], duration=s["duration"],
                        pages_read=s["pages_read"], fraction_read=s["fraction_read"],
                    ))
                continue
            for library, calibre_book_id in identities:
                # Una sessione di lettura e' identificata da BIBLIOTECA, LIBRO
                # e ISTANTE DI INIZIO. Il dispositivo NON fa parte della
                # chiave, e includerlo era un bug vero.
                #
                # Chi sincronizza statistics.sqlite3 fra due dispositivi (con
                # Syncthing e' pratica corrente fra gli utenti KOReader) fa
                # arrivare a Kolibre la stessa identica sessione due volte, da
                # due device_id diversi: con il dispositivo nella chiave i due
                # controlli non si vedevano e nascevano due righe, sempre, per
                # costruzione.
                #
                # Misurato su dati reali: 737 delle 743 sessioni di un
                # dispositivo erano copie esatte di sessioni dell'altro —
                # stesso libro, stessa durata, stesso start_time al secondo, e
                # le due storie cominciavano nel medesimo istante. Il 46%
                # delle ore registrate non era mai stato letto.
                #
                # Due dispositivi che cominciano lo stesso libro nello stesso
                # secondo non sono una cosa che capita: meglio fondere una
                # coincidenza rarissima che raddoppiare una biblioteca intera.
                existing = db.query(models.ReadingSession).filter(
                    # L'utente SI', il dispositivo no. Il ragionamento sopra
                    # spiega perche' due dispositivi della stessa persona
                    # devono fondersi; fra due PERSONE non vale: su una
                    # biblioteca condivisa, chi caricava il proprio
                    # statistics.sqlite3 per secondo trovava le righe
                    # dell'altro con lo stesso start_time e le saltava, quindi
                    # le sue letture non venivano mai registrate — senza
                    # niente nel log.
                    models.ReadingSession.user_id == user_id,
                    models.ReadingSession.library == library,
                    models.ReadingSession.calibre_book_id == calibre_book_id,
                    models.ReadingSession.start_time == s["start_time"],
                ).first()
                if existing:
                    # A session is keyed by its START time, and KOReader keeps
                    # extending the same session while you read: reprocessing a
                    # later backup of the same statistics.sqlite3 brings back
                    # the SAME start_time with a LARGER duration and page
                    # count. Skipping outright froze every session at whatever
                    # length it happened to have when the first backup was
                    # taken — and "carica backup" can fire on app start, book
                    # open and book close, so a session interrupted by one was
                    # truncated permanently, with no way to recover it later.
                    # Only ever grow: a partial backup must never shrink a
                    # session we already know to be longer.
                    if (s["duration"] or 0) > (existing.duration or 0):
                        existing.duration = s["duration"]
                    if (s["pages_read"] or 0) > (existing.pages_read or 0):
                        existing.pages_read = s["pages_read"]
                    # Stessa regola del resto: una sessione puo' solo
                    # crescere, mai rimpicciolirsi per colpa di un backup
                    # parziale.
                    if (s["fraction_read"] or 0) > (existing.fraction_read or 0):
                        existing.fraction_read = s["fraction_read"]
                    # Il dispositivo resta quello che ha registrato per primo
                    # la sessione: se la stessa lettura riarriva da un secondo
                    # dispositivo e' una copia, non un secondo lettore, e
                    # riscrivere device_id farebbe migrare la sessione
                    # sull'ultimo che ha sincronizzato.
                    continue
                db.add(models.ReadingSession(
                    user_id=user_id, library=library, calibre_book_id=calibre_book_id,
                    device_id=device_id, source="koreader", start_time=s["start_time"],
                    duration=s["duration"], pages_read=s["pages_read"],
                    fraction_read=s["fraction_read"],
                ))
                summary["sessions_added"] += 1
            # Now resolved (possibly only via the BookHashHistory fallback
            # above) — drop any OrphanReadingSession an earlier reprocess
            # created for this exact session before the hash existed/matched,
            # so a book doesn't keep showing as both orphaned and resolved.
            db.query(models.OrphanReadingSession).filter(
                models.OrphanReadingSession.device_id == device_id,
                models.OrphanReadingSession.md5 == local_id_to_md5[s["local_book_id"]],
                models.OrphanReadingSession.start_time == s["start_time"],
            ).delete()

        if summary["sessions_skipped_unresolved"]:
            # Warning-level, not silent: this is exactly the kind of gap that
            # made the stats dashboard look like it only had 2026 data —
            # years of real history sitting in the backup file, unresolved
            # because these titles never got a BookHash (rescan/
            # recompute-hashes fixes it going forward, from THIS SAME file).
            # Now imported into OrphanReadingSession rather than discarded,
            # but still worth a log line: the normal dashboards don't show
            # orphan data, so this is the only visible signal of the gap.
            log_message(
                "warning", "stats",
                f"Backup statistics.sqlite3 del dispositivo {device_id}: "
                f"{summary['sessions_skipped_unresolved']} sessioni importate come orfane "
                f"(nessun BookHash corrispondente) per {len(unresolved_titles)} "
                f"libri: {', '.join(sorted(unresolved_titles))[:500]}",
            )

        for local_id, identities in identities_by_local_id.items():
            total_pages = local_total_pages.get(local_id)
            if not total_pages:
                continue
            n_distinct = len(distinct_pages.get(local_id, ()))
            if not n_distinct:
                continue
            coverage = min(100.0, round(n_distinct / total_pages * 100, 1))
            for library, calibre_book_id in identities:
                position = db.query(models.ReadingPosition).filter(
                    models.ReadingPosition.user_id == user_id,
                    models.ReadingPosition.library == library,
                    models.ReadingPosition.calibre_book_id == calibre_book_id,
                ).first()
                # Only updates an EXISTING position row (created by the real
                # KOSync push, which also owns percentage/progress) — a book
                # never opened through the reader/KOSync yet has no row to
                # attach a coverage estimate to, and creating one here with
                # no percentage/progress would violate those columns'
                # nullable=False.
                if position and coverage > (position.coverage_percent or 0):
                    position.coverage_percent = coverage
                    summary["positions_updated"] += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        conn.close()
    return summary


def pair_orphan_sessions(db: Session, user_id, md5: str, library: str, calibre_book_id: int) -> dict:
    """
    The "Accoppia manualmente" action for orphan reading sessions — see
    StatsHashPairing's own docstring for why this exists (the definitive
    fix for history orphaned before BookHashHistory did, which has nothing
    left to recover automatically). Mirrors devices.py's
    _migrate_orphan_highlights: get-or-create the pairing row (idempotent —
    re-pairing the same md5 just repoints it), copy every OrphanReadingSession
    with this md5 into a real ReadingSession (deduped the same way
    process_statistics_db already dedupes, by library+calibre_book_id+
    device_id+start_time, in case a reprocess in the meantime already
    resolved some of them another way), then delete the now-migrated
    orphan rows. Global by md5, not scoped to one device or one user's
    orphan rows only — see StatsHashPairing's own docstring for why.
    """
    pairing = db.query(models.StatsHashPairing).filter(models.StatsHashPairing.md5 == md5).first()
    if pairing:
        pairing.library = library
        pairing.calibre_book_id = calibre_book_id
        pairing.paired_by_user_id = user_id
    else:
        db.add(models.StatsHashPairing(
            md5=md5, library=library, calibre_book_id=calibre_book_id, paired_by_user_id=user_id,
        ))

    orphans = db.query(models.OrphanReadingSession).filter(models.OrphanReadingSession.md5 == md5).all()
    migrated = 0
    for orphan in orphans:
        existing = db.query(models.ReadingSession).filter(
            models.ReadingSession.library == library,
            models.ReadingSession.calibre_book_id == calibre_book_id,
            models.ReadingSession.device_id == orphan.device_id,
            models.ReadingSession.start_time == orphan.start_time,
        ).first()
        if not existing:
            db.add(models.ReadingSession(
                user_id=orphan.user_id, library=library, calibre_book_id=calibre_book_id,
                device_id=orphan.device_id, source="koreader", start_time=orphan.start_time,
                duration=orphan.duration, pages_read=orphan.pages_read,
            ))
            migrated += 1
        db.delete(orphan)

    db.commit()
    return {"sessions_migrated": migrated, "sessions_already_resolved": len(orphans) - migrated}


def discard_orphan_sessions(db: Session, user_id, md5: str) -> int:
    """
    The "Scarta" action for orphan reading sessions — the complement of
    pair_orphan_sessions above, for the case a probable book (per its
    self-reported title/author) is genuinely not worth tracking for
    statistics at all, rather than mismatched to the wrong Calibre book.
    Get-or-create the StatsHashDiscard row (idempotent, same shape as the
    pairing side), then delete every existing OrphanReadingSession for this
    md5 outright — there is nothing to migrate anywhere, unlike pairing.
    Global by md5, same scope as StatsHashPairing/pair_orphan_sessions.
    """
    existing = db.query(models.StatsHashDiscard).filter(models.StatsHashDiscard.md5 == md5).first()
    if not existing:
        db.add(models.StatsHashDiscard(md5=md5, discarded_by_user_id=user_id))

    removed = db.query(models.OrphanReadingSession).filter(models.OrphanReadingSession.md5 == md5).delete()
    db.commit()
    return removed


def reprocess_all_device_backups(db: Session) -> dict:
    """
    Re-parses every device's already-stored statistics.sqlite3 through
    process_statistics_db. Exists because that function otherwise only ever
    runs synchronously inside upload_device_backup itself, at the moment of
    upload — a backup already sitting on disk from BEFORE this stats
    feature existed (or from before the server was last redeployed with it)
    would otherwise never be processed at all, with no way to catch up
    short of the device re-uploading. devices.py's upload_device_backup
    always overwrites this same path in place
    ({BACKUPS_DIR}/{device_id}/statistics.sqlite3, no versioning), so only
    the latest snapshot is ever recoverable this way — acceptable since
    KOReader's own statistics.sqlite3 is itself cumulative (a later upload
    normally still contains everything an older one did).

    Called by the periodic refresh loop (see main.py::_refresh_stats_loop);
    process_statistics_db's own dedup-by-start_time check makes repeated
    calls across every refresh cycle safe, not just a one-time backfill.
    """
    summary = {"devices_processed": 0, "sessions_added": 0, "sessions_skipped_unresolved": 0}
    for device in db.query(models.Device).all():
        db_path = os.path.join(config.BACKUPS_DIR, str(device.id), "statistics.sqlite3")
        if not os.path.exists(db_path):
            continue
        result = process_statistics_db(db_path, device.user_id, device.id, db)
        summary["devices_processed"] += 1
        summary["sessions_added"] += result["sessions_added"]
        summary["sessions_skipped_unresolved"] += result["sessions_skipped_unresolved"]
    return summary


# Quanti tag portarsi dietro per libro. I tag sono l'unico campo di
# lunghezza non limitata fra quelli che finiscono in ogni riga di sessione,
# e le righe finiscono tutte dentro StatsCache.raw_json: un libro con
# quaranta tag moltiplicato per le sue sessioni gonfierebbe la cache senza
# che nessun grafico ne tragga vantaggio (oltre i primi, i tag di un libro
# sono quasi sempre dettagli). Tre bastano per raggruppare.
_MAX_TAG_PER_LIBRO = 3


def _decennio(pubdate) -> str:
    """'1867-09-14...' -> '1860'. Serve per raggruppare per epoca di
    pubblicazione senza che ogni anno faccia gruppo a se'."""
    if not pubdate:
        return None
    anno = str(pubdate)[:4]
    if not anno.isdigit():
        return None
    return f"{int(anno) // 10 * 10}"


def _book_meta_map(library: str) -> dict:
    """
    calibre_book_id -> metadati del libro, per ogni libro della biblioteca,
    con una sola CalibreLibrary.list_books() — same batched-lookup shape as
    devices.py's own _build_book_titles, kept as a separate copy (not a
    shared import) so this module stays decoupled from devices.py, same
    reasoning that file's own docstring already gives for its twin in
    annotations.py.

    Oltre a titolo/autore/pagine/formato porta ora anche serie, tag, lingua,
    editore, valutazione e decennio. Non servono a compute_summary: servono
    a compute_raw, cioe' alla riga di sessione, e da li' al costruttore di
    grafici — che pivota su qualunque campo la riga contenga, quindi ogni
    campo aggiunto qui diventa una dimensione di raggruppamento e un filtro
    in piu' senza una riga di interfaccia.

    Il perche' e' il buco principale del cruscotto: la scheda Libreria sa i
    tag e la lingua, la scheda Lettura sa il tempo, e le due non si
    parlavano mai. Domande come "leggo davvero quello che colleziono" non
    erano difficili, erano impossibili da porre.
    """
    try:
        lib = CalibreLibrary(config.library_path(library))
        meta = {}
        for b in lib.list_books():
            tags = b.get("tags") or []
            meta[b["id"]] = {
                "title": b["title"],
                "author": b["author"] or "Autore Sconosciuto",
                "pages": b.get(f"#{PAGE_COUNT_COLUMN_LABEL}"),
                # Joined (not just the first) — a handful of books carry more
                # than one format (epub+pdf) and dropping the rest would
                # under-count them in the chart builder's "format" group-by.
                "format": ", ".join(sorted(b.get("formats") or [])) or "Sconosciuto",
                "series": b.get("series"),
                "tags": tags[:_MAX_TAG_PER_LIBRO],
                "language": b.get("language"),
                "publisher": b.get("publisher"),
                "rating": b.get("rating"),
                "decade": _decennio(b.get("pubdate")),
                # La spunta "letto": e' lei a dire quali libri sono finiti.
                # Calibre tiene i bool come 0/1, il lettore puo' gia' averli
                # convertiti — si accettano entrambe le forme.
                "letto": b.get(f"#{READ_FLAG_COLUMN_LABEL}") in (True, 1),
            }
        return meta
    except Exception:
        return {}


# L'ambito "tutte le biblioteche", scritto cosi' nel parametro `library`.
#
# Un asterisco e non una parola perche' non puo' collidere con il nome di
# una cartella: e' l'unico modo di dire "tutte" senza dover aggiungere un
# parametro a ogni endpoint e a ogni chiamata del browser.
#
# Perche' serva: le statistiche erano legate a UNA biblioteca, e in un
# impianto reale la lettura e il catalogo stanno in posti diversi — 1.703
# sessioni nella biblioteca personale, 5.843 libri nel magazzino. Il menu'
# costringeva a scegliere fra una storia ricca e un catalogo ricco, e
# non esisteva nessun numero che rispondesse a "quanto ho letto in vita
# mia". Resta un'OPZIONE e non il comportamento predefinito: le due
# biblioteche sono due usi diversi del programma, e la separazione serve.
AMBITO_TUTTE = "*"


def _senza_rumore(db: Session, sessioni: list) -> list:
    """
    Toglie le sessioni piu' brevi della soglia, se ne e' stata scelta una.

    Filtra ALLA SORGENTE, cioe' dentro le funzioni che alimentano la cache,
    perche' la soglia deve valere per tutto il cruscotto insieme: un totale
    che la rispetta accanto a un grafico che non la rispetta sarebbe peggio
    che non averla.

    Di preimpostazione la soglia e' zero e qui non succede niente — vedi
    app_settings.get_soglia_sessione per il perche' non sia accesa d'ufficio.
    """
    soglia = app_settings.get_soglia_sessione(db)
    if soglia <= 0:
        return sessioni
    return [s for s in sessioni if (s.duration or 0) >= soglia]


def _ambiti(db: Session, library: str) -> list:
    """Le biblioteche su cui lavorare: una sola, o tutte quelle registrate."""
    if library != AMBITO_TUTTE:
        return [library]
    return [r[0] for r in db.query(models.Library.folder_name).all()]


def _mappa_libri(db: Session, library: str) -> dict:
    """
    (biblioteca, id_libro) -> metadati, per ogni biblioteca dell'ambito.

    La chiave e' una COPPIA e non l'id da solo: calibre_book_id e' unico
    dentro una biblioteca, non fra biblioteche diverse. Con l'ambito globale
    l'id 7 esiste in tutte, e usarlo da solo mescolerebbe libri che non
    c'entrano niente fra loro.
    """
    unita = {}
    for folder in _ambiti(db, library):
        for book_id, meta in _book_meta_map(folder).items():
            unita[(folder, book_id)] = meta
    return unita


def _quanti_letti(db: Session, library: str) -> int:
    """Quanti libri dell'ambito sono spuntati come letti."""
    return sum(1 for m in _mappa_libri(db, library).values() if m.get("letto"))


def _anno(data_iso) -> int | None:
    """L'anno da una data che puo' essere solo un anno, e puo' essere a.C."""
    if not data_iso:
        return None
    testo = str(data_iso).strip()
    negativo = testo.startswith("-")
    if negativo:
        testo = testo[1:]
    cifre = testo[:4]
    if not cifre.isdigit():
        return None
    return -int(cifre) if negativo else int(cifre)


def _elenco(campo) -> list:
    """I campi di AuthorMetadata che portano piu' valori separati da "; "."""
    if not campo:
        return []
    return [v.strip() for v in str(campo).split(";") if v.strip()]


def _primo_elenco(campo):
    valori = _elenco(campo)
    return valori[0] if valori else None


def libri_letti(db: Session, utente) -> dict:
    """
    I libri spuntati come letti, con l'anagrafica di chi li ha scritti.

    **Perche' un endpoint a se' e non una riga di sessione.** Tutto il resto
    delle statistiche di lettura nasce da `ReadingSession`, e una sessione sa
    quanto hai letto ma non se hai FINITO. "Finito" e' la spunta `letto` sul
    libro, cioe' un fatto del catalogo — e su dati reali i due insiemi non
    coincidono nemmeno per approssimazione: 131 libri spuntati, 109 libri con
    almeno una sessione. Un conteggio di "libri letti" costruito dalle sessioni
    risponderebbe a un'altra domanda e lo farebbe sembrare la stessa.

    **Senza ambito di biblioteca**, di proposito: quanti libri ho letto in vita
    mia non e' una proprieta' di una cartella. Si guardano tutte quelle che
    l'utente puo' leggere.

    L'anagrafica (nascita, nazionalita', genere) arriva da `AuthorMetadata`, che
    il recupero online riempie: su una storia di lettura reale, dei 75 autori
    letti ne conosce 66 per
    la nascita e 67 per nazionalita' e genere — abbastanza per un grafico, non
    abbastanza per tacere su quanti mancano, che e' il motivo per cui
    `senza_anagrafica` viene restituito.

    Di un libro a piu' mani si guarda il PRIMO autore. Una data di nascita non
    si puo' mediare, e attribuire il libro a tutti e tre lo conterebbe tre
    volte in un istogramma che dice "libri".
    """
    anagrafica = {
        m.author_name: m
        for m in db.query(models.AuthorMetadata).all()
    }
    libri = []
    senza = set()
    # Le biblioteche che QUESTA persona puo' leggere, come il docstring
    # dichiara da sempre: il codice invece le prendeva tutte, e un utente con
    # una sola biblioteca condivisa riceveva titolo, autore e anagrafica di
    # ogni libro spuntato «letto» nelle biblioteche private di chiunque altro.
    from . import permessi
    for folder in [b.folder_name for b in permessi.biblioteche_visibili(db, utente)]:
        for book_id, meta in _book_meta_map(folder).items():
            if not meta.get("letto"):
                continue
            autori = string_to_authors(meta.get("author") or "")
            primo = autori[0] if autori else "Autore Sconosciuto"
            a = anagrafica.get(primo)
            if a is None or not a.birth_date:
                senza.add(primo)
            libri.append({
                "library": folder,
                "book_id": book_id,
                "title": meta.get("title") or "Sconosciuto",
                "author": primo,
                "autori": autori,
                "pages": meta.get("pages") or 0,
                "decade": meta.get("decade"),
                "language": meta.get("language"),
                "rating": meta.get("rating"),
                "author_birth_year": _anno(a.birth_date) if a else None,
                "author_death_year": _anno(a.death_date) if a else None,
                "author_gender": (a.gender if a else None) or None,
                # Nazionalita' e occupazioni sono liste separate da "; ".
                # Della nazionalita' si prende la PRIMA: Wikidata ne da' spesso
                # piu' d'una (chi ha cambiato paese, e chi e' nato in uno stato
                # che non esiste piu'), e contarle tutte moltiplicherebbe il
                # libro per quante sono. Delle occupazioni si tengono tutte,
                # perche' li' la molteplicita' e' il dato: un filosofo che e'
                # anche romanziere e' entrambe le cose, e un istogramma delle
                # occupazioni conta occupazioni, non libri.
                "author_nationality": _primo_elenco(a.nationality) if a else None,
                "author_occupations": _elenco(a.occupations) if a else [],
            })
    libri.sort(key=lambda b: (b["author"].lower(), b["title"].lower()))
    return {
        "libri": libri,
        "totale": len(libri),
        "senza_anagrafica": sorted(senza),
    }


def compute_summary(db: Session, library: str, user_id: int) -> dict:
    """
    Global + current-year + personal-record counters — mirrors the sibling
    KoServer project's own /stats/summary. Everything here is derived
    straight from ReadingSession (both koreader and web sources, unified);
    "longest book" is the one exception, which is a library-metadata fact
    (page count) rather than a reading-session fact, so it's resolved via
    _book_meta_map instead. Called by refresh_stats_cache (background) —
    GET /api/kolibre/stats/summary just reads the cached result.

    best_year/longest_book_by_time/top_author_by_time/longest_streak are the
    "richer records" added alongside the pie-chart work and the global-stats
    follow-up: the first three (plus total_books_completed) fold into the
    same single pass over `sessions` below (books_by_year/duration_by_book/
    duration_by_author) instead of separate queries; longest_streak is
    derived from that same pass's `by_day` grouping. total_books_completed
    is the one exception needing its own query, since reading-completion
    lives on ReadingPosition (one row per book, latest-wins), a table
    compute_summary otherwise never touches.

    OrphanReadingSession rows (the complaint behind them: "perché devo per
    forza accoppiare i libri per vederne le statistiche?") are folded into
    every KPI below that
    doesn't strictly require a resolved calibre_book_id — total time/pages/
    books, year totals, best day, longest session, streak, and even "top
    author by time" (orphans self-report an author string, no lookup
    needed). Two KPIs stay resolved-only on purpose: "longest book by page
    count" (OrphanReadingSession has no total-page-count field, only
    per-session pages turned — nothing to compare against _book_meta_map's
    `pages`) and "total_books_completed" (completion is a ReadingPosition
    fact, which requires a real calibre_book_id to exist at all). Orphans
    have no `library` column at all (see the model's own docstring) — every
    orphan is folded into EVERY library's own summary, not deduped across
    libraries: an honest overcount risk in a multi-library setup, chosen
    deliberately over the alternative (silently undercounting real reading
    just because it hasn't been paired yet). Resolved for good, permanently,
    the moment a session is paired — see pair_orphan_sessions, which deletes
    the orphan row once it becomes a real ReadingSession.
    """
    ambiti = _ambiti(db, library)
    sessions = _senza_rumore(db, db.query(models.ReadingSession).filter(
        models.ReadingSession.user_id == user_id,
        models.ReadingSession.library.in_(ambiti)
    ).all())
    # Con l'ambito globale gli orfani si contano UNA volta, che e' la
    # risposta giusta: non avendo una biblioteca finivano dentro il
    # riassunto di ognuna, cioe' moltiplicati per quante ne esistono.
    orphans = _senza_rumore(db, db.query(models.OrphanReadingSession).filter(
        models.OrphanReadingSession.user_id == user_id
    ).all())
    if not sessions and not orphans:
        # Tutto a zero tranne i libri completati: da quando "completato"
        # vuol dire spuntato a mano, non dipende piu' dalle sessioni. Chi ha
        # segnato duecento libri letti e non ha mai sincronizzato un
        # dispositivo deve vedere duecento, non zero.
        return {
            "total_time_seconds": 0, "total_books": 0, "total_pages": 0,
            "total_chars": 0, "chars_time_seconds": 0,
            "total_books_completed": _quanti_letti(db, library),
            "year_time_seconds": 0, "year_books": 0, "year_pages": 0,
            "best_day_seconds": 0, "longest_session_seconds": 0,
            "longest_book_title": None, "longest_book_pages": 0,
            "best_year": None, "best_year_books": 0,
            "longest_book_by_time_title": None, "longest_book_by_time_seconds": 0,
            "top_author_by_time_name": None, "top_author_by_time_seconds": 0,
            "longest_streak_days": 0, "longest_streak_start": None, "longest_streak_end": None,
        }

    year_start = datetime(datetime.utcnow().year, 1, 1)
    year_sessions = [s for s in sessions if s.start_time >= year_start]
    year_orphans = [o for o in orphans if o.start_time >= year_start]

    by_day = defaultdict(int)
    for s in sessions:
        by_day[s.start_time.date()] += s.duration
    for o in orphans:
        by_day[o.start_time.date()] += o.duration

    book_meta = _mappa_libri(db, library)
    # Ogni libro e' identificato da (biblioteca, id): vedi _mappa_libri.
    book_ids_read = {(s.library, s.calibre_book_id) for s in sessions}
    # An orphan's md5 is the only stable identity it carries — two orphan
    # sessions sharing an md5 are unambiguously the same not-yet-resolved
    # book, same role calibre_book_id plays for resolved sessions.
    orphan_md5s_read = {o.md5 for o in orphans}

    # Completato = SPUNTATO. Non dedotto.
    #
    # Prima lo decideva ReadingPosition, cioe' "dove sei arrivato": un
    # libro contava come finito solo se un dispositivo aveva spinto una
    # posizione oltre il 98%. Su dati reali quel criterio diceva
    # DUE libri completati dopo 193 ore di lettura — 89 righe di posizione
    # per 105 libri letti, e appena due sopra la soglia. Non era un errore
    # di calcolo: e' che "completato" non era mai stato definito, e la
    # tabella che faceva da giudice non era stata pensata per quel ruolo.
    #
    # Ora esiste la colonna `letto` (vedi connection.py), che una persona
    # spunta. E' l'unica fonte che sa che un libro l'hai finito su carta, o
    # che l'hai abbandonato a pagina 300 e non lo riprenderai. La copertura
    # resta a suggerire chi spuntare (pagina Interventi), mai a decidere.
    #
    # Conseguenza voluta: finche' non si spunta niente il contatore dice
    # zero. Uno zero che vuol dire "non hai ancora detto quali hai finito"
    # e' onesto; un due che vuol dire "il mio giudice e' rotto" no.
    completed_book_ids = {
        book_id for book_id, meta in book_meta.items() if meta.get("letto")
    }

    longest_book_id, longest_book_pages = None, 0
    for chiave in book_ids_read:
        pages = (book_meta.get(chiave) or {}).get("pages") or 0
        if pages > longest_book_pages:
            longest_book_id, longest_book_pages = chiave, pages

    # books-per-year (distinct book ids per calendar year), duration-per-book
    # and duration-per-author, all derived from this same session list.
    books_by_year = defaultdict(set)
    duration_by_book = defaultdict(int)
    duration_by_author = defaultdict(int)
    for s in sessions:
        chiave = (s.library, s.calibre_book_id)
        books_by_year[s.start_time.year].add(chiave)
        duration_by_book[chiave] += s.duration
        author = (book_meta.get(chiave) or {}).get("author") or "Autore Sconosciuto"
        duration_by_author[author] += s.duration
    # duration_by_book stays resolved-only: "longest book BY TIME" below
    # needs a title for whichever id wins, and only book_meta (keyed by
    # calibre_book_id) can supply one — orphans get their own parallel
    # by-md5 tally instead, compared against this one further down.
    orphan_duration_by_md5 = defaultdict(int)
    orphan_title_by_md5 = {}
    # orphans have no calibre_book_id, so they can never appear in
    # completed_book_ids (see its own comment above) and must stay out of
    # "books READ per year" — same scope limit total_books_completed
    # already had, so books_by_year (resolved sessions only) needs no
    # orphan contribution at all anymore.
    for o in orphans:
        duration_by_author[o.authors or "Autore Sconosciuto"] += o.duration
        orphan_duration_by_md5[o.md5] += o.duration
        orphan_title_by_md5[o.md5] = o.title or "Sconosciuto"

    # "Anno con più libri letti" = year with the most books actually
    # COMPLETED (per completed_book_ids), not merely touched — same fix as
    # year_books below, same underlying bug.
    best_year, best_year_books = None, 0
    for year, ids in books_by_year.items():
        completed_count = len(ids & completed_book_ids)
        if completed_count > best_year_books:
            best_year, best_year_books = year, completed_count

    longest_time_book_id = max(duration_by_book, key=duration_by_book.get, default=None)
    longest_time_book_seconds = duration_by_book.get(longest_time_book_id, 0)
    longest_time_orphan_md5 = max(orphan_duration_by_md5, key=orphan_duration_by_md5.get, default=None)
    longest_time_orphan_seconds = orphan_duration_by_md5.get(longest_time_orphan_md5, 0)
    # Whichever of "best resolved book" / "best orphan" actually read longer
    # wins the "longest book by time" record — a book shouldn't lose this
    # record just because it hasn't been paired yet.
    if longest_time_orphan_seconds > longest_time_book_seconds:
        longest_book_by_time_title = orphan_title_by_md5.get(longest_time_orphan_md5)
        longest_book_by_time_seconds = longest_time_orphan_seconds
    else:
        longest_book_by_time_title = (
            (book_meta.get(longest_time_book_id) or {}).get("title") if longest_time_book_id else None
        )
        longest_book_by_time_seconds = longest_time_book_seconds

    top_author_name = max(duration_by_author, key=duration_by_author.get, default=None)

    total_books_completed = len(completed_book_ids)

    # Longest run of consecutive calendar days with >=1 reading session,
    # found by sorting by_day's distinct dates once and walking gaps between
    # consecutive entries — reuses the same by_day grouping best_day_seconds
    # already needed, no extra query.
    sorted_days = sorted(by_day.keys())
    longest_streak_days, longest_streak_start, longest_streak_end = 0, None, None
    if sorted_days:
        run_start = sorted_days[0]
        best_len, best_start, best_end = 1, sorted_days[0], sorted_days[0]
        run_len = 1
        for prev_day, curr_day in zip(sorted_days, sorted_days[1:]):
            if (curr_day - prev_day).days == 1:
                run_len += 1
            else:
                run_start = curr_day
                run_len = 1
            if run_len > best_len:
                best_len, best_start, best_end = run_len, run_start, curr_day
        longest_streak_days, longest_streak_start, longest_streak_end = best_len, best_start, best_end

    # Caratteri letti, e il tempo delle sessioni che li hanno.
    #
    # I due numeri viaggiano insieme perche' servono insieme: la velocita' di
    # lettura e' caratteri diviso ore, e dividere i caratteri di ALCUNE
    # sessioni per le ore di TUTTE darebbe una velocita' sistematicamente
    # troppo bassa — tanto piu' bassa quanto meno libri hanno il conteggio
    # del testo. Con tutte e due, chi legge puo' dividere le cose giuste.
    caratteri_per_libro = {}
    for folder in ambiti:
        for book_id, n in _chars_map(db, folder).items():
            caratteri_per_libro[(folder, book_id)] = n
    total_chars = 0
    chars_time_seconds = 0
    for s in sessions:
        c = _chars_read(s.fraction_read, caratteri_per_libro.get((s.library, s.calibre_book_id)))
        if c:
            total_chars += c
            chars_time_seconds += s.duration

    return {
        "total_time_seconds": sum(s.duration for s in sessions) + sum(o.duration for o in orphans),
        "total_books": len(book_ids_read) + len(orphan_md5s_read),
        "total_pages": sum(s.pages_read or 0 for s in sessions) + sum(o.pages_read or 0 for o in orphans),
        "total_chars": total_chars,
        "chars_time_seconds": chars_time_seconds,
        "total_books_completed": total_books_completed,
        "year_time_seconds": sum(s.duration for s in year_sessions) + sum(o.duration for o in year_orphans),
        # I libri davvero FINITI quest'anno, non quelli soltanto aperti —
        # vedi il commento a completed_book_ids qui sopra.
        "year_books": len({(s.library, s.calibre_book_id) for s in year_sessions} & completed_book_ids),
        "year_pages": sum(s.pages_read or 0 for s in year_sessions) + sum(o.pages_read or 0 for o in year_orphans),
        "best_day_seconds": max(by_day.values()) if by_day else 0,
        "longest_session_seconds": max([s.duration for s in sessions] + [o.duration for o in orphans], default=0),
        "longest_book_title": (book_meta.get(longest_book_id) or {}).get("title") if longest_book_id else None,
        "longest_book_pages": longest_book_pages,
        "best_year": best_year,
        "best_year_books": best_year_books,
        "longest_book_by_time_title": longest_book_by_time_title,
        "longest_book_by_time_seconds": longest_book_by_time_seconds,
        "top_author_by_time_name": top_author_name,
        "top_author_by_time_seconds": duration_by_author.get(top_author_name, 0),
        "longest_streak_days": longest_streak_days,
        "longest_streak_start": longest_streak_start.isoformat() if longest_streak_start else None,
        "longest_streak_end": longest_streak_end.isoformat() if longest_streak_end else None,
    }


def compute_raw(db: Session, library: str, user_id: int) -> list:
    """
    The cardinal aggregate: one row per reading session, denormalized with
    book title/author/format and device name — same shape as grafidinamici's
    own load_dataframe() JOIN. Feeds the standard weekly/monthly/heatmap
    charts (aggregated client-side) AND the generic chart builder (Statistiche
    → Grafici personalizzati, which pivots over these same rows client-side)
    — designed once, used by both. Extending this one function is therefore
    also how orphan sessions reach the chart builder for free, with no
    chart-builder-specific code at all — it already just pivots over
    whatever rows this returns.
    Always the FULL, unfiltered list (this is what gets cached); a caller
    wanting a date range filters this same list in Python, cheap enough not
    to need its own cache entry.

    `book_id` is `None` on an orphan row (see the loop below) — there is no
    resolved calibre_book_id to give it. Every other field is filled from
    the orphan's own self-reported title/authors (device-reported, no
    library lookup needed); `format` has no equivalent on an orphan at all,
    so it's always "Sconosciuto" for these rows. See compute_summary's own
    docstring for why orphans are folded in unscoped by library rather than
    hidden until paired.
    """
    ambiti = _ambiti(db, library)
    sessions = _senza_rumore(db, db.query(models.ReadingSession).filter(
        models.ReadingSession.user_id == user_id,
        models.ReadingSession.library.in_(ambiti)
    ).order_by(models.ReadingSession.start_time.asc()).all())

    book_meta = _mappa_libri(db, library)
    # I caratteri per libro sono anch'essi per biblioteca: stessa chiave a
    # coppia, stesso motivo.
    caratteri_per_libro = {}
    for folder in ambiti:
        for book_id, n in _chars_map(db, folder).items():
            caratteri_per_libro[(folder, book_id)] = n
    device_names = {d.id: d.name for d in db.query(models.Device.id, models.Device.name).all()}

    rows = []
    for s in sessions:
        meta = book_meta.get((s.library, s.calibre_book_id)) or {}
        rows.append({
            "date": s.start_time.date().isoformat(),
            "start_time": s.start_time.isoformat(),
            "book_id": s.calibre_book_id,
            "book_title": meta.get("title") or "Sconosciuto",
            "author": meta.get("author") or "Autore Sconosciuto",
            "format": meta.get("format") or "Sconosciuto",
            "device_name": device_names.get(s.device_id) or ("Web Reader" if s.source == "web" else "Sconosciuto"),
            "source": s.source,
            "duration_seconds": s.duration,
            "pages_read": s.pages_read or 0,
            # Caratteri letti in questa sessione: frazione di libro per
            # quanto e' grande il libro. Zero quando manca uno dei due —
            # sessioni vecchie senza frazione, lettore web, o un libro di
            # cui non e' mai stato contato il testo (PDF, o "Ricalcola le
            # pagine stimate" mai lanciato).
            "chars_read": _chars_read(s.fraction_read, caratteri_per_libro.get((s.library, s.calibre_book_id))),
            # I metadati del libro viaggiano con la sessione: sono quello che
            # permette di incrociare "quanto ho letto" con "cosa possiedo".
            # None dove il metadato non c'e' (la meta' dei libri non ha tag),
            # perche' un "Sconosciuto" inventato qui diventerebbe una fetta
            # vera nei grafici — vedi _book_meta_map.
            "series": meta.get("series"),
            "tags": meta.get("tags") or [],
            "language": meta.get("language"),
            "publisher": meta.get("publisher"),
            "rating": meta.get("rating"),
            "decade": meta.get("decade"),
        })

    for o in _senza_rumore(db, db.query(models.OrphanReadingSession).filter(
            models.OrphanReadingSession.user_id == user_id).all()):
        rows.append({
            "date": o.start_time.date().isoformat(),
            "start_time": o.start_time.isoformat(),
            "book_id": None,
            "book_title": o.title or "Sconosciuto",
            "author": o.authors or "Autore Sconosciuto",
            "format": "Sconosciuto",
            "device_name": device_names.get(o.device_id) or "Sconosciuto",
            "source": "koreader",
            "duration_seconds": o.duration,
            "pages_read": o.pages_read or 0,
            # Una sessione orfana non e' ancora legata a nessun libro, quindi
            # non c'e' un conteggio caratteri da usare: resta la frazione,
            # che pero' da sola non fa caratteri.
            "chars_read": 0,
            # Stessi campi delle righe risolte, perche' il costruttore di
            # grafici pivota su una forma sola: gli orfani non hanno una
            # biblioteca in cui cercare i metadati, quindi restano vuoti —
            # tranne la serie, che il dispositivo dichiara da se'.
            "series": o.series,
            "tags": [],
            "language": None,
            "publisher": None,
            "rating": None,
            "decade": None,
        })

    rows.sort(key=lambda r: r["start_time"])
    return rows


def compute_timeline(db: Session, library: str, user_id: int, days: int = _TIMELINE_CACHE_DAYS) -> list:
    """date -> total seconds read, for the activity heatmap — mirrors
    KoServer's own /stats/timeline. Folds in OrphanReadingSession duration
    too (same "not scoped by library, honest overcount over silent
    undercount" reasoning as compute_summary's own docstring) so a day with
    only not-yet-paired reading doesn't show up empty on the heatmap."""
    since = datetime.utcnow() - timedelta(days=days)
    sessions = _senza_rumore(db, db.query(models.ReadingSession).filter(
        models.ReadingSession.user_id == user_id,
        models.ReadingSession.library.in_(_ambiti(db, library)),
        models.ReadingSession.start_time >= since,
    ).all())
    orphans = _senza_rumore(db, db.query(models.OrphanReadingSession).filter(
        models.OrphanReadingSession.user_id == user_id,
        models.OrphanReadingSession.start_time >= since,
    ).all())
    by_day = defaultdict(int)
    for s in sessions:
        by_day[s.start_time.date().isoformat()] += s.duration
    for o in orphans:
        by_day[o.start_time.date().isoformat()] += o.duration
    return [{"date": d, "total_seconds": secs} for d, secs in sorted(by_day.items())]


def refresh_stats_cache(db: Session) -> int:
    """
    Recomputes and upserts StatsCache for every registered library — the
    background counterpart GET /api/kolibre/stats/* reads instead of
    calling compute_summary/compute_raw/compute_timeline live on every
    request. Called by the periodic loop (main.py::_refresh_stats_loop),
    right after reprocess_all_device_backups so a freshly-caught-up backup
    is reflected in the SAME cycle, not one cycle later.
    """
    libraries = db.query(models.Library).all()
    # Una cache per (utente, biblioteca). Si calcola solo per gli utenti che
    # hanno davvero letto qualcosa: per gli altri non c'e' niente da
    # aggregare, e l'endpoint ricade comunque sul calcolo dal vivo — che su
    # zero sessioni costa zero. Senza questo filtro, ogni utente nuovo
    # aggiungerebbe N righe vuote per ogni giro del ciclo.
    utenti = sorted({
        u for (u,) in db.query(models.ReadingSession.user_id).distinct()
        if u is not None
    } | {
        u for (u,) in db.query(models.OrphanReadingSession.user_id).distinct()
        if u is not None
    })
    # Anche l'ambito "tutte le biblioteche" ha la sua riga di cache: e' una
    # risposta diversa dalla somma delle altre (gli orfani vi si contano una
    # volta invece che dentro ognuna) e leggerla dal vivo ad ogni apertura
    # della pagina costerebbe quanto ricalcolare tutto.
    ambiti = [r.folder_name for r in libraries]
    if len(ambiti) > 1:
        ambiti.append(AMBITO_TUTTE)

    for user_id in utenti:
        for folder in ambiti:
            summary = compute_summary(db, folder, user_id)
            raw = compute_raw(db, folder, user_id)
            timeline = compute_timeline(db, folder, user_id)
            cache = db.query(models.StatsCache).filter(
                models.StatsCache.user_id == user_id,
                models.StatsCache.library == folder,
            ).first()
            if not cache:
                cache = models.StatsCache(user_id=user_id, library=folder,
                                          summary_json="{}", raw_json="[]", timeline_json="[]")
                db.add(cache)
            cache.summary_json = json.dumps(summary)
            cache.raw_json = json.dumps(raw)
            cache.timeline_json = json.dumps(timeline)
            cache.computed_at = datetime.utcnow()
    db.commit()
    return len(ambiti) * len(utenti)


def registra_conteggio_testo(db, library: str, calibre_book_id: int, file_path: str, fmt: str) -> None:
    """
    Registra caratteri e parole di un libro, se il formato lo permette.

    Va chiamata dove si contano gia' le pagine stimate: il testo viene
    estratto comunque per quello, e prima veniva buttato via. E' il
    conteggio che trasforma una frazione di libro letta in caratteri letti
    — l'unica misura di lettura confrontabile fra libri, dispositivi e
    impostazioni di carattere diverse.

    Silenziosa se il file non si legge o e' un formato senza testo
    estraibile (PDF): meglio nessun dato che un dato inventato, e chi legge
    il conteggio sa gia' gestirne l'assenza ricadendo sulla percentuale.

    Il commit lo fa il chiamante, come per il resto di questo modulo.
    """
    from . import page_counter

    try:
        stats = page_counter.text_stats(file_path, fmt)
    except Exception:
        return
    if not stats:
        return
    riga = db.query(models.BookTextStats).filter(
        models.BookTextStats.library == library,
        models.BookTextStats.calibre_book_id == calibre_book_id,
    ).first()
    if riga:
        riga.chars = stats["chars"]
        riga.words = stats["words"]
        riga.computed_at = datetime.utcnow()
    else:
        db.add(models.BookTextStats(
            library=library, calibre_book_id=calibre_book_id,
            chars=stats["chars"], words=stats["words"],
        ))


def _chars_map(db, library: str) -> dict:
    """Quanti caratteri ha ogni libro di questa biblioteca, in una sola
    interrogazione: serve a tradurre una frazione di libro letta in
    caratteri letti, e va fatto per l'intero elenco di sessioni, non uno
    alla volta."""
    return {
        r.calibre_book_id: r.chars
        for r in db.query(models.BookTextStats).filter(models.BookTextStats.library == library).all()
    }


def _chars_read(fraction, chars) -> int:
    """Caratteri letti da una frazione di libro. Zero se manca un fattore:
    meglio non dire niente che inventare un numero."""
    if not fraction or not chars:
        return 0
    return round(fraction * chars)


# ── Copertura: quanta parte del libro e' stata vista ──────────────────────
#
# Vedi models.BookReadingCoverage per il perche' serva una misura diversa dal
# volume letto. Qui c'e' il come: una mappa di millesimi del libro, unita fra
# letture fatte con impaginazioni diverse.

_BINS = 1024  # multiplo di 8: un bit per millesimo, 128 byte tondi


def _segna_pagina(mappa: bytearray, pagina: int, totale: int) -> None:
    """Segna nella mappa i millesimi coperti da una pagina.

    Una pagina non e' un punto ma un INTERVALLO del libro: con un carattere
    grande puo' valere piu' di un millesimo, con uno piccolo meno di uno.
    Segnare solo il millesimo del suo inizio lascerebbe buchi nella
    copertura di un libro letto per intero con un font grande.
    """
    if not totale or totale <= 0 or pagina < 1:
        return
    inizio = int((pagina - 1) / totale * _BINS)
    fine = max(inizio + 1, int(pagina / totale * _BINS))
    for k in range(max(0, inizio), min(_BINS, fine)):
        mappa[k // 8] |= 1 << (k % 8)


def _conta_bit(mappa: bytes) -> int:
    return sum(bin(b).count("1") for b in mappa)


def aggiorna_copertura(db, user_id: int, library: str, calibre_book_id: int, mappa: bytearray) -> float:
    """Unisce una mappa di lettura a quella gia' registrata per il libro.

    Unione e mai sostituzione: un backup parziale, o una rilettura di soli
    tre capitoli, non deve cancellare quello che si sapeva gia'. Torna la
    copertura risultante, da 0 a 1.

    L'unione e' PER UTENTE. Unire le mappe di due persone che leggono lo
    stesso libro condiviso darebbe a entrambe una copertura che nessuna delle
    due ha: la copertura dice "quanto di questo libro ho visto io", e
    sommare occhi diversi la rende una misura di nessuno.
    """
    riga = db.query(models.BookReadingCoverage).filter(
        models.BookReadingCoverage.user_id == user_id,
        models.BookReadingCoverage.library == library,
        models.BookReadingCoverage.calibre_book_id == calibre_book_id,
    ).first()
    unita = bytearray(mappa)
    if riga and riga.bins:
        vecchia = riga.bins
        for i in range(min(len(unita), len(vecchia))):
            unita[i] |= vecchia[i]
    copertura = _conta_bit(unita) / _BINS
    if riga:
        riga.bins = bytes(unita)
        riga.coverage = copertura
        riga.updated_at = datetime.utcnow()
    else:
        db.add(models.BookReadingCoverage(
            user_id=user_id, library=library, calibre_book_id=calibre_book_id,
            bins=bytes(unita), coverage=copertura,
        ))
        # Subito visibile alle chiamate successive nella stessa transazione:
        # senza, una seconda chiamata sullo stesso libro non troverebbe la
        # riga appena aggiunta e ne creerebbe un'altra, che il vincolo di
        # unicita' rifiuta.
        db.flush()
    return copertura


# Quanto puo' essersi spostata una lettura vera fra due spinte di posizione.
#
# Il reader web spinge ogni paio di secondi: in due secondi si gira una
# pagina, che su un libro da trecento pagine e' tre millesimi. Il 2% e' largo
# dieci volte, ed e' voluto — la spinta puo' arrivare in ritardo, o dopo un
# minuto di lettura senza rete. Oltre quella soglia non e' lettura ma un
# salto: aprire il sommario, tornare a una nota, saltare a meta' libro. Un
# salto segna il punto dove sei atterrato e nient'altro, perche' il libro in
# mezzo non l'hai visto — e una copertura che si riempie saltando non misura
# piu' niente.
SALTO_MASSIMO_COPERTURA = 0.02


def segna_lettura_web(db, user_id: int, library: str, calibre_book_id: int,
                      prima, ora) -> float:
    """
    Segna nella copertura il tratto percorso dal lettore web.

    La copertura si riempiva solo dai backup di KOReader: leggere dentro
    Kolibre non la muoveva di un millesimo, e un libro letto per intero sul
    computer risultava non visto. Il dato per chiuderla c'era gia' —
    `ReadingPosition.percentage` — mancava solo di segnarlo.

    Passa dalla stessa unione di `aggiorna_copertura`, quindi le letture da
    web e da dispositivo si sommano invece di sovrascriversi, ed e' per
    utente come tutto il resto della copertura.
    """
    if ora is None:
        return 0.0
    fine = max(0.0, min(1.0, float(ora) / 100.0))
    inizio = fine
    if prima is not None:
        avanti = fine - max(0.0, min(1.0, float(prima) / 100.0))
        if 0 < avanti <= SALTO_MASSIMO_COPERTURA:
            inizio = fine - avanti

    mappa = bytearray(_BINS // 8)
    primo = int(inizio * _BINS)
    ultimo = max(primo + 1, int(fine * _BINS))
    for k in range(max(0, primo), min(_BINS, ultimo)):
        mappa[k // 8] |= 1 << (k % 8)
    return aggiorna_copertura(db, user_id, library, calibre_book_id, mappa)


# ── Panoramica del catalogo ──────────────────────────────────────────────
#
# Le quattordici statistiche della scheda "Statistiche Libreria" si
# calcolavano nel browser, che per farlo scaricava il catalogo INTERO: su
# una biblioteca da 5.843 libri sono quasi sei megabyte di titoli,
# descrizioni e identificatori, per ricavarne un paio di chilobyte di
# conteggi. Era lo stesso schema che avevamo gia' tolto da Libreria e da
# Autori, rimasto qui.
#
# Il calcolo e' UNO SOLO: queste funzioni sostituiscono quelle in
# statsCompute.ts, che sono state cancellate. Le forme tornate sono le
# stesse che si aspettava l'interfaccia, cosi' la pagina non e' stata
# riscritta ma solo ricollegata.

def _byte_leggibili(n: int) -> str:
    """Stessa resa di formatBytes nel browser, per non cambiare i numeri
    sotto gli occhi di chi li stava guardando."""
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _in_percento_sul_massimo(conteggi: dict, limite: int = None, etichetta: str = "label") -> list:
    """Le barre sono in proporzione alla PIU' ALTA, non al totale: e' quello
    che le rende leggibili quando una categoria domina le altre."""
    massimo = max(conteggi.values()) if conteggi else 1
    massimo = max(1, massimo)
    voci = sorted(conteggi.items(), key=lambda kv: (-kv[1], kv[0].casefold()))
    if limite:
        voci = voci[:limite]
    return [
        {etichetta: nome, "count": n, "percent": round(n * 100 / massimo)}
        for nome, n in voci
    ]


def panoramica_biblioteca(library: str) -> dict:
    """Tutto quello che serve alla scheda "Statistiche Libreria", contato qui
    invece che nel browser."""
    try:
        libri = CalibreLibrary(config.library_path(library)).list_books()
    except Exception:
        return {"total_books": 0}

    formati, spazio_formato = defaultdict(int), defaultdict(int)
    autori_volumi, autori_pagine, autori_spazio = defaultdict(int), defaultdict(int), defaultdict(int)
    serie, lingue, tag = defaultdict(int), defaultdict(int), defaultdict(int)
    valutazioni = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0, "Non valutato": 0}
    lunghezze = {"Corto (< 150 pag)": 0, "Medio (150-400 pag)": 0, "Lungo (> 400 pag)": 0}
    autori_distinti = set()
    completezza = 0

    for b in libri:
        nomi = string_to_authors(b.get("author") or "") or ["Autore Sconosciuto"]
        autori_distinti.add(b.get("author") or "")
        dimensione = b.get("size") or 0
        pagine = b.get(f"#{PAGE_COUNT_COLUMN_LABEL}") or 0

        for fmt in b.get("formats") or []:
            formati[fmt] += 1
            spazio_formato[fmt] += dimensione
        for nome in nomi:
            autori_volumi[nome] += 1
            autori_spazio[nome] += dimensione
            if pagine:
                autori_pagine[nome] += pagine
        if b.get("series"):
            serie[b["series"]] += 1
        lingue[b.get("language") or "Sconosciuta"] += 1
        for t in b.get("tags") or []:
            tag[t] += 1

        voto = round(b.get("rating") or 0)
        if 1 <= voto <= 5:
            valutazioni[str(voto)] += 1
        else:
            valutazioni["Non valutato"] += 1

        if pagine:
            if pagine < 150:
                lunghezze["Corto (< 150 pag)"] += 1
            elif pagine <= 400:
                lunghezze["Medio (150-400 pag)"] += 1
            else:
                lunghezze["Lungo (> 400 pag)"] += 1

        # Quattro campi, un quarto ciascuno. Nel browser il quarto
        # controllava `b.isbn`, un campo che l'elenco libri non ha mai
        # esposto: l'ISBN vive dentro `identifiers`. La clausola non poteva
        # quindi mai segnare, e la percentuale era tappata al 75% anche su
        # un libro con i metadati completi. Era stata lasciata cosi' per
        # mostrare lo stesso numero della vecchia interfaccia Vue, che non
        # c'e' piu': qui guarda l'ISBN vero.
        campi = 0
        if (b.get("description") or "").strip():
            campi += 1
        if b.get("tags"):
            campi += 1
        if b.get("series"):
            campi += 1
        if (b.get("identifiers") or {}).get("isbn"):
            campi += 1
        completezza += campi / 4 * 100

    totale_formati = sum(formati.values()) or 1
    totale_byte = sum(spazio_formato.values()) or 1
    massimo_spazio_autore = max(autori_spazio.values(), default=1) or 1

    return {
        "total_books": len(libri),
        "unique_authors": len(autori_distinti),
        "unique_series": len(serie),
        "metadata_percent": round(completezza / len(libri)) if libri else 0,
        # La distribuzione dei formati e' l'unica in percentuale sul TOTALE
        # e non sul massimo: e' una torta, e le fette devono fare cento.
        "formats": [
            {"format": f, "count": n, "percent": round(n * 100 / totale_formati)}
            for f, n in sorted(formati.items(), key=lambda kv: -kv[1])
        ],
        "format_storage": [
            {"format": f, "bytesLabel": _byte_leggibili(b), "percent": round(b * 100 / totale_byte)}
            for f, b in sorted(spazio_formato.items(), key=lambda kv: -kv[1])
        ],
        "top_authors": _in_percento_sul_massimo(autori_volumi, 10, "name"),
        "top_series": _in_percento_sul_massimo(serie, 10, "name"),
        "page_buckets": [
            {"label": k, "count": v, "percent": round(v * 100 / max(1, max(lunghezze.values())))}
            for k, v in lunghezze.items()
        ],
        "author_pages": [
            {"name": v["name"], "pages": v["count"], "percent": v["percent"]}
            for v in _in_percento_sul_massimo(autori_pagine, 10, "name")
        ],
        "author_storage": [
            {"name": nome, "bytesLabel": _byte_leggibili(b), "percent": round(b * 100 / massimo_spazio_autore)}
            for nome, b in sorted(autori_spazio.items(), key=lambda kv: -kv[1])[:10]
        ],
        "ratings": [
            {"label": k, "count": v, "percent": round(v * 100 / max(1, max(valutazioni.values())))}
            for k, v in valutazioni.items()
        ],
        "languages": _in_percento_sul_massimo(lingue),
        "tags": _in_percento_sul_massimo(tag, 10),
    }


# ── Le annotazioni come misura di intensita' ─────────────────────────────

def intensita_annotazioni(db: Session, library: str, utente, limite: int = 10) -> dict:
    """
    Quanto un libro ti ha fatto fermare: annotazioni ogni centomila
    caratteri letti.

    Il tempo misura quanto un libro ti ha trattenuto, non quanto ti ha
    coinvolto. Un libro letto in otto ore senza una sottolineatura e uno
    letto in otto ore con novanta sono due esperienze diverse, e il
    cruscotto le raccontava identiche — in una biblioteca reale 1.023
    evidenziazioni su 69 libri non comparivano nelle statistiche in nessuna
    forma.

    Normalizzata per lunghezza, altrimenti sarebbe solo la classifica dei
    libri lunghi: un saggio breve fittissimo di note deve poter battere un
    romanzo di mille pagine con tre sottolineature.

    I libri senza denominatore vengono ESCLUSI, non stimati. In un caso
    reale sono gli anni 2023-24, che hanno annotazioni ma nessuna sessione
    di lettura registrata: il conteggio caratteri non c'e' e inventarlo
    darebbe una classifica guidata dall'invenzione.
    """
    ambiti = _ambiti(db, library)

    caratteri_letti = defaultdict(int)
    for folder in ambiti:
        mappa = _chars_map(db, folder)
        for s in db.query(models.ReadingSession).filter(
            # Le proprie letture: la classifica e' «quanto un libro ha fatto
            # fermare TE», e sommare le ore di due persone divise per le note
            # di due persone dava un numero di nessuno.
            models.ReadingSession.user_id == utente.id,
            models.ReadingSession.library == folder,
        ).all():
            c = _chars_read(s.fraction_read, mappa.get(s.calibre_book_id))
            if c:
                caratteri_letti[(folder, s.calibre_book_id)] += c

    note = defaultdict(int)
    for h in db.query(
        models.Highlight.library, models.Highlight.calibre_book_id
    ).filter(
        models.Highlight.user_id == utente.id,
        models.Highlight.library.in_(ambiti),
        # Le note cancellate non contano: ogni altra query del progetto
        # filtra deleted_at, questa no — e un libro continuava a classificarsi
        # per cinquanta note che non esistevano piu'.
        models.Highlight.deleted_at.is_(None),
    ).all():
        note[(h[0], h[1])] += 1

    meta = _mappa_libri(db, library)
    righe = []
    senza_denominatore = 0
    for chiave, quante in note.items():
        caratteri = caratteri_letti.get(chiave, 0)
        if caratteri <= 0:
            senza_denominatore += 1
            continue
        righe.append({
            "title": (meta.get(chiave) or {}).get("title") or "Sconosciuto",
            "author": (meta.get(chiave) or {}).get("author") or "Autore Sconosciuto",
            "highlights": quante,
            "chars_read": caratteri,
            "per_100k": round(quante * 100_000 / caratteri, 1),
        })

    righe.sort(key=lambda r: -r["per_100k"])
    return {
        "books": righe[:limite],
        "books_total": len(righe),
        "books_without_denominator": senza_denominatore,
        "highlights_total": sum(note.values()),
    }


# ── Statistiche in salita, solo le righe nuove ───────────────────────────
#
# Fino al 28/09/2026 ogni sincronizzazione caricava `statistics.sqlite3`
# intero: 659 KB misurati su un Kindle reale, 10.822 righe che vanno dal
# febbraio 2025, per riportare quello che era successo dall'ultima volta —
# **una riga**, in una giornata normale.
#
# Ora il dispositivo chiede fin dove il server e' arrivato e manda solo le
# righe successive. Misurato sullo stesso file: un giorno 29 byte, una
# settimana di lettura vera 397. Fra le 118 e le ventimila volte piu'
# leggero a seconda di quanto si e' letto.
#
# **Il file resta il deposito.** Le righe non finiscono da qualche altra
# parte: vengono cucite dentro lo stesso `statistics.sqlite3` conservato per
# quel dispositivo, e da li' in poi non cambia niente — l'elaborazione, il
# riprocesso quando una biblioteca viene riscansionata, i backup scaricabili
# leggono tutti quel file come prima. Sostituire il trasporto non doveva
# significare cambiare il modello.
#
# **L'idempotenza e' di KOReader, non nostra**: `page_stat_data` ha
# `UNIQUE (id_book, page, start_time)`, quindi un `INSERT OR IGNORE` rende
# innocuo rimandare due volte le stesse righe — ed e' il motivo per cui la
# finestra di sovrapposizione qui sotto costa zero.

# Quanto si torna indietro rispetto all'ultima riga conosciuta.
#
# Non e' prudenza generica: KOReader scrive una riga quando la pagina viene
# LASCIATA, e un dispositivo puo' restare spento in mezzo. Chiedere
# "start_time > l'ultimo che ho" rischierebbe di saltare una riga scritta in
# ritardo ma datata prima. Un giorno di sovrapposizione costa qualche decina
# di righe che l'INSERT OR IGNORE butta via da sola.
FINESTRA_SOVRAPPOSIZIONE = 86400


def stato_statistiche(db_path: str) -> dict:
    """Da dove il dispositivo deve ripartire, e con cosa confrontarsi."""
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        return {"disponibile": False, "da": 0, "righe": 0, "somma_durate": 0}
    try:
        conn = sqlite3.connect(db_path)
        try:
            righe, somma, massimo = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(duration), 0), COALESCE(MAX(start_time), 0) "
                "FROM page_stat_data"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        # Un deposito illeggibile non e' un errore da propagare: e' un
        # dispositivo che deve rimandare tutto, ed e' esattamente quello che
        # "non disponibile" gli dice di fare.
        return {"disponibile": False, "da": 0, "righe": 0, "somma_durate": 0}
    return {
        "disponibile": righe > 0,
        "da": max(0, massimo - FINESTRA_SOVRAPPOSIZIONE),
        "righe": righe,
        "somma_durate": somma,
    }


_COLONNE_LIBRO = ("id", "title", "authors", "notes", "last_open", "highlights",
                  "pages", "series", "language", "md5", "total_read_time",
                  "total_read_pages")


def cuci_statistiche(db_path: str, libri: list, righe: list, totali: dict) -> dict:
    """
    Cuce le righe nuove dentro il deposito e dice se il conto torna.

    Il controllo d'integrita' non e' un di piu': il dispositivo dichiara
    quante righe e quanta durata ha in TUTTA la sua tabella, e dopo la
    cucitura i due numeri devono coincidere. Se non coincidono il deposito ha
    un buco — un dispositivo ripristinato da un backup, un file rifatto da
    zero, una sincronizzazione andata persa mesi fa — e l'unica risposta
    onesta e' chiedere il file intero. Meglio una salita da 659 KB ogni tanto
    che una statistica che diverge in silenzio.
    """
    esito = {"righe_aggiunte": 0, "risincronizza": False, "motivo": None}
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        esito.update(risincronizza=True, motivo="nessun_deposito")
        return esito

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        colonne_presenti = {r[1] for r in cur.execute("PRAGMA table_info(book)")}
        colonne = [c for c in _COLONNE_LIBRO if c in colonne_presenti]
        segnaposto = ", ".join("?" * len(colonne))
        for libro in libri:
            if not isinstance(libro, dict) or libro.get("id") is None:
                continue
            cur.execute(
                f"INSERT OR IGNORE INTO book ({', '.join(colonne)}) VALUES ({segnaposto})",
                [libro.get(c) for c in colonne],
            )

        prima = cur.execute("SELECT COUNT(*) FROM page_stat_data").fetchone()[0]
        da_inserire = [
            tuple(r[:5]) for r in righe
            if isinstance(r, (list, tuple)) and len(r) >= 5
            and all(isinstance(v, int) for v in r[:5])
        ]
        cur.executemany(
            "INSERT OR IGNORE INTO page_stat_data "
            "(id_book, page, start_time, duration, total_pages) VALUES (?, ?, ?, ?, ?)",
            da_inserire,
        )
        dopo, somma = cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(duration), 0) FROM page_stat_data"
        ).fetchone()
        conn.commit()
        esito["righe_aggiunte"] = dopo - prima
    except sqlite3.Error as exc:
        conn.rollback()
        esito.update(risincronizza=True, motivo=f"deposito_illeggibile: {exc}")
        return esito
    finally:
        conn.close()

    righe_dichiarate = totali.get("righe")
    somma_dichiarata = totali.get("somma_durate")
    if isinstance(righe_dichiarate, int) and dopo != righe_dichiarate:
        esito.update(risincronizza=True, motivo=f"righe {dopo} contro {righe_dichiarate}")
    elif isinstance(somma_dichiarata, int) and somma != somma_dichiarata:
        esito.update(risincronizza=True, motivo=f"durate {somma} contro {somma_dichiarata}")
    return esito
