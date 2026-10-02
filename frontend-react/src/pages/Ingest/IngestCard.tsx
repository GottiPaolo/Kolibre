import { AlertTriangle, BookOpen, ExternalLink, Loader2, Pencil, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { formatBytes } from '@/lib/format'
import { withBackendUrl } from '@/lib/api'
import type { IngestedBook } from '@/types/ingest'
import type { Library } from '@/types/library'
import { LibraryPickerButton } from '@/components/LibraryPickerButton'
import type { IngestDuplicato } from '@/lib/ingestQueries'
import { useLingua } from '@/lib/i18n'

interface IngestCardProps {
  item: IngestedBook
  destLibrary: Library | undefined
  libraries: Library[]
  onChangeDestLibrary: (id: number) => void
  onOpenFile: () => void
  onEditMetadata: () => void
  onImport: () => void
  onDiscard: () => void
  importing: boolean
  discarding: boolean
  // Libri della biblioteca di destinazione che somigliano a questo file.
  // Avviso, non blocco: un doppione vero e un'edizione diversa dello stesso
  // titolo si somigliano allo stesso modo, e decidere tocca a chi guarda.
  duplicati?: IngestDuplicato[]
}

export function IngestCard({
  item,
  destLibrary,
  libraries,
  onChangeDestLibrary,
  onOpenFile,
  onEditMetadata,
  onImport,
  onDiscard,
  importing,
  discarding,
  duplicati,
}: IngestCardProps) {
  const { t } = useLingua()
  return (
    <div className="flex items-center gap-4 rounded-lg border border-border bg-card p-3">
      {/* Copertina reale solo per EPUB con cover-image nel manifest OPF
          (vedi services/metadata_parser.py) — placeholder generico altrimenti
          (PDF, o un EPUB senza copertina propria). */}
      <div className="flex aspect-[2/3] w-14 shrink-0 items-center justify-center overflow-hidden rounded border border-border bg-muted text-muted-foreground">
        {item.cover_url ? (
          <img src={withBackendUrl(item.cover_url)} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <BookOpen className="size-5" />
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="truncate font-serif text-[15px] font-semibold">{item.title}</div>
        <div className="truncate text-[13px] text-muted-foreground">{t('ingest.card.byAuthor', { author: item.author })}</div>
        <div className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted-foreground">
          {item.formats.map((fmt) => (
            <span key={fmt} className="rounded border border-border px-1 py-0.5 font-medium">
              {fmt}
            </span>
          ))}
          <span>{formatBytes(item.size)}</span>
        </div>
        {duplicati && duplicati.length > 0 && (
          <div className="mt-0.5 flex items-start gap-1.5 text-[11.5px] text-[var(--warning)]">
            <AlertTriangle className="mt-px size-3.5 shrink-0" />
            <span className="text-muted-foreground">
              {t('ingest.card.maybeAlreadyHave')}{' '}
              <span className="text-foreground">
                {duplicati.map((d) => `${d.title}${d.formats.length ? ` (${d.formats.join(', ')})` : ''}`).join(' · ')}
              </span>
              {t('ingest.card.importAnywayHint')}
            </span>
          </div>
        )}

        <div className="mt-1 flex items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground">{t('ingest.card.destinationLabel')}</span>
          <LibraryPickerButton libraries={libraries} value={destLibrary} onChange={onChangeDestLibrary} size="sm" />
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-1.5">
        <Button variant="outline" size="sm" onClick={onOpenFile} title={t('ingest.card.openFileTitle')}>
          <ExternalLink className="size-3.5" />
          {t('ingest.card.openFileButton')}
        </Button>
        <Button variant="outline" size="sm" onClick={onEditMetadata}>
          <Pencil className="size-3.5" />
          {t('ingest.card.metadataButton')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onDiscard}
          disabled={discarding || importing}
          className="text-destructive hover:text-destructive"
          title={t('ingest.card.discardTitle')}
        >
          {discarding ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
          {t('ingest.card.discardButton')}
        </Button>
        <Button size="sm" onClick={onImport} disabled={importing || !destLibrary}>
          {importing ? <Loader2 className="size-3.5 animate-spin" /> : null}
          {t('ingest.card.importButton')}
        </Button>
      </div>
    </div>
  )
}
