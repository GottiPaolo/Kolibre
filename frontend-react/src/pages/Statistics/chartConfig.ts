import { useEffect, useState } from 'react'
import type { Valori } from '@/lib/i18n'
import { leggiLocale, scriviLocale } from '@/lib/memoriaLocale'

export interface ChartConfig {
  id: string
  label: string
  type: 'library' | 'reading'
}

type Traduci = (chiave: string, valori?: Valori) => string

// Stessi id di App.vue::chartConfigs — e stessa chiave localStorage
// (STATS_CONFIG_STORAGE_KEY) qualche riga più sotto: Vue e React coesistono
// sullo stesso localStorage durante la migrazione (vedi LibraryPage.tsx per
// il precedente identico con kolibre_column_layout_v1), così una visibilità
// già configurata in un'app resta valida nell'altra. Gli `id` restano
// invariati con la lingua (sono la chiave persistita); solo `label` — la
// sola cosa mostrata — è una funzione di `t`, come fixedColumnLabels in
// lib/libraryColumns.ts.
export function chartConfigs(t: Traduci): ChartConfig[] {
  return [
    { id: 'formatShare', label: t('stats.library.chart.formatShare'), type: 'library' },
    { id: 'storageFormat', label: t('stats.library.chart.storageFormat'), type: 'library' },
    { id: 'topAuthors', label: t('stats.library.chart.topAuthors'), type: 'library' },
    { id: 'topSeries', label: t('stats.library.chart.topSeries'), type: 'library' },
    { id: 'pageCount', label: t('stats.library.chart.pageCount'), type: 'library' },
    { id: 'pagesPerAuthor', label: t('stats.library.chart.pagesPerAuthor'), type: 'library' },
    { id: 'storagePerAuthor', label: t('stats.library.chart.storagePerAuthor'), type: 'library' },
    { id: 'ratingDistribution', label: t('stats.library.chart.ratingDistribution'), type: 'library' },
    { id: 'languageDistribution', label: t('stats.library.chart.languageDistribution'), type: 'library' },
    { id: 'topTags', label: t('stats.library.chart.topTags'), type: 'library' },
    // Anagrafica autori da Wikidata — vedi services/author_wikidata.py.
    { id: 'authorGender', label: t('stats.library.chart.authorGender'), type: 'library' },
    { id: 'authorNationality', label: t('stats.library.chart.authorNationality'), type: 'library' },
    { id: 'authorCentury', label: t('stats.library.chart.authorCentury'), type: 'library' },
    { id: 'authorOccupation', label: t('stats.library.chart.authorOccupation'), type: 'library' },
    { id: 'weeklyHistogram', label: t('stats.reading.chart.weeklyHistogram'), type: 'reading' },
    { id: 'weeksHistogram', label: t('stats.reading.chart.weeksHistogram'), type: 'reading' },
    { id: 'readingRecords', label: t('stats.reading.chart.readingRecords'), type: 'reading' },
    { id: 'peakHours', label: t('stats.reading.chart.peakHours'), type: 'reading' },
    // Tolti il 01/10/2026: 'favoriteDays' (giorni preferiti),
    // 'deviceShare' (distribuzione per dispositivo) e
    // 'progressFunnel' (stato lettura). I tre erano grafici a torta, e i loro id
    // possono essere rimasti in un localStorage già scritto: `isVisible` ricade
    // su `true` per gli id che non conosce, quindi una voce morta nello storage
    // non fa niente — non serve una migrazione.
    { id: 'heatmap', label: t('stats.reading.chart.heatmap'), type: 'reading' },
    { id: 'monthlyCalendar', label: t('stats.reading.chart.monthlyCalendar'), type: 'reading' },
    { id: 'monthlyHours', label: t('stats.reading.chart.monthlyHours'), type: 'reading' },
  ]
}

// Solo gli `id` (invarianti con la lingua): seminare i default non ha
// bisogno di `t`, che qui — fuori da un componente, nell'inizializzatore di
// useState — non sarebbe comunque disponibile.
const CHART_CONFIG_IDS = [
  'formatShare', 'storageFormat', 'topAuthors', 'topSeries', 'pageCount',
  'pagesPerAuthor', 'storagePerAuthor', 'ratingDistribution', 'languageDistribution', 'topTags',
  'authorGender', 'authorNationality', 'authorCentury', 'authorOccupation',
  'weeklyHistogram', 'weeksHistogram', 'readingRecords', 'peakHours',
  'heatmap', 'monthlyCalendar', 'monthlyHours',
]

const STORAGE_KEY = 'kolibre_stats_config_v1'

function loadVisibility(): Record<string, boolean> {
  const defaults: Record<string, boolean> = {}
  for (const id of CHART_CONFIG_IDS) defaults[id] = true
  try {
    const saved = JSON.parse(leggiLocale(STORAGE_KEY) || '{}')
    for (const id of CHART_CONFIG_IDS) {
      if (Object.prototype.hasOwnProperty.call(saved, id)) defaults[id] = !!saved[id]
    }
  } catch {
    // storage malformato — restano i default (tutto visibile)
  }
  return defaults
}

export function useChartVisibility() {
  const [visibility, setVisibility] = useState<Record<string, boolean>>(loadVisibility)

  useEffect(() => {
    try {
      scriviLocale(STORAGE_KEY, JSON.stringify(visibility))
    } catch {
      // storage non disponibile — nessuna persistenza, non bloccante
    }
  }, [visibility])

  function isVisible(id: string): boolean {
    return visibility[id] ?? true
  }
  function toggle(id: string) {
    setVisibility((prev) => ({ ...prev, [id]: !(prev[id] ?? true) }))
  }

  return { isVisible, toggle }
}
