import { Fragment, useState, type ReactNode } from 'react'
import { BookOpen, Highlighter, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Book, CustomColumn } from '@/types/library'
import { splitAuthorNames } from '@/lib/authorNames'
import { withBackendUrl } from '@/lib/api'
import { formatBytes, formatDate, ratingStars } from '@/lib/format'
import { openBookFormatInReader } from '@/lib/readerActions'
import { TagFiltrabili, ValoreFiltrabile } from '@/components/ValoreFiltrabile'
import { useIsDesktop } from '@/lib/useMediaQuery'
import type { DeviceBookColumnState } from '@/lib/deviceFormat'
import {
  loadQuickviewFieldLayout,
  loadQuickviewDescriptionVisible,
  type QuickviewFixedFieldId,
  type QuickviewDeviceInfo,
} from '@/lib/quickviewFieldLayout'
import { useLingua, type Valori } from '@/lib/i18n'

// Un campo può non avere nulla da mostrare per QUESTO libro (es. "Serie" su
// un libro senza serie) — null qui vuol dire "salta la riga", indipendente
// dal fatto che l'utente l'abbia impostato come visibile in Impostazioni.
// libraryFolder serve solo a "Formati" (apre il reader), non è un parametro
// generico per tutti i campi.
function renderQuickviewField(
  id: QuickviewFixedFieldId,
  book: Book,
  libraryFolder: string | undefined,
  t: (chiave: string, valori?: Valori) => string
): ReactNode {
  switch (id) {
    case 'series':
      return book.series ? (
        <>
          <dt className="text-muted-foreground">{t('library.field.series')}</dt>
          <dd>
            {book.series} {book.series_index != null && `#${book.series_index}`}
          </dd>
        </>
      ) : null
    // Editore, lingua e tag filtrano la libreria su quel valore, come
    // nella scheda estesa del libro: sono le stesse informazioni, e non
    // avrebbe senso che si comportassero diversamente nei due posti.
    case 'publisher':
      return book.publisher ? (
        <>
          <dt className="text-muted-foreground">{t('library.field.publisher')}</dt>
          <dd>
            <ValoreFiltrabile campo="publisher" valore={book.publisher} />
          </dd>
        </>
      ) : null
    case 'language':
      return book.language ? (
        <>
          <dt className="text-muted-foreground">{t('library.field.language')}</dt>
          <dd>
            <ValoreFiltrabile campo="language" valore={book.language} />
          </dd>
        </>
      ) : null
    case 'tags':
      return book.tags.length > 0 ? (
        <>
          <dt className="text-muted-foreground">{t('library.field.tags')}</dt>
          <dd className="flex flex-wrap gap-x-1 gap-y-0.5">
            <TagFiltrabili tags={book.tags} />
          </dd>
        </>
      ) : null
    case 'identifiers':
      return Object.keys(book.identifiers).length > 0 ? (
        <>
          <dt className="text-muted-foreground">{t('library.field.id')}</dt>
          <dd>{Object.entries(book.identifiers).map(([k, v]) => `${k}:${v}`).join(', ')}</dd>
        </>
      ) : null
    case 'formats':
      return (
        <>
          <dt className="text-muted-foreground">{t('library.field.formats')}</dt>
          <dd className="flex flex-wrap gap-1">
            {book.formats.map((f) =>
              (f === 'EPUB' || f === 'PDF') && libraryFolder ? (
                <button key={f} onClick={() => openBookFormatInReader(book, libraryFolder, f)}>
                  <Badge variant="outline" className="cursor-pointer hover:border-primary hover:text-primary">
                    {f}
                  </Badge>
                </button>
              ) : (
                <Badge key={f} variant="outline">
                  {f}
                </Badge>
              )
            )}
          </dd>
        </>
      )
    case 'size':
      return (
        <>
          <dt className="text-muted-foreground">{t('library.field.size')}</dt>
          <dd>{formatBytes(book.size)}</dd>
        </>
      )
    case 'date_added':
      return (
        <>
          <dt className="text-muted-foreground">{t('library.field.dateAdded')}</dt>
          <dd>{formatDate(book.date_added)}</dd>
        </>
      )
    case 'pubdate':
      return (
        <>
          <dt className="text-muted-foreground">{t('library.field.published')}</dt>
          <dd>{formatDate(book.pubdate)}</dd>
        </>
      )
    case 'last_modified':
      return (
        <>
          <dt className="text-muted-foreground">{t('library.field.lastModified')}</dt>
          <dd>{formatDate(book.last_modified)}</dd>
        </>
      )
    case 'uuid':
      return (
        <>
          <dt className="text-muted-foreground">{t('library.field.uuid')}</dt>
          <dd className="truncate font-mono text-[11px] text-muted-foreground">{book.uuid}</dd>
        </>
      )
    case 'rating':
      return (
        <>
          <dt className="text-muted-foreground">{t('library.field.rating')}</dt>
          <dd className={book.rating ? 'text-[var(--warning)] tracking-wide' : undefined}>
            {ratingStars(book.rating)}
          </dd>
        </>
      )
  }
}

