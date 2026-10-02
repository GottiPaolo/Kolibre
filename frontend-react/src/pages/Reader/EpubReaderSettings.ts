import { leggiLocale, scriviLocale } from '@/lib/memoriaLocale'
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

