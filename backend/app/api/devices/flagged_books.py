"""
I libri del dispositivo da riconoscere: segnalazioni e accoppiamento.

Il mestiere: un file che sta sul lettore ma che il server non sa legare a
un libro della biblioteca. Il dispositivo lo segnala, il server tenta di
riconoscerlo (per hash, per contenuto, per titolo), e quello che resta
irrisolto finisce "Da rivedere" nella webapp, dove l'utente decide.
(Trasloco del 20/11/2026: prima era tutto in api/devices.py.)

Le rotte del plugin (token di dispositivo, su sync_router):
* POST /api/kolibre/devices/scan-unmatched — "Inizializza libreria": la
  scansione completa dei file non ancora gestiti, che riconcilia anche le
  vecchie segnalazioni rimaste orfane di un rescan;
* POST .../flagged-books — la segnalazione di un singolo file irrisolto;
* POST .../identify-file — l'identificazione per CONTENUTO: il plugin non
  sa aprire uno zip/EPUB, quindi manda il file e lo apre il server.

Le rotte della webapp (JWT, su router):
* GET  /api/devices/{id}/flagged-books — l'elenco "Da rivedere";
* DELETE .../flagged-books/{fid} — la voce si archivia;
* POST .../flagged-books/{fid}/action e .../flagged-books/bulk-action —
  la decisione dell'utente (accoppia a questo libro, importa, ignora).

Regola trasversale: quando un file finalmente si accoppia, le
evidenziazioni rimaste orfane su quel percorso migrano al libro vero
(`_migrate_orphan_highlights`, in _shared): nessuna nota va persa solo
perche' il riconoscimento e' arrivato dopo la lettura.
"""

import os
import tempfile

from typing import Optional, Union
from datetime import datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ... import config, models, database, auth, schemas
from ...calibre.write_queue import CalibreWriteQueue
from ...deps import get_write_queue
from ...services import ingest_folders, koreader_hash, permessi
from ...services.library_scanner import EBOOK_EXTENSIONS
from ...services.watcher import stage_ingest_file
from ...istanti import quando

from ...logging_utils import log_message
from ...calibre.library import CalibreLibrary
from ...services import book_hash_service, text_fingerprint
from ...schemas_risposte import (
    AzioneAccodata, AzioniAccodate, Esito, FileIdentificato, LibroMandatoDalDispositivo,
    FileNonIdentificato, LibroDaRivedere, LibroSegnalato, OrfaneMigrate,
    ScansioneDeiNonAccoppiati, SegnalazioneAccoppiataDaSola,
)

from ._shared import (
    router, sync_router,
    _migrate_orphan_highlights,
)


