import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { FilterGroup } from '@/pages/Statistics/filterTree'
import type { components } from '@/api/schema'

export type { FilterGroup, FilterRule, FilterDimension } from '@/pages/Statistics/filterTree'

// **Dal 05/11/2026 questi tipi arrivano dallo schema** (`schemas_risposte.py`):
// prima erano scritti a mano sui campi reali di stats_service.py, perché il
// server non dichiarava la forma delle sue risposte. La differenza non è
// estetica: il tipo scritto a mano diceva `decade: string | null` e aveva
// ragione — il modello sul server, scritto nello stesso giorno, l'aveva
// dichiarata numero, e nessuna validazione se n'era accorta perché Pydantic
// converte. Lo ha trovato la prova che confronta i tipi dichiarati con
// quelli che arrivano davvero (`prove/forma_dichiarata_e_quella_vera.py`).

export type ReadingStatsSummary = components['schemas']['RiassuntoLetture']

/**
 * Una sessione di lettura con i metadati del libro già attaccati: è la riga
 * su cui la pagina Statistiche costruisce ogni raggruppamento, e senza i
 * metadati dovrebbe incrociarla con l'elenco dei libri da sola.
 *
 * Su una sessione **orfana** (libro non riconosciuto) `book_id` è nullo e i
 * metadati sono vuoti: non c'è una biblioteca in cui cercarli.
 */
export type ReadingSessionRaw = components['schemas']['SessioneDiLettura']

export type TimelineEntry = components['schemas']['GiornoDiLettura']


// Una riga per sessione orfana (vedi backend/app/models.py::OrphanReadingSession
// e GET /api/kolibre/stats/orphan-sessions) — un md5 riportato dal device che
// non risolve a nessun libro reale. Non scoped per libreria (un libro orfano
// non è ancora in nessuna libreria dal punto di vista di questa risoluzione),
// per questo useOrphanSessions non prende libraryFolder.
export type OrphanReadingSessionRow = components['schemas']['SessioneOrfana']

export function useOrphanSessions() {
  return useQuery({
    queryKey: ['stats-orphan-sessions'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/stats/orphan-sessions')
      if (error) throw error
      return data
    },
  })
}

// ── Grafici salvati (chart builder) ──

export type ChartBuilderType = 'bar' | 'line' | 'pie'
export type ChartBuilderSource = 'raw' | 'timeline'
// Dimensione di raggruppamento — usata sia come asse X (group_by) sia,
// opzionalmente, come "raggruppa per"/serie secondaria (group_by_secondary).
export type ChartBuilderGroupBy =
  | 'day' | 'week' | 'month'
  | 'author' | 'format' | 'device' | 'source' | 'book_title'
  // Dimensioni che arrivano dai metadati del libro: prima il costruttore
  // poteva incrociare solo autore/formato/dispositivo, cioè quasi niente di
  // quello che distingue un libro da un altro.
  | 'series' | 'tag' | 'language' | 'publisher' | 'rating' | 'decade'
// Rilevante solo per bar quando group_by_secondary è impostato: barre
// affiancate (una per sotto-categoria) vs impilate sullo stesso X. Le linee
// con serie secondaria sono sempre "affiancate" (una linea distinta per
// serie, sovrapposte sullo stesso piano) — non hanno un equivalente
// "stacked" sensato, quindi non usano questo campo.
export type ChartBuilderMode = 'grouped' | 'stacked'

// v3: "variabile" asse Y + aggregazione indipendenti, per avere la stessa
// potenza di grafidinamici — Somma/Media/Minimo/Massimo, conteggi distinti.
// agg è rilevante solo quando yVar è 'duration'|'pages_read' (per le altre
// variabili l'aggregazione è implicita: conteggio righe o nunique).
export type ChartBuilderYVar = 'duration' | 'chars_read' | 'pages_read' | 'session_count' | 'distinct_books' | 'distinct_authors'
export type ChartBuilderAgg = 'sum' | 'avg' | 'min' | 'max'
// Persistito lato backend come stringa opaca (SavedChart.metric, mai
// validata — vedi models.py::SavedChart's v3 docstring): valori legacy
// normalizzati da parseMetric() in chartBuilderCompute.ts, valori nuovi
// codificati come "<yVar>:<agg>" per duration/pages_read o come nome nudo
// per le variabili a conteggio.
export type ChartBuilderMetric =
  | 'duration_sum' | 'session_count' | 'pages_sum' // legacy
  | `duration:${ChartBuilderAgg}` | `pages_read:${ChartBuilderAgg}`
  | 'distinct_books' | 'distinct_authors'

// v3: filtri = albero di regole AND/OR annidato (vedi filterTree.ts) invece
// dell'oggetto piatto v1/v2 — nessuna modifica backend necessaria (filters
// resta un blob JSON opaco, vedi models.py::SavedChart's v3 docstring).
// Radice sempre un gruppo (di norma "and", vuoto = nessun filtro).
export type ChartBuilderFilters = FilterGroup

export interface SavedChart {
  id: number
  library: string
  name: string
  chart_type: ChartBuilderType
  data_source: ChartBuilderSource
  group_by: ChartBuilderGroupBy
  metric: ChartBuilderMetric
  group_by_secondary: ChartBuilderGroupBy | null
  chart_mode: ChartBuilderMode
  filters: ChartBuilderFilters | Record<string, unknown> | null // Record<string,unknown> = forma legacy v1/v2, vedi normalizeSavedChartConfig
  sort_by: 'label' | 'value' | null
  sort_order: 'asc' | 'desc' | null
  created_at: string
}

export function useSavedCharts(libraryFolder: string | undefined) {
  return useQuery({
    queryKey: ['stats-charts', libraryFolder],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/stats/charts', {
        params: { query: { library: libraryFolder } },
      })
      if (error) throw error
      return data as SavedChart[]
    },
    enabled: !!libraryFolder,
  })
}

export function useStatsSummary(libraryFolder: string | undefined) {
  return useQuery({
    queryKey: ['stats-summary', libraryFolder],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/stats/summary', {
        params: { query: { library: libraryFolder } },
      })
      if (error) throw error
      return data
    },
    enabled: !!libraryFolder,
  })
}

// Sempre la lista completa (nessun from_/to) — le viste settimana/mese/
// ricerca aggregano client-side sullo stesso fetch, stessa filosofia del
// Vue esistente (vedi App.vue::loadReadingStats).
export function useStatsRaw(libraryFolder: string | undefined) {
  return useQuery({
    queryKey: ['stats-raw', libraryFolder],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/stats/raw', {
        params: { query: { library: libraryFolder } },
      })
      if (error) throw error
      return data
    },
    enabled: !!libraryFolder,
  })
}

/**
 * I libri spuntati come letti, con l'anagrafica di chi li ha scritti.
 *
 * Senza `libraryFolder`, e non per dimenticanza: «quanti libri ho letto» non è
 * una proprietà di una cartella. Vedi stats_service.libri_letti per perché non
 * può venire dalle sessioni di lettura — una sessione sa quanto hai letto, non
 * se hai finito.
 */
export function useLibriLetti() {
  return useQuery({
    queryKey: ['stats-libri-letti'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/stats/libri-letti', {})
      if (error) throw error
      return data
    },
  })
}

export function useStatsTimeline(libraryFolder: string | undefined, days = 365) {
  return useQuery({
    queryKey: ['stats-timeline', libraryFolder, days],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/stats/timeline', {
        params: { query: { library: libraryFolder, days } },
      })
      if (error) throw error
      return data
    },
    enabled: !!libraryFolder,
  })
}
