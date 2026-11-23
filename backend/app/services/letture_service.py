"""
Le letture misurate in caratteri: riceverle dal dispositivo e risolverle.

**Che problema risolve** (decisione del 19/11/2026, con Paolo). Fino a oggi
«quanti caratteri ho letto» era una media: `ReadingSession.fraction_read`
somma `1/total_pages`, cioe' presume che ogni pagina contenga la stessa
quantita' di testo. Non e' vero, e si misura: la pagina 12 su 248 de «La
linea d'ombra» e' il 4,8% del libro contando le pagine e l'1,8% contandone i
caratteri, perche' le prime pagine sono apparato e aperture di capitolo.

**Come si risolve.** Il lettore manda, per ogni pagina visitata, DOVE quella
pagina comincia e finisce — gli xpointer di crengine, che sono indirizzi nel
testo e non dipendono dall'impaginazione — e il server calcola il carattere
assoluto con l'indice che usa gia' per le note
(`position_converter/chapter_text_index.py`, costruito apposta per imitare
come crengine costruisce i suoi nodi di testo). La prova resta nel database:
se l'indice migliora, lo storico si ricalcola.

**I due contatori che non si mescolano.** Misurato su «La linea d'ombra»:
314.361 caratteri nella vista collassata del nostro indice, 327.577 in
`BookTextStats` (che toglie i tag con un'espressione regolare e lascia dentro
spazi non collassati, marcatori di pagina del cartaceo, apparato). Il 4% di
differenza. Ogni riga porta percio' il PROPRIO denominatore
(`caratteri_del_libro`), ed e' l'unico con cui e' lecito farne percentuali.

**Il trasporto e' quello delle statistiche**, deliberatamente: il dispositivo
chiede da quale istante ripartire, manda da li' in avanti con una finestra di
sovrapposizione, e i doppioni li butta il server. Una riga rimandata costa
pochi byte; una riga saltata non torna piu'.
"""

import calendar
import os
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .. import config, models
from ..calibre.library import CalibreLibrary
from ..logging_utils import log_message
from .position_converter.core import (parse_chapter_document, xpointer_al_carattere,
                                     xpointer_punta_al_testo)
from .position_converter.epub_chapters import get_chapter_xhtml, get_spine_length

#: L'ordine dei campi di una riga, come il lettore la manda.
#:
#: **Deve combaciare con `KolibreLetture.CAMPI`** in
#: `plugins/koreader/kolibre.koplugin/kolibre_letture.lua`: le righe viaggiano
#: come vettori e non come oggetti, perche' su duemila righe i nomi dei campi
#: ripetuti sarebbero centosessanta KB di salita per dire quello che l'ordine
#: dice gratis. Il prezzo e' questo accoppiamento, e si paga dichiarandolo nei
#: due posti e mandando il numero di versione del formato a ogni invio: un
#: formato che non conosciamo si rifiuta invece di interpretarlo a caso.
CAMPI = (
    "genere", "istante", "durata", "pagina", "totale_pagine",
    "caratteri", "xp_inizio", "xp_fine", "impronta", "biblioteca", "libro",
)

FORMATO_ATTESO = 1

#: Quanto il dispositivo torna indietro rispetto a quello che il server ha.
#:
#: Stessa ragione e stesso valore delle statistiche di KOReader (vedi
#: `stats_service.FINESTRA_SOVRAPPOSIZIONE`): una riga viene scritta quando la
#: pagina viene LASCIATA, e un lettore puo' restare spento in mezzo. Chiedere
#: «solo quello che viene dopo l'ultimo che ho» rischia di saltare una riga
#: scritta in ritardo ma datata prima. La sovrapposizione costa qualche decina
#: di righe che il controllo dei doppioni butta da sola.
FINESTRA_SOVRAPPOSIZIONE = 86400

#: Quante righe si convertono per giro. Convertire vuol dire aprire l'EPUB e
#: analizzare i suoi capitoli: un lotto limitato, come fa gia' la conversione
#: degli indirizzi delle note.
LOTTO_DI_CONVERSIONE = 400

_DOCFRAGMENT = re.compile(r"DocFragment\[(\d+)\]")


def _epoch(quando: datetime) -> int:
    """Da data UTC a istante epoch, senza passare dal fuso della macchina.

    `calendar.timegm` e non `datetime.timestamp()`: il secondo interpreta una
    data senza fuso come LOCALE, e qui le date sono UTC — su questa macchina
    sarebbe un'ora di differenza, in estate due, e la filigrana rimandata al
    lettore gli farebbe potare righe che il server non ha.
    """
    return calendar.timegm(quando.utctimetuple())


