"""
La forma delle risposte dell'API, per chi deve scriverci un client.

**Perche' questo file esiste** (04/11/2026). Su 248 operazioni dell'API, 236
non dichiaravano la forma della loro risposta: nello schema generato
risultavano `"application/json": unknown`. Per il browser e' un fastidio — al
prezzo di 142 asserzioni scritte a mano. Per un client nativo e' il muro: da
uno schema che dice `unknown` non si genera niente, e ogni campo va scoperto
chiamando e guardando. Il conto lo tiene `prove/forma_delle_risposte.py`, e
ogni lotto di modelli scritti qui lo abbassa.

**Perche' `extra="allow"` su (quasi) tutti.** Un `response_model` rigido non
documenta: **filtra**. Un campo che il modello non dichiara viene **buttato
via dalla risposta**, in silenzio — misurato, non temuto. Su un'API viva, e
con duecento forme da scrivere a mano, quella e' la via sicura per perdere
dati senza accorgersene. Con `extra="allow"` il modello dice quello che sa e
lascia passare il resto: lo schema diventa «questi campi ci sono di sicuro, ce
ne possono essere altri», che e' la verita' ed e' comunque infinitamente piu'
di `unknown`.

**«Puo' essere nullo» e «puo' non esserci» sono due cose diverse.** Un
campo scritto `Optional[str] = None` genera `campo?: string | null`: forse
non c'e', e se c'e' puo' essere nullo. Un campo scritto `Optional[str]`
**senza difetto** genera `campo: string | null`: c'e' sempre, e il valore
puo' essere nullo. La seconda e' quasi sempre la verita', perche' questi
endpoint costruiscono un dizionario letterale dove la chiave c'e' comunque —
e dirla costa a chi legge un controllo in meno su ogni campo. Il difetto
`= None` si mette solo dove il campo **davvero** a volte non compare: le
forme alternative dello stesso indirizzo (`DestinazioniIndice`,
`PermessoScritto`, `VoceIndice.valid`).

**Perche' nessun campo e' obbligatorio per caso.** Un campo dichiarato
obbligatorio che a volte non c'e' non e' un errore di documentazione: fa
**fallire la risposta** con un 500. Ogni campo qui dentro e' stato guardato
nel codice che lo produce, uno per uno. Dove non si e' potuto verificare che
ci sia sempre, e' facoltativo.
"""

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class Permissivo(BaseModel):
    """La base di tutti: dichiara quello che sa, non butta via il resto."""
    model_config = ConfigDict(extra="allow")


class Esito(Permissivo):
    """
    `{"status": "ok"}` — la risposta piu' comune del progetto.

    Molti endpoint ci aggiungono qualcosa (quanti elementi, un id nuovo):
    `extra="allow"` lo lascia passare, e chi ha bisogno di quel campo
    dichiarato si fa un modello suo che eredita da qui.
    """
    status: str


# ── Indice full-text ─────────────────────────────────────────────────────

class FulltextImpostazioni(Permissivo):
    enabled: bool


class FulltextAvanzamento(Permissivo):
    """
    Come va l'indicizzazione, mentre gira.

    La forma l'ho ricavata dal codice che la scrive, e in quel confronto e'
    uscito un campo che nessun client conosceva: `stopped_by_limit`. Il
    frontend aveva un tipo scritto a mano con tre campi su quattro, e il
    quarto — quello che dice «mi sono fermata perche' l'indice ha raggiunto
    il tetto» — c'era nella risposta e TypeScript lo avrebbe rifiutato. E'
    il genere di cosa che `unknown` nasconde: non si scopre un campo che non
    si sa di poter cercare.
    """
    done: int
    total: int
    running: bool
    #: C'e' solo quando l'indicizzazione e' finita.
    stopped_by_limit: Optional[bool] = None


class FulltextStato(Permissivo):
    enabled: bool
    indexed: int
    total: int
    #: Valorizzato mentre l'indicizzazione gira, `None` quando e' ferma.
    progress: Optional[FulltextAvanzamento] = None
    #: L'indice tiene il testo di ogni libro e cresce senza un limite
    #: naturale (~1,6 MB a libro): quanto pesa e quanto puo' pesare sono due
    #: numeri che vanno detti, non scoperti quando il disco e' pieno.
    size_bytes: int
    limit_gb: float
    limit_reached: bool


class FulltextRisultato(Permissivo):
    id: int
    title: str
    author: str
    format: str
    #: Sempre valorizzato: senza copertina sul disco risponde quella
    #: costruita da titolo e autore.
    cover_url: str
    #: Il brano trovato, con `<b>` attorno alle parole cercate.
    snippet_html: str


class FulltextRicerca(Permissivo):
    results: list[FulltextRisultato]


# ── Colonne personalizzate di Calibre ────────────────────────────────────

class ColonnaPersonalizzata(Permissivo):
    id: int
    #: L'etichetta con cui la colonna vive nei metadati: `#letto`, `#pagine`.
    label: str
    #: Il nome che si legge nell'interfaccia.
    name: str
    #: `bool`, `int`, `float`, `text`, `enumeration`, `datetime`, `comments`…
    datatype: str
    #: Le opzioni di visualizzazione di Calibre, gia' lette dal JSON.
    display: dict


class ColonnaCreata(Esito):
    id: int


# ── Preferenze della persona ─────────────────────────────────────────────

class PreferenzeDellaPersona(Permissivo):
    #: `None` vuol dire **non ha scelto**, non «il difetto»: vedi
    #: `services/preferenze_utente.py`.
    lingua: Optional[str] = None


# ── Biblioteche ──────────────────────────────────────────────────────────

class Biblioteca(Permissivo):
    """
    Una biblioteca come la vede **chi sta guardando**.

    Tre campi non descrivono la biblioteca ma il permesso di chi chiede
    (`canEdit`, `canShare`, `canDelete`): servono a nascondere i comandi
    invece di offrirli e poi rispondere 403. Un client che li ignora
    funziona, ma offre bottoni che non funzionano.
    """
    id: int
    name: str
    folder_name: str
    path: str
    #: `library` per la prima dell'ordine, `archive` per le altre. L'ordine
    #: dell'elenco **e'** l'ordine di priorita' della persona.
    icon: str
    #: `None` se la riga di registro non ha un proprietario.
    owner: Optional[str]
    visibleUsers: list[str]
    canEdit: bool
    canShare: bool
    canDelete: bool
    fulltextEnabled: bool
    #: Dai conteggi su metadata.db (`_library_stats`).
    books_count: int
    authors_count: int
    size_bytes: int


class BibliotecaNelCestino(Permissivo):
    #: `{folder_name}_{timestamp}`, il nome della cartella nel cestino: e'
    #: anche l'identificatore da passare a restore/purge.
    id: str
    folder_name: str
    #: `None` se il nome della cartella non porta un timestamp leggibile.
    deleted_at: Optional[str]
    size_bytes: int


class CestinoBiblioteche(Permissivo):
    items: list[BibliotecaNelCestino]


class BibliotecaRipristinata(Esito):
    folder_name: str


class LibroFuoriPosto(Permissivo):
    """Un libro che non sta dove Calibre lo metterebbe."""
    id: int
    title: str
    author: str
    path: str
    new_path: str
    rename_files: bool
    reason: str
    #: La cartella non esiste: non si puo' sistemare. E' un problema diverso
    #: (file mancanti) e viene detto invece di sparire dal conteggio.
    missing: bool


class PercorsiFuoriPosto(Permissivo):
    """
    Quanti e quali. `total/movable/missing` sono i conti **veri**; i due
    `sample` sono tagliati a `limit` perche' una pagina che ne mostra una
    manciata non ha bisogno di diecimila righe.
    """
    total: int
    movable: int
    missing: int
    sample: list[LibroFuoriPosto]
    missing_sample: list[LibroFuoriPosto]


class RiparazioneFallita(Permissivo):
    id: int
    title: str
    error: str


class PercorsiRiparati(Esito):
    moved: int
    failed: list[RiparazioneFallita]
    #: Quanti restano: l'operazione e' idempotente e riprendibile, e questo
    #: numero e' quello che dice al chiamante se richiamarla.
    remaining: int


class Condivisione(Permissivo):
    user_id: int
    username: str
    can_edit: bool
    can_share: bool
    can_manage: bool


class PermessiBiblioteca(Permissivo):
    #: Il `folder_name`, non il nome mostrato.
    library: str
    owner: Optional[str]
    owner_id: Optional[int]
    #: Se chi chiede puo' cambiare questi permessi.
    puoi_gestire: bool
    condivisioni: list[Condivisione]


class PermessoScritto(Esito):
    """
    Risponde **due forme** dallo stesso endpoint: con `revoca` nel corpo
    torna `revocato: true` e nient'altro, altrimenti i tre permessi come
    sono rimasti. Per questo nessuno dei quattro e' obbligatorio.
    """
    revocato: Optional[bool] = None
    can_edit: Optional[bool] = None
    can_share: Optional[bool] = None
    can_manage: Optional[bool] = None


class ProprietarioScritto(Esito):
    owner: str


class BibliotecaRiscandita(Esito):
    imported: int


class ConteggiRicalcolati(Esito):
    updated: int


# ── Libri ────────────────────────────────────────────────────────────────

class LibroInElenco(Permissivo):
    """
    Un libro come arriva nell'elenco.

    **I campi delle colonne personalizzate non sono qui**, e non possono
    esserci: si chiamano `#etichetta` e dipendono dalla biblioteca, non dal
    programma. `extra="allow"` li lascia passare, e chi deve sapere quali
    esistono chiede `/api/kolibre/custom-columns`.

    Tre campi sono **tagliati o derivati**, non il valore grezzo di Calibre:
    `description` e' troncata a 400 caratteri (il testo intero si chiede a
    `GET /{id}/description`), e `pubdate`/`last_modified`/`date_added`
    portano solo il giorno.
    """
    id: int
    title: str
    #: Mai vuoto: senza autore risponde «Unknown Author».
    author: str
    series: Optional[str]
    series_index: Optional[float]
    tags: list[str]
    identifiers: dict[str, str]
    publisher: Optional[str]
    language: Optional[str]
    #: Troncata a 400 caratteri con «…» in coda.
    description: Optional[str]
    # Tutti e tre **obbligatori**, e non per ottimismo: `sort` e `uuid` li
    # riempie un trigger dello schema di Calibre (`books_insert_trg`), e
    # `author_sort` lo scrive sempre chi inserisce — Calibre o
    # `insert_book`. Contati sul server vero il 05/11/2026: su 8.204 libri
    # in cinque biblioteche, **zero** vuoti o nulli per tutti e tre.
    title_sort: str
    author_sort: str
    uuid: str
    #: Solo il giorno, `YYYY-MM-DD`.
    pubdate: Optional[str]
    last_modified: Optional[str]
    date_added: Optional[str]
    formats: list[str]
    #: Somma dei formati, **zero** e non `null` per un libro che non ne ha.
    size: int
    rating: Optional[float]
    #: **Sempre** valorizzato, anche senza copertina sul disco: in quel caso
    #: l'indirizzo risponde una copertina costruita da titolo e autore. Chi
    #: deve sapere se la copertina e' vera guarda `has_cover`.
    cover_url: str
    has_cover: bool
    # I due campi della biblioteca si chiamano `_library` e `_library_folder`
    # nella risposta, e qui devono passare per un alias: **un nome che
    # comincia con `_` non e' un campo per Pydantic, e' un attributo
    # privato**, e il modello lo toglie senza dire niente. Scritti nel modo
    # ovvio, questi due sparivano dallo schema — che e' lo stesso difetto
    # che tutto questo file esiste per chiudere, in piccolo.
    #
    #: Il nome **mostrato** della biblioteca.
    biblioteca_mostrata: Optional[str] = Field(alias="_library")
    #: La **cartella**. Serve a ogni azione sul libro (scaricare, mandare a
    #: un lettore, copiare): senza, il client deve cercarla al contrario dal
    #: nome mostrato, e quel giro fallisce in silenzio quando il nome e'
    #: quello di ripiego derivato dalla cartella stessa.
    biblioteca_cartella: Optional[str] = Field(alias="_library_folder")


class PaginaDiLibri(Permissivo):
    """
    Una pagina sola. Arriva **solo** se la richiesta passa `limit`: senza,
    l'endpoint risponde l'elenco nudo (una lista, non questo oggetto). Due
    forme dallo stesso indirizzo, ed e' deliberato — vedi `list_books`.
    """
    items: list[LibroInElenco]
    total: int
    offset: int
    limit: int


class ValoreDiCampo(Permissivo):
    valore: str
    libri: int


class ValoriDeiCampi(Permissivo):
    """
    `{tags: [...], author: [...], "#letto": [...]}` — le chiavi sono quelle
    del Navigatore piu' una `#etichetta` per ogni colonna personalizzata,
    quindi dipendono dalla biblioteca e non si possono elencare qui.
    Ogni elenco e' tagliato ai valori piu' frequenti.
    """
    campi: dict[str, list[ValoreDiCampo]]


class ModoPaginazione(Permissivo):
    """
    Se questo elenco va servito a pagine, e con che misura.

    E' l'impostazione (`ImpostazionePaginazione`) piu' il totale degli
    elementi di **questo** elenco piu' il verdetto che ne esce. La stessa
    forma la rispondono due indirizzi — i libri di una biblioteca e gli
    arretrati — perche' e' la stessa domanda su due elenchi diversi.
    """
    total: int
    paginated: bool
    page_size: int
    # Era dichiarato `str`. E' lo **stesso valore** che risponde
    # `/settings/library-pagination`, dove ogni scrittura lo riporta a una
    # delle tre parole: lo stesso dato non puo' avere due tipi secondo
    # l'indirizzo da cui esce, che e' il difetto trovato su `has_cover` il
    # 05/11/2026.
    mode: Literal["auto", "always", "never"]
    threshold: int


class InfoConversione(Permissivo):
    #: Se il convertitore di Calibre c'e' su questo server.
    available: bool
    path: Optional[str]
    version: Optional[str]
    supported_targets: list[str]


class AvanzamentoDiLettura(Permissivo):
    calibre_book_id: int
    #: **Obbligatoria**: la colonna e' `nullable=False`. E' gia' la posizione
    #: «vincente» fra tutti i dispositivi (l'ultimo che ha scritto): non c'e'
    #: niente da combinare lato client.
    percentage: float
    device_name: Optional[str]
    #: ISO con il fuso dichiarato (`+00:00`) — vedi `app/istanti.py`.
    updated_at: Optional[str]


class PosizioneDiLettura(Permissivo):
    """
    Dove si era arrivati. Tutti i campi sono facoltativi perche' «non c'e'
    nessuna posizione» si risponde con tutti e quattro a `null`, non con un
    404.
    """
    percentage: Optional[float]
    #: Il CFI di epub.js — valorizzato **solo** se la posizione arriva dal
    #: lettore web. Da KOReader arriva un xpointer, che non e' un CFI e qui
    #: non compare.
    cfi: Optional[str]
    device_name: Optional[str]
    updated_at: Optional[str]


class PosizioneScritta(Esito):
    """
    `status` qui non e' sempre `ok`: vale `ignored` quando il server ha
    l'impostazione «non seguire la lettura dal web» attiva, e allora
    `reason` dice perche'. Un client che guarda solo il codice HTTP crede di
    aver salvato.
    """
    reason: Optional[str] = None


class LetturaGiornaliera(Permissivo):
    #: `YYYY-MM-DD`.
    date: str
    total_seconds: int


class StatisticheLibro(Permissivo):
    """
    Le letture di **questo** libro. Senza nessuna sessione risponde comunque
    (zeri e `null`), non un 404: le evidenziazioni possono esserci anche
    senza sessioni di lettura.
    """
    total_time_seconds: int
    total_sessions: int
    total_pages_read: int
    #: Quanta parte del libro — `None` se non si sa.
    fraction_read: Optional[float]
    chars_read: Optional[int]
    coverage: Optional[float]
    first_read: Optional[str]
    last_read: Optional[str]
    daily_sessions: list[LetturaGiornaliera]
    highlights_count: int


class DescrizioneLibro(Permissivo):
    """Il testo **intero**, non troncato come nell'elenco."""
    description: Optional[str]


class LibroAggiornato(Esito):
    pass


class LibriAggiornati(Esito):
    #: Quanti sono stati toccati davvero e quanti erano stati chiesti: i due
    #: numeri differiscono quando un id non esiste piu'.
    updated: int
    requested: int


class PagineRicalcolate(Esito):
    pages: int


class FonteInterrogata(Permissivo):
    """
    Com'e' andata **una** delle fonti. Serve a distinguere «questo libro non
    e' in nessun catalogo» da «una delle tre fonti oggi non risponde»: dai
    soli risultati le due situazioni sono identiche.
    """
    nome: str
    #: `ok`, `errore`, `quota`, `lenta`.
    stato: str
    dettaglio: Optional[str] = None


