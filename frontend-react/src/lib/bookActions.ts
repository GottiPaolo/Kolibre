// Funzioni di scrittura sul libro — porting 1:1 dei payload/endpoint reali
// usati da frontend/src/App.vue (saveMetadata, deleteBook, confirmDeleteFormat,
// applyDownloadedMetadata, startConversion, copyBookToLibrary). Tutti gli
// endpoint /api/kolibre/books richiedono ora l'autenticazione (main.py li
// include con la dipendenza): il client `api` inietta l'header su ogni
// richiesta, mentre i due percorsi che non passano da lui — l'URL di
// download aperto con window.open e il fetch grezzo della conversione —
// devono procurarsi il token da soli, vedi sotto.
import { api, withBackendUrl } from './api'
import { authHeaders, currentAuthToken } from './auth'
import type { Book, MetadataCandidate, TocEntry } from '@/types/library'

export async function updateBookMetadata(
  library: string,
  bookId: number,
  fields: Record<string, unknown>
): Promise<void> {
  const { error } = await api.PUT('/api/kolibre/books/{id}', {
    params: { path: { id: bookId }, query: { library } },
    body: fields,
  })
  if (error) throw error
}

// Gli stessi campi su molti libri, in UNA richiesta: il lavoro vive sul
// server (una transazione sola su metadata.db) invece di essere un ciclo di
// PUT nel browser, che su qualche centinaio di libri vuol dire altrettante
// richieste e un'operazione che muore se si cambia scheda.
export async function bulkUpdateBooksMetadata(
  library: string,
  ids: number[],
  changes: { fields?: Record<string, unknown>; tagsAdd?: string[]; tagsRemove?: string[] }
): Promise<number> {
  const { data, error } = await api.POST('/api/kolibre/books/bulk-update', {
    params: { query: { library } },
    body: {
      ids,
      fields: changes.fields ?? {},
      tags_add: changes.tagsAdd ?? [],
      tags_remove: changes.tagsRemove ?? [],
    },
  })
  if (error) throw error
  return (data as { updated?: number })?.updated ?? 0
}

export async function deleteBook(library: string, bookId: number): Promise<void> {
  const { error } = await api.DELETE('/api/kolibre/books/{id}', {
    params: { path: { id: bookId }, query: { library } },
  })
  if (error) throw error
}

export async function deleteBookFormat(library: string, bookId: number, format: string): Promise<void> {
  const { error } = await api.DELETE('/api/kolibre/books/{id}/formats/{format}', {
    params: { path: { id: bookId, format }, query: { library } },
  })
  if (error) throw error
}

// `token` in query e non in header: questo URL finisce in window.open (e nel
// fetch del reader, che l'header ce l'ha comunque). L'endpoint /download usa
// get_current_user_flexible, che accetta entrambi — stesso schema di
// ingestFileUrl in ingestActions.ts.
export function downloadFormatUrl(library: string, bookId: number, format?: string): string {
  const params = new URLSearchParams({ library })
  if (format) params.set('format', format)
  const token = currentAuthToken()
  if (token) params.set('token', token)
  return withBackendUrl(`/api/kolibre/books/${bookId}/download?${params.toString()}`)
}

/** Come e' andata una delle fonti interrogate. */
export interface EsitoFonte {
  nome: string
  stato: 'ok' | 'quota' | 'errore' | 'lenta'
  dettaglio?: string
}

export async function cercaMetadatiOnline(
  library: string,
  bookId: number
): Promise<{ candidates: MetadataCandidate[]; fonti: EsitoFonte[] }> {
  const { data, error } = await api.GET('/api/kolibre/books/{id}/metadata-search', {
    params: { path: { id: bookId }, query: { library } },
  })
  if (error) throw error
  return data as unknown as { candidates: MetadataCandidate[]; fonti: EsitoFonte[] }
}

/** Solo i candidati, per chi non ha niente da fare con gli esiti delle fonti. */
export async function searchMetadataOnline(library: string, bookId: number): Promise<MetadataCandidate[]> {
  return (await cercaMetadatiOnline(library, bookId)).candidates
}

export interface ApplyMetadataPayload {
  title?: string
  author?: string
  identifiers?: Record<string, string>
  description?: string
  publisher?: string
  language?: string
  tags?: string[]
  pubdate?: string
  cover_url?: string
  [key: string]: unknown
}

