"""
Le sessioni di lettura di un libro che non esiste piu', spostate fra le orfane.

    docker compose exec backend python3 -m backend.app.sessioni_senza_libro
    docker compose exec backend python3 -m backend.app.sessioni_senza_libro --conferma

**Senza `--conferma` non scrive niente**: dice cosa farebbe e si ferma. E' la
forma giusta per un comando che sposta righe di dati veri — il primo giro lo
si legge, il secondo lo si fa.

────────────────────────────────────────────────────────────────────────────
DA ZERO: CHE PROBLEMA RISOLVE
────────────────────────────────────────────────────────────────────────────

Quando un libro si cancella **da Kolibre**, le sue sessioni di lettura e la
sua posizione se ne vanno con lui (`book_records.release_book`). Ma un libro
puo' uscire da Calibre per un'altra strada — cancellato da Calibre desktop,
perso in uno spostamento di biblioteca — e in quel caso nessuno chiama niente:
le sessioni restano, attaccate a un id che in biblioteca non esiste piu'.

Misurato sul server di Paolo il 17/11/2026: **20 sessioni su 1078, per 177
minuti** (l'1,40% di 210,9 ore), su cinque libri. E' tempo che Paolo ha letto
per davvero, e le statistiche lo contano — quindi non e' spazzatura da
buttare: e' un dato giusto attaccato al posto sbagliato.

**La scelta di Paolo (17/11/2026) e' spostarle fra le sessioni orfane**
(`models.OrphanReadingSession`), dove un meccanismo che esiste gia' permette
di **riaccoppiarle** a un libro o di **scartarle** con un clic dal sito
(Statistiche → le sessioni non accoppiate). Le altre due strade erano
lasciarle dov'erano, dichiarandolo, oppure cancellarle — e cancellarle vuol
dire togliere tre ore dal suo storico.

────────────────────────────────────────────────────────────────────────────
NON TUTTE SI POSSONO SPOSTARE, E IL PERCHE' VA DETTO PRIMA
────────────────────────────────────────────────────────────────────────────

La tabella delle orfane nasce per le sessioni che arrivano da un lettore
KOReader e non si riescono ad attribuire: vuole un **dispositivo** e un
**md5**, e nessuno dei due e' facoltativo. Una sessione normale puo' non
averli:

  * **l'md5** di un libro cancellato esiste solo se la sua impronta era stata
    archiviata (`book_hash_history`). Per i libri usciti da Calibre di
    nascosto non lo e' mai stata — nessuno ha visto il momento in cui
    sparivano. Misurato: **su 20 sessioni, 15 hanno un md5 recuperabile** (e
    sono quelle che portano 170 dei 177 minuti), 5 no;
  * **il dispositivo** manca alle sessioni del **lettore web**, che non e' un
    dispositivo: l'md5 non ce l'ha per costruzione, e la tabella delle orfane
    non e' mai stata pensata per lui.

**E l'md5 non si inventa.** E' la chiave con cui il sito riaccoppia e scarta
una sessione orfana: metterne uno finto vorrebbe dire creare una riga che
sembra riaccoppiabile e non lo e', cioe' una trappola al posto di un dato
mancante. Quindi le sessioni senza md5 **restano dove sono**, il comando le
elenca, e quei 7 minuti sono una cosa dichiarata invece che nascosta.

────────────────────────────────────────────────────────────────────────────
CHE COSA CAMBIA NELLE STATISTICHE, DICHIARATO
────────────────────────────────────────────────────────────────────────────

**Il totale generale non cambia di un secondo**: `compute_summary` somma le
sessioni normali **e** quelle orfane (`total_time_seconds`), quindi spostare
una riga da una tabella all'altra lascia il totale dov'era.

**Il riassunto di UNA biblioteca invece cambia, e in su.** Una sessione orfana
non ha una biblioteca, quindi entra nel riassunto di **ognuna** — e' una scelta
dichiarata nella docstring di `compute_summary`, preferita al sottocontare una
lettura vera solo perche' non e' ancora accoppiata. Conseguenza concreta qui:
quei 170 minuti oggi contano solo in `libreria`, dopo lo spostamento contano
in tutte e quattro le biblioteche.

Non e' un difetto nuovo, e' quel comportamento applicato a righe che prima non
lo avevano. **E si chiude da se' nel momento in cui Paolo riaccoppia o scarta
quelle sessioni dal sito**, che e' esattamente il motivo per cui le si sposta
la'. C'e' una prova che misura tutte e due le cose
(`backend/prove/le_sessioni_senza_libro.py`).

────────────────────────────────────────────────────────────────────────────
LE DUE REGOLE DI SICUREZZA
────────────────────────────────────────────────────────────────────────────

**1. Una biblioteca che non si apre non dice niente sui suoi libri.** E' la
regola di `services/libri_scomparsi.py`, e qui vale uguale: se l'elenco dei
libri di una biblioteca non si riesce a leggere, i suoi id non si dichiarano
morti — **il comando si ferma del tutto**. Senza questa regola un disco
scollegato o una cartella rinominata farebbero spostare le sessioni di
un'intera biblioteca in un colpo.

**2. Si fa una copia del database prima di scrivere**, e con l'API di backup
di SQLite invece di copiare il file: il database e' in modalita' WAL, e una
copia fatta con `cp` mentre il server gira puo' essere a meta'. La copia
finisce accanto al database, col giorno nel nome, e il comando dice dove.

**Idempotente**: dopo lo spostamento le righe di partenza non ci sono piu',
quindi un secondo giro non trova niente. E prima di inserire controlla che
quella sessione non sia gia' fra le orfane — cosi' anche un giro interrotto a
meta' si puo' rifare senza raddoppiare niente.
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime


def _prepara_i_percorsi() -> None:
    qui = os.path.dirname(os.path.abspath(__file__))
    radice = os.path.dirname(os.path.dirname(qui))
    if radice not in sys.path:
        sys.path.insert(0, radice)


if __package__ in (None, ""):
    _prepara_i_percorsi()
    from backend.app import config, database, models            # noqa: E402
    from backend.app.calibre.library import CalibreLibrary      # noqa: E402
    from backend.app.logging_utils import log_message           # noqa: E402
    from backend.app.services import stats_service              # noqa: E402
else:
    from . import config, database, models
    from .calibre.library import CalibreLibrary
    from .logging_utils import log_message
    from .services import stats_service


class BibliotecaIlleggibile(Exception):
    """Una biblioteca che non si apre: il comando si ferma, non indovina."""


def libri_vivi(db) -> dict:
    """
    Gli id dei libri che esistono, biblioteca per biblioteca.

    **Alza invece di saltare.** Una biblioteca che non si riesce a leggere non
    e' una biblioteca senza libri: e' una biblioteca di cui non sappiamo
    niente, e trattare le due cose allo stesso modo vorrebbe dire dichiarare
    morti tutti i suoi libri. Vedi la regola 1 in testa al file.
    """
    fuori = {}
    for riga in db.query(models.Library).all():
        percorso = riga.path or config.library_path(riga.folder_name)
        try:
            lib = CalibreLibrary(percorso)
            fuori[riga.folder_name] = {b["id"] for b in lib.list_books()}
        except Exception as e:
            raise BibliotecaIlleggibile(
                f"la biblioteca '{riga.folder_name}' non si apre ({e}): "
                f"non posso dire quali dei suoi libri non esistono piu'."
            ) from e
    return fuori


def md5_recuperabile(db, biblioteca: str, libro: int):
    """
    L'impronta archiviata di quel libro, se qualcuno l'ha archiviata.

    Si prende la **piu' recente**: se un libro e' stato riscritto piu' volte
    prima di sparire, l'ultima e' quella con cui il lettore l'aveva in mano.
    """
    riga = db.query(models.BookHashHistory).filter(
        models.BookHashHistory.library == biblioteca,
        models.BookHashHistory.calibre_book_id == libro,
    ).order_by(models.BookHashHistory.recorded_at.desc()).first()
    return riga.file_hash if riga else None


def raccogli(db) -> dict:
    """
    Che cosa c'e' da spostare, senza spostare niente.

    Torna tre elenchi: quelle che si possono spostare, quelle che no (col
    motivo), e il riepilogo in minuti. Lo usa sia il giro a vuoto sia quello
    vero, cosi' quello che si legge e quello che si fa non possono divergere.
    """
    vivi = libri_vivi(db)
    da_spostare, bloccate = [], []
    for s in db.query(models.ReadingSession).all():
        if s.library not in vivi or s.calibre_book_id in vivi[s.library]:
            continue   # il libro c'e': non e' affar nostro
        motivi = []
        md5 = md5_recuperabile(db, s.library, s.calibre_book_id)
        if not md5:
            motivi.append("nessuna impronta archiviata, e l'md5 non si inventa")
        if not s.device_id:
            motivi.append(f"nessun dispositivo (fonte {s.source or 'sconosciuta'})")
        if motivi:
            bloccate.append((s, "; ".join(motivi)))
        else:
            da_spostare.append((s, md5))
    return {
        "da_spostare": da_spostare,
        "bloccate": bloccate,
        "secondi_da_spostare": sum(s.duration or 0 for s, _ in da_spostare),
        "secondi_bloccati": sum(s.duration or 0 for s, _ in bloccate),
    }


def gia_fra_le_orfane(db, sessione, md5: str) -> bool:
    """Questa sessione e' gia' stata spostata? Serve all'idempotenza."""
    return db.query(models.OrphanReadingSession).filter(
        models.OrphanReadingSession.user_id == sessione.user_id,
        models.OrphanReadingSession.device_id == sessione.device_id,
        models.OrphanReadingSession.md5 == md5,
        models.OrphanReadingSession.start_time == sessione.start_time,
        models.OrphanReadingSession.duration == sessione.duration,
    ).first() is not None