class CandidatoMetadati(Permissivo):
    source: str
    title: Optional[str] = None
    author: str
    #: Tenuto per i chiamanti vecchi: `identifiers` ha l'insieme completo.
    isbn: Optional[str] = None
    identifiers: dict[str, str]
    description: Optional[str] = None
    tags: list[str]
    publisher: Optional[str] = None
    language: Optional[str] = None
    pubdate: Optional[str] = None
    pubdate_year: Optional[int] = None
    cover_url: Optional[str] = None
    #: `opera` quando i valori sono dell'OPERA (Wikidata) e non
    #: dell'edizione posseduta.
    livello: Optional[str] = None


class MetadatiTrovati(Permissivo):
    candidates: list[CandidatoMetadati]
    fonti: list[FonteInterrogata]


class FormatoConvertito(Esito):
    """
    La forma JSON di `POST /{id}/convert` — quella con `add_as_format` vero.
    Con falso **lo stesso indirizzo manda il file**, e lo schema dichiara
    entrambi i tipi di contenuto.
    """
    format: str
    size: int


# ── Indice (TOC) ─────────────────────────────────────────────────────────

class VoceIndice(Permissivo):
    title: str
    #: Per un EPUB e' un href, per un PDF il numero di pagina come stringa.
    dest: str
    level: int
    #: Solo per i PDF: se la pagina di destinazione esiste davvero.
    valid: Optional[bool] = None


class IndiceLibro(Permissivo):
    #: `EPUB` o `PDF`.
    format: str
    entries: list[VoceIndice]


class FileDiDestinazione(Permissivo):
    href: str
    anchors: list[str]


class DestinazioniIndice(Permissivo):
    """
    Dove si puo' puntare, e **dipende dal formato**: per un EPUB arriva
    `files`, per un PDF `page_count`. Mai entrambi.
    """
    format: str
    files: Optional[list[FileDiDestinazione]] = None
    page_count: Optional[int] = None


class AncoraCreata(Permissivo):
    anchor_id: str


class IndiceSalvato(Esito):
    format: str


# ── Annotazioni ──────────────────────────────────────────────────────────
#
# L'elenco delle annotazioni mette in UNA lista due cose diverse: le
# evidenziazioni, che stanno su un libro della biblioteca, e le **orfane**,
# arrivate da un dispositivo per un file che non si e' riusciti ad
# accoppiare a nessun libro. Si distinguono per `is_orphan`, e qui sono due
# modelli con quel campo come discriminante: un client generato puo' quindi
# restringere da solo invece di provare ad accedere a campi che nell'altra
# forma non esistono.
#
# La differenza piu' insidiosa e' l'**`id`**: numero per un'evidenziazione,
# la stringa `"orphan-<n>"` per un'orfana. Un client che lo dichiara `int`
# si rompe sulla prima riga orfana, e nessuno glielo aveva mai detto.

class _EvidenziazioneComune(Permissivo):
    text: str
    #: Il commento di chi legge — stringa vuota, non `null`, se non c'e'.
    notes: str
    chapter: Optional[str]
    #: Zero quando il dispositivo non l'ha detta.
    page: int
    device_id: Optional[int]
    #: Il nome del dispositivo, se e' ancora registrato.
    device_name: Optional[str]
    #: Uno fra yellow, green, blue, pink, orange.
    color: Optional[str]
    #: Nel cestino: non cancellata, recuperabile.
    trashed: bool
    created_at: Optional[str]
    updated_at: Optional[str]
    book_title: Optional[str]
    book_author: Optional[str]


class Evidenziazione(_EvidenziazioneComune):
    """Un'evidenziazione su un libro della biblioteca."""
    id: int
    is_orphan: Literal[False]
    calibre_book_id: int
    library: str
    #: Il CFI di epub.js. Per un'evidenziazione arrivata da KOReader e'
    #: valorizzato solo se la conversione dall'xpointer e' riuscita —
    #: guarda `position_status`.
    cfi_start: Optional[str]
    cfi_end: Optional[str]
    #: `None` = conversione mai tentata (web e calibre hanno gia' un CFI
    #: vero); `exact`/`repaired` = i due CFI si possono usare; `failed` =
    #: tentata e non risolta, e **non si ritenta** da sola.
    position_status: Optional[str]
    #: `web` (lettore di Kolibre), `device` (sincronizzazione KOReader),
    #: `calibre` (visualizzatore di Calibre Desktop).
    source: Literal["web", "device", "calibre"]
    #: I formati del libro, per aprire il lettore giusto: le note non sanno
    #: da sole se stanno su un EPUB o su un PDF, e chi apre il lettore deve
    #: saperlo **prima** di chiamare `window.open`.
    book_formats: list[str]


class EvidenziazioneOrfana(_EvidenziazioneComune):
    """
    Un'evidenziazione arrivata da un dispositivo per un file che non si e'
    accoppiato a nessun libro. Non ha una biblioteca ne' un id di Calibre,
    e il titolo e' **indovinato dal nome del file**.
    """
    #: `"orphan-<n>"`, non un numero: e' il punto in cui un client che si
    #: fida di `int` si rompe.
    id: str
    is_orphan: Literal[True]
    # Questi cinque campi **ci sono sempre e valgono sempre `null`** — per
    # costruzione: un'orfana non ha un libro di Calibre, quindi non ha una
    # biblioteca, non ha un CFI e non ha uno stato di conversione della
    # posizione.
    #
    # Si potrebbe dichiararli di tipo `None`, che e' la verita' esatta, e
    # per un po' e' stato fatto. **Non si puo'**: il generatore di tipi che
    # usa il browser (openapi-typescript piu' openapi-fetch) **scarta** una
    # proprieta' il cui tipo e' soltanto `null`, e nell'unione con l'altra
    # forma quei cinque campi sparivano — rendendo l'unione illeggibile
    # proprio dove serve. Misurato, non temuto.
    #
    # Quindi il tipo e' quello dell'altra forma, nullabile, e la certezza
    # che qui sia sempre nullo sta scritta qui sopra: una cosa che il
    # sistema di tipi del client non sa portare si dice a parole.
    calibre_book_id: Optional[int]
    library: Optional[str]
    cfi_start: Optional[str]
    cfi_end: Optional[str]
    position_status: Optional[str]
    source: Literal["device"]
    #: Identita' stabile (dispositivo + percorso sul dispositivo) per
    #: raggrupparle, dato che biblioteca e id di Calibre sono sempre nulli.
    orphan_key: str


#: Quello che l'elenco delle annotazioni restituisce davvero: le due forme
#: mescolate, distinguibili da `is_orphan`.
Annotazione = Union[Evidenziazione, EvidenziazioneOrfana]


class AnnotazioneEsportata(Permissivo):
    """
    La forma che legge il plugin Obsidian — **diversa** da quella
    dell'elenco, e di proposito: qui titolo e autore non sono mai nulli
    (hanno un ripiego), `note` e' al singolare, e un'orfana porta
    «(non accoppiato)» nel titolo e `device:<id>` come biblioteca, perche'
    il plugin raggruppa per biblioteca piu' titolo e non deve mescolare i
    file non accoppiati di due dispositivi diversi.
    """
    #: Numero per un'evidenziazione, `"orphan-<n>"` per un'orfana.
    id: Union[int, str]
    book_title: str
    book_author: str
    library: str
    chapter: Optional[str]
    #: I livelli del capitolo, separati e risolti dal server: pronti da
    #: scrivere come titoli annidati. Vuoto se la nota non ha capitolo.
    #: `chapter` resta accanto, com'e' scritto nel database.
    chapter_path: list[str]
    #: Il nome che non cambia mai: e' quello che il plugin scrive nel
    #: marcatore dentro il file. `None` solo su una riga che la migrazione
    #: non ha ancora toccato.
    id_durevole: Optional[str]
    #: L'indirizzo condivisibile che riapre quel punto nel lettore. `None`
    #: per un'orfana (non ha un libro, e il link contiene il libro) o quando
    #: non si puo' comporre.
    link: Optional[str]
    page: Optional[int]
    text: str
    note: str
    color: Optional[str]
    created_at: Optional[str]
    source: str
    device_name: Optional[str]


class ConflittoDiAppunti(Permissivo):
    """
    Un brano cambiato **in tutte due le parti**: nel vault e in Kolibre.

    E' l'unico caso che il confronto a tre vie non sa risolvere da se', e per
    decisione di Paolo si risolve dalla pagina di Kolibre — quindi questa
    forma porta quello che serve a mostrare i due testi affiancati.
    """
    id_durevole: str
    #: Il brano come sta nel file di Obsidian. Il plugin lo manda **solo** per
    #: i blocchi divergenti, quindi qui c'e' quasi sempre; e' nullo se un
    #: plugin vecchio non l'ha mandato.
    nel_vault: Optional[str]
    #: Il brano come sta in Kolibre adesso. La pagina mostra i due affiancati:
    #: senza questo, chiedere quale dei due vince sarebbe chiedere alla cieca.
    nel_server: Optional[str]
    #: Il link che apre quella nota in Kolibre, per andare a vederla nel suo
    #: punto del libro prima di decidere.
    link: Optional[str]
    impronta_nel_vault: Optional[str]
    impronta_base: Optional[str]
    #: La risposta gia' data, se c'e': «kolibre» (vince il server) o «mio»
    #: (vince il vault). Nulla finche' Paolo non ha deciso. Quando c'e', la
    #: pagina non richiede la decisione: mostra che si aspetta il plugin.
    scelta: Optional[Literal["kolibre", "mio"]]


class LibroNegliAppunti(Permissivo):
    """Un libro e lo stato del suo file nel vault."""
    library: Optional[str]
    titolo: Optional[str]
    autore: Optional[str]
    #: Nullo per un file non ancora accoppiato, che non ha un libro.
    calibre_book_id: Optional[int]
    #: Il file nel vault, se se ne conosce almeno un blocco.
    percorso: Optional[str]
    #: `in_attesa` vuol dire «la decisione c'e', manca che il plugin passi»:
    #: il server non puo' scrivere nel vault, quindi fra la decisione e il suo
    #: effetto passa il tempo di una sincronizzazione.
    #:
    #: `cancellato_da_te` vuol dire che quel file c'era, l'hai cancellato, e
    #: **il plugin non lo ricrea**. Finche' non arriva una nota mai
    #: consegnata: allora il file nasce di nuovo, con dentro solo quella.
    stato: Literal["conflitto", "non_creato", "non_aggiornato", "in_attesa",
                   "in_pari", "cancellato_da_te", "bloccato"]
    note_totali: int
    nel_vault: int
    #: Mai arrivate nel vault: il plugin le scrivera' al prossimo giro.
    mai_consegnate: int
    #: C'erano e le hai togliate: il plugin le lascia in pace. Si contano
    #: perche' altrimenti sembrerebbero sparite.
    togliate_da_te: int
    conflitti: list[ConflittoDiAppunti]
    #: Quanti di quei conflitti aspettano ancora una risposta. Zero con dei
    #: conflitti in elenco vuol dire che sono tutti decisi.
    da_decidere: int
    #: Note cambiate in Kolibre mentre nel vault c'e' ancora quello che
    #: Kolibre aveva scritto. Non c'e' niente da decidere: il plugin le
    #: riporta da se' al prossimo giro. Si contano perche' senza di loro il
    #: libro risulterebbe «in pari» con un brano vecchio dentro il file.
    da_portare: int
    #: Vero se e' stato chiesto di rifare il file da zero e il plugin non e'
    #: ancora passato.
    da_rifare: bool
    #: Quante note Paolo ha ritoccato nel vault senza che Kolibre le abbia
    #: cambiate. Non c'e' niente da decidere — il plugin le lascia stare — ma
    #: spiega perche' quelle note non si aggiorneranno piu' finche' restano
    #: cosi'.
    modificate_da_te: int


class RiassuntoDegliAppunti(Permissivo):
    """I conti in testa alla pagina, e quelli dei gruppi chiusi."""
    libri: int
    #: Quanti libri hanno bisogno di Paolo: conflitti piu' non creati piu'
    #: non aggiornati. E' il numero che la pagina mostra per primo.
    da_guardare: int
    per_stato: dict[str, int]
    note_totali: int
    note_nel_vault: int
    conflitti: int
    da_decidere: int
    mai_consegnate: int
    togliate_da_te: int
    da_portare: int
    modificate_da_te: int
    #: Decisioni gia' prese che il plugin non ha ancora eseguito. La pagina le
    #: mostra come «in attesa», non come cose da fare.
    istruzioni_in_attesa: int


class ClienteDegliAppunti(Permissivo):
    """
    Chi ha raccontato, e quando. **La data non e' un ornamento**: il server
    non sa cosa c'e' nel vault adesso, sa cosa c'era quando il plugin
    gliel'ha detto.
    """
    #: Il numero con cui chiederlo (`/stato?cliente=`), quando un account ne
    #: ha piu' di uno.
    id: int
    #: Il nome del token d'applicazione con cui parla — «Obsidian sul
    #: portatile». Nullo per chi accede con nome e password.
    nome: Optional[str]
    visto_il: Optional[str]
    file_visti: int
    note_viste: int


class NotaNegliAppunti(Permissivo):
    """
    Una evidenziazione, e come sta nel vault. E' la riga della pagina di un
    libro — la vista in cui si guardano le note «una per una».
    """
    id_durevole: str
    #: Vedi `services/appunti_nel_vault.STATI_DI_UNA_NOTA`. La coppia che
    #: conta e' `mai_consegnata` / `togliata_da_te`: tutte due vogliono dire
    #: «non e' nel file», ma la prima chiede di essere scritta e la seconda
    #: chiede di essere lasciata in pace.
    stato: Literal["conflitto", "mai_consegnata", "da_portare",
                   "modificata_da_te", "togliata_da_te", "in_pari"]
    #: Il brano come sta in Kolibre.
    testo: Optional[str]
    #: La nota scritta sul lettore, se c'e'.
    nota: Optional[str]
    page: Optional[int]
    chapter_path: list[str]
    #: L'indirizzo che riapre questa nota in Kolibre.
    link: Optional[str]
    #: Il file del vault in cui sta, se ci sta.
    percorso: Optional[str]
    #: Il brano come sta nel vault, **solo quando e' diverso** da quello di
    #: Kolibre: il plugin lo manda solo in quel caso.
    nel_vault: Optional[str]
    #: La risposta gia' data al conflitto, se c'e'.
    scelta: Optional[Literal["kolibre", "mio"]]


class DettaglioDiUnLibro(Permissivo):
    """Un libro, e tutte le sue note una per una."""
    libro: LibroNegliAppunti
    note: list[NotaNegliAppunti]


class ClienteSeCeNe(Permissivo):
    """
    La risposta della rotta leggera che chiede la barra laterale: solo se un
    client esiste. Nullo vuol dire che nessuno ha mai raccontato niente, e
    allora la voce «Appunti» non si mostra affatto.
    """
    cliente: Optional[ClienteDegliAppunti]
    #: Tutti i client dell'account. La barra guarda solo se e' vuoto.
    clienti: list[ClienteDegliAppunti]


class StatoDegliAppunti(Permissivo):
    """
    Quello che legge la pagina Appunti.

    `cliente` e' nullo quando **nessun client ha mai raccontato niente**: e'
    la verita', e serve all'interfaccia per non mostrare affatto la voce nella
    barra, come fa Dispositivi per chi non ha lettori.
    """
    #: Il client che si sta guardando: quello chiesto con `?cliente=`, o
    #: quello che ha raccontato piu' di recente.
    cliente: Optional[ClienteDegliAppunti]
    #: Tutti i client dell'account: con due vault la pagina deve poter dire
    #: quale sta guardando, invece di nasconderne uno in silenzio.
    clienti: list[ClienteDegliAppunti]
    riassunto: RiassuntoDegliAppunti
    libri: list[LibroNegliAppunti]


class LibroDaNonMandare(Permissivo):
    """Un libro che il plugin deve smettere di aggiornare."""
    library: Optional[str]
    titolo: Optional[str]


class LibroDaRifare(Permissivo):
    """Un libro il cui file va riscritto da zero dalle note del server."""
    library: Optional[str]
    calibre_book_id: Optional[int]
    titolo: Optional[str]


class ConflittoDeciso(Permissivo):
    """Chi vince, per una nota: «kolibre» o «mio»."""
    id_durevole: str
    scelta: Literal["kolibre", "mio"]


class IstruzioniPerIlPlugin(Permissivo):
    """
    Cosa il plugin deve fare al prossimo giro.

    **Sono istruzioni e non azioni** perche' il server non puo' scrivere nel
    vault: il plugin sincronizza quando Paolo gliel'ha chiesto, per sua
    decisione. Ogni cosa scelta nella pagina passa da qui.

    Si spengono quando il plugin dice di averle eseguite, non quando gli
    vengono mandate: altrimenti un plugin interrotto a meta' consumerebbe
    una decisione senza averla eseguita.
    """
    non_mandare: list[LibroDaNonMandare]
    rifai: list[LibroDaRifare]
    conflitti: list[ConflittoDeciso]
    #: I nomi durevoli delle note che il plugin **non deve riscrivere**:
    #: consegnate una volta, e non piu' nel vault — cioe' togliate a mano.
    #:
    #: Una regola sola copre due casi: una nota togliata da dentro un file che
    #: resta non si rimette, e un file cancellato non si ricrea, perche'
    #: escludendo queste note non resta niente da scriverci. Se invece fra le
    #: note di quel libro ce n'e' una mai consegnata, il file nasce con dentro
    #: **solo quella**.
    non_rimettere: list[str]