export async function applyOnlineMetadata(library: string, bookId: number, payload: ApplyMetadataPayload): Promise<void> {
  const { error } = await api.POST('/api/kolibre/books/{id}/apply-metadata', {
    params: { path: { id: bookId }, query: { library } },
    body: payload,
  })
  if (error) throw error
}

export interface ConvertResult {
  addedAsFormat: boolean
  format?: string
  size?: number
  blob?: Blob
  filename?: string
}

export async function convertBookFormat(
  library: string,
  bookId: number,
  sourceFormat: string,
  targetFormat: string,
  addAsFormat: boolean
): Promise<ConvertResult> {
  if (addAsFormat) {
    const { data, error } = await api.POST('/api/kolibre/books/{id}/convert', {
      params: { path: { id: bookId }, query: { library } },
      body: { source_format: sourceFormat, target_format: targetFormat.toLowerCase(), add_as_format: true },
    })
    if (error) throw error
    const result = data as unknown as { status: string; format: string; size: number }
    return { addedAsFormat: true, format: result.format, size: result.size }
  }

  // Risposta binaria (il file convertito in streaming) — il client
  // openapi-fetch tenterebbe di fare JSON.parse, quindi qui serve un fetch
  // grezzo, stesso baseUrl/URL del client tipizzato.
  const response = await fetch(withBackendUrl(`/api/kolibre/books/${bookId}/convert?library=${encodeURIComponent(library)}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify({ source_format: sourceFormat, target_format: targetFormat.toLowerCase(), add_as_format: false }),
  })
  if (!response.ok) {
    let detail = `Conversione fallita (${response.status})`
    try {
      const body = await response.json()
      if (body?.detail) detail = body.detail
    } catch {
      // risposta non JSON, mantieni il messaggio generico
    }
    throw new Error(detail)
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const match = /filename="?([^"]+)"?/.exec(disposition)
  const blob = await response.blob()
  return { addedAsFormat: false, blob, filename: match?.[1] }
}

export async function copyBookToLibrary(
  sourceFolder: string,
  bookId: number,
  targetFolder: string,
  deleteSource: boolean
): Promise<{ book_id: number; formats: string[] }> {
  const { data, error } = await api.POST('/api/kolibre/library-transfer/{folder}/books/{book_id}/copy-to', {
    params: { path: { folder: sourceFolder, book_id: bookId } },
    body: { target_folder: targetFolder, delete_source: deleteSource },
  })
  if (error) throw error
  return data as unknown as { book_id: number; formats: string[] }
}

export async function saveBookToc(library: string, bookId: number, format: string, entries: TocEntry[]): Promise<void> {
  const { error } = await api.POST('/api/kolibre/books/{id}/toc', {
    params: { path: { id: bookId }, query: { library } },
    body: { format, toc: entries.map(({ title, dest, level }) => ({ title, dest, level })) },
  })
  if (error) throw error
}

export async function generateBookToc(library: string, bookId: number, mode: 'major_headings' | 'all_headings' | 'files'): Promise<TocEntry[]> {
  const { data, error } = await api.POST('/api/kolibre/books/{id}/toc/generate', {
    params: { path: { id: bookId }, query: { library, format: 'EPUB' } },
    body: { mode },
  })
  if (error) throw error
  return (data as unknown as { entries: TocEntry[] }).entries
}

export async function createTocAnchor(
  library: string,
  bookId: number,
  href: string,
  path: number[]
): Promise<string> {
  const { data, error } = await api.POST('/api/kolibre/books/{id}/toc/anchor', {
    params: { path: { id: bookId }, query: { library, format: 'EPUB' } },
    body: { href, path },
  })
  if (error) throw error
  return (data as unknown as { anchor_id: string }).anchor_id
}

export function pickPreferredFormat(formats: string[]): string {
  const priority = ['EPUB', 'MOBI', 'PDF', 'AZW3', 'FB2', 'TXT']
  for (const p of priority) if (formats.includes(p)) return p
  return formats[0]
}

export function resolveBookLibraryFolder(book: Book, libraries: { name: string; folder_name: string }[]): string | undefined {
  return libraries.find((l) => l.name === book._library)?.folder_name
}
