// Domain types per la pagina Libreria. Il backend non dichiara response_model
// sugli endpoint books/libraries/custom-columns (vedi schema.d.ts: risposte
// tipate "unknown"), quindi questi tipi sono scritti a mano sulla base dei
// campi reali prodotti da backend/app/api/books.py, libraries.py e
// custom_columns.py — non generati da OpenAPI.

export interface Library {
  id: number
  name: string
  folder_name: string
  path: string
  icon: 'library' | 'archive'
  // Chi la possiede, e chi la vede. Fino al 28/09/2026 `visibleUsers` era la
  // stringa fissa ["paolo", "ospite"]: un segnaposto che raccontava una
  // condivisione inesistente.
  owner?: string | null
  visibleUsers: string[]
  // Cosa può farci chi sta guardando — serve a nascondere i comandi invece
  // di offrirli e poi rispondere 403.
  canEdit?: boolean
  canShare?: boolean
  canDelete?: boolean
  fulltextEnabled: boolean
  books_count: number
  authors_count: number
  size_bytes: number
}

export type CustomColumnDatatype = 'text' | 'enumeration' | 'datetime' | 'float' | 'rating' | 'int' | 'bool'

export interface CustomColumn {
  id: number
  label: string
  name: string
  datatype: CustomColumnDatatype
  display: Record<string, unknown>
}

export interface Book {
  id: number
  title: string
  author: string
  series: string | null
  series_index: number | null
  tags: string[]
  identifiers: Record<string, string>
  publisher: string | null
  language: string | null
  description: string | null
  title_sort: string
  author_sort: string
  uuid: string
  pubdate: string | null
  last_modified: string | null
  formats: string[]
  size: number
  rating: number | null
  date_added: string | null
  // Sempre valorizzato: un libro senza copertina sul disco riceve quella
  // costruita al volo da titolo e autore. has_cover dice se è vera — serve
  // a chi deve distinguere (es. "quali libri sono senza copertina"), non a
  // chi la deve mostrare.
  cover_url: string | null
  has_cover?: boolean
  _library?: string
  // Colonne personalizzate: una chiave `#<label>` per ogni custom column
  // definita nella libreria — dinamico, non elencabile staticamente.
  [key: string]: unknown
}

export interface BookStats {
  total_time_seconds: number
  total_sessions: number
  total_pages_read: number
  /** Quanto LIBRO è stato letto, da 0 a 1 (può superare 1 rileggendo). */
  fraction_read: number | null
  /** Caratteri letti, quando il conteggio del libro è noto. */
  chars_read: number | null
  /** Quanta PARTE del libro è stata vista almeno una volta, da 0 a 1.
   *  Diverso da fraction_read: quello è quanto si è letto (rileggendo
   *  supera 1), questo è fin dove si è arrivati (non supera mai 1). */
  coverage: number | null
  first_read: string | null
  last_read: string | null
  daily_sessions: { date: string; total_seconds: number }[]
  highlights_count: number
}

export interface TocEntry {
  title: string
  dest: string
  level: number
  valid?: boolean
}

export interface TocResponse {
  format: 'EPUB' | 'PDF'
  entries: TocEntry[]
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

export interface ConvertInfo {
  available: boolean
  path: string | null
  version: string | null
  supported_targets: string[]
}

// Una riga per libro con almeno una posizione di lettura registrata — vedi
// GET /api/kolibre/books/reading-progress. `percentage` è già la posizione
// "vincente" tra tutti i dispositivi (l'ultimo che ha scritto, stile
// kosync): nessuna combinazione multi-dispositivo da fare lato client.
export interface ReadingProgressEntry {
  calibre_book_id: number
  percentage: number
  device_name: string | null
  updated_at: string | null
}

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
