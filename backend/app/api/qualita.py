"""
La qualita' degli EPUB: impostazione, coda e lettura dei risultati.

Le rotte sono il calco di quelle della ricerca a testo pieno (`fulltext.py`),
perche' le due cose si somigliano da vicino: un lavoro pesante che gira in
sottofondo su una biblioteca intera, con un interruttore per biblioteca e uno
stato da guardare mentre va. Tenerle simili vuol dire che chi ha imparato una
pagina sa gia' leggere l'altra.

Il dettaglio di un libro esce **cosi' com'e'**, il JSON intero scritto dalla
misura: non lo si rimodella qui. Vedi `QualitaDettaglio` per il perche'.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth, config, database, models
from ..calibre.library import CalibreLibrary
from ..logging_utils import log_message
from ..schemas_risposte import (Esito, QualitaDettaglio, QualitaElenco,
                                QualitaImpostazioni, QualitaStato)
from ..services import app_settings, qualita_job
from .libraries import biblioteca_scrivibile, default_library_param

router = APIRouter(prefix="/api/kolibre/qualita", tags=["qualita"])


def _chi(utente) -> str:
    """Il nome dell'account che ha fatto la richiesta, o un segnaposto."""
    return getattr(utente, "username", None) or "?"


@router.get("/settings", response_model=QualitaImpostazioni)
def leggi_impostazioni(library: str = Depends(default_library_param), db: Session = Depends(database.get_db)):
    return {"enabled": app_settings.is_qualita_enabled(db, library)}


@router.put("/settings", response_model=QualitaImpostazioni)
def scrivi_impostazioni(payload: dict, library: str = Depends(biblioteca_scrivibile),
                        db: Session = Depends(database.get_db),
                        chi: models.User = Depends(auth.get_current_user_flexible)):
    acceso = bool(payload.get("enabled", True))
    prima = app_settings.is_qualita_enabled(db, library)
    app_settings.set_qualita_enabled(db, library, acceso)
    # Accendere vuol dire «fallo»: senza questo l'interruttore sarebbe una
    # promessa che si avvera al prossimo riavvio del server.
    accodata = qualita_job.accoda(library) if acceso else False
    # **Due righe e non una**, perche' sono due fatti diversi: l'interruttore
    # e' cambiato, e un lavoro e' partito. Il secondo e' quello che poi
    # spiega il carico sul server per i dieci minuti successivi, e chi legge
    # il registro cercando «perche' era lento alle tre» cerca quello.
    if prima != acceso:
        log_message("info", "qualita",
                    f"'{_chi(chi)}' turned the quality check "
                    f"{'on' if acceso else 'off'} for library '{library}'.")
    if accodata:
        log_message("info", "qualita",
                    f"Library '{library}' was queued for a quality pass.")
    return {"enabled": acceso}


@router.get("/status", response_model=QualitaStato)
def stato(library: str = Depends(default_library_param), db: Session = Depends(database.get_db)):
    righe = db.query(models.QualitaLibro).filter(models.QualitaLibro.library == library).all()
    try:
        lib = CalibreLibrary(config.library_path(library))
        # `formats` e' una lista di stringhe, vedi qualita_job._lavoro.
        totale = sum(1 for b in lib.list_books()
                     if any((f or "").upper() == qualita_job.FORMATO
                            for f in (b.get("formats") or [])))
    except Exception:
        totale = len(righe)
    corso = qualita_job.stato()
    attiva = corso["in_corso"] and (corso["biblioteca"] == library or library in corso["in_coda"])
    return {
        "enabled": app_settings.is_qualita_enabled(db, library),
        "versione": qualita_job.VERSIONE,
        "analizzati": sum(1 for r in righe if r.stato == "ok"),
        "totale": totale,
        "non_pronti": sum(1 for r in righe if r.pronto is False),
        "errori": sum(1 for r in righe if r.stato != "ok"),
        "da_rifare": sum(1 for r in righe if r.versione != qualita_job.VERSIONE),
        "in_corso": bool(attiva),
        "progresso": {
            "biblioteca": corso["biblioteca"],
            "fatti": corso["fatti"],
            "totale": corso["totale"],
            "errori": corso["errori"],
            "in_coda": corso["in_coda"],
        } if attiva else None,
    }


@router.post("/analizza", response_model=Esito)
def analizza(payload: dict = None, library: str = Depends(biblioteca_scrivibile),
             chi: models.User = Depends(auth.get_current_user_flexible)):
    """
    Mette la biblioteca in coda. Con `{"forza": true}` rifa' anche i libri
    che hanno gia' un punteggio buono: chi preme quel pulsante lo fa quando
    non si fida di quello che vede.
    """
    forza = bool((payload or {}).get("forza"))
    avviato = qualita_job.accoda(library, forza=forza)
    if not avviato:
        # Non e' un errore: o e' spenta, o e' gia' in coda. Lo stato lo dice.
        #
        # **Ma si scrive**, ed e' il caso che vale la pena spiegare: una
        # richiesta che non fa niente e non lo dice e' il modo in cui si
        # finisce a premere lo stesso pulsante cinque volte convinti che il
        # server non risponda. WARNING perche' e' un rifiuto, non un guasto.
        log_message("warning", "qualita",
                    f"'{_chi(chi)}' asked for a quality pass on '{library}', "
                    f"nothing started: it is switched off, or already queued.")
        return {"status": "ok", "messaggio": "already queued, or switched off"}
    log_message("info", "qualita",
                f"'{_chi(chi)}' started a quality pass on '{library}'"
                f"{', redoing the books that already have a score' if forza else ''}.")
    return {"status": "ok"}


