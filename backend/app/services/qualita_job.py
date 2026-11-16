"""
La coda che misura la qualita' degli EPUB, e l'involucro intorno alla misura.

**La divisione dei compiti, che e' la ragione di questo file.**
`qualita_epub.py` e' una funzione pura: apre un file, torna un dizionario, e
non sa niente di Kolibre. Tutto il resto — limite di tempo, eccezioni, coda,
salvataggio, quando rifare — sta qui. Serve perche' quella funzione si studia
FUORI dal progetto, su una biblioteca di prova, e ogni volta che cambia la si
sostituisce intera: se dentro ci fosse una riga di Kolibre, sostituirla
diventerebbe un lavoro invece di una copia.

**Un libro non puo' fermare la coda.** L'analisi gira in un processo a parte
con un tempo massimo, perche' in Python un ciclo impazzito dentro un thread
non si interrompe in nessun altro modo: niente segnali, niente kill. Scaduto
il tempo, o esplosa l'analisi, il libro si registra come `errore_analisi` col
motivo e il giro continua. Il processo si crea con «spawn» e non con «fork»:
dentro un server che ha gia' dei thread, fork copia anche i lucchetti che
quei thread stanno tenendo, e il figlio nasce bloccato per sempre.
Se il processo separato non si riesce a creare — un ambiente che non lo
permette — si analizza qui, senza tempo massimo, e lo si scrive nel registro:
meglio una coda che in teoria si puo' impuntare che nessuna misura.

**Quando un libro si rianalizza.** Tre casi, e nessuno di questi e' «ogni
volta»: non c'e' ancora una riga; il file e' cambiato (dimensione o data di
modifica — vedi `QualitaLibro`); la riga e' stata scritta da una VERSIONE
piu' vecchia della misura. L'ultimo caso e' in fondo alla coda apposta: i
libri mai misurati vengono prima di quelli misurati con regole vecchie.
"""

import concurrent.futures
import json
import multiprocessing
import os
import threading
from collections import deque
from datetime import datetime

from .. import config, database, models
from ..calibre.library import CalibreLibrary
from ..istanti import quando
from ..logging_utils import log_message
from . import app_settings, qualita_epub

VERSIONE = qualita_epub.VERSIONE

# Il tempo massimo per un libro. Sui 1139 della biblioteca di prova la media
# e' 0,08 secondi e il peggiore sta sotto i due: un minuto non e' una soglia
# da sfiorare, e' il segnale che quel file non finisce.
LIMITE_SECONDI = 60

# Solo gli EPUB. Un PDF non ha indice, ne' marcatura, ne' CSS: dargli un
# numero calcolato con queste regole vorrebbe dire un'altra cosa, e chi legge
# la tabella non potrebbe saperlo.
FORMATO = "EPUB"

_lock = threading.Lock()
_in_coda: deque = deque()        # nomi di cartella delle biblioteche da fare
_stato = {
    "in_corso": False,
    "biblioteca": None,
    "fatti": 0,
    "totale": 0,
    "errori": 0,
    "avviato_il": None,
    "finito_il": None,
    "versione": VERSIONE,
}


def stato() -> dict:
    """Istantanea sicura da leggere mentre il thread lavora."""
    with _lock:
        s = dict(_stato)
        s["in_coda"] = list(_in_coda)
        return s


# ── la misura, con il tempo massimo ──────────────────────────────────────

# Quando il processo separato non si puo' proprio usare. Si scopre provando,
# una volta sola: dopo, si misura qui senza riprovare ogni libro.
_processo_rotto = False


def _misura_qui(percorso: str) -> tuple:
    try:
        return qualita_epub.qualita_epub(percorso), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def analizza_file(percorso: str, limite: int = LIMITE_SECONDI) -> tuple:
    """
    Misura un file. Torna `(risultato, errore)`: uno dei due e' sempre None.

    Qui dentro non si solleva niente: un file rotto e' un dato, non un
    guasto del server.

    **Tre esiti diversi, e vanno tenuti distinti.** Il tempo scaduto e'
    un giudizio sul FILE (quel libro non finisce di essere misurato) e si
    registra come tale. Un'eccezione dentro la misura e' un giudizio sul
    file anche quella. Ma un processo figlio che non parte proprio non
    dice niente sul file: e' l'ambiente che non lo permette, e allora si
    misura qui invece di marcare come illeggibile ogni libro della
    biblioteca. La differenza si e' vista provandola: lanciando il codice
    da standard input, «spawn» non riesce a reimportare il modulo
    principale e muore prima di cominciare — e la prima stesura di questa
    funzione registrava quel guasto come un difetto del libro.
    """
    global _processo_rotto
    if _processo_rotto:
        return _misura_qui(percorso)
    try:
        contesto = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(max_workers=1, mp_context=contesto) as pool:
            futuro = pool.submit(qualita_epub.qualita_epub, percorso)
            try:
                return futuro.result(timeout=limite), None
            except concurrent.futures.TimeoutError:
                # Uscendo dal `with` il processo viene terminato: e' il solo
                # modo di fermare davvero un'analisi che non finisce.
                for p in pool._processes.values():
                    p.kill()
                return None, f"timed out ({limite}s)"
    except concurrent.futures.process.BrokenProcessPool as e:
        _processo_rotto = True
        log_message("warning", "qualita",
                    f"The separate process is unusable ({type(e).__name__}): "
                    "from here on measuring happens in the server process, with no time limit")
        return _misura_qui(percorso)
    except OSError as e:
        _processo_rotto = True
        log_message("warning", "qualita",
                    f"The separate process could not be created ({type(e).__name__}: {e}): "
                    "from here on measuring happens in the server process, with no time limit")
        return _misura_qui(percorso)
    except Exception as e:
        # Un'eccezione uscita DALLA MISURA: e' un giudizio sul file.
        return None, f"{type(e).__name__}: {e}"


