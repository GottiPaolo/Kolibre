import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type {
  Book,
  BookStats,
  ConvertInfo,
  CustomColumn,
  Library,
  ReadingProgressEntry,
  TocDestinations,
  TocResponse,
} from '@/types/library'
import type { AuthorBook, AuthorDetail, AuthorSummary } from '@/types/author'

// staleTime: Infinity — the library list only ever changes via an explicit
// user action (create/import/edit/delete a library), and every one of those
// call sites already invalidates ['libraries'] itself (CreateLibraryDialog,
// LibraryEditDialog, LibrariesTab, ImportLibraryDialog, ImportTab,
// BulkOperationsTab). Read on nearly every page via the sidebar/Layout, so avoiding
// a background refetch on every mount/window-focus (React Query's default)
// removes a network round trip from the critical path with no staleness
// risk, same reasoning as useConvertInfo below.
export function useLibraries() {
  return useQuery({
    queryKey: ['libraries'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/libraries')
      if (error) throw error
      return data as unknown as Library[]
    },
    staleTime: Infinity,
  })
}

// Fattorizzata (non solo useBooks) perché useBookLookup.ts deve interrogare
// più librerie in parallelo con esattamente la stessa queryKey/queryFn, per
// condividere la cache invece di duplicare la fetch.
export function booksQueryOptions(libraryFolder: string | undefined, abilitata = true) {
  return {
    queryKey: ['books', libraryFolder],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/books', {
        params: { query: { library: libraryFolder } },
      })
      if (error) throw error
      return data as unknown as Book[]
    },
    enabled: !!libraryFolder && abilitata,
  }
}

// L'elenco COMPLETO: filtro e ordinamento restano client-side. È quello che
// serve alle pagine che ragionano sull'intera biblioteca (Statistiche,
// Serie, i selettori di libro) e alla pagina Libreria finché i libri sono
// pochi. Oltre una certa taglia non regge — 9,4 secondi e 66 MB misurati su
// 100.000 libri — e la pagina Libreria passa a useBooksPage qui sotto.
// `abilitata=false` serve proprio a quello: non scaricare l'intera
// biblioteca quando si sta per chiederne una pagina.
export function useBooks(libraryFolder: string | undefined, abilitata = true) {
  return useQuery(booksQueryOptions(libraryFolder, abilitata))
}

// ── Biblioteche grandi ───────────────────────────────────────────────────

export interface LibraryPaginationInfo {
  total: number
  paginated: boolean
  page_size: number
  mode: 'auto' | 'always' | 'never'
  threshold: number
}

/** Se per questa biblioteca si impagina. Conta con un COUNT(*), non legge i libri. */
export function useLibraryPagination(libraryFolder: string | undefined) {
  return useQuery({
    queryKey: ['books-pagination', libraryFolder],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/books/pagination', {
        params: { query: { library: libraryFolder } },
      })
      if (error) throw error
      return data as unknown as LibraryPaginationInfo
    },
    enabled: !!libraryFolder,
  })
}

export interface BooksPage {
  items: Book[]
  total: number
  offset: number
  limit: number
}

/** Una pagina di libri, già filtrata e ordinata dal server. */
export function useBooksPage(
  libraryFolder: string | undefined,
  opts: { offset: number; limit: number; sort: string; order: 'asc' | 'desc'; q: string },
  abilitata: boolean
) {
  return useQuery({
    queryKey: ['books-page', libraryFolder, opts.offset, opts.limit, opts.sort, opts.order, opts.q],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/books', {
        params: { query: { library: libraryFolder, ...opts } },
      })
      if (error) throw error
      return data as unknown as BooksPage
    },
    enabled: !!libraryFolder && abilitata,
    // Tenere la pagina precedente mentre arriva la prossima evita che la
    // tabella sfarfalli a vuoto ad ogni cambio pagina o lettera digitata.
    placeholderData: (precedente: BooksPage | undefined) => precedente,
  })
}

// Un solo giro per libreria per la colonna "Avanzamento" della tabella
// Libreria, invece di un giro per libro visibile.
export function useReadingProgress(libraryFolder: string | undefined) {
  return useQuery({
    queryKey: ['reading-progress', libraryFolder],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/books/reading-progress', {
        params: { query: { library: libraryFolder } },
      })
      if (error) throw error
      return data as unknown as ReadingProgressEntry[]
    },
    enabled: !!libraryFolder,
  })
}

// staleTime: Infinity — same reasoning as useLibraries above: only changes
// via explicit create/delete/repair in LibraryEditDialog, which already
// invalidates ['custom-columns', folderName] itself on every one of those
// paths (invalidateColumns(), called after every mutation in that file).
export function useCustomColumns(libraryFolder: string | undefined) {
  return useQuery({
    queryKey: ['custom-columns', libraryFolder],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/custom-columns', {
        params: { query: { library: libraryFolder } },
      })
      if (error) throw error
      return data as unknown as CustomColumn[]
    },
    enabled: !!libraryFolder,
    staleTime: Infinity,
  })
}

