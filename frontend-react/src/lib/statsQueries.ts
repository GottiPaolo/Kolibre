import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { LibroLetto } from '@/pages/Statistics/statsCompute'
import type { FilterGroup } from '@/pages/Statistics/filterTree'

export type { FilterGroup, FilterRule, FilterDimension } from '@/pages/Statistics/filterTree'

// Il backend non dichiara response_model su questi tre endpoint (vedi
// schema.d.ts: "application/json": unknown) — tipi scritti a mano sulla
// base dei campi reali prodotti da backend/app/services/stats_service.py
// (compute_summary / compute_raw / compute_timeline), verificati con una
// chiamata live durante lo sviluppo di questa fase.

export interface ReadingStatsSummary {
  total_time_seconds: number
  total_books: number
  total_books_completed: number
  total_pages: number
  /** Caratteri letti in totale, dove il conteggio del libro è noto. */
  total_chars: number
  /** Tempo delle sole sessioni che hanno un conteggio caratteri — è su
   *  questo che va divisa la velocità, non sul tempo totale. */
  chars_time_seconds: number
  year_time_seconds: number
  year_books: number
  year_pages: number
  best_day_seconds: number
  longest_session_seconds: number
  longest_book_title: string | null
  longest_book_pages: number
  best_year: number | null
  best_year_books: number
  longest_book_by_time_title: string | null
  longest_book_by_time_seconds: number
  top_author_by_time_name: string | null
  top_author_by_time_seconds: number
  longest_streak_days: number
  longest_streak_start: string | null
  longest_streak_end: string | null
}

export interface ReadingSessionRaw {
  date: string
  start_time: string
  book_id: number | null
  book_title: string
  author: string
  format: string
  device_name: string
  source: string
  duration_seconds: number
  pages_read: number
  /** Caratteri letti in questa sessione. 0 quando non è calcolabile. */
  chars_read: number
  // I metadati del libro letto, che viaggiano con la sessione (vedi
  // stats_service._book_meta_map): sono quello che permette di incrociare
  // "quanto ho letto" con "cosa possiedo". `null` dove il metadato manca
  // davvero — la metà dei libri non ha tag — e sempre vuoti sulle sessioni
  // orfane, che non hanno una biblioteca in cui cercarli.
  series: string | null
  /** Al più i primi tre, per non gonfiare la cache: vedi _MAX_TAG_PER_LIBRO. */
  tags: string[]
  language: string | null
  publisher: string | null
  /** 0-5 stelle, come nel resto dell'applicazione (Calibre la tiene 0-10). */
  rating: number | null
  /** Decennio di pubblicazione, es. "1860". */
  decade: string | null
}

export interface TimelineEntry {
  date: string
  total_seconds: number
}

// Una riga per sessione orfana (vedi backend/app/models.py::OrphanReadingSession
// e GET /api/kolibre/stats/orphan-sessions) — un md5 riportato dal device che
// non risolve a nessun libro reale. Non scoped per libreria (un libro orfano
// non è ancora in nessuna libreria dal punto di vista di questa risoluzione),
// per questo useOrphanSessions non prende libraryFolder.
export interface OrphanReadingSessionRow {
  id: number
  device_id: number
  md5: string
  title: string | null
  authors: string | null
  series: string | null
  start_time: string
  duration: number
  pages_read: number
}

export function useOrphanSessions() {
  return useQuery({
    queryKey: ['stats-orphan-sessions'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/stats/orphan-sessions')
      if (error) throw error
      return data as unknown as { count: number; sessions: OrphanReadingSessionRow[] }
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
      return data as unknown as SavedChart[]
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
      return data as unknown as ReadingStatsSummary
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
      return data as unknown as ReadingSessionRaw[]
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
      return data as unknown as { libri: LibroLetto[]; totale: number; senza_anagrafica: string[] }
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
      return data as unknown as TimelineEntry[]
    },
    enabled: !!libraryFolder,
  })
}
