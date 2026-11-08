import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, ChevronDown, ChevronRight, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAnnotations } from '@/lib/annotationQueries'
import { retryFailedPositions } from '@/lib/annotationActions'
import type { Highlight } from '@/types/annotation'
import { useLingua } from '@/lib/i18n'

// Le annotazioni che hanno un libro ma non un punto nel libro.
//
// Sono la terza categoria, dopo le orfane (nessun libro) e le vedove (libro
// cancellato): queste il libro ce l'hanno, e aprendole il lettore non sa dove
// portarti. Dal 24/09/2026 te lo dice invece di aprire il libro dove capita,
// ma quello e' un cerotto — serve a distinguere un difetto da una nota che
// davvero non si puo' agganciare, non a risolvere.
//
// Questo pannello esiste per rispondere alla domanda che veniva dopo, e che
// dai dati di sviluppo non si puo' rispondere: QUANTE sono, e su QUALI libri.
// Se sono concentrate su pochi titoli il problema e' in quei file; se sono
// sparse su tutta la biblioteca il problema e' nel convertitore che traduce
// le posizioni di KOReader in CFI. Sono due indagini diverse, e il conteggio
// e' quello che dice quale delle due aprire.
//
// Sta in Interventi e non fra le statistiche perche' una decisione la chiede
// davvero: rimettere in coda la conversione, che per le note fallite in modo
// transitorio (un file non ancora indicizzato, un errore di rete) basta.

interface PerLibro {
  chiave: string
  titolo: string
  library: string
  bookId: number
  senzaAncora: number
  fallite: number
  /** Le note stesse: il conteggio dice quante, queste dicono QUALI. */
  note: Highlight[]
}

/** Una nota che ha un libro ma nessun punto utilizzabile dentro di esso. */
function senzaPosizione(n: { is_orphan: boolean; trashed: boolean; calibre_book_id: number | null; cfi_start: string | null; position_status: string | null }) {
  if (n.is_orphan || n.trashed || n.calibre_book_id == null) return false
  // Nessuna ancora, oppure un'ancora che la conversione ha dichiarato fallita.
  return !n.cfi_start || n.position_status === 'failed'
}

