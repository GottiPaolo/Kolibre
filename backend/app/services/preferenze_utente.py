"""
Le preferenze che sono della persona, non dello schermo.

**Perche' esiste questo file** (04/11/2026). Il modello `User` non aveva
nessuna colonna di preferenze: la lingua dell'interfaccia viveva soltanto in
`localStorage` di quel browser. Un client nativo partirebbe in un'altra
lingua e non ci sarebbe nessun modo di farli accordare; svuotare i dati del
sito perdeva la scelta; due persone sullo stesso browser non potevano averne
due diverse.

**Il criterio di cosa entra qui**, scritto per intero in
`docs/inventario-regole-nel-browser.md` e in una riga questo: *se due client
dessero risposte diverse, uno dei due sarebbe in torto?* Per la lingua si' —
chi ha scelto l'italiano e si sente parlare inglese ha ragione lui. Per il
formato della data no: un client Windows che segue Windows e uno Android che
segue Android hanno ragione entrambi, e imporre loro la scelta fatta su un
portatile sarebbe un peggioramento. Delle sedici cose che il browser ricorda,
qui dentro ne viene **una**.

Il che e' il punto: questo file non e' il posto dove far migrare le
preferenze, e' il posto per le poche che sono della persona. Aggiungerne una
vuol dire prima passarla dal criterio.

**Il «non ha scelto» e' un valore, non un vuoto.** `lingua: None` vuol dire
«decidi tu, client», ed e' diverso da `lingua: "it"`. Serve a chi apre
Kolibre per la prima volta: il client guarda la lingua del sistema e parla
quella, che e' la cosa gentile. Se qui ci fosse un difetto — «italiano» —
quella gentilezza sarebbe impossibile da entrambe le parti, e un tedesco si
troverebbe l'italiano per sempre.

**Perche' un JSON e non una colonna per preferenza.** Lo stesso motivo di
`app_settings.py`, che fa cosi' da sempre: una preferenza nuova non deve
chiedere una migrazione dello schema. Si paga leggendo tutto insieme, che e'
quello che il client vuole comunque — una richiesta sola all'avvio.
"""

import json
from typing import Optional

from sqlalchemy.orm import Session

from .. import models

# Il valore di ogni preferenza quando la persona non ha scelto. `None`
# significa «decidi tu, client»: vedi la nota qui sopra.
PREDEFINITE = {
    "lingua": None,
}

LINGUE_AMMESSE = {"it", "en"}


class PreferenzaRifiutata(ValueError):
    """Un valore che non si scrive. Il messaggio e' per chi l'ha mandato."""


def leggi(db: Session, user_id: int) -> dict:
    """Le preferenze di una persona, complete dei difetti."""
    riga = db.query(models.PreferenzeUtente).filter(
        models.PreferenzeUtente.user_id == user_id).first()
    if not riga:
        return dict(PREDEFINITE)
    try:
        salvate = json.loads(riga.valore_json)
    except (TypeError, ValueError):
        # Un JSON rotto non deve impedire di entrare: si riparte dai difetti,
        # e la prossima scrittura lo sistema.
        return dict(PREDEFINITE)
    if not isinstance(salvate, dict):
        return dict(PREDEFINITE)
    return {**PREDEFINITE, **{k: v for k, v in salvate.items() if k in PREDEFINITE}}


def _controlla(cambi: dict) -> None:
    """
    Rifiuta quello che non si puo' scrivere, **dicendo cosa**.

    Una chiave sconosciuta si rifiuta invece di essere ignorata: ignorarla
    vorrebbe dire che un client con un errore di battitura crede di aver
    salvato, e il giorno che quella chiave esistera' per davvero si
    ritroverebbe un valore scritto da nessuno.
    """
    if not isinstance(cambi, dict):
        raise PreferenzaRifiutata("preferences must be sent as an object")
    sconosciute = sorted(set(cambi) - set(PREDEFINITE))
    if sconosciute:
        raise PreferenzaRifiutata(
            "these preferences do not exist: " + ", ".join(sconosciute)
            + " (the ones that do are: " + ", ".join(sorted(PREDEFINITE)) + ")"
        )
    if "lingua" in cambi:
        lingua = cambi["lingua"]
        if lingua is not None and lingua not in LINGUE_AMMESSE:
            raise PreferenzaRifiutata(
                f"language not allowed: {lingua!r} (ammesse: "
                + ", ".join(sorted(LINGUE_AMMESSE)) + ", oppure niente)"
            )


def scrivi(db: Session, user_id: int, cambi: dict) -> dict:
    """
    Cambia le preferenze indicate e lascia stare le altre, e torna il quadro
    completo come lo tornerebbe `leggi`.

    Chi manda `{"lingua": "en"}` cambia la lingua e non tocca niente che non
    ha nominato: e' quello che serve a un client che vuole cambiare una cosa
    sola senza prima leggere tutto.
    """
    _controlla(cambi)
    attuali = leggi(db, user_id)
    nuove = {**attuali, **cambi}
    riga = db.query(models.PreferenzeUtente).filter(
        models.PreferenzeUtente.user_id == user_id).first()
    if riga:
        riga.valore_json = json.dumps(nuove)
    else:
        db.add(models.PreferenzeUtente(user_id=user_id, valore_json=json.dumps(nuove)))
    db.commit()
    return nuove


def lingua_di(db: Session, user_id: int) -> Optional[str]:
    """Scorciatoia per chi ha bisogno solo della lingua (es. un'email)."""
    return leggi(db, user_id).get("lingua")
