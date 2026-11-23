import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, BookOpen, Check, ChevronDown, Pencil, RefreshCw, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuthorBooks, useAuthorDetail } from '@/lib/queries'
import { useRowSelection } from '@/lib/useRowSelection'
import { useBookActions } from '@/lib/bookActionsContext'
import { splitAuthorNames } from '@/lib/authorNames'
import { useAmbitoAutori } from '@/lib/authorsScope'
import { AuthorReadingStrip } from './AuthorReadingStrip'
import { BottoneCopiaLink } from '@/components/BottoneCopiaLink'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { withBackendUrl } from '@/lib/api'
import { getWikipediaLanguagesSetting } from '@/lib/scraperSettingsActions'
import { autonym } from '@/lib/wikipediaLanguages'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
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
import { messaggioErrore } from '@/lib/messaggiErrore'

export function AuthorDetailPage() {
  const { t } = useLingua()
  const { name: rawName } = useParams()
  const name = rawName ?? ''
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: author, isLoading } = useAuthorDetail(name)
  // L'ambito scelto nell'elenco serve ancora alla fascia delle letture, non
  // ai libri: quelli sono **sempre tutti**, da ogni biblioteca, divisi per
  // biblioteca (Paolo, 08/11/2026). Prima si passava l'ambito anche qui, e
  // aprendo un autore si vedevano solo i libri della biblioteca attiva: nella
  // pratica i due insiemi coincidevano quasi sempre, e quando non coincidevano
  // non si capiva perche' un libro mancasse. L'ordine e il nome di ogni
  // biblioteca li decide il server — vedi get_author_books.
  const [ambito] = useAmbitoAutori()
  const { data: books = [] } = useAuthorBooks(name)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const actions = useBookActions()

  // Selezione multipla sulle opere: Cmd/Ctrl+click aggiunge un libro,
  // Shift+click estende dall'ultimo toccato, click semplice apre il libro
  // come prima. È il caso da cui nasce tutto questo: un autore memorizzato
  // male ("Rossi Mario") si corregge selezionando qui i suoi libri e
  // modificandoli in blocco, senza passare dalla Libreria e cercarli uno
  // per uno.
  const { selected, toggle, clear, setSelected } = useRowSelection(books.map((b) => b.id))

  // Un gruppo per biblioteca. L'elenco arriva **gia' ordinato** per nome di
  // biblioteca e poi per titolo, quindi i libri di una stessa biblioteca sono
  // contigui e basta spezzare dove il nome cambia: raggruppare qui con una
  // mappa darebbe lo stesso risultato ma rimetterebbe nel client una
  // decisione che sta nel server.
  const gruppi: { nome: string; libri: typeof books }[] = []
  for (const libro of books) {
    const nome = libro.library_name || libro.library
    const ultimo = gruppi[gruppi.length - 1]
    if (ultimo && ultimo.nome === nome) ultimo.libri.push(libro)
    else gruppi.push({ nome, libri: [libro] })
  }

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

  const [isEditing, setIsEditing] = useState(false)
  // La lingua della biografia mostrata (23/11/2026 sera): null = «decidi
  // tu», cioe' la prima dell'ordine delle Integrazioni che ha un testo.
  const [linguaBio, setLinguaBio] = useState<string | null>(null)
  useEffect(() => { setLinguaBio(null) }, [name])
  const [bioItDraft, setBioItDraft] = useState('')
  const [bioEnDraft, setBioEnDraft] = useState('')
  // Le lingue di Wikipedia scelte nelle impostazioni: decidono QUALI
  // pannelli esistono anche da vuoti. It/en come ripiego se il server
  // non risponde — sono le due lingue storiche.
  const [lingueImpostate, setLingueImpostate] = useState<string[]>(['it', 'en'])
  useEffect(() => {
    getWikipediaLanguagesSetting()
      .then(setLingueImpostate)
      .catch(() => {})
  }, [])
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
    } catch (err) {
      setError(messaggioErrore(err, t('authors.detail.saveBioFailed')))
    }
  }

  async function handleExitEditMode() {
    // "Fine modifica" salva TUTTO insieme: biografie e anagrafica. Prima
    // erano due salvataggi separati con due pulsanti diversi nello stesso
    // riquadro, che e' il motivo per cui la scheda sembrava due schede.
    // Coi pannelli per lingua (23/11/2026) le bozze modificabili sono due,
    // e si salvano tutte e due.
    await saveBio('bio_it', bioItDraft)
    await saveBio('bio_en', bioEnDraft)
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
    } catch (err) {
      setError(messaggioErrore(err, t('authors.detail.saveFactsFailed')))
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
    } catch (err) {
      setError(messaggioErrore(err, t('authors.detail.refreshFailed')))
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
      const aggiornato = await refreshAuthorFromWikipediaUrl(name, url)
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
    } catch (err) {
      setError(messaggioErrore(err, t('authors.detail.refreshFromUrlFailed')))
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
    } catch (err) {
      setError(messaggioErrore(err, t('authors.detail.uploadPhotoFailed')))
    } finally {
      e.target.value = ''
    }
  }

  async function handleDeletePhoto() {
    try {
      await deleteAuthorPhoto(name)
      invalidate()
    } catch (err) {
      setError(messaggioErrore(err, t('authors.detail.deletePhotoFailed')))
    }
  }

  async function handleResetAll() {
    if (!window.confirm(t('authors.detail.confirmResetAll', { name }))) return
    try {
      await resetAuthorData(name)
      invalidate()
      setIsEditing(false)
    } catch (err) {
      setError(messaggioErrore(err, t('authors.detail.resetFailed')))
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

  // UNA sola biografia visibile (23/11/2026 sera, giudizio di Paolo sul
  // giro del pomeriggio: la pila di pannelli era «tremenda» — «la
  // biografia sopra, parte della pagina, mai mostrarle tutte assieme ma
  // solo una per volta scegliendo da un tasto»). Le lingue offerte dal
  // tasto sono SOLO quelle che un testo ce l'hanno davvero, nell'ordine
  // delle Integrazioni; una lingua fuori impostazioni ma con una
  // biografia si accoda: i dati non si nascondono.
  const bios = author.bios ?? []
  const bioByLang = new Map(bios.map((b) => [b.lang, b]))
  const testoDi = (lang: string) =>
    (lang === 'it' ? author.bio_it : lang === 'en' ? author.bio_en : bioByLang.get(lang)?.bio) || null
  const fonteDi = (lang: string) =>
    (lang === 'it' ? author.wikipedia_url_it : lang === 'en' ? author.wikipedia_url_en : bioByLang.get(lang)?.wikipedia_url) || null
  const lingueDisponibili = [
    ...lingueImpostate,
    ...bios.map((b) => b.lang).filter((l) => !lingueImpostate.includes(l)),
  ].filter((lang, i, tutte) => tutte.indexOf(lang) === i && testoDi(lang) !== null)
  const linguaCorrente = linguaBio && lingueDisponibili.includes(linguaBio)
    ? linguaBio
    : lingueDisponibili[0] ?? null

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
        {/* Lo scaricamento da Wikipedia avviene **da se'**: questo comando
            serve solo a rifarlo a mano, quindi non e' il bottone principale
            della pagina (Paolo, 08/11/2026). Resta con la sua etichetta,
            perche' un'icona sola qui vorrebbe dire «indovina», ma in tono
            minore: fantasma e testo piccolo. E il «copia link» e' diventato
            un'icona accanto all'attribuzione, sotto la biografia. */}
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto h-7 px-2 text-[11.5px] text-muted-foreground hover:text-foreground"
          onClick={handleRefreshWikipedia}
          disabled={refreshing}
        >
          <RefreshCw className={`size-3 ${refreshing ? 'animate-spin' : ''}`} />
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
          {/* Anagrafica prima della biografia: sono i dati "da scheda", e si
              leggono a colpo d'occhio prima del testo lungo. */}
          {isEditing ? (
            <AuthorFactsForm draft={factsDraft} onChange={setFactsDraft} />
          ) : (
            <AuthorFactsList author={author} />
          )}

          {/* La biografia e' PARTE della pagina, senza riquadro, UNA per
              volta (23/11/2026 sera, scelta di Paolo sul giro del
              pomeriggio). Il tasto-lingua e' una scritta piccola col nome
              della lingua nella lingua stessa; compare solo se le lingue
              con un testo sono almeno due. All'apertura si mostra la prima
              dell'ordine delle Integrazioni che ha una biografia.
              In modifica restano le due aree storiche it/en, com'erano. */}
          {isEditing ? (
            <div className="space-y-2.5">
              {([['it', bioItDraft, setBioItDraft], ['en', bioEnDraft, setBioEnDraft]] as const).map(([lang, draft, setDraft]) => (
                <div key={lang}>
                  <div className="mb-1 text-[12px] font-semibold text-muted-foreground">{autonym(lang)}</div>
                  <textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={() => saveBio(lang === 'it' ? 'bio_it' : 'bio_en', draft)}
                    rows={6}
                    className="w-full resize-none rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
                  />
                </div>
              ))}
            </div>
          ) : (
            <div>
              {linguaCorrente && lingueDisponibili.length > 1 && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button className="mb-1 inline-flex items-center gap-0.5 text-[12px] text-muted-foreground hover:text-foreground">
                      {autonym(linguaCorrente)}
                      <ChevronDown className="size-3" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start">
                    {lingueDisponibili.map((lang) => (
                      <DropdownMenuItem key={lang} onSelect={() => setLinguaBio(lang)}>
                        {autonym(lang)}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
              <p className="text-[13.5px] leading-relaxed whitespace-pre-wrap">
                {linguaCorrente ? testoDi(linguaCorrente) : t('authors.detail.noBio')}
              </p>
              {/* Da dove viene il testo, quando viene da Wikipedia: le
                  biografie sono CC BY-SA 4.0 e l'attribuzione costa una
                  riga. Sparisce da se' per una biografia riscritta a mano
                  e senza link. */}
              {linguaCorrente && fonteDi(linguaCorrente) && (
                <div className="mt-1 text-[11px] text-muted-foreground/80">
                  {t('authors.detail.sourcePrefix')}{' '}
                  <a
                    href={fonteDi(linguaCorrente)!}
                    target="_blank"
                    rel="noreferrer"
                    className="underline decoration-dotted underline-offset-2 hover:text-foreground"
                  >
                    Wikipedia
                  </a>
                </div>
              )}
            </div>
          )}

          {/* Il «copia link» dell'autore: una volta sola, sotto la
              biografia. */}
          {!isEditing && (
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground/80">
              <BottoneCopiaLink
                sorgente={{ tipo: 'autore', nome: name }}
                soloIcona
                variant="ghost"
                className="size-6 text-muted-foreground/80 hover:text-foreground"
              />
            </div>
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
                placeholder={t('authors.detail.wikiLinkPlaceholderAnyLang')}
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
        {/* Una griglia per biblioteca, con un separatore col suo nome.
            **Con un gruppo solo il separatore non c'e'**: chi ha una sola
            biblioteca non deve vedere una sezione che si chiama come l'unica
            cosa che ha. */}
        {gruppi.map((gruppo) => (
          <div key={gruppo.nome} className="flex flex-col gap-2">
            {gruppi.length > 1 && (
              <div className="flex items-center gap-2">
                <span className="text-[11.5px] font-medium text-muted-foreground">{gruppo.nome}</span>
                <span className="h-px flex-1 bg-border" />
                <span className="text-[11px] tabular-nums text-muted-foreground/70">{gruppo.libri.length}</span>
              </div>
            )}
            <div className="grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-3">
              {gruppo.libri.map((book) => {
                const isSelected = selected.has(book.id)
                return (
                  <button
                    key={`${book.library}-${book.id}`}
                    onClick={(e) => handleBookClick(book, e)}
                    aria-pressed={isSelected}
                    className="flex flex-col gap-1 text-left"
                  >
                    {/* `relative` per la spunta d'angolo; l'anello di
                        selezione è un ring e non un bordo perché un bordo
                        sposterebbe di 2px la copertina rispetto alle vicine
                        non selezionate. */}
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
            </div>
          </div>
        ))}
        {books.length === 0 && <p className="text-[12.5px] text-muted-foreground">{t('authors.detail.noBooksFound')}</p>}
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
