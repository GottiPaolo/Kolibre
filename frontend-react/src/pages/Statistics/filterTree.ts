// Chart builder v3 (obiettivo: la stessa potenza di grafidinamici —
// vedi un precedente progetto separato — assi
// liberi, filtri con selezione dei livelli, ordinamento): albero di regole
// AND/OR annidato, ispirato al query builder di grafidinamici (app.py's
// evaluate_tree) ma con tipi/valutazione TypeScript propri, nessuna
// dipendenza da quel progetto. File puro (nessun React), separato da
// chartBuilderCompute.ts perché qui vive solo la struttura/valutazione del
// filtro, non il pivot/aggregazione.
import { splitAuthorNames } from '@/lib/authorNames'
import type { ReadingSessionRaw, TimelineEntry } from '@/lib/statsQueries'
import type { Valori } from '@/lib/i18n'
import { isoLocale } from '@/lib/format'

type Traduci = (chiave: string, valori?: Valori) => string

export type FilterDimension =
  | 'book_title'
  | 'author'
  // Dimensioni dai metadati del libro, che ora viaggiano con la sessione
  // (vedi stats_service._book_meta_map): senza queste si poteva filtrare
  // per autore e formato, cioe' quasi niente di cio' che distingue un libro.
  | 'series'
  | 'tag'
  | 'language'
  | 'publisher'
  | 'decade'
  | 'format'
  | 'device'
  | 'source'
  | 'start_time'
  | 'duration_seconds'
  | 'pages_read'
  | 'rating'

export type FilterDimensionType = 'categorical' | 'datetime' | 'numeric'

export const CATEGORICAL_DIMENSIONS = [
  'book_title', 'author', 'series', 'tag', 'language', 'publisher', 'decade',
  'format', 'device', 'source',
] as const
export type CategoricalDimension = (typeof CATEGORICAL_DIMENSIONS)[number]

// Funzione e non un oggetto costante: deve ricalcolarsi al cambio lingua,
// come fixedColumnLabels in lib/libraryColumns.ts — le `label` qui sono
// testo da mostrare, non valori che finiscono persistiti (quelli sono le
// chiavi `FilterDimension`, invarianti con la lingua).
export function dimensionMeta(t: Traduci): Record<FilterDimension, { label: string; type: FilterDimensionType }> {
  return {
    book_title: { label: t('stats.filterTree.dimension.bookTitle'), type: 'categorical' },
    author: { label: t('library.field.author'), type: 'categorical' },
    series: { label: t('library.field.series'), type: 'categorical' },
    tag: { label: t('library.field.tags'), type: 'categorical' },
    language: { label: t('library.field.language'), type: 'categorical' },
    publisher: { label: t('library.field.publisher'), type: 'categorical' },
    decade: { label: t('stats.filterTree.dimension.decade'), type: 'categorical' },
    format: { label: t('stats.filterTree.dimension.format'), type: 'categorical' },
    device: { label: t('stats.filterTree.dimension.device'), type: 'categorical' },
    source: { label: t('stats.filterTree.dimension.source'), type: 'categorical' },
    start_time: { label: t('stats.filterTree.dimension.date'), type: 'datetime' },
    duration_seconds: { label: t('stats.filterTree.dimension.sessionDuration'), type: 'numeric' },
    pages_read: { label: t('stats.filterTree.dimension.pagesReadSession'), type: 'numeric' },
    rating: { label: t('stats.filterTree.dimension.ratingStars'), type: 'numeric' },
  }
}

// Dimensioni presenti sulle righe di /stats/raw (dettaglio sessione) vs
// /stats/timeline (solo data + secondi totali per giorno) — una regola su
// una dimensione non disponibile per la sorgente corrente è vacuamente vera
// (stessa semantica già documentata oggi in chartBuilderCompute.ts's
// applyFilters: "autori/formati/... vengono ignorati quando dataSource è
// 'timeline'", qui solo generalizzata a tutte le 8 dimensioni).
export const RAW_DIMENSIONS = new Set<FilterDimension>([
  'book_title', 'author', 'series', 'tag', 'language', 'publisher', 'decade',
  'format', 'device', 'source', 'start_time', 'duration_seconds', 'pages_read', 'rating',
])
export const TIMELINE_DIMENSIONS = new Set<FilterDimension>(['start_time'])

export type DatePreset = 'last7' | 'last30' | 'last90' | 'this_week' | 'this_month' | 'this_year'

export function datePresetLabels(t: Traduci): Record<DatePreset, string> {
  return {
    last7: t('stats.filterTree.datePreset.last7'),
    last30: t('stats.filterTree.datePreset.last30'),
    last90: t('stats.filterTree.datePreset.last90'),
    this_week: t('stats.filterTree.datePreset.thisWeek'),
    this_month: t('stats.filterTree.datePreset.thisMonth'),
    this_year: t('stats.filterTree.datePreset.thisYear'),
  }
}

