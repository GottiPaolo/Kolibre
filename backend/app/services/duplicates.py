"""
I doppioni, e come si decide cosa farne.

La pipeline e' questa, e l'ordine conta piu' di quanto sembri:

  1. si cercano i candidati per AFFINITA' DI METADATI (titolo + autore);
  2. solo su quelli si calcola un hash vero, perche' hashare un'intera
     biblioteca per trovare tre doppioni sarebbe leggere gigabyte per
     niente;
  3. dove l'hash coincide sono lo STESSO FILE, e lo scarto si puo'
     proporre con un bottone solo;
  4. dove non coincide sono due file diversi dello stesso libro, e allora
     si misura la qualita' (vedi epub_quality) e decide una persona.

L'hash e' uno SHA-256 pieno e non il partial MD5 che il server gia'
calcola per i dispositivi. Quello campiona dodici blocchi da un kilobyte:
basta e avanza per riconoscere un file su un Kindle, non basta per
autorizzare una cancellazione. Se si cancella per conto dell'utente, la
prova dev'essere completa.
"""

import hashlib
import json
import os
import sqlite3
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from .. import config, models
from . import book_records
from ..calibre.functions import string_to_authors
from ..calibre.library import CalibreLibrary
from . import epub_quality

# Formati che vale la pena confrontare. Gli altri (immagini, txt) non sono
# libri, e l'elenco e' lo stesso di una precedente migrazione di biblioteca.
FORMATI = ("EPUB", "MOBI", "AZW3", "PDF")

# A parita' di tutto il resto si preferisce l'EPUB, come da nota: e' il
# formato che Kolibre sa leggere, convertire, impaginare e indicizzare.
PREFERENZA_FORMATO = {"EPUB": 3, "AZW3": 2, "MOBI": 1, "PDF": 0}


def _normalizza(testo: str) -> str:
    """
    Titolo o autore ridotti alla loro forma confrontabile.

    Via accenti, punteggiatura, articoli iniziali e spazi doppi. Serve a
    far combaciare "L'Idiota" con "Idiota, L'" e "Dostoevskij, Fedor" con
    "Fëdor Dostoevskij", che sono esattamente le differenze che una
    biblioteca vera contiene.
    """
    t = unicodedata.normalize("NFD", testo or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"^(il|lo|la|i|gli|le|un|uno|una|the|a|an|l)\s+", "", t.strip())
    return re.sub(r"\s+", " ", t).strip()


def _chiave_autore(autore: str) -> str:
    """
    I cognomi degli autori, ordinati: l'insieme dentro cui cercare
    affinita' di titolo.

    I cognomi e non i nomi interi perche' "Fedor Dostoevskij" e "F.
    Dostoevskij" sono la stessa persona e devono finire nello stesso
    blocco, mentre includere il nome li separerebbe.

    Il confronto fra titoli avviene SOLO dentro un blocco, e non e' una
    scorciatoia: e' quello che rende la ricerca praticabile. Confrontare
    ogni titolo con ogni altro su 5.843 libri sarebbe diciassette milioni
    di confronti; dentro l'opera di un autore sono qualche decina.
    """
    cognomi = sorted(
        filter(None, (_cognome(a) for a in string_to_authors(autore or "")))
    )
    return "|".join(cognomi)


def _cognome(nome: str) -> str:
    """
    Il cognome dentro un nome d'autore, nelle due forme che una biblioteca
    vera contiene davvero.

    "L'ultima parola" non basta: "Calvino, Italo" darebbe *italo* e
    "Italo Calvino" *calvino*, e i due finirebbero in blocchi diversi pur
    essendo la stessa persona. L'inversione "Cognome, Nome" e' una delle tre
    classi di disordine misurate sui 4.982 autori di una biblioteca reale
    (le altre due sono gli accenti e la punteggiatura), ed e' la piu'
    meccanica da riconoscere: la virgola, per Calibre, non separa due autori
    — quello lo fa '&' — quindi dentro un singolo nome segna la forma
    d'ordinamento, e cio' che la precede e' il cognome.
    """
    grezzo = nome or ""
    if "," in grezzo:
        grezzo = grezzo.split(",", 1)[0]
    parti = _normalizza(grezzo).split()
    return parti[-1] if parti else ""