def copia_il_database() -> str:
    """
    Una copia del database, con l'API di backup di sqlite.

    **Non `cp`**: il database e' in WAL, e copiare il file mentre il server
    gira puo' dare una copia a meta' (le pagine scritte stanno nel file
    `-wal` accanto). `Connection.backup` fa una copia coerente anche di un
    database in uso, ed e' la stessa cosa che fa `VACUUM INTO`.
    """
    sorgente = database.engine.url.database
    if not sorgente or not os.path.exists(sorgente):
        raise SystemExit(f"Non trovo il database da copiare ({sorgente!r}).")
    destinazione = (f"{sorgente}.prima-delle-sessioni-orfane-"
                    f"{datetime.utcnow():%Y%m%d-%H%M%S}")
    con_sorgente = sqlite3.connect(sorgente)
    try:
        con_copia = sqlite3.connect(destinazione)
        try:
            con_sorgente.backup(con_copia)
        finally:
            con_copia.close()
    finally:
        con_sorgente.close()
    return destinazione


def sposta(db, raccolto: dict) -> int:
    """Lo spostamento vero. Chi chiama ha gia' fatto la copia."""
    spostate = 0
    for sessione, md5 in raccolto["da_spostare"]:
        if not gia_fra_le_orfane(db, sessione, md5):
            db.add(models.OrphanReadingSession(
                user_id=sessione.user_id,
                device_id=sessione.device_id,
                md5=md5,
                # Il titolo non si recupera: il libro non e' piu' in Calibre e
                # le righe che ne portavano il percorso sono state chiuse.
                # Resta nullo invece di inventare un segnaposto che a schermo
                # sembrerebbe un titolo vero.
                title=None, authors=None, series=None,
                start_time=sessione.start_time,
                duration=sessione.duration,
                pages_read=sessione.pages_read or 0,
                fraction_read=sessione.fraction_read,
            ))
        db.delete(sessione)
        spostate += 1
    db.commit()
    return spostate


