import { useMemo, useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useLibraries, useBooks } from '@/lib/queries'
import { LibraryTable } from '@/pages/Library/LibraryTable'
import { applySortClick, compareBooks, type SortCriterion } from '@/pages/Library/sort'
import { COVER_COLUMN_WIDTH } from '@/lib/libraryColumns'
import { useLingua } from '@/lib/i18n'
import type { Book } from '@/types/library'

interface BookPickerDialogProps {
  title: string
  onClose: () => void
  onSelect: (book: Book, libraryFolder: string) => void
  // Pre-riempie la ricerca all'apertura — usato per il picker di
  // accoppiamento sessioni orfane (vedi OrphanSessionsPanel.tsx), dove il
  // titolo auto-riportato dal device è già noto e cercarlo a mano ogni
  // volta è puro lavoro ripetitivo. L'utente può comunque cancellarlo se
  // non produce risultati (es. titolo storpiato/incompleto).
  initialQuery?: string
}

// Funzione e non un array costante: le etichette devono ricalcolarsi al
// cambio lingua, stesso motivo di fixedColumnLabels in libraryColumns.ts —
// qui riusiamo verbatim le chiavi library.field.* già esistenti.
function pickerAllColumns(t: (chiave: string) => string): { id: string; label: string }[] {
  return [
    { id: 'cover', label: t('library.field.cover') },
    { id: 'title', label: t('library.field.title') },
    { id: 'author', label: t('library.field.author') },
    { id: 'series', label: t('library.field.series') },
    { id: 'formats', label: t('library.field.formats') },
  ]
}
const PICKER_DEFAULT_VISIBLE = ['cover', 'title', 'author', 'series', 'formats']
const PICKER_DEFAULT_WIDTHS = { cover: COVER_COLUMN_WIDTH, title: 280, author: 200, series: 160, formats: 120 }

// Picker "Sovrascrivi con…" / "Accoppia con…" / "Accoppia manualmente…" —
// prima era una lista testuale spoglia (solo titolo/autore, niente
// copertina, niente ordinamento): qui si riusa DAVVERO la tabella Libreria
// (stesso componente, stessa virtualizzazione, colonna copertina inclusa),
// solo con stato locale non persistito (niente localStorage — è un dialog
// transitorio) e `interactive={false}` per disattivare il menu contestuale
// "Elimina"/azioni distruttive, che qui non ha senso ed è un rischio reale.
export function BookPickerDialog({ title, onClose, onSelect, initialQuery }: BookPickerDialogProps) {
  const { t } = useLingua()
  const { data: libraries = [] } = useLibraries()
  const [libraryId, setLibraryId] = useState<number | null>(null)
  const [query, setQuery] = useState(initialQuery ?? '')
  const [sortCriteria, setSortCriteria] = useState<SortCriterion[]>([{ key: 'title', order: 'asc' }])
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>(PICKER_DEFAULT_WIDTHS)
  const [visibleColumnIds, setVisibleColumnIds] = useState<string[]>(PICKER_DEFAULT_VISIBLE)
  const [selectedBookId, setSelectedBookId] = useState<number | null>(null)

  const activeLibrary = libraries.find((l) => l.id === libraryId) ?? libraries[0]
  const { data: books = [], isLoading } = useBooks(activeLibrary?.folder_name)

  const allColumns = useMemo(() => pickerAllColumns(t), [t])
  const columns = useMemo(
    () => visibleColumnIds.map((id) => allColumns.find((c) => c.id === id)).filter((c): c is { id: string; label: string } => !!c),
    [visibleColumnIds, allColumns]
  )

  const filtered = useMemo(() => {
    const text = query.toLowerCase().trim()
    const base = text ? books.filter((b) => b.title.toLowerCase().includes(text) || (b.author ?? '').toLowerCase().includes(text)) : books
    return [...base].sort((a, b) => compareBooks(a, b, sortCriteria))
  }, [books, query, sortCriteria])

  const selectedBook = filtered.find((b) => b.id === selectedBookId) ?? null

  function toggleColumn(colId: string) {
    setVisibleColumnIds((prev) => (prev.includes(colId) ? prev.filter((id) => id !== colId) : [...prev, colId]))
  }

  function confirm() {
    if (!selectedBook || !activeLibrary) return
    onSelect(selectedBook, activeLibrary.folder_name)
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[85vh] max-w-4xl flex-col">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <div className="flex gap-2">
          <Select
            value={String(activeLibrary?.id ?? '')}
            onValueChange={(v) => {
              setLibraryId(Number(v))
              setSelectedBookId(null)
            }}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {libraries.map((lib) => (
                <SelectItem key={lib.id} value={String(lib.id)}>
                  {lib.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('devices.picker.searchPlaceholder')}
            className="flex-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
          />
        </div>

        <div className="min-h-0 flex-1" style={{ height: '55vh' }}>
          {isLoading ? (
            <p className="p-3 text-[12px] text-muted-foreground">{t('common.loading')}</p>
          ) : (
            <LibraryTable
              books={filtered}
              columns={columns}
              allColumns={allColumns}
              visibleColumnIds={visibleColumnIds}
              columnWidths={columnWidths}
              sortCriteria={sortCriteria}
              onSortClick={(colId, shiftKey) => setSortCriteria((prev) => applySortClick(prev, colId, shiftKey))}
              selectedBookId={selectedBookId}
              onSelectBook={(book) => setSelectedBookId(book.id)}
              customColumns={[]}
              onReorderColumns={setVisibleColumnIds}
              onResizeColumn={(colId, width) => setColumnWidths((prev) => ({ ...prev, [colId]: width }))}
              onToggleColumn={toggleColumn}
              interactive={false}
            />
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button disabled={!selectedBook} onClick={confirm}>
            {selectedBook ? t('devices.picker.confirmWithTitle', { title: selectedBook.title }) : t('devices.picker.selectABook')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