class IstruzioniEseguite(Permissivo):
    """Quante istruzioni il racconto appena arrivato ha chiuso."""
    rifacimenti_spenti: int
    conflitti_chiusi: int


class InventarioDegliAppunti(Permissivo):
    """
    La risposta al racconto del plugin: quanto e' stato capito, come sta la
    situazione, e **cosa deve fare adesso**.

    Le istruzioni arrivano qui e non con una chiamata a parte perche' il
    plugin ha appena finito di parlare ed e' il momento in cui sta per
    lavorare: un secondo giro di rete per chiederle sarebbe sprecato.
    """
    ricevuti: int
    #: Blocchi che non si e' potuto registrare (senza nome durevole, o
    #: ripetuti). Si contano invece di essere ignorati in silenzio.
    scartati: int
    file: int
    #: Quante note questo racconto ha segnato come consegnate per la prima
    #: volta. Al primo racconto sono tutte: e' il registro che nasce.
    consegne_nuove: int
    eseguite: IstruzioniEseguite
    riassunto: RiassuntoDegliAppunti
    istruzioni: IstruzioniPerIlPlugin


class LinkRisolto(Permissivo):
    """
    A cosa corrisponde un indirizzo condivisibile, e cosa aprire.

    **Risponde anche quando la cosa non c'e' piu'**, e per questo
    `trovato` e `motivo` sono due campi e non un codice di errore: un link
    incollato in un appunto due anni prima merita una spiegazione e un
    ripiego, non una pagina bianca. `apri` e' l'indirizzo interno da aprire —
    quello vero se `trovato`, quello del ripiego altrimenti.
    """
    tipo: Literal["biblioteca", "libro", "nota", "autore"]
    trovato: bool
    #: L'indirizzo interno da aprire, o `None` se non c'e' niente da aprire.
    apri: Optional[str]
    #: Che cosa si apre al posto della cosa chiesta: `"libro"` o
    #: `"biblioteca"`. `None` quando `trovato`, o quando non c'e' ripiego.
    ripiego: Optional[str]
    #: Perche' non si e' trovato: `nota_sparita`, `libro_sparito`,
    #: `libro_ambiguo`, `biblioteca_sparita`, `biblioteca_ambigua`,
    #: `indirizzo_senza_libro`.
    motivo: Optional[str]
    biblioteca: Optional[str]
    calibre_book_id: Optional[int]
    titolo: Optional[str]
    nota_id: Optional[int]
    id_durevole: Optional[str]
    autore: Optional[str]


class LinkGenerato(Permissivo):
    """
    Un indirizzo condivisibile appena composto, in tre pezzi.

    `percorso` e' la parte che non cambia da un impianto all'altro
    (`/k/libreria/...`). `base` e' l'indirizzo di **questa** installazione, e
    lo ricava il server: da `PUBLIC_BASE_URL` se chi l'ha installata ne ha
    dichiarato uno, altrimenti dalle intestazioni di inoltro, altrimenti dal
    nome con cui la richiesta e' arrivata piu' la porta del frontend. Vedi
    `services/link_condivisibile.indirizzo_base`.

    `indirizzo` e' i due attaccati, ed e' quello che si incolla. Resta
    `None` nel caso in cui la base non si ricavi: meglio dare il solo
    percorso che un indirizzo inventato che non si apre.
    """
    percorso: str
    base: Optional[str]
    indirizzo: Optional[str]


class GruppoVedovo(Permissivo):
    """
    Annotazioni rimaste senza il loro libro: la riga di Calibre non c'e'
    piu'. Di che libro si trattasse non lo sa piu' nessuno — il titolo se
    n'e' andato con la riga — quindi restano i capitoli e qualche riga di
    testo per riconoscerlo a occhio.
    """
    library: str
    calibre_book_id: int
    count: int
    #: Al massimo sei.
    chapters: list[str]
    #: Al massimo tre, tagliate a 160 caratteri.
    samples: list[str]


class GruppiVedovi(Permissivo):
    groups: list[GruppoVedovo]


class CandidatoVedovo(Permissivo):
    calibre_book_id: int
    library: str
    title: Optional[str]
    #: La forma d'ordinamento («Cognome, Nome»): per riconoscere un libro in
    #: un elenco di proposte basta e avanza.
    authors: Optional[str]
    #: Quante delle frasi cercate si sono ritrovate in questo libro.
    matches: int


class ProposteVedove(Permissivo):
    """
    Dove potrebbero essere finite. Si cercano alla lettera alcune frasi
    delle annotazioni nell'indice full-text: `searched` dice quante frasi
    si e' riuscito a cercare — zero vuol dire che non c'era niente da
    cercare o che l'indice non ha risposto, e non «nessun candidato».
    """
    searched: int
    candidates: list[CandidatoVedovo]


class VedoveRiparate(Esito):
    moved: int


class PosizioniDaRitentare(Esito):
    #: Quante conversioni `failed` sono tornate da ritentare.
    reset: int


# ── Statistiche di lettura ───────────────────────────────────────────────

class RiassuntoLetture(Permissivo):
    """
    I numeri grandi della pagina Statistiche.

    **`total_books_completed` non e' dedotto, e' spuntato.** Prima lo
    decideva la posizione di lettura («sei oltre il 98%?»), e su dati veri
    quel criterio diceva *due* libri completati dopo 193 ore di lettura.
    Adesso conta la colonna `letto`, che una persona spunta a mano: finche'
    non si spunta niente dice zero, e uno zero che vuol dire «non hai
    ancora detto quali hai finito» e' onesto.

    Senza nessuna sessione di lettura tutti i campi sono zero o `null`
    **tranne** quello: chi ha segnato duecento libri letti e non ha mai
    sincronizzato un dispositivo deve vedere duecento.
    """
    total_time_seconds: int
    total_books: int
    total_pages: int
    total_chars: int
    #: Il tempo delle sole sessioni per cui si sa quanti caratteri sono
    #: stati letti: e' il denominatore giusto per una velocita' di lettura.
    chars_time_seconds: int
    total_books_completed: int
    year_time_seconds: int
    year_books: int
    year_pages: int
    best_day_seconds: int
    longest_session_seconds: int
    longest_book_title: Optional[str]
    longest_book_pages: int
    best_year: Optional[int]
    best_year_books: int
    longest_book_by_time_title: Optional[str]
    longest_book_by_time_seconds: int
    top_author_by_time_name: Optional[str]
    top_author_by_time_seconds: int
    longest_streak_days: int
    #: **Giorni di calendario, non istanti** (`YYYY-MM-DD`): la striscia
    #: comincia «il 3 ottobre», non «il 3 ottobre alle 00:00 UTC» — vedi
    #: `app/istanti.py::giorno`.
    longest_streak_start: Optional[str]
    longest_streak_end: Optional[str]


class SessioneDiLettura(Permissivo):
    """
    Una sessione, con i metadati del libro gia' attaccati: e' la riga su cui
    la pagina Statistiche costruisce ogni raggruppamento, e senza i metadati
    dovrebbe incrociarla con l'elenco dei libri da sola.

    Una sessione **orfana** (il libro non si e' accoppiato a nessuna riga di
    Calibre) compare qui con `book_id` nullo, titolo e autore quelli
    dichiarati dal dispositivo, e i campi dei metadati vuoti.
    """
    #: Giorno di calendario, `YYYY-MM-DD`.
    date: str
    #: Istante ISO col fuso dichiarato. **Obbligatorio**: la colonna e'
    #: `nullable=False`.
    start_time: str
    book_id: Optional[int]
    #: Mai vuoti: hanno un ripiego («Sconosciuto»).
    book_title: str
    author: str
    format: str
    device_name: str
    #: `web` o `koreader` — **non** gli stessi valori di
    #: `Evidenziazione.source`.
    source: str
    duration_seconds: int
    pages_read: int
    chars_read: int
    series: Optional[str]
    tags: list[str]
    language: Optional[str]
    publisher: Optional[str]
    rating: Optional[float]
    #: **Stringa**, non numero: `"1860"`. La costruisce `_decennio`, e
    #: l'avevo dichiarata intera — la validazione non se n'era accorta
    #: perche' Pydantic converte, ma un client generato che aspetta un
    #: numero e riceve una stringa non decodifica.
    decade: Optional[str]


class GiornoDiLettura(Permissivo):
    #: `YYYY-MM-DD`.
    date: str
    total_seconds: int


class VoceInPercentuale(Permissivo):
    """
    Una riga di una classifica, con la percentuale **gia' calcolata sul
    massimo** della classifica (non sul totale): la barra piu' lunga fa
    cento. L'etichetta si chiama `name` nelle classifiche di persone e
    `label` nelle altre.
    """
    count: int
    percent: int
    name: Optional[str] = None
    label: Optional[str] = None


class FormatoInPercentuale(Permissivo):
    """Questa invece e' in percentuale sul **totale**: e' una torta, e le
    fette devono fare cento."""
    format: str
    count: int
    percent: int


class SpazioPerFormato(Permissivo):
    format: str
    #: Gia' leggibile («1,4 GB»): la formattazione la fa il server perche'
    #: e' la stessa per tutti i client.
    bytesLabel: str
    percent: int


class PagineDiAutore(Permissivo):
    name: str
    pages: int
    percent: int


class SpazioDiAutore(Permissivo):
    name: str
    bytesLabel: str
    percent: int


class PanoramicaBiblioteca(Permissivo):
    """
    Le quattordici statistiche di catalogo, contate sul server. Prima le
    faceva il browser, e per farle scaricava il catalogo **intero**: su
    5.843 libri quasi sei megabyte di titoli e descrizioni per ricavarne un
    paio di chilobyte di conteggi.

    **Attenzione: su una biblioteca che non si riesce a leggere arriva
    `{"total_books": 0}` e nient'altro** — nessuna delle altre tredici
    chiavi. Per questo qui sono tutte facoltative tranne la prima: un
    client che legge `formats` senza controllare si rompe proprio sul caso
    limite.
    """
    total_books: int
    unique_authors: Optional[int] = None
    unique_series: Optional[int] = None
    #: Quanto sono completi i metadati, da 0 a 100 (su quattro campi).
    metadata_percent: Optional[int] = None
    formats: Optional[list[FormatoInPercentuale]] = None
    format_storage: Optional[list[SpazioPerFormato]] = None
    top_authors: Optional[list[VoceInPercentuale]] = None
    top_series: Optional[list[VoceInPercentuale]] = None
    page_buckets: Optional[list[VoceInPercentuale]] = None
    author_pages: Optional[list[PagineDiAutore]] = None
    author_storage: Optional[list[SpazioDiAutore]] = None
    ratings: Optional[list[VoceInPercentuale]] = None
    languages: Optional[list[VoceInPercentuale]] = None
    tags: Optional[list[VoceInPercentuale]] = None


class LibroAnnotato(Permissivo):
    title: str
    author: str
    highlights: int
    chars_read: int
    #: Evidenziazioni ogni centomila caratteri letti: e' la misura che
    #: rende confrontabile un libro di cento pagine con uno di mille.
    per_100k: float


class IntensitaAnnotazioni(Permissivo):
    books: list[LibroAnnotato]
    books_total: int
    #: Quanti libri sono stati **esclusi** perche' non si sa quanti
    #: caratteri ne sono stati letti: senza denominatore la misura non si
    #: puo' fare, e dirlo e' diverso dal farli sparire.
    books_without_denominator: int
    highlights_total: int


class LibroLetto(Permissivo):
    """
    Un libro spuntato come letto, con l'anagrafica del suo autore attaccata
    — e' quello che serve alle statistiche su chi si legge (secoli,
    nazionalita', mestieri) senza che il client debba interrogare gli
    autori uno per uno.
    """
    library: str
    book_id: int
    title: str
    #: Il primo autore; `autori` porta tutti.
    author: str
    autori: list[str]
    pages: int
    #: **Stringa**, non numero: `"1860"`. La costruisce `_decennio`, e
    #: l'avevo dichiarata intera — la validazione non se n'era accorta
    #: perche' Pydantic converte, ma un client generato che aspetta un
    #: numero e riceve una stringa non decodifica.
    decade: Optional[str]
    language: Optional[str]
    rating: Optional[float]
    author_birth_year: Optional[int]
    author_death_year: Optional[int]
    author_gender: Optional[str]
    author_nationality: Optional[str]
    author_occupations: list[str]


class LibriLetti(Permissivo):
    libri: list[LibroLetto]
    totale: int
    #: I nomi degli autori di cui non si ha l'anagrafica: le statistiche su
    #: di loro sono calcolate **senza** questi, e saperlo e' la differenza
    #: fra una percentuale e una percentuale su quanti.
    senza_anagrafica: list[str]


class StatisticheRicalcolate(Permissivo):
    devices_processed: int
    sessions_added: int
    #: Sessioni lasciate da parte perche' il loro libro non si e' ancora
    #: accoppiato a nessuna riga di Calibre.
    sessions_skipped_unresolved: int
    libraries_refreshed: int


class SessioneOrfana(Permissivo):
    """
    Una sessione di lettura il cui libro non si e' potuto riconoscere.
    L'`md5` del file e' l'unica identita' stabile che porta: titolo, autore
    e serie sono quelli che il dispositivo dichiara.
    """
    id: int
    #: Dispositivo, impronta e istante sono `nullable=False`: una sessione
    #: orfana senza di loro non si potrebbe nemmeno riconoscere.
    device_id: int
    md5: str
    start_time: str
    duration: int
    pages_read: int
    #: Questi tre invece sono quelli che il **dispositivo** dichiara, e
    #: possono mancare.
    title: Optional[str]
    authors: Optional[str]
    series: Optional[str]


class SessioniOrfane(Permissivo):
    count: int
    sessions: list[SessioneOrfana]


class SessioniAccoppiate(Esito):
    sessions_migrated: int
    #: Quante erano gia' state risolte nel frattempo: non e' un errore, ed
    #: e' diverso da zero migrate per un accoppiamento sbagliato.
    sessions_already_resolved: int


class SessioniScartate(Esito):
    sessions_discarded: int


class GraficoSalvato(Permissivo):
    """
    La **configurazione** di un grafico, non i dati: quelli si ricalcolano
    da `/raw` e `/timeline` ogni volta.

    I campi arrivati con la seconda versione (`group_by_secondary`,
    `chart_mode`, `filters`, `sort_by`, `sort_order`) su una riga salvata
    prima valgono `null`, `"grouped"` e `{}`: i difetti del client trattano
    quei valori esattamente come «non configurato», quindi non serve
    distinguere vecchio da nuovo.
    """
    id: int
    library: str
    name: str
    chart_type: str
    data_source: str
    group_by: Optional[str]
    metric: Optional[str]
    group_by_secondary: Optional[str]
    chart_mode: str
    filters: dict
    sort_by: Optional[str]
    sort_order: Optional[str]
    created_at: Optional[str]


# ── Dispositivi: il portale ──────────────────────────────────────────────
#
# Questa parte la chiama il browser (o un futuro client nativo) con il JWT
# della persona: elenca i lettori, mette libri in coda, guarda lo storico.

class PatchSulDispositivo(Permissivo):
    """
    Una userpatch di KOReader che il **server** ha, con lo stato su **quel**
    dispositivo.

    Il confronto lo fa il server sull'impronta del file, e il dispositivo
    riceve un verdetto: non c'e' niente da ricalcolare per chi legge. I tre
    stati sono fermi, e `assente` non e' un guasto — una patch si installa
    quando serve e si toglie quando non serve piu' (`patch_koreader.py`).
    """
    file: str
    nome: str
    descrizione: str
    versione: str
    stato: Literal["aggiornata", "da_aggiornare", "assente"]


class RichiestaDiRipristino(Permissivo):
    """
    «Rimetti su questo lettore il backup di quell'altro».

    Nasce dal dispositivo, la conferma una persona dal portale, e la chiude
    il dispositivo quando ha finito di copiare i file. `done` non si vede
    mai qui dentro: l'elenco dei dispositivi mostra solo la richiesta
    ancora viva (`_get_open_restore_request`).
    """
    id: int
    source_device_id: int
    #: Nullo se il dispositivo di partenza e' stato cancellato nel frattempo.
    source_device_name: Optional[str]
    status: Literal["pending_admin", "confirmed_admin"]
    requested_at: Optional[str]
    #: Valorizzato solo da `confirmed_admin` in avanti.
    confirmed_at: Optional[str]


