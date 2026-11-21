import asyncio
import logging
import os
from contextlib import asynccontextmanager

import sqlalchemy as sa
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from . import schemas_risposte, config, models, database, auth, migrations
from .logging_utils import log_message
from .calibre.connection import LibraryDeletedError, LibraryMissingError
from .calibre.library import purge_expired_book_lists
from .calibre.write_queue import CalibreWriteQueue, WriteJob, retry_one_pending, serialize_pending
from .services.watcher import start_watcher, stop_watcher
from .services import (author_stats_service, highlight_position, identita_durevole,
                       ingest_folders, qualita_job, stardict_service, stats_service,
                       widowed_highlights)
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
from .api import link as link_router
from .api import appunti as appunti_router
from .api import tools as tools_router
from .api import settings as settings_router
from .api import fulltext as fulltext_router
from .api import qualita as qualita_router
from .api import library_transfer as library_transfer_router
from .api import stats as stats_router
from .api import opds as opds_router
from .api import dictionaries as dictionaries_router
from .api import vocabulary as vocabulary_router
from .api import accoppiamento as accoppiamento_router

# pypdf logga un avviso per OGNI font CFF Type1 che incontra senza fontTools
# installato ("fontTools is required to fully parse the encoding…"). È
# innocuo — il testo viene estratto lo stesso — ma si ripete per ogni pagina
# di ogni PDF: una riindicizzazione full-text di una libreria vera ne ha
# prodotte migliaia, seppellendo i log del backend e facendolo sembrare
# impazzito (riscontrato in uso). Gli errori veri di pypdf restano visibili.
logging.getLogger("pypdf").setLevel(logging.ERROR)


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
                f"Widowed notes: {marcate} marked 'book missing', {liberate} put back in the conversion queue",
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
# devices/backups_stats.py::upload_device_backup now also triggers an immediate
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
            log_message("warning", "stats", f"Periodic statistics refresh failed: {exc}")
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
            log_message("warning", "annotations", f"Periodic CFI position backfill failed: {exc}")
        finally:
            db.close()
        await asyncio.sleep(HIGHLIGHT_POSITION_BACKFILL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_directories()
    models.Base.metadata.create_all(bind=database.engine)
    # Le migrazioni dello schema vivono nel registro numerato di
    # app/migrations.py (revisione critica del 19/11/2026, punto A4). Due
    # cambi rispetto ai tre try che stavano qui:
    #   - a regime, con la versione gia' al corrente, l'avvio legge UN
    #     numero invece di rifare ~40 PRAGMA table_info e una ventina di
    #     CREATE INDEX IF NOT EXISTS che non hanno niente da fare;
    #   - niente try: una migrazione che fallisce ferma l'avvio, invece di
    #     lasciar partire il server su uno schema a meta' che risponde 500
    #     su rotte a caso. Il registro logga quale voce e' caduta e riparte
    #     da li' al prossimo avvio — il perche' per esteso sta nel docstring
    #     del modulo.
    migrations.apply_pending()
    # Le RIPARAZIONI qui sotto invece non sono migrazioni: sono idempotenti,
    # girano a ogni avvio, e ognuna sta nel suo try — la regola imparata due
    # volte: la prima che fallisce non deve far saltare le altre, e il
    # server puo' partire senza di loro perche' non toccano lo schema.
    try:
        _marca_note_vedove()
    except Exception as exc:
        log_message("error", "system", f"Marking widowed notes failed (the server starts anyway): {exc}")
    # Da' un nome durevole alle note che non ce l'hanno. Gira per intero una
    # volta sola — su un database che esisteva prima della colonna — e dopo
    # non trova mai niente da fare. Un `try` suo per la stessa ragione delle
    # altre: se fallisce, il server parte e le note restano senza nome, cosa
    # che si vede subito perche' i link non si generano.
    try:
        db_nomi = database.SessionLocal()
        try:
            quante = identita_durevole.assegna_mancanti(db_nomi)
            if quante:
                log_message("info", "system", f"Durable identity assigned to {quante} notes.")
        finally:
            db_nomi.close()
    except Exception as exc:
        log_message("error", "system", f"Assigning durable ids failed (the server starts anyway): {exc}")
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
                log_message("info", "auth", f"Founder of this installation: '{fondatore.username}'.")
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
                    f"{len(senza_proprietario)} libraries assigned to '{fondatore.username}'.",
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
                    log_message("info", "auth", f"{aggiunti} library permissions kept from the previous setup.")
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
                f"No administrator found: promoted the first user '{primo.username}'.",
            )
    finally:
        db.close()

    # Le sottocartelle di ingest per utente (21/11/2026): una per ogni
    # utente esistente, create qui cosi' il primo avvio dopo il deploy le fa
    # nascere da solo — nessun passo a mano. Idempotente (una cartella che
    # c'e' gia', anche con uno username vecchio nel nome, si riusa); una
    # RIPARAZIONE e non una migrazione, quindi nel suo try: senza cartelle
    # il server funziona lo stesso, i file si vedono e basta metterli nella
    # radice come ieri.
    try:
        db_cartelle = database.SessionLocal()
        try:
            ingest_folders.ensure_all_user_folders(db_cartelle)
        finally:
            db_cartelle.close()
    except Exception as exc:
        log_message("error", "ingest", f"Creating the per-user ingest folders failed (the server starts anyway): {exc}")

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
        log_message("warning", "authors", f"Initial fill of the author-pages cache failed: {e}")
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

    # La qualita' degli EPUB: ogni biblioteca accesa va in coda da sola.
    # Non e' un lavoro che si chiede, e' uno che si trova fatto — e la coda
    # sa gia' saltare tutto quello che non e' cambiato, quindi al secondo
    # avvio non costa niente. Un `try` suo come le altre migrazioni: se
    # questo non parte, il server parte lo stesso e i punteggi restano
    # quelli di ieri.
    try:
        quante = qualita_job.accoda_tutte()
        if quante:
            log_message("info", "qualita", f"EPUB quality: {quante} libraries queued.")
    except Exception as exc:
        log_message("error", "qualita", f"The quality queue did not start (the server starts anyway): {exc}")

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

