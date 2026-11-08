import { leggiLocale, scriviLocale } from '@/lib/memoriaLocale'
import { PREFERENZE_PREDEFINITE, type Carattere, type OverrideColori, type PreferenzeLettura, type Tema } from './EpubTheme'
// Preferenze di lettura persistite lato client (layout pagina, dimensione
// testo) — chiavi 'kolibre_reader_*', stesso namespace localStorage
// 'kolibre_*' già usato altrove nell'app (vedi useStyleVariant.ts,
// libraryColumns.ts) ma non condiviso con quei moduli: sono specifiche del
// reader EPUB, lette una sola volta all'apertura di questa finestra.
const PAGE_LAYOUT_KEY = 'kolibre_reader_page_layout'
const FONT_SCALE_KEY = 'kolibre_reader_font_scale'

export type PageLayout = 'single' | 'double'

export const FONT_SCALE_MIN = 80
export const FONT_SCALE_MAX = 200
export const FONT_SCALE_STEP = 10
export const FONT_SCALE_DEFAULT = 100

export function clampFontScale(value: number): number {
  return Math.min(FONT_SCALE_MAX, Math.max(FONT_SCALE_MIN, Math.round(value)))
}

// 'double' = comportamento storico del reader (rendition.spread('auto'):
// doppia pagina quando la finestra è abbastanza larga, singola altrimenti) —
// resta il default per chi non ha mai toccato l'impostazione.
export function loadPageLayout(): PageLayout {
  // Singola di default. La doppia ha senso su uno schermo largo, ma la
  // finestra del reader ora nasce stretta e verticale (vedi
  // READER_WINDOW_FEATURES): li' la doppia darebbe due colonne strette.
  // Chi preferisce la doppia la sceglie, e la scelta resta.
  return leggiLocale(PAGE_LAYOUT_KEY) === 'double' ? 'double' : 'single'
}

export function savePageLayout(value: PageLayout) {
  scriviLocale(PAGE_LAYOUT_KEY, value)
}

// epub.js: 'none' = sempre una pagina, 'auto' = doppia pagina quando c'è
// spazio (il comportamento storico "double" di questo reader).
export function spreadForPageLayout(layout: PageLayout): string {
  return layout === 'single' ? 'none' : 'auto'
}

export function loadFontScale(): number {
  const raw = Number(leggiLocale(FONT_SCALE_KEY))
  return raw >= FONT_SCALE_MIN && raw <= FONT_SCALE_MAX ? raw : FONT_SCALE_DEFAULT
}

export function saveFontScale(value: number) {
  scriviLocale(FONT_SCALE_KEY, String(value))
}


// ─────────────────────────────────────────────────────────────────────────
// Le preferenze di lettura vere e proprie (tema, carattere, interlinea...)
//
// In una chiave sola come JSON, non una per voce come le due qui sopra. Quelle
// sono nate una alla volta e restano dove sono — rinominarle vorrebbe dire
// buttare via le scelte gia' fatte da chi legge. Queste nascono insieme e
// cresceranno: una chiave per ciascuna significherebbe una migrazione a ogni
// voce nuova.
//
// Si legge con diffidenza: quello che c'e' in localStorage puo' venire da una
// versione precedente, da un'altra scheda, o da un dito su un cursore di
// sviluppo. Ogni campo viene validato e, se non convince, si torna al
// predefinito — mai si lascia passare un valore che poi finirebbe dentro un
// foglio di stile.
// ─────────────────────────────────────────────────────────────────────────
const PREFERENZE_KEY = 'kolibre_reader_prefs'

export const INTERLINEA_MIN = 1.1
export const INTERLINEA_MAX = 2.4
export const MARGINI_MIN = 0
export const MARGINI_MAX = 18

const TEMI: Tema[] = ['sistema', 'chiaro', 'grigio', 'sepia', 'scuro']
const OVERRIDE: OverrideColori[] = ['mai', 'scuro', 'sempre']
const CARATTERI: Carattere[] = ['libro', 'serif', 'palatino', 'times', 'sans', 'leggibile']

function unoDi<T extends string>(ammessi: T[], valore: unknown, predefinito: T): T {
  return ammessi.includes(valore as T) ? (valore as T) : predefinito
}

function numeroFra(valore: unknown, min: number, max: number, predefinito: number): number {
  const n = Number(valore)
  return Number.isFinite(n) && n >= min && n <= max ? n : predefinito
}

export function loadPreferenzeLettura(): PreferenzeLettura {
  const grezzo = leggiLocale(PREFERENZE_KEY)
  if (!grezzo) return { ...PREFERENZE_PREDEFINITE }
  let d: Record<string, unknown>
  try {
    d = JSON.parse(grezzo) as Record<string, unknown>
  } catch {
    return { ...PREFERENZE_PREDEFINITE }
  }
  return {
    tema: unoDi(TEMI, d.tema, PREFERENZE_PREDEFINITE.tema),
    overrideColori: unoDi(OVERRIDE, d.overrideColori, PREFERENZE_PREDEFINITE.overrideColori),
    carattere: unoDi(CARATTERI, d.carattere, PREFERENZE_PREDEFINITE.carattere),
    // `null` e' un valore valido e vuol dire «come l'ha voluta l'editore»:
    // va distinto da «assente», che vuol dire «mai scelto».
    interlinea: d.interlinea == null ? null : numeroFra(d.interlinea, INTERLINEA_MIN, INTERLINEA_MAX, 1.5),
    margini: numeroFra(d.margini, MARGINI_MIN, MARGINI_MAX, PREFERENZE_PREDEFINITE.margini),
    giustificato: typeof d.giustificato === 'boolean' ? d.giustificato : null,
    sillabazione: typeof d.sillabazione === 'boolean' ? d.sillabazione : PREFERENZE_PREDEFINITE.sillabazione,
  }
}

export function savePreferenzeLettura(p: PreferenzeLettura) {
  scriviLocale(PREFERENZE_KEY, JSON.stringify(p))
}
