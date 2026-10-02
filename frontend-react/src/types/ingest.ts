// Domain types per la sezione Ingest/Import (Fase 7). Il backend non
// dichiara response_model su questi endpoint (vedi schema.d.ts: risposte
// tipate "unknown"), quindi — come per types/library.ts — questi tipi sono
// scritti a mano sui campi reali prodotti da backend/app/api/ingest.py
// (_serialize_ingest_item), non generati da OpenAPI.

// Formati ebook accettati sia dal watcher (services/watcher.py) sia dal
// gate più stretto dell'upload web (EBOOK_EXTENSIONS in
// services/library_scanner.py) — letterale qui come nel Vue esistente
// (INGEST_ACCEPT), usato solo per l'hint dell'<input accept="...">.
export const INGEST_ACCEPT = '.epub,.pdf,.mobi,.azw3,.azw,.fb2,.txt'

export interface IngestedBook {
  id: number
  title: string
  author: string
  formats: string[]
  size: number
  path: string
  date_added: string
  // Popolato solo per EPUB con una cover-image nel manifest OPF (vedi
  // services/metadata_parser.py) — null per PDF/altri formati o per un EPUB
  // senza copertina propria: IngestCard mostra un placeholder in quel caso.
  cover_url: string | null
  description: string
  tags: string[]
  series: string | null
  series_index: number | null
  language: string | null
  isbn: string | null
}

export interface IngestRejectedFile {
  filename: string
  reason: string
}

export interface IngestUploadResult {
  staged: IngestedBook[]
  rejected: IngestRejectedFile[]
}