# ── Da dove ripartire ───────────────────────────────────────────────────

def stato_letture(db: Session, device_id: int) -> dict:
    """Da quale istante il dispositivo deve mandare, e quanto abbiamo.

    `da` e' l'ultimo istante noto meno la finestra di sovrapposizione, non
    l'ultimo istante secco. Su un deposito vuoto e' 0, che vuol dire «manda
    tutto quello che hai».
    """
    riga = (
        db.query(models.LetturaDiPagina)
        .filter(models.LetturaDiPagina.device_id == device_id)
        .order_by(models.LetturaDiPagina.istante.desc())
        .first()
    )
    quante = (
        db.query(models.LetturaDiPagina)
        .filter(models.LetturaDiPagina.device_id == device_id)
        .count()
    )
    if riga is None:
        return {"da": 0, "righe": 0, "formato": FORMATO_ATTESO}
    return {
        "da": max(0, _epoch(riga.istante) - FINESTRA_SOVRAPPOSIZIONE),
        "righe": quante,
        "formato": FORMATO_ATTESO,
    }


# ── Riceverle ───────────────────────────────────────────────────────────

def _valore(v):
    """Il lettore manda "" per «assente»: un nil in mezzo a un vettore Lua e'
    un buco che chi serializza in JSON tronca o trasforma in un oggetto."""
    if v == "" or v is None:
        return None
    return v


def _intero(v) -> Optional[int]:
    v = _valore(v)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _riga_dal_vettore(vettore) -> Optional[dict]:
    if not isinstance(vettore, (list, tuple)) or len(vettore) != len(CAMPI):
        return None
    grezza = dict(zip(CAMPI, vettore))
    genere = _valore(grezza.get("genere"))
    istante = _intero(grezza.get("istante"))
    if genere not in (models.LetturaDiPagina.PAGINA, models.LetturaDiPagina.NOTA):
        return None
    if istante is None or istante <= 0:
        return None
    durata = _intero(grezza.get("durata"))
    if durata is None or durata < 0:
        return None
    return {
        "genere": genere,
        "istante": datetime.utcfromtimestamp(istante),
        "durata": durata,
        "pagina": _intero(grezza.get("pagina")),
        "totale_pagine": _intero(grezza.get("totale_pagine")),
        "caratteri_dal_dispositivo": _intero(grezza.get("caratteri")),
        "xp_inizio": _valore(grezza.get("xp_inizio")),
        "xp_fine": _valore(grezza.get("xp_fine")),
        "impronta": _valore(grezza.get("impronta")),
        "library": _valore(grezza.get("biblioteca")),
        "calibre_book_id": _intero(grezza.get("libro")),
    }


def _risolvi_dall_impronta(db: Session, impronta: str):
    """Biblioteca e id di un libro, dalla sua impronta.

    La stessa strada delle annotazioni che arrivano da un dispositivo: il
    lettore conosce l'impronta del file che ha in mano, non gli id di Calibre.
    Si preferisce una riga verificata — calcolata dal server sul proprio file —
    a una dichiarata dal dispositivo in un accoppiamento a mano, perche' la
    seconda puo' essere stata fatta su un file che non e' byte per byte lo
    stesso (un Kindle che ricomprime gli EPUB: caso reale, non ipotetico).
    """
    if not impronta:
        return None, None
    righe = (
        db.query(models.BookHash)
        .filter(models.BookHash.file_hash == impronta)
        .order_by(models.BookHash.verified.desc())
        .all()
    )
    if not righe:
        return None, None
    return righe[0].library, righe[0].calibre_book_id


