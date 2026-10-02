import { createContext, useContext, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import type { Book, MetadataCandidate } from '@/types/library'
import { useLibraries } from './queries'
import { buildFieldClause, buildFieldDefs } from './libraryQuery'
import { splitAuthorNames } from './authorNames'
import { downloadFormatUrl, resolveBookLibraryFolder, updateBookMetadata } from './bookActions'
import { openBookInReader } from './readerActions'
import { MetadataEditorDialog } from '@/pages/BookDetail/MetadataEditorDialog'
import { MetadataSearchResultsDialog } from '@/pages/BookDetail/MetadataSearchResultsDialog'
import { MetadataComparisonDialog } from '@/pages/BookDetail/MetadataComparisonDialog'
import { FormatPickerDialog } from '@/pages/BookDetail/FormatPickerDialog'
import { ConvertDialog } from '@/pages/BookDetail/ConvertDialog'
import { DeleteBookDialog } from '@/pages/BookDetail/DeleteBookDialog'
import { DeleteFormatDialog } from '@/pages/BookDetail/DeleteFormatDialog'
import { TocEditorDialog } from '@/pages/BookDetail/TocEditor/TocEditorDialog'
import { BulkDeleteBooksDialog } from '@/pages/BookDetail/BulkDeleteBooksDialog'
import { BulkMetadataEditorDialog, type BulkMetadataTarget } from '@/pages/BookDetail/BulkMetadataEditorDialog'
import { toast } from '@/lib/toast'
import { t } from '@/lib/i18n'

type DialogState =
  | null
  | { type: 'metadata'; book: Book; folder: string }
  | { type: 'metadata-search'; book: Book; folder: string; candidates: MetadataCandidate[] }
  | { type: 'metadata-compare'; book: Book; folder: string; candidate: MetadataCandidate; allCandidates: MetadataCandidate[] }
  | { type: 'format-picker'; book: Book; folder: string }
  | { type: 'convert'; book: Book; folder: string }
  | { type: 'delete-book'; book: Book; folder: string }
  | { type: 'delete-format'; book: Book; folder: string; format: string }
  | { type: 'toc'; book: Book; folder: string }
  // Varianti multi-libro (selezione Cmd/Shift-click nella tabella Libreria —
  // vedi BulkBookContextMenu): richiedono ancora un `folder`, ma risolto dal
  // primo libro della selezione, dato che tutti i libri selezionati
  // appartengono sempre alla stessa libreria visualizzata.
  | { type: 'bulk-delete'; books: Book[]; folder: string }
  // La modifica metadati in blocco è l'unica variante che NON porta con sé
  // un `folder` unico: si apre anche dalla pagina di un autore, che è una
  // vista globale su tutte le biblioteche del server, quindi ogni libro si
  // porta dietro la propria (vedi BulkMetadataTarget).
  | { type: 'bulk-metadata'; targets: BulkMetadataTarget[]; alSalvataggio?: AlSalvataggioBulk }

interface BookActionsApi {
  resolveFolder(book: Book): string | undefined
  editMetadata(book: Book): void
  downloadMetadataAndCovers(book: Book): void
  showMetadataSearchResults(book: Book, folder: string, candidates: MetadataCandidate[]): void
  showMetadataComparison(book: Book, folder: string, candidate: MetadataCandidate, allCandidates: MetadataCandidate[]): void
  downloadFormat(book: Book): void
  convert(book: Book): void
  confirmDeleteBook(book: Book): void
  confirmDeleteFormat(book: Book, format: string): void
  editToc(book: Book): void
  // Varianti bulk (menu contestuale multiselezione, vedi BulkBookContextMenu).
  confirmBulkDeleteBooks(books: Book[]): void
  bulkEditMetadata(books: Book[]): void
  // Stessa finestra di bulkEditMetadata ma per chi ha in mano solo id e
  // biblioteca invece di `Book` interi — la griglia della pagina Autore,
  // che riceve dal server una forma ridotta dei libri. `alSalvataggio`
  // riceve i campi davvero applicati, per chi deve reagire al contenuto
  // della modifica e non solo al fatto che sia avvenuta.
  bulkEditMetadataTargets(targets: BulkMetadataTarget[], alSalvataggio?: AlSalvataggioBulk): void
  // Scrittura di uno o pochi campi senza passare dal dialog Modifica
  // Metadati (es. editing inline in tabella) — riusa lo stesso endpoint
  // PUT parziale di updateBookMetadata, con l'invalidazione della query
  // libri già inclusa, così il chiamante non deve occuparsene.
  updateBookField(book: Book, fields: Record<string, unknown>): Promise<void>
  readBook(book: Book): void
  openBookDetail(book: Book): void
  similarByAuthor(book: Book): void
  similarBySeries(book: Book): void
  similarByPublisher(book: Book): void
  similarByTags(book: Book): void
  // Un SINGOLO valore di un campo: cliccando un tag nella scheda di un
  // libro si vogliono i libri con QUEL tag, non con tutti i tag di questo.
  // Il filtro finisce nella barra di ricerca della libreria, scritto nella
  // stessa lingua che si userebbe a mano.
  filterByFieldValue(queryField: string, value: string, library?: string | null): void
  goToAuthor(name: string): void
  closeDialog(): void
}

export type AlSalvataggioBulk = (campiScritti: Record<string, unknown>) => void

const BookActionsContext = createContext<BookActionsApi | null>(null)

export function useBookActions(): BookActionsApi {
  const ctx = useContext(BookActionsContext)
  if (!ctx) throw new Error('useBookActions deve essere usato dentro <BookActionsProvider>')
  return ctx
}

export function BookActionsProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: libraries = [] } = useLibraries()
  const [dialog, setDialog] = useState<DialogState>(null)

  const resolveFolder = (book: Book) => resolveBookLibraryFolder(book, libraries)

  function runSimilar(kind: 'author' | 'series' | 'publisher' | 'tags', book: Book) {
    // Solo .queryField serve qui (costruzione di una query), non le
    // etichette: t non ha bisogno di essere reattivo al cambio lingua.
    const defs = buildFieldDefs([], t)
    let clause = ''
    if (kind === 'author') {
      const def = defs.find((d) => d.queryField === 'authors')!
      clause = buildFieldClause(def, splitAuthorNames(book.author), [])
    } else if (kind === 'series' && book.series) {
      clause = buildFieldClause(defs.find((d) => d.queryField === 'series')!, [book.series], [])
    } else if (kind === 'publisher' && book.publisher) {
      clause = buildFieldClause(defs.find((d) => d.queryField === 'publisher')!, [book.publisher], [])
    } else if (kind === 'tags' && book.tags.length) {
      clause = buildFieldClause(defs.find((d) => d.queryField === 'tags')!, book.tags, [])
    }
    if (clause) navigate(`/?q=${encodeURIComponent(clause)}`)
  }

  // Niente useMemo: l'oggetto è tutte funzioni leggere che chiudono su
  // `libraries`/`navigate` correnti — ricrearlo ogni render è più semplice
  // e più corretto che inseguire le dipendenze esatte di uno useMemo.
  const api: BookActionsApi = {
    resolveFolder,
      editMetadata(book) {
        const folder = resolveFolder(book)
        if (folder) setDialog({ type: 'metadata', book, folder })
      },
      downloadMetadataAndCovers(book) {
        const folder = resolveFolder(book)
        if (folder) setDialog({ type: 'metadata-search', book, folder, candidates: [] })
      },
      showMetadataSearchResults(book, folder, candidates) {
        setDialog({ type: 'metadata-search', book, folder, candidates })
      },
      showMetadataComparison(book, folder, candidate, allCandidates) {
        setDialog({ type: 'metadata-compare', book, folder, candidate, allCandidates })
      },
      downloadFormat(book) {
        const folder = resolveFolder(book)
        if (!folder) return
        // Libro monoformato: nessun motivo di mostrare un picker con una
        // sola scelta — si scarica direttamente (stesso comportamento di
        // openFormatPicker nel Vue esistente).
        if (book.formats.length <= 1) {
          window.open(downloadFormatUrl(folder, book.id, book.formats[0]), '_blank')
          return
        }
        setDialog({ type: 'format-picker', book, folder })
      },
      convert(book) {
        const folder = resolveFolder(book)
        if (folder) setDialog({ type: 'convert', book, folder })
      },
      confirmDeleteBook(book) {
        const folder = resolveFolder(book)
        if (folder) setDialog({ type: 'delete-book', book, folder })
      },
      confirmDeleteFormat(book, format) {
        const folder = resolveFolder(book)
        if (!folder) return
        if (book.formats.length <= 1) return
        setDialog({ type: 'delete-format', book, folder, format })
      },
      editToc(book) {
        const folder = resolveFolder(book)
        if (folder) setDialog({ type: 'toc', book, folder })
      },
      confirmBulkDeleteBooks(books) {
        if (books.length === 0) return
        const folder = resolveFolder(books[0])
        if (folder) setDialog({ type: 'bulk-delete', books, folder })
      },
      bulkEditMetadata(books) {
        const targets = books
          .map((b) => ({ id: b.id, library: resolveFolder(b) }))
          .filter((t): t is BulkMetadataTarget => !!t.library)
        api.bulkEditMetadataTargets(targets)
      },
      bulkEditMetadataTargets(targets, alSalvataggio) {
        if (targets.length === 0) return
        setDialog({ type: 'bulk-metadata', targets, alSalvataggio })
      },
      async updateBookField(book, fields) {
        const folder = resolveFolder(book)
        if (!folder) return
        await updateBookMetadata(folder, book.id, fields)
        invalidateBooks(folder)
      },
      readBook(book) {
        const folder = resolveFolder(book)
        if (!folder) return
        openBookInReader(book, folder).then((opened) => {
          if (!opened) toast.error(t('library.reader.unsupportedFormat'))
        })
      },
      openBookDetail(book) {
        const folder = resolveFolder(book)
        navigate(`/libri/${book.id}`, { state: { libraryFolder: folder } })
      },
      similarByAuthor: (book) => runSimilar('author', book),
      similarBySeries: (book) => runSimilar('series', book),
      similarByPublisher: (book) => runSimilar('publisher', book),
      similarByTags: (book) => runSimilar('tags', book),
      filterByFieldValue(queryField, value, library) {
        if (!value) return
        const def = buildFieldDefs([], t).find((d) => d.queryField === queryField)
        if (!def) return
        const clause = buildFieldClause(def, [value], [])
        if (!clause) return
        // Anche la biblioteca, non solo il filtro. Senza, cliccando un tag
        // nelle statistiche di UNA biblioteca si finiva nella Libreria
        // aperta sull'ULTIMA usata, filtrata su un tag che li' non esiste:
        // "0 / 50 libri" invece dei centoquaranta che si erano appena
        // visti nel grafico. Stesso meccanismo che usa gia' il ritorno
        // dalla scheda di un libro (vedi LibraryLocationState).
        navigate(`/?q=${encodeURIComponent(clause)}`, library ? { state: { libraryFolder: library } } : undefined)
      },
      goToAuthor(name) {
        navigate(`/autori/${encodeURIComponent(name)}`)
      },
      closeDialog() {
        setDialog(null)
      },
  }

  /**
   * Dopo una scrittura su un libro: rinfresca TUTTE le viste che lo mostrano.
   *
   * Prima invalidava solo `['books', folder]`, che è la query del catalogo
   * intero — quella che sopra la soglia di impaginazione la pagina Libreria
   * non usa nemmeno (`useBooks` viene disabilitata e i dati arrivano da
   * `['books-page', …]`). Risultato: su una biblioteca grande si modificava
   * il titolo di un libro, il server scriveva, il dialogo si chiudeva e la
   * riga continuava a mostrare il titolo vecchio fino a un ricaricamento
   * della pagina. Lo stesso eliminando un libro: restava in tabella.
   *
   * `['books-page', …]` ha dentro offset, limite, ordinamento e ricerca,
   * quindi non si può ricostruire la chiave esatta: si invalida per prefisso.
   * Insieme vanno il totale (`books-pagination`) e i conteggi del Navigatore
   * (`valori-campi`), che dopo un'eliminazione restavano quelli di prima.
   */
  function invalidateBooks(folder: string) {
    queryClient.invalidateQueries({ queryKey: ['books', folder] })
    queryClient.invalidateQueries({ queryKey: ['books-page', folder] })
    queryClient.invalidateQueries({ queryKey: ['books-pagination', folder] })
    queryClient.invalidateQueries({ queryKey: ['valori-campi', folder] })
  }

  return (
    <BookActionsContext.Provider value={api}>
      {children}

      {dialog?.type === 'metadata' && (
        <MetadataEditorDialog
          book={dialog.book}
          libraryFolder={dialog.folder}
          onClose={() => setDialog(null)}
          onSaved={() => {
            invalidateBooks(dialog.folder)
            setDialog(null)
          }}
          onRequestOnlineSearch={() => api.downloadMetadataAndCovers(dialog.book)}
        />
      )}

      {dialog?.type === 'metadata-search' && (
        <MetadataSearchResultsDialog
          book={dialog.book}
          libraryFolder={dialog.folder}
          initialCandidates={dialog.candidates}
          onClose={() => setDialog(null)}
          onSelectCandidate={(candidate, allCandidates) => api.showMetadataComparison(dialog.book, dialog.folder, candidate, allCandidates)}
        />
      )}

      {dialog?.type === 'metadata-compare' && (
        <MetadataComparisonDialog
          book={dialog.book}
          libraryFolder={dialog.folder}
          candidate={dialog.candidate}
          allCandidates={dialog.allCandidates}
          onClose={() => setDialog(null)}
          onApplied={() => {
            invalidateBooks(dialog.folder)
            setDialog(null)
          }}
        />
      )}

      {dialog?.type === 'format-picker' && (
        <FormatPickerDialog book={dialog.book} libraryFolder={dialog.folder} onClose={() => setDialog(null)} />
      )}

      {dialog?.type === 'convert' && (
        <ConvertDialog
          book={dialog.book}
          libraryFolder={dialog.folder}
          onClose={() => setDialog(null)}
          onConverted={() => invalidateBooks(dialog.folder)}
        />
      )}

      {dialog?.type === 'delete-book' && (
        <DeleteBookDialog
          book={dialog.book}
          libraryFolder={dialog.folder}
          onClose={() => setDialog(null)}
          onDeleted={() => {
            invalidateBooks(dialog.folder)
            setDialog(null)
          }}
        />
      )}

      {dialog?.type === 'delete-format' && (
        <DeleteFormatDialog
          book={dialog.book}
          libraryFolder={dialog.folder}
          format={dialog.format}
          onClose={() => setDialog(null)}
          onDeleted={() => {
            invalidateBooks(dialog.folder)
            setDialog(null)
          }}
        />
      )}

      {dialog?.type === 'toc' && (
        <TocEditorDialog book={dialog.book} libraryFolder={dialog.folder} onClose={() => setDialog(null)} />
      )}

      {dialog?.type === 'bulk-delete' && (
        <BulkDeleteBooksDialog
          books={dialog.books}
          libraryFolder={dialog.folder}
          onClose={() => setDialog(null)}
          onDeleted={() => {
            invalidateBooks(dialog.folder)
            setDialog(null)
          }}
        />
      )}

      {dialog?.type === 'bulk-metadata' && (
        <BulkMetadataEditorDialog
          targets={dialog.targets}
          onClose={() => setDialog(null)}
          onSaved={(librerieToccate, campiScritti) => {
            librerieToccate.forEach(invalidateBooks)
            // L'autore può essere appena cambiato: l'elenco autori, la
            // scheda dell'autore e i suoi libri mostrano tutti il vecchio
            // nome finché non li si ributta via.
            queryClient.invalidateQueries({ queryKey: ['authors'] })
            queryClient.invalidateQueries({ queryKey: ['author-books'] })
            dialog.alSalvataggio?.(campiScritti)
            setDialog(null)
          }}
        />
      )}
    </BookActionsContext.Provider>
  )
}
