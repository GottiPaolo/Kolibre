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
from typing import Optional, Union
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import config, models, schemas, database, auth
from ..istanti import quando
from starlette.background import BackgroundTask

from ..logging_utils import log_message
from ..calibre.library import CalibreLibrary
from ..services import identita_durevole
from ..services.position_converter.chapter_resolver import resolve_epub_chapter_path, resolve_pdf_chapter_path
from ..services import (book_hash_service, highlight_position, inventario_dispositivo,
                        patch_koreader, permessi, stardict_service, stats_service,
                        text_fingerprint, vocabulary_service)
from ..schemas_risposte import (
    AnnotazioniRicevute, AnnotazioniRiconciliate, AzioneAccodata, AzioniAccodate,
    AzioniSuFileConfermate, BackupRicevuto, BibliotecaPerIlDispositivo,
    CapacitaDelServer, CatalogoSfogliato, DispositivoFratello, DispositivoInElenco,
    DizionariInCoda, Esito, FileDiBackup, FileIdentificato, FileNonIdentificato,
    Handshake, HandshakeLegacy, LibriDaScoprire, LibroConsegnato, LibroDaRivedere,
    LibroSegnalato, LottoConfermato, ManifestDelDizionario, OrfaneMigrate,
    PagineRicevute, PosizionePerIlDispositivo, RichiestaDiRipristinoCreata,
    InventarioDelDispositivo, InventarioRicevuto,
    ScansioneDeiNonAccoppiati, SegnalazioneAccoppiataDaSola, SessioneChiusa,
    SezioneDelCatalogo, SincronizzazioneConfermata, SincronizzazioneNelloStorico,
    StatisticheCucite, StatisticheDaRifare, StatoDeiBackup, StatoDelleStatistiche,
    VocabolarioDimenticato,
)
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
        raise HTTPException(status_code=404, detail="Unknown session_id for this device")
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
        # Prima il nome, poi l'impronta (vedi book_hash_service.resolve_from_item):
        # il plugin manda l'identita' del libro quando ce l'ha, e ce l'ha per
        # tutto cio' che Kolibre gli ha consegnato.
        match = book_hash_service.resolve_from_item(db, item, device_id=device.id)
        if not match:
            continue
        file_hash = item.get("hash")
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
        # Solo se l'impronta c'e' davvero. Da quando il libro si riconosce
        # per nome, il plugin riporta anche le voci di cui non ha saputo
        # calcolare l'impronta — e azzerare quella registrata alla consegna
        # vorrebbe dire buttare via il terzo livello di riconoscimento per un
        # libro che si e' appena riconosciuto benissimo.
        if file_hash:
            row.delivery_hash = file_hash
        if item.get("path"):
            row.device_path = item["path"]
        if item.get("pages") is not None:
            row.device_pages = item["pages"]
            row.device_pages_updated_at = now
            pages_reported += 1
        adopted += 1
    return adopted, pages_reported


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


def _dizionari_in_coda(d: models.Device) -> list:
    """I dizionari che si e' chiesto di mandare a questo lettore.

    Sempre una lista, anche quando la colonna e' NULL o illeggibile: qui,
    al contrario delle patch, non c'e' niente da distinguere fra «non lo so»
    e «nessuno» — in entrambi i casi non c'e' niente da mandare.
    """
    if not d.dizionari_richiesti:
        return []
    try:
        valore = json.loads(d.dizionari_richiesti)
    except (ValueError, TypeError):
        return []
    if not isinstance(valore, list):
        return []
    return [x for x in valore if isinstance(x, str) and x in stardict_service.KNOWN_DICTIONARIES]


def _scrivi_dizionari_in_coda(d: models.Device, lingue: list) -> None:
    d.dizionari_richiesti = json.dumps(lingue) if lingue else None


