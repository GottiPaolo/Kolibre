import { useState } from 'react'
import { Search, AlertTriangle } from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { withBackendUrl } from '@/lib/api'
import { searchFulltext, useFulltextStatus } from '@/lib/fulltextActions'
import { openBookInReader } from '@/lib/readerActions'
import type { FulltextSearchResult } from '@/types/library'
import { useLingua } from '@/lib/i18n'

interface FulltextSearchDialogProps {
  libraryFolder: string
  onClose: () => void
}

// Ricerca nel testo di tutti i libri della libreria (non solo titolo/
// autore/tag come la barra di ricerca principale) — porting di
// FulltextSearchModal.vue. Un risultato cliccato apre il web reader con un
// deep-link (searchTerm) al punto trovato — l'indice full-text è testo
// semplice estratto, non CFI, quindi il reader stesso rifà la propria
// ricerca client-side sul termine e salta al primo hit reale (stesso
// comportamento del Vue esistente, onOpenFulltextResult).
export function FulltextSearchDialog({ libraryFolder, onClose }: FulltextSearchDialogProps) {
  const { t } = useLingua()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<FulltextSearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { data: stato } = useFulltextStatus(libraryFolder)

  // Quanti libri la ricerca sta davvero guardando. Serve qui e non solo
  // nelle Impostazioni perche' e' qui che cambia il senso di quello che si
  // legge: "nessun risultato" su un indice parziale non vuol dire che la
  // parola non c'e', vuol dire che non c'e' NEI LIBRI INDICIZZATI — e i
  // due casi erano indistinguibili.
  const scoperti = stato ? Math.max(0, stato.total - stato.indexed) : 0
  const parziale = !!stato && scoperti > 0

  async function runSearch(e?: React.FormEvent) {
    e?.preventDefault()
    const q = query.trim()
    if (!q) return
    setSearching(true)
    setError(null)
    try {
      setResults(await searchFulltext(libraryFolder, q))
    } catch {
      setError(t('library.fulltext.searchError'))
    } finally {
      setSearching(false)
    }
  }

  function openResult(result: FulltextSearchResult) {
    onClose()
    openBookInReader(
      { id: result.id, title: result.title, formats: [result.format] },
      libraryFolder,
      { searchTerm: query.trim() }
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[85vh] max-w-6xl flex-col">
        <DialogHeader>
          <DialogTitle>{t('library.fulltext.open')}</DialogTitle>
        </DialogHeader>

        <form onSubmit={runSearch} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground/70" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('library.fulltext.placeholder')}
              className="w-full rounded-md border border-border bg-background py-1.5 pr-2.5 pl-7 text-[13px] outline-none focus:border-primary"
            />
          </div>
        </form>

        {stato && (
          <p
            className={`flex items-start gap-1.5 text-[11.5px] leading-relaxed ${
              parziale ? 'text-[var(--warning)]' : 'text-muted-foreground'
            }`}
          >
            {parziale && <AlertTriangle className="mt-px size-3.5 shrink-0" />}
            <span>
              {parziale
                ? `${t('library.fulltext.coveragePartial', {
                    indexed: stato.indexed,
                    total: stato.total,
                    missing: t('library.fulltext.missingCount', { count: scoperti, n: scoperti }),
                  })} ${
                    stato.limit_reached
                      ? t('library.fulltext.limitReached', { gb: stato.limit_gb })
                      : stato.progress?.running
                        ? t('library.fulltext.indexingInProgress')
                        : t('library.fulltext.completeFromSettings')
                  }`
                : t('library.fulltext.coverageFull', { total: stato.total })}
            </span>
          </p>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto">
          {searching && <p className="p-3 text-[12.5px] text-muted-foreground">{t('library.fulltext.searching')}</p>}
          {error && <p className="p-3 text-[12.5px] text-destructive">{error}</p>}
          {!searching && results && results.length === 0 && (
            <p className="p-3 text-[12.5px] text-muted-foreground">{t('library.fulltext.noResults', { query })}</p>
          )}
          {!searching && results && results.length > 0 && (
            <ul className="flex flex-col gap-1.5">
              {results.map((r, i) => (
                <li key={`${r.id}-${i}`}>
                  <button
                    onClick={() => openResult(r)}
                    className="flex w-full items-start gap-3 rounded-md border border-border/60 p-2.5 text-left hover:bg-accent/60"
                  >
                    {r.cover_url ? (
                      <img src={withBackendUrl(r.cover_url)} alt="" className="h-14 w-10 shrink-0 rounded-sm object-cover" />
                    ) : (
                      <div className="h-14 w-10 shrink-0 rounded-sm bg-muted" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-1.5">
                        <span className="truncate font-serif text-[13px] font-medium">{r.title}</span>
                        <span className="shrink-0 rounded border border-border bg-muted px-1 py-0.5 text-[10px] font-semibold text-muted-foreground">
                          {r.format}
                        </span>
                      </div>
                      <div className="text-[11.5px] text-muted-foreground">{r.author}</div>
                      <p
                        className="mt-1 text-[12px] leading-snug text-muted-foreground [&_b]:font-semibold [&_b]:text-foreground"
                        dangerouslySetInnerHTML={{ __html: r.snippet_html }}
                      />
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
