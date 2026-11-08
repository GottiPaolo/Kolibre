"""
Note VEDOVE: accoppiate a un libro che nella libreria non c'e' piu'.

E' il terzo stato di una nota, e finora non aveva nome. Gli altri due sono
noti e gestiti: accoppiata (Highlight con un libro vivo) e orfana
(OrphanHighlight, file mai riconosciuto, con la sua pagina "Da rivedere").
Questo e' il caso di mezzo — la nota HA un (library, calibre_book_id), ma
quell'id non esiste piu'.

Non e' un'ipotesi: su un impianto reale, 266 note su 1019 puntavano a un
libro cancellato, 246 delle quali da un solo libro. E' la conseguenza
diretta di una scelta giusta — release_book lascia di proposito le note di
un libro cancellato, perche' sono roba scritta dall'utente e cancellare un
libro non deve distruggerle — per la quale pero' non era stato costruito
niente: nessuno le riconosceva, la conversione CFI ci sbatteva contro e le
marchiava 'failed' per sempre (stato che per progetto non si ritenta mai),
e il 28% di "conversioni fallite" che ne risultava nascondeva il fatto che
sui libri vivi la conversione riesce nel 99,6% dei casi.

Il rimedio parte da un'osservazione: un libro sparisce spesso
perche' e' stato cancellato e REIMPORTATO — corretto l'EPUB, rifatti i
metadati — e quindi lo stesso testo e' ancora in biblioteca sotto un altro
id. Il testo della nota e' allora la chiave per ritrovarlo: si cerca una
frase di ogni nota nell'indice full-text della libreria e si guarda su quale
libro convergono. Verificato sui tre casi reali di un impianto in uso: 78/78
riscontri, 19/19 e 1/1, tutti su libri effettivamente presenti.
"""

import os
import re
import sqlite3
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from .. import config, models
from . import fulltext_index

# Quante note al massimo si interrogano per proporre un libro: il voto si
# stabilizza molto prima, e ogni frase e' una query FTS su un indice che su
# una biblioteca reale pesa 2 GB.
_MAX_NOTE_PER_PROPOSTA = 25

# Parole della nota usate come frase di ricerca. Si salta l'inizio perche' un
# ritaglio di KOReader comincia spesso a meta' parola o dentro la
# punteggiatura, e si prendono abbastanza parole da rendere la frase unica.
_SALTA_PAROLE = 2
_PAROLE_FRASE = 8
_MIN_PAROLE = _SALTA_PAROLE + _PAROLE_FRASE


_ids_cache: dict = {}


def ids_libri_esistenti(library: str) -> Optional[set]:
    """
    Gli id dei libri che la libreria contiene davvero, letti dal metadata.db
    di Calibre in sola lettura. None se la libreria non si riesce ad aprire —
    il chiamante deve trattarlo come "non lo so", MAI come "nessun libro
    esiste": marcare vedove tutte le note di una libreria solo perche' il
    disco non risponde sarebbe il danno peggiore di quello che si ripara.

    Il risultato e' tenuto da parte finche' il metadata.db non cambia (stessa
    chiave dimensione+data usata per la struttura degli EPUB): lo interroga
    anche il risolutore degli hash, su cui passa ogni nota e ogni posizione
    di lettura, e rileggerlo ogni volta sarebbe una lettura di disco per nota.
    """
    percorso = os.path.join(config.library_path(library), "metadata.db")
    try:
        st = os.stat(percorso)
        chiave = (percorso, st.st_size, st.st_mtime_ns)
    except OSError:
        return None
    memo = _ids_cache.get(library)
    if memo and memo[0] == chiave:
        return memo[1]
    try:
        conn = sqlite3.connect(f"file:{percorso}?mode=ro", uri=True)
        try:
            ids = {r[0] for r in conn.execute("SELECT id FROM books")}
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    _ids_cache[library] = (chiave, ids)
    return ids


# Nome storico, usato nel resto di questo modulo.
_ids_esistenti = ids_libri_esistenti


def find_widowed_groups(db: Session, user_id: Optional[int] = None) -> List[dict]:
    """
    Le note vedove raggruppate per libro perduto, ordinate dalla perdita piu'
    grossa. Una interrogazione a metadata.db per libreria, non per nota.
    """
    q = db.query(
        models.Highlight.library, models.Highlight.calibre_book_id
    ).filter(models.Highlight.deleted_at.is_(None))
    if user_id is not None:
        q = q.filter(models.Highlight.user_id == user_id)
    coppie = q.distinct().all()

    esistenti: dict = {}
    gruppi = []
    for library, book_id in coppie:
        if library not in esistenti:
            esistenti[library] = _ids_esistenti(library)
        ids = esistenti[library]
        if ids is None or book_id in ids:
            continue
        note = db.query(models.Highlight).filter(
            models.Highlight.library == library,
            models.Highlight.calibre_book_id == book_id,
            models.Highlight.deleted_at.is_(None),
        ).order_by(models.Highlight.id).all()
        capitoli = []
        for n in note:
            if n.chapter and n.chapter not in capitoli:
                capitoli.append(n.chapter)
        gruppi.append({
            "library": library,
            "calibre_book_id": book_id,
            "count": len(note),
            # Di che libro si trattasse non lo sa piu' nessuno: il titolo se
            # n'e' andato con la riga di Calibre. I capitoli e qualche riga
            # di testo sono tutto quello che resta per riconoscerlo a occhio.
            "chapters": capitoli[:6],
            "samples": [n.text[:160] for n in note[:3] if n.text],
        })
    return sorted(gruppi, key=lambda g: -g["count"])


