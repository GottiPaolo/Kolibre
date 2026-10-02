"""
Le entita' della biblioteca: autori, serie, tag, editori.

Non sono libri e non sono impostazioni: sono i NOMI con cui i libri stanno
insieme, e in una biblioteca vera sono disordinati. Misurato su una
biblioteca reale il 28/09/2026, su 4.982 autori: **305 gruppi** dello stesso
autore scritto in modi diversi (García Márquez in nove grafie, Cortázar in
cinque), 84 stringhe con piu' autori separati da qualcosa che non e' `&`,
36 nomi tutti maiuscoli, 38 con spazi doppi, 25 con dentro "a cura di", 25
con delle cifre, una decina di titoli finiti nel campo autore.

Le tre classi di disordine, in ordine di quanto sono meccaniche da
riconoscere:
  1. **inversione** `Cognome, Nome` — la convenzione `author_sort` di Calibre
     finita nel nome. La piu' numerosa e la piu' sicura;
  2. **accenti** — García/Garcia/Garcìa;
  3. **punteggiatura e spaziatura** — `AA. VV.` / `AA.VV.` / `Aa. Vv.`.

Qui c'e' solo il riconoscere e il contare. L'unire vive nell'API, perche'
passa dalla coda di scrittura di Calibre — e perche' unire due entita' e' una
decisione, mai un'iniziativa del sistema.
"""

from difflib import SequenceMatcher

from ..calibre.functions import string_to_authors
from .. import models
from ..models import coppia_ordinata
from . import duplicates

# Le quattro entita', e come si tirano fuori da una biblioteca. Ogni voce
# dice: tabella dei valori, tabella di collegamento, colonna che punta al
# valore, e se il campo puo' contenere piu' nomi in una stringa sola.
TIPI = {
    "autori": {
        "etichetta": "Autori",
        "tabella": "authors", "colonna": "name",
        "legame": "books_authors_link", "chiave": "author",
        "multiplo": True,
    },
    "serie": {
        "etichetta": "Serie",
        "tabella": "series", "colonna": "name",
        "legame": "books_series_link", "chiave": "series",
        "multiplo": False,
    },
    "tag": {
        "etichetta": "Tag",
        "tabella": "tags", "colonna": "name",
        "legame": "books_tags_link", "chiave": "tag",
        "multiplo": False,
    },
    "editori": {
        "etichetta": "Editori",
        "tabella": "publishers", "colonna": "name",
        "legame": "books_publishers_link", "chiave": "publisher",
        "multiplo": False,
    },
}

# Quanto due nomi devono somigliarsi per finire nello stesso gruppo.
#
# Piu' alta della soglia dei doppioni fra libri (0,85): li' si confrontano
# titoli lunghi, dove qualche parola di differenza pesa poco; qui si
# confrontano nomi corti, dove "Mario Rossi" e "Dario Rossi" stanno gia' a
# 0,90 e sono due persone diverse. Misurata: a 0,90 i gruppi veri misurati
# (García Márquez, Cortázar, AA.VV.) restano tutti, e le coppie di omonimi
# parziali escono.
SOGLIA_AFFINITA = 0.90


def _forma_confrontabile(nome: str) -> str:
    """Il nome ridotto a cio' che conta per capire se e' la stessa persona.

    Passa dalla stessa normalizzazione dei doppioni — via accenti,
    punteggiatura, maiuscole, spazi doppi — e in piu' RIORDINA le parole.
    Senza il riordino, "Cognome, Nome" e "Nome Cognome" restano due stringhe
    diverse, ed e' la classe di disordine piu' numerosa di tutte."""
    normalizzato = duplicates._normalizza(nome or "")
    return " ".join(sorted(normalizzato.split()))


def affinita(a: str, b: str) -> float:
    fa, fb = _forma_confrontabile(a), _forma_confrontabile(b)
    if not fa or not fb:
        return 0.0
    if fa == fb:
        # Identici una volta riordinati e ripuliti: e' il caso
        # dell'inversione e quello degli accenti. Nessun dubbio.
        return 1.0
    return SequenceMatcher(None, fa, fb).ratio()


