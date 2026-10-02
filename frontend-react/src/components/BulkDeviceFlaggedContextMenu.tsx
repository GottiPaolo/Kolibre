import type { ReactNode } from 'react'
import { Link2, Trash2 } from 'lucide-react'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import { useLingua } from '@/lib/i18n'

interface BulkDeviceFlaggedContextMenuProps {
  count: number
  busy: boolean
  onPairAutomatically: () => void
  onBulkDelete: () => void
  children: ReactNode
}

// Mirror di BulkDeviceBookContextMenu.tsx per una multiselezione di righe in
// "Libri non accoppiati" — le due azioni bulk prima sopra la tabella
// (Accoppia automaticamente i selezionati / Elimina selezionati), qui
// spostate a voci di menu contestuale.
export function BulkDeviceFlaggedContextMenu({
  count,
  busy,
  onPairAutomatically,
  onBulkDelete,
  children,
}: BulkDeviceFlaggedContextMenuProps) {
  const { t } = useLingua()
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuLabel>{t('devices.bulk.selectedCount', { count, n: count })}</ContextMenuLabel>
        <ContextMenuSeparator />
        <ContextMenuItem disabled={busy} onSelect={onPairAutomatically}>
          <Link2 /> {t('devices.contextMenu.pairAutomatically')}
        </ContextMenuItem>
        <ContextMenuItem disabled={busy} variant="destructive" onSelect={onBulkDelete}>
          <Trash2 /> {t('devices.contextMenu.deleteFromDevice')}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  )
}
