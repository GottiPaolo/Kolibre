"""
La gestione del parco dispositivi, vista dall'utente.

Il mestiere: le rotte con cui una persona — dalla webapp, col proprio JWT —
registra un lettore, lo guarda, lo rinomina, decide quale libro deve
arrivarci e che fine fanno le righe dei libri a bordo. (Trasloco del
20/11/2026: prima era tutto in api/devices.py.)

Le rotte:
* POST /api/devices/register — nasce un dispositivo, e con lui il token;
* GET  /api/devices — l'elenco, coi libri a bordo, lo stato dei dizionari
  e l'eventuale richiesta di ripristino aperta;
* GET  /api/devices/me — l'unica qui sul token di dispositivo
  (device_token_router): la "prova connessione" del plugin KOReader;
* PUT  /api/devices/{id} e DELETE /api/devices/{id};
* POST /api/devices/{id}/set-default;
* POST /api/devices/{id}/queue — mette in coda un libro da mandare;
* POST /api/devices/{id}/queue/bulk — l'invio multiplo (21/11/2026):
  accoda i libri che mancano e dice quali ha saltati e perche';
* DELETE /api/devices/{id}/vocabulary — dimentica il vocabolario del
  dispositivo;
* GET  /api/devices/{id}/sync-history — lo storico delle sessioni di sync;
* POST /api/devices/{id}/books/{row}/acknowledge-removal, .../cancel,
  .../pair — le azioni sulla singola riga di libro a bordo.

Chi le chiama: la webapp (tutte, col JWT) — tranne GET /me, che e' del
plugin. Regola trasversale: niente si tocca senza che il dispositivo
appartenga all'utente del JWT; le rotte filtrano per user_id (direttamente
o con `_get_owned_device_book`), e un id altrui vale un 404.
"""

import json
import os
import shutil

from collections import defaultdict

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ... import config, models, schemas, database, auth
from ...istanti import quando

from ...logging_utils import log_message
from ...calibre.library import CalibreLibrary
from ...services import book_hash_service, patch_koreader, permessi
from ...schemas_risposte import (
    DispositivoInElenco, Esito, InviiAccodati, OrfaneMigrate,
    SincronizzazioneNelloStorico, VocabolarioDimenticato,
)
from ..libraries import resolve_default_library_folder

from ._shared import (
    router, device_token_router, _SENDABLE_STATUSES, _SYNC_HISTORY_KEEP,
    _dizionari_in_coda, _get_open_restore_request,
    _migrate_device_highlights_to_new_book, _serialize_restore_request,
)


@router.post("/register", response_model=schemas.DeviceResponse)
def register_device(
    payload: schemas.DeviceCreate,
    db: Session = Depends(database.get_db),
    # Registrare un dispositivo e' un permesso dell'account (28/09/2026).
    # Il dispositivo nasce legato a chi lo registra — sono uno a uno, e lo
    # erano gia' nel codice prima che i permessi esistessero.
    current_user: models.User = Depends(permessi.richiede_registrare_dispositivi),
):
    # Del token si salva **l'impronta** (20/11/2026, come i token
    # d'applicazione): il chiaro esiste solo in questa risposta, una volta —
    # chi lo riceve lo copia nel plugin o lo perde, e il server non e' piu'
    # in grado di ridirlo.
    token = auth.new_device_token()
    new_dev = models.Device(
        device_token_hash=auth.impronta_del_token(token),
        name=payload.name,
        model=payload.model,
        hardware_id=payload.hardware_id,
        user_id=current_user.id,
    )
    db.add(new_dev)
    db.commit()
    db.refresh(new_dev)
    log_message("info", "devices", f"Registered new device '{payload.name}' for user '{current_user.username}'")
    risposta = schemas.DeviceResponse.model_validate(new_dev)
    risposta.device_token = token
    return risposta


