import type { ReactNode } from 'react'
import { FolderInput, Link2, RefreshCw, Trash2, XCircle } from 'lucide-react'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import type { DeviceFlaggedBook } from '@/types/device'
import { useLingua } from '@/lib/i18n'

interface DeviceFlaggedContextMenuProps {
  flagged: DeviceFlaggedBook
  busy: boolean
  onPairWithCandidate: (f: DeviceFlaggedBook) => void
  onOverwriteWithCandidate: (f: DeviceFlaggedBook) => void
  onOpenPicker: (mode: 'overwrite' | 'pair', f: DeviceFlaggedBook) => void
  onQueueDelete: (f: DeviceFlaggedBook) => void
  onRemoveFromList: (f: DeviceFlaggedBook) => void
  children: ReactNode
}

// Menu contestuale per una riga "Libri non accoppiati" — mirror di
// DeviceBookContextMenu.tsx, sostituisce i bottoni inline per riga della
// vecchia tabella "Da rivedere". Una riga con pending_action non ha azioni
// disponibili (in attesa del prossimo sync): il menu mostra solo lo stato.
export function DeviceFlaggedContextMenu({
  flagged,
  busy,
  onPairWithCandidate,
  onOverwriteWithCandidate,
  onOpenPicker,
  onQueueDelete,
  onRemoveFromList,
  children,
}: DeviceFlaggedContextMenuProps) {
  const { t } = useLingua()
  const hasCandidate = !!flagged.candidate_calibre_book_id

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        {flagged.pending_action ? (
          <ContextMenuLabel>
            {t('devices.pendingSync.label', {
              action: flagged.pending_action === 'delete' ? t('devices.pendingSync.actionDelete') : t('devices.pendingSync.actionOverwrite'),
            })}
          </ContextMenuLabel>
        ) : (
          <>
            {hasCandidate && (
              <ContextMenuItem disabled={busy} onSelect={() => onPairWithCandidate(flagged)}>
                <Link2 /> {t('devices.contextMenu.pairWithThis')}
              </ContextMenuItem>
            )}
            {hasCandidate && (
              <ContextMenuItem disabled={busy} onSelect={() => onOverwriteWithCandidate(flagged)}>
                <RefreshCw /> {t('devices.contextMenu.overwriteWithThis')}
              </ContextMenuItem>
            )}
            <ContextMenuItem onSelect={() => onOpenPicker('overwrite', flagged)}>
              <FolderInput /> {t('devices.contextMenu.overwriteWith')}
            </ContextMenuItem>
            <ContextMenuItem onSelect={() => onOpenPicker('pair', flagged)}>
              <Link2 /> {t('devices.contextMenu.pairWith')}
            </ContextMenuItem>
            <ContextMenuSeparator />
            <ContextMenuItem disabled={busy} variant="destructive" onSelect={() => onQueueDelete(flagged)}>
              <Trash2 /> {t('devices.contextMenu.deleteFromDevice')}
            </ContextMenuItem>
            <ContextMenuItem disabled={busy} onSelect={() => onRemoveFromList(flagged)}>
              <XCircle /> {t('devices.contextMenu.removeFromListItem')}
            </ContextMenuItem>
          </>
        )}
      </ContextMenuContent>
    </ContextMenu>
  )
}
