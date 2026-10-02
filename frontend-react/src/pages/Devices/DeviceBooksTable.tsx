import { useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { SortableTableHead } from '@/components/ui/sortable-table-head'
import { DeviceBookContextMenu } from '@/components/DeviceBookContextMenu'
import { BulkDeviceBookContextMenu } from '@/components/BulkDeviceBookContextMenu'
import { DeviceStatusPill } from '@/components/DeviceStatusPill'
import { useLibraries } from '@/lib/queries'
import { deviceBookLibraryLabel, deviceBookStatusInfo, formatDateTime } from '@/lib/deviceFormat'
import { useRowSelection } from '@/lib/useRowSelection'
import { sortByAccessor } from '@/lib/tableSort'
import { withBackendUrl } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useLingua } from '@/lib/i18n'
import type { Device, DeviceBookRow } from '@/types/device'

type SortKey = 'title' | 'library' | 'status' | 'created_at' | 'progress' | 'highlights'

const SORT_ACCESSORS: Record<SortKey, (row: DeviceBookRow) => string | number> = {
  title: (r) => r.book_title || '',
  library: (r) => r.library,
  status: (r) => r.status,
  created_at: (r) => r.created_at || '',
  progress: (r) => r.progress_percent || 0,
  highlights: (r) => r.highlights_count || 0,
}

interface DeviceBooksTableProps {
  device: Device
  onPairManually: (device: Device, row: DeviceBookRow) => void
}