def _book_progress_percent(db: Session, library: str, calibre_book_id: int, user_id: int):
    """L'avanzamento di CHI POSSIEDE il dispositivo, non di chiunque.

    Dal 24/09/2026 la posizione e' per utente: senza questo filtro, la
    scheda di un dispositivo mostrerebbe l'avanzamento di un'altra persona
    sullo stesso libro."""
    pos = db.query(models.ReadingPosition).filter(
        models.ReadingPosition.user_id == user_id,
        models.ReadingPosition.library == library,
        models.ReadingPosition.calibre_book_id == calibre_book_id,
    ).first()
    return round(pos.percentage * 100) if pos else 0


def _build_book_titles(rows) -> dict:
    """
    (library, calibre_book_id) -> {"title":..., "author":...} for a batch of
    rows with those two attributes (DeviceBook here), one
    CalibreLibrary.list_books() call per library actually touched — mirrors
    annotations.py's own _build_book_meta (kept as a separate copy rather
    than a shared import, so the two routers stay decoupled).

    Needed because the frontend used to resolve a device row's book title by
    looking it up in books.value, which only ever holds the currently ACTIVE
    library's books — a device with books from more than one library (a
    real, common case, not hypothetical) showed "Sconosciuto" for every row
    belonging to whichever library wasn't currently selected in the
    sidebar, and never showed the author at all.
    """
    by_library = defaultdict(set)
    for r in rows:
        if r.library and r.calibre_book_id:
            by_library[r.library].add(r.calibre_book_id)
    meta = {}
    for library in by_library:
        try:
            lib = CalibreLibrary(config.library_path(library))
            for b in lib.list_books():
                meta[(library, b["id"])] = {
                    "title": b["title"],
                    "author": b["author"] or "Unknown Author",
                    # Stessa formula di books.py::list_books ("cover_url"): un URL
                    # solo se il libro ha davvero una copertina, mai un path da
                    # verificare lato client.
                    # Sempre valorizzato: senza copertina sul disco risponde
                    # quella costruita (books.py::_copertina_costruita).
                    "cover_url": f"/api/kolibre/books/{b['id']}/cover?library={library}",
                }
        except Exception:
            continue  # a library that no longer exists on disk shouldn't break this for the others
    return meta


def _build_hash_verified_map(db: Session, rows) -> dict:
    """
    (library, calibre_book_id, format) -> BookHash.verified, batched for a
    device's DeviceBook rows — see BookHash.verified's own docstring. A
    missing BookHash row (e.g. deleted since) defaults to True: nothing to
    warn about if there's no forced-hash record for it at all.
    """
    keys = {(r.library, r.calibre_book_id, r.format) for r in rows if r.library and r.calibre_book_id and r.format}
    if not keys:
        return {}
    libraries = {k[0] for k in keys}
    hash_rows = db.query(models.BookHash).filter(models.BookHash.library.in_(libraries)).all()
    return {(h.library, h.calibre_book_id, h.format): h.verified for h in hash_rows}


def _patch_riportate(d):
    """Le patch che il dispositivo ha riportato, o None se non le ha riportate.

    La distinzione conta: `None` vuol dire «plugin troppo vecchio, non lo
    sa dire», la lista vuota vuol dire «nessuna patch installata». Mostrarle
    allo stesso modo direbbe una cosa falsa nel primo caso.

    Un JSON illeggibile (una riga scritta da una versione futura, un troncamento)
    si tratta come «non riportato»: meglio dire che non si sa.
    """
    if not d.patch_installate:
        return None
    try:
        valore = json.loads(d.patch_installate)
    except (ValueError, TypeError):
        return None
    return valore if isinstance(valore, list) else None


