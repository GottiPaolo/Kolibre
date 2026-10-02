import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Save, Settings, Smartphone, Star } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useDevices, useDeviceFlaggedBooks } from '@/lib/deviceQueries'
import {
  cancelDeviceRestore,
  confirmDeviceRestore,
  deviceErrorDetail,
  downloadDeviceBackups,
  pairDeviceBookRow,
  queueFlaggedBookAction,
  setDefaultDevice,
} from '@/lib/deviceActions'
import { deletePolicyLabel, pickPreferredDeviceFormat, relativeTimeFrom } from '@/lib/deviceFormat'
import { formatBytes } from '@/lib/format'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import type { Device, DeviceBookRow, DeviceFlaggedBook } from '@/types/device'
import type { Book } from '@/types/library'
import { DeviceBooksTable } from './DeviceBooksTable'
import { DeviceHistoryTable } from './DeviceHistoryTable'
import { DeviceFlaggedTable } from './DeviceFlaggedTable'
import { DeviceEditDialog } from './DeviceEditDialog'
import { BookPickerDialog } from './BookPickerDialog'
import { toast } from '@/lib/toast'
import { useLingua } from '@/lib/i18n'

type PickerState =
  | null
  | { kind: 'overwrite-flagged'; flagged: DeviceFlaggedBook }
  | { kind: 'pair-flagged'; flagged: DeviceFlaggedBook }
  | { kind: 'pair-device-book'; row: DeviceBookRow }