def cuci_letture(db: Session, device: models.Device, payload: dict) -> dict:
    """
    Mette nel database le righe che non abbiamo ancora.

    Torna `righe_aggiunte`, `doppioni`, `rifiutate` e la `filigrana`: l'ultimo
    istante che il server ha davvero, in epoch. Il lettore pota quello che sta
    **sotto** la filigrana — quindi la riga della filigrana resta sul lettore e
    verra' rimandata una volta, che e' il prezzo giusto per non buttare mai una
    lettura che il server non ha.
    """
    esito = {"righe_aggiunte": 0, "doppioni": 0, "rifiutate": 0,
             "filigrana": 0, "motivo": None}

    formato = payload.get("formato")
    if formato != FORMATO_ATTESO:
        # Un formato che non conosciamo non si interpreta a caso: si rifiuta e
        # il lettore tiene le sue righe. Interpretare male vorrebbe dire
        # scrivere nel database numeri che sembrano buoni.
        esito["motivo"] = f"formato_sconosciuto: {formato!r}"
        esito["filigrana"] = stato_letture(db, device.id)["da"]
        return esito

    vettori = payload.get("righe") or []
    if not isinstance(vettori, list):
        esito["motivo"] = "righe_non_una_lista"
        return esito

    righe = []
    for vettore in vettori:
        r = _riga_dal_vettore(vettore)
        if r is None:
            esito["rifiutate"] += 1
        else:
            righe.append(r)

    if righe:
        # Le chiavi che abbiamo gia', chieste in UNA volta sola invece di una
        # interrogazione per riga: duemila righe sarebbero duemila giri.
        istanti = [r["istante"] for r in righe]
        presenti = set(
            db.query(
                models.LetturaDiPagina.genere,
                models.LetturaDiPagina.istante,
                models.LetturaDiPagina.pagina,
            )
            .filter(
                models.LetturaDiPagina.device_id == device.id,
                models.LetturaDiPagina.istante >= min(istanti),
                models.LetturaDiPagina.istante <= max(istanti),
            )
            .all()
        )

        # L'impronta si risolve una volta per impronta, non una per riga: una
        # sessione di lettura sono centinaia di righe dello stesso libro.
        risolte: dict = {}
        nuove = []
        for r in righe:
            chiave = (r["genere"], r["istante"], r["pagina"])
            if chiave in presenti:
                esito["doppioni"] += 1
                continue
            presenti.add(chiave)  # due righe identiche nello stesso invio
            if r["library"] is None or r["calibre_book_id"] is None:
                impronta = r["impronta"]
                if impronta not in risolte:
                    risolte[impronta] = _risolvi_dall_impronta(db, impronta)
                r["library"], r["calibre_book_id"] = risolte[impronta]
            nuove.append(models.LetturaDiPagina(
                user_id=device.user_id, device_id=device.id, **r,
            ))
        if nuove:
            db.bulk_save_objects(nuove)
            db.flush()
            esito["righe_aggiunte"] = len(nuove)

    stato = stato_letture(db, device.id)
    # La filigrana e' l'ultimo istante che il server HA, non l'ultimo che il
    # dispositivo ha mandato: se una riga e' stata rifiutata, il lettore non
    # deve potarla.
    riga = (
        db.query(models.LetturaDiPagina)
        .filter(models.LetturaDiPagina.device_id == device.id)
        .order_by(models.LetturaDiPagina.istante.desc())
        .first()
    )
    esito["filigrana"] = _epoch(riga.istante) if riga else 0
    esito["righe_in_tutto"] = stato["righe"]
    return esito


# ── Risolverle in caratteri ─────────────────────────────────────────────

def _capitolo_dell_xpointer(xp: str) -> Optional[int]:
    """Il capitolo (0-based) a cui punta un xpointer di crengine.

    `/body/DocFragment[9]/body/p[10]/text().0` sta nel nono file dell'indice,
    che per `get_chapter_xhtml` e' l'indice 8.
    """
    if not xp:
        return None
    trovato = _DOCFRAGMENT.search(xp)
    if not trovato:
        return None
    n = int(trovato.group(1))
    return n - 1 if n >= 1 else None


def offsets_del_libro(epub_path: str):
    """
    Dove comincia ogni capitolo nel testo del libro, e quanto e' lungo in
    tutto, nella vista collassata (quella che somiglia a crengine).

    Torna `(offsets, totale, documenti)`: `offsets[i]` e' il carattere a cui
    comincia il capitolo i, `documenti[i]` il suo indice del testo (serve per
    risolvere gli xpointer dentro quel capitolo).

    **Costa una lettura dell'EPUB intero**, un capitolo per volta: e' il
    motivo per cui chi chiama ordina le righe per libro e converte tutte
    quelle di un libro insieme. Su «La linea d'ombra» sono 19 capitoli.
    Tenerlo in una tabella sarebbe l'ottimizzazione successiva, e vorrebbe
    dire decidere come invalidarla quando il file cambia — oggi non serve:
    qui si gira in sottofondo, a lotti.
    """
    quanti = get_spine_length(epub_path)
    if not quanti:
        return None, None, None
    offsets, documenti, totale = [], {}, 0
    for i in range(quanti):
        offsets.append(totale)
        xhtml = get_chapter_xhtml(epub_path, i)
        if xhtml is None:
            continue
        try:
            doc = parse_chapter_document(xhtml)
        except Exception:
            continue
        documenti[i] = doc
        totale += len(doc.index.collapsed)
    return offsets, totale, documenti


