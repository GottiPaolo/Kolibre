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
            detail=f"Il tuo account non può {cosa}.",
        )
    return dipendenza


richiede_creare_biblioteche = _richiede("can_create_libraries", "creare biblioteche")
richiede_creare_utenti = _richiede("can_create_users", "creare utenti")
richiede_gestire_permessi = _richiede("can_manage_permissions", "gestire i permessi altrui")
richiede_registrare_dispositivi = _richiede("can_register_devices", "registrare dispositivi")
richiede_modificare_autori = _richiede("can_edit_authors", "modificare i dati degli autori")
