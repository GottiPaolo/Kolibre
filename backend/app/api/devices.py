import difflib
import hashlib
import json
import os
import random
import re
import shutil
import tempfile
import unicodedata
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import config, models, schemas, database, auth
from starlette.background import BackgroundTask

from ..logging_utils import log_message
from ..calibre.library import CalibreLibrary
from ..services.position_converter.chapter_resolver import resolve_epub_chapter_path, resolve_pdf_chapter_path
from ..services import book_hash_service, permessi, stardict_service, stats_service, text_fingerprint, vocabulary_service
from .libraries import resolve_default_library_folder

router = APIRouter(prefix="/api/devices", tags=["devices"])

# KOReader-facing sync protocol, device-token authenticated,
# kept under its own prefix/router since it's a different auth scheme (permanent
# device bearer token) from the rest of /api/devices (human JWT).
sync_router = APIRouter(prefix="/api/kolibre/devices", tags=["koreader-sync"])

# Terzo router, stesso prefisso di `router` ma senza la dipendenza JWT che
# main.py applica a quest'ultimo: raccoglie gli endpoint sotto /api/devices
# che si autenticano con il TOKEN DI DISPOSITIVO invece che con il JWT
# dell'utente. Senza questa separazione avrebbero preteso entrambi, e il
# plugin KOReader (che il JWT non ce l'ha) si sarebbe visto rifiutare anche
# il semplice "prova connessione".
device_token_router = APIRouter(prefix="/api/devices", tags=["devices"])

_SAFE_BACKUP_FILENAME = re.compile(r"^[A-Za-z0-9_.-]+$")


@router.post("/register", response_model=schemas.DeviceResponse)
def register_device(
    payload: schemas.DeviceCreate,
    db: Session = Depends(database.get_db),
    # Registrare un dispositivo e' un permesso dell'account (28/09/2026).
    # Il dispositivo nasce legato a chi lo registra — sono uno a uno, e lo
    # erano gia' nel codice prima che i permessi esistessero.
    current_user: models.User = Depends(permessi.richiede_registrare_dispositivi),
):
    token = f"kolibre_tok_{os.urandom(8).hex()}"
    new_dev = models.Device(
        device_token=token,
        name=payload.name,
        model=payload.model,
        hardware_id=payload.hardware_id,
        user_id=current_user.id,
    )
    db.add(new_dev)
    db.commit()
    db.refresh(new_dev)
    log_message("info", "devices", f"Registered new device '{payload.name}' for user '{current_user.username}'")
    return new_dev


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


# --- Sync protocol v2 helpers (session-based handshake) ---

# DeviceBook rows in these statuses are offered to the device in sends[].
_SENDABLE_STATUSES = ("pending_send", "send_failed")
# Statuses a managed_books report must NOT flip back to 'synced': a device
# reporting "I still hold this file" is expected while a delete is pending or
# was declined — it must not silently cancel the desired removal.
_STICKY_STATUSES = ("pending_delete", "delete_declined")

_SYNC_SESSION_BLOCK_WINDOW = timedelta(minutes=10)   # a newer open session than this blocks a new handshake
_SYNC_SESSION_ABANDON_AFTER = timedelta(hours=1)     # open sessions older than this get lazily abandoned
_SYNC_HISTORY_KEEP = 100                             # max history rows per device


def _library_token(db: Session, device_id: int) -> str:
    """
    Cheap change-detection token: digests the
    device's desired-state table and the global hash table. If the token the
    client cached still matches, nothing relevant changed server-side and the
    client may skip re-reporting its whole managed_books list.
    """
    db_count, db_max = db.query(
        func.count(models.DeviceBook.id), func.max(models.DeviceBook.updated_at)
    ).filter(models.DeviceBook.device_id == device_id).one()
    bh_count, bh_max = db.query(
        func.count(models.BookHash.id), func.max(models.BookHash.computed_at)
    ).one()
    raw = f"{db_count}|{db_max}|{bh_count}|{bh_max}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _get_history_session(db: Session, device_id: int, session_id) -> models.DeviceSyncHistory:
    hist = db.query(models.DeviceSyncHistory).filter(
        models.DeviceSyncHistory.session_id == str(session_id or ""),
        models.DeviceSyncHistory.device_id == device_id,
    ).first()
    if not hist:
        raise HTTPException(status_code=404, detail="session_id sconosciuto per questo dispositivo")
    return hist


def _adopt_managed_books(db: Session, device: models.Device, managed: list) -> tuple:
    """
    Reconciles the device's own "I hold these files" report into DeviceBook.
    Only books whose KOReader hash resolves (book_hash_service's three tiers:
    live hash, archived hash, hash delivered to THIS device) are considered —
    Kolibre manages ONLY its own books, everything else on the device is
    invisible to it (§7 decision on 3.4). Returns (adopted, pages_reported).
    """
    now = datetime.utcnow()
    adopted, pages_reported = 0, 0
    for item in managed:
        file_hash = item.get("hash")
        if not file_hash:
            continue
        match = book_hash_service.resolve_first_book_match(db, file_hash, device_id=device.id)
        if not match:
            continue
        fmt = (item.get("format") or "").upper() or match.format
        row = db.query(models.DeviceBook).filter(
            models.DeviceBook.device_id == device.id,
            models.DeviceBook.library == match.library,
            models.DeviceBook.calibre_book_id == match.calibre_book_id,
            models.DeviceBook.format == fmt,
        ).first()
        if not row:
            row = models.DeviceBook(
                device_id=device.id, library=match.library,
                calibre_book_id=match.calibre_book_id, format=fmt,
                status="synced", requested_by="device", synced_at=now,
            )
            db.add(row)
        elif row.status not in _STICKY_STATUSES:
            # requested_by intentionally kept: adoption verifies presence, it
            # doesn't change who asked for the book in the first place.
            row.status = "synced"
            row.removed_at = None
        row.delivery_hash = file_hash
        if item.get("path"):
            row.device_path = item["path"]
        if item.get("pages") is not None:
            row.device_pages = item["pages"]
            row.device_pages_updated_at = now
            pages_reported += 1
        adopted += 1
    return adopted, pages_reported


@sync_router.post("/scan-unmatched")
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


@sync_router.post("/flagged-books")
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
            f"Accoppiamento automatico per identità di contenuto: '{payload.get('local_title')}' -> "
            f"{library}/{calibre_book_id} ({migrated} evidenziazioni orfane migrate).",
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


def _mark_missing_books(db: Session, device: models.Device, missing: list) -> int:
    """missing_books report: books the plugin used to manage but no longer
    finds on disk. The row survives as 'removed_by_device' until the web GUI
    archives it — never silently dropped, the user must see it happened."""
    now = datetime.utcnow()
    count = 0
    for item in missing:
        query = db.query(models.DeviceBook).filter(
            models.DeviceBook.device_id == device.id,
            models.DeviceBook.library == item.get("library"),
            models.DeviceBook.calibre_book_id == item.get("calibre_book_id"),
            # A pending_send/send_failed book was never delivered, so a
            # "missing" report about it is meaningless — don't flag those.
            models.DeviceBook.status.notin_(_SENDABLE_STATUSES),
        )
        fmt = (item.get("format") or "").upper()
        if fmt:
            query = query.filter(models.DeviceBook.format == fmt)
        for row in query.all():
            row.status = "removed_by_device"
            row.removed_at = now
            count += 1
    return count


def _build_sends(db: Session, device: models.Device) -> list:
    """sends[] for the handshake response: everything the server wants ON the
    device that isn't there yet. Stamps delivery_hash on each row now, so the
    device can later prove (by hash) it holds exactly the delivered file."""
    rows = db.query(models.DeviceBook).filter(
        models.DeviceBook.device_id == device.id,
        models.DeviceBook.status.in_(_SENDABLE_STATUSES),
    ).all()
    sends, libraries_cache = [], {}
    for row in rows:
        lib = libraries_cache.setdefault(row.library, CalibreLibrary(config.library_path(row.library)))
        book_row = lib.get_book(row.calibre_book_id)
        author = lib.get_book_author(row.calibre_book_id)
        folder_cover_url = None
        if author:
            author_meta = db.query(models.AuthorMetadata).filter(models.AuthorMetadata.author_name == author).first()
            if author_meta and author_meta.image_cached:
                folder_cover_url = f"/api/kolibre/authors/{quote(author)}/photo/thumbnail"
        book_hash = db.query(models.BookHash).filter(
            models.BookHash.library == row.library,
            models.BookHash.calibre_book_id == row.calibre_book_id,
            models.BookHash.format == row.format,
        ).first()
        row.delivery_hash = book_hash.file_hash if book_hash else None
        sends.append({
            "book_id": row.id,
            "calibre_book_id": row.calibre_book_id,
            "library": row.library,
            "format": row.format,
            "title": book_row["title"] if book_row else None,
            "author": author,
            "download_url": f"/api/kolibre/books/{row.calibre_book_id}/download?library={row.library}&format={row.format}",
            "folder_cover_url": folder_cover_url,
            "delivery_hash": row.delivery_hash,
        })
    return sends


def _build_removes(db: Session, device: models.Device) -> list:
    """removes[] for the handshake response — empty when the per-device policy
    is 'never': the server doesn't even mention deletions to such a device."""
    if device.delete_policy == "never":
        return []
    rows = db.query(models.DeviceBook).filter(
        models.DeviceBook.device_id == device.id,
        models.DeviceBook.status == "pending_delete",
    ).all()
    removes, libraries_cache = [], {}
    for row in rows:
        lib = libraries_cache.setdefault(row.library, CalibreLibrary(config.library_path(row.library)))
        book_row = lib.get_book(row.calibre_book_id)
        removes.append({
            "book_id": row.id,
            "calibre_book_id": row.calibre_book_id,
            "library": row.library,
            "format": row.format,
            "title": book_row["title"] if book_row else None,
            "expected_path": row.device_path,
        })
    return removes


def _build_file_actions(db: Session, device: models.Device) -> list:
    """
    file_actions[] for the handshake response: web-UI-queued changes to
    local files the device-init scan found but never registered as a
    DeviceBook ("da rivedere" entries) — 'delete' (remove local_path) or
    'overwrite' (delete local_path, then download the given book in its
    place). Applied by the plugin's syncNow right after its own downloads
    (Fase 2.5) and acked via /sync/file-actions/ack, which deletes the row.
    """
    rows = db.query(models.DeviceFlaggedBook).filter(
        models.DeviceFlaggedBook.device_id == device.id,
        models.DeviceFlaggedBook.pending_action.isnot(None),
    ).all()
    actions, libraries_cache = [], {}
    for row in rows:
        entry = {
            "id": row.id,
            "action": row.pending_action,
            "local_path": row.local_path,
        }
        if row.pending_action == "overwrite":
            lib = libraries_cache.setdefault(
                row.pending_action_library, CalibreLibrary(config.library_path(row.pending_action_library))
            )
            book_row = lib.get_book(row.pending_action_calibre_book_id)
            fmt = row.pending_action_format
            if not fmt:
                formats = lib.get_formats(row.pending_action_calibre_book_id)
                fmt = formats[0]["format"] if formats else "EPUB"
            entry.update({
                "library": row.pending_action_library,
                "calibre_book_id": row.pending_action_calibre_book_id,
                "format": fmt,
                "title": book_row["title"] if book_row else None,
                "author": lib.get_book_author(row.pending_action_calibre_book_id),
                "download_url": (
                    f"/api/kolibre/books/{row.pending_action_calibre_book_id}/download"
                    f"?library={row.pending_action_library}&format={fmt}"
                ),
            })
        actions.append(entry)
    return actions


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
                    "author": b["author"] or "Autore Sconosciuto",
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


