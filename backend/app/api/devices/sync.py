"""
Il protocollo di sincronizzazione col plugin KOReader.

Il mestiere: la conversazione periodica tra il lettore e il server — chi
sei, cosa hai a bordo, cosa ti mando, cosa togli — autenticata SEMPRE col
token di dispositivo (mai col JWT di una persona). Questo modulo e'
l'implementazione lato server di quel dialogo. (Trasloco del 20/11/2026:
prima era tutto in api/devices.py.)

Le rotte:
* POST /api/kolibre/devices/sync — l'handshake: v2 apre una sessione
  tracciata (DeviceSyncHistory) e risponde con sends[]/removes[]; un
  payload senza "protocol" riceve la risposta legacy v1;
* POST .../sync/ack e .../sync/finish — gli esiti, lotto per lotto, e la
  chiusura della sessione v2;
* POST .../sync/confirm — la conferma del protocollo legacy v1;
* POST .../sync/file-actions/ack — l'esito delle azioni sui file;
* POST .../pages — le stime di pagine contate dal dispositivo;
* POST .../books/removed e .../books/delivered — un libro tolto o arrivato;
* GET  .../libraries, .../siblings, .../capabilities — le biblioteche
  dell'utente, gli altri suoi dispositivi, cosa sa fare questo server.

Chi le chiama: solo il plugin. Le regole trasversali del mestiere:
* idempotenza — il plugin puo' ripetere un report o un ack senza fare
  danni: lo stato desiderato vive in DeviceBook e ogni report viene
  riconciliato, non applicato ciecamente (vedi `_adopt_managed_books` e
  `_STICKY_STATUSES`: "ho ancora il file" non annulla una rimozione
  decisa);
* il server non si fida dell'eta' del dato — un campo assente in un
  payload vecchio non sovrascrive mai quello che il server sa gia';
* ogni sessione v2 lascia storico (potato a `_SYNC_HISTORY_KEEP` righe),
  ed e' lo stesso storico che la webapp rilegge da
  GET /api/devices/{id}/sync-history (management).
"""

import hashlib
import json
import uuid

from typing import Union
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import config, models, database, auth
from ...istanti import quando

from ...logging_utils import log_message
from ...calibre.library import CalibreLibrary
from ...calibre.connection import PAGE_COUNT_COLUMN_LABEL
from ...services import book_hash_service, permessi
from ...schemas_risposte import (
    AzioniSuFileConfermate, BibliotecaPerIlDispositivo,
    CapacitaDelServer, DispositivoFratello, Handshake, HandshakeLegacy,
    LibroConsegnato, LibroToltoDalDispositivo, LottoConfermato,
    PagineRicevute, SessioneChiusa, SincronizzazioneConfermata,
)
from ..libraries import resolve_default_library_folder

from ._shared import (
    sync_router, _SENDABLE_STATUSES, _SYNC_HISTORY_KEEP,
    _dizionari_in_coda, _get_open_restore_request,
    _serialize_restore_request,
)


# --- Sync protocol v2 helpers (session-based handshake) ---


# Statuses a managed_books report must NOT flip back to 'synced': a device
# reporting "I still hold this file" is expected while a delete is pending or
# was declined — it must not silently cancel the desired removal.
_STICKY_STATUSES = ("pending_delete", "delete_declined")


_SYNC_SESSION_BLOCK_WINDOW = timedelta(minutes=10)   # a newer open session than this blocks a new handshake


_SYNC_SESSION_ABANDON_AFTER = timedelta(hours=1)     # open sessions older than this get lazily abandoned


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


def _stime_delle_pagine(righe) -> dict:
    """{(biblioteca, id libro): stima del server}, per un gruppo di righe
    DeviceBook — una query per biblioteca, non una per libro.

    **Perche' il server deve mandare la sua stima, visto che il lettore sa
    contare le pagine da se'.** Sono due numeri diversi e servono a due cose
    diverse. Il conteggio di KOReader dipende da come TU leggi: carattere,
    corpo, margini, orientamento. Cambi il font e cambia. La stima del
    server viene dal testo del libro ed e' la stessa su ogni dispositivo:
    e' l'unica con cui si possono confrontare due libri fra loro, ed e'
    quella che da' la lunghezza alla barra nella UI. Se la barra usasse il
    conteggio del lettore cambierebbe lunghezza dopo la prima apertura del
    libro — cioe' mentirebbe proprio nel momento in cui la guardi.

    Niente valore: niente chiave. La UI non disegna mai una barra finta, e
    `None` nel manifesto e' indistinguibile da "non lo so".
    """
    per_biblioteca = {}
    for r in righe:
        per_biblioteca.setdefault(r.library, set()).add(r.calibre_book_id)
    stime = {}
    for nome, ids in per_biblioteca.items():
        try:
            valori = CalibreLibrary(config.library_path(nome)).get_custom_column_values(
                PAGE_COUNT_COLUMN_LABEL, list(ids))
        except Exception as e:
            # Una biblioteca che non si apre non deve far fallire la
            # sincronizzazione: si perde la barra, non il giro.
            log_message("warning", "sync", f"Page estimates unavailable for library '{nome}': {e}")
            continue
        for cid, valore in valori.items():
            if valore:
                stime[(nome, cid)] = int(valore)
    return stime