class LibroSulDispositivo(Permissivo):
    """
    Una riga dello **stato desiderato** di un lettore, arricchita.

    Non e' la riga del database: titolo, autore, copertina, avanzamento e
    numero di note li aggiunge l'endpoint leggendo la biblioteca e le
    annotazioni. I tre nulli sono veri: un libro tolto dalla biblioteca
    lascia la riga senza titolo ne' autore.

    `status` dice cosa il server **vuole**, non cosa c'e': `pending_send`
    e' «da mandare», `pending_delete` «da togliere», `delete_declined` «il
    lettore ha detto no».
    """
    id: int
    calibre_book_id: int
    library: str
    format: str
    book_title: Optional[str]
    book_author: Optional[str]
    cover_url: Optional[str]
    #: `true` quando non c'e' nessuna impronta forzata da segnalare.
    hash_verified: bool
    status: Literal["synced", "pending_send", "send_failed", "pending_delete",
                    "delete_declined", "removed_by_device"]
    created_at: Optional[str]
    #: Contate **sul dispositivo**, mai scritte nei metadati di Calibre.
    #: Nulle con un plugin che non le riporta: 246 righe su 313 sul server
    #: vero il 05/11/2026.
    device_pages: Optional[int]
    device_path: Optional[str]
    #: `"server"` se la coda l'ha fatta il portale, `"device"` se il libro
    #: l'ha preso il lettore dal catalogo di bordo.
    requested_by: Optional[str]
    last_error: Optional[str]
    #: Percentuale intera di **chi possiede il lettore**, zero se non ha
    #: ancora aperto il libro.
    progress_percent: int
    highlights_count: int


class LibroInCodaPerIlDispositivo(Permissivo):
    """
    La stessa riga di `LibroSulDispositivo`, ridotta e con un verbo al
    posto dello stato: e' la forma che il portale di prima si aspettava, e
    resta per non romperlo. Si costruisce dalle stesse righe, filtrando
    quelle in attesa.
    """
    id: int
    calibre_book_id: int
    library: str
    action: Literal["queued_download", "queued_delete"]
    format: str


class DispositivoInElenco(Permissivo):
    """
    Un lettore come lo vede il portale.

    **Il token non c'e'.** Lo si vede una volta sola, appena registrato
    (`POST /api/devices/register`), e da allora non torna piu' in nessuna
    risposta.

    Tre coppie di campi dicono cose diverse che sembrano uguali, e
    confonderle fa dire al portale una bugia:

    * `patches` **e** `patches_riportate`: la prima e' sempre una lista, e
      vuota quando il dispositivo non ha detto niente. La seconda distingue
      «non lo ha detto» (plugin piu' vecchio della 0.9.0) da «nessuna patch
      installata».
    * i tre `storage_*` sono `null` con un plugin che non li misura — e
      `null` non e' zero: zero vorrebbe dire «disco pieno».
    * `dizionari_richiesti` e' una **coda**, quindi vuota appena sono
      arrivati: non e' l'elenco di quelli installati sul lettore.
    """
    id: int
    name: str
    model: str
    is_default: bool
    #: Tutte e tre `YYYY-MM-DD HH:MM:SS`, in UTC, e nulle finche' non e'
    #: successo: un lettore appena registrato non si e' mai fatto vivo.
    last_sync_at: Optional[str]
    last_backup_at: Optional[str]
    last_seen_at: Optional[str]
    plugin_version: Optional[str]
    delete_policy: Literal["ask", "auto", "never"]
    patches: list[PatchSulDispositivo]
    patches_riportate: bool
    #: Codici di lingua (`"it"`, `"en"`), solo quelli che il server conosce.
    dizionari_richiesti: list[str]
    storage_used: Optional[int]
    storage_total: Optional[int]
    storage_available: Optional[int]
    backup_file_count: int
    pending_restore_request: Optional[RichiestaDiRipristino]
    #: **Uguale per tutti i dispositivi**: non c'e' niente che la persista
    #: per lettore. E' un dato da mostrare, non una preferenza.
    supported_formats: list[str]
    folder_layout: str
    write_folder_cover: bool
    books: list[LibroSulDispositivo]
    sync_queue: list[LibroInCodaPerIlDispositivo]


class DizionariInCoda(Esito):
    """La coda dei dizionari **dopo** la modifica: chi chiama non deve
    rileggerla."""
    dizionari_richiesti: list[str]


class VocabolarioDimenticato(Esito):
    """
    Quante parole sono state buttate, e se anche la copia del file di
    KOReader e' andata via.

    `snapshot_rimosso` puo' essere `false` con `status: "ok"`: le parole
    sono via dal database ma il file sul disco e' rimasto (permessi, disco
    pieno). Dire «ok» e tacerlo renderebbe invisibile il fatto che al
    prossimo backup quelle parole tornano.
    """
    parole_tolte: int
    snapshot_rimosso: bool


class FileDiBackup(Permissivo):
    """Un file del backup di un lettore, come sta sul server."""
    filename: str
    size: int
    modified_at: str


class SincronizzazioneNelloStorico(Permissivo):
    """
    Una sessione di sincronizzazione finita (o abbandonata).

    `outcome` passa da `open` a uno dei quattro finali. `abandoned` lo
    scrive il **server**, non il dispositivo: una sessione che nessuno ha
    chiuso entro un'ora viene archiviata cosi' al primo handshake
    successivo, altrimenti bloccherebbe per sempre quel lettore.

    Lo storico tiene le ultime cento sessioni per dispositivo.
    """
    id: int
    session_id: str
    started_at: Optional[str]
    #: Nullo mentre la sessione e' ancora aperta.
    finished_at: Optional[str]
    outcome: Literal["open", "ok", "partial", "error", "abandoned"]
    plugin_version: Optional[str]
    #: Testo libero del plugin: `manual`, `auto_open`, `auto_resume`…
    trigger: Optional[str]
    books_reported: int
    downloads_requested: int
    downloads_ok: int
    downloads_failed: int
    deletes_requested: int
    deletes_done: int
    deletes_declined: int
    removed_by_device: int
    pages_reported: int
    #: JSON **come stringa**, non un oggetto: lo scrive il plugin e il
    #: server non lo interpreta. Nullo su 36 sessioni su 236 sul server
    #: vero (05/11/2026).
    detail_json: Optional[str]


class LibroDaRivedere(Permissivo):
    """
    Un file trovato **sul lettore** che non si e' accoppiato a nessun libro
    della biblioteca.

    I campi `local_*` li riporta il dispositivo guardando il proprio file;
    i `candidate_*` sono il libro che il server propone, e sono nulli
    quando non ne ha trovato nessuno.
    """
    id: int
    local_path: str
    local_title: Optional[str]
    local_author: Optional[str]
    match_status: str
    #: Frazione fra 0 e 1 letta sul dispositivo, non una percentuale.
    local_percent_read: Optional[float]
    local_highlights_count: Optional[int]
    candidate_library: Optional[str]
    candidate_calibre_book_id: Optional[int]
    candidate_title: Optional[str]
    candidate_author: Optional[str]
    flagged_at: Optional[str]
    #: Un'azione chiesta dal portale e non ancora applicata dal lettore.
    pending_action: Optional[Literal["delete", "overwrite"]]


class AzioneAccodata(Esito):
    """`delete` e `overwrite` si mettono in coda: il lettore puo' essere
    spento, e il file lo tocca lui alla prossima sincronizzazione."""
    pending_action: Literal["delete", "overwrite"]


class OrfaneMigrate(Esito):
    """
    `pair` invece si applica **subito**: non tocca nessun file sul
    dispositivo, quindi non c'e' niente da accodare. Il numero sono le
    annotazioni orfane che hanno ritrovato il loro libro.
    """
    migrated_highlights: int


class AzioniAccodate(Esito):
    """Quante righe ha preso l'azione in blocco."""
    updated: int


# ── Dispositivi: il protocollo che parla col plugin KOReader ─────────────
#
# Queste risposte non passano dal browser: le legge il plugin Lua su un
# e-reader, autenticato col token permanente del dispositivo. Dichiararle
# serve a loro, non al portale — ed e' il motivo per cui questo lotto e'
# stato fatto per ultimo.

class CandidatoDiAccoppiamento(Permissivo):
    """
    Un libro che potrebbe essere quel file.

    Sono **piu' di uno** di proposito: lo stesso file puo' stare in due
    biblioteche, e indovinare al posto della persona e' peggio che
    chiedere.
    """
    library: str
    calibre_book_id: int
    title: Optional[str]
    author: Optional[str]


class FileRiconosciutoDalloScan(Permissivo):
    """Un file del lettore la cui impronta ha trovato almeno un libro."""
    hash: str
    #: Ripetuti da quello che il dispositivo ha mandato: nulli se li aveva
    #: omessi.
    path: Optional[str]
    format: Optional[str]
    candidates: list[CandidatoDiAccoppiamento]


class ScansioneDeiNonAccoppiati(Permissivo):
    """
    L'esito di «Inizializza libreria»: cosa il server ha riconosciuto e
    cosa no.

    `unmatched` e' **la voce del dispositivo rimandata indietro intatta**,
    non una forma del server: il plugin la usa per provare un confronto
    per titolo e autore contro il catalogo. Per questo e' un dizionario
    libero e non un modello — la sua forma la decide chi chiama.
    """
    matched: list[FileRiconosciutoDalloScan]
    unmatched: list[dict]


class LibroSegnalato(Esito):
    """Il file e' finito in «Da rivedere», e questo e' l'id della riga."""
    id: int


class SegnalazioneAccoppiataDaSola(Esito):
    """
    Il file si e' accoppiato da solo, e nessuna riga da rivedere e' nata.

    `auto_paired` c'e' **solo** in questa forma, ed e' sempre `true`: e' la
    sola cosa che distingue le due risposte dello stesso indirizzo.
    """
    auto_paired: Literal[True]
    migrated_highlights: int


class BibliotecaPerIlDispositivo(Permissivo):
    """
    Le biblioteche, ridotte a due campi per il lettore.

    `library` e' la **cartella** e non il nome: e' quello che va in ogni
    richiesta successiva.
    """
    name: str
    library: str


class DispositivoFratello(Permissivo):
    """Un altro lettore della stessa persona — serve a chiedere il
    ripristino da quello giusto."""
    id: int
    name: str
    model: str


class CapacitaDelServer(Permissivo):
    """
    Cosa questo server sa fare, per un plugin che puo' essere piu' nuovo o
    piu' vecchio di lui.

    I valori sono **costanti nel codice**: non si calcolano, si alzano a
    mano quando una capacita' nuova esiste davvero.
    """
    serverVersion: str
    capabilities: list[str]


class VoceDiSezione(Permissivo):
    """Un nome (autore, serie o etichetta) e quanti libri lo portano."""
    name: str
    count: int


class SezioneDelCatalogo(Permissivo):
    """
    Una pagina di nomi per «sfoglia per autore / per serie / per
    etichetta».

    Si conta per **nome** e non per identificativo interno di Calibre:
    quelli l'elenco dei libri non li espone a questo livello, e i filtri
    del catalogo lavorano gia' per nome. Un libro con tre etichette conta
    in tre gruppi; `"Alice & Bob"` conta in due.
    """
    page: int
    size: int
    total: int
    has_next: bool
    items: list[VoceDiSezione]


class LibroDelCatalogo(Permissivo):
    """
    Un libro come lo vede il lettore quando sfoglia il catalogo del
    server.

    E' una forma **sua**, piu' corta di `LibroInElenco`: niente colonne
    personalizzate, niente biblioteca (la chiede lui), niente indirizzo
    della copertina — solo `has_cover`, perche' la copertina la scarica da
    un indirizzo che sa costruire.
    """
    id: int
    title: str
    author: Optional[str]
    formats: list[str]
    series: Optional[str]
    series_index: Optional[float]
    tags: list[str]
    rating: Optional[float]
    #: Solo il giorno, `YYYY-MM-DD`.
    pubdate: Optional[str]
    #: **Booleano**, come in ogni altra risposta del progetto.
    #:
    #: Fino al 05/11/2026 qui arrivava `0` oppure `1` — il valore grezzo
    #: della colonna di Calibre, lasciato passare tale e quale mentre
    #: `/api/kolibre/books` lo converte (`books.py`,
    #: `bool(b["cover_path"])`): lo stesso campo con due tipi secondo
    #: l'indirizzo da cui usciva. Lo ha trovato la prova che confronta il
    #: tipo dichiarato con quello che arriva.
    #:
    #: Perche' qui era peggio che altrove: questa risposta la legge un
    #: plugin scritto in **Lua**, e in Lua **lo zero e' vero**. Un
    #: `if book.has_cover then` sarebbe entrato sempre, anche per un libro
    #: senza copertina. Nessun client lo leggeva ancora — cercato in tutti
    #: i plugin, zero occorrenze — quindi era il momento meno costoso che
    #: ci sarebbe mai stato per uniformarlo.
    has_cover: bool
    size: Optional[int]


class LibriDaScoprire(Permissivo):
    """
    «Da scoprire»: libri che su questo lettore non ci sono, scelti fra
    quelli dello stesso autore o con le stesse etichette di cio' che e'
    stato letto **su di lui**, e completati a sorte quando non bastano.
    """
    books: list[LibroDelCatalogo]


class CatalogoSfogliato(Permissivo):
    """
    Il catalogo, filtrato e ordinato.

    **Due forme da un indirizzo.** `page` e `has_next` compaiono solo se la
    richiesta chiede una pagina; senza, la risposta e' tagliata a
    cinquecento libri e `truncated` lo dice. Sono gli unici due campi
    davvero facoltativi di questo modello.
    """
    total: int
    truncated: bool
    books: list[LibroDelCatalogo]
    page: Optional[int] = None
    has_next: Optional[bool] = None


class FileIdentificato(Permissivo):
    """
    Il file aperto sul lettore e' questo libro.

    `id` e `calibre_book_id` portano **lo stesso numero**: il primo e'
    rimasto per il plugin di prima, e togliere un campo da un protocollo
    che gira su dispositivi che non si aggiornano da soli e' un'altra
    faccenda.
    """
    matched: Literal[True]
    id: int
    library: str
    calibre_book_id: int
    title: Optional[str]
    author: Optional[str]
    formats: list[str]


class FileNonIdentificato(Permissivo):
    """
    Non si e' riconosciuto, e **perche'**: il plugin si comporta in modo
    diverso per ognuno dei tre motivi.
    """
    matched: Literal[False]
    reason: Literal["unsupported_format", "extraction_failed", "no_match"]


class AnnotazioniRicevute(Esito):
    """
    Cos'e' successo alle annotazioni mandate dal lettore.

    `orphaned` sono quelle il cui file non si e' accoppiato a nessun libro:
    **non vengono buttate**, diventano annotazioni orfane e `orphan_paths`
    dice da quali file, cosi' il plugin puo' proporre un accoppiamento a
    mano.
    """
    created: int
    updated: int
    unresolved: int
    orphaned: int
    orphan_paths: list[str]


class AnnotazioniRiconciliate(Esito):
    """Quante annotazioni sono state cancellate perche' sul lettore non ci
    sono piu'."""
    deleted: int


class LibroDaMandare(Permissivo):
    """
    Un libro che il server vuole **sul** lettore e che lui non ha.

    `delivery_hash` e' l'impronta che il server si aspetta dal file
    consegnato: serve al dispositivo per dimostrare poi di avere
    esattamente quel file. Nulla se del libro non esiste ancora
    un'impronta.
    """
    #: L'id della **riga**, non del libro: e' quello con cui si conferma.
    book_id: int
    calibre_book_id: int
    library: str
    format: str
    title: Optional[str]
    author: Optional[str]
    #: Relativo, da attaccare all'indirizzo del server.
    download_url: str
    #: La foto dell'autore, se il server ce l'ha: il lettore la scrive
    #: nella cartella come copertina.
    folder_cover_url: Optional[str]
    delivery_hash: Optional[str]


class LibroDaTogliere(Permissivo):
    """
    Un libro che il server vuole **via** dal lettore.

    L'elenco e' **vuoto** per un dispositivo la cui politica e' `never`: a
    un lettore cosi' il server non parla nemmeno di cancellazioni.
    """
    book_id: int
    calibre_book_id: int
    library: str
    format: str
    title: Optional[str]
    #: Dove il lettore aveva detto di averlo messo; nullo se non lo ha mai
    #: riportato.
    expected_path: Optional[str]


class AzioneDiEliminazione(Permissivo):
    """Togli questo file dal lettore. Tre campi, e nessun libro: il file
    non si era accoppiato a niente, e' per questo che si cancella."""
    id: int
    action: Literal["delete"]
    local_path: str


class AzioneDiSovrascrittura(Permissivo):
    """
    Togli questo file e metti **quel** libro al suo posto.

    E' la stessa voce di `AzioneDiEliminazione` con sei campi in piu', e
    non un modello diverso per capriccio: `action` dice quale delle due
    forme e' arrivata, e i sei campi esistono **solo** in questa.
    """
    id: int
    action: Literal["overwrite"]
    local_path: str
    library: str
    calibre_book_id: int
    #: Se nessuno l'ha scelto, il server prende il primo formato che il
    #: libro ha — `EPUB` se non ne ha nessuno.
    format: str
    title: Optional[str]
    author: Optional[str]
    download_url: str