def _converti_una(riga, offsets, totale, documenti) -> str:
    """
    Scrive i caratteri assoluti su una riga, e torna lo stato risultante:
    `exact`, `senza_testo` o `failed`.

    `senza_testo` non e' un fallimento ed e' per questo che ha un nome suo:
    e' la pagina che non contiene testo. La prima pagina di quasi ogni EPUB e'
    la copertina — `/body/DocFragment[1]/body/div/img.0` o `.../svg.0` — e un
    divisorio di sezione e' un div vuoto. Sui primi dati veri (19/11/2026) era
    il caso di 7 righe su 25: chiamarle «fallite» voleva dire due cose
    sbagliate insieme, una parola falsa e un «ritenta le fallite» che ci
    riprova in eterno. Il tempo passato su quella pagina resta registrato,
    perche' e' vero; i caratteri restano vuoti, perche' sono zero.
    """
    capitolo = _capitolo_dell_xpointer(riga.xp_inizio)
    if capitolo is None or capitolo not in documenti or capitolo >= len(offsets):
        return "failed"
    inizio = xpointer_al_carattere(documenti[capitolo], riga.xp_inizio)
    if inizio is None:
        if not xpointer_punta_al_testo(documenti[capitolo], riga.xp_inizio):
            return "senza_testo"
        return "failed"
    riga.carattere_inizio = offsets[capitolo] + inizio
    riga.caratteri_del_libro = totale

    # La fine puo' stare in un ALTRO capitolo: una pagina a cavallo fra due
    # file dell'EPUB e' il caso normale, non l'eccezione.
    if riga.xp_fine:
        capitolo_fine = _capitolo_dell_xpointer(riga.xp_fine)
        if capitolo_fine is not None and capitolo_fine in documenti:
            fine = xpointer_al_carattere(documenti[capitolo_fine], riga.xp_fine, fine=True)
            if fine is not None:
                riga.carattere_fine = offsets[capitolo_fine] + fine
    else:
        # Regola 4, corretta (decisione di Paolo, 23/11/2026): l'ultima
        # pagina di un libro non ha «l'inizio della pagina dopo», ma la sua
        # fine non e' ignota — e' la fine del libro. Il numero giusto e' il
        # totale dell'indice del server, la STESSA misura di
        # carattere_inizio: mai book_text_stats.chars, che e' l'altra misura
        # (scarto 0,3-5,6% per libro, misurato il 23/11). Cosi' il tempo sul
        # finale di ogni libro finito entra nei caratteri e nella copertura.
        riga.carattere_fine = totale
    return "exact"


def converti_le_letture(db: Session, limite: int = LOTTO_DI_CONVERSIONE) -> dict:
    """
    Risolve in caratteri assoluti le righe che non lo sono ancora.

    Non solleva mai, per lo stesso contratto della conversione degli indirizzi
    delle note: un EPUB mancante o corrotto di un libro non deve impedire la
    conversione di tutti gli altri.

    Gli stati, e perche' sono tre e non due:
      * `exact` — i caratteri sono usabili;
      * `libro_assente` — il libro non e' piu' in biblioteca, o non e' un
        EPUB: la riga non e' difettosa, manca il testo su cui misurarla, e
        «ritenta le fallite» qui non servirebbe a niente;
      * `senza_testo` — l'indirizzo si risolve, ma dove punta non c'e'
        testo: la pagina e' la copertina (`.../div/img.0`, `.../div/svg.0`) o
        un divisorio vuoto. Il tempo resta registrato perche' e' vero, i
        caratteri restano vuoti perche' sono zero, e «ritenta le fallite» non
        ci riprova in eterno. Misurato: 7 righe sulle prime 25 vere;
      * `failed` — ci ho provato e l'indirizzo non si e' risolto. Questa si
        potra' riprovare quando l'indice migliora, ed e' il motivo per cui le
        posizioni restano scritte sulla riga.
    """
    from sqlalchemy import and_, or_
    righe = (
        db.query(models.LetturaDiPagina)
        .filter(
            or_(
                models.LetturaDiPagina.stato_conversione.is_(None),
                # Le righe d'ultima pagina convertite PRIMA della regola 4
                # (23/11/2026): exact con l'inizio noto ma la fine mai
                # scritta, perche' xp_fine non esiste sull'ultima pagina.
                # Si riprendono qui, una volta: appena la conversione
                # scrive carattere_fine = caratteri_del_libro smettono di
                # corrispondere al filtro. Il caso vero: «Fini e inizi»
                # p. 206, exact dal 22/11 ma senza fine.
                and_(
                    models.LetturaDiPagina.stato_conversione == "exact",
                    models.LetturaDiPagina.xp_fine.is_(None),
                    models.LetturaDiPagina.carattere_fine.is_(None),
                ),
            ),
            models.LetturaDiPagina.xp_inizio.isnot(None),
            models.LetturaDiPagina.library.isnot(None),
            models.LetturaDiPagina.calibre_book_id.isnot(None),
        )
        # Ordinate per libro: cosi' l'EPUB si apre una volta per libro e non
        # una per riga. E' la stessa ragione per cui il riempimento degli
        # indirizzi delle note ordina il suo lotto.
        .order_by(
            models.LetturaDiPagina.library,
            models.LetturaDiPagina.calibre_book_id,
            models.LetturaDiPagina.istante,
        )
        .limit(limite)
        .all()
    )
    esito = {"convertite": 0, "fallite": 0, "senza_testo": 0,
             "libro_assente": 0, "libri": 0}
    if not righe:
        return esito

    adesso = datetime.utcnow()
    chiave_corrente, offsets, totale, documenti = None, None, None, None
    for riga in righe:
        chiave = (riga.library, riga.calibre_book_id)
        if chiave != chiave_corrente:
            chiave_corrente = chiave
            offsets, totale, documenti = None, None, None
            esito["libri"] += 1
            try:
                lib = CalibreLibrary(config.library_path(riga.library))
                percorso = lib.get_format_file_path(riga.calibre_book_id, "EPUB")
            except Exception:
                percorso = None
            if percorso and os.path.exists(percorso):
                try:
                    offsets, totale, documenti = offsets_del_libro(percorso)
                except Exception as exc:  # noqa: BLE001
                    log_message("warning", "stats",
                                f"Reading rows: cannot index book {riga.library}/"
                                f"{riga.calibre_book_id}: {exc}")

        riga.convertita_il = adesso
        if not documenti or not totale:
            riga.stato_conversione = "libro_assente"
            esito["libro_assente"] += 1
            continue
        try:
            stato = _converti_una(riga, offsets, totale, documenti)
        except Exception:  # noqa: BLE001
            stato = "failed"
        riga.stato_conversione = stato
        if stato == "exact":
            esito["convertite"] += 1
        elif stato == "senza_testo":
            esito["senza_testo"] += 1
        else:
            esito["fallite"] += 1

    db.commit()
    return esito


