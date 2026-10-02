// Porting del motore del Navigatore Biblioteca da frontend/src/App.vue
// (tokenizeQuery/parseQuery/evalQueryNode + browserFieldDefs/browserTree,
// righe ~5184-5570). Interamente client-side: il backend non offre alcun
// endpoint di ricerca/filtro testuale sui libri (verificato — vedi
// backend/app/api/books.py), quindi questa logica va riprodotta qui pari
// pari, non chiamata da remoto.
import type { Book, CustomColumn } from '@/types/library'
import { foldAccents } from './foldAccents'
import { splitAuthorNames } from './authorNames'
import type { Valori } from './i18n'

type Traduci = (chiave: string, valori?: Valori) => string

// ── Definizioni di campo (Navigatore Biblioteca) ───────────────────────────

export interface FieldDef {
  key: string
  label: string
  queryField: string
  getValues: (book: Book) => string[]
  formatDisplay?: (value: string) => string
}

const FIELD_NAME_ALIASES: Record<string, string> = {
  tag: 'tags',
  author: 'authors',
  format: 'formats',
  editore: 'publisher',
  lingua: 'language',
  valutazione: 'rating',
}

function canonicalField(field: string): string {
  const lower = field.toLowerCase()
  return FIELD_NAME_ALIASES[lower] ?? lower
}

export function buildFieldDefs(customColumns: CustomColumn[], t: Traduci): FieldDef[] {
  const fixed: FieldDef[] = [
    { key: 'tags', label: t('library.field.tags'), queryField: 'tags', getValues: (b) => b.tags ?? [] },
    {
      key: 'author',
      label: t('library.field.author'),
      queryField: 'authors',
      getValues: (b) => splitAuthorNames(b.author),
    },
    { key: 'series', label: t('library.field.series'), queryField: 'series', getValues: (b) => (b.series ? [b.series] : []) },
    { key: 'formats', label: t('library.field.formats'), queryField: 'formats', getValues: (b) => b.formats ?? [] },
    {
      key: 'publisher',
      label: t('library.field.publisher'),
      queryField: 'publisher',
      getValues: (b) => (b.publisher ? [b.publisher] : []),
    },
    {
      key: 'language',
      label: t('library.field.language'),
      queryField: 'language',
      getValues: (b) => (b.language ? [b.language] : []),
    },
    {
      key: 'rating',
      label: t('library.field.rating'),
      queryField: 'rating',
      getValues: (b) => (b.rating ? [String(b.rating)] : []),
      formatDisplay: (v) => '★'.repeat(Number(v)),
    },
  ]

  // Una entry per ogni colonna personalizzata non di tipo data — stessa
  // esclusione del Vue esistente (una data non ha un insieme di "valori"
  // sensato da navigare ad albero).
  const custom: FieldDef[] = customColumns
    .filter((col) => col.datatype !== 'datetime')
    .map((col) => ({
      key: `#${col.label}`,
      label: col.name,
      queryField: `#${col.label}`,
      getValues: (b) => {
        const v = b[`#${col.label}`]
        return v === null || v === undefined || v === '' ? [] : [String(v)]
      },
    }))

  return [...fixed, ...custom]
}

function findDef(defs: FieldDef[], field: string): FieldDef | undefined {
  const canonical = canonicalField(field)
  return defs.find((d) => d.queryField.toLowerCase() === canonical || d.queryField.toLowerCase() === field.toLowerCase())
}

// ── Tokenizer / parser ──────────────────────────────────────────────────────

