"""
Diagnostica, ripristino da backup e inventario della cartella dei libri.

Il mestiere: i tre attrezzi da officina del parco dispositivi — quello che
si usa quando qualcosa e' andato storto o va capito. (Trasloco del
20/11/2026: prima era tutto in api/devices.py.)

Il RIPRISTINO — un dispositivo nuovo riparte dai backup di uno vecchio;
la richiesta la apre il plugin, la conferma l'utente, la consuma il
dispositivo sorgente:
* POST .../sync/restore-request (plugin) — la apre;
* POST /api/devices/{id}/restore-request/confirm e DELETE
  /api/devices/{id}/restore-request (webapp) — conferma o annulla;
* GET  .../sync/restore-request/{source_id}/file (plugin) — scarica i file
  del dispositivo sorgente;
* POST .../sync/restore-request/{request_id}/complete (plugin) — chiude.
ATTENZIONE (promemoria del 19/11): il ripristino e' scritto ma MAI provato
su dati veri — non dichiararlo funzionante.

La DIAGNOSTICA — il crash.log di KOReader, che su un Kindle si raggiunge
solo con un cavo, mandato dal plugin gia' ripulito di token e indirizzi:
* POST /api/kolibre/devices/diagnostic-log (plugin) — l'upload, tetto a
  `_MAX_DIAGNOSTIC_BYTES`;
* GET  /api/devices/{id}/diagnostics e .../diagnostics/{filename}
  (webapp) — l'elenco e la lettura. Non e' un backup: e' roba da leggere
  e buttare.

L'INVENTARIO — la fotografia della cartella dei libri del dispositivo,
file per file, anche di quello che il server non gestisce:
* POST /api/kolibre/devices/inventory (plugin) — la riceve;
* GET  /api/devices/{id}/inventory (webapp) — la mostra, raggruppata e
  con l'identita' dei file riconosciuti.

Regola trasversale: i nomi di file che arrivano dal dispositivo passano
SEMPRE dal filtro `_SAFE_BACKUP_FILENAME` (in _shared) prima di toccare il
disco, e le rotte webapp verificano la proprieta' del dispositivo con
`_get_owned_device` (404 per un id altrui).
"""

import json
import os

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ... import config, models, database, auth
from ...istanti import quando

from ...logging_utils import log_message
from ...calibre.library import CalibreLibrary
from ...services import inventario_dispositivo
from ...schemas_risposte import (
    Esito, RichiestaDiRipristinoCreata, InventarioDelDispositivo,
    InventarioRicevuto,
)

from ._shared import (
    router, sync_router, _SAFE_BACKUP_FILENAME,
    _get_open_restore_request, _get_owned_device,
)


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


# ── il registro di diagnostica di un lettore ─────────────────────────────
#
# Nato il 15/11/2026 da una domanda senza risposta: sul Kindle di Paolo la
# UI «non parte e non dà problemi», e il perché sta nel `crash.log` di
# KOReader — che su un Kindle si raggiunge solo con un cavo. Il plugin lo
# manda qui da una voce di menu, DOPO averlo ripulito di token e indirizzi
# (vedi `kolibre_diagnostica.lua` nel plugin) e averne preso la coda.
#
# Non è un backup e non sta fra i backup: un backup è roba che si può
# rimettere su un lettore, questo è roba da leggere e buttare.
_MAX_DIAGNOSTIC_BYTES = 512 * 1024


def _diagnostics_dir(device_id: int) -> str:
    return os.path.join(config.DIAGNOSTICS_DIR, str(device_id))


@sync_router.post("/diagnostic-log", responses={200: {"model": dict}})
async def upload_diagnostic_log(
    request: Request,
    db: Session = Depends(database.get_db),
    current_device: models.Device = Depends(auth.get_current_device),
):
    """
    Il registro di un lettore, mandato a richiesta dal suo menu.

    Corpo grezzo come `upload_device_backup`: è testo, non serve multipart.
    Il nome del file lo decide il SERVER e non il dispositivo — un nome che
    arriva da fuori è un modo di scrivere dove non si dovrebbe, e qui non
    c'è nessuna ragione per cui debba sceglierlo il lettore.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body")
    if len(body) > _MAX_DIAGNOSTIC_BYTES:
        raise HTTPException(status_code=413, detail="Diagnostic log too large")

    cartella = _diagnostics_dir(current_device.id)
    os.makedirs(cartella, exist_ok=True)
    # **La «Z» nel nome non e' decorazione.** Questo non e' un istante
    # serializzato, e' il nome di un file — ma e' un nome che si legge, che
    # si serve a un client (`list_device_diagnostics`) e su cui si riordina
    # la cartella, e senza fuso dichiarato dice un'ora che non e' quella del
    # posto in cui la si legge. Un carattere, e il nome diventa vero.
    # L'ordine alfabetico resta l'ordine cronologico, perche' la «Z» sta
    # dopo i secondi; `_SAFE_BACKUP_FILENAME` la ammette.
    nome = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%SZ") + ".log"
    with open(os.path.join(cartella, nome), "wb") as f:
        f.write(body)

    # Si tengono gli ultimi dieci e basta: sono file da leggere una volta, e
    # una cartella che cresce per sempre è un modo lento di riempire un
    # disco.
    vecchi = sorted(os.listdir(cartella))
    for extra in vecchi[:-10]:
        try:
            os.remove(os.path.join(cartella, extra))
        except OSError:
            pass

    log_message("info", "diagnostica",
                f"Diagnostic log '{nome}' ({len(body)} bytes) received from '{current_device.name}'")
    return {"filename": nome, "size": len(body)}


@router.get("/{device_id}/diagnostics", responses={200: {"model": list}})
def list_device_diagnostics(
    device_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """I registri che questo lettore ha mandato, dal più recente."""
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    cartella = _diagnostics_dir(device_id)
    if not os.path.isdir(cartella):
        return []
    out = []
    for nome in sorted(os.listdir(cartella), reverse=True):
        percorso = os.path.join(cartella, nome)
        out.append({
            "filename": nome,
            "size": os.path.getsize(percorso),
            "modified_at": quando(datetime.fromtimestamp(os.path.getmtime(percorso), tz=timezone.utc)),
        })
    return out


@router.get("/{device_id}/diagnostics/{filename}", response_class=Response,
            responses={200: {"content": {"text/plain": {}}}})
def read_device_diagnostic(
    device_id: int,
    filename: str,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Un registro, come testo da leggere nel browser.

    `text/plain` e non un allegato: serve aprirlo e guardarlo, non salvarlo.
    """
    if not _SAFE_BACKUP_FILENAME.match(filename):
        raise HTTPException(status_code=400, detail="Invalid file name")
    dev = db.query(models.Device).filter(
        models.Device.id == device_id, models.Device.user_id == current_user.id
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    percorso = os.path.join(_diagnostics_dir(device_id), filename)
    if not os.path.isfile(percorso):
        raise HTTPException(status_code=404, detail="Log not found")
    with open(percorso, "rb") as f:
        return Response(content=f.read(), media_type="text/plain; charset=utf-8")


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