def _get_open_restore_request(db: Session, target_device_id: int):
    """Most recent non-'done' DeviceRestoreRequest for this target, or None —
    there is at most one 'alive' request per target by construction (see
    create_device_restore_request, which clears any prior one first)."""
    return (
        db.query(models.DeviceRestoreRequest)
        .filter(
            models.DeviceRestoreRequest.target_device_id == target_device_id,
            models.DeviceRestoreRequest.status != "done",
        )
        .order_by(models.DeviceRestoreRequest.id.desc())
        .first()
    )


def _serialize_restore_request(db: Session, req: models.DeviceRestoreRequest) -> dict:
    source = db.query(models.Device).filter(models.Device.id == req.source_device_id).first()
    return {
        "id": req.id,
        "source_device_id": req.source_device_id,
        "source_device_name": source.name if source else None,
        "status": req.status,
        "requested_at": req.requested_at.strftime('%Y-%m-%d %H:%M:%S') if req.requested_at else None,
        "confirmed_at": req.confirmed_at.strftime('%Y-%m-%d %H:%M:%S') if req.confirmed_at else None,
    }


@router.get("")
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
            # Misurati dal plugin sul volume dei libri (v0.6.15+); su un
            # dispositivo con un plugin piu' vecchio restano None e la scheda
            # continua a dire "non riportato".
            "storage_used": d.storage_used,
            "storage_total": d.storage_total,
            "storage_available": d.storage_available,
            "backup_file_count": backup_file_count,
            "pending_restore_request": _serialize_restore_request(db, open_restore_request) if open_restore_request else None,
            "supported_formats": ["EPUB", "PDF", "MOBI", "MD"],
            "folder_layout": d.folder_layout,
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
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    if payload.folder_layout is not None and payload.folder_layout not in ("author", "flat"):
        raise HTTPException(status_code=400, detail="folder_layout deve essere 'author' o 'flat'")
    if payload.delete_policy is not None and payload.delete_policy not in ("auto", "ask", "never"):
        raise HTTPException(status_code=400, detail="delete_policy deve essere 'auto', 'ask' o 'never'")
    for field in ("name", "model", "folder_layout", "write_folder_cover", "delete_policy"):
        value = getattr(payload, field)
        if value is not None:
            setattr(dev, field, value)
    db.commit()
    db.refresh(dev)
    return dev


@router.delete("/{device_id}")
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
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")

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


def _get_owned_device(db: Session, device_id: int, current_user: models.User) -> models.Device:
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    return dev


