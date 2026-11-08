"""
L'inventario di un lettore: cosa c'e' davvero nella sua cartella dei libri, e
cosa il server riesce a riconoscere.

**Perche' esiste** (05/11/2026). Il server sapeva solo quello che *lui* aveva
consegnato e quello che il dispositivo non aveva saputo accoppiare. Dei file
che ci sono davvero la' sopra non sapeva niente, e per questo non poteva
accorgersi della cosa piu' banale: lo **stesso libro in due copie**. Il
difetto che le creava e' chiuso (plugin 0.12.0, il percorso di consegna non
ignora piu' il manifesto); questo modulo serve a vedere e pulire quelle che
ci sono.

**Tre lezioni misurate sul Kindle di Paolo, e ognuna e' una regola qui
dentro.**

1. **Il nome non accoppia niente.** Nel suo storico di lettura ci sono due
   file `Che fare_.epub`, uno sotto `Lenin` e uno sotto `Cernysevskij`: due
   libri diversi con lo stesso titolo, non un doppione. Qui non si guarda
   mai il nome: si guarda l'identita' del libro.

2. **L'impronta da sola non basta.** Su sette coppie di doppioni, in **sei**
   una delle due impronte non risolve affatto sul server — e quelle che
   risolvono, risolvono dallo *storico* delle impronte e non da quella viva.
   Per questo `raggruppa` accetta un risolutore che puo' dire «non lo so», e
   un file che non si riconosce **non diventa mai un candidato alla
   cancellazione**.

3. **«Tieni la piu' recente» e' la regola sbagliata.** In quattro coppie su
   sette la copia aperta piu' di recente e' quella con **meno** lettura — e
   «la piu' recente» e' proprio quella che il manifesto del dispositivo tiene
   in mano. La regola giusta e' «tieni quella su cui hai letto», e si misura
   da `percent_finished` e dalle annotazioni, non dalle date.

Il modulo non cancella niente e non parla con nessuno: prende righe, le
raggruppa, e dice cosa ha visto. Per questo si prova senza rete e senza
dispositivo (`prove/inventario_del_dispositivo.py`).
"""

import re
import unicodedata
from typing import Callable, Optional


def valore_di_lettura(riga: dict) -> tuple:
    """
    Quanto «vale» un file quando si deve scegliere quale copia tenere.
    Si confronta come una tupla: il primo criterio che li distingue vince.

    1. **L'impronta viva**, e viene prima di tutto perche' e' l'unica
       **prova**: quel file e' byte per byte identico a quello che il server
       ha adesso. Gli altri criteri sono indizi. Misurato sui venti gruppi
       veri del Kindle di Paolo: l'impronta viva e' **unica in tutti e
       venti**, mentre il nome del file non sapeva decidere in otto — e dove
       il nome decideva, non ha mai contraddetto l'impronta.
    2. **Le annotazioni**, che pesano piu' della percentuale: una percentuale
       si rifa' aprendo il libro e scorrendo, un'annotazione no.
    3. **La percentuale letta.**
    4. **La dimensione**, che e' l'indizio piu' debole e serve solo a non
       lasciare la scelta al caso.

    Senza il campo `impronta_viva` (chi passa righe che non lo portano) il
    primo criterio e' pari per tutti e decide la lettura, che e' il
    comportamento di prima.
    """
    return (
        1 if riga.get("impronta_viva") else 0,
        riga.get("annotazioni") or 0,
        riga.get("percent_finished") or 0.0,
        riga.get("size_bytes") or 0,
    )


def _nudo(testo: Optional[str]) -> str:
    """Un titolo ridotto alle sue lettere: senza accenti, senza punteggiatura,
    senza spazi. Serve a confrontare un nome di file con un titolo quando i
    due non si scrivono allo stesso modo — e sul Kindle non si scrivono allo
    stesso modo quasi mai."""
    testo = "".join(
        c for c in unicodedata.normalize("NFKD", (testo or "").lower())
        if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "", testo)


def il_nome_dice_il_libro(nome_file: str, titoli: list) -> bool:
    """
    Il nome di questo file corrisponde a uno dei titoli di quel libro?

    **Perche' questo controllo esiste, e non e' pedanteria.** Il 05/11/2026
    l'inventario del Kindle di Paolo ha trovato venti libri «in doppia
    copia». Diciannove lo erano. Il ventesimo era questo:

        libro 671 «Dialoghi con Leuco»
          casa in collina, La.epub     160512 byte
          Dialoghi con Leuco.epub       91601 byte

    **Due libri diversi.** «La casa in collina» e' in biblioteca per conto
    suo, e quel file e' il suo. Il server li aveva messi insieme perche' ha
    un'impronta **archiviata** che lega il primo file al libro 671: cioe'
    quel file *stava* nello slot del 671 in un momento passato, prima che
    quel libro cambiasse file o metadati. **Un'impronta archiviata dice
    «questo file ERA di questo libro», che non e' «questo file E' di questo
    libro».** Senza questo controllo si sarebbe cancellata la copia vera del
    671 tenendo un libro che non c'entra.

    Si confrontano il **titolo** e il **titolo per ordinamento** (il plugin
    ha usato prima l'uno e poi l'altro per dare il nome ai file), ridotti
    alle sole lettere: sul Kindle gli accenti sono andati perduti e la
    punteggiatura cambia. E si accetta anche l'**anagramma**, perche'
    `Commedia umana, La` e `La Commedia umana` sono le stesse lettere in
    ordine diverso — che e' esattamente la differenza fra le due convenzioni.

    Provato sui venti gruppi veri: **diciannove sì, uno no**, e il no e'
    Pavese. Niente soglie, niente caricamenti, niente impronta di contenuto.
    """
    nome = _nudo(nome_file.rsplit("/", 1)[-1].rsplit(".", 1)[0])
    for titolo in titoli:
        atteso = _nudo(titolo)
        if not atteso:
            continue
        if nome == atteso or sorted(nome) == sorted(atteso):
            return True
    return False


