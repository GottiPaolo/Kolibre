import { useMemo, useState } from 'react'
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table'
import { SortableTableHead } from '@/components/ui/sortable-table-head'
import { DeviceStatusPill } from '@/components/DeviceStatusPill'
import { useDeviceSyncHistory } from '@/lib/deviceQueries'
import { formatDateTime, syncOutcomeInfo } from '@/lib/deviceFormat'
import { sortByAccessor } from '@/lib/tableSort'
import { useLingua, type Valori } from '@/lib/i18n'
import type { DeviceSyncHistoryEntry } from '@/types/device'

type Traduci = (chiave: string, valori?: Valori) => string

interface DeviceHistoryTableProps {
  deviceId: number
}

type SortKey = 'started_at' | 'outcome' | 'durata' | 'downloads' | 'deletes' | 'removed_by_device' | 'plugin_version' | 'trigger'

const SORT_ACCESSORS: Record<SortKey, (row: DeviceSyncHistoryEntry) => string | number> = {
  started_at: (h) => h.started_at || '',
  outcome: (h) => h.outcome || '',
  durata: (h) => syncSeconds(h) ?? -1,
  downloads: (h) => h.downloads_ok ?? 0,
  deletes: (h) => h.deletes_done ?? 0,
  removed_by_device: (h) => h.removed_by_device ?? 0,
  plugin_version: (h) => h.plugin_version || '',
  trigger: (h) => h.trigger || '',
}


// Etichette delle fasi riportate dal plugin (device_sync_history.detail_json).
// Due sono conteggi, non secondi: tenerli separati evita di scrivere
// "backup caricati 3s", che sarebbe semplicemente falso.
//
// Le CHIAVI sono i nomi di fase scritti dal plugin nel JSON — dati, non
// visualizzazione: restano fisse. Funzioni e non oggetti costanti perché le
// ETICHETTE devono ricalcolarsi al cambio lingua, stesso motivo di
// fixedColumnLabels in libraryColumns.ts.
function phaseLabels(t: Traduci): Record<string, string> {
  return {
    preparazione: t('devices.history.phase.preparation'),
    download: t('devices.history.phase.download'),
    rimozioni: t('devices.history.phase.removals'),
    pagine: t('devices.history.phase.pages'),
    note_posizioni: t('devices.history.phase.notesPositions'),
    backup: t('devices.history.phase.backup'),
  }
}
function phaseCounts(t: Traduci): Record<string, string> {
  return {
    backup_caricati: t('devices.history.count.backupUploaded'),
    backup_saltati: t('devices.history.count.backupSkipped'),
    // Le righe di lettura mandate al posto dei 659 KB del file intero: è il
    // numero che dice se l'invio incrementale sta funzionando davvero.
    statistiche_righe: t('devices.history.count.newReadingLines'),
  }
}

/** Le fasi riportate dal plugin, se leggibili. */
function fasi(detailJson: string | null | undefined): Record<string, number> {
  if (!detailJson) return {}
  try {
    return (JSON.parse(detailJson) as { phases?: Record<string, number> }).phases ?? {}
  } catch {
    return {}
  }
}

/**
 * Cosa è stato fatto, a parole.
 *
 * I numeri c'erano già — in tre colonne intitolate "↓ ok/falliti",
 * "Rimossi/Rifiutati", "Rimossi dal device" — ma per leggerli bisognava
 * ricordarsi cosa fosse ciascuna, e uno zero non si distingueva da una fase
 * mai eseguita. Dall'uso reale, 29/09/2026: serve vedere COSA è stato fatto,
 * non solo quando.
 *
 * Si elencano solo le cose ACCADUTE: una sincronizzazione in cui non è
 * successo niente lo dice in due parole, invece di allineare sei zeri.
 */
function cosaEStatoFatto(h: DeviceSyncHistoryEntry, t: Traduci): string[] {
  const f = fasi(h.detail_json)
  const parti: string[] = []

  if (h.downloads_ok) parti.push(t('devices.history.booksReceived', { count: h.downloads_ok, n: h.downloads_ok }))
  if (h.downloads_failed) parti.push(t('devices.history.downloadsFailed', { count: h.downloads_failed, n: h.downloads_failed }))
  if (h.deletes_done) parti.push(t('devices.history.booksRemoved', { count: h.deletes_done, n: h.deletes_done }))
  if (h.deletes_declined) parti.push(t('devices.history.deletesDeclined', { n: h.deletes_declined }))
  if (h.removed_by_device) parti.push(t('devices.history.removedByDevice', { n: h.removed_by_device }))
  if (h.pages_reported) parti.push(t('devices.history.pageCounts', { n: h.pages_reported }))
  if (f.statistiche_righe) parti.push(t('devices.history.readingLines', { count: f.statistiche_righe, n: f.statistiche_righe }))
  if (f.backup_caricati) parti.push(t('devices.history.backupFiles', { count: f.backup_caricati, n: f.backup_caricati }))
  // Le note e le posizioni non hanno un contatore proprio: il plugin riporta
  // solo il tempo speso in quella fase. Un tempo sopra lo zero vuol dire che
  // qualcosa è stato mandato — dirlo senza il numero è meglio che tacerlo.
  if (f.note_posizioni) parti.push(t('devices.history.notesPositionsSent'))
  return parti
}

