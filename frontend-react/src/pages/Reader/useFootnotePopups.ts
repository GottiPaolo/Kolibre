// Le note a pie' di pagina del lettore, estratte da ReaderPage.tsx
// (revisione del 19/11, punto A3) SENZA cambiare comportamento: il popup
// che apre la nota sul posto, e i bersagli trasparenti disegnati nella
// pagina esterna sopra ogni rimando — l'unica strada perche' le note
// funzionino su Safari, dove l'iframe sandboxato non consegna i click ai
// listener del padre (WebKit 218086; il racconto intero sta nei commenti
// originali, spostati qui col codice).
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import type { Book, Contents, Location as EpubRenditionLocation, Rendition } from 'epubjs'
import { isNoteLink, isNoteBacklink, loadNoteText } from './EpubHelpers'
import type { PageLayout } from './EpubReaderSettings'
import type { SidebarTab } from './EpubTypes'
import type { Valori } from '@/lib/i18n'

/**
 * Un rimando di nota visibile sulla pagina, nelle coordinate della finestra
 * esterna: sopra ognuno si disegna un bersaglio trasparente che riceve il
 * click al posto dell'iframe. Vedi refreshNoteHitboxes.
 */
interface NoteHitbox {
  key: string
  left: number
  top: number
  width: number
  height: number
  href: string
  /** Il testo del rimando ("1", "[12]"): serve a togliere lo stesso
   *  numero dalla testa della nota. Vedi loadNoteText. */
  marcatore: string
  contents: Contents
}

// Larghezza del popup della nota. Larga: una nota e' spesso un periodo
// intero con una citazione dentro, e in una colonna stretta diventa una
// scaletta di parole.
const LARGHEZZA_NOTA = 560

/**
 * Dove mettere il popup della nota: centrato sul rimando, sotto se ci sta,
 * sopra altrimenti, e comunque dentro lo schermo.
 *
 * `altezza` e' quella misurata dopo la resa (0 al primo giro, vedi
 * useLayoutEffect in ReaderPage): finche' non si conosce, si tenta sotto.
 */
export function posizioneNota(p: { x: number; y: number }, altezza: number) {
  const larghezza = Math.min(LARGHEZZA_NOTA, window.innerWidth - 32)
  const left = Math.max(16, Math.min(p.x - larghezza / 2, window.innerWidth - larghezza - 16))
  const sotto = p.y + 18
  const ciSta = sotto + altezza + 16 <= window.innerHeight
  const top = ciSta ? sotto : Math.max(16, p.y - 18 - altezza)
  return { left, top, width: larghezza }
}

interface ParametriNote {
  renditionRef: RefObject<Rendition | null>
  containerRef: RefObject<HTMLDivElement | null>
  bookRef: RefObject<Book | null>
  /** L'ultima posizione nota: base per risolvere i percorsi relativi. */
  lastLocationRef: RefObject<EpubRenditionLocation | null>
  /** Dito invece di mouse: allarga i bersagli a 44px (vedi refreshNoteHitboxes). */
  tocco: boolean
  t: (chiave: string, valori?: Valori) => string
  // I tre riflussi che spostano i rimandi: pannello laterale, impaginazione,
  // corpo del testo. Servono solo come dipendenze dell'effetto di rimisura.
  sidebarTab: SidebarTab
  pageLayout: PageLayout
  fontScale: number
}

