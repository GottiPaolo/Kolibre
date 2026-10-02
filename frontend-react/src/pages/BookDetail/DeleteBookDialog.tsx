import { useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import type { Book } from '@/types/library'
import { deleteBook } from '@/lib/bookActions'

interface DeleteBookDialogProps {
  book: Book
  libraryFolder: string
  onClose: () => void
  onDeleted: () => void
}

export function DeleteBookDialog({ book, libraryFolder, onClose, onDeleted }: DeleteBookDialogProps) {
  const { t } = useLingua()
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleDelete() {
    setDeleting(true)
    setError(null)
    try {
      await deleteBook(libraryFolder, book.id)
      onDeleted()
    } catch {
      setError(t('library.deleteBook.failed'))
      setDeleting(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('library.deleteBook.title')}</DialogTitle>
        </DialogHeader>
        <p className="text-[13px]">
          {t('library.deleteBook.confirm', { title: book.title })}
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
