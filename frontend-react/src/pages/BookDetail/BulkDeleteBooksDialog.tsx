import { useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import type { Book } from '@/types/library'
import { deleteBook } from '@/lib/bookActions'

interface BulkDeleteBooksDialogProps {
  books: Book[]
  libraryFolder: string
  onClose: () => void
  onDeleted: () => void
}

// Variante multi-libro di DeleteBookDialog — porta a termine ogni
// eliminazione indipendentemente (Promise.allSettled, stesso pattern già
// usato per le azioni bulk di AnnotationsPage): un formato/file già mancante
// su UN libro della selezione non deve bloccare l'eliminazione degli altri.
export function BulkDeleteBooksDialog({ books, libraryFolder, onClose, onDeleted }: BulkDeleteBooksDialogProps) {
  const { t } = useLingua()
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleDelete() {
    setDeleting(true)
    setError(null)
    const results = await Promise.allSettled(books.map((b) => deleteBook(libraryFolder, b.id)))
    const failed = results.filter((r) => r.status === 'rejected').length
    if (failed > 0) {
      setError(t('library.bulkDelete.someFailed', { n: failed, total: books.length }))
      setDeleting(false)
    } else {
      onDeleted()
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('library.bulkDelete.title', { count: books.length, n: books.length })}</DialogTitle>
        </DialogHeader>
        <p className="text-[13px]">
          {t('library.bulkDelete.confirm', { count: books.length, n: books.length })}
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
