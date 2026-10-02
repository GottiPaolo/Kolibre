// Funzioni pure condivise dal reader EPUB — porting 1:1 della logica in
// frontend/src/ReaderView.vue (helper di colore/escaping/CFI/TOC/ricerca),
// estratte in un modulo senza React così ReaderPage.tsx resta leggibile.
import type Book from 'epubjs/types/book'
import type Section from 'epubjs/types/section'
import type { Contents, NavItem } from 'epubjs'
import type { Highlight } from '@/types/annotation'
import type { Valori } from '@/lib/i18n'
import { type EpubSearchMatch, findInSection, loadSectionDocument, locationsTotal } from './EpubTypes'
import { leggiLingua, localeDi } from '@/lib/i18n'

export interface HighlightColorOption {
  value: string
  hex: string
}

export const HIGHLIGHT_COLORS: HighlightColorOption[] = [
  { value: 'yellow', hex: '#e6c84b' },
  { value: 'green', hex: '#7a937a' },
  { value: 'blue', hex: '#5a8bb0' },
  { value: 'pink', hex: '#c05a8a' },
]

export function colorHex(colorValue: string | null | undefined): string {
  return (HIGHLIGHT_COLORS.find((c) => c.value === colorValue) ?? HIGHLIGHT_COLORS[0]).hex
}

export function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s
}

