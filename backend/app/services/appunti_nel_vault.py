"""
Cosa c'e' nelle note di Obsidian, e cosa ci manca.

**Il contesto, da zero.** Il plugin Obsidian tiene un file per libro, con
dentro un blocco per evidenziazione. Paolo ci scrive attorno: link suoi, note
sue, ancore per citare un paragrafo da fuori. Vuole due cose che sembrano in
contrasto: che il file si **aggiorni** quando una nota arriva o cambia, e che
quello che ha scritto lui **non si tocchi mai**.

Si tengono insieme con tre idee, e questo modulo e' la terza.

1. **Il marcatore e' un confine.** Dentro un blocco, sopra il marcatore
   scrive Kolibre, sotto scrive Paolo e Kolibre non legge nemmeno. Il caso
   piu' frequente — «ho aggiunto un link» — smette di essere un conflitto.
2. **Il confronto a tre vie.** Il blocco porta l'impronta di quello che
   Kolibre aveva scritto l'ultima volta (la *base*). Da tre valori — base,
   com'e' adesso nel file, com'e' adesso sul server — escono quattro casi, e
   tre si risolvono da se'. Il quarto, cambiato in tutte due le parti, lo
   decide Paolo **dalla pagina di Kolibre**, e il plugin esegue (sua
   decisione del 05/11/2026).
3. **Il server tiene una fotografia, non uno specchio.** A ogni
   sincronizzazione il plugin racconta cosa ha: per ogni blocco, l'identita'
   della nota e le due impronte. Il server se lo scrive **con la data** e da
   quello ricava gli stati. Non e' un registro di cosa dovrebbe esserci: e'
   il racconto di cosa c'era alle 14:32. Se Paolo cancella un file, il
   prossimo racconto lo dice e lo stato torna «non creato» — che e' la
   verita', non un difetto.

   La differenza non e' accademica: **il manifesto del Kindle che non
   guardava il disco e' precisamente la cosa che ha creato 21 libri in doppia
   copia.**

**Questo modulo non parla col database.** Prende le tre cose (le note del
server, la fotografia, le decisioni) e dice gli stati. Cosi' si puo' provare
sui casi veri senza un vault, senza Obsidian e senza interfaccia.
"""

import hashlib
import re
from typing import Iterable, Optional

_SPAZI = re.compile(r"\s+")

#: Lo stato di un libro, dal piu' urgente al piu' tranquillo. L'ordine e' lo
#: stesso con cui la pagina li mostra: Paolo ha chiesto di vedere per difetto
#: **solo quello che ha bisogno di lui**, e con settantanove libri annotati i
#: tre che contano non devono stare in mezzo agli altri settantasei.
#:
#: `in_attesa` vuol dire «la decisione c'e' gia', manca solo che il plugin
#: passi». Sta **dopo** i tre che hanno bisogno di Paolo e prima di `in_pari`:
#: non e' in pari — il vault non rispecchia ancora la decisione — ma non c'e'
#: niente da fare, e metterlo fra le cose urgenti vorrebbe dire chiedere due
#: volte la stessa cosa.
#:
#: `cancellato_da_te` sta in fondo, accanto a `bloccato`, perche' e' **quiete
#: voluta**: quel file l'ha cancellato lui e il plugin non lo ricrea. Non e'
#: un difetto da segnalare, e' una decisione da ricordare. Se intanto
#: arrivano note mai consegnate il libro passa da se' a `non_creato`, perche'
#: quelle il plugin le porta.
ORDINE_DEGLI_STATI = ("conflitto", "non_creato", "non_aggiornato", "in_attesa",
                      "in_pari", "cancellato_da_te", "bloccato")

#: Lo stato di **una** nota dentro il vault. Li' dove lo stato di un libro
#: riassume, questo distingue — ed e' quello che la pagina di un libro mostra
#: riga per riga.
#:
#: La coppia che conta e' `mai_consegnata` / `togliata_da_te`: tutte due vuol
#: dire «questa nota non e' nel file», ma la prima chiede di essere scritta e
#: la seconda **chiede di essere lasciata in pace**. Senza il registro delle
#: consegne le due sono indistinguibili, ed e' il motivo per cui il plugin
#: rimetteva ogni nota che Paolo togliesse a mano.
STATI_DI_UNA_NOTA = ("conflitto", "mai_consegnata", "da_portare",
                     "modificata_da_te", "togliata_da_te", "in_pari")


