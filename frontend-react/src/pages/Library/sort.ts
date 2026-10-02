import type { Book, CustomColumn } from '@/types/library'
import { formatDate } from '@/lib/format'
import type { DeviceBookColumnState } from '@/lib/deviceFormat'
import { t } from '@/lib/i18n'

export interface SortCriterion {
  key: string
  order: 'asc' | 'desc'
}

const DEVICE_STATUS_ORDER: Record<DeviceBookColumnState, number> = { on: 3, queued: 2, pending_delete: 1, off: 0 }

/** L'ISBN se c'e', altrimenti il primo identificativo in ordine alfabetico. */
function identificativoPrincipale(book: Book): string {
  const ids = book.identifiers ?? {}
  if (ids.isbn) return ids.isbn
  const chiavi = Object.keys(ids).sort()
  return chiavi.length ? `${chiavi[0]}:${ids[chiavi[0]]}` : ''
}

export function getSortValue(
  book: Book,
  colId: string,
  progressByBookId?: Record<number, number>,
  deviceStatusByBookId?: Record<number, Record<number, DeviceBookColumnState>>
): string | number | null {
  switch (colId) {
    case 'title':
      return book.title
    case 'author':
      return book.author
    case 'series':
      return book.series
    case 'series_index':
      return book.series_index
    case 'tags':
      return (book.tags ?? []).join(', ') || null
    case 'formats':
      return (book.formats ?? []).join(', ') || null
    case 'size':
      return book.size
    case 'date_added':
      return book.date_added
    case 'rating':
      return book.rating
    case 'identifiers':
      // Si ordina sull'ISBN quando c'e' — e' quello che si cerca — e sul
      // primo identificativo disponibile altrimenti. I libri che non ne
      // hanno nessuno finiscono in fondo, come ogni altro valore vuoto.
      return identificativoPrincipale(book) || null
    case 'progress':
      // Non è un campo di Book: vive in una mappa separata (vedi
      // LibraryPage.tsx, useReadingProgress) perché calcolata da
      // ReadingPosition, non dai metadati Calibre.
      return progressByBookId?.[book.id] ?? null
    default: {
      if (colId.startsWith('device-')) {
        // Colonna dinamica "Su: <dispositivo>" (vedi LibraryPage.tsx,
        // deviceStatusByBookId) — non è un campo di Book. 'off' equivale ad
        // "assente sul dispositivo": va trattato come vuoto (in fondo alla
        // lista, come ogni altro valore isEmpty), non come un terzo valore
        // ordinabile — altrimenti "off" finirebbe minore di "queued" ma non
        // "vuoto", cambiando dove finiscono i libri mai inviati a nessun
        // dispositivo rispetto a un normale campo assente.
        const deviceId = Number(colId.slice('device-'.length))
        const status = deviceStatusByBookId?.[book.id]?.[deviceId]
        return status && status !== 'off' ? DEVICE_STATUS_ORDER[status] : null
      }
      if (colId.startsWith('#')) {
        const v = book[colId]
        return v === null || v === undefined || v === '' ? null : (v as string | number)
      }
      return null
    }
  }
}

function isEmpty(v: string | number | null): boolean {
  return v === null || v === undefined || v === ''
}

// Porting del comparatore di frontend/src/App.vue (sortedBooks, righe
// 5573-5617): un valore vuoto non è mai "uguale" a un altro — va sempre in
// fondo, indipendentemente da asc/desc (altrimenti il libro selezionato
// "non si riordina", il bug originale). Solo un pareggio vero passa al
// criterio successivo.
export function compareBooks(
  a: Book,
  b: Book,
  criteria: SortCriterion[],
  progressByBookId?: Record<number, number>,
  deviceStatusByBookId?: Record<number, Record<number, DeviceBookColumnState>>
): number {
  for (const { key, order } of criteria) {
    const av = getSortValue(a, key, progressByBookId, deviceStatusByBookId)
    const bv = getSortValue(b, key, progressByBookId, deviceStatusByBookId)
    const aEmpty = isEmpty(av)
    const bEmpty = isEmpty(bv)
    if (aEmpty && bEmpty) continue
    if (aEmpty) return 1
    if (bEmpty) return -1
    let cmp: number
    if (typeof av === 'number' && typeof bv === 'number') cmp = av - bv
    else cmp = String(av).toLowerCase().localeCompare(String(bv).toLowerCase())
    if (cmp !== 0) return order === 'asc' ? cmp : -cmp
  }
  return 0
}

// Click semplice: la colonna diventa il criterio primario; se era già in
// classifica, la sposta in testa invertendone la direzione. Shift+click:
// la inserisce come secondo criterio, senza toccare il primario corrente.
export function applySortClick(prev: SortCriterion[], key: string, shiftKey: boolean): SortCriterion[] {
  const existingIdx = prev.findIndex((c) => c.key === key)
  if (shiftKey) {
    if (existingIdx !== -1) {
      const item = prev[existingIdx]
      const rest = prev.filter((_, i) => i !== existingIdx)
      const [primary, ...others] = rest
      return primary ? [primary, item, ...others] : [item]
    }
    const [primary, ...rest] = prev
    const newItem: SortCriterion = { key, order: 'asc' }
    return primary ? [primary, newItem, ...rest] : [newItem]
  }
  if (existingIdx !== -1) {
    const item = prev[existingIdx]
    const flipped: SortCriterion = { key, order: item.order === 'asc' ? 'desc' : 'asc' }
    return [flipped, ...prev.filter((_, i) => i !== existingIdx)]
  }
  return [{ key, order: 'asc' }, ...prev]
}

export function renderCellValue(book: Book, colId: string, customColumns: CustomColumn[]): string {
  switch (colId) {
    case 'title':
      return book.title
    case 'author':
      return book.author || '—'
    case 'series':
      return book.series ?? '—'
    case 'series_index':
      return book.series_index != null ? String(book.series_index) : '—'
    case 'tags':
      return book.tags?.length ? book.tags.join(', ') : '—'
    case 'formats':
      return book.formats?.length ? book.formats.join(', ') : '—'
    case 'identifiers': {
      const voci = Object.entries(book.identifiers ?? {})
      if (voci.length === 0) return '—'
      // L'ISBN per primo: in una colonna stretta si vede solo il primo
      // valore, e quello che si cerca e' quasi sempre l'ISBN.
      voci.sort(([a], [b]) => (a === 'isbn' ? -1 : b === 'isbn' ? 1 : a.localeCompare(b)))
      return voci.map(([k, v]) => `${k}:${v}`).join(' · ')
    }
    default:
      if (colId.startsWith('#')) {
        const label = colId.slice(1)
        const col = customColumns.find((c) => c.label === label)
        const value = book[colId]
        if (value === null || value === undefined || value === '') return '—'
        if (col?.datatype === 'rating') return '★'.repeat(Number(value))
        if (col?.datatype === 'bool') return value ? t('common.yes') : t('common.no')
        if (col?.datatype === 'datetime') return formatDate(String(value))
        return String(value)
      }
      return '—'
  }
}