@router.post("/{device_id}/restore-request/confirm")
def confirm_device_restore_request(
    device_id: int,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Seconda delle tre conferme (vedi DeviceRestoreRequest): l'admin conferma
    sul frontend la richiesta che il device target ha creato. request_id nel
    body, non solo device_id nel path, per evitare di confermare per sbaglio
    una richiesta già sostituita da una più recente per lo stesso target.
    """
    _get_owned_device(db, device_id, current_user)
    request_id = payload.get("request_id")
    req = db.query(models.DeviceRestoreRequest).filter(
        models.DeviceRestoreRequest.id == request_id,
        models.DeviceRestoreRequest.target_device_id == device_id,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Richiesta di migrazione non trovata")
    if req.status != "pending_admin":
        raise HTTPException(status_code=400, detail=f"La richiesta è già in stato '{req.status}'")
    req.status = "confirmed_admin"
    req.confirmed_at = datetime.utcnow()
    db.commit()
    return {"status": "ok"}


@router.delete("/{device_id}/restore-request")
def cancel_device_restore_request(
    device_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Annulla qualunque richiesta non ancora completata per questo target —
    ce n'è al massimo una alla volta (vedi _get_open_restore_request)."""
    _get_owned_device(db, device_id, current_user)
    req = _get_open_restore_request(db, device_id)
    if not req:
        raise HTTPException(status_code=404, detail="Nessuna richiesta di migrazione in corso")
    db.delete(req)
    db.commit()
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
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    db.query(models.Device).filter(models.Device.user_id == current_user.id).update({"is_default": False})
    dev.is_default = True
    db.commit()
    db.refresh(dev)
    return dev


@router.post("/{device_id}/queue")
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
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")

    action = payload.get("action")
    if action not in ("queued_download", "queued_delete"):
        raise HTTPException(status_code=400, detail="action deve essere 'queued_download' o 'queued_delete'")
    calibre_book_id = payload.get("calibre_book_id")
    library = payload.get("library") or resolve_default_library_folder(db)
    if not library:
        raise HTTPException(status_code=404, detail="Nessuna libreria configurata. Creane una prima di continuare.")
    if not calibre_book_id:
        raise HTTPException(status_code=400, detail="calibre_book_id obbligatorio")
    fmt = (payload.get("format") or "").upper() or None

    if action == "queued_download":
        if not fmt:
            # v1 allowed a missing format; DeviceBook.format is NOT NULL, so
            # fall back to the book's first available format.
            lib = CalibreLibrary(config.library_path(library))
            formats = lib.get_formats(calibre_book_id)
            if not formats:
                raise HTTPException(status_code=404, detail="Il libro non ha formati disponibili da inviare")
            fmt = formats[0]["format"]
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
                detail="Il libro non risulta presente su questo dispositivo: non c'è nulla da rimuovere",
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


@sync_router.get("/libraries")
def list_libraries_for_device(
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """Device-token-friendly library picker for the plugin's catalog browser
    — returns the `folder_name` slug that /catalog and /books/{id}/download
    expect as `library`, unlike the web UI's /api/kolibre/libraries which is
    display-oriented."""
    rows = db.query(models.Library).order_by(models.Library.id).all()
    return [{"name": row.name, "library": row.folder_name} for row in rows]


@sync_router.get("/siblings")
def list_sibling_devices(
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """Device-token-friendly picker source for 'Resetta a stato di
    dispositivo': altri dispositivi dello stesso account, esclude se stesso.
    Solo id/nome/modello — niente che serva altrove al plugin."""
    rows = db.query(models.Device).filter(
        models.Device.user_id == current_device.user_id, models.Device.id != current_device.id,
    ).order_by(models.Device.name).all()
    return [{"id": d.id, "name": d.name, "model": d.model} for d in rows]


def _fold_accents(s: str) -> str:
    """
    Lowercased, diacritic-stripped form of s — a Kindle/USB-transferred
    filename very often loses accents ("Garcia") while Calibre's own
    metadata keeps them ("García"), so a plain .lower() substring check
    between the two NEVER matches even when the guessed title/author is
    otherwise exactly right. Confirmed as the second half of a real
    fuzzy-match failure (the first half was _guessTitleFromPath's own bug,
    fixed in main.lua) while investigating why an already-catalogued book
    stayed stuck on "no_candidate".
    """
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


# Below this containment threshold real fuzzy matching kicks in — see
# browse_catalog's own docstring for why substring matching alone (AND/OR,
# accent-folded) isn't enough: a subtitle, a differently-guessed word order,
# or stray punctuation in the device-side filename guess can make an
# otherwise obvious match return zero substring hits. Punctuation is folded
# to spaces (not stripped outright) so "Il generale e il giudice: romanzo"
# and "Il generale e il giudice" still overlap almost entirely token-wise.
_FUZZY_MATCH_THRESHOLD = 0.6
_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")

# Calibre's own title_sort() moves a leading article to the end for
# alphabetical sorting ("Il mare" -> "mare, Il") — and on a device where
# the on-disk filename/folder-title comes straight from that sort field
# (confirmed on a real device: an "author" folder_layout writes
# <Author>/<title_sort>.epub, not the display title), the guessed query
# arrives in that reordered form. Left alone, the comma is just folded to a
# space below and "mare il" vs "il mare" scores under threshold even
# though it's an exact match — reordering here undoes Calibre's own
# transform instead of trying to fuzzy-match around it.
_TITLE_SORT_ARTICLES = (
    "the", "a", "an",
    "lo", "gli", "il", "le", "la", "l'", "i",
    "les", "un", "une", "des",
    "el", "los", "las", "unos", "unas", "una",
    "der", "die", "das", "ein", "eine",
)
_TITLE_SORT_SUFFIX_RE = re.compile(
    r"^(?P<title>.+),\s*(?P<article>%s)$" % "|".join(re.escape(a) for a in _TITLE_SORT_ARTICLES),
    re.IGNORECASE,
)


def _reorder_title_sort_article(title: str) -> str:
    match = _TITLE_SORT_SUFFIX_RE.match((title or "").strip())
    if not match:
        return title or ""
    return f"{match.group('article')} {match.group('title')}"


def _normalize_for_fuzzy(s: str) -> str:
    s = _fold_accents(s or "")
    s = _PUNCTUATION_RE.sub(" ", s)
    return _WHITESPACE_RE.sub(" ", s).strip()


def _fuzzy_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


@sync_router.get("/capabilities")
def device_capabilities(current_device: models.Device = Depends(auth.get_current_device)):
    """
    Capability negotiation (foundation for the richer catalog-browsing
    navigator planned for the plugin, phase 1 of that work — this endpoint
    itself ships no UI, it just lets a future plugin ask "does this server
    support the newer catalog features" before calling them). Deliberately
    trivial — auth only, no DB query — so it stays fast and can't itself
    become a reason a handshake fails. An older Kolibre server without this
    route 404s on it, and that 404 IS the "no new features" signal a caller
    should degrade on; there's nothing here to special-case for that.

    `capabilities` is a plain hardcoded list for now (grows later by adding
    strings, no config system needed yet). `serverVersion` mirrors the
    literal in main.py's `FastAPI(..., version=...)` kwarg — no separate
    version-tracking machinery exists in this codebase, so this is the one
    other place that string lives; keep the two in sync by hand if it ever
    changes.
    """
    return {"serverVersion": "2.0", "capabilities": ["catalogSections", "catalogDiscover"]}


def _bucket_counts(all_books: list, section: str) -> dict:
    """
    Name -> book count for one section ('authors'/'series'/'tags') over an
    already-fetched list_books() result — see catalog_sections' own
    docstring for why this stays name-keyed (matching browse_catalog's
    existing author/series/tag filters) instead of Calibre's internal
    integer FKs, which list_books() doesn't expose at this layer anyway.
    """
    counts: dict = defaultdict(int)
    if section == "authors":
        for b in all_books:
            author_str = b.get("author") or ""
            for name in author_str.split(" & "):
                name = name.strip()
                if name:
                    counts[name] += 1
    elif section == "series":
        for b in all_books:
            name = (b.get("series") or "").strip()
            if name:
                counts[name] += 1
    else:  # tags
        for b in all_books:
            for name in b.get("tags") or []:
                name = (name or "").strip()
                if name:
                    counts[name] += 1
    return counts


@sync_router.get("/catalog/sections/{section}")
def catalog_sections(
    section: str,
    library: str,
    page: int = 1,
    size: int = 50,
    q: str = None,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Drill-down "buckets" behind browse_catalog's own author/series/tag
    filters (foundation for the catalog navigator, phase 1 — no UI here yet,
    just the data surface it'll page over): every distinct author/series/tag
    name across the library with how many books carry it, so a future
    "browse by author" screen can list authors first and only then ask
    browse_catalog?author=... for one author's books, instead of pulling the
    whole catalog client-side to build that list itself.

    Pure in-Python group-by over list_books() (already fetched for
    browse_catalog, no new SQL/schema) — deliberately NOT keyed by Calibre's
    internal integer FKs, which list_books() never surfaces at this layer;
    staying name-based matches the existing author/series/tag filters on
    browse_catalog, which already match by name too.

    A multi-author book's `author` field is `"Alice & Bob"` (Calibre's own
    authors_to_string join) — split on `" & "` so each author is counted
    once in their own bucket, never as a separate combined "Alice & Bob"
    bucket. A book contributes to every tag it has (3 tags = +1 to 3
    buckets). `series` uses list_books()'s own singular (already `LIMIT 1`)
    series field, skipping books with none.
    """
    if section not in ("authors", "series", "tags"):
        raise HTTPException(status_code=400, detail="section deve essere 'authors', 'series' o 'tags'")
    if page < 1 or size < 1:
        raise HTTPException(status_code=400, detail="page e size devono essere >= 1")

    lib = CalibreLibrary(config.library_path(library))
    all_books = lib.list_books()
    counts = _bucket_counts(all_books, section)

    names = sorted(counts.keys())
    if q:
        needle = _fold_accents(q)
        names = [n for n in names if needle in _fold_accents(n)]

    total = len(names)
    start = (page - 1) * size
    page_names = names[start:start + size]
    return {
        "page": page,
        "size": size,
        "total": total,
        "has_next": (page * size) < total,
        "items": [{"name": n, "count": counts[n]} for n in page_names],
    }


def _serialize_catalog_book(b: dict) -> dict:
    """Shared shape for every catalog-style response (browse_catalog, and the
    Discover endpoint below) — kept in one place so a field added/renamed
    here never drifts between the two."""
    return {
        "id": b["id"], "title": b["title"], "author": b.get("author"), "formats": b["formats"],
        "series": b.get("series"), "series_index": b.get("series_index"),
        "tags": b.get("tags") or [], "rating": b.get("rating"),
        "pubdate": b.get("pubdate"), "has_cover": b.get("has_cover"),
        "size": b.get("size"),
    }


def _device_book_ids_on_device(db: Session, device_id: int, library: str) -> set:
    """calibre_book_id set "currently on this device" for one library —
    every DeviceBook row except status='removed_by_device' (a device can
    have a pending_send/pending_delete/send_failed/delete_declined row that
    is still physically present or about to be, so only an actually-
    confirmed removal should make a book eligible again for Discover/the
    "non sul device" filter)."""
    rows = db.query(models.DeviceBook.calibre_book_id).filter(
        models.DeviceBook.device_id == device_id,
        models.DeviceBook.library == library,
        models.DeviceBook.status != "removed_by_device",
    ).all()
    return {r[0] for r in rows}


@sync_router.get("/catalog/discover")
def catalog_discover(
    library: str,
    limit: int = 12,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    "Da scoprire": books NOT already on this device, preferring ones that
    share an author or a tag with what was recently read ON THIS DEVICE
    (ReadingSession.device_id, same scoping already used elsewhere for
    per-device stats — see stats_service.py's own device_id-only filters,
    no separate user scope needed since device_id already identifies a
    single owner). Falls back to a random pick from the rest of the library
    when there aren't enough (or any) author/tag matches, exactly as
    requested: "stesso autore o stessi tag e poi scelta randomica".
    """
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit deve essere >= 1")

    on_device = _device_book_ids_on_device(db, current_device.id, library)

    recent_rows = db.query(models.ReadingSession.calibre_book_id).filter(
        models.ReadingSession.device_id == current_device.id,
        models.ReadingSession.library == library,
    ).order_by(models.ReadingSession.start_time.desc()).limit(20).all()
    recent_ids = list(dict.fromkeys(r[0] for r in recent_rows))  # dedup, keep recency order

    lib = CalibreLibrary(config.library_path(library))
    all_books = lib.list_books()
    books_by_id = {b["id"]: b for b in all_books}

    recent_authors = set()
    recent_tags = set()
    for cbid in recent_ids:
        rb = books_by_id.get(cbid)
        if not rb:
            continue
        if rb.get("author"):
            recent_authors.add(rb["author"])
        for t in rb.get("tags") or []:
            if t:
                recent_tags.add(t)

    excluded = on_device | set(recent_ids)
    candidates = [b for b in all_books if b["id"] not in excluded]

    matched = [
        b for b in candidates
        if (b.get("author") and b["author"] in recent_authors)
        or any(t in recent_tags for t in (b.get("tags") or []))
    ]
    random.shuffle(matched)
    result = matched[:limit]

    if len(result) < limit:
        chosen_ids = {b["id"] for b in result}
        filler_pool = [b for b in candidates if b["id"] not in chosen_ids]
        random.shuffle(filler_pool)
        result.extend(filler_pool[: limit - len(result)])

    return {"books": [_serialize_catalog_book(b) for b in result]}


@sync_router.get("/catalog")
def browse_catalog(
    library: str,
    q: str = None,
    author: str = None,
    series: str = None,
    tag: str = None,
    sort: str = "author",
    page: int = None,
    size: int = None,
    exclude_on_device: bool = False,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Catalog browser for the plugin's "Sfoglia catalogo" (stile BookOrbit):
    unlike the server-driven sync queue (Fase 5's core loop), this is the
    device *pulling* whatever it wants, on demand. Returns the full matching
    set (capped) rather than a server-paginated page — KOReader's own Menu
    widget already paginates a long item_table on-device, so there's no need
    to reinvent that here. `sort`: "author" (default) or "recent" (newest
    added first, by Calibre's own `timestamp` column).

    `author`, when given alongside `q`, tightens the fuzzy device-init match
    (main.lua's _findProbableCatalogMatches) from "q anywhere in title OR
    author" to "q in title AND author in author" — plain OR on a single
    needle built by mashing a guessed title and author together (the old
    behavior) is usually a substring of NEITHER field alone, which is why
    filenames that split cleanly into title+author still failed to match.
    Falls back to the original OR-on-q-alone behavior when the AND filter
    finds nothing, so a wrong/noisy author guess never makes matching worse
    than before.

    If BOTH substring passes above come up empty, a real fuzzy pass (edit-
    distance ratio, not containment) runs over the whole catalog as a last
    resort — confirmed as a real gap, not hypothetical: a subtitle, a
    slightly-off title guess from the filename, or reordered
    title/author words all defeat plain substring containment even when a
    human would call the match obvious. This only ever ADDS candidates when
    the substring passes found zero — it never changes/reorders a query that
    already got substring hits, so the interactive "Sfoglia catalogo"
    type-ahead search (short partial words, where a containment check is
    exactly right) is untouched.

    `series`/`tag` (new, for the catalog-navigator foundation work): simple
    independent substring filters (accent-folded, same as `author`) applied
    on top of whatever q/author already selected — deliberately NOT folded
    into the tightening/fuzzy-fallback logic above, which exists only to
    rescue a noisy device-init title/author guess, not to serve every filter
    combination.

    `page`/`size` (new, both optional): when neither is given, behavior is
    byte-for-byte what it always was — up to 500 books, `truncated` if more
    exist. Passing both switches to a real page of the already-filtered/
    sorted list instead of the flat [:500] cap, adding `page`/`has_next` to
    the response. Passing only one of the two falls back to the old
    unpaginated behavior rather than half-implementing pagination.

    `exclude_on_device` (new, for the Browser's "Non sul device" view):
    drops any book already on the CALLING device for this library (see
    `_device_book_ids_on_device`) before sorting/paginating. Default False
    keeps existing behavior byte-for-byte for every caller that doesn't pass
    it — including an un-updated plugin, which never will.
    """
    lib = CalibreLibrary(config.library_path(library))
    all_books = lib.list_books()
    books = all_books
    if q and author:
        q_needle, author_needle = _fold_accents(q), _fold_accents(author)
        tightened = [
            b for b in books
            if q_needle in _fold_accents(b.get("title") or "") and author_needle in _fold_accents(b.get("author") or "")
        ]
        if tightened:
            books = tightened
        elif q:
            needle = _fold_accents(q)
            books = [
                b for b in books
                if needle in _fold_accents(b.get("title") or "") or needle in _fold_accents(b.get("author") or "")
            ]
    elif q:
        needle = _fold_accents(q)
        books = [
            b for b in books
            if needle in _fold_accents(b.get("title") or "") or needle in _fold_accents(b.get("author") or "")
        ]

    if q and not books:
        query_norm = _normalize_for_fuzzy(f"{_reorder_title_sort_article(q)} {author or ''}")
        scored = []
        for b in all_books:
            candidate_title = _reorder_title_sort_article(b.get("title") or "")
            candidate_norm = _normalize_for_fuzzy(f"{candidate_title} {b.get('author') or ''}")
            score = _fuzzy_ratio(query_norm, candidate_norm)
            if score >= _FUZZY_MATCH_THRESHOLD:
                scored.append((score, b))
        if scored:
            scored.sort(key=lambda pair: pair[0], reverse=True)
            books = [b for _, b in scored]

    if series:
        series_needle = _fold_accents(series)
        books = [b for b in books if series_needle in _fold_accents(b.get("series") or "")]
    if tag:
        tag_needle = _fold_accents(tag)
        books = [b for b in books if any(tag_needle in _fold_accents(t) for t in (b.get("tags") or []))]
    if exclude_on_device:
        on_device = _device_book_ids_on_device(db, current_device.id, library)
        books = [b for b in books if b["id"] not in on_device]

    if sort == "recent":
        books.sort(key=lambda b: (b.get("timestamp") or ""), reverse=True)
    else:
        books.sort(key=lambda b: ((b.get("author") or ""), (b.get("title") or "")))
    total = len(books)

    if page is not None and size is not None:
        start = (page - 1) * size
        page_books = books[start:start + size]
    else:
        page_books = books[:500]

    result = {
        "total": total,
        "truncated": total > 500,
        "books": [_serialize_catalog_book(b) for b in page_books],
    }
    if page is not None and size is not None:
        result["page"] = page
        result["has_next"] = (page * size) < total
    return result


@sync_router.post("/identify-file")
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
    if not _SAFE_BACKUP_FILENAME.match(filename):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in text_fingerprint.SUPPORTED_FINGERPRINT_FORMATS:
        return {"matched": False, "reason": "unsupported_format"}

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Corpo della richiesta vuoto")

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


def _parse_koreader_datetime(value):
    """KOReader's own highlight-creation timestamp (readerannotation.lua
    stamps this once, "%Y-%m-%d %H:%M:%S", never touched again after) — see
    main.lua's own comment on why this is forwarded now. Returns None for
    anything missing/malformed (older plugin builds before this field
    existed, or a genuinely garbled value) so callers can fall back to their
    own "now" default exactly like before this existed."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _upsert_orphan_highlight(db: Session, current_device: models.Device, local_path: str, file_hash: str, item: dict) -> bool:
    """
    Records an annotation whose file_hash didn't resolve via BookHash —
    see models.OrphanHighlight for why this is a separate table rather than
    a nullable Highlight.calibre_book_id. Dedup/update key mirrors
    push_device_annotations' own (device_id, local_path, koreader_pos0)
    instead of (library, calibre_book_id, koreader_pos0), since there's no
    book identity yet — including that function's own (page, text) fallback
    for when pos0 is missing (PDFs have no crengine xpointer at all, see its
    comment there): without it, every PDF highlight from an unmatched file
    inserted a brand new row on every single device sync (since NULL !=
    NULL in the table's own UniqueConstraint, nothing blocked it), each
    with a new id — and since the Obsidian export's dedup marker IS that id
    (`orphan-<id>`, see annotations.py::export_annotations), those
    highlights kept re-appearing as "new" in Obsidian forever. The matched-
    book path got this same fix earlier (see push_device_annotations'
    'pos0 missing' branch) but this orphan path was missed — confirmed
    real, not hypothetical: exactly this symptom was reported in use,
    isolated to un-paired highlights. Returns False if there's nothing usable to
    store (no text), matching the caller's own guard.
    """
    text = item.get("text")
    if not text:
        return False
    pos0 = item.get("pos0")
    # The device is the only source of truth for when a highlight was
    # ACTUALLY made — always applied (insert AND update, see below) rather
    # than only on first insert, so a highlight that sat unmatched for a
    # while still self-heals to its real date on its very next sync instead
    # of staying wrong forever. None (older plugin, or a genuinely garbled
    # value) leaves created_at exactly as it behaved before this existed.
    hl_datetime = _parse_koreader_datetime(item.get("datetime"))
    existing = None
    if pos0:
        existing = db.query(models.OrphanHighlight).filter(
            models.OrphanHighlight.device_id == current_device.id,
            models.OrphanHighlight.local_path == local_path,
            models.OrphanHighlight.koreader_pos0 == pos0,
            models.OrphanHighlight.deleted_at.is_(None),
        ).first()
    else:
        existing = db.query(models.OrphanHighlight).filter(
            models.OrphanHighlight.device_id == current_device.id,
            models.OrphanHighlight.local_path == local_path,
            models.OrphanHighlight.koreader_pos0.is_(None),
            models.OrphanHighlight.page == item.get("page"),
            models.OrphanHighlight.text == text,
            models.OrphanHighlight.deleted_at.is_(None),
        ).first()
    if existing:
        existing.text = text
        # `or existing.comment`, like every neighbouring field: a note written
        # in Kolibre must survive a sync from a device that doesn't have it.
        # KOReader only sends a "note" when one was typed ON the device, so a
        # plain assignment here wiped every web-written note at the next sync.
        # The trade-off is deliberate and matches color/chapter/page: a note
        # cleared on the device won't propagate as a deletion. Losing an
        # erasure is recoverable, losing the text isn't.
        existing.comment = item.get("comment") or existing.comment
        existing.color = item.get("color") or existing.color
        existing.chapter = item.get("chapter") or existing.chapter
        existing.koreader_pos1 = item.get("pos1") or existing.koreader_pos1
        existing.page = item.get("page") or existing.page
        existing.file_hash = file_hash
        if hl_datetime:
            existing.created_at = hl_datetime
    else:
        db.add(models.OrphanHighlight(
            user_id=current_device.user_id, device_id=current_device.id,
            local_path=local_path, file_hash=file_hash,
            text=text, comment=item.get("comment"), chapter=item.get("chapter"),
            page=item.get("page"), koreader_pos0=pos0, koreader_pos1=item.get("pos1"),
            color=item.get("color") or "yellow",
            **({"created_at": hl_datetime} if hl_datetime else {}),
        ))
    return True


def _utente_del_dispositivo(db: Session, device_id: int):
    """L'utente a cui appartiene un dispositivo. Serve ai filtri per utente
    delle note, dove l'alternativa era passare l'id dell'utente attraverso
    quattro chiamanti diversi."""
    return db.query(models.Device.user_id).filter(models.Device.id == device_id).scalar()


def _migrate_orphan_highlights(db: Session, device_id: int, local_path: str, library: str, calibre_book_id: int) -> int:
    """
    Copies every OrphanHighlight for (device_id, local_path) into a real
    Highlight against the now-known book, then removes the orphan rows.
    Called by the manual 'pair' action (queue_flagged_book_action), by its
    automatic counterpart (auto_pair_orphan_annotations, triggered by the
    plugin's own content-fingerprint follow-up right after a sync), and
    opportunistically from push_device_annotations whenever a hash that
    used to be unresolved starts matching on its own (e.g. right after a
    recompute-hashes backfill) — pairing isn't the only way a book stops
    being an orphan.

    position_status is left None (not copied from anywhere, since orphan
    rows never had one) so each migrated highlight re-enters the normal
    lazy CFI-resolution batch in annotations.py's list_annotations exactly
    like a fresh device highlight would — a resolution failure there already
    means "keep the highlight, just can't deep-link it" (position_status=
    'failed'), never deletion, which is exactly the guarantee this feature
    was built to keep.
    """
    orphans = db.query(models.OrphanHighlight).filter(
        models.OrphanHighlight.device_id == device_id,
        models.OrphanHighlight.local_path == local_path,
        models.OrphanHighlight.deleted_at.is_(None),
    ).all()
    migrated = 0
    for o in orphans:
        existing = None
        if o.koreader_pos0:
            existing = db.query(models.Highlight).filter(
                # Per utente: lo stesso xpointer sullo stesso libro esiste
                # identico nelle note di chiunque altro lo abbia evidenziato,
                # e senza questo filtro la nota orfana ci finiva sopra.
                # L'utente si ricava dal dispositivo invece di farselo passare:
                # un argomento in piu' e' un argomento che qualche chiamante
                # dimentichera'.
                models.Highlight.user_id == _utente_del_dispositivo(db, device_id),
                models.Highlight.library == library,
                models.Highlight.calibre_book_id == calibre_book_id,
                models.Highlight.koreader_pos0 == o.koreader_pos0,
                models.Highlight.deleted_at.is_(None),
            ).first()
        if existing:
            existing.text = o.text
            # Same rule as _upsert_orphan_highlight: the orphan row is being
            # folded into a Highlight that may already carry a note and a
            # colour set in Kolibre, so the orphan's values only fill gaps.
            existing.comment = o.comment or existing.comment
            existing.color = o.color or existing.color
            existing.chapter = existing.chapter or o.chapter
            existing.koreader_pos1 = existing.koreader_pos1 or o.koreader_pos1
            existing.page = existing.page or o.page
            # o.created_at already holds the real KOReader date (see
            # _upsert_orphan_highlight) — without copying it here, migrating
            # out of orphan status would silently reset it back to "now",
            # exactly the bug this whole change is fixing, just one step
            # later in the pipeline.
            existing.created_at = o.created_at
        else:
            db.add(models.Highlight(
                user_id=o.user_id, device_id=o.device_id, library=library, calibre_book_id=calibre_book_id,
                text=o.text, comment=o.comment, chapter=o.chapter, page=o.page,
                koreader_pos0=o.koreader_pos0, koreader_pos1=o.koreader_pos1, color=o.color,
                source="device", position_status=None, created_at=o.created_at,
            ))
        db.delete(o)
        migrated += 1
    return migrated


def _migrate_device_highlights_to_new_book(
    db: Session, current_user: models.User, device_id: int,
    old_library: str, old_calibre_book_id: int, new_library: str, new_calibre_book_id: int,
) -> int:
    """
    Used by the "Accoppia manualmente" action on an already-matched
    DeviceBook row (pair_device_book below) — a re-pairing, not a first-time
    pairing (see _migrate_orphan_highlights for that case, which is a
    different, mutually exclusive scenario: an orphan was never matched to
    any book, a DeviceBook row always already is).

    Deliberately scoped to THIS device's own 'device'-sourced highlights on
    the OLD book — never every Highlight on (old_library, old_calibre_book_id):
    that same book identity may also carry 'web'/'calibre' highlights, or
    'device' highlights pushed by a DIFFERENT device that is correctly
    matched to it, none of which have anything to do with this one device's
    mismatch and must not be dragged along.

    cfi_start/cfi_end/position_status are reset to None — a position
    resolved against the OLD book's EPUB structure is almost certainly wrong
    against the NEW one, so each migrated highlight re-enters the normal
    lazy CFI-resolution batch (annotations.py's list_annotations) instead of
    keeping a stale, silently-wrong deep link.
    """
    rows = db.query(models.Highlight).filter(
        models.Highlight.user_id == current_user.id,
        models.Highlight.library == old_library,
        models.Highlight.calibre_book_id == old_calibre_book_id,
        models.Highlight.source == "device",
        models.Highlight.device_id == device_id,
    ).all()
    for h in rows:
        # A Highlight may already sit at the NEW book identity for the same
        # koreader_pos0 — e.g. re-pairing to a book this same device (or
        # another one) already correctly synced highlights for. Blindly
        # mutating h.library/calibre_book_id in that case would leave two
        # rows sharing an identical (library, calibre_book_id, pos0) — a
        # genuine collision the dedup key elsewhere (push_device_annotations)
        # is supposed to prevent, but a straight re-point bypasses it
        # entirely. Merge into the existing row instead, same pattern
        # _migrate_orphan_highlights already uses for the analogous case.
        collision = None
        if h.koreader_pos0:
            collision = db.query(models.Highlight).filter(
                models.Highlight.id != h.id,
                models.Highlight.library == new_library,
                models.Highlight.calibre_book_id == new_calibre_book_id,
                models.Highlight.koreader_pos0 == h.koreader_pos0,
                models.Highlight.deleted_at.is_(None),
            ).first()
        if collision:
            collision.text = h.text
            collision.comment = collision.comment or h.comment
            collision.color = h.color or collision.color
            collision.chapter = collision.chapter or h.chapter
            collision.koreader_pos1 = collision.koreader_pos1 or h.koreader_pos1
            collision.page = collision.page or h.page
            db.delete(h)
        else:
            h.library = new_library
            h.calibre_book_id = new_calibre_book_id
            h.cfi_start = None
            h.cfi_end = None
            h.position_status = None
    return len(rows)


@sync_router.post("/annotations")
def push_device_annotations(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Bulk upload of KOReader annotations read straight from .sdr sidecar files
    (see main.lua's syncAnnotations) — device-token authed, unlike the rest
    of /api/annotations which is JWT/human. Body: {annotations: [{hash,
    text, comment, chapter, page, pos0, pos1, color, path}]}. Dedup/update
    key is (library, calibre_book_id, koreader_pos0): re-syncing the same
    highlight after an edit on the device updates it in place instead of
    duplicating it.

    An annotation whose hash doesn't resolve to any BookHash is no longer
    silently dropped — if the item carries `path` (the local file path,
    added specifically for this), it's stored as an OrphanHighlight instead,
    so it's still visible/exportable even though it isn't attached to a
    Kolibre book yet (see the frontend Annotations page and the Obsidian
    export, both of which now include orphans). `orphaned` in the response
    counts these separately from `unresolved` (items with no `path` at all —
    older plugin builds before this field existed — which are still dropped,
    same as before).

    `chapter` as sent by the device is only KOReader's own leaf-title fallback
    now (the plugin no longer reads/walks the book's TOC at all — see
    main.lua's now-removed _resolveFullChapterPath) — the real ancestry is
    resolved here instead, reusing the same EPUB/PDF the server already opens
    for CFI conversion. `_file_path_cache` avoids re-opening the same book
    file once per item in a bulk push (a single sync commonly resends many
    highlights from the same book back to back).
    """
    items = payload.get("annotations", [])
    created, updated, unresolved, orphaned = 0, 0, 0, 0
    # Distinct local_path values that ended up orphaned THIS call — returned
    # to the plugin so it can try to auto-resolve each one via content
    # fingerprint (_identifyFileByContent + /annotations/auto-pair) right
    # after a routine sync, instead of only ever finding out about them
    # during a full device-init scan or a human trip through "Da rivedere".
    orphan_paths = set()
    _file_path_cache = {}
    # File per cui le orfane sono gia' state raccolte in questa richiesta.
    _migrati: set = set()
    for item in items:
        file_hash = item.get("hash")
        text = item.get("text")
        if not file_hash or not text:
            continue
        match = book_hash_service.resolve_first_book_match(db, file_hash, device_id=current_device.id)
        if not match:
            local_path = item.get("path")
            if local_path and _upsert_orphan_highlight(db, current_device, local_path, file_hash, item):
                orphaned += 1
                orphan_paths.add(local_path)
            else:
                unresolved += 1
            continue

        local_path = item.get("path")
        if local_path and local_path not in _migrati:
            # The hash resolved this time — sweep up any leftover orphan
            # rows for this same local file (e.g. it was pushed before a
            # recompute-hashes fixed the match, not just via manual pairing).
            #
            # Una volta per FILE, non per nota: un invio manda tutte le note
            # di un libro insieme (246 in un caso reale), e questa girava per
            # ognuna — centinaia di interrogazioni su orphan_highlights per
            # ripulire le stesse righe, che dopo la prima volta non ci sono
            # nemmeno piu'.
            _migrati.add(local_path)
            _migrate_orphan_highlights(db, current_device.id, local_path, match.library, match.calibre_book_id)

        pos0 = item.get("pos0")
        existing = None
        if pos0:
            existing = db.query(models.Highlight).filter(
                # user_id: senza, la ricerca del duplicato trova la nota di
                # UN ALTRO utente sulla stessa riga dello stesso libro (lo
                # xpointer di crengine e' deterministico per lo stesso EPUB,
                # quindi due persone che evidenziano lo stesso paragrafo
                # producono lo stesso pos0) e la riscrive con la propria. Il
                # gemello _migrate_device_highlights_to_new_book filtra per
                # utente apposta e lo spiega; qui mancava.
                models.Highlight.user_id == current_device.user_id,
                models.Highlight.library == match.library,
                models.Highlight.calibre_book_id == match.calibre_book_id,
                models.Highlight.koreader_pos0 == pos0,
                models.Highlight.deleted_at.is_(None),
            ).first()
        else:
            # PDFs have no crengine xpointer at all (pos0 is EPUB-only), so
            # this isn't a rare edge case — without a fallback key, every
            # PDF highlight re-synced from the device duplicated on every
            # single sync (confirmed as a real gap, not hypothetical: the
            # dedup key was pos0-only, so pos0 missing meant no lookup ran
            # at all). (page, text) is the best available substitute.
            existing = db.query(models.Highlight).filter(
                # Vedi il filtro per utente del ramo qui sopra.
                models.Highlight.user_id == current_device.user_id,
                models.Highlight.library == match.library,
                models.Highlight.calibre_book_id == match.calibre_book_id,
                models.Highlight.koreader_pos0.is_(None),
                models.Highlight.page == item.get("page"),
                models.Highlight.text == text,
                models.Highlight.deleted_at.is_(None),
            ).first()

        cache_key = (match.library, match.calibre_book_id, match.format)
        if cache_key not in _file_path_cache:
            try:
                lib = CalibreLibrary(config.library_path(match.library))
                _file_path_cache[cache_key] = lib.get_format_file_path(match.calibre_book_id, match.format)
            except Exception:
                _file_path_cache[cache_key] = None
        file_path = _file_path_cache[cache_key]

        resolved_chapter = None
        if file_path and pos0 and match.format == "EPUB":
            resolved_chapter = resolve_epub_chapter_path(file_path, pos0)
        elif file_path and match.format == "PDF" and item.get("page"):
            resolved_chapter = resolve_pdf_chapter_path(file_path, item.get("page"))
        chapter = resolved_chapter or item.get("chapter")

        # Same "device is the source of truth for the real creation date"
        # fix as _upsert_orphan_highlight's own — applied on update too, not
        # just insert, so a highlight synced late (e.g. its book only just
        # got matched) self-heals to its real date on THIS sync rather than
        # staying stuck at whatever day its row first happened to be
        # created — confirmed real: a highlight known to date from
        # 11/02/2025 turned up dated to a much later sync day.
        hl_datetime = _parse_koreader_datetime(item.get("datetime"))
        if existing:
            existing.text = text
            # See _upsert_orphan_highlight for why this is `or` and not a
            # plain assignment: it's the same web-note-destroying bug, on the
            # matched-book path instead of the orphan one.
            existing.comment = item.get("comment") or existing.comment
            existing.color = item.get("color") or existing.color
            existing.chapter = chapter or existing.chapter
            existing.koreader_pos1 = item.get("pos1") or existing.koreader_pos1
            existing.page = item.get("page") or existing.page
            if hl_datetime:
                existing.created_at = hl_datetime
            updated += 1
        else:
            db.add(models.Highlight(
                user_id=current_device.user_id, device_id=current_device.id,
                library=match.library, calibre_book_id=match.calibre_book_id,
                text=text, comment=item.get("comment"), chapter=chapter,
                page=item.get("page"), koreader_pos0=pos0, koreader_pos1=item.get("pos1"),
                color=item.get("color") or "yellow", source="device",
                **({"created_at": hl_datetime} if hl_datetime else {}),
            ))
            created += 1
    db.commit()
    log_message(
        "info", "annotations",
        f"Da '{current_device.name}': {created} nuove, {updated} aggiornate, "
        f"{orphaned} non accoppiate (importate comunque), {unresolved} scartate (nessun path)",
    )
    return {
        "status": "ok", "created": created, "updated": updated, "unresolved": unresolved, "orphaned": orphaned,
        "orphan_paths": sorted(orphan_paths),
    }


@sync_router.post("/annotations/reconcile")
def reconcile_device_annotations(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Note cancellate SUL DISPOSITIVO: le toglie anche di qui.

    Finora la sincronizzazione era solo additiva — una nota cancellata su
    KOReader restava sul server per sempre e niente la riconciliava. Il
    costo per accorgersene era pero' gia' pagato: il plugin manda comunque
    l'insieme COMPLETO delle note di un libro, e lo usavamo come se fosse
    un'aggiunta.

    Corpo: {files: [{hash, path, keys: [{pos0, page, text}]}]} — le chiavi
    sono quelle su cui push_device_annotations decide se una nota e' gia'
    vista, quindi qui e li' si parla della stessa cosa.

    Tre limiti deliberati, perche' questa e' l'unica parte del protocollo
    che DISTRUGGE:

    - solo note con source='device' E device_id di QUESTO dispositivo. Un
      libro letto su due dispositivi ha note che l'altro non conosce, e
      un'evidenziazione fatta nel reader web (source='web') non sta nel
      sidecar di nessuno: nessuna delle due deve sparire perche' questo
      Kindle non ce l'ha;
    - cancellazione MORBIDE (deleted_at), che e' il cestino gia' esistente:
      un errore qui si recupera, non si piange;
    - un file le cui chiavi arrivano vuote non cancella niente. Un sidecar
      illeggibile o un'estrazione fallita produrrebbero esattamente quel
      corpo, e "non ho trovato niente" non e' "l'utente ha cancellato
      tutto".
    """
    files = payload.get("files") or []
    eliminate = 0
    for f in files:
        file_hash, keys = f.get("hash"), f.get("keys") or []
        if not file_hash or not keys:
            continue
        match = book_hash_service.resolve_first_book_match(db, file_hash, device_id=current_device.id)
        if not match:
            continue
        vive_pos0 = {k.get("pos0") for k in keys if k.get("pos0")}
        vive_senza_pos0 = {(k.get("page"), k.get("text")) for k in keys if not k.get("pos0")}
        righe = db.query(models.Highlight).filter(
            models.Highlight.library == match.library,
            models.Highlight.calibre_book_id == match.calibre_book_id,
            models.Highlight.device_id == current_device.id,
            models.Highlight.source == "device",
            models.Highlight.deleted_at.is_(None),
        ).all()
        for r in righe:
            se_ne_va = (
                r.koreader_pos0 not in vive_pos0
                if r.koreader_pos0
                else (r.page, r.text) not in vive_senza_pos0
            )
            if se_ne_va:
                r.deleted_at = datetime.utcnow()
                eliminate += 1
    if eliminate:
        db.commit()
        log_message(
            "info", "annotations",
            f"Da '{current_device.name}': {eliminate} annotazioni cancellate sul dispositivo, "
            f"spostate nel cestino anche qui",
        )
    return {"status": "ok", "deleted": eliminate}


@sync_router.post("/annotations/auto-pair")
def auto_pair_orphan_annotations(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Device-token counterpart of queue_flagged_book_action's 'pair' branch —
    same two effects (record_device_hash + _migrate_orphan_highlights), same
    non-destructive guarantee (touches no file on the device, only server-
    side bookkeeping), just triggered automatically by the plugin right
    after a routine annotation push instead of requiring a human trip
    through "Da rivedere".

    Root-cause fix for the Kindle case (confirmed against real data): a
    Kindle re-packages EPUBs on
    transfer, so its partial-MD5 never matches BookHash.file_hash — every
    highlight from such a file becomes an OrphanHighlight on EVERY sync
    until a human manually pairs it. The plugin now follows up
    push_device_annotations' `orphan_paths` with a content-identify call
    (_identifyFileByContent, existing endpoint /identify-file) for each
    still-unresolved file, and on a match calls this endpoint with the
    result — closing the gap upstream instead of relying on manual review.

    Body: {local_path, file_hash, library, calibre_book_id, format}. All
    required — this never guesses a candidate itself, it only registers one
    the plugin already got a confident fingerprint match for.

    Also drops any DeviceFlaggedBook row for the same (device, local_path):
    once auto-paired here, that file is resolved and would otherwise sit in
    "Da rivedere" forever pointing at a book that's already been handled.
    """
    local_path = payload.get("local_path")
    file_hash = payload.get("file_hash")
    library = payload.get("library")
    calibre_book_id = payload.get("calibre_book_id")
    format = payload.get("format") or "EPUB"
    if not local_path or not file_hash or not library or not calibre_book_id:
        raise HTTPException(status_code=400, detail="local_path, file_hash, library e calibre_book_id sono obbligatori")

    book_hash_service.record_device_hash(db, library, calibre_book_id, format, file_hash)
    migrated = _migrate_orphan_highlights(db, current_device.id, local_path, library, calibre_book_id)
    flagged = db.query(models.DeviceFlaggedBook).filter(
        models.DeviceFlaggedBook.device_id == current_device.id,
        models.DeviceFlaggedBook.local_path == local_path,
    ).first()
    if flagged:
        db.delete(flagged)
    db.commit()
    log_message(
        "info", "annotations",
        f"Auto-pair da '{current_device.name}': {local_path} -> {library}/{calibre_book_id} "
        f"({migrated} note migrate)",
    )
    return {"status": "ok", "migrated_highlights": migrated}


@sync_router.post("/sync")
def koreader_sync_handshake(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Sync handshake. Protocol v2 ({"protocol": 2, ...}) opens a tracked session
    (DeviceSyncHistory), reconciles the device's managed/missing report into
    DeviceBook desired state, and answers with sends[]/removes[] the plugin
    must apply and then acknowledge via /sync/ack + /sync/finish.
    A payload WITHOUT "protocol" gets the legacy v1 response (downloads[]/
    deletions[] keyed by queue_id, closed via /sync/confirm) synthesized from
    the same DeviceBook state — kept for one release of plugin lag.
    """
    if payload.get("protocol") != 2:
        return _legacy_sync_handshake(payload, db, current_device)

    now = datetime.utcnow()
    current_device.plugin_version = payload.get("plugin_version") or current_device.plugin_version

    # Spazio sul volume che ospita i libri, dal plugin v0.6.15 in avanti.
    # Un plugin piu' vecchio non manda niente e i valori restano quelli
    # dell'ultima volta (o NULL): meglio un dato vecchio, che si vede essere
    # vecchio dalla data di sync, che nessun dato.
    for campo in ("storage_used", "storage_total", "storage_available"):
        valore = payload.get(campo)
        if isinstance(valore, int) and valore >= 0:
            setattr(current_device, campo, valore)

    # Session serialization: lazily abandon sessions the plugin never closed,
    # then refuse to open a second one while a fresh one is still running.
    db.query(models.DeviceSyncHistory).filter(
        models.DeviceSyncHistory.device_id == current_device.id,
        models.DeviceSyncHistory.outcome == "open",
        models.DeviceSyncHistory.started_at < now - _SYNC_SESSION_ABANDON_AFTER,
    ).update({"outcome": "abandoned", "finished_at": now}, synchronize_session=False)
    blocking = db.query(models.DeviceSyncHistory).filter(
        models.DeviceSyncHistory.device_id == current_device.id,
        models.DeviceSyncHistory.outcome == "open",
        models.DeviceSyncHistory.started_at >= now - _SYNC_SESSION_BLOCK_WINDOW,
    ).first()
    if blocking:
        db.commit()  # persist the lazy abandons + plugin_version anyway
        raise HTTPException(
            status_code=409,
            detail=(
                f"Un'altra sessione di sync è già aperta per questo dispositivo "
                f"(session_id={blocking.session_id}, iniziata {blocking.started_at.isoformat()}Z). "
                f"Chiudila con /sync/finish oppure riprova tra qualche minuto."
            ),
        )

    # Light sync: if the client proves (token match) that nothing changed
    # server-side AND omits managed_books, skip the whole reconciliation pass.
    managed = payload.get("managed_books")
    client_token = payload.get("library_token")
    server_token = _library_token(db, current_device.id)
    light = client_token is not None and client_token == server_token and managed is None

    books_reported, pages_reported, removed_count = 0, 0, 0
    if not light:
        if managed:
            books_reported, pages_reported = _adopt_managed_books(db, current_device, managed)
        missing = payload.get("missing_books")
        if missing:
            removed_count = _mark_missing_books(db, current_device, missing)

    sends = _build_sends(db, current_device)
    removes = _build_removes(db, current_device)
    file_actions = _build_file_actions(db, current_device)
    open_restore_request = _get_open_restore_request(db, current_device.id)
    restore_request = (
        _serialize_restore_request(db, open_restore_request)
        if open_restore_request and open_restore_request.status == "confirmed_admin"
        else None
    )

    session_id = uuid.uuid4().hex
    db.add(models.DeviceSyncHistory(
        device_id=current_device.id, session_id=session_id,
        plugin_version=payload.get("plugin_version"), trigger=payload.get("trigger"),
        books_reported=books_reported,
        downloads_requested=len(sends),
        deletes_requested=len(removes),
        removed_by_device=removed_count,
        pages_reported=pages_reported,
    ))
    current_device.last_sync_at = now
    db.commit()

    log_message(
        "info", "sync",
        f"Handshake v2 da '{current_device.name}' (trigger={payload.get('trigger')}, light={light}): "
        f"{books_reported} gestiti, {len(sends)} da inviare, {len(removes)} da rimuovere, {removed_count} rimossi dal device",
    )
    return {
        "session_id": session_id,
        "library_token": _library_token(db, current_device.id),
        "sends": sends,
        "removes": removes,
        "file_actions": file_actions,
        "restore_request": restore_request,
        "settings": {
            "folder_layout": current_device.folder_layout,
            "write_folder_cover": current_device.write_folder_cover,
            "delete_policy": current_device.delete_policy,
            "report_pages": True,
        },
    }


def _legacy_sync_handshake(payload: dict, db: Session, current_device: models.Device):
    """
    v1 compat shim: same request/response shape the pre-v2 plugin expects,
    but backed by DeviceBook desired state instead of SyncQueue. queue_id is
    the DeviceBook row id, which the untouched /sync/confirm contract maps
    back onto. No history session is opened for legacy handshakes.
    """
    managed = payload.get("managed_books")
    if managed:
        _adopt_managed_books(db, current_device, managed)

    downloads = [
        {
            "queue_id": s["book_id"], "calibre_book_id": s["calibre_book_id"],
            "library": s["library"], "format": s["format"],
            "download_url": s["download_url"], "author": s["author"],
            "title": s["title"], "folder_cover_url": s["folder_cover_url"],
        }
        for s in _build_sends(db, current_device)
    ]
    deletions = [
        {"queue_id": r["book_id"], "calibre_book_id": r["calibre_book_id"], "library": r["library"], "format": r["format"]}
        for r in _build_removes(db, current_device)
    ]

    current_device.last_sync_at = datetime.utcnow()
    db.commit()
    log_message("info", "sync", f"Handshake v1 (legacy) da '{current_device.name}': {len(downloads)} download, {len(deletions)} eliminazioni in coda")
    return {
        "downloads": downloads,
        "deletions": deletions,
        "settings": {
            "folder_layout": current_device.folder_layout,
            "write_folder_cover": current_device.write_folder_cover,
        },
    }


@sync_router.post("/sync/ack")
def koreader_sync_ack(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Per-batch acknowledgement inside a v2 session (repeatable — the plugin can
    ack after every download instead of one giant report at the end). Body:
    {session_id, downloads: [{book_id, ok, path?, pages?, error?}],
     deletions: [{book_id, result: deleted|declined|missing|error, error?}]}.
    book_id is the DeviceBook row id handed out in sends[]/removes[].
    """
    hist = _get_history_session(db, current_device.id, payload.get("session_id"))
    now = datetime.utcnow()

    def _own_row(book_id):
        if book_id is None:
            return None
        return db.query(models.DeviceBook).filter(
            models.DeviceBook.id == book_id,
            models.DeviceBook.device_id == current_device.id,
        ).first()

    applied, skipped = 0, 0
    for item in payload.get("downloads", []):
        row = _own_row(item.get("book_id"))
        if not row:
            skipped += 1
            continue
        if item.get("ok"):
            row.status = "synced"
            row.synced_at = now
            row.last_error = None
            row.removed_at = None
            if item.get("path"):
                row.device_path = item["path"]
            if item.get("pages") is not None:
                row.device_pages = item["pages"]
                row.device_pages_updated_at = now
                hist.pages_reported += 1
            hist.downloads_ok += 1
        else:
            row.status = "send_failed"
            row.last_error = item.get("error") or "download fallito (nessun dettaglio dal plugin)"
            hist.downloads_failed += 1
        applied += 1

    for item in payload.get("deletions", []):
        row = _own_row(item.get("book_id"))
        if not row:
            skipped += 1
            continue
        result = item.get("result")
        if result in ("deleted", "missing"):
            # Confirmed gone (deleted now, or already absent): the desired
            # state is reached, the row disappears — the history keeps the trace.
            db.delete(row)
            hist.deletes_done += 1
        elif result == "declined":
            row.status = "delete_declined"
            row.requested_by = row.requested_by or "server"
            hist.deletes_declined += 1
        elif result == "error":
            # Stays pending_delete: it will be re-offered at the next handshake.
            row.last_error = item.get("error") or "eliminazione fallita (nessun dettaglio dal plugin)"
        else:
            skipped += 1
            continue
        applied += 1

    db.commit()
    return {"status": "ok", "applied": applied, "skipped": skipped}


@sync_router.post("/sync/finish")
def koreader_sync_finish(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """Closes a v2 session: stamps finished_at, computes the outcome from the
    session counters (any failed download → 'partial'; the plugin may force
    'error'), and prunes this device's history down to the newest 100 rows."""
    hist = _get_history_session(db, current_device.id, payload.get("session_id"))
    hist.finished_at = datetime.utcnow()
    outcome = payload.get("outcome")
    if outcome not in ("ok", "partial", "error"):
        outcome = None
    hist.outcome = outcome or ("partial" if hist.downloads_failed > 0 else "ok")

    # Tempi per fase riportati dal plugin. La colonna detail_json esisteva
    # da sempre ed era NULL in ogni riga: nessuno ci scriveva, quindi di una
    # sincronizzazione da 55 secondi non si poteva sapere DOVE fossero
    # andati. Senza questo ogni ottimizzazione del sync e' alla cieca.
    phases = payload.get("phases")
    if isinstance(phases, dict) and phases:
        # Solo numeri, e arrotondati: e' una diagnostica, non un contratto —
        # e non deve diventare un canale per far scrivere al dispositivo
        # oggetti arbitrari nel database.
        clean = {
            str(k)[:40]: round(float(v), 2)
            for k, v in phases.items()
            if isinstance(v, (int, float))
        }
        if clean:
            hist.detail_json = json.dumps({"phases": clean}, ensure_ascii=False)

    stale_ids = [
        row_id for (row_id,) in db.query(models.DeviceSyncHistory.id)
        .filter(models.DeviceSyncHistory.device_id == current_device.id)
        .order_by(models.DeviceSyncHistory.started_at.desc(), models.DeviceSyncHistory.id.desc())
        .offset(_SYNC_HISTORY_KEEP)
        .all()
    ]
    if stale_ids:
        db.query(models.DeviceSyncHistory).filter(
            models.DeviceSyncHistory.id.in_(stale_ids)
        ).delete(synchronize_session=False)
    db.commit()
    log_message("info", "sync", f"Sessione {hist.session_id} chiusa per '{current_device.name}': outcome={hist.outcome}")
    return {"status": "ok", "outcome": hist.outcome}


@sync_router.post("/sync/file-actions/ack")
def ack_file_actions(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Confirms the plugin actually applied the given file_actions[] entries
    (see _build_file_actions) — the "da rivedere" row is deleted once
    acked, same "row disappears when resolved" pattern as DeviceBook's
    pending_delete. Body: {ids: [...]}.
    """
    ids = payload.get("ids") or []
    deleted = (
        db.query(models.DeviceFlaggedBook)
        .filter(models.DeviceFlaggedBook.device_id == current_device.id, models.DeviceFlaggedBook.id.in_(ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"status": "ok", "deleted": deleted}


@sync_router.post("/pages")
def push_device_pages(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    On-device page counts (GUI display only, per §7 decisions — never written
    to Calibre metadata). Body: {books: [{hash, pages}]}. Only updates
    DeviceBook rows this device already has; a hash that doesn't resolve — or
    resolves to a book the device isn't tracking — counts as unresolved.
    """
    now = datetime.utcnow()
    updated, unresolved = 0, 0
    for item in payload.get("books", []):
        file_hash = item.get("hash")
        pages = item.get("pages")
        if not file_hash or pages is None:
            unresolved += 1
            continue
        match = book_hash_service.resolve_first_book_match(db, file_hash, device_id=current_device.id)
        if not match:
            unresolved += 1
            continue
        row = db.query(models.DeviceBook).filter(
            models.DeviceBook.device_id == current_device.id,
            models.DeviceBook.library == match.library,
            models.DeviceBook.calibre_book_id == match.calibre_book_id,
            models.DeviceBook.format == match.format,
        ).first()
        if not row:
            unresolved += 1
            continue
        row.device_pages = pages
        row.device_pages_updated_at = now
        updated += 1
    db.commit()
    return {"updated": updated, "unresolved": unresolved}


@sync_router.post("/books/delivered")
def report_book_delivered(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Device-initiated acquisition: the plugin downloaded a book on its own from
    the on-device catalog browser and tells the server to start managing it.
    Body: {calibre_book_id, library, format, path?, hash?}.
    """
    calibre_book_id = payload.get("calibre_book_id")
    fmt = (payload.get("format") or "").upper()
    library = payload.get("library") or resolve_default_library_folder(db)
    if not calibre_book_id or not fmt:
        raise HTTPException(status_code=400, detail="calibre_book_id e format sono obbligatori")
    if not library:
        raise HTTPException(status_code=404, detail="Nessuna libreria configurata")

    now = datetime.utcnow()
    row = db.query(models.DeviceBook).filter(
        models.DeviceBook.device_id == current_device.id,
        models.DeviceBook.library == library,
        models.DeviceBook.calibre_book_id == calibre_book_id,
        models.DeviceBook.format == fmt,
    ).first()
    if not row:
        row = models.DeviceBook(
            device_id=current_device.id, library=library,
            calibre_book_id=calibre_book_id, format=fmt,
        )
        db.add(row)
    row.status = "synced"
    row.requested_by = "device"
    row.synced_at = now
    row.last_error = None
    row.removed_at = None
    if payload.get("path"):
        row.device_path = payload["path"]
    if payload.get("hash"):
        row.delivery_hash = payload["hash"]
    db.commit()
    log_message("info", "sync", f"'{current_device.name}' ha scaricato dal catalogo il libro {calibre_book_id} ({fmt}, {library})")
    return {"status": "ok", "book_id": row.id}


@sync_router.put("/progress")
def push_reading_progress(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    KOSync-style push: mirrors stock KOReader's plugins/kosync.koplugin
    protocol semantics (percentage + progress string, latest write wins) but
    over our own device-token auth. Body: {hash, format, percentage, progress}.

    A file_hash can resolve to MORE than one (library, calibre_book_id): the
    exact same book uploaded to more than one Kolibre library hashes the
    same (already handled for the device-init "cerca libri non accoppiati"
    scan — this is the same ambiguity, silently resolved by .first() before,
    which could update the wrong library's copy depending on row order).
    Since every match IS the same file, the position genuinely applies to
    all of them — updated together rather than guessing one.
    """
    file_hash = payload.get("hash")
    # "format" non e' nell'elenco: il libro si riconosce dall'hash del file,
    # che il formato ce l'ha gia' dentro. Il messaggio lo chiedeva e nessuno
    # lo controllava.
    if not file_hash or payload.get("percentage") is None or not payload.get("progress"):
        raise HTTPException(status_code=400, detail="hash, percentage e progress sono obbligatori")

    matches = book_hash_service.resolve_book_identities(db, file_hash, device_id=current_device.id)
    if not matches:
        raise HTTPException(status_code=404, detail="Libro non riconosciuto (hash sconosciuto)")

    now = datetime.utcnow()
    for library, calibre_book_id in matches:
        existing = db.query(models.ReadingPosition).filter(
            models.ReadingPosition.user_id == current_device.user_id,
            models.ReadingPosition.library == library,
            models.ReadingPosition.calibre_book_id == calibre_book_id,
        ).first()
        if existing:
            existing.device_id = current_device.id
            existing.device_name = current_device.name
            existing.percentage = payload["percentage"]
            existing.progress = str(payload["progress"])
            existing.updated_at = now
        else:
            db.add(models.ReadingPosition(
                user_id=current_device.user_id,
                library=library, calibre_book_id=calibre_book_id,
                device_id=current_device.id, device_name=current_device.name,
                percentage=payload["percentage"], progress=str(payload["progress"]),
                updated_at=now,
            ))
    db.commit()
    return {"status": "ok"}


@router.delete("/{device_id}/vocabulary")
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
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")

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
                        f"Vocabolario dimenticato ma lo snapshot resta: {exc}")
    log_message("warning", "devices",
                f"Dimenticate {tolte} parole del vocabolario di '{mio.name}' (snapshot rimosso: {snapshot_tolto})")
    return {"status": "ok", "parole_tolte": tolte, "snapshot_rimosso": snapshot_tolto}


@sync_router.get("/progress")
def pull_reading_progress(
    hash: str,
    format: str = None,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    matches = book_hash_service.resolve_book_identities(db, hash, device_id=current_device.id)
    if not matches:
        raise HTTPException(status_code=404, detail="Libro non riconosciuto (hash sconosciuto)")

    # Same ambiguity as push_reading_progress above. push writes the same
    # value to every match, so in the normal case they all agree — but a row
    # created before this fix (or a library linked after the fact) could
    # still diverge, so pick the most recently updated one explicitly
    # instead of an arbitrary .first().
    pos = None
    for library, calibre_book_id in matches:
        candidate = db.query(models.ReadingPosition).filter(
            models.ReadingPosition.user_id == current_device.user_id,
            models.ReadingPosition.library == library,
            models.ReadingPosition.calibre_book_id == calibre_book_id,
        ).first()
        if candidate and (pos is None or (candidate.updated_at or datetime.min) > (pos.updated_at or datetime.min)):
            pos = candidate
    if not pos:
        return {"percentage": None, "progress": None}

    return {
        "percentage": pos.percentage,
        "progress": pos.progress,
        "device_name": pos.device_name,
        "updated_at": pos.updated_at.isoformat() if pos.updated_at else None,
        "is_own_device": pos.device_id == current_device.id,
    }


@sync_router.get("/dictionaries/{lang}/manifest")
def dictionary_manifest_for_device(
    lang: str,
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    "Scarica dizionario sul dispositivo" (main.lua): same manifest +
    per-file-download shape the plugin already uses for its own self-update
    (_downloadAndInstallUpdate) — reused instead of inventing an on-device
    unzip, since KOReader has no archive-extraction library available to
    this plugin (confirmed: the self-update path deliberately avoids one).
    """
    files = stardict_service.device_manifest(lang)
    if not files:
        raise HTTPException(status_code=404, detail=f"Dizionario '{lang}' non installato sul server")
    return {"lang": lang, "files": files}


@sync_router.get("/dictionaries/{lang}/file/{filename}")
def dictionary_file_for_device(
    lang: str,
    filename: str,
    current_device: models.Device = Depends(auth.get_current_device),
):
    path = stardict_service.file_path_for_device(lang, filename)
    if not path:
        raise HTTPException(status_code=404, detail="File non trovato")
    return FileResponse(path, media_type="application/octet-stream")


def _file_md5(path: str) -> str:
    """MD5 completo, letto a blocchi per non tenere in memoria l'intero file."""
    digest = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(256 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@sync_router.get("/backup/state")
def device_backup_state(
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Cosa il server ha gia', per ogni file di backup di questo dispositivo:
    dimensione e hash parziale KOReader.

    Serve al plugin per NON ricaricare cio' che non e' cambiato. Prima
    backupNow caricava dodici file a ogni sincronizzazione, sempre e
    comunque, senza alcun controllo (nel plugin le parole mtime/modification
    comparivano zero volte): ~700 KB e dodici round-trip per file che nella
    maggior parte dei casi — gesti, scorciatoie, ordini di menu — non
    cambiano mai.

    L'hash e' ricalcolato dal file su disco a ogni richiesta, non memorizzato
    da nessuna parte: e' lo stesso valore che il dispositivo calcola con
    ffi/MD5.sumFile, quindi i due sono confrontabili senza che il server
    debba tenere uno stato che puo' disallinearsi. Se un file qui viene
    perso o corrotto, l'hash cambia o sparisce e il dispositivo lo ricarica
    da solo.

    MD5 COMPLETO e non il partial-MD5 usato per i libri, benche' quest'ultimo
    sia gia' in casa e piu' economico. Il partial campiona alcuni blocchi: e'
    perfetto per riconoscere un libro, ma qui la domanda e' "questo file e'
    cambiato?" e la risposta sbagliata significa un backup che smette
    silenziosamente di aggiornarsi. Provato: su SQLite il partial se ne
    accorge comunque (il contatore di modifiche nell'header sta nel primo
    blocco campionato, verificato con UPDATE e INSERT a dimensione
    invariata), ma sui file .lua di impostazioni la garanzia non c'e'. Su
    file da al massimo qualche centinaio di KB la differenza di costo e'
    irrilevante, la differenza di certezza no.
    """
    device_dir = os.path.join(config.BACKUPS_DIR, str(current_device.id))
    files = {}
    if os.path.isdir(device_dir):
        for name in os.listdir(device_dir):
            path = os.path.join(device_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                files[name] = {
                    "size": os.path.getsize(path),
                    "hash": _file_md5(path),
                }
            except OSError:
                continue
    return {"files": files}


@sync_router.post("/backup")
async def upload_device_backup(
    request: Request,
    filename: str,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Raw-bytes backup upload (no multipart — plain request body), one call per
    file. The device decides what's worth backing up (statistics.sqlite3,
    settings.reader.lua, etc. — see main.lua's backupNow); the server just
    stores the latest copy per device, no versioning yet.
    """
    if not _SAFE_BACKUP_FILENAME.match(filename):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Corpo della richiesta vuoto")

    device_dir = os.path.join(config.BACKUPS_DIR, str(current_device.id))
    os.makedirs(device_dir, exist_ok=True)
    with open(os.path.join(device_dir, filename), "wb") as f:
        f.write(body)

    current_device.last_backup_at = datetime.utcnow()
    db.commit()
    log_message("info", "backup", f"Backup '{filename}' ({len(body)} bytes) ricevuto da '{current_device.name}'")

    stats_summary = None
    if filename == "statistics.sqlite3":
        # Best-effort: a malformed/partial statistics.sqlite3 must never
        # fail the backup upload itself, which already succeeded above.
        try:
            stats_summary = stats_service.process_statistics_db(
                os.path.join(device_dir, filename), current_device.user_id, current_device.id, db
            )
            if stats_summary["sessions_added"] or stats_summary["positions_updated"]:
                log_message(
                    "info", "backup",
                    f"Statistiche di lettura da '{current_device.name}': "
                    f"{stats_summary['sessions_added']} nuove sessioni, "
                    f"{stats_summary['positions_updated']} posizioni aggiornate.",
                )
                # Refresh immediato: senza questo, la dashboard resterebbe
                # ferma alla StatsCache precedente finché non scatta il
                # prossimo giro di _refresh_stats_loop (ora giornaliero, non
                # più ogni 10 minuti — vedi main.py). Un device può toccare
                # più librerie nello stesso file (_resolve_book_identities),
                # quindi si aggiornano tutte piuttosto che tracciarne una sola.
                try:
                    stats_service.refresh_stats_cache(db)
                except Exception as e:
                    log_message("warning", "backup", f"Refresh cache statistiche post-upload fallito: {e}")
        except Exception as e:
            log_message("warning", "backup", f"Elaborazione statistics.sqlite3 fallita: {e}")

    vocabulary_summary = None
    if filename == "vocabulary_builder.sqlite3":
        # Same best-effort contract as statistics.sqlite3 above.
        try:
            vocabulary_summary = vocabulary_service.process_vocabulary_db(
                os.path.join(device_dir, filename), current_device.user_id, current_device.id, db
            )
            if vocabulary_summary["words_added"] or vocabulary_summary["words_updated"]:
                log_message(
                    "info", "backup",
                    f"Vocabolario da '{current_device.name}': "
                    f"{vocabulary_summary['words_added']} nuovi termini, "
                    f"{vocabulary_summary['words_updated']} aggiornati.",
                )
        except Exception as e:
            log_message("warning", "backup", f"Elaborazione vocabulary_builder.sqlite3 fallita: {e}")

    return {"status": "ok", "bytes": len(body), "stats": stats_summary, "vocabulary": vocabulary_summary}


@sync_router.get("/stats/state")
def device_stats_state(
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Da dove il dispositivo deve ripartire per le statistiche di lettura.

    Vedi `stats_service.stato_statistiche`: "da" e' l'ultimo istante noto
    meno una finestra di sovrapposizione, non l'ultimo istante secco.
    """
    return stats_service.stato_statistiche(
        os.path.join(config.BACKUPS_DIR, str(current_device.id), "statistics.sqlite3")
    )


@sync_router.post("/stats/incremental")
def upload_stats_incremental(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Le sole righe di `page_stat_data` successive alla filigrana.

    Al posto dei 659 KB del file intero — misurati su un Kindle reale — una
    giornata normale sono 29 byte. Le righe vengono cucite dentro lo stesso
    `statistics.sqlite3` conservato per questo dispositivo, che resta il
    deposito unico: da li' in poi l'elaborazione e' quella di sempre.

    Se il conto non torna (righe o durate totali diverse da quelle dichiarate
    dal dispositivo) la risposta e' `{"risincronizza": true}` e il plugin
    ricarica il file per intero. Una statistica che diverge in silenzio e'
    molto peggio di una salita da 659 KB ogni tanto.
    """
    device_dir = os.path.join(config.BACKUPS_DIR, str(current_device.id))
    db_path = os.path.join(device_dir, "statistics.sqlite3")

    esito = stats_service.cuci_statistiche(
        db_path,
        payload.get("books") or [],
        payload.get("rows") or [],
        payload.get("totals") or {},
    )
    if esito["risincronizza"]:
        log_message("info", "backup",
                    f"Statistiche di '{current_device.name}': serve il file intero ({esito['motivo']})")
        return {"status": "resync", "risincronizza": True, "motivo": esito["motivo"]}

    current_device.last_backup_at = datetime.utcnow()
    db.commit()

    riassunto = None
    if esito["righe_aggiunte"]:
        # Stesso contratto best-effort dell'upload intero: un'elaborazione
        # che fallisce non deve far fallire una consegna gia' riuscita.
        try:
            riassunto = stats_service.process_statistics_db(
                db_path, current_device.user_id, current_device.id, db
            )
            if riassunto["sessions_added"] or riassunto["positions_updated"]:
                log_message(
                    "info", "backup",
                    f"Statistiche di lettura da '{current_device.name}' (incrementale): "
                    f"{esito['righe_aggiunte']} righe nuove, "
                    f"{riassunto['sessions_added']} nuove sessioni, "
                    f"{riassunto['positions_updated']} posizioni aggiornate.",
                )
                try:
                    stats_service.refresh_stats_cache(db)
                except Exception as e:
                    log_message("warning", "backup", f"Refresh cache statistiche post-incrementale fallito: {e}")
        except Exception as e:
            log_message("warning", "backup", f"Elaborazione incrementale fallita: {e}")

    return {"status": "ok", "righe_aggiunte": esito["righe_aggiunte"], "stats": riassunto}


@sync_router.post("/sync/restore-request")
def create_device_restore_request(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Prima delle tre conferme (vedi DeviceRestoreRequest): il device stesso,
    dopo che l'utente ha scelto un dispositivo sorgente e confermato
    localmente ("Resetta a stato di dispositivo" nel plugin), crea la
    richiesta. Non applica nulla qui — serve ancora la conferma admin sul
    frontend e una seconda conferma locale (vedi /sync → restore_request, e
    /sync/restore-request/{id}/complete).
    """
    source_device_id = payload.get("source_device_id")
    if not source_device_id:
        raise HTTPException(status_code=400, detail="source_device_id obbligatorio")
    if source_device_id == current_device.id:
        raise HTTPException(status_code=400, detail="Il dispositivo sorgente non può essere lo stesso dispositivo")
    source = db.query(models.Device).filter(
        models.Device.id == source_device_id, models.Device.user_id == current_device.user_id,
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Dispositivo sorgente non trovato")

    # Una sola richiesta "viva" per target: una nuova sostituisce la precedente.
    existing = _get_open_restore_request(db, current_device.id)
    if existing:
        db.delete(existing)
        db.flush()

    req = models.DeviceRestoreRequest(target_device_id=current_device.id, source_device_id=source_device_id)
    db.add(req)
    db.commit()
    db.refresh(req)
    log_message(
        "info", "devices",
        f"Richiesta di migrazione creata: '{current_device.name}' <- backup di '{source.name}' (id={req.id})",
    )
    return {"status": "ok", "id": req.id}


@sync_router.get("/sync/restore-request/{source_device_id}/file")
def download_restore_request_file(
    source_device_id: int,
    filename: str,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Scarica un singolo file dal backup del dispositivo sorgente — consentito
    solo se esiste una richiesta 'confirmed_admin' per questo device target
    che referenzia esattamente quel source_device_id (mai libero accesso ai
    backup di un altro dispositivo).
    """
    req = _get_open_restore_request(db, current_device.id)
    if not req or req.status != "confirmed_admin" or req.source_device_id != source_device_id:
        raise HTTPException(status_code=403, detail="Nessuna richiesta di migrazione confermata per questo dispositivo sorgente")
    if not _SAFE_BACKUP_FILENAME.match(filename):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    file_path = os.path.join(config.BACKUPS_DIR, str(source_device_id), filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File non presente nel backup del dispositivo sorgente")
    return FileResponse(file_path, filename=filename, media_type="application/octet-stream")


@sync_router.post("/sync/restore-request/{request_id}/complete")
def complete_device_restore_request(
    request_id: int,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Chiude la richiesta dopo che il plugin ha scaricato e scritto localmente
    i file scelti. Nessuna logica di duplicazione statistiche qui: il plugin
    chiama subito dopo il normale backupNow(), che fa già ripartire
    process_statistics_db su statistics.sqlite3 per questo stesso device_id
    (vedi upload_device_backup sopra) — qui si registra solo l'esito.
    """
    req = db.query(models.DeviceRestoreRequest).filter(
        models.DeviceRestoreRequest.id == request_id,
        models.DeviceRestoreRequest.target_device_id == current_device.id,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Richiesta di migrazione non trovata")
    req.status = "done"
    req.completed_at = datetime.utcnow()
    req.files_applied = json.dumps(payload.get("files_applied") or [])
    db.commit()
    log_message("info", "devices", f"Migrazione completata per '{current_device.name}' (request id={req.id})")
    return {"status": "ok"}


@router.get("/{device_id}/backups")
def list_device_backups(
    device_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    device_dir = os.path.join(config.BACKUPS_DIR, str(device_id))
    if not os.path.isdir(device_dir):
        return []
    files = []
    for fname in sorted(os.listdir(device_dir)):
        fpath = os.path.join(device_dir, fname)
        files.append({
            "filename": fname,
            "size": os.path.getsize(fpath),
            "modified_at": datetime.fromtimestamp(os.path.getmtime(fpath)).isoformat(),
        })
    return files


@router.get("/{device_id}/backups/download")
def download_device_backups(
    device_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """Zips whatever this device has backed up so far, for restore purposes."""
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    device_dir = os.path.join(config.BACKUPS_DIR, str(device_id))
    if not os.path.isdir(device_dir) or not os.listdir(device_dir):
        raise HTTPException(status_code=404, detail="Nessun backup disponibile per questo dispositivo")

    # mkstemp + pulizia dopo la risposta, come fa gia' tools.py per gli zip dei
    # plugin e per la stessa ragione. Prima il nome era deterministico
    # (kolibre_backup_device_<id>.zip in /tmp): nessuno lo cancellava, quindi
    # ogni download lasciava in /tmp il statistics.sqlite3 e il
    # settings.reader.lua del dispositivo, leggibili da qualunque processo nel
    # container; e due download dello stesso dispositivo si sovrascrivevano il
    # file a vicenda mentre veniva servito.
    fd, zip_path = tempfile.mkstemp(prefix=f"kolibre_backup_device_{device_id}_", suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for fname in os.listdir(device_dir):
            z.write(os.path.join(device_dir, fname), arcname=fname)

    safe_device_name = re.sub(r"[^A-Za-z0-9_-]", "_", dev.name)
    download_name = f"kolibre_backup_{safe_device_name}_{datetime.utcnow().strftime('%Y%m%d')}.zip"
    return FileResponse(zip_path, filename=download_name, background=BackgroundTask(_elimina_zip_temporaneo, zip_path))


def _elimina_zip_temporaneo(path: str) -> None:
    try:
        os.remove(path)
    except OSError as e:
        log_message("warning", "devices", f"Pulizia zip backup temporaneo fallita per '{path}': {e}")


@sync_router.post("/sync/confirm")
def koreader_sync_confirm(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    v1 compat shim: the old plugin acknowledges applied queue entries by id.
    Since protocol v2 those ids ARE DeviceBook row ids (see the legacy branch
    of /sync), so confirming a download marks the row synced and confirming a
    delete removes it — same transitions as /sync/ack, without a session.
    """
    queue_ids = payload.get("queue_ids", [])
    now = datetime.utcnow()
    rows = db.query(models.DeviceBook).filter(
        models.DeviceBook.id.in_(queue_ids), models.DeviceBook.device_id == current_device.id
    ).all()
    for row in rows:
        if row.status in _SENDABLE_STATUSES:
            row.status = "synced"
            row.synced_at = now
            row.last_error = None
        elif row.status == "pending_delete":
            db.delete(row)
    db.commit()
    return {"status": "ok", "confirmed": len(rows)}


@router.get("/{device_id}/sync-history")
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
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
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
            "started_at": h.started_at.isoformat() if h.started_at else None,
            "finished_at": h.finished_at.isoformat() if h.finished_at else None,
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


@router.get("/{device_id}/flagged-books")
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
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
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
            "flagged_at": r.flagged_at.isoformat() if r.flagged_at else None,
            "pending_action": r.pending_action,
        }
        for r in rows
    ]


def _get_owned_flagged_book(db: Session, device_id: int, flagged_id: int, current_user: models.User) -> models.DeviceFlaggedBook:
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    row = db.query(models.DeviceFlaggedBook).filter(
        models.DeviceFlaggedBook.id == flagged_id, models.DeviceFlaggedBook.device_id == device_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Voce non trovata")
    return row


@router.delete("/{device_id}/flagged-books/{flagged_id}")
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


@router.post("/{device_id}/flagged-books/{flagged_id}/action")
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
        raise HTTPException(status_code=400, detail="action deve essere 'delete', 'overwrite' o 'pair'")
    row = _get_owned_flagged_book(db, device_id, flagged_id, current_user)
    if action == "overwrite":
        library = payload.get("library")
        calibre_book_id = payload.get("calibre_book_id")
        if not library or not calibre_book_id:
            raise HTTPException(status_code=400, detail="library e calibre_book_id sono obbligatori per 'overwrite'")
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
            raise HTTPException(status_code=400, detail="library e calibre_book_id sono obbligatori per 'pair'")
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


@router.post("/{device_id}/flagged-books/bulk-action")
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
        raise HTTPException(status_code=400, detail="Solo l'azione 'delete' è supportata in massa")
    ids = payload.get("ids") or []
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    updated = (
        db.query(models.DeviceFlaggedBook)
        .filter(models.DeviceFlaggedBook.device_id == device_id, models.DeviceFlaggedBook.id.in_(ids))
        .update({"pending_action": "delete"}, synchronize_session=False)
    )
    db.commit()
    return {"status": "ok", "updated": updated}


def _get_owned_device_book(db: Session, device_id: int, book_row_id: int, current_user: models.User) -> models.DeviceBook:
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    row = db.query(models.DeviceBook).filter(
        models.DeviceBook.id == book_row_id, models.DeviceBook.device_id == device_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Libro non trovato su questo dispositivo")
    return row


@router.post("/{device_id}/books/{book_row_id}/acknowledge-removal")
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
        raise HTTPException(status_code=400, detail="Il libro non è in stato 'removed_by_device'")
    db.delete(row)
    db.commit()
    return {"status": "ok"}


@router.post("/{device_id}/books/{book_row_id}/cancel")
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
        raise HTTPException(status_code=400, detail=f"Nessuna azione annullabile: il libro è in stato '{row.status}'")
    db.commit()
    return {"status": "ok"}


@router.post("/{device_id}/books/{book_row_id}/pair")
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
        raise HTTPException(status_code=400, detail="library e calibre_book_id sono obbligatori")
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