export interface FilterRuleCategorical {
  kind: 'rule'
  id: string
  dimension: CategoricalDimension
  op: 'in'
  values: string[]
}

export interface FilterRuleContains {
  kind: 'rule'
  id: string
  dimension: CategoricalDimension
  op: 'contains'
  text: string
}

export interface FilterRuleDateRange {
  kind: 'rule'
  id: string
  dimension: 'start_time'
  op: 'range'
  from: string | null
  to: string | null
}

export interface FilterRuleDatePreset {
  kind: 'rule'
  id: string
  dimension: 'start_time'
  op: 'preset'
  preset: DatePreset
}

export interface FilterRuleNumeric {
  kind: 'rule'
  id: string
  dimension: 'duration_seconds' | 'pages_read'
  op: 'gt' | 'lt' | 'eq'
  value: number
}

export interface FilterRuleBetween {
  kind: 'rule'
  id: string
  dimension: 'duration_seconds' | 'pages_read'
  op: 'between'
  min: number
  max: number
}

export type FilterRule =
  | FilterRuleCategorical
  | FilterRuleContains
  | FilterRuleDateRange
  | FilterRuleDatePreset
  | FilterRuleNumeric
  | FilterRuleBetween

export interface FilterGroup {
  kind: 'group'
  id: string
  logic: 'and' | 'or'
  children: (FilterRule | FilterGroup)[]
}

export type ChartBuilderFilters = FilterGroup

let uidCounter = 0
// Non _random()/Date.now() (evitati altrove nel progetto in contesti dove
// contano la riproducibilità/i workflow) — qui basta un id stabile e unico
// per la sessione del browser, solo per usarlo come React key e come target
// di modifica dell'albero (vedi FilterTreeEditor.tsx).
export function nextId(prefix: string): string {
  uidCounter += 1
  return `${prefix}-${uidCounter}-${Math.random().toString(36).slice(2, 8)}`
}

export function emptyFilterGroup(): FilterGroup {
  return { kind: 'group', id: nextId('group'), logic: 'and', children: [] }
}

// I valori di fallback qui sotto ('Sconosciuto', 'Fuori serie', 'Senza tag'…)
// NON sono tradotti di proposito: possono finire selezionati in
// LevelPicker (FilterTreeEditor.tsx), che li legge da distinctLevels più
// in basso, e salvati dentro un FilterRuleCategorical.values — che
// persiste nel FilterGroup di un SavedChart sul server. Tradurli
// cambierebbe silenziosamente il valore scritto nei filtri già salvati a
// ogni cambio di lingua, stesso motivo di STATO_DISPOSITIVO in
// lib/libraryQuery.ts.
function rowCategoricalValue(row: ReadingSessionRaw, dimension: CategoricalDimension): string {
  switch (dimension) {
    case 'book_title':
      return row.book_title || 'Sconosciuto'
    case 'format':
      return row.format || 'Sconosciuto'
    case 'device':
      return row.device_name || 'Sconosciuto'
    case 'source':
      return row.source === 'web' ? 'Web Reader' : 'KOReader'
    case 'series':
      return row.series || 'Fuori serie'
    case 'language':
      return row.language || 'Lingua ignota'
    case 'publisher':
      return row.publisher || 'Editore ignoto'
    case 'decade':
      return row.decade ? `${row.decade}s` : 'Data ignota'
    case 'author':
    case 'tag':
      // Gestiti separatamente in matchesRule (esplodono su più valori) — non
      // dovrebbero mai arrivare qui, ma un fallback ragionevole non fa male.
      return dimension === 'tag'
        ? row.tags?.join(', ') || 'Senza tag'
        : row.author || 'Autore Sconosciuto'
  }
}

function presetRange(preset: DatePreset, todayIso: string): { from: string; to: string } {
  const today = new Date(todayIso + 'T00:00:00')
  const iso = isoLocale
  const daysAgo = (n: number) => {
    const d = new Date(today)
    d.setDate(d.getDate() - n)
    return d
  }
  switch (preset) {
    case 'last7':
      return { from: iso(daysAgo(6)), to: todayIso }
    case 'last30':
      return { from: iso(daysAgo(29)), to: todayIso }
    case 'last90':
      return { from: iso(daysAgo(89)), to: todayIso }
    case 'this_week': {
      const dow = (today.getDay() + 6) % 7 // 0 = lunedì
      return { from: iso(daysAgo(dow)), to: todayIso }
    }
    case 'this_month':
      return { from: todayIso.slice(0, 8) + '01', to: todayIso }
    case 'this_year':
      return { from: todayIso.slice(0, 4) + '-01-01', to: todayIso }
  }
}

// Un libro non valutato vale 0 stelle per i confronti: e' l'unica risposta
// che non lo fa sparire da "valutazione < 3".
function valoreNumerico(row: ReadingSessionRaw, dimension: FilterDimension): number {
  if (dimension === 'pages_read') return row.pages_read
  if (dimension === 'rating') return row.rating ?? 0
  return row.duration_seconds
}

