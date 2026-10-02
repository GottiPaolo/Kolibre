// Ricerca full-text — porting di FulltextSearchModal.vue (frontend/src/
// App.vue, righe ~3858-3880). File separato da queries.ts per lo stesso
// motivo di annotationQueries.ts/deviceQueries.ts: evitare conflitti di
// merge con altre pagine in lavorazione in parallelo.
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { FulltextSearchResult } from '@/types/library'

export async function searchFulltext(
  libraryFolder: string,
  query: string,
  limit = 40
): Promise<FulltextSearchResult[]> {
  const { data, error } = await api.GET('/api/kolibre/fulltext/search', {
    params: { query: { q: query, library: libraryFolder, limit } },
  })
  if (error) throw error
  const results = (data as unknown as { results: FulltextSearchResult[] }).results
  return results
}

export interface FulltextStatus {
  enabled: boolean
  /** Libri con il testo dentro l'indice. */
  indexed: number
  /** Libri nel catalogo della biblioteca. */
  total: number
  progress: { done: number; total: number; running: boolean } | null
  size_bytes: number
  limit_gb: number
  /** L'indice ha raggiunto il tetto: da qui in poi non cresce piu'. */
  limit_reached: boolean
}

// L'endpoint esisteva da sempre e non lo leggeva nessuno. Senza, la ricerca
// full-text puo' coprire meta' biblioteca senza dirlo: l'indicizzazione si
// ferma al tetto configurato (10 GB in un'installazione reale, ~1,6 MB a
// libro) e i libri rimasti fuori semplicemente non compaiono fra i risultati
// — che e' indistinguibile da "quella parola non c'e'".
export function useFulltextStatus(libraryFolder: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ['fulltext-status', libraryFolder],
    enabled: enabled && !!libraryFolder,
    queryFn: async (): Promise<FulltextStatus> => {
      const { data, error } = await api.GET('/api/kolibre/fulltext/status', {
        params: { query: { library: libraryFolder! } },
      })
      if (error) throw error
      return data as unknown as FulltextStatus
    },
  })
}
