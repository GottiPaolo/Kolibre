import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Check, ChevronDown, Globe, LayoutGrid, Library as LibraryIcon, Loader2, Search, Table as TableIcon, Users, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuthors, useAuthorsPagination, useLibraries } from '@/lib/queries'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { fetchScrapeAuthorsStatus, startScrapeMissingAuthors } from '@/lib/authorActions'
import type { AuthorSummary } from '@/types/author'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { useAmbitoAutori, useVistaAutori } from '@/lib/authorsScope'
import { withBackendUrl } from '@/lib/api'
import { cn } from '@/lib/utils'
import { ListError } from '@/components/ListError'
import { AuthorAlphabetIndex, authorInitial } from './AuthorAlphabetIndex'
import { AuthorQuickview } from './AuthorQuickview'
import { conClausola, confrontaAutori, filtraAutori, type CampoAutore } from './authorsQuery'
import { applySortClick, type SortCriterion } from '@/pages/Library/sort'
import { formatDate, genderShort } from './AuthorFacts'
import { toast } from '@/lib/toast'
import { leggiLingua, localeDi, numero, useLingua } from '@/lib/i18n'

// "Ha già dati" = ha una foto — stesso segnale usato dal Vue esistente
// (authorHasScrapedData) per decidere chi saltare nello scrape "solo
// mancanti".
function authorHasData(author: AuthorSummary): boolean {
  return !!author.photo_url
}

/** Ora locale leggibile da un istante ISO in UTC. */
function formatTime(iso: string): string {
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString(localeDi(leggiLingua()), { hour: '2-digit', minute: '2-digit' })
}

// In quale pagina dell'elenco si era.
//
// Lo scorrimento lo ricorda gia' useScrollMemory, ma con l'elenco a pagine
// non basta: tornando indietro si ripartiva sempre dalla pagina 1, e la
// posizione salvata cadeva in mezzo a autori diversi da quelli che si stava
// guardando. Era la regressione introdotta dall'impaginazione — prima
// dell'impaginazione l'elenco era uno solo e il solo scorrimento bastava.
//
// In memoria e non in sessionStorage, stessa scelta (e stesso motivo) di
// useScrollMemory: e' una comodita' del momento, non un dato.
let paginaRicordata = 0

