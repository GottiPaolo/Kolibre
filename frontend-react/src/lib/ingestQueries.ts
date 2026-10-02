import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { IngestedBook } from '@/types/ingest'

// Stessa chiave sia qui sia in ingestActions.ts (invalidazione dopo
// upload/import) — se in futuro la sidebar vuole un badge col conteggio
// staging (Vue: badge: () => ingestBooks.value.length), questa stessa hook
// condivide già la cache, nessun endpoint/query aggiuntivo necessario.
export const INGEST_QUERY_KEY = ['ingest'] as const

// GET /api/kolibre/ingest fa anche da poll-on-request fallback lato backend
// (_scan_ingest_folder) per i file già presenti nella cartella ingest prima
// che il watcher partisse.
export function useIngestBooks(abilitata = true) {
  return useQuery({
    queryKey: INGEST_QUERY_KEY,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/ingest')
      if (error) throw error
      return data as unknown as IngestedBook[]
    },
    enabled: abilitata,
  })
}

// ── Tante cose da rivedere ────────────────────────────────────────────────
//
// Ogni voce in Ingest e' una scheda con copertina, metadati e quattro
// comandi: qualche centinaio e la pagina e' gia' pesante, e chi svuota una
// cartella di arretrati ne ha migliaia. Oltre la soglia (Impostazioni ▸
// Sistema) si chiede una pagina per volta.

export interface IngestPaginationInfo {
  total: number
  paginated: boolean
  page_size: number
  mode: 'auto' | 'always' | 'never'
  threshold: number
}

export function useIngestPagination() {
  return useQuery({
    queryKey: ['ingest-pagination'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/ingest/pagination')
      if (error) throw error
      return data as unknown as IngestPaginationInfo
    },
  })
}

export interface IngestPage {
  items: IngestedBook[]
  total: number
  offset: number
  limit: number
}

export function useIngestPage(opts: { offset: number; limit: number }, abilitata: boolean) {
  return useQuery({
    queryKey: ['ingest-page', opts.offset, opts.limit],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/ingest', {
        params: { query: opts },
      })
      if (error) throw error
      return data as unknown as IngestPage
    },
    enabled: abilitata,
    placeholderData: (precedente: IngestPage | undefined) => precedente,
  })
}

// ── Importazione in blocco: vive sul server ───────────────────────────────
//
// Prima era un ciclo nella pagina, e cambiando scheda moriva a meta'. Ora si
// avvia un lavoro sul server e si guarda come va: chiudere il browser non lo
// ferma, e lo stato si puo' interrogare da qualunque pagina. Stessa forma del
// giro di massa sugli autori.

export interface IngestImportJob {
  running: boolean
  total: number
  processed: number
  imported: number
  failed: Array<{ id: number; title: string; error: string }>
  current: number | null
  started_at: string | null
  finished_at: string | null
  cancelled: boolean
}

export const INGEST_JOB_KEY = ['ingest-import-job'] as const

export function useIngestImportJob() {
  return useQuery({
    queryKey: INGEST_JOB_KEY,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/ingest/import-job')
      if (error) throw error
      return data as unknown as IngestImportJob
    },
    // Si interroga spesso solo mentre lavora: a riposo una volta ogni tanto
    // basta per accorgersi di un lavoro avviato da un'altra scheda.
    refetchInterval: (q) => ((q.state.data as IngestImportJob | undefined)?.running ? 1000 : 15000),
  })
}

export async function startIngestImportJob(body: {
  ids?: number[]
  library?: string
  per_item?: Record<string, string>
}): Promise<{ total: number }> {
  const { data, error } = await api.POST('/api/kolibre/ingest/import-job', { body })
  if (error) throw error
  return data as unknown as { total: number }
}

export async function stopIngestImportJob(): Promise<void> {
  const { error } = await api.POST('/api/kolibre/ingest/import-job/stop', {})
  if (error) throw error
}

// ── Forse ce l'hai già ────────────────────────────────────────────────────
//
// Quali file in attesa somigliano a qualcosa che nella biblioteca di
// destinazione c'è già. **Avvisa, non blocca**: un doppione vero e
// un'edizione diversa dello stesso titolo si somigliano esattamente allo
// stesso modo, e da qui non si possono distinguere — il sistema può dire
// "questo credo di averlo già", decidere tocca a chi guarda.
//
// Stesso criterio del motore dei doppioni (services/duplicates.py), così un
// file segnalato qui e un libro che la pagina doppioni raggrupperebbe dopo
// l'importazione sono la stessa cosa.
export interface IngestDuplicato {
  id: number
  title: string
  author: string | null
  formats: string[]
}

export function useIngestDuplicati(libraryFolder: string | undefined, abilitata = true) {
  return useQuery({
    queryKey: ['ingest-duplicati', libraryFolder],
    queryFn: async (): Promise<Record<string, IngestDuplicato[]>> => {
      const { data, error } = await api.GET('/api/kolibre/ingest/duplicati', {
        params: { query: libraryFolder ? { library: libraryFolder } : {} },
      })
      if (error) throw error
      return (data as unknown as { duplicati: Record<string, IngestDuplicato[]> }).duplicati
    },
    enabled: abilitata && !!libraryFolder,
  })
}