def elenca(lib, tipo: str) -> list:
    """I valori di questo tipo, con quanti libri ciascuno."""
    forma = TIPI[tipo]
    conn = lib._connect()
    try:
        righe = conn.execute(f"""
            SELECT v.id AS id, v.{forma['colonna']} AS valore, COUNT(l.book) AS libri
            FROM {forma['tabella']} v
            LEFT JOIN {forma['legame']} l ON l.{forma['chiave']} = v.id
            GROUP BY v.id ORDER BY v.{forma['colonna']} COLLATE NOCASE
        """).fetchall()
        return [{"id": r["id"], "valore": r["valore"], "libri": r["libri"]} for r in righe]
    finally:
        conn.close()


def elenca_ovunque(biblioteche: list, tipo: str) -> list:
    """Gli stessi valori, ma su piu' biblioteche insieme.

    Serve perche' il disordine dei nomi non si ferma al confine di una
    biblioteca: "Svetlana Aleksievič" sta in una biblioteca e "Svetlana
    Aleksievic" in un'altra, e guardandole una per volta non si somigliano
    mai — sono due elenchi diversi. Uniformare gli autori e' proprio la
    ragione per cui questa pagina esiste, quindi deve poterle vedere tutte
    insieme.

    Il conteggio si somma per VALORE e non per id: l'id di un autore e'
    interno alla sua biblioteca, e "l'autore numero 12" di due biblioteche
    diverse sono due persone diverse. `dove` dice in quali biblioteche
    compare, che e' l'informazione che l'id non puo' dare piu'.
    """
    per_valore = {}
    for nome, lib in biblioteche:
        for voce in elenca(lib, tipo):
            riga = per_valore.setdefault(
                voce["valore"], {"id": voce["valore"], "valore": voce["valore"], "libri": 0, "dove": []}
            )
            riga["libri"] += voce["libri"]
            if voce["libri"] and nome not in riga["dove"]:
                riga["dove"].append(nome)
    return sorted(per_valore.values(), key=lambda v: v["valore"].lower())


def coppie_distinte(db, tipo: str) -> set:
    """Le coppie che qualcuno ha dichiarato essere cose diverse."""
    return {
        coppia_ordinata(r.valore_a, r.valore_b)
        for r in db.query(models.EntitaDistinte).filter(models.EntitaDistinte.tipo == tipo)
    }


def dichiara_distinte(db, tipo: str, valori: list, chi: str | None = None) -> int:
    """Registra che i valori dati sono cose diverse, a due a due.

    Si prendono TUTTE le coppie e non solo la prima con la seconda: rifiutare
    un gruppo di tre significa dire che nessuna delle tre e' l'altra, e
    registrarne solo una lascerebbe il gruppo a ricomparire senza un pezzo.
    """
    puliti = []
    for v in valori:
        v = (v or "").strip()
        if v and v not in puliti:
            puliti.append(v)
    if len(puliti) < 2:
        return 0
    gia = coppie_distinte(db, tipo)
    nuove = 0
    for i, a in enumerate(puliti):
        for b in puliti[i + 1:]:
            coppia = coppia_ordinata(a, b)
            if coppia in gia:
                continue
            db.add(models.EntitaDistinte(
                tipo=tipo, valore_a=coppia[0], valore_b=coppia[1], deciso_da=chi,
            ))
            gia.add(coppia)
            nuove += 1
    db.commit()
    return nuove


def dimentica_distinte(db, tipo: str, valori: list) -> int:
    """Torna a proporre una coppia: il rifiuto era sbagliato, o non serve piu'."""
    if len(valori) < 2:
        return 0
    a, b = coppia_ordinata(valori[0], valori[1])
    tolte = db.query(models.EntitaDistinte).filter(
        models.EntitaDistinte.tipo == tipo,
        models.EntitaDistinte.valore_a == a,
        models.EntitaDistinte.valore_b == b,
    ).delete()
    db.commit()
    return tolte


