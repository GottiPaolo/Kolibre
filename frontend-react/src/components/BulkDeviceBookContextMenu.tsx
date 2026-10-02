import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Trash2 } from 'lucide-react'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import type { Device, DeviceBookRow } from '@/types/device'
import { queueBookForDevice, deviceErrorDetail } from '@/lib/deviceActions'
import { toast } from '@/lib/toast'
import { useLingua } from '@/lib/i18n'

interface BulkDeviceBookContextMenuProps {
  device: Device
  rows: DeviceBookRow[]
  onDone: () => void
  children: ReactNode
}

// Mirror di BulkBookContextMenu.tsx (libri di libreria) per una
// multiselezione di righe nella tabella "Libri sul dispositivo" — le due
// azioni bulk che prima erano bottoni sopra la tabella (DeviceBooksTable),
// qui spostate a voci di menu contestuale per coerenza con Libreria.
export function BulkDeviceBookContextMenu({ device, rows, onDone, children }: BulkDeviceBookContextMenuProps) {
  const { t } = useLingua()
  const queryClient = useQueryClient()

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['devices'] })
  }

  async function resendFailed() {
    const failed = rows.filter((r) => r.status === 'send_failed')
    if (!failed.length) {
      toast.info(t('devices.bulkBooks.noneFailed'))
      return
    }
    await Promise.all(
      failed.map((row) =>
        queueBookForDevice(device.id, {
          calibre_book_id: row.calibre_book_id,
          library: row.library,
          format: row.format,
          action: 'queued_download',
        }).catch((e) => toast.error(deviceErrorDetail(e, t('devices.error.queueing'))))
      )
    )
    onDone()
    invalidate()
  }

  async function removeAll() {
    await Promise.all(
      rows.map((row) =>
        queueBookForDevice(device.id, {
          calibre_book_id: row.calibre_book_id,
          library: row.library,
          format: row.format,
          action: 'queued_delete',
        }).catch((e) => toast.error(deviceErrorDetail(e, t('devices.error.queueing'))))
      )
    )
    onDone()
    invalidate()
  }

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuLabel>{t('devices.bulk.selectedCount', { count: rows.length, n: rows.length })}</ContextMenuLabel>
        <ContextMenuSeparator />
        <ContextMenuItem onSelect={() => void resendFailed()}>
          <RefreshCw /> {t('devices.bulkBooks.retryFailed')}
        </ContextMenuItem>
        <ContextMenuItem variant="destructive" onSelect={() => void removeAll()}>
          <Trash2 /> {t('devices.contextMenu.removeFromDevice')}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  )
}
