// Note rimaste senza libro, e come rimetterle al loro posto.
//
// Compare solo quando ce ne sono: è una riparazione, non una funzione di
// tutti i giorni. Non ricollega niente da sola — due edizioni dello stesso
// testo prendono lo stesso punteggio pieno (accaduto davvero: il titolo di
// un'opera e il titolo del suo primo volume, 78 riscontri su 78 entrambi),
// e fra le due deve scegliere una persona.
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookX, Link2, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { toast } from '@/lib/toast'
import {
  fetchWidowedGroups,
  fetchWidowedSuggestions,
  repairWidowedGroup,
  type WidowedCandidate,
  type WidowedGroup,
} from '@/lib/annotationActions'
import { useLingua, type Valori } from '@/lib/i18n'

export function WidowedNotesPanel() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const [aperto, setAperto] = useState<string | null>(null)

  const { data: gruppi = [] } = useQuery({
    queryKey: ['annotations', 'widowed'],
    queryFn: fetchWidowedGroups,
  })

  if (gruppi.length === 0) return null

  const totale = gruppi.reduce((sum, g) => sum + g.count, 0)
  const booksPhrase =
    gruppi.length === 1
      ? t('interventions.widowed.oneBookGone')
      : t('interventions.widowed.booksGoneCount', { n: gruppi.length })

  return (
    <div className="mb-4 rounded-lg border border-border bg-card p-3">
      <div className="flex items-center gap-2">
        <BookX className="size-4 shrink-0 text-muted-foreground" />
        <span className="text-[13px]">
          <strong>{totale}</strong> {t('interventions.widowed.intro', { count: totale, n: totale, books: booksPhrase })}
        </span>
      </div>
      <p className="mt-1 mb-2 text-[12px] text-muted-foreground">
        {t('interventions.widowed.explanation')}
      </p>

      <div className="flex flex-col gap-1.5">
        {gruppi.map((g) => {
          const chiave = `${g.library}/${g.calibre_book_id}`
          return (
            <GruppoVedovo
              key={chiave}
              gruppo={g}
              aperto={aperto === chiave}
              onApri={() => setAperto(aperto === chiave ? null : chiave)}
              onRiparato={() => {
                setAperto(null)
                void queryClient.invalidateQueries({ queryKey: ['annotations'] })
              }}
              t={t}
            />
          )
        })}
      </div>
    </div>
  )
}

function GruppoVedovo({
  gruppo, aperto, onApri, onRiparato, t,
}: {
  gruppo: WidowedGroup
  aperto: boolean
  onApri: () => void
  onRiparato: () => void
  t: (chiave: string, valori?: Valori) => string
}) {
  // Le proposte si cercano solo quando il gruppo viene aperto: ogni nota è
  // un'interrogazione dell'indice full-text, che su una biblioteca vera pesa
  // un paio di gigabyte. Non è lavoro da fare per tutti i gruppi all'arrivo
  // in pagina, quando magari all'utente ne interessa uno.
  const { data, isLoading } = useQuery({
    queryKey: ['annotations', 'widowed', gruppo.library, gruppo.calibre_book_id],
    queryFn: () => fetchWidowedSuggestions(gruppo.library, gruppo.calibre_book_id),
    enabled: aperto,
  })

  const ripara = useMutation({
    mutationFn: (c: WidowedCandidate) => repairWidowedGroup(gruppo, c),
    onSuccess: (spostate) => {
      toast.success(t('interventions.widowed.relinkedCount', { count: spostate, n: spostate }))
      onRiparato()
    },
    onError: () => toast.error(t('interventions.widowed.relinkFailed')),
  })

  return (
    <div className="rounded-md border border-border/70">
      <button
        type="button"
        onClick={onApri}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px] hover:bg-accent/40"
      >
        <span className="font-medium">{t('interventions.widowed.noteCountLabel', { count: gruppo.count, n: gruppo.count })}</span>
        <span className="min-w-0 flex-1 truncate text-muted-foreground">
          {gruppo.chapters.length > 0 ? gruppo.chapters.join(' · ') : gruppo.samples[0] || '—'}
        </span>
        <span className="shrink-0 text-[11px] text-muted-foreground">
          {t('interventions.widowed.libraryIdLabel', { library: gruppo.library, id: gruppo.calibre_book_id })}
        </span>
      </button>

      {aperto && (
        <div className="border-t border-border/70 px-2.5 py-2">
          {isLoading && (
            <p className="flex items-center gap-2 text-[12px] text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" />
              {t('interventions.widowed.searching')}
            </p>
          )}
          {!isLoading && data && data.candidates.length === 0 && (
            <p className="text-[12px] text-muted-foreground">
              {t('interventions.widowed.noCandidates')}
              {data.searched > 0
                ? ` ${t('interventions.widowed.searchedPhrasesCount', { count: data.searched, n: data.searched })}`
                : ''}
              {t('interventions.widowed.noCandidatesExplanation')}
            </p>
          )}
          {!isLoading && data && data.candidates.length > 0 && (
            <>
              <p className="mb-1.5 text-[11.5px] text-muted-foreground">
                {t('interventions.widowed.searchedPhrasesIntro', { count: data.searched, n: data.searched })}
              </p>
              <div className="flex flex-col gap-1">
                {data.candidates.map((c) => (
                  <div key={`${c.library}/${c.calibre_book_id}`} className="flex items-center gap-2">
                    <span className="w-12 shrink-0 text-right text-[12px] tabular-nums">
                      {c.matches}/{data.searched}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[12.5px]">
                      {c.title}
                      {c.authors && <span className="text-muted-foreground"> — {c.authors}</span>}
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={ripara.isPending}
                      onClick={() => ripara.mutate(c)}
                    >
                      <Link2 className="size-3.5" />
                      {t('interventions.widowed.relinkButton')}
                    </Button>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}


/** Quanti gruppi di note vedove aspettano: serve all'intestazione della
 *  sezione, che si legge da chiusa. */
export function useQuanteVedove(): number | null {
  const { data } = useQuery({
    queryKey: ['annotations', 'widowed'],
    queryFn: fetchWidowedGroups,
  })
  return data ? data.length : null
}
