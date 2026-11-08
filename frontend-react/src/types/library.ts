// Domain types per la pagina Libreria.
//
// **Dal 05/11/2026 i tipi delle risposte di books/libraries NON sono più
// scritti a mano**: arrivano dallo schema generato. Prima lo erano, perché il
// backend non dichiarava la forma di quelle risposte (nello schema
// risultavano `unknown`), e un tipo scritto a mano contro un server che tace
// è una supposizione che invecchia da sola: l'ha dimostrato
// `FulltextStatus`, a cui mancava un campo su quattro — e quel campo il
// server lo mandava da sempre.
//
// Quello che resta scritto a mano qui sotto è deliberato, e di due specie:
// tipi che il server non produce affatto (stato della pagina, forme del
// lettore), e restringimenti che il client sa e lo schema non può dire
// (`icon: 'library' | 'archive'`, `format: 'EPUB' | 'PDF'`) — vedi i commenti
// sui singoli casi.
import type { components } from '@/api/schema'

/**
 * Una biblioteca come la vede **chi sta guardando**: tre dei campi
 * (`canEdit`, `canShare`, `canDelete`) non descrivono la biblioteca ma il
 * permesso di chi ha fatto la richiesta.
 *
 * Lo `icon` lo restringiamo qui: il server manda una stringa e di fatto sono
 * sempre questi due valori (`library` per la prima dell'ordine, `archive`
 * per le altre), ma è una convenzione del server, non un contratto — per
 * questo il restringimento sta da questa parte e non nello schema.
 */
// Intersezione e non `Omit`: questi tipi portano un indice
// `[key: string]: unknown` (il modello sul server lascia passare i campi che
// non dichiara), e `Omit` su un tipo con un indice del genere lo **cancella**
// — `keyof` diventa `string`, e di tutti i campi dichiarati non resta
// niente. Preso così al primo giro: trenta errori che sembravano campi
// mancanti nel server.
export type Library = components['schemas']['Biblioteca'] & {
  icon: 'library' | 'archive'
}

export type CustomColumnDatatype = 'text' | 'enumeration' | 'datetime' | 'float' | 'rating' | 'int' | 'bool'

export interface CustomColumn {
  id: number
  label: string
  name: string
  datatype: CustomColumnDatatype
  display: Record<string, unknown>
}

/**
 * Un libro come arriva nell'elenco.
 *
 * Le colonne personalizzate sono una chiave `#<label>` per ognuna definita
 * nella biblioteca: dinamiche, non elencabili staticamente. Arrivano
 * dall'indice `[key: string]: unknown` che lo schema porta con sé, perché il
 * modello sul server le lascia passare esplicitamente.
 *
 * `cover_url` è **sempre** valorizzato — un libro senza copertina sul disco
 * riceve quella costruita da titolo e autore. `has_cover` dice se è vera:
 * serve a chi deve distinguere («quali libri sono senza copertina»), non a
 * chi la deve mostrare.
 */
export type Book = components['schemas']['LibroInElenco']

/**
 * Le letture di un libro.
 *
 * Due campi si somigliano e non sono la stessa cosa: `fraction_read` è
 * **quanto** si è letto (rileggendo supera 1), `coverage` è **fin dove** si è
 * arrivati (non supera mai 1).
 */
export type BookStats = components['schemas']['StatisticheLibro']

export type TocEntry = components['schemas']['VoceIndice']

/**
 * `format` qui è ristretto a mano: il server manda una stringa, e sono
 * sempre questi due perché l'indice si legge solo da un EPUB o da un PDF
 * (`_resolve_toc_target`). Il restringimento serve a far scegliere al
 * compilatore fra le due forme delle destinazioni, qui sotto.
 */
export type TocResponse = components['schemas']['IndiceLibro'] & {
  format: 'EPUB' | 'PDF'
}

export interface TocDestinationsEpub {
  format: 'EPUB'
  files: { href: string; anchors: string[] }[]
}
export interface TocDestinationsPdf {
  format: 'PDF'
  page_count: number
}
export type TocDestinations = TocDestinationsEpub | TocDestinationsPdf

export interface MetadataCandidate {
  /** 'opera' quando i valori sono della OPERA (Wikidata) e non dell'edizione posseduta. */
  livello?: 'opera'
  source: string
  title: string | null
  author: string
  isbn: string | null
  identifiers: Record<string, string>
  description: string | null
  tags: string[]
  publisher: string | null
  language: string | null
  pubdate: string | null
  pubdate_year: number | null
  cover_url: string | null
}

export type ConvertInfo = components['schemas']['InfoConversione']

// Una riga per libro con almeno una posizione di lettura registrata.
// `percentage` è già la posizione "vincente" tra tutti i dispositivi
// (l'ultimo che ha scritto, stile kosync): nessuna combinazione
// multi-dispositivo da fare lato client.
export type ReadingProgressEntry = components['schemas']['AvanzamentoDiLettura']

// Un risultato di GET /api/kolibre/fulltext/search. `snippet_html` è già
// sicuro da renderizzare direttamente (il backend fa html.escape() sul testo
// grezzo PRIMA di reintrodurre solo i tag <b>/</b> letterali per
// l'evidenziazione — vedi backend/app/api/fulltext.py, _snippet_to_html):
// nessun contenuto del libro può iniettare markup arbitrario.
export interface FulltextSearchResult {
  id: number
  title: string
  author: string
  format: string
  cover_url: string | null
  snippet_html: string
}