function matchesRule(rule: FilterRule, row: ReadingSessionRaw, availableDimensions: Set<FilterDimension>, todayIso: string): boolean {
  if (!availableDimensions.has(rule.dimension)) return true // vacuamente vera (dimensione non disponibile su questa sorgente)

  switch (rule.op) {
    case 'in': {
      if (rule.dimension === 'author') {
        const names = splitAuthorNames(row.author)
        return names.length === 0 ? rule.values.includes('Autore Sconosciuto') : names.some((n) => rule.values.includes(n))
      }
      // Un libro con più tag corrisponde se ANCHE SOLO UNO è fra quelli
      // scelti — stessa regola degli autori multipli qui sopra.
      if (rule.dimension === 'tag') {
        const tags = row.tags || []
        return tags.length === 0 ? rule.values.includes('Senza tag') : tags.some((t) => rule.values.includes(t))
      }
      return rule.values.includes(rowCategoricalValue(row, rule.dimension))
    }
    case 'contains': {
      const haystack = rule.dimension === 'author' ? row.author || '' : rowCategoricalValue(row, rule.dimension)
      return haystack.toLowerCase().includes(rule.text.toLowerCase())
    }
    case 'range': {
      if (rule.from && row.date < rule.from) return false
      if (rule.to && row.date > rule.to) return false
      return true
    }
    case 'preset': {
      const { from, to } = presetRange(rule.preset, todayIso)
      return row.date >= from && row.date <= to
    }
    case 'gt':
    case 'lt':
    case 'eq': {
      const v = valoreNumerico(row, rule.dimension)
      return rule.op === 'gt' ? v > rule.value : rule.op === 'lt' ? v < rule.value : v === rule.value
    }
    case 'between': {
      const v = valoreNumerico(row, rule.dimension)
      return v >= rule.min && v <= rule.max
    }
  }
}

function matchesTimelineRule(rule: FilterRule, row: TimelineEntry, availableDimensions: Set<FilterDimension>, todayIso: string): boolean {
  if (!availableDimensions.has(rule.dimension)) return true
  if (rule.op === 'range') {
    if (rule.from && row.date < rule.from) return false
    if (rule.to && row.date > rule.to) return false
    return true
  }
  if (rule.op === 'preset') {
    const { from, to } = presetRange(rule.preset, todayIso)
    return row.date >= from && row.date <= to
  }
  return true // le altre regole non hanno senso su una riga timeline, già vacuamente vere via availableDimensions
}

function evaluateGroup<TRow>(
  group: FilterGroup,
  row: TRow,
  matchRule: (rule: FilterRule, row: TRow) => boolean
): boolean {
  if (group.children.length === 0) return true
  const results = group.children.map((child) =>
    child.kind === 'group' ? evaluateGroup(child, row, matchRule) : matchRule(child, row)
  )
  return group.logic === 'and' ? results.every(Boolean) : results.some(Boolean)
}

// today in formato 'YYYY-MM-DD' — passato dal chiamante (non calcolato con
// `new Date()` qui) così i preset restano deterministici/testabili.
export function matchesFilterTree(tree: FilterGroup, row: ReadingSessionRaw, todayIso: string): boolean {
  return evaluateGroup(tree, row, (rule, r) => matchesRule(rule, r, RAW_DIMENSIONS, todayIso))
}

export function matchesFilterTreeTimeline(tree: FilterGroup, row: TimelineEntry, todayIso: string): boolean {
  return evaluateGroup(tree, row, (rule, r) => matchesTimelineRule(rule, r, TIMELINE_DIMENSIONS, todayIso))
}

export function countActiveRules(tree: FilterGroup): number {
  return tree.children.reduce(
    (sum, child) => sum + (child.kind === 'group' ? countActiveRules(child) : 1),
    0
  )
}

// Valori distinti per popolare le liste "livelli" (operatore "in") — calcolati
// sul dataset NON filtrato, stesse "sfaccettature stabili" già documentate in
// chartBuilderCompute.ts::distinctValues. Per 'author' esplode con
// splitAuthorNames (gap rispetto a oggi: un filtro "Autore A" deve poter
// catturare anche righe "Autore A & Autore B", non solo il match esatto
// sulla stringa unita).
export function distinctLevels(raw: ReadingSessionRaw[], dimension: CategoricalDimension): string[] {
  const set = new Set<string>()
  if (dimension === 'author') {
    for (const row of raw) {
      const names = splitAuthorNames(row.author)
      if (names.length === 0) set.add('Autore Sconosciuto')
      else names.forEach((n) => set.add(n))
    }
  } else if (dimension === 'tag') {
    for (const row of raw) {
      const tags = row.tags || []
      if (tags.length === 0) set.add('Senza tag')
      else tags.forEach((t) => set.add(t))
    }
  } else {
    for (const row of raw) set.add(rowCategoricalValue(row, dimension))
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b, 'it'))
}
