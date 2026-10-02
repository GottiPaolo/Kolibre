import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { searchAuthorImages, setAuthorPhotoFromUrl } from '@/lib/authorActions'
import { messaggioErrore } from '@/lib/messaggiErrore'
import type { AuthorImageResult } from '@/types/author'
import { useLingua } from '@/lib/i18n'

interface AuthorPhotoSearchDialogProps {
  authorName: string
  onClose: () => void
  onApplied: () => void
}

export function AuthorPhotoSearchDialog({ authorName, onClose, onApplied }: AuthorPhotoSearchDialogProps) {
  const { t } = useLingua()
  const [query, setQuery] = useState(authorName)
  const [results, setResults] = useState<AuthorImageResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // L'indirizzo incollato a mano. Aggiunto il 01/10/2026: la ricerca
  // su Commons copre gli autori che Wikipedia conosce, e per tutti gli altri —
  // o quando la foto giusta sta da un'altra parte — l'unica strada era
  // scaricare il file e ricaricarlo.
  const [indirizzo, setIndirizzo] = useState('')
  const [scaricando, setScaricando] = useState(false)

  async function runSearch() {
    setLoading(true)
    setError(null)
    try {
      const found = await searchAuthorImages(query)
      setResults(found)
      if (found.length === 0) setError(t('authors.photoSearch.noResults'))
    } catch {
      setError(t('authors.photoSearch.searchFailed'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    runSearch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function daIndirizzo() {
    const url = indirizzo.trim()
    if (!url) return
    setScaricando(true)
    setError(null)
    try {
      await setAuthorPhotoFromUrl(authorName, url)
      onApplied()
    } catch (err) {
      // Il messaggio del server e' gia' scritto per una persona — «L'indirizzo
      // punta dentro la rete locale», «Non sembra un'immagine» — e dirlo com'e'
      // spiega cosa correggere; un «non riuscito» nostro no.
      setError(messaggioErrore(err, t('authors.photoSearch.downloadFailed')))
    } finally {
      setScaricando(false)
    }
  }

  async function choose(result: AuthorImageResult) {
    try {
      // La miniatura (600px) evita di superare il limite di 5MB lato
      // server con gli originali Commons a piena risoluzione.
      await setAuthorPhotoFromUrl(authorName, result.thumb_url || result.url)
      onApplied()
    } catch {
      setError(t('authors.photoSearch.setFailed'))
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('authors.photoSearch.title', { name: authorName })}</DialogTitle>
        </DialogHeader>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            runSearch()
          }}
          className="flex gap-2"
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
          />
        </form>

        {/* Oppure l'indirizzo di un'immagine qualunque. Sotto la ricerca e non
            accanto: la ricerca e' la strada normale, questa quella per quando
            non basta. */}
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void daIndirizzo()
          }}
          className="flex items-center gap-2"
        >
          <input
            value={indirizzo}
            onChange={(e) => setIndirizzo(e.target.value)}
            placeholder={t('authors.photoSearch.urlPlaceholder')}
            className="flex-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
          />
          <Button type="submit" size="sm" disabled={!indirizzo.trim() || scaricando}>
            {scaricando ? <Loader2 className="size-3.5 animate-spin" /> : t('authors.photoSearch.download')}
          </Button>
        </form>

        {loading && <p className="text-[12.5px] text-muted-foreground">{t('library.fulltext.searching')}</p>}
        {error && <p className="text-[12.5px] text-muted-foreground">{error}</p>}

        <div className="grid max-h-[50vh] grid-cols-[repeat(auto-fill,minmax(100px,1fr))] gap-2 overflow-y-auto">
          {results.map((r) => (
            <button key={r.url} onClick={() => choose(r)} className="flex flex-col items-center gap-1 rounded-md p-1 hover:bg-accent">
              <img src={r.thumb_url} alt={r.title} className="aspect-square w-full rounded object-cover" />
              <span className="line-clamp-2 text-[10.5px] text-muted-foreground">{r.title}</span>
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