def _frasi_di_ricerca(testi: Iterable[str]) -> List[str]:
    frasi = []
    for t in testi:
        parole = re.findall(r"\w+", t or "")
        if len(parole) < _MIN_PAROLE:
            continue
        frasi.append(" ".join(parole[_SALTA_PAROLE:_SALTA_PAROLE + _PAROLE_FRASE]))
    return frasi


def suggest_books(db: Session, library: str, calibre_book_id: int, user_id: int) -> dict:
    """
    Quali libri della biblioteca contengono il testo di queste note.

    Cerca ogni frase come frase esatta (le virgolette sono sintassi FTS5) e
    conta su quale libro convergono. Il risultato e' una PROPOSTA con il suo
    punteggio, mai un'azione: due edizioni dello stesso testo prendono lo
    stesso punteggio pieno — succede davvero: in un caso reale lo stesso
    volume catalogato due volte, una col titolo dell'opera e una col titolo
    della sua prima sezione, ha fatto 78/78 in entrambe le righe — e a
    scegliere fra le due deve essere una persona.
    """
    note = db.query(models.Highlight.text).filter(
        # Le proprie: la proposta si costruisce sul testo delle note, e quelle
        # di un altro utente non devono entrare nel conto ne' uscirne.
        models.Highlight.user_id == user_id,
        models.Highlight.library == library,
        models.Highlight.calibre_book_id == calibre_book_id,
        models.Highlight.deleted_at.is_(None),
        models.Highlight.text.isnot(None),
    ).limit(_MAX_NOTE_PER_PROPOSTA * 3).all()
    frasi = _frasi_di_ricerca(t for (t,) in note)[:_MAX_NOTE_PER_PROPOSTA]
    if not frasi:
        return {"searched": 0, "candidates": []}

    library_path = config.library_path(library)
    ids = _ids_esistenti(library) or set()
    voti: dict = {}
    cercate = 0
    for frase in frasi:
        try:
            risultati = fulltext_index.search(library_path, f'"{frase}"', limit=5)
        except Exception:
            continue
        cercate += 1
        for r in risultati:
            bid = r.get("book_id")
            # L'indice full-text conserva le righe dei libri cancellati (il
            # reindex non le ripulisce): senza questo filtro una nota vedova
            # ritroverebbe se stessa nel proprio libro sparito, che e'
            # esattamente il contrario di quello che serve.
            if bid is None or bid == calibre_book_id or bid not in ids:
                continue
            voti[bid] = voti.get(bid, 0) + 1

    from ..calibre.library import CalibreLibrary
    lib = CalibreLibrary(library_path)
    candidati = []
    for bid, n in sorted(voti.items(), key=lambda x: -x[1])[:5]:
        try:
            book = lib.get_book(bid)
        except Exception:
            book = None
        if not book:
            continue
        candidati.append({
            "calibre_book_id": bid,
            "library": library,
            "title": book.get("title"),
            # get_book non restituisce "authors": la riga di Calibre porta
            # author_sort, gli autori veri stanno nella tabella di
            # collegamento. Per riconoscere un libro in un elenco di
            # proposte, la forma d'ordinamento ("Cognome, Nome") basta e
            # avanza.
            "authors": book.get("authors") or book.get("author_sort"),
            "matches": n,
        })
    return {"searched": cercate, "candidates": candidati}


def repair(db: Session, library: str, calibre_book_id: int, target_library: str, target_book_id: int, user_id: int) -> int:
    """
    Riporta le note vedove sul libro scelto. Azzera anche cfi/position_status:
    la conversione era fallita solo perche' il file non c'era, e col libro
    nuovo va rifatta da capo invece di restare marchiata come impossibile.
    Non fa commit — decide il chiamante.

    Sposta anche gli HASH, e non e' un dettaglio: il file sul dispositivo e'
    ancora quello, e il suo hash continuerebbe a risolvere al libro morto
    (le righe BookHash dei libri cancellati restano). Alla prima
    sincronizzazione le note vedove si ricreerebbero tali e quali, e la
    riparazione sarebbe durata fino al sync successivo. Dire "quell'hash e'
    questo libro" e' del resto la verita': il dispositivo ha in mano
    esattamente il libro che si e' appena scelto.
    """
    from . import book_hash_service

    vecchi = db.query(models.BookHash).filter(
        models.BookHash.library == library,
        models.BookHash.calibre_book_id == calibre_book_id,
    ).all()
    for riga in vecchi:
        if riga.file_hash:
            book_hash_service.record_device_hash(
                db, target_library, target_book_id, riga.format or "EPUB", riga.file_hash
            )
        db.delete(riga)

    # Solo le proprie: su una biblioteca condivisa, senza questo filtro chi
    # ripara le proprie note vedove spostava anche quelle di tutti gli altri
    # sul libro che aveva scelto lui. find_widowed_groups qui sopra filtra per
    # utente, quindi l'elenco mostrato era gia' giusto: era l'azione a non
    # esserlo.
    return db.query(models.Highlight).filter(
        models.Highlight.user_id == user_id,
        models.Highlight.library == library,
        models.Highlight.calibre_book_id == calibre_book_id,
        models.Highlight.deleted_at.is_(None),
    ).update(
        {
            "library": target_library,
            "calibre_book_id": target_book_id,
            "cfi_start": None,
            "cfi_end": None,
            "position_status": None,
        },
        synchronize_session=False,
    )
