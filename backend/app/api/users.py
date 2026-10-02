import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import config, models, schemas, database, auth
from ..logging_utils import log_message
from ..services import permessi

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


@router.put("/me", response_model=schemas.UserResponse)
def update_profile(
    update: schemas.UserUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if update.username:
        existing = db.query(models.User).filter(models.User.username == update.username).first()
        if existing and existing.id != current_user.id:
            raise HTTPException(status_code=400, detail="Username già in uso")
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
        raise HTTPException(status_code=400, detail="Formato immagine non supportato (usa jpg, png, webp o gif)")
    content = await file.read()
    if len(content) > 2_000_000:
        raise HTTPException(status_code=400, detail="Il file supera il limite di 2MB")

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


@public_router.get("/{user_id}/photo", dependencies=[Depends(auth.utente_o_dispositivo)])
def get_profile_photo(user_id: int):
    path = _find_photo_file(user_id)
    if not path:
        raise HTTPException(status_code=404, detail="Foto non disponibile")
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
        raise HTTPException(status_code=400, detail="username e password sono obbligatori")
    if db.query(models.User).filter(models.User.username == username).first():
        raise HTTPException(status_code=409, detail="Esiste già un utente con questo nome")

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
    log_message("info", "auth", f"Utente '{username}' creato.")
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
        raise HTTPException(status_code=404, detail="Utente non trovato")
    if utente.is_founder:
        raise HTTPException(status_code=403, detail="I permessi del fondatore non si modificano.")
    for campo in _PERMESSI_ACCOUNT:
        if campo in payload:
            setattr(utente, campo, bool(payload[campo]))
    db.commit()
    db.refresh(utente)
    log_message("info", "auth", f"Permessi aggiornati per '{utente.username}'.")
    return utente


@router.delete("/{user_id}")
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
        raise HTTPException(status_code=400, detail="Non puoi cancellare il tuo stesso account.")
    utente = db.query(models.User).filter(models.User.id == user_id).first()
    if not utente:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    if utente.is_founder:
        raise HTTPException(status_code=403, detail="Il fondatore dell'impianto non si cancella.")
    nome = utente.username
    db.delete(utente)
    db.commit()
    log_message("warning", "auth", f"Utente '{nome}' cancellato.")
    return {"status": "ok"}
