"""
Le annotazioni che il dispositivo manda al server.

Il mestiere: evidenziazioni e note fatte leggendo su KOReader, spinte al
server col token di dispositivo. Il server le aggancia al libro giusto se
il file e' accoppiato, altrimenti le tiene ORFANE (legate al percorso sul
dispositivo) finche' l'accoppiamento non arriva — il macchinario della
migrazione sta in _shared.py perche' lo usano anche flagged_books e
management. (Trasloco del 20/11/2026: prima era tutto in api/devices.py.)

Le rotte (tutte del plugin, su sync_router):
* POST /api/kolibre/devices/annotations — il push: upsert per identita'
  durevole della nota, mai doppioni da un re-invio;
* POST .../annotations/reconcile — il confronto server/dispositivo su cosa
  esiste gia';
* POST .../annotations/auto-pair — il tentativo di adozione automatica
  delle orfane quando spunta l'accoppiamento.

Regola trasversale: l'idempotenza. Il plugin puo' rimandare lo stesso
lotto dopo un timeout senza creare copie: ogni nota viaggia con la sua
identita' durevole (vedi services/identita_durevole) e il push e' un
upsert, non un insert.
"""

from typing import Optional
from datetime import datetime

from fastapi import BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ... import config, models, database, auth

from ...logging_utils import log_message
from ...calibre.library import CalibreLibrary
from ...services.position_converter.chapter_resolver import (
    resolve_epub_chapter_path, resolve_pdf_chapter_path,
)
from ...services import book_hash_service, highlight_position
from ...schemas_risposte import AnnotazioniRicevute, AnnotazioniRiconciliate, OrfaneMigrate

from ._shared import (
    sync_router, _migrate_orphan_highlights, _parse_koreader_datetime,
    _upsert_orphan_highlight,
)


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
