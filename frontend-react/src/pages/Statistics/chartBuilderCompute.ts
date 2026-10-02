// Aggregazione client-side per il chart builder (Statistiche → Grafici
// personalizzati). Nessun nuovo endpoint di aggregazione lato backend: pivot
// sugli stessi array già scaricati da useStatsRaw/useStatsTimeline (vedi
// stats_service.compute_raw's own docstring — "designed once, used by
// both" i widget fissi e questo builder generico), stessa filosofia di
// statsCompute.ts per i widget esistenti. File separato da statsCompute.ts
// perché quello è un porting 1:1 delle computed di App.vue, questo è nuovo.
//
// v2 (assi indipendenti + serie secondaria/modalità + filtri): groupBy resta
// il nome del campo storico (asse X) e metric l'asse Y — non rinominati per
// non rompere la persistenza (SavedChart.group_by/.metric lato backend), ma
// la UI li presenta esplicitamente come "Asse X" / "Asse Y". groupBySecondary
// è la dimensione opzionale "raggruppa per" (serie): stesso set di opzioni
// di groupBy, nullable, applicabile solo a /raw (vedi GROUP_BY_OPTIONS).
//
// v3 (obiettivo: la stessa potenza di grafidinamici — assi liberi,
// aggregazioni multiple, filtri a livelli, ordinamento, vedi
// un precedente progetto separato): metric si
// scompone in yVar+agg (parseMetric/encodeMetric), i filtri sono un albero
// AND/OR (vedi filterTree.ts) invece di un oggetto piatto, e i bucket
// dell'asse primario/serie possono essere ordinati esplicitamente per
// etichetta o valore. L'accumulo per bucket passa da un semplice
// Map<string, number> (sum) a Map<string, MetricAccumulator> — necessario
// per calcolare media/minimo/massimo/conteggio-distinti correttamente,
// INCLUSO per il bucket "Altro" (che deve fondere gli accumulatori grezzi
// dell'overflow, non sommare valori già finalizzati — altrimenti una media
// di medie o un minimo di minimi sarebbe sbagliato).
import { splitAuthorNames } from '@/lib/authorNames'
import type { Valori } from '@/lib/i18n'
import { emptyFilterGroup, matchesFilterTree, matchesFilterTreeTimeline } from './filterTree'
import { monthLabels } from './statsCompute'
import { isoLocale } from '@/lib/format'
import type {
  ChartBuilderAgg,
  ChartBuilderFilters,
  ChartBuilderGroupBy,
  ChartBuilderMetric,
  ChartBuilderMode,
  ChartBuilderSource,
  ChartBuilderType,
  ChartBuilderYVar,
  ReadingSessionRaw,
  SavedChart,
  TimelineEntry,
} from '@/lib/statsQueries'

type Traduci = (chiave: string, valori?: Valori) => string

export interface ChartBuilderConfig {
  chartType: ChartBuilderType
  dataSource: ChartBuilderSource
  groupBy: ChartBuilderGroupBy // asse X
  metric: ChartBuilderMetric // asse Y (variabile:aggregazione, vedi parseMetric)
  groupBySecondary: ChartBuilderGroupBy | null // "raggruppa per" (serie), opzionale
  chartMode: ChartBuilderMode // solo bar con groupBySecondary impostato: affiancate vs impilate
  filters: ChartBuilderFilters
  sortBy: 'label' | 'value' | null // null = policy legacy (cronologico asc / valore desc)
  sortOrder: 'asc' | 'desc' | null
}

export const DEFAULT_CHART_BUILDER_CONFIG: ChartBuilderConfig = {
  chartType: 'bar',
  dataSource: 'raw',
  groupBy: 'week',
  metric: 'duration:sum',
  groupBySecondary: null,
  chartMode: 'grouped',
  filters: emptyFilterGroup(),
  sortBy: null,
  sortOrder: null,
}

