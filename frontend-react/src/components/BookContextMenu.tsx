import { Fragment, type ReactNode } from 'react'
import {
  BookOpen,
  BookOpenText,
  Building2,
  Copy,
  Download,
  FolderInput,
  Layers,
  ListTree,
  Pencil,
  RefreshCw,
  Scissors,
  Send,
  Smartphone,
  Tag,
  Trash2,
  User,
  Wand2,
  XCircle,
} from 'lucide-react'
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
import type { Book, Library } from '@/types/library'
import type { Device } from '@/types/device'
import { useBookActions } from '@/lib/bookActionsContext'
import { copyBookToLibrary } from '@/lib/bookActions'
import { queueBookForDevice, deviceErrorDetail } from '@/lib/deviceActions'
import { deviceBookColumnState, pickPreferredDeviceFormat, sendBlockReason, sendSkipReasonLabel } from '@/lib/deviceFormat'
import { splitAuthorNames } from '@/lib/authorNames'
import { errorDetail, recomputeBookPageCount } from '@/lib/librarySettingsActions'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from '@/lib/toast'
import { useLingua } from '@/lib/i18n'

interface BookContextMenuProps {
  book: Book
  children: ReactNode
}

// Menu contestuale libro — porting dell'elenco voci di frontend/src/App.vue
// (righe 2492-2635). Le voci "Invia al dispositivo"/"Rimuovi dal
// dispositivo" sono rimandate alla Fase 5 (Dispositivi): questa app non ha
// ancora dati dispositivi da mostrare.
//
// Questo componente viene istanziato UNA VOLTA PER RIGA della tabella
// Libreria — con una libreria di centinaia/migliaia di libri, un
// useLibraries() qui dentro significherebbe altrettante sottoscrizioni
// indipendenti alla stessa query (era il bug reale dietro la lentezza
// segnalata). Si legge invece la cache già popolata da chi ha davvero
// bisogno di reattività su questo dato (LibraryPage/SeriesPage, che
// chiamano useLibraries()) senza sottoscriversi: l'elenco librerie cambia
// così di rado che non serve un re-render dedicato per riga.
// Le viste che mostrano un libro sono quattro, non una: il catalogo intero,
// la pagina corrente (che è quella usata sopra la soglia di impaginazione),
// il totale e i conteggi del Navigatore. Invalidarne una sola lasciava la
// tabella con i dati vecchi proprio sulle biblioteche grandi. Vedi la stessa
// funzione in lib/bookActionsContext.tsx.
function invalidaViste(queryClient: ReturnType<typeof useQueryClient>, folder: string) {
  for (const chiave of ['books', 'books-page', 'books-pagination', 'valori-campi']) {
    queryClient.invalidateQueries({ queryKey: [chiave, folder] })
  }
}