def impronta(percorso: str) -> tuple:
    """Dimensione e data di modifica: l'impronta del file. Vedi QualitaLibro."""
    st = os.stat(percorso)
    return st.st_size, st.st_mtime


def _da_rifare(riga, byte: int, mtime: float) -> bool:
    if riga is None:
        return True
    if riga.versione != VERSIONE:
        return True
    # Il confronto della data con una tolleranza: fra un filesystem e l'altro
    # i decimali non sopravvivono sempre, e un millesimo di secondo non e' un
    # file cambiato.
    return riga.file_byte != byte or abs((riga.file_mtime or 0) - mtime) > 1.0


def _salva(db, library: str, book_id: int, percorso: str, risultato, errore) -> None:
    riga = db.query(models.QualitaLibro).filter(
        models.QualitaLibro.library == library,
        models.QualitaLibro.calibre_book_id == book_id,
    ).first()
    if riga is None:
        riga = models.QualitaLibro(library=library, calibre_book_id=book_id)
        db.add(riga)
    try:
        byte, mtime = impronta(percorso)
    except OSError:
        byte, mtime = None, None
    riga.formato = FORMATO
    riga.file_byte, riga.file_mtime = byte, mtime
    riga.versione = VERSIONE
    riga.analizzato_il = datetime.utcnow()
    if risultato is None:
        riga.stato = "errore_analisi"
        riga.punteggio = None
        riga.pronto = None
        riga.risultato = None
        riga.errore = errore
    else:
        riga.stato = "ok"
        riga.punteggio = risultato.get("punteggio")
        riga.pronto = bool(risultato.get("pronto"))
        riga.risultato = json.dumps(risultato, ensure_ascii=False)
        riga.errore = None


# ── il giro su una biblioteca ────────────────────────────────────────────

def _lavoro(db, library: str) -> list:
    """I libri da misurare, nell'ordine: prima i mai visti, poi i vecchi."""
    try:
        lib = CalibreLibrary(config.library_path(library))
        libri = lib.list_books()
    except Exception as e:
        log_message("error", "qualita", f"Library '{library}' could not be read: {e}")
        return []

    righe = {r.calibre_book_id: r for r in db.query(models.QualitaLibro).filter(
        models.QualitaLibro.library == library).all()}
    nuovi, vecchi = [], []
    for libro in libri:
        # `formats` e' una lista di STRINGHE («EPUB», «PDF»), non di
        # dizionari: list_books le appiattisce (calibre/library.py:423).
        # Scritto col .get() addosso, il giro moriva sul primo libro e il
        # thread della coda spariva in silenzio.
        formati = {(f or "").upper() for f in (libro.get("formats") or [])}
        if FORMATO not in formati:
            continue
        percorso = lib.get_format_file_path(libro["id"], FORMATO)
        if not percorso:
            continue
        try:
            byte, mtime = impronta(percorso)
        except OSError:
            continue
        riga = righe.get(libro["id"])
        if not _da_rifare(riga, byte, mtime):
            continue
        # I mai misurati prima di quelli da rifare per versione: chi guarda la
        # tabella vuole vedere i buchi riempirsi, non i numeri spostarsi di uno.
        (vecchi if riga is not None and riga.versione != VERSIONE else nuovi).append((libro["id"], percorso))
    return nuovi + vecchi


def _giro() -> None:
    db = database.SessionLocal()
    try:
        while True:
            with _lock:
                if not _in_coda:
                    # `quando()` e non `.isoformat()`: questi due istanti
                    # escono verso un client (`api/qualita.py` li serve in
                    # `/qualita/stato`), e una data senza fuso un client la
                    # legge come ora locale — sbagliata di tutto l'offset.
                    _stato.update(in_corso=False, biblioteca=None,
                                  finito_il=quando(datetime.utcnow()))
                    return
                library = _in_coda.popleft()
                _stato.update(biblioteca=library, fatti=0, totale=0, errori=0)

            lavoro = _lavoro(db, library)
            with _lock:
                _stato["totale"] = len(lavoro)
            if lavoro:
                log_message("info", "qualita", f"Quality: {len(lavoro)} books to measure in '{library}'")
            for book_id, percorso in lavoro:
                risultato, errore = analizza_file(percorso)
                try:
                    _salva(db, library, book_id, percorso, risultato, errore)
                    db.commit()
                except Exception as e:
                    db.rollback()
                    log_message("error", "qualita", f"Quality not saved for book {book_id}: {e}")
                with _lock:
                    _stato["fatti"] += 1
                    if errore:
                        _stato["errori"] += 1
            if lavoro:
                log_message("info", "qualita", f"Qualita': finita '{library}'")
    finally:
        db.close()


