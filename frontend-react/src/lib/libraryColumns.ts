import { leggiLocale, scriviLocale } from './memoriaLocale'
// Porting delle definizioni/persistenza colonne da frontend/src/App.vue
// (FIXED_COLUMN_LABELS, DEFAULT_VISIBLE_COLS, COLUMN_LAYOUT_STORAGE_KEY,
// righe ~4343-4361). Le colonne "stato dispositivo" del Vue esistente sono
// rimandate alla Fase 5 (Dispositivi) di questa migrazione — non c'è ancora
// alcun dato dispositivi caricato in questa app.
export const FIXED_COLUMNS = [
  'cover',
  'title',
  'author',
  'series',
  'series_index',
  'tags',
  'formats',
  'size',
  'date_added',
  'rating',
  'identifiers',
  'progress',
] as const

export type FixedColumnId = (typeof FIXED_COLUMNS)[number]

// Funzione e non un oggetto costante: deve ricalcolarsi al cambio lingua, non
// restare congelata a quella in vigore al primo import del modulo — vedi
// l'uso in LibraryPage (dentro un useMemo con `t` fra le deps).
export function fixedColumnLabels(t: (chiave: string) => string): Record<FixedColumnId, string> {
  return {
    cover: t('library.field.cover'),
    title: t('library.field.title'),
    author: t('library.field.author'),
    series: t('library.field.series'),
    series_index: t('library.field.seriesIndex'),
    tags: t('library.field.tags'),
    formats: t('library.field.formats'),
    size: t('library.field.size'),
    date_added: t('library.field.dateAdded'),
    rating: t('library.field.rating'),
    // 815 libri su 1.216 hanno un ISBN, 910 hanno almeno un identificativo, e
    // fino a oggi si vedevano solo aprendo la scheda del libro: la tabella non
    // aveva una colonna per mostrarli. Non e' fra quelle visibili di
    // preimpostazione — e' informazione da catalogo, che si accende quando
    // serve — ma ora esiste e si puo' ordinare.
    identifiers: t('library.field.identifiers'),
    progress: t('library.field.progress'),
  }
}

// "Avanzamento" (progresso di lettura, combinato tra dispositivi — vedi
// LibraryTable) è visibile di default, come richiesto esplicitamente, e
// nascondibile come le altre colonne dal menu colonne della tabella.
export const DEFAULT_VISIBLE_COLS: string[] = ['title', 'author', 'series', 'formats', 'size', 'date_added', 'progress']

const COLUMN_LAYOUT_STORAGE_KEY = 'kolibre_column_layout_v1'