# Nome pubblico della chiave d'autore. Il controllo doppioni della pagina
# Ingest usa la stessa, e attraversare un nome privato da un altro modulo e'
# il modo in cui due criteri che devono restare identici prendono strade
# diverse senza che nessuno se ne accorga.
chiave_autore = _chiave_autore


# Quanto due titoli devono somigliarsi per finire nello stesso gruppo.
#
# Misurata, non scelta a occhio: sulla biblioteca di prova le tre edizioni
# vere della stessa opera in piu' volumi stanno fra 0,87 e 0,91 — lo stesso
# titolo catalogato una volta con l'articolo, una volta senza e una volta
# con "V1" al posto di "Volume 1" — e la prima coppia NON imparentata sta
# sotto 0,50. In mezzo c'e' parecchio spazio: 0,85 sta dalla parte giusta
# con margine.
#
# Un margine che serve, perche' il costo dei due errori non e' lo stesso:
# un doppione non trovato resta li' in silenzio, un falso positivo chiede
# all'utente di esaminare due libri che non c'entrano — e dopo tre di
# quelli nessuno guarda piu' l'elenco.
SOGLIA_AFFINITA = 0.85


def _numeri(testo: str) -> list:
    """I numeri dentro un titolo, in ordine. "Vol. 2" -> ["2"]."""
    return re.findall(r"\d+", testo or "")


# Le parentesi che non contengono cifre: collana, edizione, provenienza.
#
# Su una biblioteca reale 723 titoli su 7.057 ne hanno almeno una, e 641 di
# quelle sono il solo "(Italian Edition)" che Kindle attacca a tutto. Non
# dicono NIENTE su quale libro sia, e in un confronto di somiglianza pesano
# come testo vero: "La casa grigia (Narrativa) (Italian Edition)" e "La casa
# bianca (Narrativa) (Italian Edition)" sono due romanzi diversi che il
# suffisso condiviso spingeva sopra soglia.
#
# Misurato togliendole: quattro falsi doppioni spariti (le due case di Bang,
# due Manganelli diversi, i due Padre Brown di Chesterton) e cinque doppioni
# veri trovati — sempre lo stesso libro presente due volte, una con il
# suffisso e una senza, che e' esattamente il modo in cui nascono.
#
# Le parentesi CON cifre restano dove sono: "(Vol. 2)" distingue due tomi, e
# toglierla disinnescherebbe la regola dei numeri qui sotto.
_PARENTESI_SENZA_CIFRE = re.compile(r"\((?!\s*\d)[^()\d]*\)")


def _senza_collana(titolo: str) -> str:
    return _PARENTESI_SENZA_CIFRE.sub(" ", titolo or "")


def affinita_titoli(a: str, b: str) -> float:
    """
    Quanto due titoli si somigliano, con una regola in piu' sui NUMERI.

    Se entrambi i titoli contengono cifre e le cifre sono diverse, non
    sono lo stesso libro — e non importa quanto si somiglino le lettere.
    "Guerra e pace vol. 1" e "Guerra e pace vol. 2" stanno sopra 0,95 di
    somiglianza testuale: senza questa regola un'opera in dieci tomi
    diventa un unico gruppo di doppioni, e accorparlo cancellerebbe nove
    volumi veri.

    Trovato provando: nella biblioteca di prova "Magazzino 00" e
    "Magazzino 07" dello stesso autore finivano insieme, e con loro altri
    quindici gruppi inventati.

    I numeri si confrontano come INSIEME e non in ordine, perche' "Vol. 1"
    e "1 - Volume" sono lo stesso; e la regola scatta solo se li hanno
    tutti e due: un titolo con l'indicazione del tomo e uno senza possono
    benissimo essere la stessa edizione catalogata in due modi, che e'
    proprio il caso delle tre edizioni citate in SOGLIA_AFFINITA.

    Prima del confronto cadono le parentesi di collana/edizione: vedi
    `_PARENTESI_SENZA_CIFRE`.
    """
    na, nb = _normalizza(_senza_collana(a)), _normalizza(_senza_collana(b))
    ca, cb = _numeri(na), _numeri(nb)
    if ca and cb and sorted(int(x) for x in ca) != sorted(int(x) for x in cb):
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def sha256(percorso: str) -> str | None:
    """L'hash intero del file. None se non si legge."""
    try:
        h = hashlib.sha256()
        with open(percorso, "rb") as f:
            for blocco in iter(lambda: f.read(1024 * 1024), b""):
                h.update(blocco)
        return h.hexdigest()
    except OSError:
        return None