def accoda(library: str, forza: bool = False) -> bool:
    """
    Mette una biblioteca in coda. Torna False se e' spenta per quella
    biblioteca, o se e' gia' in coda.

    `forza` serve al pulsante «Analizza tutto»: riscrive anche le righe
    buone, perche' chi preme quel pulsante lo fa proprio quando non si fida
    di quello che c'e'.
    """
    db = database.SessionLocal()
    try:
        if not app_settings.is_qualita_enabled(db, library):
            return False
        if forza:
            db.query(models.QualitaLibro).filter(models.QualitaLibro.library == library).delete()
            db.commit()
    finally:
        db.close()
    with _lock:
        if library in _in_coda or _stato.get("biblioteca") == library:
            return False
        _in_coda.append(library)
        if _stato["in_corso"]:
            return True
        _stato.update(in_corso=True, avviato_il=quando(datetime.utcnow()), finito_il=None)
    threading.Thread(target=_giro, daemon=True, name="qualita").start()
    return True


def accoda_tutte() -> int:
    """All'avvio del server: ogni biblioteca accesa va in coda da sola."""
    db = database.SessionLocal()
    try:
        cartelle = [b.folder_name for b in db.query(models.Library).all()]
    finally:
        db.close()
    return sum(1 for c in cartelle if accoda(c))


def analizza_libro_async(library: str, book_id: int, percorso: str) -> None:
    """
    Misura UN libro appena importato, in sottofondo.

    Serve perche' il travaso dall'ingest fallisce quasi sempre proprio nel
    caso normale: se l'incorporamento del conteggio pagine e' acceso, Kolibre
    riscrive l'EPUB subito dopo averlo copiato, e il file nella biblioteca non
    e' piu' quello misurato in ingest. Senza questa chiamata il libro
    resterebbe senza punteggio fino al prossimo giro della coda.
    """
    def _fai():
        db = database.SessionLocal()
        try:
            risultato, errore = analizza_file(percorso)
            _salva(db, library, book_id, percorso, risultato, errore)
            db.commit()
        except Exception as e:
            db.rollback()
            log_message("error", "qualita", f"Quality not measured for book {book_id}: {e}")
        finally:
            db.close()

    threading.Thread(target=_fai, daemon=True, name=f"qualita-libro-{book_id}").start()


# ── i file in ingest ─────────────────────────────────────────────────────

def analizza_ingest(item_id: int) -> None:
    """
    Misura un file appena messo in lista per l'importazione, in sottofondo.

    Si fa qui e non quando qualcuno apre la pagina perche' il punto di questo
    numero e' scegliere fra due versioni dello stesso libro *prima* di
    importarlo: deve essere gia' li' quando guardi.
    """
    threading.Thread(target=_analizza_ingest, args=(item_id,), daemon=True,
                     name=f"qualita-ingest-{item_id}").start()


def _analizza_ingest(item_id: int) -> None:
    db = database.SessionLocal()
    try:
        item = db.query(models.IngestedBook).filter(models.IngestedBook.id == item_id).first()
        if not item or (item.file_format or "").upper() != FORMATO:
            return
        if not os.path.isfile(item.file_path):
            return
        risultato, errore = analizza_file(item.file_path)
        if risultato is None:
            risultato = {"versione": VERSIONE, "leggibile": False, "pronto": False,
                         "si_sistema_da_solo": False, "punteggio": 0, "dimensioni": {},
                         "misure": {}, "difetti": [], "errore_analisi": errore}
        item.qualita_punteggio = risultato.get("punteggio")
        item.qualita_json = json.dumps(risultato, ensure_ascii=False)
        db.commit()
    except Exception as e:
        db.rollback()
        log_message("error", "qualita", f"Quality not measured during ingest ({item_id}): {e}")
    finally:
        db.close()


def travasa_da_ingest(db, item, library: str, book_id: int, percorso: str) -> bool:
    """
    All'importazione: il risultato gia' calcolato sul file in ingest diventa
    la riga della biblioteca, se il file e' lo stesso.

    Il confronto e' sulla dimensione: il percorso cambia (il file si sposta
    dentro la biblioteca) e la data di modifica pure, quindi l'impronta non
    serve a niente qui. Se Kolibre riscrive l'EPUB per metterci il conteggio
    delle pagine la dimensione cambia, e allora non si travasa: il libro
    finisce in coda come tutti gli altri, che e' la risposta giusta.
    """
    if not item or not item.qualita_json:
        return False
    try:
        risultato = json.loads(item.qualita_json)
    except ValueError:
        return False
    if risultato.get("versione") != VERSIONE:
        return False
    try:
        byte, mtime = impronta(percorso)
    except OSError:
        return False
    if item.file_size_bytes is not None and byte != item.file_size_bytes:
        return False
    _salva(db, library, book_id, percorso, risultato, None)
    return True
