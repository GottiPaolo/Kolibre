import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useLingua, type Valori } from '@/lib/i18n'
import type { ReadingSessionRaw } from '@/lib/statsQueries'
import { libriPerGiorno, type LibroDelGiorno } from './statsCompute'

type Traduci = (chiave: string, valori?: Valori) => string

// Il calendario di lettura: dentro ogni giorno, COSA si è letto.
//
// Prima era una seconda heatmap — gli stessi minuti della striscia 52-settimane
// in una griglia mensile, con un colore per cella. Due viste della stessa
// informazione, e la più grande era anche la più povera: lo spazio di una cella
// mensile basta per dei titoli, e il titolo è l'unica cosa che una heatmap non
// può dare. Scelta del 01/10/2026: non deve essere un'alternativa della
// heatmap, deve riportare dentro ai singoli giorni una riga per ogni libro
// letto, con affianco il tempo.
//
// La heatmap resta, e ora le due dicono cose diverse: quella quanto, questa che
// cosa.

function nomiMesi(t: Traduci): string[] {
  return [
    t('stats.calendar.monthFull.jan'), t('stats.calendar.monthFull.feb'), t('stats.calendar.monthFull.mar'),
    t('stats.calendar.monthFull.apr'), t('stats.calendar.monthFull.may'), t('stats.calendar.monthFull.jun'),
    t('stats.calendar.monthFull.jul'), t('stats.calendar.monthFull.aug'), t('stats.calendar.monthFull.sep'),
    t('stats.calendar.monthFull.oct'), t('stats.calendar.monthFull.nov'), t('stats.calendar.monthFull.dec'),
  ]
}

function inizialiGiorni(t: Traduci): string[] {
  return [
    t('stats.calendar.weekdayInitial.mon'),
    t('stats.calendar.weekdayInitial.tue'),
    t('stats.calendar.weekdayInitial.wed'),
    t('stats.calendar.weekdayInitial.thu'),
    t('stats.calendar.weekdayInitial.fri'),
    t('stats.calendar.weekdayInitial.sat'),
    t('stats.calendar.weekdayInitial.sun'),
  ]
}

// Quante righe stanno in una cella prima che diventi illeggibile. Oltre, si
// dice quante ne restano: un elenco troncato in silenzio fa sembrare che quel
// giorno si siano letti tre libri invece di sei.
const RIGHE_MASSIME = 3

/** Il tempo nella forma più corta che resti chiara: "1h20", "45m", "<1m". */
function durataCorta(secondi: number): string {
  const minuti = Math.round(secondi / 60)
  // "0m" sarebbe una bugia su un libro che è stato comunque aperto, e qui
  // succede spesso: la durata MEDIANA di un libro, sui dati veri, è un minuto.
  if (secondi > 0 && minuti === 0) return '<1m'
  if (minuti < 60) return `${minuti}m`
  const ore = Math.floor(minuti / 60)
  const resto = minuti % 60
  return resto ? `${ore}h${String(resto).padStart(2, '0')}` : `${ore}h`
}

/** Le celle del mese, lunedì come primo giorno, con i giorni di contorno. */
function celleDelMese(anno: number, mese: number) {
  const primo = new Date(anno, mese, 1)
  const inizio = new Date(primo)
  inizio.setDate(primo.getDate() - ((primo.getDay() + 6) % 7))
  const oggi = new Date()
  const oggiISO = `${oggi.getFullYear()}-${String(oggi.getMonth() + 1).padStart(2, '0')}-${String(oggi.getDate()).padStart(2, '0')}`
  const celle = []
  for (let i = 0; i < 42; i++) {
    const d = new Date(inizio)
    d.setDate(inizio.getDate() + i)
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    celle.push({
      iso,
      giorno: d.getDate(),
      nelMese: d.getMonth() === mese,
      oggi: iso === oggiISO,
      futuro: iso > oggiISO,
    })
    // Sei righe solo se servono: un mese che ci sta in cinque non deve
    // lasciarne una vuota in fondo.
    if (i >= 34 && d.getMonth() !== mese && (i + 1) % 7 === 0) break
  }
  return celle
}

/**
 * Il mese su cui aprirsi: quello corrente se ci si è letto, altrimenti l'ultimo
 * in cui si è letto qualcosa.
 *
 * Aprire sempre sul mese corrente significa, per chi non legge da due
 * settimane, aprire su una griglia vuota — e una griglia vuota non lascia
 * capire che il calendario sa mostrare i titoli.
 */
