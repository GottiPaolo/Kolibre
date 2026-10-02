import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { FileSearch, Filter, LayoutGrid, Library as LibraryIcon, List, Search, Table as TableIcon, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useBooks, useBooksPage, useCustomColumns, useLibraries, useLibraryPagination, useReadingProgress, useValoriDeiCampi } from '@/lib/queries'
import { serverSortKey, sortNonSupportato } from './serverPaging'
import { useDevices } from '@/lib/deviceQueries'
import { deviceBookColumnState, type DeviceBookColumnState } from '@/lib/deviceFormat'
import { useIsDesktop } from '@/lib/useMediaQuery'
import { buildDeviceFieldDefs, buildFieldDefs, buildProgressFieldDef, cycleBrowserFilter, matchesQuery } from '@/lib/libraryQuery'
import {
  DEFAULT_VISIBLE_COLS,
  FIXED_COLUMNS,
  fixedColumnLabels,
  loadColumnLayout,
  loadQuickviewWidth,
  loadViewMode,
  pruneStaleVisibleColumns,
  saveColumnLayout,
  saveQuickviewWidth,
  saveViewMode,
  QUICKVIEW_MAX_WIDTH,
  QUICKVIEW_MIN_WIDTH,
  type LibraryViewMode,
} from '@/lib/libraryColumns'
import { applySortClick, compareBooks, type SortCriterion } from './sort'
import { useRowSelection } from '@/lib/useRowSelection'
import { LibraryTable, type SelectModifiers } from './LibraryTable'
import { LibraryCards } from './LibraryCards'
import { QuickviewPanel } from './QuickviewPanel'
import { NavigatorDrawer } from './NavigatorDrawer'
import { FulltextSearchDialog } from './FulltextSearchDialog'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { useSettingsDialog } from '@/lib/settingsDialogContext'
import type { Book } from '@/types/library'
import { ListError } from '@/components/ListError'
import { numero, useLingua } from '@/lib/i18n'

// Stesso pattern di BookDetail/useBookLookup.ts (state di history, non
// sessionStorage): la riga selezionata viene "taggata" sull'entry corrente
// prima di navigare verso Autore (vedi handleAuthorClick), così il tasto
// indietro del browser la ritrova qui in location.state — LibraryPage viene
// smontata/rimontata ad ogni cambio rotta e perderebbe altrimenti la
// selezione (un semplice useState locale).
interface LibraryLocationState {
  selectedBookId?: number | null
  /** Da quale libreria si stava guardando quel libro. */
  libraryFolder?: string | null
}

