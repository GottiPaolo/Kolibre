import { useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import type { Book } from '@/types/library'
import { deleteBook } from '@/lib/bookActions'
import { messaggioErrore } from '@/lib/messaggiErrore'

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
    const rifiutate = results.filter((r) => r.status === 'rejected') as PromiseRejectedResult[]
    if (rifiutate.length > 0) {
      // Il conto dice QUANTI, il motivo dice PERCHE'. Su una biblioteca in
      // sola lettura falliscono tutti per la stessa ragione, e un «3 su 3
      // non eliminati» senza quella ragione somiglia a un guasto: e' il
      // difetto che Paolo ha trovato l'08/11/2026 sull'eliminazione di un
      // libro solo. Si prende il motivo del PRIMO rifiuto — quando sono
      // tutti lo stesso, come in sola lettura, e' quello giusto per tutti.
      const conto = t('library.bulkDelete.someFailed', {
        n: rifiutate.length, total: books.length,
      })
      // Ripiego vuoto di proposito: senza `detail` dal server il conto e'
      // gia' tutto quello che si sa, e una seconda frase generica
      // raddoppierebbe il nulla.
      const motivo = messaggioErrore(rifiutate[0].reason, '')
      setError(motivo ? `${conto} ${motivo}` : conto)
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