def nomi_file(cartella_biblioteca: str) -> dict:
    """
    (id libro, FORMATO) -> nome del file, come lo sa Calibre.

    Si legge dalla tabella `data`, che e' l'unico posto dove il nome vero
    e' scritto: i file importati da altrove non seguono la convenzione
    Calibre — nella biblioteca di prova ce n'e' uno chiamato "Titolo
    (z-library.sk, 1lib.sk, z-lib.sk).epub" — quindi comporlo da titolo e
    autore non funziona.

    E nemmeno funziona guardare nella cartella e prendere il primo file
    con l'estensione giusta, che era la prima versione di questa funzione:
    dove `path` e' vuoto o due libri condividono una cartella, ogni libro
    si vedeva attribuito lo STESSO file. Su una funzione che poi autorizza
    una cancellazione, indovinare non e' accettabile.
    """
    percorso_db = os.path.join(cartella_biblioteca, "metadata.db")
    if not os.path.exists(percorso_db):
        return {}
    try:
        conn = sqlite3.connect(f"file:{percorso_db}?mode=ro", uri=True)
        try:
            return {
                (r[0], (r[1] or "").upper()): r[2]
                for r in conn.execute("SELECT book, format, name FROM data")
            }
        finally:
            conn.close()
    except sqlite3.Error:
        return {}


def _file_del_libro(cartella_biblioteca: str, libro: dict, nomi: dict) -> list:
    """
    I file veri di un libro, uno per formato.

    Un formato senza il suo nome in `data`, o il cui file non esiste sul
    disco, viene SALTATO: meglio un libro che risulta non misurabile —
    caso che la pipeline sa gestire, si ferma e chiede — di un libro a cui
    e' stato attribuito il file di un altro.
    """
    cartella = os.path.join(cartella_biblioteca, libro.get("path") or "")
    fuori = []
    for fmt in {f.upper() for f in (libro.get("formats") or [])} & set(FORMATI):
        nome = nomi.get((libro["id"], fmt))
        if not nome:
            continue
        percorso = os.path.join(cartella, f"{nome}.{fmt.lower()}")
        if os.path.exists(percorso):
            fuori.append({"formato": fmt, "percorso": percorso})
    return fuori


def _coppie_distinte(db: Session) -> set:
    return {r.chiave for r in db.query(models.DuplicatiDistinti).all()}


def trova_doppioni(db: Session, biblioteca: str, limite_gruppi: int = 200) -> dict:
    """
    I gruppi di libri che potrebbero essere lo stesso, DENTRO una sola
    biblioteca.

    Una sola, per scelta: lo stesso libro presente in due
    biblioteche diverse non e' un problema da segnalare. Fra una
    biblioteca personale e un magazzino la sovrapposizione e' il
    funzionamento normale — e' proprio cosi' che un libro passa dal
    secondo alla prima — e trattarla come un doppione riempirebbe la coda
    di lavoro di cose che nessuno vuole risolvere.
    """
    per_autore = defaultdict(list)
    try:
        cartella = config.library_path(biblioteca)
        libri = CalibreLibrary(cartella).list_books()
        mappa_nomi = nomi_file(cartella)
    except Exception:
        return {"gruppi": [], "gruppi_totali": 0, "non_mostrati": 0}

    for b in libri:
        chiave = _chiave_autore(b.get("author") or "")
        if not chiave or not (b.get("title") or "").strip():
            continue
        per_autore[chiave].append({
            "library": biblioteca, "cartella": cartella, "libro": b, "nomi": mappa_nomi,
        })

    distinte = _coppie_distinte(db)
    gruppi = []
    for chiave_autore, voci in per_autore.items():
        if len(voci) < 2:
            continue
        for gruppo in _raggruppa_per_affinita(voci):
            if len(gruppo) < 2:
                continue
            # Se OGNI coppia del gruppo e' gia' stata dichiarata distinta,
            # il gruppo e' chiuso e non va riproposto.
            if _tutte_distinte(gruppo, distinte):
                continue
            gruppi.append((f"{chiave_autore}|{_normalizza(gruppo[0]['libro']['title'])}", gruppo))

    # Prima i gruppi piu' numerosi: sono quelli dove si guadagna di piu' a
    # decidere, e dove un errore di raggruppamento si vede subito.
    gruppi.sort(key=lambda g: (-len(g[1]), g[0]))
    troncati = max(0, len(gruppi) - limite_gruppi)

    fuori = []
    for chiave, voci in gruppi[:limite_gruppi]:
        fuori.append(_descrivi_gruppo(chiave, voci, distinte))
    return {"gruppi": fuori, "gruppi_totali": len(gruppi), "non_mostrati": troncati}


