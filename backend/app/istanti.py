"""
Un istante come un client deve poterlo leggere.

**Perche' esiste questo file** (04/11/2026). Il server tiene le date in UTC —
`datetime.utcnow()` in tutto `models.py` — e le mandava **senza dirlo**:
`"2026-11-04 21:00:00"`, oppure `"2026-11-04T21:00:00"`. Un client che le
legge con gli strumenti normali (`new Date(...)` in JavaScript,
`fromisoformat` in Python) le interpreta come **ora locale**, perche' e' cosi'
che dicono di fare le specifiche quando il fuso non c'e'. Lo sbaglio e' di
tutto l'offset: in Italia un'ora d'inverno e due d'estate, e per un istante
vicino a mezzanotte e' il giorno sbagliato.

Non era ipotetico: il plugin Obsidian scriveva negli appunti di Paolo le date
spostate di un'ora, e per un'evidenziazione presa dopo le 22 il giorno prima.
Il lettore web faceva lo stesso. Il frontend no, ma solo perche' ha una
funzione che rimette la «Z» che il server non metteva — cioe' il silenzio del
server costava a ogni client una funzione che non dovrebbe servire. E il
server lo sapeva fare: dove doveva parlare con uno standard (l'OPDS)
dichiarava il fuso da sempre.

**Perche' `+00:00` e non `Z`**, che sono entrambi ISO 8601 validi: e' la forma
che `datetime.fromisoformat` accetta in ogni versione di Python, e' quella che
`calibre/library.py::_now_iso` usa gia', e JavaScript le legge entrambe. Una
forma sola in tutto il progetto vale piu' della sua brevita'.

**Cosa NON fa questa funzione.** Non tocca una data senza ora: un giorno di
calendario (`.date().isoformat()`, "2026-11-04") non ha un fuso, e
dichiararglielo vorrebbe dire inventare un'ora.
"""

from datetime import date, datetime, timezone
from typing import Optional, Union


def quando(dt: Optional[datetime]) -> Optional[str]:
    """
    Un istante in ISO 8601 col fuso dichiarato, o `None` se non c'e' istante.

    Una data **senza** fuso viene dal nostro database, dove si scrive UTC:
    quindi si dichiara UTC, non si converte. Una data che il fuso ce l'ha
    gia' si **converte** in UTC: dichiararla sarebbe spostare l'istante di
    cui si sta parlando.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.astimezone(timezone.utc).isoformat()


def giorno(d: Optional[Union[date, datetime]]) -> Optional[str]:
    """
    Un giorno di calendario, `YYYY-MM-DD`, o `None`.

    **Esiste per dire a voce che non e' un istante.** La striscia di giorni di
    lettura comincia «il 3 ottobre», non «il 3 ottobre alle 00:00 UTC»: quelle
    sono date, e appiccicare loro un fuso vorrebbe dire inventare un'ora che
    nessuno ha misurato — e poi vederla slittare al giorno prima per chi legge
    da un fuso a ovest.

    Il motivo per cui questa funzione non si limita a un `.isoformat()`
    scritto sul posto e' il controllo sul sorgente in
    `prove/istanti_col_fuso.py`: quel controllo rifiuta ogni `.isoformat()`
    nei moduli dell'API, perche' nove volte su dieci e' un istante senza
    fuso. Chiamare `giorno()` e' il modo di dire «questa volta e' la decima»,
    e di dirlo in un posto dove si legge.
    """
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date().isoformat()
    return d.isoformat()
