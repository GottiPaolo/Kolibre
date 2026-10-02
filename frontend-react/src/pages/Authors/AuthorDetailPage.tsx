import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, BookOpen, Check, Pencil, RefreshCw, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuthorBooks, useAuthorDetail } from '@/lib/queries'
import { useRowSelection } from '@/lib/useRowSelection'
import { useBookActions } from '@/lib/bookActionsContext'
import { splitAuthorNames } from '@/lib/authorNames'
import { useAmbitoAutori } from '@/lib/authorsScope'
import { AuthorReadingStrip } from './AuthorReadingStrip'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { withBackendUrl } from '@/lib/api'
import {
  deleteAuthorPhoto,
  refreshAuthorFromWikipedia,
  refreshAuthorFromWikipediaUrl,
  resetAuthorData,
  updateAuthorBio,
  updateAuthorFields,
  uploadAuthorPhoto,
} from '@/lib/authorActions'
import { AuthorPhotoSearchDialog } from './AuthorPhotoSearchDialog'
import {
  AuthorFactsForm,
  AuthorFactsList,
  draftFromAuthor,
  draftToFields,
  type FactsDraft,
} from './AuthorFacts'
import { useLingua } from '@/lib/i18n'

export function AuthorDetailPage() {
  const { t } = useLingua()
  const { name: rawName } = useParams()
  const name = rawName ?? ''
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: author, isLoading } = useAuthorDetail(name)
  // Lo stesso ambito scelto nell'elenco: chi guarda "gli autori di X" non
  // si aspetta, aprendone uno, di trovare libri che in X non ci sono.
  const [ambito] = useAmbitoAutori()
  const { data: books = [] } = useAuthorBooks(name, ambito)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const actions = useBookActions()

  // Selezione multipla sulle opere: Cmd/Ctrl+click aggiunge un libro,
  // Shift+click estende dall'ultimo toccato, click semplice apre il libro
  // come prima. È il caso da cui nasce tutto questo: un autore memorizzato
  // male ("Rossi Mario") si corregge selezionando qui i suoi libri e
  // modificandoli in blocco, senza passare dalla Libreria e cercarli uno
  // per uno.
  const { selected, toggle, clear, setSelected } = useRowSelection(books.map((b) => b.id))

  function handleBookClick(book: { id: number; library: string }, e: React.MouseEvent) {
    if (e.metaKey || e.ctrlKey || e.shiftKey) {
      // Su una griglia, Shift+click seleziona anche del testo attorno: con
      // la selezione multipla attiva è solo rumore visivo.
      e.preventDefault()
      toggle(book.id, { shiftKey: e.shiftKey })
      return
    }
    if (selected.size > 0) {
      // Con una selezione aperta, il click semplice la chiude invece di
      // portare via dalla pagina: uscire per sbaglio dopo aver scelto venti
      // libri è la cosa più fastidiosa che possa succedere qui.
      clear()
      return
    }
    navigate(`/libri/${book.id}`, { state: { libraryFolder: book.library } })
  }

  // Dopo una modifica in blocco: via la selezione, e — se è cambiato
  // l'autore — via anche da questa pagina. Correggere "Rossi Mario" da qui
  // significa che questo autore ora NON ESISTE PIÙ: restando fermi si
  // vedrebbe la sua scheda con "Nessun libro trovato" e la barra di
  // selezione ancora accesa, cioè una pagina che sembra rotta proprio
  // quando l'operazione è riuscita.
  function alSalvataggioInBlocco(campiScritti: Record<string, unknown>) {
    clear()
    const nuovo = typeof campiScritti.author === 'string' ? campiScritti.author.trim() : ''
    if (!nuovo || nuovo === name) return
    // Con più autori ("A & B") la pagina di destinazione è quella del
    // primo: un indirizzo con la stringa intera non è un autore reale.
    const primo = splitAuthorNames(nuovo)[0] ?? nuovo
    navigate(`/autori/${encodeURIComponent(primo)}`, { replace: true })
  }

  // Esc annulla la selezione, come in ogni gestore di file.
  useEffect(() => {
    if (selected.size === 0) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') clear()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected.size, clear])

  useSetPageHeader(name)

  const [bioLang, setBioLang] = useState<'it' | 'en'>('it')
  const [isEditing, setIsEditing] = useState(false)
  const [bioItDraft, setBioItDraft] = useState('')
  const [bioEnDraft, setBioEnDraft] = useState('')
  const [showPhotoSearch, setShowPhotoSearch] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [wikiUrlDraft, setWikiUrlDraft] = useState('')
  const [refreshingFromUrl, setRefreshingFromUrl] = useState(false)

  useEffect(() => {
    if (author) {
      setBioItDraft(author.bio_it ?? '')
      setBioEnDraft(author.bio_en ?? '')
    }
  }, [author])

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['author', name] })
    queryClient.invalidateQueries({ queryKey: ['authors'] })
  }

  async function saveBio(field: 'bio_it' | 'bio_en', value: string) {
    try {
      await updateAuthorBio(name, { [field]: value })
      invalidate()
    } catch {
      setError(t('authors.detail.saveBioFailed'))
    }
  }

  async function handleExitEditMode() {
    // "Fine modifica" salva TUTTO insieme: biografia e anagrafica. Prima
    // erano due salvataggi separati con due pulsanti diversi nello stesso
    // riquadro, che e' il motivo per cui la scheda sembrava due schede.
    await saveBio(bioLang === 'it' ? 'bio_it' : 'bio_en', bioLang === 'it' ? bioItDraft : bioEnDraft)
    await saveFacts(draftToFields(factsDraft))
    setIsEditing(false)
  }

  async function saveFacts(fields: Record<string, string | string[]>) {
    setError(null)
    try {
      const updated = await updateAuthorFields(name, fields)
      queryClient.setQueryData(['author', name], updated)
      // L'elenco autori mostra le stesse colonne: senza questo resterebbe
      // indietro finche' non scade la cache.
      void queryClient.invalidateQueries({ queryKey: ['authors'] })
    } catch {
      setError(t('authors.detail.saveFactsFailed'))
    }
  }

  async function handleRefreshWikipedia() {
    if (!window.confirm(t('authors.detail.confirmRefresh', { name }))) return
    setRefreshing(true)
    setError(null)
    try {
      const aggiornato = await refreshAuthorFromWikipedia(name)
      // Stessa ragione del modulo con l'indirizzo qui sotto: se si e' in
      // modifica, la bozza non si aggiorna da sola.
      setFactsDraft(draftFromAuthor(aggiornato))
      invalidate()
    } catch {
      setError(t('authors.detail.refreshFailed'))
    } finally {
      setRefreshing(false)
    }
  }

  async function handleRefreshFromUrl(e: React.FormEvent) {
    e.preventDefault()
    const url = wikiUrlDraft.trim()
    if (!url) return
    setRefreshingFromUrl(true)
    setError(null)
    try {
      const aggiornato = await refreshAuthorFromWikipediaUrl(name, url, bioLang)
      // La bozza va riseminata con quello che e' appena arrivato.
      //
      // Senza, l'anagrafica presa da Wikidata restava invisibile — e, molto
      // peggio, salvando la si cancellava: l'effetto qui sopra aggiorna la
      // bozza solo quando NON si sta modificando, e questo modulo si usa
      // proprio mentre si modifica. Il pannello continuava a mostrare i
      // campi vuoti di prima, e "Salva" li rimandava vuoti al server.
      // In uso si vedeva come "incollo il link e importa solo biografia".
      setFactsDraft(draftFromAuthor(aggiornato))
      invalidate()
      setWikiUrlDraft('')
    } catch {
      setError(t('authors.detail.refreshFromUrlFailed'))
    } finally {
      setRefreshingFromUrl(false)
    }
  }

  async function handleUploadPhoto(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      await uploadAuthorPhoto(name, file)
      invalidate()
    } catch {
      setError(t('authors.detail.uploadPhotoFailed'))
    } finally {
      e.target.value = ''
    }
  }

  async function handleDeletePhoto() {
    try {
      await deleteAuthorPhoto(name)
      invalidate()
    } catch {
      setError(t('authors.detail.deletePhotoFailed'))
    }
  }

  async function handleResetAll() {
    if (!window.confirm(t('authors.detail.confirmResetAll', { name }))) return
    try {
      await resetAuthorData(name)
      invalidate()
      setIsEditing(false)
    } catch {
      setError(t('authors.detail.resetFailed'))
    }
  }

  // Bozza dell'anagrafica. DEVE stare prima del return anticipato qui sotto:
  // React conta gli hook in ordine, e dichiararli dopo un return significa
  // chiamarne un numero diverso a seconda che i dati siano arrivati o no
  // ("Rendered more hooks than during the previous render"). Il compilatore
  // non lo vede, il browser si'.
  const [factsDraft, setFactsDraft] = useState<FactsDraft>({
    gender: '', nationality: '', birth_date: '', death_date: '', occupations: '',
  })
  useEffect(() => {
    if (author && !isEditing) setFactsDraft(draftFromAuthor(author))
  }, [author, isEditing])

  if (isLoading || !author) return <p className="text-muted-foreground">{t('common.loading')}</p>

  const wikipediaUrl = bioLang === 'it' ? author.wikipedia_url_it : author.wikipedia_url_en
  const bioText = bioLang === 'it' ? author.bio_it : author.bio_en
  // La voce da cui viene la biografia mostrata, nella lingua mostrata.
  const fonteBio = bioLang === 'it' ? author.wikipedia_url_it : author.wikipedia_url_en

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="flex items-center gap-2">
        {/* Il nome viaggia con la navigazione: l'elenco lo usa per riaprirsi
            sulla pagina giusta e rimettersi proprio su questo autore. Con
            l'elenco a pagine il solo ripristino dello scorrimento non basta
            piu' — si ripartiva sempre dalla prima pagina. */}
        <Button variant="ghost" size="sm" onClick={() => navigate('/autori', { state: { autore: name } })}>
          <ArrowLeft className="size-3.5" />
          {t('authors.detail.allAuthors')}
        </Button>
        <h1 className="font-serif text-[18px] font-semibold">{name}</h1>
        {wikipediaUrl && (
          <a href={wikipediaUrl} target="_blank" rel="noreferrer" className="text-[12.5px] text-primary hover:underline">
            Wikipedia ↗
          </a>
        )}
        <Button variant="outline" size="sm" className="ml-auto" onClick={handleRefreshWikipedia} disabled={refreshing}>
          <RefreshCw className={`size-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          {t('authors.detail.refreshFromWikipedia')}
        </Button>
      </div>

      {/* Removibile: e' un componente suo con un endpoint suo, e sparisce da
          solo sugli autori mai letti. Vedi AuthorReadingStrip. */}
      {name && <AuthorReadingStrip name={name} library={ambito} />}

      <div className="flex gap-5">
        {/* self-start: senza, il contenitore si stira in altezza per pareggiare
            la colonna a fianco — che in modifica cresce — e il cerchio diventa
            una pastiglia con la foto in cima e un vuoto sotto (difetto
            riscontrato in uso). Stesso identico difetto gia' corretto sulla
            copertina nella scheda libro. */}
        <div className="w-[140px] shrink-0 self-start overflow-hidden rounded-full border border-border bg-muted">
          {author.photo_url ? (
            <img src={withBackendUrl(author.photo_url)} alt={name} loading="lazy" className="aspect-square w-full object-cover" />
          ) : (
            <div className="flex aspect-square w-full items-center justify-center text-muted-foreground">
              <Users className="size-8" />
            </div>
          )}
        </div>

        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex gap-1">
            <Button variant={bioLang === 'it' ? 'secondary' : 'ghost'} size="sm" onClick={() => setBioLang('it')}>
              {t('authors.detail.langItalian')}
            </Button>
            <Button variant={bioLang === 'en' ? 'secondary' : 'ghost'} size="sm" onClick={() => setBioLang('en')}>
              {t('authors.detail.langEnglish')}
            </Button>
          </div>

          {/* Anagrafica prima della biografia: sono i dati "da scheda", e si
              leggono a colpo d'occhio prima del testo lungo. */}
          {isEditing ? (
            <AuthorFactsForm draft={factsDraft} onChange={setFactsDraft} />
          ) : (
            <AuthorFactsList author={author} />
          )}

          {isEditing ? (
            <textarea
              autoFocus
              value={bioLang === 'it' ? bioItDraft : bioEnDraft}
              onChange={(e) => (bioLang === 'it' ? setBioItDraft(e.target.value) : setBioEnDraft(e.target.value))}
              onBlur={() => saveBio(bioLang === 'it' ? 'bio_it' : 'bio_en', bioLang === 'it' ? bioItDraft : bioEnDraft)}
              rows={8}
              className="w-full resize-none rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
            />
          ) : (
            <>
              <p className="text-[13.5px] leading-relaxed whitespace-pre-wrap">{bioText || t('authors.detail.noBio')}</p>
              {/* Da dove viene il testo, quando viene da Wikipedia.
                  Le biografie sono CC BY-SA 4.0 e non escono mai da qui — non
                  finiscono nell'export delle annotazioni, nel vault Obsidian o
                  nella libreria Calibre — quindi l'obbligo è sottile: morde su
                  chi ridistribuisce o mostra in pubblico, e un'istanza
                  personale non fa né l'uno né l'altro. Morde però appena un
                  secondo utente legge questa pagina, e Kolibre è multiutente.
                  Costa una riga, e verso chi quel testo l'ha scritto è
                  semplicemente la cosa giusta.
                  La riga sparisce da sé quando la biografia è stata riscritta
                  a mano e non c'è più un link: lì non c'è niente da attribuire. */}
              {bioText && fonteBio && (
                <p className="text-[11px] text-muted-foreground/80">
                  {t('authors.detail.sourcePrefix')}{' '}
                  <a
                    href={fonteBio}
                    target="_blank"
                    rel="noreferrer"
                    className="underline decoration-dotted underline-offset-2 hover:text-foreground"
                  >
                    Wikipedia
                  </a>{' '}
                  ·{' '}
                  <a
                    href="https://creativecommons.org/licenses/by-sa/4.0/deed.it"
                    target="_blank"
                    rel="noreferrer"
                    className="underline decoration-dotted underline-offset-2 hover:text-foreground"
                  >
                    CC BY-SA 4.0
                  </a>
                </p>
              )}
            </>
          )}

          <div className="flex justify-end">
            <Button variant="ghost" size="icon-sm" onClick={() => setIsEditing(true)} aria-label={t('authors.detail.editBioAriaLabel')}>
              <Pencil className="size-3.5" />
            </Button>
          </div>

          {isEditing && (
            <form onSubmit={handleRefreshFromUrl} className="flex gap-1.5 border-t border-border pt-2">
              <input
                value={wikiUrlDraft}
                onChange={(e) => setWikiUrlDraft(e.target.value)}
                placeholder={t('authors.detail.wikiLinkPlaceholder', { lang: bioLang === 'it' ? 'IT' : 'EN' })}
                className="w-full min-w-0 flex-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
              />
              <Button type="submit" variant="outline" size="sm" disabled={refreshingFromUrl || !wikiUrlDraft.trim()}>
                <RefreshCw className={`size-3.5 ${refreshingFromUrl ? 'animate-spin' : ''}`} />
                {t('authors.detail.downloadFromLink')}
              </Button>
            </form>
          )}

          {isEditing && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleUploadPhoto} />
              <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
                {t('authors.detail.changePhoto')}
              </Button>
              <Button variant="outline" size="sm" onClick={() => setShowPhotoSearch(true)}>
                🔍 {t('authors.detail.searchPhotoOnline')}
              </Button>
              <Button variant="outline" size="sm" onClick={handleDeletePhoto}>
                {t('authors.detail.deletePhoto')}
              </Button>
              <Button variant="destructive" size="sm" onClick={handleResetAll}>
                {t('authors.detail.resetAllData')}
              </Button>
              <Button size="sm" onClick={handleExitEditMode}>
                ✓ {t('authors.detail.exitEditMode')}
              </Button>
            </div>
          )}

          {error && <p className="text-[12.5px] text-destructive">{error}</p>}
        </div>
      </div>

      <div>
        <div className="mb-2 flex min-h-7 items-center gap-2">
          <h3 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('authors.detail.worksInLibrary')}</h3>
          {selected.size > 0 ? (
            <div className="ml-auto flex items-center gap-2">
              <span className="text-[12px] text-primary">{t('library.selection.count', { count: selected.size, n: selected.size })}</span>
              {selected.size < books.length && (
                // Correggere un autore scritto male riguarda quasi sempre
                // TUTTI i suoi libri: senza questo si finisce a cliccarne
                // quaranta a mano.
                <Button variant="ghost" size="sm" onClick={() => setSelected(new Set(books.map((b) => b.id)))}>
                  {t('authors.detail.selectAll', { count: books.length })}
                </Button>
              )}
              <Button
                size="sm"
                onClick={() =>
                  actions.bulkEditMetadataTargets(
                    books.filter((b) => selected.has(b.id)).map((b) => ({ id: b.id, library: b.library })),
                    alSalvataggioInBlocco
                  )
                }
              >
                <Pencil className="size-3.5" />
                {t('authors.detail.editMetadata')}
              </Button>
              <Button variant="ghost" size="sm" onClick={clear}>
                {t('common.cancel')}
              </Button>
            </div>
          ) : (
            books.length > 1 && (
              <span className="ml-auto text-[11.5px] text-muted-foreground">
                {t('authors.detail.multiSelectHint')}
              </span>
            )
          )}
        </div>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-3">
          {books.map((book) => {
            const isSelected = selected.has(book.id)
            return (
              <button
                key={book.id}
                onClick={(e) => handleBookClick(book, e)}
                aria-pressed={isSelected}
                className="flex flex-col gap-1 text-left"
              >
                {/* `relative` per la spunta d'angolo; l'anello di selezione è
                    un ring e non un bordo perché un bordo sposterebbe di 2px
                    la copertina rispetto alle vicine non selezionate. */}
                <div
                  className={`relative aspect-[2/3] overflow-hidden rounded-md border border-border bg-muted ${
                    isSelected ? 'ring-2 ring-primary ring-offset-1 ring-offset-background' : ''
                  }`}
                >
                  {book.cover_url ? (
                    <img src={withBackendUrl(book.cover_url)} alt={book.title} loading="lazy" className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-muted-foreground">
                      <BookOpen className="size-6" />
                    </div>
                  )}
                  {isSelected && (
                    <span className="absolute top-1 right-1 flex size-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
                      <Check className="size-3.5" />
                    </span>
                  )}
                </div>
                <span className={`line-clamp-2 text-[11.5px] ${isSelected ? 'text-primary' : ''}`}>{book.title}</span>
              </button>
            )
          })}
          {books.length === 0 && <p className="text-[12.5px] text-muted-foreground">{t('authors.detail.noBooksFound')}</p>}
        </div>
      </div>

      {showPhotoSearch && (
        <AuthorPhotoSearchDialog
          authorName={name}
          onClose={() => setShowPhotoSearch(false)}
          onApplied={() => {
            invalidate()
            setShowPhotoSearch(false)
          }}
        />
      )}
    </div>
  )
}
