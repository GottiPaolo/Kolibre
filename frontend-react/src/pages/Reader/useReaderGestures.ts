// I gesti del lettore e lo zoom del testo, estratti da ReaderPage.tsx
// (revisione del 19/11, punto A3) SENZA cambiare comportamento: tocchi e
// scorrimenti per voltare pagina, pinch-zoom a due dita e da trackpad, le
// freccette che compaiono ai bordi, e i doppi registri dei listener dentro
// l'iframe del libro (il perche' di ciascuno sta nei commenti originali,
// spostati qui col codice). La pagina passa le due funzioni del livello
// note (ridisegnaEvidenziazioni, scheduleNoteHitboxes) come parametri: i
// segni e i bersagli dei rimandi vanno rimessi dove le parole stanno dopo
// ogni cambio di corpo, ma vivono nell'altro strato.
import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import type { Contents, Rendition } from 'epubjs'
import { clampFontScale, FONT_SCALE_STEP, saveFontScale } from './EpubReaderSettings'

// Distanza euclidea tra i due punti di tocco di un gesto pinch — unica
// funzione pura serve sia al touchmove sul container esterno sia a quello
// registrato dentro ogni documento iframe (vedi attachPinchZoomListeners).
function touchDistance(touches: TouchList): number {
  const a = touches[0]
  const b = touches[1]
  return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
}

interface ParametriGesti {
  renditionRef: RefObject<Rendition | null>
  containerRef: RefObject<HTMLDivElement | null>
  /** Il corpo del testo corrente (stato React della pagina). */
  fontScale: number
  setFontScale: (valore: number) => void
  prevPage: () => void
  nextPage: () => void
  /** Dal livello delle note: i segni vanno ridisegnati a fine gesto. */
  ridisegnaEvidenziazioni: () => void
  /** Dal livello delle note: i bersagli dei rimandi seguono il riflusso. */
  scheduleNoteHitboxes: () => void
}

