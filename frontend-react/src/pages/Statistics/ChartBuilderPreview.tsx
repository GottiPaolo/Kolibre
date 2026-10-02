import { BarChart } from '@/components/charts/BarChart'
import { LineChart } from '@/components/charts/LineChart'
import { PieChart } from '@/components/charts/PieChart'
import { useLingua } from '@/lib/i18n'
import { EmptyNote } from './StatBar'
import { formatDurationHuman } from './statsCompute'
import { parseMetric, type ChartBuilderConfig, type ChartSeriesResult } from './chartBuilderCompute'

// Estratto da ChartBuilderPage.tsx (era locale a quel file) per essere
// riusabile anche fuori dalla pagina del costruttore — vedi ReadingStatsTab,
// che renderizza i grafici salvati in una sezione dedicata. Import diretto
// da ChartBuilderPage avrebbe trascinato l'intera pagina (e il suo chunk
// lazy-loaded) dentro il bundle di Statistiche Lettura.
//
// Rendering condiviso tra l'anteprima live del builder e le mini-anteprime
// dei grafici salvati — stessa conversione di unità già usata da
// ReadingStatsTab per i widget fissi (minuti pre-divisi per Bar/Line con
// yUnit='min', secondi grezzi + valueFormatter per Pie, vedi PieChart.tsx).
// Consuma un ChartSeriesResult (1+ serie) invece del vecchio ChartPoint[] a
// dimensione singola — buildChartSeries ricade comunque su un'unica serie
// "sintetica" quando non c'è raggruppamento secondario, quindi il percorso
// senza serie resta visivamente identico a prima.
export function ChartBuilderPreview({ config, result, height = 220 }: { config: ChartBuilderConfig; result: ChartSeriesResult; height?: number }) {
  const { t } = useLingua()
  if (result.labels.length === 0) return <EmptyNote>{t('stats.chartBuilder.noDataForFilters')}</EmptyNote>

  const isDuration = parseMetric(config.metric).yVar === 'duration'
  const toDisplay = (v: number) => (isDuration ? Math.round(v / 60) : v)

  if (config.chartType === 'pie') {
    // La torta non ha mai una serie secondaria (buildChartSeries la
    // ignora per chartType==='pie'), quindi in pratica qui non arriva mai
    // un null — ?? 0 solo per restare coerenti col tipo ora condiviso con
    // le barre.
    const single = result.series[0]
    return (
      <PieChart
        labels={result.labels}
        data={single ? single.data.map((v) => v ?? 0) : []}
        height={height}
        valueFormatter={isDuration ? formatDurationHuman : undefined}
      />
    )
  }

  if (config.chartType === 'line') {
    return (
      <LineChart
        labels={result.labels}
        series={result.series.map((s) => ({ label: s.label, data: s.data.map((v) => (v == null ? 0 : toDisplay(v))) }))}
        valueSuffix={isDuration ? ' min' : ''}
        height={height}
      />
    )
  }

  return (
    <BarChart
      labels={result.labels}
      // null (bucket assente per questa serie, non zero reale) propagato
      // intatto — BarChart lo passa a Chart.js così com'è, che lo esclude
      // sia dal disegno della barra sia (via tooltip.filter) dal tooltip:
      // passando sopra una colonna si vedono solo le serie che quella
      // colonna ha davvero.
      datasets={result.series.map((s) => ({ label: s.label, data: s.data.map((v) => (v == null ? null : toDisplay(v))) }))}
      stacked={result.series.length > 1 && config.chartMode === 'stacked'}
      yUnit={isDuration ? 'min' : ''}
      showLegend={result.series.length > 1}
      height={height}
    />
  )
}
