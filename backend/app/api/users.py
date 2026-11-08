import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import config, models, schemas, database, auth
from ..schemas_risposte import (Esito, PreferenzeDellaPersona, TokenApplicazioneCreato,
                                TokenDellApplicazione)
from ..istanti import quando
from ..logging_utils import log_message
from ..services import permessi, preferenze_utente

router = APIRouter(prefix="/api/users", tags=["users"])

# Endpoint deliberatamente SENZA autenticazione: sono URL che il
# browser (o il plugin KOReader) carica senza poter allegare un header
# Authorization — <img src>, @font-face, self-update del plugin. Tutto
# il resto di questo modulo passa da `router`, che main.py include con
# la dipendenza di autenticazione. Se aggiungi qui un endpoint, stai
# scegliendo di renderlo pubblico: fallo solo se e' in sola lettura.
public_router = APIRouter(prefix="/api/users", tags=["users"])

_ALLOWED_PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _find_photo_file(user_id: int):
    for ext in _ALLOWED_PHOTO_EXTENSIONS:
        path = os.path.join(config.USERS_DIR, f"{user_id}{ext}")
        if os.path.exists(path):
            return path
    return None


@router.get("/me", response_model=schemas.UserResponse)
def get_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


@router.get("/me/preferenze", response_model=PreferenzeDellaPersona)
def leggi_le_mie_preferenze(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Le preferenze della persona che sta guardando.

    Una preferenza a `null` vuol dire **«non ha scelto»**, non «il difetto»:
    il client decide lui, e per la lingua la cosa gentile e' guardare la
    lingua del sistema. Vedi `services/preferenze_utente.py` per il criterio
    di cosa sta qui e cosa resta nel client.
    """
    return preferenze_utente.leggi(db, current_user.id)


@router.put("/me/preferenze", response_model=PreferenzeDellaPersona)
def cambia_le_mie_preferenze(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Cambia le preferenze nominate e lascia stare le altre.

    Si risponde col quadro completo, non con quello che e' stato mandato: chi
    cambia una cosa sola non deve fare una seconda richiesta per sapere come
    sta il resto.
    """
    try:
        return preferenze_utente.scrivi(db, current_user.id, payload)
    except preferenze_utente.PreferenzaRifiutata as rifiuto:
        # 400 e non 422: la forma della richiesta e' giusta, e' il VALORE che
        # non si puo' scrivere — e il messaggio dice quale e perche'.
        raise HTTPException(status_code=400, detail=str(rifiuto))


@router.put("/me", response_model=schemas.UserResponse)
def update_profile(
    update: schemas.UserUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if update.username:
        existing = db.query(models.User).filter(models.User.username == update.username).first()
        if existing and existing.id != current_user.id:
            raise HTTPException(status_code=400, detail="That username is already taken")
        current_user.username = update.username
    if update.fullname:
        current_user.fullname = update.fullname
    if update.password:
        current_user.hashed_password = auth.get_password_hash(update.password)
    db.commit()
    db.refresh(current_user)
    log_message("info", "profile", f"Profile updated for user: {current_user.username}")
    return current_user


@router.post("/me/photo", response_model=schemas.UserResponse)
async def upload_profile_photo(
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_PHOTO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported image format (use jpg, png, webp or gif)")
    content = await file.read()
    if len(content) > 2_000_000:
        raise HTTPException(status_code=400, detail="The file is larger than the 2MB limit")

    os.makedirs(config.USERS_DIR, exist_ok=True)
    # Remove any previous photo under a different extension first, so
    # switching from a .png to a .jpg doesn't leave the old file behind.
    old = _find_photo_file(current_user.id)
    if old:
        os.remove(old)
    with open(os.path.join(config.USERS_DIR, f"{current_user.id}{ext}"), "wb") as f:
        f.write(content)

    current_user.photo_url = f"/api/users/{current_user.id}/photo"
    db.commit()
    db.refresh(current_user)
    log_message("info", "profile", f"Photo uploaded for user: {current_user.username}")
    return current_user


@router.delete("/me/photo", response_model=schemas.UserResponse)
def delete_profile_photo(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    old = _find_photo_file(current_user.id)
    if old:
        os.remove(old)
    current_user.photo_url = None
    db.commit()
    db.refresh(current_user)
    return current_user


@public_router.get("/{user_id}/photo", response_class=FileResponse, responses={200: {"content": {"image/*": {}}}}, dependencies=[Depends(auth.utente_o_dispositivo)])
def get_profile_photo(user_id: int):
    path = _find_photo_file(user_id)
    if not path:
        raise HTTPException(status_code=404, detail="Photo not available")
    return FileResponse(path)


# ── Utenti e permessi d'account ───────────────────────────────────────────
#
# Fino al 28/09/2026 gli utenti nascevano solo all'avvio del server (uno,
# dal file di configurazione) e non c'era modo di crearne altri da nessuna
# parte. Queste rotte sono l'interfaccia che serviva.

@router.get("", response_model=list[schemas.UserResponse])
def list_users(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Chi c'e' su questo impianto.

    Aperto a chiunque sia autenticato, e non e' una svista: per condividere
    una biblioteca bisogna poter scegliere con chi, e i nomi degli utenti di
    un server di famiglia non sono un segreto. Quello che non e' aperto e'
    CAMBIARE i loro permessi — vedi le rotte qui sotto.
    """
    return db.query(models.User).order_by(models.User.id).all()


@router.post("", response_model=schemas.UserResponse)
def create_user(
    payload: dict,
    db: Session = Depends(database.get_db),
    _chi: models.User = Depends(permessi.richiede_creare_utenti),
):
    """Un utente nuovo, senza nessun permesso se non quelli chiesti.

    Nasce potendo registrare dispositivi e nient'altro: e' il minimo che
    rende un account utile a leggere, ed e' anche il default del modello."""
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password are required")
    if db.query(models.User).filter(models.User.username == username).first():
        raise HTTPException(status_code=409, detail="A user with this name already exists")

    utente = models.User(
        username=username,
        hashed_password=auth.get_password_hash(password),
        fullname=(payload.get("fullname") or "").strip() or None,
        is_admin=bool(payload.get("is_admin")),
        can_create_libraries=bool(payload.get("can_create_libraries")),
        can_create_users=bool(payload.get("can_create_users")),
        can_manage_permissions=bool(payload.get("can_manage_permissions")),
        can_register_devices=bool(payload.get("can_register_devices", True)),
        can_edit_authors=bool(payload.get("can_edit_authors")),
    )
    db.add(utente)
    db.commit()
    db.refresh(utente)
    log_message("info", "auth", f"User '{username}' created.")
    return utente


_PERMESSI_ACCOUNT = (
    "can_create_libraries", "can_create_users", "can_manage_permissions",
    "can_register_devices", "can_edit_authors", "is_admin",
)


@router.put("/{user_id}/permessi", response_model=schemas.UserResponse)
def update_user_permissions(
    user_id: int,
    payload: dict,
    db: Session = Depends(database.get_db),
    _chi: models.User = Depends(permessi.richiede_gestire_permessi),
):
    """I permessi d'account di qualcun altro.

    Il fondatore non si tocca: e' l'unico account che sta fuori da ogni
    limitazione, e poterglieli cambiare vorrebbe dire poter chiudere fuori il
    proprietario dell'impianto dal proprio impianto. `is_founder` non e'
    nell'elenco dei campi modificabili per la stessa ragione — non si
    diventa fondatori per delibera."""
    utente = db.query(models.User).filter(models.User.id == user_id).first()
    if not utente:
        raise HTTPException(status_code=404, detail="User not found")
    if utente.is_founder:
        raise HTTPException(status_code=403, detail="The founder's permissions cannot be changed.")
    for campo in _PERMESSI_ACCOUNT:
        if campo in payload:
            setattr(utente, campo, bool(payload[campo]))
    db.commit()
    db.refresh(utente)
    log_message("info", "auth", f"Permissions updated for '{utente.username}'.")
    return utente


@router.delete("/{user_id}", response_model=Esito)
def delete_user(
    user_id: int,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(permessi.richiede_creare_utenti),
):
    """Cancella un utente. Con lui se ne vanno i suoi dispositivi, le sue
    annotazioni, le sue letture: sono suoi, e il modello li lega a lui con
    un `cascade`.

    Le sue biblioteche NO: restano senza proprietario invece di sparire
    (`owner_id` va a NULL). Un utente cancellato non deve portarsi via dei
    libri, e il fondatore continua a vederle comunque."""
    if user_id == chi.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    utente = db.query(models.User).filter(models.User.id == user_id).first()
    if not utente:
        raise HTTPException(status_code=404, detail="User not found")
    if utente.is_founder:
        raise HTTPException(status_code=403, detail="The founder of this installation cannot be deleted.")
    nome = utente.username
    db.delete(utente)
    db.commit()
    log_message("warning", "auth", f"User '{nome}' deleted.")
    return {"status": "ok"}


# ── I token delle applicazioni ───────────────────────────────────────────
#
# Un token con cui un'applicazione parla col server a nome di questa persona:
# il plugin Obsidian, uno script, un domani un client nativo. Esistono perche'
# il plugin Obsidian conservava la **password** dentro il vault — cioe' nella
# cartella che la gente sincronizza — per potersi rinnovare l'accesso da se'.
# Vedi `models.TokenApplicazione`.


@router.post(
    "/me/tokens",
    responses={200: {"model": TokenApplicazioneCreato}},
)
def crea_token_applicazione(
    payload: dict,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user),
):
    """
    Fabbrica un token per un'applicazione, e **lo mostra una volta sola**.

    Si chiede con la sessione normale — cioe' chi lo crea ha appena provato
    di essere lui. Da quel momento l'applicazione usa il token e **puo'
    dimenticare la password**.

    Non si puo' creare un token **usando un token**: sarebbe una catena che
    non si rompe piu' — chi ne ruba uno se ne fabbrica altri dieci, e
    revocare quello rubato non servirebbe a niente. Serve una sessione vera.
    """
    if getattr(chi, "_da_token_applicazione", False):
        raise HTTPException(
            status_code=403,
            detail="An application token is created by signing in with your password, "
                   "not with another token.",
        )
    nome = (payload.get("nome") or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Give the token a name: it is how you tell "
                                                    "which one to switch off when you have more than one.")
    token = auth.crea_token_applicazione(db, chi, nome)
    riga = db.query(models.TokenApplicazione).filter(
        models.TokenApplicazione.token_hash == auth.impronta_del_token(token)).first()
    log_message("info", "auth", f"Application token '{nome}' created for '{chi.username}'.")
    return {"id": riga.id, "nome": riga.nome, "token": token,
            "creato_il": quando(riga.creato_il)}


@router.get(
    "/me/tokens",
    responses={200: {"model": TokenDellApplicazione}},
)
def elenca_token_applicazione(
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user),
):
    """
    I token vivi di questa persona. **Il token non c'e'**: non e' nascosto,
    e' che il server ne ha solo l'impronta e non puo' ridirlo.

    I revocati non compaiono, ma la loro riga resta nel database: «spento il
    giorno tale» e' un'informazione, e una riga cancellata non la racconta.
    """
    righe = db.query(models.TokenApplicazione).filter(
        models.TokenApplicazione.user_id == chi.id,
        models.TokenApplicazione.revocato_il.is_(None),
    ).order_by(models.TokenApplicazione.id).all()
    return {"items": [
        {"id": r.id, "nome": r.nome, "creato_il": quando(r.creato_il),
         "ultimo_uso_il": quando(r.ultimo_uso_il)}
        for r in righe
    ]}


@router.delete(
    "/me/tokens/{token_id}",
    responses={200: {"model": Esito}},
)
def revoca_token_applicazione(
    token_id: int,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user),
):
    """
    Spegne un token. Da quel momento non apre piu' niente, e questa e' la
    ragione per cui un token e' meglio di una password: **la password si
    cambia per tutti, un token si spegne da solo**.

    Il token di un'altra persona risponde 404 e non 403: dire «esiste ma non
    e' tuo» direbbe a chiunque quanti token ha qualcun altro.
    """
    riga = db.query(models.TokenApplicazione).filter(
        models.TokenApplicazione.id == token_id,
        models.TokenApplicazione.user_id == chi.id,
        models.TokenApplicazione.revocato_il.is_(None),
    ).first()
    if not riga:
        raise HTTPException(status_code=404, detail="Token not found")
    riga.revocato_il = datetime.utcnow()
    db.commit()
    log_message("warning", "auth",
                f"Application token '{riga.nome}' revoked by '{chi.username}'.")
    return {"status": "ok"}