def _raggruppa_per_affinita(voci: list) -> list:
    """
    Dentro l'opera di un autore, mette insieme i titoli che si somigliano.

    Aggregazione avida e TRANSITIVA: se A somiglia a B e B a C, i tre
    finiscono insieme anche quando A e C da soli starebbero appena sotto
    soglia. E' voluto — sono proprio le tre edizioni della stessa opera con
    titoli scritti in tre modi, il caso da cui questa funzione nasce — e il
    rischio di catena resta piccolo perche' il confronto avviene gia'
    dentro un solo autore.
    """
    gruppi: list = []
    for v in voci:
        titolo = v["libro"].get("title") or ""
        for g in gruppi:
            if any(affinita_titoli(titolo, m["libro"].get("title") or "") >= SOGLIA_AFFINITA for m in g):
                g.append(v)
                break
        else:
            gruppi.append([v])
    return gruppi


def _tutte_distinte(voci: list, distinte: set) -> bool:
    for i in range(len(voci)):
        for j in range(i + 1, len(voci)):
            k = models.chiave_coppia(
                voci[i]["library"], voci[i]["libro"]["id"],
                voci[j]["library"], voci[j]["libro"]["id"],
            )
            if k not in distinte:
                return False
    return True


def _descrivi_gruppo(chiave: str, voci: list, distinte: set) -> dict:
    """
    Un gruppo con tutto quello che serve a decidere: hash, qualita',
    formati, dimensione.

    L'hash si calcola QUI e non prima: e' il passo 2 della pipeline, e
    girare su tutta la biblioteca invece che sui candidati vorrebbe dire
    leggere ogni file del server per trovare tre doppioni.
    """
    membri = []
    for v in voci:
        b = v["libro"]
        file = _file_del_libro(v["cartella"], b, v["nomi"])
        # Il file migliore di questo libro e' quello su cui si decide: un
        # libro con epub+pdf vale quanto il suo epub.
        file.sort(key=lambda f: -PREFERENZA_FORMATO.get(f["formato"], 0))
        principale = file[0] if file else None
        qualita = epub_quality.qualita_file(principale["percorso"], principale["formato"]) if principale else None
        membri.append({
            "library": v["library"],
            "id": b["id"],
            "title": b.get("title"),
            "author": b.get("author"),
            "formats": b.get("formats") or [],
            "size": b.get("size") or 0,
            "date_added": b.get("date_added"),
            "formato_principale": principale["formato"] if principale else None,
            "hash": sha256(principale["percorso"]) if principale else None,
            "qualita": qualita["punteggio"] if qualita else None,
            "qualita_dettaglio": qualita["dettaglio"] if qualita else None,
            "leggibile": qualita["leggibile"] if qualita else None,
        })

    # Sottogruppi a hash identico: quelli sono lo STESSO file, e per loro
    # la decisione e' meccanica.
    per_hash = defaultdict(list)
    for m in membri:
        if m["hash"]:
            per_hash[m["hash"]].append(m["id"])
    identici = [ids for ids in per_hash.values() if len(ids) > 1]

    return {
        "chiave": chiave,
        "titolo": membri[0]["title"],
        "autore": membri[0]["author"],
        "membri": membri,
        "identici": identici,
        # Il migliore per qualita', a parita' il formato preferito, a
        # parita' il piu' grande. None quando nessuno e' misurabile: e'
        # proprio il caso in cui l'automatismo deve fermarsi.
        "migliore": _migliore(membri),
    }


def _migliore(membri: list) -> int | None:
    misurabili = [m for m in membri if m["qualita"] is not None]
    if not misurabili:
        return None
    return max(
        misurabili,
        key=lambda m: (
            m["qualita"],
            PREFERENZA_FORMATO.get(m["formato_principale"] or "", -1),
            m["size"] or 0,
        ),
    )["id"]


