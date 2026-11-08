"""
Chi puo' fare cosa.

Due famiglie, come disegnate il 24/09/2026, e la distinzione non
e' burocratica: rispondono a domande di tipo diverso.

**Legati alla coppia utente-biblioteca** — modificare, condividere a sua
volta, gestire i permessi degli altri su quella biblioteca. Dipendono da
*quale* biblioteca.

**Legati all'account** — creare biblioteche, creare utenti, gestire i permessi
altrui, registrare dispositivi, modificare gli autori. Non dipendono da
nessuna biblioteca: "posso crearne una?" non ha un complemento di luogo.

Il **fondatore** sta fuori da ogni limitazione, ed e' l'unico. Ha un flag
esplicito e non e' "l'utente con id 1": un id non e' un ruolo.

---

Una cosa che questo modulo NON fa, di proposito: filtrare i dati personali.
Permesso e proprieta' sono cose diverse. Avere accesso a una biblioteca
condivisa non da' accesso alle annotazioni di chi altro la legge — quelle
sono private per utente (decisione del 28/09), e il filtro sta nelle query,
dove sta gia'. Il confine e' coperto da una prova di isolamento fra utenti,
che va tenuta viva.
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import auth, database, models


def _permesso(db: Session, user_id: int, library_id: int):
    return db.query(models.LibraryPermission).filter(
        models.LibraryPermission.user_id == user_id,
        models.LibraryPermission.library_id == library_id,
    ).first()


def biblioteche_visibili(db: Session, utente: models.User) -> list:
    """Le righe Library che questa persona puo' vedere.

    Il fondatore le vede tutte. Gli altri vedono quelle che possiedono piu'
    quelle su cui hanno una riga di permesso: l'esistenza della riga E' il
    permesso di leggere.
    """
    if utente.is_founder:
        return db.query(models.Library).order_by(models.Library.sort_order, models.Library.id).all()
    condivise = {
        p.library_id for p in db.query(models.LibraryPermission).filter(
            models.LibraryPermission.user_id == utente.id
        ).all()
    }
    return [
        row for row in db.query(models.Library)
        .order_by(models.Library.sort_order, models.Library.id).all()
        if row.owner_id == utente.id or row.id in condivise
    ]


def cartelle_leggibili(db: Session, utente: models.User):
    # -> set[str] con un utente, None senza: vedi l'ultimo capoverso.
    """I nomi di CARTELLA delle biblioteche che questa persona puo' leggere.

    **Perche' serve una seconda forma di `biblioteche_visibili`.** Quella
    torna righe `Library`, ed e' giusto per chi deve mostrare un elenco: il
    nome, l'ordine, il proprietario. Ma gli endpoint che aggregano piu'
    biblioteche non partono dal registro — camminano su
    `os.listdir(LIBRARIES_DIR)`, perche' e' il disco a dire quali
    `metadata.db` esistono — e quello che hanno in mano e' un nome di
    cartella. Chiedere a ognuno di ricostruirsi l'insieme e' il modo in cui
    un filtro finisce dimenticato in uno dei quattro posti (8/11/2026: era
    dimenticato in tutti e quattro).

    **Torna None quando non c'e' niente da restringere**, e sono due casi:
    il fondatore, che sta fuori da ogni limitazione, e `utente` a None, che
    vuol dire «qui non si e' passati dall'autenticazione» — un problema
    diverso, che si risolve prima (vedi `_AUTH` in main.py). E' la stessa
    convenzione di `esigi_biblioteca_scrivibile` e `default_library_param`.

    Chi chiama distingue con `is None`, mai con la verita' dell'insieme: un
    utente senza nessuna biblioteca ha un insieme **vuoto**, e vuoto non
    vuol dire «tutte» — vuol dire «nessuna», che e' il caso che l'8/11/2026
    si e' scoperto trattato come «tutte».

    E None non e' solo una comodita' di scrittura: e' quello che permette a
    chi aggrega di restare sulla strada veloce — la cache delle pagine per
    autore e' una somma su tutto il server, e una somma non sa chi la sta
    guardando, quindi vale per chi vede tutto e per nessun altro.

    Una cartella sul disco senza riga nel registro non c'e' dentro, e quindi
    non si vede: e' il contrario di quanto fa `default_library_param`, che la
    lascia passare perche' esiste quell'istante — durante una creazione o
    una scansione — in cui la cartella c'e' e la riga non ancora. La
    differenza e' voluta: la' si tratta di non rifiutare una biblioteca che
    si sta creando, qui di non mostrarne una di cui non si sa ancora di chi
    sia. Dura un istante, e sbaglia dalla parte giusta.
    """
    if utente is None or utente.is_founder:
        return None
    return {riga.folder_name for riga in biblioteche_visibili(db, utente)}


def puo_leggere(db: Session, utente: models.User, biblioteca: models.Library) -> bool:
    if utente.is_founder or biblioteca.owner_id == utente.id:
        return True
    return _permesso(db, utente.id, biblioteca.id) is not None


def puo_modificare(db: Session, utente: models.User, biblioteca: models.Library) -> bool:
    if utente.is_founder or biblioteca.owner_id == utente.id:
        return True
    riga = _permesso(db, utente.id, biblioteca.id)
    return bool(riga and riga.can_edit)


def puo_condividere(db: Session, utente: models.User, biblioteca: models.Library) -> bool:
    if utente.is_founder or biblioteca.owner_id == utente.id:
        return True
    riga = _permesso(db, utente.id, biblioteca.id)
    return bool(riga and (riga.can_share or riga.can_manage))


def puo_gestire_permessi(db: Session, utente: models.User, biblioteca: models.Library) -> bool:
    if utente.is_founder or biblioteca.owner_id == utente.id:
        return True
    riga = _permesso(db, utente.id, biblioteca.id)
    return bool(riga and riga.can_manage)


def puo_cancellare(db: Session, utente: models.User, biblioteca: models.Library) -> bool:
    """Solo il proprietario — e il fondatore, che e' fuori da tutto.

    Decisione del 28/09: cancellare una biblioteca non e' una
    modifica piu' grande delle altre, e' un'altra cosa. Chi puo' modificare
    puo' sbagliare un titolo; chi puo' cancellare porta via i libri a tutti
    quelli con cui e' condivisa."""
    return bool(utente.is_founder or biblioteca.owner_id == utente.id)


# ── Permessi dell'account, come dipendenze FastAPI ────────────────────────
#
# Il fondatore passa sempre. Nessun controllo separato per `is_admin`: resta
# quello che era, l'amministratore tecnico dell'impianto, e sui permessi non
# vale piu' di quanto valga il flag specifico.

def _richiede(campo: str, cosa: str):
    def dipendenza(
        current_user: models.User = Depends(auth.get_current_user),
        db: Session = Depends(database.get_db),
    ) -> models.User:
        if current_user.is_founder or getattr(current_user, campo, False):
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Your account cannot {cosa}.",
        )
    return dipendenza


richiede_creare_biblioteche = _richiede("can_create_libraries", "create libraries")
richiede_creare_utenti = _richiede("can_create_users", "creare utenti")
richiede_gestire_permessi = _richiede("can_manage_permissions", "gestire i permessi altrui")
richiede_registrare_dispositivi = _richiede("can_register_devices", "register devices")
richiede_modificare_autori = _richiede("can_edit_authors", "edit author details")
