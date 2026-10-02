import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from . import config, models, database

# ── La chiave che firma i token di accesso ───────────────────────────────
#
# Prima c'era un valore di ripiego scritto nel codice. Finche' il codice e'
# privato e' un difetto; il giorno che diventa pubblico quella stringa la
# conosce chiunque, e chi non ha impostato SECRET_KEY si ritrova un'istanza
# dove un estraneo puo' FABBRICARE un token valido per qualunque account —
# senza password, senza lasciare traccia di un tentativo fallito.
#
# Il ripiego non e' pero' "rifiutarsi di partire": un programma che si
# autoinstalla con `docker compose up` deve funzionare al primo colpo, e una
# installazione che muore all'avvio con un messaggio su una variabile manda
# via chi stava provando. Quindi: se la chiave non c'e', se ne genera una
# vera e si tiene su disco. Casuale, unica per installazione, e stabile fra
# un riavvio e l'altro — rigenerarla ogni volta scollegherebbe tutti ad ogni
# aggiornamento.
#
# I valori-segnaposto vengono RIFIUTATI anche quando sono nell'ambiente: sono
# scritti in .env.example e in vecchie guide, quindi finiranno copiati
# tali e quali, e accettarli sarebbe lo stesso buco con un altro nome.
#
# Cosa si rompe cambiandola: le sessioni aperte nei browser, che devono
# rifare l'accesso. I dispositivi NO — KOReader e il plugin Calibre usano un
# token loro (`kolibre_tok_…`, colonna `devices.device_token`), non un JWT,
# quindi le sincronizzazioni continuano come prima.

_SEGNAPOSTO = {
    "your-secret-key-for-kolibre-CHANGE-IN-PRODUCTION",
    "change-me-this-default-is-not-secure-generate-a-real-one",
    "changeme",
    "secret",
    "",
}
_FILE_CHIAVE = os.path.join(config.DATA_DIR, "secret_key")
# Sotto questa lunghezza una chiave e' indovinabile a forza bruta: meglio
# generarne una vera che fidarsi di quella che e' stata scritta.
_LUNGHEZZA_MINIMA = 16


def _chiave_dal_disco() -> str:
    """La chiave di questa installazione: letta, o generata e salvata."""
    try:
        if os.path.exists(_FILE_CHIAVE):
            with open(_FILE_CHIAVE, "r", encoding="utf-8") as f:
                salvata = f.read().strip()
            if len(salvata) >= _LUNGHEZZA_MINIMA:
                return salvata
        nuova = secrets.token_hex(32)
        os.makedirs(config.DATA_DIR, exist_ok=True)
        # 0600: la chiave vale quanto tutte le password insieme, e la cartella
        # dei dati e' montata da fuori nel container.
        fd = os.open(_FILE_CHIAVE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(nuova)
        logging.info(
            "Generata una chiave di firma nuova in %s. Le sessioni aperte nei "
            "browser vanno rifatte; i dispositivi non sono toccati.", _FILE_CHIAVE,
        )
        return nuova
    except OSError as exc:
        # Disco in sola lettura, permessi sbagliati: si va avanti con una
        # chiave buona ma solo in memoria. Chi riavvia dovra' riaccedere, ed
        # e' comunque meglio di una chiave che conoscono tutti.
        logging.warning(
            "Non riesco a salvare la chiave di firma in %s (%s): ne uso una "
            "valida solo fino al prossimo riavvio.", _FILE_CHIAVE, exc,
        )
        return secrets.token_hex(32)


def _scegli_chiave() -> str:
    dall_ambiente = (os.environ.get("SECRET_KEY") or "").strip()
    if dall_ambiente and dall_ambiente not in _SEGNAPOSTO and len(dall_ambiente) >= _LUNGHEZZA_MINIMA:
        return dall_ambiente
    if dall_ambiente:
        logging.warning(
            "SECRET_KEY e' un valore di esempio o troppo corto: lo ignoro e uso "
            "la chiave di questa installazione. Per impostarne una tua: "
            "openssl rand -hex 32",
        )
    return _chiave_dal_disco()


SECRET_KEY = _scegli_chiave()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def verify_password(plain_password: str, hashed_password: str):
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def _decode_token(token: str, db: Session):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)):
    return _decode_token(token, db)

def get_current_user_flexible(token_header: Optional[str] = Depends(oauth2_scheme_optional), token: Optional[str] = Query(None), db: Session = Depends(database.get_db)):
    """Accepts token from Authorization header OR ?token= query param (for browser downloads)."""
    resolved = token_header or token
    if not resolved:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if resolved.startswith("Bearer "):
        resolved = resolved.replace("Bearer ", "")
    return _decode_token(resolved, db)

def get_current_active_admin(current_user: models.User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=400, detail="The user doesn't have enough privileges")
    return current_user


DEVICE_TOKEN_PREFIX = "kolibre_tok_"

_device_token_header = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def get_current_device(
    token: Optional[str] = Depends(_device_token_header),
    db: Session = Depends(database.get_db),
) -> "models.Device":
    """
    Authenticates a KOReader/device client via its permanent `kolibre_tok_...`
    bearer token (distinct from the short-lived JWT issued to human users at
    /token). Devices never log in with a username/password; the token is
    generated once by POST /api/devices/register and embedded in the
    downloadable, pre-configured plugin package.
    """
    if not token or not token.startswith(DEVICE_TOKEN_PREFIX):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token dispositivo non valido")
    device = db.query(models.Device).filter(models.Device.device_token == token).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dispositivo non registrato")
    # Single choke point for "device was heard from": every device-token
    # request refreshes last_seen_at, so no endpoint has to remember to.
    # FastAPI caches get_db per request, so this is the same session the
    # endpoint will use — committing here is safe (nothing else is pending
    # yet, auth runs before the endpoint body).
    device.last_seen_at = datetime.utcnow()
    db.commit()
    return device


