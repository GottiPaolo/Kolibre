// Web reader EPUB — porting 1:1 (comportamento, non markup) di
// frontend/src/ReaderView.vue. Entry point standalone (vedi reader-main.tsx
// + reader.html): niente React Router, niente QueryClientProvider — i
// parametri arrivano dalla query string della finestra e i dati passano da
// chiamate dirette a lib/api.ts, non da hook di React Query.
import { useEffect, useRef, useState } from 'react'
import ePub from 'epubjs'
import type { Book, Contents, Location as EpubRenditionLocation, NavItem, Rendition } from 'epubjs'
import { AlertTriangle, ArrowLeft, ChevronLeft, ChevronRight, List, Search, Settings2, Sparkles, X } from 'lucide-react'
import { authHeaders } from '@/lib/auth'
import { api, withBackendUrl } from '@/lib/api'
import { downloadFormatUrl } from '@/lib/bookActions'
import { READER_HEIGHT, READER_WIDTH } from '@/lib/readerActions'
import { salvaAncoraRitrovata } from '@/lib/annotationActions'
import { getReadingPosition } from '@/lib/readingPositionActions'
import { copiaNegliAppunti } from '@/lib/appunti'
import { coloriDi, temaEScuro, temaPerEpubJs, type PreferenzeLettura } from './EpubTheme'
import { unisciIRiquadriDeiSegni } from './UnisciRiquadri'
import { useStyleVariant } from '@/lib/useStyleVariant'
import { useLingua } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import {
  HIGHLIGHT_COLORS,
  chapterPathForCfi,
  formatHighlightMeta,
  isSingleWord,
  searchInBook,
  tocEntryForHref,
} from './EpubHelpers'
import {
  type EpubSearchMatch,
  locationsTotal,
  renditionContentsList,
  type SidebarTab,
} from './EpubTypes'
import { posizioneNelLibro, type PosizioneNelLibro } from './PosizioneNelLibro'
import { titoloDellaFinestra } from './TitoloDellaFinestra'
import {
  loadFontScale,
  loadPreferenzeLettura,
  savePreferenzeLettura,
  loadPageLayout,
  type PageLayout,
  savePageLayout,
  spreadForPageLayout,
} from './EpubReaderSettings'
import { EpubHighlightPopup } from './EpubHighlightPopup'
import { EpubSettingsPanel } from './EpubSettingsPanel'
import { EpubSidebar } from './EpubSidebar'
import { messaggioErrore } from '@/lib/messaggiErrore'
import { useReaderGestures } from './useReaderGestures'
import { posizioneNota, useFootnotePopups } from './useFootnotePopups'
import { useAnnotationLayer } from './useAnnotationLayer'
import { useReadingPositionSync } from './useReadingPositionSync'

// Caratteri che l'XML non ammette e basta: i controlli C0 tranne tab, a
// capo e ritorno a capo (XML 1.0 §2.2). Sono invisibili, non vogliono dire
// niente, e un EPUB non dovrebbe contenerli.
// I caratteri di controllo sono esattamente quello che queste due espressioni
// devono trovare: è il loro mestiere, non una svista.
// eslint-disable-next-line no-control-regex
const CONTROLLI_ILLEGALI = /[\x00-\x08\x0B\x0C\x0E-\x1F]/g
// eslint-disable-next-line no-control-regex
const HA_CONTROLLI_ILLEGALI = /[\x00-\x08\x0B\x0C\x0E-\x1F]/

/**
 * Toglie i caratteri di controllo illegali dai file dell'EPUB PRIMA che il
 * browser provi a interpretarli come XML.
 *
 * Perche' serve: un capitolo che ne contiene uno non si apre a meta' — si
 * apre rotto. Il parser XML del browser si ferma al primo carattere
 * illegale e sostituisce TUTTO il documento con la propria pagina d'errore
 * ("This page contains the following errors... Below is a rendering of the
 * page up to the first error"). Succede su libri veri: in una biblioteca
 * reale un EPUB ha un form-feed grezzo a meta' del capitolo 5, e da
 * li' in poi il capitolo semplicemente non esiste — comprese le sue note,
 * che risultano "non trovate".
 *
 * Non e' un problema di browser: Chromium e WebKit falliscono identici. Il
 * libro e' malformato, e libri malformati ce ne sono parecchi.
 *
 * Perche' QUI e non nell'hook `serialize` di epub.js, che a prima vista
 * sembrerebbe il posto giusto: quando serialize gira il documento e' gia'
 * stato interpretato, cioe' e' gia' la pagina d'errore. L'unico punto utile
 * e' il testo grezzo, prima di `parse()` — cioe' getText, da cui passano
 * tutti i file dell'archivio, capitoli, OPF e NCX compresi.
 *
 * Si sostituisce con uno spazio e non col nulla: un form-feed sta fra due
 * parole, e toglierlo del tutto le attaccherebbe.
 */
function ripulisciCaratteriIllegali(book: Book) {
  const archivio = (book as unknown as { archive?: { getText?: (u: string, e?: string) => Promise<string> } }).archive
  if (!archivio || typeof archivio.getText !== 'function') return
  const originale = archivio.getText.bind(archivio)
  archivio.getText = (url: string, encoding?: string) => {
    const risposta = originale(url, encoding)
    // `Archive.getText` di epub.js restituisce `undefined` — non una promessa
    // rifiutata — quando la voce non esiste nello zip, e `Archive.request` conta
    // esattamente su quello per rispondere "File not found in the epub":
    //
    //     response = this.getText(url)
    //     if (response) { ... } else { deferred.reject({message: "File not found..."}) }
    //
    // Chiamare `.then` su quell'undefined fa esplodere la richiesta invece di
    // farla fallire nel modo previsto. Finche' la patch girava solo sui
    // capitoli non si vedeva; da quando copre anche container.xml, l'OPF e
    // l'NCX — che e' il punto — un EPUB a cui manchi uno di quei file
    // rompeva il caricamento invece di dare l'errore giusto.
    if (!risposta || typeof risposta.then !== 'function') return risposta
    return risposta.then((testo) =>
      typeof testo === 'string' && HA_CONTROLLI_ILLEGALI.test(testo)
        ? testo.replace(CONTROLLI_ILLEGALI, ' ')
        : testo
    )
  }
}

const iconBtnClass =
  'flex size-8 items-center justify-center rounded-md text-foreground hover:bg-muted data-[active=true]:bg-muted'
const navBtnClass =
  'absolute top-1/2 z-10 flex size-9 -translate-y-1/2 items-center justify-center rounded-full bg-background/75 text-foreground shadow hover:bg-background transition-opacity duration-150'

unisciIRiquadriDeiSegni()