# ── Che cosa sei, e con chi puoi parlare ──
#
# **Il numero di versione dell'API, e perche' non e' la versione del
# server.** Sono due cose diverse e vanno tenute separate: `version` dice
# QUALE DEPLOY sta girando (cambia a ogni rilascio, anche per una correzione
# che non tocca nessuna rotta), `api` dice QUALE CONTRATTO parla — cambia
# solo quando una rotta cambia in modo che un client scritto prima non
# funzioni piu'. Un client deve guardare `api`: legarsi a `version` vorrebbe
# dire rifiutare un server perfettamente compatibile perche' ha un numero
# diverso.
#
# **Si alza quando si rompe qualcosa, non quando si aggiunge.** Aggiungere
# una rotta o un campo non rompe nessuno: un client che non lo conosce lo
# ignora. Togliere un campo, rinominarlo, cambiarne il tipo o il significato
# invece si': quello e' il momento di alzare questo numero, e di alzare anche
# CLIENT_MINIMO.
#
# **Da 1 a 2 il 17/11/2026, e il motivo NON e' quello che si vede nel commit
# in cui questo numero si muove.** E' la rotta dell'accoppiamento: il 16/11 un
# programma chiedeva di entrare con `POST /api/pairing/requests` e ritirava il
# token con `GET /api/pairing/requests/{ticket}`; il 17 quelle due rotte, piu'
# l'elenco e le due di conferma, sono state **togliere** (l'invito parte dal
# server, vedi `api/accoppiamento.py`). Togliere rotte e' esattamente il caso
# che questo numero esiste per annunciare: un client scritto contro l'1 non
# funziona piu', e l'unico modo che ha di saperlo prima di provare e' leggere
# qui.
#
# **Doveva muoversi in quel commit e non si e' mosso**: l'ho dimenticato, e me
# ne sono accorto cercando dove fosse la «VERSION» da alzare per il giro dei
# log. I log non c'entrano — non cambiano nessun contratto — ma il numero e'
# questo e andava a 2 comunque.
API = 2

# **La versione minima di client che questo server accetta di servire.** Non
# e' un controllo che il server fa — e' un'informazione che da', e che il
# client usa per dire a chi lo usa «il tuo server e' troppo vecchio per
# questa versione, aggiornalo» invece di rompersi in un modo che nessuno sa
# spiegare. Resta a 0.0.0 finche' un client esiste: un numero piu' alto
# oggi rifiuterebbe un client che non c'e'.
CLIENT_MINIMO = "0.0.0"


def _commit_in_esecuzione():
    """Il commit da cui gira questo server, o `None` se non si sa.

    **Tre strade, in ordine, e `None` come ultima risposta.** Prima
    KOLIBRE_COMMIT dall'ambiente, che e' come lo scrive il build. Poi, se
    c'e' un `.git` accanto al codice (cioe' in sviluppo), si legge il
    riferimento a mano — **senza chiamare `git`**, che in un container non
    c'e' e lanciare un processo per quattro byte e' lavoro sproporzionato.

    **`None` e non `"unknown"`.** Una stringa scritta a mano un client non
    la puo' distinguere da un commit vero: proverebbe a confrontarla, a
    mostrarla, a mandarla in un rapporto. `None` e' l'unica risposta che
    dice «non lo so» in un modo che non si confonde con un dato.
    """
    dall_ambiente = (os.environ.get("KOLIBRE_COMMIT") or "").strip()
    if dall_ambiente:
        return dall_ambiente
    try:
        radice = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        testa = os.path.join(radice, ".git", "HEAD")
        with open(testa, "r", encoding="utf-8") as f:
            contenuto = f.read().strip()
        if contenuto.startswith("ref: "):
            riferimento = contenuto[5:].strip()
            with open(os.path.join(radice, ".git", riferimento), "r", encoding="utf-8") as f:
                contenuto = f.read().strip()
        return contenuto[:40] or None
    except OSError:
        return None