export function chartModeOptions(t: Traduci): { value: ChartBuilderMode; label: string }[] {
  return [
    { value: 'grouped', label: t('stats.chartBuilder.chartMode.grouped') },
    { value: 'stacked', label: t('stats.chartBuilder.chartMode.stacked') },
  ]
}

export function chartTypeOptions(t: Traduci): { value: ChartBuilderType; label: string }[] {
  return [
    { value: 'bar', label: t('stats.chartBuilder.chartType.bar') },
    { value: 'line', label: t('stats.chartBuilder.chartType.line') },
    { value: 'pie', label: t('stats.chartBuilder.chartType.pie') },
  ]
}

export function dataSourceOptions(t: Traduci): { value: ChartBuilderSource; label: string }[] {
  return [
    { value: 'raw', label: t('stats.chartBuilder.dataSource.raw') },
    { value: 'timeline', label: t('stats.chartBuilder.dataSource.timeline') },
  ]
}

// Per sorgente: quali dimensioni di raggruppamento sono davvero derivabili
// dai dati che quella sorgente porta con sé — /raw ha una riga per sessione
// con titolo/autore/formato/dispositivo/sorgente, /timeline è già
// pre-aggregata per giorno (solo data + secondi totali), quindi può solo
// essere ri-raggruppata su base temporale.
export function groupByOptions(t: Traduci): Record<ChartBuilderSource, { value: ChartBuilderGroupBy; label: string }[]> {
  return {
    raw: [
      { value: 'day', label: t('stats.chartBuilder.groupBy.day') },
      { value: 'week', label: t('stats.chartBuilder.groupBy.week') },
      { value: 'month', label: t('stats.chartBuilder.groupBy.month') },
      { value: 'book_title', label: t('stats.filterTree.dimension.bookTitle') },
      { value: 'author', label: t('library.field.author') },
      { value: 'series', label: t('library.field.series') },
      { value: 'tag', label: t('library.field.tags') },
      { value: 'language', label: t('library.field.language') },
      { value: 'publisher', label: t('library.field.publisher') },
      { value: 'rating', label: t('library.field.rating') },
      { value: 'decade', label: t('stats.filterTree.dimension.decade') },
      { value: 'format', label: t('stats.filterTree.dimension.format') },
      { value: 'device', label: t('stats.filterTree.dimension.device') },
      { value: 'source', label: t('stats.filterTree.dimension.source') },
    ],
    timeline: [
      { value: 'day', label: t('stats.chartBuilder.groupBy.day') },
      { value: 'week', label: t('stats.chartBuilder.groupBy.week') },
      { value: 'month', label: t('stats.chartBuilder.groupBy.month') },
    ],
  }
}

// v3: "variabile" Y e aggregazione scelte indipendentemente — solo
// duration/pages_read hanno un'aggregazione che ha senso scegliere
// (Somma/Media/Minimo/Massimo); le altre variabili sono già di per sé un
// conteggio (righe o valori distinti), l'aggregazione non si applica.
export function yVarLabels(t: Traduci): Record<ChartBuilderYVar, string> {
  return {
    duration: t('stats.chartBuilder.yVar.duration'),
    // I caratteri prima delle pagine: sono l'unita' confrontabile fra libri e
    // fra impostazioni di carattere diverse (vedi il report sulle statistiche
    // di KOReader). Le pagine restano, per chi le vuole.
    chars_read: t('stats.chartBuilder.yVar.charsRead'),
    pages_read: t('stats.chartBuilder.yVar.pagesRead'),
    session_count: t('stats.chartBuilder.yVar.sessionCount'),
    distinct_books: t('stats.chartBuilder.yVar.distinctBooks'),
    distinct_authors: t('stats.chartBuilder.yVar.distinctAuthors'),
  }
}

export function aggLabels(t: Traduci): Record<ChartBuilderAgg, string> {
  return {
    sum: t('stats.chartBuilder.agg.sum'),
    avg: t('stats.chartBuilder.agg.avg'),
    min: t('stats.chartBuilder.agg.min'),
    max: t('stats.chartBuilder.agg.max'),
  }
}