def smaltisci_conversioni(db: Session) -> dict:
    """
    Converte TUTTO l'arretrato, un lotto dopo l'altro, finche' ce n'e'.

    Nata dal caso vero delle 89 righe ferme (trovato il 23/11/2026): le 489
    righe di un backup arrivate in un colpo solo, il lotto da 400, e il
    resto mai ripreso — perche' la conversione partiva SOLO quando
    arrivavano righe nuove, e il giro successivo convertiva le nuove
    lasciando indietro l'eventuale nuovo resto. Qui si gira a lotti (cosi'
    il commit resta frequente e un libro storto non blocca niente) finche'
    la coda non e' vuota.

    La guardia sui giri e' un paracadute, non un limite di progetto: 50
    lotti sono 20.000 righe in una passata, piu' di un mese di letture.
    Se mai scattasse, il giro periodico riprende da dove si e' fermato.
    """
    totale = {"convertite": 0, "fallite": 0, "senza_testo": 0,
              "libro_assente": 0, "giri": 0}
    while totale["giri"] < 50:
        esito = converti_le_letture(db, LOTTO_DI_CONVERSIONE)
        lavorate = (esito["convertite"] + esito["fallite"]
                    + esito["senza_testo"] + esito["libro_assente"])
        for chiave in ("convertite", "fallite", "senza_testo", "libro_assente"):
            totale[chiave] += esito[chiave]
        if lavorate == 0:
            break
        totale["giri"] += 1
    return totale


def ritenta_fallite(db: Session, eta_ore: int = 24) -> dict:
    """
    Rimette in coda le righe `failed` tentate piu' di `eta_ore` fa.

    Il contratto dichiarato di `failed` e' sempre stato «si potra'
    riprovare quando l'indice migliora» — ma nessuno riprovava mai (difetto
    D8, confermato da Paolo il 23/11/2026). Ora il giro quotidiano le
    rimette a NULL e `smaltisci_conversioni` le riprende: se falliscono di
    nuovo tornano `failed` con una `convertita_il` fresca, quindi si
    ritenta al massimo una volta al giorno, non in eterno a vuoto.

    `senza_testo` e `libro_assente` restano fuori DI PROPOSITO: la prima
    non e' un fallimento (la pagina e' una copertina: i caratteri sono
    zero), la seconda si risolve solo se il libro ricompare — e in quel
    caso e' la rielaborazione completa a riportarlo dentro, non un
    ritentativo cieco ogni giorno su libri che non ci sono piu'.
    """
    soglia = datetime.utcnow() - timedelta(hours=eta_ore)
    rimesse = (
        db.query(models.LetturaDiPagina)
        .filter(models.LetturaDiPagina.stato_conversione == "failed",
                models.LetturaDiPagina.convertita_il < soglia)
        .update({models.LetturaDiPagina.stato_conversione: None},
                synchronize_session=False)
    )
    db.commit()
    return {"rimesse_in_coda": rimesse}


