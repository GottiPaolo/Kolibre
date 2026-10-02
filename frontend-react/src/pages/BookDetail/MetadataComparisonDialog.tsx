import { useMemo, useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import type { Book, MetadataCandidate } from '@/types/library'
import { applyOnlineMetadata } from '@/lib/bookActions'

interface MetadataComparisonDialogProps {
  book: Book
  libraryFolder: string
  candidate: MetadataCandidate
  allCandidates: MetadataCandidate[]
  onClose: () => void
  onApplied: () => void
}

export function MetadataComparisonDialog({ book, libraryFolder, candidate, allCandidates, onClose, onApplied }: MetadataComparisonDialogProps) {
  const { t } = useLingua()
  // Solo i campi effettivamente trovati sono pre-selezionati — altrimenti un
  // checkbox spuntato su un campo vuoto sovrascriverebbe silenziosamente il
  // valore corrente (stesso fix del Vue esistente, selectMetadataCandidate).
  const [applyTitle, setApplyTitle] = useState(!!candidate.title)
  const [applyAuthor, setApplyAuthor] = useState(!!candidate.author)
  const [applyIdentifiers, setApplyIdentifiers] = useState(Object.keys(candidate.identifiers ?? {}).length > 0)
  const [applyDescription, setApplyDescription] = useState(!!candidate.description)
  const [applyPublisher, setApplyPublisher] = useState(!!candidate.publisher)
  const [applyLanguage, setApplyLanguage] = useState(!!candidate.language)
  const [applyTags, setApplyTags] = useState(candidate.tags.length > 0)
  const [applyPubdate, setApplyPubdate] = useState(!!candidate.pubdate)
  const [applyCover, setApplyCover] = useState(!!candidate.cover_url)
  const [coverUrl, setCoverUrl] = useState(candidate.cover_url)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const coverOptions = useMemo(
    () => Array.from(new Set(allCandidates.map((c) => c.cover_url).filter((u): u is string => !!u))),
    [allCandidates]
  )

  async function handleApply() {
    setApplying(true)
    setError(null)
    try {
      await applyOnlineMetadata(libraryFolder, book.id, {
        ...(applyTitle && candidate.title ? { title: candidate.title } : {}),
        ...(applyAuthor && candidate.author ? { author: candidate.author } : {}),
        ...(applyIdentifiers && Object.keys(candidate.identifiers ?? {}).length ? { identifiers: candidate.identifiers } : {}),
        ...(applyDescription && candidate.description ? { description: candidate.description } : {}),
        ...(applyPublisher && candidate.publisher ? { publisher: candidate.publisher } : {}),
        ...(applyLanguage && candidate.language ? { language: candidate.language } : {}),
        ...(applyTags && candidate.tags.length ? { tags: candidate.tags } : {}),
        ...(applyPubdate && candidate.pubdate ? { pubdate: candidate.pubdate } : {}),
        ...(applyCover && coverUrl ? { cover_url: coverUrl } : {}),
      })
      onApplied()
    } catch {
      setError(t('library.metadata.applyFailed'))
      setApplying(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{t('library.metadata.compareTitle', { title: book.title })}</DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-3">
            <h4 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('library.metadata.currentValues')}</h4>
            <ReadonlyField label={t('library.field.title')} value={book.title} />
            <ReadonlyField label={t('library.field.author')} value={book.author} />
            <ReadonlyField label={t('library.field.identifiers')} value={Object.entries(book.identifiers).map(([k, v]) => `${k}:${v}`).join(', ') || '—'} />
            <ReadonlyField label={t('library.field.publisher')} value={book.publisher || '—'} />
            <ReadonlyField label={t('library.field.language')} value={book.language || '—'} />
            <ReadonlyField label={t('library.field.tags')} value={book.tags.join(', ') || '—'} />
            {book.cover_url && <img src={book.cover_url} alt="" className="h-32 w-auto rounded border border-border" />}
          </div>

          <div className="space-y-3">
            <h4 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
              {t('library.metadata.downloaded', { source: candidate.source })}
            </h4>
            <CheckField label={t('library.field.title')} checked={applyTitle} onChange={setApplyTitle} disabled={!candidate.title} value={candidate.title ?? '—'} />
            <CheckField label={t('library.field.author')} checked={applyAuthor} onChange={setApplyAuthor} disabled={!candidate.author} value={candidate.author || '—'} />
            <CheckField
              label={t('library.field.identifiers')}
              checked={applyIdentifiers}
              onChange={setApplyIdentifiers}
              disabled={Object.keys(candidate.identifiers ?? {}).length === 0}
              value={Object.entries(candidate.identifiers ?? {}).map(([k, v]) => `${k}:${v}`).join(', ') || '—'}
            />
            <CheckField
              label={t('library.field.description')}
              checked={applyDescription}
              onChange={setApplyDescription}
              disabled={!candidate.description}
              value={candidate.description ? `${candidate.description.slice(0, 80)}…` : '—'}
            />
            <CheckField
              label={t('library.field.publisher')}
              checked={applyPublisher}
              onChange={setApplyPublisher}
              disabled={!candidate.publisher}
              value={candidate.publisher || '—'}
            />
            <CheckField
              label={t('library.field.language')}
              checked={applyLanguage}
              onChange={setApplyLanguage}
              disabled={!candidate.language}
              value={candidate.language || '—'}
            />
            <CheckField
              label={t('library.field.tags')}
              checked={applyTags}
              onChange={setApplyTags}
              disabled={candidate.tags.length === 0}
              value={candidate.tags.join(', ') || '—'}
            />
            <CheckField
              label={t('library.field.published')}
              checked={applyPubdate}
              onChange={setApplyPubdate}
              disabled={!candidate.pubdate}
              value={candidate.pubdate || '—'}
            />
            <CheckField
              label={t('library.metadata.cover')}
              checked={applyCover}
              onChange={setApplyCover}
              disabled={!coverUrl}
              value={coverUrl ? <img src={coverUrl} alt="" className="h-24 w-auto rounded border border-border" /> : '—'}
            />
          </div>
        </div>

        {coverOptions.length > 1 && (
          <div className="space-y-1.5">
            <h4 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('library.metadata.otherCoversFound')}</h4>
            <div className="flex gap-2 overflow-x-auto">
              {coverOptions.map((url) => (
                <button key={url} onClick={() => setCoverUrl(url)} className="shrink-0">
                  <img
                    src={url}
                    alt=""
                    className={`h-20 w-auto rounded border-2 ${url === coverUrl ? 'border-primary' : 'border-transparent'}`}
                  />
                </button>
              ))}
            </div>
          </div>
        )}

        {error && <p className="text-[12.5px] text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleApply} disabled={applying}>
            {applying ? t('library.metadata.applying') : t('library.metadata.apply')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ReadonlyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="text-[13px]">{value}</p>
    </div>
  )
}

function CheckField({
  label,
  checked,
  onChange,
  disabled,
  value,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled: boolean
  value: React.ReactNode
}) {
  return (
    <label className={`flex items-start gap-2 ${disabled ? 'opacity-50' : ''}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="mt-0.5" />
      <span>
        <span className="block text-[11px] text-muted-foreground">{label}</span>
        <span className="block text-[13px]">{value}</span>
      </span>
    </label>
  )
}