export function yVarOptions(t: Traduci): Record<ChartBuilderSource, { value: ChartBuilderYVar; label: string }[]> {
  const labels = yVarLabels(t)
  return {
    raw: (['duration', 'chars_read', 'pages_read', 'session_count', 'distinct_books', 'distinct_authors'] as ChartBuilderYVar[]).map(
      (v) => ({ value: v, label: labels[v] })
    ),
    // /timeline porta solo un totale di secondi per giorno — nessuna delle
    // altre variabili è derivabile da quella forma.
    timeline: [{ value: 'duration', label: labels.duration }],
  }
}

export function aggOptions(t: Traduci): { value: ChartBuilderAgg; label: string }[] {
  const labels = aggLabels(t)
  return (['sum', 'avg', 'min', 'max'] as ChartBuilderAgg[]).map((v) => ({ value: v, label: labels[v] }))
}

export function aggApplicable(yVar: ChartBuilderYVar): boolean {
  return yVar === 'duration' || yVar === 'pages_read' || yVar === 'chars_read'
}

export function metricLabel(yVar: ChartBuilderYVar, agg: ChartBuilderAgg, t: Traduci): string {
  const yLabels = yVarLabels(t)
  return aggApplicable(yVar) ? `${yLabels[yVar]} (${aggLabels(t)[agg].toLowerCase()})` : yLabels[yVar]
}

// Normalizza il valore grezzo persistito di SavedChart.metric (stringa
// opaca lato backend, vedi models.py::SavedChart's v3 docstring) in
// {yVar, agg} — copre sia i 3 valori legacy v1/v2 sia i nuovi valori
// codificati "yVar:agg" (o il nome nudo per le variabili a conteggio).
export function parseMetric(raw: ChartBuilderMetric): { yVar: ChartBuilderYVar; agg: ChartBuilderAgg } {
  if (raw === 'duration_sum') return { yVar: 'duration', agg: 'sum' }
  if (raw === 'pages_sum') return { yVar: 'pages_read', agg: 'sum' }
  if (raw === 'session_count') return { yVar: 'session_count', agg: 'sum' }
  if (raw === 'distinct_books' || raw === 'distinct_authors') return { yVar: raw, agg: 'sum' }
  const [yVarRaw, aggRaw] = raw.split(':')
  const yVar = (yVarRaw as ChartBuilderYVar) || 'duration'
  const agg = (aggRaw as ChartBuilderAgg) || 'sum'
  return { yVar, agg }
}

export function encodeMetric(yVar: ChartBuilderYVar, agg: ChartBuilderAgg): ChartBuilderMetric {
  if (yVar === 'session_count' || yVar === 'distinct_books' || yVar === 'distinct_authors') return yVar
  return `${yVar}:${agg}` as ChartBuilderMetric
}

const TIME_GROUP_BYS: ChartBuilderGroupBy[] = ['day', 'week', 'month']

// Quante categorie (titolo/autore/formato/dispositivo/sorgente) mostrare
// come serie proprie prima di raggrupparle in "Altro" — stessa soglia/
// filosofia del "Top 8 + Altro" già usato da statsCompute.ts.
const CATEGORICAL_TOP_N = 12

// Idem per la dimensione SECONDARIA (serie): più basso di CATEGORICAL_TOP_N
// perché ogni categoria in più è una barra/linea intera aggiunta a OGNI
// punto dell'asse X, non una singola voce di elenco.
const SECONDARY_TOP_N = 6

function mondayOfWeek(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  const dow = (d.getDay() + 6) % 7 // 0 = lunedì
  d.setDate(d.getDate() - dow)
  return isoLocale(d)
}

function formatDayLabel(dateStr: string, t: Traduci): string {
  const d = new Date(dateStr + 'T00:00:00')
  return `${d.getDate()} ${monthLabels(t)[d.getMonth()]}`
}