// Tab "Libri sul dispositivo" — riavvicinata alla tabella Libreria, perché
// chi la apre si aspetta la stessa tabella della libreria: niente checkbox
// laterale, selezione per click riga con Cmd/Shift (stesso schema di
// LibraryPage.selectBook, ma con un solo Set — questa tabella non ha editing
// inline né un pannello Quickview da pilotare, quindi non serve distinguere
// una riga "a fuoco" dalla selezione multipla), copertina e avanzamento come
// colonne vere. Azioni massive spostate dai bottoni sopra la tabella al menu
// contestuale (BulkDeviceBookContextMenu), coerente con LibraryTable.
export function DeviceBooksTable({ device, onPairManually }: DeviceBooksTableProps) {
  const { t } = useLingua()
  const navigate = useNavigate()
  const { data: libraries = [] } = useLibraries()
  const [sortKey, setSortKey] = useState<SortKey>('created_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

  // La scheda del libro in biblioteca. row.library e' gia' lo slug della
  // cartella, non il nome mostrato (vedi DeviceBook.library nel backend).
  function apriScheda(row: DeviceBookRow) {
    navigate(`/libri/${row.calibre_book_id}`, { state: { libraryFolder: row.library } })
  }

  function handleSortClick(key: SortKey) {
    if (key === sortKey) {
      setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortOrder('asc')
    }
  }

  const sortedBooks = useMemo(
    () => sortByAccessor(device.books, SORT_ACCESSORS, sortKey, sortOrder),
    [device.books, sortKey, sortOrder]
  )

  const { selected, toggle, selectOnly, clear } = useRowSelection(sortedBooks.map((b) => b.id))
  const [focusedId, setFocusedId] = useState<number | null>(null)
  const rowRefs = useRef<Record<number, HTMLTableRowElement | null>>({})

  function handleRowClick(row: DeviceBookRow, e: React.MouseEvent) {
    setFocusedId(row.id)
    if (e.shiftKey || e.metaKey || e.ctrlKey) {
      toggle(row.id, e)
    } else {
      selectOnly(row.id)
    }
  }

  // Navigazione a frecce come in LibraryTable: anche questa tabella deve
  // essere navigabile dai tasti e permettere la selezione multipla come
  // quella normale — nessuna virtualizzazione qui (tabella corta), quindi
  // scrollIntoView diretto sulla riga invece del virtualizer di Libreria.
  function handleTableKeyDown(e: React.KeyboardEvent) {
    if (sortedBooks.length === 0) return
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    e.preventDefault()
    const currentIndex = sortedBooks.findIndex((b) => b.id === focusedId)
    const nextIndex = e.altKey
      ? e.key === 'ArrowUp'
        ? 0
        : sortedBooks.length - 1
      : currentIndex === -1
        ? 0
        : Math.min(sortedBooks.length - 1, Math.max(0, currentIndex + (e.key === 'ArrowDown' ? 1 : -1)))
    const nextRow = sortedBooks[nextIndex]
    setFocusedId(nextRow.id)
    if (e.shiftKey) {
      toggle(nextRow.id, { shiftKey: true })
    } else {
      selectOnly(nextRow.id)
    }
    rowRefs.current[nextRow.id]?.scrollIntoView({ block: 'nearest' })
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] text-muted-foreground">{t('devices.books.hint')}</p>

      <div
        tabIndex={0}
        onKeyDown={handleTableKeyDown}
        className="max-h-[420px] overflow-y-auto rounded-md border border-border focus:outline-none"
      >
        <Table>
          <TableHeader className="sticky top-0 bg-card">
            <TableRow>
              <TableHead className="w-10" />
              <SortableTableHead label={t('devices.books.col.title')} sortKey="title" active={sortKey === 'title'} order={sortOrder} onClick={handleSortClick} />
              <SortableTableHead label={t('devices.books.col.library')} sortKey="library" active={sortKey === 'library'} order={sortOrder} onClick={handleSortClick} />
              <SortableTableHead label={t('authors.field.status')} sortKey="status" active={sortKey === 'status'} order={sortOrder} onClick={handleSortClick} />
              <SortableTableHead
                label={t('devices.books.col.addedAt')}
                sortKey="created_at"
                active={sortKey === 'created_at'}
                order={sortOrder}
                onClick={handleSortClick}
              />
              <SortableTableHead label={t('library.field.progress')} sortKey="progress" active={sortKey === 'progress'} order={sortOrder} onClick={handleSortClick} />
              <SortableTableHead label={t('devices.books.col.highlights')} sortKey="highlights" active={sortKey === 'highlights'} order={sortOrder} onClick={handleSortClick} />
            </TableRow>
          </TableHeader>
          <TableBody>
            {device.books.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  {t('devices.books.empty')}
                </TableCell>
              </TableRow>
            )}
            {sortedBooks.map((row) => {
              const status = deviceBookStatusInfo(row.status, t)
              const isSelected = selected.has(row.id)
              const isMultiSelected = isSelected && selected.size > 1

              const rowEl = (
                <TableRow
                  ref={(el: HTMLTableRowElement | null) => {
                    rowRefs.current[row.id] = el
                  }}
                  className={cn('cursor-pointer', isSelected && 'bg-primary/10 hover:bg-primary/10')}
                  onClick={(e) => handleRowClick(row, e)}
                  // Doppio clic = la scheda del libro, come ci si aspetta da
                  // una riga che un libro ce l'ha. Sui libri non riconosciuti
                  // non c'e' scheda da aprire e il doppio clic non fa niente.
                  onDoubleClick={() => {
                    if (row.book_title) apriScheda(row)
                  }}
                  onContextMenu={() => {
                    if (!isSelected) selectOnly(row.id)
                  }}
                >
                  <TableCell className="px-1">
                    {row.cover_url ? (
                      <img src={withBackendUrl(row.cover_url)} alt="" loading="lazy" className="h-9 w-7 rounded-sm object-cover" />
                    ) : (
                      <div className="h-9 w-7 rounded-sm bg-muted" />
                    )}
                  </TableCell>
                  <TableCell
                    className="whitespace-normal"
                    title={!row.book_title ? t('devices.books.unpairedTitle') : undefined}
                  >
                    <div className="font-serif font-medium">
                      {row.book_title || t('devices.books.unknownTitle')}
                      {row.format && (
                        <span className="ml-1.5 rounded border border-border bg-muted px-1 py-0.5 text-[10px] font-semibold text-muted-foreground">
                          {row.format}
                        </span>
                      )}
                      {row.hash_verified === false && (
                        <span
                          className="ml-1.5 text-[11px] text-[var(--warning)]"
                          title={t('devices.books.unverifiedTitle')}
                        >
                          ⚠ {t('devices.books.unverifiedLabel')}
                        </span>
                      )}
                    </div>
                    <div className="text-[12px] text-muted-foreground">{row.book_author || '—'}</div>
                  </TableCell>
                  <TableCell className="text-[12px] text-muted-foreground">
                    {deviceBookLibraryLabel(libraries, row.library)}
                  </TableCell>
                  <TableCell>
                    <DeviceStatusPill
                      label={status.label}
                      tone={status.tone}
                      title={row.status === 'send_failed' && row.last_error ? row.last_error : undefined}
                    />
                    {row.device_pages != null && (
                      <span className="ml-1.5 text-[11px] text-muted-foreground" title={t('devices.books.pagesReportedTitle')}>
                        · {t('devices.books.pagesCount', { count: row.device_pages, n: row.device_pages })}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-[12px] text-muted-foreground">
                    {row.created_at ? formatDateTime(row.created_at) : '—'}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2 text-[11px]">
                      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary"
                          style={{ width: `${row.progress_percent || 0}%` }}
                        />
                      </div>
                      <span>{row.progress_percent || 0}%</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-[12px] text-muted-foreground">
                    {t('devices.books.highlightsCount', { count: row.highlights_count || 0, n: row.highlights_count || 0 })}
                  </TableCell>
                </TableRow>
              )

              if (isMultiSelected) {
                return (
                  <BulkDeviceBookContextMenu
                    key={row.id}
                    device={device}
                    rows={sortedBooks.filter((b) => selected.has(b.id))}
                    onDone={clear}
                  >
                    {rowEl}
                  </BulkDeviceBookContextMenu>
                )
              }
              return (
                <DeviceBookContextMenu key={row.id} device={device} row={row} onPairManually={onPairManually}>
                  {rowEl}
                </DeviceBookContextMenu>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
