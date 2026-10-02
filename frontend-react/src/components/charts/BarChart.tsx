import { useMemo } from 'react'
import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Tooltip,
  type TooltipItem,
} from 'chart.js'
import { Bar } from 'react-chartjs-2'
import { useStyleVariant } from '@/lib/useStyleVariant'
import { numeroCompatto, t } from '@/lib/i18n'

ChartJS.register(BarElement, CategoryScale, LinearScale, Legend, Tooltip)

// Stesso helper di LineChart.tsx (non condiviso da un modulo comune per non
// introdurre un file che esporta sia componenti che funzioni — vedi il
// warning "only-export-components" già tollerato altrove in questo repo per
// i file ui/* di shadcn, ma qui evitabile con una duplicazione di 4 righe).
function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

// Golden-angle (~137.5°) HSL generator invece di una palette fissa — porting
// diretto di frontend/src/ChartWidget.vue::goldenColor. Serve per colorare
// un numero di serie che varia a runtime (un dataset per libro letto, "Top 8
// + Altro"), che una manciata di --chart-N fisse non potrebbe coprire senza
// ripetersi.
function goldenColor(index: number, alpha = 1): string {
  const hue = (index * 137.5) % 360
  return `hsla(${hue}, 65%, 55%, ${alpha})`
}

function fmtVal(value: number, yUnit: '' | 'min' | 'h' | 'car'): string {
  if (yUnit === 'min') {
    const v = Math.round(value)
    const h = Math.floor(v / 60)
    const m = v % 60
    return h > 0 ? `${h}h ${m}m` : `${m}m`
  }
  if (yUnit === 'h') return `${Math.round(value)}h`
  // I caratteri si contano a milioni: "1400000" sull'asse occupa spazio per
  // dire male quello che "1,4 M" dice bene.
  if (yUnit === 'car') {
    return numeroCompatto(Math.round(value))
  }
  return String(value)
}

export interface BarChartDataset {
  label: string
  // null = questa serie non ha alcun dato in quel punto dell'asse X
  // (bucket assente, distinto da un valore zero reale) — vedi
  // chartBuilderCompute.ts::buildChartSeries. Chart.js non disegna una
  // barra per un valore null e tooltip.filter (sotto) lo esclude anche dal
  // tooltip, così l'hover su una colonna mostra solo le serie presenti lì.
  data: (number | null)[]
}

interface BarChartProps {
  labels: string[]
  datasets: BarChartDataset[]
  stacked?: boolean
  yUnit?: '' | 'min' | 'h' | 'car'
  height?: number
  showLegend?: boolean
}

// Istogramma multi-serie (impilato o affiancato), ispirato alla vista
// statistiche di KoServer — stesso ruolo di ChartWidget.vue in modalità
// type="bar" quando questa pagina lo usa per gli andamenti settimanale/
// mensile di lettura, colorati per libro.
export function BarChart({ labels, datasets, stacked = false, yUnit = '', height = 220, showLegend = true }: BarChartProps) {
  const { variant } = useStyleVariant()
  // `variant` non è usato dentro cssVar: serve da INNESCO. I token
  // stanno nel DOM, non in una variabile, quindi l'unico modo di
  // rileggerli al cambio di stile è far ricalcolare la memo. Il linter
  // lo vede come superfluo perché guarda i riferimenti, non gli effetti.
  /* eslint-disable react-hooks/exhaustive-deps */
  const border = useMemo(() => cssVar('--border', '#e5e7eb'), [variant])
  const textFaint = useMemo(() => cssVar('--text-faint', cssVar('--muted-foreground', '#94a3b8')), [variant])
  /* eslint-enable react-hooks/exhaustive-deps */

  const data = {
    labels,
    datasets: datasets.map((ds, i) => ({
      label: ds.label,
      data: ds.data,
      backgroundColor: goldenColor(i, stacked ? 0.9 : 0.6),
      borderRadius: stacked ? 0 : 4,
      borderWidth: 0,
    })),
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: showLegend, labels: { color: textFaint, boxWidth: 10, font: { size: 11 } } },
      tooltip: {
        mode: 'index' as const,
        intersect: false,
        // Con "mode: index" Chart.js elencherebbe una riga per OGNI
        // dataset a quell'indice X, incluse le serie senza alcun dato lì
        // (raw === null, vedi BarChartDataset sopra) — questo filtro le
        // esclude, così passando sopra una colonna si vedono solo colori e
        // nomi delle serie realmente presenti in quella colonna, non di
        // tutto il grafico. Chart.js applica filter PRIMA di costruire gli
        // "items" passati a footer, quindi il totale impilato sotto resta
        // corretto.
        filter: (item: TooltipItem<'bar'>) => item.raw != null,
        callbacks: {
          label: (ctx: TooltipItem<'bar'>) => `${ctx.dataset.label}: ${fmtVal(ctx.parsed.y ?? 0, yUnit)}`,
          footer: stacked
            ? (items: TooltipItem<'bar'>[]) =>
                t('stats.chart.total', { valore: fmtVal(items.reduce((sum, it) => sum + (it.parsed.y ?? 0), 0), yUnit) })
            : undefined,
        },
      },
    },
    scales: {
      x: { stacked, grid: { display: false }, ticks: { color: textFaint, font: { size: 10 } } },
      y: {
        stacked,
        grid: { color: border },
        ticks: {
          color: textFaint,
          font: { size: 10 },
          // Senza `precision: 0` Chart.js divide anche un intervallo di un
          // minuto in dieci tacche frazionarie, e `fmtVal` le arrotonda tutte
          // alla stessa etichetta: l'asse diceva "1m 1m 1m 1m 0m 0m 0m" e
          // sembrava rotto. I valori qui sono sempre interi — minuti o
          // caratteri — quindi non si perde niente.
          precision: 0,
          callback: (v: string | number) => fmtVal(Number(v), yUnit),
        },
        beginAtZero: true,
      },
    },
  }

  return (
    <div style={{ height }}>
      <Bar data={data} options={options} />
    </div>
  )
}
