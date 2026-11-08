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
import { Search } from 'lucide-react'
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

  // Il filtro di ricerca (chiesto da Paolo il 04/11/2026). Lavora sulle righe
  // che sono GIA' in mano al browser — la scheda del dispositivo le riceve
  // tutte insieme — quindi filtrare qui non e' una regola che il server
  // dovrebbe avere: e' guardare meglio dei dati che si hanno gia'. (Se un
  // giorno le righe arrivassero a pagine, questo filtro andrebbe nel server:
  // vedi il principio in «Come si lavora qui» nel backlog.)
  const [ricerca, setRicerca] = useState('')

  // Si cerca in tutto quello che si vede nella riga, non solo nel titolo: il
  // formato («epub»), lo stato («in attesa»), la biblioteca, l'autore, e anche
  // il percorso sul lettore — che e' il modo di ritrovare un file quando il
  // titolo non si sa, cioe' proprio quando serve cercare. Lo stato si cerca
  // nella sua traduzione, perche' e' quella che si legge: chi digita «attesa»
  // non sta pensando a `pending_send`.
  const filteredBooks = useMemo(() => {
    const q = ricerca.trim().toLowerCase()
    if (!q) return device.books
    // Le parole si cercano TUTTE, in qualunque ordine e in qualunque campo:
    // «marx epub» trova gli EPUB di Marx. Una sola stringa intera non lo
    // farebbe, perche' «marx epub» non compare mai di fila in nessun campo.
    const parole = q.split(/\s+/)
    return device.books.filter((row) => {
      const campi = [
        row.book_title, row.book_author, row.format,
        // La biblioteca si cerca col nome MOSTRATO e con lo slug: in riga si
        // legge «Libreria», ma chi conosce il progetto digita «libreria».
        row.library, deviceBookLibraryLabel(libraries, row.library),
        row.device_path, row.requested_by,
        deviceBookStatusInfo(row.status, t).label,
      ].filter(Boolean).join(' ').toLowerCase()
      return parole.every((parola) => campi.includes(parola))
    })
  }, [device.books, ricerca, libraries, t])

  const sortedBooks = useMemo(
    () => sortByAccessor(filteredBooks, SORT_ACCESSORS, sortKey, sortOrder),
    [filteredBooks, sortKey, sortOrder]
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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">{t('devices.books.hint')}</p>
        <div className="flex items-center gap-2">
          {/* Il conto di cosa si sta guardando. Compare solo filtrando,
              perche' «218 di 218» non dice niente a nessuno — e quando il
              filtro non trova nulla e' l'unica cosa che spiega una tabella
              vuota che un attimo prima era piena. */}
          {ricerca.trim() !== '' && (
            <span className="text-[11px] text-muted-foreground tabular-nums">
              {t('devices.books.searchCount', { n: sortedBooks.length, total: device.books.length })}
            </span>
          )}
          {/* Stesso campo di ricerca del Vocabolario, classi comprese: due
              campi che fanno la stessa cosa devono somigliarsi. */}
          <div className="relative w-52">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground/70" />
            <input
              value={ricerca}
              onChange={(e) => setRicerca(e.target.value)}
              placeholder={t('devices.books.searchPlaceholder')}
              aria-label={t('devices.books.searchPlaceholder')}
              className="w-full rounded-md border border-border bg-background py-1 pr-2.5 pl-7 text-[12.5px] outline-none focus:border-primary"
            />
          </div>
        </div>
      </div>

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
            {sortedBooks.length === 0 && device.books.length > 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-6 text-center text-[12px] text-muted-foreground">
                  {t('devices.books.searchEmpty', { q: ricerca.trim() })}
                </TableCell>
              </TableRow>
            )}
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
