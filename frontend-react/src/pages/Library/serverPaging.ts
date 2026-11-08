// Quali colonne il server sa ordinare, e come tradurci i criteri della
// tabella.
//
// Non sono tutte, ma ora ci sono tutte quelle che POSSONO esserci.
// Avanzamento di lettura e stato del dispositivo vivono in app.db, non nel
// metadata.db di Calibre: ordinare per quelle richiederebbe di unire due
// database diversi, e in modalita' impaginata il server non puo' farlo.
// Meglio dirlo che ordinare per finta la sola pagina visibile — sembrerebbe
// ordinato e non lo sarebbe.
//
// Dimensione e numero di serie invece stavano in metadata.db da sempre:
// erano escluse e basta, e in modalita' impaginata la tabella semplicemente
// non si lasciava ordinare su quelle due colonne.
import type { SortCriterion } from './sort'

export const SERVER_SORTABLE = new Set([
  'title',
  'author',
  'series',
  'date_added',
  'pubdate',
  'last_modified',
  'rating',
  'size',
  'series_index',
])

/** Il primo criterio che il server sa applicare, o l'ordine di default. */
export function serverSortKey(criteri: SortCriterion[]): { sort: string; order: 'asc' | 'desc' } {
  const utile = criteri.find((c) => SERVER_SORTABLE.has(c.key))
  if (!utile) return { sort: 'date_added', order: 'desc' }
  return { sort: utile.key, order: utile.order === 'asc' ? 'asc' : 'desc' }
}

/** Vero se l'utente ha chiesto un ordinamento che in questa modalita' non si puo' fare. */
export function sortNonSupportato(criteri: SortCriterion[]): string | null {
  const primo = criteri[0]
  if (!primo || SERVER_SORTABLE.has(primo.key)) return null
  return primo.key
}
