import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, BookOpen, Library as LibraryIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useBooks, useLibraries } from '@/lib/queries'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { withBackendUrl } from '@/lib/api'
import { splitAuthorNames } from '@/lib/authorNames'
import { ListError } from '@/components/ListError'
import { useLingua } from '@/lib/i18n'

// Le serie sono per-libreria (a differenza di Autori, che è cross-libreria)
// e derivate client-side dai libri già caricati — nessun endpoint dedicato
// esiste lato backend (verificato: nessun router "series.py").
export function SeriesPage() {
  const { t } = useLingua()
  const navigate = useNavigate()
  const { data: libraries } = useLibraries()
  const [activeLibraryId, setActiveLibraryId] = useState<number | null>(null)
  const activeLibrary = useMemo(
    () => libraries?.find((l) => l.id === activeLibraryId) ?? libraries?.[0],
    [libraries, activeLibraryId]
  )
  const { data: books = [], isLoading, isError, refetch } = useBooks(activeLibrary?.folder_name)

  // Il titolo della PAGINA, non il nome della biblioteca: la riga in alto
  // diceva «Library» anche stando su Serie, ed era l'unica pagina a farlo —
  // tutte le altre mettono il proprio titolo, e la Libreria mette il nome
  // della biblioteca perché lì è quello il soggetto.
  useSetPageHeader(t('series.pageTitle'))

  const [selectedSeries, setSelectedSeries] = useState<string | null>(null)

  const uniqueSeries = useMemo(() => {
    const counts = new Map<string, number>()
    for (const b of books) {
      if (b.series) counts.set(b.series, (counts.get(b.series) ?? 0) + 1)
    }
    return Array.from(counts.entries()).map(([name, count]) => ({ name, count }))
  }, [books])

  const booksInSeries = useMemo(
    () =>
      books
        .filter((b) => b.series === selectedSeries)
        .sort((a, b) => (a.series_index ?? 0) - (b.series_index ?? 0)),
    [books, selectedSeries]
  )

  if (isLoading) return <p className="text-muted-foreground">{t('common.loading')}</p>

  return (
    <div className="flex flex-col gap-3">
      {!selectedSeries && libraries && libraries.length > 1 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="self-start">
              <LibraryIcon className="size-3.5" />
              {activeLibrary?.name}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {libraries.map((lib) => (
              <DropdownMenuItem key={lib.id} onSelect={() => setActiveLibraryId(lib.id)}>
                {lib.name}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      {!selectedSeries && (
        <div className="flex flex-col gap-1">
          {uniqueSeries.map((s) => (
            <button
              key={s.name}
              onClick={() => setSelectedSeries(s.name)}
              className="flex items-center gap-2 rounded-md border border-border/60 px-3 py-2 text-left text-[13px] hover:bg-accent/60"
            >
              <span>📚 {s.name}</span>
              <Badge variant="outline" className="ml-auto">
                {s.count} {t('series.badge.bookCount', { count: s.count, n: s.count })}
              </Badge>
            </button>
          ))}
          {isError && <ListError what={t('series.error.subject')} onRetry={() => void refetch()} />}
          {!isError && uniqueSeries.length === 0 && (
            <p className="text-muted-foreground">{t('series.empty.noSeries')}</p>
          )}
        </div>
      )}

      {selectedSeries && (
        <div className="flex flex-col gap-3">
          <Button variant="ghost" size="sm" className="self-start" onClick={() => setSelectedSeries(null)}>
            <ArrowLeft className="size-3.5" />
            {t('series.allSeries')}
          </Button>
          <h2 className="font-serif text-[17px] font-semibold">{selectedSeries}</h2>
          <div className="flex flex-col gap-1">
            {booksInSeries.map((book) => (
              <button
                key={book.id}
                onClick={() => navigate(`/libri/${book.id}`, { state: { libraryFolder: activeLibrary?.folder_name } })}
                className="flex items-center gap-3 rounded-md border border-border/60 px-3 py-2 text-left text-[13px] hover:bg-accent/60"
              >
                <div className="h-12 w-8 shrink-0 overflow-hidden rounded bg-muted">
                  {book.cover_url ? (
                    <img src={withBackendUrl(book.cover_url)} alt={book.title} loading="lazy" className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-muted-foreground">
                      <BookOpen className="size-3.5" />
                    </div>
                  )}
                </div>
                <div className="min-w-0">
                  <p className="truncate">
                    {t('series.volumeLine', { index: book.series_index ?? '—', title: book.title })}
                  </p>
                  <p className="truncate text-[11.5px] text-muted-foreground">{splitAuthorNames(book.author).join(' & ')}</p>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