export function AuthorsPage() {
  const { t } = useLingua()
  useSetPageHeader(t('authors.pageTitle'))
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  // Tutti gli autori, o quelli di una biblioteca sola. La scelta resta, e
  // vale anche nella scheda del singolo autore — vedi lib/authorsScope.ts.
  const [ambito, setAmbito] = useAmbitoAutori()
  const { data: libraries = [] } = useLibraries()
  const { data: authors = [], isLoading, isError, refetch } = useAuthors(ambito)
  const bibliotecaScelta = libraries.find((l) => l.folder_name === ambito)

  // Ricordata fra una visita e l'altra: chi lavora in tabella ci lavora sempre,
  // e ritrovare la griglia a ogni apertura è lo stesso clic rifatto ogni volta.
  const [view, setView] = useVistaAutori()
  const [searchText, setSearchText] = useState('')
  // Ordinamento CONCATENATO come nella tabella dei libri: click semplice
  // per il criterio principale, shift+click per aggiungerne uno che decide
  // i pareggi. Stessa funzione, applySortClick, per non avere due
  // comportamenti diversi in due tabelle della stessa applicazione.
  const [sortCriteria, setSortCriteria] = useState<SortCriterion[]>([{ key: 'name', order: 'asc' }])
  // L'autore su cui e' aperto il pannello laterale.
  const [selezionato, setSelezionato] = useState<string | null>(null)

  // Il giro NON gira più qui dentro. Prima era un ciclo `for` in questa
  // funzione: continuava a girare anche cambiando pagina (una closure async
  // non è legata al ciclo di vita di React), ma lo stato spariva col
  // componente, il riepilogo finale atterrava sul vuoto, una ricarica lo
  // uccideva a metà, e la guardia "sto già scaricando" — essendo stato del
  // componente — si azzerava al rimontaggio, permettendo di lanciarne un
  // secondo in parallelo. Ora è un lavoro del server e qui si legge soltanto.
  const { data: job } = useQuery({
    queryKey: ['authors', 'scrape-status'],
    queryFn: fetchScrapeAuthorsStatus,
    // Interroga spesso mentre lavora, una volta ogni tanto quando è fermo:
    // così riaprendo la pagina si ritrova un'operazione già in corso invece
    // di non saperne nulla.
    refetchInterval: (query) => (query.state.data?.running ? 1500 : false),
    refetchOnMount: true,
  })
  const isScrapingAll = job?.running ?? false

  // A fine corsa i dati degli autori sul server sono cambiati (foto, bio):
  // senza questo la griglia resterebbe con i segnaposto finché non si
  // ricarica a mano.
  useEffect(() => {
    if (job && !job.running && job.finished_at) {
      void queryClient.invalidateQueries({ queryKey: ['authors'] })
    }
    // Le dipendenze sono i due CAMPI, non l'oggetto `job`: quella query si
    // ripete ogni 1,5 secondi mentre l'operazione gira, e dipendere da
    // `job` intero significherebbe invalidare la cache degli autori a ogni
    // giro invece che una volta alla fine.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.finished_at, job?.running, queryClient])

  async function startScrape(force: boolean) {
    try {
      const outcome = await startScrapeMissingAuthors(force)
      if (outcome === 'nothing_to_do') {
        toast.info(t('authors.scrape.nothingToDo'))
        return
      }
      toast.success(t('authors.scrape.started'))
      void queryClient.invalidateQueries({ queryKey: ['authors', 'scrape-status'] })
    } catch (e) {
      const status = (e as { status?: number })?.status
      toast.error(
        status === 409
          ? t('authors.scrape.alreadyRunning')
          : t('authors.scrape.startFailed')
      )
    }
  }

  function handleGlobalScrapeClick() {
    const missingCount = authors.filter((a) => !authorHasData(a)).length
    if (missingCount === 0) {
      toast.info(t('authors.scrape.allHaveData'))
      return
    }
    if (window.confirm(t('authors.scrape.confirmMissing', { count: missingCount }))) {
      void startScrape(false)
    }
  }

  function handleGlobalScrapeContextMenu(e: React.MouseEvent) {
    e.preventDefault()
    if (isScrapingAll) return
    if (window.confirm(t('authors.scrape.confirmAll', { count: authors.length }))) {
      void startScrape(true)
    }
  }

  // Non piu' un semplice "contiene" sul nome: c'e' un piccolo linguaggio
  // (genere:, nazionalita:, mestiere:, epoca:, stato:) perche' il pannello
  // laterale rende cliccabili i metadati — vedi authorsQuery.ts.
  const filtered = useMemo(() => filtraAutori(authors, searchText), [authors, searchText])

  const sorted = useMemo(() => {
    if (view !== 'table') return filtered
    return [...filtered].sort((a, b) => confrontaAutori(a, b, sortCriteria))
  }, [filtered, view, sortCriteria])

  // ── Tanti autori ──
  //
  // Misurato con 20.000 autori: 180.219 nodi nel DOM e 12,6 secondi perche'
  // una ricerca si assesti. I dati arrivano in mezzo secondo — il costo e'
  // tutto nel disegnare ventimila schede insieme. Quindi si impagina il
  // DISEGNO, non la richiesta: l'elenco completo resta qui, la ricerca
  // continua a cercare fra tutti, e l'indice A-Z continua a funzionare
  // perche' sa calcolare in che pagina sta la lettera.
  const { data: confPag } = useAuthorsPagination()
  const impaginata =
    confPag?.mode === 'always' || (confPag?.mode !== 'never' && sorted.length > (confPag?.threshold ?? 500))
  const dimPagina = confPag?.page_size ?? 200
  const [pagina, setPagina] = useState(() => paginaRicordata)
  const numPagine = impaginata ? Math.max(1, Math.ceil(sorted.length / dimPagina)) : 1
  const paginaCorrente = Math.min(pagina, numPagine - 1)
  const mostrati = useMemo(
    () => (impaginata ? sorted.slice(paginaCorrente * dimPagina, (paginaCorrente + 1) * dimPagina) : sorted),
    [impaginata, sorted, paginaCorrente, dimPagina]
  )

  // Cambiando ricerca o ordinamento si riparte dalla prima pagina: restare
  // alla pagina 12 di un elenco filtrato non vuol dire niente.
  //
  // Ma NON al montaggio: li' non e' cambiato niente, si sta solo tornando —
  // e azzerare buttava via sia la pagina ricordata sia il salto sull'autore
  // da cui si veniva.
  // Si guarda se i valori sono CAMBIATI, non quante volte l'effetto e'
  // partito: in sviluppo React esegue ogni effetto due volte di fila, quindi
  // una guardia "primo giro" si consuma al primo colpo e il secondo azzera
  // lo stesso — era proprio cosi' che il salto veniva annullato.
  const ultimoFiltroRef = useRef<string | null>(null)
  useEffect(() => {
    const firma = JSON.stringify([searchText, sortCriteria, view])
    if (ultimoFiltroRef.current === firma) return
    const primaVolta = ultimoFiltroRef.current === null
    ultimoFiltroRef.current = firma
    if (!primaVolta) setPagina(0)
  }, [searchText, sortCriteria, view])

  useEffect(() => {
    paginaRicordata = paginaCorrente
  }, [paginaCorrente])

  // Tornando dalla scheda di un autore ci si rimette SU DI LUI, non solo
  // nella pagina giusta: la scheda passa il nome in location.state (vedi il
  // pulsante "Tutti gli Autori" in AuthorDetailPage). Una volta sola per
  // montaggio, e solo quando l'elenco e' arrivato — prima non si saprebbe
  // in che pagina sta.
  const autoreDaRitrovare = (location.state as { autore?: string } | null)?.autore
  const ritrovatoRef = useRef(false)
  useEffect(() => {
    if (ritrovatoRef.current || !autoreDaRitrovare || sorted.length === 0) return
    const posizione = sorted.findIndex((a) => a.name === autoreDaRitrovare)
    if (posizione < 0) return
    ritrovatoRef.current = true
    if (impaginata) setPagina(Math.floor(posizione / dimPagina))
    attendiEScorriAutore(autoreDaRitrovare)
  }, [autoreDaRitrovare, sorted, impaginata, dimPagina])

  // Due numeri veri in cima, non decorativi: quanti autori distinti ci sono
  // e quanti libri coprono.
  const riepilogo = useMemo(() => {
    const libri = authors.reduce((n, a) => n + (a.book_count || 0), 0)
    return { autori: authors.length, libri }
  }, [authors])

  // L'indice A-Z ha senso solo se l'elenco è davvero alfabetico: la griglia
  // lo è sempre (il server restituisce gli autori già ordinati per nome), la
  // tabella solo quando si ordina per nome in senso crescente.
  const alphabetical =
    view === 'grid' || (sortCriteria[0]?.key === 'name' && sortCriteria[0]?.order === 'asc')

  // Prima occorrenza di ogni iniziale: è l'elemento a cui saltare, ed è
  // anche l'unico a cui serve un id nel DOM.
  const firstOfLetter = useMemo(() => {
    const map = new Map<string, string>()
    if (!alphabetical) return map
    for (const a of sorted) {
      const letter = authorInitial(a.name)
      if (!map.has(letter)) map.set(letter, a.name)
    }
    return map
  }, [sorted, alphabetical])

  const availableLetters = useMemo(() => new Set(firstOfLetter.keys()), [firstOfLetter])

  function jumpToLetter(letter: string) {
    const name = firstOfLetter.get(letter)
    if (!name) return
    // Con l'elenco a pagine la lettera puo' stare su un'altra pagina: ci si
    // sposta prima, poi si scorre. Senza, l'indice A-Z indicherebbe
    // posizioni che in questa pagina non esistono — cioe' mentirebbe, che e'
    // esattamente cio' che AuthorAlphabetIndex evita gia' disattivandosi
    // quando l'elenco non e' alfabetico.
    if (impaginata) {
      const posizione = sorted.findIndex((a) => a.name === name)
      if (posizione >= 0) {
        const suPagina = Math.floor(posizione / dimPagina)
        if (suPagina !== paginaCorrente) {
          setPagina(suPagina)
          // Si ASPETTA che l'ancora esista, invece di scommettere su un
          // ritardo: con un timer fisso da 60 ms React non aveva ancora
          // disegnato la pagina nuova, getElementById tornava nullo e lo
          // scorrimento non avveniva — si restava in cima alla pagina
          // nuova, che e' la coda della lettera PRECEDENTE. Premendo M si
          // finiva fra le L, premendo T fra le S.
          attendiEScorri(name)
          return
        }
      }
    }
    // scrollIntoView e non un calcolo di offset: il contenitore che scorre è
    // quello di Layout, non questa pagina, e il browser sa già trovarlo.
    document.getElementById(letterAnchorId(name))?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }

  /** Scorre all'ancora appena compare, per al massimo una trentina di frame. */
  function attendiEScorri(name: string, tentativi = 0) {
    const el = document.getElementById(letterAnchorId(name))
    if (el) {
      el.scrollIntoView({ block: 'start' })
      return
    }
    if (tentativi < 30) requestAnimationFrame(() => attendiEScorri(name, tentativi + 1))
  }

  /** Scorre fino a un autore qualsiasi appena compare nella pagina. */
  function attendiEScorriAutore(name: string, tentativi = 0) {
    const el = document.querySelector(`[data-autore="${CSS.escape(name)}"]`)
    if (el) {
      // 'center' e non 'start': tornando a un autore si vuole vederlo con
      // intorno quelli vicini, non incollato al bordo superiore.
      el.scrollIntoView({ block: 'center' })
      return
    }
    if (tentativi < 30) requestAnimationFrame(() => attendiEScorriAutore(name, tentativi + 1))
  }

  /** id stabile solo per il primo autore di ogni lettera (vedi firstOfLetter). */
  function letterAnchorId(name: string) {
    return `autore-ancora-${encodeURIComponent(name)}`
  }
  function anchorPropsFor(name: string) {
    // Prima occorrenza della lettera NELLA PAGINA MOSTRATA: impaginando, il
    // primo autore in assoluto di una lettera puo' non essere qui, e
    // l'ancora finirebbe su un elemento che non esiste.
    const primoQui = mostrati.find((a) => authorInitial(a.name) === authorInitial(name))
    // `data-autore` su TUTTI: l'id serve all'indice A-Z (una sola ancora per
    // lettera), questo serve a ritrovare l'autore da cui si e' tornati, che
    // puo' essere qualunque.
    return primoQui?.name === name
      ? { id: letterAnchorId(name), 'data-autore': name }
      : { 'data-autore': name }
  }

  // L'autore mostrato nel pannello, e la sua posizione nella pagina: serve
  // alle frecce, che devono muoversi nell'ordine che si vede.
  const autoreSelezionato = useMemo(
    () => mostrati.find((a) => a.name === selezionato) ?? null,
    [mostrati, selezionato]
  )

  // Frecce su/giu' per scorrere l'elenco, Invio per aprire la scheda,
  // Esc per chiudere il pannello. Attive solo nella vista a tabella e solo
  // quando non si sta scrivendo nella casella di ricerca.
  useEffect(() => {
    if (view !== 'table') return
    function onKey(e: KeyboardEvent) {
      const dentroUnCampo = (e.target as HTMLElement)?.tagName === 'INPUT'
      if (e.key === 'Escape') {
        setSelezionato(null)
        return
      }
      if (dentroUnCampo || mostrati.length === 0) return
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Enter') return
      e.preventDefault()
      const i = mostrati.findIndex((a) => a.name === selezionato)
      if (e.key === 'Enter') {
        if (i >= 0) openAuthor(mostrati[i].name)
        return
      }
      const passo = e.key === 'ArrowDown' ? 1 : -1
      // Partendo da nessuna selezione, la freccia giu' prende il primo e la
      // freccia su l'ultimo: e' quello che ci si aspetta da un elenco.
      const prossimo = i < 0 ? (passo > 0 ? 0 : mostrati.length - 1) : Math.min(mostrati.length - 1, Math.max(0, i + passo))
      setSelezionato(mostrati[prossimo].name)
      document.querySelector(`[data-autore="${CSS.escape(mostrati[prossimo].name)}"]`)
        ?.scrollIntoView({ block: 'nearest' })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // `openAuthor` è una funzione del corpo del componente, quindi nuova a
    // ogni render: metterla qui rimonterebbe l'ascoltatore di tastiera a
    // ogni render. Non serve, perché le tre dipendenze qui sotto cambiano
    // insieme a lei ogni volta che il suo contenuto conta davvero.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, mostrati, selezionato])

  // Cliccando un metadato nel pannello la clausola entra nella ricerca —
  // e ricliccandolo esce, vedi conClausola.
  function filtraPer(campo: CampoAutore, valore: string) {
    setSearchText((q) => conClausola(q, campo, valore))
  }

  // Click semplice: criterio principale. Shift+click: si aggiunge come
  // secondo, a decidere i pareggi. Stessa funzione della tabella dei libri.
  function setSort(key: string, shiftKey: boolean) {
    setSortCriteria((prev) => applySortClick(prev, key, shiftKey))
  }

  function openAuthor(name: string) {
    navigate(`/autori/${encodeURIComponent(name)}`)
  }

  return (
    // Nella vista a TABELLA la pagina non scorre: scorre la tabella, dentro
    // il suo contenitore. Senza, arrivando in fondo all'elenco il pannello
    // dell'autore restava in cima e spariva dallo schermo — cioe' proprio
    // mentre lo si stava usando. Stesso schema della pagina Libreria.
    // La griglia continua a scorrere come tutta la pagina: li' non c'e' un
    // pannello da tenere fermo, e l'indice A-Z si aspetta lo scorrimento
    // normale.
    <div
      className={cn(
        'flex flex-col gap-3',
        view === 'table' && 'h-[calc(100vh-72px)] md:h-[calc(100vh-96px)]'
      )}
    >
      {/* Due numeri veri, non decorativi. Il secondo conta i libri COPERTI
          dagli autori mostrati, che su una biblioteca con co-autori non e' lo
          stesso numero dei libri in libreria — per quello c'e' la Libreria. */}
      {authors.length > 0 && (
        <p className="text-[12px] text-muted-foreground">
          <strong className="text-foreground">{numero(riepilogo.autori)}</strong>{' '}
          {t('authors.summary.distinctCount', { count: riepilogo.autori, n: riepilogo.autori })}
          {bibliotecaScelta && <> {t('authors.summary.inLibrary', { library: bibliotecaScelta.name })}</>}
          {riepilogo.libri > 0 && (
            <> · {numero(riepilogo.libri)} {t('authors.summary.bookCount', { count: riepilogo.libri, n: riepilogo.libri })}</>
          )}
          {sorted.length !== authors.length && (
            <> · {numero(sorted.length)} {t('authors.summary.matchingSearch', { count: sorted.length, n: sorted.length })}</>
          )}
        </p>
      )}

      <div className="flex items-center gap-2">
        {/* Solo con piu' di una biblioteca: con una sola, "tutti gli autori"
            e "gli autori di quella" sono la stessa cosa e il menu sarebbe
            una scelta finta. */}
        {libraries.length > 1 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <LibraryIcon className="size-3.5" />
                {bibliotecaScelta ? bibliotecaScelta.name : t('authors.scope.all')}
                <ChevronDown className="size-3.5 opacity-60" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onSelect={() => setAmbito(null)}>{t('authors.scope.all')}</DropdownMenuItem>
              {libraries.map((lib) => (
                <DropdownMenuItem key={lib.id} onSelect={() => setAmbito(lib.folder_name)}>
                  {t('authors.scope.ofLibrary', { library: lib.name })}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        <div className="relative max-w-[280px] flex-1">
          <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground/70" />
          <input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder={t('authors.search.placeholder')}
            className="w-full rounded-md border border-border bg-card py-1.5 pr-2.5 pl-7 text-[13px] outline-none focus:border-primary"
          />
        </div>

        <Button
          variant="outline"
          size="icon-sm"
          disabled={isScrapingAll}
          onClick={handleGlobalScrapeClick}
          onContextMenu={handleGlobalScrapeContextMenu}
          title={t('authors.scrape.buttonTitle')}
        >
          {isScrapingAll ? <Loader2 className="size-3.5 animate-spin" /> : <Globe className="size-3.5" />}
        </Button>

        <div className="ml-auto flex gap-1">
          <Button variant={view === 'grid' ? 'secondary' : 'ghost'} size="icon-sm" onClick={() => setView('grid')}>
            <LayoutGrid className="size-3.5" />
          </Button>
          <Button variant={view === 'table' ? 'secondary' : 'ghost'} size="icon-sm" onClick={() => setView('table')}>
            <TableIcon className="size-3.5" />
          </Button>
        </div>
      </div>

      {isLoading && <p className="text-muted-foreground">{t('common.loading')}</p>}

      {/* Due colonne: l'elenco e, a destra, l'indice alfabetico. L'indice
          si monta solo quando l'elenco è davvero in ordine alfabetico —
          vedi AuthorAlphabetIndex per il perché. */}
      {/* flex-1 + min-h-0 su ENTRAMBI: senza, questa riga resta alta quanto
          lo schermo ma NON limita i figli, e la tabella dentro cresce fino a
          seimila pixel traboccando in silenzio — il pannello dell'autore si
          allungava con lei invece di restare fermo. */}
      <div className="flex min-h-0 flex-1 gap-2">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {!isLoading && view === 'grid' && (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-4">
          {mostrati.map((author) => {
            const status = job?.current === author.name ? 'scraping' : undefined
            return (
              <button
                key={author.name}
                {...anchorPropsFor(author.name)}
                onClick={() => openAuthor(author.name)}
                className="flex flex-col items-center gap-1.5 text-center"
              >
                <div className="relative aspect-square w-full overflow-hidden rounded-full border border-border bg-muted">
                  {author.photo_url ? (
                    <img src={withBackendUrl(author.photo_url)} alt={author.name} loading="lazy" className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-muted-foreground">
                      <Users className="size-6" />
                    </div>
                  )}
                  {status && (
                    <div className="absolute inset-0 flex items-center justify-center bg-black/50 text-white">
                      {status === 'scraping' ? (
                        <Loader2 className="size-5 animate-spin" />
                      ) : status === 'failed' ? (
                        <X className="size-5 text-destructive" />
                      ) : (
                        <Check className="size-5" />
                      )}
                    </div>
                  )}
                </div>
                <span className="line-clamp-2 text-[12.5px] font-medium">{author.name}</span>
              </button>
            )
          })}
        </div>
      )}

      {!isLoading && view === 'table' && (
        <div className="flex min-h-0 flex-1 gap-0 overflow-hidden rounded-lg border border-border">
        <div className="min-w-0 flex-1 overflow-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-border bg-muted">
                {/* Il numero di riga, come nella tabella dei libri: serve a
                    dire "il quarantesimo" senza doverli contare, e a
                    ritrovare il punto dopo aver guardato altrove. Non e'
                    ordinabile perche' non e' un dato dell'autore: e' la sua
                    posizione nell'ordinamento corrente. */}
                <th className="w-9 border-r border-border px-2 py-2 text-right text-[11.5px] font-semibold text-muted-foreground">#</th>
                <Th label={t('authors.field.name')} sortKey="name" criteria={sortCriteria} onClick={setSort} t={t} />
                <Th label={t('authors.field.bookCount')} sortKey="book_count" criteria={sortCriteria} onClick={setSort} t={t} />
                <Th label={t('authors.field.pages')} sortKey="total_pages" criteria={sortCriteria} onClick={setSort} t={t} />
                <Th label={t('authors.field.gender')} sortKey="gender" criteria={sortCriteria} onClick={setSort} t={t} />
                <Th label={t('authors.field.nationality')} sortKey="nationality" criteria={sortCriteria} onClick={setSort} t={t} />
                <Th label={t('authors.field.occupation')} sortKey="occupations" criteria={sortCriteria} onClick={setSort} t={t} />
                <Th label={t('authors.field.birth')} sortKey="birth_date" criteria={sortCriteria} onClick={setSort} t={t} />
                <Th label={t('authors.field.death')} sortKey="death_date" criteria={sortCriteria} onClick={setSort} t={t} />
                {isScrapingAll && (
                  <th className="border-r border-border px-3 py-2 text-left text-[11.5px] font-semibold text-muted-foreground">{t('authors.field.scraperColumn')}</th>
                )}
              </tr>
            </thead>
            <tbody>
              {mostrati.map((author, riga) => (
                <tr
                  key={author.name}
                  {...anchorPropsFor(author.name)}
                  // Un click apre il PANNELLO, due aprono la scheda: cosi'
                  // si puo' scorrere l'elenco confrontando gli autori senza
                  // perdere il posto, che era il difetto di prima.
                  onClick={() => setSelezionato(author.name)}
                  onDoubleClick={() => openAuthor(author.name)}
                  className={cn(
                    'cursor-pointer border-b border-border/60 transition-colors hover:bg-accent/60',
                    // Stessa zebratura della tabella dei libri, stessa
                    // intensita': le due tabelle si guardano allo stesso modo.
                    riga % 2 === 1 && 'bg-muted/25',
                    selezionato === author.name && 'bg-primary/10 hover:bg-primary/10'
                  )}
                >
                  <td className="border-r border-border/40 px-2 py-1.5 text-right text-[10px] tabular-nums text-muted-foreground/60 select-none">
                    {riga + 1}
                  </td>
                  <td className="px-3 py-1.5">{author.name}</td>
                  <td className="px-3 py-1.5">{author.book_count}</td>
                  <td className="px-3 py-1.5">{numero(author.total_pages)}</td>
                  {/* M/F invece di "maschio"/"femmina": in una colonna di
                      tabella una lettera basta. Gli altri valori restano per
                      esteso — vedi genderShort. */}
                  <td className="px-3 py-1.5 text-muted-foreground" title={author.gender ?? undefined}>
                    {genderShort(author.gender, t) ?? '—'}
                  </td>
                  {/* Solo la prima cittadinanza in tabella, il resto nel tooltip:
                      Emma Goldman ne ha cinque e la colonna diventerebbe illeggibile. */}
                  <td className="px-3 py-1.5 text-muted-foreground" title={author.nationality.join(' · ')}>
                    {author.nationality[0] ?? '—'}
                    {author.nationality.length > 1 && (
                      <span className="text-muted-foreground/60"> +{author.nationality.length - 1}</span>
                    )}
                  </td>
                  {/* Come per la nazionalita': solo il primo mestiere in
                      tabella, gli altri nel tooltip. */}
                  <td className="px-3 py-1.5 text-muted-foreground" title={author.occupations.join(' · ')}>
                    {author.occupations[0] ?? '—'}
                    {author.occupations.length > 1 && (
                      <span className="text-muted-foreground/60"> +{author.occupations.length - 1}</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{formatDate(author.birth_date) ?? '—'}</td>
                  {/* Un autore nato e non morto e' vivo, non un dato mancante:
                      merita una parola, non un trattino uguale a "non lo sappiamo". */}
                  <td className="px-3 py-1.5 tabular-nums text-muted-foreground">
                    {author.death_date ? formatDate(author.death_date) : author.birth_date ? t('authors.field.living') : '—'}
                  </td>
                  {isScrapingAll && (
                    <td className="px-3 py-1.5 text-center text-[11.5px] font-semibold">
                      {job?.current === author.name && <span className="text-primary">{t('authors.scrape.inProgress')}</span>}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {/* Il pannello dell'autore selezionato. Compare solo quando c'e' una
            selezione: una colonna vuota accanto alla tabella toglierebbe
            spazio senza dare niente. */}
        {autoreSelezionato && (
          <AuthorQuickview
            author={autoreSelezionato}
            query={searchText}
            onFiltra={filtraPer}
            onApri={openAuthor}
            onChiudi={() => setSelezionato(null)}
          />
        )}
        </div>
      )}

      {/* Comandi di pagina: solo quando c'e' davvero piu' di una pagina.
          L'indice A-Z qui accanto sa cambiare pagina da solo, vedi
          jumpToLetter. */}
      {impaginata && numPagine > 1 && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-1.5 text-[11.5px]">
          <Button variant="outline" size="sm" disabled={paginaCorrente === 0} onClick={() => setPagina((p) => Math.max(0, p - 1))}>
            {t('common.previous')}
          </Button>
          <span className="tabular-nums text-muted-foreground">
            {t('authors.pagination.status', {
              from: numero(paginaCorrente * dimPagina + 1),
              to: numero(Math.min((paginaCorrente + 1) * dimPagina, sorted.length)),
              total: numero(sorted.length),
              page: paginaCorrente + 1,
              numPages: numero(numPagine),
            })}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={paginaCorrente + 1 >= numPagine}
            onClick={() => setPagina((p) => p + 1)}
          >
            {t('common.next')}
          </Button>
          <span className="text-muted-foreground">{t('authors.pagination.searchAcrossAll')}</span>
        </div>
      )}
        </div>

        {alphabetical && availableLetters.size > 1 && (
          <AuthorAlphabetIndex available={availableLetters} onJump={jumpToLetter} />
        )}
      </div>

      {/* Avanzamento e riepilogo vengono dal server, quindi si vedono anche
          tornando su questa pagina a operazione già iniziata — e restano leggibili
          dopo una ricarica. */}
      {job?.running && (
        <p className="text-[13px] text-muted-foreground">
          {t('authors.scrape.progress', { processed: job.processed, total: job.total })}
          {job.current ? ` — ${t('authors.scrape.inProgressSuffix', { name: job.current })}` : null}
          {job.failed.length > 0 ? ` · ${t('authors.scrape.failedSuffix', { count: job.failed.length, n: job.failed.length })}` : null}
        </p>
      )}

      {/* A giro finito si distinguono quattro esiti, perché richiedono quattro
          reazioni diverse: "completo" non va più toccato, "senza foto" e "senza
          voce" non vanno ritentati a mano (ci pensa il server, fra settimane),
          e "fermato dal limite" è l'unico che merita di riprovare — e dice
          quando. Prima erano tutti indistinguibili. */}
      {!job?.running && job?.finished_at && job.total > 0 && (
        <div className="space-y-1 text-[13px] text-muted-foreground">
          <p>
            {t('authors.scrape.finished', {
              completed: job.total - job.failed.length - job.not_found.length - job.no_image.length,
            })}
            {job.no_image.length > 0 ? `, ${t('authors.scrape.noImageSuffix', { count: job.no_image.length, n: job.no_image.length })}` : ''}
            {job.not_found.length > 0 ? `, ${t('authors.scrape.notFoundSuffix', { count: job.not_found.length, n: job.not_found.length })}` : ''}
            {job.failed.length > 0 ? `, ${t('authors.scrape.failedSuffix', { count: job.failed.length, n: job.failed.length })}` : ''}
            {job.skipped > 0 ? ` · ${t('authors.scrape.skippedSuffix', { count: job.skipped, n: job.skipped })}` : ''}
          </p>
          {job.stopped_early && (
            <p className="text-destructive">
              {t('authors.scrape.stoppedEarly')}
              {job.blocked_until ? `, ${t('authors.scrape.blockedUntilSuffix', { time: formatTime(job.blocked_until) })}` : ''}.
            </p>
          )}
          {job.no_image.length > 0 && (
            <p className="text-[12px]">
              {t('authors.scrape.noImageList', { names: job.no_image.slice(0, 6).join(', ') })}
              {job.no_image.length > 6 ? ` ${t('authors.scrape.noImageMore', { n: job.no_image.length - 6 })}` : ''}. {t('authors.scrape.noImageHint')}
            </p>
          )}
        </div>
      )}

      {!isLoading && isError && <ListError what={t('authors.error.subject')} onRetry={() => void refetch()} />}
      {!isLoading && !isError && sorted.length === 0 && (
        <p className="text-muted-foreground">{t('authors.empty.noMatch')}</p>
      )}
    </div>
  )
}

function Th({
  label,
  sortKey,
  criteria,
  onClick,
  t,
}: {
  label: string
  sortKey: string
  criteria: SortCriterion[]
  onClick: (key: string, shiftKey: boolean) => void
  t: (chiave: string) => string
}) {
  const posizione = criteria.findIndex((c) => c.key === sortKey)
  const criterio = posizione >= 0 ? criteria[posizione] : null
  return (
    <th
      onClick={(e) => onClick(sortKey, e.shiftKey)}
      title={t('authors.table.sortHint')}
      className="cursor-pointer border-r border-border px-3 py-2 text-left text-[11.5px] font-semibold text-muted-foreground select-none"
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {criterio?.order === 'asc' && <ArrowUp className="size-3" />}
        {criterio?.order === 'desc' && <ArrowDown className="size-3" />}
        {/* Il numerino compare solo quando i criteri sono piu' d'uno: su un
            ordinamento semplice sarebbe un "1" senza significato. */}
        {posizione >= 0 && criteria.length > 1 && (
          <span className="text-[9.5px] text-muted-foreground/70 tabular-nums">{posizione + 1}</span>
        )}
      </span>
    </th>
  )
}