@app.get(
    "/api/kolibre/version",
    responses={200: {"model": schemas_risposte.VersioneDelServer}},
)
def get_version():
    """
    Chi sei, che contratto parli, e da quale commit giri.

    **Nessuna autenticazione, apposta** — e dal 16/11/2026 e' una ragione in
    piu' che prima: oltre a poter controllare con un curl se il server e'
    allineato all'ultimo tag, questa e' la prima domanda che fa un client che
    NON HA ANCORA un account. Dietro l'autenticazione sarebbe inutile
    proprio nel momento in cui serve.

    **Perche' non e' una rotta nuova chiamata `/api/version`.** Perche'
    questa c'era gia', ed e' quella che il frontend web interroga
    (`components/ConnectionStatus.tsx`). Due indirizzi che rispondono «chi
    sei» sono il modo di farli divergere: uno viene aggiornato e l'altro no,
    e chi legge quello sbagliato crede a una versione che non gira.

    `version` arriva da KOLIBRE_VERSION, che si scrive in .env prima del
    build (la propria automazione di deploy lo ricava da `git describe`); se
    non c'e', risponde "dev". Vedi `API` e `CLIENT_MINIMO` per la differenza
    fra la versione del deploy e quella del contratto.
    """
    return {
        "version": os.environ.get("KOLIBRE_VERSION", "dev"),
        "commit": _commit_in_esecuzione(),
        "api": API,
        "client_minimo": CLIENT_MINIMO,
    }


@app.exception_handler(LibraryDeletedError)
async def _library_deleted_handler(request: Request, exc: LibraryDeletedError):
    # A request naming a library the user explicitly deleted (see
    # DELETED_LIBRARY_MARKER) should read as "not found", not as a server
    # crash — without this, any route that opens a CalibreLibrary directly
    # (not through one of the soft cross-library lookups that already
    # catch-and-skip) surfaced a bare 500 instead.
    return JSONResponse(status_code=404, content={"detail": "This library has been deleted."})


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
    log_message("warning", "libraries", f"Requested a library that does not exist: {exc}")
    return JSONResponse(status_code=404, content={"detail": "This library does not exist."})

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
app.include_router(link_router.router, dependencies=_AUTH)
app.include_router(appunti_router.router, dependencies=_AUTH)
app.include_router(tools_router.router, dependencies=_AUTH)
app.include_router(settings_router.router, dependencies=_AUTH)
app.include_router(fulltext_router.router, dependencies=_AUTH)
app.include_router(qualita_router.router, dependencies=_AUTH)
app.include_router(library_transfer_router.router, dependencies=_AUTH)
app.include_router(stats_router.router, dependencies=_AUTH)
app.include_router(interventions_router.router, dependencies=_AUTH)
app.include_router(dictionaries_router.router, dependencies=_AUTH)
app.include_router(vocabulary_router.router, dependencies=_AUTH)
app.include_router(accoppiamento_router.router, dependencies=_AUTH)  # chi crea gli inviti

# OPDS ha gia' la sua autenticazione, HTTP Basic (require_opds_auth): i
# lettori esterni che consumano il feed non sanno nulla del JWT di Kolibre.
app.include_router(opds_router.router)

# Endpoint che il browser o il plugin caricano senza poter allegare un
# header: copertine e foto in <img src>, font in @font-face, self-update
# del plugin KOReader. In sola lettura tutti tranne il riscatto di un invito
# qui sotto, che e' la sola parte SENZA autenticazione che scriva nel
# database — e scrive soltanto se il codice che le arriva e' uno di quelli
# nati dentro il server. Vedi il commento accanto a ciascun public_router nel
# rispettivo modulo.
app.include_router(users_router.public_router)
app.include_router(ingest_router.public_router)
app.include_router(books_router.device_or_user_router)                    # persona O dispositivo
app.include_router(books_router.public_router)
app.include_router(authors_router.public_router)
app.include_router(tools_router.public_router)
# Senza autenticazione per forza: un programma che scambia un codice di
# accoppiamento col suo token non ha ancora nessuna credenziale da
# presentare. **E' una rotta sola** (`POST /api/pairing/redeem`), e dal
# 17/11/2026 non ce n'e' piu' nessuna con cui un programma possa far
# comparire qualcosa nel server: l'invito lo crea chi e' dentro. I limiti che
# tengono stretta questa superficie stanno in testa a `api/accoppiamento.py`.
app.include_router(accoppiamento_router.public_router)
