"""
Il percorso del capitolo di un'annotazione, come va scritto in una nota.

**Perche' sta qui e non nel plugin.** Il server conserva il capitolo come una
stringa sola — `"1. La Rivoluzione russa ▸ VIII."` — coi livelli separati da
` ▸ `. Chi deve SCRIVERE la nota, pero', non vuole una stringa: vuole i
livelli separati, perche' diventano titoli annidati di profondita' diversa.

**Quella stringa la scrive Kolibre, non il lettore.** E' importante sapere di
chi e' la convenzione, perche' decide se qui si sta decodificando qualcosa di
proprio o si sta indovinando il formato di qualcun altro. KOReader, di suo,
nelle annotazioni mette **solo il titolo del capitolo piu' interno** («III»):
l'antenatura completa non la manda. La compone Kolibre, in due posti suoi —
`position_converter/chapter_resolver.py` quando arriva una nota da un lettore
(apre l'EPUB e legge il suo indice; il titolo che il lettore ha mandato gli
serve solo da ripiego per i formati che non sa aprire) e
`pages/Reader/EpubHelpers.ts` quando si evidenzia nel lettore web.

Esiste anche una patch della comunita' di KOReader
(github.com/koreader/koreader/issues/12480) che fa mandare al lettore la
sequenza intera, con lo stesso separatore, e Paolo ce l'ha installata da
prima di avere Kolibre. **Ma non e' una cosa su cui contare**: e' una patch
sua, non KOReader normale, e lui stesso la segnala difettosa. Quello che
arriva da un lettore senza quella patch e' un titolo solo — che qui diventa
un percorso di un livello, cioe' esattamente quello che e'. Niente di questo
modulo si aspetta ` ▸ ` dal lettore.

Quel passaggio — dalla stringa ai livelli — il plugin Obsidian lo faceva da
se', in un centinaio di righe di JavaScript, e il commento che le spiegava
diceva di essere un port fedele di `ReaderView.vue::chapterPathForCfi`: un
file del **vecchio frontend Vue**, che non esiste piu' da mesi. Era logica
scritta due volte e provata zero: nel plugin Obsidian non c'e' modo di
eseguire una prova, e infatti non ce n'era nessuna. Spostarla qui non e' solo
alleggerire il client — e' il solo modo di poterla provare (vedi
`prove/capitoli_delle_note.py`).

Le due cose che fa, e che non sono ovvie:

1. **Toglie il titolo del libro** quando l'indice lo mette come radice. Molti
   EPUB hanno il titolo come primo nodo dell'indice: lasciandolo, ogni nota
   di ogni capitolo finirebbe sotto un titolo di primo livello che ripete il
   nome del libro — e la nota ce l'ha gia' scritto in testa.

2. **Fa eredi' gli antenati** a un percorso "nudo", cioe' di un livello solo.
   Serve perche' gli EPUB veri non sono annidati in modo coerente:
   verificato su un libro reale (*La Rivoluzione russa* di Victor Serge), i
   sottocapitoli in numeri romani stanno sotto la loro parte per ALCUNE voci
   dell'indice e non per altre, quindi la stessa sorgente riporta
   `"1. La Rivoluzione russa ▸ VIII."` per una nota e un nudo `"VIII."` per
   quella accanto. Senza l'eredita' il nudo diventerebbe un capitolo di
   primo livello suo, slegato dalla parte a cui appartiene davvero.

   Ma un percorso nudo **non e' sempre** una foglia smarrita: sullo stesso
   libro, `"2. Trent'anni dopo la Rivoluzione russa"` compare nudo una volta
   — e' la PRIMA nota di quella parte, prima che un suo sottocapitolo abbia
   prodotto un percorso lungo — e farla ereditare la metterebbe sotto la
   parte 1. Quindi: un primo giro raccoglie ogni etichetta che altrove
   compare come **primo elemento di un percorso lungo**, e un nudo che sta in
   quell'insieme comincia sempre un contesto nuovo. E' una prova portata dai
   dati che quella etichetta e' un titolo di primo livello, non un indovinello
   sulla forma del testo.

L'eredita' e' una scansione sequenziale in ordine di pagina, e vale **dentro
un libro**: due libri diversi non si passano antenati. Per questo
`con_i_percorsi` raggruppa prima di risolvere, con la stessa chiave che usa
il plugin per decidere in quale nota finisce un'evidenziazione
(biblioteca + titolo) — altrimenti la prima nota nuda di un libro erediterebbe
la parte dell'ultimo libro guardato.
"""

import re
from typing import List, Optional

#: Lo stesso separatore che usano la patch di KOReader, il lettore web e
#: `chapter_resolver._toc_entries_with_paths`. Sta scritto in un posto solo
#: da questo lato: chi serve la risposta non lo compone a mano.
SEPARATORE = " ▸ "

