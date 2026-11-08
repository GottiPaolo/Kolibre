import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ExternalLink, Link2, RefreshCw, Trash2, Undo2 } from 'lucide-react'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import type { Device, DeviceBookRow } from '@/types/device'
import {
  acknowledgeDeviceBookRemoval,
  cancelDeviceBookAction,
  deviceErrorDetail,
  queueBookForDevice,
} from '@/lib/deviceActions'
import { toast } from '@/lib/toast'
import { useLingua } from '@/lib/i18n'

interface DeviceBookContextMenuProps {
  device: Device
  row: DeviceBookRow
  onPairManually: (device: Device, row: DeviceBookRow) => void
  children: ReactNode
}

// Menu contestuale di un libro sul dispositivo — porting delle voci del Vue
// esistente (frontend/src/App.vue, righe 2637-2686: openDeviceBookContextMenu
// + azioni condizionali sullo status, cantiere A3). Deliberatamente un
// componente NUOVO e separato da BookContextMenu.tsx (libri di libreria,
// altra fase): qui il "libro" è una riga DeviceBook (calibre_book_id+library+
// format su UN dispositivo), non un Book di libreria, e le azioni disponibili
// dipendono dallo status server-driven della riga invece che dai formati
// disponibili.
export function DeviceBookContextMenu({ device, row, onPairManually, children }: DeviceBookContextMenuProps) {
  const { t } = useLingua()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['devices'] })
  }

  async function run(action: () => Promise<unknown>, fallback: string) {
    try {
      await action()
    } catch (e) {
      toast.error(deviceErrorDetail(e, fallback))
    } finally {
      invalidate()
    }
  }

  // "Mostra nella biblioteca" — stesso pattern di openAuthorBook/
  // showDeviceBookInLibrary nel Vue: passa la libreria di appartenenza via
  // stato di navigazione (row.library è già lo slug/folder_name, non il nome
  // visualizzato — vedi DeviceBook.library nel backend).
  function showInLibrary() {
    navigate(`/libri/${row.calibre_book_id}`, { state: { libraryFolder: row.library } })
  }

  const resend = () =>
    run(
      () =>
        queueBookForDevice(device.id, {
          calibre_book_id: row.calibre_book_id,
          library: row.library,
          format: row.format,
          action: 'queued_download',
        }),
      t('devices.error.queueOnServer')
    )
  const requeueDelete = () =>
    run(
      () =>
        queueBookForDevice(device.id, {
          calibre_book_id: row.calibre_book_id,
          library: row.library,
          format: row.format,
          action: 'queued_delete',
        }),
      t('devices.error.queueOnServer')
    )
  const cancel = () => run(() => cancelDeviceBookAction(device.id, row.id), t('devices.error.deviceOperation'))
  const acknowledge = () =>
    run(() => acknowledgeDeviceBookRemoval(device.id, row.id), t('devices.error.deviceOperation'))

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        {row.book_title && (
          <ContextMenuItem onSelect={showInLibrary}>
            <ExternalLink /> {t('devices.contextMenu.openBookCard')}
          </ContextMenuItem>
        )}
        {/* "Accoppia manualmente" compare solo dove serve davvero (scelta
            del 28/09: solo sui libri non gestiti da Kolibre), e cioe' quando
            la riga non ha trovato il suo libro — oppure quando
            l'ha trovato ma senza la garanzia del checksum, che e' l'unico
            caso in cui un accoppiamento esistente puo' essere sbagliato (un
            hash fuzzy che ha risolto sull'edizione sbagliata). Su un libro
            mandato da Kolibre e verificato non c'e' niente da accoppiare, e
            la voce era solo un modo per rompere una cosa che funziona. */}
        {(!row.book_title || row.hash_verified === false) && (
          <ContextMenuItem onSelect={() => onPairManually(device, row)}>
            <Link2 /> {t('devices.contextMenu.pairManually')}
          </ContextMenuItem>
        )}
        <ContextMenuSeparator />

        {(row.status === 'pending_send' || row.status === 'send_failed') && (
          <>
            {row.status === 'send_failed' && (
              <ContextMenuItem onSelect={resend}>
                <RefreshCw /> {t('devices.contextMenu.retrySend')}
              </ContextMenuItem>
            )}
            <ContextMenuItem onSelect={cancel}>
              <Undo2 /> {t('devices.contextMenu.cancelSend')}
            </ContextMenuItem>
          </>
        )}

        {row.status === 'pending_delete' && (
          <ContextMenuItem onSelect={cancel}>
            <Undo2 /> {t('devices.contextMenu.cancelRemoval')}
          </ContextMenuItem>
        )}

        {row.status === 'delete_declined' && (
          <>
            <ContextMenuItem onSelect={requeueDelete}>
              <RefreshCw /> {t('devices.contextMenu.retryRemoval')}
            </ContextMenuItem>
            <ContextMenuItem onSelect={cancel}>
              <Undo2 /> {t('devices.contextMenu.cancelRemoval')}
            </ContextMenuItem>
          </>
        )}

        {row.status === 'removed_by_device' && (
          <>
            <ContextMenuItem onSelect={acknowledge}>
              <CheckCircle2 /> {t('devices.contextMenu.acknowledge')}
            </ContextMenuItem>
            <ContextMenuItem onSelect={resend}>
              <RefreshCw /> {t('devices.contextMenu.resend')}
            </ContextMenuItem>
          </>
        )}

        {row.status !== 'pending_send' &&
          row.status !== 'send_failed' &&
          row.status !== 'pending_delete' &&
          row.status !== 'delete_declined' &&
          row.status !== 'removed_by_device' && (
            <ContextMenuItem variant="destructive" onSelect={requeueDelete}>
              <Trash2 /> {t('devices.contextMenu.removeFromDevice')}
            </ContextMenuItem>
          )}
      </ContextMenuContent>
    </ContextMenu>
  )
}