export function useFootnotePopups({
  renditionRef,
  containerRef,
  bookRef,
  lastLocationRef,
  tocco,
  t,
  sidebarTab,
  pageLayout,
  fontScale,
}: ParametriNote) {
  // Nota a pie' di pagina aperta sul posto. `text` null mentre carica: il
  // file delle note puo' essere un documento a parte da leggere.
  const [notePopup, setNotePopup] = useState<{ x: number; y: number; text: string | null } | null>(null)
  // Bersagli cliccabili disegnati NELLA PAGINA ESTERNA sopra ogni rimando di
  // nota. Vedi refreshNoteHitboxes: in Safari il click dentro l'iframe non
  // arriva mai al nostro codice, quindi il rimando va intercettato da fuori.
  const [noteHitboxes, setNoteHitboxes] = useState<NoteHitbox[]>([])
  const notePopupRef = useRef<HTMLDivElement | null>(null)
  const [noteHeight, setNoteHeight] = useState(0)
  const attachedNoteDocsRef = useRef(new WeakSet<Document>())

  // Ridimensionare la finestra reimpagina il libro: i bersagli delle note
  // vanno rimisurati, o restano dov'erano sopra il testo nuovo.
  useEffect(() => {
    const onResize = () => scheduleNoteHitboxes()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Aprire il pannello laterale restringe l'area di lettura senza che la
  // finestra cambi dimensione: stessa necessita' di rimisurare.
  useEffect(() => {
    scheduleNoteHitboxes()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sidebarTab, pageLayout, fontScale])

  // Altezza reale del popup della nota, misurata dopo averlo reso: serve a
  // decidere se ci sta sotto il rimando o va messo sopra (vedi
  // posizioneNota). useLayoutEffect e non useEffect perche' la correzione
  // deve avvenire PRIMA che il browser disegni, o il popup si vedrebbe
  // saltare da una posizione all'altra.
  useLayoutEffect(() => {
    const el = notePopupRef.current
    if (el) setNoteHeight(el.offsetHeight)
  }, [notePopup?.text, notePopup?.x, notePopup?.y])

  // Note a pie' di pagina: si aprono sul posto invece di far saltare a fondo
  // volume perdendo il segno — e' il comportamento che hanno Kindle e Apple
  // Books, e l'unico sensato per una nota di due righe.
  //
  // In cattura (true) e con preventDefault: epub.js gestisce a sua volta i
  // click sui link interni per navigare, e senza fermarlo qui il salto
  // avverrebbe comunque, subito dopo aver aperto il popup.
  function attachNoteListeners(contents: Contents) {
    const doc = contents.document
    if (!doc || attachedNoteDocsRef.current.has(doc)) return
    attachedNoteDocsRef.current.add(doc)
    doc.addEventListener('click', (e: MouseEvent) => {
      const a = (e.target as HTMLElement | null)?.closest?.('a[href]') as HTMLAnchorElement | null
      if (!a || !isNoteLink(a) || isNoteBacklink(a)) return
      e.preventDefault()
      e.stopPropagation()

      // Le coordinate del click sono relative all'iframe: vanno riportate
      // alla finestra esterna, dove il popup vive.
      const rect = contents.document.defaultView?.frameElement?.getBoundingClientRect()
      openNotePopup(contents, a.getAttribute('href') || '', a.textContent || '', (rect?.left ?? 0) + e.clientX, (rect?.top ?? 0) + e.clientY)
    }, true)
  }

  /** Apre il popup e ci carica dentro il testo della nota. */
  function openNotePopup(contents: Contents, href: string, marcatore: string, x: number, y: number) {
    setNotePopup({ x, y, text: null })
    const book = bookRef.current
    if (!book) return
    // Il capitolo corrente serve come base per risolvere i percorsi
    // relativi delle note in un file separato (vedi resolveSection).
    const base = lastLocationRef.current?.start?.href
    void loadNoteText(book, contents, href, base, marcatore).then((testo) => {
      setNotePopup((prev) => (prev ? { ...prev, text: testo ?? t('reader.note.notFound') } : prev))
    })
  }

  /**
   * Ridisegna i bersagli cliccabili sopra i rimandi di nota della pagina.
   *
   * Perche' non basta il listener qui sopra: in WebKit (Safari, e quindi
   * anche la webapp sul Mac e su iPhone) un iframe con sandbox senza
   * `allow-scripts` non consegna NESSUN evento ai listener che il padre gli
   * attacca — ne' click, ne' mouseup, ne' touchend. Verificato riga per riga
   * con il motore di Safari su "Fini e inizi": in Chromium il listener
   * scatta e il popup si apre, in WebKit non scatta e il browser segue il
   * link, portando l'iframe su un indirizzo che nell'app non esiste. E' il
   * bug https://bugs.webkit.org/show_bug.cgi?id=218086, gia' citato piu' su:
   * la nota nel codice diceva che attaccare dal padre bastava, e per Chrome
   * e' vero, per Safari no.
   *
   * Dal padre il DOM dell'iframe resta pero' LEGGIBILE (e' same-origin):
   * possiamo sapere dove sta ogni rimando e mettergli sopra un bottone
   * trasparente nella nostra pagina, che il click lo riceve sempre — e che
   * per giunta impedisce al browser di seguire il link.
   */
  function refreshNoteHitboxes() {
    const rendition = renditionRef.current
    if (!rendition) {
      setNoteHitboxes([])
      return
    }
    // La finestrella di lettura vera: l'iframe di epub.js e' largo quanto
    // TUTTO il capitolo impaginato a colonne, e viene fatto scorrere dentro
    // questo contenitore. Ritagliare sull'iframe non filtrerebbe nulla —
    // i rimandi delle pagine successive risultavano "visibili" a 3000px di
    // distanza e prendevano un bersaglio in mezzo al testo.
    const pagina = containerRef.current?.getBoundingClientRect()
    if (!pagina) {
      setNoteHitboxes([])
      return
    }
    const risultato = rendition.getContents() as unknown
    const sezioni = (Array.isArray(risultato) ? risultato : [risultato]) as Contents[]
    const bersagli: NoteHitbox[] = []
    for (const contents of sezioni) {
      const doc = contents?.document
      const frame = doc?.defaultView?.frameElement as HTMLElement | null | undefined
      if (!doc || !frame) continue
      const cornice = frame.getBoundingClientRect()
      let n = 0
      doc.querySelectorAll('a[href]').forEach((el) => {
        const a = el as HTMLAnchorElement
        if (!isNoteLink(a) || isNoteBacklink(a)) return
        const r = a.getBoundingClientRect()
        if (r.width === 0 || r.height === 0) return
        const left = cornice.left + r.left
        const top = cornice.top + r.top
        if (left + r.width <= pagina.left || left >= pagina.right) return
        if (top + r.height <= pagina.top || top >= pagina.bottom) return
        // Un paio di pixel di margine: un click appena fuori dal bersaglio
        // finirebbe sul link vero, che in Safari sposta via l'iframe. Col
        // dito serve molto di piu': un rimando e' un numerino in apice di
        // una dozzina di pixel, e centrarlo era quasi impossibile — se si
        // sbagliava si finiva sulla fascia che volta pagina (visto provando
        // col dito). 44px e' il minimo che Apple raccomanda per un bersaglio
        // tattile, e il bersaglio si allarga attorno al numero restando
        // centrato su di esso.
        const minimo = tocco ? 44 : 0
        const larghezza = Math.max(r.width + 4, minimo)
        const altezza = Math.max(r.height + 4, minimo)
        bersagli.push({
          key: `${(contents as unknown as { sectionIndex?: number }).sectionIndex ?? 0}-${n++}-${Math.round(left)}-${Math.round(top)}`,
          left: left + r.width / 2 - larghezza / 2,
          top: top + r.height / 2 - altezza / 2,
          width: larghezza,
          height: altezza,
          href: a.getAttribute('href') || '',
          marcatore: a.textContent || '',
          contents,
        })
      })
    }
    setNoteHitboxes(bersagli)
  }

  // I rimandi si spostano a ogni cambio pagina e a ogni ridimensionamento.
  // Il rinvio di un frame lascia finire l'impaginazione di epub.js: misurare
  // subito darebbe le posizioni della pagina precedente.
  function scheduleNoteHitboxes() {
    window.setTimeout(refreshNoteHitboxes, 120)
  }

  return {
    // Il popup della nota e la sua misura (per posizioneNota).
    notePopup,
    setNotePopup,
    notePopupRef,
    noteHeight,
    // I bersagli trasparenti da disegnare nella pagina esterna.
    noteHitboxes,
    // Registrato su hooks.content dalla pagina, una volta per capitolo.
    attachNoteListeners,
    // Usata dai bersagli: apre il popup e ci carica il testo.
    openNotePopup,
    // Rimisura i bersagli dopo un riflusso: la chiamano anche gli altri
    // strati (cambio pagina, cambio corpo, cambio tema).
    scheduleNoteHitboxes,
  }
}