function mesePiuRecenteConLetture(sessions: ReadingSessionRaw[]): { anno: number; mese: number } {
  const oggi = new Date()
  const corrente = { anno: oggi.getFullYear(), mese: oggi.getMonth() }
  const prefisso = `${corrente.anno}-${String(corrente.mese + 1).padStart(2, '0')}`
  if (sessions.some((s) => s.date.startsWith(prefisso))) return corrente
  let ultima: string | null = null
  for (const s of sessions) if (!ultima || s.date > ultima) ultima = s.date
  if (!ultima) return corrente
  return { anno: Number(ultima.slice(0, 4)), mese: Number(ultima.slice(5, 7)) - 1 }
}

export function ReadingCalendar({ sessions }: { sessions: ReadingSessionRaw[] }) {
  const { t } = useLingua()
  const oggi = new Date()
  // Il mese mostrato si DERIVA finché nessuno ha navigato, e non si inizializza
  // con useState: al primo render le sessioni non sono ancora arrivate, quindi
  // un valore iniziale sarebbe calcolato su un elenco vuoto e resterebbe quello
  // — che è esattamente perché il calendario si apriva su un mese vuoto.
  const partenza = useMemo(() => mesePiuRecenteConLetture(sessions), [sessions])
  const [scelto, setScelto] = useState<{ anno: number; mese: number } | null>(null)
  const { anno, mese } = scelto ?? partenza
  const vaiA = (anno: number, mese: number) => setScelto({ anno, mese })

  const perGiorno = useMemo(() => libriPerGiorno(sessions), [sessions])
  const celle = useMemo(() => celleDelMese(anno, mese), [anno, mese])
  const meseCorrente = anno === oggi.getFullYear() && mese === oggi.getMonth()

  const totaleMese = useMemo(() => {
    let secondi = 0
    const titoli = new Set<string>()
    for (const c of celle) {
      if (!c.nelMese) continue
      for (const l of perGiorno.get(c.iso) ?? []) {
        secondi += l.secondi
        titoli.add(l.title)
      }
    }
    return { secondi, libri: titoli.size }
  }, [celle, perGiorno])

  function indietro() {
    if (mese === 0) vaiA(anno - 1, 11)
    else vaiA(anno, mese - 1)
  }
  function avanti() {
    if (meseCorrente) return
    if (mese === 11) vaiA(anno + 1, 0)
    else vaiA(anno, mese + 1)
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[12.5px] font-medium">
          {nomiMesi(t)[mese]} {anno}
          {totaleMese.secondi > 0 && (
            <span className="ml-2 font-normal text-muted-foreground">
              {t('stats.calendar.monthTotal', {
                duration: durataCorta(totaleMese.secondi),
                count: totaleMese.libri,
                n: totaleMese.libri,
              })}
            </span>
          )}
        </span>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="xs" onClick={indietro}>
            {t('stats.calendar.prev')}
          </Button>
          <Button variant="outline" size="xs" disabled={meseCorrente} onClick={avanti}>
            {t('stats.calendar.next')}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-7 gap-1">
        {inizialiGiorni(t).map((g, i) => (
          <div key={i} className="pb-0.5 text-center text-[10px] text-muted-foreground">
            {g}
          </div>
        ))}
        {celle.map((c) => {
          const libri: LibroDelGiorno[] = c.nelMese ? perGiorno.get(c.iso) ?? [] : []
          const mostrati = libri.slice(0, RIGHE_MASSIME)
          const nascosti = libri.length - mostrati.length
          return (
            <div
              key={c.iso}
              // Altezza minima e non fissa: un giorno vuoto non deve occupare
              // quanto uno pieno, ma la griglia deve restare una griglia.
              className={cn(
                'min-h-[64px] rounded-[5px] border px-1 pt-0.5 pb-1 text-[10px] leading-tight',
                c.nelMese ? 'border-border' : 'border-transparent',
                libri.length > 0 && 'bg-[color-mix(in_srgb,var(--chart-1)_7%,var(--card))]',
                c.oggi && 'ring-1 ring-primary'
              )}
              title={
                libri.length
                  ? `${c.iso}\n${libri.map((l) => `${l.title} — ${durataCorta(l.secondi)}`).join('\n')}`
                  : undefined
              }
            >
              <div
                className={cn(
                  'mb-0.5 text-right tabular-nums',
                  c.nelMese && !c.futuro ? 'text-muted-foreground' : 'text-muted-foreground/35'
                )}
              >
                {c.giorno}
              </div>
              {mostrati.map((l) => (
                <div key={l.title} className="flex items-baseline gap-1">
                  {/* Il titolo cede, il tempo no: un titolo tagliato si
                      riconosce ancora, un tempo tagliato è un numero falso. */}
                  <span className="min-w-0 flex-1 truncate" title={l.title}>
                    {l.title}
                  </span>
                  <span className="shrink-0 tabular-nums text-muted-foreground">{durataCorta(l.secondi)}</span>
                </div>
              ))}
              {nascosti > 0 && (
                <div className="text-muted-foreground/70">{t('stats.calendar.moreBooks', { count: nascosti, n: nascosti })}</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
