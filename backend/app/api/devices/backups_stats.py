"""
I backup del dispositivo e le statistiche di lettura di KOReader.

Il mestiere: le copie di sicurezza che il lettore carica sul server (i
suoi metadata/sidecar, da cui un dispositivo nuovo puo' ripartire) e il
database delle statistiche di KOReader, cucito incrementalmente. (Trasloco
del 20/11/2026: prima era tutto in api/devices.py.)

Le rotte del plugin (token di dispositivo, su sync_router):
* GET  /api/kolibre/devices/backup/state — cosa il server ha gia', file
  per file con md5: il plugin manda solo quello che manca;
* POST .../backup — l'upload del singolo file (corpo grezzo);
* GET  .../stats/state e POST .../stats/incremental — lo stato e la
  cucitura del database statistiche (vedi services/stats_service).

Le rotte della webapp (JWT, su router):
* GET /api/devices/{id}/backups — l'elenco dei file di backup;
* GET /api/devices/{id}/backups/download — lo zip di tutto, costruito in
  un temporaneo e cancellato a risposta mandata.

Regola trasversale: anche qui tutto e' ripetibile — lo "state" prima
dell'upload serve esattamente a non rimandare mai due volte lo stesso
byte, e un upload doppio sovrascrive lo stesso file, non ne crea un
secondo. I nomi di file che arrivano dal dispositivo passano dal filtro
`_SAFE_BACKUP_FILENAME` (in _shared) prima di toccare il disco.
"""

import hashlib
import os
import re
import tempfile
import zipfile

from typing import Union
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ... import config, models, database, auth
from ...istanti import quando
from starlette.background import BackgroundTask

from ...logging_utils import log_message
from ...services import letture_service, stats_service, vocabulary_service
from ...schemas_risposte import (
    BackupRicevuto, FileDiBackup, StatisticheCucite,
    StatisticheDaRifare, StatoDeiBackup, StatoDelleStatistiche,
)

from ._shared import (
    router, sync_router, _SAFE_BACKUP_FILENAME,
)


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
                # Passo 4 (20/11/2026): le sessioni appena nate possono avere
                # gia' le loro righe in caratteri (i due canali del lettore
                # sincronizzano insieme, in ordine non garantito). La
                # derivazione e' idempotente, quindi rigirarla qui e' gratis
                # e la cache qua sotto parte coi numeri veri.
                try:
                    letture_service.derive_reading_sessions(db)
                except Exception as e:
                    log_message("warning", "backup",
                                f"Deriving sessions from reading rows failed: {e}")
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
                # Passo 4: come nel gemello della salita del file intero —
                # le sessioni appena nate possono avere gia' le loro righe
                # in caratteri, e la derivazione idempotente le arricchisce
                # prima che la cache si rifaccia.
                try:
                    letture_service.derive_reading_sessions(db)
                except Exception as e:
                    log_message("warning", "backup",
                                f"Deriving sessions from reading rows failed: {e}")
                try:
                    # Solo le biblioteche toccate — vedi il gemello nella
                    # salita del file intero, e refresh_stats_cache.
                    stats_service.refresh_stats_cache(db, riassunto.get("biblioteche"))
                except Exception as e:
                    log_message("warning", "backup", f"Statistics cache refresh after the incremental sync failed: {e}")
        except Exception as e:
            log_message("warning", "backup", f"Incremental processing failed: {e}")

    return {"status": "ok", "righe_aggiunte": esito["righe_aggiunte"], "stats": riassunto}


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
