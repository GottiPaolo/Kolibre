import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { components } from '@/api/schema'

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
      // **Due forme da un indirizzo**: senza `limit` arriva l'elenco nudo,
      // che è quello che questa query chiede. Se arrivasse una pagina si
      // prendono i suoi elementi invece di buttarla via — stessa regola di
      // `useBooks` per i libri.
      return Array.isArray(data) ? data : data.items
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

/**
 * Se l'elenco degli arretrati va servito a pagine, e con che misura.
 *
 * È **la stessa forma** che risponde `/books/pagination` per i libri di una
 * biblioteca (nel server si chiama `ModoPaginazione`): la stessa domanda su
 * due elenchi diversi. Erano due tipi scritti a mano in due file.
 */
export type IngestPaginationInfo = components['schemas']['ModoPaginazione']

export function useIngestPagination() {
  return useQuery({
    queryKey: ['ingest-pagination'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/ingest/pagination')
      if (error) throw error
      return data
    },
  })
}

/**
 * Una pagina sola di arretrati. Arriva **solo** se la richiesta passa
 * `limit`: senza, l'endpoint risponde l'elenco nudo (una lista, non questo
 * oggetto) — due forme dallo stesso indirizzo, come per `/books`.
 */
export type IngestPage = components['schemas']['PaginaDiArretrati']

export function useIngestPage(opts: { offset: number; limit: number }, abilitata: boolean) {
  return useQuery({
    queryKey: ['ingest-page', opts.offset, opts.limit],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/ingest', {
        params: { query: opts },
      })
      if (error) throw error
      if (Array.isArray(data)) {
        // L'elenco nudo arriva solo chiedendo senza `limit`, cosa che questa
        // query non fa mai. Se arrivasse, sono comunque tutti gli arretrati:
        // si mostrano come pagina unica.
        return { items: data, total: data.length, offset: 0, limit: data.length }
      }
      return data
    },
    enabled: abilitata,
    placeholderData: (precedente) => precedente,
  })
}

// ── Importazione in blocco: vive sul server ───────────────────────────────
//
// Prima era un ciclo nella pagina, e cambiando scheda moriva a meta'. Ora si
// avvia un lavoro sul server e si guarda come va: chiudere il browser non lo
// ferma, e lo stato si puo' interrogare da qualunque pagina. Stessa forma del
// giro di massa sugli autori.

/**
 * A che punto è l'importazione in blocco.
 *
 * `current` è **l'id dell'arretrato in lavorazione, non il suo titolo** —
 * questo tipo scritto a mano lo diceva giusto (`number | null`), e la prima
 * dichiarazione nello schema lo aveva sbagliato leggendo il nome del campo.
 *
 * `failed` porta errore per errore e non un conteggio: un'importazione che
 * fallisce su trenta libri su tremila deve poter dire *quali*.
 */
export type IngestImportJob = components['schemas']['StatoImportazione']

export const INGEST_JOB_KEY = ['ingest-import-job'] as const

export function useIngestImportJob() {
  return useQuery({
    queryKey: INGEST_JOB_KEY,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/ingest/import-job')
      if (error) throw error
      return data
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
  return data
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
export type IngestDuplicato = components['schemas']['LibroSimile']

export function useIngestDuplicati(libraryFolder: string | undefined, abilitata = true) {
  return useQuery({
    queryKey: ['ingest-duplicati', libraryFolder],
    queryFn: async (): Promise<Record<string, IngestDuplicato[]>> => {
      const { data, error } = await api.GET('/api/kolibre/ingest/duplicati', {
        params: { query: libraryFolder ? { library: libraryFolder } : {} },
      })
      if (error) throw error
      return data.duplicati
    },
    enabled: abilitata && !!libraryFolder,
  })
}
