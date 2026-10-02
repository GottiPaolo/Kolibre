import os
import shutil
import time
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import auth, config, models, database
from ..logging_utils import log_message
from ..calibre.connection import get_connection, page_count_fields, DELETED_LIBRARY_MARKER
from ..calibre.library import CalibreLibrary
from ..calibre.functions import string_to_authors
from ..calibre.write_queue import CalibreWriteQueue
from ..deps import get_write_queue
from ..services import stats_service, library_scanner, page_counter, app_settings, book_hash_service, opf_metadata, author_ingest_hook, author_stats_service, permessi

router = APIRouter(prefix="/api/kolibre/libraries", tags=["libraries"])

TRASH_DIR = os.path.join(config.DATA_DIR, "_trash_libraries")


def _next_sort_order(db: Session) -> int:
    """A newly-created/discovered library is appended at the end of the
    user's order, never inserted at the top (which would silently make it
    "the default" — see resolve_default_library_folder)."""
    current_max = db.query(func.max(models.Library.sort_order)).scalar()
    return (current_max or 0) + 1


def resolve_default_library_folder(db: Session, utente: models.User = None):
    """
    La biblioteca predefinita e' semplicemente la prima nell'ordine scelto
    dall'utente (Impostazioni → Librerie ▲▼): nessun flag dedicato, nessun
    nome di cartella privilegiato. In particolare **non esiste una biblioteca
    chiamata "default"** — il nome compare solo come valore di ripiego in due
    schemi Pydantic antichi, e non corrisponde a niente sul disco.

    Con un `utente`, la predefinita e' la prima **fra quelle che quella
    persona puo' vedere**. Senza questo, chi non ha accesso a nessuna
    biblioteca si vedeva assegnare d'ufficio la prima del server e riceveva
    un 403 su ogni singola cosa che apriva: un rifiuto al posto di una
    spiegazione. Riscontrato in uso il 28/09/2026.

    Torna None se non ce n'e' nessuna: chi chiama deve gestirlo, perche' il
    server deve continuare a funzionare con zero biblioteche.
    """
    if utente is not None:
        visibili = permessi.biblioteche_visibili(db, utente)
        return visibili[0].folder_name if visibili else None
    row = db.query(models.Library).order_by(models.Library.sort_order, models.Library.id).first()
    return row.folder_name if row else None


# Il messaggio che riceve chi non ha nessuna biblioteca da guardare.
#
# Distinto da "non ce n'e' nessuna sul server": sono due situazioni che si
# risolvono in modi opposti — una si risolve creandone una, l'altra
# chiedendo a qualcuno di condividerla. Dire "errore" per entrambe non
# aiuterebbe nessuno dei due.
NESSUNA_BIBLIOTECA_TUA = (
    "Non hai accesso a nessuna biblioteca. Chiedi a chi ne possiede una di condividerla con te, "
    "oppure creane una tu se il tuo account può farlo."
)
NESSUNA_BIBLIOTECA_ESISTE = "Non c'è ancora nessuna biblioteca. Creane una per cominciare."


def default_library_param(
    library: str = None,
    db: Session = Depends(database.get_db),
    utente: models.User = Depends(auth.utente_effettivo_opzionale),
) -> str:
    """
    Risolve il parametro `library` in un nome di cartella, ripiegando sulla
    biblioteca predefinita (la prima in ordine) quando non viene indicata.

    **Ed e' anche il cancello di lettura.** Ci passa ogni endpoint che
    lavora su una biblioteca, quindi controllare qui vuol dire controllare
    ovunque in una volta sola — invece di aggiungere lo stesso `if` a un
    centinaio di funzioni e dimenticarlo in tre.

    Chi chiede senza credenziali (le poche rotte pubbliche: copertine,
    caratteri) passa come prima: quelle rotte sono in sola lettura e
    pubbliche per scelta, e chiuderle qui sarebbe cambiarle di nascosto.
    Un dispositivo vale per il suo proprietario.

    Una biblioteca non ancora registrata nella tabella `libraries` non viene
    rifiutata: esiste quel momento, durante una creazione o una scansione, in
    cui la cartella c'e' e la riga non ancora, e rispondere 403 li' sarebbe
    un difetto travestito da rigore.
    """
    if not library:
        library = resolve_default_library_folder(db, utente)
        if not library:
            # 404 e non 403: non e' un permesso negato su una cosa precisa,
            # e' che non c'e' niente da aprire. Il messaggio distingue i due
            # casi perche' si risolvono in modi opposti — creare una
            # biblioteca, o farsene condividere una.
            esistono = db.query(models.Library).first() is not None
            raise HTTPException(
                status_code=404,
                detail=NESSUNA_BIBLIOTECA_TUA if (esistono and utente is not None) else NESSUNA_BIBLIOTECA_ESISTE,
            )
    if utente is not None:
        riga = db.query(models.Library).filter(models.Library.folder_name == library).first()
        if riga is not None and not permessi.puo_leggere(db, utente, riga):
            raise HTTPException(status_code=403, detail=f"Non hai accesso alla biblioteca '{riga.name}'.")
    return library


def biblioteca_scrivibile(
    library: str = Depends(default_library_param),
    db: Session = Depends(database.get_db),
    utente: models.User = Depends(auth.utente_effettivo_opzionale),
) -> str:
    """Come sopra, ma per chi scrive: serve il permesso di modifica.

    Si appoggia a `default_library_param`, quindi chi non puo' nemmeno
    leggere riceve il 403 di la' — e chi legge ma non modifica lo riceve
    qui, con il motivo giusto."""
    if utente is not None:
        riga = db.query(models.Library).filter(models.Library.folder_name == library).first()
        if riga is not None and not permessi.puo_modificare(db, utente, riga):
            raise HTTPException(status_code=403, detail=f"Non puoi modificare la biblioteca '{riga.name}'.")
    return library


def library_display_name(db: Session, folder_name: str) -> str:
    row = db.query(models.Library).filter(models.Library.folder_name == folder_name).first()
    return row.name if row else folder_name.capitalize().replace("_", " ")