// Distingue una selezione "singola parola" (candidata al lookup nel
// dizionario, vedi ReaderPage.tsx) da una selezione multi-parola (che resta
// solo evidenziabile) — nessuno spazio/a capo interno, almeno una lettera,
// lunghezza ragionevole per escludere blob di testo senza spazi.
export function isSingleWord(text: string): boolean {
  return text.length > 0 && text.length <= 40 && !/\s/.test(text) && /\p{L}/u.test(text)
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// Usato solo per l'estratto nella sidebar di ricerca — testo già escapato,
// poi iniettato via dangerouslySetInnerHTML (equivalente Vue: v-html) solo
// per evidenziare <strong> il match.
export function highlightMatchHtml(excerpt: string, query: string): string {
  const escaped = escapeHtml(excerpt)
  const escapedQuery = escapeHtml(query).trim().replace(/[-[\]{}()*+?.,\\^$|#\s]/g, '\\$&')
  if (!escapedQuery) return escaped
  return escaped.replace(new RegExp(escapedQuery, 'gi'), (m) => `<strong>${m}</strong>`)
}

// Mirrors the Obsidian plugin's own source badge (plugins/obsidian/kolibre-highlights/main.js)
// so the same highlight reads the same way everywhere.
//
// Riceve `t` come parametro (e non lo importa a livello di modulo) perche'
// viene chiamata durante il render di ReaderPage/EpubSidebar: deve restare
// reattiva a un cambio di lingua a caldo, stesso motivo di fixedColumnLabels
// in lib/libraryColumns.ts.
export function formatHighlightSource(hl: Highlight | null, t: (chiave: string, valori?: Valori) => string): string {
  if (!hl) return ''
  if (hl.source === 'device') return `📱 ${hl.device_name || t('reader.highlight.sourceDeviceFallback')}`
  if (hl.source === 'calibre') return '📚 Calibre'
  return '🌐 Web'
}

export function formatHighlightMeta(hl: Highlight | null, t: (chiave: string, valori?: Valori) => string): string {
  if (!hl) return ''
  // Data lasciata in formato italiano indipendentemente dalla lingua
  // dell'app — stessa scelta di .toLocaleString('it-IT') per i numeri nel
  // resto del programma (vedi il commento su STATO_DISPOSITIVO in
  // lib/libraryQuery.ts): qui non c'e' nemmeno un round-trip da rompere,
  // e' solo testo mostrato una volta.
  const dateStr = hl.created_at
    ? new Date(hl.created_at).toLocaleDateString(localeDi(leggiLingua()), { day: 'numeric', month: 'short', year: 'numeric' })
    : null
  return [dateStr, formatHighlightSource(hl, t)].filter(Boolean).join(' · ')
}

// Reader-created ('web') highlights store a single self-contained Range CFI
// in cfi_start (epub.js's own contents.cfiFromRange() output, parent+start+
// end already joined). Device-origin highlights instead get cfi_start/
// cfi_end as two INDEPENDENT point CFIs out of services/position_converter
// (ported from BookOrbit, which has no notion of epub.js's joined Range CFI
// form) — resolving a bare point CFI gives a zero-width Range, so the
// overlay renders nothing visible even though jumping to it works fine.
// Re-joins the two points into a real Range CFI by factoring out the first
// content-doc step (identical in both: same chapter, same parse) as the
// shared "parent" component.
const RANGE_CFI_FIRST_STEP = /^epubcfi\(([^!]*!)(\/\d+(?:\[[^\]]*\])?)(.*)\)$/

export function highlightRenderCfi(hl: Highlight): string {
  const start = hl.cfi_start ?? ''
  if (!hl.cfi_end || hl.cfi_end === start || start.includes(',')) return start
  const startMatch = start.match(RANGE_CFI_FIRST_STEP)
  const endMatch = hl.cfi_end.match(RANGE_CFI_FIRST_STEP)
  if (!startMatch || !endMatch) return start
  const [, base, step1, restStart] = startMatch
  const restEnd = endMatch[3]
  return `epubcfi(${base}${step1},${restStart},${restEnd})`
}

export interface FlatTocEntry {
  href: string
  path: string[]
}

// Flattens epub.js's nested TOC (item.subitems) into a flat list of
// {href, path}, where `path` is the full ancestor-to-self title chain —
// mirrors the " ▸ "-joined convention the KOReader community patch already
// uses for the same purpose, so both highlight sources parse identically on
// the Obsidian side.
export function flattenToc(items: NavItem[] | undefined, ancestors: string[] = []): FlatTocEntry[] {
  let flat: FlatTocEntry[] = []
  for (const item of items || []) {
    const path = [...ancestors, (item.label || '').trim()]
    flat.push({ href: item.href, path })
    if (item.subitems && item.subitems.length) {
      flat = flat.concat(flattenToc(item.subitems, path))
    }
  }
  return flat
}

export function stripFragment(href: string | null | undefined): string {
  return (href || '').split('#')[0]
}

// Chapter path for a highlight (Obsidian export needs a heading path that
// recreates the book's real structure). Derived purely from the CFI at save
// time, no extra state needs threading through the selection popup.
export function chapterPathForCfi(book: Book, tocItems: NavItem[], cfi: string): string | null {
  try {
    const section = book.spine.get(cfi)
    if (!section) return null
    const sectionHref = stripFragment(section.href)
    const flat = flattenToc(tocItems)
    let match = flat.find((e) => stripFragment(e.href) === sectionHref)
    if (!match) {
      // Many EPUBs only have TOC entries for top-level chapter files, not
      // every finer subsection — fall back to the closest TOC entry at or
      // before this section in spine order, rather than giving up entirely.
      let bestIndex = -1
      for (const e of flat) {
        const s = book.spine.get(e.href)
        if (s && s.index <= section.index && s.index > bestIndex) {
          match = e
          bestIndex = s.index
        }
      }
    }
    return match ? match.path.filter(Boolean).join(' ▸ ') : null
  } catch {
    return null
  }
}

// A pseudo-page number from epub.js's own location index — only meaningful
// within epub.js itself (won't match KOReader's real page count for the
// same book). Omitted entirely if locations haven't finished generating yet
// rather than blocking the save on it.
export function pseudoPageForCfi(book: Book, locationsReady: boolean, cfi: string): number | null {
  if (!locationsReady) return null
  try {
    const pct = book.locations.percentageFromCfi(cfi)
    const idx = Math.round(pct * locationsTotal(book))
    return idx > 0 ? idx : 1
  } catch {
    return null
  }
}

// Ricerca client-side sull'intero libro (book.spine), sezione per sezione —
// non c'è alcuna mappatura server-side testo→CFI (l'indice fulltext è
// costruito dal testo estratto, non da epub.js), quindi sia il deep-link
// da ricerca fulltext sia la sidebar "Cerca nel libro" passano da qui.
export async function searchInBook(book: Book, query: string): Promise<EpubSearchMatch[]> {
  const perSectionMatches: Promise<EpubSearchMatch[]>[] = []
  book.spine.each((section: Section) => {
    perSectionMatches.push(
      loadSectionDocument(section, book.load.bind(book))
        .then(() => {
          const matches = findInSection(section, query)
          section.unload()
          return matches
        })
        .catch(() => [] as EpubSearchMatch[])
    )
  })
  const results = await Promise.all(perSectionMatches)
  return results.flat()
}


/**
 * Voce del sommario che corrisponde alla posizione corrente, cercando per
 * file (href) invece che per CFI.
 *
 * epub.js, a ogni spostamento, dice in quale FILE dell'EPUB ci si trova
 * (`location.start.href`); il sommario elenca href con l'eventuale ancora
 * (`testo/parte3.xhtml#cap7`). Confrontare la sola parte di percorso e'
 * quindi sufficiente e robusto.
 *
 * Limite noto e accettato: quando piu' capitoli vivono nello STESSO file e si
 * distinguono solo per l'ancora, questa funzione non puo' dire a quale dei due
 * siamo arrivati e restituisce il primo. Distinguere richiederebbe di
 * confrontare le posizioni delle ancore nel documento reso, che e' molto piu'
 * lavoro per un'etichetta in fondo allo schermo.
 */
export function tocEntryForHref(
  items: NavItem[],
  href: string | null | undefined
): { label: string; href: string } | null {
  if (!href) return null
  const file = (h: string) => h.split('#')[0].replace(/^\.?\//, '')
  const cercato = file(href)

  let trovato: { label: string; href: string } | null = null
  const visita = (nodi: NavItem[]) => {
    for (const n of nodi) {
      // Il piu' PROFONDO che combacia vince: un sottocapitolo e' piu'
      // informativo della parte che lo contiene.
      if (n.href && file(n.href) === cercato && !trovato) trovato = { label: n.label.trim(), href: n.href }
      if (n.subitems?.length) visita(n.subitems)
    }
  }
  visita(items)
  return trovato
}

// ── Note a piè di pagina ──────────────────────────────────────────────────

/**
 * Un link dentro il libro punta a una nota?
 *
 * EPUB 3 lo dice: `epub:type="noteref"` sul rimando. EPUB 2 non ha nulla del
 * genere, e la maggior parte dei libri reali sono EPUB 2 o EPUB 3 scritti
 * male — quindi servono anche indizi. Sono deliberatamente stretti: aprire un
 * popup al posto di un vero salto di capitolo sarebbe peggio del problema che
 * si vuole risolvere.
 *
 *   - un rimando a nota e' quasi sempre un numero o un simbolo corto
 *     ("1", "12", "*", "[3]"): se il testo del link e' una frase, non lo e';
 *   - oppure sta dentro un <sup>, che e' come si scrivono gli esponenti;
 *   - oppure ha una classe che lo dichiara (note, fn, footnote, endnote).
 *
 * In tutti i casi serve un frammento (#...): senza, non c'e' un punto preciso
 * da mostrare e tanto vale lasciare la navigazione normale.
 */
/**
 * Il link di RITORNO, quello che dalla nota riporta al punto del testo.
 *
 * Ha la stessa forma del rimando — un numeretto con un frammento — e
 * isNoteLink lo accetta. Sul rimando aprire il popup e' giusto; sul ritorno
 * no: li' il salto e' proprio quello che serve, e intercettarlo lascerebbe
 * il lettore in fondo al capitolo con un popup che ripete il paragrafo da
 * cui era partito.
 */
export function isNoteBacklink(a: HTMLAnchorElement): boolean {
  const indizi = `${a.className} ${a.getAttribute('epub:type') || ''} ${a.getAttribute('rel') || ''}`
  return /\b(backlink|back-link|noteback|note-back|footnote-back|referrer|torna)\b/i.test(indizi)
}

export function isNoteLink(a: HTMLAnchorElement): boolean {
  const href = a.getAttribute('href') || ''
  if (!href.includes('#')) return false

  const epubType = a.getAttribute('epub:type') || a.getAttribute('type') || ''
  if (/\bnoteref\b/i.test(epubType)) return true

  const classi = `${a.className} ${a.parentElement?.className ?? ''}`
  if (/\b(note|fn|footnote|endnote|nota)\b/i.test(classi)) return true

  const testo = (a.textContent || '').trim()
  // Parentesi di ogni tipo: nei libri reali il rimando compare come
  // "4", "{56}", "[3]", "(12)". Fino a 6 caratteri per far stare "{100}".
  const cortoENumerico = testo.length > 0 && testo.length <= 6
    && /^[[({<]?[\d*†‡§¶]+[\])}>]?$/.test(testo)
  if (!cortoENumerico) return false

  // Un numero corto da solo non basta: potrebbe essere un indice o una
  // numerazione di capitolo. Se sta in un <sup> e' un esponente, quindi una
  // nota; altrimenti si richiede che il link punti a un ALTRO documento
  // (il classico file di note a fine volume) o a un id che si dichiara nota.
  // Sia <sup><a>4</a></sup> sia <a><sup>4</sup></a>: nei libri reali si
  // incontrano entrambe le nidificazioni, e la prima versione vedeva solo
  // quella esterna.
  if (a.closest('sup') || a.querySelector('sup')) return true
  const frammento = href.split('#')[1] || ''
  return /^(fn|note|nota|ftn|endnote)/i.test(frammento) || href.split('#')[0] !== ''
}

/**
 * Testo della nota puntata da `href`, oppure null.
 *
 * SOLO TESTO, mai HTML: il contenuto arriva da un EPUB, che e' un file
 * scaricato da internet e va trattato come non fidato. Inserirne il markup
 * nella nostra pagina reintrodurrebbe esattamente la falla chiusa
 * disattivando gli script nell'iframe (vedi ReaderPage). Una nota a pie' di
 * pagina e' testo: non ci perdiamo niente.
 */
/**
 * Il documento della nota, a partire da un percorso RELATIVO al capitolo che
 * si sta leggendo.
 *
 * E' il punto in cui la prima versione si rompeva, ed e' anche il caso piu'
 * comune nei libri veri: `href="../Text/footnotes.xhtml#footnote-0004"` e'
 * relativo al file corrente, mentre `spine.get()` vuole un percorso relativo
 * all'OPF. Passandogli "../Text/..." non trovava niente e la nota risultava
 * assente — in silenzio, perche' "non trovata" e "non risolta" finivano nello
 * stesso ramo.
 *
 * Si risolve con l'URL del browser (che sa fare "../") usando come base il
 * capitolo corrente, e si ricade su tentativi piu' grossolani: il percorso
 * cosi' com'e', e in ultimo il solo nome del file, che basta nella stragrande
 * maggioranza degli EPUB dove i documenti hanno nomi distinti.
 */
function resolveSection(book: Book, file: string, baseHref?: string): Section | null {
  const tentativi: string[] = []
  if (baseHref) {
    try {
      tentativi.push(new URL(file, `http://epub.invalid/${baseHref}`).pathname.slice(1))
    } catch {
      // base non valida: si prosegue con gli altri tentativi
    }
  }
  tentativi.push(file, file.replace(/^\.{1,2}\//, ''))
  for (const t of tentativi) {
    const s = book.spine.get(t)
    if (s) return s
  }
  const nome = file.split('/').pop() || ''
  return nome ? book.spine.get(nome) : null
}


/**
 * Il nocciolo di un marcatore di nota: "[12]" e "12." danno entrambi "12".
 * Serve a confrontare il numero in testa alla nota con quello del rimando
 * che e' stato toccato, che nei libri veri sono scritti diversi.
 */
function nocciolo(t: string | null | undefined): string {
  return (t || '').trim().replace(/^[[({<]+|[\])}>]+$/g, '').replace(/[.)°:,;]+$/, '').trim()
}

/**
 * Il testo della nota, senza il numero con cui si apre.
 *
 * Quasi tutti gli EPUB ripetono il numero in testa alla nota — spesso come
 * link di ritorno al punto del testo. Nel libro stampato serve a ritrovare
 * il rimando scorrendo la pagina; in un popup che si e' aperto proprio
 * perche' hai toccato quel rimando, non dice niente. KOReader infatti
 * mostra solo la nota, ed e' il comportamento che si vuole qui.
 *
 * Non si indovina: `marcatore` e' il testo del rimando cliccato, e si toglie
 * solo cio' che gli corrisponde. Senza questo vincolo una nota che comincia
 * davvero per numero ("12 marzo 1848: in una lettera scrive...") verrebbe
 * mutilata.
 * L'unica cosa che si toglie a prescindere e' il link di ritorno, che si
 * riconosce da se' (isNoteBacklink) e non e' testo della nota in nessun caso.
 */
function testoNota(el: Element, marcatore?: string): string {
  const copia = el.cloneNode(true) as Element
  copia.querySelectorAll('a').forEach((a) => {
    if (isNoteBacklink(a as HTMLAnchorElement)) a.remove()
  })
  const atteso = nocciolo(marcatore)
  if (atteso) {
    // I primi nodi che ripetono il marcatore se ne vanno: puo' essere un
    // <a>, un <sup>, uno <span>, o piu' d'uno annidati.
    while (copia.firstChild) {
      const n = copia.firstChild
      if (n.nodeType === Node.TEXT_NODE && !(n.textContent || '').trim()) {
        n.remove()
        continue
      }
      if (n.nodeType === Node.ELEMENT_NODE && nocciolo(n.textContent) === atteso) {
        n.remove()
        continue
      }
      break
    }
  }
  let testo = (copia.textContent || '').trim()
  // Il numero scritto come testo semplice, non dentro un elemento suo:
  // stesso confronto, sul primo pezzo di testo.
  if (atteso) {
    const m = testo.match(/^(\S{1,8})\s+(\S[\s\S]*)$/)
    if (m && nocciolo(m[1]) === atteso) testo = m[2]
    // La punteggiatura che stava attaccata al numero ("<a>1</a>. Testo")
    // resta orfana quando il numero se ne va. Solo quella di coda: una
    // virgoletta o un trattino aprono la nota e vanno tenuti.
    testo = testo.replace(/^[\s.,;:)\]}]+/, '')
  }
  return testo
}

export async function loadNoteText(
  book: Book,
  contents: Contents,
  href: string,
  baseHref?: string,
  marcatore?: string
): Promise<string | null> {
  const [file, frammento] = href.split('#')
  if (!frammento) return null

  let doc: Document | null = null
  if (!file) {
    doc = contents.document
  } else {
    try {
      const section = resolveSection(book, file, baseHref)
      if (!section) return null
      doc = (await book.load(section.href)) as Document
    } catch {
      return null
    }
  }
  if (!doc) return null

  const target = doc.getElementById(frammento)
  if (!target) return null

  // L'ancora puo' essere sulla nota stessa (<aside>, <li>, <p>) oppure essere
  // un segnaposto vuoto subito prima del testo: in quel caso si sale al
  // contenitore, e se anche quello e' vuoto si prende l'elemento successivo.
  let testo = testoNota(target, marcatore)
  if (testo.length < 3 && target.parentElement) {
    testo = testoNota(target.parentElement, marcatore)
  }
  if (testo.length < 3 && target.nextElementSibling) {
    testo = testoNota(target.nextElementSibling, marcatore)
  }
  return testo.length < 3 ? null : testo
}
