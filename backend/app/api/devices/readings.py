"""
Le letture: la posizione e il tempo misurato in caratteri.

Il mestiere: quanto e dove l'utente ha letto, raccontato dal dispositivo
al server. Due famiglie: la POSIZIONE di lettura (il segnalibro, per
riprendere da un altro dispositivo o dal lettore web) e le LETTURE MISURATE
IN CARATTERI — una riga per pagina visitata: quando, per quanto, da quale
carattere a quale. Il perche' dei caratteri come unita' di misura, e come
l'intero dialogo si incastra nel protocollo, sta in
docs/storico/come-un-dispositivo-parla-con-il-server.md. (Trasloco del
20/11/2026: prima era tutto in api/devices.py.)

Le rotte (tutte del plugin, col token di dispositivo):
* PUT /api/kolibre/devices/progress — il push della posizione;
* GET /api/kolibre/devices/progress — il pull (per riprendere a leggere);
* GET /api/kolibre/devices/caratteri/state — da quale istante mandare le
  letture (con la finestra di sovrapposizione di un giorno: vedi
  letture_service.stato_letture) — la rotta esiste anche per dire al
  plugin che QUESTO server sa riceverle;
* POST /api/kolibre/devices/caratteri/incremental — la cucitura
  incrementale delle righe nuove.

Regola trasversale: lo stato e' incrementale e ricucibile — il dispositivo
puo' restare spento settimane e poi mandare tutto; la finestra di
sovrapposizione e la cucitura lato servizio (letture_service) rendono
innocuo il re-invio della stessa riga.
"""

from datetime import datetime

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ... import models, database, auth
from ...istanti import quando

from ...logging_utils import log_message
from ...services import book_hash_service, letture_service, stats_service
from ...schemas_risposte import (
    Esito, PosizionePerIlDispositivo, LettureCucite, StatoDelleLetture,
)

from ._shared import (
    sync_router,
)


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


@sync_router.get(
    "/caratteri/state",
    responses={200: {"model": StatoDelleLetture}},
)
def device_letture_state(
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Da quale istante il dispositivo deve mandare le letture misurate in
    caratteri.

    Vedi `letture_service.stato_letture`: "da" e' l'ultimo istante noto meno
    una finestra di sovrapposizione di un giorno, non l'ultimo istante secco —
    una riga viene scritta quando la pagina viene LASCIATA, e un lettore puo'
    restare spento in mezzo.

    **Questa rotta esiste anche per dire al plugin che il server sa riceverle:**
    un plugin piu' nuovo del server trova un 404 e tiene le sue righe invece
    di buttarle.
    """
    return letture_service.stato_letture(db, current_device.id)


@sync_router.post(
    "/caratteri/incremental",
    responses={200: {"model": LettureCucite}},
)
def upload_letture_incremental(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Le letture misurate in caratteri che il dispositivo ha e il server no.

    Una riga per pagina visitata — quando, per quanto, da quale carattere a
    quale — piu' una per ogni popup di nota tenuto aperto. Le posizioni sono
    xpointer di crengine; il carattere assoluto lo calcola il server
    (`letture_service.converti_le_letture`), e questo e' il punto dell'intero
    disegno: la PROVA resta nel database, quindi se l'indice del testo
    migliora lo storico si ricalcola. Vedi la testa di `letture_service.py`.

    La conversione si fa **subito dopo**, sul lotto appena arrivato, e non e'
    bloccante per la risposta nel senso che conta: se fallisce, le righe
    restano con `stato_conversione` vuoto e il giro successivo le riprende.
    Una conversione che fallisce non deve far fallire una consegna riuscita.
    """
    esito = letture_service.cuci_letture(db, current_device, payload)
    if esito["motivo"]:
        log_message("info", "backup",
                    f"Reading rows from '{current_device.name}' refused: {esito['motivo']}")
        db.rollback()
        return {"status": "ok", "righe_aggiunte": 0, "doppioni": 0,
                "rifiutate": esito["rifiutate"], "filigrana": esito["filigrana"],
                "motivo": esito["motivo"]}

    db.commit()
    if esito["righe_aggiunte"]:
        current_device.last_backup_at = datetime.utcnow()
        db.commit()
        try:
            conversione = letture_service.converti_le_letture(db)
            log_message(
                "info", "backup",
                f"Reading rows from '{current_device.name}': "
                f"{esito['righe_aggiunte']} new, {esito['doppioni']} already had, "
                f"{conversione['convertite']} resolved into characters "
                f"over {conversione['libri']} book(s)",
            )
        except Exception as e:  # noqa: BLE001
            log_message("warning", "backup", f"Resolving reading rows into characters failed: {e}")
        # Passo 4 (20/11/2026): le righe appena risolte arricchiscono le
        # sessioni (caratteri veri, exact=1) e la copertura. Stesso contratto
        # best-effort della conversione: una derivazione che fallisce non fa
        # fallire una consegna riuscita, e il passo e' idempotente — il giro
        # successivo riprende tutto.
        try:
            derivazione = letture_service.derive_reading_sessions(db)
            if derivazione["sessioni_arricchite"] or derivazione["copertura_aggiornata"]:
                log_message(
                    "info", "backup",
                    f"Reading rows from '{current_device.name}': "
                    f"{derivazione['sessioni_arricchite']} session(s) now carry the exact "
                    f"character measure, coverage updated for "
                    f"{derivazione['copertura_aggiornata']} book(s)",
                )
                # La cache delle statistiche mostra i caratteri per sessione:
                # senza questo refresh resterebbe alla stima fino al prossimo
                # giro di _refresh_stats_loop. Solo le biblioteche toccate,
                # come fa gia' il gemello di statistics.sqlite3.
                try:
                    stats_service.refresh_stats_cache(db, derivazione.get("biblioteche"))
                except Exception as e:  # noqa: BLE001
                    log_message("warning", "backup",
                                f"Statistics cache refresh after session derivation failed: {e}")
        except Exception as e:  # noqa: BLE001
            log_message("warning", "backup", f"Deriving sessions from reading rows failed: {e}")

    return {
        "status": "ok",
        "righe_aggiunte": esito["righe_aggiunte"],
        "doppioni": esito["doppioni"],
        "rifiutate": esito["rifiutate"],
        "filigrana": esito["filigrana"],
        "righe_in_tutto": esito.get("righe_in_tutto"),
    }
