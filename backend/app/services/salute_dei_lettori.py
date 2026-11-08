"""
Se il legame fra il server e i lettori regge, e dove non regge.

**Il guasto che questo modulo cerca, spiegato da zero.** Un lettore e il
server devono poter dire «lo stesso libro». Dal 06/10/2026 lo fanno per
nome — biblioteca, id Calibre, formato — che e' immune a qualunque
riscrittura. Ma prima lo facevano confrontando un'**impronta** del file, un
campionamento a salti dei suoi byte, e quell'impronta resta come rete per
tutto quello che il nome non copre: un libro consegnato prima di quella data,
un file che sta solo sul lettore, un messaggio da un plugin vecchio.

Quella rete si logora in silenzio. Kolibre riscrive gli EPUB (ci incorpora il
conteggio pagine), e se l'impronta registrata non viene rifatta, descrive una
versione del file che non esiste piu'. Il lettore manda una nota, il server
non riconosce il libro, e la nota diventa orfana. **Nessuno se ne accorge**:
non c'e' un errore, c'e' un dato che non arriva.

Il 04/11/2026 su questo impianto erano 2 impronte su 8251 (il 04/10 erano
130: la differenza l'hanno fatta le riscritture di massa e il difetto
d'ordine corretto lo stesso giorno). Due su ottomila sembra niente, ma sono
due libri che perdono le note di chi li legge, e per saperlo bisognava che
scrivessi uno script a mano.

**Perche' si lancia a mano e non si conta sempre.** Misurare un'impronta
vuol dire aprire il file: 8217 file in 24 secondi, misurati. La pagina
Interventi conta le sue voci a ogni apertura, e 24 secondi di lettura disco
per aprire una pagina sarebbero inaccettabili — e inutili, perche' questo
non cambia da solo fra un'apertura e l'altra. Quindi: un controllo che si
chiede, con il suo avanzamento, e un risultato che resta.

**Tre categorie, e si riparano in modi diversi** — l'ordine e' quello di
quanto e' sicuro intervenire:

1. `da_ricalcolare` — l'impronta registrata non descrive il file che c'e'.
   Si ripara **dal lato server**: si rifa' il conto e si archivia la
   vecchia, cosi' un lettore che aveva scaricato la copia precedente
   continua a riconoscersi. Non tocca niente fuori dal server, quindi e'
   sempre reversibile.
2. `non_riconoscibili` — un libro che un lettore dichiara di avere, e la cui
   impronta di consegna non si risolve piu' in nessun modo. **Questo modulo
   non lo ripara**: la riparazione passerebbe dal dispositivo, e quella
   decisione e' rinviata (vedi il backlog, «quanto si puo' toccare sul
   dispositivo»). Si dice, e basta: e' il caso che perde dati, e sapere che
   esiste vale piu' che ripararlo male.
3. `senza_file` — righe che parlano di un file che non c'e' piu'. Innocue
   per il riconoscimento, ma gonfiano il conto e nascondono le altre due
   categorie. Si possono dimenticare.

**Lo stato vive in memoria**, come gli altri giri lunghi del server
(`author_scrape_job`, `ingest_import_job`): un riavvio lo perde, ed e' una
scelta. Il controllo si rilancia in ventiquattro secondi, e quello che
conta — le impronte stesse — sta nel database.
"""

import hashlib
import os
import threading
from datetime import datetime
from typing import Optional

from .. import database, models, config
from ..istanti import quando
from ..calibre.library import CalibreLibrary
from ..logging_utils import log_message
from . import book_hash_service

# Lo stesso campionamento di KOReader: 1024 byte a offset che crescono per
# potenze di quattro. Rifatto qui e non preso da koreader_hash perche'
# questo modulo deve poter dire che l'impronta registrata e' SBAGLIATA, e
# chiedere la risposta giusta alla stessa funzione che l'ha prodotta non
# dimostrerebbe niente.
_PASSO = 1024
_SALTI = range(-1, 11)


def impronta_del_file(percorso: str) -> Optional[str]:
    try:
        with open(percorso, "rb") as f:
            md5 = hashlib.md5()
            for i in _SALTI:
                f.seek(_PASSO << (2 * i) if i >= 0 else 0)
                pezzo = f.read(_PASSO)
                if not pezzo:
                    break
                md5.update(pezzo)
            return md5.hexdigest()
    except OSError:
        return None


_lock = threading.Lock()
_stato = {
    "in_corso": False,
    "totale": 0,
    "fatti": 0,
    "biblioteca": None,
    # Le tre categorie, ognuna con le sue righe: non solo il conteggio,
    # perche' «due impronte sbagliate» non si ripara, «questi due libri» si'.
    "da_ricalcolare": [],
    "non_riconoscibili": [],
    "senza_file": [],
    # Una biblioteca che non si apre non dice NIENTE sui suoi libri, ed e' la
    # stessa regola di libri_scomparsi: un disco scollegato non deve far
    # dichiarare rotto tutto quello che contiene.
    "biblioteche_illeggibili": [],
    "iniziato": None,
    "finito": None,
}