export function useBookStats(libraryFolder: string | undefined, bookId: number | undefined) {
  return useQuery({
    queryKey: ['book-stats', libraryFolder, bookId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/books/{id}/stats', {
        params: { path: { id: bookId! }, query: { library: libraryFolder } },
      })
      if (error) throw error
      return data as unknown as BookStats
    },
    enabled: !!libraryFolder && !!bookId,
  })
}

export function useBookDescription(libraryFolder: string | undefined, bookId: number | undefined) {
  return useQuery({
    queryKey: ['book-description', libraryFolder, bookId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/books/{id}/description', {
        params: { path: { id: bookId! }, query: { library: libraryFolder } },
      })
      if (error) throw error
      return (data as unknown as { description: string | null }).description
    },
    enabled: !!libraryFolder && !!bookId,
  })
}

export function useConvertInfo() {
  return useQuery({
    queryKey: ['convert-info'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/books/convert-info')
      if (error) throw error
      return data as unknown as ConvertInfo
    },
    staleTime: Infinity,
  })
}

export function useBookToc(libraryFolder: string | undefined, bookId: number | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['book-toc', libraryFolder, bookId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/books/{id}/toc', {
        params: { path: { id: bookId! }, query: { library: libraryFolder } },
      })
      if (error) throw error
      return data as unknown as TocResponse
    },
    enabled: !!libraryFolder && !!bookId && enabled,
  })
}

export function useTocDestinations(
  libraryFolder: string | undefined,
  bookId: number | undefined,
  format: string | undefined,
  enabled: boolean
) {
  return useQuery({
    queryKey: ['toc-destinations', libraryFolder, bookId, format],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/books/{id}/toc/destinations', {
        params: { path: { id: bookId! }, query: { library: libraryFolder, format } },
      })
      if (error) throw error
      return data as unknown as TocDestinations
    },
    enabled: !!libraryFolder && !!bookId && !!format && enabled,
  })
}

export async function fetchTocDestinationContent(
  libraryFolder: string,
  bookId: number,
  href: string,
  format: string
): Promise<string> {
  const { data, error } = await api.GET('/api/kolibre/books/{id}/toc/destinations/content', {
    params: { path: { id: bookId }, query: { library: libraryFolder, href, format } },
    parseAs: 'text',
  })
  if (error) throw error
  return data as unknown as string
}

// Autori: sempre cross-libreria (list_authors/get_author_books scandiscono
// tutte le librerie sul server) — nessun parametro `library` da passare.
// `library` (folder_name) restringe l'elenco agli autori di quella
// biblioteca — vedi lib/authorsScope.ts per dove viene scelto e perché la
// scelta deve valere anche nella scheda del singolo autore.
export function useAuthors(library?: string | null) {
  return useQuery({
    queryKey: ['authors', library ?? null],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/authors', {
        params: { query: library ? { library } : {} },
      })
      if (error) throw error
      return data as unknown as AuthorSummary[]
    },
  })
}

export function useAuthorDetail(name: string | undefined) {
  return useQuery({
    queryKey: ['author', name],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/authors/{name}', {
        params: { path: { name: name! } },
      })
      if (error) throw error
      return data as unknown as AuthorDetail
    },
    enabled: !!name,
  })
}

export function useAuthorBooks(name: string | undefined, library?: string | null) {
  return useQuery({
    queryKey: ['author-books', name, library ?? null],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/authors/{name}/books', {
        params: { path: { name: name! }, query: library ? { library } : {} },
      })
      if (error) throw error
      return data as unknown as AuthorBook[]
    },
    enabled: !!name,
  })
}

/** Soglia oltre cui la pagina Autori si divide in pagine. */
export function useAuthorsPagination() {
  return useQuery({
    queryKey: ['authors-pagination'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/settings/authors-pagination', {})
      if (error) throw error
      return data as unknown as { mode: 'auto' | 'always' | 'never'; threshold: number; page_size: number }
    },
    staleTime: 60_000,
  })
}

// ── I valori veri del Navigatore ──────────────────────────────────────────
//
// Il Navigatore costruiva il suo albero dai libri CARICATI: sopra la soglia
// di impaginazione erano duecento, e l'albero elencava i valori di quella
// pagina spacciandoli per quelli della biblioteca — una voce "Autore" con
// dodici nomi su quattromila. Qui arrivano quelli veri, contati da SQLite.
//
// La query fa parte della chiave: i valori si restringono insieme ai libri,
// che è quello che ci si aspetta da un navigatore a faccette.
export interface ValoreCampo {
  valore: string
  libri: number
}

export function useValoriDeiCampi(libraryFolder: string | undefined, q: string, abilitata: boolean) {
  return useQuery({
    queryKey: ['valori-campi', libraryFolder, q],
    enabled: abilitata && !!libraryFolder,
    queryFn: async (): Promise<Record<string, ValoreCampo[]>> => {
      const { data, error } = await api.GET('/api/kolibre/books/valori', {
        params: { query: { library: libraryFolder!, q } },
      })
      if (error) throw error
      return (data as unknown as { campi: Record<string, ValoreCampo[]> }).campi
    },
  })
}