def dichiara_distinti(db: Session, coppie: list) -> int:
    """Ricorda che queste coppie non sono lo stesso libro."""
    gia = _coppie_distinte(db)
    nuove = 0
    for c in coppie:
        k = models.chiave_coppia(c["library_a"], c["book_a"], c["library_b"], c["book_b"])
        if k in gia:
            continue
        db.add(models.DuplicatiDistinti(
            chiave=k, library_a=c["library_a"], book_a=int(c["book_a"]),
            library_b=c["library_b"], book_b=int(c["book_b"]),
        ))
        gia.add(k)
        nuove += 1
    db.commit()
    return nuove


# ── Decidere ─────────────────────────────────────────────────────────────

# Di quanto il migliore deve staccare gli altri perche' l'automatismo se la
# senta. Cinque punti su cento sono poco in assoluto ed e' voluto: il vero
# freno e' il dominio su OGNI criterio, questo serve solo a scartare i
# pareggi tecnici.
STACCO_MINIMO = 5


CRITERI = ("integrita", "toc", "struttura", "css", "peso")


def domina(vincitore: dict, altri: list) -> bool:
    """
    Se il perdente perde su TUTTI i fronti — la regola di partenza.

    Tradotta con cura, perche' la prima stesura la prendeva alla lettera
    ("strettamente meglio su ogni criterio") e non scattava mai: due file
    sani hanno entrambi integrita' 100, e piu' intatto di intatto non si
    puo' essere. Chiedere il segno di maggiore su una scala che ha un
    tetto raggiungibile significa chiedere l'impossibile.

    Quello che conta davvero e' l'altra meta': NESSUN criterio in cui il
    perdente sia migliore. Se il file che sta per essere accorpato ha un
    indice migliore, o pesa di piu' perche' contiene immagini che l'altro
    non ha, il punteggio complessivo sta nascondendo qualcosa e la
    decisione torna a una persona.

    Quindi: il vincitore non e' mai sotto su niente, e stacca di almeno
    STACCO_MINIMO in totale. Sulle tre edizioni citate sopra (87, 85, 85) non
    scatta — lo stacco e' due — ed e' giusto cosi'.
    """
    mio = vincitore.get("qualita_dettaglio")
    if not mio or vincitore.get("qualita") is None:
        return False
    for a in altri:
        suo = a.get("qualita_dettaglio")
        # Un file non misurabile non e' un file peggiore: e' un file di cui
        # non si sa niente, e ci si ferma.
        if not suo or a.get("qualita") is None:
            return False
        if vincitore["qualita"] - a["qualita"] < STACCO_MINIMO:
            return False
        for criterio in CRITERI:
            # Un dettaglio PARZIALE arriva davvero: per un file illeggibile
            # epub_quality torna presto con il solo criterio "integrita" e un
            # punteggio non nullo, quindi passava la guardia qui sopra e poi
            # si moriva su suo["toc"]. Ed e' il caso di punta — un EPUB
            # troncato a meta' download — quindi bastava un file cosi' per
            # rendere la pagina Doppioni un 500 permanente.
            if criterio not in mio or criterio not in suo:
                return False
            if mio[criterio]["punteggio"] < suo[criterio]["punteggio"]:
                return False
    return True


def ha_roba_dell_utente(db: Session, library: str, book_id: int) -> bool:
    """
    Se su questo libro c'e' qualcosa che l'utente ha prodotto: note, o ore
    di lettura.

    Regola ferma: un libro cosi' si preserva A PRESCINDERE. Non e' un
    di piu' — le note sono ancorate al testo di QUELLA edizione, e le ore
    sono un fatto accaduto. Un automatismo che le sposta altrove fa una
    scommessa; un automatismo che si ferma no.
    """
    if db.query(models.Highlight).filter(
        models.Highlight.library == library,
        models.Highlight.calibre_book_id == book_id,
    ).first():
        return True
    return bool(db.query(models.ReadingSession).filter(
        models.ReadingSession.library == library,
        models.ReadingSession.calibre_book_id == book_id,
    ).first())