export function ReaderPage() {
  // Applica lo `data-style` corrente (Sake/Museo/Carta) alla finestra —
  // questa apre come documento a sé, non eredita l'attributo dal resto
  // dell'app (vedi useStyleVariant.ts).
  useStyleVariant()
  const { t } = useLingua()

  // Porta la finestra alla misura e alla posizione volute DALL'INTERNO.
  //
  // Le dimensioni passate a window.open bastano in un browser normale, ma
  // vengono ignorate quando Kolibre gira come APP WEB (Safari aggiunto al
  // Dock, PWA): li' la finestra la crea il sistema, grande quanto decide lui.
  // Questo e' l'unico modo che resta per provare a rimpicciolirla, e va fatto
  // da dentro la finestra appena aperta.
  //
  // resizeTo/moveTo sono permessi solo su finestre aperte da script — da cui
  // il controllo su window.opener, che e' anche cio' che evita di ridimensionare
  // la finestra dell'app se qualcuno apre il reader come scheda normale.
  //
  // Se il browser rifiuta, non succede nulla di male: si resta con la finestra
  // che ha deciso lui. Non c'e' un terzo modo — una pagina non puo' imporre
  // la propria dimensione a una finestra che non ha aperto.
  useEffect(() => {
    if (!window.opener) return
    const larghezza = Math.min(READER_WIDTH, window.screen.availWidth)
    const altezza = Math.min(READER_HEIGHT, window.screen.availHeight)
    try {
      window.resizeTo(larghezza, altezza)
      // Centrata sullo schermo in uso: availWidth/Height escludono dock e
      // barra dei menu, e su un portatile collegato a un monitor esterno
      // sono quelli del monitor su cui la finestra e' effettivamente nata.
      window.moveTo(
        Math.max(0, Math.round((window.screen.availWidth - larghezza) / 2)),
        Math.max(0, Math.round((window.screen.availHeight - altezza) / 2))
      )
    } catch {
      // Permesso negato: previsto in un'app web, nessuna conseguenza.
    }
  }, [])

  const paramsRef = useRef(new URLSearchParams(window.location.search))
  const params = paramsRef.current
  const bookId = Number(params.get('bookId'))
  const library = params.get('library') || 'default'
  const format = params.get('format') || 'EPUB'
  const startCfiParam = params.get('cfi')
  const titleParam = params.get('title') || ''
  // Pre-import preview (App.vue's readIngestBookWeb / la futura pagina
  // Ingest): un file in staging non ha ancora un calibre book id/library, e
  // quindi si apre con `ingestId` invece di `bookId`+`library`, streamando
  // dall'endpoint raw dell'ingest invece di /download, e senza mai
  // caricare/salvare una posizione di lettura o le evidenziazioni.
  const ingestId = params.get('ingestId')
  const isIngestPreview = !!ingestId
  // Deep-link dalla ricerca fulltext: nessun CFI disponibile lato server
  // (l'indice è testo estratto, non epub.js), quindi si fa ripartire la
  // ricerca client-side del reader con questo termine e si atterra sul
  // primo risultato reale.
  const searchTermParam = params.get('searchTerm')
  // Il testo di una NOTA, distinto da `searchTerm`: sono due cose diverse e
  // vanno trattate diversamente. `searchTerm` e' una query che una persona
  // ha digitato — si mostra nel pannello ricerca, e se non trova niente si
  // ricade sulla prima parola. Il testo di una nota e' un passo del libro
  // trascritto alla lettera: non va messo in un campo di ricerca (sono
  // duecento caratteri), e ricadere sulla sua prima parola porterebbe alla
  // prima occorrenza di "Il" nel libro. Vedi ritrovaDalTesto.
  const notaTestoParam = params.get('notaTesto')
  // QUALE nota si e' chiesto di aprire. Serve per una ragione precisa: il
  // controllo "il segno e' comparso?" deve riguardare QUESTA nota, non il
  // libro. La prima versione contava i segni disegnati in tutto il libro, e
  // in un libro con molte note ne bastava una riuscita perche' il ripiego
  // non scattasse mai per quella che si stava aprendo — che e' esattamente
  // il caso riscontrato in uso su un libro reale: la nota c'e', il libro si
  // apre altrove, e nessun avviso lo dice.
  const notaIdParam = params.get('notaId')

  const [bookTitle, setBookTitle] = useState(titleParam)
  // L'autore serve solo al nome della finestra, e viene dai metadati del file
  // invece che da chi apre il lettore: cosi' ce l'hanno anche l'anteprima di
  // un file in importazione (che in biblioteca non esiste ancora) e un
  // collegamento incollato a mano. Per i libri gestiti sono i metadati che
  // Kolibre stesso ha incorporato, quindi quelli di Calibre.
  const [bookAuthor, setBookAuthor] = useState('')

  // Il nome della finestra: «Titolo — Autore», cosi' che con tre libri aperti
  // si capisca dalla linguetta quale sia quale. Si rifa' a ogni cambiamento
  // perche' le due parti arrivano in momenti diversi — il titolo subito dalla
  // URL (se chi apre lo sapeva), l'autore quando l'EPUB ha finito di leggere i
  // suoi metadati — e perche' la lingua si puo' cambiare a lettore aperto.
  useEffect(() => {
    document.title = titoloDellaFinestra(bookTitle, bookAuthor, t('reader.windowTitle'))
  }, [bookTitle, bookAuthor, t])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const tocItemsRef = useRef<NavItem[]>([])
  const [tocItems, setTocItems] = useState<NavItem[]>([])
  // Avanzamento e capitolo corrente, per la barra in basso. `posizione` resta
  // null finche' epub.js non ha finito di indicizzare il libro (locations):
  // prima di allora una posizione nel libro non esiste, e mostrarne una finta
  // sarebbe peggio che non mostrarla. Si mostra invece che si sta contando
  // (vedi la barra in fondo al file).
  const [posizione, setPosizione] = useState<PosizioneNelLibro | null>(null)
  // true quando l'indicizzazione e' FALLITA: senza indice non esiste nessun
  // numero riferito al libro intero, e va detto invece di lasciare «conto le
  // pagine...» acceso per sempre.
  const [conteggioImpossibile, setConteggioImpossibile] = useState(false)
  const [currentToc, setCurrentToc] = useState<{ label: string; href: string } | null>(null)
  // La barra in alto e' nascosta di default: il reader deve somigliare a una
  // pagina, non a un'applicazione. Si scopre toccando la fascia superiore.
  const [chromeVisible, setChromeVisible] = useState(false)
  // Dito invece di mouse. Deciso una volta sola all'avvio: non e' una cosa
  // che cambia mentre si legge, e rivalutarla ad ogni render non servirebbe.
  // Vero quando il lettore NON ha una finestra sua da chiudere: sempre col
  // dito, e ovunque non ci sia una finestra che ci ha aperti.
  //
  // Il solo window.opener non basta, ed e' l'errore della prima versione:
  // nella webapp risulta valorizzato anche quando window.open non
  // ha aperto un bel niente e il lettore ha preso il posto della libreria
  // nella stessa scheda — cosi' il tasto spariva esattamente dove serviva.
  // Sul telefono la finestra non si chiude comunque: il tasto ci sta sempre.
  const [senzaFinestraPropria] = useState(
    () => typeof window !== 'undefined'
      && (!window.opener || !!window.matchMedia?.('(pointer: coarse)').matches)
  )
  const [tocco] = useState(
    () => typeof window !== 'undefined' && !!window.matchMedia?.('(pointer: coarse)').matches
  )
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>(null)
  // Il campo di ricerca della barra laterale, per portarci il fuoco quando
  // Cmd/Ctrl+F apre la scheda: senza, la scheda si apre e bisogna comunque
  // andare a cliccare dentro, che è metà della scorciatoia.
  const searchInputRef = useRef<HTMLInputElement | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<EpubSearchMatch[]>([])
  const [searching, setSearching] = useState(false)
  // L'avviso "nota non ritrovata". Non e' un messaggio fugace come gli
  // altri: e' la risposta a un gesto esplicito — hai chiesto di aprire UNA
  // nota — e se il lettore finisce altrove deve dirlo e restare li' a dirlo,
  // finche' non lo chiudi. In questa fase resta visibile anche per
  // distinguere un difetto da una nota che non si riesce a identificare.
  const [notaNonTrovata, setNotaNonTrovata] = useState<{ testo: string; motivo: string } | null>(null)
  // Mostrato invece di fallire in silenzio: un'evidenziazione/posizione
  // poteva sembrare salvata (resa localmente) anche quando il salvataggio
  // server-side falliva davvero — invisibile finché non spariva
  // misteriosamente, altrove, in tutt'altra finestra.
  const [saveError, setSaveError] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [pageLayout, setPageLayout] = useState<PageLayout>(() => loadPageLayout())
  const [fontScale, setFontScale] = useState<number>(() => loadFontScale())
  const [preferenze, setPreferenze] = useState<PreferenzeLettura>(() => loadPreferenzeLettura())
  // Il sistema puo' cambiare idea mentre si legge (al tramonto, su macOS), e
  // il tema 'sistema' deve seguirlo senza ricaricare la finestra.
  const [sistemaEScuro, setSistemaEScuro] = useState(
    () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
  )

  // In ref, e non solo in stato: il blocco che crea la rendition gira UNA
  // volta sola e le sue closure restano quelle del primo render (vedi la nota
  // lunga piu' in alto su questo file). Leggere `preferenze` direttamente da
  // li' darebbe per sempre i valori di apertura.
  const preferenzeRef = useRef(preferenze)
  preferenzeRef.current = preferenze
  const sistemaEScuroRef = useRef(sistemaEScuro)
  sistemaEScuroRef.current = sistemaEScuro

  const containerRef = useRef<HTMLDivElement | null>(null)
  const bookRef = useRef<Book | null>(null)
  const renditionRef = useRef<Rendition | null>(null)
  // true solo quando generate() è COMPLETAMENTE risolta — book.locations.length()
  // può già essere non zero a metà generazione, il che calcolerebbe una
  // percentuale su un indice parziale (troppo piccolo), letta come "100%"
  // dopo un solo cambio pagina. Ref (non state): letta da handler epub.js
  // registrati una sola volta (relocated/markClicked) che altrimenti
  // vedrebbero per sempre il valore chiuso nella closure del primo render.
  const locationsReadyRef = useRef(false)
  const lastLocationRef = useRef<EpubRenditionLocation | null>(null)
  // Impostato solo quando si riprende da una posizione di origine KOReader
  // (percentuale ma nessun CFI utilizzabile) — consumato una volta finita
  // la generazione delle locations, dato che cfiFromPercentage ha bisogno
  // dello stesso indice di percentageFromCfi.
  const pendingResumePercentageRef = useRef<number | null>(null)
  // Qualcuno ha gia' deciso DOVE si deve stare? La ripresa differita della
  // posizione salvata (vedi locations.generate piu' sotto) arriva quando
  // l'indicizzazione finisce, cioe' in un momento che non controlliamo: su un
  // libro lungo arriva DOPO la ricerca del testo di una nota, e il salto alla
  // posizione salvata vinceva perche' era l'ultimo. Da fuori: «apro una nota e
  // il libro si apre in un punto dove non c'e' niente di evidenziato», senza
  // nemmeno l'avviso, perche' la ricerca ERA riuscita.
  const miraPresaRef = useRef(false)
  // La scrittura della posizione di lettura vive in
  // useReadingPositionSync.ts (estrazione del 20/11/2026); showSaveError
  // e' una dichiarazione di funzione piu' sotto (hoisted).
  const { scheduleSavePosition, flushReadingPosition } = useReadingPositionSync({
    library,
    bookId,
    isIngestPreview,
    t,
    showSaveError,
  })
  const saveErrorTimerRef = useRef<number | undefined>(undefined)

  // Le note a pie' di pagina vivono in useFootnotePopups.ts (estrazione del
  // 20/11/2026): popup, bersagli per Safari e le rimisure dopo i riflussi.
  const {
    notePopup,
    setNotePopup,
    notePopupRef,
    noteHeight,
    noteHitboxes,
    attachNoteListeners,
    openNotePopup,
    scheduleNoteHitboxes,
  } = useFootnotePopups({
    renditionRef,
    containerRef,
    bookRef,
    lastLocationRef,
    tocco,
    t,
    sidebarTab,
    pageLayout,
    fontScale,
  })

  // Selezione, popup ed evidenziazioni vivono in useAnnotationLayer.ts
  // (estrazione del 20/11/2026). ritrovaDalTesto, apriRicercaSeScorciatoia
  // e showSaveError sono dichiarazioni di funzione piu' sotto (hoisted).
  const {
    existingHighlights,
    annotazioniNonPosizionate,
    annotazioniInAttesa,
    selectionPopup,
    selectedColor,
    setSelectedColor,
    selectionNote,
    setSelectionNote,
    wordLookup,
    highlightPopup,
    editNote,
    setEditNote,
    editColor,
    setEditColor,
    ridisegnaEvidenziazioni,
    loadExistingHighlights,
    dismissSelectionPopup,
    addSelectionToVocabulary,
    saveHighlight,
    applicaModifiche,
    chiudiPopupEvidenziazione,
    deleteHighlightAction,
    spostaEstremo,
    goToHighlightAndEdit,
    onMarkClicked,
    showSelectionPopup,
    attachDirectSelectionListeners,
  } = useAnnotationLayer({
    renditionRef,
    bookRef,
    bookId,
    library,
    isIngestPreview,
    tocItems,
    locationsReadyRef,
    t,
    showSaveError,
    setSidebarTab,
    setNotaNonTrovata,
    ritrovaDalTesto,
    apriRicercaSeScorciatoia,
  })

  // I gesti e lo zoom vivono in useReaderGestures.ts (estrazione del
  // 20/11/2026): qui arrivano solo i pezzi che pagina e JSX usano davvero.
  // ridisegnaEvidenziazioni e scheduleNoteHitboxes sono dichiarazioni di
  // funzione piu' sotto (hoisted), quindi passarle qui e' sicuro.
  const {
    hoverEdge,
    setHoverEdge,
    onEdgeHoverMove,
    stepFontScale,
    handlePinchStart,
    handlePinchMove,
    handlePinchEnd,
    attaccaGestiTrackpad,
    staccaGestiTrackpad,
    attachPinchZoomListeners,
    attachEdgeHoverListeners,
    attachTapNavigationListeners,
    handleTapStart,
    handleTapEnd,
    zonaClick,
    zonaTouchStart,
    zonaTouchMove,
    zonaTouchEnd,
    tapStateRef,
    gestoConsumatoRef,
  } = useReaderGestures({
    renditionRef,
    containerRef,
    fontScale,
    setFontScale,
    prevPage,
    nextPage,
    ridisegnaEvidenziazioni,
    scheduleNoteHitboxes,
  })

  function showSaveError(msg: string) {
    setSaveError(msg)
    if (saveErrorTimerRef.current) window.clearTimeout(saveErrorTimerRef.current)
    saveErrorTimerRef.current = window.setTimeout(() => setSaveError(''), 6000)
  }

  function prevPage() {
    renditionRef.current?.prev()
  }
  function nextPage() {
    renditionRef.current?.next()
  }

  function toggleSidebar(tab: Exclude<SidebarTab, null>) {
    setSidebarTab((prev) => (prev === tab ? null : tab))
  }

  function changePageLayout(next: PageLayout) {
    renditionRef.current?.spread(spreadForPageLayout(next))
    setPageLayout(next)
    savePageLayout(next)
  }

  /**
   * Riporta dentro la pagina gli elementi che il libro nasconde buttandoli
   * fuori campo.
   *
   * **Il difetto, misurato.** «His Royal Nibs» (Standard Ebooks) si bloccava
   * dopo poche pagine: il lettore continuava a girare, il contatore saliva —
   * «pagina 3 di 42» — e il testo non cambiava mai. Quel capitolo ha 1199
   * caratteri: 42 pagine non esistono.
   *
   * La causa e' un modo di nascondere un titolo che va per la maggiore da
   * vent'anni: `position: absolute; left: -999em`, cioe' spostarlo fuori
   * schermo lasciandolo leggibile a chi usa un lettore di schermo. Su questo
   * libro `-999em` diventa **-23.976 px**.
   *
   * E epub.js misura la larghezza di un capitolo cosi' (`Contents.textWidth`):
   * prende un `Range` su tutto il corpo e ne chiede il riquadro. **Un Range
   * comprende anche cio' che e' posizionato fuori campo**, quindi quel
   * riquadro risulta largo 24.551 px invece di 550 — e 24.551 diviso la
   * larghezza di una pagina fa 41. Da li' le pagine inventate: il lettore
   * scorre dentro il vuoto, e il CFI non cambia perche' li' non c'e' niente.
   *
   * **La correzione non li nasconde**, che sarebbe toglierli a chi li usa
   * davvero: li rimette a zero e li rende invisibili con la tecnica moderna
   * (un pixel, ritagliato), che e' esattamente quello che quel CSS voleva
   * ottenere e che non allarga il riquadro. Per questo si corregge nel
   * lettore e non nel libro: il libro non e' sbagliato, e' epub.js che lo
   * misura in un modo che quel trucco non prevedeva.
   */
  const FUORI_CAMPO_PX = 2000

  function riportaDentroGliElementiFuoriCampo(doc: Document | null | undefined) {
    if (!doc?.body) return
    try {
      const finestra = doc.defaultView
      if (!finestra) return
      for (const el of Array.from(doc.body.querySelectorAll<HTMLElement>('*'))) {
        const stile = finestra.getComputedStyle(el)
        if (stile.position !== 'absolute' && stile.position !== 'fixed') continue
        const fuori =
          Math.abs(parseFloat(stile.left) || 0) > FUORI_CAMPO_PX ||
          Math.abs(parseFloat(stile.right) || 0) > FUORI_CAMPO_PX ||
          Math.abs(parseFloat(stile.top) || 0) > FUORI_CAMPO_PX
        if (!fuori) continue
        // Invisibile ma presente, e soprattutto largo un pixel: e' la forma
        // che non allarga il riquadro del Range.
        el.style.setProperty('left', '0', 'important')
        el.style.setProperty('right', 'auto', 'important')
        el.style.setProperty('top', '0', 'important')
        el.style.setProperty('width', '1px', 'important')
        el.style.setProperty('height', '1px', 'important')
        el.style.setProperty('overflow', 'hidden', 'important')
        el.style.setProperty('clip-path', 'inset(50%)', 'important')
        el.style.setProperty('white-space', 'nowrap', 'important')
      }
    } catch {
      // documento gia' invalidato: il prossimo capitolo riprova
    }
  }

  function goToTocItem(item: NavItem) {
    renditionRef.current?.display(item.href)
    setSidebarTab(null)
  }

  function goToCfi(cfi: string | null) {
    if (cfi) {
      // Vale anche per i salti dell'utente a lettura iniziata (sommario,
      // risultato di ricerca, clic su un'evidenziazione): chi ha gia' scelto
      // dove stare non va strappato via dalla ripresa che arriva in ritardo.
      miraPresaRef.current = true
      renditionRef.current?.display(cfi)
    }
    setSidebarTab(null)
  }

  // Jump to a search hit AND flash it. Without the flash, landing mid-chapter
  // gives no visual cue of WHERE on the page the matched text actually is.
  // Transient by design: a different className from real highlights
  // ('kolibre-search-match', never added to existingHighlights) so it can't
  // be mistaken for a user annotation, and it fades on its own. This is an
  // epub.js SVG overlay painted inside the book's sandboxed iframe (not a
  // Tailwind/CSS-reachable DOM node), so — same as the Vue source — the
  // "fade" is really an abrupt add-then-remove after 4s, not a CSS transition.
  function flashSearchMatch(cfi: string | null) {
    const rendition = renditionRef.current
    if (!cfi || !rendition) return
    try {
      rendition.annotations.add('highlight', cfi, {}, undefined, 'kolibre-search-match', {
        fill: '#f2b705',
        'fill-opacity': '0.55',
        'mix-blend-mode': 'multiply',
      })
      window.setTimeout(() => {
        try {
          rendition.annotations.remove(cfi, 'highlight')
        } catch {
          // best-effort cleanup
        }
      }, 4000)
    } catch {
      // the jump itself already succeeded; the flash is best-effort
    }
  }

  function goToSearchResult(cfi: string) {
    goToCfi(cfi)
    flashSearchMatch(cfi)
  }

  /**
   * Ritrova una nota partendo dal suo TESTO, quando la sua ancora non serve
   * a niente.
   *
   * Una nota ha sempre due cose: dove stava (il CFI) e cosa diceva (il
   * testo). Il CFI e' fragile — arriva da una conversione, punta a un file
   * che puo' essere stato reimportato, e per le note di KOReader puo'
   * mancare del tutto — mentre il testo e' quello che la persona ha
   * effettivamente sottolineato ed e' quasi sempre ancora li' dentro.
   * Finora, senza un'ancora buona, non succedeva NIENTE: dalla pagina
   * Annotazioni il libro si apriva sulla posizione di lettura salvata (cioe'
   * in un punto a caso rispetto alla nota, ed e' il caso riscontrato in
   * uso), e dal pannello del lettore il click era inerte.
   *
   * Si cerca un pezzo iniziale e non tutto il testo: epub.js cerca una
   * sottostringa contigua, e una nota lunga attraversa quasi sempre piu'
   * elementi — cercandola intera non si troverebbe mai.
   */
  async function ritrovaDalTesto(testo: string, idNota?: string | null): Promise<boolean> {
    const book = bookRef.current
    const pulito = (testo || '').replace(/\s+/g, ' ').trim()
    if (!book || pulito.length < 8) return false

    // Il testo INTERO per primo, poi via via piu' corto.
    //
    // Prima si partiva da 60 caratteri perche' `section.find()` cercava dentro
    // un nodo di testo per volta e una frase lunga non ci stava quasi mai. Ora
    // la ricerca attraversa gli elementi (EpubSearch.ts), quindi il testo
    // intero e' il tentativo migliore — ed e' anche il piu' probabilmente
    // UNIVOCO, che e' quello che conta davvero qui.
    const parole = pulito.split(' ')
    const tentativi: string[] = [pulito]
    for (const limite of [60, 30]) {
      let frammento = ''
      for (const w of parole) {
        if ((frammento + ' ' + w).trim().length > limite) break
        frammento = (frammento + ' ' + w).trim()
      }
      if (frammento.length >= 8 && !tentativi.includes(frammento)) tentativi.push(frammento)
    }

    // Un risultato ambiguo si usa per andarci, ma NON si scrive nel database.
    //
    // Questa funzione salva l'ancora che trova, e la salva per sempre. Se il
    // testo compare piu' volte nel libro, "il primo risultato" e' un tiro di
    // dadi — e con una ricerca piu' tollerante (accenti, virgolette,
    // sillabazione) i casi ambigui aumentano, non diminuiscono. Il server, nel
    // ripiego equivalente, accetta solo se il testo compare UNA VOLTA SOLA
    // (`trova_testo_nel_libro`); qui quella regola non c'era.
    //
    // Compromesso: con un solo riscontro si salta e si salva, come prima. Con
    // piu' riscontri si salta comunque al primo — navigare e' meglio di non
    // fare niente — ma non si incide nel database una scelta che e' casuale.
    let ripiego: string | null = null
    for (const frammento of tentativi) {
      const risultati = await searchInBook(book, frammento)
      if (risultati.length === 0) continue

      if (risultati.length === 1) {
        goToSearchResult(risultati[0].cfi)
        // Trovata una volta, salvata per sempre: senza, questa ricerca su
        // tutto il libro si rifarebbe a ogni apertura della nota.
        const id = Number(idNota)
        if (idNota && Number.isFinite(id)) {
          void salvaAncoraRitrovata(id, risultati[0].cfi).catch(() => {
            // Il salvataggio e' una comodita': se non riesce, la nota si
            // e' comunque ritrovata e la prossima volta si ricerchera'.
          })
        }
        return true
      }
      // Ambiguo. Si tiene da parte il riscontro del frammento PIU' LUNGO —
      // il primo che arriva qui, perche' i tentativi scendono di lunghezza —
      // e si continua.
      //
      // Non si continua sperando che un frammento piu' corto sia univoco: un
      // prefisso non puo' comparire meno volte del testo intero, quindi piu'
      // corto vuol dire semmai PIU' ambiguo. Si continua per l'altro caso: un
      // frammento corto puo' essere TROVATO dove quello lungo non lo era,
      // perche' la nota e' stata trascritta con una parola diversa in fondo.
      if (ripiego === null) ripiego = risultati[0].cfi
    }

    if (ripiego) {
      goToSearchResult(ripiego)
      return true
    }
    return false
  }

  async function handleSearchSubmit() {
    const book = bookRef.current
    const q = searchQuery.trim()
    if (!q || !book) {
      setSearchResults([])
      return
    }
    setSearching(true)
    try {
      setSearchResults(await searchInBook(book, q))
    } finally {
      setSearching(false)
    }
  }

  /**
   * L'ancora copre davvero il testo della nota, o solo un pezzo?
   *
   * `rendition.getRange(cfi)` risolve il CFI nel capitolo CORRENTE — quindi
   * questa domanda ha senso solo dopo essere saltati alla nota, che e'
   * esattamente quando la si pone.
   *
   * La soglia e' larga di proposito (meta'): fra il testo salvato e quello
   * reso ci sono sempre piccole differenze — spazi collassati, un soft hyphen
   * che il salvataggio non ha, le virgolette. Qui non si cerca la precisione,
   * si cerca il caso grosso: un'evidenziazione che copre un frammento di
   * quello che la persona aveva sottolineato.
   *
   * In caso di dubbio si risponde «si'»: una nota riancorata per sbaglio e'
   * peggio di una nota lasciata com'era.
   */
  function copreIlTesto(cfi: string | null | undefined, testoNota: string | null | undefined): boolean {
    if (!cfi || !testoNota) return true
    const atteso = testoNota.replace(/\s+/g, ' ').trim().length
    if (atteso < 40) return true
    try {
      const range = renditionRef.current?.getRange(cfi)
      const reso = range?.toString().replace(/\s+/g, ' ').trim().length ?? 0
      if (reso === 0) return true
      return reso >= atteso * 0.5
    } catch {
      return true
    }
  }

  /**
   * L'indirizzo che riapre QUESTO libro in QUESTO punto.
   *
   * Due scelte che contano:
   *
   * **Niente token.** Il reader si autentica con l'header come tutto il resto
   * dell'app: il `token` in query string che `readerActions.ts` aggiunge non
   * gli serve. Metterlo qui significherebbe incollare una credenziale dentro
   * ogni appunto di Obsidian, per sempre, in chiaro.
   *
   * **Anche il testo, non solo il CFI.** Un CFI punta a una posizione nel DOM:
   * se il file viene riscaricato, riconvertito o sostituito con un'altra
   * edizione, non risolve piu' e il link porta all'inizio del libro. Con
   * `notaTesto` il lettore ha il ripiego che usa gia' per le note — cerca il
   * brano nel libro e ci va. Troncato, perche' un indirizzo di settecento
   * caratteri e' ingestibile e le prime righe bastano a ritrovarlo.
   */
  function linkAlPassaggio(cfi: string, testo: string): string {
    const q = new URLSearchParams({
      bookId: String(bookId),
      library,
      format,
      cfi,
    })
    if (titleParam) q.set('title', titleParam)
    const perRitrovarlo = testo.replace(/\s+/g, ' ').trim().slice(0, 160)
    if (perRitrovarlo.length >= 12) q.set('notaTesto', perRitrovarlo)
    return `${window.location.origin}/reader.html?${q.toString()}`
  }

  /**
   * Copia l'indirizzo che riapre il libro su QUESTA nota.
   *
   * Porta solo l'id (`?nota=889`), non la posizione — vedi ApriNota.tsx per il
   * perche': un link che porta un'identita' continua a funzionare quando
   * l'ancora della nota viene riparata, uno che porta una coordinata no.
   */
  async function copiaLinkDiNota(id: number | string | null | undefined) {
    if (id == null) return
    const fatto = await copiaNegliAppunti(await linkDiNota(id))
    showSaveError(fatto ? t('reader.highlight.linkCopied') : t('reader.cite.failed'))
  }

  /**
   * L'indirizzo da copiare per una nota: **quello condivisibile**, chiesto al
   * server, con il vecchio come ripiego.
   *
   * Il condivisibile (`/k/<biblioteca>/<libro>/n/<nome durevole>`) è
   * migliore per due ragioni, e nessuna delle due è l'eleganza: porta un nome
   * della nota che **non cambia** quando la riga del database viene rifatta
   * (un'orfana accoppiata, due note fuse), e si può **tagliare** per ottenere
   * il libro.
   *
   * Il ripiego sul vecchio `?nota=<id>` non è prudenza: serve a due casi
   * veri. Una nota di un file **non ancora accoppiato** non ha un libro, e
   * quindi non può avere un indirizzo gerarchico (il server risponde 409); e
   * un server più vecchio di questo frontend non conosce quell'indirizzo. In
   * entrambi i casi il vecchio link funziona, ed è meglio di un bottone che
   * non fa niente.
   */
  async function linkDiNota(id: number | string): Promise<string> {
    const vecchio = `${window.location.origin}/reader.html?nota=${id}`
    if (typeof id === 'string' && !/^\d+$/.test(id)) return vecchio
    try {
      const { data } = await api.GET('/api/kolibre/link/di-una-nota', {
        params: { query: { id: Number(id) } },
      })
      const d = data as { indirizzo?: string | null; percorso?: string } | undefined
      if (d?.indirizzo) return d.indirizzo
      if (d?.percorso) return `${window.location.origin}${d.percorso}`
    } catch {
      // Un server che non sa comporre quell'indirizzo non deve far fallire
      // un gesto che prima funzionava.
    }
    return vecchio
  }

  /**
   * Copia il brano come citazione Markdown con il link che lo riapre.
   *
   * La forma e' pensata per essere incollata in Obsidian: una citazione, e
   * sotto l'attribuzione cliccabile. Chi legge l'appunto fra sei mesi non deve
   * ricordarsi da dove veniva — ci torna.
   */
  async function citaSelezione() {
    const { cfiRange, text } = selectionPopup
    if (!cfiRange || !text) return
    const book = bookRef.current
    const capitolo = book ? chapterPathForCfi(book, tocItemsRef.current, cfiRange) : null
    const etichetta = [titleParam || t('reader.cite.thisBook'), capitolo].filter(Boolean).join(' — ')
    const brano = text.replace(/\s+/g, ' ').trim()
    const markdown = `> ${brano}\n\n— [${etichetta}](${linkAlPassaggio(cfiRange, brano)})\n`
    const fatto = await copiaNegliAppunti(markdown)
    showSaveError(fatto ? t('reader.cite.copied') : t('reader.cite.failed'))
    dismissSelectionPopup()
  }

  // Il tema del sistema puo' cambiare mentre si legge: con tema 'sistema' la
  // pagina deve seguirlo senza ricaricare la finestra.
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const cambia = (e: MediaQueryListEvent) => setSistemaEScuro(e.matches)
    mq.addEventListener('change', cambia)
    return () => mq.removeEventListener('change', cambia)
  }, [])

  /**
   * Scrive il foglio di stile del tema dentro le sezioni gia' rese.
   *
   * **Azzera prima.** `themes.default()` non sostituisce niente: epub.js
   * AGGIUNGE le regole in fondo allo stesso `<style>` (`addStylesheetRules`
   * fa `insertRule(..., cssRules.length)`) e non lo svuota mai. Finche' ogni
   * regola viene riscritta a ogni giro l'ultima vince e non si nota; ma una
   * regola che a volte NON c'e' resta quella di prima, per sempre.
   *
   * E' il difetto del passaggio da scuro a chiaro: col tema scuro si scrive
   * `* { color: #c7cbd1 }` per non farsi abbagliare dai colori dell'editore,
   * col tema chiaro quella regola non si scrive affatto — e restava. Il
   * `body` tornava nero, ma `*` colpisce i paragrafi DIRETTAMENTE mentre il
   * colore del body si limita a ereditare, e un colore diretto batte uno
   * ereditato: il testo restava grigio su bianco.
   */
  function applicaTema(preferenze: PreferenzeLettura, sistemaEScuro: boolean) {
    const rendition = renditionRef.current
    if (!rendition) return
    try {
      for (const contenuto of renditionContentsList(rendition)) {
        contenuto.document?.getElementById('epubjs-inserted-css-default')?.remove()
      }
      rendition.themes.default(temaPerEpubJs(preferenze, sistemaEScuro))
    } catch {
      // Un tema che non si applica non deve far cadere la lettura.
    }
  }

  // Ri-applica il foglio di stile a ogni cambio di preferenza.
  //
  // Il CFI non cambia, perche' cambiare stile non tocca il DOM — quindi la
  // posizione di lettura e le evidenziazioni restano dove sono.
  useEffect(() => {
    if (!renditionRef.current) return
    applicaTema(preferenze, sistemaEScuro)
    // Il testo si riflow, quindi i bersagli trasparenti sopra i rimandi di
    // nota — misurati in pixel nella pagina esterna — non sono piu' dove
    // erano.
    ridisegnaEvidenziazioni()
    scheduleNoteHitboxes()
    // `scheduleNoteHitboxes` fuori dalle dipendenze di proposito: e'
    // ridefinita a ogni render, e metterla li' riapplicherebbe il tema a ogni
    // render invece che quando cambia davvero.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preferenze, sistemaEScuro])

  function aggiornaPreferenze(parziali: Partial<PreferenzeLettura>) {
    setPreferenze((prima) => {
      const dopo = { ...prima, ...parziali }
      savePreferenzeLettura(dopo)
      return dopo
    })
  }

  /**
   * Torna da dove si e' arrivati. Indietro nella cronologia, non un salto
   * alla home: se il lettore ha preso il posto della libreria nella stessa
   * scheda, tornare indietro la ritrova com'era — filtri, ricerca e punto
   * della lista compresi. Il salto secco serve solo a chi e' arrivato qui
   * con un link diretto, che una cronologia da cui tornare non ce l'ha.
   */
  function tornaIndietro() {
    // Indietro solo se dietro c'e' davvero una nostra pagina: quando il
    // lettore si apre in una finestra nuova, dietro c'e' un about:blank, e
    // tornarci vorrebbe dire restare a guardare una pagina bianca.
    const dietro = document.referrer
    if (window.history.length > 1 && dietro && dietro.startsWith(window.location.origin)
        && !dietro.includes('reader.html')) {
      window.history.back()
      return
    }
    window.location.href = '/'
  }

  // Il fuoco è dentro un campo di testo? Allora le frecce servono a muovere
  // il cursore, non a girare pagina: scrivendo nella barra di ricerca del
  // lettore, correggere una lettera faceva saltare avanti il libro.
  //
  // Il controllo guarda il documento dell'evento e non `document`: questo
  // stesso gestore è agganciato anche al `keyup` dentro l'iframe del libro
  // (vedi rendition.on più sotto), dove il documento attivo è un altro. Lì
  // campi di testo non ce ne sono, quindi non cambia niente — ma leggere il
  // fuoco della finestra sbagliata sarebbe il genere di dettaglio che si
  // rompe la prima volta che nel libro compare un <input>.
  function stoScrivendo(e: KeyboardEvent): boolean {
    const doc = (e.target as Node | null)?.ownerDocument ?? document
    const attivo = doc.activeElement as HTMLElement | null
    if (!attivo) return false
    const tag = attivo.tagName
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || attivo.isContentEditable
  }

  // Cmd/Ctrl+F apre la ricerca DEL LIBRO, non quella del browser: la seconda
  // cerca dentro la pagina HTML, che contiene solo il capitolo visibile — su
  // un libro di quattrocento pagine non trova quasi mai niente, e sembra che
  // il libro non contenga quella parola.
  //
  // Torna true se ha gestito il tasto. Vive per conto suo perché serve in due
  // posti: la finestra madre e il documento dentro l'iframe, dove il fuoco
  // sta per quasi tutto il tempo di lettura.
  function apriRicercaSeScorciatoia(e: KeyboardEvent): boolean {
    if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 'f') return false
    e.preventDefault()
    setChromeVisible(true)
    setSidebarTab('search')
    // Dopo il render della scheda, altrimenti il campo non esiste ancora.
    // `select` e non solo `focus`: con una ricerca già aperta, Cmd+F deve
    // dare un campo pronto da riscrivere, come in qualunque altra ricerca.
    window.setTimeout(() => {
      searchInputRef.current?.focus()
      searchInputRef.current?.select()
    }, 0)
    return true
  }

  function onKeydown(e: KeyboardEvent) {
    if (apriRicercaSeScorciatoia(e)) return
// Solo le frecce si fermano davanti a un campo di testo. Esc no: mentre
    // si scrive nella ricerca è anzi il modo naturale di chiudere tutto, e
    // toglierglielo sarebbe una seconda sorpresa al posto della prima.
    if (e.key === 'ArrowLeft') {
      if (!stoScrivendo(e)) prevPage()
    } else if (e.key === 'ArrowRight') {
      if (!stoScrivendo(e)) nextPage()
    } else if (e.key === 'Escape') {
      dismissSelectionPopup()
      chiudiPopupEvidenziazione()
      setSettingsOpen(false)
      // Esc chiude anche la barra: la scorciatoia da tastiera per la X.
      setChromeVisible(false)
      setNotePopup(null)
    }
  }

  useEffect(() => {
    // Guardia contro il doppio mount di StrictMode (dev-only): il primo giro
    // "finto" può avviare il fetch e venire smontato prima che risolva —
    // ogni checkpoint sotto verifica `cancelled` prima di toccare stato o
    // creare rendition/book, così il secondo giro (quello vero) riparte
    // pulito invece di duplicare il rendering nello stesso container.
    let cancelled = false

    if (!isIngestPreview && (!bookId || !library)) {
      setError(t('reader.error.missingParams'))
      setLoading(false)
      return
    }

    // Catturato qui (fuori dalla IIFE async sotto) così la cleanup function
    // di questo effetto — che gira anche se il fetch/setup fallisce a metà —
    // può rimuovere gli stessi listener che stiamo per registrare.
    const containerEl = containerRef.current

    window.addEventListener('keydown', onKeydown)
    // `beforeunload` da solo non basta su Safari iOS, dove spesso non parte:
    // l'applicazione passa in secondo piano, la scheda viene scartata, e con il
    // debounce di 2 secondi la posizione dell'ultima pagina girata si perde.
    // `pagehide` e `visibilitychange` sono i due eventi che li' funzionano.
    const flushSeNascosto = () => {
      if (document.visibilityState === 'hidden') flushReadingPosition()
    }
    window.addEventListener('beforeunload', flushReadingPosition)
    window.addEventListener('pagehide', flushReadingPosition)
    document.addEventListener('visibilitychange', flushSeNascosto)
    if (containerEl) {
      containerEl.addEventListener('touchstart', handlePinchStart, { passive: true })
      containerEl.addEventListener('touchmove', handlePinchMove, { passive: false })
      containerEl.addEventListener('touchend', handlePinchEnd, { passive: true })
    }
    // Anche sul NOSTRO documento, non solo su quello del libro: il pinch del
    // trackpad puo' partire con il cursore sopra la barra o un pannello, e li'
    // deve fare la stessa cosa invece dello zoom della pagina.
    attaccaGestiTrackpad(document)

    void (async () => {
      try {
        const url = isIngestPreview ? withBackendUrl(`/api/kolibre/ingest/${ingestId}/file`) : downloadFormatUrl(library, bookId, format)
        // Fetch the bytes ourselves rather than handing epub.js a URL: epub.js
        // decides "packed archive" vs "unpacked directory" by sniffing the
        // URL's file extension, and our download endpoint's path has none
        // (it's a query string) — it would otherwise misdetect this as a
        // directory and try to fetch META-INF/container.xml as a sibling
        // path (404). Handing it the ArrayBuffer directly sidesteps that
        // detection entirely.
        const res = await fetch(url, { headers: await authHeaders() })
        if (!res.ok) throw new Error(`download HTTP ${res.status}`)
        const buffer = await res.arrayBuffer()
        if (cancelled) return

        const book = ePub(buffer)
        bookRef.current = book
        // PRIMA di qualunque lettura, e non dopo `book.opened`: `book.archive`
        // e' assegnato sincronamente dentro il costruttore, mentre `opened` si
        // risolve quando container.xml, l'OPF e l'NCX sono GIA' stati letti e
        // parsati. Installando la patch dopo, copriva solo i capitoli (che si
        // caricano pigramente) e un carattere di controllo nell'OPF mandava
        // ancora il libro nella schermata «Impossibile caricare il libro».
        ripulisciCaratteriIllegali(book)

        // `book.opened` puo' non risolversi MAI, e non e' un'ipotesi: in
        // `unpack()` di epub.js, per un libro caricato da buffer (il nostro
        // caso), `this.opening.resolve(this)` sta dentro
        // `this.replacements().then(...)`, e quel ramo ha un `.catch` che si
        // limita a `console.error(err)`. Se la sostituzione delle risorse
        // fallisce — per esempio perche' un CSS dichiarato nel manifest non
        // c'e' nello zip — l'errore finisce in console e la promessa resta
        // appesa per sempre. Da fuori: «Loading book» a tempo indeterminato,
        // senza nessun errore, che e' il peggiore dei modi di fallire.
        //
        // Non possiamo risolverlo dentro epub.js, ma possiamo smettere di
        // aspettare in silenzio: scaduto il tempo si dice che e' andata male e
        // si manda a guardare la console, dove l'errore vero c'e'.
        const APERTURA_MAX_MS = 30000
        let scaduta = false
        await Promise.race([
          book.opened,
          new Promise<void>((resolve) => window.setTimeout(() => { scaduta = true; resolve() }, APERTURA_MAX_MS)),
        ])
        if (cancelled) return
        if (scaduta) throw new Error('epub.js non ha mai risolto book.opened (vedi la console)')

        const rendition = book.renderTo(containerRef.current!, {
          width: '100%',
          height: '100%',
          // Paginated — text-only with page turns, no scrollbar. Layout
          // (single vs double pagina) parte dalla preferenza salvata
          // dell'utente (impostazioni reader), non da un valore fisso.
          flow: 'paginated',
          spread: spreadForPageLayout(pageLayout),
          // allowScriptedContent RESTA SPENTO. Era acceso in via cautelare
          // ("il gestore eventi potrebbe non funzionare in un iframe
          //  sandboxato"), ma epub.js imposta gia' sandbox="allow-same-origin"
          // e aggiungere allow-scripts alle due insieme ANNULLA la sandbox:
          // il codice dentro l'EPUB gira nella stessa origine dell'app, con
          // accesso pieno a localStorage e a fetch autenticate. Un EPUB
          // scaricato da internet poteva quindi leggere le credenziali e
          // mandarle altrove — e succedeva anche solo con l'anteprima in
          // Importa, prima di decidere se importarlo.
          // I listener (click, selezione, tastiera) li attacca epub.js DAL
          // PADRE sul contentDocument, cosa che l'iframe same-origin permette
          // senza allow-scripts. A restare disattivato e' solo il codice
          // contenuto nel libro, che non deve girare.
          // ATTENZIONE pero': questo vale per Chrome e Firefox. WebKit, cioe'
          // Safari, senza allow-scripts non consegna NESSUN evento nemmeno ai
          // listener messi dal padre (bug 218086). Dove serve davvero, il
          // click si intercetta da fuori: vedi refreshNoteHitboxes.
        })
        renditionRef.current = rendition
        // epub.js's iframe is a separate document — it does NOT inherit this
        // app's dark theme, and most books' own CSS never sets an explicit
        // background/text color at all. Without a theme, that leaves the
        // iframe on the browser's UA default (white bg, black text), which
        // sounds fine — except epub.js itself resets the rendered body to a
        // TRANSPARENT background by default (so reader apps can pick the
        // page color), letting this page's own dark chrome show through
        // behind unstyled black text: unreadable black-on-black. Forcing an
        // explicit light page here — independent of the app's own Sake/
        // Museo/Carta theme — matches how virtually every EPUB reader keeps
        // the reading surface on its own paper-like color regardless of
        // chrome theme.
        // Il foglio di stile della lettura, costruito dalle preferenze (vedi
        // EpubTheme.ts). Era una pagina bianca fissa, per il motivo scritto
        // qui sopra, che resta valido: quello che cambia e' che adesso il
        // colore della pagina lo sceglie chi legge invece di essere imposto.
        applicaTema(preferenzeRef.current, sistemaEScuroRef.current)
        // Dimensione testo salvata dell'utente, applicata subito alla prima
        // resa (non solo dopo il primo tocco di +/- o pinch).
        rendition.themes.fontSize(`${fontScale}%`)
        // La lingua del documento, senza la quale `hyphens: auto` non fa NIENTE.
        //
        // Il browser sceglie il dizionario di sillabazione da `lang`: senza,
        // non sillaba affatto — e sillabare l'italiano con le regole
        // dell'inglese sarebbe peggio. Molti EPUB la dichiarano solo nell'OPF
        // e non in ogni capitolo, quindi qui si copia dai metadati del libro
        // sul documento reso, ma SOLO se il capitolo non ne ha gia' una sua:
        // un libro con capitoli in lingue diverse sa meglio di noi.
        const linguaLibro = (book.packaging?.metadata?.language || '').trim()
        if (linguaLibro) {
          rendition.hooks.content.register((contents: Contents) => {
            try {
              const html = contents.document?.documentElement
              if (html && !html.getAttribute('lang')) html.setAttribute('lang', linguaLibro)
            } catch {
              // documento gia' invalidato: il prossimo capitolo riprova
            }
          })
        }
        // PRIMA di tutto il resto: epub.js misura il capitolo subito dopo
        // questi agganci, e la misura e' quella che decide quante pagine
        // crede che il capitolo abbia.
        rendition.hooks.content.register((contents: Contents) =>
          riportaDentroGliElementiFuoriCampo(contents.document))
        rendition.hooks.content.register(attachDirectSelectionListeners)
        rendition.hooks.content.register(attachPinchZoomListeners)
        rendition.hooks.content.register(attachEdgeHoverListeners)
        rendition.hooks.content.register(attachNoteListeners)
        rendition.hooks.content.register(attachTapNavigationListeners)

        // Dove sono nel LIBRO. Non si usa location.start.displayed.{page,total}
        // perche' quello conta le pagine DENTRO il file corrente (copertina,
        // frontespizio, capitolo 1... sono file separati) e riparte da 1 a
        // ogni file: misurato su un libro vero, 128 pagine girate danno 28
        // etichette in tutto, e «pagina 1 di 5» compare su 9 pagine diverse.
        // Il conto riferito al libro intero sta in posizioneNelLibro.
        //
        // Restituisce la frazione (0..1) usata per il conto, o null se non si
        // puo' ancora dire niente — la stessa frazione che si salva come
        // posizione di lettura, cosi' si misura una volta sola.
        const aggiornaPosizione = (location: EpubRenditionLocation | null): number | null => {
          if (!location || !locationsReadyRef.current || !location.start?.cfi) return null
          const frazione = book.locations.percentageFromCfi(location.start.cfi)
          setPosizione(posizioneNelLibro(frazione, locationsTotal(book)))
          return frazione
        }

        rendition.on('relocated', (location: EpubRenditionLocation) => {
          lastLocationRef.current = location
          const frazione = aggiornaPosizione(location)
          setCurrentToc(tocEntryForHref(tocItemsRef.current, location.start?.href))
          if (!isIngestPreview && frazione != null && location.start?.cfi) {
            scheduleSavePosition(location.start.cfi, frazione)
          }
          scheduleNoteHitboxes()
        })
        rendition.on('rendered', () => {
          setLoading(false)
          scheduleNoteHitboxes()
        })
        rendition.on('resized', scheduleNoteHitboxes)
        // Kept as a harmless, redundant fallback — the real mechanism is the
        // direct-DOM mouseup/touchend attachment registered above.
        rendition.on('selected', (cfiRange: string, contents: Contents) => showSelectionPopup(contents, cfiRange))
        // Clicking an existing highlight overlay: epub.js attaches this
        // click listener itself, directly on the highlight's own DOM
        // element, so this one didn't need the direct-attachment workaround.
        rendition.on('markClicked', onMarkClicked)
        // Arrow keys fired while focus is inside the book's iframe don't
        // bubble to the outer window — epub.js re-emits DOM events from each
        // rendered iframe on the Rendition itself, so this covers that case too.
        rendition.on('keyup', onKeydown)

        // A plain open (no deep-link cfi/searchTerm already dictating where
        // to land) resumes the saved reading position instead of always
        // starting at page one. An exact web-reader CFI wins outright; a
        // KOReader-origin percentage-only position is deferred until
        // locations finish generating below.
        let effectiveStartCfi = startCfiParam
        // `notaTestoParam` e' una mira quanto le altre due: si apre una nota
        // senza ancora proprio per ANDARE a quella nota. Senza questa
        // condizione la ripresa restava armata e poi scavalcava la ricerca.
        if (!isIngestPreview && !startCfiParam && !searchTermParam && !notaTestoParam) {
          try {
            const saved = await getReadingPosition(library, bookId)
            if (cancelled) return
            if (saved?.cfi) {
              effectiveStartCfi = saved.cfi
            } else if (saved?.percentage != null) {
              pendingResumePercentageRef.current = saved.percentage
            }
          } catch {
            // Best-effort — a plain page-1 start is an acceptable fallback.
          }
        }

        // Un'ancora che non risolve NON deve impedire di aprire il libro.
        // display() rigetta su un CFI che punta a una sezione che in questo
        // file non esiste (nota vecchia, EPUB reimportato, conversione da
        // KOReader andata storta) o su un CFI malformato — e finendo dentro
        // il try che avvolge tutta l'inizializzazione, faceva comparire
        // "Impossibile caricare il libro nel web reader" su un libro
        // perfettamente leggibile. Riprodotto su Chromium e su WebKit: e' il
        // "si apre male" che si vedeva cliccando una nota.
        //
        // Ripiego: si apre dove si aprirebbe senza l'ancora, e lo si dice,
        // invece di non aprire niente e non spiegare perche'.
        let ancoraPersa = false
        try {
          await rendition.display(effectiveStartCfi || undefined)
        } catch (errore) {
          // Senza ancora non c'e' ripiego: se fallisce anche l'apertura
          // semplice, il problema e' il libro e la schermata d'errore e'
          // giusta.
          if (!effectiveStartCfi) throw errore
          ancoraPersa = true
          await rendition.display()
        }
        if (cancelled) return
        if (ancoraPersa) {
          showSaveError(
            startCfiParam
              ? t('reader.save.anchorLostFromNote')
              : t('reader.save.anchorLostGeneric')
          )
        }

        if (searchTermParam && !startCfiParam) {
          // The backend fulltext index treats "casa villaggio" as an AND
          // search (both words anywhere in the book), but epub.js's own
          // section.find() only matches a literal contiguous substring — so
          // re-running the exact multi-word query here often finds nothing
          // at all even though the backend legitimately matched this book.
          // Try the term as given first (handles both a quoted exact phrase
          // and multi-word queries that do happen to be contiguous), then
          // fall back to just its first word so the jump/highlight still
          // lands somewhere real instead of silently doing nothing.
          const isQuotedPhrase = /^".*"$/.test(searchTermParam.trim())
          const literalTerm = isQuotedPhrase ? searchTermParam.trim().slice(1, -1) : searchTermParam
          setSearchQuery(literalTerm)
          setSidebarTab('search')
          setSearching(true)
          let results = await searchInBook(book, literalTerm)
          if (results.length === 0 && !isQuotedPhrase && /\s/.test(literalTerm.trim())) {
            const firstWord = literalTerm.trim().split(/\s+/)[0]
            setSearchQuery(firstWord)
            results = await searchInBook(book, firstWord)
          }
          if (!cancelled) {
            setSearchResults(results)
            setSearching(false)
            if (results.length > 0) goToSearchResult(results[0].cfi)
          }
        }

        book.loaded.navigation.then((nav) => {
          if (!cancelled) {
            setTocItems(nav.toc || [])
            // Anche in un ref: il gestore 'relocated' e' registrato una volta
            // sola, quindi una lettura diretta di `tocItems` resterebbe per
            // sempre all'array vuoto del primo render.
            tocItemsRef.current = nav.toc || []
          }
        })
        // I metadati si leggono sempre, non solo quando il titolo manca:
        // l'autore non arriva mai dalla URL, e serve al nome della finestra.
        book.loaded.metadata.then((meta) => {
          if (cancelled) return
          if (!titleParam) setBookTitle(meta.title || '')
          setBookAuthor(meta.creator || '')
        })

        // Indexing the whole book for percentage takes a moment on longer
        // books (misurati 3,4 s su un EPUB di 660 KB); do it in the background
        // and refresh the label once it's ready rather than blocking the
        // initial render on it.
        book.locations.generate(1600).then(() => {
          if (cancelled) return
          locationsReadyRef.current = true
          aggiornaPosizione(lastLocationRef.current)
          if (pendingResumePercentageRef.current != null) {
            const resumeCfi = book.locations.cfiFromPercentage(pendingResumePercentageRef.current)
            pendingResumePercentageRef.current = null
            // Si consuma comunque (anche quando non si salta), cosi' non resta
            // armata per il resto della sessione.
            if (resumeCfi && !miraPresaRef.current) goToCfi(resumeCfi)
          }
        }, (e: unknown) => {
          // Rete di sicurezza, non un caso riprodotto. Senza indice non
          // esiste nessun numero riferito al libro intero — ne' pagina, ne'
          // percentuale, ne' la ripresa da una posizione arrivata da un
          // dispositivo, che e' una percentuale — e senza questo ramo la
          // barra resterebbe su «conto le pagine...» per sempre.
          //
          // Misurato togliendo un capitolo dallo zip di un EPUB vero:
          // generate() NON fallisce, l'indice esce semplicemente piu' corto
          // (189 fette invece di 196) e nessuno se ne accorge. Quindi il modo
          // ovvio di rompere l'indice non passa di qui: resta da capire se
          // qualcosa ci passi davvero.
          console.error('[ReaderPage] locations.generate failed, no book-wide position available', e)
          if (!cancelled) setConteggioImpossibile(true)
        })

        // Highlights are keyed on calibre_book_id + library, neither of
        // which exists yet for a staging file — nothing to load.
        const disegnate = isIngestPreview ? new Set<string>() : await loadExistingHighlights()
        if (cancelled) return

        // Il caso riscontrato in uso: si apre una nota dalla pagina
        // Annotazioni e il libro si apre "in un punto in cui non c'e'
        // niente di evidenziato".
        //
        // Tre modi di arrivarci, e ora hanno tutti e tre lo stesso ripiego:
        //   - la nota non ha ancora (conversione da KOReader mai riuscita):
        //     senza CFI il lettore riprendeva la POSIZIONE DI LETTURA
        //     salvata, cioe' un punto del libro che con la nota non c'entra
        //     niente — in un caso reale il 69%;
        //   - l'ancora c'e' ma non risolve (ancoraPersa): si finiva
        //     all'inizio del libro;
        //   - l'ancora risolve ma non disegna nemmeno un rettangolo: si
        //     arriva nel posto giusto e non si vede niente.
        //
        // Il testo della nota e' la cosa che non si rompe: e' quello che la
        // persona ha sottolineato, ed e' ancora dentro il file.
        // Il segno di QUESTA nota, non un segno qualsiasi del libro.
        //
        // E «si vede» non basta: un'ancora puo' risolvere, disegnare un
        // rettangolo, e coprire META' della nota. Succede davvero, ed e' il
        // caso che ha fatto dannare: un'ancora vecchia prodotta da una
        // ricerca che non sapeva attraversare i soft hyphen si fermava
        // esattamente sul trattino invisibile in mezzo a una parola, lasciando
        // evidenziata la prima meta' del brano. Il lettore la considerava
        // «mostrata» e non ci tornava piu' sopra.
        const questaNotaSiVede = !!notaIdParam && disegnate.has(notaIdParam)
          && copreIlTesto(startCfiParam, notaTestoParam)
        if (notaTestoParam && (!startCfiParam || ancoraPersa || !questaNotaSiVede)) {
          const trovata = await ritrovaDalTesto(notaTestoParam, notaIdParam)
          if (!cancelled) {
            if (trovata) {
              showSaveError(t('reader.save.anchorRecoveredByText'))
            } else {
              setNotaNonTrovata({
                testo: notaTestoParam,
                motivo: !startCfiParam
                  ? t('reader.noteMissing.reason.noAnchor')
                  : ancoraPersa
                    ? t('reader.noteMissing.reason.anchorGone')
                    : t('reader.noteMissing.reason.anchorEmpty'),
              })
            }
          }
        }

        // Ultimo caso del "si apre in un punto dove non c'e' niente di
        // evidenziato": l'ancora ha risolto — quindi siamo arrivati da
        // qualche parte e nessun errore e' scattato — ma nessun segno e'
        // comparso. Un'evidenziazione che non disegna nemmeno un rettangolo
        // non e' un'evidenziazione mostrata, e restare li' e' peggio che
        // cercare: il testo della nota si trova quasi sempre.
        //
        // La condizione e' stretta di proposito (ZERO segni in tutto il
        // libro): con anche un solo segno disegnato non si va a rovistare.
      } catch (err) {
        if (!cancelled) {
          setLoading(false)
          setError(messaggioErrore(err, t('reader.error.loadFailed')))
        }
      }
    })()

    return () => {
      cancelled = true
      window.removeEventListener('keydown', onKeydown)
      window.removeEventListener('beforeunload', flushReadingPosition)
      window.removeEventListener('pagehide', flushReadingPosition)
      document.removeEventListener('visibilitychange', flushSeNascosto)
      if (containerEl) {
        containerEl.removeEventListener('touchstart', handlePinchStart)
        containerEl.removeEventListener('touchmove', handlePinchMove)
        containerEl.removeEventListener('touchend', handlePinchEnd)
      }
      staccaGestiTrackpad(document)
      // Final flush: the debounced save may not have fired yet if the
      // window is closed right after a page turn.
      flushReadingPosition()
      if (renditionRef.current) {
        try {
          renditionRef.current.destroy()
        } catch {
          // ignore
        }
        renditionRef.current = null
      }
      if (bookRef.current) {
        try {
          bookRef.current.destroy()
        } catch {
          // ignore
        }
        bookRef.current = null
      }
    }
    // Mount-once by design: legge i parametri URL una sola volta (fissi per
    // tutta la vita di questa finestra) e possiede l'intero ciclo di vita di
    // book/rendition — vedi il commento su `cancelled` sopra per come viene
    // gestito il doppio mount di StrictMode in dev.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="fixed inset-0 flex flex-col bg-background text-foreground">
      <div
        className={cn(
          'flex h-[50px] shrink-0 items-center gap-2 border-b border-border bg-card px-4 transition-all duration-150',
          !chromeVisible && 'pointer-events-none h-0 overflow-hidden border-b-0 opacity-0'
        )}
      >
        {/* Torna alla libreria. C'e' solo quando il lettore non ha una
            finestra sua: sul telefono, e nella webapp in particolare, non si
            apre una scheda nuova — il lettore prende il posto della libreria,
            e senza questo non c'e' modo di tornare indietro. Dove invece la
            finestra e' sua, si chiude come ogni altra finestra e un comando
            in piu' sarebbe solo da spiegare. */}
        {senzaFinestraPropria && (
          <button type="button" onClick={tornaIndietro} className={iconBtnClass} title={t('reader.nav.backToLibrary')}>
            <ArrowLeft className="size-[18px]" />
          </button>
        )}
        <button
          type="button"
          onClick={() => toggleSidebar('toc')}
          data-active={sidebarTab === 'toc'}
          className={iconBtnClass}
          title={t('reader.toc.title')}
        >
          <List className="size-[18px]" />
        </button>
        <button
          type="button"
          onClick={() => toggleSidebar('search')}
          data-active={sidebarTab === 'search'}
          className={iconBtnClass}
          title={t('reader.search.title')}
        >
          <Search className="size-[18px]" />
        </button>
        {!isIngestPreview && (
          <button
            type="button"
            onClick={() => toggleSidebar('notes')}
            data-active={sidebarTab === 'notes'}
            className={iconBtnClass}
            title={t('reader.notes.title')}
          >
            <Sparkles className="size-[18px]" />
          </button>
        )}
        <span className="flex-1 truncate font-serif text-[15px] font-semibold">{bookTitle}</span>
        {isIngestPreview && (
          <span
            title={t('reader.ingestPreview.tooltip')}
            className="cursor-help rounded-md bg-primary/15 px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap text-primary"
          >
            {t('reader.ingestPreview.badge')}
          </span>
        )}
        {/* Le impostazioni stanno a destra, con la chiusura, e non a sinistra
            con sommario, ricerca e note. Quelli tre aprono un pannello sul
            TESTO e si usano leggendo; questo cambia come il testo e' fatto e
            si tocca una volta ogni tanto. Separarli e' separare «dove sono
            nel libro» da «come lo guardo». */}
        <button
          type="button"
          onClick={() => setSettingsOpen((prev) => !prev)}
          data-active={settingsOpen}
          className={iconBtnClass}
          title={t('reader.settings.title')}
        >
          <Settings2 className="size-[18px]" />
        </button>
        {/* La posizione non si ripete qui: da quando c'e' la barra in basso,
            sempre visibile, quella in alto e' solo comandi. */}
        {/* Chiude LA BARRA, non la finestra: la finestra si chiude come ogni
            altra finestra, e un bottone che lo rifa' dentro la pagina e' un
            comando in piu' da spiegare. La barra invece un modo per sparire
            lo deve avere, e deve stare qui: farla sparire ritoccando la
            stessa fascia che la scopre significa che basta un tocco storto
            per perderla. */}
        <button
          type="button"
          onClick={() => setChromeVisible(false)}
          className={iconBtnClass}
          title={t('reader.nav.hideBar')}
        >
          <X className="size-[18px]" />
        </button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <EpubSidebar
          tab={sidebarTab}
          tocItems={tocItems}
          currentTocHref={currentToc?.href ?? null}
          onGoToToc={goToTocItem}
          searchQuery={searchQuery}
          searchInputRef={searchInputRef}
          onSearchQueryChange={setSearchQuery}
          onSubmitSearch={handleSearchSubmit}
          searching={searching}
          searchResults={searchResults}
          onGoToSearchResult={goToSearchResult}
          highlights={existingHighlights}
          nonPosizionate={annotazioniNonPosizionate}
          inAttesa={annotazioniInAttesa}
          onGoToHighlight={goToHighlightAndEdit}
          onCopyHighlightLink={(h) => void copiaLinkDiNota(h.id)}
        />

        {/* Tutto cio' che si sovrappone al libro sta DENTRO questo riquadro,
            che e' il libro e basta — non la riga intera, che comprende anche
            il pannello laterale. Misurandosi sulla riga, le fasce di
            navigazione coprivano il pannello: aperta la ricerca, toccare un
            risultato voltava pagina invece di aprirlo, difetto visto in uso.
            min-w-0: senza, un flex item cresce fino al contenuto intrinseco —
            il manager interno di epub.js si dimensiona su quello, quindi
            l'intera area lettore (e ogni coordinata calcolata da essa,
            selezione testo inclusa) si allargherebbe alla larghezza interna
            completa del libro. */}
        <div
          className="relative min-w-0 flex-1"
          onMouseMove={onEdgeHoverMove}
          onMouseLeave={() => setHoverEdge(null)}
          onTouchStart={(e) => handleTapStart(e.nativeEvent)}
          onTouchEnd={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            handleTapEnd(e.nativeEvent, rect.width, rect.left)
          }}
        >
          <div ref={containerRef} className="h-full w-full overflow-hidden" />

          {/* Col dito: due fasce larghe che voltano pagina al tocco e allo
              scorrimento, come su KOReader. Stanno QUI FUORI e non dentro
              l'iframe — la navigazione a tocco era attaccata al documento del
              libro (attachTapNavigationListeners), e su Safari/iOS quel
              documento non consegna nessun evento: sul telefono voltare
              pagina semplicemente non funzionava. Vedi refreshNoteHitboxes
              per la causa per esteso.
              La freccia si vede appena: serve a far capire dove toccare, non
              a stare in mezzo alla lettura. Il terzo centrale resta libero,
              cosi' si puo' ancora selezionare il testo e toccare i link del
              libro — e li' lo scorrimento funziona lo stesso, dove il
              browser gli eventi dell'iframe li consegna davvero. */}
          {tocco && (
            <>
              <button
                type="button"
                aria-label={t('reader.nav.prevPage')}
                onTouchStart={zonaTouchStart}
                onTouchMove={zonaTouchMove}
                onTouchEnd={(e) => zonaTouchEnd(e, 'sinistra')}
                onTouchCancel={() => { tapStateRef.current = null; gestoConsumatoRef.current = false }}
                onClick={() => zonaClick('sinistra')}
                className="absolute top-7 bottom-0 left-0 z-10 flex w-[30%] touch-none items-center justify-start pl-3 text-black/20"
              >
                <ChevronLeft className="size-7" />
              </button>
              <button
                type="button"
                aria-label={t('reader.nav.nextPage')}
                onTouchStart={zonaTouchStart}
                onTouchMove={zonaTouchMove}
                onTouchEnd={(e) => zonaTouchEnd(e, 'destra')}
                onTouchCancel={() => { tapStateRef.current = null; gestoConsumatoRef.current = false }}
                onClick={() => zonaClick('destra')}
                className="absolute top-7 right-0 bottom-0 z-10 flex w-[30%] touch-none items-center justify-end pr-3 text-black/20"
              >
                <ChevronRight className="size-7" />
              </button>
            </>
          )}

          <button
            type="button"
            onClick={prevPage}
            title={t('reader.nav.prevPageTitle')}
            className={cn(navBtnClass, 'left-2', hoverEdge === 'left' ? 'opacity-100' : 'pointer-events-none opacity-0')}
          >
            <ChevronLeft className="size-5" />
          </button>

          {/* Fascia sensibile che SCOPRE la barra dei comandi — e basta: a
              chiuderla ci pensa la X sulla barra stessa. Prima faceva da
              interruttore, ma una fascia invisibile in cima alla pagina e' un
              posto dove il dito capita per sbaglio, e vederla sparire subito
              dopo averla aperta e' il contrario di un comando.
              Non prende il fuoco, o le frecce andrebbero al pulsante invece
              che al libro.
              Cancellata per sbaglio il 19/09 rimuovendo l'impostazione della
              larghezza colonna, che stava proprio qui accanto: la barra e'
              rimasta chiusa senza modo di aprirla. */}
          <button
            type="button"
            aria-label={t('reader.nav.showBar')}
            onClick={() => setChromeVisible(true)}
            tabIndex={-1}
            onMouseDown={(e) => e.preventDefault()}
            className="absolute inset-x-0 top-0 z-20 h-7"
          />

          <button
            type="button"
            onClick={nextPage}
            title={t('reader.nav.nextPageTitle')}
            className={cn(navBtnClass, 'right-2', hoverEdge === 'right' ? 'opacity-100' : 'pointer-events-none opacity-0')}
          >
            <ChevronRight className="size-5" />
          </button>
        </div>

        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background font-serif text-muted-foreground">
            {t('reader.loading')}
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-background font-serif text-destructive">{error}</div>
        )}
        {saveError && (
          <div className="absolute top-3 left-1/2 z-30 max-w-[420px] -translate-x-1/2 rounded-lg bg-destructive px-3.5 py-2 text-center text-xs text-white shadow-lg">
            {saveError}
          </div>
        )}

        {/* "Nota non trovata": un avviso che RESTA, non un messaggio che
            passa. Il motivo e' che risponde a un gesto esplicito — hai
            chiesto di aprire UNA nota — e se il lettore finisce altrove deve
            dirlo e continuare a dirlo. Dice anche DOVE sei finito: senza,
            "si e' aperto un libro a caso" e' esattamente come appare.
            Serve a distinguere un difetto da una nota che semplicemente
            non si puo' piu' agganciare. */}
        {notaNonTrovata && (
          <div className="absolute inset-0 z-40 flex items-center justify-center bg-background/80 p-6">
            <div className="max-w-[440px] rounded-lg border border-[var(--warning)]/50 bg-card p-4 shadow-lg">
              <p className="mb-2 flex items-center gap-2 text-[14px] font-semibold">
                <AlertTriangle className="size-4 shrink-0 text-[var(--warning)]" />
                {t('reader.noteMissing.title')}
              </p>
              <p className="mb-2 text-[12.5px] leading-relaxed text-muted-foreground">
                {notaNonTrovata.motivo} {t('reader.noteMissing.searchedText')}
              </p>
              <p className="mb-3 rounded border border-border bg-muted/40 p-2 text-[12px] leading-snug italic">
                “{notaNonTrovata.testo.slice(0, 180)}
                {notaNonTrovata.testo.length > 180 ? '…' : ''}”
              </p>
              <p className="mb-3 text-[12px] leading-relaxed text-muted-foreground">
                {t('reader.noteMissing.openedPrefix')} <b>{t('reader.noteMissing.openedBold')}</b>
                {t('reader.noteMissing.openedSuffix')}
              </p>
              <div className="flex justify-end">
                <button
                  onClick={() => setNotaNonTrovata(null)}
                  className="rounded-md bg-primary px-3 py-1.5 text-[12.5px] text-primary-foreground hover:opacity-90"
                >
                  {t('reader.noteMissing.gotIt')}
                </button>
              </div>
            </div>
          </div>
        )}

        {settingsOpen && (
          <EpubSettingsPanel
            pageLayout={pageLayout}
            onPageLayoutChange={changePageLayout}
            fontScale={fontScale}
            onFontScaleStep={stepFontScale}
            preferenze={preferenze}
            onPreferenzeChange={aggiornaPreferenze}
            sistemaEScuro={sistemaEScuro}
            onClose={() => setSettingsOpen(false)}
          />
        )}

        {/* Il velo che chiude al clic fuori.
            Trasparente e non scurito come quello della nota a pie' di pagina:
            li' il popup e' un momento di lettura a se', qui e' un attrezzo
            sopra il testo e oscurare la pagina sarebbe sproporzionato.
            Copre anche l'iframe, quindi il primo clic chiude e basta — non
            seleziona anche altro testo, che sarebbe due cose per un gesto. */}
        {(selectionPopup.visible || highlightPopup.visible) && (
          <div
            className="fixed inset-0 z-10"
            onMouseDown={() => { dismissSelectionPopup(); chiudiPopupEvidenziazione() }}
          />
        )}

        {selectionPopup.visible && (
          <EpubHighlightPopup
            x={selectionPopup.x}
            y={selectionPopup.y}
            text={selectionPopup.text}
            colors={HIGHLIGHT_COLORS}
            selectedColor={selectedColor}
            onColorChange={setSelectedColor}
            note={selectionNote}
            onNoteChange={setSelectionNote}
            onPrimary={saveHighlight}
            primaryLabel={t('reader.highlight.create')}
            onCite={citaSelezione}
            {...(!isIngestPreview && isSingleWord(selectionPopup.text)
              ? {
                  dictionaryLoading: wordLookup.loading,
                  dictionaryDefinition: wordLookup.definition,
                  dictionarySource: wordLookup.source,
                  onAddToVocabulary: addSelectionToVocabulary,
                  vocabularyAdded: wordLookup.added,
                }
              : {})}
          />
        )}

        {highlightPopup.visible && (
          <EpubHighlightPopup
            x={highlightPopup.x}
            y={highlightPopup.y}
            text={highlightPopup.highlight?.text || ''}
            metaLabel={formatHighlightMeta(highlightPopup.highlight, t)}
            colors={HIGHLIGHT_COLORS}
            selectedColor={editColor}
            // Il colore si scrive appena lo si tocca: e' una scelta sola e
            // finita, non c'e' niente da confermare.
            onColorChange={(c) => { setEditColor(c); void applicaModifiche(c, editNote) }}
            note={editNote}
            onNoteChange={setEditNote}
            onNoteCommit={() => void applicaModifiche(editColor, editNote)}
            onDelete={deleteHighlightAction}
            onMoveEdge={highlightPopup.highlight ? (e, v) => void spostaEstremo(highlightPopup.highlight!, e, v) : undefined}
            onCopyLink={highlightPopup.highlight?.id != null ? () => void copiaLinkDiNota(highlightPopup.highlight?.id) : undefined}
          />
        )}
      </div>

      {/* Bersagli trasparenti sopra i rimandi di nota: sono LORO a ricevere
          il click, non il link dentro l'iframe. Unico modo perche' le note
          funzionino su Safari — vedi refreshNoteHitboxes. */}
      {noteHitboxes.map((h) => (
        <button
          key={h.key}
          type="button"
          aria-label={t('reader.note.openAriaLabel')}
          className="fixed z-20 cursor-pointer bg-transparent"
          style={{ left: h.left, top: h.top, width: h.width, height: h.height }}
          onClick={(e) => {
            e.preventDefault()
            openNotePopup(h.contents, h.href, h.marcatore, e.clientX, e.clientY)
          }}
        />
      ))}

      {/* Popup della nota a pie' di pagina. Sta qui, fuori dall'area di
          lettura, perche' deve poter uscire dai bordi dell'iframe.
          Il testo e' inserito come TESTO e mai come HTML: viene da un EPUB,
          che e' un file scaricato da internet e non fidato — vedi
          loadNoteText.
          La forma e' quella del popup delle note di KOReader: il testo e
          basta, nel carattere del libro, su uno sfondo appena scurito che lo
          stacca dalla pagina. Niente intestazione "Nota" e niente numero in
          testa (lo toglie loadNoteText): sono due modi di ripetere una cosa
          che il lettore ha appena fatto, cioe' toccare quel rimando li'. */}
      {notePopup && (
        <>
          {/* Uno strato sotto il popup: un click fuori lo chiude, senza dover
              cercare il pulsante. Appena scurito, cosi' si vede che c'e'. */}
          <div className="fixed inset-0 z-30 bg-black/20" onClick={() => setNotePopup(null)} />
          <div
            ref={notePopupRef}
            role="dialog"
            aria-label={t('reader.note.dialogAriaLabel')}
            className="animate-in fade-in zoom-in-95 fixed z-40 max-h-[55vh] overflow-y-auto rounded-xl px-6 py-5 shadow-2xl duration-150"
            // Colori della PAGINA, non della chrome dell'app: una nota e' testo
            // del libro, e un riquadro scuro in mezzo alla pagina chiara la fa
            // sembrare un avviso di sistema.
            //
            // Presi da `coloriDi` e non ricopiati a mano: erano due costanti
            // uguali a quelle del tema, e con i temi di lettura sarebbero
            // rimaste bianche sopra una pagina sepia o scura.
            style={{
              ...posizioneNota(notePopup, noteHeight),
              background: coloriDi(preferenze.tema, sistemaEScuro).sfondo,
              color: coloriDi(preferenze.tema, sistemaEScuro).testo,
              border: `1px solid ${temaEScuro(preferenze.tema, sistemaEScuro) ? 'rgba(255,255,255,0.16)' : 'rgba(0,0,0,0.14)'}`,
            }}
          >
            <button
              type="button"
              onClick={() => setNotePopup(null)}
              aria-label={t('reader.note.closeAriaLabel')}
              className="absolute top-2.5 right-2.5 opacity-35 hover:opacity-80"
            >
              <X className="size-4" />
            </button>
            <p className="font-serif text-[15.5px] leading-[1.7] whitespace-pre-wrap">
              {notePopup.text ?? t('common.loading')}
            </p>
          </div>
        </>
      )}

      {/* Barra in basso: dove sono nel libro e in quale capitolo. Resta
          sempre visibile — a differenza di quella in alto, che sono comandi,
          questa e' informazione di lettura, cioe' l'unica cosa che su un
          libro di carta si ha sempre sott'occhio (lo spessore che resta, il
          titolo corrente in testa alla pagina). */}
      <div className="shrink-0 border-t border-border bg-card">
        {/* La barra di avanzamento compare solo quando la posizione esiste
            davvero: epub.js impiega qualche secondo a indicizzare il libro, e
            una barra ferma a zero in quel frattempo direbbe una cosa falsa. */}
        <div className="h-[3px] w-full bg-muted">
          {posizione && (
            <div
              className="h-full bg-primary transition-[width] duration-200"
              style={{ width: `${posizione.percento}%` }}
            />
          )}
        </div>
        <div className="flex items-center gap-3 px-4 py-1.5 text-[11.5px] text-muted-foreground">
          <span className="min-w-0 flex-1 truncate" title={currentToc?.label || undefined}>
            {currentToc?.label ?? bookTitle}
          </span>
          {/* Pagina e percentuale riferite a TUTTO il libro, mai al file
              aperto (che e' uno dei tanti dentro l'EPUB). Il titolo spiega di
              che pagina si tratta, perche' non e' quella dell'edizione di
              carta ne' quella che conta KOReader. */}
          <span
            className="shrink-0 tabular-nums"
            title={conteggioImpossibile ? t('reader.locationLabel.unavailableTitle') : t('reader.locationLabel.explain')}
          >
            {posizione
              ? t('reader.locationLabel.book', { page: posizione.pagina, total: posizione.totale, percent: posizione.percento })
              : conteggioImpossibile
                ? t('reader.locationLabel.unavailable')
                : t('reader.locationLabel.counting')}
          </span>
        </div>
      </div>
    </div>
  )
}