def impronta_del_brano(testo: Optional[str]) -> str:
    """
    L'impronta di un brano: sedici caratteri.

    **Serve a confrontare due testi scritti da due programmi diversi**, quindi
    la cosa che conta non e' l'algoritmo ma che le due parti normalizzino
    **allo stesso modo**. Qui gli spazi di qualunque tipo — spazi, tabulazioni,
    ritorni a capo — diventano uno spazio solo, e si tolgono quelli ai bordi.
    Senza questo, un blocco riscritto da Obsidian con un ritorno a capo in piu'
    sembrerebbe modificato da Paolo, e il plugin smetterebbe per sempre di
    aggiornarlo.

    Non si normalizza niente d'altro, e in particolare **non si tocca la
    punteggiatura ne' le maiuscole**: una correzione di refuso dentro una
    citazione *deve* risultare una modifica, perche' e' una modifica.

    Sedici caratteri esadecimali sono 64 bit: per distinguere due brani dello
    stesso libro e' abbondante, e in un file di testo si leggono.

    `prove/appunti_nel_vault.py` fissa alcune coppie (testo, impronta) proprio
    perche' l'altra meta' di questo confronto e' scritta in JavaScript: quei
    valori sono il modo di controllare che le due parti si capiscano.
    """
    pulito = _SPAZI.sub(" ", (testo or "")).strip()
    return hashlib.sha256(pulito.encode("utf-8")).hexdigest()[:16]


def chiave_del_libro(biblioteca: Optional[str], titolo: Optional[str]) -> tuple:
    """
    Come si raggruppano le note in file.

    **E' la stessa chiave che usa il plugin** (`biblioteca::titolo`), e non per
    comodita': se le due divergessero, il server calcolerebbe gli stati su un
    raggruppamento e il plugin scriverebbe su un altro — e un libro
    risulterebbe «non creato» mentre il suo file e' la'. Vale anche per i file
    non ancora accoppiati, che arrivano con `device:<id>` come biblioteca.
    """
    return (biblioteca or "", titolo or "")


def _conflitto(blocco: dict, impronta_del_server: str) -> bool:
    """
    Vero solo quando **tutte due le parti** hanno cambiato quel brano rispetto
    a quello che Kolibre aveva scritto l'ultima volta.

    Un blocco senza base non e' un conflitto: e' un blocco scritto da una
    versione del plugin che non la portava, e per cui non si puo' dire chi ha
    cambiato cosa. Si lascia stare, ed e' la scelta prudente — nel dubbio non
    si riscrive il file di qualcuno.
    """
    base = blocco.get("impronta_base")
    if not base:
        return False
    nel_file = blocco.get("impronta_attuale") or ""
    return nel_file != base and impronta_del_server != base


def stato_di_una_nota(blocco: Optional[dict], impronta_server: str,
                      consegnata: bool) -> str:
    """
    Lo stato di una nota, da tre cose: com'e' nel file, com'e' sul server, e
    **se e' mai stata consegnata**.

    Il terzo e' l'ingrediente aggiunto il 06/11/2026, e serve a distinguere
    due situazioni che fino a quel giorno erano lo stesso dato:

    - una nota che **non e' mai arrivata** nel vault, da scrivere;
    - una nota che **c'era e Paolo l'ha togliata**, da lasciare in pace.

    Una fotografia del vault non sa dire cosa c'era prima: «questo libro non
    ha nessun blocco» e' identico, carattere per carattere, a «questo libro
    non ha mai avuto un file». Per questo il plugin rimetteva ogni nota
    cancellata a mano, e ricreava ogni file cancellato — non per insistenza,
    perche' non aveva modo di distinguere.
    """
    if blocco is None:
        return "togliata_da_te" if consegnata else "mai_consegnata"
    if _conflitto(blocco, impronta_server):
        return "conflitto"
    base = blocco.get("impronta_base")
    if base and blocco.get("impronta_attuale") != base:
        # Cambiato solo da lui: il plugin lo lascia stare e non c'e' niente da
        # decidere. Si conta, perche' spiega perche' quella nota non si
        # aggiornera' piu' finche' resta cosi'.
        return "modificata_da_te"
    if base and base != impronta_server:
        # **Cambiato solo in Kolibre**, e nel file sta ancora quello che
        # Kolibre aveva scritto: il caso che si risolve da se', e lo risolve
        # il plugin riscrivendo quel blocco.
        return "da_portare"
    return "in_pari"


def _per_libro(note: Iterable[dict]) -> dict:
    """Le note raggruppate come il plugin raggruppa i file, con cosa serve."""
    fuori: dict = {}
    for n in note:
        chiave = chiave_del_libro(n.get("library"), n.get("book_title"))
        riga = fuori.setdefault(chiave, {
            "library": n.get("library"), "titolo": n.get("book_title"),
            "autore": n.get("book_author"),
            "calibre_book_id": n.get("calibre_book_id"),
            "note": {}, "righe": {}, "percorso": None,
        })
        if n.get("id_durevole"):
            riga["note"][n["id_durevole"]] = impronta_del_brano(n.get("text"))
            riga["righe"][n["id_durevole"]] = n
    return fuori