/** Riepilogo leggibile delle fasi, da mostrare come tooltip sulla durata. */
function phaseSummary(detailJson: string | null | undefined, t: Traduci): string | null {
  if (!detailJson) return null
  let phases: Record<string, number>
  try {
    phases = (JSON.parse(detailJson) as { phases?: Record<string, number> }).phases ?? {}
  } catch {
    // detail_json è scritto dal dispositivo: un contenuto illeggibile non
    // deve far cadere la tabella.
    return null
  }
  const labels = phaseLabels(t)
  const counts2 = phaseCounts(t)
  const times = Object.entries(phases)
    .filter(([k, v]) => k in labels && v > 0)
    .map(([k, v]) => `${labels[k]} ${v}s`)
  const counts = Object.entries(phases)
    .filter(([k]) => k in counts2)
    .map(([k, v]) => `${counts2[k]}: ${v}`)
  const all = [...times, ...counts]
  return all.length > 0 ? all.join(' · ') : null
}

/** Durata totale in secondi, dal lato server. */
function syncSeconds(h: DeviceSyncHistoryEntry): number | null {
  if (!h.started_at || !h.finished_at) return null
  const ms = new Date(h.finished_at).getTime() - new Date(h.started_at).getTime()
  return Number.isFinite(ms) && ms >= 0 ? Math.round(ms / 1000) : null
}

// Tab "Cronologia" — porting della tabella deviceSyncHistory nel Vue
// esistente (frontend/src/App.vue, righe 1437-1469). Caricata solo quando la
// tab è attiva (React Query `enabled`), stesso comportamento lazy di
// loadDeviceSyncHistory/openDeviceTab nel Vue.
export function DeviceHistoryTable({ deviceId }: DeviceHistoryTableProps) {
  const { t } = useLingua()
  const { data: history = [], isLoading } = useDeviceSyncHistory(deviceId, true)
  const [sortKey, setSortKey] = useState<SortKey>('started_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

  function handleSortClick(key: SortKey) {
    if (key === sortKey) {
      setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortOrder('asc')
    }
  }

  const sortedHistory = useMemo(
    () => sortByAccessor(history, SORT_ACCESSORS, sortKey, sortOrder),
    [history, sortKey, sortOrder]
  )

  if (isLoading) return <p className="mt-2 text-[12px] text-muted-foreground">{t('common.loading')}</p>
  if (history.length === 0) return <p className="mt-2 text-[12px] text-muted-foreground">{t('devices.history.empty')}</p>

  return (
    <div className="max-h-[420px] overflow-y-auto rounded-md border border-border">
      <Table>
        <TableHeader className="sticky top-0 bg-card">
          <TableRow>
            <SortableTableHead label={t('devices.history.col.when')} sortKey="started_at" active={sortKey === 'started_at'} order={sortOrder} onClick={handleSortClick} />
            <SortableTableHead label={t('devices.history.col.outcome')} sortKey="outcome" active={sortKey === 'outcome'} order={sortOrder} onClick={handleSortClick} />
            <SortableTableHead label={t('devices.history.col.duration')} sortKey="durata" active={sortKey === 'durata'} order={sortOrder} onClick={handleSortClick} />
            <SortableTableHead
              label={t('devices.history.col.whatHappened')}
              sortKey="downloads"
              active={sortKey === 'downloads'}
              order={sortOrder}
              onClick={handleSortClick}
            />
            <SortableTableHead
              label={t('devices.history.col.plugin')}
              sortKey="plugin_version"
              active={sortKey === 'plugin_version'}
              order={sortOrder}
              onClick={handleSortClick}
            />
            <SortableTableHead label={t('devices.history.col.trigger')} sortKey="trigger" active={sortKey === 'trigger'} order={sortOrder} onClick={handleSortClick} />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sortedHistory.map((h) => {
            const outcome = syncOutcomeInfo(h.outcome, t)
            return (
              <TableRow key={h.id}>
                <TableCell className="whitespace-nowrap">{formatDateTime(h.started_at)}</TableCell>
                <TableCell>
                  <DeviceStatusPill label={outcome.label} tone={outcome.tone} />
                </TableCell>
                {/* Il dettaglio per fase arriva dal plugin 0.6.13 in su: per le
                    sincronizzazioni più vecchie c'è solo la durata totale, ed è
                    giusto così — nessuno le aveva mai misurate. */}
                <TableCell className="whitespace-nowrap" title={phaseSummary(h.detail_json, t) ?? undefined}>
                  {(() => {
                    const secs = syncSeconds(h)
                    if (secs === null) return <span className="text-muted-foreground">—</span>
                    const detail = phaseSummary(h.detail_json, t)
                    return (
                      <span className={detail ? 'underline decoration-dotted underline-offset-2' : undefined}>
                        {secs}s
                      </span>
                    )
                  })()}
                </TableCell>
                <TableCell className="text-[12px]">
                  {(() => {
                    const fatto = cosaEStatoFatto(h, t)
                    return fatto.length ? (
                      fatto.join(' · ')
                    ) : (
                      <span className="text-muted-foreground">{t('devices.history.nothingDone')}</span>
                    )
                  })()}
                </TableCell>
                <TableCell>{h.plugin_version || '—'}</TableCell>
                <TableCell>{h.trigger || '—'}</TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