@router.get("/libri", response_model=QualitaElenco)
def elenco(library: str = Depends(default_library_param), db: Session = Depends(database.get_db),
           ordina: str = "punteggio", verso: str = "asc", solo: str = "tutti",
           limite: int = 200, salta: int = 0):
    """
    La tabella di «Interventi». I titoli e gli autori vengono dalla
    biblioteca di Calibre, i punteggi da qui: un libro cancellato da Calibre
    sparisce dalla tabella anche se la sua riga esiste ancora.
    """
    righe = db.query(models.QualitaLibro).filter(models.QualitaLibro.library == library).all()
    try:
        lib = CalibreLibrary(config.library_path(library))
        libri = {b["id"]: b for b in lib.list_books()}
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"The library could not be read: {e}")

    fuori = []
    for r in righe:
        libro = libri.get(r.calibre_book_id)
        if not libro:
            continue
        if solo == "non_pronti" and r.pronto is not False:
            continue
        if solo == "errori" and r.stato == "ok":
            continue
        dati = {}
        if r.risultato:
            try:
                dati = json.loads(r.risultato)
            except ValueError:
                dati = {}
        fuori.append({
            "id": r.calibre_book_id,
            "title": libro.get("title") or "",
            "author": libro.get("author"),
            "stato": r.stato,
            "punteggio": r.punteggio,
            "pronto": r.pronto,
            "dimensioni": dati.get("dimensioni") or {},
            "difetti": len(dati.get("difetti") or []),
            "errore": r.errore,
        })

    ordinati = ordina_le_righe(fuori, ordina, verso)
    return {"libri": ordinati[salta:salta + max(1, min(limite, 2000))], "totale": len(ordinati)}


#: I nomi di colonna che NON sono una dimensione. Le dimensioni si chiedono
#: come `dimensioni.<nome>` e non si elencano qui di proposito: la misura puo'
#: aggiungerne (vedi `qualita_job.VERSIONE`), e un elenco scritto a mano
#: smetterebbe di ordinare la colonna nuova in silenzio — che e' il difetto
#: che questa funzione sta chiudendo, visto dall'altro lato.
PREFISSO_DIMENSIONE = "dimensioni."


def _valore_da_ordinare(riga: dict, ordina: str):
    """
    Il valore su cui ordinare, o `None` se quella riga non ce l'ha.

    `None` non vuol dire «zero»: vuol dire «di questa riga non si sa». Chi
    chiama lo tiene separato, vedi `ordina_le_righe`.
    """
    if ordina == "titolo":
        return (riga["title"] or "").lower()
    if ordina == "autore":
        return (riga["author"] or "").lower()
    if ordina == "difetti":
        return riga["difetti"]
    if ordina.startswith(PREFISSO_DIMENSIONE):
        nome = ordina[len(PREFISSO_DIMENSIONE):]
        valore = (riga.get("dimensioni") or {}).get(nome)
        return valore if isinstance(valore, (int, float)) else None
    return riga["punteggio"]


def ordina_le_righe(righe: list, ordina: str, verso: str) -> list:
    """
    La tabella ordinata per la colonna chiesta, con una regola sola.

    **Il difetto che questa funzione chiude** (17/11/2026, chiesto da Paolo:
    «ogni colonna deve essere ordinabile, non solo alcune»). Prima
    l'ordinamento era un dizionario con due chiavi — titolo e autore — e un
    ripiego:

        chiave = {"titolo": ..., "autore": ...}.get(ordina, lambda f: f["punteggio"])

    cioe' **qualunque altra colonna ordinava per punteggio, senza dirlo**.
    Mettere un bottone sulle colonne delle dimensioni senza toccare questo
    avrebbe dato tre colonne che sembrano ordinare e ordinano per un'altra
    cosa — che e' peggio di una colonna che non si clicca, perche' una
    colonna che non si clicca almeno non mente.

    **Le righe a cui quel valore manca vanno in fondo, in tutti e due i
    versi.** Non sono «le peggiori»: sono quelle di cui non si sa niente, e
    metterle prime fra le peggiori direbbe una cosa falsa. Era la regola che
    c'era gia' per il punteggio, **generalizzata alla colonna chiesta**: se si
    ordina per una dimensione, in fondo vanno i libri che quella dimensione
    non l'hanno (una misura piu' vecchia, un'analisi fallita), non quelli
    senza punteggio.

    **E una conseguenza da dichiarare, perche' e' un cambiamento.** Prima i
    libri con l'analisi fallita stavano in fondo **anche ordinando per
    titolo**, perche' la regola guardava sempre il punteggio. Adesso no: un
    titolo c'e' sempre, quindi ordinando per titolo quei libri si mescolano
    agli altri al loro posto alfabetico. E' la regola applicata per davvero
    invece che a meta' — e chi li vuole tutti insieme ha il filtro «errori»,
    che e' fatto per quello.
    """
    con = [r for r in righe if _valore_da_ordinare(r, ordina) is not None]
    senza = [r for r in righe if _valore_da_ordinare(r, ordina) is None]
    con.sort(key=lambda r: _valore_da_ordinare(r, ordina), reverse=(verso == "desc"))
    return con + senza


@router.get("/libri/{book_id}", response_model=QualitaDettaglio)
def dettaglio(book_id: int, library: str = Depends(default_library_param),
              db: Session = Depends(database.get_db)):
    riga = db.query(models.QualitaLibro).filter(
        models.QualitaLibro.library == library,
        models.QualitaLibro.calibre_book_id == book_id,
    ).first()
    if not riga:
        raise HTTPException(status_code=404, detail="This book has not been analysed yet")
    if riga.stato != "ok" or not riga.risultato:
        raise HTTPException(status_code=409, detail=riga.errore or "Analisi non riuscita")
    try:
        return json.loads(riga.risultato)
    except ValueError:
        raise HTTPException(status_code=500, detail="The stored result could not be read")
