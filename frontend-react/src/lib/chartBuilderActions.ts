// Scrittura per il chart builder (Statistiche → Grafici personalizzati) —
// file separato da statsQueries.ts (che resta di sola lettura, come
// annotationQueries.ts/annotationActions.ts già separano lettura e
// scrittura per Annotazioni).
import { api } from './api'
import type {
  ChartBuilderFilters,
  ChartBuilderGroupBy,
  ChartBuilderMetric,
  ChartBuilderMode,
  ChartBuilderSource,
  ChartBuilderType,
  SavedChart,
} from './statsQueries'

// I campi sono quelli "grezzi" già usati da SavedChart/ChartBuilderConfig
// (definito in pages/Statistics/chartBuilderCompute.ts) — non importato da
// qui per non far dipendere lib/ da pages/, l'inverso di ogni altra
// dipendenza in questo repo.
export interface SavedChartPayload {
  library: string
  name: string
  chartType: ChartBuilderType
  dataSource: ChartBuilderSource
  groupBy: ChartBuilderGroupBy
  metric: ChartBuilderMetric
  groupBySecondary: ChartBuilderGroupBy | null
  chartMode: ChartBuilderMode
  filters: ChartBuilderFilters
  sortBy: 'label' | 'value' | null
  sortOrder: 'asc' | 'desc' | null
}

function toBody(payload: SavedChartPayload) {
  return {
    library: payload.library,
    name: payload.name,
    chart_type: payload.chartType,
    data_source: payload.dataSource,
    group_by: payload.groupBy,
    metric: payload.metric,
    group_by_secondary: payload.groupBySecondary,
    chart_mode: payload.chartMode,
    // Radice vuota ({kind:'group',children:[]}) equivale a "nessun filtro"
    // per il backend (filters_json resta NULL — vedi stats.py::create_saved_chart).
    // Cast: FilterGroup è un'interfaccia con campi noti, lo schema generato
    // da FastAPI (Optional[Dict[str, Any]]) lo tipizza come
    // Record<string, unknown> — stesso valore a runtime (albero JSON-
    // serializzabile), solo una forma nominale diversa per TypeScript, che
    // altrimenti rifiuta il cast diretto per assenza di indice di stringa.
    filters: payload.filters as unknown as Record<string, unknown>,
    sort_by: payload.sortBy,
    sort_order: payload.sortOrder,
  }
}

export async function createSavedChart(payload: SavedChartPayload): Promise<SavedChart> {
  const { data, error } = await api.POST('/api/kolibre/stats/charts', { body: toBody(payload) })
  if (error) throw error
  return data as unknown as SavedChart
}

export async function updateSavedChart(id: number, payload: SavedChartPayload): Promise<SavedChart> {
  const { data, error } = await api.PUT('/api/kolibre/stats/charts/{id}', {
    params: { path: { id } },
    body: toBody(payload),
  })
  if (error) throw error
  return data as unknown as SavedChart
}

export async function deleteSavedChart(id: number): Promise<void> {
  const { error } = await api.DELETE('/api/kolibre/stats/charts/{id}', { params: { path: { id } } })
  if (error) throw error
}
