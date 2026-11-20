// Il livello delle annotazioni del lettore, estratto da ReaderPage.tsx
// (revisione del 19/11, punto A3) SENZA cambiare comportamento: la
// selezione del testo (eventi diretti dove arrivano, sondaggio a
// intervalli dove Safari li trattiene), i due popup — quello della
// selezione e quello dell'evidenziazione esistente — il disegno dei segni
// e della sottolineatura delle note, e le scritture verso il server
// (creazione, colore, nota, estremi, cestino). I perche' stanno nei
// commenti originali, spostati qui col codice.
import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import type { Book, Contents, NavItem, Rendition } from 'epubjs'
import { api } from '@/lib/api'
import {
  createAnnotation,
  riposizionaAnnotazione,
  trashHighlight,
  updateHighlightColor,
  updateHighlightNotes,
} from '@/lib/annotationActions'
import type { NewAnnotationPayload } from '@/lib/annotationActions'
import { lookupWord } from '@/lib/dictionaryActions'
import { addWordToVocabulary } from '@/lib/vocabularyActions'
import {
  chapterPathForCfi,
  colorHex,
  highlightRenderCfi,
  isSingleWord,
  pseudoPageForCfi,
} from './EpubHelpers'
import { spostaEstremoDiUnaParola, type Estremo, type Verso } from './EpubSearch'
import {
  EMPTY_HIGHLIGHT_POPUP,
  EMPTY_SELECTION_POPUP,
  type HighlightPopupState,
  renditionContentsList,
  type SelectionPopupState,
  type SidebarTab,
} from './EpubTypes'
import type { RealHighlight } from '@/types/annotation'
import type { Valori } from '@/lib/i18n'

const POPUP_WIDTH = 220
const POPUP_HEIGHT = 190 // rough estimate: color row + note textarea + action buttons

interface MarkClickData {
  id?: number | string | null
  cfiRange?: string
}

// Vue's NewAnnotationPayload equivalent (annotationActions.ts) omits
// chapter/page/cfi_position — real fields the backend's HighlightCreate
// schema does accept (see schema.d.ts), just not modeled in that narrower
// interface (built for the manual "Nuova annotazione" dialog on the
// Annotazioni page, which has none of these). Assigning through a variable
// of this wider type (rather than an inline object literal at the call
// site) sidesteps TS's excess-property check while still reusing
// createAnnotation 1:1 as instructed, instead of duplicating the POST call.
interface ReaderAnnotationPayload extends NewAnnotationPayload {
  chapter?: string | null
  page?: number | null
  cfi_position?: string | null
}

interface ParametriAnnotazioni {
  renditionRef: RefObject<Rendition | null>
  bookRef: RefObject<Book | null>
  bookId: number
  library: string
  /** Anteprima pre-importazione: niente id Calibre, niente scritture. */
  isIngestPreview: boolean
  /** Il sommario come STATO (saveHighlight lo legge dal render corrente). */
  tocItems: NavItem[]
  /** true solo a indicizzazione finita: serve alla pseudo-pagina. */
  locationsReadyRef: RefObject<boolean>
  t: (chiave: string, valori?: Valori) => string
  showSaveError: (msg: string) => void
  setSidebarTab: (tab: SidebarTab) => void
  setNotaNonTrovata: (valore: { testo: string; motivo: string } | null) => void
  /** Il ripiego sul testo quando l'ancora non serve (vive nella pagina). */
  ritrovaDalTesto: (testo: string, idNota?: string | null) => Promise<boolean>
  /** Cmd/Ctrl+F dentro l'iframe apre la ricerca del libro (vive nella pagina). */
  apriRicercaSeScorciatoia: (e: KeyboardEvent) => boolean
}