def dimentica_distinte_fra(db, tipo: str, valori: list) -> int:
    """Toglie ogni rifiuto fra i valori dati.

    La chiama l'unione: se si uniscono due grafie che erano state dichiarate
    diverse, quel "no" e' stato ritirato col gesto stesso di unirle, e lasciarlo
    scritto vorrebbe dire tenere in archivio un'affermazione che chi l'ha fatta
    ha poi smentito.
    """
    coppie = {
        coppia_ordinata(a, b)
        for i, a in enumerate(valori) for b in valori[i + 1:]
        if a != b
    }
    if not coppie:
        return 0
    tolte = 0
    for a, b in coppie:
        tolte += db.query(models.EntitaDistinte).filter(
            models.EntitaDistinte.tipo == tipo,
            models.EntitaDistinte.valore_a == a,
            models.EntitaDistinte.valore_b == b,
        ).delete()
    if tolte:
        db.commit()
    return tolte


def _spezza_sui_rifiuti(gruppo: list, distinte: set) -> list:
    """Divide un gruppo dove qualcuno ha detto "questi due sono diversi".

    Serve perche' un gruppo puo' avere piu' di due voci, e un rifiuto ne
    riguarda due: con {A, B, C} e il rifiuto A-B, buttare via tutto
    perderebbe A-C, che nessuno ha rifiutato.

    Il criterio e' quello minimo che non inventa niente: ogni voce entra nel
    primo sottogruppo con cui non litiga, e se litiga con tutti ne apre uno
    suo. Le voci arrivano in ordine di preferenza (Wikipedia, poi numero di
    libri), quindi il sottogruppo che si forma per primo e' quello attorno
    alla grafia piu' probabile. I sottogruppi rimasti con una voce sola
    spariscono: una grafia da sola non e' un suggerimento.

    Conseguenza da conoscere: con {A, B, C} e il rifiuto A-B, resta proposto
    {A, C} e la coppia {B, C} non compare, pur non essendo stata rifiutata.
    Non si perde — unito A con C, al giro dopo B si ritrova davanti una sola
    grafia e il gruppo si riforma. La scelta e' voluta: mostrare C in due
    gruppi diversi significa che unirne uno svuota l'altro sotto gli occhi di
    chi guarda.
    """
    if len(gruppo) < 2:
        return []
    sotto = []
    for voce in gruppo:
        for pezzo in sotto:
            if all(coppia_ordinata(voce["valore"], altro["valore"]) not in distinte
                   for altro in pezzo):
                pezzo.append(voce)
                break
        else:
            sotto.append([voce])
    return [p for p in sotto if len(p) > 1]