export function BookContextMenu({ book, children }: BookContextMenuProps) {
  const { t } = useLingua()
  const actions = useBookActions()
  const queryClient = useQueryClient()
  const folder = actions.resolveFolder(book)
  // Una scheda fantasma (soli metadati, nessun file — l'inventario di una
  // libreria fisica, 22/11/2026): Leggi, Scarica e Invia non hanno niente
  // su cui lavorare. Le voci restano visibili ma spente, col motivo nel
  // tooltip — una voce che sparisce non spiega niente (stessa regola del
  // blocco invio qui sotto).
  const soloScheda = !book.formats || book.formats.length === 0
  const libraries = queryClient.getQueryData<Library[]>(['libraries']) ?? []
  // Si confronta la CARTELLA e non il nome mostrato: vedi
  // `resolveBookLibraryFolder`. Col ripiego sul nome per una risposta
  // tenuta in cache, che il campo nuovo non ce l'ha.
  const otherLibraries = libraries.filter((l) =>
    book._library_folder ? l.folder_name !== book._library_folder : l.name !== book._library
  )

  // Stessa disciplina delle librerie sopra: si legge la cache di useDevices()
  // (già popolata da chi ha davvero bisogno di reattività, es. la pagina
  // Dispositivi o la colonna "Su: <dispositivo>" della Libreria) invece di
  // sottoscriversi qui — istanziato una volta per riga, un hook qui
  // moltiplicherebbe le sottoscrizioni per il numero di libri visibili.
  const devices = queryClient.getQueryData<Device[]>(['devices']) ?? []
  const deviceStatusById = new Map(
    devices.map((d) => {
      const row = d.books.find((b) => b.library === folder && b.calibre_book_id === book.id)
      return [d.id, row ? deviceBookColumnState(row.status) : 'off'] as const
    })
  )
  // Perché un invio verso quel dispositivo NON partirebbe (21/11/2026,
  // regola di Paolo): prima la voce spariva solo per lo stato 'on', e un
  // libro in coda o in attesa di rimozione si poteva «rimandare» — la
  // clessidra compariva senza un invio vero dietro. Ora la voce resta
  // visibile ma disabilitata, col motivo nel tooltip: una voce che
  // sparisce non spiega niente. Il blocco vero sta sul server (409).
  const sendBlockById = new Map(
    devices.map((d) => {
      const statuses = d.books
        .filter((b) => b.library === folder && b.calibre_book_id === book.id)
        .map((b) => b.status)
      return [d.id, sendBlockReason(statuses)] as const
    })
  )
  const removeTargets = devices.filter((d) => deviceStatusById.get(d.id) !== 'off')

  async function handleCopy(targetFolder: string, deleteSource: boolean) {
    if (!folder) return
    if (deleteSource && !window.confirm(t('library.contextMenu.confirmCopyAndDelete', { title: book.title }))) return
    try {
      await copyBookToLibrary(folder, book.id, targetFolder, deleteSource)
    } catch (e) {
      // Era l'unica azione del file senza cattura: un 403 (copia verso una
      // biblioteca su cui non si ha la scrittura) diventava una promise
      // rifiutata e basta — nessun messaggio, il menu si chiudeva, e sembrava
      // che fosse andata bene.
      toast.error(errorDetail(e, t('library.contextMenu.copyFailed')))
      return
    }
    invalidaViste(queryClient, targetFolder)
    if (deleteSource) invalidaViste(queryClient, folder)
  }

  async function handleSendToDevice(device: Device) {
    if (!folder) return
    const format = pickPreferredDeviceFormat(book.formats)
    if (!format) return
    try {
      await queueBookForDevice(device.id, { calibre_book_id: book.id, library: folder, format, action: 'queued_download' })
    } catch (e) {
      toast.error(deviceErrorDetail(e, t('library.contextMenu.sendToDeviceFailed')))
    } finally {
      queryClient.invalidateQueries({ queryKey: ['devices'] })
    }
  }

  async function handleRemoveFromDevice(device: Device) {
    if (!folder) return
    const format = pickPreferredDeviceFormat(book.formats)
    if (!format) return
    try {
      await queueBookForDevice(device.id, { calibre_book_id: book.id, library: folder, format, action: 'queued_delete' })
    } catch (e) {
      toast.error(deviceErrorDetail(e, t('library.contextMenu.removeFromDeviceFailed')))
    } finally {
      queryClient.invalidateQueries({ queryKey: ['devices'] })
    }
  }

  async function handleRecomputePages() {
    if (!folder) return
    try {
      const res = await recomputeBookPageCount(book.id, folder)
      toast.success(t('library.contextMenu.recomputePagesSuccess', { title: book.title, pages: res.pages }))
    } catch (e) {
      toast.error(errorDetail(e, t('library.contextMenu.recomputePagesFailed')))
    } finally {
      invalidaViste(queryClient, folder)
    }
  }

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        {/* Il div attorno serve al tooltip: la voce disabilitata ha
            pointer-events-none, e un title su di lei non comparirebbe. */}
        <div title={soloScheda ? t('library.contextMenu.soloSchedaHint') : undefined}>
          <ContextMenuItem disabled={soloScheda} onSelect={() => actions.readBook(book)}>
            <BookOpen /> {t('library.contextMenu.read')}
          </ContextMenuItem>
        </div>

        <ContextMenuSub>
          <ContextMenuSubTrigger>
            <Pencil /> {t('library.detail.editMetadata')}
          </ContextMenuSubTrigger>
          <ContextMenuSubContent>
            <ContextMenuItem onSelect={() => actions.editMetadata(book)}>
              <Pencil /> {t('library.contextMenu.editMetadataIndividually')}
            </ContextMenuItem>
            <ContextMenuItem onSelect={() => actions.downloadMetadataAndCovers(book)}>
              <Download /> {t('library.metadata.downloadMetadataAndCovers')}
            </ContextMenuItem>
          </ContextMenuSubContent>
        </ContextMenuSub>

        <div title={soloScheda ? t('library.contextMenu.soloSchedaHint') : undefined}>
          <ContextMenuItem disabled={soloScheda} onSelect={() => actions.downloadFormat(book)}>
            <Download /> {t('library.formatPicker.download')}
          </ContextMenuItem>
        </div>
        <ContextMenuItem onSelect={() => actions.convert(book)}>
          <RefreshCw /> {t('library.contextMenu.convertFormat')}
        </ContextMenuItem>
        <ContextMenuItem onSelect={() => actions.editToc(book)}>
          <ListTree /> {t('library.contextMenu.editToc')}
        </ContextMenuItem>
        <ContextMenuItem onSelect={() => void handleRecomputePages()}>
          <RefreshCw /> {t('library.contextMenu.recomputePages')}
        </ContextMenuItem>

        <ContextMenuSeparator />

        <ContextMenuItem onSelect={() => actions.openBookDetail(book)}>
          <BookOpenText /> {t('library.contextMenu.bookDetails')}
        </ContextMenuItem>
        <ContextMenuItem onSelect={() => actions.goToAuthor(splitAuthorNames(book.author)[0] ?? book.author)}>
          <User /> {t('library.contextMenu.goToAuthor')}
        </ContextMenuItem>

        <ContextMenuSub>
          <ContextMenuSubTrigger>
            <Wand2 /> {t('library.contextMenu.similarBooks')}
          </ContextMenuSubTrigger>
          <ContextMenuSubContent>
            <ContextMenuItem onSelect={() => actions.similarByAuthor(book)}>
              <User /> {t('library.contextMenu.similarByAuthor')}
            </ContextMenuItem>
            {book.series && (
              <ContextMenuItem onSelect={() => actions.similarBySeries(book)}>
                <Layers /> {t('library.contextMenu.similarBySeries')}
              </ContextMenuItem>
            )}
            {book.publisher && (
              <ContextMenuItem onSelect={() => actions.similarByPublisher(book)}>
                <Building2 /> {t('library.contextMenu.similarByPublisher')}
              </ContextMenuItem>
            )}
            {book.tags.length > 0 && (
              <ContextMenuItem onSelect={() => actions.similarByTags(book)}>
                <Tag /> {t('library.contextMenu.similarByTags')}
              </ContextMenuItem>
            )}
          </ContextMenuSubContent>
        </ContextMenuSub>

        {otherLibraries.length > 0 && (
          <ContextMenuSub>
            <ContextMenuSubTrigger>
              <FolderInput /> {t('library.contextMenu.copyToLibrary')}
            </ContextMenuSubTrigger>
            <ContextMenuSubContent>
              {otherLibraries.map((lib) => (
                <Fragment key={lib.id}>
                  <ContextMenuLabel>{lib.name}</ContextMenuLabel>
                  <ContextMenuItem onSelect={() => handleCopy(lib.folder_name, false)}>
                    <Copy /> {t('library.contextMenu.copyInto', { name: lib.name })}
                  </ContextMenuItem>
                  <ContextMenuItem onSelect={() => handleCopy(lib.folder_name, true)} variant="destructive">
                    <Scissors /> {t('library.contextMenu.copyAndDeleteOrigin')}
                  </ContextMenuItem>
                </Fragment>
              ))}
            </ContextMenuSubContent>
          </ContextMenuSub>
        )}

        {devices.length > 0 && (
          <ContextMenuSub>
            <div title={soloScheda ? t('library.contextMenu.soloSchedaHint') : undefined}>
              <ContextMenuSubTrigger disabled={soloScheda}>
                <Send /> {t('library.contextMenu.sendToDevice')}
              </ContextMenuSubTrigger>
            </div>
            <ContextMenuSubContent>
              {devices.map((d) => {
                const block = sendBlockById.get(d.id) ?? null
                return (
                  // Il div attorno serve al tooltip: la voce disabilitata
                  // ha pointer-events-none, e un title messo su di lei non
                  // comparirebbe mai.
                  <div key={d.id} title={block ? sendSkipReasonLabel(block, t) : undefined}>
                    <ContextMenuItem disabled={block !== null} onSelect={() => handleSendToDevice(d)}>
                      <Smartphone /> {d.name}
                    </ContextMenuItem>
                  </div>
                )
              })}
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
                <ContextMenuItem key={d.id} variant="destructive" onSelect={() => handleRemoveFromDevice(d)}>
                  <Trash2 /> {d.name}
                </ContextMenuItem>
              ))}
            </ContextMenuSubContent>
          </ContextMenuSub>
        )}

        {book.formats.length > 1 && (
          <ContextMenuSub>
            <ContextMenuSubTrigger>
              <XCircle /> {t('library.contextMenu.deleteFormatEllipsis')}
            </ContextMenuSubTrigger>
            <ContextMenuSubContent>
              {book.formats.map((format) => (
                <ContextMenuItem key={format} variant="destructive" onSelect={() => actions.confirmDeleteFormat(book, format)}>
                  <XCircle /> {format}
                </ContextMenuItem>
              ))}
            </ContextMenuSubContent>
          </ContextMenuSub>
        )}

        <ContextMenuSeparator />
        <ContextMenuItem variant="destructive" onSelect={() => actions.confirmDeleteBook(book)}>
          <Trash2 /> {t('library.deleteBook.delete')}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  )
}
