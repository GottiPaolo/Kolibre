import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useStatsRaw, useStatsSummary, useStatsTimeline, useSavedCharts } from '@/lib/statsQueries'
import { formatDate, isoLocale } from '@/lib/format'
import { BarChart } from '@/components/charts/BarChart'
import { numeroCompatto, useLingua, type Valori } from '@/lib/i18n'
import { ChartCard, RecordRow, StatBarRow } from './StatBar'
import { ChartBuilderPreview } from './ChartBuilderPreview'
import { AnnotationIntensity } from './AnnotationIntensity'
import { HeatmapCalendar } from './HeatmapCalendar'
import { ReadingCalendar } from './ReadingCalendar'
import { GlobalReadingStats } from './GlobalReadingStats'
import { buildChartSeries, normalizeSavedChartConfig } from './chartBuilderCompute'
import {
  monthLabels,
  weekdayLabels,
  buildHeatmapDays,
  buildStackedByBookDatasets,
  currentStreakDays,
  etichettaSettimana,
  formatDurationHuman,
  inizioSettimanaDi,
  peakHoursBuckets,
  readingSpeedCharsPerHour,
  readingSpeedPagesPerHour,
  unitaMisura,
  weekDates,
  weekStarts,
  type Misura,
} from './statsCompute'
import type { useChartVisibility } from './chartConfig'
import type { ReadingSessionRaw } from '@/lib/statsQueries'

type Traduci = (chiave: string, valori?: Valori) => string

const SAGE = 'var(--chart-2)'

/** Quante settimane guarda l'istogramma delle settimane. */
const SETTIMANE = 10

/**
 * Minuti o caratteri.
 *
 * Due bottoni e non un menù: sono due, e un menù per due voci costa un clic in
 * più per nascondere l'unica alternativa. Scelta del 01/10/2026.
 */
function ScambiaMisura({ misura, onChange }: { misura: Misura; onChange: (m: Misura) => void }) {
  const { t } = useLingua()
  return (
    <div className="flex items-center gap-1">
      <Button variant={misura === 'minuti' ? 'secondary' : 'ghost'} size="xs" onClick={() => onChange('minuti')}>
        {t('stats.reading.unit.minutes')}
      </Button>
      <Button variant={misura === 'caratteri' ? 'secondary' : 'ghost'} size="xs" onClick={() => onChange('caratteri')}>
        {t('stats.reading.unit.chars')}
      </Button>
    </div>
  )
}

// ── Il periodo ──────────────────────────────────────────────────────────

export type Periodo = 'sempre' | 'anno' | 'ultimi12' | 'ultimi30'

function periodi(t: Traduci): { value: Periodo; label: string }[] {
  return [
    { value: 'sempre', label: t('stats.reading.period.always') },
    { value: 'anno', label: t('stats.reading.period.thisYear') },
    { value: 'ultimi12', label: t('stats.reading.period.last12Months') },
    { value: 'ultimi30', label: t('stats.reading.period.last30Days') },
  ]
}

function inizioPeriodo(periodo: Periodo): string | null {
  const oggi = new Date()
  if (periodo === 'anno') return `${oggi.getFullYear()}-01-01`
  const d = new Date(oggi)
  if (periodo === 'ultimi12') d.setFullYear(d.getFullYear() - 1)
  else if (periodo === 'ultimi30') d.setDate(d.getDate() - 29)
  else return null
  return isoLocale(d)
}

function filtraPerPeriodo(righe: ReadingSessionRaw[], periodo: Periodo): ReadingSessionRaw[] {
  const da = inizioPeriodo(periodo)
  return da ? righe.filter((r) => r.date >= da) : righe
}

// Un numero grande, per le tre cose che si guardano davvero.
function Grande({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-card px-4 py-3">
      <p className="font-serif text-[26px] leading-none font-semibold tabular-nums">{value}</p>
      <p className="mt-1.5 text-[11px] text-muted-foreground">{label}</p>
    </div>
  )
}

interface ReadingStatsTabProps {
  libraryFolder: string | undefined
  visibility: ReturnType<typeof useChartVisibility>
}

// Un numero di caratteri si legge solo abbreviato: "1,2 M" dice quello che
// "1.203.918" non dice.
function formatCaratteriCompatto(n: number): string {
  return numeroCompatto(n)
}