def gruppi_affini(valori: list, limite: int = 200, distinte: set | None = None) -> list:
    """I valori che sembrano la stessa cosa scritta in modi diversi.

    Raggruppati per **forma confrontabile**: due nomi che si riducono alla
    stessa forma sono certamente parenti, e attorno a quel nucleo si
    raccolgono i vicini sopra soglia. Cosi' quei 305 gruppi escono senza
    confrontare 4.982 nomi a due a due (dodici milioni di paragoni).
    """
    # Le voci senza libri non partecipano: sono il residuo di accorpamenti
    # gia' fatti — unendo "eleuthera" in "eleuthera" con l'accento, la prima
    # resta nella tabella di Calibre senza piu' collegamenti — e proporre di
    # unirle significa proporre un lavoro gia' finito. Riscontrato in uso il
    # 29/09/2026: veniva ancora suggerito un editore a zero libri.
    valori = [v for v in valori if v["libri"] > 0]

    per_forma = {}
    for voce in valori:
        per_forma.setdefault(_forma_confrontabile(voce["valore"]), []).append(voce)

    gruppi = [list(v) for v in per_forma.values() if len(v) > 1]
    gia_dentro = {id(v) for gruppo in gruppi for v in gruppo}

    # Il secondo giro: i nomi che NON coincidono una volta ripuliti ma si
    # somigliano molto — le abbreviazioni, soprattutto ("Gilbert Keith
    # Chesterton" e "Gilbert K. Chesterton").
    #
    # **Non a due a due.** Su 3.842 autori sarebbero sette milioni di
    # confronti: misurati, due minuti. Si confrontano solo i nomi che
    # condividono almeno una PAROLA lunga — un cognome, in pratica — e il
    # conto scende di tre ordini di grandezza senza perdere un gruppo: due
    # grafie dello stesso autore che non hanno nemmeno una parola in comune
    # non le riconoscerebbe nemmeno una persona.
    rimasti = [v for v in valori if id(v) not in gia_dentro]
    rimasti.sort(key=lambda v: -v["libri"])
    per_parola = {}
    for voce in rimasti:
        for parola in set(_forma_confrontabile(voce["valore"]).split()):
            if len(parola) >= 4:
                per_parola.setdefault(parola, []).append(voce)

    usati = set()
    for voce in rimasti:
        if id(voce) in usati or len(gruppi) >= limite:
            continue
        candidati = {}
        for parola in set(_forma_confrontabile(voce["valore"]).split()):
            if len(parola) < 4:
                continue
            for altro in per_parola.get(parola, ()):
                if altro is not voce and id(altro) not in usati:
                    candidati[id(altro)] = altro
        vicini = [voce]
        for altro in candidati.values():
            if affinita(voce["valore"], altro["valore"]) >= SOGLIA_AFFINITA:
                vicini.append(altro)
                usati.add(id(altro))
        if len(vicini) > 1:
            usati.add(id(voce))
            gruppi.append(vicini)

    # Chi va proposto per primo — cioe' la destinazione suggerita dell'unione.
    #
    # Prima era "quello con piu' libri", e sbagliava proprio i casi che
    # contano. Il caso del 28/09/2026: «Gladwell, Malcolm ← Malcolm
    # Gladwell», e la grafia giusta e' la seconda. Il numero di libri non sa
    # niente di come si
    # scrive un nome: se la grafia storta e' quella che hai importato di piu',
    # vince la storta.
    #
    # **Wikipedia lo sa.** Se per una grafia il recupero dei metadati ha
    # trovato una voce e per l'altra no, quella e' la grafia con cui il resto
    # del mondo chiama quella persona: "Svetlana Aleksievič" ha una pagina,
    # "Svetlana Aleksievic" no. E' un indizio esterno, non una preferenza
    # nostra, ed e' il solo pezzo di informazione vera disponibile qui.
    #
    # Il numero di libri resta, ma come SECONDO criterio: decide solo fra
    # grafie che Wikipedia conosce allo stesso modo (o non conosce affatto).
    for gruppo in gruppi:
        gruppo.sort(key=lambda v: (not v.get("conosciuto"), -v["libri"], v["valore"]))

    # I rifiuti si applicano QUI, a gruppi già ordinati: l'ordine decide quale
    # sottogruppo si forma per primo, e va fatto prima di spezzare. E prima del
    # taglio a `limite`, altrimenti un gruppo svuotato da un rifiuto sprecherebbe
    # uno dei duecento posti disponibili.
    if distinte:
        spezzati = []
        for gruppo in gruppi:
            spezzati.extend(_spezza_sui_rifiuti(gruppo, distinte))
        gruppi = spezzati

    gruppi.sort(key=lambda g: -sum(v["libri"] for v in g))
    return gruppi[:limite]


def segna_conosciuti(valori: list, nomi_con_dati: set) -> list:
    """Marca i valori per cui esiste una voce trovata online.

    Separata dal raggruppamento perche' la fonte e' un'altra: i nomi arrivano
    dalla biblioteca Calibre, questo dato da `author_metadata` in app.db. Un
    solo posto dove le due cose si incontrano, e si vede quale.
    """
    for voce in valori:
        voce["conosciuto"] = voce["valore"] in nomi_con_dati
    return valori


def sostituisci_in_stringa(stringa_autori: str, vecchio: str, nuovo: str) -> str:
    """Un autore dentro una stringa che puo' contenerne piu' d'uno.

    "Anna Bianchi & Mario Rossi", sostituendo "Mario Rossi" con "M. Rossi",
    deve diventare "Anna Bianchi & M. Rossi" e non "M. Rossi". E se il nuovo
    nome c'e' gia' nella stringa, il vecchio sparisce invece di comparire due
    volte: unire due grafie dello stesso autore su un libro che le aveva
    entrambe non deve lasciarlo con un coautore fantasma."""
    nomi = string_to_authors(stringa_autori or "")
    risultato = []
    for nome in nomi:
        candidato = nuovo if nome == vecchio else nome
        if candidato not in risultato:
            risultato.append(candidato)
    return " & ".join(risultato)
