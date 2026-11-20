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
    righe = (
        db.query(models.LetturaDiPagina)
        .filter(
            models.LetturaDiPagina.stato_conversione.is_(None),
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


def derive_reading_sessions(db: Session) -> dict:
    """
    Arricchisce sessioni e copertura con le righe risolte in caratteri.

    **Cosa fa, per ogni libro/utente che ha righe `exact`:**

      1. **Sessioni.** Ogni riga di PAGINA esatta cade (o no) nella finestra
         temporale di una sessione KOReader dello stesso utente e libro —
         `start_time <= istante <= start_time + duration`. Sulle sessioni
         che hanno almeno una riga si scrive: `chars_read` (somma degli
         intervalli carattere_fine - carattere_inizio), `char_start`/
         `char_end` (min/max assoluti) e `exact` = 1. Le sessioni senza
         righe NON si toccano: restano stimate, `exact` = 0.
      2. **Copertura.** I bin del bitmap (`BookReadingCoverage`) si marcano
         dagli intervalli veri, normalizzati col `caratteri_del_libro`
         DELLA RIGA, e si uniscono alla mappa esistente con la stessa
         unione di `stats_service.aggiorna_copertura`.

    **Le decisioni dichiarate, e il loro perche':**

      * **Le righe di NOTA (genere 'n') non si sommano ai caratteri di
        pagina.** Il tempo su un popup di nota e' gia' separato alla fonte
        proprio perche' KOReader lo attribuiva alla pagina ferma sotto, e
        rimetterlo dentro qui rifarebbe lo stesso errore sui caratteri: i
        caratteri della nota sono un dato SUO, che restera' leggibile dalle
        righe grezze quando si decidera' come mostrarlo. Per lo stesso
        motivo le note non marcano la copertura: l'apparato non e' il corpo
        del libro percorso.
      * **La finestra e' [inizio, inizio + durata] inclusivo**, su istanti
        UTC (lo stesso orologio: entrambe le tabelle convertono l'epoch del
        lettore con utcfromtimestamp). Una riga che non cade in nessuna
        finestra — la sessione arrivera' col prossimo backup delle
        statistiche — resta in attesa: questo passo e' rieseguibile e la
        riprende al giro dopo.
      * **Il dispositivo NON fa parte dell'aggancio**, di proposito: le
        sessioni si fondono fra dispositivi della stessa persona (il caso
        Syncthing: 737 doppioni su 743, misurato) e `device_id` resta al
        primo che ha sincronizzato, mentre le righe portano il dispositivo
        che le ha misurate. Pretendere l'uguaglianza mancherebbe proprio le
        sessioni fuse. L'utente, il libro e la finestra bastano.
      * **Solo sessioni `source` = 'koreader'**: le righe vengono dal
        lettore; una sessione del lettore web nello stesso momento e' una
        lettura diversa e non va rietichettata.
      * **Una riga senza `carattere_fine`** (l'ultima pagina del libro, che
        non ha «l'inizio della pagina dopo») non entra ne' nella somma ne'
        nella copertura: di quel tratto si sa dove comincia ma non quanto e'
        lungo, e inventare una fine sarebbe un numero falso.
      * **Idempotente per ricalcolo da zero**: ogni giro RICALCOLA i valori
        dalla totalita' delle righe esatte invece di accumulare sul valore
        precedente, quindi due giri danno lo stesso risultato, e un giro
        dopo che l'indice e' migliorato (righe `failed` diventate `exact`)
        aggiorna tutto lo storico — e' il principio «si conserva la prova».
        La copertura e' un OR di bit: rimarcarla non cambia niente.
      * **Niente soglie e niente pulizia degli outlier** (Paolo, 20/11/2026,
        punto F2): una pagina lasciata aperta la notte conta per la sua
        durata vera. La soglia si decidera' guardando i dati grezzi, che
        restano — non qui.

    **Esatto e stimato sullo stesso libro convivono cosi':** sulla singola
    sessione vince una misura sola, dichiarata da `exact`; sul bitmap di
    copertura le due si UNISCONO (OR), perche' la copertura risponde a «cosa
    ho visto almeno una volta» e un millesimo visto resta visto con
    qualunque misura lo si sia guardato.

    Il costo: oggi ricalcola su TUTTE le righe esatte a ogni giro — che al
    20/11/2026 sono decine, non migliaia. Limitarlo ai libri toccati
    dall'ultimo lotto e' l'ottimizzazione successiva, quando servira'.

    Commit alla fine, come `converti_le_letture`. Non solleva per un libro
    storto: ogni gruppo e' indipendente.
    """
    from . import stats_service  # qui e non in testa: nessun giro di import

    righe = (
        db.query(models.LetturaDiPagina)
        .filter(
            models.LetturaDiPagina.stato_conversione == "exact",
            models.LetturaDiPagina.genere == models.LetturaDiPagina.PAGINA,
            models.LetturaDiPagina.carattere_inizio.isnot(None),
            models.LetturaDiPagina.carattere_fine.isnot(None),
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
    esito = {"sessioni_arricchite": 0, "righe_esatte": len(righe),
             "libri": 0, "biblioteche": [], "copertura_aggiornata": 0}
    if not righe:
        return esito

    gruppi: dict = {}
    for riga in righe:
        gruppi.setdefault((riga.user_id, riga.library, riga.calibre_book_id), []).append(riga)

    biblioteche = set()
    for (user_id, library, calibre_book_id), del_libro in gruppi.items():
        esito["libri"] += 1

        # ── 1. Le sessioni di questo libro, arricchite dalla finestra ──
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
        for sessione in sessioni:
            inizio_finestra = sessione.start_time
            fine_finestra = sessione.start_time + timedelta(seconds=sessione.duration or 0)
            somma, char_start, char_end, quante = 0, None, None, 0
            for riga in del_libro:
                if riga.istante < inizio_finestra or riga.istante > fine_finestra:
                    continue
                larghezza = riga.carattere_fine - riga.carattere_inizio
                if larghezza <= 0:
                    continue
                quante += 1
                somma += larghezza
                if char_start is None or riga.carattere_inizio < char_start:
                    char_start = riga.carattere_inizio
                if char_end is None or riga.carattere_fine > char_end:
                    char_end = riga.carattere_fine
            if not quante:
                continue  # nessuna riga: la sessione resta stimata, intatta
            if (sessione.chars_read != somma or sessione.char_start != char_start
                    or sessione.char_end != char_end or not sessione.exact):
                sessione.chars_read = somma
                sessione.char_start = char_start
                sessione.char_end = char_end
                sessione.exact = 1
                esito["sessioni_arricchite"] += 1
                biblioteche.add(library)

        # ── 2. La copertura, dagli intervalli veri ─────────────────────
        mappa = bytearray(stats_service._BINS // 8)
        segnato = False
        for riga in del_libro:
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
