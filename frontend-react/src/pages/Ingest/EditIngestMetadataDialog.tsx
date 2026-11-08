import { useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import type { IngestedBook } from '@/types/ingest'

export interface IngestMetadataEdits {
  title: string
  author: string
  description: string
  tags: string[]
  series: string
  series_index: number | null
  language: string
  isbn: string
}

interface EditIngestMetadataDialogProps {
  item: IngestedBook
  onClose: () => void
  onSave: (edits: IngestMetadataEdits) => void
}

// Editor esteso: title/author/description/tags/series/series_index/
// language/isbn arrivano TUTTI davvero a /api/kolibre/ingest/import-book
// (vedi IngestImportRequest in schemas.py e import_book_from_ingest) — a
// differenza della versione ridotta precedente, che si limitava a
// title/author perché il backend non accettava altro. description/tags
// sono pre-compilati con quanto auto-estratto in staging dall'EPUB (vedi
// services/metadata_parser.py); series/language/isbn lo sono solo se
// l'EPUB porta i meta calibre:series/dc:language/dc:identifier — altrimenti
// vuoti, editabili qui prima di importare.
export function EditIngestMetadataDialog({ item, onClose, onSave }: EditIngestMetadataDialogProps) {
  const { t } = useLingua()
  const [title, setTitle] = useState(item.title)
  const [author, setAuthor] = useState(item.author)
  const [description, setDescription] = useState(item.description)
  const [tagsText, setTagsText] = useState(item.tags.join(', '))
  const [series, setSeries] = useState(item.series || '')
  const [seriesIndex, setSeriesIndex] = useState(item.series_index != null ? String(item.series_index) : '')
  const [language, setLanguage] = useState(item.language || '')
  const [isbn, setIsbn] = useState(item.isbn || '')

  function handleSave() {
    const parsedIndex = seriesIndex.trim() ? Number(seriesIndex) : null
    onSave({
      title: title.trim() || item.title,
      author: author.trim() || item.author,
      description: description.trim(),
      tags: tagsText
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
      series: series.trim(),
      series_index: parsedIndex != null && !Number.isNaN(parsedIndex) ? parsedIndex : null,
      language: language.trim(),
      isbn: isbn.trim(),
    })
    onClose()
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('ingest.editMetadata.title')}</DialogTitle>
        </DialogHeader>
        <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto pr-1">
          <label className="flex flex-col gap-1 text-[12.5px] font-medium">
            {t('library.field.title')}
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="rounded-md border border-border bg-card px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
            />
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] font-medium">
            {t('library.field.author')}
            <input
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
              className="rounded-md border border-border bg-card px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
            />
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] font-medium">
            {t('library.field.description')}
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="resize-none rounded-md border border-border bg-card px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
            />
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] font-medium">
            {t('ingest.editMetadata.tagsLabel')}
            <input
              value={tagsText}
              onChange={(e) => setTagsText(e.target.value)}
              className="rounded-md border border-border bg-card px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1 text-[12.5px] font-medium">
              {t('library.field.series')}
              <input
                value={series}
                onChange={(e) => setSeries(e.target.value)}
                className="rounded-md border border-border bg-card px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
              />
            </label>
            <label className="flex flex-col gap-1 text-[12.5px] font-medium">
              {t('ingest.editMetadata.seriesIndexLabel')}
              <input
                value={seriesIndex}
                onChange={(e) => setSeriesIndex(e.target.value)}
                inputMode="decimal"
                className="rounded-md border border-border bg-card px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
              />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1 text-[12.5px] font-medium">
              {t('library.field.language')}
              <input
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                placeholder={t('ingest.editMetadata.languagePlaceholder')}
                className="rounded-md border border-border bg-card px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
              />
            </label>
            <label className="flex flex-col gap-1 text-[12.5px] font-medium">
              {t('ingest.editMetadata.isbnLabel')}
              <input
                value={isbn}
                onChange={(e) => setIsbn(e.target.value)}
                className="rounded-md border border-border bg-card px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
              />
            </label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleSave}>{t('common.save')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