export function NotesWithoutPositionPanel() {
  const { t } = useLingua()
  const navigate = useNavigate()
  const { data: note = [], refetch } = useAnnotations()
  const [rimesse, setRimesse] = useState<number | null>(null)
  const [inCorso, setInCorso] = useState(false)
  // Quali libri sono aperti. Il conteggio da solo non basta a decidere:
  // per capire SE una nota e' recuperabile bisogna vederne il testo — una
  // frase lunga si ritrova, tre parole no.
  const [aperti, setAperti] = useState<Set<string>>(new Set())

  function apriChiudi(chiave: string) {
    setAperti((prec) => {
      const p = new Set(prec)
      if (p.has(chiave)) p.delete(chiave)
      else p.add(chiave)
      return p
    })
  }

  const { gruppi, totale, totaleNote } = useMemo(() => {
    const per = new Map<string, PerLibro>()
    let tot = 0
    for (const n of note) {
      if (!senzaPosizione(n)) continue
      tot += 1
      const chiave = `${n.library}/${n.calibre_book_id}`
      const g = per.get(chiave) ?? {
        chiave,
        titolo: n.book_title || `Libro #${n.calibre_book_id}`,
        library: n.library || '',
        bookId: n.calibre_book_id as number,
        senzaAncora: 0,
        fallite: 0,
        note: [],
      }
      if (n.position_status === 'failed') g.fallite += 1
      else g.senzaAncora += 1
      g.note.push(n)
      per.set(chiave, g)
    }
    const vive = note.filter((n) => !n.is_orphan && !n.trashed).length
    return {
      gruppi: [...per.values()].sort((a, b) => b.senzaAncora + b.fallite - (a.senzaAncora + a.fallite)),
      totale: tot,
      totaleNote: vive,
    }
  }, [note])

  async function rimettiInCoda() {
    setInCorso(true)
    try {
      setRimesse(await retryFailedPositions())
      await refetch()
    } catch {
      setRimesse(-1)
    } finally {
      setInCorso(false)
    }
  }

  if (gruppi.length === 0) {
    return <p className="text-[13px] text-muted-foreground">{t('interventions.notesWithoutPosition.allPositioned')}</p>
  }

  const percentuale = totaleNote > 0 ? Math.round((totale / totaleNote) * 100) : 0

  return (
    <>
      <p className="mb-1 text-[12.5px] text-muted-foreground">
        <b className="text-foreground tabular-nums">{totale}</b> {t('interventions.notesWithoutPosition.countMiddle')}{' '}
        <b className="text-foreground tabular-nums">{totaleNote}</b>{' '}
        {t('interventions.notesWithoutPosition.countSuffix', { percent: percentuale })}
      </p>
      {/* La forma del problema conta più del totale: concentrato su pochi
          libri significa "quei file", sparso significa "il convertitore". */}
      <p className="mb-3 text-[12.5px] text-muted-foreground">
        {t('interventions.notesWithoutPosition.spreadPrefix')}{' '}
        <b className="text-foreground tabular-nums">{gruppi.length}</b>{' '}
        {t('interventions.notesWithoutPosition.bookWord', { count: gruppi.length, n: gruppi.length })}
        {gruppi.length <= 3
          ? t('interventions.notesWithoutPosition.concentratedSuffix')
          : t('interventions.notesWithoutPosition.spreadSuffix')}
      </p>

      {/* Dal 25/09/2026 riprovare ha un senso nuovo: il convertitore ha
          imparato a cercare il testo della nota in TUTTO il libro, non solo
          nel capitolo che l'xpointer dichiarava. Le note fallite prima di
          quella data non hanno mai avuto quella possibilità. */}
      <p className="mb-2 text-[12.5px] leading-relaxed text-muted-foreground">
        {t('interventions.notesWithoutPosition.retryExplanation')}
      </p>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Button variant="outline" size="xs" onClick={() => void rimettiInCoda()} disabled={inCorso}>
          <RotateCcw className="size-3" />
          {inCorso ? t('interventions.notesWithoutPosition.requeueInProgress') : t('interventions.notesWithoutPosition.requeueButton')}
        </Button>
        {rimesse != null && (
          <span className="text-[12px] text-muted-foreground">
            {rimesse < 0
              ? t('interventions.notesWithoutPosition.requeueFailed')
              : rimesse === 0
                ? t('interventions.notesWithoutPosition.requeueNoneFailed')
                : t('interventions.notesWithoutPosition.requeuedCount', { count: rimesse, n: rimesse })}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1">
        {gruppi.slice(0, 40).map((g) => {
          const aperto = aperti.has(g.chiave)
          const Freccia = aperto ? ChevronDown : ChevronRight
          return (
            <div key={g.chiave} className="rounded-md">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-1 py-1.5 text-[13px] hover:bg-accent/50">
                <button
                  onClick={() => apriChiudi(g.chiave)}
                  className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                  aria-expanded={aperto}
                >
                  <Freccia className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 truncate" title={g.titolo}>{g.titolo}</span>
                </button>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {g.senzaAncora > 0 && t('interventions.notesWithoutPosition.missingAnchorCount', { n: g.senzaAncora })}
                  {g.senzaAncora > 0 && g.fallite > 0 && ' · '}
                  {g.fallite > 0 && t('interventions.notesWithoutPosition.failedConversionCount', { count: g.fallite, n: g.fallite })}
                </span>
                <Button variant="ghost" size="xs" onClick={() => navigate(`/libri/${g.bookId}`)}>
                  {t('interventions.notesWithoutPosition.openBookButton')}
                  <ArrowRight className="size-3" />
                </Button>
              </div>
              {aperto && (
                <ul className="mb-1 ml-5 flex flex-col gap-1 border-l border-border pl-3">
                  {g.note.map((n) => (
                    <li key={n.id} className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
                      <span className="min-w-0 flex-1 italic text-muted-foreground">
                        “{(n.text || '').trim().slice(0, 160)}
                        {(n.text || '').trim().length > 160 ? '…' : ''}”
                      </span>
                      {/* Lo stato dice quale rimedio ha senso: "fallita" si
                          rimette in coda, "senza punto" no. */}
                      <span className="shrink-0 rounded border border-border px-1 py-px text-[10.5px] text-muted-foreground">
                        {n.position_status === 'failed'
                          ? t('interventions.notesWithoutPosition.statusFailed')
                          : t('interventions.notesWithoutPosition.statusNoAnchor')}
                      </span>
                      {n.chapter && <span className="shrink-0 text-[11px] text-muted-foreground">{n.chapter}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )
        })}
        {gruppi.length > 40 && (
          <p className="px-2 pt-1 text-[12px] text-muted-foreground">
            {t('interventions.notesWithoutPosition.moreBooksSuffix', { count: gruppi.length - 40, n: gruppi.length - 40 })}
          </p>
        )}
      </div>
    </>
  )
}

/** Quante annotazioni non sanno dove stanno: serve all'intestazione. */
export function useQuanteSenzaPosizione(): number | null {
  const { data } = useAnnotations()
  if (!data) return null
  return data.filter(senzaPosizione).length
}