def stato_dei_libri(note: Iterable[dict], blocchi: Iterable[dict],
                    bloccati: Iterable[tuple] = (),
                    da_rifare: Iterable[tuple] = (),
                    scelte: Optional[dict] = None,
                    consegnate: Optional[set] = None) -> list:
    """
    Un libro per riga, col suo stato.

    `note` sono le evidenziazioni che il server ha (come le manda
    l'esportazione: `id_durevole`, `library`, `book_title`, `text`).
    `blocchi` e' la fotografia del vault. `bloccati` sono le chiavi dei libri
    che Paolo ha deciso di non mandare, `da_rifare` quelle dei libri di cui ha
    chiesto il rifacimento, `scelte` le risposte ai conflitti (nome durevole
    -> "kolibre" o "mio").

    `consegnate` sono i nomi durevoli delle note che questo client ha **gia'
    ricevuto almeno una volta**: il registro delle consegne. Senza quello, una
    nota assente dal vault non si puo' distinguere da una che Paolo ha
    togliato — vedi `stato_di_una_nota`.

    **Le due istruzioni sono cose che il plugin non ha ancora eseguito**, e
    cambiano lo stato in `in_attesa`: la decisione c'e', e chiederla di nuovo
    sarebbe un difetto. Il server non puo' scrivere nel vault, quindi fra la
    decisione e il suo effetto passa il tempo di una sincronizzazione.

    L'uscita e' ordinata **per urgenza** e, a pari stato, per titolo: e' la
    pagina che Paolo ha scelto, dove in testa sta solo quello che ha bisogno
    di lui.
    """
    insieme_bloccati = {chiave_del_libro(*b) for b in bloccati}
    insieme_da_rifare = {chiave_del_libro(*b) for b in da_rifare}
    scelte = scelte or {}
    consegnate = consegnate or set()

    per_libro = _per_libro(note)

    # La fotografia si incolla sulle note per identita' durevole, non per
    # posizione nel file: un blocco spostato a mano da Paolo resta lo stesso
    # blocco.
    blocchi_per_nome = {b["id_durevole"]: b for b in blocchi if b.get("id_durevole")}
    for riga in per_libro.values():
        for nome in riga["note"]:
            b = blocchi_per_nome.get(nome)
            if b and b.get("percorso"):
                riga["percorso"] = b["percorso"]
                break

    fuori = []
    for chiave, riga in per_libro.items():
        conti = {stato: 0 for stato in STATI_DI_UNA_NOTA}
        conflitti = []
        for nome, impronta_server in riga["note"].items():
            b = blocchi_per_nome.get(nome)
            stato_nota = stato_di_una_nota(b, impronta_server, nome in consegnate)
            conti[stato_nota] += 1
            if stato_nota == "conflitto":
                conflitti.append({
                    "id_durevole": nome,
                    "nel_vault": b.get("testo_attuale"),
                    "nel_server": riga["righe"][nome].get("text"),
                    "link": riga["righe"][nome].get("link"),
                    "impronta_nel_vault": b.get("impronta_attuale"),
                    "impronta_base": b.get("impronta_base"),
                    # La risposta gia' data, se c'e'. La pagina la mostra
                    # invece di richiedere la decisione.
                    "scelta": scelte.get(nome),
                })

        nel_vault = sum(conti[s] for s in ("conflitto", "da_portare",
                                           "modificata_da_te", "in_pari"))
        da_decidere = [c for c in conflitti if not c["scelta"]]

        if chiave in insieme_bloccati:
            stato = "bloccato"
        elif chiave in insieme_da_rifare:
            # Rifare il file da zero risolve tutto il resto, conflitti
            # compresi: il file viene riscritto dalle note del server.
            stato = "in_attesa"
        elif da_decidere:
            stato = "conflitto"
        elif conflitti:
            stato = "in_attesa"
        elif not nel_vault:
            # Niente nel vault. **Le due ragioni sono diverse**, e il
            # registro delle consegne le distingue: un file che non c'e' mai
            # stato nascera' al prossimo giro, uno che Paolo ha cancellato
            # resta cancellato. Se fra le note ce n'e' almeno una mai
            # consegnata il file nascera' comunque — con dentro solo quella,
            # per sua scelta del 06/11/2026.
            stato = "non_creato" if conti["mai_consegnata"] else "cancellato_da_te"
        elif conti["mai_consegnata"] or conti["da_portare"]:
            stato = "non_aggiornato"
        else:
            # Le note togliate a mano non contano come lavoro da fare: e'
            # esattamente quello che vuol dire averle togliate.
            stato = "in_pari"

        fuori.append({
            "library": riga["library"], "titolo": riga["titolo"],
            "autore": riga["autore"],
            "calibre_book_id": riga["calibre_book_id"],
            "percorso": riga["percorso"],
            "stato": stato,
            "note_totali": len(riga["note"]),
            "nel_vault": nel_vault,
            #: Mai arrivate nel vault: il plugin le scrivera'.
            "mai_consegnate": conti["mai_consegnata"],
            #: C'erano e le hai togliate: il plugin le lascia in pace.
            "togliate_da_te": conti["togliata_da_te"],
            #: Cambiate in Kolibre e non nel vault: le riporta il plugin, da
            #: se', senza che nessuno debba decidere niente.
            "da_portare": conti["da_portare"],
            "modificate_da_te": conti["modificata_da_te"],
            "conflitti": conflitti,
            "da_decidere": len(da_decidere),
            "da_rifare": chiave in insieme_da_rifare,
        })

    fuori.sort(key=lambda r: (ORDINE_DEGLI_STATI.index(r["stato"]), (r["titolo"] or "").lower()))
    return fuori