def get_user_or_device(
    token_header: Optional[str] = Depends(oauth2_scheme_optional),
    token: Optional[str] = Query(None),
    db: Session = Depends(database.get_db),
):
    """
    Accetta l'accesso di una PERSONA (il JWT breve di /token) oppure quello
    di un DISPOSITIVO (il token permanente `kolibre_tok_...`).

    Serve a quei pochi endpoint che devono rispondere a tutti e due, e il
    caso vero e' uno solo: scaricare il file di un libro. Il server stesso
    dice al dispositivo di chiamare
    `/api/kolibre/books/{id}/download` (vedi il campo `download_url` in
    api/devices.py), ma quel percorso stava dietro l'autenticazione utente,
    che un dispositivo non ha e non puo' avere: dalla chiusura delle API
    (18/09/2026) ogni download dal plugin KOReader rispondeva 401. Riscontrato
    in uso, con il log del dispositivo.

    Non e' un allentamento: un token di dispositivo e' una credenziale a
    tutti gli effetti, legata a un dispositivo registrato da un utente, ed e'
    gia' quella che apre il catalogo e la sincronizzazione. Qui vale per
    leggere un file che quel dispositivo ha comunque il diritto di ricevere.
    """
    resolved = token_header or token
    if not resolved:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if resolved.startswith("Bearer "):
        resolved = resolved.replace("Bearer ", "", 1)
    if resolved.startswith(DEVICE_TOKEN_PREFIX):
        device = db.query(models.Device).filter(models.Device.device_token == resolved).first()
        if not device:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dispositivo non registrato")
        device.last_seen_at = datetime.utcnow()
        db.commit()
        return device
    return _decode_token(resolved, db)


def utente_effettivo_opzionale(
    token_header: Optional[str] = Depends(oauth2_scheme_optional),
    token: Optional[str] = Query(None),
    db: Session = Depends(database.get_db),
) -> Optional["models.User"]:
    """
    Chi sta chiedendo, quando serve saperlo ma non e' obbligatorio saperlo.

    Torna l'utente per un token di persona, il PROPRIETARIO del dispositivo
    per un token di dispositivo — i dispositivi sono uno a uno con gli utenti,
    quindi l'accesso di un lettore e' quello di chi l'ha registrato — e None
    per una richiesta senza credenziali (le poche rotte pubbliche: copertine,
    caratteri, aggiornamento dei plugin).

    Non solleva mai 401: e' il controllo dei permessi sulla biblioteca a
    decidere, e un endpoint che deve essere autenticato lo e' gia' per conto
    suo. Un token illeggibile qui vale come "non so chi sei", non come "sei
    fuori": chiudere qui sarebbe un secondo cancello d'accesso nascosto in
    una funzione che si chiama "opzionale".
    """
    resolved = token_header or token
    if not resolved:
        return None
    if resolved.startswith("Bearer "):
        resolved = resolved.replace("Bearer ", "", 1)
    if resolved.startswith(DEVICE_TOKEN_PREFIX):
        device = db.query(models.Device).filter(models.Device.device_token == resolved).first()
        return device.user if device else None
    try:
        return _decode_token(resolved, db)
    except HTTPException:
        return None


# ── Immagini: chi ha un account, oppure un dispositivo registrato ────────
#
# Copertine, foto degli autori, foto profilo e font erano raggiungibili SENZA
# autenticazione. La ragione era buona — un `<img src>` non puo' allegare un
# header `Authorization`, e lo stesso vale per un `url()` dentro una regola
# @font-face — ma la conseguenza era che chiunque raggiungesse il server
# poteva sfogliare le copertine di tutta la biblioteca senza accedere, con gli
# id che sono sequenziali.
#
# La soluzione esisteva gia' per meta': `get_current_user_flexible` accetta il
# token anche come `?token=` in query, ed e' cosi' che funzionano i download
# aperti con window.open. Mancava l'altra meta': i DISPOSITIVI. KOReader e il
# plugin Calibre scaricano le copertine, e mandano gia' il loro
# `Authorization: Bearer …` su ogni richiesta — solo che il loro e' un
# `kolibre_tok_…` (colonna `devices.device_token`), non un JWT, e il decoder
# dei JWT lo rifiuterebbe.
#
# Quindi: si accetta l'uno o l'altro. Il dispositivo non diventa un utente —
# restituisce il proprietario del dispositivo, che e' chi ha diritto a vedere
# quelle immagini.
#
# Il prezzo, dichiarato: un token in query finisce nei log del server e nella
# cronologia del browser. Per un'immagine e' un compromesso accettabile; per
# qualunque altra cosa si usa l'header.

def utente_o_dispositivo(
    token_header: Optional[str] = Depends(oauth2_scheme_optional),
    token: Optional[str] = Query(None),
    db: Session = Depends(database.get_db),
):
    grezzo = (token_header or token or "").strip()
    if grezzo.startswith("Bearer "):
        grezzo = grezzo[len("Bearer "):].strip()
    if not grezzo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # Il token di un dispositivo si riconosce dal prefisso che gli diamo noi
    # alla registrazione: non e' una scorciatoia, e' il solo modo di sapere
    # quale dei due decoder provare senza far fallire l'altro per finta.
    if grezzo.startswith(DEVICE_TOKEN_PREFIX):
        dispositivo = db.query(models.Device).filter(models.Device.device_token == grezzo).first()
        if dispositivo is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        proprietario = db.query(models.User).filter(models.User.id == dispositivo.user_id).first()
        if proprietario is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return proprietario

    return _decode_token(grezzo, db)