function formatTimeLabel(key: string, groupBy: ChartBuilderGroupBy, t: Traduci): string {
  if (groupBy === 'month') {
    const [y, m] = key.split('-')
    return `${monthLabels(t)[Number(m) - 1]} ${y}`
  }
  return groupBy === 'week' ? t('stats.chartBuilder.weekOf', { label: formatDayLabel(key, t) }) : formatDayLabel(key, t)
}

function timeGroupKey(dateStr: string, groupBy: ChartBuilderGroupBy): string {
  if (groupBy === 'month') return dateStr.slice(0, 7)
  if (groupBy === 'week') return mondayOfWeek(dateStr)
  return dateStr
}

// Le etichette dei metadati mancanti sono dichiarate, non inventate: un
// libro senza tag finisce in "Senza tag", non sparisce e non si traveste da
// categoria vera. Metà dei libri non ha tag, quindi quella fetta è spesso la
// più grande — ed è giusto che si veda.
//
// Tradotte (a differenza dei fallback omonimi in filterTree.ts): qui sono
// solo etichette dell'asse del grafico, ricalcolate a ogni chiamata — non
// finiscono mai in un FilterRuleCategorical.values persistito, quindi non
// c'è il rischio di rottura di un filtro già salvato che vieta di tradurre
// quelli (vedi il commento su rowCategoricalValue in filterTree.ts).
function senza(t: Traduci) {
  return {
    series: t('stats.chartBuilder.noSeries'),
    tag: t('stats.chartBuilder.noTag'),
    language: t('stats.chartBuilder.unknownLanguage'),
    publisher: t('stats.chartBuilder.unknownPublisher'),
    rating: t('stats.library.unrated'),
    decade: t('stats.chartBuilder.unknownDate'),
  } as const
}

/**
 * Le chiavi di gruppo di una sessione. Quasi sempre una sola — ma i tag sono
 * multivalore, e un libro di filosofia E politica deve comparire sotto
 * entrambi. Conseguenza voluta: sommando le fette dei tag si supera il tempo
 * totale, perché la stessa ora di lettura appartiene davvero a più tag.
 */
function rawGroupKeys(row: ReadingSessionRaw, groupBy: ChartBuilderGroupBy, t: Traduci): string[] {
  const SENZA = senza(t)
  switch (groupBy) {
    case 'day':
    case 'week':
    case 'month':
      return [timeGroupKey(row.date, groupBy)]
    case 'book_title':
      return [row.book_title || t('stats.chartBuilder.unknown')]
    case 'author':
      return [row.author || t('stats.chartBuilder.unknownAuthor')]
    case 'format':
      return [row.format || t('stats.chartBuilder.unknown')]
    case 'device':
      return [row.device_name || t('stats.chartBuilder.unknown')]
    case 'source':
      // "Web Reader"/"KOReader": nomi propri, identici nelle due lingue — non
      // tradotti di proposito.
      return [row.source === 'web' ? 'Web Reader' : 'KOReader']
    case 'series':
      return [row.series || SENZA.series]
    case 'tag':
      return row.tags?.length ? row.tags : [SENZA.tag]
    case 'language':
      return [row.language || SENZA.language]
    case 'publisher':
      return [row.publisher || SENZA.publisher]
    case 'rating':
      return [row.rating != null ? '★'.repeat(row.rating) || t('stats.chartBuilder.zeroStars') : SENZA.rating]
    case 'decade':
      return [row.decade ? `${row.decade}s` : SENZA.decade]
  }
}

export interface ChartPoint {
  label: string
  value: number
}

// Accumulatore per bucket: tiene tutto il necessario per finalizzare
// QUALSIASI combinazione yVar/agg alla fine, incluso dopo aver fuso più
// bucket insieme (vedi mergeAccumulators, usato per il bucket "Altro" e per
// le celle della griglia primario×secondario) — fondere accumulatori grezzi
// e poi finalizzare UNA VOLTA è la sola via per una media/minimo/massimo
// corretti sull'overflow (una media di medie sarebbe sbagliata).
interface MetricAccumulator {
  sum: number
  count: number
  min: number
  max: number
  bookIds: Set<string>
  authorNames: Set<string>
}

