import { Fragment, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { SortableTableHead } from '@/components/ui/sortable-table-head'
import { DeviceStatusPill } from '@/components/DeviceStatusPill'
import { DeviceFlaggedContextMenu } from '@/components/DeviceFlaggedContextMenu'
import { BulkDeviceFlaggedContextMenu } from '@/components/BulkDeviceFlaggedContextMenu'
import { useDeviceFlaggedBooks } from '@/lib/deviceQueries'
import {
  bulkDeleteFlaggedBooks,
  deleteFlaggedBook,
  deviceErrorDetail,
  queueFlaggedBookAction,
} from '@/lib/deviceActions'
import { flaggedReasonLabel, formatDateTime } from '@/lib/deviceFormat'
import { useRowSelection } from '@/lib/useRowSelection'
import { sortByAccessor } from '@/lib/tableSort'
import { cn } from '@/lib/utils'
import { useLingua } from '@/lib/i18n'
import type { Device, DeviceFlaggedBook } from '@/types/device'
import { toast } from '@/lib/toast'

type SortKey = 'title' | 'reason' | 'candidate' | 'flagged_at'

const SORT_ACCESSORS: Record<SortKey, (row: DeviceFlaggedBook) => string | number> = {
  title: (f) => f.local_title || f.local_path,
  reason: (f) => f.match_status,
  candidate: (f) => f.candidate_title || '',
  flagged_at: (f) => f.flagged_at || '',
}

interface DeviceFlaggedTableProps {
  device: Device
  onOpenPicker: (mode: 'overwrite' | 'pair', flagged: DeviceFlaggedBook) => void
}

// Tab "Libri non accoppiati" (ex "Da rivedere") — libri trovati dallo scan
// "Inizializza libreria" del plugin che non sono stati toccati in automatico:
// nessuna corrispondenza certa, o corrispondenza probabile ma il file locale
// ha già lettura/note (mai tocca il device da solo — vedi il backend,
// report_flagged_book). Redesign: niente checkbox laterale, selezione per
// click riga con Cmd/Shift (stesso schema, un solo Set, di DeviceBooksTable),
// autore del file locale come sottotesto (local_author, popolato solo da un
// plugin KOReader aggiornato — vuoto altrimenti), azioni per riga e bulk
// spostate dai bottoni al menu contestuale.
export function DeviceFlaggedTable({ device, onOpenPicker }: DeviceFlaggedTableProps) {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: flagged = [], isLoading } = useDeviceFlaggedBooks(device.id, true)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [bulkPairing, setBulkPairing] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>('flagged_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

  function handleSortClick(key: SortKey) {
    if (key === sortKey) {
      setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortOrder('asc')
    }
  }

  const sortedFlagged = useMemo(
    () => sortByAccessor(flagged, SORT_ACCESSORS, sortKey, sortOrder),
    [flagged, sortKey, sortOrder]
  )

  const { selected, toggle, selectOnly, clear } = useRowSelection(sortedFlagged.map((f) => f.id))

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['device-flagged-books', device.id] })
  }

  function handleRowClick(f: DeviceFlaggedBook, e: React.MouseEvent) {
    if (f.pending_action) return
    if (e.shiftKey || e.metaKey || e.ctrlKey) {
      toggle(f.id, e)
    } else {
      selectOnly(f.id)
    }
  }

  async function bulkDelete() {
    const ids = Array.from(selected)
    if (!ids.length) return
    try {
      await bulkDeleteFlaggedBooks(device.id, ids)
      clear()
    } catch (e) {
      toast.error(deviceErrorDetail(e, t('devices.flagged.bulkDeleteError')))
    } finally {
      invalidate()
    }
  }

  // Nessun endpoint bulk per 'pair' lato backend — e non potrebbe essercene
  // uno "a un solo libro condiviso" (bulk-action del backend lo dice
  // esplicitamente): ogni riga ha il SUO candidato. Quindi si itera in
  // sequenza sulle righe selezionate che ne hanno già uno, richiamando la
  // stessa azione singola già usata da "Accoppia con questo" — nessuna
  // modifica al backend, stesso pattern già usato per lo scrape bulk autori.
  async function bulkPairWithCandidates() {
    const rows = flagged.filter((f) => selected.has(f.id) && f.candidate_calibre_book_id && f.candidate_library)
    const skipped = selected.size - rows.length
    if (!rows.length) {
      toast.info(t('devices.flagged.noAutoMatchSelected'))
      return
    }
    setBulkPairing(true)
    let done = 0
    let migratedTotal = 0
    for (const f of rows) {
      try {
        const data = await queueFlaggedBookAction(device.id, f.id, {
          action: 'pair',
          library: f.candidate_library!,
          calibre_book_id: f.candidate_calibre_book_id!,
        })
        migratedTotal += data.migrated_highlights || 0
        done++
      } catch {
        // un fallimento non deve fermare il resto della coda
      }
    }
    setBulkPairing(false)
    clear()
    invalidate()
    const skippedMsg = skipped > 0 ? ` ${t('devices.flagged.skippedCount', { count: skipped, n: skipped })}` : ''
    const migratedMsg = migratedTotal > 0 ? ` ${t('devices.flagged.migratedCount', { count: migratedTotal, n: migratedTotal })}` : ''
    toast.success(`${t('devices.flagged.autoPairedCount', { count: done, n: done })}${skippedMsg}${migratedMsg}`)
  }

  // "Accoppia con questo" — usa il candidato già trovato dal fuzzy-match del
  // plugin, senza passare per il picker. Non specifica un formato (come nel
  // Vue esistente, pairWithCandidate/pairFlaggedBook: costruiscono un "libro"
  // fittizio con formats: [] per il candidato, quindi il campo format finisce
  // sempre omesso dalla richiesta) — il backend applica il proprio default
  // 'EPUB' (queue_flagged_book_action). Comportamento ereditato 1:1, non
  // corretto qui: vedi il report finale.
  async function pairWithCandidate(f: DeviceFlaggedBook) {
    if (!f.candidate_library || !f.candidate_calibre_book_id) return
    setBusyId(f.id)
    try {
      const data = await queueFlaggedBookAction(device.id, f.id, {
        action: 'pair',
        library: f.candidate_library,
        calibre_book_id: f.candidate_calibre_book_id,
      })
      const migrated = data.migrated_highlights || 0
      if (migrated > 0) toast.success(t('devices.flagged.linkedNotesImported', { count: migrated, n: migrated }))
    } catch (e) {
      toast.error(deviceErrorDetail(e, t('devices.error.pairOnServer')))
    } finally {
      setBusyId(null)
      invalidate()
    }
  }

  async function overwriteWithCandidate(f: DeviceFlaggedBook) {
    if (!f.candidate_library || !f.candidate_calibre_book_id) return
    if (
      f.match_status === 'flagged_started' &&
      !window.confirm(t('devices.flagged.confirmOverwriteStarted'))
    ) {
      return
    }
    setBusyId(f.id)
    try {
      await queueFlaggedBookAction(device.id, f.id, {
        action: 'overwrite',
        library: f.candidate_library,
        calibre_book_id: f.candidate_calibre_book_id,
      })
    } catch (e) {
      toast.error(deviceErrorDetail(e, t('devices.error.queueActionOnServer')))
    } finally {
      setBusyId(null)
      invalidate()
    }
  }

  async function queueDelete(f: DeviceFlaggedBook) {
    setBusyId(f.id)
    try {
      await queueFlaggedBookAction(device.id, f.id, { action: 'delete' })
    } catch (e) {
      toast.error(deviceErrorDetail(e, t('devices.error.queueActionOnServer')))
    } finally {
      setBusyId(null)
      invalidate()
    }
  }

  async function removeFromList(f: DeviceFlaggedBook) {
    setBusyId(f.id)
    try {
      await deleteFlaggedBook(device.id, f.id)
    } catch {
      toast.error(t('devices.flagged.removeFromListError'))
    } finally {
      setBusyId(null)
      invalidate()
    }
  }

  if (isLoading) return <p className="mt-2 text-[12px] text-muted-foreground">{t('common.loading')}</p>

  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] text-muted-foreground">{t('devices.flagged.hint')}</p>

      {flagged.length === 0 ? (
        <p className="text-[12px] text-muted-foreground">{t('devices.flagged.empty')}</p>
      ) : (
        <div className="max-h-[420px] overflow-y-auto rounded-md border border-border">
          <Table>
            <TableHeader className="sticky top-0 bg-card">
              <TableRow>
                <SortableTableHead label={t('devices.flagged.col.title')} sortKey="title" active={sortKey === 'title'} order={sortOrder} onClick={handleSortClick} />
                <SortableTableHead label={t('devices.flagged.col.reason')} sortKey="reason" active={sortKey === 'reason'} order={sortOrder} onClick={handleSortClick} />
                <SortableTableHead
                  label={t('devices.flagged.col.candidate')}
                  sortKey="candidate"
                  active={sortKey === 'candidate'}
                  order={sortOrder}
                  onClick={handleSortClick}
                />
                <SortableTableHead
                  label={t('devices.flagged.col.flaggedAt')}
                  sortKey="flagged_at"
                  active={sortKey === 'flagged_at'}
                  order={sortOrder}
                  onClick={handleSortClick}
                />
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedFlagged.map((f) => {
                const isSelected = !f.pending_action && selected.has(f.id)
                const isMultiSelected = isSelected && selected.size > 1

                const rowEl = (
                  <TableRow
                    className={cn('cursor-pointer', isSelected && 'bg-primary/10 hover:bg-primary/10')}
                    onClick={(e) => handleRowClick(f, e)}
                    onContextMenu={() => {
                      if (!f.pending_action && !selected.has(f.id)) selectOnly(f.id)
                    }}
                  >
                    <TableCell className="whitespace-normal">
                      <div className="font-serif font-medium">{f.local_title || f.local_path}</div>
                      {f.local_author && <div className="text-[12px] text-muted-foreground">{f.local_author}</div>}
                    </TableCell>
                    <TableCell className="whitespace-normal">
                      <DeviceStatusPill
                        label={f.match_status === 'no_candidate' ? t('devices.flagged.noMatchLabel') : t('devices.flagged.matchFoundLabel')}
                        tone={f.match_status === 'no_candidate' ? 'muted' : 'warning'}
                      />
                      <div className="mt-0.5 text-[11px] text-muted-foreground">{flaggedReasonLabel(f, t)}</div>
                    </TableCell>
                    <TableCell className="whitespace-normal">
                      {f.candidate_title ? (
                        <>
                          {f.candidate_title}
                          {f.candidate_author && <> — {f.candidate_author}</>}
                        </>
                      ) : (
                        '—'
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{formatDateTime(f.flagged_at)}</TableCell>
                    <TableCell className="whitespace-normal">
                      {f.pending_action && (
                        <DeviceStatusPill
                          tone="warning"
                          label={t('devices.pendingSync.label', {
                            action: f.pending_action === 'delete' ? t('devices.pendingSync.actionDelete') : t('devices.pendingSync.actionOverwrite'),
                          })}
                        />
                      )}
                    </TableCell>
                  </TableRow>
                )

                if (f.pending_action) return <Fragment key={f.id}>{rowEl}</Fragment>

                if (isMultiSelected) {
                  return (
                    <BulkDeviceFlaggedContextMenu
                      key={f.id}
                      count={selected.size}
                      busy={bulkPairing}
                      onPairAutomatically={bulkPairWithCandidates}
                      onBulkDelete={bulkDelete}
                    >
                      {rowEl}
                    </BulkDeviceFlaggedContextMenu>
                  )
                }
                return (
                  <DeviceFlaggedContextMenu
                    key={f.id}
                    flagged={f}
                    busy={busyId === f.id}
                    onPairWithCandidate={pairWithCandidate}
                    onOverwriteWithCandidate={overwriteWithCandidate}
                    onOpenPicker={onOpenPicker}
                    onQueueDelete={queueDelete}
                    onRemoveFromList={removeFromList}
                  >
                    {rowEl}
                  </DeviceFlaggedContextMenu>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