def _build_sends(db: Session, device: models.Device) -> list:
    """sends[] for the handshake response: everything the server wants ON the
    device that isn't there yet. Stamps delivery_hash on each row now, so the
    device can later prove (by hash) it holds exactly the delivered file."""
    rows = db.query(models.DeviceBook).filter(
        models.DeviceBook.device_id == device.id,
        models.DeviceBook.status.in_(_SENDABLE_STATUSES),
    ).all()
    stime = _stime_delle_pagine(rows)
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
            # Nome distinto da `pages` apposta: nel manifesto del lettore
            # `pages` e' gia' il conteggio di KOReader, e i due numeri non
            # si sovrascrivono a vicenda. Vedi `_stime_delle_pagine`.
            "server_pages": stime.get((row.library, row.calibre_book_id)),
        })
    return sends


def _stime_per_il_manifesto(db: Session, device: models.Device) -> dict:
    """{"<biblioteca>:<id>:<FORMATO>": stima}, per i libri che il lettore ha
    gia'. E' la chiave del manifesto del plugin, costruita uguale.

    **Perche' non basta mandarla nella consegna.** La stima viaggia con il
    libro solo quando il libro parte. Tutti i libri gia' scaricati — sul
    Kindle di Paolo sono trecento — sono arrivati prima che questo campo
    esistesse, e senza questa mappa resterebbero per sempre senza barra:
    l'unico modo per dargliela sarebbe cancellarli e riscaricarli.

    Si manda a ogni giro, non una volta sola, e costa una query per
    biblioteca. Cosi' si aggiorna da se' anche quando il server ricalcola le
    stime: «Ricalcola le pagine» sul server e i lettori si allineano al
    giro dopo, senza nessun meccanismo in piu'.
    """
    righe = db.query(models.DeviceBook).filter(
        models.DeviceBook.device_id == device.id,
        models.DeviceBook.status.notin_(_SENDABLE_STATUSES),
    ).all()
    stime = _stime_delle_pagine(righe)
    fuori = {}
    for r in righe:
        valore = stime.get((r.library, r.calibre_book_id))
        if valore:
            fuori["%s:%s:%s" % (r.library, r.calibre_book_id, (r.format or "").upper())] = valore
    return fuori