def stato() -> dict:
    """Istantanea, sicura da leggere mentre il controllo lavora."""
    with _lock:
        s = dict(_stato)
        for chiave in ("da_ricalcolare", "non_riconoscibili", "senza_file",
                       "biblioteche_illeggibili"):
            s[chiave] = list(_stato[chiave])
        return s


def avvia(nomi_biblioteche: list) -> bool:
    """
    Avvia il controllo. Torna False se ce n'e' gia' uno in corso — e la
    guardia sta qui, non nella pagina: due schede del browser aperte sulla
    stessa pagina non devono poter far partire due giri sugli stessi file.
    """
    with _lock:
        if _stato["in_corso"]:
            return False
        _stato.update(
            in_corso=True, totale=0, fatti=0, biblioteca=None,
            da_ricalcolare=[], non_riconoscibili=[], senza_file=[],
            biblioteche_illeggibili=[],
            iniziato=quando(datetime.utcnow()), finito=None,
        )
    threading.Thread(target=_gira, args=(list(nomi_biblioteche),), daemon=True).start()
    return True


def _gira(nomi: list) -> None:
    db = database.SessionLocal()
    try:
        _controlla_le_impronte(db, nomi)
        _controlla_i_lettori(db)
    except Exception as e:  # il thread non deve morire in silenzio
        log_message("error", "devices", f"Reader-link check stopped: {e}")
    finally:
        db.close()
        with _lock:
            _stato["in_corso"] = False
            _stato["finito"] = quando(datetime.utcnow())
        s = stato()
        log_message(
            "info", "devices",
            f"Reader-link check: {len(s['da_ricalcolare'])} fingerprints to redo, "
            f"{len(s['non_riconoscibili'])} books that cannot be recognised, "
            f"{len(s['senza_file'])} rows with no file",
        )


def _controlla_le_impronte(db, nomi: list) -> None:
    righe_per_biblioteca = {}
    for nome in nomi:
        righe_per_biblioteca[nome] = db.query(models.BookHash).filter_by(library=nome).all()
    with _lock:
        _stato["totale"] = sum(len(v) for v in righe_per_biblioteca.values())

    for nome, righe in righe_per_biblioteca.items():
        with _lock:
            _stato["biblioteca"] = nome
        try:
            lib = CalibreLibrary(config.library_path(nome))
            titoli = {b["id"]: b.get("title") for b in lib.list_books()}
        except Exception:
            # Non si afferma niente sui libri di una biblioteca che non si
            # apre, e si dice che non si e' potuto guardare.
            with _lock:
                _stato["biblioteche_illeggibili"].append(nome)
                _stato["fatti"] += len(righe)
            continue

        for bh in righe:
            percorso = lib.get_format_file_path(bh.calibre_book_id, bh.format or "EPUB")
            if not percorso or not os.path.exists(percorso):
                with _lock:
                    _stato["senza_file"].append({
                        "library": nome, "calibre_book_id": bh.calibre_book_id,
                        "format": bh.format,
                        "title": titoli.get(bh.calibre_book_id),
                        "in_biblioteca": bh.calibre_book_id in titoli,
                    })
                    _stato["fatti"] += 1
                continue
            vera = impronta_del_file(percorso)
            if vera and vera != bh.file_hash:
                with _lock:
                    _stato["da_ricalcolare"].append({
                        "library": nome, "calibre_book_id": bh.calibre_book_id,
                        "format": bh.format,
                        "title": titoli.get(bh.calibre_book_id),
                        "registrata": bh.file_hash, "vera": vera,
                        # Una riga «verificata» che sbaglia e' peggio di una
                        # forzata a mano da un accoppiamento: quella e'
                        # sbagliata per scelta, questa mente.
                        "verified": bool(bh.verified),
                    })
            with _lock:
                _stato["fatti"] += 1


def _controlla_i_lettori(db) -> None:
    """I libri che un lettore dice di avere, e che il server non sa piu' nominare.

    **Perche' NON si chiama il risolutore con `device_id`.** Il risolutore ha
    tre livelli, e il terzo e' «l'impronta che risulta consegnata a QUESTO
    dispositivo», cioe' il campo di questa riga. Interrogarlo cosi' vuol dire
    chiedergli se la riga conferma sé stessa: risponde sempre si', e un
    controllo costruito in quel modo non trova mai niente — era il primo
    difetto di questo modulo, trovato dalla sua prova, dopo che su 317 righe
    vere ne aveva dichiarate zero da sistemare.

    Si guardano quindi i due livelli che vengono da FUORI: l'impronta viva del
    file e quelle archiviate. Se nessuno dei due riconosce l'impronta, quella
    riga si regge solo su sé stessa — funziona finche' non viene ricostruita, e
    merita di essere nominata.

    Una riga senza impronta di consegna non e' un guasto: vuol dire che non le
    e' mai servita.
    """
    righe = db.query(models.DeviceBook).filter(
        models.DeviceBook.status == "synced",
        models.DeviceBook.delivery_hash.isnot(None),
    ).all()
    nomi_dispositivi = {d.id: d.name for d in db.query(models.Device).all()}
    for r in righe:
        viva = db.query(models.BookHash).filter_by(file_hash=r.delivery_hash).first()
        if viva:
            continue
        archiviata = db.query(models.BookHashHistory).filter_by(
            file_hash=r.delivery_hash).first()
        if archiviata:
            continue
        with _lock:
            _stato["non_riconoscibili"].append({
                "id": r.id, "device_id": r.device_id,
                "device_name": nomi_dispositivi.get(r.device_id),
                "library": r.library, "calibre_book_id": r.calibre_book_id,
                "format": r.format, "device_path": r.device_path,
                "delivery_hash": r.delivery_hash,
                # L'identita' c'e' quasi sempre, e cambia il significato della
                # riga: con lei il libro si riconosce comunque per nome, e
                # l'impronta che non risolve e' un difetto di contabilita', non
                # una perdita di dati.
                "ha_identita": r.calibre_book_id is not None,
            })