# ── Dal dato grezzo alle sessioni e alla copertura (passo 4) ────────────
#
# Le sessioni (`ReadingSession`) continuano a NASCERE dal canale statistiche
# col raggruppamento a 15 minuti: qui non se ne crea e non se ne cancella
# nessuna. Il dato vero le ARRICCHISCE — decisione di Paolo, 20/11/2026 —
# scrivendo sulle sessioni che hanno righe esatte nella propria finestra
# temporale i caratteri davvero letti, e lasciando TUTTE le altre come sono
# (stima da fraction_read, `exact` = 0).

def _segna_intervallo_esatto(mappa: bytearray, bins: int,
                             inizio: int, fine: int, totale: int) -> bool:
    """Segna nella mappa di copertura i bin coperti da un intervallo di
    caratteri — l'ingresso ESATTO del bitmap, accanto a quello per pagine
    di `stats_service._segna_pagina`.

    Il denominatore e' `totale`, cioe' `caratteri_del_libro` DELLA RIGA:
    l'unico con cui e' lecito normalizzare i suoi caratteri (vedi la testa
    di questo modulo: le due misure del totale differiscono del 4% misurato,
    e una frazione fatta mescolandole e' sbagliata senza che niente lo dica).
    """
    if not totale or totale <= 0 or inizio is None or fine is None:
        return False
    if fine <= inizio or inizio >= totale:
        return False
    primo = int(inizio / totale * bins)
    ultimo = max(primo + 1, int(min(fine, totale) / totale * bins))
    for k in range(max(0, primo), min(bins, ultimo)):
        mappa[k // 8] |= 1 << (k % 8)
    return True


#: Regola 1, il limite della finestra allungata (decisione di Paolo,
#: 23/11/2026, «si potra' riprendere»). La finestra di una sessione si
#: allunga fino all'inizio della successiva dello stesso libro — ma al
#: massimo questi secondi dopo la propria fine naturale, che e' la stessa
#: pausa che separa due sessioni (stats_service._SESSION_GAP_SECONDS).
#:
#: **Il caso che l'ha resa necessaria**: con la regola letterale, fra due
#: sessioni lontane la finestra della prima copre settimane. Su «Un
#: rivoluzionario chiamato Pancho», una sessione del 6/10 si prendeva le
#: girate fatte il 22/11 pochi secondi prima dell'inizio della sessione di
#: quel giorno (5.238 caratteri grezzi). Con il limite, una riga misurata
#: in una pausa breve entra ancora nella sessione giusta; una riga lontana
#: resta in attesa della sua.
WINDOW_EXTENSION_MAX_SECONDS = 900


def _unisci_intervalli(intervalli) -> tuple:
    """Unione di intervalli [a, b) di caratteri assoluti: (lista fusa,
    totale coperto). E' il cuore della D1: lo stesso tratto di testo, anche
    visto da pagine di impaginazioni diverse (oggi 104-532, domani 455-600),
    conta una volta — ci si sovrappongono i CARATTERI, non le pagine."""
    fusi = []
    for a, b in sorted((int(a), int(b)) for a, b in intervalli if b > a):
        if fusi and a <= fusi[-1][1]:
            if b > fusi[-1][1]:
                fusi[-1][1] = b
        else:
            fusi.append([a, b])
    return fusi, sum(b - a for a, b in fusi)


def derive_reading_sessions(db: Session) -> dict:
    """
    Arricchisce sessioni e copertura con le righe risolte in caratteri — e
    da fase 3 (decisioni di Paolo del 23/11/2026) scrive anche i valori
    RIPULITI, nelle colonne accanto ai grezzi.

    **I grezzi restano come sono sempre stati**: `chars_read` e' la somma
    degli intervalli esatti nella finestra, `char_start`/`char_end` i loro
    estremi, `exact` il distintivo. Niente di cio' che c'era cambia.

    **La pulizia, nell'ordine deciso:**

      1. **Finestra allungata (regola 1).** La finestra di una sessione
         arriva all'INIZIO della sessione successiva dello stesso libro, ma
         al massimo WINDOW_EXTENSION_MAX_SECONDS (15 minuti) dopo la sua
         fine naturale: la durata non comprende le pause, e una riga
         misurata in una pausa breve non deve restare orfana per sempre.
      2. **Sfoglio (D2).** Una pagina con velocita' oltre la soglia (3x la
         tipica, da reading_thresholds) — o con durata <= 2 s, sfoglio per
         definizione — NON conta nei caratteri puliti ne' nella mappa di
         copertura. Il suo tempo resta.
      3. **Delta delle note (D5).** Il tempo dei popup si sposta dalla
         pagina alla voce `note_time`; il canale del tempo non si tocca.
      4. **Tetto (D3).** Il tempo contato di una pagina non supera
         larghezza/velocita' lenta, mai sotto i 120 s. Si applica DOPO il
         delta, e solo ai valori ripuliti (`duration_clean`).
      5. **Unione degli intervalli (D1).** I caratteri puliti della
         sessione sono l'UNIONE degli intervalli delle pagine buone, in
         caratteri assoluti: ogni tratto una volta, pagina spezzata dalla
         sospensione compresa (e' lo stesso intervallo due volte).
      6. **Nuovo e riletto.** In ordine di tempo, per libro: la parte di
         unione mai coperta dalle sessioni precedenti e' `chars_new`; il
         riletto e' la differenza. Distinguibile dal 19/11/2026, da quando
         il grezzo esiste.

    `duration_clean` e' la misura di tempo DELLO STESSO canale dei
    caratteri (righe di pagina della finestra, delta e tetto applicati):
    serve alle velocita' oneste, NON sostituisce `duration` nei totali —
    i due canali tagliano in modo diverso e non si mescolano.

    Le altre decisioni dichiarate (il dispositivo non fa parte
    dell'aggancio; solo sessioni koreader; niente ritocchi ai grezzi;
    idempotente per ricalcolo da zero) restano quelle di sempre — vedi la
    storia di questo file.
    """
    from . import reading_thresholds, stats_service  # qui: nessun giro di import

    soglie = reading_thresholds.current(db)
    sfoglio_cps = soglie.get("skim_threshold_cps")
    lenta_cps = soglie.get("slow_speed_cps")
    tetto_minimo = reading_thresholds.PAGE_TIME_FLOOR_SECONDS
    sfoglio_durata = reading_thresholds.SKIM_MIN_DURATION_SECONDS

    righe = (
        db.query(models.LetturaDiPagina)
        .filter(
            models.LetturaDiPagina.library.isnot(None),
            models.LetturaDiPagina.calibre_book_id.isnot(None),
        )
        .order_by(
            models.LetturaDiPagina.library,
            models.LetturaDiPagina.calibre_book_id,
            models.LetturaDiPagina.istante,
        )
        .all()
    )
    esito = {"sessioni_arricchite": 0, "righe_esatte": 0,
             "libri": 0, "biblioteche": [], "copertura_aggiornata": 0}
    if not righe:
        return esito

    def e_esatta(riga):
        return (riga.genere == models.LetturaDiPagina.PAGINA
                and riga.stato_conversione == "exact"
                and riga.carattere_inizio is not None
                and riga.carattere_fine is not None
                and riga.carattere_fine > riga.carattere_inizio)

    def e_sfoglio(riga):
        # Solo per righe esatte: senza larghezza la velocita' non esiste.
        if riga.durata <= sfoglio_durata:
            return True
        if not sfoglio_cps:
            return False
        larghezza = riga.carattere_fine - riga.carattere_inizio
        return (larghezza / riga.durata) > sfoglio_cps

    def tetto_di(riga):
        if e_esatta(riga) and lenta_cps:
            larghezza = riga.carattere_fine - riga.carattere_inizio
            return max(larghezza / lenta_cps, tetto_minimo)
        # Senza larghezza (copertine, righe non convertite) vale il minimo
        # fisso: non dipende dai dati.
        return tetto_minimo

    gruppi: dict = {}
    for riga in righe:
        gruppi.setdefault((riga.user_id, riga.library, riga.calibre_book_id), []).append(riga)

    biblioteche = set()
    for (user_id, library, calibre_book_id), del_libro in gruppi.items():
        pagine = [r for r in del_libro if r.genere == models.LetturaDiPagina.PAGINA]
        note = [r for r in del_libro if r.genere == models.LetturaDiPagina.NOTA]
        esatte = [r for r in pagine if e_esatta(r)]
        esito["righe_esatte"] += len(esatte)
        if not pagine and not note:
            continue
        esito["libri"] += 1

        sessioni = (
            db.query(models.ReadingSession)
            .filter(
                models.ReadingSession.user_id == user_id,
                models.ReadingSession.library == library,
                models.ReadingSession.calibre_book_id == calibre_book_id,
                models.ReadingSession.source == "koreader",
            )
            .order_by(models.ReadingSession.start_time)
            .all()
        )
        if not sessioni:
            # Niente sessioni ancora (arriveranno col prossimo backup): le
            # righe aspettano, ma la copertura si marca comunque, sotto.
            pass

        # Le finestre, con la regola 1 allungata e il suo limite
        # (WINDOW_EXTENSION_MAX_SECONDS: il perche' sta li').
        finestre = []
        allungamento = timedelta(seconds=WINDOW_EXTENSION_MAX_SECONDS)
        for i, sessione in enumerate(sessioni):
            inizio = sessione.start_time
            fine_naturale = inizio + timedelta(seconds=sessione.duration or 0)
            fine = fine_naturale + allungamento
            if i + 1 < len(sessioni):
                fine = min(fine, sessioni[i + 1].start_time - timedelta(seconds=1))
            finestre.append((inizio, max(fine, fine_naturale)))

        # Un giro per sessione, in ordine di tempo: prima i valori grezzi
        # (identici a prima), poi i puliti, poi la cronologia nuovo/riletto.
        coperti_prima = []   # unione cumulativa delle sessioni precedenti
        for sessione, (inizio, fine) in zip(sessioni, finestre):
            in_pagine = [r for r in pagine if inizio <= r.istante <= fine]
            in_note = [r for r in note if inizio <= r.istante <= fine]
            in_esatte = [r for r in in_pagine if e_esatta(r)]

            # ── I grezzi, come sono sempre stati ──
            somma, char_start, char_end = 0, None, None
            for riga in in_esatte:
                larghezza = riga.carattere_fine - riga.carattere_inizio
                somma += larghezza
                if char_start is None or riga.carattere_inizio < char_start:
                    char_start = riga.carattere_inizio
                if char_end is None or riga.carattere_fine > char_end:
                    char_end = riga.carattere_fine

            # ── I puliti ──
            buone = [r for r in in_esatte if not e_sfoglio(r)]
            intervalli_buoni, unione = _unisci_intervalli(
                (r.carattere_inizio, r.carattere_fine) for r in buone)

            tempo_note = sum(n.durata or 0 for n in in_note) if in_note else None
            durata_pulita = None
            if in_pagine:
                durata_pulita = 0
                for riga in in_pagine:
                    sovrapposte = sum(
                        n.durata or 0 for n in in_note
                        if riga.istante <= n.istante
                        <= riga.istante + timedelta(seconds=riga.durata or 0))
                    netta = max((riga.durata or 0) - sovrapposte, 0)
                    durata_pulita += int(min(netta, tetto_di(riga)))

            chars_clean = unione if in_esatte else None
            nuovi = None
            if chars_clean is not None:
                prima = sum(b - a for a, b in coperti_prima)
                dopo, totale_dopo = _unisci_intervalli(
                    [tuple(iv) for iv in coperti_prima]
                    + [tuple(iv) for iv in intervalli_buoni])
                nuovi = totale_dopo - prima
                coperti_prima = dopo

            cambiata = False
            if in_esatte:
                if (sessione.chars_read != somma or sessione.char_start != char_start
                        or sessione.char_end != char_end or not sessione.exact):
                    sessione.chars_read = somma
                    sessione.char_start = char_start
                    sessione.char_end = char_end
                    sessione.exact = 1
                    cambiata = True
            if (sessione.chars_read_clean != chars_clean
                    or sessione.chars_new != nuovi
                    or sessione.note_time != tempo_note
                    or sessione.duration_clean != durata_pulita):
                sessione.chars_read_clean = chars_clean
                sessione.chars_new = nuovi
                sessione.note_time = tempo_note
                sessione.duration_clean = durata_pulita
                cambiata = True
            if cambiata:
                esito["sessioni_arricchite"] += 1
                biblioteche.add(library)

        # ── La copertura, dagli intervalli veri, sfoglio escluso (D2) ──
        mappa = bytearray(stats_service._BINS // 8)
        segnato = False
        for riga in esatte:
            if e_sfoglio(riga):
                continue
            if _segna_intervallo_esatto(mappa, stats_service._BINS,
                                        riga.carattere_inizio, riga.carattere_fine,
                                        riga.caratteri_del_libro):
                segnato = True
        if segnato:
            stats_service.aggiorna_copertura(db, user_id, library, calibre_book_id, mappa)
            esito["copertura_aggiornata"] += 1
            biblioteche.add(library)

    esito["biblioteche"] = sorted(biblioteche)
    db.commit()
    return esito