_SOLO_LETTERE_E_NUMERI = re.compile(r"[^a-z0-9]")


def _nudo(s: str) -> str:
    return _SOLO_LETTERE_E_NUMERI.sub("", s.lower())


def livelli_del_capitolo(capitolo: Optional[str], titolo_libro: Optional[str]) -> List[str]:
    """
    `"Parte 1 ▸ Capitolo 2 ▸ Sezione"` -> `["Parte 1", "Capitolo 2", "Sezione"]`

    Niente capitolo -> elenco vuoto. Se il primo livello somiglia al titolo
    del libro, se ne va (vedi il punto 1 in testa al modulo). Il confronto e'
    "somiglia" e non "e' uguale" perche' il titolo nell'indice dell'EPUB e
    quello nei metadati di Calibre quasi mai coincidono alla lettera: uno dei
    due e' spesso troncato, o ha il sottotitolo e l'altro no.
    """
    if not capitolo:
        return []
    parti = [p.strip() for p in capitolo.split(SEPARATORE)]
    parti = [p for p in parti if p]
    if len(parti) > 1 and titolo_libro:
        primo = _nudo(parti[0])
        titolo = _nudo(titolo_libro)
        if primo == titolo or titolo.startswith(primo) or primo.startswith(titolo):
            parti.pop(0)
    return parti


def percorsi_di_un_libro(capitoli: List[Optional[str]], titolo_libro: Optional[str]) -> List[List[str]]:
    """
    Un percorso risolto per ogni capitolo, nello stesso ordine.

    `capitoli` deve essere **gia' in ordine di pagina**: il secondo giro e'
    una scansione sequenziale, non una ricerca. Chi non ha l'ordine giusto
    non ottiene un errore, ottiene eredita' sbagliate — per questo l'ordine
    lo mette `con_i_percorsi` e non chi chiama.
    """
    grezzi = [livelli_del_capitolo(c, titolo_libro) for c in capitoli]

    primi_livelli_veri = {p[0] for p in grezzi if len(p) > 1}

    corrente: List[str] = []
    risolti: List[List[str]] = []
    for percorso in grezzi:
        if len(percorso) > 1:
            corrente = percorso
        elif len(percorso) == 1:
            if not corrente or percorso[0] in primi_livelli_veri:
                # Non c'e' ancora niente da ereditare, oppure questa etichetta
                # e' confermata altrove come titolo di primo livello: non la si
                # infila sotto il capitolo che per caso era aperto.
                corrente = percorso
            else:
                # Foglia nuda con un'ascendenza gia' aperta: erediti ogni
                # livello sopra di se', sostituendo solo il piu' profondo.
                corrente = corrente[:-1] + percorso
        # Un percorso vuoto (nota senza capitolo) **lascia il contesto dov'e'**
        # invece di azzerarlo: una nota senza capitolo in mezzo a un capitolo
        # non deve sfrattare quel capitolo per la nota vera che viene dopo.
        risolti.append([] if not percorso else list(corrente))
    return risolti


def _pagina(riga: dict):
    # `page` puo' essere nullo (nota senza pagina) o zero (lo e' per le
    # orfane, che la pagina non ce l'hanno sempre): in entrambi i casi va in
    # fondo, come fa `(a.page || Infinity)` dal lato del plugin.
    return riga.get("page") or float("inf")


def con_i_percorsi(righe: List[dict]) -> List[dict]:
    """
    Le stesse righe esportate, ognuna con il suo `chapter_path`.

    L'ordine delle righe in uscita e' quello in entrata: chi legge la
    risposta raggruppa da se', e cambiargli l'ordine sotto i piedi non
    servirebbe a niente. Il raggruppamento per (biblioteca, titolo) e
    l'ordinamento per pagina servono solo a risolvere, e non si vedono fuori.
    """
    per_libro: dict = {}
    for indice, riga in enumerate(righe):
        chiave = (riga.get("library"), riga.get("book_title"))
        per_libro.setdefault(chiave, []).append(indice)

    percorsi: List[List[str]] = [[] for _ in righe]
    for (_biblioteca, titolo), indici in per_libro.items():
        # `sorted` e' stabile: a pari pagina resta l'ordine di partenza, come
        # il `.sort()` di JavaScript (stabile per specifica da ES2019).
        in_ordine = sorted(indici, key=lambda i: _pagina(righe[i]))
        risolti = percorsi_di_un_libro([righe[i].get("chapter") for i in in_ordine], titolo)
        for posto, indice in enumerate(in_ordine):
            percorsi[indice] = risolti[posto]

    return [{**riga, "chapter_path": percorsi[i]} for i, riga in enumerate(righe)]