export function loadColumnLayout(): Record<string, string[]> {
  try {
    const raw = leggiLocale(COLUMN_LAYOUT_STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

export function saveColumnLayout(layout: Record<string, string[]>) {
  scriviLocale(COLUMN_LAYOUT_STORAGE_KEY, JSON.stringify(layout))
}

// Rimuove dall'array visibilità/ordine qualunque id che non sia più una
// colonna reale (es. una custom column cancellata da un altro client) —
// senza questo, quell'id resterebbe bloccato per sempre nel layout salvato.
export function pruneStaleVisibleColumns(cols: string[], validIds: Set<string>): string[] {
  return cols.filter((id) => validIds.has(id))
}

export const DEFAULT_COLUMN_WIDTH = 160
export const MIN_COLUMN_WIDTH = 90
export const COVER_COLUMN_WIDTH = 40
export const DEVICE_COLUMN_WIDTH = 90

// Quanto e' alta una riga della tabella.
//
// Trentasei pixel finche' non si mostra la copertina: quella, in una riga
// cosi' bassa, veniva ritagliata in una striscia — si vedeva la fascia
// centrale del disegno e nient'altro, che di una copertina e' la parte meno
// riconoscibile. Con la colonna accesa la riga cresce quanto serve a
// mostrarla intera, nelle proporzioni di un libro (2:3).
//
// Segue la LARGHEZZA della colonna, che e' ridimensionabile: allargando la
// copertina la riga si alza di conseguenza, invece di ritagliare di nuovo.
// Il tetto serve a non trasformare la tabella in una galleria per sbaglio —
// per quella c'e' gia' la vista a griglia.
const RAPPORTO_COPERTINA = 1.5
const ALTEZZA_RIGA_BASE = 36
const ALTEZZA_RIGA_MASSIMA = 180

export function rowHeight(colIds: string[], widths: Record<string, number>): number {
  if (!colIds.includes('cover')) return ALTEZZA_RIGA_BASE
  const alta = Math.round(columnWidth('cover', widths) * RAPPORTO_COPERTINA) + 8
  return Math.min(ALTEZZA_RIGA_MASSIMA, Math.max(ALTEZZA_RIGA_BASE, alta))
}

export function columnWidth(colId: string, widths: Record<string, number>): number {
  if (colId === 'cover') return widths[colId] ?? COVER_COLUMN_WIDTH
  if (colId.startsWith('device-')) return widths[colId] ?? DEVICE_COLUMN_WIDTH
  return widths[colId] ?? DEFAULT_COLUMN_WIDTH
}

// Toggle tabella/griglia copertine in Libreria — persistito così la scelta
// sopravvive al refresh e al cambio pagina, come column layout/quickview
// width qui sopra. Sotto "md" LibraryCards resta comunque forzata a
// prescindere da questo valore (vedi LibraryPage: la tabella non funziona a
// quella larghezza), quindi il valore salvato conta solo su desktop.
// Tre viste, non piu' due. "list" e' l'elenco compatto con le copertine
// che il telefono usa da sempre: una riga per libro, copertina piccola e i
// metadati essenziali. Su schermo grande era gia' scritto e gia' buono, ma
// non c'era modo di sceglierlo — si otteneva solo restringendo la finestra.
//
// Sotto "md" resta comunque forzato, qualunque cosa dica questa
// impostazione: la tabella li' non ci sta, e la griglia di copertine
// mostra tre libri per schermata.
export type LibraryViewMode = 'table' | 'grid' | 'list'
const VIEW_MODE_KEY = 'kolibre_library_view_mode'

export function loadViewMode(): LibraryViewMode {
  const salvato = leggiLocale(VIEW_MODE_KEY)
  return salvato === 'grid' || salvato === 'list' ? salvato : 'table'
}

export function saveViewMode(mode: LibraryViewMode) {
  scriviLocale(VIEW_MODE_KEY, mode)
}

export const QUICKVIEW_WIDTH_KEY = 'kolibre_quickview_width'
export const QUICKVIEW_MIN_WIDTH = 240
export const QUICKVIEW_MAX_WIDTH = 640
export const QUICKVIEW_DEFAULT_WIDTH = 320

export function loadQuickviewWidth(): number {
  const raw = Number(leggiLocale(QUICKVIEW_WIDTH_KEY))
  return raw && raw >= QUICKVIEW_MIN_WIDTH && raw <= QUICKVIEW_MAX_WIDTH ? raw : QUICKVIEW_DEFAULT_WIDTH
}

export function saveQuickviewWidth(width: number) {
  scriviLocale(QUICKVIEW_WIDTH_KEY, String(width))
}

// ── Quanto è larga davvero una colonna ────────────────────────────────────

/**
 * La colonna dei numeri di riga, a sinistra di tutte le altre.
 *
 * Non è una colonna del sistema colonne: non si sposta, non si ridimensiona
 * e non si spegne. Sta qui, e non dentro il componente, perché **il conto
 * della larghezza deve poterla includere** — vedi `larghezzaDellaRiga` e il
 * difetto raccontato lì.
 */
export const ROW_NUMBER_WIDTH = 34

/**
 * Le larghezze con cui disegnare le colonne, dato lo spazio che c'è.
 *
 * **Il difetto da cui nasce** (06/11/2026, segnalato due volte da Paolo con
 * lo screenshot). Le colonne avevano una larghezza fissa e basta: quando la
 * loro somma superava il riquadro, l'ultima restava tagliata a metà contro
 * il bordo arrotondato; quando invece avanzava spazio, restava una striscia
 * vuota. Il primo tentativo di correzione riscalava sulla larghezza del
 * **riquadro**, ed era ancora sbagliato per un motivo che si vede solo su
 * una macchina con le barre di scorrimento sempre visibili: la zona che
 * scorre è più stretta del riquadro di quanto misura la barra, una quindicina
 * di pixel, e le colonne continuavano a sforare — proprio «un cm».
 *
 * Quindi questa funzione prende lo spazio **dentro** la zona che scorre, e
 * chi la chiama ha il compito di misurarlo con `clientWidth`, che la barra
 * la esclude già.
 *
 * Le regole, in ordine:
 *
 * - si parte dalle larghezze che la persona ha scelto, e si scala tutto
 *   dello stesso fattore: la proporzione fra le colonne non cambia mai;
 * - nessuna colonna scende sotto `MIN_COLUMN_WIDTH`: sotto quella soglia si
 *   torna a scorrere, che è l'unica cosa onesta quando lo spazio non c'è;
 * - se avanza spazio le colonne si allargano a riempirlo, così non resta la
 *   striscia vuota accanto all'ultima.
 */
/**
 * La larghezza di una riga intera: la colonna dei numeri **più** le colonne.
 *
 * **Il difetto da cui nasce** (06/11/2026, terza segnalazione dello stesso
 * sintomo). La riga, l'intestazione e il contenitore delle righe prendevano
 * come larghezza la somma delle sole colonne — ma tutti e tre contengono
 * anche la cella dei numeri di riga, larga 34 pixel. Finché le colonne
 * avevano larghezza fissa e sfondavano il riquadro non si vedeva: si
 * scorreva. Appena le colonne hanno cominciato a stare *esattamente* nello
 * spazio disponibile, la riga è risultata 34 pixel più corta del riquadro —
 * e quei 34 pixel sono la striscia vuota fra l'ultima colonna e il bordo.
 *
 * La morale, per la prossima volta: `spazioPerLeColonne` e la larghezza che
 * si dichiara sulla riga sono **due numeri diversi**, e la differenza è
 * esattamente questa colonna. Prenderne uno per l'altro non dà nessun
 * errore: dà un centimetro di vuoto.
 */
export function larghezzaDellaRiga(
  colonne: string[],
  scelte: Record<string, number>,
  spazioDisponibile: number
): number {
  const larghezze = larghezzeDelleColonne(colonne, scelte, spazioDisponibile)
  return ROW_NUMBER_WIDTH + colonne.reduce((a, id) => a + larghezze[id], 0)
}

export function larghezzeDelleColonne(
  colonne: string[],
  scelte: Record<string, number>,
  spazioDisponibile: number
): Record<string, number> {
  const naturali = colonne.map((id) => columnWidth(id, scelte))
  const somma = naturali.reduce((a, b) => a + b, 0)
  // Finché non si è misurato niente (primo render) si usano le larghezze
  // così come sono: meglio un frame con lo scorrimento che uno a zero.
  if (spazioDisponibile <= 0 || somma <= 0) {
    return Object.fromEntries(colonne.map((id, i) => [id, naturali[i]]))
  }

  const grezza = spazioDisponibile / somma
  // La scala che porterebbe la colonna più stretta sotto il minimo: non si
  // scende oltre.
  const minima = Math.max(...naturali.map((w) => MIN_COLUMN_WIDTH / w))
  const scala = Math.max(grezza, minima)

  const fuori: Record<string, number> = {}
  colonne.forEach((id, i) => {
    fuori[id] = Math.max(MIN_COLUMN_WIDTH, Math.round(naturali[i] * scala))
  })

  // L'arrotondamento può lasciare uno o due pixel di scarto: finiscono
  // sull'ultima colonna, così la somma combacia **esattamente** con lo
  // spazio e il bordo destro non resta mai scoperto di un pelo.
  const sommaFinale = colonne.reduce((a, id) => a + fuori[id], 0)
  const scarto = spazioDisponibile - sommaFinale
  const ultima = colonne[colonne.length - 1]
  if (ultima && scarto !== 0 && fuori[ultima] + scarto >= MIN_COLUMN_WIDTH) {
    fuori[ultima] += scarto
  }
  return fuori
}