AzioneSuFile = Union[AzioneDiEliminazione, AzioneDiSovrascrittura]


class ImpostazioniPerIlDispositivo(Permissivo):
    """
    Le impostazioni che il lettore deve rispettare, decise dal portale.

    `report_pages` e' **sempre** `true`: il server le pagine le vuole
    sempre, e il campo esiste per poter dire di no un giorno senza
    cambiare la forma della risposta.
    """
    folder_layout: str
    write_folder_cover: bool
    delete_policy: Literal["ask", "auto", "never"]
    report_pages: bool


class Handshake(Permissivo):
    """
    La risposta all'inizio di una sincronizzazione: cosa fare, in questo
    giro.

    `library_token` e' un'impronta dello stato desiderato: se il lettore la
    rimanda uguale e non manda il suo elenco, il server salta tutta la
    riconciliazione. E' il motivo per cui una sincronizzazione a vuoto
    costa quasi niente.

    `dictionaries` resta pieno a **ogni** giro finche' il dispositivo non
    conferma di aver preso i file: se lo scaricamento si interrompe, al
    prossimo giro ci riprova da se'.
    """
    #: Da ripetere in ogni conferma di questo giro.
    session_id: str
    library_token: str
    sends: list[LibroDaMandare]
    removes: list[LibroDaTogliere]
    file_actions: list[AzioneSuFile]
    #: Valorizzato **solo** quando una persona l'ha confermata dal portale.
    restore_request: Optional[RichiestaDiRipristino]
    dictionaries: list[str]
    settings: ImpostazioniPerIlDispositivo


class ScaricamentoLegacy(Permissivo):
    """Un libro da scaricare, nella forma di prima del protocollo 2."""
    #: Lo stesso numero di `LibroDaMandare.book_id`, con il nome di prima.
    queue_id: int
    calibre_book_id: int
    library: str
    format: str
    download_url: str
    author: Optional[str]
    title: Optional[str]
    folder_cover_url: Optional[str]


class EliminazioneLegacy(Permissivo):
    """Un libro da togliere, nella forma di prima del protocollo 2."""
    queue_id: int
    calibre_book_id: int
    library: str
    format: str


class ImpostazioniLegacy(Permissivo):
    """Due impostazioni su quattro: le altre il plugin di prima non le
    sapeva leggere."""
    folder_layout: str
    write_folder_cover: bool


class HandshakeLegacy(Permissivo):
    """
    La risposta per un plugin che non dichiara `protocol: 2`.

    **Due forme dallo stesso indirizzo, e a scegliere e' il corpo della
    richiesta** — non un parametro nell'indirizzo, come negli altri casi
    del progetto. Un client che manda `protocol: 2` non vedra' mai questa.
    """
    downloads: list[ScaricamentoLegacy]
    deletions: list[EliminazioneLegacy]
    settings: ImpostazioniLegacy


class LottoConfermato(Esito):
    """
    Quante conferme sono state applicate e quante buttate.

    `skipped` conta le righe che **non sono di questo dispositivo** (o non
    esistono): un lettore non puo' confermare per un altro, e dirlo in
    silenzio sarebbe un buco.
    """
    applied: int
    skipped: int


class SessioneChiusa(Esito):
    """Com'e' finita la sessione, secondo il conto del server."""
    outcome: Literal["ok", "partial", "error"]


class AzioniSuFileConfermate(Esito):
    """Quante righe «da rivedere» sono sparite perche' il lettore ha fatto
    quello che gli era stato chiesto."""
    deleted: int


class PagineRicevute(Permissivo):
    """
    Le pagine contate sul lettore.

    **Non c'e' `status`**: e' una delle poche risposte del progetto che non
    lo porta, e cambiarlo adesso vorrebbe dire cambiare un protocollo che
    gira su dispositivi che non si aggiornano da soli.

    `unresolved` conta anche i libri che il lettore ha ma il server non
    gestisce: per lui sono la stessa cosa — non ha dove scrivere il numero.
    """
    updated: int
    unresolved: int


class LibroConsegnato(Esito):
    """Il lettore ha scaricato da se' un libro dal catalogo, e da ora il
    server lo gestisce: questo e' l'id della riga nata (o ritrovata)."""
    book_id: int


class PosizionePerIlDispositivo(Permissivo):
    """
    Dove e' arrivata la lettura di questo libro, per il lettore che
    chiede.

    **Due forme dallo stesso indirizzo.** Senza nessuna posizione salvata
    la risposta e' `{"percentage": null, "progress": null}` e nient'altro:
    gli altri cinque campi non compaiono. Per questo i primi due sono
    sempre presenti e gli altri facoltativi.

    `is_own_device` conta: una posizione che viene da un altro lettore si
    propone, non si applica.
    """
    #: Frazione fra 0 e 1.
    percentage: Optional[float]
    #: La posizione nel formato di KOReader (un XPointer), opaca per chi la
    #: trasporta.
    progress: Optional[str]
    device_name: Optional[str] = None
    updated_at: Optional[str] = None
    is_own_device: Optional[bool] = None
    #: `letto`, `in_lettura`, `da_leggere`… lo stato dichiarato a mano.
    stato: Optional[str] = None
    #: Solo il giorno.
    stato_modificato: Optional[str] = None


class FileDelDizionario(Permissivo):
    """
    Un file di un dizionario StarDict, da prendere uno per uno.

    Si manda un elenco e non un archivio perche' **KOReader non ha una
    libreria per scompattarlo**: il plugin scarica file per file e li
    rinomina, come fa gia' per aggiornare se stesso.
    """
    name: str
    size: int
    sha256: str


class ManifestDelDizionario(Permissivo):
    """
    Cosa scaricare per avere quel dizionario.

    `display_name` arriva da qui e non dal dispositivo: il lettore non ha
    modo di sapere come si chiama il dizionario `it`, e un messaggio che
    dice «dizionario it installato» non e' un messaggio.
    """
    lang: str
    display_name: str
    files: list[FileDelDizionario]


class FileDiBackupSulServer(Permissivo):
    """Dimensione e impronta di un file che il server ha gia'."""
    size: int
    #: MD5 **intero**, non quello parziale usato per i libri: qui la
    #: domanda e' «questo file e' cambiato?», e sui file `.lua` il
    #: parziale non lo garantisce.
    hash: str


class StatoDeiBackup(Permissivo):
    """
    Cosa il server ha gia', per non farsi ricaricare quello che non e'
    cambiato. Le chiavi sono i nomi dei file.
    """
    files: dict[str, FileDiBackupSulServer]


class RiassuntoStatistiche(Permissivo):
    """
    Cos'e' uscito dal file delle statistiche di KOReader.

    `sessions_skipped_unresolved` non sono sessioni perse: sono quelle di
    un libro che il server non ha mai visto, e finiscono fra le sessioni
    orfane. Se la biblioteca che manca viene riscandita, la prossima
    rielaborazione dello stesso file le recupera.
    """
    sessions_added: int
    positions_updated: int
    books_seen: int
    sessions_skipped_unresolved: int
    #: Le cartelle toccate, per sapere quali cache rifare.
    biblioteche: list[str]


class RiassuntoVocabolario(Permissivo):
    """Quante parole nuove e quante aggiornate dal vocabolario di
    KOReader."""
    words_added: int
    words_updated: int


class BackupRicevuto(Esito):
    """
    Il file e' arrivato.

    I due riassunti sono **nulli quasi sempre**: ci sono solo quando il
    file caricato era `statistics.sqlite3` oppure
    `vocabulary_builder.sqlite3`, e solo se l'elaborazione non e'
    fallita — un errore li' non fa fallire il caricamento, perche' il file
    e' comunque salvo.
    """
    bytes: int
    stats: Optional[RiassuntoStatistiche]
    vocabulary: Optional[RiassuntoVocabolario]


class StatoDelleStatistiche(Permissivo):
    """
    Da dove il lettore deve ripartire, e con cosa confrontarsi.

    `da` non e' l'ultimo istante noto: e' quello **meno una finestra di
    sovrapposizione**, perche' una riga scritta nello stesso secondo
    dell'ultima lettura altrimenti si perderebbe. `righe` e
    `somma_durate` sono i due numeri con cui il dispositivo verifica che
    il deposito del server non abbia buchi.
    """
    disponibile: bool
    da: int
    righe: int
    somma_durate: int


class StatisticheCucite(Permissivo):
    """
    Le righe nuove sono entrate nel deposito del server.

    Una giornata normale sono **29 byte** invece dei 659 KB del file
    intero, misurati su un Kindle vero. `stats` c'e' solo se qualche riga
    e' entrata davvero e la rielaborazione e' andata a buon fine.
    """
    status: Literal["ok"]
    righe_aggiunte: int
    stats: Optional[RiassuntoStatistiche]


class StatisticheDaRifare(Permissivo):
    """
    Il conto non torna: serve il file intero.

    Il dispositivo dichiara quante righe e quanta durata ha in tutta la
    sua tabella, e dopo la cucitura i due numeri devono coincidere. Se non
    coincidono il deposito ha un buco — un dispositivo ripristinato, un
    file rifatto da zero, una sincronizzazione persa mesi fa — e l'unica
    risposta onesta e' chiedere tutto. Una statistica che diverge in
    silenzio e' molto peggio di una salita da 659 KB ogni tanto.
    """
    status: Literal["resync"]
    #: Sempre `true`: il campo e' quello che il plugin guarda, e `status`
    #: e' arrivato dopo.
    risincronizza: Literal[True]
    #: Leggibile da una persona: `nessun_deposito`, `righe 10 contro 12`…
    motivo: str


class RichiestaDiRipristinoCreata(Esito):
    """La richiesta e' nata e aspetta che una persona la confermi dal
    portale."""
    id: int


class SincronizzazioneConfermata(Esito):
    """Quante righe ha chiuso la conferma del protocollo di prima."""
    confirmed: int


# ── Impostazioni del server ──────────────────────────────────────────────
#
# Diciotto operazioni, nove coppie `GET`/`PUT`: ogni `PUT` risponde **il
# valore come e' rimasto dopo la scrittura**, non un `{"status": "ok"}`. E'
# la cosa migliore che potessero fare, e qui va dichiarata: chi scrive non
# deve rileggere per sapere cos'e' stato salvato — e in tre casi su nove il
# valore che torna **non e'** quello mandato, perche' il server lo riporta
# nei limiti.

class Interruttore(Permissivo):
    """
    Un'impostazione che e' acceso-spento, e nient'altro.

    Tre interruttori hanno questa forma, e hanno in comune solo quella:

    * `auto-wiki-scrape` — se all'importazione si va a cercare su Wikipedia
      i dati di un autore nuovo. **Acceso** di preimpostazione.
    * `opds-feed` — se le rotte `/opds` servono il feed o rispondono 404.
      **Spento**.
    * `web-reader-tracking` — se leggere nel browser conta come lettura.
      **Spento**, e il perche' sta scritto accanto alla chiave
      (`app_settings.WEB_READER_TRACKING_KEY`): contarlo sporca le
      statistiche e riporta indietro il segnalibro del Kindle.

    Il valore che torna dalla scrittura e' quello salvato, gia' convertito
    in booleano.
    """
    enabled: bool


class ImpostazioneContoPagine(Permissivo):
    """
    Come si **stimano** le pagine di un libro che non e' un PDF (un PDF le
    pagine ce le ha, e si contano).

    `mode` vale `words` o `chars`, e gli altri due dicono quante parole o
    quanti caratteri fanno una pagina.

    **Questa e' la sola impostazione del server che non valida niente.** Le
    tre paginazioni riportano ogni valore nei limiti e scartano un `mode`
    che non conoscono; qui invece la scrittura e' un `{**difetti,
    **ricevuto}` e basta. Misurato il 05/11/2026: un `words_per_page:
    "trecento"` viene **salvato**, riletto tale e quale, e poi fa fallire
    con un `TypeError` ogni ricalcolo delle pagine
    (`page_counter._pagine_da_testo`). I tre campi sono dichiarati per
    quello che devono essere — un client che manda altro rompe il server, e
    questo e' un difetto da chiudere, non una forma da documentare.
    """
    #: `words` oppure `chars`. **Non validato**: vedi sopra.
    mode: str
    words_per_page: int
    chars_per_page: int


class ImpostazionePaginazione(Permissivo):
    """
    Da quanti elementi in su una pagina si divide in pagine, e quanto grandi.

    Tre pagine hanno questa impostazione, con tre soglie diverse perche'
    pesano in modo diverso: la Libreria (10.000 — misurato: 100.000 libri
    sono 9,4 secondi e 66 MB in una risposta sola), gli Arretrati (200 —
    ogni riga e' una scheda con comandi, non una riga di tabella) e gli
    Autori (500 — misurato: 20.000 autori sono 180.219 nodi nel DOM e 12,6
    secondi perche' una ricerca si assesti).

    **Il valore che torna dalla scrittura puo' non essere quello mandato.**
    Un `mode` sconosciuto diventa quello di preimpostazione, e soglia e
    misura della pagina vengono riportate nei limiti: provato il 05/11/2026,
    un `page_size: 999999` risponde `2000`. Per questo la risposta e' il
    valore salvato e non un esito — altrimenti chi scrive crederebbe di aver
    impostato una cosa che non ha impostato.

    Non confondere con `ModoPaginazione`, che e' la **risposta calcolata**
    per una biblioteca precisa (questa impostazione piu' il totale dei suoi
    libri piu' il verdetto).
    """
    mode: Literal["auto", "always", "never"]
    threshold: int
    page_size: int


class TettoDellIndice(Permissivo):
    """
    Quanto puo' crescere l'indice full-text, in gigabyte.

    Misurato su un impianto reale: 1,9 GB per 1.229 libri, circa 1,6 MB a
    libro. A 100.000 libri sarebbero 160 GB. Il tetto non cancella niente e
    non spegne la ricerca: ferma l'indicizzazione dei libri **nuovi** e lo
    dice. `0` vuol dire nessun tetto; il massimo e' 10.000, e anche questo
    valore torna riportato nei limiti.
    """
    max_gb: float


class SogliaDelleSessioni(Permissivo):
    """
    Sotto quanti secondi una sessione di lettura non entra nelle statistiche.

    Zero di preimpostazione, cioe' nessun filtro: misurato su dati veri, il
    19% delle sessioni sta sotto il minuto ma vale lo 0,5% delle ore — un'ora
    su 193. Il tetto e' un'ora: oltre non si sta piu' togliendo rumore, si
    sta buttando via letture vere.
    """
    seconds: int


# ── Autori ───────────────────────────────────────────────────────────────

class _AnagraficaAutore(Permissivo):
    """
    I sei campi che arrivano da Wikidata, nella stessa forma in due
    risposte diverse.

    Non sono una base per comodita': sono **gli stessi sei campi** nella
    scheda e nell'elenco, e il codice che li costruisce e' una funzione sola
    (`authors.py::_anagrafica`). Se qui divergessero, divergerebbero in due
    posti che l'utente vede come uno.
    """
    #: L'etichetta italiana di P21: `"maschio"`, `"femmina"`…
    gender: Optional[str]
    #: P27, **una lista**: chi ha cambiato paese ne ha piu' di uno, e ci
    #: sono stati storici («Regno d'Italia»). Nel database e' una stringa
    #: unica separata da `;`, e qui torna spacchettata.
    nationality: list[str]
    #: ISO, ma **puo' essere solo l'anno**: `"1821"` tanto quanto
    #: `"1821-11-11"`. Chi lo mostra non puo' assumere una data intera.
    birth_date: Optional[str]
    #: `null` **anche per i viventi**, e non e' un dato mancante: non c'e'
    #: modo di distinguere «vivo» da «non lo sappiamo» guardando solo
    #: questo campo (vedi `AuthorMetadata.wikidata_fetched_at`).
    death_date: Optional[str]
    #: P106, una lista. E' il campo che dice davvero **che cosa** si legge.
    occupations: list[str]
    wikidata_qid: Optional[str]


class AutoreInElenco(_AnagraficaAutore):
    """
    Un autore nell'elenco, con quanto se ne possiede e la sua foto.

    `book_count` e `total_pages` sono sommati su **tutte** le biblioteche,
    non su quella aperta: la pagina Autori e' una vista globale, e con il
    parametro `library` si restringe tutto insieme.

    I sei campi dell'anagrafica ci sono **sempre**, anche per un autore di
    cui non si sa niente: in quel caso l'elenco mette a mano i sei valori
    vuoti. E' la differenza con `SchedaAutore`, dove invece non compaiono.
    """
    name: str
    book_count: int
    #: Somma delle pagine stimate, **zero** e non `null` per un autore di
    #: cui nessun libro ha un conto pagine.
    total_pages: int
    #: Valorizzato solo se la foto e' davvero sul disco del server.
    photo_url: Optional[str]


