import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useLingua } from '@/lib/i18n'
import type { Book, MetadataCandidate } from '@/types/library'
import { cercaMetadatiOnline, type EsitoFonte } from '@/lib/bookActions'

interface MetadataSearchResultsDialogProps {
  book: Book
  libraryFolder: string
  initialCandidates: MetadataCandidate[]
  onClose: () => void
  onSelectCandidate: (candidate: MetadataCandidate, allCandidates: MetadataCandidate[]) => void
}

export function MetadataSearchResultsDialog({
  book,
  libraryFolder,
  initialCandidates,
  onClose,
  onSelectCandidate,
}: MetadataSearchResultsDialogProps) {
  const { t } = useLingua()
  const [candidates, setCandidates] = useState(initialCandidates)
  const [fonti, setFonti] = useState<EsitoFonte[]>([])
  const [loading, setLoading] = useState(initialCandidates.length === 0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (initialCandidates.length > 0) return
    let cancelled = false
    cercaMetadatiOnline(libraryFolder, book.id)
      .then(({ candidates: results, fonti: esiti }) => {
        if (cancelled) return
        setCandidates(results)
        setFonti(esiti || [])
        setLoading(false)
        if (results.length === 0) setError(t('library.metadata.noOnlineResults'))
      })
      .catch(() => {
        if (!cancelled) {
          setError(t('library.metadata.onlineSearchFailed'))
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('library.metadata.searchResultsTitle', { title: book.title })}</DialogTitle>
        </DialogHeader>

        {loading && <p className="text-[12.5px] text-muted-foreground">{t('library.metadata.searching')}</p>}
        {error && <p className="text-[12.5px] text-muted-foreground">{error}</p>}

        {/* Una lista corta puo' voler dire "questo libro non e' nei
            cataloghi" oppure "una delle tre fonti oggi non risponde": senza
            dirlo, le due cose sono identiche a chi guarda. */}
        {fonti.filter((f) => f.stato !== 'ok').map((f) => (
          <p key={f.nome} className="flex items-start gap-1.5 text-[11.5px] leading-snug text-[var(--warning)]">
            <AlertTriangle className="mt-px size-3.5 shrink-0" />
            <span><b>{f.nome}</b>: {f.dettaglio || t('library.metadata.sourceNoResponse')}</span>
          </p>
        ))}

        <div className="flex max-h-[60vh] flex-col gap-1.5 overflow-y-auto">
          {candidates.map((cand, idx) => (
            <button
              key={idx}
              onClick={() => onSelectCandidate(cand, candidates)}
              className="flex items-center gap-3 rounded-md border border-border p-2 text-left hover:bg-accent"
            >
              <div className="h-16 w-11 shrink-0 overflow-hidden rounded bg-muted">
                {cand.cover_url && <img src={cand.cover_url} alt="" className="h-full w-full object-cover" />}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium">{cand.title ?? t('library.metadata.untitled')}</p>
                <p className="truncate text-[12px] text-muted-foreground">{cand.author}</p>
                <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                  <span>{cand.source}</span>
                  {cand.pubdate_year ? <span>· {cand.pubdate_year}</span> : null}
                  {/* Wikidata descrive l'OPERA, le altre due l'EDIZIONE: 1867
                      e 2015 sono due risposte giuste a due domande diverse, e
                      senza questa etichetta sembrano una contraddizione. */}
                  {cand.livello === 'opera' && (
                    <span className="rounded border border-border px-1 py-px text-[10px]">
                      {t('library.metadata.workNotEditionData')}
                    </span>
                  )}
                </p>
              </div>
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
