// Reader PDF (Fase 9) — porting 1:1 del comportamento di
// frontend/src/PdfReaderView.vue in React/TS. Apre in una finestra propria
// (vedi pdf-reader.html / src/pdf-reader-main.tsx), niente React Router:
// tutti i parametri arrivano da window.location.search. Molto più semplice
// del reader EPUB (nessun highlight, nessuna ricerca, nessun deep-link):
// singolo canvas, una pagina alla volta, posizione = solo percentuale.
// Bug reale riscontrato in uso e risolto (il reader PDF non si apriva
// affatto): package.json era fermo su pdfjs-dist ^6.2.108. La
// libreria 6.x (verificato anche su 6.3.289) chiama internamente
// Map.prototype.getOrInsertComputed durante page.render() — un metodo Map
// nativo troppo recente, non ancora presente nei browser stabili testati
// (Chromium 140) — che fa fallire OGNI rendering di pagina con
// "TypeError: ...getOrInsertComputed is not a function" (la pagina restava
// bloccata su "Impossibile caricare il PDF."). Il catch dell'effetto di
// caricamento inghiottiva l'errore reale senza mai loggarlo (vedi sotto),
// per questo il sintomo sembrava un generico "non funziona" senza indizi.
// Fix: downgrade a pdfjs-dist 5.4.624 (ultima della serie 5.x, senza questa
// dipendenza) — verificato con un rendering reale end-to-end (caricamento,
// cambio pagina, zoom). NON risalire alla 6.x senza riverificare prima che
// questo metodo sia davvero disponibile nei browser target.
import { useCallback, useEffect, useRef, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import type { PDFDocumentLoadingTask, PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist'
// Import Vite-friendly del worker: `?url` fa sì che Vite serva/impacchetti il
// file del worker come asset (URL stringa), non il suo contenuto — è il modo
// più comune per rompere pdf.js con Vite se sbagliato. Stesso pattern del
// Vue esistente.
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { ChevronLeft, ChevronRight, Minus, Plus, Scan, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { downloadFormatUrl } from '@/lib/bookActions'
import { withBackendUrl } from '@/lib/api'
import { authHeaders } from '@/lib/auth'
import { getReadingPosition, putReadingPosition } from '@/lib/readingPositionActions'
import { useStyleVariant } from '@/lib/useStyleVariant'
import { useLingua } from '@/lib/i18n'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

const ZOOM_STEP = 1.2
const MIN_SCALE = 0.25
const MAX_SCALE = 5
const SAVE_DEBOUNCE_MS = 2000
const RESIZE_DEBOUNCE_MS = 150

function fitWidthScale(page: PDFPageProxy, container: HTMLDivElement | null): number {
  if (!container) return 1
  const baseViewport = page.getViewport({ scale: 1 })
  // Piccolo margine perché la pagina non tocchi i bottoni di navigazione ai
  // bordi.
  const available = Math.max(100, container.clientWidth - 24)
  return available / baseViewport.width
}

export function PdfReaderPage() {
  useStyleVariant()
  const { t } = useLingua()

  const params = new URLSearchParams(window.location.search)
  const bookId = Number(params.get('bookId'))
  const library = params.get('library') || 'default'
  const format = params.get('format') || 'PDF'
  const ingestId = params.get('ingestId')
  const isIngestPreview = !!ingestId
  const bookTitle = params.get('title') || ''

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const [numPages, setNumPages] = useState(0)
  const [fitWidth, setFitWidthState] = useState(true)

  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // Stato imperativo "non reattivo" (equivalente alle variabili di modulo
  // del Vue esistente) — evita chiusure stantie nei callback async senza
  // dover ricreare quest'ultimi a ogni render.
  const pdfDocRef = useRef<PDFDocumentProxy | null>(null)
  // `destroy()` vive sul loading task restituito da `getDocument()`, non sul
  // `PDFDocumentProxy` risolto — va tenuto da parte per poterlo annullare.
  const loadingTaskRef = useRef<PDFDocumentLoadingTask | null>(null)
  const renderTaskRef = useRef<RenderTask | null>(null)
  const renderSeqRef = useRef(0) // guardia anti out-of-order su render async (page flip rapidi)
  const currentPageRef = useRef(1)
  const numPagesRef = useRef(0)
  const currentScaleRef = useRef(1) // scala effettiva; ricalcolata dalla larghezza del container quando fitWidth è attivo
  const fitWidthRef = useRef(true)
  const savePositionTimerRef = useRef<number | null>(null)
  const resizeTimerRef = useRef<number | null>(null)

  const pushReadingPosition = useCallback(
    async (percentage: number, opts?: { keepalive?: boolean }) => {
      if (isIngestPreview || percentage == null) return
      try {
        await putReadingPosition(library, bookId, { percentage, cfi: null }, opts)
      } catch {
        // Best-effort — il prossimo cambio pagina (o il flush finale alla
        // chiusura) riprova.
      }
    },
    [isIngestPreview, library, bookId]
  )

  const scheduleSavePosition = useCallback(() => {
    if (isIngestPreview || !numPagesRef.current) return
    if (savePositionTimerRef.current !== null) window.clearTimeout(savePositionTimerRef.current)
    // Debounced: conta solo l'ULTIMA posizione prima che il reader si
    // chiuda/si fermi.
    savePositionTimerRef.current = window.setTimeout(() => {
      pushReadingPosition(currentPageRef.current / numPagesRef.current)
    }, SAVE_DEBOUNCE_MS)
  }, [isIngestPreview, pushReadingPosition])

  const flushReadingPosition = useCallback(() => {
    if (savePositionTimerRef.current !== null) window.clearTimeout(savePositionTimerRef.current)
    if (numPagesRef.current) {
      pushReadingPosition(currentPageRef.current / numPagesRef.current, { keepalive: true })
    }
  }, [pushReadingPosition])

  const renderPage = useCallback(
    async (pageNum: number) => {
      const pdfDoc = pdfDocRef.current
      if (!pdfDoc) return
      const seq = ++renderSeqRef.current
      if (renderTaskRef.current) {
        try {
          renderTaskRef.current.cancel()
        } catch {
          // no-op
        }
      }
      const page = await pdfDoc.getPage(pageNum)
      if (seq !== renderSeqRef.current) return // un render più recente ha già superato questo

      if (fitWidthRef.current) currentScaleRef.current = fitWidthScale(page, containerRef.current)
      const viewport = page.getViewport({ scale: currentScaleRef.current })
      const canvas = canvasRef.current
      if (!canvas) return

      // Nitido su schermi retina: il backing store del canvas è DPR volte
      // più grande della dimensione CSS, e il render viene scalato su
      // tramite il parametro transform.
      const dpr = window.devicePixelRatio || 1
      canvas.width = Math.floor(viewport.width * dpr)
      canvas.height = Math.floor(viewport.height * dpr)
      canvas.style.width = `${Math.floor(viewport.width)}px`
      canvas.style.height = `${Math.floor(viewport.height)}px`

      const renderTask = page.render({
        canvas,
        viewport,
        transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
      })
      renderTaskRef.current = renderTask
      try {
        await renderTask.promise
      } catch (e) {
        if (e instanceof Error && e.name === 'RenderingCancelledException') return
        throw e
      }
      if (seq !== renderSeqRef.current) return

      currentPageRef.current = pageNum
      setCurrentPage(pageNum)
      scheduleSavePosition()
      // Una nuova pagina si legge sempre dall'inizio.
      if (containerRef.current) containerRef.current.scrollTop = 0
    },
    [scheduleSavePosition]
  )

  const goToPage = useCallback(
    (pageNum: number) => {
      if (!pdfDocRef.current) return
      const target = Math.min(Math.max(1, pageNum), numPagesRef.current)
      if (target === currentPageRef.current && renderSeqRef.current > 0) return
      renderPage(target).catch(() => setError(t('reader.pdf.pageRenderFailed')))
    },
    [renderPage, t]
  )

  const prevPage = useCallback(() => goToPage(currentPageRef.current - 1), [goToPage])
  const nextPage = useCallback(() => goToPage(currentPageRef.current + 1), [goToPage])

  const rerenderCurrent = useCallback(() => {
    if (pdfDocRef.current) renderPage(currentPageRef.current).catch(() => {})
  }, [renderPage])

  const zoomIn = useCallback(() => {
    fitWidthRef.current = false
    setFitWidthState(false)
    currentScaleRef.current = Math.min(MAX_SCALE, currentScaleRef.current * ZOOM_STEP)
    rerenderCurrent()
  }, [rerenderCurrent])

  const zoomOut = useCallback(() => {
    fitWidthRef.current = false
    setFitWidthState(false)
    currentScaleRef.current = Math.max(MIN_SCALE, currentScaleRef.current / ZOOM_STEP)
    rerenderCurrent()
  }, [rerenderCurrent])

  const setFitWidth = useCallback(() => {
    fitWidthRef.current = true
    setFitWidthState(true)
    rerenderCurrent()
  }, [rerenderCurrent])

  useEffect(() => {
    if (!isIngestPreview && (!bookId || !library)) {
      setError(t('reader.error.missingParams'))
      setLoading(false)
      return
    }

    let cancelled = false

    const onKeydown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') prevPage()
      else if (e.key === 'ArrowRight') nextPage()
      else if (e.key === '+' || e.key === '=') zoomIn()
      else if (e.key === '-') zoomOut()
    }

    // Mentre fit-width è attivo, un resize della finestra cambia la scala
    // giusta.
    const onResize = () => {
      if (!fitWidthRef.current) return
      if (resizeTimerRef.current !== null) window.clearTimeout(resizeTimerRef.current)
      resizeTimerRef.current = window.setTimeout(rerenderCurrent, RESIZE_DEBOUNCE_MS)
    }

    window.addEventListener('keydown', onKeydown)
    window.addEventListener('resize', onResize)
    window.addEventListener('beforeunload', flushReadingPosition)

    void (async () => {
      const url = isIngestPreview
        ? withBackendUrl(`/api/kolibre/ingest/${ingestId}/file`)
        : downloadFormatUrl(library, bookId, format)
      try {
        // Entrambi gli endpoint sono autenticati (il /download di un libro
        // reale lo è diventato quando l'auth è passata a livello di router in
        // main.py), quindi l'header serve sempre.
        const res = await fetch(url, { headers: await authHeaders() })
        if (!res.ok) throw new Error(`download HTTP ${res.status}`)
        const buffer = await res.arrayBuffer()
        if (cancelled) return

        const loadingTask = pdfjsLib.getDocument({ data: buffer })
        loadingTaskRef.current = loadingTask
        const pdfDoc = await loadingTask.promise
        if (cancelled) {
          try {
            loadingTask.destroy()
          } catch {
            // no-op
          }
          return
        }
        pdfDocRef.current = pdfDoc
        numPagesRef.current = pdfDoc.numPages
        setNumPages(pdfDoc.numPages)

        // Riparte dalla posizione salvata (solo percentuale), se presente —
        // saltato del tutto per un file di staging, che non ha una
        // posizione stabile da riprendere.
        let startPage = 1
        if (!isIngestPreview) {
          try {
            const saved = await getReadingPosition(library, bookId)
            if (saved && saved.percentage != null) {
              startPage = Math.min(Math.max(1, Math.round(saved.percentage * pdfDoc.numPages)), pdfDoc.numPages)
            }
          } catch {
            // Best-effort — si parte da pagina 1.
          }
        }
        if (cancelled) return

        await renderPage(startPage)
        if (!cancelled) setLoading(false)
      } catch (e) {
        // Prima qui l'errore reale veniva inghiottito senza mai loggarlo —
        // "non funziona" senza indizi, vedi il commento sulla versione di
        // pdfjs-dist in cima al file per il bug reale che questo ha nascosto.
        console.error('[PdfReaderPage] load/render failed', e)
        if (!cancelled) {
          setLoading(false)
          setError(t('reader.pdf.loadFailed'))
        }
      }
    })()

    return () => {
      cancelled = true
      window.removeEventListener('keydown', onKeydown)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('beforeunload', flushReadingPosition)
      flushReadingPosition()
      if (renderTaskRef.current) {
        try {
          renderTaskRef.current.cancel()
        } catch {
          // no-op
        }
      }
      if (loadingTaskRef.current) {
        try {
          loadingTaskRef.current.destroy()
        } catch {
          // no-op
        }
        loadingTaskRef.current = null
      }
      pdfDocRef.current = null
    }
    // Effetto di montaggio, eseguito una sola volta come l'onMounted del Vue
    // esistente — i valori derivati dai parametri URL non cambiano nella
    // vita di questa pagina (finestra dedicata a un solo libro).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const locationLabel = numPages
    ? t('reader.pdf.pageLabel', { page: currentPage, total: numPages, percent: Math.round((currentPage / numPages) * 100) })
    : ''

  return (
    <div className="fixed inset-0 flex flex-col bg-background font-sans text-foreground">
      <div className="flex h-[50px] shrink-0 items-center gap-4 border-b border-border bg-card px-4">
        <span className="flex-1 truncate font-serif text-[15px] font-semibold">{bookTitle}</span>
        {isIngestPreview && (
          <span
            className="cursor-help whitespace-nowrap rounded-md bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground"
            title={t('reader.ingestPreview.tooltip')}
          >
            {t('reader.ingestPreview.badge')}
          </span>
        )}
        <span className="whitespace-nowrap text-[12px] text-muted-foreground">{locationLabel}</span>
        <div className="flex items-center gap-0.5">
          <Button variant="ghost" size="icon-sm" title={t('reader.pdf.zoomOutTitle')} onClick={zoomOut}>
            <Minus className="size-4" />
          </Button>
          <Button
            variant={fitWidth ? 'secondary' : 'ghost'}
            size="icon-sm"
            title={t('reader.pdf.fitWidthTitle')}
            onClick={setFitWidth}
          >
            <Scan className="size-4" />
          </Button>
          <Button variant="ghost" size="icon-sm" title={t('reader.pdf.zoomInTitle')} onClick={zoomIn}>
            <Plus className="size-4" />
          </Button>
        </div>
        <Button variant="ghost" size="icon-sm" title={t('common.close')} onClick={() => window.close()}>
          <X className="size-4" />
        </Button>
      </div>

      <div className="relative flex flex-1 overflow-hidden">
        <button
          className="absolute top-1/2 left-2 z-10 flex size-9 -translate-y-1/2 items-center justify-center rounded-full bg-card/80 text-foreground shadow-md hover:bg-card"
          title={t('reader.nav.prevPageTitle')}
          onClick={prevPage}
        >
          <ChevronLeft className="size-5" />
        </button>

        <div ref={containerRef} className="flex flex-1 min-w-0 items-start justify-center overflow-auto bg-muted px-0 py-4">
          <canvas ref={canvasRef} className="mx-auto block bg-white shadow-lg" />
        </div>

        <button
          className="absolute top-1/2 right-2 z-10 flex size-9 -translate-y-1/2 items-center justify-center rounded-full bg-card/80 text-foreground shadow-md hover:bg-card"
          title={t('reader.nav.nextPageTitle')}
          onClick={nextPage}
        >
          <ChevronRight className="size-5" />
        </button>

        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background font-serif text-[15px]">
            {t('reader.pdf.loading')}
          </div>
        )}
        {error && !loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background font-serif text-[15px] text-destructive">
            {error}
          </div>
        )}
      </div>
    </div>
  )
}
