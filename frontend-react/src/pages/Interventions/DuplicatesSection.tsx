import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Loader2, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { openBookFormatInReader } from '@/lib/readerActions'
import { formatBytes } from '@/lib/format'
import { toast } from '@/lib/toast'
import { leggiLingua, localeDi, useLingua, type Valori } from '@/lib/i18n'

// I doppioni: trovarli, guardarli, decidere.
//
// La pipeline e' quella del backend — affinita' sui metadati, poi hash, poi
// qualita' — e questa pagina ne mostra il risultato rispettando la sua
// distinzione piu' importante: l'automatismo agisce SOLO sui file
// identici. Dove i file differiscono si suggerisce quale tenere, ma
// decide una persona, perche' la prova che siano lo stesso libro e' una
// somiglianza di titolo e non una certezza.

interface Membro {
  library: string
  id: number
  title: string
  author: string
  formats: string[]
  size: number
  formato_principale: string | null
  hash: string | null
  qualita: number | null
  qualita_dettaglio: Record<string, { punteggio: number }> | null
  leggibile: boolean | null
}

interface Azioni {
  automatico: boolean
  suggerimento: 'identici' | 'qualita' | null
  tenere: number | null
  scartare: number[]
  trattenuti: number[]
}

interface Risposta {
  gruppi: Gruppo[]
  gruppi_totali: number
  non_mostrati: number
  calcolato_il: string | null
  mai_cercato: boolean
}

interface Gruppo {
  chiave: string
  titolo: string
  autore: string
  membri: Membro[]
  identici: number[][]
  migliore: number | null
  azioni: Azioni
}

/** Le etichette dei criteri di qualità. Funzione e non una costante, come
 *  etichetteStato in EntitiesPage.tsx: deve ricalcolarsi al cambio lingua. */
function criteri(t: (chiave: string, valori?: Valori) => string): readonly [string, string][] {
  return [
    ['integrita', t('interventions.duplicates.criteria.integrity')],
    ['toc', t('interventions.duplicates.criteria.toc')],
    ['struttura', t('interventions.duplicates.criteria.structure')],
    ['css', t('interventions.duplicates.criteria.css')],
    ['peso', t('interventions.duplicates.criteria.weight')],
  ]
}

function Punteggio({ valore, t }: { valore: number | null; t: (chiave: string, valori?: Valori) => string }) {
  if (valore == null) return <span className="text-muted-foreground">{t('interventions.duplicates.notMeasurable')}</span>
  const colore = valore >= 70 ? 'var(--chart-2)' : valore >= 45 ? 'var(--chart-3)' : 'var(--chart-1)'
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-1.5 w-10 overflow-hidden rounded-full bg-muted">
        <span className="block h-full" style={{ width: `${valore}%`, backgroundColor: colore }} />
      </span>
      <span className="tabular-nums">{valore}</span>
    </span>
  )
}

