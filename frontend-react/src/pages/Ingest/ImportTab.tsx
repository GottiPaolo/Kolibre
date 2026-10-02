import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Loader2, Trash2, Upload, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useLibraries } from '@/lib/queries'
import {
  useIngestBooks, useIngestPage, useIngestPagination, useIngestImportJob, useIngestDuplicati,
  startIngestImportJob, stopIngestImportJob, INGEST_QUERY_KEY, INGEST_JOB_KEY,
} from '@/lib/ingestQueries'
import { aBatch } from '@/lib/aBatch'
import { api } from '@/lib/api'
import { uploadIngestFiles, importIngestBook, discardIngestItem, ingestFileUrl } from '@/lib/ingestActions'
import { openIngestBookInReader } from '@/lib/readerActions'
import { INGEST_ACCEPT, type IngestedBook, type IngestRejectedFile } from '@/types/ingest'
import { LibraryPickerButton } from '@/components/LibraryPickerButton'
import { IngestCard } from './IngestCard'
import { EditIngestMetadataDialog, type IngestMetadataEdits } from './EditIngestMetadataDialog'
import { numero, useLingua } from '@/lib/i18n'

function errorDetail(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'detail' in err && typeof (err as { detail?: unknown }).detail === 'string') {
    return (err as { detail: string }).detail
  }
  return fallback
}