def raggruppa(righe: list, identita: Callable[[dict], Optional[tuple]],
              conferma: Optional[Callable[[dict, tuple], bool]] = None) -> dict:
    """
    Divide i file dell'inventario in quattro gruppi.

    `identita` riceve una riga e torna la terna (biblioteca, libro, formato)
    che il server riconosce, oppure `None` se non lo sa. Si passa come
    argomento e non si interroga il database qui dentro: e' quello che rende
    provabile il raggruppamento.

    Torna:

    * `doppioni`  — un elenco di gruppi, uno per libro presente **piu' di una
      volta**. Ogni gruppo dice quale tenere e quali sono le altre, e
      l'ordine non e' casuale: la prima e' quella su cui si e' letto di piu'.
    * `singoli`   — i file riconosciuti e presenti una volta sola: niente da
      fare.
    * `sconosciuti` — i file la cui identita' non si riconosce. **Non sono
      candidati alla cancellazione**: su uno di questi, sul Kindle di Paolo,
      c'erano cinquantasei ore di lettura.
    * `da_salvare` — i file sconosciuti che portano annotazioni. Sono quelli
      da spingere al server **prima** di toccare qualunque cosa, perche' le
      loro note vivono solo la'.
    * `da_guardare` — gruppi in cui **almeno un file non sembra quel libro**.
      Non sono proposte: sono domande. `conferma` e' quello che lo decide
      (vedi `il_nome_dice_il_libro`), e senza `conferma` questo elenco e'
      sempre vuoto — chi non lo passa ottiene il comportamento di prima.
    """
    per_libro: dict = {}
    sconosciuti = []
    for riga in righe:
        chiave = identita(riga)
        if chiave is None:
            sconosciuti.append(riga)
            continue
        per_libro.setdefault(chiave, []).append(riga)

    doppioni, singoli, da_guardare = [], [], []
    for chiave, gruppo in sorted(per_libro.items(), key=lambda v: str(v[0])):
        if len(gruppo) == 1:
            singoli.append(gruppo[0])
            continue
        # **Un gruppo in cui un file non sembra quel libro non e' una
        # proposta: e' una domanda.** Il server puo' mettere insieme due file
        # diversi quando uno dei due *stava* nello slot di quel libro in
        # passato, e li' cancellare vorrebbe dire buttare via il libro
        # giusto. Succede: uno dei venti gruppi veri del Kindle di Paolo era
        # cosi'.
        if conferma is not None and not all(conferma(r, chiave) for r in gruppo):
            da_guardare.append({
                "library": chiave[0],
                "calibre_book_id": chiave[1],
                "format": chiave[2],
                "file": sorted(gruppo, key=lambda r: r["local_path"]),
                "sospetti": [r["local_path"] for r in gruppo if not conferma(r, chiave)],
            })
            continue
        ordinate = sorted(gruppo, key=valore_di_lettura, reverse=True)
        doppioni.append({
            "library": chiave[0],
            "calibre_book_id": chiave[1],
            "format": chiave[2],
            "tenere": ordinate[0],
            "scartare": ordinate[1:],
            # **Il numero che rende la decisione leggibile.** Se una copia ha
            # tutta la lettura e l'altra niente, la scelta e' ovvia; se sono
            # vicine, non lo e', e chi guarda deve poterlo vedere prima di
            # confermare. Sul Kindle di Paolo una coppia era 140 contro 36
            # minuti: quella va guardata, non applicata.
            "lettura_tenuta": valore_di_lettura(ordinate[0]),
            "lettura_scartata": max(
                (valore_di_lettura(r) for r in ordinate[1:]), default=(0, 0, 0.0, 0)),
        })

    return {
        "doppioni": doppioni,
        "singoli": singoli,
        "sconosciuti": sconosciuti,
        "da_salvare": [r for r in sconosciuti if (r.get("annotazioni") or 0) > 0],
        "da_guardare": da_guardare,
    }


def riassunto(gruppi: dict, totale: int) -> dict:
    """I numeri che il dispositivo mostra appena ha finito di camminare."""
    da_scartare = sum(len(g["scartare"]) for g in gruppi["doppioni"])
    return {
        "file_letti": totale,
        "riconosciuti": len(gruppi["singoli"]) + sum(
            1 + len(g["scartare"]) for g in gruppi["doppioni"]),
        "libri_in_piu_copie": len(gruppi["doppioni"]),
        "copie_in_eccesso": da_scartare,
        "sconosciuti": len(gruppi["sconosciuti"]),
        "da_salvare": len(gruppi["da_salvare"]),
        #: Gruppi in cui un file non sembra quel libro. **Non si cancellano.**
        "da_guardare": len(gruppi.get("da_guardare") or []),
    }