@router.post(
    "/{device_id}/dictionaries",
    responses={200: {"model": DizionariInCoda}},
)
def accoda_dizionario_per_dispositivo(
    device_id: int,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    «Manda questo dizionario a quel lettore», dal portale.

    **Perche' e' una coda e non un invio.** Un server non puo' raggiungere un
    e-reader: e' il lettore che si fa vivo quando e' accesso e ha la rete.
    Quindi qui si scrive soltanto *cosa dovra' prendere*, e lui lo prende
    alla prima sincronizzazione (vedi la risposta di /sync e
    /sync/dictionaries/ack, che svuota la voce quando e' arrivato).

    Due rifiuti, entrambi per non promettere l'impossibile:
    - una lingua che non conosciamo;
    - un dizionario che il server **non ha installato**: non essendoci i
      file, il lettore chiederebbe un manifest che risponde 404 e
      resterebbe in coda per sempre. Si installa prima da Impostazioni →
      Integrazioni → Dizionari.
    """
    device = _get_owned_device(db, device_id, current_user)
    lang = (payload or {}).get("lang")
    if lang not in stardict_service.KNOWN_DICTIONARIES:
        raise HTTPException(status_code=404, detail=f"Unknown dictionary: '{lang}'")
    if not stardict_service.is_installed(lang):
        raise HTTPException(
            status_code=409,
            detail=f"The '{lang}' dictionary is not installed on the server: install it first from Settings → Integrations.",
        )
    in_coda = _dizionari_in_coda(device)
    if lang not in in_coda:
        in_coda.append(lang)
        _scrivi_dizionari_in_coda(device, in_coda)
        db.commit()
        log_message("info", "devices", f"Dictionary '{lang}' queued for '{device.name}'.")
    return {"status": "ok", "dizionari_richiesti": in_coda}


@router.delete(
    "/{device_id}/dictionaries/{lang}",
    responses={200: {"model": DizionariInCoda}},
)
def annulla_dizionario_per_dispositivo(
    device_id: int,
    lang: str,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Toglie dalla coda un dizionario non ancora arrivato. Non disinstalla
    niente dal lettore: quello che e' gia' la' resta la' — da qui si annulla
    solo una richiesta, e dire il contrario sarebbe una bugia."""
    device = _get_owned_device(db, device_id, current_user)
    in_coda = _dizionari_in_coda(device)
    if lang not in in_coda:
        raise HTTPException(status_code=404, detail=f"The '{lang}' dictionary is not queued for this device")
    in_coda = [x for x in in_coda if x != lang]
    _scrivi_dizionari_in_coda(device, in_coda)
    db.commit()
    return {"status": "ok", "dizionari_richiesti": in_coda}


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
        raise HTTPException(status_code=404, detail="Device not found")
    if payload.folder_layout is not None and payload.folder_layout not in ("author", "flat"):
        raise HTTPException(status_code=400, detail="folder_layout must be 'author' or 'flat'")
    if payload.delete_policy is not None and payload.delete_policy not in ("auto", "ask", "never"):
        raise HTTPException(status_code=400, detail="delete_policy must be 'auto', 'ask' or 'never'")
    for field in ("name", "model", "folder_layout", "write_folder_cover", "delete_policy"):
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


def _get_owned_device(db: Session, device_id: int, current_user: models.User) -> models.Device:
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    return dev


@router.post(
    "/{device_id}/restore-request/confirm",
    responses={200: {"model": Esito}},
)
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
        raise HTTPException(status_code=404, detail="Migration request not found")
    if req.status != "pending_admin":
        raise HTTPException(status_code=400, detail=f"The request is already in state '{req.status}'")
    req.status = "confirmed_admin"
    req.confirmed_at = datetime.utcnow()
    db.commit()
    return {"status": "ok"}


@router.delete(
    "/{device_id}/restore-request",
    responses={200: {"model": Esito}},
)
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
        raise HTTPException(status_code=404, detail="No migration request is in progress")
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
        raise HTTPException(status_code=404, detail="Device not found")
    db.query(models.Device).filter(models.Device.user_id == current_user.id).update({"is_default": False})
    dev.is_default = True
    db.commit()
    db.refresh(dev)
    return dev


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
        if not fmt:
            # v1 allowed a missing format; DeviceBook.format is NOT NULL, so
            # fall back to the book's first available format.
            lib = CalibreLibrary(config.library_path(library))
            formats = lib.get_formats(calibre_book_id)
            if not formats:
                raise HTTPException(status_code=404, detail="The book has no formats available to send")
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


@sync_router.get(
    "/libraries",
    responses={200: {"model": list[BibliotecaPerIlDispositivo]}},
)
def list_libraries_for_device(
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """Device-token-friendly library picker for the plugin's catalog browser
    — returns the `folder_name` slug that /catalog and /books/{id}/download
    expect as `library`, unlike the web UI's /api/kolibre/libraries which is
    display-oriented.

    **Quelle del proprietario del dispositivo** (8/11/2026). Elencava ogni
    biblioteca del server: il Kindle di un utente secondario vedeva nel
    selettore anche i nomi delle biblioteche a cui quell'account non ha
    accesso. I libri non arrivavano — `/catalog` passa dal cancello di
    lettura — ma i nomi si', e un nome e' un dato."""
    proprietario = db.query(models.User).filter(
        models.User.id == current_device.user_id).first()
    rows = permessi.biblioteche_visibili(db, proprietario) if proprietario else []
    return [{"name": row.name, "library": row.folder_name} for row in rows]


@sync_router.get(
    "/siblings",
    responses={200: {"model": list[DispositivoFratello]}},
)
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


@sync_router.get(
    "/capabilities",
    responses={200: {"model": CapacitaDelServer}},
)
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


@sync_router.get(
    "/catalog/sections/{section}",
    responses={200: {"model": SezioneDelCatalogo}},
)
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
        raise HTTPException(status_code=400, detail="section must be 'authors', 'series' or 'tags'")
    if page < 1 or size < 1:
        raise HTTPException(status_code=400, detail="page and size must be >= 1")

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
    """
    Shared shape for every catalog-style response (browse_catalog, and the
    Discover endpoint below) — kept in one place so a field added/renamed
    here never drifts between the two.

    `has_cover` passa per un `bool()`, e non e' pedanteria. Fino al
    05/11/2026 qui usciva il valore grezzo della colonna di Calibre, cioe'
    `0` oppure `1`, mentre lo stesso campo da `/api/kolibre/books` usciva
    `true`/`false` (vedi `books.py`): lo stesso dato con due tipi secondo
    l'indirizzo. Questa risposta la legge un plugin scritto in **Lua**, dove
    **lo zero e' vero** — un `if book.has_cover then` sarebbe entrato anche
    per un libro senza copertina. Nessun client lo leggeva ancora, quindi
    era il momento meno costoso per uniformarlo.
    """
    return {
        "id": b["id"], "title": b["title"], "author": b.get("author"), "formats": b["formats"],
        "series": b.get("series"), "series_index": b.get("series_index"),
        "tags": b.get("tags") or [], "rating": b.get("rating"),
        "pubdate": b.get("pubdate"), "has_cover": bool(b.get("has_cover")),
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


@sync_router.get(
    "/catalog/discover",
    responses={200: {"model": LibriDaScoprire}},
)
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
        raise HTTPException(status_code=400, detail="limit must be >= 1")

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


@sync_router.get(
    "/catalog",
    responses={200: {"model": CatalogoSfogliato}},
)
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
    if not _SAFE_BACKUP_FILENAME.match(filename):
        raise HTTPException(status_code=400, detail="Invalid file name")
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
            # **Due nomi diventano uno.** Questa orfana si ripiega su una nota
            # che esiste gia', quindi il suo nome durevole smette di indicare
            # una riga — ma qualcuno puo' averlo scritto in un file di
            # Obsidian o in un link quando il libro non era ancora accoppiato.
            # Il rimando lo tiene valido.
            identita_durevole.registra_rimando(db, o.id_durevole, existing.id_durevole)
        else:
            db.add(models.Highlight(
                user_id=o.user_id, device_id=o.device_id, library=library, calibre_book_id=calibre_book_id,
                text=o.text, comment=o.comment, chapter=o.chapter, page=o.page,
                koreader_pos0=o.koreader_pos0, koreader_pos1=o.koreader_pos1, color=o.color,
                source="device", position_status=None, created_at=o.created_at,
                # **Il nome si porta dietro.** E' tutto il senso di avere un
                # nome che non e' il numero di riga: qui la riga cambia (quella
                # orfana viene cancellata due righe sotto) ma la nota e' la
                # stessa, e un marcatore scritto prima dell'accoppiamento
                # continua a riconoscerla.
                id_durevole=o.id_durevole,
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
            # Come sopra: la riga `h` se ne va e il suo nome durevole
            # continuerebbe a non significare niente. Da adesso significa la
            # nota sopravvissuta.
            identita_durevole.registra_rimando(db, h.id_durevole, collision.id_durevole)
            db.delete(h)
        else:
            h.library = new_library
            h.calibre_book_id = new_calibre_book_id
            h.cfi_start = None
            h.cfi_end = None
            h.position_status = None
    return len(rows)


@sync_router.post(
    "/annotations",
    responses={200: {"model": AnnotazioniRicevute}},
)
def push_device_annotations(
    payload: dict,
    background: BackgroundTasks,
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
        if not text or not (file_hash or item.get("calibre_book_id")):
            continue
        match = book_hash_service.resolve_from_item(db, item, device_id=current_device.id)
        local_path = item.get("path")
        if not match:
            # L'impronta non risolve: prima di dichiararla orfana si guarda
            # l'elenco dei libri DI QUESTO dispositivo, per percorso.
            #
            # Non e' una congettura come il titolo indovinato dal nome del
            # file: e' una cosa che il server SA perche' l'ha fatta lui. Se
            # esiste una riga DeviceBook per (questo dispositivo, questo
            # percorso), quel file e' quel libro — gliel'abbiamo consegnato
            # noi, a quell'indirizzo.
            #
            # Caso reale che l'ha fatto emergere (04/10/2026): «Nel Paese dei
            # Ciechi» su un Mac che legge da una cartella OneDrive. Il libro
            # risultava inviato e presente sia nel pannello del dispositivo
            # sia nel plugin, con `status: synced` e il percorso identico a
            # quello dell'annotazione — eppure ogni evidenziazione finiva fra
            # le orfane, perche' i tre livelli di risoluzione guardano tutti e
            # tre un'IMPRONTA, e l'impronta di quel file era cambiata sotto
            # (una cartella sincronizzata riscrive i file).
            #
            # L'impronta puo' cambiare; il fatto che quel file sia quel libro
            # no. Questo gradino rende la mappa piu' forte del checksum.
            match = _risolvi_per_percorso_dispositivo(db, current_device.id, local_path)
            if match:
                # Si impara l'impronta nuova, cosi' la prossima volta risolve
                # al primo livello senza ripassare da qui.
                book_hash_service.record_device_hash(
                    db, match.library, match.calibre_book_id, match.format, file_hash
                )
        if not match:
            if local_path and _upsert_orphan_highlight(db, current_device, local_path, file_hash, item):
                orphaned += 1
                orphan_paths.add(local_path)
            else:
                unresolved += 1
            continue

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
        f"From '{current_device.name}': {created} new, {updated} updated, "
        f"{orphaned} not paired (imported anyway), {unresolved} discarded (no path)",
    )
    # Le note appena arrivate non hanno ancora il loro punto nel libro:
    # tradurre l'indirizzo di KOReader vuol dire aprire l'EPUB, troppo lento
    # per farlo qui. Si fa SUBITO DOPO aver risposto, invece di aspettare il
    # giro periodico: il dispositivo non aspetta un millisecondo in piu', e
    # chi apre il lettore trova le note gia' al loro posto.
    if created or updated:
        background.add_task(highlight_position.converti_subito_le_nuove)
    return {
        "status": "ok", "created": created, "updated": updated, "unresolved": unresolved, "orphaned": orphaned,
        "orphan_paths": sorted(orphan_paths),
    }


@sync_router.post(
    "/annotations/reconcile",
    responses={200: {"model": AnnotazioniRiconciliate}},
)
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
        keys = f.get("keys") or []
        if not keys or not (f.get("hash") or f.get("calibre_book_id")):
            continue
        # Qui si CANCELLA, quindi il modo piu' certo di identificare il libro
        # non e' un di piu': risolvere all'altro libro vorrebbe dire mettere
        # nel cestino le note di quello.
        match = book_hash_service.resolve_from_item(db, f, device_id=current_device.id)
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
            f"From '{current_device.name}': {eliminate} annotations deleted on the device, "
            f"moved to the trash here too",
        )
    return {"status": "ok", "deleted": eliminate}


@sync_router.post(
    "/annotations/auto-pair",
    responses={200: {"model": OrfaneMigrate}},
)
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
        raise HTTPException(status_code=400, detail="local_path, file_hash, library and calibre_book_id are required")

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
        f"Auto-pair from '{current_device.name}': {local_path} -> {library}/{calibre_book_id} "
        f"({migrated} notes migrated)",
    )
    return {"status": "ok", "migrated_highlights": migrated}


@sync_router.post(
    "/sync",
    responses={200: {"model": Union[Handshake, HandshakeLegacy]}},
)
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

    # Le userpatch installate sul dispositivo (plugin v0.9.0+). Si scrive solo
    # se il campo c'e': un plugin piu' vecchio non lo manda, e sovrascrivere
    # con "niente" direbbe «nessuna patch installata» — che e' un'affermazione
    # diversa da «non lo ha detto», e sarebbe falsa. Vedi
    # models.Device.patch_installate.
    patch_riportate = payload.get("patches")
    if isinstance(patch_riportate, list):
        pulite = [
            {"file": str(v.get("file")), "sha256": str(v.get("sha256") or "")}
            for v in patch_riportate
            if isinstance(v, dict) and v.get("file")
        ]
        current_device.patch_installate = json.dumps(pulite)

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
                f"Another sync session is already open for this device "
                f"(session_id={blocking.session_id}, started {quando(blocking.started_at)}). "
                f"Close it with /sync/finish, or try again in a few minutes."
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
        f"Handshake v2 from '{current_device.name}' (trigger={payload.get('trigger')}, light={light}): "
        f"{books_reported} handled, {len(sends)} to send, {len(removes)} to remove, {removed_count} removed from the device",
    )
    return {
        "session_id": session_id,
        "library_token": _library_token(db, current_device.id),
        "sends": sends,
        "removes": removes,
        "file_actions": file_actions,
        "restore_request": restore_request,
        # I dizionari chiesti dal portale. Restano nella risposta di ogni
        # sincronizzazione finche' il dispositivo non conferma di averli
        # presi (/sync/dictionaries/ack): se il download si interrompe, al
        # prossimo giro ci riprova da se'.
        "dictionaries": _dizionari_in_coda(current_device),
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
    log_message("info", "sync", f"Handshake v1 (legacy) from '{current_device.name}': {len(downloads)} download, {len(deletions)} deletions queued")
    return {
        "downloads": downloads,
        "deletions": deletions,
        "settings": {
            "folder_layout": current_device.folder_layout,
            "write_folder_cover": current_device.write_folder_cover,
        },
    }


@sync_router.post(
    "/sync/ack",
    responses={200: {"model": LottoConfermato}},
)
def koreader_sync_ack(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Per-batch acknowledgement inside a v2 session (repeatable — the plugin can
    ack after every download instead of one giant report at the end). Body:
    {session_id, downloads: [{book_id, ok, path?, hash?, pages?, error?}],
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
            # **L'impronta MISURATA dal dispositivo su quello che ha appena
            # scaricato.** E' l'unica che valga: `delivery_hash` veniva
            # riempita in `_build_sends` copiando l'impronta ARCHIVIATA, cioe'
            # un'etichetta — e se l'etichetta era stantia il terzo livello di
            # riconoscimento nasceva sbagliato insieme al primo. Solo il
            # dispositivo sa che byte sono arrivati.
            if item.get("hash"):
                row.delivery_hash = item["hash"]
            if item.get("pages") is not None:
                row.device_pages = item["pages"]
                row.device_pages_updated_at = now
                hist.pages_reported += 1
            hist.downloads_ok += 1
        else:
            row.status = "send_failed"
            row.last_error = item.get("error") or "download failed (no detail from the plugin)"
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
            row.last_error = item.get("error") or "deletion failed (no detail from the plugin)"
        else:
            skipped += 1
            continue
        applied += 1

    db.commit()
    return {"status": "ok", "applied": applied, "skipped": skipped}


@sync_router.post(
    "/sync/finish",
    responses={200: {"model": SessioneChiusa}},
)
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
    log_message("info", "sync", f"Sessione {hist.session_id} closed for '{current_device.name}': outcome={hist.outcome}")
    return {"status": "ok", "outcome": hist.outcome}


@sync_router.post(
    "/sync/file-actions/ack",
    responses={200: {"model": AzioniSuFileConfermate}},
)
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


@sync_router.post(
    "/pages",
    responses={200: {"model": PagineRicevute}},
)
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
        pages = item.get("pages")
        if pages is None or not (item.get("hash") or item.get("calibre_book_id")):
            unresolved += 1
            continue
        match = book_hash_service.resolve_from_item(db, item, device_id=current_device.id)
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


@sync_router.post(
    "/books/delivered",
    responses={200: {"model": LibroConsegnato}},
)
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
        raise HTTPException(status_code=400, detail="calibre_book_id and format are required")
    if not library:
        raise HTTPException(status_code=404, detail="No library is configured")

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
    log_message("info", "sync", f"'{current_device.name}' downloaded from the catalogue the book {calibre_book_id} ({fmt}, {library})")
    return {"status": "ok", "book_id": row.id}


@sync_router.put(
    "/progress",
    responses={200: {"model": Esito}},
)
def push_reading_progress(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    KOSync-style push: mirrors stock KOReader's plugins/kosync.koplugin
    protocol semantics (percentage + progress string, latest write wins) but
    over our own device-token auth. Body: {hash, format, percentage, progress},
    piu' due campi nostri e facoltativi: {stato, stato_modificato}.

    **Lo stato del libro, e perche' arriva da qui.** `stato` e' quello che
    KOReader dichiara nel suo sidecar ('reading', 'complete', 'abandoned'):
    e' la risposta che la persona ha dato alla domanda «segnare questo libro
    come finito?». Finora nessuno la chiedeva, e il server se la deduceva
    dalla copertura (vedi api/interventions.py) — una stima al posto di una
    dichiarazione. Viaggia insieme alla posizione perche' e' lo stesso dato
    e lo stesso momento: si chiude un libro, si dice che e' finito, e la
    chiusura e' il momento in cui il plugin manda dov'eri arrivato.

    I campi sono facoltativi di proposito: un plugin piu' vecchio continua a
    mandare solo la posizione, e deve continuare a funzionare. E il valore
    non si traduce — vedi models.ReadingPosition.stato_lettura.

    A file_hash can resolve to MORE than one (library, calibre_book_id): the
    exact same book uploaded to more than one Kolibre library hashes the
    same (already handled for the device-init "cerca libri non accoppiati"
    scan — this is the same ambiguity, silently resolved by .first() before,
    which could update the wrong library's copy depending on row order).
    Since every match IS the same file, the position genuinely applies to
    all of them — updated together rather than guessing one.
    """
    # Il libro si identifica per nome se il plugin lo manda, per impronta
    # altrimenti. "format" da solo non identifica niente e non si controlla.
    if payload.get("percentage") is None or not payload.get("progress"):
        raise HTTPException(status_code=400, detail="percentage and progress are required")
    if not payload.get("hash") and payload.get("calibre_book_id") is None:
        raise HTTPException(status_code=400, detail="the book's identity or its fingerprint is required")

    matches = book_hash_service.resolve_identities_from_item(db, payload, device_id=current_device.id)
    if not matches:
        raise HTTPException(status_code=404, detail="Book not recognised")

    # Si accettano i tre valori di KOReader e nient'altro: uno stato che non
    # si conosce non si scrive, perche' un valore ignoto in quella colonna
    # diventerebbe un «forse finito» che nessuno sa interpretare. Non e' un
    # errore della richiesta — la posizione va salvata comunque — quindi si
    # ignora e si annota.
    STATI_NOTI = ("reading", "complete", "abandoned")
    stato = payload.get("stato")
    if stato is not None and stato not in STATI_NOTI:
        log_message("warning", "devices",
                    f"Unrecognised reading status from '{current_device.name}': {stato!r} (ignorato)")
        stato = None
    # KOReader scrive solo il giorno (`summary.modified` = "2026-11-03").
    # Se e' illeggibile si tiene lo stato e si perde la data, non il
    # contrario: lo stato e' il dato, la data e' il contorno.
    stato_il = None
    grezza = payload.get("stato_modificato")
    if stato and isinstance(grezza, str) and grezza.strip():
        try:
            stato_il = datetime.strptime(grezza.strip()[:10], "%Y-%m-%d")
        except ValueError:
            log_message("warning", "devices",
                        f"Unreadable status date from '{current_device.name}': {grezza!r}")

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
            # Solo se e' arrivato: un plugin che non lo manda non deve
            # cancellare uno stato che un altro dispositivo ha dichiarato.
            if stato:
                existing.stato_lettura = stato
                existing.stato_dichiarato_il = stato_il
            existing.updated_at = now
        else:
            db.add(models.ReadingPosition(
                user_id=current_device.user_id,
                library=library, calibre_book_id=calibre_book_id,
                device_id=current_device.id, device_name=current_device.name,
                percentage=payload["percentage"], progress=str(payload["progress"]),
                stato_lettura=stato, stato_dichiarato_il=stato_il,
                updated_at=now,
            ))
    db.commit()
    return {"status": "ok"}


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


@sync_router.get(
    "/progress",
    responses={200: {"model": PosizionePerIlDispositivo}},
)
def pull_reading_progress(
    hash: str = None,
    format: str = None,
    library: str = None,
    calibre_book_id: int = None,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    # `hash` non e' piu' obbligatorio: un plugin aggiornato chiede la
    # posizione per nome del libro, e il nome non si rompe quando il file
    # viene riscritto da una delle due parti.
    if not hash and calibre_book_id is None:
        raise HTTPException(status_code=400, detail="the book's identity or its fingerprint is required")
    matches = book_hash_service.resolve_identities_from_item(
        db, {"hash": hash, "library": library, "calibre_book_id": calibre_book_id, "format": format},
        device_id=current_device.id,
    )
    if not matches:
        raise HTTPException(status_code=404, detail="Book not recognised")

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
        "updated_at": quando(pos.updated_at),
        "is_own_device": pos.device_id == current_device.id,
        "stato": pos.stato_lettura,
        "stato_modificato": pos.stato_dichiarato_il.date().isoformat() if pos.stato_dichiarato_il else None,
    }


@sync_router.post(
    "/sync/dictionaries/ack",
    responses={200: {"model": Esito}},
)
def conferma_dizionario_dal_dispositivo(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    «Il dizionario e' arrivato»: lo togliamo dalla coda.

    Lo dice il dispositivo e non lo decide il server, per lo stesso motivo
    per cui esiste la conferma dei download dei libri: aver *mandato* i file
    non prova che siano arrivati interi. Il plugin conferma solo dopo aver
    verificato l'impronta di ogni file (vedi downloadDictionary); se non
    conferma, la voce resta in coda e al prossimo giro si riprova.
    """
    lang = (payload or {}).get("lang")
    in_coda = _dizionari_in_coda(current_device)
    if lang in in_coda:
        _scrivi_dizionari_in_coda(current_device, [x for x in in_coda if x != lang])
        db.commit()
        log_message("info", "sync", f"Dictionary '{lang}' installed on '{current_device.name}'.")
    # Nessun errore se non c'era: una conferma ripetuta (due sincronizzazioni
    # sovrapposte) deve essere innocua, non un fallimento.
    return {"status": "ok"}


@sync_router.get(
    "/dictionaries/{lang}/manifest",
    responses={200: {"model": ManifestDelDizionario}},
)
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
        raise HTTPException(status_code=404, detail=f"Dictionary '{lang}' is not installed on the server")
    # Il nome da mostrare viene da qui e non dal dispositivo: il plugin non ha
    # modo di sapere come si chiama il dizionario "it", e un messaggio che
    # dice «dizionario it installato» non e' un messaggio.
    conosciuto = stardict_service.KNOWN_DICTIONARIES.get(lang) or {}
    return {"lang": lang, "display_name": conosciuto.get("display_name") or lang, "files": files}


@sync_router.get("/dictionaries/{lang}/file/{filename}", response_class=FileResponse, responses={200: {"content": {"application/octet-stream": {}}}})
def dictionary_file_for_device(
    lang: str,
    filename: str,
    current_device: models.Device = Depends(auth.get_current_device),
):
    path = stardict_service.file_path_for_device(lang, filename)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="application/octet-stream")


def _file_md5(path: str) -> str:
    """MD5 completo, letto a blocchi per non tenere in memoria l'intero file."""
    digest = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(256 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@sync_router.get(
    "/backup/state",
    responses={200: {"model": StatoDeiBackup}},
)
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


@sync_router.post(
    "/backup",
    responses={200: {"model": BackupRicevuto}},
)
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
        raise HTTPException(status_code=400, detail="Invalid file name")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body")

    device_dir = os.path.join(config.BACKUPS_DIR, str(current_device.id))
    os.makedirs(device_dir, exist_ok=True)
    with open(os.path.join(device_dir, filename), "wb") as f:
        f.write(body)

    current_device.last_backup_at = datetime.utcnow()
    db.commit()
    log_message("info", "backup", f"Backup '{filename}' ({len(body)} bytes) received from '{current_device.name}'")

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
                    f"Reading statistics from '{current_device.name}': "
                    f"{stats_summary['sessions_added']} new sessions, "
                    f"{stats_summary['positions_updated']} positions updated.",
                )
                # Refresh immediato: senza questo, la dashboard resterebbe
                # ferma alla StatsCache precedente finché non scatta il
                # prossimo giro di _refresh_stats_loop (ora giornaliero, non
                # più ogni 10 minuti — vedi main.py).
                #
                # Solo le biblioteche che QUESTO deposito ha toccato: un
                # dispositivo può toccarne più di una nello stesso file
                # (_resolve_book_identities), e ora è il riassunto a dirlo
                # invece di rifarle tutte per prudenza. Misurato, un
                # ricalcolo completo costa 772 ms su quattro biblioteche.
                try:
                    stats_service.refresh_stats_cache(db, stats_summary.get("biblioteche"))
                except Exception as e:
                    log_message("warning", "backup", f"Statistics cache refresh after the upload failed: {e}")
        except Exception as e:
            log_message("warning", "backup", f"Processing statistics.sqlite3 failed: {e}")

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
                    f"Vocabulary from '{current_device.name}': "
                    f"{vocabulary_summary['words_added']} new terms, "
                    f"{vocabulary_summary['words_updated']} updated.",
                )
        except Exception as e:
            log_message("warning", "backup", f"Processing vocabulary_builder.sqlite3 failed: {e}")

    return {"status": "ok", "bytes": len(body), "stats": stats_summary, "vocabulary": vocabulary_summary}


@sync_router.get(
    "/stats/state",
    responses={200: {"model": StatoDelleStatistiche}},
)
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


@sync_router.post(
    "/stats/incremental",
    responses={200: {"model": Union[StatisticheCucite, StatisticheDaRifare]}},
)
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
                    f"Statistics of '{current_device.name}': the whole file is needed ({esito['motivo']})")
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
                    f"Reading statistics from '{current_device.name}' (incremental): "
                    f"{esito['righe_aggiunte']} new rows, "
                    f"{riassunto['sessions_added']} new sessions, "
                    f"{riassunto['positions_updated']} positions updated.",
                )
                try:
                    # Solo le biblioteche toccate — vedi il gemello nella
                    # salita del file intero, e refresh_stats_cache.
                    stats_service.refresh_stats_cache(db, riassunto.get("biblioteche"))
                except Exception as e:
                    log_message("warning", "backup", f"Statistics cache refresh after the incremental sync failed: {e}")
        except Exception as e:
            log_message("warning", "backup", f"Incremental processing failed: {e}")

    return {"status": "ok", "righe_aggiunte": esito["righe_aggiunte"], "stats": riassunto}


@sync_router.post(
    "/sync/restore-request",
    responses={200: {"model": RichiestaDiRipristinoCreata}},
)
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
        raise HTTPException(status_code=400, detail="source_device_id is required")
    if source_device_id == current_device.id:
        raise HTTPException(status_code=400, detail="The source device cannot be the device itself")
    source = db.query(models.Device).filter(
        models.Device.id == source_device_id, models.Device.user_id == current_device.user_id,
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source device not found")

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
        f"Migration request created: '{current_device.name}' <- backup of '{source.name}' (id={req.id})",
    )
    return {"status": "ok", "id": req.id}


@sync_router.get("/sync/restore-request/{source_device_id}/file", response_class=FileResponse, responses={200: {"content": {"application/octet-stream": {}}}})
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
        raise HTTPException(status_code=403, detail="No confirmed migration request for this source device")
    if not _SAFE_BACKUP_FILENAME.match(filename):
        raise HTTPException(status_code=400, detail="Invalid file name")
    file_path = os.path.join(config.BACKUPS_DIR, str(source_device_id), filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="That file is not in the source device's backup")
    return FileResponse(file_path, filename=filename, media_type="application/octet-stream")


@sync_router.post(
    "/sync/restore-request/{request_id}/complete",
    responses={200: {"model": Esito}},
)
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
        raise HTTPException(status_code=404, detail="Migration request not found")
    req.status = "done"
    req.completed_at = datetime.utcnow()
    req.files_applied = json.dumps(payload.get("files_applied") or [])
    db.commit()
    log_message("info", "devices", f"Migration completed for '{current_device.name}' (request id={req.id})")
    return {"status": "ok"}


@router.get(
    "/{device_id}/backups",
    responses={200: {"model": list[FileDiBackup]}},
)
def list_device_backups(
    device_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    device_dir = os.path.join(config.BACKUPS_DIR, str(device_id))
    if not os.path.isdir(device_dir):
        return []
    files = []
    for fname in sorted(os.listdir(device_dir)):
        fpath = os.path.join(device_dir, fname)
        files.append({
            "filename": fname,
            "size": os.path.getsize(fpath),
            # `tz=timezone.utc` non e' un ornamento: `fromtimestamp` senza fuso
            # da' l'ora LOCALE della macchina, e dichiararla UTC sposterebbe
            # l'istante di tutto l'offset. Qui si chiede in UTC alla fonte.
            "modified_at": quando(datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)),
        })
    return files


@router.get("/{device_id}/backups/download", response_class=FileResponse, responses={200: {"content": {"application/zip": {}}}})
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
        raise HTTPException(status_code=404, detail="Device not found")
    device_dir = os.path.join(config.BACKUPS_DIR, str(device_id))
    if not os.path.isdir(device_dir) or not os.listdir(device_dir):
        raise HTTPException(status_code=404, detail="No backup available for this device")

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
        log_message("warning", "devices", f"Cleaning up the temporary backup zip failed for '{path}': {e}")


@sync_router.post(
    "/sync/confirm",
    responses={200: {"model": SincronizzazioneConfermata}},
)
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


def _risolvi_per_percorso_dispositivo(db: Session, device_id: int, local_path: Optional[str]):
    """
    Il libro che QUESTO dispositivo tiene a QUESTO percorso, se c'e'.

    E' l'ultimo gradino prima di dichiarare orfana un'annotazione, e il solo
    che non passa da un'impronta. Vale perche' la riga DeviceBook la scrive il
    server quando consegna il file: non e' una somiglianza, e' un registro di
    cio' che e' stato fatto.

    Si escludono le righe segnate come rimosse dal dispositivo: quel percorso
    puo' essere stato riusato per un altro libro, e in quel caso non si sa piu'
    niente — meglio un'orfana che un'attribuzione sbagliata.

    Se per lo stesso percorso ci fossero piu' righe vive non si sceglie: un
    percorso che punta a due libri e' una contraddizione, e indovinare qui
    vorrebbe dire scrivere l'evidenziazione nel libro sbagliato.
    """
    if not local_path:
        return None
    righe = (
        db.query(models.DeviceBook)
        .filter(
            models.DeviceBook.device_id == device_id,
            models.DeviceBook.device_path == local_path,
            models.DeviceBook.removed_at.is_(None),
        )
        .all()
    )
    if len(righe) != 1:
        return None
    r = righe[0]
    return book_hash_service.BookMatch(library=r.library, calibre_book_id=r.calibre_book_id, format=r.format)


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


# ── L'inventario della cartella dei libri ────────────────────────────────

def _intero(valore):
    """Un numero intero, o `None`. Mai un'eccezione: questi valori arrivano da
    un dispositivo, e un campo scritto male non deve far fallire l'inventario
    di duecento file."""
    try:
        return int(valore)
    except (TypeError, ValueError):
        return None


def _frazione(valore):
    """Una frazione fra 0 e 1, o `None`. Si riporta nei limiti invece di
    rifiutarla: `percent_finished` lo scrive KOReader, e un 1.0000001 non e'
    un motivo per perdere la riga."""
    try:
        return max(0.0, min(float(valore), 1.0))
    except (TypeError, ValueError):
        return None


def _riga_di_inventario(f: models.FileSulDispositivo) -> dict:
    """La riga come la vedono il raggruppamento e chi legge."""
    return {
        "local_path": f.local_path,
        "format": f.format,
        "file_hash": f.file_hash,
        "size_bytes": f.size_bytes,
        "percent_finished": f.percent_finished,
        "stato_lettura": f.stato_lettura,
        "stato_modificato": f.stato_modificato,
        "annotazioni": f.annotazioni,
        "pagine": f.pagine,
        "ultima_posizione": f.ultima_posizione,
        "visto_il": quando(f.visto_il),
    }


def _identita_di(db: Session, device_id: int):
    """
    Da una riga d'inventario al libro che rappresenta, o `None`.

    **Tre vie, e la terza e' quella che serve davvero.** L'impronta viva
    riconosce un file identico a quello che il server ha adesso; lo storico
    riconosce una copia precedente (il server riscrive i file quando ci
    incorpora metadati o copertina); e il **percorso** riconosce un file che
    il server sa di aver consegnato a QUESTO dispositivo. Misurato sul
    Kindle di Paolo: su sette coppie di doppioni, in **sei** una delle due
    impronte non risolveva ne' per la prima via ne' per la seconda.

    Chi non si riconosce torna `None`, e **non diventa mai un candidato alla
    cancellazione**: su uno di quei file c'erano cinquantasei ore di lettura.
    """
    per_percorso = {
        r.device_path: (r.library, r.calibre_book_id, r.format)
        for r in db.query(models.DeviceBook).filter(
            models.DeviceBook.device_id == device_id,
            models.DeviceBook.device_path.isnot(None),
        ).all()
    }

    def identita(riga: dict):
        impronta = riga.get("file_hash")
        if impronta:
            viva = db.query(models.BookHash).filter(
                models.BookHash.file_hash == impronta).first()
            if viva:
                # **La prova, e si segna sulla riga.** Un file la cui impronta
                # e' quella VIVA e' byte per byte identico a quello che il
                # server ha adesso; le altre vie sono indizi. Serve a scegliere
                # quale copia tenere (vedi `valore_di_lettura`), e misurato sui
                # venti gruppi veri del Kindle di Paolo era l'unico criterio
                # che sapeva decidere in tutti e venti.
                riga["impronta_viva"] = True
                return (viva.library, viva.calibre_book_id, viva.format)
            storica = db.query(models.BookHashHistory).filter(
                models.BookHashHistory.file_hash == impronta).first()
            if storica:
                return (storica.library, storica.calibre_book_id, storica.format)
        return per_percorso.get(riga.get("local_path"))

    return identita


def _conferma_il_nome(db: Session):
    """
    Per ogni (biblioteca, libro), i titoli con cui un suo file potrebbe
    chiamarsi — il **titolo** e il **titolo per ordinamento**, perche' il
    plugin ha usato prima l'uno e poi l'altro.

    Si legge una biblioteca alla volta e una volta sola: chiedere il titolo
    libro per libro su duecento file sarebbe un N+1 su disco.
    """
    titoli: dict = {}

    def conferma(riga: dict, chiave: tuple) -> bool:
        cartella = chiave[0]
        if cartella not in titoli:
            try:
                titoli[cartella] = {
                    b["id"]: [b.get("title"), b.get("title_sort")]
                    for b in CalibreLibrary(config.library_path(cartella)).list_books()
                }
            except Exception:
                titoli[cartella] = {}
        suoi = titoli[cartella].get(chiave[1])
        if not suoi:
            # Biblioteca illeggibile o libro non piu' in catalogo: non si
            # afferma niente. Senza il titolo il controllo non si puo' fare,
            # e dire «non torna» sarebbe un'accusa senza prova.
            return True
        return inventario_dispositivo.il_nome_dice_il_libro(riga["local_path"], suoi)

    return conferma


def _inventario_raggruppato(db: Session, device_id: int) -> dict:
    righe_db = db.query(models.FileSulDispositivo).filter(
        models.FileSulDispositivo.device_id == device_id).all()
    righe = [_riga_di_inventario(f) for f in righe_db]
    gruppi = inventario_dispositivo.raggruppa(
        righe, _identita_di(db, device_id), _conferma_il_nome(db))
    return {
        "aggiornato_il": quando(max((f.visto_il for f in righe_db if f.visto_il), default=None)),
        "riassunto": inventario_dispositivo.riassunto(gruppi, len(righe)),
        "doppioni": gruppi["doppioni"],
        "sconosciuti": gruppi["sconosciuti"],
        "da_salvare": gruppi["da_salvare"],
        "da_guardare": gruppi["da_guardare"],
    }


@sync_router.post(
    "/inventory",
    responses={200: {"model": InventarioRicevuto}},
)
def ricevi_inventario(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Cosa c'e' davvero nella cartella dei libri di questo dispositivo.

    Corpo: `{files: [{path, hash, format, size, percent_finished, status,
    status_modified, annotations, pages, last_xpointer}]}`.

    **E' un'istantanea e sostituisce quella di prima.** Un file che non viene
    piu' riportato non c'e' piu', e tenerne la riga direbbe una cosa falsa.
    Per questo si cancella tutto e si riscrive, invece di aggiornare: un
    inventario a metà e' peggio di nessun inventario.

    **Non cancella e non propone niente sul dispositivo.** Risponde solo i
    numeri — ed e' la misura che prima non esisteva: finche' non c'era,
    nessuno sapeva quanti file ci fossero davvero su quel lettore.

    Un file senza percorso si salta invece di far fallire tutto: su duecento
    file, uno illeggibile non deve buttare via gli altri centonovantanove.
    """
    arrivati = payload.get("files") or []
    adesso = datetime.utcnow()

    db.query(models.FileSulDispositivo).filter(
        models.FileSulDispositivo.device_id == current_device.id
    ).delete(synchronize_session=False)

    visti = set()
    for voce in arrivati:
        if not isinstance(voce, dict):
            continue
        percorso = voce.get("path")
        if not percorso or percorso in visti:
            continue  # due volte lo stesso percorso non e' possibile, ma non si fida
        visti.add(percorso)
        db.add(models.FileSulDispositivo(
            device_id=current_device.id,
            local_path=percorso,
            file_hash=voce.get("hash") or None,
            format=(voce.get("format") or "").upper() or "?",
            size_bytes=_intero(voce.get("size")),
            percent_finished=_frazione(voce.get("percent_finished")),
            stato_lettura=voce.get("status") or None,
            stato_modificato=voce.get("status_modified") or None,
            annotazioni=_intero(voce.get("annotations")),
            pagine=_intero(voce.get("pages")),
            ultima_posizione=voce.get("last_xpointer") or None,
            visto_il=adesso,
        ))
    db.commit()

    esito = _inventario_raggruppato(db, current_device.id)
    r = esito["riassunto"]
    log_message(
        "info", "devices",
        f"Inventory from '{current_device.name}': {r['file_letti']} file, "
        f"{r['libri_in_piu_copie']} books in more than one copy ({r['copie_in_eccesso']} extra copies), "
        f"{r['sconosciuti']} unknown, {r['da_salvare']} to save",
    )
    return {"status": "ok", "riassunto": r}


@router.get(
    "/{device_id}/inventory",
    responses={200: {"model": InventarioDelDispositivo}},
)
def inventario_del_dispositivo(
    device_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    L'inventario confrontato con quello che il server sa.

    Il confronto **non si conserva**: si rifa' qui, sulle impronte di adesso.
    Conservarlo vorrebbe dire mostrare una decisione presa su dati di ieri —
    e fra un inventario e il momento in cui si guarda la pagina il server
    puo' aver riscritto dei file.

    Su un dispositivo che non ha mai mandato un inventario risponde la stessa
    forma con tutto a zero e `aggiornato_il` nullo, non un 404: «non lo ha
    mai fatto» e' una risposta, non un errore.
    """
    _get_owned_device(db, device_id, current_user)
    return _inventario_raggruppato(db, device_id)
