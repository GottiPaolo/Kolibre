"""
I dizionari StarDict mandati al dispositivo.

Il mestiere: l'utente sceglie dalla webapp una lingua da avere sul
lettore; il server la mette in coda sul dispositivo; al sync successivo il
plugin trova la voce nel manifesto, scarica i file e conferma. Lo stato
della coda vive sul Device stesso (`_dizionari_in_coda`, in _shared,
perche' lo leggono anche l'elenco dispositivi e l'handshake). (Trasloco
del 20/11/2026: prima era tutto in api/devices.py.)

Le rotte della webapp (JWT, su router):
* POST   /api/devices/{id}/dictionaries — accoda una lingua;
* DELETE /api/devices/{id}/dictionaries/{lang} — la toglie dalla coda.

Le rotte del plugin (token di dispositivo, su sync_router):
* POST /api/kolibre/devices/sync/dictionaries/ack — "l'ho installato";
* GET  .../dictionaries/{lang}/manifest — i file che compongono il
  dizionario di una lingua, con md5;
* GET  .../dictionaries/{lang}/file/{filename} — il singolo file.

Regola trasversale: la coda e' per lingua e idempotente — accodare due
volte la stessa lingua e' un 409, confermarla due volte non fa danni; i
dizionari disponibili e i loro file li conosce services/stardict_service,
qui si gestisce solo il viaggio verso il dispositivo.
"""

import json

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ... import models, database, auth

from ...logging_utils import log_message
from ...services import stardict_service
from ...schemas_risposte import DizionariInCoda, Esito, ManifestDelDizionario

from ._shared import (
    router, sync_router, _dizionari_in_coda, _get_owned_device,
)


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
