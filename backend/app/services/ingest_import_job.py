"""
Importazione in blocco che vive sul SERVER, non nel browser.

Prima il pulsante "Importa tutti" era un ciclo nella pagina: una richiesta
HTTP per libro, e se si cambiava scheda l'operazione moriva a meta'. Su
dieci libri non si nota; su tremila e' un lavoro di minuti che nessuno puo'
stare a guardare, e interromperlo a meta' lascia la cartella in uno stato
che poi bisogna capire.

Stessa forma del giro di massa sugli autori (author_scrape_job.py), da cui
questo modulo e' modellato: un solo lavoro alla volta, guardia dove nessun
rimontaggio di componente e nessuna seconda scheda del browser puo'
azzerarla, e uno stato che si puo' interrogare da qualunque pagina.

Una differenza rispetto a quel giro: qui si usa un task asyncio e non un
thread. L'importazione passa per la coda di scrittura su metadata.db
(CalibreWriteQueue), che e' asincrona e vive sul loop dell'applicazione:
un thread a parte non potrebbe aspettarla.
"""

import asyncio
import threading
from datetime import datetime
from typing import Optional

from .. import database, models
from ..logging_utils import log_message

_lock = threading.Lock()
_state = {
    "running": False,
    "total": 0,
    "processed": 0,
    "imported": 0,
    # Errore per errore, non solo il conteggio: un'importazione che fallisce
    # su trenta libri su tremila deve poter dire QUALI, o non c'e' modo di
    # rimediare se non riprovando tutto.
    "failed": [],
    "current": None,
    "started_at": None,
    "finished_at": None,
    "cancelled": False,
}
_task: Optional[asyncio.Task] = None


def status() -> dict:
    with _lock:
        snapshot = dict(_state)
        snapshot["failed"] = list(_state["failed"])
        return snapshot


def start(voci: list, write_queue) -> bool:
    """
    `voci`: lista di (ingest_id, folder_name_destinazione).
    Torna False se un'importazione e' gia' in corso.
    """
    global _task
    with _lock:
        if _state["running"]:
            return False
        _state.update(
            running=True, total=len(voci), processed=0, imported=0,
            failed=[], current=None, cancelled=False,
            started_at=datetime.utcnow().isoformat(), finished_at=None,
        )
    try:
        _task = asyncio.create_task(_esegui(list(voci), write_queue))
    except RuntimeError:
        # Nessun event loop: lo stato era gia' stato messo a "in corso", e
        # lasciarlo li' bloccherebbe per sempre ogni avvio successivo con un
        # lavoro che non esiste. Capitato per davvero, con l'endpoint
        # dichiarato sincrono.
        with _lock:
            _state.update(running=False, finished_at=datetime.utcnow().isoformat())
        raise
    return True


def stop() -> bool:
    """Chiede di fermarsi dopo il libro in corso. Quelli gia' importati restano."""
    with _lock:
        if not _state["running"]:
            return False
        _state["cancelled"] = True
        return True


async def _esegui(voci: list, write_queue) -> None:
    # Import differito: api/ingest.py importa questo modulo per avviare il
    # lavoro, e importarlo qui in cima farebbe un giro chiuso. La funzione
    # dell'endpoint e' async e accetta argomenti espliciti, quindi si puo'
    # chiamare direttamente passandole sessione e coda — nessuna copia della
    # logica di importazione, che e' lunga e delicata (compensazione in caso
    # di fallimento a meta').
    from ..api.ingest import import_book_from_ingest
    from .. import schemas

    for ingest_id, libreria in voci:
        with _lock:
            if _state["cancelled"]:
                break
            _state["current"] = ingest_id
        db = database.SessionLocal()
        try:
            riga = db.query(models.IngestedBook).filter(models.IngestedBook.id == ingest_id).first()
            titolo = riga.title if riga else str(ingest_id)
            payload = schemas.IngestImportRequest(id=ingest_id, library=libreria)
            await import_book_from_ingest(payload, db=db, write_queue=write_queue)
            with _lock:
                _state["imported"] += 1
        except Exception as exc:
            dettaglio = getattr(exc, "detail", None) or str(exc)
            with _lock:
                _state["failed"].append({"id": ingest_id, "title": titolo, "error": str(dettaglio)[:200]})
        finally:
            db.close()
            with _lock:
                _state["processed"] += 1
        # Un respiro fra un libro e l'altro: la coda di scrittura e' condivisa
        # con le richieste normali, e un'importazione da tremila libri non
        # deve rendere il resto dell'applicazione inservibile per mezz'ora.
        await asyncio.sleep(0)

    with _lock:
        _state["running"] = False
        _state["current"] = None
        _state["finished_at"] = datetime.utcnow().isoformat()
        importati, falliti, interrotto = _state["imported"], len(_state["failed"]), _state["cancelled"]
    log_message(
        "info", "ingest",
        f"Importazione in blocco {'interrotta' if interrotto else 'completata'}: "
        f"{importati} importati, {falliti} falliti",
    )
