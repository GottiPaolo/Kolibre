import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, BookCheck, ChevronLeft, ChevronRight, Pencil, ListTree } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import { risultaLetto } from '@/lib/readFlag'
import { Badge } from '@/components/ui/badge'
import { useBookLookup } from './useBookLookup'
import { useBookActions } from '@/lib/bookActionsContext'
import { useBookStats, useCustomColumns, useLibraries } from '@/lib/queries'
import { withBackendUrl } from '@/lib/api'
import { splitAuthorNames } from '@/lib/authorNames'
import { formatBytes, formatDate } from '@/lib/format'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { useShortcuts } from '@/lib/useShortcuts'
import { openBookFormatInReader } from '@/lib/readerActions'
import { HighlightsPanel } from './HighlightsPanel'
import { StatsPanel } from './StatsPanel'
import { identifierUrl } from '@/lib/identifiers'
import { TagFiltrabili, ValoreFiltrabile } from '@/components/ValoreFiltrabile'

export function BookDetailPage() {
  const { t } = useLingua()
  const { id } = useParams()
  const bookId = Number(id)
  const navigate = useNavigate()
  const actions = useBookActions()
  const { book, libraryFolder, isLoading, notFound, prevId, nextId } = useBookLookup(bookId)
  const { data: stats, isError: statsInErrore, refetch: ricaricaStats } = useBookStats(libraryFolder, book?.id)
  const { data: customColumns = [] } = useCustomColumns(libraryFolder)
  const { data: libraries = [] } = useLibraries()

  useSetPageHeader(book?.title ?? t('library.detail.pageTitle'))

  // "e" apre i metadati, "v" apre il lettore — i tasti sono quelli del
  // registro comandi (personalizzabili in Impostazioni ▸ Sistema), non
  // costanti scritte qui. DEVE stare prima dei return anticipati qui sotto:
  // React conta gli hook in ordine, e saltarne uno quando il libro non e'
  // ancora arrivato romperebbe il render successivo.
  useShortcuts({
    'edit-metadata': () => book && actions.editMetadata(book),
    'read-book-web': () => book && actions.readBook(book),
  })

  if (isLoading) return <p className="text-muted-foreground">{t('common.loading')}</p>
  if (notFound || !book) return <p className="text-muted-foreground">{t('library.detail.notFound')}</p>

  const authors = splitAuthorNames(book.author)
  const pagesCol = customColumns.find((c) => c.label === 'pages')
  const estimatedPages = pagesCol ? book[`#${pagesCol.label}`] : undefined

  function goTo(targetId: number | null) {
    if (targetId === null) return
    navigate(`/libri/${targetId}`, { state: { libraryFolder } })
  }

  // Se il libro risulta letto. Solo un'indicazione, non un comando:
  // cambiare lo stato di lettura non e' un gesto che si fa spesso, e un
  // pulsante sempre in vista lo faceva sembrare tale. Si cambia da dove si
  // cambiano gli altri metadati (Modifica Metadati) o in blocco dalla
  // pagina Interventi.
  const letto = risultaLetto(book)

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="flex items-center gap-2">
        {/* selectedBookId in location.state: LibraryPage lo legge al mount e
            ripristina la selezione (il meccanismo esisteva gia', usato dal
            salto verso la pagina Autore, ma questo pulsante non lo passava).
            Tornando alla libreria la riga del libro appena guardato risulta
            quindi selezionata, e insieme al ripristino dello scorrimento si
            ritrova esattamente il punto da cui si era partiti. */}
        {/* Anche la libreria, non solo il libro: un libro aperto da una
            libreria che non e' la prima dell'elenco riportava alla PRIMA, e
            li' il libro selezionato non esiste nemmeno. Difetto riscontrato
            in uso. */}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate('/', { state: { selectedBookId: bookId, libraryFolder } })}
        >
          <ArrowLeft className="size-3.5" />
          {t('library.detail.backToLibrary')}
        </Button>
        <Button variant="outline" size="sm" onClick={() => actions.editMetadata(book)}>
          <Pencil className="size-3.5" />
          {t('library.detail.editMetadata')}
        </Button>
        <Button variant="outline" size="sm" onClick={() => actions.editToc(book)}>
          <ListTree className="size-3.5" />
          {t('library.detail.editToc')}
        </Button>
        <div className="ml-auto flex gap-1">
          <Button variant="ghost" size="icon-sm" onClick={() => goTo(prevId)} disabled={prevId === null}>
            <ChevronLeft className="size-4" />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => goTo(nextId)} disabled={nextId === null}>
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </div>

      <div className="flex gap-5">
        {/* self-start: senza, questo box (cross-axis di un flex row) viene
            stirato in altezza per pareggiare la colonna di testo a fianco —
            l'immagine reale resta alta quanto il suo rapporto naturale,
            lasciando sotto uno spazio vuoto color bg-muted che si vede come
            un "riquadro" attorno a una copertina più piccola. Difetto
            riscontrato in uso. */}
        <div className="w-[160px] shrink-0 self-start overflow-hidden rounded-md border border-border bg-muted">
          {book.cover_url && <img src={withBackendUrl(book.cover_url)} alt={book.title} className="w-full object-cover" />}
        </div>

        <div className="min-w-0 flex-1 space-y-3">
          <div>
            <div className="flex items-start gap-2">
              <h1 className="min-w-0 flex-1 font-serif text-[22px] font-semibold leading-tight">{book.title}</h1>
              {letto && (
                <Badge variant="secondary" className="mt-1 shrink-0 gap-1">
                  <BookCheck className="size-3" />
                  {t('library.detail.read')}
                </Badge>
              )}
            </div>
            <p className="mt-1 text-[14px] text-muted-foreground">
              {authors.map((name, idx) => (
                <span key={name}>
                  {idx > 0 && ' & '}
                  <button onClick={() => actions.goToAuthor(name)} className="hover:text-primary hover:underline">
                    {name}
                  </button>
                </span>
              ))}
            </p>
          </div>

          <dl className="grid grid-cols-[110px_1fr] gap-y-1.5 text-[13px]">
            <dt className="text-muted-foreground">{t('library.field.formats')}</dt>
            <dd className="flex flex-wrap gap-1">
              {book.formats.map((f) =>
                f === 'EPUB' || f === 'PDF' ? (
                  <button key={f} onClick={() => libraryFolder && openBookFormatInReader(book, libraryFolder, f)}>
                    <Badge variant="outline" className="cursor-pointer hover:border-primary hover:text-primary">
                      {f}
                    </Badge>
                  </button>
                ) : (
                  <Badge key={f} variant="outline">
                    {f}
                  </Badge>
                )
              )}
            </dd>
            {book.series && (
              <>
                <dt className="text-muted-foreground">{t('library.field.series')}</dt>
                <dd>
                  {book.series} {book.series_index != null && `#${book.series_index}`}
                </dd>
              </>
            )}
            {/* Editore, lingua e tag portano alla libreria filtrata su quel
                valore. Autore e formato restano fuori: hanno gia' un loro
                comportamento (la scheda dell'autore, l'apertura nel
                lettore) e cambiarlo sarebbe una perdita. */}
            {book.publisher && (
              <>
                <dt className="text-muted-foreground">{t('library.field.publisher')}</dt>
                <dd>
                  <ValoreFiltrabile campo="publisher" valore={book.publisher} />
                </dd>
              </>
            )}
            {book.language && (
              <>
                <dt className="text-muted-foreground">{t('library.field.language')}</dt>
                <dd>
                  <ValoreFiltrabile campo="language" valore={book.language} />
                </dd>
              </>
            )}
            {book.tags.length > 0 && (
              <>
                <dt className="text-muted-foreground">{t('library.field.tags')}</dt>
                <dd className="flex flex-wrap gap-x-1 gap-y-0.5">
                  <TagFiltrabili tags={book.tags} />
                </dd>
              </>
            )}
            {Object.keys(book.identifiers).length > 0 && (
              <>
                <dt className="text-muted-foreground">{t('library.field.identifiers')}</dt>
                {/* Uno per riga e non piu' tutti schiacciati su una stringa
                    sola: un libro reale ne ha fino a dieci (isbn, google,
                    goodreads, oclc, viaf, lccn, isni…) e "isbn:978…,
                    google:AbC…, oclc-owi:123…" era illeggibile. Quelli che
                    hanno un catalogo consultabile diventano collegamenti. */}
                <dd className="flex flex-col gap-0.5">
                  {Object.entries(book.identifiers).map(([k, v]) => {
                    const href = identifierUrl(k, String(v))
                    return (
                      <span key={k} className="flex gap-2">
                        <span className="w-32 shrink-0 text-muted-foreground">{k}</span>
                        {href ? (
                          <a
                            href={href}
                            target="_blank"
                            rel="noreferrer"
                            className="min-w-0 break-all text-primary hover:underline"
                          >
                            {String(v)}
                          </a>
                        ) : (
                          <span className="min-w-0 break-all">{String(v)}</span>
                        )}
                      </span>
                    )
                  })}
                </dd>
              </>
            )}
            <dt className="text-muted-foreground">{t('library.field.sizeShort')}</dt>
            <dd>{formatBytes(book.size)}</dd>
            {estimatedPages != null && estimatedPages !== '' && (
              <>
                <dt className="text-muted-foreground">{t('library.detail.estimatedPages')}</dt>
                <dd>{String(estimatedPages)}</dd>
              </>
            )}
            <dt className="text-muted-foreground">{t('library.field.published')}</dt>
            <dd>{formatDate(book.pubdate)}</dd>
            <dt className="text-muted-foreground">{t('library.field.lastModified')}</dt>
            <dd>{formatDate(book.last_modified)}</dd>
            {/* Da quale biblioteca viene. Solo quando ce n'e' piu' d'una:
                con una sola libreria e' un'informazione che non distingue
                niente. Il nome e' quello VISUALIZZATO, gia' allegato a ogni
                libro dal backend (_library), non la cartella. */}
            {libraries.length > 1 && book._library && (
              <>
                <dt className="text-muted-foreground">{t('library.detail.library')}</dt>
                <dd>{book._library}</dd>
              </>
            )}
            <dt className="text-muted-foreground">{t('library.field.uuid')}</dt>
            <dd className="truncate font-mono text-[11px] text-muted-foreground">{book.uuid}</dd>
          </dl>
        </div>
      </div>

      {book.description && (
        <div>
          <h3 className="mb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('library.field.description')}</h3>
          <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed">{book.description}</p>
        </div>
      )}

      {/* Un errore qui NON deve assomigliare a "questo libro non ha
          statistiche": lo stato vuoto vive dentro StatsPanel, quindi
          rendendo solo `stats && ...` una chiamata fallita faceva sparire
          l'intero riquadro, banner compreso. E' successo davvero — un 500
          su questo endpoint (vedi 7e56b47) si e' presentato, in uso, come
          "i pannelli non ci sono piu'", senza niente che lo spiegasse. */}
      {(stats || statsInErrore) && (
        <div>
          <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('library.detail.readingStats')}</h3>
          {stats ? (
            <StatsPanel stats={stats} />
          ) : (
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--warning)]/40 px-3 py-2 text-[12.5px] text-[var(--warning)]">
              <span>{t('library.detail.statsLoadFailed')}</span>
              <button onClick={() => void ricaricaStats()} className="underline underline-offset-2">
                {t('common.retry')}
              </button>
            </div>
          )}
        </div>
      )}

      {libraryFolder && <HighlightsPanel book={book} libraryFolder={libraryFolder} />}
    </div>
  )
}
