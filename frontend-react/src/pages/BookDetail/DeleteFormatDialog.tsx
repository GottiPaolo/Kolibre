import { useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import type { Book } from '@/types/library'
import { deleteBookFormat } from '@/lib/bookActions'

interface DeleteFormatDialogProps {
  book: Book
  libraryFolder: string
  format: string
  onClose: () => void
  onDeleted: () => void
}

export function DeleteFormatDialog({ book, libraryFolder, format, onClose, onDeleted }: DeleteFormatDialogProps) {
  const { t } = useLingua()
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleDelete() {
    setDeleting(true)
    setError(null)
    try {
      await deleteBookFormat(libraryFolder, book.id, format)
      onDeleted()
    } catch {
      setError(t('library.deleteFormat.failed'))
      setDeleting(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('library.deleteFormat.title')}</DialogTitle>
        </DialogHeader>
        <p className="text-[13px]">
          {t('library.deleteFormat.confirm', { format, title: book.title })}
        </p>
        {error && <p className="text-[12.5px] text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
            {deleting ? t('library.deleteBook.deleting') : t('library.deleteBook.delete')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
