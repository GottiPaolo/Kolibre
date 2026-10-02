import type { ReactNode } from 'react'
import { Pencil, Send, Smartphone, Trash2 } from 'lucide-react'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import type { Book } from '@/types/library'
import type { Device } from '@/types/device'
import { useBookActions } from '@/lib/bookActionsContext'
import { queueBookForDevice } from '@/lib/deviceActions'
import { deviceBookColumnState, pickPreferredDeviceFormat } from '@/lib/deviceFormat'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from '@/lib/toast'
import { useLingua } from '@/lib/i18n'

interface BulkBookContextMenuProps {
  books: Book[]
  children: ReactNode
}

// Menu contestuale per una selezione multipla di libri (Cmd/Shift-click
// nella tabella Libreria — vedi LibraryTable/LibraryPage). Porting ridotto
// di BookContextMenu.tsx: solo i comandi che hanno senso applicati a N libri
// insieme (modifica metadati comune, invia/
// rimuovi dispositivo, elimina). Niente sottomenu "Copia nella biblioteca"/
// "Libri simili"/ecc., intrinsecamente single-book — per quelli l'utente
// può sempre deselezionare tutto tranne un libro.
export function BulkBookContextMenu({ books, children }: BulkBookContextMenuProps) {
  const { t } = useLingua()
  const actions = useBookActions()
  const queryClient = useQueryClient()
  const folder = actions.resolveFolder(books[0])

  // Stessa disciplina di lettura-cache-senza-sottoscrizione di
  // BookContextMenu: instanziato una volta per riga selezionata, un
  // useDevices() qui moltiplicherebbe le sottoscrizioni.
  const devices = queryClient.getQueryData<Device[]>(['devices']) ?? []

  function statusFor(device: Device, book: Book) {
    if (!folder) return 'off'
    const row = device.books.find((b) => b.library === folder && b.calibre_book_id === book.id)
    return row ? deviceBookColumnState(row.status) : 'off'
  }
  // Un dispositivo compare come bersaglio "Invia" se almeno uno dei libri
  // selezionati non ce l'ha ancora sopra (e viceversa per "Rimuovi") — non
  // nasconde il dispositivo solo perché uno dei tanti libri scelti è già a
  // posto, altrimenti l'azione bulk sparirebbe per selezioni miste.
  const sendTargets = devices.filter((d) => books.some((b) => statusFor(d, b) !== 'on'))
  const removeTargets = devices.filter((d) => books.some((b) => statusFor(d, b) !== 'off'))

  async function handleBulkSendToDevice(device: Device) {
    if (!folder) return
    const results = await Promise.allSettled(
      books.map((book) => {
        const format = pickPreferredDeviceFormat(book.formats)
        if (!format) return Promise.reject(new Error('nessun formato compatibile'))
        return queueBookForDevice(device.id, { calibre_book_id: book.id, library: folder, format, action: 'queued_download' })
      })
    )
    const failed = results.filter((r) => r.status === 'rejected').length
    if (failed > 0) toast.error(t('library.contextMenu.bulkSendFailed', { n: failed, total: books.length, name: device.name }))
    queryClient.invalidateQueries({ queryKey: ['devices'] })
  }

  async function handleBulkRemoveFromDevice(device: Device) {
    if (!folder) return
    const results = await Promise.allSettled(
      books.map((book) => {
        const format = pickPreferredDeviceFormat(book.formats)
        if (!format) return Promise.reject(new Error('nessun formato compatibile'))
        return queueBookForDevice(device.id, { calibre_book_id: book.id, library: folder, format, action: 'queued_delete' })
      })
    )
    const failed = results.filter((r) => r.status === 'rejected').length
    if (failed > 0) toast.error(t('library.contextMenu.bulkRemoveFailed', { n: failed, total: books.length, name: device.name }))
    queryClient.invalidateQueries({ queryKey: ['devices'] })
  }

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuLabel>{t('library.contextMenu.selectedCount', { n: books.length })}</ContextMenuLabel>
        <ContextMenuSeparator />

        <ContextMenuItem onSelect={() => actions.bulkEditMetadata(books)}>
          <Pencil /> {t('library.contextMenu.editMetadataEllipsis')}
        </ContextMenuItem>

        {sendTargets.length > 0 && (
          <ContextMenuSub>
            <ContextMenuSubTrigger>
              <Send /> {t('library.contextMenu.sendToDevice')}
            </ContextMenuSubTrigger>
            <ContextMenuSubContent>
              {sendTargets.map((d) => (
                <ContextMenuItem key={d.id} onSelect={() => handleBulkSendToDevice(d)}>
                  <Smartphone /> {d.name}
                </ContextMenuItem>
              ))}
            </ContextMenuSubContent>
          </ContextMenuSub>
        )}

        {removeTargets.length > 0 && (
          <ContextMenuSub>
            <ContextMenuSubTrigger>
              <Smartphone /> {t('library.contextMenu.removeFromDevice')}
            </ContextMenuSubTrigger>
            <ContextMenuSubContent>
              {removeTargets.map((d) => (
                <ContextMenuItem key={d.id} variant="destructive" onSelect={() => handleBulkRemoveFromDevice(d)}>
                  <Trash2 /> {d.name}
                </ContextMenuItem>
              ))}
            </ContextMenuSubContent>
          </ContextMenuSub>
        )}

        <ContextMenuSeparator />
        <ContextMenuItem variant="destructive" onSelect={() => actions.confirmBulkDeleteBooks(books)}>
          <Trash2 /> {t('library.bulkDelete.title', { count: books.length, n: books.length })}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  )
}