// Pagina di dettaglio dispositivo — porting di activePage === 'device-detail'
// nel Vue esistente (frontend/src/App.vue, righe 1323-1547): header con
// stato/badge, tab Libri/Cronologia/Da rivedere, footer con backup e azioni.
// Il dispositivo non ha un GET singolo lato backend (verificato: solo /me,
// device-token) — come nel Vue esistente, si trova nell'elenco già caricato
// da useDevices() (selectedDevice = devices.find(...)).
export function DeviceDetailPage() {
  const { t } = useLingua()
  const { id } = useParams()
  const deviceId = Number(id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: devices = [], isLoading } = useDevices()
  const device = devices.find((d) => d.id === deviceId) ?? null

  const [tab, setTab] = useState('books')
  const [showEdit, setShowEdit] = useState(false)
  const [picker, setPicker] = useState<PickerState>(null)

  // Solo per il conteggio nel titolo della tab "Libri non accoppiati" — la tabella
  // stessa (DeviceFlaggedTable) fa la propria fetch con lo stesso queryKey,
  // condividendo la cache di React Query, non duplicando la richiesta.
  const { data: flaggedBooks = [] } = useDeviceFlaggedBooks(device?.id, true)

  useSetPageHeader(device?.name ?? t('devices.detailFallbackTitle'))

  if (isLoading) return <p className="text-muted-foreground">{t('common.loading')}</p>
  if (!device) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-muted-foreground">{t('devices.detail.notFound')}</p>
        <Button variant="outline" size="sm" onClick={() => navigate('/dispositivi')} className="self-start">
          <ArrowLeft className="size-3.5" /> {t('devices.detail.backButton')}
        </Button>
      </div>
    )
  }

  function invalidateDevices() {
    queryClient.invalidateQueries({ queryKey: ['devices'] })
  }

  async function handleSetDefault() {
    try {
      await setDefaultDevice(device!.id)
    } catch (e) {
      toast.error(deviceErrorDetail(e, t('devices.detail.setDefaultError')))
    } finally {
      invalidateDevices()
    }
  }

  async function handleConfirmRestore(requestId: number) {
    if (!window.confirm(t('devices.detail.confirmRestoreConfirm'))) return
    try {
      await confirmDeviceRestore(device!.id, requestId)
    } catch (e) {
      toast.error(deviceErrorDetail(e, t('devices.detail.confirmRestoreError')))
    } finally {
      invalidateDevices()
    }
  }

  async function handleCancelRestore() {
    if (!window.confirm(t('devices.detail.cancelRestoreConfirm'))) return
    try {
      await cancelDeviceRestore(device!.id)
    } catch (e) {
      toast.error(deviceErrorDetail(e, t('devices.detail.cancelRestoreError')))
    } finally {
      invalidateDevices()
    }
  }

  function openPairManually(_dev: Device, row: DeviceBookRow) {
    setPicker({ kind: 'pair-device-book', row })
  }

  function openFlaggedPicker(mode: 'overwrite' | 'pair', flagged: DeviceFlaggedBook) {
    setPicker(mode === 'overwrite' ? { kind: 'overwrite-flagged', flagged } : { kind: 'pair-flagged', flagged })
  }

  // Instrada la scelta del BookPickerDialog verso l'azione backend giusta in
  // base a COME è stato aperto — stesso smistamento di confirmOverwritePicker
  // nel Vue esistente (tre modalità sullo stesso dialog: 'overwrite'/'pair'
  // per una riga "Da rivedere", 'pair-device-book' per una riga già
  // accoppiata nella tabella principale).
  async function handlePickerSelect(book: Book, libraryFolder: string) {
    if (!picker) return
    const current = picker
    setPicker(null)
    try {
      if (current.kind === 'overwrite-flagged') {
        await queueFlaggedBookAction(device!.id, current.flagged.id, {
          action: 'overwrite',
          library: libraryFolder,
          calibre_book_id: book.id,
        })
        queryClient.invalidateQueries({ queryKey: ['device-flagged-books', device!.id] })
      } else if (current.kind === 'pair-flagged') {
        const format = pickPreferredDeviceFormat(book.formats)
        await queueFlaggedBookAction(device!.id, current.flagged.id, {
          action: 'pair',
          library: libraryFolder,
          calibre_book_id: book.id,
          format,
        })
        queryClient.invalidateQueries({ queryKey: ['device-flagged-books', device!.id] })
      } else if (current.kind === 'pair-device-book') {
        const format = pickPreferredDeviceFormat(book.formats) || current.row.format
        const result = await pairDeviceBookRow(device!.id, current.row.id, {
          library: libraryFolder,
          calibre_book_id: book.id,
          format,
        })
        const migrated = result.migrated_highlights || 0
        if (migrated > 0) toast.success(t('devices.detail.pairedNotesMigrated', { count: migrated, n: migrated }))
        invalidateDevices()
      }
    } catch (e) {
      toast.error(deviceErrorDetail(e, t('devices.error.pairOnServer')))
    }
  }

  const pickerTitle =
    picker?.kind === 'overwrite-flagged'
      ? t('devices.detail.overwritePickerTitle')
      : t('devices.detail.pairPickerTitle')

  return (
    <div className="flex flex-col gap-4">
      <Button variant="ghost" size="sm" onClick={() => navigate('/dispositivi')} className="self-start">
        <ArrowLeft className="size-3.5" /> {t('devices.detail.backButton')}
      </Button>

      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2.5">
          <Smartphone className={device.is_default ? 'size-5 text-[var(--positive)]' : 'size-5 text-primary'} />
          <h1 className="font-serif text-[20px] font-semibold">{device.name}</h1>
          {device.plugin_version && (
            <Badge variant="outline" title={t('devices.pluginVersionTitle')}>
              v{device.plugin_version}
            </Badge>
          )}
          {device.last_seen_at && (
            <span className="text-[11px] text-muted-foreground" title={t('devices.lastSeenTitle', { time: device.last_seen_at })}>
              {t('devices.seenPrefix', { time: relativeTimeFrom(device.last_seen_at, t) })}
            </span>
          )}
          {device.is_default && (
            <span className="inline-flex items-center gap-1 text-[10px] font-bold text-[var(--positive)]">
              <Star className="size-3 fill-current" /> {t('devices.badge.default')}
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-5 text-[13px] text-muted-foreground">
          <span>{t('devices.detail.syncLine', { value: device.last_sync_at || t('devices.never') })}</span>
          <span>{t('devices.detail.backupLine', { value: device.last_backup_at || t('devices.never') })}</span>
          <span>{t('devices.bookCount', { count: device.books.length, n: device.books.length })}</span>
        </div>
      </div>

      <div className="flex flex-col gap-1.5 border-b border-border pb-4 text-[12px] text-muted-foreground">
        {/* Lo spazio arriva dal plugin (v0.6.15+), misurato sul volume che
            ospita i libri e non su quello di sistema: la domanda vera è "ci
            sta un altro libro?". Un plugin più vecchio non lo manda, e il
            messaggio torna a essere "non riportato" — che per tutta la vita
            precedente del campo era l'unica cosa che si vedeva. */}
        <div>
          <strong className="text-foreground">{t('devices.detail.storageLabel')}</strong>{' '}
          {device.storage_total ? (
            <>
              <b className="tabular-nums text-foreground">{formatBytes(device.storage_available ?? 0)}</b>{' '}
              {t('devices.detail.storageFreeSuffix', { total: formatBytes(device.storage_total) })}
              <span className="ml-2 inline-flex h-1.5 w-24 overflow-hidden rounded-full bg-muted align-middle">
                <span
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${Math.min(100, Math.round(((device.storage_used ?? 0) / device.storage_total) * 100))}%` }}
                />
              </span>
            </>
          ) : (
            t('devices.detail.storageUnknown')
          )}
        </div>
        <div>
          <strong className="text-foreground">{t('devices.detail.deletePolicyLabel')}</strong> {deletePolicyLabel(device.delete_policy, t)}
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="books">{t('devices.detail.tabBooks', { n: device.books.length })}</TabsTrigger>
          <TabsTrigger value="history">{t('devices.detail.tabHistory')}</TabsTrigger>
          <TabsTrigger value="flagged">
            {t('devices.detail.tabFlagged')}{flaggedBooks.length > 0 && ` (${flaggedBooks.length})`}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="books">
          <DeviceBooksTable device={device} onPairManually={openPairManually} />
        </TabsContent>
        <TabsContent value="history">
          <DeviceHistoryTable deviceId={device.id} />
        </TabsContent>
        <TabsContent value="flagged">
          <DeviceFlaggedTable device={device} onOpenPicker={openFlaggedPicker} />
        </TabsContent>
      </Tabs>

      {device.pending_restore_request && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[12px]">
          {device.pending_restore_request.status === 'pending_admin' ? (
            <>
              <span>
                {t('devices.detail.restoreRequestFromPrefix')}{' '}
                <strong>{device.pending_restore_request.source_device_name ?? t('devices.detail.unknownDevice')}</strong>
                {device.pending_restore_request.requested_at &&
                  ` ${t('devices.detail.requestedOnSuffix', { date: device.pending_restore_request.requested_at })}`}
                .
              </span>
              <Button size="sm" onClick={() => void handleConfirmRestore(device.pending_restore_request!.id)}>
                {t('devices.detail.confirmButton')}
              </Button>
              <Button variant="outline" size="sm" onClick={() => void handleCancelRestore()}>
                {t('common.cancel')}
              </Button>
            </>
          ) : (
            <>
              <span>
                {t('devices.detail.restoreConfirmedFromPrefix')}{' '}
                <strong>{device.pending_restore_request.source_device_name ?? t('devices.detail.unknownDevice')}</strong>{' '}
                {t('devices.detail.restoreConfirmedWaitingSuffix')}
              </span>
              <Button variant="outline" size="sm" onClick={() => void handleCancelRestore()}>
                {t('common.cancel')}
              </Button>
            </>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4 text-[12px] text-muted-foreground">
        <span>
          <strong className="text-foreground">{t('devices.detail.backupFooterLabel')}</strong>{' '}
          {device.last_backup_at
            ? t('devices.detail.backupFooterInfo', {
                date: device.last_backup_at,
                count: device.backup_file_count,
                n: device.backup_file_count,
              })
            : t('devices.detail.noBackupFooter')}
        </span>
        {device.last_backup_at && (
          <Button variant="outline" size="sm" onClick={() => void downloadDeviceBackups(device.id)}>
            <Save className="size-3.5" /> {t('devices.detail.downloadBackupButton')}
          </Button>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => setShowEdit(true)}>
          <Settings className="size-3.5" /> {t('devices.detail.editButton')}
        </Button>
        {!device.is_default && (
          <Button variant="outline" size="sm" onClick={handleSetDefault}>
            <Star className="size-3.5" /> {t('devices.detail.setDefaultButton')}
          </Button>
        )}
      </div>

      {showEdit && (
        <DeviceEditDialog
          device={device}
          onClose={() => setShowEdit(false)}
          onDeleted={() => {
            setShowEdit(false)
            navigate('/dispositivi')
          }}
        />
      )}

      {picker && (
        <BookPickerDialog title={pickerTitle} onClose={() => setPicker(null)} onSelect={handlePickerSelect} />
      )}
    </div>
  )
}