function newAccumulator(): MetricAccumulator {
  return { sum: 0, count: 0, min: Infinity, max: -Infinity, bookIds: new Set(), authorNames: new Set() }
}

function getOrCreateAcc(map: Map<string, MetricAccumulator>, key: string): MetricAccumulator {
  let acc = map.get(key)
  if (!acc) {
    acc = newAccumulator()
    map.set(key, acc)
  }
  return acc
}

function accumulateSample(acc: MetricAccumulator, v: number) {
  acc.sum += v
  acc.count += 1
  if (v < acc.min) acc.min = v
  if (v > acc.max) acc.max = v
}

function accumulateRaw(acc: MetricAccumulator, row: ReadingSessionRaw, yVar: ChartBuilderYVar) {
  if (yVar === 'duration') accumulateSample(acc, row.duration_seconds)
  else if (yVar === 'pages_read') accumulateSample(acc, row.pages_read)
  else if (yVar === 'chars_read') accumulateSample(acc, row.chars_read || 0)
  else acc.count += 1 // session_count/distinct_books/distinct_authors: solo il conteggio/i Set contano

  acc.bookIds.add(row.book_id != null ? `id:${row.book_id}` : `t:${row.book_title || 'Sconosciuto'}`)
  const names = splitAuthorNames(row.author)
  if (names.length === 0) acc.authorNames.add('Autore Sconosciuto')
  else names.forEach((n) => acc.authorNames.add(n))
}

function accumulateTimeline(acc: MetricAccumulator, row: TimelineEntry) {
  accumulateSample(acc, row.total_seconds) // /timeline ha solo "duration" come variabile disponibile
}

function mergeAccumulators(list: MetricAccumulator[]): MetricAccumulator {
  const merged = newAccumulator()
  for (const acc of list) {
    merged.sum += acc.sum
    merged.count += acc.count
    if (acc.min < merged.min) merged.min = acc.min
    if (acc.max > merged.max) merged.max = acc.max
    acc.bookIds.forEach((id) => merged.bookIds.add(id))
    acc.authorNames.forEach((n) => merged.authorNames.add(n))
  }
  return merged
}

function finalizeMetric(acc: MetricAccumulator, yVar: ChartBuilderYVar, agg: ChartBuilderAgg): number {
  switch (yVar) {
    case 'session_count':
      return acc.count
    case 'distinct_books':
      return acc.bookIds.size
    case 'distinct_authors':
      return acc.authorNames.size
    default: // duration | pages_read | chars_read
      if (acc.count === 0) return 0
      if (agg === 'avg') return acc.sum / acc.count
      if (agg === 'min') return acc.min
      if (agg === 'max') return acc.max
      return acc.sum
  }
}

// Applica l'albero di filtri (vedi filterTree.ts) PRIMA di qualunque
// aggregazione — client-side, stessa filosofia già in uso per from_/to su
// GET /stats/raw. today è passato una sola volta da qui (non calcolato
// dentro filterTree.ts) così un solo `new Date()` per chiamata basta per
// tutte le righe.
export function applyFilterTree(
  filters: ChartBuilderFilters,
  raw: ReadingSessionRaw[],
  timeline: TimelineEntry[]
): { raw: ReadingSessionRaw[]; timeline: TimelineEntry[] } {
  const today = isoLocale(new Date())
  return {
    raw: raw.filter((r) => matchesFilterTree(filters, r, today)),
    timeline: timeline.filter((r) => matchesFilterTreeTimeline(filters, r, today)),
  }
}

