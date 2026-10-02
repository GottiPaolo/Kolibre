import { useEffect, useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { Book } from '@/types/library'
import { useConvertInfo } from '@/lib/queries'
import { convertBookFormat } from '@/lib/bookActions'
import { useLingua } from '@/lib/i18n'

interface ConvertDialogProps {
  book: Book
  libraryFolder: string
  onClose: () => void
  onConverted: () => void
}

export function ConvertDialog({ book, libraryFolder, onClose, onConverted }: ConvertDialogProps) {
  const { t } = useLingua()
  const { data: info, isLoading } = useConvertInfo()
  // `?? ''` e non `book.formats[0]`: un record Calibre senza file esiste
  // (si crea aprendo i metadati, o eliminando l'unico formato), il menu
  // contestuale offre «Converti formato» su qualunque libro, e
  // `sourceFormat.toLowerCase()` qui sotto faceva saltare l'intero albero
  // React con un TypeError.
  const [sourceFormat, setSourceFormat] = useState(book.formats[0] ?? '')
  const [targetFormat, setTargetFormat] = useState('')
  const [addAsFormat, setAddAsFormat] = useState(false)
  const [status, setStatus] = useState<'idle' | 'converting' | 'done' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (info?.supported_targets.length && !targetFormat) {
      setTargetFormat(info.supported_targets.find((t) => t !== sourceFormat.toLowerCase()) ?? info.supported_targets[0])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [info])

  async function startConversion() {
    setStatus('converting')
    setError(null)
    try {
      const result = await convertBookFormat(libraryFolder, book.id, sourceFormat, targetFormat, addAsFormat)
      if (result.addedAsFormat) {
        onConverted()
      } else if (result.blob) {
        const url = URL.createObjectURL(result.blob)
        const a = document.createElement('a')
        a.href = url
        a.download = result.filename ?? `${book.title}.${targetFormat}`
        a.click()
        URL.revokeObjectURL(url)
      }
      setStatus('done')
      setTimeout(onClose, 1200)
    } catch (err) {
      setStatus('error')
      setError(err instanceof Error ? err.message : t('library.convert.failed'))
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('library.convert.title', { title: book.title })}</DialogTitle>
        </DialogHeader>

        {isLoading && <p className="text-[12.5px] text-muted-foreground">{t('library.convert.checkingEngine')}</p>}

        {!isLoading && !info?.available && (
          <p className="text-[12.5px] text-muted-foreground">
            {t('library.convert.engineUnavailable')} <code>KOLIBRE_EBOOK_CONVERT</code>.
          </p>
        )}

        {!isLoading && info?.available && (
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              {book.cover_url && <img src={book.cover_url} alt="" className="h-20 w-auto rounded border border-border" />}
              <div>
                <p className="text-[13px] font-medium">{book.title}</p>
                <p className="text-[12px] text-muted-foreground">{book.author}</p>
              </div>
            </div>

            <div>
              <label className="mb-1 block text-[11px] font-medium text-muted-foreground">{t('library.convert.sourceFormat')}</label>
              <Select value={sourceFormat} onValueChange={setSourceFormat}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {book.formats.map((f) => (
                    <SelectItem key={f} value={f}>
                      {f}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <label className="mb-1 block text-[11px] font-medium text-muted-foreground">{t('library.convert.targetFormat')}</label>
              <Select value={targetFormat} onValueChange={setTargetFormat}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {info.supported_targets.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t.toUpperCase()}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <label className="flex items-center gap-2 text-[12.5px]">
                <input type="radio" checked={!addAsFormat} onChange={() => setAddAsFormat(false)} />
                {t('library.convert.downloadFile')}
              </label>
              <label className="flex items-center gap-2 text-[12.5px]">
                <input type="radio" checked={addAsFormat} onChange={() => setAddAsFormat(true)} />
                {t('library.convert.addAsFormat')}
              </label>
            </div>

            {status === 'converting' && <p className="text-[12.5px] text-muted-foreground">{t('library.convert.converting')}</p>}
            {status === 'done' && <p className="text-[12.5px] text-primary">{t('library.convert.done')}</p>}
            {status === 'error' && <p className="text-[12.5px] text-destructive">{error}</p>}
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {info?.available ? t('common.cancel') : t('common.close')}
          </Button>
          {info?.available && (
            <Button onClick={startConversion} // I formati arrivano da due parti con due convenzioni: `book.formats` è
              // maiuscolo ('EPUB'), `supported_targets` minuscolo ('epub'). Il
              // confronto diretto era quindi sempre falso, e si poteva lanciare una
              // conversione EPUB→EPUB.
              disabled={
                status === 'converting' ||
                !sourceFormat ||
                sourceFormat.toLowerCase() === targetFormat.toLowerCase()
              }>
              {t('library.convert.convert')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