def main(argv=None) -> int:
    pezzi = argparse.ArgumentParser(
        prog="python3 -m backend.app.sessioni_senza_libro",
        description="Sposta fra le sessioni orfane le sessioni di lettura di "
                    "libri che non esistono piu' in biblioteca.")
    pezzi.add_argument("--conferma", action="store_true",
                       help="Fa lo spostamento. Senza, dice solo cosa farebbe.")
    scelte = pezzi.parse_args(argv)

    db = database.SessionLocal()
    try:
        try:
            raccolto = raccogli(db)
        except BibliotecaIlleggibile as e:
            print(f"\n    FERMO: {e}")
            print("    Nessuna riga e' stata toccata. Vedi la regola 1 in "
                  "testa a questo file.\n")
            return 2

        da, bloccate = raccolto["da_spostare"], raccolto["bloccate"]
        print()
        if not da and not bloccate:
            print("    Nessuna sessione di lettura parla di un libro che non "
                  "esiste piu'. Niente da fare.\n")
            return 0

        print(f"    DA SPOSTARE: {len(da)} sessioni, "
              f"{raccolto['secondi_da_spostare'] // 60} minuti")
        per_libro = {}
        for s, md5 in da:
            k = (s.library, s.calibre_book_id, md5)
            per_libro[k] = per_libro.get(k, 0) + (s.duration or 0)
        for (bibl, libro, md5), secondi in sorted(per_libro.items(),
                                                  key=lambda x: -x[1]):
            print(f"      {bibl}/{libro}: {secondi // 60} min  "
                  f"(md5 {md5[:12]}…)")

        if bloccate:
            print()
            print(f"    RESTANO DOVE SONO: {len(bloccate)} sessioni, "
                  f"{raccolto['secondi_bloccati'] // 60} minuti")
            for s, motivo in bloccate:
                print(f"      {s.library}/{s.calibre_book_id} "
                      f"({s.duration or 0} s): {motivo}")

        if not scelte.conferma:
            print()
            print("    Giro a vuoto: non e' stato scritto niente.")
            print("    Per farlo davvero:  --conferma\n")
            return 0

        copia = copia_il_database()
        print()
        print(f"    copia del database: {copia}")
        spostate = sposta(db, raccolto)
        # Il cruscotto legge una cache: senza questo, i numeri cambierebbero
        # solo al prossimo giro periodico e lo spostamento sembrerebbe non
        # aver fatto niente.
        biblioteche = stats_service.refresh_stats_cache(db)
        log_message("info", "stats",
                    f"{spostate} reading session(s) of books that no longer "
                    f"exist were moved to the orphan sessions; "
                    f"{len(bloccate)} could not be moved.")
        print(f"    spostate: {spostate}")
        print(f"    statistiche rinfrescate: {biblioteche} bibliotech"
              f"{'e' if biblioteche != 1 else 'a'}")
        print()
        print("    Adesso si riaccoppiano o si scartano dal sito, in "
              "Statistiche.")
        print()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