// Decide l'ordine finale delle chiavi di una dimensione (etichette asse X o
// serie): senza un sort esplicito, replica la policy legacy — cronologico
// asc per le dimensioni temporali (nessun cap), valore desc con "Top N +
// Altro" per quelle categoriche. Con sortBy/sortOrder espliciti, riordina i
// bucket TENUTI (quelli scelti dal Top N) per etichetta o per valore — ma
// "Altro" resta sempre l'ultimo, per non spostare il bucket catch-all in
// mezzo ai dati. Il valore del bucket "Altro" è l'accumulatore
// dell'overflow FUSO e poi finalizzato una volta (vedi mergeAccumulators),
// non una somma di valori già finalizzati — l'unico modo per una media/
// minimo/massimo corretti sull'overflow.
function bucketOrder(
  accs: Map<string, MetricAccumulator>,
  groupBy: ChartBuilderGroupBy,
  topN: number,
  yVar: ChartBuilderYVar,
  agg: ChartBuilderAgg,
  sortBy: 'label' | 'value' | null,
  sortOrder: 'asc' | 'desc' | null,
  other: string
): { order: string[]; valueOf: (key: string) => number; bucketOf: (key: string) => string } {
  const isTimeGroup = TIME_GROUP_BYS.includes(groupBy)
  const finalizedByKey = new Map<string, number>()
  for (const [k, acc] of accs) finalizedByKey.set(k, finalizeMetric(acc, yVar, agg))

  let kept: string[]
  let overflow: string[]
  if (isTimeGroup) {
    kept = Array.from(accs.keys())
    overflow = []
  } else {
    const sortedByValueDesc = Array.from(accs.keys()).sort(
      (a, b) => (finalizedByKey.get(b) || 0) - (finalizedByKey.get(a) || 0)
    )
    kept = sortedByValueDesc.slice(0, topN)
    overflow = sortedByValueDesc.slice(topN)
  }

  const keptSet = new Set(kept)
  const bucketOf = (key: string) => (isTimeGroup || keptSet.has(key) ? key : other)

  const hasOverflow = overflow.length > 0
  const overflowValue = hasOverflow ? finalizeMetric(mergeAccumulators(overflow.map((k) => accs.get(k)!)), yVar, agg) : 0
  const valueOf = (key: string) => (key === other && hasOverflow ? overflowValue : finalizedByKey.get(key) || 0)

  let baseOrder: string[]
  if (isTimeGroup) {
    baseOrder = [...kept].sort((a, b) => a.localeCompare(b))
  } else {
    baseOrder = hasOverflow ? [...kept, other] : [...kept]
  }

  if (!sortBy) return { order: baseOrder, valueOf, bucketOf }

  const withoutAltro = baseOrder.filter((k) => k !== other)
  const dir = sortOrder === 'asc' ? 1 : -1
  withoutAltro.sort((a, b) => (sortBy === 'value' ? (valueOf(a) - valueOf(b)) * dir : a.localeCompare(b, 'it') * dir))
  const order = hasOverflow ? [...withoutAltro, other] : withoutAltro

  return { order, valueOf, bucketOf }
}

// Pivot a una dimensione — usato internamente da buildChartSeries quando
// non c'è nessuna serie secondaria da costruire. Non applica i filtri (vedi
// applyFilterTree), si aspetta righe già filtrate dal chiamante.
export function buildChartPoints(config: ChartBuilderConfig, raw: ReadingSessionRaw[], timeline: TimelineEntry[], t: Traduci): ChartPoint[] {
  const { yVar, agg } = parseMetric(config.metric)
  const accs = new Map<string, MetricAccumulator>()

  if (config.dataSource === 'timeline') {
    for (const row of timeline) accumulateTimeline(getOrCreateAcc(accs, timeGroupKey(row.date, config.groupBy)), row)
  } else {
    for (const row of raw) {
      for (const key of rawGroupKeys(row, config.groupBy, t)) {
        accumulateRaw(getOrCreateAcc(accs, key), row, yVar)
      }
    }
  }

  const other = t('stats.chartBuilder.other')
  const { order, valueOf } = bucketOrder(accs, config.groupBy, CATEGORICAL_TOP_N, yVar, agg, config.sortBy, config.sortOrder, other)
  const isTimeGroup = TIME_GROUP_BYS.includes(config.groupBy)

  return order.map((key) => ({
    label: isTimeGroup && key !== other ? formatTimeLabel(key, config.groupBy, t) : key,
    value: valueOf(key),
  }))
}

