import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, ChevronDown, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAnnotations } from '@/lib/annotationQueries'
import type { Highlight } from '@/types/annotation'
import { useLingua } from '@/lib/i18n'

// Le annotazioni che non sono legate a nessun libro.
//
// Sono il caso opposto delle vedove: quelle hanno un libro che non esiste
// piu', queste non ne hanno mai avuto uno — arrivano da un dispositivo che
// leggeva un file che il server non ha mai riconosciuto.
//
// Finora non avevano una casa. Si vedevano nella pagina Annotazioni, che
// pero' si limitava a dire "vai su Dispositivi ▸ Da rivedere per
// accoppiarla", e l'accoppiamento vero vive nel flusso dei libri segnalati
// di un dispositivo. Tre pagine, e nessuna che dicesse quante ne sono in
// attesa.
//
// Qui NON si riscrive quell'accoppiamento: si conta, si dice da quale
// dispositivo e da quale file vengono, e si porta dove si risolvono. La
// pagina Interventi serve a sapere cosa c'e' da decidere, non a
// raddoppiare i posti in cui si decide.

interface Gruppo {
  chiave: string
  titolo: string
  dispositivo: string
  quante: number
  deviceId: number | null
  /** Le note stesse: servono a riconoscere il libro da cui vengono. */
  note: Highlight[]
}

export function OrphanNotesPanel() {
  const { t } = useLingua()
  const navigate = useNavigate()
  // Il nome del file spesso non dice niente ("book_0412.epub"), mentre il
  // TESTO delle note dice subito di che libro si tratta — che e' proprio
  // l'informazione che serve per accoppiarlo a mano.
  const [aperti, setAperti] = useState<Set<string>>(new Set())

  function apriChiudi(chiave: string) {
    setAperti((prec) => {
      const p = new Set(prec)
      if (p.has(chiave)) p.delete(chiave)
      else p.add(chiave)
      return p
    })
  }

  const { data: note = [] } = useAnnotations()

  const gruppi = useMemo(() => {
    const per = new Map<string, Gruppo>()
    for (const n of note) {
      // Solo le orfane vive: una nota cestinata non aspetta nessuna
      // decisione, aspetta solo di essere dimenticata.
      if (!n.is_orphan || n.trashed) continue
      const chiave = n.orphan_key || String(n.id)
      const g = per.get(chiave)
      if (g) {
        g.quante += 1
        g.note.push(n)
      } else
        per.set(chiave, {
          chiave,
          titolo: n.book_title || t('interventions.orphanNotes.unknownFile'),
          dispositivo: n.device_name || t('interventions.orphanNotes.unknownDevice'),
          quante: 1,
          deviceId: n.device_id ?? null,
          note: [n],
        })
    }
    return [...per.values()].sort((a, b) => b.quante - a.quante)
  }, [note, t])

  const totale = gruppi.reduce((sum, g) => sum + g.quante, 0)
  if (gruppi.length === 0) {
    return <p className="text-[13px] text-muted-foreground">{t('interventions.orphanNotes.none')}</p>
  }

  const filePhrase =
    gruppi.length === 1
      ? t('interventions.orphanNotes.oneFile')
      : t('interventions.orphanNotes.fileCount', { count: gruppi.length, n: gruppi.length })

  return (
    <>
      <p className="mb-3 text-[12.5px] text-muted-foreground">
        {t('interventions.orphanNotes.intro', { count: totale, n: totale, files: filePhrase })}
      </p>

      <div className="flex flex-col gap-1">
        {gruppi.map((g) => {
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
                  <span className="min-w-0 truncate" title={g.titolo}>
                    {g.titolo}
                    <span className="text-muted-foreground"> · {g.dispositivo}</span>
                  </span>
                </button>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {t('interventions.orphanNotes.noteCount', { count: g.quante, n: g.quante })}
                </span>
                {g.deviceId != null && (
                  <Button variant="outline" size="xs" onClick={() => navigate(`/dispositivi/${g.deviceId}`)}>
                    {t('interventions.orphanNotes.pairButton')}
                    <ArrowRight className="size-3" />
                  </Button>
                )}
              </div>
              {aperto && (
                <ul className="mb-1 ml-5 flex flex-col gap-1 border-l border-border pl-3">
                  {g.note.map((n) => (
                    <li key={n.id} className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
                      <span className="min-w-0 flex-1 italic text-muted-foreground">
                        “{(n.text || '').trim().slice(0, 160)}
                        {(n.text || '').trim().length > 160 ? '…' : ''}”
                      </span>
                      {n.chapter && <span className="shrink-0 text-[11px] text-muted-foreground">{n.chapter}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )
        })}
      </div>
    </>
  )
}

/** Quante annotazioni orfane aspettano: serve all'intestazione. */
export function useQuanteOrfane(): number | null {
  const { data } = useAnnotations()
  if (!data) return null
  return data.filter((n) => n.is_orphan && !n.trashed).length
}