def sync_library_registry(db: Session) -> None:
    """
    Ensure every folder with a metadata.db under LIBRARIES_DIR has a matching
    row in app.db's `libraries` table, and vice versa isn't required (a row
    whose folder disappeared is left alone rather than deleted, in case it was
    a transient unmount). Called at startup and defensively from list_libraries
    so libraries created by earlier/other means (or manually on disk) still get
    a stable id.

    This is the fix for the volatile library "id" bug: it used to be
    `hash(folder_name) % 100000`, which is reseeded randomly by Python on every
    process restart (PYTHONHASHSEED), so anything keyed by library id on the
    frontend (e.g. per-library visible-columns) silently lost its association
    on every backend restart.
    """
    if not os.path.exists(config.LIBRARIES_DIR):
        return
    known_folder_names = {row.folder_name for row in db.query(models.Library.folder_name).all()}
    known_names = {row.name for row in db.query(models.Library.name).all()}
    # A folder the user explicitly deleted must never come back on its own —
    # see DeletedLibraryFolder's docstring for why the folder can reappear on
    # disk even after a real deletion.
    deleted_folder_names = {row.folder_name for row in db.query(models.DeletedLibraryFolder.folder_name).all()}
    for folder_name in sorted(os.listdir(config.LIBRARIES_DIR)):
        if folder_name in known_folder_names or folder_name in deleted_folder_names:
            continue
        db_path = os.path.join(config.library_path(folder_name), "metadata.db")
        if not os.path.exists(db_path):
            continue
        display_name = folder_name.capitalize().replace("_", " ")
        if display_name in known_names:
            # Two distinct folder_names (e.g. differing only by case, or a
            # stray duplicate/backup folder) can capitalize to the SAME
            # display name — `Library.name` is UNIQUE, so inserting as-is
            # crashed the INSERT and, since this function runs on every
            # GET /api/kolibre/libraries (including the container's own
            # healthcheck), took the entire backend down instead of just
            # failing to register one odd folder. Disambiguate with a
            # numbered suffix so it still shows up (renameable from
            # Impostazioni → Librerie) rather than either vanishing or
            # crashing the app.
            suffix = 2
            candidate = f"{display_name} ({suffix})"
            while candidate in known_names:
                suffix += 1
                candidate = f"{display_name} ({suffix})"
            display_name = candidate
        db.add(models.Library(
            name=display_name,
            folder_name=folder_name,
            path=config.library_path(folder_name),
            sort_order=_next_sort_order(db),
        ))
        known_names.add(display_name)
    db.commit()


def resolve_folder_name(db: Session, name: str) -> str:
    """
    Resolves a library's real on-disk folder_name from either its display
    `name` OR the folder_name itself (the frontend now sends the real
    folder_name it got from GET /api/kolibre/libraries — see librarySlug in
    App.vue — but this also still accepts a raw display name for any older
    cached client). Checking folder_name first matters for real: a display
    name containing characters that don't round-trip through a naive
    lowercase+underscore slug (parens, accents, a "(2)" disambiguation
    suffix — see sync_library_registry) used to make every one of these
    per-library actions (delete/rescan/recompute-*) silently 404 forever,
    with no way to recover from the web UI (confirmed as a real, not
    hypothetical, stuck-library bug).
    """
    row = db.query(models.Library).filter(
        (models.Library.folder_name == name) | (models.Library.name == name)
    ).first()
    return row.folder_name if row else name.lower().replace(" ", "_")


def _clear_deletion_tombstone(db: Session, folder_name: str) -> None:
    """Un-deletes a folder_name: the user is intentionally (re)creating a
    library at this slug, so it should no longer be excluded from
    sync_library_registry, nor refused by bootstrap_library's own on-disk
    marker (see DELETED_LIBRARY_MARKER) — a folder about to be recreated
    at this same path can't still carry the "never resurrect me" marker."""
    db.query(models.DeletedLibraryFolder).filter(models.DeletedLibraryFolder.folder_name == folder_name).delete()
    marker_path = os.path.join(config.library_path(folder_name), DELETED_LIBRARY_MARKER)
    if os.path.exists(marker_path):
        os.remove(marker_path)


def _library_stats(folder_name: str) -> dict:
    db_path = os.path.join(config.library_path(folder_name), "metadata.db")
    books_count = authors_count = size_bytes = 0
    if os.path.exists(db_path):
        try:
            conn = get_connection(db_path)
            books_count = conn.execute("SELECT count(*) FROM books").fetchone()[0]
            authors_count = conn.execute("SELECT count(*) FROM authors").fetchone()[0]
            size_bytes = conn.execute("SELECT COALESCE(SUM(uncompressed_size), 0) FROM data").fetchone()[0]
            conn.close()
        except Exception:
            pass
    return {"books_count": books_count, "authors_count": authors_count, "size_bytes": size_bytes}


