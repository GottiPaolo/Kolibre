import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, BarChart3, ChevronDown, ChevronRight, LineChart as LineChartIcon, Library as LibraryIcon, PieChart as PieChartIcon, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useLibraries } from '@/lib/queries'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { useLingua, type Valori } from '@/lib/i18n'
import {
  useStatsRaw,
  useStatsTimeline,
  useSavedCharts,
  type ChartBuilderGroupBy,
  type ChartBuilderType,
  type ChartBuilderYVar,
  type SavedChart,
} from '@/lib/statsQueries'
import { createSavedChart, deleteSavedChart, updateSavedChart } from '@/lib/chartBuilderActions'
import { ChartCard, EmptyNote } from './StatBar'
import { ChartBuilderPreview } from './ChartBuilderPreview'
import { countActiveRules } from './filterTree'
import { FilterTreeEditor } from './FilterTreeEditor'
import {
  aggOptions,
  chartModeOptions,
  chartTypeOptions,
  dataSourceOptions,
  DEFAULT_CHART_BUILDER_CONFIG,
  groupByOptions,
  yVarOptions,
  aggApplicable,
  buildChartSeries,
  encodeMetric,
  normalizeSavedChartConfig,
  parseMetric,
  type ChartBuilderConfig,
} from './chartBuilderCompute'

type Traduci = (chiave: string, valori?: Valori) => string

const CHART_TYPE_ICONS: Record<ChartBuilderType, typeof BarChart3> = {
  bar: BarChart3,
  line: LineChartIcon,
  pie: PieChartIcon,
}

// null (mai persistito nel select, tradotto in/da 'auto' qui) = policy
// legacy — cronologico asc per gli assi temporali, valore desc con Top N +
// Altro per quelli categorici (vedi chartBuilderCompute.ts::bucketOrder).
function sortByOptions(t: Traduci): { value: 'auto' | 'label' | 'value'; label: string }[] {
  return [
    { value: 'auto', label: t('stats.chartBuilder.sortBy.auto') },
    { value: 'label', label: t('stats.chartBuilder.sortBy.label') },
    { value: 'value', label: t('stats.chartBuilder.sortBy.value') },
  ]
}
function sortOrderOptions(t: Traduci): { value: 'asc' | 'desc'; label: string }[] {
  return [
    { value: 'desc', label: t('stats.chartBuilder.sortOrder.desc') },
    { value: 'asc', label: t('stats.chartBuilder.sortOrder.asc') },
  ]
}