export function LibraryPage() {
  const { t } = useLingua()
  const navigate = useNavigate()
  const location = useLocation()
  const { openSettings } = useSettingsDialog()
  const { data: libraries } = useLibraries()
  // Tornando dalla scheda di un libro si riprende dalla libreria da cui
  // quel libro veniva, non dalla prima dell'elenco.
  const [activeLibraryId, setActiveLibraryId] = useState<number | null>(null)
  const cartellaDiRitorno = (location.state as LibraryLocationState | null)?.libraryFolder ?? null
  const activeLibrary = useMemo(
    () =>
      libraries?.find((l) => l.id === activeLibraryId) ??
      (cartellaDiRitorno ? libraries?.find((l) => l.folder_name === cartellaDiRitorno) : undefined) ??
      libraries?.[0],
    [libraries, activeLibraryId, cartellaDiRitorno]
  )

  // Sotto "md" la tabella (colonne fisse in pixel, pensata per lo scroll
  // orizzontale da mouse) lascia il posto a LibraryCards, un elenco a riga
  // singola pensato per lo scroll verticale col dito — vedi LibraryCards.tsx.
  const isDesktop = useIsDesktop()

  // Scelta manuale tabella/griglia, valida solo su desktop (sotto "md"
  // LibraryCards resta comunque forzata, vedi il rendering più sotto).
  const [viewMode, setViewModeState] = useState<LibraryViewMode>(() => loadViewMode())
  function setViewMode(mode: LibraryViewMode) {
    saveViewMode(mode)
    setViewModeState(mode)
  }

  const { data: customColumns = [] } = useCustomColumns(activeLibrary?.folder_name)


  const { data: readingProgress = [] } = useReadingProgress(activeLibrary?.folder_name)
  const progressByBookId = useMemo(
    () => Object.fromEntries(readingProgress.map((p) => [p.calibre_book_id, Math.round(p.percentage * 100)])),
    [readingProgress]
  )

  // Colonna dinamica per dispositivo ("Su: <nome>") — porting delle
  // colonne device-* del Vue esistente. deviceStatusByBookId è pre-calcolata
  // qui (una volta per libreria attiva) invece che dentro ogni cella, così
  // LibraryTable/specialCell restano puri lookup O(1).
  const { data: devices = [] } = useDevices()
  const deviceColumns = useMemo(
    () => devices.map((d) => ({ id: `device-${d.id}`, label: t('library.field.onDevice', { name: d.name }) })),
    [devices, t]
  )
  const deviceStatusByBookId = useMemo(() => {
    const map: Record<number, Record<number, DeviceBookColumnState>> = {}
    if (!activeLibrary) return map
    for (const device of devices) {
      for (const row of device.books) {
        if (row.library !== activeLibrary.folder_name) continue
        ;(map[row.calibre_book_id] ??= {})[device.id] = deviceBookColumnState(row.status)
      }
    }
    return map
  }, [devices, activeLibrary])

  // I campi su cui il Navigatore Biblioteca sa filtrare. Oltre a quelli che
  // stanno dentro il libro, ci sono le due colonne che vivono altrove: la
  // presenza sui dispositivi e l'avanzamento di lettura. Erano le uniche
  // colonne visibili in tabella ma non filtrabili.
  const fieldDefs = useMemo(
    () => [
      ...buildFieldDefs(customColumns, t),
      ...buildDeviceFieldDefs(devices, deviceStatusByBookId, t),
      buildProgressFieldDef(progressByBookId, t),
    ],
    [customColumns, devices, deviceStatusByBookId, progressByBookId, t]
  )

  useSetPageHeader(activeLibrary?.name ?? '')

  const [searchText, setSearchText] = useState('')
  const [showNavigator, setShowNavigator] = useState(false)
  const [showFulltextSearch, setShowFulltextSearch] = useState(false)
  const [expandedFields, setExpandedFields] = useState<Set<string>>(new Set())

  // Query preimpostata da un'altra pagina (es. "Libri simili" dal menu
  // contestuale, o "Vai all'Autore") — one-shot: applicata e poi rimossa
  // dall'URL, così un refresh non la ripropone all'infinito.
  const [searchParams, setSearchParams] = useSearchParams()
  useEffect(() => {
    const q = searchParams.get('q')
    if (q !== null) {
      setSearchText(q)
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.delete('q')
          return next
        },
        // `state` va ripassato: setSearchParams sostituisce l'entry di
        // history, e senza questo si porta via anche lo stato. Chi arriva
        // qui da una statistica manda INSIEME la query e la biblioteca in
        // cui cercarla (vedi filterByFieldValue): perdendo la seconda si
        // finiva a filtrare "tags:=romanzo" nella biblioteca sbagliata, e
        // il risultato era zero libri invece dei centoquaranta appena
        // visti nel grafico.
        { replace: true, state: location.state }
      )
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  const [selectedBookId, setSelectedBookId] = useState<number | null>(
    () => (location.state as LibraryLocationState | null)?.selectedBookId ?? null
  )
  // Consumata una sola volta, al primo giro utile dell'effect sotto: se il
  // mount porta già una selezione ripristinata da location.state, quel giro
  // non deve sovrascriverla con "primo libro della libreria" — i cambi di
  // libreria successivi (voluti dall'utente) continuano invece a resettare
  // normalmente sul primo libro.
  const restoredSelectionRef = useRef(selectedBookId !== null)
  const prevLibraryIdRef = useRef<number | null>(null)

  const [sortCriteria, setSortCriteria] = useState<SortCriterion[]>([{ key: 'date_added', order: 'desc' }])

  // ── Biblioteche grandi ──
  // Oltre la soglia impostata (Impostazioni ▸ Sistema) la pagina smette di
  // scaricare l'intera biblioteca e ne chiede una pagina per volta: su
  // 100.000 libri l'elenco completo costa 9,4 secondi e 66 MB. Sotto la
  // soglia non cambia rigorosamente nulla, ed e' il caso di tutti.
  const { data: infoPaginazione } = useLibraryPagination(activeLibrary?.folder_name)
  const impaginata = infoPaginazione?.paginated ?? false
  const [pagina, setPagina] = useState(0)
  const [ricercaServer, setRicercaServer] = useState('')
  const dimPagina = infoPaginazione?.page_size ?? 200

  const { data: tutti = [], isLoading: caricaTutti, isError: erroreTutti, refetch } =
    useBooks(activeLibrary?.folder_name, !impaginata)
  const ordineServer = serverSortKey(sortCriteria)
  const paginaQuery = useBooksPage(
    activeLibrary?.folder_name,
    { offset: pagina * dimPagina, limit: dimPagina, sort: ordineServer.sort, order: ordineServer.order, q: ricercaServer },
    impaginata
  )
  // Memoizzato e non calcolato al volo: `?? []` costruisce un array nuovo a
  // ogni render finché la pagina non è arrivata, e quell'identità nuova
  // faceva ricalcolare a vuoto i due useMemo qui sotto a ogni render.
  const books = useMemo(
    () => (impaginata ? (paginaQuery.data?.items ?? []) : tutti),
    [impaginata, paginaQuery.data, tutti]
  )
  const isLoading = impaginata ? paginaQuery.isLoading : caricaTutti
  const isError = impaginata ? paginaQuery.isError : erroreTutti
  const totaleFiltrato = impaginata ? (paginaQuery.data?.total ?? 0) : null

  // I valori del Navigatore contati da SQLite sull'intera biblioteca, non
  // sui libri caricati. Si chiedono solo quando la biblioteca è impaginata e
  // il Navigatore è aperto: sotto la soglia i libri ci sono già tutti in
  // memoria e una richiesta in più non aggiungerebbe niente.
  const { data: valoriCampi } = useValoriDeiCampi(
    activeLibrary?.folder_name,
    ricercaServer,
    impaginata && showNavigator
  )
  const selectedBook = books.find((b) => b.id === selectedBookId) ?? null

  // Ordine+visibilità colonne per libreria, persistiti — stessa chiave
  // localStorage del Vue esistente (kolibre_column_layout_v1) così il
  // layout non "salta" cambiando app durante la coesistenza.
  const [columnLayout, setColumnLayout] = useState<Record<string, string[]>>(() => loadColumnLayout())
  useEffect(() => saveColumnLayout(columnLayout), [columnLayout])

  const allColumns = useMemo(() => {
    const labels = fixedColumnLabels(t)
    return [
      ...FIXED_COLUMNS.map((id) => ({ id, label: labels[id] })),
      ...customColumns.map((c) => ({ id: `#${c.label}`, label: c.name })),
      ...deviceColumns,
    ]
  }, [customColumns, deviceColumns, t])
  const validColumnIds = useMemo(() => new Set(allColumns.map((c) => c.id)), [allColumns])

  const libKey = activeLibrary ? String(activeLibrary.id) : null
  const visibleColumnIds = useMemo(() => {
    if (!libKey) return DEFAULT_VISIBLE_COLS
    const saved = columnLayout[libKey] ?? DEFAULT_VISIBLE_COLS
    return pruneStaleVisibleColumns(saved, validColumnIds)
  }, [columnLayout, libKey, validColumnIds])
  const orderedColumns = useMemo(
    () => visibleColumnIds.map((id) => allColumns.find((c) => c.id === id)).filter((c): c is { id: string; label: string } => !!c),
    [visibleColumnIds, allColumns]
  )

  function setVisibleColumnIds(next: string[]) {
    if (!libKey) return
    setColumnLayout((prev) => ({ ...prev, [libKey]: next }))
  }
  function toggleColumn(colId: string) {
    if (colId === 'title') return
    const next = visibleColumnIds.includes(colId) ? visibleColumnIds.filter((id) => id !== colId) : [...visibleColumnIds, colId]
    setVisibleColumnIds(next)
  }

  // Larghezze colonna: deliberatamente solo in-memoria, come nel Vue
  // esistente — non fanno parte della superficie di impostazioni
  // persistite di questa app.
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({})

  const [quickviewWidth, setQuickviewWidthState] = useState(() => loadQuickviewWidth())
  function handleQuickviewResizeStart(e: React.MouseEvent) {
    const startX = e.clientX
    const startWidth = quickviewWidth
    const onMove = (moveEvt: MouseEvent) => {
      const delta = startX - moveEvt.clientX
      setQuickviewWidthState(Math.min(QUICKVIEW_MAX_WIDTH, Math.max(QUICKVIEW_MIN_WIDTH, startWidth + delta)))
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      setQuickviewWidthState((w) => {
        saveQuickviewWidth(w)
        return w
      })
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  // In modalita' impaginata filtro e ordinamento li ha gia' fatti SQLite:
  // rifarli qui riordinerebbe la sola pagina corrente, che e' peggio che
  // non ordinare — sembrerebbe ordinato e non lo sarebbe.
  const filteredBooks = useMemo(
    () => (impaginata ? books : books.filter((b) => matchesQuery(searchText, b, fieldDefs))),
    [impaginata, books, searchText, fieldDefs]
  )
  const sortedBooks = useMemo(
    () =>
      impaginata
        ? filteredBooks
        : [...filteredBooks].sort((a, b) => compareBooks(a, b, sortCriteria, progressByBookId, deviceStatusByBookId)),
    [impaginata, filteredBooks, sortCriteria, progressByBookId, deviceStatusByBookId]
  )

  // La casella di ricerca pilota il server, con una pausa: una query per
  // lettera digitata su una biblioteca grande e' un giro di troppo.
  useEffect(() => {
    if (!impaginata) return
    const id = window.setTimeout(() => {
      setRicercaServer(searchText)
      setPagina(0)
    }, 350)
    return () => window.clearTimeout(id)
  }, [searchText, impaginata])

  // Cambiare ordinamento o biblioteca riporta alla prima pagina: restare
  // alla pagina 40 di un elenco riordinato non vuol dire niente.
  useEffect(() => {
    setPagina(0)
  }, [ordineServer.sort, ordineServer.order, activeLibrary?.folder_name])

  function handleSortClick(colId: string, shiftKey: boolean) {
    setSortCriteria((prev) => applySortClick(prev, colId, shiftKey))
  }

  function handleAuthorClick(name: string) {
    // Aggiorna l'entry corrente della history con la selezione attuale prima
    // di spostarsi su Autore, così il tasto indietro del browser la
    // ritrova in location.state (vedi LibraryLocationState sopra).
    navigate(location.pathname + location.search, { replace: true, state: { selectedBookId } })
    navigate(`/autori/${encodeURIComponent(name)}`)
  }

  function toggleExpandField(key: string) {
    setExpandedFields((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // Selezione multipla (Cmd/Shift-click) per le azioni bulk del menu
  // contestuale (elimina/invia-rimuovi dispositivo/modifica metadati in
  // blocco, vedi BulkBookContextMenu). `selectedBookId`
  // sopra resta la riga "a fuoco" (editing inline, navigazione a frecce,
  // Quickview) — con una multiselezione attiva è solo l'ultima toccata,
  // mentre `selected` qui contiene TUTTI gli id evidenziati.
  const { selected: selectedIds, toggle: toggleSelection, selectOnly, clear: clearSelection } = useRowSelection(
    sortedBooks.map((b) => b.id)
  )

  useEffect(() => {
    if (activeLibrary && activeLibrary.id !== prevLibraryIdRef.current && books.length > 0) {
      // All'apertura (nessuna selezione da ripristinare da
      // location.state) non deve essere selezionato nessun libro né aperto
      // nessun pannello laterale — prima qui si selezionava books[0], che
      // essendo l'array non ordinato (non sortedBooks) risultava quasi sempre
      // il libro più vecchio invece che una scelta sensata.
      if (restoredSelectionRef.current && selectedBookId != null) {
        selectOnly(selectedBookId)
      } else {
        // Cambiando biblioteca la selezione va svuotata, non lasciata lì: gli
        // id Calibre ricominciano da 1 in ogni biblioteca, quindi gli STESSI
        // numeri esistono anche nell'altra. Tre libri scelti in una
        // biblioteca risultavano evidenziati — e raccolti da
        // selectedBooksForMenu — su tre libri mai visti dell'altra, pronti
        // per «Elimina selezionati (3)». Anche il libro a fuoco va lasciato
        // andare, altrimenti il pannello laterale si apre su un altro libro.
        clearSelection()
        setSelectedBookId(null)
      }
      restoredSelectionRef.current = false
      prevLibraryIdRef.current = activeLibrary.id
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeLibrary, books])

  // Non un useCallback a deps vuote come prima: selectOnly/toggleSelection
  // non sono perfettamente stabili tra un render e l'altro (vedi
  // useRowSelection), quindi la garanzia "referenza stabile per LibraryRow
  // memoizzata" citata più sotto vale solo in parte già oggi (handleRowSelect
  // in LibraryTable non è a sua volta memoizzato) — non un problema nuovo
  // introdotto qui, la virtualizzazione limita comunque il costo alle sole
  // righe visibili.
  const selectBook = useCallback(
    (book: Book, modifiers?: SelectModifiers) => {
      setSelectedBookId(book.id)
      if (modifiers && (modifiers.shiftKey || modifiers.metaKey || modifiers.ctrlKey)) {
        toggleSelection(book.id, { shiftKey: modifiers.shiftKey })
      } else {
        selectOnly(book.id)
      }
    },
    [toggleSelection, selectOnly]
  )

  const closeQuickview = useCallback(() => {
    setSelectedBookId(null)
    clearSelection()
  }, [clearSelection])

  // Nessuna biblioteca da guardare: un avviso, non una tabella vuota.
  //
  // Prima si vedeva una biblioteca senza libri, che è la stessa immagine di
  // una biblioteca appena creata — e le due situazioni si risolvono in modi
  // opposti (aggiungere libri, oppure farsi condividere una biblioteca).
  // Emerso il 28/09/2026 provando i permessi con un secondo
  // account.
  if (libraries && libraries.length === 0) {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 text-center">
        <LibraryIcon className="size-8 text-muted-foreground/60" />
        <p className="font-serif text-[17px] font-semibold">{t('library.empty.title')}</p>
        <p className="max-w-md text-[13px] leading-relaxed text-muted-foreground">
          {t('library.empty.description')}
        </p>
        <Button variant="outline" size="sm" onClick={() => openSettings('librerie')}>
          {t('library.empty.openSettings')}
        </Button>
      </div>
    )
  }

  return (
    <div className="relative flex h-[calc(100vh-72px)] flex-col gap-3 md:h-[calc(100vh-96px)]">
      <div className="flex flex-wrap items-center gap-2">
        {libraries && libraries.length > 1 && activeLibrary && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm">
                <LibraryIcon className="size-3.5" />
                {activeLibrary.name}
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

        <div className="relative max-w-[320px] flex-1">
          <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground/70" />
          <input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder={t('library.search.placeholder')}
            className={`w-full rounded-md border border-border bg-card py-1.5 pl-7 text-[13px] outline-none focus:border-primary ${
              searchText ? 'pr-8' : 'pr-2.5'
            }`}
          />
          {/* Svuota TUTTI i filtri, non solo il testo digitato: anche quelli
              messi dal Navigatore Biblioteca finiscono qui dentro (vedi
              cycleBrowserFilter), quindi questa casella e' l'unico posto in
              cui i filtri vivono. Compare solo quando c'e' qualcosa da
              togliere: un pulsante che non fa niente e' peggio che assente. */}
          {searchText && (
            <button
              onClick={() => setSearchText('')}
              title={t('library.search.clearAll')}
              aria-label={t('library.search.clearAll')}
              className="absolute top-1/2 right-1.5 flex size-5 -translate-y-1/2 items-center justify-center rounded text-muted-foreground/70 hover:bg-muted hover:text-foreground"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>

        <Button variant={showNavigator ? 'secondary' : 'outline'} size="sm" onClick={() => setShowNavigator((v) => !v)}>
          <Filter className="size-3.5" />
          {t('library.navigator.toggle')}
        </Button>

        {activeLibrary?.fulltextEnabled && (
          <Button variant="outline" size="sm" onClick={() => setShowFulltextSearch(true)}>
            <FileSearch className="size-3.5" />
            {t('library.fulltext.open')}
          </Button>
        )}

        <div className="ml-auto flex items-center gap-3">
          {isDesktop && (
            <div className="flex gap-1">
              <Button variant={viewMode === 'table' ? 'secondary' : 'ghost'} size="icon-sm" onClick={() => setViewMode('table')} title={t('library.view.table')}>
                <TableIcon className="size-3.5" />
              </Button>
              {/* L'elenco compatto in mezzo ai due: sta fra la densita'
                  della tabella e l'ingombro delle copertine grandi, ed e'
                  la stessa vista che il telefono usa da sempre. */}
              <Button variant={viewMode === 'list' ? 'secondary' : 'ghost'} size="icon-sm" onClick={() => setViewMode('list')} title={t('library.view.list')}>
                <List className="size-3.5" />
              </Button>
              <Button variant={viewMode === 'grid' ? 'secondary' : 'ghost'} size="icon-sm" onClick={() => setViewMode('grid')} title={t('library.view.grid')}>
                <LayoutGrid className="size-3.5" />
              </Button>
            </div>
          )}
          <span className="text-[12px] text-muted-foreground">
            {impaginata
              ? t('library.count.paginatedRange', {
                  from: numero(pagina * dimPagina + 1),
                  to: numero(Math.min((pagina + 1) * dimPagina, totaleFiltrato ?? 0)),
                  total: numero(totaleFiltrato ?? 0),
                })
              : t('library.count.simple', { shown: sortedBooks.length, total: books.length })}
          </span>
        </div>
      </div>

      <div className="relative flex flex-1 gap-0 overflow-hidden rounded-lg">
        <NavigatorDrawer
          open={showNavigator}
          onClose={() => setShowNavigator(false)}
          searchText={searchText}
          onSearchTextChange={setSearchText}
          fieldDefs={fieldDefs}
          books={books}
          expandedFields={expandedFields}
          onToggleExpand={toggleExpandField}
          onCycleFilter={(def, value, additive) =>
            setSearchText((prev) => cycleBrowserFilter(prev, def, value, additive))
          }
          onClear={() => setSearchText('')}
          valoriDalServer={valoriCampi}
        />

        {/* Sotto "md" il Navigatore è un overlay (niente spazio riservato):
            a quella larghezza spingere il contenuto di 300px lo schiaccerebbe
            via — sopra "md" il comportamento resta quello originale. */}
        <div
          className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
          style={{ paddingLeft: showNavigator && isDesktop ? 300 : 0 }}
        >
          {isLoading ? (
            <div className="p-8 text-center text-muted-foreground">{t('library.loading')}</div>
          ) : isError ? (
            // Ramo nuovo. Prima un fetch fallito cadeva direttamente nella
            // tabella con books=[], che mostra "Nessun libro corrisponde ai
            // filtri correnti": con il backend spento la libreria sembrava
            // semplicemente vuota.
            <ListError what={t('library.error.subject')} onRetry={() => void refetch()} />
          ) : isDesktop && viewMode === 'table' ? (
            <LibraryTable
              books={sortedBooks}
              columns={orderedColumns}
              allColumns={allColumns}
              visibleColumnIds={visibleColumnIds}
              columnWidths={columnWidths}
              sortCriteria={sortCriteria}
              onSortClick={handleSortClick}
              selectedBookId={selectedBookId}
              onSelectBook={selectBook}
              selectedIds={selectedIds}
              customColumns={customColumns}
              onReorderColumns={setVisibleColumnIds}
              onResizeColumn={(colId, width) => setColumnWidths((prev) => ({ ...prev, [colId]: width }))}
              onToggleColumn={toggleColumn}
              progressByBookId={progressByBookId}
              deviceStatusByBookId={deviceStatusByBookId}
            />
          ) : (
            <LibraryCards
              books={sortedBooks}
              selectedBookId={selectedBookId}
              onSelectBook={selectBook}
              progressByBookId={progressByBookId}
              // Sotto "md" sempre l'elenco: la griglia di copertine li'
              // mostrerebbe tre libri per schermata.
              variant={isDesktop && viewMode === 'grid' ? 'grid' : 'list'}
            />
          )}
        </div>

        {selectedBook && (
          <QuickviewPanel
            book={selectedBook}
            libraryFolder={activeLibrary?.folder_name}
            width={quickviewWidth}
            customColumns={customColumns}
            devices={devices}
            deviceStatusByBookId={deviceStatusByBookId}
            onResizeStart={handleQuickviewResizeStart}
            onOpenDetail={() => navigate(`/libri/${selectedBook.id}`, { state: { libraryFolder: activeLibrary?.folder_name } })}
            onOpenAnnotations={() => navigate('/annotazioni')}
            onAuthorClick={handleAuthorClick}
            onClose={closeQuickview}
          />
        )}
      </div>

      {/* Comandi di pagina: ci sono solo in modalita' impaginata, e lo
          dicono. Il numero di pagine viene dal totale che il server ha
          contato, non da quello che abbiamo in mano. */}
      {impaginata && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-1.5 text-[11.5px]">
          <Button
            variant="outline"
            size="sm"
            disabled={pagina === 0}
            onClick={() => setPagina((p) => Math.max(0, p - 1))}
          >
            {t('common.previous')}
          </Button>
          <span className="tabular-nums text-muted-foreground">
            {t('library.pagination.status', {
              page: pagina + 1,
              total: numero(Math.max(1, Math.ceil((totaleFiltrato ?? 0) / dimPagina))),
            })}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={(pagina + 1) * dimPagina >= (totaleFiltrato ?? 0)}
            onClick={() => setPagina((p) => p + 1)}
          >
            {t('common.next')}
          </Button>
          <span className="ml-2 text-muted-foreground">
            {t('library.pagination.largeLibraryNotice')}
            {sortNonSupportato(sortCriteria) && ` ${t('library.pagination.sortNotSupported')}`}
            {' '}{t('library.pagination.navigatorNotice')}
          </span>
        </div>
      )}

      {activeLibrary && (
        <div className="flex shrink-0 items-center gap-3 rounded-md border border-border bg-muted/30 px-3 py-1.5 text-[11.5px] text-muted-foreground">
          <span className="font-medium text-foreground">{activeLibrary.name}</span>
          <span>
            {t('library.count.total', { n: numero(impaginata ? (infoPaginazione?.total ?? 0) : books.length) })}
          </span>
          {selectedIds.size > 1 && (
            <span className="ml-auto text-primary">{t('library.selection.count', { count: selectedIds.size, n: selectedIds.size })}</span>
          )}
        </div>
      )}

      {showFulltextSearch && activeLibrary && (
        <FulltextSearchDialog libraryFolder={activeLibrary.folder_name} onClose={() => setShowFulltextSearch(false)} />
      )}
    </div>
  )
}