export function DuplicatesSection({ libraryFolder }: { libraryFolder: string | undefined }) {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const [inCorso, setInCorso] = useState(false)
  // Quale tenere, per gruppo: parte dal suggerimento e si puo' cambiare.
  const [scelto, setScelto] = useState<Record<string, number>>({})

  // Si legge il risultato CONSERVATO, non se ne fa uno nuovo: cercare i
  // doppioni legge i file dal disco per calcolarne l'hash, e farlo ad ogni
  // apertura della pagina vorrebbe dire aspettare ogni volta.
  const { data } = useQuery({
    queryKey: ['doppioni', libraryFolder],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/interventions/duplicates', {
        params: { query: { library: libraryFolder } },
      })
      if (error) throw error
      return data as unknown as Risposta
    },
    enabled: !!libraryFolder,
  })

  async function cerca() {
    setInCorso(true)
    try {
      const { error } = await api.POST('/api/kolibre/interventions/duplicates/scan', {
        params: { query: { library: libraryFolder } },
      })
      if (error) throw error
      aggiorna()
    } catch {
      toast.error(t('interventions.duplicates.searchFailed'))
    }
    setInCorso(false)
  }

  const gruppi = data?.gruppi ?? []
  const automatici = gruppi.filter((g) => g.azioni.automatico).length

  function aggiorna() {
    queryClient.invalidateQueries({ queryKey: ['doppioni', libraryFolder] })
    queryClient.invalidateQueries({ queryKey: ['books'] })
    queryClient.invalidateQueries({ queryKey: ['books-page'] })
  }

  async function accorpa(g: Gruppo) {
    const tenere = scelto[g.chiave] ?? g.azioni.tenere ?? g.migliore
    if (tenere == null) return
    const per = new Map(g.membri.map((m) => [m.id, m]))
    const scartare = g.membri.filter((m) => m.id !== tenere).map((m) => ({ library: m.library, id: m.id }))
    if (!window.confirm(
      `${t('interventions.duplicates.confirmMergeTitle', { count: scartare.length, n: scartare.length, title: per.get(tenere)?.title ?? '' })}\n\n` +
      t('interventions.duplicates.confirmMergeNote')
    )) return
    setInCorso(true)
    try {
      const { error } = await api.POST('/api/kolibre/interventions/duplicates/merge', {
        params: { query: { library: libraryFolder } },
        body: { tenere: { library: per.get(tenere)!.library, id: tenere }, scartare },
      })
      if (error) throw error
      toast.success(t('interventions.duplicates.mergedSuccess'))
      aggiorna()
    } catch {
      toast.error(t('interventions.duplicates.mergeFailed'))
    }
    setInCorso(false)
  }

  async function distinti(g: Gruppo) {
    const coppie = []
    for (let i = 0; i < g.membri.length; i++) {
      for (let j = i + 1; j < g.membri.length; j++) {
        coppie.push({
          library_a: g.membri[i].library, book_a: g.membri[i].id,
          library_b: g.membri[j].library, book_b: g.membri[j].id,
        })
      }
    }
    try {
      const { error } = await api.POST('/api/kolibre/interventions/duplicates/distinct', { params: { query: { library: libraryFolder } }, body: { coppie, chiave: g.chiave } })
      if (error) throw error
      toast.success(t('interventions.duplicates.markedDistinct'))
      aggiorna()
    } catch {
      toast.error(t('interventions.duplicates.markDistinctFailed'))
    }
  }

  async function tuttiIdentici() {
    if (!window.confirm(
      `${t('interventions.duplicates.confirmMergeAllTitle', { count: automatici, n: automatici })}\n\n` +
      t('interventions.duplicates.confirmMergeAllNote')
    )) return
    setInCorso(true)
    try {
      const { data, error } = await api.POST('/api/kolibre/interventions/duplicates/merge-identical', {
        params: { query: { library: libraryFolder } },
      })
      if (error) throw error
      const r = data as unknown as { accorpati: number; lasciati: number }
      toast.success(t('interventions.duplicates.mergedAllResult', { merged: r.accorpati, left: r.lasciati }))
      aggiorna()
    } catch {
      toast.error(t('interventions.duplicates.mergeAllFailed'))
    }
    setInCorso(false)
  }

  const gruppiVisti = data?.gruppi ?? []

  return (
    <>
      <p className="mb-3 text-[12.5px] text-muted-foreground">
        {t('interventions.duplicates.introPrefix')}{' '}
        <strong>{t('interventions.duplicates.introStrong')}</strong>
        {t('interventions.duplicates.introSuffix')}
      </p>

      <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md bg-muted/40 p-2.5">
        <Button variant="outline" size="xs" onClick={() => void cerca()} disabled={inCorso || !libraryFolder}>
          {inCorso ? <Loader2 className="size-3.5 animate-spin" /> : null}
          {data?.mai_cercato ? t('interventions.duplicates.searchButton') : t('interventions.duplicates.searchAgainButton')}
        </Button>
        <span className="text-[11.5px] text-muted-foreground">
          {data?.mai_cercato
            ? t('interventions.duplicates.searchHintNeverDone')
            : data?.calcolato_il
              ? t('interventions.duplicates.lastSearchedAt', { date: new Date(data.calcolato_il).toLocaleString(localeDi(leggiLingua())) })
              : ''}
        </span>
        {automatici > 0 && (
          <>
            <ShieldCheck className="ml-auto size-3.5 text-muted-foreground" />
            <span className="text-[12px] text-muted-foreground">
              {t('interventions.duplicates.identicalGroupsCount', { count: automatici, n: automatici })}
            </span>
            <Button size="xs" onClick={() => void tuttiIdentici()} disabled={inCorso}>
              {t('interventions.duplicates.mergeAllIdenticalButton')}
            </Button>
          </>
        )}
      </div>

      {gruppiVisti.length === 0 && !data?.mai_cercato && (
        <p className="text-[13px] text-muted-foreground">{t('interventions.duplicates.noneFound')}</p>
      )}

      <div className="flex flex-col gap-3">
        {gruppi.map((g) => {
          const tenere = scelto[g.chiave] ?? g.azioni.tenere ?? g.migliore
          return (
            <div key={g.chiave} className="rounded-md border border-border/70 p-2.5">
              <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
                <span className="text-[13px] font-medium">{g.titolo}</span>
                <span className="text-[12px] text-muted-foreground">{g.autore}</span>
                {g.azioni.suggerimento === 'identici' && (
                  <span className="rounded-sm bg-[var(--chart-2)]/15 px-1.5 py-0.5 text-[11px] text-[var(--chart-2)]">
                    {t('interventions.duplicates.identicalBadge')}
                  </span>
                )}
              </div>

              <div className="flex flex-col gap-1">
                {g.membri.map((m) => (
                  <label
                    key={`${m.library}-${m.id}`}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded px-1.5 py-1 text-[12.5px] hover:bg-accent/50"
                  >
                    <input
                      type="radio"
                      name={`tenere-${g.chiave}`}
                      checked={tenere === m.id}
                      onChange={() => setScelto((s) => ({ ...s, [g.chiave]: m.id }))}
                    />
                    <span className="min-w-0 flex-1 truncate" title={m.title}>
                      {m.title}
                      <span className="text-muted-foreground"> · {m.library}</span>
                    </span>
                    <Punteggio valore={m.qualita} t={t} />
                    <span className="tabular-nums text-muted-foreground">{formatBytes(m.size)}</span>
                    <span className="text-muted-foreground">{m.formato_principale ?? '—'}</span>
                    {/* Un bottone per libro: si aprono in due finestre e si
                        confrontano a occhio, che e' il solo modo di decidere
                        quando i metadati non bastano.
                        openBookFormatInReader e non un link a mano — porta il
                        token di autenticazione e apre una finestra nominata
                        per libro, cosi' i due non si sovrascrivono a vicenda. */}
                    {m.formato_principale && (
                      <button
                        onClick={(e) => {
                          e.preventDefault()
                          e.stopPropagation()
                          void openBookFormatInReader(
                            { id: m.id, title: m.title, formats: m.formats },
                            m.library,
                            m.formato_principale!
                          )
                        }}
                        className="inline-flex items-center gap-1 text-primary hover:underline"
                      >
                        <BookOpen className="size-3" />
                        {t('interventions.duplicates.openButton')}
                      </button>
                    )}
                  </label>
                ))}
              </div>

              {/* Il dettaglio dei criteri, per capire da dove viene il
                  punteggio invece di doverci credere. */}
              {g.membri.some((m) => m.qualita_dettaglio) && (
                <p className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-muted-foreground/80">
                  {criteri(t).map(([chiave, etichetta]) => (
                    <span key={chiave}>
                      {etichetta}{' '}
                      {g.membri.map((m, i) => (
                        <span key={m.id}>
                          {i > 0 && '/'}
                          <span className={m.id === tenere ? 'text-foreground' : ''}>
                            {m.qualita_dettaglio?.[chiave]?.punteggio ?? '—'}
                          </span>
                        </span>
                      ))}
                    </span>
                  ))}
                </p>
              )}

              {g.azioni.trattenuti.length > 0 && (
                <p className="mt-1.5 text-[11.5px] text-muted-foreground">
                  {t('interventions.duplicates.hasNotesWarning', { count: g.azioni.trattenuti.length, n: g.azioni.trattenuti.length })}
                </p>
              )}

              <div className="mt-2 flex flex-wrap gap-2">
                <Button size="xs" onClick={() => void accorpa(g)} disabled={inCorso || tenere == null}>
                  {t('interventions.duplicates.keepSelectedButton')}
                </Button>
                <Button variant="outline" size="xs" onClick={() => void distinti(g)} disabled={inCorso}>
                  {t('interventions.duplicates.markDistinctButton')}
                </Button>
              </div>
            </div>
          )
        })}
      </div>

      {(data?.non_mostrati ?? 0) > 0 && (
        <p className="mt-2.5 text-[11.5px] text-muted-foreground">
          {t('interventions.duplicates.moreHiddenGroups', { count: data!.non_mostrati, n: data!.non_mostrati })}
        </p>
      )}
    </>
  )
}

/** Quanti gruppi aspettano: serve all'intestazione, che si vede a sezione chiusa. */
export function useQuantiDoppioni(libraryFolder: string | undefined): number | null {
  const { data } = useQuery({
    queryKey: ['doppioni', libraryFolder],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/interventions/duplicates', {
        params: { query: { library: libraryFolder } },
      })
      if (error) throw error
      return data as unknown as Risposta
    },
    enabled: !!libraryFolder,
  })
  return data ? data.gruppi.length : null
}
