import { useMemo } from 'react'
import { ArcElement, Chart as ChartJS, Legend, Tooltip, type TooltipItem } from 'chart.js'
import { Pie } from 'react-chartjs-2'
import { useStyleVariant } from '@/lib/useStyleVariant'

ChartJS.register(ArcElement, Legend, Tooltip)

// Stesso helper di BarChart.tsx/LineChart.tsx (duplicato, non condiviso —
// vedi il commento di BarChart.tsx sul perché di questa scelta).
function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

// Stessa palette golden-angle di BarChart.tsx (frontend/src/ChartWidget.vue::
// goldenColor) così le fette di una torta e le barre di un istogramma non
// stonano se affiancate nella stessa dashboard.
function goldenColor(index: number, alpha = 1): string {
  const hue = (index * 137.5) % 360
  return `hsla(${hue}, 65%, 55%, ${alpha})`
}

interface PieChartProps {
  labels: string[]
  data: number[]
  height?: number
  valueFormatter?: (value: number) => string
}

// Torta per distribuzioni categoriche a poche fette che sommano al 100% del
// totale (formato, lingua, dispositivo, giorni feriali/weekend...) — dove
// StatBarRow (barre orizzontali indipendenti) rende bene un ranking, la torta
// rende meglio "che quota del totale" perché lo si vede in un colpo solo.
export function PieChart({ labels, data, height = 220, valueFormatter }: PieChartProps) {
  const { variant } = useStyleVariant()
  // `variant` non è usato dentro cssVar: serve da INNESCO. I token
  // stanno nel DOM, non in una variabile, quindi l'unico modo di
  // rileggerli al cambio di stile è far ricalcolare la memo. Il linter
  // lo vede come superfluo perché guarda i riferimenti, non gli effetti.
  /* eslint-disable react-hooks/exhaustive-deps */
  const textFaint = useMemo(() => cssVar('--text-faint', cssVar('--muted-foreground', '#94a3b8')), [variant])
  const cardBg = useMemo(() => cssVar('--card', '#ffffff'), [variant])
  /* eslint-enable react-hooks/exhaustive-deps */

  const chartData = {
    labels,
    datasets: [
      {
        data,
        backgroundColor: labels.map((_, i) => goldenColor(i, 0.85)),
        borderColor: cardBg,
        borderWidth: 2,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'right' as const,
        labels: { color: textFaint, boxWidth: 10, font: { size: 11 } },
      },
      tooltip: {
        callbacks: {
          label: (ctx: TooltipItem<'pie'>) => {
            const value = (ctx.parsed as number) ?? 0
            const total = (ctx.dataset.data as number[]).reduce((a, b) => a + b, 0) || 1
            const percent = Math.round((value / total) * 100)
            const valueLabel = valueFormatter ? valueFormatter(value) : String(value)
            return `${ctx.label}: ${valueLabel} (${percent}%)`
          },
        },
      },
    },
  }

  return (
    <div style={{ height }}>
      <Pie data={chartData} options={options} />
    </div>
  )
}