def riassunto(libri: Iterable[dict]) -> dict:
    """I conti che la pagina mostra in testa, piu' quelli dei gruppi chiusi."""
    libri = list(libri)
    per_stato = {s: 0 for s in ORDINE_DEGLI_STATI}
    for r in libri:
        per_stato[r["stato"]] = per_stato.get(r["stato"], 0) + 1
    # **`cancellato_da_te` e `bloccato` non sono cose da guardare**: sono
    # decisioni di Paolo da ricordare. Metterle qui vorrebbe dire chiedergli
    # due volte la stessa cosa.
    da_guardare = (per_stato["conflitto"] + per_stato["non_creato"]
                   + per_stato["non_aggiornato"])
    return {
        "libri": len(libri),
        "da_guardare": da_guardare,
        "per_stato": per_stato,
        "note_totali": sum(r["note_totali"] for r in libri),
        "note_nel_vault": sum(r["nel_vault"] for r in libri),
        "conflitti": sum(len(r["conflitti"]) for r in libri),
        "da_decidere": sum(r["da_decidere"] for r in libri),
        "mai_consegnate": sum(r["mai_consegnate"] for r in libri),
        "togliate_da_te": sum(r["togliate_da_te"] for r in libri),
        "da_portare": sum(r["da_portare"] for r in libri),
        "modificate_da_te": sum(r["modificate_da_te"] for r in libri),
        # Le istruzioni che il plugin non ha ancora eseguito: i libri da
        # rifare, piu' i conflitti con la risposta gia' data. La pagina le
        # mostra come «in attesa che il plugin passi», non come cose da fare.
        "istruzioni_in_attesa": (
            sum(1 for r in libri if r["da_rifare"])
            + sum(len(r["conflitti"]) - r["da_decidere"] for r in libri)
        ),
    }


def note_di_un_libro(note: Iterable[dict], blocchi: Iterable[dict],
                     consegnate: Optional[set] = None,
                     scelte: Optional[dict] = None) -> list:
    """
    Una riga per evidenziazione: e' quello che mostra la pagina di un libro.

    Qui non si riassume niente — ogni nota dice **il suo** stato, il brano
    come sta in Kolibre e, quando le due versioni divergono, anche come sta
    nel vault. E' la vista in cui si guardano le note «una per una», che Paolo
    ha scelto fra le tre azioni il 05/11/2026.

    L'ordine e' quello del libro (pagina, poi capitolo): e' come le ha lette,
    e cercare una nota per pagina e' l'unico modo naturale di cercarla. Non
    per urgenza, perche' qui il contesto e' il libro e non la lista delle
    cose da fare.
    """
    consegnate = consegnate or set()
    scelte = scelte or {}
    blocchi_per_nome = {b["id_durevole"]: b for b in blocchi if b.get("id_durevole")}

    fuori = []
    for n in note:
        nome = n.get("id_durevole")
        if not nome:
            continue
        b = blocchi_per_nome.get(nome)
        impronta_server = impronta_del_brano(n.get("text"))
        stato = stato_di_una_nota(b, impronta_server, nome in consegnate)
        fuori.append({
            "id_durevole": nome,
            "stato": stato,
            "testo": n.get("text"),
            "nota": n.get("note"),
            "page": n.get("page"),
            "chapter_path": n.get("chapter_path") or [],
            "link": n.get("link"),
            "percorso": (b or {}).get("percorso"),
            # Il brano come sta nel file, **solo quando e' diverso**: il
            # plugin lo manda solo in quel caso, e mostrarlo sempre vorrebbe
            # dire ripetere lo stesso testo due volte per mille note.
            "nel_vault": (b or {}).get("testo_attuale"),
            "scelta": scelte.get(nome),
        })
    fuori.sort(key=lambda r: (r["page"] if r["page"] is not None else float("inf"),
                              " ▸ ".join(r["chapter_path"])))
    return fuori
