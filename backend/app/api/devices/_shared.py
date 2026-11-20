"""
Il corredo comune del pacchetto dei dispositivi.

Qui vivono i tre router su cui gli altri moduli del pacchetto appendono le
loro rotte, e gli attrezzi che servono a piu' di un mestiere. Nessuna rotta
e' definita qui. Il modulo esiste perche' il trasloco del 20/11/2026 (punto
A1 della revisione del 19/11: api/devices.py era un file solo di ~4.300
righe e 61 rotte) ha spaccato il file per mestiere, e quello che dentro un
file unico era semplicemente "sopra" e' rimasto condiviso fra moduli:
spostato qui UNA volta, mai duplicato.

I tre router (ricomposti per main.py da __init__.py):
* `router` — /api/devices, autenticazione col JWT dell'utente: main.py gli
  applica la dipendenza di autenticazione quando lo monta. E' la webapp.
* `device_token_router` — stesso prefisso /api/devices ma col TOKEN DI
  DISPOSITIVO (vedi il commento accanto alla definizione: il plugin
  KOReader un JWT non ce l'ha). main.py lo monta PRIMA di `router`.
* `sync_router` — /api/kolibre/devices, il protocollo di sincronizzazione,
  sempre col token di dispositivo.

Gli attrezzi condivisi, e chi li usa:
* `_SENDABLE_STATUSES` — gli stati di DeviceBook "da mandare": li guardano
  il manifesto del sync, la coda della webapp (management) e la conferma
  legacy; `_SYNC_HISTORY_KEEP` — quante sessioni di storico si tengono
  (le scrive sync, le rilegge management);
* `_get_owned_device` — carica un dispositivo solo se e' dell'utente del
  JWT: un id altrui vale un 404, mai un 403 che ne confermerebbe
  l'esistenza (dictionaries e diagnostics);
* `_get_open_restore_request` / `_serialize_restore_request` — la
  richiesta di ripristino aperta: la mostrano l'elenco dispositivi
  (management) e l'handshake (sync), la gestisce diagnostics;
* `_dizionari_in_coda` — la coda dei dizionari sul dispositivo, letta da
  management, sync e dictionaries;
* `_SAFE_BACKUP_FILENAME` — il filtro sui nomi di file che arrivano dal
  dispositivo, contro i path traversal (flagged_books, backups_stats,
  diagnostics);
* il macchinario delle evidenziazioni orfane (`_parse_koreader_datetime`,
  `_upsert_orphan_highlight`, `_utente_del_dispositivo`,
  `_migrate_orphan_highlights`, `_migrate_device_highlights_to_new_book`)
  — un'evidenziazione arrivata per un file non ancora accoppiato resta
  "orfana" finche' qualcuno non accoppia il file al libro: lo usano le
  annotazioni (annotations), le segnalazioni (flagged_books) e
  l'accoppiamento manuale della webapp (management).
"""

import json
import re

from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from ... import models

from ...services import identita_durevole
from ...services import stardict_service


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


# DeviceBook rows in these statuses are offered to the device in sends[].
_SENDABLE_STATUSES = ("pending_send", "send_failed")


_SYNC_HISTORY_KEEP = 100                             # max history rows per device


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


def _get_owned_device(db: Session, device_id: int, current_user: models.User) -> models.Device:
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    return dev


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
