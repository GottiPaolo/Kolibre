"""
Le pagine di un file in attesa d'importazione, contate in sottofondo.

**Perche' esiste** (22/11/2026, richiesta di Paolo): «nell'ingest deve
caricare anche le pagine di lunghezza del libro». Il numero serve a
scegliere fra due copie simili PRIMA di importare — molto spesso si
scaricano due versioni dello stesso libro per tenerne una sola — quindi
deve essere gia' li' quando si guarda la pagina, come la qualita'
(qualita_job.analizza_ingest, che e' il modello di questo file).

**In sottofondo, come la qualita'.** Contare le pagine di un EPUB vuol
dire estrarne tutto il testo (page_counter): il watcher ha altri file da
mettere in lista e la pagina Ingest non deve aspettare. Il conteggio usa
le stesse impostazioni della biblioteca (modo parole/caratteri e relative
soglie), cosi' il numero del file in attesa e quello del libro gia' in
casa si confrontano alla pari.

**E' un'anteprima, non IL conteggio.** All'importazione le pagine si
ricontano sul file spostato, con le impostazioni di quel momento, ed e'
quel numero che finisce nella colonna #pages di Calibre: qui non cambia
niente di quel percorso.
"""

import threading

from .. import database, models
from ..logging_utils import log_message
from . import app_settings, page_counter

# I formati che page_counter sa leggere: per gli altri il numero non ci
# sara' mai, e non si avvia un thread per scoprirlo.
COUNTABLE_FORMATS = ("EPUB", "PDF", "TXT")

# Gli id con un conteggio gia' in corso, e quelli falliti. Il primo insieme
# evita i doppioni: i GET della pagina Ingest arrivano in coppia (elenco +
# impaginazione) e ognuno ripassa le righe senza numero. Il secondo evita
# di riprovare per sempre un file illeggibile a ogni apertura della pagina:
# si riprova al prossimo avvio del server, non al prossimo sguardo.
_lock = threading.Lock()
_in_flight: set = set()
_failed: set = set()


def count_in_background(item_id: int) -> None:
    """Avvia il conteggio per una riga di staging, se non e' gia' in corso
    o gia' fallito in questo processo. Innocuo chiamarla due volte."""
    with _lock:
        if item_id in _in_flight or item_id in _failed:
            return
        _in_flight.add(item_id)
    threading.Thread(target=_count, args=(item_id,), daemon=True,
                     name=f"pagine-ingest-{item_id}").start()


def _count(item_id: int) -> None:
    ok = False
    try:
        db = database.SessionLocal()
        try:
            item = db.query(models.IngestedBook).filter(models.IngestedBook.id == item_id).first()
            if not item:
                return
            if item.pages is not None:
                ok = True
                return
            if (item.file_format or "").upper() not in COUNTABLE_FORMATS:
                return
            conf = app_settings.get_page_count_settings(db)
            pages = page_counter.count_pages(
                item.file_path, item.file_format, conf["mode"],
                conf["words_per_page"], conf["chars_per_page"],
            )
            if pages is not None:
                item.pages = pages
                db.commit()
                ok = True
        except Exception as e:
            db.rollback()
            log_message("error", "pages", f"Pages not counted in ingest ({item_id}): {e}")
        finally:
            db.close()
    finally:
        with _lock:
            _in_flight.discard(item_id)
            if not ok:
                _failed.add(item_id)
