import { memo, useEffect, useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { cn } from '@/lib/utils'
import type { Book } from '@/types/library'
import { withBackendUrl } from '@/lib/api'
import { ratingStars } from '@/lib/format'
import { useScrollMemory } from '@/lib/useScrollMemory'
import { useLingua } from '@/lib/i18n'

interface LibraryCardsProps {
  books: Book[]
  selectedBookId: number | null
  onSelectBook: (book: Book) => void
  progressByBookId?: Record<number, number>
  // 'list' (default): elenco verticale a riga singola, per schermi sotto
  // "md" dove la tabella non ci sta. 'grid': griglia multi-colonna di
  // copertine, usata su desktop quando l'utente sceglie quella vista al
  // posto della tabella (vedi LibraryPage) — stesso componente, niente fork,
  // perché selezione/Quickview/dati sono identici tra le due viste.
  variant?: 'list' | 'grid'
}

// Altezza fissa per riga — stesso motivo di ROW_HEIGHT in LibraryTable.tsx
// (necessaria alla virtualizzazione): copertina + titolo/autore + una riga
// di metadati secondari ci stanno sempre in questo spazio con troncamento.
const CARD_HEIGHT = 92

// Vista alternativa alla tabella per schermi sotto "md" (768px): la tabella
// ha troppe colonne per un layout stretto, qui ogni libro è una riga singola
// (copertina + titolo/autore + serie/valutazione/formati), niente colonne
// configurabili né menu contestuale — le azioni restano raggiungibili dalla
// Quickview aperta al tap (vedi LibraryPage) e dal Dettaglio Esteso.
const LibraryCard = memo(function LibraryCard({
  book,
  isSelected,
  progressPercent,
  riga,
  onSelectBook,
}: {
  book: Book
  isSelected: boolean
  progressPercent: number | undefined
  /** Posizione nell'elenco, per le righe a colori alternati. */
  riga: number
  onSelectBook: (book: Book) => void
}) {
  return (
    <div
      role="row"
      aria-selected={isSelected}
      onClick={() => onSelectBook(book)}
      style={{ height: CARD_HEIGHT }}
      className={cn(
        'flex cursor-pointer items-center gap-3 border-b border-border/60 px-3 transition-colors hover:bg-accent/60',
        riga % 2 === 1 && 'bg-muted/25',
        isSelected && 'bg-primary/10 hover:bg-primary/10'
      )}
    >
      <div className="h-16 w-11 shrink-0 overflow-hidden rounded-sm bg-muted">
        {book.cover_url && <img src={withBackendUrl(book.cover_url)} alt="" loading="lazy" className="h-full w-full object-cover" />}
      </div>

      <div className="min-w-0 flex-1">
        <p className="truncate font-serif text-[14px] font-medium">{book.title}</p>
        <p className="truncate text-[12px] text-muted-foreground">{book.author || '—'}</p>
        <div className="mt-1 flex items-center gap-2 truncate text-[11px] text-muted-foreground">
          {book.series && (
            <span className="truncate">
              {book.series}
              {book.series_index != null && ` #${book.series_index}`}
            </span>
          )}
          {book.rating != null && <span className="shrink-0 text-[var(--warning)]">{ratingStars(book.rating)}</span>}
          {book.formats?.length > 0 && <span className="shrink-0">{book.formats.join(' · ')}</span>}
        </div>
        {progressPercent != null && (
          <div className="mt-1 flex items-center gap-1.5">
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary" style={{ width: `${progressPercent}%` }} />
            </div>
            <span className="shrink-0 text-[10px] text-muted-foreground">{progressPercent}%</span>
          </div>
        )}
      </div>
    </div>
  )
})

// Card della griglia copertine: verticale (copertina in alto, titolo/autore
// sotto) invece che a riga come LibraryCard — qui la copertina è il punto
// focale, come in AuthorsPage/DevicesPage (grid-cols auto-fill con card
// verticali). Niente serie/formati: a quella dimensione di card non ci
// stanno leggibili, e restano comunque visibili in Quickview al click.
const LibraryGridCard = memo(function LibraryGridCard({
  book,
  isSelected,
  progressPercent,
  onSelectBook,
}: {
  book: Book
  isSelected: boolean
  progressPercent: number | undefined
  onSelectBook: (book: Book) => void
}) {
  return (
    <div
      role="row"
      aria-selected={isSelected}
      onClick={() => onSelectBook(book)}
      className={cn(
        'flex cursor-pointer flex-col gap-1.5 rounded-md p-1.5 transition-colors hover:bg-accent/60',
        isSelected && 'bg-primary/10 hover:bg-primary/10'
      )}
    >
      <div className="aspect-[2/3] w-full overflow-hidden rounded-sm bg-muted shadow-sm">
        {book.cover_url && <img src={withBackendUrl(book.cover_url)} alt="" loading="lazy" className="h-full w-full object-cover" />}
      </div>
      <div className="min-w-0">
        <p className="truncate font-serif text-[13px] font-medium">{book.title}</p>
        <p className="truncate text-[11.5px] text-muted-foreground">{book.author || '—'}</p>
        {progressPercent != null && (
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary" style={{ width: `${progressPercent}%` }} />
          </div>
        )}
      </div>
    </div>
  )
})

export function LibraryCards({ books, selectedBookId, onSelectBook, progressByBookId = {}, variant = 'list' }: LibraryCardsProps) {
  const { t } = useLingua()
  const scrollRef = useRef<HTMLDivElement>(null)
  // Libreria ha il suo contenitore di scroll, indipendente da quello di
  // Layout: va ricordato a parte, o tornando da un dettaglio libro si
  // ripartirebbe comunque dalla prima riga.
  useScrollMemory(scrollRef, 'libreria-schede')

  // In modalità griglia la virtualizzazione a riga singola non serve (i libri
  // si dispongono su più colonne via CSS grid, non su un asse solo) — count 0
  // disattiva il virtualizer senza dover condizionare la chiamata all'hook.
  const virtualizer = useVirtualizer({
    count: variant === 'list' ? books.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => CARD_HEIGHT,
    overscan: 12,
  })

  // Stesso comportamento di LibraryTable: riprende lo scroll sulla riga già
  // selezionata solo al mount, non ad ogni cambio di selezione successivo.
  useEffect(() => {
    if (variant !== 'list' || selectedBookId == null) return
    const idx = books.findIndex((b) => b.id === selectedBookId)
    if (idx !== -1) virtualizer.scrollToIndex(idx, { align: 'auto' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const virtualItems = variant === 'list' ? virtualizer.getVirtualItems() : []

  // Le freccie scorrono i libri, come nella tabella. Solo nell'elenco: nella
  // griglia i libri stanno su piu' colonne, e "giu'" dovrebbe saltare di una
  // riga intera — un conteggio di colonne che qui non esiste, lo decide il
  // CSS. Meglio niente che una freccia che si muove di traverso.
  function scorriConLeFreccie(e: React.KeyboardEvent<HTMLDivElement>) {
    if (variant !== 'list') return
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    if (books.length === 0) return
    e.preventDefault()
    const corrente = books.findIndex((b) => b.id === selectedBookId)
    // Alt salta agli estremi; senza selezione la prima freccia parte dal
    // primo libro, in qualsiasi direzione la si prema.
    const prossimo = e.altKey
      ? e.key === 'ArrowUp'
        ? 0
        : books.length - 1
      : corrente === -1
        ? 0
        : Math.min(books.length - 1, Math.max(0, corrente + (e.key === 'ArrowDown' ? 1 : -1)))
    onSelectBook(books[prossimo])
    virtualizer.scrollToIndex(prossimo, { align: 'auto' })
  }

  return (
    <div role="table" className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-border text-[13px] text-foreground">
      <div
        ref={scrollRef}
        role="rowgroup"
        tabIndex={0}
        onKeyDown={scorriConLeFreccie}
        className={cn('min-h-0 flex-1 overflow-y-auto focus:outline-none', variant === 'grid' && 'p-3')}
      >
        {books.length === 0 ? (
          <div className="px-3 py-8 text-center text-muted-foreground">{t('library.empty.noMatch')}</div>
        ) : variant === 'grid' ? (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-3">
            {books.map((book) => (
              <LibraryGridCard
                key={book.id}
                book={book}
                isSelected={selectedBookId === book.id}
                progressPercent={progressByBookId[book.id]}
                onSelectBook={onSelectBook}
              />
            ))}
          </div>
        ) : (
          <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
            {virtualItems.map((virtualRow) => {
              const book = books[virtualRow.index]
              return (
                <div key={book.id} style={{ position: 'absolute', top: 0, left: 0, right: 0, transform: `translateY(${virtualRow.start}px)` }}>
                  <LibraryCard
                    book={book}
                    isSelected={selectedBookId === book.id}
                    progressPercent={progressByBookId[book.id]}
                    riga={virtualRow.index}
                    onSelectBook={onSelectBook}
                  />
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
