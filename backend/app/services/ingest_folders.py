"""
Le sottocartelle per utente della cartella di ingest (21/11/2026).

**Da dove viene.** Richiesta di Paolo del 21/11/2026: «[l'ingest] e' uno
globale, mentre dovrebbe essere uno per utente: facciamo che nella cartella
di ingest si crea in automatico una cartella per utente». E' la voce del
03/11 della roadmap («La cartella di ingest e' una sola per tutti»): la
tabella dei file in attesa non aveva un proprietario, quindi con due persone
la pagina Ingest mostrava a ciascuno i file degli altri.

**La forma del nome: `<id>-<username sanificato>`, es. `3-paolo`.** Il
proprietario si riconosce SOLO dal numero in testa: l'id e' stabile per
costruzione (un utente rinominato resta lo stesso utente), mentre lo
username dopo il trattino e' solo leggibilita' per chi apre la cartella dal
Finder o da Syncthing. Per questo:

  * se l'utente si rinomina, la cartella vecchia continua a funzionare
    (l'id in testa non cambia) e NON se ne crea una seconda: prima di
    creare si cerca una cartella esistente con quell'id;
  * una cartella fatta a mano che non comincia con `<numero>` o
    `<numero>-...` non viene mai scambiata per una cartella utente;
  * un numero in testa che non corrisponde a nessun utente non attribuisce
    niente (il controllo d'esistenza lo fa chi stagia, con il database in
    mano).

**I file nella RADICE di ingest restano senza proprietario**: e' il
comportamento di prima, conservato apposta — la radice non diventa un buco
nero, e nessun file di nessuno viene spostato.
"""

import os
import re

from .. import config
from ..logging_utils import log_message

# Una cartella utente e' `<id>` oppure `<id>-qualcosa`: il gruppo 1 e' l'id.
_USER_FOLDER_RE = re.compile(r"^(\d+)(?:-.*)?$")


def sanitize_username(username: str) -> str:
    """La parte leggibile del nome cartella: minuscole, solo [a-z0-9_-].

    Tutto il resto (spazi, accenti, slash) diventa un trattino, perche' il
    nome finisce sul filesystem e dentro percorsi sincronizzati: meglio
    brutto che ambiguo."""
    pulito = re.sub(r"[^a-z0-9_-]+", "-", (username or "").lower()).strip("-")
    return pulito


def folder_name_for(user_id: int, username: str) -> str:
    """`3-paolo`, o solo `3` se dello username non resta niente di usabile."""
    slug = sanitize_username(username)
    return f"{user_id}-{slug}" if slug else str(user_id)


def find_user_folder(user_id: int) -> str | None:
    """La cartella esistente di questo utente (percorso assoluto), se c'e'.

    Si cerca per id in testa e non per nome intero: cosi' la cartella creata
    quando l'utente si chiamava in un altro modo resta la sua."""
    if not os.path.isdir(config.INGEST_DIR):
        return None
    for nome in sorted(os.listdir(config.INGEST_DIR)):
        percorso = os.path.join(config.INGEST_DIR, nome)
        if not os.path.isdir(percorso):
            continue
        m = _USER_FOLDER_RE.match(nome)
        if m and int(m.group(1)) == user_id:
            return percorso
    return None


def ensure_user_folder(user_id: int, username: str) -> str:
    """La cartella di ingest di questo utente, creandola se manca.

    Idempotente: se una cartella con quell'id in testa esiste gia' — anche
    con uno username vecchio nel nome — si usa quella e non se ne crea una
    seconda."""
    esistente = find_user_folder(user_id)
    if esistente:
        return esistente
    percorso = os.path.join(config.INGEST_DIR, folder_name_for(user_id, username))
    os.makedirs(percorso, exist_ok=True)
    log_message("info", "ingest", f"Created the per-user ingest folder '{os.path.basename(percorso)}'")
    return percorso


def ensure_all_user_folders(db) -> None:
    """Una cartella per ogni utente esistente. Chiamata all'avvio (main.py)
    cosi' il primo deploy le fa nascere da solo, senza mani."""
    # Import locale per evitare il ciclo models -> services -> models.
    from .. import models
    os.makedirs(config.INGEST_DIR, exist_ok=True)
    for user_id, username in db.query(models.User.id, models.User.username).all():
        ensure_user_folder(user_id, username)


def owner_id_from_path(file_path: str) -> int | None:
    """L'id utente dichiarato dal percorso, o None.

    Un file in `ingest/<id>-<nome>/...` appartiene a quell'id (anche in una
    sottocartella piu' profonda: conta il primo segmento). Un file nella
    radice di ingest, fuori da ingest, o in una cartella che non ha un id in
    testa, non appartiene a nessuno. Qui NON si controlla che l'utente
    esista: lo fa chi stagia, che ha una sessione di database in mano."""
    rel = os.path.relpath(os.path.abspath(file_path), config.INGEST_DIR)
    parti = rel.split(os.sep)
    if len(parti) < 2 or parti[0] in (".", ".."):
        return None
    m = _USER_FOLDER_RE.match(parti[0])
    return int(m.group(1)) if m else None


def is_hidden_ingest_path(file_path: str) -> bool:
    """Se un segmento del percorso dentro ingest comincia con un punto.

    Con la scansione ricorsiva entrano in vista anche le cartelle di
    servizio dei sincronizzatori (`.stfolder`, `.stversions` di Syncthing):
    quello che ci sta dentro non e' un libro da mettere in attesa."""
    rel = os.path.relpath(os.path.abspath(file_path), config.INGEST_DIR)
    parti = rel.split(os.sep)
    if parti and parti[0] == "..":
        return False
    return any(p.startswith(".") for p in parti)