const QUERY_TOKEN_RE = /\(|\)|[A-Za-z_#][\w#]*:"(?:[^"\\]|\\.)*"|[A-Za-z_#][\w#]*:[^\s()]+|"(?:[^"\\]|\\.)*"|[^\s()]+/g

function tokenize(query: string): string[] {
  return query.match(QUERY_TOKEN_RE) ?? []
}

function unquote(raw: string): string {
  if (raw.startsWith('"') && raw.endsWith('"')) {
    return raw.slice(1, -1).replace(/\\(.)/g, '$1')
  }
  return raw
}

export type QueryNode =
  | { type: 'and'; children: QueryNode[] }
  | { type: 'or'; children: QueryNode[] }
  | { type: 'not'; child: QueryNode }
  | { type: 'term'; field: string; value: string; exact: boolean }
  | { type: 'freetext'; value: string }

function parseFieldToken(tok: string): QueryNode {
  const sep = tok.indexOf(':')
  const field = tok.slice(0, sep)
  let value = unquote(tok.slice(sep + 1))
  let exact = false
  if (value.startsWith('=')) {
    exact = true
    value = value.slice(1)
  }
  return { type: 'term', field, value, exact }
}

const FIELD_TOKEN_RE = /^[A-Za-z_#][\w#]*:/

class Parser {
  tokens: string[]
  pos = 0
  constructor(tokens: string[]) {
    this.tokens = tokens
  }
  peek(): string | undefined {
    return this.tokens[this.pos]
  }
  consume(): string | undefined {
    return this.tokens[this.pos++]
  }
  parseOr(): QueryNode {
    const children = [this.parseAnd()]
    while (this.peek()?.toLowerCase() === 'or') {
      this.consume()
      children.push(this.parseAnd())
    }
    return children.length === 1 ? children[0] : { type: 'or', children }
  }
  parseAnd(): QueryNode {
    const children: QueryNode[] = []
    for (;;) {
      const next = this.peek()
      if (next === undefined || next === ')' || next.toLowerCase() === 'or') break
      if (next.toLowerCase() === 'and') {
        this.consume()
        continue
      }
      children.push(this.parseNot())
    }
    return children.length === 1 ? children[0] : { type: 'and', children }
  }
  parseNot(): QueryNode {
    if (this.peek()?.toLowerCase() === 'not') {
      this.consume()
      return { type: 'not', child: this.parseAtom() }
    }
    return this.parseAtom()
  }
  parseAtom(): QueryNode {
    const tok = this.consume()
    if (tok === undefined) return { type: 'freetext', value: '' }
    if (tok === '(') {
      const node = this.parseOr()
      if (this.peek() === ')') this.consume()
      return node
    }
    if (FIELD_TOKEN_RE.test(tok)) return parseFieldToken(tok)
    return { type: 'freetext', value: unquote(tok) }
  }
}

export function parseQuery(query: string): QueryNode | null {
  const tokens = tokenize(query.trim())
  if (tokens.length === 0) return null
  return new Parser(tokens).parseOr()
}

export function evalQueryNode(node: QueryNode, book: Book, defs: FieldDef[]): boolean {
  switch (node.type) {
    case 'and':
      return node.children.every((c) => evalQueryNode(c, book, defs))
    case 'or':
      return node.children.some((c) => evalQueryNode(c, book, defs))
    case 'not':
      return !evalQueryNode(node.child, book, defs)
    case 'term': {
      const def = findDef(defs, node.field)
      if (!def) return false
      const values = def.getValues(book)
      // Accenti ignorati anche nei filtri per campo: "lingua:francais" deve
      // trovare "français" come "Emile" trova "Émile". Vedi foldAccents.
      const needle = foldAccents(node.value)
      return node.exact
        ? values.some((v) => foldAccents(v) === needle)
        : values.some((v) => foldAccents(v).includes(needle))
    }
    case 'freetext': {
      const needle = foldAccents(node.value)
      if (!needle) return true
      return (
        foldAccents(book.title).includes(needle) ||
        foldAccents(book.author).includes(needle) ||
        (book.tags ?? []).some((t) => foldAccents(t).includes(needle))
      )
    }
  }
}

export function matchesQuery(query: string, book: Book, defs: FieldDef[]): boolean {
  const ast = parseQuery(query)
  if (!ast) return true
  return evalQueryNode(ast, book, defs)
}

// ── Query editabile: split/estrazione/scrittura per conjunct AND ──────────

// Spacca la query nei conjunct AND di primo livello, rispettando
// parentesi/quote (necessario perché lo stato di un campo può essere
// sparso su più conjunct separati, es. `formats:"=PDF" and not
// formats:"=EPUB"` — leggere solo il primo farebbe "sparire" metà stato).
export function splitTopLevelAnd(query: string): string[] {
  const tokens = tokenize(query.trim())
  const conjuncts: string[][] = [[]]
  let depth = 0
  for (const tok of tokens) {
    if (tok === '(') depth++
    if (tok === ')') depth--
    if (depth === 0 && tok.toLowerCase() === 'and') {
      conjuncts.push([])
      continue
    }
    conjuncts[conjuncts.length - 1].push(tok)
  }
  return conjuncts.map((c) => c.join(' ')).filter((c) => c.trim().length > 0)
}

function fieldsInConjunct(conjunct: string): string[] {
  const tokens = tokenize(conjunct)
  const fields: string[] = []
  for (const tok of tokens) {
    if (FIELD_TOKEN_RE.test(tok)) {
      fields.push(canonicalField(tok.slice(0, tok.indexOf(':'))))
    }
  }
  return fields
}

// Un conjunct "appartiene" a un campo solo se OGNI field-term al suo
// interno è di quel campo — così si tocca solo ciò che l'UI stessa
// potrebbe aver generato, non testo scritto a mano dall'utente che mischia
// campi diversi in un solo conjunct.
function conjunctBelongsToField(conjunct: string, queryField: string): boolean {
  const fields = fieldsInConjunct(conjunct)
  if (fields.length === 0) return false
  const canonical = canonicalField(queryField)
  return fields.every((f) => f === canonical)
}

export interface FieldState {
  include: string[]
  exclude: string[]
}

export function extractFieldState(query: string, def: FieldDef): FieldState {
  const include: string[] = []
  const exclude: string[] = []
  for (const conjunct of splitTopLevelAnd(query)) {
    if (!conjunctBelongsToField(conjunct, def.queryField)) continue
    const ast = parseQuery(conjunct)
    if (!ast) continue
    // Il "not" (se presente) è già dentro l'AST del conjunct (parseQuery lo
    // riconosce come token) — passare qui un negated iniziale calcolato di
    // nuovo da regex applicherebbe la negazione due volte, annullandola.
    collectTermValues(ast, false).forEach(({ value, excluded }) => {
      if (excluded) exclude.push(value)
      else include.push(value)
    })
  }
  return { include: dedupe(include), exclude: dedupe(exclude) }
}

function collectTermValues(node: QueryNode, negated: boolean): { value: string; excluded: boolean }[] {
  switch (node.type) {
    case 'term':
      return [{ value: node.value, excluded: negated }]
    case 'not':
      return collectTermValues(node.child, !negated)
    case 'and':
    case 'or':
      return node.children.flatMap((c) => collectTermValues(c, negated))
    default:
      return []
  }
}

function dedupe(arr: string[]): string[] {
  return Array.from(new Set(arr))
}

function quoteExact(value: string): string {
  return `"=${value.replace(/"/g, '\\"')}"`
}

export function buildFieldClause(def: FieldDef, include: string[], exclude: string[]): string {
  const parts: string[] = []
  if (include.length === 1) {
    parts.push(`${def.queryField}:${quoteExact(include[0])}`)
  } else if (include.length > 1) {
    parts.push(`(${include.map((v) => `${def.queryField}:${quoteExact(v)}`).join(' or ')})`)
  }
  if (exclude.length === 1) {
    parts.push(`not ${def.queryField}:${quoteExact(exclude[0])}`)
  } else if (exclude.length > 1) {
    parts.push(`not (${exclude.map((v) => `${def.queryField}:${quoteExact(v)}`).join(' or ')})`)
  }
  return parts.join(' and ')
}

export function setFieldClauseInQuery(query: string, def: FieldDef, clause: string): string {
  const remaining = splitTopLevelAnd(query).filter((c) => !conjunctBelongsToField(c, def.queryField))
  const result = clause ? [...remaining, clause] : remaining
  return result.join(' and ')
}

// Click semplice: se il valore è già l'unico incluso -> diventa escluso;
// se già l'unico escluso -> torna a "nessuno"; altrimenti diventa l'unico
// incluso (sostituisce l'intera selezione del campo). Cmd/Ctrl+click
// (additive): toggla solo quel valore dentro/fuori la selezione OR
// multi-valore, senza toccare le altre.
export function cycleBrowserFilter(query: string, def: FieldDef, value: string, additive: boolean): string {
  const state = extractFieldState(query, def)
  let next: FieldState
  if (additive) {
    const included = state.include.includes(value)
    next = {
      include: included ? state.include.filter((v) => v !== value) : [...state.include, value],
      exclude: state.exclude.filter((v) => v !== value),
    }
  } else if (state.include.length === 1 && state.include[0] === value) {
    next = { include: [], exclude: [value] }
  } else if (state.exclude.length === 1 && state.exclude[0] === value) {
    next = { include: [], exclude: [] }
  } else {
    next = { include: [value], exclude: [] }
  }
  return setFieldClauseInQuery(query, def, buildFieldClause(def, next.include, next.exclude))
}

export interface BrowserTreeValue {
  value: string
  display: string
  count: number
  state: 'include' | 'exclude' | 'none'
}

export interface BrowserTreeField {
  def: FieldDef
  values: BrowserTreeValue[]
}

// Conteggi calcolati su TUTTI i libri della libreria attiva (non filtrati
// dalla query corrente) — replica il comportamento di default del Tag
// Browser di Calibre.
/**
 * L'albero del Navigatore.
 *
 * `valoriDalServer`, quando c'è, sostituisce il conteggio fatto sui libri
 * caricati: sopra la soglia di impaginazione quelli sono duecento, e l'albero
 * elencherebbe i valori di una pagina spacciandoli per quelli della
 * biblioteca. I campi che il server non conosce — presenza sui dispositivi,
 * avanzamento di lettura, che non stanno dentro `Book` — continuano a
 * contarsi sui libri caricati: sono già filtrati per ciò che si vede, ed è
 * l'unico posto dove quel dato esiste.
 */
export function buildBrowserTree(
  books: Book[],
  defs: FieldDef[],
  query: string,
  valoriDalServer?: Record<string, { valore: string; libri: number }[]>
): BrowserTreeField[] {
  return defs.map((def) => {
    const counts = new Map<string, number>()
    const dalServer = valoriDalServer?.[def.key]
    if (dalServer) {
      for (const v of dalServer) counts.set(v.valore, v.libri)
    } else {
      for (const book of books) {
        for (const v of def.getValues(book)) {
          counts.set(v, (counts.get(v) ?? 0) + 1)
        }
      }
    }
    const state = extractFieldState(query, def)
    const values: BrowserTreeValue[] = Array.from(counts.entries())
      .sort((a, b) => a[0].localeCompare(b[0], 'it'))
      .map(([value, count]) => ({
        value,
        display: def.formatDisplay ? def.formatDisplay(value) : value,
        count,
        state: state.include.includes(value) ? 'include' : state.exclude.includes(value) ? 'exclude' : 'none',
      }))
    return { def, values }
  })
}

export function countActiveFilters(query: string, defs: FieldDef[]): number {
  return defs.reduce((sum, def) => {
    const state = extractFieldState(query, def)
    return sum + state.include.length + state.exclude.length
  }, 0)
}

// ── Campi che non stanno dentro il libro ───────────────────────────────────
//
// Il Navigatore costruisce le sue voci da `Book`, ma due colonne della
// tabella non vivono li': la presenza su un dispositivo (che dipende da
// quale dispositivo si guarda) e l'avanzamento di lettura (che arriva da
// una query sua). Erano quindi le uniche colonne che si potevano vedere
// in tabella ma non usare per filtrare — difetto riscontrato in uso.
//
// Si costruiscono qui come definizioni di campo normali, chiudendo sulle
// mappe che la pagina ha gia' in mano: da li' in poi sono campi come tutti
// gli altri, compresa la scrittura nella barra di ricerca.

// Etichette leggibili per gli stati di deviceFormat.deviceBookColumnState —
// NON tradotte di proposito: diventano il VALORE del termine di ricerca
// quando si clicca una voce del Navigatore (vedi buildFieldClause più sopra,
// es. `device_3:"=In coda"`), quindi sono sintassi tanto quanto i nomi dei
// campi — tradurle romperebbe una query già scritta cambiando lingua, come
// per "vivente"/"deceduto" nel linguaggio di ricerca di Autori
// (authorsQuery.ts).
const STATO_DISPOSITIVO: Record<string, string> = {
  on: 'Sì',
  queued: 'In coda',
  pending_delete: 'Da rimuovere',
  off: 'No',
}

export function buildDeviceFieldDefs(
  devices: { id: number; name: string }[],
  statoPerLibro: Record<number, Record<number, string>>,
  t: Traduci
): FieldDef[] {
  return devices.map((d) => ({
    key: `device-${d.id}`,
    label: t('library.field.onDevice', { name: d.name }),
    // Un nome di dispositivo puo' contenere spazi e accenti, che nel
    // linguaggio della ricerca non sono ammessi in un nome di campo: l'id
    // e' stabile e sempre scrivibile.
    queryField: `device_${d.id}`,
    getValues: (book) => [STATO_DISPOSITIVO[statoPerLibro[book.id]?.[d.id] ?? 'off'] ?? 'No'],
  }))
}

export function buildProgressFieldDef(percentualePerLibro: Record<number, number>, t: Traduci): FieldDef {
  return {
    key: 'progress',
    label: t('library.field.readingStatus'),
    queryField: 'lettura',
    // A fasce e non a percentuali esatte: "47%" come voce di un elenco non
    // serve a nessuno, "In lettura" si'. Valori NON tradotti per lo stesso
    // motivo di STATO_DISPOSITIVO qui sopra: sono il testo che finisce
    // scritto nella query.
    getValues: (book) => {
      const p = percentualePerLibro[book.id]
      if (p == null) return ['Non iniziato']
      if (p >= 99) return ['Finito']
      if (p <= 1) return ['Non iniziato']
      return ['In lettura']
    },
  }
}