def _consegne_per_il_manifesto(db: Session, device: models.Device) -> dict:
    """{"<biblioteca>:<id>:<FORMATO>": secondi}, **quando il server ha
    consegnato quel libro a QUESTO lettore**. Stessa chiave del manifesto del
    plugin, come `_stime_per_il_manifesto`.

    **Perche' il server deve dirlo, misurato il 17/11/2026.** Il plugin
    scriveva una sua data (`downloaded_at`) e il pannello «ultimi invii» la
    usava per ordinare. Solo che quella data non e' la consegna: e' **il
    momento in cui la riga del manifesto e' stata scritta**, e il manifesto si
    scrive anche quando il libro sul dispositivo c'era gia' e Kolibre lo
    riconosce (`_linkHashMatch`), o quando una vecchia migrazione adotta in
    blocco quello che trova. In quei due casi la data e' quella dell'adozione,
    e decine di libri finiscono nello stesso secondo: il pannello li mostra in
    un ordine che non significa niente. Misurato sul Mac di Paolo: 25 libri su
    29 in due soli istanti.

    Il server invece lo sa per davvero: `DeviceBook.synced_at` e' scritto in
    `/sync/ack` quando il download riesce. Sul Kindle di Paolo quelle date
    sono sparse su diciannove giorni fra luglio e novembre — cioe' la storia
    vera, che il manifesto del lettore non ha.

    **In secondi e non in ISO**, al contrario di tutto il resto dell'API: il
    plugin non ha un lettore di date e questo numero gli serve per fare
    conti e per `os.date`. Un intero non ha fusi da sbagliare — che e' il
    problema che la regola ISO risolve altrove (vedi `istanti.py`).

    Si manda a ogni giro come le stime, e per la stessa ragione: i libri
    arrivati prima che questo campo esistesse non hanno altro modo di
    saperlo.
    """
    righe = db.query(models.DeviceBook).filter(
        models.DeviceBook.device_id == device.id,
        models.DeviceBook.status.notin_(_SENDABLE_STATUSES),
        models.DeviceBook.synced_at.isnot(None),
    ).all()
    fuori = {}
    for r in righe:
        chiave = "%s:%s:%s" % (r.library, r.calibre_book_id, (r.format or "").upper())
        fuori[chiave] = int(r.synced_at.replace(tzinfo=timezone.utc).timestamp())
    return fuori


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
        # Le stime del server per i libri che il lettore ha GIA'. Non e' un
        # doppione di `sends[].server_pages`: quella riguarda i libri in
        # partenza, questa quelli gia' arrivati. Vedi
        # `_stime_per_il_manifesto` per il perche' di entrambe.
        "server_pages": _stime_per_il_manifesto(db, current_device),
        # **Quando ciascun libro e' stato consegnato a QUESTO lettore.** Il
        # plugin da solo non lo sa: la sua data e' quella in cui ha scritto
        # la riga del manifesto, che per un libro adottato invece che
        # consegnato e' tutt'altro momento. Vedi `_consegne_per_il_manifesto`.
        "delivered_at": _consegne_per_il_manifesto(db, current_device),
        "file_actions": file_actions,
        "restore_request": restore_request,
        # I dizionari chiesti dal portale. Restano nella risposta di ogni
        # sincronizzazione finche' il dispositivo non conferma di averli
        # presi (/sync/dictionaries/ack): se il download si interrompe, al
        # prossimo giro ci riprova da se'.
        "dictionaries": _dizionari_in_coda(current_device),
        "settings": {
            # Zeppa di compatibilita' (20/11/2026, punto B8): l'opzione
            # folder_layout non esiste piu' — sui 4 lettori reali e' sempre
            # stata "author", e il layout e' quello: una cartella per autore,
            # i suoi libri dentro, senza sottocartelle per libro. Ma il
            # plugin fino alla 0.25.0 la legge da QUI
            # (kolibre_sync.lua: settings.folder_layout or "author"), quindi
            # il campo resta, hardcoded, fino alla rottura d'API di B1 —
            # quando l'API passera' a 3, questo campo muore.
            "folder_layout": "author",
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
            # Stessa zeppa del handshake v2 qui sopra (20/11/2026): il
            # plugin pre-v2 legge folder_layout da questa risposta. Muore
            # con la rottura d'API di B1.
            "folder_layout": "author",
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
    "/books/removed",
    responses={200: {"model": LibroToltoDalDispositivo}},
)
def report_book_removed(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    «Questo lettore non vuole piu' questo libro»: lo chiede il plugin, quando
    si tiene premuto un libro nella vista Kolibre e si sceglie «elimina dal
    dispositivo». Corpo: l'identita' del libro, come per `/progress`
    ({hash} oppure {library, calibre_book_id}, piu' {format} facoltativo).

    **Perche' il dispositivo deve passare da qui e non cancellare e basta**
    (ed e' la ragione per cui questo endpoint esiste). Lo stato desiderato —
    «quali libri stanno su questo lettore» — lo tiene il server: e' lui che
    al prossimo handshake offre al dispositivo quello che gli manca. Un
    plugin che cancellasse il file per conto suo si vedrebbe **riconsegnare
    lo stesso libro** alla sincronizzazione dopo, e chi ha premuto «elimina»
    non lo capirebbe mai. Quindi la cancellazione comincia qui, e il file
    sparisce dopo.

    **Il dispositivo poteva gia' AGGIUNGERE** da se' (`/books/delivered`, lo
    sfoglia-catalogo sul lettore): questa e' l'operazione simmetrica, e la
    riga che nasce la' con `requested_by = "device"` se ne va qui.

    **Una riga mai consegnata non si segna, si butta.** Se il libro era in
    coda di invio e non e' mai arrivato, «eliminarlo dal dispositivo» vuol
    dire annullare l'invio: e' quello che fa anche il pulsante del sito
    (`queue_device_book_action`, ramo `queued_delete`), e qui si fa lo
    stesso perche' la domanda e' la stessa.

    **La riga se ne va anche quando il libro era consegnato**, e non diventa
    `pending_delete`: quello stato vuol dire «il server vuole che il
    dispositivo lo cancelli, e aspetta conferma». Qui la conferma e' la
    richiesta stessa — il dispositivo sta per cancellarlo, e lo sa lui. E'
    la stessa scelta che `/sync/ack` fa quando il plugin dichiara
    `result = deleted`: la riga se ne va e la storia ne conserva la traccia.
    """
    if not payload.get("hash") and payload.get("calibre_book_id") is None:
        raise HTTPException(status_code=400,
                            detail="the book's identity or its fingerprint is required")

    matches = book_hash_service.resolve_identities_from_item(
        db, payload, device_id=current_device.id)
    if not matches:
        raise HTTPException(status_code=404, detail="Book not recognised")

    fmt = (payload.get("format") or "").upper() or None
    quante = 0
    for library, calibre_book_id in matches:
        query = db.query(models.DeviceBook).filter(
            models.DeviceBook.device_id == current_device.id,
            models.DeviceBook.library == library,
            models.DeviceBook.calibre_book_id == calibre_book_id,
        )
        # Il formato restringe se c'e'. Senza, se ne va il libro in tutti i
        # formati che stanno su questo lettore: e' quello che vuol dire
        # «togli questo libro», e un plugin che il formato non lo manda non
        # deve lasciare meta' libro indietro.
        if fmt:
            query = query.filter(models.DeviceBook.format == fmt)
        for row in query.all():
            db.delete(row)
            quante += 1
    if quante == 0:
        raise HTTPException(
            status_code=404,
            detail="The book is not on this device: there is nothing to remove",
        )
    db.commit()
    log_message("info", "devices",
                f"Device '{current_device.name}' removed a book it no longer wants "
                f"({quante} row(s) of desired state).")
    return {"status": "ok", "removed": quante}


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