class SchedaAutore(_AnagraficaAutore):
    """
    La scheda di un autore: le biografie, gli indirizzi, la foto.

    **Due forme dallo stesso indirizzo.** Per un autore di cui il server
    non ha nessuna riga, la risposta sono queste sette chiavi e
    **nient'altro**: i sei campi dell'anagrafica non compaiono. Per un
    autore che una riga ce l'ha, ci sono tutti e tredici. E' un'asimmetria
    con l'elenco, che quei sei li mette comunque — e per questo qui sono
    facoltativi mentre la' sono obbligatori.

    `bio_it` e `bio_en` sono due scomparti distinti e non una traduzione
    l'uno dell'altro: il recupero riempie quello della lingua in cui ha
    trovato la voce.
    """
    name: str
    bio_it: Optional[str]
    bio_en: Optional[str]
    wikipedia_url_it: Optional[str]
    wikipedia_url_en: Optional[str]
    photo_url: Optional[str]
    #: Quando si e' provato a cercarlo, non quando ci si e' riusciti.
    last_scraped_at: Optional[str]

    gender: Optional[str] = None
    nationality: Optional[list[str]] = None
    birth_date: Optional[str] = None
    death_date: Optional[str] = None
    occupations: Optional[list[str]] = None
    wikidata_qid: Optional[str] = None


class LibroDiUnAutore(Permissivo):
    """
    Un libro di quell'autore, da qualunque biblioteca.

    E' una forma **corta** di proposito: serve a disegnare una copertina con
    un titolo sotto. Chi vuole il resto apre il libro, e per aprirlo gli
    servono i due campi che ci sono — `id` e `library`.
    """
    id: int
    title: str
    #: **Sempre** valorizzato: senza copertina sul disco l'indirizzo
    #: risponde quella costruita da titolo e autore.
    cover_url: str
    #: La **cartella** della biblioteca, non il nome mostrato.
    library: str
    #: Il nome **mostrato** della biblioteca: e' il titolo della sezione in
    #: cui questo libro va messo. L'elenco arriva ordinato per questo campo
    #: e poi per titolo, quindi i gruppi sono contigui e chi disegna mette un
    #: separatore quando cambia — con un gruppo solo, nessuno.
    library_name: str


class ImmagineProposta(Permissivo):
    """
    Una foto candidata, da Wikimedia Commons.

    `thumb_url` serve alla griglia e `url` e' quello che il server scarica
    davvero se la si scegli. Possono essere nulli: li manda Commons, e un
    file senza miniatura ricade sull'originale.

    La ricerca torna una lista **vuota** se Commons non risponde o
    risponde male — non un errore: una proposta che non si e' potuta
    chiedere e una ricerca senza risultati sono la stessa cosa per chi
    guarda la griglia.
    """
    title: str
    thumb_url: Optional[str]
    url: Optional[str]


class LettureDiUnAutore(Permissivo):
    """
    Quanto e' stato letto **di** questo autore.

    Su un autore di cui non si possiede nessun libro torna tutto a zero con
    le due date nulle: la stessa forma, nessuna chiave in meno.

    `books_read` sono i libri su cui esiste almeno una sessione di lettura;
    `books_marked_read` quelli spuntati a mano. I due numeri non si
    sovrappongono per forza, ed e' il motivo per cui ci sono entrambi: un
    libro letto prima di avere un lettore sincronizzato e' spuntato e non
    ha sessioni, e uno aperto a meta' ha sessioni e non e' spuntato.
    """
    books_owned: int
    books_read: int
    books_marked_read: int
    total_time_seconds: int
    #: Stimati dalla frazione letta di ogni sessione per i caratteri del
    #: libro — non contati uno per uno.
    chars_read: int
    sessions: int
    #: ISO col fuso, oppure nulle se non c'e' nessuna sessione.
    first_read: Optional[str]
    last_read: Optional[str]
    highlights: int


class StatoDelRecupero(Permissivo):
    """
    A che punto e' il recupero dei dati degli autori da Wikipedia.

    **Vive sul server e non nel browser**, e il perche' e' tutto il motivo
    per cui questo endpoint esiste: prima era un ciclo dentro la pagina
    Autori, e bastava ricaricare per interromperlo a meta' senza traccia di
    cosa mancava. Ora il giro e' uno per tutto il server, sopravvive al
    cambio pagina e si legge da qualunque scheda.

    Lo stato vive **in memoria**: un riavvio del backend lo perde, ed e' una
    scelta — `AuthorMetadata.last_scraped_at` fa da memoria vera di cosa si
    e' gia' tentato, quindi un secondo giro non riparte da zero.

    I tre elenchi non sono tre modi di dire «errore»: `failed` e' la
    richiesta andata storta (rete, limite), `not_found` e' Wikipedia che
    non ha quella voce — e non e' un guasto — e `no_image` e' la voce
    trovata senza nessuna foto libera.
    """
    running: bool
    total: int
    processed: int
    #: L'autore in lavorazione, nullo quando il giro non sta girando.
    current: Optional[str]
    failed: list[str]
    not_found: list[str]
    no_image: list[str]
    #: ISO col fuso. Nulli finche' non e' mai partito / finche' non ha finito.
    started_at: Optional[str]
    finished_at: Optional[str]
    #: Il giro si e' fermato da se' perche' Wikipedia stava rifiutando.
    stopped_early: bool
    #: Prima di questo istante non ha senso ritentare.
    blocked_until: Optional[str]
    #: Autori non riprovati perche' gia' completi o ancora in attesa.
    skipped: int


class RecuperoAvviato(StatoDelRecupero):
    """
    Il giro e' partito. E' lo stato di sopra con una parola in piu'.

    Se un giro era gia' in corso la risposta non e' questa: e' un 409. La
    guardia sta sul server, dove ne' un cambio pagina ne' una seconda
    scheda possono azzerarla.
    """
    status: Literal["started"]


class NienteDaRecuperare(StatoDelRecupero):
    """
    Non c'era niente da fare: tutti gia' completi, o tutti ancora in
    attesa del loro prossimo tentativo.

    **`skipped` qui non e' il conto di adesso.** La risposta si costruisce
    come `{"status": ..., "skipped": appena_contati, **stato_del_giro}`, e
    le chiavi che vengono dopo vincono: quello che arriva e' lo `skipped`
    dell'**ultimo giro fatto girare** — zero se non ne e' mai partito uno.
    Misurato il 05/11/2026: 42 autori saltati, risposta `0`. E' un difetto,
    non una forma da documentare, e nessun client oggi lo legge (la pagina
    Autori prende questo numero da `/scrape-status`).
    """
    status: Literal["nothing_to_do"]


# ── Interventi: la coda di lavoro del catalogo ───────────────────────────
#
# Quindici operazioni, e quasi tutte seguono lo stesso disegno: un `GET` che
# dice **cosa non torna**, e uno o piu' `POST` che fanno la cosa. Niente qui
# dentro agisce da se': ogni elenco e' da confermare, e questo e' il motivo
# per cui le risposte hanno la forma che hanno.

class MotivoDiCopertura(Permissivo):
    """
    «Questo libro l'hai attraversato quasi tutto.»

    E' una **deduzione** dalle sessioni di KOReader, e sbaglia per difetto:
    la soglia e' al 90% proprio perche' l'ultima parte di un libro —
    ringraziamenti, note, indice — spesso non viene letta.
    """
    tipo: Literal["copertura"]
    #: Frazione fra 0 e 1, arrotondata a tre decimali.
    valore: float


class MotivoDiColonna(Permissivo):
    """
    «In una tua colonna c'e' scritto che l'hai letto.»

    Vale molto piu' della copertura: non e' una deduzione, e' **una
    decisione umana gia' presa** — magari anni prima che Kolibre esistesse,
    in una colonna personalizzata di Calibre. Per questo i candidati che
    hanno questo motivo si ordinano per primi.
    """
    tipo: Literal["colonna"]
    #: L'etichetta della colonna, senza il `#`.
    colonna: str
    #: **Stringa**, non il valore grezzo: una data, un `"letto"`, un `1`
    #: tornano tutti qui come testo.
    valore: str


MotivoDaSegnareLetto = Union[MotivoDiCopertura, MotivoDiColonna]


class DaSegnareLetto(Permissivo):
    """
    Un libro che **risulta** letto e non e' ancora spuntato.

    `reasons` non e' decorativo e non e' un elenco di stringhe: ogni motivo
    e' una **forma diversa** con un peso diverso, e nelle due il campo
    `valore` ha due tipi — un numero per la copertura, una stringa per la
    colonna. Era la cosa che un client generato dallo schema non poteva
    indovinare.
    """
    id: int
    title: str
    #: Mai vuoto: senza autore risponde «Unknown Author».
    author: str
    #: Almeno uno: un libro senza motivi non entra nell'elenco.
    reasons: list[MotivoDaSegnareLetto]


class SuggerimentiDaSegnareLetto(Permissivo):
    """
    L'elenco da confermare, **non** una scrittura.

    Questo endpoint non spunta niente: la spunta passa dal solito
    `POST /books/bulk-update`, che e' gia' il modo con cui si scrive una
    colonna personalizzata su piu' libri. Su una biblioteca che non si
    riesce ad aprire risponde una lista vuota e zero, non un errore.
    """
    candidates: list[DaSegnareLetto]
    #: Quanti erano **gia'** spuntati, per dare la misura di quanto manca.
    already_marked: int


class SuggerimentoRipreso(Esito):
    """Quanti suggerimenti rifiutati sono stati rimessi in elenco."""
    ripresi: int


class VoceDiQualita(Permissivo):
    """
    Una delle cinque voci su cui si misura un EPUB, col suo punteggio.

    Oltre al punteggio ogni voce porta i **numeri su cui l'ha dato** — quanti
    file rotti, quante voci d'indice, quanti documenti, quanti byte di CSS —
    e sono diversi da voce a voce: `extra="allow"` li lascia passare tutti,
    e `punteggio` e' l'unico che c'e' sempre. E' la parte che si mostra
    aprendo il dettaglio di un confronto.
    """
    #: Da 0 a 100.
    punteggio: int


class MembroDiUnGruppo(Permissivo):
    """
    Un libro dentro un gruppo di possibili doppioni, con tutto quello che
    serve a decidere quale tenere.

    **Solo gli EPUB si sanno misurare.** Per ogni altro formato `qualita`,
    `qualita_dettaglio` e `leggibile` sono `null` — «non lo so», non zero —
    ed e' esattamente il caso in cui un accorpamento automatico deve
    fermarsi e chiedere.
    """
    library: str
    id: int
    title: Optional[str]
    author: Optional[str]
    formats: list[str]
    #: **Zero** e non `null` per un libro senza formati.
    size: int
    date_added: Optional[str]
    #: Il formato su cui si e' misurata la qualita': il preferito fra quelli
    #: che il libro ha. Nullo se non ha nessun file sul disco.
    formato_principale: Optional[str]
    #: SHA-256 del file principale — **l'hash intero, non quello parziale**:
    #: qui la domanda e' «sono lo stesso file», e la risposta deve essere
    #: una prova, non un indizio.
    hash: Optional[str]
    qualita: Optional[int]
    #: Il perche' del punteggio, voce per voce: le chiavi sono i cinque
    #: criteri (`integrita`, `toc`, `struttura`, `css`, `peso`), e
    #: compaiono tutte o nessuna — su un file che non si apre affatto il
    #: dettaglio e' vuoto.
    qualita_dettaglio: Optional[dict[str, VoceDiQualita]]
    leggibile: Optional[bool]


class AzioniSulGruppo(Permissivo):
    """
    Cosa si puo' fare su questo gruppo, con la **prova** separata
    dall'**indizio**.

    `automatico` e' `true` **solo** quando due file hanno lo stesso
    SHA-256: li' non serve credere a niente, sono lo stesso file, e
    tenerne uno e' una constatazione. In tutti gli altri casi e' `false`
    per quanto netto sia il punteggio, e la ragione e' precisa: la qualita'
    risponde a «quale dei due e' migliore» ma da' per scontato «sono lo
    stesso libro», e quella certezza viene da una somiglianza di titolo
    sopra 0,85 — un indizio forte, non una prova.

    `trattenuti` sono i libri che si sarebbero scartati e **non si
    scartano**, perche' hanno note o sessioni di lettura. Il freno vale per
    cio' che viene *proposto*; una persona che decide a mano puo'
    accorparli comunque, e le note migrano.
    """
    automatico: bool
    #: `identici` quando i file sono uguali byte per byte, `qualita` quando
    #: uno domina gli altri per punteggio. Nullo quando non c'e' niente da
    #: suggerire.
    suggerimento: Optional[Literal["identici", "qualita"]]
    tenere: Optional[int]
    scartare: list[int]
    trattenuti: list[int]


class GruppoDiDoppioni(Permissivo):
    """
    Un gruppo di libri che potrebbero essere lo stesso, **dentro una sola
    biblioteca**.

    Una sola per scelta: lo stesso libro in due biblioteche diverse non e'
    un problema da segnalare — fra una personale e un magazzino la
    sovrapposizione e' il funzionamento normale, ed e' proprio cosi' che un
    libro passa dal secondo alla prima.

    `identici` sono i sottoinsiemi di membri con lo **stesso hash**: una
    lista di liste, perche' un gruppo da quattro puo' contenere due coppie
    di file identici fra loro e diversi dall'altra coppia.
    """
    #: `autore|titolo` normalizzati. Serve a togliere il gruppo dal
    #: risultato conservato quando si decide qualcosa, senza rifare la
    #: ricerca — che e' l'operazione cara.
    chiave: str
    titolo: Optional[str]
    autore: Optional[str]
    membri: list[MembroDiUnGruppo]
    identici: list[list[int]]
    #: Il migliore per qualita', a parita' il formato preferito, a parita'
    #: il piu' grande. Nullo quando nessun membro e' misurabile.
    migliore: Optional[int]
    azioni: AzioniSulGruppo


class RicercaDoppioni(Permissivo):
    """
    L'esito di una ricerca di doppioni, nuova o conservata.

    **La ricerca costa**: si leggono i file dal disco per calcolarne lo
    SHA-256. Per questo il `GET` restituisce quella di prima con la sua
    data, e rifarla e' un `POST` a parte.

    `mai_cercato` distingue «cercato, nessun doppione» da «mai cercato»,
    che per chi guarda sono due cose completamente diverse: la prima e' una
    buona notizia, la seconda e' un lavoro da fare.
    """
    gruppi: list[GruppoDiDoppioni]
    #: Puo' essere maggiore di `len(gruppi)`: l'elenco e' troncato a un
    #: tetto, e `non_mostrati` dice quanti sono rimasti fuori.
    gruppi_totali: int
    non_mostrati: int
    #: Quando e' stata fatta la ricerca conservata. Nullo se mai fatta.
    calcolato_il: Optional[str]
    mai_cercato: bool


class DistintiRegistrati(Esito):
    """Quante coppie «questi due non sono lo stesso libro» sono state
    registrate. Restano registrate: una ricerca successiva non le ripropone."""
    registrate: int


class DoppioniAccorpati(Esito):
    """
    Quanti libri sono stati assorbiti, e quante note sono migrate.

    Le note **non si perdono mai** in un accorpamento: passano al libro
    tenuto. E' il motivo per cui una persona puo' decidere di accorpare un
    libro annotato anche se il sistema non lo proporrebbe mai.
    """
    accorpati: int
    note_migrate: int


class IdenticiAccorpati(DoppioniAccorpati):
    """
    Come sopra, ma per il giro automatico sui soli file identici.

    `lasciati` sono i gruppi che l'automatismo **non ha toccato**: i file
    non erano identici, o tutti i candidati da scartare avevano note o
    sessioni. Dirlo conta — un «fatti 3» senza «lasciati 11» farebbe
    credere di aver finito.
    """
    lasciati: int


class RigaSenzaLibro(Permissivo):
    """
    Un libro che un lettore ha in carico, e che in biblioteca non c'e' piu'.

    **Non e' il difetto delle note vedove**: quelle sono annotazioni rimaste
    senza libro, questa e' una **riga di consegna** rimasta senza libro. Il
    server crede ancora di avere quel libro su quel dispositivo e lo conta
    fra i suoi, e nessuno lo contraddice perche' il lettore non ha modo di
    sapere che in biblioteca e' stato cancellato.
    """
    id: int
    device_id: int
    device_name: str
    #: Serve a non promettere una cancellazione che non avverra': a un
    #: lettore con politica `never` il server non nomina nemmeno le
    #: rimozioni.
    delete_policy: str
    library: str
    calibre_book_id: int
    format: str
    status: str
    device_path: Optional[str]
    #: **Il campo che cambia tutto.** Se e' `true`, quel file sul lettore e'
    #: la copia di un libro **vivo**, riabbinata dal lettore stesso: farlo
    #: cancellare sarebbe un danno, e l'unica cosa sensata e' dimenticare la
    #: riga.
    percorso_di_un_libro_vivo: bool
    created_at: Optional[str]
    updated_at: Optional[str]