export function ReadingStatsTab({ libraryFolder, visibility }: ReadingStatsTabProps) {
  const { t } = useLingua()
  const navigate = useNavigate()
  const { isVisible } = visibility
  const { data: summary } = useStatsSummary(libraryFolder)
  const { data: raw = [] } = useStatsRaw(libraryFolder)
  // Grafici personalizzati (costruiti in Statistiche → Grafici Personalizzati)
  // — sezione sempre visibile in fondo, non passa per isVisible/CHART_CONFIGS
  // (widget dinamici con id numerico, non statico) — un grafico appena
  // salvato si deve ritrovare qui subito, senza dover attivare nulla.
  const { data: savedCharts = [] } = useSavedCharts(libraryFolder)
  const { data: timeline = [] } = useStatsTimeline(libraryFolder, 365)

  const [weekOffset, setWeekOffset] = useState(0)
  const [yearOffset, setYearOffset] = useState(0)
  const [periodo, setPeriodo] = useState<Periodo>('sempre')
  // Una misura sola per i due istogrammi: sono due tagli della stessa domanda,
  // e cambiarne una sola darebbe due unità nella stessa schermata.
  const [misura, setMisura] = useState<Misura>('minuti')

  // Un periodo solo per tutta la pagina.
  //
  // Prima ogni grafico aveva il suo "quando": l'istogramma le sue frecce
  // settimanali, il grafico mensile il suo anno, la heatmap i suoi 365
  // giorni fissi. Tre modi diversi di dire la stessa cosa nella stessa
  // schermata, e nessuno che valesse per tutto.
  //
  // Restano fuori l'istogramma settimanale e quello mensile: per loro la
  // navigazione nel tempo non e' un filtro, e' il loro modo di esistere.
  const rawPeriodo = useMemo(() => filtraPerPeriodo(raw, periodo), [raw, periodo])
  const tuttoIlTempo = periodo === 'sempre'

  // Con un periodo attivo i numeri si ricalcolano dalle sessioni filtrate
  // invece di leggere il riassunto del server, che parla sempre di tutto.
  // Mostrare gli uni accanto agli altri darebbe due scale nella stessa
  // schermata senza dirlo — che e' esattamente il difetto appena corretto
  // nelle statistiche sugli autori.
  const totali = useMemo(() => {
    if (tuttoIlTempo) {
      return {
        secondi: summary?.total_time_seconds || 0,
        caratteri: summary?.total_chars || 0,
        libri: summary?.total_books_completed || 0,
        etichettaLibri: t('stats.reading.booksFinished'),
        sessionePiuLunga: summary?.longest_session_seconds || 0,
        giornataMigliore: summary?.best_day_seconds || 0,
      }
    }
    const perGiorno = new Map<string, number>()
    for (const s of rawPeriodo) perGiorno.set(s.date, (perGiorno.get(s.date) || 0) + s.duration_seconds)
    return {
      secondi: rawPeriodo.reduce((t, s) => t + s.duration_seconds, 0),
      caratteri: rawPeriodo.reduce((t, s) => t + (s.chars_read || 0), 0),
      // "Finiti" non ha una data: la spunta `letto` non dice QUANDO. In un
      // periodo si contano quelli aperti, e l'etichetta lo dichiara.
      libri: new Set(rawPeriodo.map((s) => s.book_id ?? s.book_title)).size,
      etichettaLibri: t('stats.reading.booksOpened'),
      sessionePiuLunga: rawPeriodo.reduce((m, s) => Math.max(m, s.duration_seconds), 0),
      giornataMigliore: Math.max(0, ...perGiorno.values()),
    }
  }, [tuttoIlTempo, summary, rawPeriodo, t])

  const weekDays = useMemo(() => weekDates(weekOffset), [weekOffset])
  const weekLabel = weekOffset === 0 ? t('stats.reading.thisWeek') : `${weekDays[0]} — ${weekDays[6]}`
  const weekDatasets = useMemo(
    () => buildStackedByBookDatasets(weekDays, raw, (s) => s.date, t, misura),
    [weekDays, raw, misura, t]
  )

  const settimane = useMemo(() => weekStarts(SETTIMANE), [])
  const weeksDatasets = useMemo(
    () => buildStackedByBookDatasets(settimane, raw, (s) => inizioSettimanaDi(s.date), t, misura),
    [settimane, raw, misura, t]
  )

  const monthYear = new Date().getFullYear() + yearOffset
  // Solo la lunghezza (12) serve qui: le etichette vere arrivano da
  // monthLabels(t) più sotto, non da questo array di chiavi giorno/mese.
  const monthKeys = useMemo(() => Array.from({ length: 12 }, (_, i) => String(i + 1).padStart(2, '0')), [])
  const monthDatasets = useMemo(() => {
    const sessionsInYear = raw.filter((s) => s.date.startsWith(String(monthYear)))
    return buildStackedByBookDatasets(monthKeys, sessionsInYear, (s) => s.date.slice(5, 7), t)
  }, [raw, monthYear, monthKeys, t])

  const peakHours = useMemo(() => peakHoursBuckets(rawPeriodo, t), [rawPeriodo, t])
  const streak = useMemo(() => currentStreakDays(raw), [raw])
  const speed = useMemo(() => readingSpeedPagesPerHour(summary), [summary])
  // Caratteri all'ora quando c'e' abbastanza materiale, pagine altrimenti:
  // una "pagina" di KOReader dipende dal corpo del carattere, quindi come
  // velocita' non si puo' confrontare con niente — nemmeno con se stessa
  // dopo aver cambiato font.
  const speedChars = useMemo(() => readingSpeedCharsPerHour(summary), [summary])
  const heatmapDays = useMemo(() => buildHeatmapDays(timeline, 365), [timeline])

  return (
    <div className="flex flex-col gap-4">
      {/* Un periodo solo, in cima, che vale per tutta la pagina — tranne i
          due istogrammi con navigazione propria, che lo dicono da sé. */}
      <div className="flex flex-wrap items-center gap-2">
        {periodi(t).map((p) => (
          <Button
            key={p.value}
            variant={periodo === p.value ? 'secondary' : 'ghost'}
            size="xs"
            onClick={() => setPeriodo(p.value)}
          >
            {p.label}
          </Button>
        ))}
      </div>

      {/* Prima la risposta, poi il dettaglio: otto numeri della stessa
          dimensione non sono una gerarchia, sono un elenco. Tre grandi, il
          resto in una riga di testo sotto. */}
      <div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <Grande label={t('stats.reading.readingTime')} value={formatDurationHuman(totali.secondi)} />
          <Grande label={t('stats.reading.charsRead')} value={formatCaratteriCompatto(totali.caratteri)} />
          <Grande label={totali.etichettaLibri} value={String(totali.libri)} />
        </div>

        <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-muted-foreground">
          <span>
            <span className="tabular-nums text-foreground">{streak}</span> {t('stats.reading.streakSuffix')}
          </span>
          <span>
            <span className="tabular-nums text-foreground">
              {speedChars != null
                ? t('stats.reading.charsPerHour', { n: formatCaratteriCompatto(speedChars) })
                : t('stats.reading.pagesPerHour', { n: speed })}
            </span>{' '}
            {t('stats.reading.speedSuffix')}
          </span>
          <span>
            {t('stats.reading.longestSessionPrefix')}{' '}
            <span className="tabular-nums text-foreground">{formatDurationHuman(totali.sessionePiuLunga)}</span>
          </span>
          <span>
            {t('stats.reading.bestDayPrefix')}{' '}
            <span className="tabular-nums text-foreground">{formatDurationHuman(totali.giornataMigliore)}</span>
          </span>
          {tuttoIlTempo && (
            <span>
              <span className="tabular-nums text-foreground">{summary?.year_books || 0}</span> {t('stats.reading.finishedThisYearSuffix')}
            </span>
          )}
        </p>
      </div>

      {isVisible('readingRecords') && summary && tuttoIlTempo && (
        <ChartCard title={t('stats.reading.chart.readingRecords')}>
          <div className="grid grid-cols-1 gap-x-6 md:grid-cols-2">
            <RecordRow
              label={t('stats.reading.record.bestYear')}
              title={summary.best_year ? String(summary.best_year) : '—'}
              value={t('stats.library.bookCount', { count: summary.best_year_books, n: summary.best_year_books })}
            />
            <RecordRow
              label={t('stats.reading.record.longestBookPages')}
              title={summary.longest_book_title || '—'}
              value={t('stats.library.pagesShort', { n: summary.longest_book_pages })}
            />
            <RecordRow
              label={t('stats.reading.record.longestBookTime')}
              title={summary.longest_book_by_time_title || '—'}
              value={formatDurationHuman(summary.longest_book_by_time_seconds)}
            />
            <RecordRow
              label={t('stats.reading.record.topAuthorByTime')}
              title={summary.top_author_by_time_name || '—'}
              value={formatDurationHuman(summary.top_author_by_time_seconds)}
            />
            <RecordRow
              label={t('stats.reading.record.longestStreak')}
              title={
                summary.longest_streak_days > 0
                  ? `${formatDate(summary.longest_streak_start)} – ${formatDate(summary.longest_streak_end)}`
                  : '—'
              }
              value={t('stats.reading.dayCount', { count: summary.longest_streak_days, n: summary.longest_streak_days })}
            />
          </div>
        </ChartCard>
      )}

      {isVisible('weeklyHistogram') && (
        <ChartCard
          title={t('stats.reading.dailyHistogramTitle', { unit: misura === 'caratteri' ? t('stats.reading.unit.chars') : t('stats.reading.unit.minutes') })}
          action={
            <div className="flex items-center gap-2">
              <ScambiaMisura misura={misura} onChange={setMisura} />
              <Button variant="outline" size="xs" onClick={() => setWeekOffset((o) => o - 1)}>
                {t('stats.calendar.prev')}
              </Button>
              <span className="min-w-[110px] text-center text-[12px] text-muted-foreground">{weekLabel}</span>
              <Button variant="outline" size="xs" disabled={weekOffset >= 0} onClick={() => setWeekOffset((o) => o + 1)}>
                {t('stats.calendar.next')}
              </Button>
              {weekOffset !== 0 && (
                <Button variant="outline" size="xs" onClick={() => setWeekOffset(0)}>
                  {t('stats.reading.today')}
                </Button>
              )}
            </div>
          }
        >
          <BarChart labels={weekdayLabels(t)} datasets={weekDatasets} stacked yUnit={unitaMisura(misura)} height={240} />
        </ChartCard>
      )}

      {/* Le ultime dieci settimane. Il gemello per giorni risponde a «com'è
          andata questa settimana»; per sapere se stai leggendo più o meno di un
          mese fa non serve a niente, perché bisogna cambiare settimana sette
          volte e ricordarsi i numeri. Stessa misura dell'altro: sono due tagli
          della stessa domanda e cambiarne una sola darebbe due unità nella
          stessa schermata. */}
      {isVisible('weeksHistogram') && (
        <ChartCard
          title={t('stats.reading.weeksHistogramTitle', {
            n: SETTIMANE,
            unit: misura === 'caratteri' ? t('stats.reading.unit.inChars') : t('stats.reading.unit.inMinutes'),
          })}
          action={<ScambiaMisura misura={misura} onChange={setMisura} />}
        >
          <BarChart
            labels={settimane.map((s) => etichettaSettimana(s, t))}
            datasets={weeksDatasets}
            stacked
            yUnit={unitaMisura(misura)}
            height={240}
          />
        </ChartCard>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {isVisible('peakHours') && (
          <ChartCard title={t('stats.reading.chart.peakHours')}>
            <div className="flex flex-col gap-2">
              {peakHours.map((b) => (
                <StatBarRow key={b.label} label={b.label} value={`${b.percent}%`} percent={b.percent} color={SAGE} />
              ))}
            </div>
          </ChartCard>
        )}

        <AnnotationIntensity libraryFolder={libraryFolder} />

      </div>

      {isVisible('heatmap') && (
        <ChartCard title={t('stats.reading.chart.heatmap')}>
          <HeatmapCalendar days={heatmapDays} />
        </ChartCard>
      )}

      {isVisible('monthlyCalendar') && (
        <ChartCard title={t('stats.reading.chart.monthlyCalendar')}>
          <ReadingCalendar sessions={raw} />
        </ChartCard>
      )}

      {isVisible('monthlyHours') && (
        <ChartCard
          title={t('stats.reading.monthlyHoursTitle')}
          action={
            <div className="flex items-center gap-2">
              <Button variant="outline" size="xs" onClick={() => setYearOffset((o) => o - 1)}>
                {t('stats.calendar.prev')}
              </Button>
              <span className="min-w-[50px] text-center text-[12px] text-muted-foreground">{monthYear}</span>
              <Button variant="outline" size="xs" disabled={yearOffset >= 0} onClick={() => setYearOffset((o) => o + 1)}>
                {t('stats.calendar.next')}
              </Button>
            </div>
          }
        >
          <BarChart labels={monthLabels(t)} datasets={monthDatasets} stacked yUnit="min" height={260} />
        </ChartCard>
      )}

      <GlobalReadingStats sessions={raw} />

      {savedCharts.length > 0 && (
        <div>
          <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('stats.customCharts')}</h3>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {savedCharts.map((chart) => {
              const chartConfig = normalizeSavedChartConfig(chart)
              const chartResult = buildChartSeries(chartConfig, raw, timeline, t)
              return (
                <ChartCard
                  key={chart.id}
                  title={chart.name}
                  action={
                    <Button
                      variant="ghost"
                      size="xs"
                      onClick={() => navigate(libraryFolder ? `/statistiche/grafici?library=${libraryFolder}` : '/statistiche/grafici')}
                    >
                      {t('stats.chartBuilder.edit')}
                    </Button>
                  }
                >
                  <ChartBuilderPreview config={chartConfig} result={chartResult} height={180} />
                </ChartCard>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
