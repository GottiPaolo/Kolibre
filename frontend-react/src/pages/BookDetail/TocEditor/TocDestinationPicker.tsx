import { useEffect, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import { useTocDestinations, fetchTocDestinationContent } from '@/lib/queries'
import { createTocAnchor } from '@/lib/bookActions'
import type { TocDestinationsEpub } from '@/types/library'

interface TocDestinationPickerProps {
  libraryFolder: string
  bookId: number
  format: 'EPUB' | 'PDF'
  mode: 'edit' | 'create'
  initialTitle: string
  onCancel: () => void
  onApply: (dest: string, title: string) => void
}

function computeElementPath(el: Element, root: Element): number[] {
  const path: number[] = []
  let node: Element | null = el
  while (node && node !== root) {
    const parent: Element | null = node.parentElement
    if (!parent) break
    path.unshift(Array.from(parent.children).indexOf(node))
    node = parent
  }
  return path
}

export function TocDestinationPicker({ libraryFolder, bookId, format, mode, initialTitle, onCancel, onApply }: TocDestinationPickerProps) {
  const { t } = useLingua()
  const destinationsQuery = useTocDestinations(libraryFolder, bookId, format, true)
  const [title, setTitle] = useState(initialTitle)
  const [selectedHref, setSelectedHref] = useState<string | null>(null)
  const [previewHtml, setPreviewHtml] = useState('')
  const [selectedDest, setSelectedDest] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const iframeRef = useRef<HTMLIFrameElement>(null)

  useEffect(() => {
    if (format === 'EPUB' && destinationsQuery.data && 'files' in destinationsQuery.data && destinationsQuery.data.files.length > 0 && !selectedHref) {
      setSelectedHref(destinationsQuery.data.files[0].href)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [destinationsQuery.data])

  useEffect(() => {
    if (!selectedHref) return
    fetchTocDestinationContent(libraryFolder, bookId, selectedHref, 'EPUB').then(setPreviewHtml).catch(() => setPreviewHtml(`<p>${t('library.toc.previewLoadError')}</p>`))
  }, [selectedHref, libraryFolder, bookId, t])

  function handleIframeLoad() {
    const doc = iframeRef.current?.contentDocument
    if (!doc || !doc.body) return
    const style = doc.createElement('style')
    style.textContent = '.kolibre-hover{outline:2px solid var(--color-primary,#3b82f6);cursor:pointer;}'
    doc.head.appendChild(style)

    let lastHovered: Element | null = null
    doc.body.addEventListener('mouseover', (e) => {
      const target = e.target as Element
      if (lastHovered) lastHovered.classList.remove('kolibre-hover')
      target.classList.add('kolibre-hover')
      lastHovered = target
    })

    doc.body.addEventListener('click', async (e) => {
      e.preventDefault()
      const target = e.target as Element
      if (!selectedHref) return
      const existingId = target.getAttribute('id')
      if (existingId) {
        setSelectedDest(`${selectedHref}#${existingId}`)
        return
      }
      try {
        const path = computeElementPath(target, doc.body)
        const anchorId = await createTocAnchor(libraryFolder, bookId, selectedHref, path)
        setSelectedDest(`${selectedHref}#${anchorId}`)
      } catch {
        setError(t('library.toc.anchorCreateFailed'))
      }
    })
  }

  function handleApply() {
    if (format === 'PDF') {
      onApply(String(page), title)
    } else if (selectedDest) {
      onApply(selectedDest, title)
    } else if (selectedHref) {
      onApply(selectedHref, title)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{mode === 'create' ? t('library.toc.newEntryTitle') : t('library.toc.changeDestination')}</DialogTitle>
        </DialogHeader>

        <div>
          <label className="mb-1 block text-[11px] font-medium text-muted-foreground">{t('library.field.title')}</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
          />
        </div>

        {format === 'PDF' ? (
          <div>
            <label className="mb-1 block text-[11px] font-medium text-muted-foreground">
              {t('library.toc.pageNumber', {
                max: destinationsQuery.data && 'page_count' in destinationsQuery.data ? destinationsQuery.data.page_count : '…',
              })}
            </label>
            <input
              type="number"
              min={1}
              max={destinationsQuery.data && 'page_count' in destinationsQuery.data ? destinationsQuery.data.page_count : undefined}
              value={page}
              onChange={(e) => setPage(Number(e.target.value))}
              className="w-32 rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
            />
          </div>
        ) : (
          <div className="flex h-[380px] gap-3">
            <div className="w-[220px] shrink-0 overflow-y-auto rounded-md border border-border">
              {(destinationsQuery.data as TocDestinationsEpub | undefined)?.files.map((f) => (
                <button
                  key={f.href}
                  onClick={() => {
                    setSelectedHref(f.href)
                    setSelectedDest(null)
                  }}
                  className={`block w-full truncate px-2 py-1.5 text-left text-[12px] hover:bg-accent ${f.href === selectedHref ? 'bg-primary/10 font-medium' : ''}`}
                >
                  {f.href}
                </button>
              ))}
            </div>
            <iframe
              ref={iframeRef}
              srcDoc={previewHtml}
              sandbox="allow-same-origin"
              onLoad={handleIframeLoad}
              className="flex-1 rounded-md border border-border bg-white"
              title={t('library.toc.chapterPreview')}
            />
          </div>
        )}

        {error && <p className="text-[12.5px] text-destructive">{error}</p>}
        {format === 'EPUB' && !selectedDest && <p className="text-[11.5px] text-muted-foreground">{t('library.toc.clickToChooseDestination')}</p>}

        <DialogFooter>
          <Button variant="ghost" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleApply} disabled={format === 'EPUB' && !selectedHref}>
            {t('library.metadata.apply')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