export function useReaderGestures({
  renditionRef,
  containerRef,
  fontScale,
  setFontScale,
  prevPage,
  nextPage,
  ridisegnaEvidenziazioni,
  scheduleNoteHitboxes,
}: ParametriGesti) {
  // Quando l'ultimo gesto tattile e' stato gestito, per scartare il click
  // sintetico che il browser manda subito dopo. Vedi zonaClick.
  const ultimoToccoRef = useRef(0)
  // Gesto gia' servito durante il movimento: vedi zonaTouchMove.
  const gestoConsumatoRef = useRef(false)
  const attachedPinchDocsRef = useRef<WeakSet<Document>>(new WeakSet())
  const attachedHoverDocsRef = useRef<WeakSet<Document>>(new WeakSet())
  const attachedTapDocsRef = useRef<WeakSet<Document>>(new WeakSet())
  // Posizione+istante del touchstart a UN dito — null quando non c'è un tap
  // in corso (gesto a 2 dita, o già degenerato in trascinamento/selezione).
  // Letto al touchend per decidere se è stato un vero tap (vedi
  // isTap/attachTapNavigationListeners) o solo scartato.
  const tapStateRef = useRef<{ x: number; y: number; time: number } | null>(null)
  // null = niente vicino al bordo, altrimenti quale freccia mostrare — le
  // freccette restano nascoste durante la lettura e compaiono solo quando il
  // cursore si avvicina al bordo sinistro/destro (scelta del 2026-08-18),
  // sia sopra il wrapper esterno sia dentro l'iframe di
  // epub.js (la stragrande maggioranza dell'area lettore).
  const [hoverEdge, setHoverEdge] = useState<'left' | 'right' | null>(null)
  // Stato del gesto pinch in corso: distanza iniziale tra le due dita e
  // fontScale di partenza, così ogni touchmove calcola una nuova percentuale
  // relativa invece di accumulare deriva da un delta frame-a-frame.
  const salvaCorpoTimerRef = useRef<number | null>(null)
  const corpoDaApplicareRef = useRef<number | null>(null)
  const fotogrammaCorpoRef = useRef<number | null>(null)
  const pinchStateRef = useRef<{ distance: number; baseScale: number } | null>(null)
  // Specchio di fontScale leggibile dai listener touch registrati una sola
  // volta dentro ogni documento iframe (attachPinchZoomListeners) — stesso
  // motivo di highlightsRef sopra.
  const fontScaleRef = useRef(fontScale)

  useEffect(() => {
    fontScaleRef.current = fontScale
  }, [fontScale])

  // Applica la dimensione testo a rendition + stato React senza persisterla —
  // usata anche dal pinch, che la chiama molte volte per secondo durante il
  // gesto: scrivere su localStorage ad ogni touchmove non serve (solo il
  // valore finale conta) e sarebbe solo overhead sincrono nel bel mezzo del
  // gesto.
  /**
   * Applica una dimensione del testo durante un gesto, senza farlo a scatti.
   *
   * Il problema da cui nasce: un trackpad manda decine di eventi al secondo, e
   * per ognuno si faceva `themes.fontSize()` — che riflow l'INTERO capitolo —
   * piu' il ridisegno di tutte le evidenziazioni. Il risultato era un gesto a
   * scatti, con il testo che arrancava dietro alle dita.
   *
   * Due cose, e sono diverse:
   *
   * 1. **Si applica una volta per fotogramma**, non una per evento. Gli eventi
   *    in mezzo aggiornano solo il valore da raggiungere; disegna il browser,
   *    quando e' pronto lui.
   * 2. **Le evidenziazioni si ridisegnano alla FINE**, non durante. Durante il
   *    gesto il testo si sta muovendo comunque e rifare i rettangoli a ogni
   *    passo e' lavoro buttato; quello che conta e' che siano giusti quando ci
   *    si ferma.
   */
  function applyFontScaleLive(next: number) {
    const clamped = clampFontScale(next)
    if (clamped === fontScaleRef.current) return
    fontScaleRef.current = clamped
    corpoDaApplicareRef.current = clamped
    if (fotogrammaCorpoRef.current != null) return
    fotogrammaCorpoRef.current = window.requestAnimationFrame(() => {
      fotogrammaCorpoRef.current = null
      const valore = corpoDaApplicareRef.current
      if (valore == null) return
      corpoDaApplicareRef.current = null
      renditionRef.current?.themes.fontSize(`${valore}%`)
      setFontScale(valore)
    })
  }

  /** Fine del gesto: si rimettono i segni dove le parole stanno adesso. */
  function fineCambioCorpo() {
    saveFontScale(fontScaleRef.current)
    ridisegnaEvidenziazioni()
    scheduleNoteHitboxes()
  }

  /** I bottoni +/-: un colpo solo, si puo' fare tutto subito. */
  function applyFontScaleStep(next: number) {
    const clamped = clampFontScale(next)
    renditionRef.current?.themes.fontSize(`${clamped}%`)
    ridisegnaEvidenziazioni()
    // E anche i bersagli dei rimandi di nota, per la stessa ragione per cui
    // si ridisegnano i segni: cambiando il corpo del testo le parole si
    // spostano, e i rimandi con loro. Mancava, e `fineCambioCorpo` (la fine
    // del gesto di pizzico) lo faceva: la stessa cosa fatta in un modo e non
    // nell'altro.
    //
    // Su Safari non e' un dettaglio estetico ma la differenza fra un link che
    // funziona e uno che rompe la lettura: li' il click non arriva ai
    // listener dentro l'iframe (bug WebKit 218086, spiegato in
    // `refreshNoteHitboxes`), quindi passa per questi bersagli. Se restano
    // dov'erano, il click cade a vuoto E il browser segue il link, portando
    // l'iframe su un indirizzo che l'applicazione non ha.
    scheduleNoteHitboxes()
    fontScaleRef.current = clamped
    setFontScale(clamped)
  }

  /** I bottoni +/- e le scorciatoie: un colpo solo, si applica e si salva. */
  function commitFontScale(next: number) {
    applyFontScaleStep(next)
    saveFontScale(clampFontScale(next))
  }

  function stepFontScale(direction: 1 | -1) {
    commitFontScale(fontScale + direction * FONT_SCALE_STEP)
  }

  function handlePinchStart(e: TouchEvent) {
    if (e.touches.length === 2) {
      pinchStateRef.current = { distance: touchDistance(e.touches), baseScale: fontScaleRef.current }
    }
  }

  function handlePinchMove(e: TouchEvent) {
    const state = pinchStateRef.current
    if (e.touches.length !== 2 || !state) return
    // Impedisce lo zoom/scroll nativo del browser sul gesto a due dita —
    // senza, safari/chrome mobile provano a fare il proprio pinch-zoom della
    // pagina oltre (o al posto di) quello del reader.
    e.preventDefault()
    const distance = touchDistance(e.touches)
    if (distance <= 0) return
    applyFontScaleLive(state.baseScale * (distance / state.distance))
  }

  function handlePinchEnd(e: TouchEvent) {
    if (e.touches.length < 2 && pinchStateRef.current) {
      pinchStateRef.current = null
      fineCambioCorpo()
    }
  }

  // ── Il pinch del TRACKPAD, che e' un'altra cosa da quello a due dita ────
  //
  // I gestori qui sopra sono per il tocco, e su un telefono vanno bene. Ma su
  // un portatile il pinch del trackpad non e' un evento touch: Safari lo manda
  // come `gesturestart/gesturechange/gestureend` (con `e.scale` relativa
  // all'inizio del gesto), i browser basati su Chromium come un `wheel` con
  // `ctrlKey` acceso. Nessuno dei due era gestito, quindi il gesto cadeva
  // sullo zoom della PAGINA — che e' esattamente quello che non deve fare: il
  // testo di un libro si ingrandisce cambiando corpo e riflow, non ingrandendo
  // i pixel di tutta la finestra insieme alla barra e ai pannelli.

  interface EventoGesto extends Event { scale: number }

  function iniziaGesto(e: Event) {
    e.preventDefault()
    pinchStateRef.current = { distance: 1, baseScale: fontScaleRef.current }
  }

  function cambiaGesto(e: Event) {
    const state = pinchStateRef.current
    if (!state) return
    e.preventDefault()
    const scala = (e as EventoGesto).scale
    if (!Number.isFinite(scala) || scala <= 0) return
    applyFontScaleLive(state.baseScale * scala)
  }

  function finisceGesto(e: Event) {
    if (!pinchStateRef.current) return
    e.preventDefault()
    pinchStateRef.current = null
    fineCambioCorpo()
  }

  // Il pinch del trackpad su Chromium: un `wheel` con `ctrlKey`. Lo stesso
  // evento arriva da Ctrl+rotella con il mouse, e li' il significato e' lo
  // stesso — «ingrandisci» — quindi va bene trattarli insieme.
  function rotellaConCtrl(e: WheelEvent) {
    if (!e.ctrlKey) return
    e.preventDefault()
    // deltaY negativo = pinch in apertura.
    //
    // Il fattore era 0.01, cioe' fino al 10% a evento — e con decine di eventi
    // al secondo il corpo sbatteva da 80 a 200 in mezzo gesto. 0.0015 da' un
    // gesto che si puo' dosare: serve un movimento vero per attraversare tutta
    // la scala, che e' quello che ci si aspetta da un pinch.
    const fattore = 1 - e.deltaY * 0.0015
    applyFontScaleLive(fontScaleRef.current * fattore)
    if (salvaCorpoTimerRef.current) window.clearTimeout(salvaCorpoTimerRef.current)
    salvaCorpoTimerRef.current = window.setTimeout(fineCambioCorpo, 300)
  }

  /** Attacca i gesti del trackpad a un documento (l'iframe del libro o il nostro). */
  function attaccaGestiTrackpad(doc: Document | null | undefined) {
    if (!doc) return
    doc.addEventListener('gesturestart', iniziaGesto, { passive: false })
    doc.addEventListener('gesturechange', cambiaGesto, { passive: false })
    doc.addEventListener('gestureend', finisceGesto, { passive: false })
    doc.addEventListener('wheel', rotellaConCtrl as EventListener, { passive: false })
  }

  function staccaGestiTrackpad(doc: Document | null | undefined) {
    if (!doc) return
    doc.removeEventListener('gesturestart', iniziaGesto)
    doc.removeEventListener('gesturechange', cambiaGesto)
    doc.removeEventListener('gestureend', finisceGesto)
    doc.removeEventListener('wheel', rotellaConCtrl as EventListener)
  }

  // Stesso motivo di attachDirectSelectionListeners sopra: un touch a due
  // dita sul testo del libro avviene dentro il documento dell'iframe, i cui
  // eventi non risalgono al documento esterno — il pinch-to-zoom va quindi
  // intercettato qui, non (solo) sul container React.
  function attachPinchZoomListeners(contents: Contents) {
    const doc = contents.document
    if (!doc || attachedPinchDocsRef.current.has(doc)) return
    attachedPinchDocsRef.current.add(doc)
    doc.addEventListener('touchstart', handlePinchStart, { passive: true })
    doc.addEventListener('touchmove', handlePinchMove, { passive: false })
    doc.addEventListener('touchend', handlePinchEnd, { passive: true })
    attaccaGestiTrackpad(doc)
  }

  // Soglia in pixel entro cui il cursore "attiva" la freccetta più vicina —
  // stessa soglia usata sia sul wrapper esterno (onEdgeHoverMove sotto) sia
  // dentro ogni iframe (attachEdgeHoverListeners), così il comportamento non
  // cambia a seconda di dove si trova esattamente il cursore.
  const EDGE_HOVER_THRESHOLD = 110

  function edgeFromX(clientX: number, width: number): 'left' | 'right' | null {
    if (clientX <= EDGE_HOVER_THRESHOLD) return 'left'
    if (clientX >= width - EDGE_HOVER_THRESHOLD) return 'right'
    return null
  }

  function onEdgeHoverMove(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    setHoverEdge(edgeFromX(e.clientX - rect.left, rect.width))
  }

  // La maggior parte dell'area lettore è dentro l'iframe di epub.js, i cui
  // eventi mouse non risalgono al documento esterno (stesso motivo di
  // attachDirectSelectionListeners/attachPinchZoomListeners sopra) — senza
  // questo, avvicinarsi al bordo mentre il cursore è sul testo del libro non
  // farebbe comparire nulla.
  function attachEdgeHoverListeners(contents: Contents) {
    const doc = contents.document
    if (!doc || attachedHoverDocsRef.current.has(doc)) return
    attachedHoverDocsRef.current.add(doc)
    doc.addEventListener('mousemove', (e: MouseEvent) => {
      const width = doc.defaultView?.innerWidth || 800
      setHoverEdge(edgeFromX(e.clientX, width))
    })
    doc.addEventListener('mouseleave', () => setHoverEdge(null))
  }

  // Tocco singolo che si sposta <10px e dura <300ms — soglie standard per
  // distinguere un tap da un trascinamento (selezione testo, già gestita da
  // attachDirectSelectionListeners) o da un gesto pinch (handlePinchStart lo
  // intercetta per primo con touches.length===2, quindi qui arrivano solo
  // tocchi a un dito).
  const TAP_MAX_MOVE = 10
  const TAP_MAX_DURATION = 300

  function handleTapStart(e: TouchEvent) {
    if (e.touches.length !== 1) {
      tapStateRef.current = null
      return
    }
    const t = e.touches[0]
    tapStateRef.current = { x: t.clientX, y: t.clientY, time: Date.now() }
  }

  // width è la larghezza del documento/container in cui il tap è avvenuto —
  // dentro l'iframe è quella del suo defaultView (coordinate già relative al
  // proprio iframe, left=0), sul container esterno quella del proprio
  // elemento; `left` è l'offset da sottrarre a clientX per lo stesso motivo
  // per cui onEdgeHoverMove fa `e.clientX - rect.left` — il container
  // esterno non parte necessariamente dal bordo sinistro della finestra
  // (nessun "terzo" globale che ignori dove il container è davvero
  // posizionato).
  // Spostamento orizzontale oltre il quale il gesto e' uno scorrimento e non
  // un tocco storto. 45px su un telefono sono circa un centimetro: abbastanza
  // da essere intenzionale, abbastanza poco da non dover attraversare mezzo
  // schermo. Il confronto con lo spostamento verticale (1.5x) evita che uno
  // scorrimento in diagonale, o il gesto di selezione, volti pagina.
  const SWIPE_MIN = 45
  const SWIPE_MAX_DURATION = 800

  /** Pagina voltata da uno scorrimento, oppure false se il gesto non lo era. */
  function scorrimento(dx: number, dy: number, dt: number): boolean {
    if (Math.abs(dx) < SWIPE_MIN || Math.abs(dx) < Math.abs(dy) * 1.5 || dt > SWIPE_MAX_DURATION) return false
    // Si tira la pagina verso sinistra per andare avanti, come si gira un
    // foglio: la direzione e' quella del testo, non quella del bottone.
    if (dx < 0) nextPage()
    else prevPage()
    return true
  }

  // Le fasce laterali gestiscono il gesto per intero — tocco e scorrimento —
  // invece di affidarsi al click: un click sintetico arriverebbe anche in
  // fondo a uno scorrimento, voltando due pagine invece di una.
  /**
   * Il click che resta: le fasce sono <button> veri, non <div>, perche'
   * VoiceOver e gli altri lettori di schermo attivano un bottone generando
   * un click, non un tocco — con soli gestori touch sarebbero inattivabili.
   * Questo tiene a bada il doppione: un click che arriva subito dopo un
   * tocco gia' gestito viene ignorato.
   */
  function zonaClick(lato: 'sinistra' | 'destra') {
    if (Date.now() - ultimoToccoRef.current < 600) return
    if (lato === 'sinistra') prevPage()
    else nextPage()
  }

  function zonaTouchStart(e: React.TouchEvent) {
    const t = e.touches[0]
    tapStateRef.current = t ? { x: t.clientX, y: t.clientY, time: Date.now() } : null
    gestoConsumatoRef.current = false
  }

  /**
   * La pagina si volta appena il dito ha percorso abbastanza, non alla fine
   * del gesto.
   *
   * Non e' solo reattivita': decidere al `touchend` voleva dire non decidere
   * affatto quando il touchend non arriva. Su iOS trascinare verso destra
   * partendo da sinistra e' il gesto di sistema "torna indietro": il sistema
   * se lo prende, il nostro tocco viene ANNULLATO, e lo scorrimento
   * all'indietro non funzionava mai mentre quello in avanti si' (verificato
   * su iOS). Deciso durante il movimento, la pagina e' gia' voltata quando
   * il sistema interviene. Il `touch-action: none` sulle fasce chiede al
   * browser di non interpretare da se' i gesti che cominciano li'.
   */
  function zonaTouchMove(e: React.TouchEvent) {
    const start = tapStateRef.current
    if (!start || gestoConsumatoRef.current) return
    const t = e.touches[0]
    if (!t) return
    if (scorrimento(t.clientX - start.x, t.clientY - start.y, Date.now() - start.time)) {
      gestoConsumatoRef.current = true
      ultimoToccoRef.current = Date.now()
    }
  }

  function zonaTouchEnd(e: React.TouchEvent, lato: 'sinistra' | 'destra') {
    const start = tapStateRef.current
    tapStateRef.current = null
    const t = e.changedTouches[0]
    // Niente click sintetico dopo il tocco: il gesto lo gestiamo tutto qui, e
    // un click in coda a uno scorrimento volterebbe una seconda pagina.
    e.preventDefault()
    // Pagina gia' voltata durante il movimento: qui non resta niente da fare.
    if (gestoConsumatoRef.current) {
      gestoConsumatoRef.current = false
      return
    }
    if (!start || !t) return
    if (typeof window !== 'undefined' && window.getSelection()?.toString()) return
    ultimoToccoRef.current = Date.now()
    const dx = t.clientX - start.x
    const dy = t.clientY - start.y
    const dt = Date.now() - start.time
    if (scorrimento(dx, dy, dt)) return
    if (Math.abs(dx) > TAP_MAX_MOVE || Math.abs(dy) > TAP_MAX_MOVE || dt > TAP_MAX_DURATION) return
    if (lato === 'sinistra') prevPage()
    else nextPage()
  }

  function handleTapEnd(e: TouchEvent, width: number, left = 0) {
    const start = tapStateRef.current
    tapStateRef.current = null
    // Pagina gia' voltata mentre il dito si muoveva: vedi zonaTouchMove.
    if (gestoConsumatoRef.current) {
      gestoConsumatoRef.current = false
      return
    }
    if (!start) return
    // L'utente ha appena selezionato del testo (gestito da
    // attachDirectSelectionListeners) — un tap non deve anche voltare
    // pagina in quel caso.
    if (typeof window !== 'undefined' && window.getSelection()?.toString()) return
    const touch = e.changedTouches[0]
    if (!touch) return
    // Lo scorrimento vale anche qui, nel terzo centrale, sui browser che gli
    // eventi dell'iframe li consegnano: cosi' dove funziona si scorre da
    // tutta la pagina, non solo dai bordi.
    if (scorrimento(touch.clientX - start.x, touch.clientY - start.y, Date.now() - start.time)) return
    const dx = Math.abs(touch.clientX - start.x)
    const dy = Math.abs(touch.clientY - start.y)
    const dt = Date.now() - start.time
    if (dx > TAP_MAX_MOVE || dy > TAP_MAX_MOVE || dt > TAP_MAX_DURATION) return
    const x = touch.clientX - left
    if (x < width / 3) prevPage()
    else if (x > (width * 2) / 3) nextPage()
    // Terzo centrale: nessuna azione. La barra si scopre dalla fascia in
    // alto, e lasciare libero il centro vuol dire poterci ancora selezionare
    // il testo senza che ogni tocco volti pagina.
  }

  // Stesso pattern doppio-registro di attachPinchZoomListeners/
  // attachDirectSelectionListeners/attachEdgeHoverListeners: la maggior
  // parte dell'area lettore vive dentro l'iframe di epub.js, i cui eventi
  // touch non risalgono al documento esterno.
  function attachTapNavigationListeners(contents: Contents) {
    const doc = contents.document
    if (!doc || attachedTapDocsRef.current.has(doc)) return
    attachedTapDocsRef.current.add(doc)
    doc.addEventListener('touchstart', (e: TouchEvent) => {
      handleTapStart(e)
      gestoConsumatoRef.current = false
    }, { passive: true })
    doc.addEventListener('touchmove', (e: TouchEvent) => {
      const start = tapStateRef.current
      if (!start || gestoConsumatoRef.current) return
      const t = e.touches[0]
      if (!t) return
      if (scorrimento(t.clientX - start.x, t.clientY - start.y, Date.now() - start.time)) {
        gestoConsumatoRef.current = true
      }
    }, { passive: true })
    doc.addEventListener('touchend', (e: TouchEvent) => {
      // I terzi vanno misurati sulla PAGINA, non sull'iframe: impaginato a
      // colonne, l'iframe e' largo quanto tutto il capitolo e scorre dentro
      // il contenitore, quindi il suo innerWidth e' un numero enorme. Usarlo
      // voleva dire che praticamente ogni tocco cadeva nel "terzo sinistro" —
      // toccare in mezzo alla pagina tornava indietro di una pagina, su
      // Android e su Chrome desktop con schermo tattile.
      const pagina = containerRef.current?.getBoundingClientRect()
      const cornice = doc.defaultView?.frameElement?.getBoundingClientRect()
      if (!pagina || !cornice) return
      handleTapEnd(e, pagina.width, pagina.left - cornice.left)
    }, { passive: true })
  }

  return {
    // Stato e setter dei bordi attivi (le freccette ai lati).
    hoverEdge,
    setHoverEdge,
    onEdgeHoverMove,
    // I bottoni +/- del pannello impostazioni.
    stepFontScale,
    // Pinch a due dita: la pagina li aggancia anche al container esterno.
    handlePinchStart,
    handlePinchMove,
    handlePinchEnd,
    // Pinch del trackpad sul documento esterno (aggancio e pulizia).
    attaccaGestiTrackpad,
    staccaGestiTrackpad,
    // I tre registri dentro ogni documento iframe del libro.
    attachPinchZoomListeners,
    attachEdgeHoverListeners,
    attachTapNavigationListeners,
    // Tap e scorrimenti sul wrapper esterno del libro.
    handleTapStart,
    handleTapEnd,
    // Le fasce laterali col dito.
    zonaClick,
    zonaTouchStart,
    zonaTouchMove,
    zonaTouchEnd,
    // Esposti per onTouchCancel delle fasce, che li azzera direttamente.
    tapStateRef,
    gestoConsumatoRef,
  }
}