class RigheSenzaLibro(Permissivo):
    righe: list[RigaSenzaLibro]
    totale: int


class RigheDimenticate(Esito):
    """Quante righe sono state togliere dal conto del server. **Il file sul
    lettore non si tocca**: dimenticare la riga lo rende «non abbinato», e
    sara' «Inizializza libreria» a proporre cosa farne."""
    dimenticate: int


class RimozioniAccodate(Esito):
    """
    Quante rimozioni sono partite verso il lettore, e quante sono state
    rifiutate.

    Il rifiuto non e' un errore: sono le righe il cui file e' la copia di un
    libro **ancora in biblioteca** (e quelle di un lettore con politica
    `never`). `dimenticabili` porta i loro id, cosi' chi guarda puo' offrire
    l'unica cosa che su quelle righe si puo' fare.
    """
    in_coda: int
    rifiutate: int
    rifiutate_politica: int
    dimenticabili: list[int]


class ImprontaDaRifare(Permissivo):
    """
    Un'impronta registrata che **non descrive il file che c'e'**.

    E' il difetto che fa sparire in silenzio le annotazioni di un libro: il
    dispositivo manda l'impronta del suo file, il server non la riconosce, e
    le note diventano orfane. Qui si vedono prima.
    """
    library: str
    calibre_book_id: int
    format: str
    title: Optional[str]
    registrata: str
    vera: str
    #: Una riga **«verificata»** che sbaglia e' peggio di una forzata a mano
    #: da un accoppiamento: quella e' sbagliata per scelta, questa mente.
    verified: bool


class RigaNonRiconoscibile(Permissivo):
    """
    Un libro che un lettore dichiara di avere, e la cui impronta non si
    risolve da nessuna parte.
    """
    id: int
    device_id: int
    device_name: Optional[str]
    library: Optional[str]
    calibre_book_id: Optional[int]
    format: Optional[str]
    device_path: Optional[str]
    delivery_hash: Optional[str]
    #: Cambia il significato della riga: con l'identita' il libro si
    #: riconosce comunque per nome, e l'impronta che non risolve e' un
    #: difetto di contabilita', non una perdita di dati.
    ha_identita: bool


class RigaSenzaFile(Permissivo):
    """Una riga che parla di un file che non c'e' piu'."""
    library: str
    calibre_book_id: int
    format: str
    title: Optional[str]
    #: Se il libro in biblioteca c'e' ancora, manca solo il file di quel
    #: formato; se non c'e', la riga parla di niente.
    in_biblioteca: bool


class StatoDelLegame(Permissivo):
    """
    Lo stato del controllo «le impronte descrivono i file che ci sono?».

    **Vive sul server e non nel browser**, come il recupero degli autori: la
    guardia «ce n'e' gia' uno in corso» sta qui, dove due schede aperte
    sulla stessa pagina non possono far partire due giri sugli stessi file.

    Le tre categorie hanno **le righe e non solo il conteggio**, e non e' un
    di piu': «due impronte sbagliate» non si ripara, «questi due libri»
    si'.

    `biblioteche_illeggibili` e' il freno di prudenza: una biblioteca che
    non si apre non dice **niente** sui suoi libri, e un disco scollegato
    non deve far dichiarare rotto tutto quello che contiene.
    """
    in_corso: bool
    totale: int
    fatti: int
    #: Quella in lavorazione, nulla quando il giro non sta girando.
    biblioteca: Optional[str]
    da_ricalcolare: list[ImprontaDaRifare]
    non_riconoscibili: list[RigaNonRiconoscibile]
    senza_file: list[RigaSenzaFile]
    #: Solo i nomi delle cartelle.
    biblioteche_illeggibili: list[str]
    iniziato: Optional[str]
    finito: Optional[str]


class ControlloAvviato(Permissivo):
    """
    `avviato` e' `false` quando un controllo era gia' in corso — e non e' un
    errore: lo stato che arriva insieme e' quello del giro che sta
    girando, quindi chi chiama ha comunque quello che gli serve.
    """
    avviato: bool
    stato: StatoDelLegame


class ImpronteRifatte(Esito):
    """
    `non_riuscite` porta i **nomi** e non il numero, per la stessa ragione
    per cui lo stato porta le righe: un elenco di fallimenti si riprova, un
    conteggio no.
    """
    rifatte: int
    gia_a_posto: int
    non_riuscite: list[str]


class RigheSenzaFileDimenticate(Esito):
    """
    `tornate` sono le righe che **non** si sono dimenticate perche' nel
    frattempo il file e' ricomparso: il disco era scollegato, e rimuovere
    quelle righe avrebbe buttato via una contabilita' giusta.
    """
    tolte: int
    tornate: int


# ── Arretrati (ingest) ───────────────────────────────────────────────────

class LibroInArretrato(Permissivo):
    """
    Un file in attesa di essere importato, coi metadati letti dal file
    stesso.

    E' la **stessa forma** che risponde il caricamento dal browser: chi
    carica vede subito le schede, senza rileggere l'elenco.
    """
    id: int
    #: Mai vuoto: senza titolo nei metadati risponde «Unknown Title».
    title: str
    #: Mai vuoto: senza autore risponde «Unknown Author».
    author: str
    #: **Sempre uno solo**: un arretrato e' un file, non un libro con
    #: piu' formati. La lista c'e' per somigliare alla forma di un libro
    #: vero e poter riusare le stesse schede.
    formats: list[str]
    #: **Zero** e non `null` se la dimensione non si e' potuta leggere.
    size: int
    #: Il percorso sul disco del server, nella cartella degli arretrati.
    path: str
    #: Solo il giorno, `YYYY-MM-DD`.
    date_added: str
    #: Valorizzato **solo** per un EPUB che ha una copertina dentro di se':
    #: un PDF o un EPUB senza copertina non ne ha una da mostrare, e qui —
    #: al contrario dei libri in biblioteca — non ce n'e' una costruita.
    cover_url: Optional[str]
    #: **Stringa vuota** e non `null` quando non c'e'.
    description: str
    tags: list[str]
    series: Optional[str]
    series_index: Optional[float]
    language: Optional[str]
    isbn: Optional[str]


class PaginaDiArretrati(Permissivo):
    """
    Una pagina sola. Arriva **solo** se la richiesta passa `limit`: senza,
    l'endpoint risponde l'elenco nudo (una lista, non questo oggetto). Due
    forme dallo stesso indirizzo, nella stessa forma di `/books` — e serve
    al caso vero: una cartella con migliaia di file da rivedere, dove la
    pagina disegna una scheda per ognuno.
    """
    items: list[LibroInArretrato]
    total: int
    offset: int
    limit: int


class FileRifiutato(Permissivo):
    """Un file caricato che non e' stato preso, col perche' scritto per una
    persona: nome non valido, formato non ammesso, troppo grande."""
    filename: str
    reason: str


class ArretratiCaricati(Permissivo):
    """
    Il caricamento dal browser e' **parziale per costruzione**: ogni file e'
    indipendente, e uno rifiutato non ferma gli altri. Per questo la
    risposta ha due liste invece di un esito.
    """
    staged: list[LibroInArretrato]
    rejected: list[FileRifiutato]


class ImportazioneAvviata(Permissivo):
    """Il giro e' partito. Se ce n'era gia' uno in corso la risposta non e'
    questa: e' un 409."""
    status: Literal["started"]
    total: int


class ImportazioneFallita(Permissivo):
    """Un libro che non si e' potuto importare, col suo errore."""
    id: int
    title: Optional[str]
    #: Troncato a 200 caratteri.
    error: str


class StatoImportazione(Permissivo):
    """
    A che punto e' l'importazione in blocco degli arretrati.

    Come il recupero degli autori, **vive sul server**: sopravvive al cambio
    pagina e alla chiusura del browser, e si legge da qualunque scheda.

    `failed` porta **errore per errore** e non solo il conteggio: una
    importazione che fallisce su trenta libri su tremila deve poter dire
    *quali*, o non c'e' modo di rimediare se non riprovando tutto.
    """
    running: bool
    total: int
    processed: int
    #: Quanti sono entrati davvero: `processed` conta anche i falliti.
    imported: int
    failed: list[ImportazioneFallita]
    #: **L'id dell'arretrato in lavorazione, non il suo titolo** — al
    #: contrario di `StatoDelRecupero.current`, che porta il nome
    #: dell'autore. L'avevo dichiarato stringa leggendo il nome del campo,
    #: e il tipo scritto a mano nel browser aveva ragione: `number | null`.
    #: Nullo quando il giro non sta girando.
    current: Optional[int]
    started_at: Optional[str]
    finished_at: Optional[str]
    #: `true` se qualcuno l'ha fermata a mano: distingue «finita» da
    #: «interrotta», che davanti a un elenco incompleto sono due cose
    #: diverse.
    cancelled: bool


class ImportazioneDaFermare(Permissivo):
    """
    `stopping` e' `false` quando non c'era niente da fermare.

    Non c'e' un «fermata»: la richiesta alza una bandierina e il giro si
    ferma fra un libro e l'altro, perche' interrompere a meta' una scrittura
    in biblioteca lascerebbe un libro dimezzato.
    """
    stopping: bool


class LibroSimile(Permissivo):
    """Un libro in biblioteca che somiglia a un file in attesa."""
    id: int
    title: str
    author: Optional[str]
    formats: list[str]


class DoppioniInArrivo(Permissivo):
    """
    Quali file in attesa somigliano a qualcosa che in biblioteca c'e' gia'.

    **Avvisa, non blocca.** Un doppione vero e un'edizione diversa dello
    stesso titolo si somigliano esattamente allo stesso modo, e da qui non
    si possono distinguere: il sistema puo' dire «questo credo di averlo
    gia'», decidere tocca a chi guarda.

    E' un confronto di **metadati**, non di contenuto: l'hash risponde a
    un'altra domanda — «e' lo stesso file» — e due edizioni dello stesso
    libro hanno hash diversi, che e' proprio il caso che si vuole vedere
    prima di importare.
    """
    #: La cartella contro cui si e' confrontato. Nulla se non c'e' nessuna
    #: biblioteca configurata.
    library: Optional[str]
    #: Le chiavi sono gli **id degli arretrati come stringhe** (un oggetto
    #: JSON non ha chiavi numeriche), e i valori al massimo cinque libri.
    #: Un arretrato senza somiglianze non compare affatto.
    duplicati: dict[str, list[LibroSimile]]


class LibroImportato(Esito):
    """L'id che il libro ha preso **in biblioteca**, non quello che aveva
    fra gli arretrati: quella riga a questo punto non c'e' piu'."""
    book_id: int


# ── L'inventario di un lettore ────────────────────────────────────────────
#
# Cosa c'e' davvero nella cartella dei libri di un dispositivo. Nato il
# 05/11/2026 per vedere e pulire i libri presenti in piu' copie, e disegnato
# per restare: il plugin quella camminata la fa gia' in quattro posti e ogni
# volta butta il risultato.

class FileDelDispositivo(Permissivo):
    """
    Un file di libro come sta sul dispositivo, con quello che il suo
    «sidecar» dice della lettura.

    **I campi del sidecar sono la ragione per cui questa forma vale.**
    KOReader tiene la lettura — quanto hai letto, se l'hai finito, le note —
    in una cartella accanto al file. Senza quei numeri «quale delle due
    copie cancello» non ha risposta; con quelli ce l'ha, e misurata: su un
    libro vero le due copie erano 3367 minuti contro 24. Sono tutti nulli
    per un file che non e' mai stato aperto.
    """
    local_path: str
    format: str
    #: Il partial-MD5 di KOReader. **Nullo si puo'**: su un file illeggibile
    #: il calcolo non riesce, e riportare il file senza impronta e' meglio
    #: che non riportarlo.
    file_hash: Optional[str]
    size_bytes: Optional[int]
    #: Frazione fra 0 e 1.
    percent_finished: Optional[float]
    #: `reading`, `complete`, `abandoned` — la risposta che la persona ha
    #: dato alla domanda «segno questo libro come finito?».
    stato_lettura: Optional[str]
    #: Solo il giorno, com'e' scritto nel sidecar.
    stato_modificato: Optional[str]
    #: **Quante**, non quali: l'inventario e' una misura.
    annotazioni: Optional[int]
    pagine: Optional[int]
    ultima_posizione: Optional[str]
    visto_il: Optional[str]


class LibroInPiuCopie(Permissivo):
    """
    Lo stesso libro presente sul dispositivo in **piu' di un file**, con la
    copia da tenere gia' scelta.

    **La scelta non guarda le date.** Misurato sul Kindle di Paolo: in
    quattro coppie su sette la copia aperta piu' di recente era quella con
    **meno** lettura — e «la piu' recente» e' esattamente quella che il
    manifesto del dispositivo tiene in mano. Si tiene quella su cui si e'
    letto: prima le annotazioni (una percentuale si rifa' scorrendo, una
    nota no), poi la percentuale, poi la dimensione.

    `lettura_tenuta` e `lettura_scartata` ci sono perche' **la decisione
    deve restare leggibile**: se una copia ha tutta la lettura e l'altra
    niente, la scelta e' ovvia; se sono vicine — 140 minuti contro 36, un
    caso vero — non lo e', e chi guarda deve poterlo vedere prima di
    confermare.
    """
    library: str
    calibre_book_id: int
    format: str
    tenere: FileDelDispositivo
    #: Mai vuoto: un gruppo con una copia sola non e' un gruppo.
    scartare: list[FileDelDispositivo]
    #: `(annotazioni, frazione letta, byte)`, nell'ordine in cui contano.
    lettura_tenuta: list
    lettura_scartata: list


class GruppoDaGuardare(Permissivo):
    """
    Piu' file che il server riconduce **allo stesso libro**, ma in cui almeno
    uno **non sembra quel libro**. Non e' una proposta: e' una domanda.

    **Il caso vero.** Il 05/11/2026 l'inventario del Kindle di Paolo ha
    trovato venti libri «in doppia copia». Diciannove lo erano. Il ventesimo
    metteva insieme `casa in collina, La.epub` e `Dialoghi con Leuco.epub`:
    due libri diversi, e il primo e' la copia di un altro libro che in
    biblioteca c'e' per conto suo. Il server li aveva uniti per
    un'impronta **archiviata** — che dice «questo file ERA di questo libro»,
    non «E' di questo libro». Senza questo gruppo si sarebbe cancellata la
    copia vera.

    Non porta `tenere` ne' `scartare`: su un gruppo cosi' non si propone
    niente.
    """
    library: str
    calibre_book_id: int
    format: str
    file: list[FileDelDispositivo]
    #: I percorsi il cui nome non corrisponde ai titoli di quel libro.
    sospetti: list[str]


class RiassuntoInventario(Permissivo):
    """
    I numeri che il dispositivo mostra appena ha finito di camminare — ed e'
    anche la misura che prima non esisteva: finche' non c'era, nessuno
    sapeva quanti file ci fossero davvero su quel lettore.
    """
    file_letti: int
    #: Quanti si sono ricondotti a un libro della biblioteca.
    riconosciuti: int
    libri_in_piu_copie: int
    #: Le copie che si cancellerebbero tenendone una per libro.
    copie_in_eccesso: int
    #: Impronta che non risolve. **Non sono candidati alla cancellazione**:
    #: su uno di questi, sul Kindle di Paolo, c'erano cinquantasei ore di
    #: lettura.
    sconosciuti: int
    #: Gli sconosciuti che portano annotazioni: sono quelli da spingere al
    #: server **prima** di toccare qualunque cosa, perche' le loro note
    #: vivono solo sul dispositivo.
    da_salvare: int
    #: Gruppi in cui un file non sembra quel libro. **Non si cancellano**:
    #: su uno di questi, sul Kindle di Paolo, c'era la copia buona di un
    #: libro che la regola avrebbe buttato.
    da_guardare: int


class InventarioRicevuto(Esito):
    """L'inventario e' stato sostituito, e questo e' cosa ci si e' trovato."""
    riassunto: RiassuntoInventario


class InventarioDelDispositivo(Permissivo):
    """
    L'inventario confrontato con quello che il server sa, per la pagina che
    deve decidere.

    Il confronto **non si conserva**: si rifa' a ogni lettura sulle impronte
    di adesso. Conservarlo vorrebbe dire mostrare una decisione presa su
    dati di ieri.
    """
    #: Nullo se quel dispositivo non ha mai mandato un inventario.
    aggiornato_il: Optional[str]
    riassunto: RiassuntoInventario
    doppioni: list[LibroInPiuCopie]
    #: I gruppi su cui il server **non si pronuncia**.
    da_guardare: list[GruppoDaGuardare]
    sconosciuti: list[FileDelDispositivo]
    #: Gli sconosciuti con annotazioni, ripetuti qui perche' sono l'unica
    #: cosa da fare **prima** di cancellare niente.
    da_salvare: list[FileDelDispositivo]


