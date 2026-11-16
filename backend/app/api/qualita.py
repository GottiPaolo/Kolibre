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

from .. import config, database, models
from ..calibre.library import CalibreLibrary
from ..schemas_risposte import (Esito, QualitaDettaglio, QualitaElenco,
                                QualitaImpostazioni, QualitaStato)
from ..services import app_settings, qualita_job
from .libraries import biblioteca_scrivibile, default_library_param

router = APIRouter(prefix="/api/kolibre/qualita", tags=["qualita"])


@router.get("/settings", response_model=QualitaImpostazioni)
def leggi_impostazioni(library: str = Depends(default_library_param), db: Session = Depends(database.get_db)):
    return {"enabled": app_settings.is_qualita_enabled(db, library)}


@router.put("/settings", response_model=QualitaImpostazioni)
def scrivi_impostazioni(payload: dict, library: str = Depends(biblioteca_scrivibile),
                        db: Session = Depends(database.get_db)):
    acceso = bool(payload.get("enabled", True))
    app_settings.set_qualita_enabled(db, library, acceso)
    # Accendere vuol dire «fallo»: senza questo l'interruttore sarebbe una
    # promessa che si avvera al prossimo riavvio del server.
    if acceso:
        qualita_job.accoda(library)
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
def analizza(payload: dict = None, library: str = Depends(biblioteca_scrivibile)):
    """
    Mette la biblioteca in coda. Con `{"forza": true}` rifa' anche i libri
    che hanno gia' un punteggio buono: chi preme quel pulsante lo fa quando
    non si fida di quello che vede.
    """
    forza = bool((payload or {}).get("forza"))
    avviato = qualita_job.accoda(library, forza=forza)
    if not avviato:
        # Non e' un errore: o e' spenta, o e' gia' in coda. Lo stato lo dice.
        return {"status": "ok", "messaggio": "already queued, or switched off"}
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

    # L'ordinamento: i libri senza punteggio (errore di analisi) stanno in
    # fondo in tutti e due i versi, perche' non sono «i peggiori» — sono
    # quelli di cui non si sa niente, e metterli primi fra i peggiori direbbe
    # una cosa falsa.
    senza = [f for f in fuori if f["punteggio"] is None]
    con = [f for f in fuori if f["punteggio"] is not None]
    chiave = {"titolo": lambda f: (f["title"] or "").lower(),
              "autore": lambda f: (f["author"] or "").lower()}.get(ordina, lambda f: f["punteggio"])
    con.sort(key=chiave, reverse=(verso == "desc"))
    ordinati = con + senza
    return {"libri": ordinati[salta:salta + max(1, min(limite, 2000))], "totale": len(ordinati)}


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