export function useAnnotationLayer({
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
}: ParametriAnnotazioni) {
  // Il testo dell'ultima selezione per cui il popup e' stato mostrato: serve
  // a non riproporlo dopo che l'utente l'ha scartato. Vedi il sondaggio
  // della selezione piu' sotto.
  const selezioneMostrataRef = useRef('')
  // Solo le evidenziazioni vere: un'annotazione orfana non ha un CFI e non
  // si può disegnare su una pagina. Vedi HighlightPopupState.
  const [existingHighlights, setExistingHighlights] = useState<RealHighlight[]>([])
  // Quante annotazioni hanno un'ancora che in QUESTO file non risolve. Zero
  // e' il caso normale; qualunque altro numero va detto.
  const [annotazioniNonPosizionate, setAnnotazioniNonPosizionate] = useState(0)
  // E quante non hanno ancora un'ancora per niente: arrivate da un
  // dispositivo e non ancora convertite. E' uno stato di passaggio, non un
  // guasto, e va detto in un altro modo.
  const [annotazioniInAttesa, setAnnotazioniInAttesa] = useState(0)
  const [selectionPopup, setSelectionPopup] = useState<SelectionPopupState>(EMPTY_SELECTION_POPUP)
  const [selectedColor, setSelectedColor] = useState('yellow')
  const [selectionNote, setSelectionNote] = useState('')
  // Lookup dizionario per selezioni di una singola parola (vedi isSingleWord
  // in EpubHelpers.ts) — mostrato nello stesso EpubHighlightPopup della
  // selezione, non un popup a parte (vedi EpubHighlightPopup.tsx).
  const [wordLookup, setWordLookup] = useState<{
    loading: boolean
    definition: string | null
    source: string | null
    added: boolean
  }>({ loading: false, definition: null, source: null, added: false })
  const [highlightPopup, setHighlightPopup] = useState<HighlightPopupState>(EMPTY_HIGHLIGHT_POPUP)
  const [editNote, setEditNote] = useState('')
  const [editColor, setEditColor] = useState('yellow')
  const attachedDocsRef = useRef<WeakSet<Document>>(new WeakSet())
  // Specchio di existingHighlights leggibile da onMarkClicked, registrato
  // una sola volta su rendition — stesso motivo di locationsReadyRef sopra.
  const highlightsRef = useRef<RealHighlight[]>([])

  useEffect(() => {
    highlightsRef.current = existingHighlights
  }, [existingHighlights])

  /**
   * Ridisegna i rettangoli delle evidenziazioni dove sta il testo ADESSO.
   *
   * epub.js ridisegna il pannello dei segni solo dentro `resize(w, h)`, cioe'
   * quando cambiano le dimensioni della vista. Ma in impaginato cambiare il
   * corpo del testo NON cambia le dimensioni dell'iframe — le colonne si
   * riflow e basta — quindi i rettangoli restavano dove erano, sopra il testo
   * vecchio, e si vedeva l'evidenziazione scollata dalla frase.
   *
   * Si toglie e si rimette, invece di cercare il pannello dentro le viste:
   * `annotations.remove/add` sono API pubbliche, e il CFI non e' cambiato —
   * cambiare stile non tocca il DOM — quindi rimettere lo stesso segno lo
   * ricalcola sulle coordinate nuove senza spostare niente.
   */
  function ridisegnaEvidenziazioni() {
    const rendition = renditionRef.current
    if (!rendition) return
    for (const h of highlightsRef.current) {
      const cfi = highlightRenderCfi(h)
      if (!cfi) continue
      try {
        rendition.annotations.remove(cfi, 'highlight')
      } catch {
        // non c'era: si disegna e basta
      }
      renderHighlightMark(cfi, h.color, h.id)
      renderNoteUnderline(cfi, !!(h.notes && h.notes.trim()), h.color)
    }
  }

  /** `false` se l'evidenziazione non si e' potuta disegnare: serve a contarle. */
  /**
   * La linea sottile che distingue chi ha un commento.
   *
   * Un'evidenziazione con una nota e' una cosa diversa da una senza: la prima
   * dice «qui ho pensato qualcosa», la seconda «qui torna a leggere». A
   * colpo d'occhio erano identiche.
   *
   * E' una SECONDA annotazione sullo stesso punto, di tipo 'underline':
   * epub.js indicizza gli overlay per `cfi + tipo`, quindi convive con la
   * 'highlight' invece di sostituirla.
   *
   * Continua e fine. Era tratteggiata, e il tratteggio sotto il testo
   * competeva con il testo: a 3+2 px i segmenti hanno circa il passo delle
   * aste delle lettere e la riga sembrava sporca invece che annotata.
   *
   * Poi l'ho fatta continua a mezzo pixel e 0,5 di opacita', e Paolo (06/10)
   * non l'ha vista: «si vede davvero poco». Mezzo pixel non e' mezzo pixel —
   * l'antialiasing lo spalma su due righe di pixel a meta' intensita', e
   * moltiplicato per 0,5 di opacita' resta un quarto di segno.
   *
   * E non era continua lo stesso: `marks-pane` disegna un segmento per ogni
   * riquadro che il browser restituisce, quindi una riga sola attraversata da
   * un corsivo diventava tre trattini con due buchi. Lo risolve l'unione dei
   * riquadri (vedi UnisciRiquadri.ts), che vale anche qui perche' `Underline`
   * eredita da `Highlight`.
   */
  function renderNoteUnderline(cfiRange: string, haNota: boolean, colore?: string | null) {
    const rendition = renditionRef.current
    if (!rendition) return
    try {
      rendition.annotations.remove(cfiRange, 'underline')
    } catch {
      // non c'era: e' il caso normale
    }
    if (!haNota) return
    try {
      rendition.annotations.add('underline', cfiRange, {}, undefined, 'kolibre-nota', {
        // **Il colore dell'evidenziazione, non quello del testo.** Era il
        // colore del testo, cioe' un grigio chiaro sotto una fascia gialla:
        // si leggeva come uno sbaglio di disegno, non come un segno. Tirata
        // nella tinta della fascia e a piena opacita' diventa il suo bordo
        // inferiore marcato — la stessa cosa, solo piu' decisa.
        stroke: colorHex(colore),
        'stroke-opacity': '1',
        'stroke-width': '1.6',
      })
    } catch {
      // un CFI che non risolve: il segno e' un di piu', non si insiste
    }
  }

  function renderHighlightMark(cfiRange: string, colorValue: string | null, id: number | string | null): boolean {
    const rendition = renditionRef.current
    if (!rendition) return false
    try {
      // cfiRange è salvato anche in `data` (non solo usato come chiave di
      // add()) così onMarkClicked può ritrovare l'evidenziazione anche
      // quando `id` è ancora null (evidenziazione creata in questa sessione,
      // prima che arrivi la risposta POST col vero id).
      rendition.annotations.add('highlight', cfiRange, { id, cfiRange }, undefined, 'kolibre-highlight', {
        fill: colorHex(colorValue),
        // **L'opacita' sta sul GRUPPO, non sul riempimento dei rettangoli.**
        //
        // Un'evidenziazione non e' un rettangolo: `marks-pane` ne disegna uno
        // per ogni riquadro che `Range.getClientRects()` restituisce, e quei
        // riquadri si sovrappongono di continuo — una riga e la successiva
        // quando l'interlinea e' maggiore del corpo, e due pezzi della stessa
        // riga quando il brano attraversa un corsivo o un trattino
        // invisibile. `filteredRanges()` scarta solo quelli contenuti *per
        // intero* in un altro: le sovrapposizioni parziali restano tutte.
        //
        // Con `fill-opacity` ogni rettangolo si componeva per conto suo, e
        // dove due si toccavano il colore si sommava — 0,35 due volte fa
        // 0,58. Da qui le bande piu' scure fra le righe e le cuciture
        // verticali dentro una riga sola: non erano un difetto del colore,
        // erano due rettangoli.
        //
        // `opacity` su un gruppo SVG lo fa disegnare prima a parte e poi
        // comporre una volta sola: dentro il gruppo le sovrapposizioni non
        // esistono piu'. E' il motivo per cui questa riga non puo' tornare a
        // essere `fill-opacity`.
        'fill-opacity': '1',
        opacity: '0.35',
        // `mix-blend-mode` stava qui e non ha mai fatto niente: e' una
        // proprieta' CSS e NON un attributo di presentazione SVG, e tutto
        // quello che passiamo qui `marks-pane` lo scrive con `setAttribute`.
        // Misurato: con la moltiplicazione attiva un giallo chiaro su fondo
        // scuro verrebbe PIU' scuro dello sfondo, e invece e' piu' chiaro.
        // Tolto: una riga che sembra fare una cosa e non la fa e' peggio di
        // una riga che non c'e'.
        // **Senza questo un'evidenziazione non si puo' cliccare**, e non su
        // Safari: in nessun browser. `marks-pane` mette `pointer-events: none`
        // sull'<svg> del pannello e i rettangoli dentro non lo ridichiarano,
        // quindi lo ereditano e il clic passa attraverso. epub.js attacca
        // diligentemente il suo listener su un elemento che non puo' ricevere
        // clic, ed e' per questo che `markClicked` non si e' mai sentito.
        //
        // Gli `styles` che passiamo qui diventano attributi sull'elemento del
        // segno, e in SVG `pointer-events` e' un attributo di presentazione:
        // messo sul gruppo, vale per i rettangoli dentro.
        'pointer-events': 'auto',
      })
      return true
    } catch {
      // A CFI from a different edition/format of this book won't resolve — skip it rather than crash.
      return false
    }
  }

  /** Torna gli id delle annotazioni che e' riuscita a disegnare davvero. */
  async function loadExistingHighlights(): Promise<Set<string>> {
    try {
      const { data, error } = await api.GET('/api/kolibre/annotations')
      if (error) return new Set<string>()
      // Nessuna asserzione: da quando l'elenco dichiara le sue due forme
      // (05/11/2026) il tipo arriva dallo schema, ed e' l'unione delle
      // evidenziazioni vere con le orfane.
      const all = data
      // TUTTE le annotazioni vive di questo libro, anche quelle senza
      // ancora. Prima il filtro pretendeva `cfi_start`, quindi una nota la
      // cui conversione non era mai riuscita — il caso normale per le
      // annotazioni arrivate da KOReader e mai convertite — non compariva
      // nemmeno nell'elenco laterale: il pannello diceva "Nessuna
      // annotazione per questo libro" su un libro pieno di annotazioni, che
      // e' indistinguibile dall'averle perse.
      // Il filtro **esclude le orfane**, e non per scelta di questa pagina:
      // un'orfana non ha un libro di Calibre, quindi non puo' corrispondere
      // a `bookId`. Prima era implicito nel confronto; adesso lo si dice al
      // compilatore, che da li' in poi sa che queste sono tutte vere e ha
      // un CFI da disegnare.
      const mine = all.filter((h): h is RealHighlight =>
        !h.is_orphan && h.calibre_book_id === bookId && h.library === library && !h.trashed)
      setExistingHighlights(mine)
      // Disegnare puo' fallire in silenzio (un CFI di un'altra edizione dello
      // stesso libro non risolve, e il catch lo ingoia). Si contano: un
      // numero e' l'unica differenza fra "non ci sono" e "non si riescono a
      // mettere in questa pagina".
      // **Due casi diversi, e dirli uguali era una bugia.** Una nota appena
      // arrivata da un dispositivo NON ha ancora un punto: la conversione
      // dall'indirizzo di KOReader gira in sottofondo ogni cinque minuti
      // (main.py, HIGHLIGHT_POSITION_BACKFILL_INTERVAL_SECONDS), quindi fra
      // la sincronizzazione e quel momento la nota c'e' e il suo punto no.
      // Dire «il punto a cui punta non esiste in questo file» in quel caso
      // afferma una cosa piu' grave e falsa — che l'ancora sia rotta — e
      // manda a cercare un guasto che non c'e'. Segnalato da Paolo il 06/10
      // su una nota presa sul Kindle: rifacendo la conversione a mano
      // riusciva benissimo, era solo arrivato prima lui.
      let inAttesa = 0
      let nonRisolte = 0
      const disegnate = new Set<string>()
      for (const h of mine) {
        if (!h.cfi_start) { inAttesa += 1; continue }
        const cfiDisegno = highlightRenderCfi(h)
        if (renderHighlightMark(cfiDisegno, h.color, h.id)) {
          disegnate.add(String(h.id))
          renderNoteUnderline(cfiDisegno, !!(h.notes && h.notes.trim()), h.color)
        }
        else nonRisolte += 1
      }
      setAnnotazioniInAttesa(inAttesa)
      setAnnotazioniNonPosizionate(nonRisolte)
      return disegnate
    } catch {
      // Highlights are a nice-to-have overlay; don't block reading if this fails.
      return new Set<string>()
    }
  }

  // Scioglie la selezione dentro l'iframe del libro.
  //
  // Serve perche' il browser dipinge DA SE' il testo selezionato, e nessuno la
  // scioglieva: appena creata un'evidenziazione il testo restava selezionato e
  // l'azzurro di sistema si sommava al nostro giallo — due evidenziazioni sullo
  // stesso testo. Su WebKit durava anche di piu', perche' li' il popup nasce
  // dal sondaggio della selezione e non da un clic che l'avrebbe sciolta.
  //
  // Si scioglie qui e non si spegne `::selection`: spegnerla toglierebbe anche
  // il riscontro visivo MENTRE si trascina per selezionare, che e' l'unico modo
  // di vedere cosa si sta prendendo.
  function sciogliSelezione() {
    const rendition = renditionRef.current
    if (!rendition) return
    // Stessa forma usata dal sondaggio piu' sotto: i tipi di epub.js dicono
    // `Contents`, a runtime e' un array di sezioni attive.
    const risultato = rendition.getContents() as unknown
    const sezioni = (Array.isArray(risultato) ? risultato : [risultato]) as Contents[]
    for (const contents of sezioni) {
      try {
        contents?.window?.getSelection?.()?.removeAllRanges()
      } catch {
        // documento invalidato da un cambio capitolo: si passa oltre
      }
    }
  }

  /**
   * Sposta un estremo dell'evidenziazione di una frase.
   *
   * **Perche' cosi' e non con le maniglie, e non con la selezione.**
   *
   * La prima versione riapriva la selezione sul brano e chiedeva di rifarla a
   * mano. Non serviva a niente: se devi riselezionare tutto, «estendi» non fa
   * nulla che «elimina e rifai» non facesse gia' — e non si capiva nemmeno
   * quale estremo si stesse muovendo.
   *
   * Le maniglie da trascinare vorrebbero `mousemove` e `touchmove` mentre il
   * dito sta sopra il testo, cioe' dentro l'iframe blindato: la classe di
   * eventi che su WebKit non arriva, quella che tiene rotti il pinch e le
   * frecce ai bordi.
   *
   * Quattro bottoni invece: quale estremo e in che direzione lo dice
   * l'etichetta, il risultato si vede subito perche' l'evidenziazione si
   * ridisegna, e non serve nessun evento nuovo dentro l'iframe. Una frase per
   * volta perche' e' l'unita' con cui si pensa leggendo: «prendi anche la
   * frase dopo» si vuole davvero, «prendi anche la parola dopo» quasi mai.
   */
  async function spostaEstremo(h: RealHighlight, estremo: Estremo, verso: Verso) {
    const rendition = renditionRef.current
    const cfi = highlightRenderCfi(h)
    if (!rendition || !cfi) return
    try {
      const range = rendition.getRange(cfi)
      const doc = range?.startContainer.ownerDocument
      if (!range || !doc) { showSaveError(t('reader.highlight.extendFailed')); return }
      const nuovo = spostaEstremoDiUnaParola(doc, range, estremo, verso)
      if (!nuovo) { showSaveError(t('reader.highlight.extendNoRoom')); return }

      const contents = renditionContentsList(rendition).find((c) => c.document === doc)
      const nuovoCfi = contents?.cfiFromRange(nuovo)
      const testo = nuovo.toString().replace(/\s+/g, ' ').trim()
      if (!nuovoCfi || !testo) { showSaveError(t('reader.highlight.extendFailed')); return }

      try { rendition.annotations.remove(cfi, 'highlight') } catch { /* poteva non esserci */ }
      renderHighlightMark(nuovoCfi, h.color, h.id)
      // La sottolineatura e' un'annotazione a parte: va spostata a mano,
      // altrimenti resta sul brano di prima mentre l'evidenziazione e' gia'
      // altrove — due segni per una nota sola.
      renderNoteUnderline(cfi, false)
      renderNoteUnderline(nuovoCfi, !!h.notes?.trim(), h.color)
      setExistingHighlights((prev) => prev.map((x) =>
        x.id === h.id ? { ...x, cfi_start: nuovoCfi, cfi_end: nuovoCfi, text: testo, position_status: 'manuale' } : x
      ))
      setHighlightPopup((p) => (p.highlight?.id === h.id
        ? { ...p, highlight: { ...p.highlight, cfi_start: nuovoCfi, cfi_end: nuovoCfi, text: testo } }
        : p))
      await riposizionaAnnotazione(Number(h.id), nuovoCfi, testo)
    } catch {
      showSaveError(t('reader.save.highlightFailed'))
    }
  }

  function dismissSelectionPopup() {
    sciogliSelezione()
    // Il sondaggio ricorda l'ultimo testo per cui ha gia' mostrato il popup:
    // azzerarlo qui fa si' che riselezionando la STESSA frase il popup
    // ricompaia, invece di restare muto fino a che non si seleziona altro.
    selezioneMostrataRef.current = ''
    setSelectionPopup(EMPTY_SELECTION_POPUP)
    setSelectionNote('')
    setSelectedColor('yellow')
    setWordLookup({ loading: false, definition: null, source: null, added: false })
  }

  // Cerca la definizione non appena il popup mostra la selezione di UNA sola
  // parola — nessuna persistenza qui (vedi lookupWord/dictionaryActions.ts),
  // solo un'anteprima prima che l'utente scelga se aggiungerla al vocabolario.
  useEffect(() => {
    if (!selectionPopup.visible || !isSingleWord(selectionPopup.text)) return
    let cancelled = false
    setWordLookup({ loading: true, definition: null, source: null, added: false })
    lookupWord(selectionPopup.text).then((result) => {
      if (cancelled) return
      setWordLookup({ loading: false, definition: result?.definition ?? null, source: result?.source ?? null, added: false })
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionPopup.visible, selectionPopup.text])

  /**
   * Evidenziare col dito su Safari: la selezione si CHIEDE, non si aspetta.
   *
   * Il popup di selezione nasce da mouseup/touchend attaccati al documento
   * dentro l'iframe (attachDirectSelectionListeners), e su WebKit quegli
   * eventi non arrivano mai — quindi sul telefono selezionare del testo non
   * apriva niente e un'evidenziazione non si poteva proprio creare
   * (verificato su un telefono reale). Ma il DOM dell'iframe resta LEGGIBILE
   * dal padre:
   * la selezione la si puo' interrogare a intervalli, che e' l'unica cosa
   * che la sandbox non impedisce.
   *
   * Si aspetta che il testo selezionato smetta di cambiare prima di mostrare
   * il popup: mentre si trascinano le maniglie la selezione cresce ad ogni
   * giro, e un popup che insegue il dito e' peggio di nessun popup.
   */
  useEffect(() => {
    const PAUSA = 200
    const STABILE = 400
    let ultimo = ''
    let fermoDa = 0
    const id = window.setInterval(() => {
      const rendition = renditionRef.current
      if (!rendition) return
      const risultato = rendition.getContents() as unknown
      const sezioni = (Array.isArray(risultato) ? risultato : [risultato]) as Contents[]
      for (const contents of sezioni) {
        let testo = ''
        try {
          testo = contents?.window?.getSelection?.()?.toString().trim() || ''
        } catch {
          // documento non piu' valido (cambio capitolo): si passa oltre
        }
        if (!testo) continue
        if (testo !== ultimo) {
          ultimo = testo
          fermoDa = Date.now()
          return
        }
        // Gia' mostrato per questo stesso testo — anche dal percorso a
        // eventi, dove funziona: non si ripropone a chi l'ha appena chiuso.
        if (selezioneMostrataRef.current === testo) return
        if (Date.now() - fermoDa < STABILE) return
        showSelectionPopup(contents)
        return
      }
      ultimo = ''
    }, PAUSA)
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function addSelectionToVocabulary() {
    const { text } = selectionPopup
    if (!text || isIngestPreview) return
    try {
      await addWordToVocabulary({
        library,
        calibre_book_id: bookId,
        word: text,
        highlight: text,
        definition: wordLookup.definition,
        definition_source: wordLookup.source,
      })
      setWordLookup((prev) => ({ ...prev, added: true }))
    } catch {
      showSaveError(t('reader.save.vocabularyFailed'))
    }
  }

  async function saveHighlight() {
    const { cfiRange, text } = selectionPopup
    if (!cfiRange) return
    // No calibre_book_id exists yet for a staging file — saving here would
    // write a highlight against a bogus id that no real book will ever have.
    if (isIngestPreview) {
      showSaveError(t('reader.save.highlightUnavailablePreImport'))
      dismissSelectionPopup()
      return
    }
    renderHighlightMark(cfiRange, selectedColor, null)
    try {
      const book = bookRef.current
      const payload: ReaderAnnotationPayload = {
        calibre_book_id: bookId,
        library,
        text,
        comment: selectionNote || null,
        color: selectedColor,
        chapter: book ? chapterPathForCfi(book, tocItems, cfiRange) : null,
        page: book ? pseudoPageForCfi(book, locationsReadyRef.current, cfiRange) : null,
        cfi_position: cfiRange,
      }
      const created = await createAnnotation(payload)
      setExistingHighlights((prev) => [...prev, created])
      // Il popup non si chiude: CAMBIA STATO. Da «stai per evidenziare» a
      // «questa e' la tua evidenziazione», con la nota, gli estremi e il link.
      // E' il momento in cui si vuole scrivere il commento, e chiuderlo
      // obbligherebbe a ritrovare il brano per riaprirlo.
      // Si chiude cliccando fuori, come tutto il resto.
      sciogliSelezione()
      selezioneMostrataRef.current = ''
      setSelectionPopup(EMPTY_SELECTION_POPUP)
      setSelectionNote('')
      setWordLookup({ loading: false, definition: null, source: null, added: false })
      setEditColor(created.color || selectedColor)
      setEditNote(created.notes || '')
      setHighlightPopup({ visible: true, x: selectionPopup.x, y: selectionPopup.y, highlight: created })
      return
    } catch {
      showSaveError(t('reader.save.highlightFailed'))
    }
    dismissSelectionPopup()
  }

  // Lo stato che il server ha davvero per l'evidenziazione aperta. Serve a non
  // rimandare due volte la stessa modifica: `highlightPopup.highlight` resta
  // quello di quando il popup si e' aperto, e confrontarsi con lui direbbe
  // «cambiato» anche subito dopo aver salvato.
  const ultimoSalvatoRef = useRef<{ id: RealHighlight['id']; color: string; notes: string } | null>(null)

  function dismissHighlightPopup() {
    setHighlightPopup(EMPTY_HIGHLIGHT_POPUP)
  }

  function onMarkClicked(cfiRange: string, data: MarkClickData, contents: Contents) {
    const targetCfi = data?.cfiRange || cfiRange
    const hl = highlightsRef.current.find((h) => h.id === data?.id || h.cfi_start === targetCfi)
    if (!hl) return

    let rect: { left: number; top: number; width: number; bottom: number }
    try {
      rect = contents.range(targetCfi).getBoundingClientRect()
    } catch {
      rect = { left: 100, top: 100, width: 0, bottom: 120 }
    }
    const iframeEl = contents.window.frameElement
    const iframeRect = iframeEl ? iframeEl.getBoundingClientRect() : { left: 0, top: 0 }

    let x = iframeRect.left + rect.left + rect.width / 2 - POPUP_WIDTH / 2
    let y = iframeRect.top + rect.bottom + 8
    x = Math.max(8, Math.min(x, window.innerWidth - POPUP_WIDTH - 8))
    if (y + POPUP_HEIGHT > window.innerHeight) {
      y = iframeRect.top + rect.top - POPUP_HEIGHT - 8
    }
    y = Math.max(8, y)

    setEditNote(hl.notes || '')
    setEditColor(hl.color || 'yellow')
    ultimoSalvatoRef.current = { id: hl.id, color: hl.color || 'yellow', notes: hl.notes || '' }
    setHighlightPopup({ visible: true, x, y, highlight: hl })
  }

  /**
   * Scrive colore e nota, e NON chiude il popup.
   *
   * Non c'e' piu' un «Salva»: si salva da se'. Un bottone di conferma su un
   * pannello che non puo' fare altro che salvare pone una domanda a cui non si
   * puo' rispondere male, e nel frattempo lascia credere che chiudere senza
   * premerlo perda qualcosa.
   *
   * Si chiama da tre punti — il colore appena lo si tocca, la nota quando si
   * finisce di scriverla, e la chiusura per tutto cio' che restasse — quindi
   * deve poter essere chiamata a vuoto senza mandare niente: ci pensa
   * `ultimoSalvatoRef`.
   */
  async function applicaModifiche(colore: string, nota: string) {
    const hl = highlightPopup.highlight
    if (!hl) return
    const precedente = ultimoSalvatoRef.current
    if (precedente && precedente.id === hl.id && precedente.color === colore && precedente.notes === nota) return
    // Si segna PRIMA della richiesta: due chiamate ravvicinate (l'ultimo tocco
    // sul colore e il clic fuori che lo segue) devono mandare una PUT sola.
    ultimoSalvatoRef.current = { id: hl.id, color: colore, notes: nota }
    try {
      await Promise.all([updateHighlightColor(hl, colore), updateHighlightNotes(hl, nota)])
    } catch {
      ultimoSalvatoRef.current = precedente
      showSaveError(t('reader.save.editFailed'))
      return
    }
    const updated: RealHighlight = { ...hl, notes: nota, color: colore }
    renditionRef.current?.annotations.remove(highlightRenderCfi(hl), 'highlight')
    renderHighlightMark(highlightRenderCfi(updated), colore, updated.id)
    // La sottolineatura compare o sparisce con la nota: aggiungerne una a
    // un'evidenziazione che non ne aveva deve VEDERSI subito, non alla
    // prossima apertura del libro.
    renderNoteUnderline(highlightRenderCfi(updated), !!nota.trim(), colore)
    setExistingHighlights((prev) => prev.map((h) => (h.id === hl.id ? updated : h)))
    // Anche l'evidenziazione tenuta dal popup, altrimenti la prossima
    // modifica ripartirebbe da quella di quando si e' aperto.
    setHighlightPopup((prec) => (prec.visible && prec.highlight?.id === hl.id ? { ...prec, highlight: updated } : prec))
  }

  /** Chiude tenendo: e' il gesto normale di uscita, non un annullamento. */
  function chiudiPopupEvidenziazione() {
    void applicaModifiche(editColor, editNote)
    dismissHighlightPopup()
  }

  async function deleteHighlightAction() {
    const hl = highlightPopup.highlight
    if (!hl) return
    try {
      await trashHighlight(hl)
    } catch {
      // Remove it locally regardless — worst case it reappears next time existingHighlights reloads from the server.
    }
    renditionRef.current?.annotations.remove(highlightRenderCfi(hl), 'highlight')
    // E la sottolineatura della nota, che e' una SECONDA annotazione sullo
    // stesso punto: togliendo solo la 'highlight' restava a galleggiare sul
    // testo una riga sotto niente, e non andava via fino alla riapertura del
    // libro. `renderNoteUnderline(cfi, false)` e' il modo di toglierla.
    renderNoteUnderline(highlightRenderCfi(hl), false)
    setExistingHighlights((prev) => prev.filter((h) => h.id !== hl.id))
    dismissHighlightPopup()
  }

  // Click su una nota nella sidebar "Annotazioni": prima si limitava a un
  // goToCfi che saltava lì e chiudeva la sidebar senza mostrare altro,
  // costringendo a ritrovare a occhio l'evidenziazione nel testo e
  // ricliccarla per poterne leggere/modificare la nota. Naviga E apre subito
  // lo stesso popup di onMarkClicked, ancorato all'evidenziazione appena
  // raggiunta.
  function goToHighlightAndEdit(hl: RealHighlight) {
    if (!hl.cfi_start) {
      // Senza ancora il click era inerte. Ora si prova col testo, e se non
      // si trova nemmeno quello lo si dice invece di non fare niente.
      setSidebarTab(null)
      void ritrovaDalTesto(hl.text || '', String(hl.id)).then((trovata) => {
        if (trovata) {
          showSaveError(t('reader.save.noteFoundByText'))
        } else {
          setNotaNonTrovata({
            testo: hl.text || '',
            motivo: t('reader.noteMissing.reason.noAnchor'),
          })
        }
      })
      return
    }
    const targetCfi = highlightRenderCfi(hl)
    setSidebarTab(null)
    // Il container del libro deve prima riprendere la larghezza piena (sidebar
    // chiusa) prima di navigare — altrimenti le coordinate del popup, calcolate
    // da onMarkClicked sul rendering post-navigazione, sarebbero relative a un
    // layout che sta per cambiare sotto i piedi. Stesso motivo del piccolo
    // setTimeout usato per la selezione testuale sopra.
    window.setTimeout(async () => {
      const rendition = renditionRef.current
      if (!rendition) return
      try {
        await rendition.display(targetCfi)
      } catch {
        return
      }
      for (const contents of renditionContentsList(rendition)) {
        try {
          contents.range(targetCfi)
        } catch {
          continue // non è questa sezione (spread doppio: due view attive)
        }
        onMarkClicked(targetCfi, { id: hl.id, cfiRange: targetCfi }, contents)
        return
      }
    }, 50)
  }

  // epub.js's own "selected" event only fires from an internal, debounced
  // (250ms) `selectionchange` listener attached inside the sandboxed iframe —
  // in practice that can silently miss real mouse-driven selections. This
  // reader hedges the exact same way the source Vue implementation does: it
  // listens to *both* `selectionchange` (via rendition's own 'selected'
  // event below) and the immediate, synchronous `mouseup`/`touchend` that
  // ends a drag (attachDirectSelectionListeners) — whichever fires first
  // shows the popup; the other is a harmless no-op re-check.
  function showSelectionPopup(contents: Contents, cfiRangeHint?: string) {
    const selection = contents.window.getSelection()
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) return
    const text = selection.toString().trim()
    if (!text) return

    const range = selection.getRangeAt(0)
    const rect = range.getBoundingClientRect()
    if (rect.width === 0 && rect.height === 0) return // stale/invalid range
    const cfiRange = cfiRangeHint || contents.cfiFromRange(range)

    const iframeEl = contents.window.frameElement
    const iframeRect = iframeEl ? iframeEl.getBoundingClientRect() : { left: 0, top: 0 }

    let x = iframeRect.left + rect.left + rect.width / 2 - POPUP_WIDTH / 2
    let y = iframeRect.top + rect.bottom + 8
    x = Math.max(8, Math.min(x, window.innerWidth - POPUP_WIDTH - 8))
    if (y + POPUP_HEIGHT > window.innerHeight) {
      y = iframeRect.top + rect.top - POPUP_HEIGHT - 8 // flip above the selection instead
    }
    y = Math.max(8, y)

    selezioneMostrataRef.current = text
    setSelectionPopup({ visible: true, x, y, cfiRange, text })
  }

  // Direct DOM attachment: registered on the same `hooks.content` extension
  // point epub.js itself uses internally to bridge its own events, but
  // bypassing that bridge entirely and reaching the real iframe Document
  // (citing https://bugs.webkit.org/show_bug.cgi?id=218086 — event handling
  // inside a sandboxed iframe can silently misbehave without allow-scripts).
  // Fires once per rendered section/chapter (a new iframe document each time).
  function attachDirectSelectionListeners(contents: Contents) {
    const doc = contents.document
    if (!doc || attachedDocsRef.current.has(doc)) return
    attachedDocsRef.current.add(doc)
    doc.addEventListener('mouseup', () => {
      window.setTimeout(() => showSelectionPopup(contents), 10)
    })
    doc.addEventListener('touchend', () => {
      window.setTimeout(() => showSelectionPopup(contents), 10)
    })
    // Cmd/Ctrl+F mentre si legge: il fuoco è dentro l'iframe, quindi il
    // keydown non arriva alla finestra madre e sarebbe il browser a
    // rispondere. epub.js inoltra solo il `keyup`, e un preventDefault su
    // keyup arriva troppo tardi per fermare la ricerca del browser: l'unico
    // punto utile è il keydown sul documento vero, che è questo.
    //
    // SOLO quella scorciatoia, e non tutto `onKeydown`: le frecce dentro
    // l'iframe le gestisce già il keyup inoltrato da epub.js, e aggiungere
    // qui un secondo gestore farebbe girare due pagine per ogni freccia.
    doc.addEventListener('keydown', (e: KeyboardEvent) => apriRicercaSeScorciatoia(e))
  }

  return {
    // Le evidenziazioni del libro e i due contatori di quelle non mostrabili.
    existingHighlights,
    annotazioniNonPosizionate,
    annotazioniInAttesa,
    // Il popup della selezione e i suoi campi.
    selectionPopup,
    selectedColor,
    setSelectedColor,
    selectionNote,
    setSelectionNote,
    wordLookup,
    // Il popup dell'evidenziazione esistente e i suoi campi.
    highlightPopup,
    editNote,
    setEditNote,
    editColor,
    setEditColor,
    // Disegno e caricamento dei segni (il mount della pagina li usa).
    ridisegnaEvidenziazioni,
    loadExistingHighlights,
    // Azioni dei popup.
    dismissSelectionPopup,
    addSelectionToVocabulary,
    saveHighlight,
    applicaModifiche,
    chiudiPopupEvidenziazione,
    deleteHighlightAction,
    spostaEstremo,
    goToHighlightAndEdit,
    // Registrati su rendition dal mount della pagina.
    onMarkClicked,
    showSelectionPopup,
    attachDirectSelectionListeners,
  }
}