def ricalcola(db, voci: list) -> dict:
    """
    Rifa' le impronte indicate, archiviando la vecchia.

    Ricontrolla ogni voce invece di fidarsi di quello che la pagina ha
    mandato: fra il controllo e il clic possono passare minuti, e un file
    puo' essere cambiato di nuovo. Una voce che ormai e' a posto non si
    tocca e si conta a parte, perche' «rifatte 5 su 7» con 2 gia' a posto e'
    un esito diverso da «rifatte 5, 2 fallite».
    """
    rifatte, gia_a_posto, non_riuscite = 0, 0, []
    per_biblioteca = {}
    for v in voci:
        per_biblioteca.setdefault(v.get("library"), []).append(v)

    for nome, elenco in per_biblioteca.items():
        try:
            lib = CalibreLibrary(config.library_path(nome))
        except Exception:
            non_riuscite.extend(f"{nome}/{v.get('calibre_book_id')}" for v in elenco)
            continue
        for v in elenco:
            cid, fmt = v.get("calibre_book_id"), (v.get("format") or "EPUB")
            percorso = lib.get_format_file_path(cid, fmt)
            if not percorso or not os.path.exists(percorso):
                non_riuscite.append(f"{nome}/{cid}")
                continue
            vera = impronta_del_file(percorso)
            riga = db.query(models.BookHash).filter_by(
                library=nome, calibre_book_id=cid, format=fmt).first()
            if not vera or not riga:
                non_riuscite.append(f"{nome}/{cid}")
                continue
            if riga.file_hash == vera:
                gia_a_posto += 1
                continue
            # Passa da upsert_book_hash e non da una scrittura diretta: e' lui
            # che archivia la vecchia impronta in book_hash_history, ed e'
            # esattamente la cosa che era mancata quando queste righe si sono
            # rotte.
            book_hash_service.upsert_book_hash(db, nome, cid, fmt, percorso)
            rifatte += 1
    db.commit()
    if rifatte:
        log_message("info", "devices",
                    f"Fingerprints redone by the reader-link check: {rifatte}")
    # Lo stato in memoria non descrive piu' la realta' per le voci rifatte:
    # si tolgono, cosi' la pagina non ripropone un'azione gia' fatta.
    if rifatte:
        with _lock:
            fatte = {(v.get("library"), v.get("calibre_book_id"), v.get("format")) for v in voci}
            _stato["da_ricalcolare"] = [
                x for x in _stato["da_ricalcolare"]
                if (x["library"], x["calibre_book_id"], x["format"]) not in fatte
            ]
    return {"rifatte": rifatte, "gia_a_posto": gia_a_posto, "non_riuscite": non_riuscite}


def dimentica_righe_senza_file(db, voci: list) -> dict:
    """
    Toglie le righe `book_hashes` che parlano di un file che non c'e'.

    Ricontrolla, come sopra: una riga il cui file e' RICOMPARSO non si
    cancella. Succede per davvero — una biblioteca su un disco esterno che
    torna collegato.
    """
    tolte, tornate = 0, 0
    for v in voci:
        nome, cid, fmt = v.get("library"), v.get("calibre_book_id"), (v.get("format") or "EPUB")
        try:
            lib = CalibreLibrary(config.library_path(nome))
            percorso = lib.get_format_file_path(cid, fmt)
        except Exception:
            # Biblioteca illeggibile: non si cancella niente. Un disco
            # scollegato non e' un libro scomparso.
            continue
        if percorso and os.path.exists(percorso):
            tornate += 1
            continue
        riga = db.query(models.BookHash).filter_by(
            library=nome, calibre_book_id=cid, format=fmt).first()
        if riga:
            db.delete(riga)
            tolte += 1
    db.commit()
    if tolte:
        with _lock:
            fatte = {(v.get("library"), v.get("calibre_book_id"), v.get("format")) for v in voci}
            _stato["senza_file"] = [
                x for x in _stato["senza_file"]
                if (x["library"], x["calibre_book_id"], x["format"]) not in fatte
            ]
    return {"tolte": tolte, "tornate": tornate}