// Pagina dedicata "Grafici personalizzati", raggiunta dal bottone in
// StatisticsPage — costruttore (tipo grafico, sorgente dati, asse X, asse Y/
// variabile+aggregazione, raggruppamento secondario opzionale con modalità
// affiancata/impilata, filtri ad albero AND/OR, ordinamento) con anteprima
// live, che pivotta client-side sugli stessi array già scaricati da
// useStatsRaw/useStatsTimeline invece di un nuovo endpoint di aggregazione
// (vedi chartBuilderCompute.ts). Ispirato a grafidinamici (progetto
// separato, Flask/pandas/Chart.js — vedi un precedente progetto separato) per la POTENZA (assi liberi, aggregazioni
// multiple, filtri a livelli con albero AND/OR, ordinamento: serviva la
// stessa potenza di grafidinamici), non per il codice: qui i primitivi
// (Select/Button/input già in uso nel resto di Statistiche) restano quelli
// di Kolibre, nessun ispettore JSON.
export function ChartBuilderPage() {
  const { t } = useLingua()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()

  const { data: libraries } = useLibraries()
  const libraryFromUrl = searchParams.get('library')
  const activeLibrary = useMemo(
    () => libraries?.find((l) => l.folder_name === libraryFromUrl) ?? libraries?.[0],
    [libraries, libraryFromUrl]
  )
  const folder = activeLibrary?.folder_name

  useSetPageHeader(t('stats.chartBuilder.pageTitle'))

  const { data: raw = [] } = useStatsRaw(folder)
  const { data: timeline = [] } = useStatsTimeline(folder, 400)
  const { data: savedCharts = [] } = useSavedCharts(folder)

  const [config, setConfig] = useState<ChartBuilderConfig>(DEFAULT_CHART_BUILDER_CONFIG)
  const [name, setName] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filtersOpen, setFiltersOpen] = useState(false)

  // Cambiando sorgente dati, asse X/asse Y (e l'eventuale serie secondaria)
  // potrebbero non essere più validi per quella sorgente (es. "autore" non
  // esiste su /timeline, che quindi non supporta nemmeno una serie
  // secondaria) — si riallineano al primo valore ammesso invece di lasciare
  // una combinazione silenziosamente incoerente.
  useEffect(() => {
    const validGroupBys: ChartBuilderGroupBy[] = groupByOptions(t)[config.dataSource].map((o) => o.value)
    const validYVars: ChartBuilderYVar[] = yVarOptions(t)[config.dataSource].map((o) => o.value)
    setConfig((c) => {
      const groupBy = validGroupBys.includes(c.groupBy) ? c.groupBy : validGroupBys[0]
      const { yVar, agg } = parseMetric(c.metric)
      const metric = validYVars.includes(yVar) ? c.metric : encodeMetric(validYVars[0], agg)
      const secondaryStillValid =
        c.dataSource === 'raw' && !!c.groupBySecondary && c.groupBySecondary !== groupBy && validGroupBys.includes(c.groupBySecondary)
      return { ...c, groupBy, metric, groupBySecondary: secondaryStillValid ? c.groupBySecondary : null }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.dataSource])

  // Le due dimensioni (asse X e "raggruppa per") devono restare distinte —
  // se l'utente cambia l'asse X su un valore che coincide con la serie
  // secondaria già scelta, questa si azzera invece di produrre un pivot
  // degenere (ogni bucket secondario conterrebbe un solo punto).
  useEffect(() => {
    setConfig((c) => (c.groupBySecondary === c.groupBy ? { ...c, groupBySecondary: null } : c))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.groupBy])

  const activeFilterCount = countActiveRules(config.filters)

  const result = useMemo(() => buildChartSeries(config, raw, timeline, t), [config, raw, timeline, t])

  function resetBuilder() {
    setConfig(DEFAULT_CHART_BUILDER_CONFIG)
    setName('')
    setEditingId(null)
    setError(null)
    setFiltersOpen(false)
  }

  function openSavedChart(chart: SavedChart) {
    // normalizeSavedChartConfig gestisce sia le righe v1/v2 (campi NULL →
    // "nessuna serie secondaria / affiancate / nessun filtro / ordinamento
    // legacy", filters piatto → albero equivalente) sia quelle v3 — nessun
    // grafico esistente cambia aspetto.
    setConfig(normalizeSavedChartConfig(chart))
    setName(chart.name)
    setEditingId(chart.id)
    setError(null)
    setFiltersOpen(false)
    // Non più window.scrollTo: da quando Layout.tsx tiene sidebar/Topbar
    // fuori dal flusso scrollabile (fix sidebar che scorreva via nella
    // pagina Autori), è questo contenitore — non la finestra — a scorrere.
    document.getElementById('page-scroll-container')?.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function handleSave() {
    if (!folder) return
    if (!name.trim()) {
      setError(t('stats.chartBuilder.nameRequired'))
      return
    }
    setSaving(true)
    setError(null)
    try {
      const payload = { library: folder, name: name.trim(), ...config }
      if (editingId) await updateSavedChart(editingId, payload)
      else await createSavedChart(payload)
      await queryClient.invalidateQueries({ queryKey: ['stats-charts', folder] })
      resetBuilder()
    } catch {
      setError(t('stats.chartBuilder.saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(chart: SavedChart) {
    if (!window.confirm(t('stats.chartBuilder.deleteConfirm', { name: chart.name }))) return
    await deleteSavedChart(chart.id)
    if (editingId === chart.id) resetBuilder()
    await queryClient.invalidateQueries({ queryKey: ['stats-charts', folder] })
  }

  const secondaryOptions = groupByOptions(t)[config.dataSource].filter((o) => o.value !== config.groupBy)
  const canHaveSecondary = config.chartType !== 'pie' && config.dataSource === 'raw'

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => navigate('/statistiche')}>
          <ArrowLeft className="size-3.5" /> {t('stats.chartBuilder.backToStats')}
        </Button>

        {libraries && libraries.length > 1 && activeLibrary && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm">
                <LibraryIcon className="size-3.5" />
                {activeLibrary.name}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {libraries.map((lib) => (
                <DropdownMenuItem key={lib.id} onSelect={() => setSearchParams({ library: lib.folder_name })}>
                  {lib.name}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      <ChartCard title={editingId ? t('stats.chartBuilder.editChart') : t('stats.chartBuilder.newChart')}>
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_1fr]">
            <div className="flex flex-col gap-3">
              <div>
                <p className="mb-1.5 text-[11px] font-medium text-muted-foreground">{t('stats.chartBuilder.chartTypeLabel')}</p>
                <div className="flex gap-1.5">
                  {chartTypeOptions(t).map((opt) => {
                    const Icon = CHART_TYPE_ICONS[opt.value]
                    return (
                      <Button
                        key={opt.value}
                        variant={config.chartType === opt.value ? 'secondary' : 'outline'}
                        size="sm"
                        onClick={() => setConfig((c) => ({ ...c, chartType: opt.value }))}
                      >
                        <Icon className="size-3.5" />
                        {opt.label}
                      </Button>
                    )
                  })}
                </div>
              </div>

              <LabeledSelect
                label={t('stats.chartBuilder.dataSourceLabel')}
                value={config.dataSource}
                options={dataSourceOptions(t)}
                onChange={(v) => setConfig((c) => ({ ...c, dataSource: v as ChartBuilderConfig['dataSource'] }))}
              />

              <div className="grid grid-cols-2 gap-2">
                <LabeledSelect
                  label={t('stats.chartBuilder.xAxisLabel')}
                  value={config.groupBy}
                  options={groupByOptions(t)[config.dataSource]}
                  onChange={(v) => setConfig((c) => ({ ...c, groupBy: v as ChartBuilderConfig['groupBy'] }))}
                />
                <LabeledSelect
                  label={t('stats.chartBuilder.yAxisLabel')}
                  value={parseMetric(config.metric).yVar}
                  options={yVarOptions(t)[config.dataSource]}
                  onChange={(v) =>
                    setConfig((c) => ({ ...c, metric: encodeMetric(v as ChartBuilderYVar, parseMetric(c.metric).agg) }))
                  }
                />
              </div>

              {aggApplicable(parseMetric(config.metric).yVar) && (
                <LabeledSelect
                  label={t('stats.chartBuilder.aggLabel')}
                  value={parseMetric(config.metric).agg}
                  options={aggOptions(t)}
                  onChange={(v) => setConfig((c) => ({ ...c, metric: encodeMetric(parseMetric(c.metric).yVar, v) }))}
                />
              )}

              {canHaveSecondary && (
                <LabeledSelect
                  label={t('stats.chartBuilder.secondaryGroupLabel')}
                  value={config.groupBySecondary ?? 'none'}
                  options={[{ value: 'none' as const, label: t('stats.chartBuilder.none') }, ...secondaryOptions]}
                  onChange={(v) =>
                    setConfig((c) => ({ ...c, groupBySecondary: v === 'none' ? null : (v as ChartBuilderGroupBy) }))
                  }
                />
              )}

              {config.chartType === 'bar' && config.groupBySecondary && (
                <div>
                  <p className="mb-1.5 text-[11px] font-medium text-muted-foreground">{t('stats.chartBuilder.barModeLabel')}</p>
                  <div className="flex gap-1.5">
                    {chartModeOptions(t).map((opt) => (
                      <Button
                        key={opt.value}
                        variant={config.chartMode === opt.value ? 'secondary' : 'outline'}
                        size="sm"
                        onClick={() => setConfig((c) => ({ ...c, chartMode: opt.value }))}
                      >
                        {opt.label}
                      </Button>
                    ))}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-2">
                <LabeledSelect
                  label={t('stats.chartBuilder.sortByLabel')}
                  value={config.sortBy ?? 'auto'}
                  options={sortByOptions(t)}
                  onChange={(v) =>
                    setConfig((c) => ({
                      ...c,
                      sortBy: v === 'auto' ? null : v,
                      sortOrder: v === 'auto' ? null : c.sortOrder ?? 'desc',
                    }))
                  }
                />
                {config.sortBy && (
                  <LabeledSelect
                    label={t('stats.chartBuilder.sortOrderLabel')}
                    value={config.sortOrder ?? 'desc'}
                    options={sortOrderOptions(t)}
                    onChange={(v) => setConfig((c) => ({ ...c, sortOrder: v }))}
                  />
                )}
              </div>

              <div>
                <button
                  type="button"
                  onClick={() => setFiltersOpen((v) => !v)}
                  className="flex w-full items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground"
                >
                  {filtersOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                  {t('stats.chartBuilder.filters')}
                  {activeFilterCount > 0 && (
                    <span className="ml-1 rounded-full bg-primary/15 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                      {activeFilterCount}
                    </span>
                  )}
                </button>

                {filtersOpen && (
                  <div className="mt-2 rounded-md border border-border bg-muted/30 p-2.5">
                    <FilterTreeEditor
                      group={config.filters}
                      onChange={(next) => setConfig((c) => ({ ...c, filters: next }))}
                      raw={raw}
                      isRoot
                    />
                  </div>
                )}
              </div>

              <div>
                <p className="mb-1.5 text-[11px] font-medium text-muted-foreground">{t('stats.chartBuilder.chartNameLabel')}</p>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t('stats.chartBuilder.chartNamePlaceholder')}
                  className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
                />
              </div>

              {error && <p className="text-[12px] text-destructive">{error}</p>}

              <div className="flex gap-2">
                <Button size="sm" onClick={() => void handleSave()} disabled={saving || !folder}>
                  {editingId ? t('stats.chartBuilder.updateChart') : t('stats.chartBuilder.saveChart')}
                </Button>
                {editingId && (
                  <Button variant="outline" size="sm" onClick={resetBuilder}>
                    {t('stats.chartBuilder.cancelEdit')}
                  </Button>
                )}
              </div>
            </div>

            <div className="rounded-md border border-border bg-background p-3">
              <ChartBuilderPreview config={config} result={result} height={280} />
            </div>
          </div>
        </div>
      </ChartCard>

      <div>
        <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('stats.chartBuilder.savedCharts')}</h3>
        {savedCharts.length === 0 ? (
          <EmptyNote>{t('stats.chartBuilder.noSavedCharts')}</EmptyNote>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {savedCharts.map((chart) => {
              const chartConfig = normalizeSavedChartConfig(chart)
              const chartResult = buildChartSeries(chartConfig, raw, timeline, t)
              return (
                <ChartCard
                  key={chart.id}
                  title={chart.name}
                  action={
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" size="xs" onClick={() => openSavedChart(chart)}>
                        {t('stats.chartBuilder.open')}
                      </Button>
                      <Button variant="ghost" size="icon-sm" onClick={() => void handleDelete(chart)} title={t('stats.chartBuilder.delete')}>
                        <Trash2 className="size-3.5 text-destructive" />
                      </Button>
                    </div>
                  }
                >
                  <ChartBuilderPreview config={chartConfig} result={chartResult} height={180} />
                </ChartCard>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

function LabeledSelect<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div>
      <p className="mb-1.5 text-[11px] font-medium text-muted-foreground">{label}</p>
      <Select value={value} onValueChange={(v) => onChange(v as T)}>
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

