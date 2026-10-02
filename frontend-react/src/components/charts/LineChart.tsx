import { useMemo } from 'react'
import { CategoryScale, Chart as ChartJS, Filler, Legend, LinearScale, LineElement, PointElement, Tooltip, type TooltipItem } from 'chart.js'
import { Line } from 'react-chartjs-2'
import { useStyleVariant } from '@/lib/useStyleVariant'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Legend, Tooltip, Filler)

// Letti dai token CSS già definiti in index.css (uno per stile — Sake/
// Museo/Carta) così il grafico segue lo stile attivo invece di colori fissi
// scelti a caso.
//
// Riletti al cambio di stile, non solo al mount: la Fase 8 è arrivata
// (Impostazioni ▸ Aspetto), e lì lo stile si cambia da una modale SOPRA la
// pagina — i grafici non si rimontano, quindi griglia (--border) ed etichette
// (--text-faint) restavano del tema precedente su una scheda dell'altro. La
// dipendenza è `variant` di useStyleVariant, che cambia a ogni scelta.
function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

// Stessa palette golden-angle di BarChart.tsx/PieChart.tsx (duplicata, non
// condivisa — vedi il commento di BarChart.tsx sul perché) — usata solo
// quando ci sono più serie (chart builder con "raggruppa per"); una singola
// serie resta colorata con --primary come prima, per non cambiare l'aspetto
// dei widget esistenti (StatsPanel.tsx) che passano solo `points`.
function goldenColor(index: number): string {
  const hue = (index * 137.5) % 360
  return `hsla(${hue}, 65%, 55%, 1)`
}

export interface LineChartPoint {
  label: string
  value: number
}

export interface LineChartSeries {
  label: string
  data: number[]
}

interface LineChartProps {
  // Singola serie (retrocompatibile, usato da StatsPanel.tsx per il tempo
  // cumulativo di un libro) — ignorato se `series` è passato.
  points?: LineChartPoint[]
  // Multi-serie (chart builder con dimensione secondaria: una linea per
  // sotto-categoria, sovrapposte sullo stesso asse X) — richiede `labels`
  // condivise fra tutte le serie.
  labels?: string[]
  series?: LineChartSeries[]
  valueSuffix?: string
  height?: number
}

// Serie storica a pallini collegati da linee, ispirata alla vista
// statistiche di KoServer — pensata per progressioni cumulative (es. tempo
// di lettura totale nel tempo) o per confrontare più andamenti nel tempo
// (chart builder). Con una sola serie la legenda resta nascosta (nulla da
// distinguere); con più di una viene mostrata automaticamente.
export function LineChart({ points, labels, series, valueSuffix = '', height = 180 }: LineChartProps) {
  const { variant } = useStyleVariant()
  // `variant` non è usato dentro cssVar: serve da INNESCO. I token
  // stanno nel DOM, non in una variabile, quindi l'unico modo di
  // rileggerli al cambio di stile è far ricalcolare la memo. Il linter
  // lo vede come superfluo perché guarda i riferimenti, non gli effetti.
  /* eslint-disable react-hooks/exhaustive-deps */
  const primary = useMemo(() => cssVar('--primary', '#3b82f6'), [variant])
  const border = useMemo(() => cssVar('--border', '#e5e7eb'), [variant])
  const textFaint = useMemo(() => cssVar('--text-faint', cssVar('--muted-foreground', '#94a3b8')), [variant])
  /* eslint-enable react-hooks/exhaustive-deps */

  const resolvedLabels = series ? labels ?? [] : (points ?? []).map((p) => p.label)
  const resolvedSeries: LineChartSeries[] = series ?? [{ label: '', data: (points ?? []).map((p) => p.value) }]
  const showLegend = resolvedSeries.length > 1

  const data = {
    labels: resolvedLabels,
    datasets: resolvedSeries.map((s, i) => {
      const color = showLegend ? goldenColor(i) : primary
      return {
        label: s.label,
        data: s.data,
        borderColor: color,
        backgroundColor: color,
        pointBackgroundColor: color,
        pointBorderColor: color,
        pointRadius: 3,
        pointHoverRadius: 5,
        borderWidth: 2,
        tension: 0.25,
        fill: false,
      }
    }),
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: showLegend, labels: { color: textFaint, boxWidth: 10, font: { size: 11 } } },
      tooltip: {
        mode: showLegend ? ('index' as const) : undefined,
        intersect: false,
        callbacks: {
          label: (ctx: TooltipItem<'line'>) => (showLegend ? `${ctx.dataset.label}: ${ctx.parsed.y}${valueSuffix}` : `${ctx.parsed.y}${valueSuffix}`),
        },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { color: textFaint, font: { size: 10 }, maxRotation: 0, autoSkip: true },
      },
      y: {
        grid: { color: border },
        ticks: { color: textFaint, font: { size: 10 } },
        beginAtZero: true,
      },
    },
  }

  return (
    <div style={{ height }}>
      <Line data={data} options={options} />
    </div>
  )
}