@router.get(
    "",
    responses={200: {"model": list[DispositivoInElenco]}},
)
def list_devices(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    devs = db.query(models.Device).filter(models.Device.user_id == current_user.id).all()
    result = []
    for d in devs:
        books = db.query(models.DeviceBook).filter(models.DeviceBook.device_id == d.id).all()
        book_meta = _build_book_titles(books)
        hash_verified_map = _build_hash_verified_map(db, books)
        backup_dir = os.path.join(config.BACKUPS_DIR, str(d.id))
        backup_file_count = len(os.listdir(backup_dir)) if os.path.isdir(backup_dir) else 0
        open_restore_request = _get_open_restore_request(db, d.id)
        result.append({
            "id": d.id,
            "name": d.name,
            "model": d.model,
            "is_default": d.is_default,
            "last_sync_at": d.last_sync_at.strftime('%Y-%m-%d %H:%M:%S') if d.last_sync_at else None,
            "last_backup_at": d.last_backup_at.strftime('%Y-%m-%d %H:%M:%S') if d.last_backup_at else None,
            "last_seen_at": d.last_seen_at.strftime('%Y-%m-%d %H:%M:%S') if d.last_seen_at else None,
            "plugin_version": d.plugin_version,
            "delete_policy": d.delete_policy,
            # Le userpatch del server, con lo stato su QUESTO dispositivo
            # (aggiornata / da_aggiornare / assente). Lista vuota se il
            # dispositivo non lo ha riportato: la scheda distingue i due casi.
            "patches": patch_koreader.stato_sul_dispositivo(_patch_riportate(d)),
            "patches_riportate": d.patch_installate is not None,
            # I dizionari in attesa di partire per questo lettore: una coda,
            # quindi vuota appena sono arrivati.
            "dizionari_richiesti": _dizionari_in_coda(d),
            # Misurati dal plugin sul volume dei libri (v0.6.15+); su un
            # dispositivo con un plugin piu' vecchio restano None e la scheda
            # continua a dire "non riportato".
            "storage_used": d.storage_used,
            "storage_total": d.storage_total,
            "storage_available": d.storage_available,
            "backup_file_count": backup_file_count,
            "pending_restore_request": _serialize_restore_request(db, open_restore_request) if open_restore_request else None,
            "supported_formats": ["EPUB", "PDF", "MOBI", "MD"],
            "write_folder_cover": d.write_folder_cover,
            "books": [
                {
                    "id": b.id,
                    "calibre_book_id": b.calibre_book_id, "library": b.library, "format": b.format,
                    "book_title": book_meta.get((b.library, b.calibre_book_id), {}).get("title"),
                    "book_author": book_meta.get((b.library, b.calibre_book_id), {}).get("author"),
                    "cover_url": book_meta.get((b.library, b.calibre_book_id), {}).get("cover_url"),
                    "hash_verified": hash_verified_map.get((b.library, b.calibre_book_id, b.format), True),
                    "status": b.status,
                    "created_at": b.created_at.strftime('%Y-%m-%d %H:%M:%S') if b.created_at else None,
                    "device_pages": b.device_pages,
                    "device_path": b.device_path,
                    "requested_by": b.requested_by,
                    "last_error": b.last_error,
                    "progress_percent": _book_progress_percent(db, b.library, b.calibre_book_id, d.user_id),
                    # Filtrato per utente come _book_progress_percent due righe
                    # sopra: senza, la scheda di un dispositivo sommava le note
                    # di chiunque avesse letto quel libro.
                    "highlights_count": db.query(models.Highlight).filter(
                        models.Highlight.user_id == d.user_id,
                        models.Highlight.library == b.library,
                        models.Highlight.calibre_book_id == b.calibre_book_id,
                        models.Highlight.deleted_at.is_(None),
                    ).count(),
                }
                for b in books
            ],
            # Kept for the current frontend, but now synthesized from
            # DeviceBook desired state — SyncQueue is no longer written to.
            "sync_queue": [
                {
                    "id": b.id, "calibre_book_id": b.calibre_book_id, "library": b.library,
                    "action": "queued_delete" if b.status == "pending_delete" else "queued_download",
                    "format": b.format,
                }
                for b in books
                if b.status in ("pending_send", "send_failed", "pending_delete")
            ],
        })
    return result


@device_token_router.get("/me", response_model=schemas.DeviceResponse)
def get_own_device(current_device: models.Device = Depends(auth.get_current_device)):
    """
    Device-token-authenticated "whoami": lets the KOReader plugin's "Test
    Connection" menu action verify pairing without
    triggering a full sync. This is the first endpoint that uses the permanent
    device bearer token instead of the human JWT.
    """
    return current_device


@router.put("/{device_id}", response_model=schemas.DeviceResponse)
def update_device(
    device_id: int,
    payload: schemas.DeviceUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    if payload.delete_policy is not None and payload.delete_policy not in ("auto", "ask", "never"):
        raise HTTPException(status_code=400, detail="delete_policy must be 'auto', 'ask' or 'never'")
    # `folder_layout` non e' piu' nell'elenco (20/11/2026, punto B8): una
    # webapp vecchia che ancora lo manda viene servita lo stesso — il campo
    # sconosciuto lo scarta Pydantic alla validazione, non un errore qui.
    for field in ("name", "model", "write_folder_cover", "delete_policy"):
        value = getattr(payload, field)
        if value is not None:
            setattr(dev, field, value)
    db.commit()
    db.refresh(dev)
    return dev


@router.delete(
    "/{device_id}",
    responses={200: {"model": Esito}},
)
def delete_device(
    device_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    There was no way to remove a device once registered — not from the UI,
    not from the API. Manually deletes the dependent rows (SyncQueue,
    DeviceBook) instead of relying on the models' declarative
    ondelete="CASCADE": that only takes effect if SQLite has
    `PRAGMA foreign_keys=ON` for the connection, which database.py's own
    pragma listener never sets, so those FKs aren't actually enforced here.
    BookHash is deliberately left alone — it's keyed by (library, book,
    format), shared across every device via hash matching, not owned by any
    one of them.
    """
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")

    db.query(models.SyncQueue).filter(models.SyncQueue.device_id == device_id).delete()
    db.query(models.DeviceBook).filter(models.DeviceBook.device_id == device_id).delete()
    db.query(models.DeviceSyncHistory).filter(models.DeviceSyncHistory.device_id == device_id).delete()
    db.delete(dev)
    db.commit()

    backup_dir = os.path.join(config.BACKUPS_DIR, str(device_id))
    if os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir, ignore_errors=True)

    log_message("info", "devices", f"Deleted device '{dev.name}' (id={device_id}) for user '{current_user.username}'")
    return {"status": "ok"}


@router.post("/{device_id}/set-default", response_model=schemas.DeviceResponse)
def set_default_device(
    device_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    db.query(models.Device).filter(models.Device.user_id == current_user.id).update({"is_default": False})
    dev.is_default = True
    db.commit()
    db.refresh(dev)
    return dev


#: Gli stati di DeviceBook con cui un NUOVO invio dello stesso libro non ha
#: senso, in QUALUNQUE formato (21/11/2026, regola di Paolo: un libro gia'
#: sul dispositivo non si rimanda — e mandare un altro formato dello stesso
#: libro e' il doppione che file_sul_dispositivo e' nata per ripulire):
#: `synced` e `delete_declined` — il file e' a bordo; `pending_delete` — e'
#: ancora a bordo finche' il lettore non conferma la rimozione (per
#: ripensarci c'e' /books/{row}/cancel, non un nuovo invio); `pending_send`
#: — un invio e' gia' in coda, rifarlo sarebbe solo un doppione di coda.
#: Fuori di proposito: `send_failed` (ritentare e' il rimedio giusto) e
#: `removed_by_device` (il file sul lettore non c'e' piu').
_SEND_BLOCKING_STATUSES = ("synced", "delete_declined", "pending_delete", "pending_send")

#: La frase che arriva al browser per ciascun motivo di rifiuto — in
#: inglese come ogni `detail` del server (vedi il_server_parla_inglese.py).
_SEND_BLOCK_DETAILS = {
    "already_on_device": "The book is already on this device",
    "removal_pending": "The book is still on this device, waiting to be "
                       "removed: cancel the removal instead of sending it again",
    "already_queued": "The book is already queued for this device",
}


def _send_block_reason(db, device_id, library, calibre_book_id):
    """
    Perche' un invio di questo libro NON deve partire — o None se puo'.

    Guarda TUTTE le righe del libro su quel dispositivo, non solo quella del
    formato chiesto: «gia' sul dispositivo» per Paolo e' una proprieta' del
    libro (e' cosi' che la colonna della Libreria la mostra), e un secondo
    formato a bordo sarebbe comunque una copia doppia. I motivi in ordine di
    forza: presente batte in coda. (21/11/2026)
    """
    statuses = {s for (s,) in db.query(models.DeviceBook.status).filter(
        models.DeviceBook.device_id == device_id,
        models.DeviceBook.library == library,
        models.DeviceBook.calibre_book_id == calibre_book_id,
        models.DeviceBook.status.in_(_SEND_BLOCKING_STATUSES),
    ).all()}
    if "synced" in statuses or "delete_declined" in statuses:
        return "already_on_device"
    if "pending_delete" in statuses:
        return "removal_pending"
    if "pending_send" in statuses:
        return "already_queued"
    return None


def _resolve_send_format(library, calibre_book_id, fmt):
    """
    Il formato da mandare: quello chiesto, o il primo che il libro ha.

    v1 ammetteva la richiesta senza formato, e DeviceBook.format e' NOT
    NULL: da li' il ripiego sul primo formato disponibile. None vuol dire
    che il libro non ha proprio formati, e cosa farne lo decide chi chiama:
    errore secco nell'invio singolo, riga saltata in quello multiplo.
    (21/11/2026: estratto dalla rotta singola per servire anche il multiplo.)
    """
    if fmt:
        return fmt
    lib = CalibreLibrary(config.library_path(library))
    formats = lib.get_formats(calibre_book_id)
    return formats[0]["format"] if formats else None


def _upsert_pending_send(db, device_id, library, calibre_book_id, fmt):
    """
    Scrive lo stato desiderato «da mandare» per (libro, formato).

    Se la riga esiste — e il blocco qui sopra e' gia' passato, quindi puo'
    essere solo `send_failed` o `removed_by_device` — la si rimette in coda
    pulendo l'errore e la data di rimozione; altrimenti nasce adesso.
    (21/11/2026: estratto dalla rotta singola per servire anche il multiplo.)
    """
    row = db.query(models.DeviceBook).filter(
        models.DeviceBook.device_id == device_id,
        models.DeviceBook.library == library,
        models.DeviceBook.calibre_book_id == calibre_book_id,
        models.DeviceBook.format == fmt,
    ).first()
    if row:
        row.status = "pending_send"
        row.requested_by = "server"
        row.last_error = None
        row.removed_at = None
    else:
        db.add(models.DeviceBook(
            device_id=device_id, library=library, calibre_book_id=calibre_book_id,
            format=fmt, status="pending_send", requested_by="server",
        ))


@router.post(
    "/{device_id}/queue",
    responses={200: {"model": Esito}},
)
def queue_book_for_device(
    device_id: int,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Web-UI action ("Invia a dispositivo" / "Rimuovi da dispositivo"): queues a
    download or delete for a device's next sync handshake. Body (unchanged
    from v1): {calibre_book_id, library, action: "queued_download"|
    "queued_delete", format}. Since protocol v2 this writes the DeviceBook
    desired state directly — SyncQueue is no longer written to (the table
    survives one release for the v1 shim's sake only).
    """
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")

    action = payload.get("action")
    if action not in ("queued_download", "queued_delete"):
        raise HTTPException(status_code=400, detail="action must be 'queued_download' or 'queued_delete'")
    calibre_book_id = payload.get("calibre_book_id")
    library = payload.get("library") or resolve_default_library_folder(db)
    if not library:
        raise HTTPException(status_code=404, detail="No library is configured. Create one first.")
    if not calibre_book_id:
        raise HTTPException(status_code=400, detail="calibre_book_id is required")
    fmt = (payload.get("format") or "").upper() or None

    if action == "queued_download":
        # Il blocco dell'invio (21/11/2026, regola di Paolo): un libro che
        # risulta gia' sul dispositivo — o gia' in coda per arrivarci — si
        # rifiuta, col motivo. Il blocco sta QUI e non solo nel browser,
        # perche' solo il server vede lo stato vero delle righe.
        reason = _send_block_reason(db, device_id, library, calibre_book_id)
        if reason:
            raise HTTPException(status_code=409, detail=_SEND_BLOCK_DETAILS[reason])
        fmt = _resolve_send_format(library, calibre_book_id, fmt)
        if not fmt:
            raise HTTPException(status_code=404, detail="The book has no formats available to send")
        _upsert_pending_send(db, device_id, library, calibre_book_id, fmt)
    else:  # queued_delete
        query = db.query(models.DeviceBook).filter(
            models.DeviceBook.device_id == device_id,
            models.DeviceBook.library == library,
            models.DeviceBook.calibre_book_id == calibre_book_id,
        )
        if fmt:
            query = query.filter(models.DeviceBook.format == fmt)
        rows = query.all()
        if not rows:
            raise HTTPException(
                status_code=404,
                detail="The book is not on this device: there is nothing to remove",
            )
        for row in rows:
            if row.status in _SENDABLE_STATUSES:
                # Never delivered — deleting is just cancelling the send.
                db.delete(row)
            else:
                row.status = "pending_delete"
                row.requested_by = "server"
                row.last_error = None
    db.commit()
    log_message("info", "devices", f"Queued {action} for book {calibre_book_id} on device '{dev.name}'")
    return {"status": "ok"}


@router.post(
    "/{device_id}/queue/bulk",
    responses={200: {"model": InviiAccodati}},
)
def queue_books_for_device(
    device_id: int,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    L'invio multiplo (21/11/2026, regola di Paolo): «se seleziono un libro
    sul dispositivo e uno no, partono SOLO quelli che mancano».

    Prima questa rotta non c'era: il browser faceva N chiamate a /queue, e
    un libro gia' a bordo tornava in coda come se niente fosse (la clessidra
    che Paolo ha visto). Qui il giro e' UNO, e la risposta dice libro per
    libro cosa e' partito (`queued`) e cosa no e perche' (`skipped`, con un
    codice motivo): saltare in silenzio sarebbe l'altro modo di mentire.

    Corpo: {library, action: "queued_download", books: [{calibre_book_id,
    format?}]}. Solo l'invio: le rimozioni in blocco restano sulle chiamate
    per riga di /queue, dove la riga c'e' per forza. Un libro saltato non
    e' un errore della richiesta — la selezione mista e' il caso normale —
    quindi si risponde 200 anche quando non parte niente.
    """
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")

    if payload.get("action") != "queued_download":
        raise HTTPException(status_code=400, detail="action must be 'queued_download'")
    library = payload.get("library") or resolve_default_library_folder(db)
    if not library:
        raise HTTPException(status_code=404, detail="No library is configured. Create one first.")
    books = payload.get("books")
    if not isinstance(books, list) or not books:
        raise HTTPException(status_code=400, detail="books must be a list with at least one entry")

    queued, skipped = [], []
    #: I libri gia' accodati DENTRO questa richiesta: la sessione ha
    #: autoflush=False, quindi _send_block_reason non vede le righe appena
    #: aggiunte e lo stesso libro chiesto due volte passerebbe due volte —
    #: fino all'IntegrityError sul vincolo unico. Il doppione si ferma qui,
    #: col suo stesso motivo: per chi chiama E' gia' in coda. (21/11/2026)
    queued_in_request = set()
    for entry in books:
        book_id = entry.get("calibre_book_id") if isinstance(entry, dict) else None
        if not book_id:
            raise HTTPException(status_code=400, detail="calibre_book_id is required for every book")
        if book_id in queued_in_request:
            skipped.append({"calibre_book_id": book_id, "reason": "already_queued"})
            continue
        reason = _send_block_reason(db, device_id, library, book_id)
        if reason:
            skipped.append({"calibre_book_id": book_id, "reason": reason})
            continue
        fmt = _resolve_send_format(library, book_id, (entry.get("format") or "").upper() or None)
        if not fmt:
            skipped.append({"calibre_book_id": book_id, "reason": "no_format"})
            continue
        _upsert_pending_send(db, device_id, library, book_id, fmt)
        queued.append({"calibre_book_id": book_id, "format": fmt})
        queued_in_request.add(book_id)
    db.commit()
    log_message("info", "devices",
                f"Bulk queue for device '{dev.name}': {len(queued)} queued, {len(skipped)} skipped")
    return {"status": "ok", "queued": queued, "skipped": skipped}


@router.delete(
    "/{device_id}/vocabulary",
    responses={200: {"model": VocabolarioDimenticato}},
)
def forget_device_vocabulary(
    device_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Dimentica il vocabolario di UN dispositivo, tenendo tutto il resto.

    Serve quando le parole di quel dispositivo sono una COPIA di quelle di un
    altro, non parole sue: e' il caso di due lettori fra cui e' stato
    sincronizzato il database di KOReader.

    Come per le statistiche del Boox, si cancella anche il backup conservato
    di vocabulary_builder.sqlite3: senza, il ciclo che rilegge i backup
    rimetterebbe dentro tutto entro il giro successivo, e la pulizia
    sembrerebbe riuscita per poi disfarsi da sola.

    Il dispositivo resta registrato, con i suoi libri, le sue annotazioni e
    le sue impostazioni: cancellare il vocabolario non e' cancellare il
    lettore.
    """
    mio = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not mio:
        raise HTTPException(status_code=404, detail="Device not found")

    tolte = db.query(models.VocabularyEntry).filter(
        models.VocabularyEntry.device_id == device_id
    ).delete(synchronize_session=False)
    db.commit()

    percorso = os.path.join(config.BACKUPS_DIR, str(device_id), "vocabulary_builder.sqlite3")
    snapshot_tolto = False
    if os.path.exists(percorso):
        try:
            os.remove(percorso)
            snapshot_tolto = True
        except OSError as exc:
            log_message("warning", "devices",
                        f"Vocabulary forgotten but the snapshot remains: {exc}")
    log_message("warning", "devices",
                f"Forgotten {tolte} vocabulary words of '{mio.name}' (snapshot removed: {snapshot_tolto})")
    return {"status": "ok", "parole_tolte": tolte, "snapshot_rimosso": snapshot_tolto}


@router.get(
    "/{device_id}/sync-history",
    responses={200: {"model": list[SincronizzazioneNelloStorico]}},
)
def get_device_sync_history(
    device_id: int,
    limit: int = 30,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Web-GUI view of the device's recent v2 sync sessions, newest first."""
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    rows = (
        db.query(models.DeviceSyncHistory)
        .filter(models.DeviceSyncHistory.device_id == device_id)
        .order_by(models.DeviceSyncHistory.started_at.desc(), models.DeviceSyncHistory.id.desc())
        .limit(max(1, min(limit, _SYNC_HISTORY_KEEP)))
        .all()
    )
    return [
        {
            "id": h.id,
            "session_id": h.session_id,
            "started_at": quando(h.started_at),
            "finished_at": quando(h.finished_at),
            "outcome": h.outcome,
            "plugin_version": h.plugin_version,
            "trigger": h.trigger,
            "books_reported": h.books_reported,
            "downloads_requested": h.downloads_requested,
            "downloads_ok": h.downloads_ok,
            "downloads_failed": h.downloads_failed,
            "deletes_requested": h.deletes_requested,
            "deletes_done": h.deletes_done,
            "deletes_declined": h.deletes_declined,
            "removed_by_device": h.removed_by_device,
            "pages_reported": h.pages_reported,
            "detail_json": h.detail_json,
        }
        for h in rows
    ]


def _get_owned_device_book(db: Session, device_id: int, book_row_id: int, current_user: models.User) -> models.DeviceBook:
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    row = db.query(models.DeviceBook).filter(
        models.DeviceBook.id == book_row_id, models.DeviceBook.device_id == device_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Book not found on this device")
    return row


@router.post(
    "/{device_id}/books/{book_row_id}/acknowledge-removal",
    responses={200: {"model": Esito}},
)
def acknowledge_book_removal(
    device_id: int,
    book_row_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Web-GUI archives a 'removed_by_device' notification: the user has seen
    that the device dropped the book, so the row can finally go away."""
    row = _get_owned_device_book(db, device_id, book_row_id, current_user)
    if row.status != "removed_by_device":
        raise HTTPException(status_code=400, detail="The book is not in the 'removed_by_device' state")
    db.delete(row)
    db.commit()
    return {"status": "ok"}


@router.post(
    "/{device_id}/books/{book_row_id}/cancel",
    responses={200: {"model": Esito}},
)
def cancel_pending_book_action(
    device_id: int,
    book_row_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Web-GUI undo for a queued action the device hasn't applied yet:
    a pending send disappears entirely, a pending delete goes back to synced.
    delete_declined counts too — "the user on the device said no" is still a
    removal request the owner may want to withdraw, settling the book back
    to plain synced instead of leaving the declined flag around forever."""
    row = _get_owned_device_book(db, device_id, book_row_id, current_user)
    if row.status in _SENDABLE_STATUSES:
        db.delete(row)
    elif row.status in ("pending_delete", "delete_declined"):
        row.status = "synced"
        row.last_error = None
    else:
        raise HTTPException(status_code=400, detail=f"Nothing to undo: the book is in state '{row.status}'")
    db.commit()
    return {"status": "ok"}


@router.post(
    "/{device_id}/books/{book_row_id}/pair",
    responses={200: {"model": OrfaneMigrate}},
)
def pair_device_book(
    device_id: int,
    book_row_id: int,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    "Accoppia manualmente" from the main device-books view — unlike
    queue_flagged_book_action's 'pair' (which links a file that was NEVER
    matched to a book), this row is already matched to SOME book; the whole
    point here is to RE-point it to a different one the user picked (e.g.
    a hash that resolved to the wrong edition). Available regardless of the
    row's current status, by design — no guard on pending_send/pending_delete.
    """
    row = _get_owned_device_book(db, device_id, book_row_id, current_user)
    new_library = payload.get("library")
    new_calibre_book_id = payload.get("calibre_book_id")
    if not new_library or not new_calibre_book_id:
        raise HTTPException(status_code=400, detail="library and calibre_book_id are required")
    new_format = payload.get("format") or row.format
    old_library, old_calibre_book_id = row.library, row.calibre_book_id

    if row.delivery_hash:
        book_hash_service.record_device_hash(db, new_library, new_calibre_book_id, new_format, row.delivery_hash)

    migrated = _migrate_device_highlights_to_new_book(
        db, current_user, device_id, old_library, old_calibre_book_id, new_library, new_calibre_book_id
    )

    existing = db.query(models.DeviceBook).filter(
        models.DeviceBook.device_id == device_id,
        models.DeviceBook.library == new_library,
        models.DeviceBook.calibre_book_id == new_calibre_book_id,
        models.DeviceBook.format == new_format,
    ).first()
    if existing and existing.id != row.id:
        db.delete(row)
    else:
        row.library = new_library
        row.calibre_book_id = new_calibre_book_id
        row.format = new_format

    db.commit()
    return {"status": "ok", "migrated_highlights": migrated}