@router.get("")
def list_libraries(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Le biblioteche che QUESTA persona puo' vedere.

    Fino al 28/09/2026 le restituiva tutte, e `visibleUsers` era la stringa
    fissa `["paolo", "ospite"]` — un segnaposto che raccontava una
    condivisione inesistente."""
    sync_library_registry(db)
    # Questo ordine E' l'ordine di priorita' dell'utente (Impostazioni →
    # Librerie ▲▼): il frontend tratta libraries[0] come predefinita.
    rows = permessi.biblioteche_visibili(db, current_user)
    nomi_utenti = {u.id: u.username for u in db.query(models.User).all()}
    per_biblioteca = {}
    for p in db.query(models.LibraryPermission).all():
        per_biblioteca.setdefault(p.library_id, []).append(p)
    libs = []
    for i, row in enumerate(rows):
        stats = _library_stats(row.folder_name)
        condivisa_con = [
            nomi_utenti.get(p.user_id) for p in per_biblioteca.get(row.id, [])
            if nomi_utenti.get(p.user_id)
        ]
        libs.append({
            "id": row.id,
            "name": row.name,
            "folder_name": row.folder_name,
            "path": row.path,
            "icon": "library" if i == 0 else "archive",
            "owner": nomi_utenti.get(row.owner_id),
            "visibleUsers": sorted(filter(None, [nomi_utenti.get(row.owner_id)] + condivisa_con)),
            # Cosa puo' farci chi sta guardando: serve al frontend per
            # nascondere i comandi invece di offrirli e poi rispondere 403.
            "canEdit": permessi.puo_modificare(db, current_user, row),
            "canShare": permessi.puo_condividere(db, current_user, row),
            "canDelete": permessi.puo_cancellare(db, current_user, row),
            "fulltextEnabled": app_settings.is_fulltext_enabled(db, row.folder_name),
            **stats,
        })
    return libs


@router.put("/order")
def reorder_libraries(
    payload: dict,
    db: Session = Depends(database.get_db),
    # L'ordine e' globale, e il primo elemento diventa la biblioteca
    # predefinita per TUTTI (vedi resolve_default_library_folder): non e' una
    # preferenza di chi clicca, e' una scelta dell'installazione.
    _chi: models.User = Depends(auth.get_current_active_admin),
):
    """Body: {"order": [id, id, ...]} in the desired display order — the
    first entry becomes the new default library (see resolve_default_library_folder).
    Persists what the ▲▼ buttons in Impostazioni → Librerie only used to
    change in local frontend state."""
    order = payload.get("order")
    if not isinstance(order, list) or not order:
        raise HTTPException(status_code=400, detail="order (lista di id) obbligatorio")
    rows = {row.id: row for row in db.query(models.Library).filter(models.Library.id.in_(order)).all()}
    for position, lib_id in enumerate(order):
        if lib_id in rows:
            rows[lib_id].sort_order = position
    db.commit()
    return {"status": "ok"}


@router.post("")
def create_library(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(permessi.richiede_creare_biblioteche),
):
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    folder_name = name.lower().replace(" ", "_")
    if db.query(models.Library).filter(models.Library.folder_name == folder_name).first():
        raise HTTPException(status_code=409, detail="Una libreria con questo nome esiste già")

    # Must run BEFORE CalibreLibrary(...) below: bootstrap_library refuses to
    # create a metadata.db while the on-disk DELETED_LIBRARY_MARKER is still
    # present (see LibraryDeletedError), which this same folder_name can
    # carry if a library with this exact name was deleted before. Recreating
    # a deleted library used to fail unconditionally here — the tombstone
    # was only ever cleared AFTER the CalibreLibrary(...) call already threw.
    _clear_deletion_tombstone(db, folder_name)
    # Creazione vera: e' l'unico posto, con l'importazione qui sotto, che
    # ha il diritto di far nascere una biblioteca (vedi bootstrap_library).
    CalibreLibrary(config.library_path(folder_name), crea=True)
    db.add(models.Library(
        name=name, folder_name=folder_name, path=config.library_path(folder_name),
        sort_order=_next_sort_order(db),
        # Chi la crea la possiede: e' l'unica assegnazione che non richiede
        # di chiedere niente a nessuno.
        owner_id=current_user.id,
    ))
    db.commit()
    log_message("info", "libraries", f"Created library: {name}")
    return {"status": "ok"}


async def _recompute_after_import(folder_name: str, write_queue: CalibreWriteQueue) -> None:
    """
    Fire-and-forget follow-up to a zero-copy library import: the imported
    folder can be an existing Calibre library with hundreds of books already
    in it, so computing every page count/hash synchronously inside the
    import request — the way the single-book upload paths do inline — would
    make that one request hang for minutes. Instead this just triggers the
    exact same per-library loops the "Ricalcola" buttons in Impostazioni
    already run by hand (POST .../recompute-pages and .../recompute-hashes),
    right after the import instead of leaving every imported book without a
    page count until someone remembers to press them.

    Runs on its own DB session: the request's own session is closed once the
    response is sent, well before a library-wide recompute over hundreds of
    books would finish.
    """
    db = database.SessionLocal()
    try:
        await recompute_page_counts(folder_name, db=db, write_queue=write_queue)
        recompute_hashes(folder_name, db=db)
        # Only meaningful once the pass above has ensured the `pages` custom
        # column exists and populated it for this newly-imported library —
        # doing this any earlier (e.g. inline in import_library itself)
        # would mark the cache dirty before there's anything real to
        # recompute from, and the next GET /authors would just cache zeros
        # for this library's authors again.
        author_stats_service.safe_mark_author_pages_dirty(db)
    except Exception as e:
        log_message("warning", "libraries", f"Recompute automatico post-import fallito per '{folder_name}': {e}")
    finally:
        db.close()


@router.post("/import")
def import_library(
    payload: dict,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(database.get_db),
    # Stesso permesso di create_library: le due rotte fanno la stessa cosa —
    # far nascere una biblioteca — e questa non chiedeva niente. Con un
    # `path` arbitrario creava anche un metadata.db dentro una cartella
    # qualunque del server.
    current_user: models.User = Depends(permessi.richiede_creare_biblioteche),
):
    """
    Zero-copy import of an existing Calibre library: we never duplicate the
    library's metadata.db or book files, only point at the external folder via
    a symlink under LIBRARIES_DIR. If the filesystem doesn't support symlinks
    we fail loudly instead of silently falling back to copying just the
    metadata.db (the previous behavior left a copy that referenced book files
    which weren't actually copied alongside it — a broken, misleading "import").

    Schedules _recompute_after_import as a background task once the import
    itself is done — see its own docstring for why this is async/background
    rather than inline like every other book-add path in this codebase.
    """
    name = payload.get("name")
    path = payload.get("path")
    if not name or not path:
        raise HTTPException(status_code=400, detail="Name and path required")

    folder_name = name.lower().replace(" ", "_")
    if db.query(models.Library).filter(models.Library.folder_name == folder_name).first():
        raise HTTPException(status_code=409, detail="Una libreria con questo nome esiste già")

    db_path = os.path.join(path, "metadata.db")
    if not os.path.exists(db_path):
        CalibreLibrary(path, crea=True)  # bootstraps a fresh Calibre-compatible metadata.db in place

    target_link = config.library_path(folder_name)
    if os.path.lexists(target_link):
        if os.path.islink(target_link):
            os.unlink(target_link)
        else:
            # An unregistered real folder is already sitting at this slug
            # (the common case — a name already used by a registered library —
            # is rejected above). Trash it rather than rmtree, same reasoning
            # as delete_library: never silently destroy real files on disk.
            os.makedirs(TRASH_DIR, exist_ok=True)
            shutil.move(target_link, os.path.join(TRASH_DIR, f"{folder_name}_{int(time.time())}"))

    try:
        os.symlink(path, target_link)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Impossibile creare un symlink verso '{path}': l'import zero-copy "
                f"richiede un filesystem che supporti i symlink ({exc})"
            ),
        )

    db.add(models.Library(
        name=name, folder_name=folder_name, path=target_link, sort_order=_next_sort_order(db),
    ))
    _clear_deletion_tombstone(db, folder_name)
    db.commit()
    log_message("info", "libraries", f"Imported library: {name} from {path}")
    background_tasks.add_task(_recompute_after_import, folder_name, request.app.state.write_queue)
    return {"status": "ok"}


def _trash_entry_path(entry: str) -> str:
    """Resolves a trash listing id — always the literal subfolder name under
    _trash_libraries, e.g. "narrativa_1787094506" — to an absolute path,
    rejecting anything that could escape TRASH_DIR (this comes straight from
    a URL path parameter, not from a listing we generated ourselves)."""
    if not entry or "/" in entry or "\\" in entry or entry in (".", ".."):
        raise HTTPException(status_code=400, detail="Nome cestino non valido")
    path = os.path.abspath(os.path.join(TRASH_DIR, entry))
    if not path.startswith(os.path.abspath(TRASH_DIR) + os.sep):
        raise HTTPException(status_code=400, detail="Nome cestino non valido")
    return path


def _dir_size_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for fname in files:
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                pass
    return total


@router.get("/trash")
def list_trashed_libraries(_chi: models.User = Depends(auth.get_current_active_admin)):
    """
    Contents of _trash_libraries — folders moved there by delete_library/
    import_library instead of being deleted outright (see TRASH_DIR's own
    docstring above) with, until now, NO way to act on them at all: confirmed
    nothing else in this codebase ever reads from or writes into this
    directory besides those two call sites. Without this (and the
    restore/purge endpoints below), it only ever grows.
    """
    if not os.path.isdir(TRASH_DIR):
        return {"items": []}
    items = []
    for entry in sorted(os.listdir(TRASH_DIR)):
        full_path = os.path.join(TRASH_DIR, entry)
        if not os.path.isdir(full_path):
            continue
        # Every entry is named "{folder_name}_{unix_timestamp}" by the two
        # write sites above — rsplit once from the right so a folder_name
        # that itself contains underscores still parses correctly.
        folder_name, _, ts = entry.rpartition("_")
        deleted_at = None
        if ts.isdigit():
            try:
                deleted_at = datetime.utcfromtimestamp(int(ts)).isoformat() + "Z"
            except (OverflowError, OSError, ValueError):
                deleted_at = None
        items.append({
            "id": entry,
            "folder_name": folder_name or entry,
            "deleted_at": deleted_at,
            "size_bytes": _dir_size_bytes(full_path),
        })
    return {"items": items}


@router.post("/trash/{entry}/restore")
def restore_trashed_library(
    entry: str,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(database.get_db),
    # Come il purge accanto: il cestino contiene biblioteche di chiunque, e
    # elencarle o farne rinascere una non puo' essere alla portata di ogni
    # account. Il purge il controllo ce l'aveva, questi due no.
    _chi: models.User = Depends(auth.get_current_active_admin),
):
    """
    The reverse of delete_library: moves a trashed folder back to its
    original slug and re-registers it, same shape as import_library (down to
    reusing its own post-restore background recompute). Refuses outright
    rather than guessing whenever the slug is no longer free — silently
    overwriting whatever is there now would be exactly the kind of
    "eliminates real files with no undo" mistake TRASH_DIR exists to avoid.
    """
    trash_path = _trash_entry_path(entry)
    if not os.path.isdir(trash_path):
        raise HTTPException(status_code=404, detail="Voce del cestino non trovata")

    folder_name = entry.rpartition("_")[0]
    if not folder_name:
        raise HTTPException(status_code=400, detail="Impossibile ricostruire il nome della libreria da questa voce")
    if db.query(models.Library).filter(models.Library.folder_name == folder_name).first():
        raise HTTPException(
            status_code=409,
            detail=f"Una libreria '{folder_name}' è già registrata — rimuovila prima di ripristinare questa",
        )

    target_path = config.library_path(folder_name)
    if os.path.isdir(target_path):
        # The only legitimate reason this exists is delete_library's own
        # tombstone placeholder (an empty folder + DELETED_LIBRARY_MARKER) —
        # anything else is a real, unregistered folder already occupying
        # this slug, which must never be silently clobbered.
        if sorted(os.listdir(target_path)) not in ([], [DELETED_LIBRARY_MARKER]):
            raise HTTPException(
                status_code=409,
                detail=f"'{folder_name}' esiste già sul disco con contenuto proprio — spostalo o rimuovilo prima di ripristinare",
            )
        shutil.rmtree(target_path)

    shutil.move(trash_path, target_path)
    db.add(models.Library(
        name=folder_name.replace("_", " ").capitalize(),
        folder_name=folder_name,
        path=target_path,
        sort_order=_next_sort_order(db),
    ))
    _clear_deletion_tombstone(db, folder_name)
    db.commit()
    log_message("info", "libraries", f"Restored library '{folder_name}' from trash entry '{entry}'")
    background_tasks.add_task(_recompute_after_import, folder_name, request.app.state.write_queue)
    return {"status": "ok", "folder_name": folder_name}


@router.delete("/trash/{entry}")
def purge_trashed_library(
    entry: str,
    _admin: models.User = Depends(auth.get_current_active_admin),
):
    """Permanent, unrecoverable delete of one trash entry — the action
    TRASH_DIR was always missing a way to actually perform.

    Riservato a un amministratore: e' l'unica cancellazione del progetto
    da cui non si torna indietro."""
    trash_path = _trash_entry_path(entry)
    if not os.path.isdir(trash_path):
        raise HTTPException(status_code=404, detail="Voce del cestino non trovata")
    shutil.rmtree(trash_path)
    log_message("warning", "libraries", f"Permanently deleted trash entry '{entry}' ({trash_path})")
    return {"status": "ok"}


@router.post("/{name}/rescan")
async def rescan_library(
    name: str,
    db: Session = Depends(database.get_db),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    """
    Indexes book folders that already exist on disk (Author/Title/file.ext)
    but aren't yet in this library's metadata.db — e.g. a library recovered
    without its index, or files copied in by hand outside the normal ingest
    flow. Files are read in place and never moved (unlike ingest import, which
    relocates staged files into the folder structure).

    Also computes BookHash for every format found here — this was the one
    path into a library that never did (ingest and recompute-hashes both
    already did), so a book that only ever entered its library via rescan had
    no row for a KOReader device's push_device_annotations to resolve its own
    reported hash against, and every annotation for it was silently dropped
    into that endpoint's 'unresolved' counter with no error anywhere.

    Same reasoning now applies to the page-count estimate: this used to be
    the one book-add path that left it uncomputed until someone ran the
    library-wide "Ricalcola" tool by hand (reported in use — a book that
    reached the server only via rescan showed up on a KOReader device with
    no page count at all).
    """
    folder_name = resolve_folder_name(db, name)
    library_path = config.library_path(folder_name)
    if not os.path.isdir(library_path):
        raise HTTPException(status_code=404, detail="Library not found")

    lib = CalibreLibrary(library_path)
    # Stesso motivo di recompute_page_counts: camminare l'intero albero della
    # libreria e poi hashare/contare pagine file per file sono lavori da
    # secondi, e questo e' un `async def`.
    already_indexed = await run_in_threadpool(lib.list_book_paths)
    candidates = await run_in_threadpool(
        library_scanner.find_unindexed_book_folders, library_path, already_indexed
    )
    page_settings = app_settings.get_page_count_settings(db)

    discovered_authors: set[str] = set()
    for item in candidates:
        discovered_authors.update(string_to_authors(item["author"]))
        book_id = await write_queue.submit(
            "insert_book", {"title": item["title"], "author": item["author"]}, library_path
        )
        await write_queue.submit(
            "update_book", {"book_id": book_id, "fields": {"path": item["rel_dir"]}}, library_path
        )
        format_paths: dict[str, str] = {}
        for fmt in item["formats"]:
            await write_queue.submit(
                "add_format",
                {
                    "book_id": book_id,
                    "fmt": fmt["format"],
                    "size_bytes": fmt["size_bytes"],
                    "name": os.path.splitext(fmt["file_name"])[0],
                },
                library_path,
            )
            file_path = os.path.join(library_path, item["rel_dir"], fmt["file_name"])
            await run_in_threadpool(
                book_hash_service.upsert_book_hash, db, folder_name, book_id, fmt["format"], file_path
            )
            format_paths[fmt["format"]] = file_path

        if format_paths:
            preferred_fmt = page_counter.pick_preferred_format(list(format_paths.keys()))
            preferred_path = format_paths[preferred_fmt]
            pages = await run_in_threadpool(
                page_counter.count_pages,
                preferred_path, preferred_fmt, page_settings["mode"],
                page_settings["words_per_page"], page_settings["chars_per_page"],
            )
            if pages is not None:
                await write_queue.submit(
                    "update_book", {"book_id": book_id, "fields": page_count_fields(pages)}, library_path
                )
                try:
                    await run_in_threadpool(
                        opf_metadata.embed_page_count, library_path, preferred_path, preferred_fmt, pages
                    )
                except Exception as e:
                    log_message("warning", "libraries", f"Embedding pagine nell'OPF fallito per '{preferred_path}': {e}")
    db.commit()

    if candidates:
        author_stats_service.safe_mark_author_pages_dirty(db)
    author_ingest_hook.maybe_trigger_wiki_scrape(discovered_authors)
    log_message("info", "libraries", f"Rescan '{name}': indexed {len(candidates)} new book folder(s)")
    return {"status": "ok", "imported": len(candidates)}


@router.post("/{name}/recompute-pages")
async def recompute_page_counts(
    name: str,
    db: Session = Depends(database.get_db),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    """
    (Re)computes the "Pagine (stimate)" value for every book in a library,
    using each book's first available format and the current global
    page-count settings (PUT /api/kolibre/settings/page-count). Needed for
    books that existed before this feature (imported/rescanned libraries),
    since normal ingest already computes it at import time.
    """
    folder_name = resolve_folder_name(db, name)
    library_path = config.library_path(folder_name)
    if not os.path.isdir(library_path):
        raise HTTPException(status_code=404, detail="Library not found")

    settings = app_settings.get_page_count_settings(db)
    lib = CalibreLibrary(library_path)
    updated = 0
    # run_in_threadpool su tutto cio' che apre file veri: questo endpoint e'
    # `async def`, quindi senza girava sull'event loop e per tutta la sua
    # durata OGNI altra richiesta al server si metteva in coda. Misurato:
    # 53 ms a libro, cioe' ~65 secondi su 1.216 libri, con le richieste
    # normali ritardate fino a 309 ms. La stessa cosa e' gia' fatta bene in
    # books.py (recompute pagine di un libro singolo); qui mancava.
    # recompute_hashes qui sotto non ne ha bisogno: e' `def` e basta, quindi
    # FastAPI lo manda gia' in un thread da solo.
    for book in await run_in_threadpool(lib.list_books):
        formats = lib.get_formats(book["id"])
        if not formats:
            continue
        fmt = page_counter.pick_preferred_format([f["format"] for f in formats])
        file_path = lib.get_format_file_path(book["id"], fmt)
        if not file_path:
            continue
        pages = await run_in_threadpool(
            page_counter.count_pages,
            file_path, fmt, settings["mode"], settings["words_per_page"], settings["chars_per_page"],
        )
        # Nello stesso giro si registra anche quanti caratteri ha il libro:
        # il testo e' gia' stato estratto per contare le pagine, e senza quel
        # numero una frazione di libro letta non si puo' tradurre in
        # caratteri letti (vedi stats_service). E' anche il modo in cui una
        # biblioteca esistente si riempie: questo e' il pulsante "Ricalcola
        # le pagine stimate" che si usa gia'.
        await run_in_threadpool(
            stats_service.registra_conteggio_testo, db, folder_name, book["id"], file_path, fmt
        )
        if pages is None:
            continue
        await write_queue.submit(
            "update_book", {"book_id": book["id"], "fields": page_count_fields(pages)}, library_path
        )
        # Best-effort, same reasoning as ingest.py's own call site — see
        # opf_metadata.py's docstring. Runs here too so already-imported
        # books (this endpoint's whole reason to exist) get the embedded
        # value retroactively, not just newly-ingested ones.
        try:
            await run_in_threadpool(opf_metadata.embed_page_count, library_path, file_path, fmt, pages)
        except Exception as e:
            log_message("warning", "libraries", f"Embedding pagine nell'OPF fallito per '{file_path}': {e}")
        updated += 1

    # I conteggi caratteri raccolti nel giro qui sopra: un commit solo alla
    # fine, non uno per libro.
    db.commit()
    log_message("info", "libraries", f"Recompute pages '{name}': updated {updated} book(s)")
    return {"status": "ok", "updated": updated}


@router.post("/{name}/recompute-hashes")
def recompute_hashes(name: str, db: Session = Depends(database.get_db)):
    """
    Computes/refreshes the KOReader-compatible partial-MD5 for every format of
    every book in a library — needed so a device's sync handshake can resolve
    its own reported hashes to a Calibre book. Normal ingest already computes
    this at import time; this catches books that existed before (imported or
    rescanned libraries).
    """
    folder_name = resolve_folder_name(db, name)
    library_path = config.library_path(folder_name)
    if not os.path.isdir(library_path):
        raise HTTPException(status_code=404, detail="Library not found")

    lib = CalibreLibrary(library_path)
    updated = 0
    for book in lib.list_books():
        for fmt_info in lib.get_formats(book["id"]):
            fmt = fmt_info["format"]
            file_path = lib.get_format_file_path(book["id"], fmt)
            if not file_path:
                continue
            if book_hash_service.upsert_book_hash(db, folder_name, book["id"], fmt, file_path):
                updated += 1
    db.commit()

    log_message("info", "libraries", f"Recompute hashes '{name}': updated {updated} format(s)")
    return {"status": "ok", "updated": updated}


@router.get("/{name}/book-paths")
def analyze_book_paths(name: str, limit: int = 50, db: Session = Depends(database.get_db)):
    """
    Quali libri stanno in una cartella intestata a un autore che non e' piu'
    il loro. Sola lettura: serve a far vedere cosa si sta per spostare prima
    di spostarlo.

    `limit` limita solo gli ESEMPI riportati, non il conteggio: su una
    biblioteca grande non ha senso spedire diecimila righe a una pagina che
    ne mostra una manciata, ma il totale deve restare quello vero.
    """
    folder_name = resolve_folder_name(db, name)
    library_path = config.library_path(folder_name)
    if not os.path.isdir(library_path):
        raise HTTPException(status_code=404, detail="Library not found")

    fuori = CalibreLibrary(library_path).percorsi_fuori_posto()
    mancanti = [v for v in fuori if v["missing"]]
    spostabili = [v for v in fuori if not v["missing"]]
    return {
        "total": len(fuori),
        "movable": len(spostabili),
        "missing": len(mancanti),
        "sample": spostabili[:limit],
        "missing_sample": mancanti[:limit],
    }


@router.post("/{name}/book-paths/repair")
async def repair_book_paths(
    name: str,
    payload: dict | None = None,
    db: Session = Depends(database.get_db),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    """
    Sposta i libri sotto la cartella dell'autore giusto.

    Passa dalla coda di scrittura come ogni altra modifica a metadata.db:
    spostare la cartella e aggiornare `books.path` sono la stessa operazione,
    e non deve intrecciarsi con altre scritture sulla stessa biblioteca.

    Accetta un `limit` perche' e' pensata per essere chiamata piu' volte: e'
    idempotente e riprendibile, quindi la pagina puo' avanzare a blocchi e
    mostrare a che punto e' senza bloccare tutto in un'unica richiesta lunga.
    """
    folder_name = resolve_folder_name(db, name)
    library_path = config.library_path(folder_name)
    if not os.path.isdir(library_path):
        raise HTTPException(status_code=404, detail="Library not found")

    payload = payload or {}
    esito = await write_queue.submit(
        "ripara_percorsi",
        {"book_ids": payload.get("ids"), "limite": int(payload.get("limit") or 0)},
        library_path,
    )
    log_message(
        "info", "libraries",
        f"Percorsi libri '{name}': {esito['moved']} spostati, "
        f"{len(esito['failed'])} falliti, {esito['remaining']} ancora da fare",
    )
    return {"status": "ok", **esito}


def purge_orphans_for_library(db: Session, folder_name: str) -> dict:
    """
    Rows that become pure dead weight once a library is really gone — no
    authored content, no path back to anything a user could want restored,
    unlike Highlight (see delete_library's own comment) or SavedChart (a
    user's own chart configuration, left alone for the same "authored
    content" reason). Split out from delete_library so the exact same
    cleanup can also be run once, by hand, for libraries deleted BEFORE this
    function existed (their DeletedLibraryFolder tombstone is already
    there — see the one-off admin script that calls this for each of them).

    StatsHashDiscard is deliberately NOT touched here: it has no `library`
    column at all (global by md5, see its own docstring), so it can never
    be orphaned by a library's deletion in the first place.
    """
    counts = {
        "stats_cache": db.query(models.StatsCache).filter(models.StatsCache.library == folder_name).delete(),
        "book_hash_history": db.query(models.BookHashHistory).filter(models.BookHashHistory.library == folder_name).delete(),
        "stats_hash_pairings": db.query(models.StatsHashPairing).filter(models.StatsHashPairing.library == folder_name).delete(),
        "pending_calibre_writes": db.query(models.PendingCalibreWrite).filter(
            models.PendingCalibreWrite.library_path == config.library_path(folder_name)
        ).delete(),
    }

    # A flagged-book row's own identity (device_id, local_path) has nothing
    # to do with any library — only clear the now-meaningless SUGGESTION
    # fields that pointed at the deleted one, never the row itself (deleting
    # it would silently drop a real "questo file non è mai stato accoppiato"
    # signal the device still needs surfaced).
    stale_candidates = db.query(models.DeviceFlaggedBook).filter(
        models.DeviceFlaggedBook.candidate_library == folder_name
    ).update({
        "candidate_library": None,
        "candidate_calibre_book_id": None,
        "candidate_title": None,
        "candidate_author": None,
    }, synchronize_session=False)
    # A queued 'overwrite'/'delete' action pointing at the deleted library
    # can never be applied by the plugin on its next sync — drop the whole
    # pending action, not just the library reference, so the row goes back
    # to plain "flagged, nothing queued" instead of retrying forever.
    stale_pending = db.query(models.DeviceFlaggedBook).filter(
        models.DeviceFlaggedBook.pending_action_library == folder_name
    ).update({
        "pending_action": None,
        "pending_action_library": None,
        "pending_action_calibre_book_id": None,
        "pending_action_format": None,
    }, synchronize_session=False)
    counts["device_flagged_book_candidates_cleared"] = stale_candidates
    counts["device_flagged_book_pending_actions_cleared"] = stale_pending
    return counts


@router.delete("/{name}")
def delete_library(
    name: str,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Riservato al PROPRIETARIO della biblioteca (e al fondatore).

    Decisione del 28/09/2026: cancellare non e' una modifica piu'
    grande delle altre, e' un'altra cosa. Chi puo' modificare puo' sbagliare
    un titolo; chi puo' cancellare porta via i libri a tutti quelli con cui
    la biblioteca e' condivisa. Prima bastava essere amministratore, e prima
    ancora — fino al 27/09 — bastava essere autenticati.

    `is_admin` esisteva sul modello Utente da sempre, `get_current_active_admin`
    era scritta in auth.py, e NESSUN endpoint la usava: qualunque utente
    autenticato poteva cancellare una biblioteca intera. Questo e questo solo
    e' il punto che si puo' chiudere senza aver prima deciso niente sul
    multiutente — chi possiede una biblioteca, chi la condivide e con quali
    livelli sono sei domande ancora aperte, ma "cancellare
    tutto non e' un gesto da ospite" non ne richiede nessuna.

    Il commento qui sotto sul cestino diceva gia' "until an admin empties the
    trash": il codice dava per scontato un controllo che non c'era."""
    folder_name = resolve_folder_name(db, name)
    lib_path = config.library_path(folder_name)
    row = db.query(models.Library).filter(models.Library.folder_name == folder_name).first()
    if not (os.path.exists(lib_path) or os.path.lexists(lib_path)) and not row:
        raise HTTPException(status_code=404, detail="Library not found")
    if row is not None and not permessi.puo_cancellare(db, current_user, row):
        raise HTTPException(status_code=403, detail=f"Solo il proprietario può cancellare '{row.name}'.")

    if os.path.islink(lib_path):
        # Zero-copy imported library: the real data lives elsewhere, untouched.
        # Removing the symlink is inherently safe, nothing to lose.
        os.unlink(lib_path)
    elif os.path.exists(lib_path):
        # This folder IS the library's actual storage — never permanently
        # delete real book files on a single click with no undo. Move it into
        # a timestamped trash folder instead of shutil.rmtree; recoverable
        # manually until an admin empties the trash for real.
        os.makedirs(TRASH_DIR, exist_ok=True)
        trashed_path = os.path.join(TRASH_DIR, f"{folder_name}_{int(time.time())}")
        shutil.move(lib_path, trashed_path)
        log_message("warning", "libraries", f"Library '{name}' moved to trash: {trashed_path}")

    # A fresh, empty folder holding ONLY the tombstone marker (see
    # bootstrap_library) — without this, the very next plain CalibreLibrary(...)
    # call for this folder_name (e.g. a cross-library book-title lookup keyed
    # off a stale BookHash/DeviceBook row, below) would silently recreate a
    # real, empty metadata.db here, undoing the deletion from the inside.
    os.makedirs(lib_path, exist_ok=True)
    with open(os.path.join(lib_path, DELETED_LIBRARY_MARKER), "w"):
        pass

    # BookHash/DeviceBook/ReadingPosition/ReadingSession rows for this
    # folder_name are all mechanical tracking data (a hash is just a
    # fingerprint, a DeviceBook row just "this file is on this device", a
    # reading position/session just "how far/how long" — none of it
    # authored content) — cascading them on every deletion, not just once
    # by hand, is what makes "elimina libreria" leave nothing dangling
    # behind for a real, confirmed-gone library ever again. Highlights
    # (actual notes/quotes the user wrote or selected) are the one
    # exception, deliberately left alone: real authored content shouldn't
    # silently vanish just because its library did, in case the trashed
    # folder (or a manual restore) ever makes calibre_book_id meaningful
    # again for this folder_name.
    db.query(models.BookHash).filter(models.BookHash.library == folder_name).delete()
    db.query(models.DeviceBook).filter(models.DeviceBook.library == folder_name).delete()
    db.query(models.ReadingPosition).filter(models.ReadingPosition.library == folder_name).delete()
    db.query(models.ReadingSession).filter(models.ReadingSession.library == folder_name).delete()
    purge_orphans_for_library(db, folder_name)

    if row:
        db.delete(row)
    if not db.query(models.DeletedLibraryFolder).filter(models.DeletedLibraryFolder.folder_name == folder_name).first():
        db.add(models.DeletedLibraryFolder(folder_name=folder_name))
    db.commit()

    author_stats_service.safe_mark_author_pages_dirty(db)
    log_message("info", "libraries", f"Deleted library: {name}")
    return {"status": "ok"}


# ── Condividere una biblioteca ────────────────────────────────────────────

def _biblioteca(db: Session, name: str) -> models.Library:
    riga = db.query(models.Library).filter(
        models.Library.folder_name == resolve_folder_name(db, name)
    ).first()
    if not riga:
        raise HTTPException(status_code=404, detail="Biblioteca non trovata")
    return riga


@router.get("/{name}/permessi")
def library_permissions(
    name: str,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Con chi e' condivisa questa biblioteca, e con che livello."""
    riga = _biblioteca(db, name)
    if not permessi.puo_leggere(db, current_user, riga):
        raise HTTPException(status_code=403, detail="Non hai accesso a questa biblioteca.")
    nomi = {u.id: u.username for u in db.query(models.User).all()}
    condivisioni = db.query(models.LibraryPermission).filter(
        models.LibraryPermission.library_id == riga.id
    ).all()
    return {
        "library": riga.folder_name,
        "owner": nomi.get(riga.owner_id),
        "owner_id": riga.owner_id,
        "puoi_gestire": permessi.puo_gestire_permessi(db, current_user, riga),
        "condivisioni": [
            {
                "user_id": p.user_id, "username": nomi.get(p.user_id),
                "can_edit": p.can_edit, "can_share": p.can_share, "can_manage": p.can_manage,
            }
            for p in condivisioni if nomi.get(p.user_id)
        ],
    }


@router.put("/{name}/permessi")
def set_library_permission(
    name: str,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Da', cambia o toglie l'accesso di una persona a questa biblioteca.
    Body: {"user_id": n, "can_edit": bool, "can_share": bool, "can_manage": bool}
    oppure {"user_id": n, "revoca": true}.

    Chi puo' **condividere** puo' dare accesso; chi puo' **gestire** puo'
    anche togliere e assegnare a sua volta i permessi di gestione. La
    differenza conta: condividere un libro e decidere chi altro puo'
    condividerlo sono due gesti diversi.

    Nessuno puo' dare piu' di quello che ha — tranne il proprietario e il
    fondatore, che hanno tutto. Senza questa regola, "condividere" sarebbe
    la scala che porta ovunque: basterebbe darsi can_manage da soli.
    """
    riga = _biblioteca(db, name)
    if not permessi.puo_condividere(db, current_user, riga):
        raise HTTPException(status_code=403, detail="Non puoi condividere questa biblioteca.")

    user_id = payload.get("user_id")
    destinatario = db.query(models.User).filter(models.User.id == user_id).first()
    if not destinatario:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    if destinatario.id == riga.owner_id:
        raise HTTPException(status_code=400, detail="Il proprietario ha già tutti i permessi.")

    esistente = db.query(models.LibraryPermission).filter(
        models.LibraryPermission.library_id == riga.id,
        models.LibraryPermission.user_id == destinatario.id,
    ).first()

    if payload.get("revoca"):
        if not permessi.puo_gestire_permessi(db, current_user, riga):
            raise HTTPException(status_code=403, detail="Togliere un accesso richiede di poter gestire i permessi.")
        if esistente:
            db.delete(esistente)
            db.commit()
        return {"status": "ok", "revocato": True}

    puo_gestire = permessi.puo_gestire_permessi(db, current_user, riga)
    voluto = {
        "can_edit": bool(payload.get("can_edit")),
        "can_share": bool(payload.get("can_share")),
        "can_manage": bool(payload.get("can_manage")),
    }
    if not puo_gestire and (voluto["can_share"] or voluto["can_manage"]):
        raise HTTPException(
            status_code=403,
            detail="Puoi dare accesso, non il potere di condividere o gestire a sua volta.",
        )
    # «Nessuno puo' dare piu' di quello che ha» era scritto nel docstring ma
    # valeva solo per can_share e can_manage: can_edit non era controllato,
    # quindi chi aveva can_share e NON can_edit poteva darlo lo stesso.
    if voluto["can_edit"] and not permessi.puo_modificare(db, current_user, riga):
        raise HTTPException(
            status_code=403,
            detail="Non puoi dare il permesso di modificare una biblioteca che tu stesso non puoi modificare.",
        )
    # E non lo si da' a se' stessi: con can_share ci si scriveva la propria
    # riga di permesso e ci si aggiungeva can_edit.
    if destinatario.id == current_user.id and not puo_gestire:
        raise HTTPException(
            status_code=403,
            detail="Non puoi modificare i tuoi stessi permessi su questa biblioteca.",
        )

    if esistente:
        for campo, valore in voluto.items():
            setattr(esistente, campo, valore)
    else:
        db.add(models.LibraryPermission(library_id=riga.id, user_id=destinatario.id, **voluto))
    db.commit()
    log_message("info", "auth", f"Permessi su '{riga.name}' aggiornati per '{destinatario.username}'.")
    return {"status": "ok", **voluto}


@router.put("/{name}/proprietario")
def set_library_owner(
    name: str,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Passa la proprieta' a un'altra persona. Solo il proprietario (o il
    fondatore) puo' farlo: cedere e' un gesto del proprietario, non di chi
    amministra."""
    riga = _biblioteca(db, name)
    if not permessi.puo_cancellare(db, current_user, riga):
        raise HTTPException(status_code=403, detail="Solo il proprietario può cedere la biblioteca.")
    nuovo = db.query(models.User).filter(models.User.id == payload.get("user_id")).first()
    if not nuovo:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    vecchio_id = riga.owner_id
    riga.owner_id = nuovo.id
    # Il vecchio proprietario non resta fuori dalla sua biblioteca: prende
    # una condivisione piena. Cedere non e' cacciarsi.
    if vecchio_id and vecchio_id != nuovo.id:
        gia = db.query(models.LibraryPermission).filter(
            models.LibraryPermission.library_id == riga.id,
            models.LibraryPermission.user_id == vecchio_id,
        ).first()
        if not gia:
            db.add(models.LibraryPermission(
                library_id=riga.id, user_id=vecchio_id,
                can_edit=True, can_share=True, can_manage=True,
            ))
    # Una condivisione verso il nuovo proprietario non serve piu'.
    db.query(models.LibraryPermission).filter(
        models.LibraryPermission.library_id == riga.id,
        models.LibraryPermission.user_id == nuovo.id,
    ).delete(synchronize_session=False)
    db.commit()
    log_message("info", "auth", f"'{riga.name}' passa a '{nuovo.username}'.")
    return {"status": "ok", "owner": nuovo.username}