// Porting di App.vue's activePage === 'ingest' (Fase 7): staging folder,
// upload multipart, drag&drop, importazione singola/massiva verso una
// libreria di destinazione. Decisioni di scope rispetto al Vue originale
// sono commentate punto per punto qui sotto e nel report della fase.
export function ImportTab() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: libraries = [] } = useLibraries()
  // ── Tanti file da rivedere ──
  // Ogni voce e' una scheda con copertina e comandi: oltre la soglia
  // (Impostazioni ▸ Sistema) si chiede una pagina per volta invece di
  // disegnarne migliaia.
  const { data: infoPag } = useIngestPagination()
  const impaginata = infoPag?.paginated ?? false
  const dimPagina = infoPag?.page_size ?? 100
  const [pagina, setPagina] = useState(0)
  const { data: tuttiIngest = [], isLoading: caricaTutti } = useIngestBooks(!impaginata)
  const paginaQuery = useIngestPage({ offset: pagina * dimPagina, limit: dimPagina }, impaginata)
  const ingestBooks = impaginata ? (paginaQuery.data?.items ?? []) : tuttiIngest
  const isLoading = impaginata ? paginaQuery.isLoading : caricaTutti
  const totaleInStaging = impaginata ? (paginaQuery.data?.total ?? 0) : tuttiIngest.length

  // Avanzamento di "Scarta tutti", che resta un ciclo qui nella pagina: e'
  // un'operazione molto piu' leggera per file, e non vale un lavoro sul
  // server. L'IMPORTAZIONE invece vive sul server, vedi lavoro qui sotto.
  const [avanzamento, setAvanzamento] = useState<{ fatti: number; totale: number; cosa: string } | null>(null)

  // L'importazione in blocco gira SUL SERVER: chiudere la pagina non la
  // ferma, e tornando qui si ritrova a che punto e'. Prima era un ciclo nel
  // browser, e cambiare scheda la interrompeva a meta'.
  const { data: lavoro } = useIngestImportJob()
  const importazioneInCorso = lavoro?.running ?? false
  const stavaLavorando = useRef(false)

  const [destLibraryId, setDestLibraryId] = useState<number | null>(null)
  const destLibrary = useMemo(
    () => libraries.find((l) => l.id === destLibraryId) ?? libraries[0],
    [libraries, destLibraryId]
  )
  // Override per-card, tenuto solo in memoria (come ib._destLibraryId nel
  // Vue esistente) — si perde a un refetch della lista, ma tanto la lista
  // stessa (ingestBooks) è già "usa e getta" fino all'importazione.
  const [perItemLibrary, setPerItemLibrary] = useState<Record<number, number>>({})

  // "Forse ce l'hai già": si chiede per la biblioteca di destinazione
  // generale, perché è quella di quasi tutte le schede. Chi cambia la
  // destinazione di una singola scheda vede l'avviso di quella generale —
  // meno preciso, ma una richiesta per biblioteca a ogni cambio di tendina
  // costerebbe molto di più di quanto valga.
  const { data: duplicatiPerItem = {} } = useIngestDuplicati(destLibrary?.folder_name)

  const [uploading, setUploading] = useState(false)
  const [rejected, setRejected] = useState<IngestRejectedFile[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [importingIds, setImportingIds] = useState<Set<number>>(new Set())
  const [discardingIds, setDiscardingIds] = useState<Set<number>>(new Set())
  const [editingItem, setEditingItem] = useState<IngestedBook | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function handleFiles(fileList: FileList | null) {
    const files = Array.from(fileList ?? [])
    if (files.length === 0) return
    setUploading(true)
    setRejected([])
    setMessage(null)
    try {
      const result = await uploadIngestFiles(files)
      setRejected(result.rejected || [])
      if (result.staged?.length) {
        const n = result.staged.length
        setMessage({ kind: 'success', text: t('ingest.importTab.uploadedCount', { count: n, n }) })
        await queryClient.invalidateQueries({ queryKey: INGEST_QUERY_KEY })
      } else if (!result.rejected?.length) {
        setMessage({ kind: 'error', text: t('ingest.importTab.noFilesUploaded') })
      }
    } catch (err) {
      setMessage({ kind: 'error', text: errorDetail(err, t('ingest.importTab.uploadError')) })
    } finally {
      setUploading(false)
    }
  }

  function handleFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    void handleFiles(e.target.files)
    e.target.value = ''
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    void handleFiles(e.dataTransfer?.files ?? null)
  }

  async function doDiscard(item: IngestedBook) {
    setDiscardingIds((prev) => new Set(prev).add(item.id))
    try {
      await discardIngestItem(item.id)
      return { ok: true as const }
    } catch (err) {
      return { ok: false as const, error: errorDetail(err, t('ingest.importTab.discardFailed', { name: item.title })) }
    } finally {
      setDiscardingIds((prev) => {
        const next = new Set(prev)
        next.delete(item.id)
        return next
      })
    }
  }

  // Elimina davvero un solo file dallo staging (file + riga, vedi
  // ingest.py::discard_ingest_item) — cancellazione volutamente vera, a
  // differenza del vecchio "Scarta Tutti" che svuotava solo l'elenco in
  // memoria senza toccare il backend (il file restava sul disco e
  // ricompariva al prossimo refetch).
  async function handleDiscardOne(item: IngestedBook) {
    if (!window.confirm(t('ingest.importTab.confirmDiscardOne', { name: item.title }))) return
    setMessage(null)
    const result = await doDiscard(item)
    if (result.ok) {
      await queryClient.invalidateQueries({ queryKey: INGEST_QUERY_KEY })
    } else {
      setMessage({ kind: 'error', text: result.error })
    }
  }

  useEffect(() => {
    if (!lavoro) return
    if (stavaLavorando.current && !lavoro.running) {
      // Appena finito: gli elenchi vanno riletti, e conviene dirlo.
      void ricaricaTutto()
      void queryClient.invalidateQueries({ queryKey: ['libraries'] })
      libraries.forEach((lib) => void queryClient.invalidateQueries({ queryKey: ['books', lib.folder_name] }))
      setPagina(0)
      const imported = lavoro.imported
      setMessage(
        lavoro.failed.length === 0
          ? {
              kind: 'success',
              text: lavoro.cancelled
                ? t('ingest.importTab.importedCancelled', { count: imported, n: imported })
                : t('ingest.importTab.importedSuccess', { count: imported, n: imported }),
            }
          : {
              kind: 'error',
              text: t('ingest.importTab.importedWithFailures', { count: imported, n: imported, failed: lavoro.failed.length }),
            }
      )
    }
    stavaLavorando.current = lavoro.running
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lavoro?.running])

  /**
   * Tutte le voci in staging, non solo quelle della pagina mostrata.
   * Chiesto solo quando serve davvero — cioe' quando si preme un comando
   * che dice "tutti" — e non ad ogni caricamento della pagina.
   */
  async function tutteLeVoci(): Promise<IngestedBook[]> {
    if (!impaginata) return ingestBooks
    const { data, error } = await api.GET('/api/kolibre/ingest')
    if (error) return []
    return data as unknown as IngestedBook[]
  }

  async function ricaricaTutto() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: INGEST_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: ['ingest-page'] }),
      queryClient.invalidateQueries({ queryKey: ['ingest-pagination'] }),
    ])
  }

  async function discardAll() {
    const voci = await tutteLeVoci()
    if (voci.length === 0) return
    if (!window.confirm(t('ingest.importTab.confirmDiscardAll', { count: voci.length, n: voci.length }))) return
    setMessage(null)
    // Poche per volta e non tutte insieme: vedi aBatch. Su migliaia di file
    // un Promise.all e' una raffica che il server prende tutta in faccia, e
    // la pagina resta senza alcun segno di vita finche' non finisce.
    const results = await aBatch(voci, doDiscard, {
      onProgress: (fatti, totale) => setAvanzamento({ fatti, totale, cosa: t('ingest.importTab.discardingProgress') }),
    })
    setAvanzamento(null)
    const okCount = results.filter((r) => r.ok).length
    const failCount = results.length - okCount
    await ricaricaTutto()
    setPagina(0)
    setMessage(
      failCount === 0
        ? { kind: 'success', text: t('ingest.importTab.discardedSuccess', { count: okCount, n: okCount }) }
        : { kind: 'error', text: t('ingest.importTab.discardedWithFailures', { count: okCount, n: okCount, failed: failCount }) }
    )
  }

  async function doImport(item: IngestedBook, libraryFolder: string) {
    setImportingIds((prev) => new Set(prev).add(item.id))
    try {
      await importIngestBook({
        id: item.id,
        library: libraryFolder,
        title: item.title,
        author: item.author,
        description: item.description,
        tags: item.tags,
        series: item.series,
        series_index: item.series_index,
        language: item.language,
        isbn: item.isbn,
      })
      return { ok: true as const }
    } catch (err) {
      return { ok: false as const, error: errorDetail(err, t('ingest.importTab.importFailed', { name: item.title })) }
    } finally {
      setImportingIds((prev) => {
        const next = new Set(prev)
        next.delete(item.id)
        return next
      })
    }
  }

  function resolveDestFor(item: IngestedBook) {
    const id = perItemLibrary[item.id] ?? destLibraryId ?? destLibrary?.id
    return libraries.find((l) => l.id === id) ?? destLibrary
  }

  async function handleImportOne(item: IngestedBook) {
    const target = resolveDestFor(item)
    if (!target) return
    setMessage(null)
    const result = await doImport(item, target.folder_name)
    if (result.ok) {
      setMessage({ kind: 'success', text: t('ingest.importTab.importedOneSuccess', { title: item.title, library: target.name }) })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: INGEST_QUERY_KEY }),
        queryClient.invalidateQueries({ queryKey: ['books', target.folder_name] }),
        queryClient.invalidateQueries({ queryKey: ['libraries'] }),
      ])
    } else {
      setMessage({ kind: 'error', text: result.error })
    }
  }

  // A differenza di bulkImport nel Vue esistente (che spara tutte le
  // richieste con un forEach senza aspettarle, poi mostra sempre lo stesso
  // "Importazione massiva avviata!" indipendentemente da come va a
  // finire), qui si aspetta ogni risultato e si riporta un conteggio reale
  // di successi/fallimenti — nessuna chiamata aggiuntiva al backend, solo
  // un resoconto onesto di quelle già fatte.
  /**
   * Avvia l'importazione in blocco sul server. `solo` = le voci di questa
   * pagina; senza, tutte quelle in attesa — e in quel caso l'elenco lo fa il
   * server, perche' con la pagina impaginata qui non si conoscono tutte.
   *
   * La destinazione resta una decisione di qui: la libreria scelta in alto,
   * piu' le eccezioni per singolo libro (perItemLibrary). Quelle si mandano
   * come eccezioni esplicite, il resto va nella libreria generale.
   */
  async function handleBulkImport(solo?: IngestedBook[]) {
    const generale = destLibrary?.folder_name
    if (!generale) {
      setMessage({ kind: 'error', text: t('ingest.importTab.noDestLibrary') })
      return
    }
    const eccezioni: Record<string, string> = {}
    for (const [id, libId] of Object.entries(perItemLibrary)) {
      const lib = libraries.find((l) => l.id === libId)
      if (lib) eccezioni[id] = lib.folder_name
    }
    setMessage(null)
    try {
      const { total } = await startIngestImportJob({
        ids: solo ? solo.map((i) => i.id) : undefined,
        library: generale,
        per_item: eccezioni,
      })
      stavaLavorando.current = true
      await queryClient.invalidateQueries({ queryKey: INGEST_JOB_KEY })
      setMessage({ kind: 'success', text: t('ingest.importTab.bulkImportStarted', { total: numero(total) }) })
    } catch {
      setMessage({ kind: 'error', text: t('ingest.importTab.bulkImportStartFailed') })
    }
  }

  async function handleOpenFile(item: IngestedBook) {
    // Solo EPUB/PDF hanno un reader dedicato — altri formati (es. MOBI)
    // aprono ancora il file grezzo direttamente, come prima di Fase 9.
    const openedInReader = await openIngestBookInReader(item)
    if (!openedInReader) {
      const url = await ingestFileUrl(item.id)
      window.open(url, '_blank')
    }
  }

  // Nessuna chiamata al backend qui: come per title/author, gli edit restano
  // solo in cache React Query finché non si importa davvero — è
  // import_book_from_ingest a scriverli sul libro Calibre (vedi doImport
  // sopra, che li rimanda tutti indietro da `item`).
  function handleSaveMetadata(item: IngestedBook, edits: IngestMetadataEdits) {
    queryClient.setQueryData<IngestedBook[]>(INGEST_QUERY_KEY, (prev) =>
      prev?.map((b) =>
        b.id === item.id
          ? {
              ...b,
              title: edits.title,
              author: edits.author,
              description: edits.description,
              tags: edits.tags,
              series: edits.series || null,
              series_index: edits.series_index,
              language: edits.language || null,
              isbn: edits.isbn || null,
            }
          : b
      )
    )
  }

  return (
    <div
      className="relative flex flex-col gap-3"
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {dragOver && (
        <div className="absolute inset-0 z-20 flex items-center justify-center rounded-lg border-2 border-dashed border-primary bg-background/95">
          <div className="flex flex-col items-center gap-2 text-center font-semibold text-primary">
            <Upload className="size-8" />
            {t('ingest.importTab.dropHint')}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 p-3">
        <div className="flex flex-wrap items-center gap-4">
          <div>
            <div className="text-[11px] font-bold tracking-wide text-muted-foreground uppercase">{t('ingest.importTab.stagingFolderLabel')}</div>
            <div className="text-[12px] text-muted-foreground">
              {t('ingest.importTab.filesWaiting', { count: ingestBooks.length, n: ingestBooks.length })}
            </div>
          </div>
          <div className="flex items-center gap-2 border-l border-border pl-4">
            <span className="text-[11px] text-muted-foreground">{t('ingest.importTab.destLibraryLabel')}</span>
            <LibraryPickerButton libraries={libraries} value={destLibrary} onChange={setDestLibraryId} />
          </div>
        </div>

        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={INGEST_ACCEPT}
            className="hidden"
            onChange={handleFileInputChange}
          />
          <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()} title={t('ingest.importTab.acceptedFormatsTitle', { formats: INGEST_ACCEPT })}>
            <Upload className="size-3.5" />
            {t('ingest.importTab.uploadButton')}
          </Button>
          <Button variant="outline" size="sm" onClick={() => void discardAll()} disabled={totaleInStaging === 0}>
            <Trash2 className="size-3.5" />
            {t('ingest.importTab.discardAllButton')}
          </Button>
          {/* Due comandi distinti solo quando c'e' davvero piu' di una
              pagina: chi ha dieci libri non deve scegliere fra due bottoni
              che in quel caso farebbero la stessa identica cosa. */}
          {impaginata && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleBulkImport(ingestBooks)}
              disabled={importazioneInCorso || ingestBooks.length === 0}
            >
              {t('ingest.importTab.importPageButton', { n: ingestBooks.length })}
            </Button>
          )}
          <Button size="sm" onClick={() => void handleBulkImport()} disabled={importazioneInCorso || totaleInStaging === 0}>
            {importazioneInCorso ? <Loader2 className="size-3.5 animate-spin" /> : null}
            {impaginata
              ? t('ingest.importTab.importAllPaginatedButton', { n: numero(totaleInStaging) })
              : t('ingest.importTab.importAllReadyButton')}
          </Button>
        </div>
      </div>

      {uploading && (
        <div className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-[12px] text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />
          {t('ingest.importTab.uploading')}
        </div>
      )}

      {message && (
        <div
          className={
            message.kind === 'success'
              ? 'rounded-md border border-primary/30 bg-primary/10 px-3 py-2 text-[12.5px] text-primary'
              : 'rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-[12.5px] text-destructive'
          }
        >
          {message.text}
        </div>
      )}

      {rejected.length > 0 && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-[12.5px] text-destructive">
          <div className="mb-1.5 flex items-center justify-between">
            <strong className="inline-flex items-center gap-1.5">
              <AlertTriangle className="size-3.5" />
              {t('ingest.importTab.rejectedCount', { count: rejected.length, n: rejected.length })}
            </strong>
            <button onClick={() => setRejected([])} className="inline-flex items-center gap-1 underline">
              <X className="size-3" />
              {t('common.close')}
            </button>
          </div>
          {rejected.map((rej, idx) => (
            <div key={idx}>
              <strong>{rej.filename}</strong> — {rej.reason}
            </div>
          ))}
        </div>
      )}

      {isLoading && <p className="text-muted-foreground">{t('common.loading')}</p>}

      {!isLoading && ingestBooks.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border py-16 text-center text-muted-foreground">
          <Upload className="size-8 opacity-40" />
          <p className="text-[13px]">
            {t('ingest.importTab.emptyState', { uploadLabel: t('ingest.importTab.uploadButton') })}
          </p>
        </div>
      )}

      {/* L'importazione sul server. Compare anche arrivando qui da un'altra
          pagina mentre e' in corso, ed e' proprio il punto: il lavoro non
          appartiene a questa scheda del browser. */}
      {lavoro?.running && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-[12.5px]">
          <Loader2 className="size-3.5 shrink-0 animate-spin text-primary" />
          <span className="tabular-nums">
            {t('ingest.importTab.serverImportProgress', {
              processed: numero(lavoro.processed),
              total: numero(lavoro.total),
            })}
            {lavoro.failed.length > 0 && ` · ${t('ingest.importTab.failedSuffix', { count: lavoro.failed.length, n: lavoro.failed.length })}`}
          </span>
          <div className="h-1.5 min-w-[120px] flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full bg-primary transition-[width] duration-300"
              style={{ width: `${Math.round((lavoro.processed / Math.max(1, lavoro.total)) * 100)}%` }}
            />
          </div>
          <span className="text-muted-foreground">{t('ingest.importTab.canLeavePage')}</span>
          <Button variant="outline" size="sm" onClick={() => void stopIngestImportJob()}>
            {t('ingest.importTab.stopButton')}
          </Button>
        </div>
      )}

      {/* I libri su cui l'importazione e' fallita, uno per uno: un blocco che
          fallisce su trenta libri su tremila deve poter dire QUALI. */}
      {!lavoro?.running && (lavoro?.failed.length ?? 0) > 0 && (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-[12.5px]">
          <p className="mb-1 font-medium">
            {t('ingest.importTab.lastImportFailedHeading', { count: lavoro!.failed.length, n: lavoro!.failed.length })}
          </p>
          <ul className="max-h-32 overflow-y-auto">
            {lavoro!.failed.slice(0, 50).map((f) => (
              <li key={f.id} className="truncate text-muted-foreground">
                {f.title} — {f.error}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Avanzamento di "Scarta tutti", che resta un ciclo qui nella pagina.
          Senza, la pagina resta immobile per minuti e sembra piantata. */}
      {avanzamento && (
        <div className="flex items-center gap-3 rounded-md border border-border bg-muted/30 px-3 py-2 text-[12.5px]">
          <Loader2 className="size-3.5 shrink-0 animate-spin" />
          <span className="tabular-nums">
            {t('ingest.importTab.discardProgress', {
              cosa: avanzamento.cosa,
              fatti: numero(avanzamento.fatti),
              totale: numero(avanzamento.totale),
            })}
          </span>
          <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full bg-primary transition-[width] duration-150"
              style={{ width: `${Math.round((avanzamento.fatti / Math.max(1, avanzamento.totale)) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Comandi di pagina: solo quando c'e' piu' di una pagina. */}
      {impaginata && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-1.5 text-[11.5px]">
          <Button variant="outline" size="sm" disabled={pagina === 0} onClick={() => setPagina((p) => Math.max(0, p - 1))}>
            {t('common.previous')}
          </Button>
          <span className="tabular-nums text-muted-foreground">
            {t('ingest.importTab.paginationStatus', {
              from: numero(pagina * dimPagina + 1),
              to: numero(Math.min((pagina + 1) * dimPagina, totaleInStaging)),
              total: numero(totaleInStaging),
              page: pagina + 1,
              numPages: numero(Math.max(1, Math.ceil(totaleInStaging / dimPagina))),
            })}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={(pagina + 1) * dimPagina >= totaleInStaging}
            onClick={() => setPagina((p) => p + 1)}
          >
            {t('common.next')}
          </Button>
        </div>
      )}

      {!isLoading && ingestBooks.length > 0 && (
        <div className="flex flex-col gap-3">
          {ingestBooks.map((item) => (
            <IngestCard
              key={item.id}
              item={item}
              libraries={libraries}
              destLibrary={resolveDestFor(item)}
              onChangeDestLibrary={(id) => setPerItemLibrary((prev) => ({ ...prev, [item.id]: id }))}
              onOpenFile={() => void handleOpenFile(item)}
              onEditMetadata={() => setEditingItem(item)}
              onImport={() => void handleImportOne(item)}
              onDiscard={() => void handleDiscardOne(item)}
              importing={importingIds.has(item.id)}
              discarding={discardingIds.has(item.id)}
              duplicati={duplicatiPerItem[String(item.id)]}
            />
          ))}
        </div>
      )}

      {editingItem && (
        <EditIngestMetadataDialog
          item={editingItem}
          onClose={() => setEditingItem(null)}
          onSave={(edits) => handleSaveMetadata(editingItem, edits)}
        />
      )}
    </div>
  )
}