// Stessa resa spunta/trattino delle colonne di presenza dispositivo in
// tabella (LibraryTable.tsx, colId.startsWith('device-')) — niente 0/1
// grezzo per un valore binario.
function renderQuickviewCustomField(col: CustomColumn, book: Book): ReactNode {
  const value = book[`#${col.label}`]
  if (value === null || value === undefined || value === '') return null
  if (col.datatype === 'bool') {
    return (
      <>
        <dt className="text-muted-foreground">{col.name}</dt>
        <dd>{value ? <span className="text-primary">✓</span> : <span className="text-muted-foreground">–</span>}</dd>
      </>
    )
  }
  return (
    <>
      <dt className="text-muted-foreground">{col.name}</dt>
      <dd className={col.datatype === 'rating' ? 'text-[var(--warning)] tracking-wide' : undefined}>
        {col.datatype === 'rating'
          ? '★'.repeat(Number(value))
          : col.datatype === 'datetime'
            ? formatDate(String(value))
            : String(value)}
      </dd>
    </>
  )
}

// Stessa iconografia di LibraryTable.tsx (colId.startsWith('device-')) —
// niente riga saltata quando lo stato è assente: "non presente sul
// dispositivo" è già l'informazione stessa (a differenza di una colonna
// personalizzata non impostata, qui non c'è un vero "nessun dato").
function renderQuickviewDeviceField(
  device: QuickviewDeviceInfo,
  state: DeviceBookColumnState | undefined,
  t: (chiave: string, valori?: Valori) => string
): ReactNode {
  return (
    <>
      <dt className="text-muted-foreground">{t('library.field.onDevice', { name: device.name })}</dt>
      <dd>
        {state === 'on' && <span className="text-primary" title={t('library.device.onDevice')}>✓</span>}
        {state === 'queued' && (
          <span className="text-[var(--warning)]" title={t('library.device.queued')}>
            ⏳
          </span>
        )}
        {state === 'pending_delete' && (
          <span className="text-destructive" title={t('library.device.pendingDelete')}>
            🗑
          </span>
        )}
        {(state === 'off' || state === undefined) && <span className="text-muted-foreground">–</span>}
      </dd>
    </>
  )
}

interface QuickviewPanelProps {
  book: Book
  libraryFolder: string | undefined
  width: number
  customColumns: CustomColumn[]
  devices: QuickviewDeviceInfo[]
  deviceStatusByBookId: Record<number, Record<number, DeviceBookColumnState>>
  onResizeStart: (e: React.MouseEvent) => void
  onOpenDetail: () => void
  onOpenAnnotations: () => void
  onAuthorClick: (name: string) => void
  onClose: () => void
}