export interface ChartSeries {
  key: string
  label: string
  data: (number | null)[]
}

export interface ChartSeriesResult {
  labels: string[]
  series: ChartSeries[]
}

// Pivot a due dimensioni: asse X (config.groupBy) incrociato con la serie
// secondaria (config.groupBySecondary) — es. "settimana × autore" produce,
// per ogni settimana, un valore per autore invece di un unico aggregato.
// Applica i filtri e, per ENTRAMBI gli assi, lo stesso "Top N + Altro" già
// usato da buildChartPoints per una sola dimensione. Senza serie secondaria
// (o su /timeline, o su 'pie') ricade sul pivot a una dimensione.
export function buildChartSeries(config: ChartBuilderConfig, raw: ReadingSessionRaw[], timeline: TimelineEntry[], t: Traduci): ChartSeriesResult {
  const { raw: filteredRaw, timeline: filteredTimeline } = applyFilterTree(config.filters, raw, timeline)
  const { yVar, agg } = parseMetric(config.metric)
  const secondary = config.chartType === 'pie' || config.dataSource === 'timeline' ? null : config.groupBySecondary
  const other = t('stats.chartBuilder.other')

  if (!secondary) {
    const points = buildChartPoints(config, filteredRaw, filteredTimeline, t)
    return {
      labels: points.map((p) => p.label),
      series: [{ key: '__single__', label: metricLabel(yVar, agg, t), data: points.map((p) => p.value) }],
    }
  }

  // Accumulatori marginali (per bucketOrder, che decide Top N + Altro
  // indipendentemente sui due assi) e la griglia grezza pKey→sKey→
  // accumulatore, che verrà ri-bucketizzata e fusa per cella più sotto.
  const primaryAccs = new Map<string, MetricAccumulator>()
  const secondaryAccs = new Map<string, MetricAccumulator>()
  const nested = new Map<string, Map<string, MetricAccumulator>>()

  for (const row of filteredRaw) {
    // Prodotto fra le chiavi dei due assi: con dimensioni a valore singolo
    // e' una cella sola, come prima. Con i tag su un asse (o su entrambi) la
    // riga contribuisce a ogni combinazione, che e' il comportamento giusto
    // — vedi rawGroupKeys.
    const pKeys = rawGroupKeys(row, config.groupBy, t)
    const sKeys = rawGroupKeys(row, secondary, t)

    for (const pKey of pKeys) accumulateRaw(getOrCreateAcc(primaryAccs, pKey), row, yVar)
    for (const sKey of sKeys) accumulateRaw(getOrCreateAcc(secondaryAccs, sKey), row, yVar)

    for (const pKey of pKeys) {
      let sub = nested.get(pKey)
      if (!sub) {
        sub = new Map<string, MetricAccumulator>()
        nested.set(pKey, sub)
      }
      for (const sKey of sKeys) accumulateRaw(getOrCreateAcc(sub, sKey), row, yVar)
    }
  }

  const primaryBucket = bucketOrder(primaryAccs, config.groupBy, CATEGORICAL_TOP_N, yVar, agg, config.sortBy, config.sortOrder, other)
  const secondaryBucket = bucketOrder(secondaryAccs, secondary, SECONDARY_TOP_N, yVar, agg, null, null, other)

  // Rigrigliatura: ogni (pKey,sKey) grezzo contribuisce, con l'accumulatore
  // intero (non un numero), al suo bucket primario × bucket secondario
  // finale — così una cella che riceve overflow su uno o entrambi gli assi
  // può ancora essere finalizzata correttamente (media/minimo/massimo/
  // distinti sull'unione, non sulla somma di valori già finalizzati).
  const grid = new Map<string, Map<string, MetricAccumulator[]>>()
  for (const [pKey, sub] of nested) {
    const pBucket = primaryBucket.bucketOf(pKey)
    let gsub = grid.get(pBucket)
    if (!gsub) {
      gsub = new Map<string, MetricAccumulator[]>()
      grid.set(pBucket, gsub)
    }
    for (const [sKey, acc] of sub) {
      const sBucket = secondaryBucket.bucketOf(sKey)
      const list = gsub.get(sBucket) ?? []
      list.push(acc)
      gsub.set(sBucket, list)
    }
  }

  // null (non 0) quando la cella non ha ALCUNA riga grezza — distingue "la
  // serie non è presente in questo bucket" da "presente con valore
  // legittimamente zero" (es. min di sessioni a durata 0). Fondamentale per
  // il tooltip: con ogni cella sempre riempita a 0, il tooltip mostrava
  // ogni serie ad ogni barra, incluse quelle mai lette quella settimana.
  const cellValue = (pBucket: string, sBucket: string): number | null => {
    const list = grid.get(pBucket)?.get(sBucket)
    return list && list.length > 0 ? finalizeMetric(mergeAccumulators(list), yVar, agg) : null
  }

  const isTimePrimary = TIME_GROUP_BYS.includes(config.groupBy)
  const isTimeSecondary = TIME_GROUP_BYS.includes(secondary)

  const labels = primaryBucket.order.map((key) => (isTimePrimary && key !== other ? formatTimeLabel(key, config.groupBy, t) : key))
  const series = secondaryBucket.order.map((sKey) => ({
    key: sKey,
    label: isTimeSecondary && sKey !== other ? formatTimeLabel(sKey, secondary, t) : sKey,
    data: primaryBucket.order.map((pKey) => cellValue(pKey, sKey)),
  }))

  return { labels, series }
}

