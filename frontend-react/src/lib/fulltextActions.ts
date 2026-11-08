// Ricerca full-text — porting di FulltextSearchModal.vue (frontend/src/
// App.vue, righe ~3858-3880). File separato da queries.ts per lo stesso
// motivo di annotationQueries.ts/deviceQueries.ts: evitare conflitti di
// merge con altre pagine in lavorazione in parallelo.
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { components } from '@/api/schema'
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
  // Niente asserzione scritta a mano: da quando l'endpoint dichiara la sua
  // forma (04/11/2026, `backend/app/schemas_risposte.py`) il tipo arriva
  // dallo schema generato.
  return data.results as FulltextSearchResult[]
}

/**
 * Lo stato dell'indice, **dallo schema** e non riscritto a mano.
 *
 * Il tipo che c'era qui aveva tre campi su quattro dentro `progress`: gli
 * mancava `stopped_by_limit`, che il server manda da sempre per dire «mi sono
 * fermata perche' l'indice ha raggiunto il tetto». Nessuno lo sapeva, e
 * TypeScript lo avrebbe rifiutato — e' il genere di cosa che una risposta
 * senza forma dichiarata nasconde: non si cerca un campo che non si sa di
 * poter cercare.
 */
export type FulltextStatus = components['schemas']['FulltextStato']

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
      return data
    },
  })
}
