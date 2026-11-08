import { useCallback, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Download, RotateCcw, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import {
  exportAnnotations,
  confermaCestino,
  purgeHighlight,
  restoreHighlight,
  retryFailedPositions,
  trashHighlight,
  updateHighlightNotes,
} from '@/lib/annotationActions'
import { useAnnotationDevices, useAnnotations } from '@/lib/annotationQueries'
import { openBookInReader } from '@/lib/readerActions'
import { useVistaAnnotazioni, VISTE } from '@/lib/annotationsView'
import { numero, useLingua } from '@/lib/i18n'
import type { Highlight } from '@/types/annotation'
import { ExportDialog } from './ExportDialog'
import { VistaIndice } from './VistaIndice'
import { VistaLettura } from './VistaLettura'
import { VistaScaffale, type ChiaveScaffale } from './VistaScaffale'

type Feedback = { kind: 'error' | 'info'; text: string }

// Porting 1:1 della pagina Annotazioni di frontend/src/App.vue
// (activePage === 'annotations'): filtri (tab attive/cestino, ricerca estesa
// a testo/nota/autore/capitolo/dispositivo, filtro dispositivo, solo con
// note), 4 modalità di raggruppamento, azioni singole e massive, export
// client-side. "Apri nel Reader" (vedi AnnotationRow) apre il web reader
// EPUB con deep-link alla posizione dell'evidenziazione (cfi_start).
export function AnnotationsPage() {
  const { t } = useLingua()
  useSetPageHeader(t('annotations.pageTitle'))
  const queryClient = useQueryClient()
  const { data: highlights = [], isLoading } = useAnnotations()
  const { data: devices = [] } = useAnnotationDevices()

  const [tab, setTab] = useState<'active' | 'trashed'>('active')
  const [vista, cambiaVista] = useVistaAnnotazioni()
  // Dove si è dentro lo Scaffale: per cosa è raggruppato, e quale scheda è
  // aperta. Vivono qui e non nella vista perché cambiando vista e tornando
  // indietro ci si aspetta di ritrovare il libro che si stava guardando.
  const [perScaffale, setPerScaffale] = useState<ChiaveScaffale>('libro')
  const [apertoScaffale, setApertoScaffale] = useState<string | null>(null)
  const [deviceFilter, setDeviceFilter] = useState('all')
  const [notesFilter, setNotesFilter] = useState<'all' | 'with' | 'without'>('all')
  const [searchText, setSearchText] = useState('')
  const [showExportDialog, setShowExportDialog] = useState(false)
  const [feedback, setFeedback] = useState<Feedback | null>(null)

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['annotations'] })
  }

  // Sempre su TUTTO, non su quello che i filtri lasciano passare: è il
  // contesto, cioè la cosa che non deve cambiare mentre si cerca. Un totale
  // che si muove insieme al filtro è un secondo conteggio dei risultati, e
  // quello c'è già dentro ogni gruppo.
  const contesto = useMemo(() => {
    const attive = highlights.filter((h) => !h.trashed)
    return {
      annotazioni: attive.length,
      libri: new Set(attive.map((h) => h.book_title || '—')).size,
      autori: new Set(attive.map((h) => h.book_author || '—')).size,
      conNota: attive.filter((h) => (h.notes || '').trim()).length,
      cestinate: highlights.length - attive.length,
    }
  }, [highlights])

  const deviceOptions = useMemo(
    () => [
      { value: 'all', label: t('annotations.device.all') },
      { value: 'web', label: `🌐 ${t('annotations.device.webReader')}` },
      { value: 'calibre', label: '📚 Calibre' },
      ...devices.map((d) => ({ value: `device:${d.id}`, label: `📱 ${d.name}` })),
    ],
    [devices, t]
  )

  const filtered = useMemo(() => {
    let list = highlights.filter((h) => h.trashed === (tab === 'trashed'))

    if (notesFilter === 'with') list = list.filter((h) => h.notes.trim() !== '')
    else if (notesFilter === 'without') list = list.filter((h) => h.notes.trim() === '')

    if (deviceFilter !== 'all') {
      if (deviceFilter.startsWith('device:')) {
        const id = Number(deviceFilter.slice('device:'.length))
        list = list.filter((h) => h.source === 'device' && h.device_id === id)
      } else {
        list = list.filter((h) => (h.source || 'web') === deviceFilter)
      }
    }

    const text = searchText.toLowerCase().trim()
    if (text) {
      const has = (v: string | null | undefined) => !!v && v.toLowerCase().includes(text)
      list = list.filter((h) => has(h.text) || has(h.notes) || has(h.book_title) || has(h.book_author) || has(h.chapter) || has(h.device_name))
    }

    return list
  }, [highlights, tab, notesFilter, deviceFilter, searchText])

  // Le azioni di un passaggio, una volta sola: le tre viste mostrano lo stesso
  // passaggio e devono poterci fare le stesse cose.
  const azioni = useCallback(
    (hl: Highlight) => ({
      onToggleTrash: () => void handleToggleTrash(hl),
      onPurge: () => void handlePurge(hl),
      onNotesChange: (notes: string) => void handleNotesChange(hl, notes),
      onOpenBook: () => handleOpenBook(hl),
    }),
    // Le funzioni sono ridefinite ad ogni render ma non chiudono su stato che
    // conti: ricrearle qui ad ogni render costerebbe di più del guadagno.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  )

  const failedPositionCount = useMemo(() => highlights.filter((h) => h.position_status === 'failed').length, [highlights])

  async function handleNotesChange(hl: Highlight, notes: string) {
    try {
      await updateHighlightNotes(hl, notes)
      invalidate()
    } catch {
      setFeedback({ kind: 'error', text: t('annotations.error.saveNote') })
    }
  }

  async function handleToggleTrash(hl: Highlight) {
    // La conferma solo nel verso che toglie: ripristinare non ha bisogno di
    // essere difeso, e chiedere anche lì renderebbe la domanda un rumore.
    if (!hl.trashed && !confermaCestino(hl)) return
    try {
      if (hl.trashed) await restoreHighlight(hl)
      else await trashHighlight(hl)
      invalidate()
    } catch {
      setFeedback({ kind: 'error', text: t('annotations.error.moveToTrash') })
    }
  }

  async function handlePurge(hl: Highlight) {
    if (!window.confirm(t('annotations.confirmPurge'))) return
    try {
      await purgeHighlight(hl)
      invalidate()
    } catch {
      setFeedback({ kind: 'error', text: t('annotations.error.purge') })
    }
  }


  // Il formato lo dice l'highlight (book_formats, aggiunto al payload),
  // non lo si dà per scontato. Qui c'era scritto "le evidenziazioni esistono
  // solo per libri EPUB, nessun percorso di sync da dispositivo produce
  // highlight su un PDF" e si passava sempre ['EPUB']: non è vero — devices.py
  // ha un ramo di deduplica apposta per i PDF, dove pos0 (xpointer crengine,
  // che esiste solo per gli EPUB) manca e si ricade su pagina+testo. Su un
  // libro di solo PDF si apriva quindi il lettore EPUB, che mostrava
  // "Impossibile caricare il libro nel web reader" su un libro sanissimo.
  function handleOpenBook(hl: Highlight) {
    if (hl.is_orphan) {
      setFeedback({ kind: 'info', text: t('annotations.error.orphanNote') })
      return
    }
    if (hl.calibre_book_id == null || hl.library == null) return
    void openBookInReader(
      { id: hl.calibre_book_id, title: hl.book_title || '', formats: hl.book_formats || [] },
      hl.library,
      // Il testo viaggia SEMPRE, anche quando c'e' un'ancora: se quella non
      // regge (nota vecchia, file reimportato, conversione da KOReader mai
      // riuscita) il lettore la ritrova cercando il testo, invece di aprire
      // il libro dove capita.
      { cfi: hl.cfi_start ?? undefined, notaTesto: hl.text || undefined, notaId: hl.id }
    ).then((aperto) => {
      if (!aperto) {
        setFeedback({ kind: 'info', text: t('annotations.error.unsupportedFormat') })
      }
    })
  }

  async function handleRetryFailed() {
    try {
      const reset = await retryFailedPositions()
      invalidate()
      setFeedback({ kind: 'info', text: t('annotations.retry.success', { n: reset }) })
    } catch {
      setFeedback({ kind: 'error', text: t('annotations.error.retry') })
    }
  }

  // Scarica SEMPRE tutte le evidenziazioni, non solo quelle che
  // corrispondono ai filtri/ricerca correnti in vista — il download è un
  // backup, non un'esportazione "di quello che sto guardando ora", e
  // filtrarlo silenziosamente in base a un filtro dimenticato attivo era
  // sorprendente. Include sia attive che cestinate: "tutte" senza eccezioni.
  function handleExportRequest() {
    if (highlights.length === 0) {
      setFeedback({ kind: 'error', text: t('annotations.error.nothingToExport') })
      return
    }
    setShowExportDialog(true)
  }

  async function handleExport(format: 'md' | 'html', scope: 'single' | 'multi') {
    const { groupCount } = await exportAnnotations(highlights, format, scope)
    setShowExportDialog(false)
    setFeedback({
      kind: 'info',
      text: t('annotations.export.success', { n: highlights.length, format: format.toUpperCase(), groupCount }),
    })
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Quanto c'è, prima di qualunque filtro.
          Scelta del 01/10/2026, primo passo del ridisegno: la
          pagina si apriva su un elenco senza dire di cosa fosse l'elenco. Tre
          numeri, e sono i tre che danno la misura della cosa — quante
          annotazioni, da quanti libri, di quanti autori. Il cestino compare
          solo quando non è vuoto: un «0 nel cestino» sempre presente è una
          riga che si impara a non leggere. */}
      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[13px] text-muted-foreground">
        <b className="font-serif text-[20px] font-semibold text-foreground tabular-nums">
          {numero(contesto.annotazioni)}
        </b>
        {t('authors.readingStrip.highlights', { count: contesto.annotazioni, n: contesto.annotazioni })}
        <span className="text-muted-foreground/50">·</span>
        <span className="tabular-nums text-foreground">{contesto.libri}</span>
        {t('annotations.count.books', { count: contesto.libri, n: contesto.libri })}
        <span className="text-muted-foreground/50">·</span>
        <span className="tabular-nums text-foreground">{contesto.autori}</span>
        {t('annotations.count.authors', { count: contesto.autori, n: contesto.autori })}
        {contesto.conNota > 0 && (
          <>
            <span className="text-muted-foreground/50">·</span>
            <span className="tabular-nums text-foreground">{contesto.conNota}</span>
            {t('annotations.count.withYourNote')}
          </>
        )}
        {contesto.cestinate > 0 && (
          <>
            <span className="text-muted-foreground/50">·</span>
            <button
              type="button"
              onClick={() => setTab('trashed')}
              className="underline decoration-dotted underline-offset-2 hover:text-foreground"
            >
              {contesto.cestinate} {t('annotations.count.inTrash')}
            </button>
          </>
        )}
      </p>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card p-3">
        <div className="flex gap-1 border-r border-border pr-2">
          <Button
            variant={tab === 'active' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setTab('active')}
          >
            {t('annotations.tab.active')}
          </Button>
          <Button variant={tab === 'trashed' ? 'secondary' : 'ghost'} size="sm" onClick={() => setTab('trashed')}>
            {t('annotations.tab.trash')}
          </Button>
        </div>

        <div className="relative min-w-[240px] flex-1 basis-[280px]">
          <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground/70" />
          <input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder={t('annotations.search.placeholder')}
            className="w-full rounded-md border border-border bg-background py-1.5 pr-2.5 pl-7 text-[13px] outline-none focus:border-primary"
          />
        </div>

        {/* Le tre viste, non un menù: sono tre e vanno provate, e un menù per
            tre voci nasconde due terzi di quello che c'è da provare. Il
            raggruppamento per libro e per autore non è sparito, è diventato
            lo Scaffale — che è la stessa idea con una forma migliore. */}
        <div className="flex gap-1">
          {VISTE(t).map((v) => (
            <Button
              key={v.id}
              variant={vista === v.id ? 'secondary' : 'ghost'}
              size="sm"
              title={v.a_cosa_serve}
              onClick={() => cambiaVista(v.id)}
            >
              {v.nome}
            </Button>
          ))}
        </div>

        <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
          {t('annotations.filter.deviceLabel')}
          <Select value={deviceFilter} onValueChange={setDeviceFilter}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {deviceOptions.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
          {t('annotations.filter.notesLabel')}
          <Select value={notesFilter} onValueChange={(v) => setNotesFilter(v as 'all' | 'with' | 'without')}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('annotations.notesFilter.all')}</SelectItem>
              <SelectItem value="with">💬 {t('annotations.notesFilter.withNotes')}</SelectItem>
              <SelectItem value="without">{t('annotations.notesFilter.withoutNotes')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {failedPositionCount > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleRetryFailed}
            title={t('annotations.retry.title')}
          >
            <RotateCcw className="size-3.5" />
            {t('annotations.retry.button', { n: failedPositionCount })}
          </Button>
        )}

        <Button variant="ghost" size="icon-sm" className="ml-auto" onClick={handleExportRequest} title={t('annotations.export.button')}>
          <Download className="size-4" />
        </Button>
      </div>


      {feedback && <p className={feedback.kind === 'error' ? 'text-[12.5px] text-destructive' : 'text-[12.5px] text-muted-foreground'}>{feedback.text}</p>}

      {isLoading && <p className="text-muted-foreground">{t('common.loading')}</p>}

      {!isLoading && filtered.length === 0 && (
        <div className="rounded-lg border border-dashed border-border py-10 text-center text-muted-foreground">
          {t('annotations.empty.noMatch')}
        </div>
      )}

      {!isLoading && filtered.length > 0 && vista === 'lettura' && (
        <VistaLettura passaggi={filtered} azioni={azioni} cerca={searchText} />
      )}

      {!isLoading && filtered.length > 0 && vista === 'scaffale' && (
        <VistaScaffale
          passaggi={filtered}
          azioni={azioni}
          per={perScaffale}
          onPer={setPerScaffale}
          aperto={apertoScaffale}
          onApri={setApertoScaffale}
          cerca={searchText}
        />
      )}

      {!isLoading && filtered.length > 0 && vista === 'indice' && (
        <VistaIndice passaggi={filtered} azioni={azioni} cerca={searchText} />
      )}

      {showExportDialog && <ExportDialog onClose={() => setShowExportDialog(false)} onExport={handleExport} />}
    </div>
  )
}