// Compatibilità con i grafici già salvati prima della v3 (vincolo: nessun
// grafico esistente deve cambiare aspetto). filters legacy era un oggetto
// piatto {dateFrom,dateTo,authors,formats,devices,sources} (o {}/null) —
// viene avvolto in un FilterGroup "and" equivalente, una regola per campo
// non vuoto. metric legacy viene lasciato tal quale: parseMetric lo
// normalizza già a runtime, non serve riscriverlo qui.
export function normalizeSavedChartConfig(chart: SavedChart): ChartBuilderConfig {
  const rawFilters = chart.filters as Record<string, unknown> | null
  const filters: ChartBuilderFilters =
    rawFilters && (rawFilters as { kind?: string }).kind === 'group'
      ? (rawFilters as unknown as ChartBuilderFilters)
      : legacyFiltersToTree(rawFilters)

  return {
    chartType: chart.chart_type,
    dataSource: chart.data_source,
    groupBy: chart.group_by,
    metric: chart.metric,
    groupBySecondary: chart.group_by_secondary,
    chartMode: chart.chart_mode,
    filters,
    sortBy: chart.sort_by,
    sortOrder: chart.sort_order,
  }
}

function legacyFiltersToTree(legacy: Record<string, unknown> | null): ChartBuilderFilters {
  const group = emptyFilterGroup()
  if (!legacy) return group
  const dateFrom = (legacy.dateFrom as string | null) ?? null
  const dateTo = (legacy.dateTo as string | null) ?? null
  if (dateFrom || dateTo) {
    group.children.push({ kind: 'rule', id: `${group.id}-date`, dimension: 'start_time', op: 'range', from: dateFrom, to: dateTo })
  }
  const categoricalFields: { key: 'authors' | 'formats' | 'devices' | 'sources'; dimension: 'author' | 'format' | 'device' | 'source' }[] = [
    { key: 'authors', dimension: 'author' },
    { key: 'formats', dimension: 'format' },
    { key: 'devices', dimension: 'device' },
    { key: 'sources', dimension: 'source' },
  ]
  for (const { key, dimension } of categoricalFields) {
    const values = legacy[key] as string[] | undefined
    if (values && values.length > 0) {
      group.children.push({ kind: 'rule', id: `${group.id}-${key}`, dimension, op: 'in', values })
    }
  }
  return group
}