export function QuickviewPanel({
  book,
  libraryFolder,
  width,
  customColumns,
  devices,
  deviceStatusByBookId,
  onResizeStart,
  onOpenDetail,
  onOpenAnnotations,
  onAuthorClick,
  onClose,
}: QuickviewPanelProps) {
  const { t } = useLingua()
  const authors = splitAuthorNames(book.author)
  // Sotto "md" niente "pannello laterale ridimensionabile" (non c'è spazio):
  // diventa un overlay a piena larghezza sopra l'elenco, chiudibile con la X
  // — la larghezza inline resta quindi solo un dettaglio desktop.
  const isDesktop = useIsDesktop()
  // Letti una volta al mount, non reattivi tra tab — stesso comportamento
  // di sidebarLayout in Layout.tsx: una modifica in Impostazioni ▸ Libreria
  // si applica al prossimo caricamento della pagina, non dal vivo tra due
  // tab aperte. Per libreria (libraryFolder), non globale — le colonne
  // personalizzate e i dispositivi che questa lista può includere dipendono
  // dalla libreria attiva tanto quanto i libri stessi (i dispositivi no, ma
  // la loro presenza sì — stessa lista, stesso posto).
  const [fieldLayout] = useState(() => loadQuickviewFieldLayout(libraryFolder, customColumns, devices))
  const [descriptionVisible] = useState(() => loadQuickviewDescriptionVisible(libraryFolder))
  const customColumnsByLabel = new Map(customColumns.map((c) => [c.label, c]))
  const devicesById = new Map(devices.map((d) => [String(d.id), d]))
  const deviceStatusForBook = deviceStatusByBookId[book.id]

  return (
    <div
      className="absolute inset-0 z-30 shrink-0 border-border bg-card shadow-[-6px_0_16px_-8px_rgb(0_0_0_/_0.25)] md:relative md:inset-auto md:z-auto md:border-l-2"
      style={isDesktop ? { width } : undefined}
    >
      <div
        onMouseDown={onResizeStart}
        className="absolute top-0 left-0 z-10 hidden h-full w-1.5 -translate-x-1/2 cursor-col-resize hover:bg-primary/40 md:block"
      />
      <button
        onClick={onClose}
        aria-label={t('library.quickview.closeAriaLabel')}
        className="absolute top-2 right-2 z-10 flex size-6 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <X className="size-3.5" />
      </button>

      <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
        <div className="mx-auto w-[140px] shrink-0 overflow-hidden rounded-md border border-border bg-muted">
          {book.cover_url ? (
            // Larghezza fissa, altezza libera (niente aspect-ratio/object-fit
            // forzati): la copertina va riportata così com'è, al suo rapporto
            // reale — un riquadro con altezza fissa produceva bande vuote
            // (letterbox) per ogni copertina non esattamente 2:3, peggio del
            // ritaglio che doveva risolvere. Stesso approccio di
            // BookDetailPage.tsx.
            // shrink-0 è essenziale: questo div è un figlio di un flex-col
            // (il pannello) con overflow-hidden su di sé — senza shrink-0, i
            // libri con molti campi/descrizione lunga fanno traboccare
            // l'altezza del pannello, e flexbox reagisce RESTRINGENDO tutti
            // i figli (la copertina compresa) invece di scrollare, con
            // l'overflow-hidden che poi ritaglia l'immagine schiacciata.
            // Difetto riscontrato in uso: su un libro con la scheda lunga
            // la copertina arrivava ritagliata via quasi del tutto.
            <img src={withBackendUrl(book.cover_url)} alt={book.title} loading="lazy" className="w-full" />
          ) : (
            <div className="flex aspect-[2/3] items-center justify-center">
              <BookOpen className="size-8 text-muted-foreground" />
            </div>
          )}
        </div>

        <div>
          <h3 className="font-serif text-[15px] font-semibold leading-snug">{book.title}</h3>
          <p className="mt-0.5 text-[12.5px] text-muted-foreground">
            {authors.map((name, idx) => (
              <span key={name}>
                {idx > 0 && ' & '}
                <button onClick={() => onAuthorClick(name)} className="hover:text-primary hover:underline">
                  {name}
                </button>
              </span>
            ))}
            {authors.length === 0 && '—'}
          </p>
        </div>

        <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1.5 text-[12.5px]">
          {fieldLayout.map((entry) => {
            if (!entry.visible) return null
            if (entry.kind === 'fixed') {
              return <Fragment key={entry.id}>{renderQuickviewField(entry.id, book, libraryFolder, t)}</Fragment>
            }
            if (entry.kind === 'device') {
              const device = devicesById.get(entry.id)
              // Dispositivo cancellato dopo l'ultimo salvataggio dell'ordine
              // — stesso guardrail delle colonne personalizzate sotto.
              if (!device) return null
              return (
                <Fragment key={`device:${entry.id}`}>
                  {renderQuickviewDeviceField(device, deviceStatusForBook?.[device.id], t)}
                </Fragment>
              )
            }
            const col = customColumnsByLabel.get(entry.id)
            // Colonna cancellata dalla libreria dopo l'ultimo salvataggio
            // dell'ordine — loadQuickviewFieldLayout la scarta già al
            // prossimo caricamento, questo è solo un guardrail per il
            // render corrente.
            if (!col) return null
            return <Fragment key={entry.id}>{renderQuickviewCustomField(col, book)}</Fragment>
          })}
        </dl>

        {descriptionVisible && book.description && (
          <div>
            <h3 className="mb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('library.field.description')}</h3>
            <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{book.description}</p>
          </div>
        )}

        <div className="mt-auto flex flex-col gap-1.5 pt-2">
          <Button variant="secondary" size="sm" onClick={onOpenDetail}>
            {t('library.quickview.fullDetail')}
          </Button>
          <Button variant="ghost" size="sm" onClick={onOpenAnnotations}>
            <Highlighter className="size-3.5" />
            {t('library.quickview.viewAnnotations')}
          </Button>
        </div>
      </div>
    </div>
  )
}