@sync_router.post(
    "/scan-unmatched",
    responses={200: {"model": ScansioneDeiNonAccoppiati}},
)
def scan_unmatched_books(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    "Inizializza libreria" (cerca libri non accoppiati) — a device-initiated,
    on-demand reconciliation pass, separate from the routine /sync handshake
    on purpose: unlike managed_books adoption (silent, always-on), here the
    plugin wants to know exactly which hashes DIDN'T resolve, so it can offer
    the user a fuzzy title/author mapping for those specifically. Body:
    {items: [{hash, format, path}]}. Returns matched (candidates identified
    per hash, ready to adopt into the manifest exactly like a routine
    managed_books report — a list rather than a single pick, since the exact
    same file can legitimately be hashed under more than one library, and
    the plugin must let the user choose rather than guessing) and unmatched
    (untouched, for client-side fuzzy matching against /catalog).

    Also reconciles "Da rivedere" against this fresh full-library scan
    (root-cause fix, 2026-09-12): report_flagged_book only ever
    adds/refreshes a row for a file still unresolved on some past scan —
    nothing ever told the server "this file is fine now, drop it", so a
    later rescan that finally resolves a book (or a file removed from the
    device entirely) left its old flagged row behind forever, confirmed
    against production data (81 of 151 rows for one device predated its
    latest rescan by weeks). `items` here IS always the device's full,
    not-yet-managed local library (see _runLibraryInit: `candidates` comes
    from walking the whole books_dir, never a partial/incremental set), so
    any existing DeviceFlaggedBook row for this device whose local_path
    isn't in THIS payload is provably stale — deleted here, before this
    scan gets the chance to re-flag whatever's genuinely still unresolved.
    Rows with a pending_action (delete/overwrite queued from the web UI,
    not yet applied by the device) are left alone on purpose — that is a
    separate, still-pending decision, not something a rescan should ever
    silently discard.
    """
    items = payload.get("items", [])
    scanned_paths = {item.get("path") for item in items if item.get("path")}
    if scanned_paths:
        stale = db.query(models.DeviceFlaggedBook).filter(
            models.DeviceFlaggedBook.device_id == current_device.id,
            models.DeviceFlaggedBook.pending_action.is_(None),
            models.DeviceFlaggedBook.local_path.notin_(scanned_paths),
        ).all()
        for row in stale:
            db.delete(row)
        if stale:
            db.commit()

    matched, unmatched = [], []
    for item in items:
        file_hash = item.get("hash")
        if not file_hash:
            continue
        # **Qui l'impronta non e' un ripiego: e' l'unico strumento possibile.**
        # Questi sono i file che stanno sul dispositivo e che Kolibre non ha
        # consegnato — nessuna identita' condivisa esiste, per definizione, e
        # confrontare i contenuti e' l'unico modo di capire se quel file e' un
        # libro che in biblioteca c'e' gia'. E' il motivo per cui il confronto
        # per impronta resta, dopo che tutto il resto e' passato all'identita'
        # (vedi book_hash_service.resolve_from_item).
        hits = book_hash_service.resolve_book_matches(db, file_hash, device_id=current_device.id)
        if not hits:
            unmatched.append(item)
            continue
        candidates = []
        for hit in hits:
            lib = CalibreLibrary(config.library_path(hit.library))
            book = lib.get_book(hit.calibre_book_id)
            candidates.append({
                "library": hit.library,
                "calibre_book_id": hit.calibre_book_id,
                "title": book.get("title") if book else None,
                "author": lib.get_book_author(hit.calibre_book_id),
            })
        matched.append({
            "hash": file_hash,
            "path": item.get("path"),
            "format": item.get("format") or hits[0].format,
            "candidates": candidates,
        })
    return {"matched": matched, "unmatched": unmatched}


@sync_router.post(
    "/flagged-books",
    responses={200: {"model": Union[LibroSegnalato, SegnalazioneAccoppiataDaSola]}},
)
def report_flagged_book(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Parks a local book the device-init scan couldn't safely resolve on its
    own — either a *probable* (not hash-identical) match whose local file
    already has reading progress or annotations (match_status
    'flagged_started', with candidate_* filled in), or no plausible match at
    all (match_status 'no_candidate', candidate_* left null) — the plugin
    never touches that file's content on its own (see main.lua's device-init
    flow), it only records it here so the user can review/resolve it later from
    the web UI. Body: {local_path, local_title, match_status,
    local_percent_read, local_highlights_count, candidate_library,
    candidate_calibre_book_id, candidate_title, candidate_author, hash}.
    `hash` (the device's own partial-MD5 for this file, already computed for
    the scan-unmatched round-trip that led here) is needed by the 'pair'
    action later — see queue_flagged_book_action/book_hash_service.

    `match_source` ("fingerprint" from _identifyFileByContent, or "fuzzy"
    from the title/author guess) distinguishes an authoritative content
    identity from a plausible guess. A fingerprint match on a file that
    already has progress/highlights (match_status 'flagged_started') is
    resolved immediately here via the exact same safe logic as the manual
    'pair' action (queue_flagged_book_action) — record the device's hash,
    migrate any orphan highlights, and never park it in "Da rivedere" at
    all. This is what "il candidato è certo, accoppialo anche se il libro è
    già iniziato" needs: pairing never touches the device's file/sidecar, so
    there is no data-loss risk in doing this automatically for a fingerprint
    match, unlike a fuzzy guess which still always needs human review.
    """
    library = payload.get("candidate_library")
    calibre_book_id = payload.get("candidate_calibre_book_id")
    if (
        payload.get("match_status") == "flagged_started"
        and payload.get("match_source") == "fingerprint"
        and library and calibre_book_id
    ):
        file_hash = payload.get("hash")
        format = payload.get("format") or "EPUB"
        if file_hash:
            book_hash_service.record_device_hash(db, library, calibre_book_id, format, file_hash)
        migrated = _migrate_orphan_highlights(
            db, current_device.id, payload.get("local_path") or "", library, calibre_book_id
        )
        db.commit()
        log_message(
            "info", "devices",
            f"Automatic pairing by content identity: '{payload.get('local_title')}' -> "
            f"{library}/{calibre_book_id} ({migrated} orphan highlights migrated).",
        )
        return {"status": "ok", "auto_paired": True, "migrated_highlights": migrated}

    local_path = payload.get("local_path") or ""
    # Upsert on (device_id, local_path): the device-init scan ("Inizializza
    # libreria") re-reports every still-unmanaged file on EVERY run, not just
    # new ones (nothing marks a flagged-but-never-paired file as "already
    # reported" on the device side). Without this, re-scanning after a
    # plugin update (e.g. one that now sends local_author) used to insert a
    # second, duplicate row instead of refreshing the existing one — the old
    # row (with stale/missing fields) stayed forever, and both showed up in
    # "Libri non accoppiati". `pending_action*` is deliberately left alone on
    # update: it's a separate, still-pending decision from the web UI
    # (delete/overwrite queued for the device's next sync), not something a
    # re-scan should ever touch or lose.
    existing = db.query(models.DeviceFlaggedBook).filter(
        models.DeviceFlaggedBook.device_id == current_device.id,
        models.DeviceFlaggedBook.local_path == local_path,
    ).first()
    row = existing or models.DeviceFlaggedBook(device_id=current_device.id, local_path=local_path)
    row.local_title = payload.get("local_title")
    # Opzionale: un plugin KOReader precedente a questo campo semplicemente
    # non lo manda, .get(...) risolve a None senza errori.
    row.local_author = payload.get("local_author")
    row.match_status = payload.get("match_status") or "flagged_started"
    row.local_percent_read = payload.get("local_percent_read")
    row.local_highlights_count = payload.get("local_highlights_count")
    row.candidate_library = payload.get("candidate_library")
    row.candidate_calibre_book_id = payload.get("candidate_calibre_book_id")
    row.candidate_title = payload.get("candidate_title")
    row.candidate_author = payload.get("candidate_author")
    row.file_hash = payload.get("hash")
    if existing:
        row.flagged_at = datetime.utcnow()
    else:
        db.add(row)
    db.commit()
    return {"status": "ok", "id": row.id}


def _nome_dal_lettore(filename: str) -> str:
    """
    Il nome di un file mandato dal lettore, o un 400.

    Il nome e' quello del libro sul lettore, spazi e accenti compresi. Il
    controllo dei backup (`_SAFE_BACKUP_FILENAME`, solo lettere, cifre e
    `_.-`) qui rifiutava quasi ogni titolo vero: fino al 24/11/2026
    `/identify-file` rispondeva «Invalid file name» a ogni file con uno
    spazio nel nome, e il riaccoppiamento delle note orfane per contenuto
    falliva in silenzio. Si guarda solo quello che e' pericoloso: un
    percorso invece di un nome, un file nascosto, un nome vuoto o troppo
    lungo.
    """
    nome = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if (not nome or nome != filename or nome.startswith(".") or "\x00" in nome
            or len(nome.encode("utf-8")) > 255):
        raise HTTPException(status_code=400, detail="Invalid file name")
    return nome


@sync_router.post(
    "/identify-file",
    responses={200: {"model": Union[FileIdentificato, FileNonIdentificato]}},
)
async def identify_device_file(
    request: Request,
    filename: str,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Content-level identity for a device file the plugin couldn't otherwise
    place — see text_fingerprint.py's own docstring for why: the filename
    guess (_guessTitleFromPath/_guessAuthorFromPath, used by
    _findProbableCatalogMatches's fuzzy search) is fragile to naming
    conventions (Calibre title_sort, folder layout, ...), and the byte hash
    (BookHash.file_hash) only matches a file byte-identical to the server's
    own copy. KOReader's Lua environment has no way to read inside a
    zip/EPUB itself (confirmed: no zip library exists in this plugin or
    anywhere reusable in it), so the device uploads the raw file here —
    same raw-body convention as upload_device_backup — and the SERVER (which
    already has zip/OPF-parsing code for the TOC editor and page counter)
    computes the fingerprint and looks it up.

    Searches BookHash across every library (mirrors _findProbableCatalogMatches'
    own "search every library the device can see" behavior), not just one —
    the device doesn't know in advance which library the match is in.
    """
    filename = _nome_dal_lettore(filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in text_fingerprint.SUPPORTED_FINGERPRINT_FORMATS:
        return {"matched": False, "reason": "unsupported_format"}

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(body)
            tmp_path = tmp.name

        fingerprint = text_fingerprint.compute_fingerprint(tmp_path, ext)
        if not fingerprint:
            return {"matched": False, "reason": "extraction_failed"}

        match = db.query(models.BookHash).filter(models.BookHash.content_fingerprint == fingerprint).first()
        if not match:
            return {"matched": False, "reason": "no_match"}

        lib = CalibreLibrary(config.library_path(match.library))
        book = lib.get_book(match.calibre_book_id)
        if not book:
            return {"matched": False, "reason": "no_match"}

        return {
            "matched": True,
            "id": match.calibre_book_id,
            "library": match.library,
            "calibre_book_id": match.calibre_book_id,
            "title": book.get("title"),
            "author": lib.get_book_author(match.calibre_book_id),
            "formats": [f["format"] for f in lib.get_formats(match.calibre_book_id)],
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


@router.get(
    "/{device_id}/flagged-books",
    responses={200: {"model": list[LibroDaRivedere]}},
)
def list_flagged_books(
    device_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Web-GUI review list for the plugin's device-init scan: local books
    fuzzy-matched to a server book but left untouched because they already
    have reading progress or annotations (see /sync-router's
    /flagged-books POST)."""
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    rows = (
        db.query(models.DeviceFlaggedBook)
        .filter(models.DeviceFlaggedBook.device_id == device_id)
        .order_by(models.DeviceFlaggedBook.flagged_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "local_path": r.local_path,
            "local_title": r.local_title,
            "local_author": r.local_author,
            "match_status": r.match_status,
            "local_percent_read": r.local_percent_read,
            "local_highlights_count": r.local_highlights_count,
            "candidate_library": r.candidate_library,
            "candidate_calibre_book_id": r.candidate_calibre_book_id,
            "candidate_title": r.candidate_title,
            "candidate_author": r.candidate_author,
            "flagged_at": quando(r.flagged_at),
            "pending_action": r.pending_action,
        }
        for r in rows
    ]


def _get_owned_flagged_book(db: Session, device_id: int, flagged_id: int, current_user: models.User) -> models.DeviceFlaggedBook:
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    row = db.query(models.DeviceFlaggedBook).filter(
        models.DeviceFlaggedBook.id == flagged_id, models.DeviceFlaggedBook.device_id == device_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")
    return row


@router.delete(
    "/{device_id}/flagged-books/{flagged_id}",
    responses={200: {"model": Esito}},
)
def delete_flagged_book(
    device_id: int,
    flagged_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """"Rimuovi dall'elenco": drops the row without touching the device at
    all — distinct from the /action endpoint below, which queues a real
    on-device change applied by the plugin on its next sync."""
    row = _get_owned_flagged_book(db, device_id, flagged_id, current_user)
    db.delete(row)
    db.commit()
    return {"status": "ok"}


@router.post(
    "/{device_id}/flagged-books/{flagged_id}/action",
    responses={200: {"model": Union[AzioneAccodata, OrfaneMigrate]}},
)
def queue_flagged_book_action(
    device_id: int,
    flagged_id: int,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    'delete' (remove the local file) and 'overwrite' (delete it, then
    download the given book in its place) are queued for the device — it may
    be offline, so this only sets pending_action_* here; the plugin picks it
    up as `file_actions` in its next sync handshake and acks it once applied
    (see sync_router's /sync and /sync/file-actions/ack), at which point this
    row is deleted.

    'pair' is different: it touches no file on the device at all, so it's
    applied immediately, synchronously, right here — record the device's own
    reported hash for this file against the chosen book (so future pushes
    for it resolve normally even if the bytes never match the server's own
    copy — see book_hash_service.record_device_hash), migrate any
    OrphanHighlight rows already imported for this local file onto the real
    book, and remove this review-list row.
    """
    action = payload.get("action")
    if action not in ("delete", "overwrite", "pair"):
        raise HTTPException(status_code=400, detail="action must be 'delete', 'overwrite' or 'pair'")
    row = _get_owned_flagged_book(db, device_id, flagged_id, current_user)
    if action == "overwrite":
        library = payload.get("library")
        calibre_book_id = payload.get("calibre_book_id")
        if not library or not calibre_book_id:
            raise HTTPException(status_code=400, detail="library and calibre_book_id are required for 'overwrite'")
        row.pending_action_library = library
        row.pending_action_calibre_book_id = calibre_book_id
        row.pending_action_format = payload.get("format")
        row.pending_action = action
        db.commit()
        return {"status": "ok", "pending_action": row.pending_action}
    if action == "pair":
        library = payload.get("library")
        calibre_book_id = payload.get("calibre_book_id")
        if not library or not calibre_book_id:
            raise HTTPException(status_code=400, detail="library and calibre_book_id are required for 'pair'")
        format = payload.get("format") or "EPUB"
        if row.file_hash:
            book_hash_service.record_device_hash(db, library, calibre_book_id, format, row.file_hash)
        migrated = _migrate_orphan_highlights(db, row.device_id, row.local_path, library, calibre_book_id)
        db.delete(row)
        db.commit()
        return {"status": "ok", "migrated_highlights": migrated}
    row.pending_action = action
    db.commit()
    return {"status": "ok", "pending_action": row.pending_action}


@router.post(
    "/{device_id}/flagged-books/bulk-action",
    responses={200: {"model": AzioniAccodate}},
)
def bulk_queue_flagged_book_action(
    device_id: int,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Bulk counterpart of the single-row /action endpoint — 'delete' only:
    each row has its own candidate (if any), so a bulk 'overwrite' with one
    shared target book wouldn't make sense."""
    if payload.get("action") != "delete":
        raise HTTPException(status_code=400, detail="Only the 'delete' action is supported in bulk")
    ids = payload.get("ids") or []
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    updated = (
        db.query(models.DeviceFlaggedBook)
        .filter(models.DeviceFlaggedBook.device_id == device_id, models.DeviceFlaggedBook.id.in_(ids))
        .update({"pending_action": "delete"}, synchronize_session=False)
    )
    db.commit()
    return {"status": "ok", "updated": updated}


@sync_router.post(
    "/books/upload",
    responses={200: {"model": LibroMandatoDalDispositivo}},
)
async def upload_unpaired_device_book(
    request: Request,
    filename: str,
    library: Optional[str] = None,
    path: Optional[str] = None,
    db: Session = Depends(database.get_db),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    «Manda al server questo file esatto»: la seconda meta' di «Initialize
    library» (piano 1.0.0, approvato da Paolo il 24/11/2026).

    **Da zero.** Sul lettore ci sono libri che nessuna impronta riconosce:
    copiati a mano prima di Kolibre, o arrivati da un altro programma. Fino
    alla 0.33.0 il plugin li cercava nel catalogo per titolo e autore e, se
    trovava qualcosa di simile, proponeva di SOVRASCRIVERE il file del lettore
    con quello del server. Paolo: «il server deve essere la parte di smanetto,
    non il device». Adesso il file del lettore e' quello buono: viene qui tale
    e quale, entra in biblioteca come un libro nuovo, e da questo momento e'
    accoppiato al lettore. I quasi doppioni che ne nascono sono un problema
    del server, da trattare dopo.

    **Lo stesso giro dell'ingest**, non uno parallelo: il file si salva nella
    cartella di ingest di chi possiede il lettore, `stage_ingest_file` ne
    legge i metadati, e `import_book_from_ingest` lo porta in biblioteca —
    copertina, pagine, qualita', impronta. Il file arriva in biblioteca
    **identico byte per byte** (`shutil.copy2`, e dal 24/11 il server non
    riscrive piu' gli EPUB), quindi l'impronta che il server registra e'
    quella che il lettore ha in mano.

    **Mai due volte lo stesso file.** Se l'impronta e' gia' in una
    biblioteca visibile (un secondo giro dello stesso comando, o il file
    accoppiato nel frattempo), non si importa niente: si accoppia quello
    che c'e' e si dice `gia_presente`.

    `library` e' la cartella della biblioteca (quella di `/libraries`), e ci
    vuole il permesso di modificarla. Se manca, va bene solo quando chi
    possiede il lettore ne puo' modificare una sola.
    """
    from ..ingest import (
        MAX_UPLOAD_SIZE_BYTES, _open_ingest_destination, import_book_from_ingest,
    )
    from .sync import report_book_delivered

    nome = _nome_dal_lettore(filename)
    ext = os.path.splitext(nome)[1].lower()
    if ext not in EBOOK_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Format '{ext or '(none)'}' is not accepted")

    proprietario = db.query(models.User).filter(models.User.id == current_device.user_id).first()
    if not proprietario:
        raise HTTPException(status_code=403, detail="This device has no owner")
    modificabili = [b for b in permessi.biblioteche_visibili(db, proprietario)
                    if permessi.puo_modificare(db, proprietario, b)]
    if library:
        scelta = next((b for b in modificabili if b.folder_name == library), None)
        if scelta is None:
            raise HTTPException(status_code=403, detail="You cannot add books to this library")
    elif len(modificabili) == 1:
        scelta = modificabili[0]
    else:
        raise HTTPException(status_code=400, detail="Choose the library to add the book to")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body")
    if len(body) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File is too large")

    # L'impronta, prima di tutto: se il file c'e' gia', non si importa.
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(body)
        tmp_path = tmp.name
    try:
        impronta = koreader_hash.partial_md5(tmp_path)
    finally:
        os.remove(tmp_path)
    visibili = {b.folder_name for b in permessi.biblioteche_visibili(db, proprietario)}
    gia = [m for m in book_hash_service.resolve_book_matches(db, impronta) if m.library in visibili] \
        if impronta else []

    if gia:
        m = gia[0]
        libreria, book_id, fmt = m.library, m.calibre_book_id, (m.format or ext.lstrip(".")).upper()
        gia_presente = True
    else:
        os.makedirs(config.INGEST_DIR, exist_ok=True)
        cartella = ingest_folders.ensure_user_folder(proprietario.id, proprietario.username)
        out_handle, dest_path = _open_ingest_destination(cartella, os.path.basename(filename))
        with out_handle:
            out_handle.write(body)
        stage_ingest_file(db, dest_path)
        item = db.query(models.IngestedBook).filter(
            models.IngestedBook.file_path == os.path.abspath(dest_path)).first()
        if item is None:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            raise HTTPException(status_code=500, detail="The file could not be staged")
        esito = await import_book_from_ingest(
            schemas.IngestImportRequest(id=item.id, library=scelta.folder_name),
            db=db, write_queue=write_queue, current_user=proprietario)
        libreria, book_id, fmt = scelta.folder_name, esito["book_id"], ext.lstrip(".").upper()
        gia_presente = False

    report_book_delivered(
        {"calibre_book_id": book_id, "library": libreria, "format": fmt,
         "path": path, "hash": impronta},
        db=db, current_device=current_device)

    lib = CalibreLibrary(config.library_path(libreria))
    libro = lib.get_book(book_id) or {}
    log_message("info", "devices",
                f"Device '{current_device.name}' sent an unpaired file: book {book_id} in "
                f"'{libreria}'" + (" (already there)" if gia_presente else " (imported)"))
    return {
        "status": "ok", "library": libreria, "calibre_book_id": book_id, "format": fmt,
        "title": libro.get("title"), "author": lib.get_book_author(book_id),
        "hash": impronta, "gia_presente": gia_presente,
    }