# ── Entita': autori, serie, editori, etichette, lingue ───────────────────
#
# Nove operazioni. La pagina Entita' serve a **pulire i nomi**: su una
# biblioteca cresciuta per importazioni le stesse persone si chiamano in
# cinque modi, e queste risposte sono quello che permette di accorgersene.

class StatoDatiAutore(Permissivo):
    """
    Cosa il server ha di un autore, e se ha mai provato a cercarlo.

    I quattro stati non sono gradi dello stesso: `mai_cercato` e
    `non_trovato` sono due cose diverse — il primo e' un lavoro da fare, il
    secondo e' una risposta — e confonderli vorrebbe dire ripetere per
    sempre le richieste a Wikipedia per autori di cui si sa gia' che non ha
    niente.
    """
    stato: str
    # **Per un autore mai cercato arriva la sola chiave `stato`**, e gli altri
    # cinque campi non compaiono affatto: l'elenco li costruisce solo per chi
    # ha una riga nel database, e per gli altri mette un dizionario con una
    # chiave sola (`entities.py`, il ripiego di `per_nome.get`). Su una
    # biblioteca cresciuta per importazioni quelli sono la maggioranza —
    # quindi la forma «corta» e' il caso normale, non l'eccezione. Trovato
    # dalla prova che valida le risposte vere.
    bio: Optional[bool] = None
    immagine: Optional[bool] = None
    anagrafica: Optional[bool] = None
    #: L'esito dell'ultimo tentativo: `ok`, `no_image`, `no_page`,
    #: `blocked`, `error`. Nullo se si e' provato senza trovare niente.
    esito: Optional[str] = None
    cercato_il: Optional[str] = None


class ValoreDiEntita(Permissivo):
    """
    Un valore (un nome d'autore, un titolo di serie, un'etichetta) con
    quanti libri lo portano e **in quali biblioteche**.

    `dove` e' la ragione per cui questa pagina serve: lo stesso nome scritto
    in due modi in due biblioteche diverse non si vede guardandone una sola.
    """
    #: Uguale a `valore`: c'e' per chi disegna elenchi e vuole una chiave.
    id: str
    valore: str
    libri: int
    #: I nomi **mostrati** delle biblioteche in cui compare.
    dove: list[str]
    #: Se di questo valore il server ha dei dati (per gli autori: una
    #: scheda). Serve a non riproporre un lavoro gia' fatto.
    conosciuto: bool
    #: **Solo per gli autori**, e non c'e' affatto per gli altri tipi.
    dati: Optional[StatoDatiAutore] = None


class ElencoDiEntita(Permissivo):
    """
    Tutti i valori di un tipo. `riepilogo_dati` e' valorizzato **solo per
    gli autori** (per gli altri tipi e' quattro zeri): e' quello che serve a
    decidere se lanciare un recupero e su chi, senza contare a mano.
    """
    tipo: str
    valori: list[ValoreDiEntita]
    #: Dallo stato al numero di autori in quello stato.
    riepilogo_dati: dict[str, int]


class GruppoAffine(Permissivo):
    """
    Valori che **somigliano** fra loro: cinque grafie della stessa persona.

    `suggerito` e' il primo del gruppo, non un verdetto: unire e' una
    decisione, e questo endpoint non la prende.
    """
    suggerito: str
    valori: list[ValoreDiEntita]
    #: La somma dei libri del gruppo — quanto si guadagna a unirlo.
    libri: int


class EntitaAffini(Permissivo):
    tipo: str
    gruppi: list[GruppoAffine]


class CoppiaDistinta(Permissivo):
    """«Questi due non sono la stessa cosa», detto una volta e ricordato."""
    #: Sempre due.
    valori: list[str]
    deciso_da: Optional[str]
    deciso_il: Optional[str]


class DistintiDichiarati(Permissivo):
    tipo: str
    coppie: list[CoppiaDistinta]


class DistintiAnnullati(Esito):
    """Quante dichiarazioni «sono diversi» sono state ritirate: un «no»
    detto per sbaglio non deve essere definitivo."""
    tolte: int


class EntitaUnite(Esito):
    """
    L'esito di un'unione di grafie.

    **Tre campi su cinque non ci sono in un caso solo**: quando l'elenco dei
    valori da assorbire, dopo aver tolto quello da tenere, resta **vuoto** —
    cioe' si e' chiesto di unire un valore con se' stesso. Allora la risposta
    e' `{"status": "ok", "libri_toccati": 0}` e nient'altro. Chiedere di unire
    un valore che non esiste **non** e' quel caso: li' l'unione si fa, tocca
    zero libri, e i cinque campi ci sono tutti.

    `grafie_corrette` conta le **scritture nei metadati**, che possono essere
    piu' dei libri toccati: un libro con due autori da correggere si scrive
    una volta e conta due grafie.
    """
    libri_toccati: int
    grafie_corrette: Optional[int] = None
    #: Le grafie assorbite.
    unite: Optional[list[str]] = None
    #: La grafia tenuta. Si chiama `in` nella risposta, che in Python e' una
    #: parola riservata: da qui l'alias.
    verso: Optional[str] = Field(default=None, alias="in")


class TipoDiEntita(Permissivo):
    """
    Un tipo che si puo' elencare.

    **Solo l'id.** Il nome da mostrare lo mette il client, che sa in che
    lingua lo sta mostrando: qui usciva anche un'etichetta italiana, e
    nessuno la guardava. Vedi `api/entities.tipi_disponibili`.
    """
    id: str


class TipiDiEntita(Permissivo):
    tipi: list[TipoDiEntita]


class OrfanePulite(Esito):
    """
    Quante voci senza nessun libro sono state togliere da Calibre.

    `nomi` e' **tagliato ai primi cinquanta**: serve a far vedere *cosa* si e'
    tolto, non a elencarlo tutto — su una pulizia da duemila voci l'elenco
    intero non lo legge nessuno.
    """
    tolte: int
    nomi: list[str]


class SerieSciolte(Esito):
    """
    Quante serie sono state sciolte, e quante sono diventate un'etichetta.

    I due numeri sono diversi di proposito: sciogliere una serie toglie
    l'appartenenza, e `in_tag` dice su quanti libri quell'informazione e'
    stata **conservata** come etichetta invece di essere buttata.
    """
    libri_toccati: int
    in_tag: int


# ── Strumenti: porte, plugin, patch, log ─────────────────────────────────

class PortaDelServer(Permissivo):
    """
    La porta **pubblica**, che puo' non essere quella su cui il processo
    ascolta: dietro un proxy sono due numeri diversi, e questo e' quello da
    scrivere nella configurazione di un dispositivo.
    """
    #: **Una stringa, non un numero**: il valore arriva da una variabile
    #: d'ambiente (`PUBLIC_BACKEND_PORT`) e nessuno lo converte. Nel browser
    #: non si vede — una stringa in un'interpolazione funziona come un
    #: numero — ma il tipo scritto a mano la' dichiara `number`, e un client
    #: generato che aspetta un intero fallirebbe a decodificarla. Trovato
    #: dalla prova che confronta il tipo dichiarato con quello che arriva.
    port: str


class VersioneDelServer(Permissivo):
    """
    Si risponde **senza autenticazione**, di proposito: serve a controllare
    con un `curl` se il server e' allineato all'ultimo tag, e chiedere di
    accedere per saperlo sarebbe un impiccio senza guadagno. `"dev"` quando
    la versione non e' stata scritta al momento del build.
    """
    version: str


class VersioneDelPlugin(Permissivo):
    """
    La versione di un plugin come sta sul server. **Nulla si puo'**: se il
    file del plugin non si legge, dire «non lo so» e' meglio che inventare
    un numero — un dispositivo che confronta le versioni si fermerebbe
    invece di scaricare a vuoto.
    """
    version: Optional[str]
    #: Cosa cambia in questa versione, nella lingua chiesta — `None` quando
    #: nessuno l'ha scritto. Vedi services/novita.py.
    novita: Optional[str] = None


class ImprontaDiUnFile(Permissivo):
    """L'impronta di un file del plugin e quanto pesa: la seconda serve a
    accorgersi di un download troncato prima di calcolare la prima."""
    sha256: str
    size: int


class ManifestDelPlugin(Permissivo):
    """
    Cosa scaricare per aggiornare un plugin, e con che impronte.

    Si manda un elenco di file e non un archivio perche' **l'ambiente che
    aggiorna non sa scompattare**: KOReader non ha una libreria per gli zip
    disponibile al plugin, e Obsidian aggiorna file per file. Le impronte
    servono ad accorgersi di un download troncato.
    """
    version: Optional[str]
    files: list[str]
    #: Dal percorso del file alla sua **impronta e dimensione**, non alla
    #: sola impronta: l'avevo dichiarata `str` leggendo il nome del campo, e
    #: la prova che valida le risposte vere ha trovato che e' un oggetto.
    checksums: dict[str, "ImprontaDiUnFile"]


class PatchDiKOReader(Permissivo):
    """
    Una userpatch che il server offre. **Non dice se e' installata**: quello
    dipende dal dispositivo, e lo dice `PatchSulDispositivo`.
    """
    file: str
    nome: str
    descrizione: str
    versione: str
    #: Il numero in testa al nome del file: KOReader applica le patch in
    #: quest'ordine.
    priorita: int
    dimensione: int
    sha256: str
    #: Cosa cambia rispetto alla versione installata, **in inglese**: una
    #: patch e' un file unico per tutti. `None` quando nessuno l'ha scritto.
    novita: Optional[str] = None


class ElencoPatch(Permissivo):
    patches: list[PatchDiKOReader]


# ── Travaso di una biblioteca ────────────────────────────────────────────

class BibliotecaTrasferibile(Permissivo):
    """
    Una biblioteca come la vede il plugin Calibre, con la **cartella** e non
    solo il nome mostrato: ogni altro indirizzo per biblioteca vuole la
    cartella, e l'elenco che usa il browser non la espone.
    """
    name: str
    folder_name: str
    fulltext_enabled: bool
    books_count: int
    authors_count: int
    size_bytes: int


class LibroNelManifest(Permissivo):
    """
    Un libro nel manifest di travaso, con tutto quello che serve a
    ricostruirlo in una biblioteca Calibre locale.

    **Qui `cover_url` e' nullo se la copertina non c'e' davvero**, al
    contrario di ogni altra risposta del progetto, dove si risponde quella
    costruita da titolo e autore. E' deliberato: questo manifest serve a
    **copiare**, e una copertina costruita da noi finirebbe scritta dentro la
    biblioteca di destinazione come se fosse vera. Il ripiego visivo vale per
    chi guarda, non per chi copia.

    I valori delle colonne personalizzate (`#letto`, `#pagine`…) arrivano
    insieme agli altri campi: `extra="allow"` li lascia passare, e quali
    esistano lo dice `custom_columns` nel manifest.
    """
    id: int
    title: str
    author: str
    series: Optional[str]
    series_index: Optional[float]
    tags: list[str]
    formats: list[str]
    size: int
    cover_url: Optional[str]
    #: Serve al confronto fra due biblioteche accoppiate: senza, il plugin
    #: non sa distinguere un libro cambiato sul server da uno intatto.
    last_modified: Optional[str]
    rating: Optional[float]
    pubdate: Optional[str]


class FulltextNelManifest(Permissivo):
    """Se l'indice full-text di questa biblioteca si puo' scaricare, e
    quanto pesa. `size_bytes` e' **zero** e non nullo quando non c'e'."""
    available: bool
    size_bytes: int


class ManifestDiBiblioteca(Permissivo):
    """Tutto quello che serve a copiare una biblioteca altrove."""
    folder_name: str
    display_name: str
    custom_columns: list[ColonnaPersonalizzata]
    fulltext: FulltextNelManifest
    books: list[LibroNelManifest]
    total_books: int


class IndiceFulltextRicevuto(Esito):
    bytes: int


class LibroCaricato(Esito):
    """
    L'id che il libro ha preso **nella biblioteca di destinazione**, e quali
    formati sono stati scritti.

    `formats` puo' essere piu' corto di quello che si e' mandato: un formato
    che non si e' potuto scrivere non fa fallire gli altri, e dirlo e'
    l'unico modo di accorgersene.
    """
    book_id: int
    formats: list[str]


# ── Dizionari ────────────────────────────────────────────────────────────

class DefinizioneTrovata(Permissivo):
    """
    Una definizione, **senza salvare niente**: la usa il popup del lettore
    web per mostrare il significato *prima* che la persona decida se tenere
    la parola. Salvarla per mostrarla riempirebbe il vocabolario di parole
    solo guardate.

    `source` dice da dove viene — il dizionario locale o Wiktionary — e non
    e' un dettaglio: una definizione presa dalla rete puo' non essere
    disponibile la prossima volta.
    """
    definition: str
    source: str


class DizionarioConosciuto(Permissivo):
    """
    Un dizionario che il server sa installare, con il suo stato **su questo
    server**.

    `bookname` e `wordcount` arrivano dal file `.ifo` del dizionario e sono
    nulli se non e' installato — o se il file non li dichiara.
    """
    lang: str
    display_name: str
    #: La licenza e la fonte, da mostrare: sono dizionari di altri.
    attribution: str
    installed: bool
    bookname: Optional[str]
    wordcount: Optional[int]


class DizionariConosciuti(Permissivo):
    """Un elenco **unico** di installabili e installati, cosi' la pagina
    mostra una riga per dizionario con l'azione giusta invece di due liste."""
    items: list[DizionarioConosciuto]


class DizionarioInstallato(Esito):
    lang: str
    display_name: str
    bookname: Optional[str]
    wordcount: Optional[int]


# ── Vocabolario ──────────────────────────────────────────────────────────

class ParolaDelVocabolario(Permissivo):
    """
    Una parola cercata, da qualunque parte venga.

    **`id` non e' un numero**: e' `"device:<n>"` o `"web:<n>"`, perche'
    questo elenco mescola due tabelle diverse — le parole che i lettori
    KOReader hanno raccolto e quelle cercate nel lettore web — e due numeri
    uguali da due tabelle diverse non sono la stessa parola. E' il punto in
    cui un client che si fida di `int` si rompe.

    `library` e `calibre_book_id` sono **sempre nulli** per una parola che
    viene da un dispositivo: KOReader sa il titolo del libro, non quale
    libro della biblioteca sia.
    """
    id: str
    source: Literal["device", "web"]
    #: Il nome del dispositivo per le parole dei lettori, **stringa vuota**
    #: per quelle del lettore web.
    source_label: str
    word: str
    highlight: Optional[str]
    book_title: Optional[str]
    library: Optional[str]
    calibre_book_id: Optional[int]
    context_before: Optional[str]
    context_after: Optional[str]
    create_time: Optional[str]
    #: Valorizzati solo da una ricerca esplicita: all'importazione non si
    #: cerca niente.
    definition: Optional[str]
    definition_source: Optional[str]
    definition_fetched_at: Optional[str]


class Vocabolario(Permissivo):
    """Tutte le parole, dal piu' recente: una pagina sola invece di una
    scheda per dispositivo."""
    items: list[ParolaDelVocabolario]


class SovrapposizioneConUnAltro(Permissivo):
    id: int
    nome: str
    #: Quante parole questi due dispositivi hanno in comune.
    parole: int


class DispositivoDelVocabolario(Permissivo):
    """
    Quante parole ha un lettore, e quante ne condivide con gli altri.

    Serve a rispondere a una domanda sola: **vale la pena unificare?** Due
    lettori con molte parole in comune sono la stessa persona che legge in
    due posti; due senza niente in comune sono due vocabolari separati.
    """
    id: int
    nome: str
    parole: int
    #: Solo i dispositivi con cui c'e' davvero qualcosa in comune.
    in_comune: list[SovrapposizioneConUnAltro]


class SovrapposizioniDelVocabolario(Permissivo):
    dispositivi: list[DispositivoDelVocabolario]


# ── I token delle applicazioni ───────────────────────────────────────────

class TokenApplicazioneCreato(Permissivo):
    """
    Il token appena fabbricato, **e questa e' l'unica volta che lo si vede**:
    il server ne conserva l'impronta e non e' in grado di ridirlo. Chi lo
    riceve lo salva subito o lo perde — ed e' il punto, perche' un token che
    il server sa ancora leggere non e' meglio di una password.
    """
    id: int
    nome: str
    #: Comincia per `kolibre_app_`.
    token: str
    creato_il: Optional[str]


class TokenApplicazioneInElenco(Permissivo):
    """
    Un token vivo. **Non porta il token**: non c'e' campo che lo contenga,
    perche' il server non lo ha.

    `ultimo_uso_il` e' la sola cosa che dice se un token serve ancora o e'
    stato dimenticato su un computer che non c'e' piu'. Nullo per uno appena
    creato e mai usato.
    """
    id: int
    nome: str
    creato_il: Optional[str]
    ultimo_uso_il: Optional[str]


class TokenDellApplicazione(Permissivo):
    """I token vivi di questa persona: i revocati non compaiono."""
    items: list[TokenApplicazioneInElenco]
