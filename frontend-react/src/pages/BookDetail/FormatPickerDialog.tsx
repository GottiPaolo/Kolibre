import { useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import type { Book } from '@/types/library'
import { downloadFormatUrl, pickPreferredFormat } from '@/lib/bookActions'

interface FormatPickerDialogProps {
  book: Book
  libraryFolder: string
  onClose: () => void
}

export function FormatPickerDialog({ book, libraryFolder, onClose }: FormatPickerDialogProps) {
  const { t } = useLingua()
  const [selected, setSelected] = useState<Set<string>>(new Set([pickPreferredFormat(book.formats)]))

  function toggle(format: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(format)) next.delete(format)
      else next.add(format)
      return next
    })
  }

  function handleDownload() {
    for (const format of selected) {
      window.open(downloadFormatUrl(libraryFolder, book.id, format), '_blank')
    }
    onClose()
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xs">
        <DialogHeader>
          <DialogTitle>{t('library.formatPicker.title', { title: book.title })}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-1.5">
          {book.formats.map((format) => (
            <label key={format} className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-accent">
              <input type="checkbox" checked={selected.has(format)} onChange={() => toggle(format)} />
              <span className="text-[13px]">{format}</span>
            </label>
          ))}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleDownload} disabled={selected.size === 0}>
            {t('library.formatPicker.download')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