def accorpa(db: Session, tenere: tuple, scartare: tuple) -> dict:
    """
    Sposta sul libro da tenere tutto quello che era attaccato all'altro, e
    poi lo toglie dal catalogo.

    ACCORPARE e non scartare: posizioni, sessioni,
    accoppiamenti di hash e note passano al vincitore invece di sparire con
    il perdente.

    Le note migrano con il loro TESTO ma senza la loro posizione: il CFI
    puntava dentro l'altro file e li' non vale piu' niente. Azzerare
    cfi/position_status le rimette nella conversione normale, che le
    riaggancia cercando il loro testo nel nuovo libro — lo stesso
    meccanismo gia' usato quando si accoppia una nota orfana. Se il passo
    non c'e' (edizioni con traduzioni diverse, per dire) la nota sopravvive
    come testo senza posizione, che e' il terzo stato che
    widowed_highlights gia' conosce: non si perde niente in silenzio.

    NON committa: decide il chiamante, cosi' l'operazione puo' unirsi alla
    cancellazione del libro nella stessa transazione.
    """
    lib_da, id_da = scartare
    lib_a, id_a = tenere

    note = db.query(models.Highlight).filter(
        models.Highlight.library == lib_da,
        models.Highlight.calibre_book_id == id_da,
    ).count()

    book_records.release_book(db, lib_da, id_da, migrate_to=(lib_a, id_a))

    # Le note migrate perdono l'ancora: si riconverte tutto il libro, che e'
    # piu' semplice e piu' sicuro che indovinare quali erano le arrivate.
    db.query(models.Highlight).filter(
        models.Highlight.library == lib_a,
        models.Highlight.calibre_book_id == id_a,
    ).update(
        {"cfi_start": None, "cfi_end": None, "position_status": None},
        synchronize_session=False,
    )

    # Copertura e conteggio caratteri restano appesi a un libro che non
    # esiste piu' (release_book non li tocca, ne' sul percorso di
    # cancellazione ne' su quello di spostamento). Con una deduplica di
    # massa diventerebbero parecchie righe morte, e su un id riassegnato
    # darebbero numeri di un altro libro.
    for modello in (models.BookReadingCoverage, models.BookTextStats):
        db.query(modello).filter(
            modello.library == lib_da, modello.calibre_book_id == id_da
        ).delete(synchronize_session=False)

    return {"note_migrate": note}


def cosa_si_puo_fare(db: Session, gruppo: dict) -> dict:
    """
    Cosa si puo' fare su questo gruppo, distinguendo la PROVA
    dall'INDIZIO. Sono due cose diverse e devono restare separate anche
    nel nome, o prima o poi qualcuno tratta la seconda come la prima.

    `automatico=True` SOLO quando i file sono identici byte per byte.
    Li' non serve credere a niente: due file con lo stesso SHA-256 sono lo
    stesso file, e tenerne uno solo e' una constatazione. Vale anche se il
    raggruppamento fosse sbagliato a monte — restano identici comunque.

    In tutti gli altri casi `automatico=False`, per quanto netto sia il
    punteggio, e per una ragione precisa: la qualita' risponde a
    "quale dei due e' migliore", ma da' per scontato "sono lo stesso
    libro", e quella certezza viene da una somiglianza di titolo sopra
    0,85 — un indizio forte, non una prova. Un falso positivo li' dentro
    piu' un accorpamento automatico fa sparire un libro che non c'entrava
    niente, e nessuno se ne accorge finche' non lo cerca.

    Quando il punteggio e' netto si offre un SUGGERIMENTO: quale tenere,
    gia' scelto, a un clic di distanza. La differenza fra suggerire e fare
    e' tutta la sicurezza di questa funzione.

    Poi il freno di sempre: mai su un libro che ha note o sessioni di
    lettura.
    """
    membri = gruppo["membri"]
    per_id = {m["id"]: m for m in membri}
    niente = {
        "automatico": False, "suggerimento": None,
        "tenere": None, "scartare": [], "trattenuti": [],
    }

    biblioteca = membri[0]["library"]

    def senza_roba_dell_utente(ids: list) -> tuple:
        tengono = [i for i in ids if not ha_roba_dell_utente(db, biblioteca, i)]
        return tengono, [i for i in ids if i not in tengono]

    # ── La prova: stesso file ────────────────────────────────────────
    if gruppo["identici"]:
        ids = sorted(gruppo["identici"][0])
        scartare, trattenuti = senza_roba_dell_utente(ids[1:])
        if not scartare:
            return {**niente, "trattenuti": trattenuti}
        return {
            "automatico": True, "suggerimento": "identici",
            "tenere": ids[0], "scartare": scartare, "trattenuti": trattenuti,
        }

    # ── L'indizio: file diversi, uno nettamente migliore ─────────────
    migliore = gruppo.get("migliore")
    if migliore is None:
        return niente
    altri = [m for m in membri if m["id"] != migliore]
    if not altri or not domina(per_id[migliore], altri):
        return niente
    scartare, trattenuti = senza_roba_dell_utente([m["id"] for m in altri])
    if not scartare:
        return {**niente, "trattenuti": trattenuti}
    return {
        # File diversi: si propone, non si fa.
        "automatico": False, "suggerimento": "qualita",
        "tenere": migliore, "scartare": scartare, "trattenuti": trattenuti,
    }


# ── La ricerca tenuta da parte ───────────────────────────────────────────
#
# Cercare i doppioni costa: per sapere se due file sono lo stesso si
# leggono dal disco e se ne calcola lo SHA-256. Rifarlo a ogni apertura
# della pagina vuol dire aspettare ogni volta, e rifarlo dopo ogni azione
# vuol dire che l'azione sembra non aver fatto niente.
#
# Quindi il risultato si conserva, e si aggiorna in due modi diversi: per
# intero quando si chiede una nuova ricerca, e per SOTTRAZIONE quando si
# accorpa o si dichiara una coppia distinta. E' il secondo che rende la
# pagina viva — il gruppo esce dall'elenco subito, senza rileggere un byte.


def leggi_scansione(db: Session, biblioteca: str) -> dict | None:
    riga = db.query(models.DoppioniScansione).filter(
        models.DoppioniScansione.ambito == biblioteca
    ).first()
    if not riga:
        return None
    try:
        dati = json.loads(riga.risultato_json)
    except ValueError:
        return None
    dati["calcolato_il"] = riga.calcolato_il.isoformat() if riga.calcolato_il else None
    return dati


def salva_scansione(db: Session, biblioteca: str, risultato: dict) -> None:
    riga = db.query(models.DoppioniScansione).filter(
        models.DoppioniScansione.ambito == biblioteca
    ).first()
    if not riga:
        riga = models.DoppioniScansione(ambito=biblioteca, risultato_json="{}")
        db.add(riga)
    # `calcolato_il` viene ricalcolato dalla riga in lettura: non va nel
    # JSON, o una sottrazione successiva lo riscriverebbe come se fosse
    # stata rifatta la ricerca.
    riga.risultato_json = json.dumps({k: v for k, v in risultato.items() if k != "calcolato_il"})
    riga.calcolato_il = datetime.utcnow()
    db.commit()


def cerca_e_conserva(db: Session, biblioteca: str) -> dict:
    risultato = trova_doppioni(db, biblioteca)
    for g in risultato["gruppi"]:
        g["azioni"] = cosa_si_puo_fare(db, g)
    salva_scansione(db, biblioteca, risultato)
    return leggi_scansione(db, biblioteca) or risultato


def togli_libri(db: Session, biblioteca: str, ids: list) -> None:
    """
    Toglie dei libri dal risultato conservato, senza rifare la ricerca.

    Un gruppo che scende sotto i due membri non e' piu' un doppione e
    sparisce: e' quello che deve succedere dopo un accorpamento.
    """
    dati = leggi_scansione(db, biblioteca)
    if not dati:
        return
    fuori = []
    for g in dati.get("gruppi", []):
        g["membri"] = [m for m in g["membri"] if m["id"] not in ids]
        if len(g["membri"]) < 2:
            continue
        # Gli hash identici vanno ripuliti anche loro, o un gruppo
        # continuerebbe a dirsi "automatico" per un libro che non c'e' piu'.
        g["identici"] = [
            [i for i in gruppo if i not in ids]
            for gruppo in g.get("identici", [])
        ]
        g["identici"] = [gruppo for gruppo in g["identici"] if len(gruppo) > 1]
        g["azioni"] = cosa_si_puo_fare(db, g)
        fuori.append(g)
    dati["gruppi"] = fuori
    dati["gruppi_totali"] = len(fuori) + dati.get("non_mostrati", 0)
    salva_scansione(db, biblioteca, dati)


def togli_gruppo(db: Session, biblioteca: str, chiave: str) -> None:
    """Toglie un gruppo intero: serve dopo "sono libri distinti"."""
    dati = leggi_scansione(db, biblioteca)
    if not dati:
        return
    dati["gruppi"] = [g for g in dati.get("gruppi", []) if g.get("chiave") != chiave]
    dati["gruppi_totali"] = len(dati["gruppi"]) + dati.get("non_mostrati", 0)
    salva_scansione(db, biblioteca, dati)
