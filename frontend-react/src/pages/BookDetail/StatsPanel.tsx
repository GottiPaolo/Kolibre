import { useMemo } from 'react'
import type { BookStats } from '@/types/library'
import { formatDate } from '@/lib/format'
import { LineChart } from '@/components/charts/LineChart'
import { numeroCompatto, useLingua } from '@/lib/i18n'

// I caratteri si leggono a colpo d'occhio solo abbreviati: "1,2 M" dice
// quello che "1.203.918" non dice.
function formatCaratteri(n: number): string {
  return numeroCompatto(n)
}

function formatDurationHuman(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

export function StatsPanel({ stats }: { stats: BookStats }) {
  const { t } = useLingua()
  // Tempo di lettura cumulativo giorno per giorno — non il tempo letto
  // quel giorno isolato, ma il totale progressivo, come nella vista
  // statistiche di KoServer: una linea che sale, mai che scende.
  const cumulative = useMemo(() => {
    let running = 0
    return stats.daily_sessions.map((d) => {
      running += d.total_seconds
      return { label: formatDate(d.date), value: Math.round((running / 3600) * 10) / 10 }
    })
  }, [stats.daily_sessions])

  if (stats.total_sessions === 0) {
    return <p className="text-[12.5px] text-muted-foreground">{t('library.statsPanel.noSessions')}</p>
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-4 gap-2">
        <Kpi label={t('library.statsPanel.totalTime')} value={formatDurationHuman(stats.total_time_seconds)} />
        <Kpi label={t('library.statsPanel.sessions')} value={String(stats.total_sessions)} />
        <Kpi label={t('library.statsPanel.highlights')} value={String(stats.highlights_count)} />
        {/* "Quanto libro" al posto delle pagine: una pagina di KOReader
            dipende dal corpo del carattere, e fra due libri — o fra due
            riletture dello stesso con impostazioni diverse — non è la stessa
            quantità di testo. La percentuale e i caratteri invece sì. Le
            pagine restano nel sottotitolo, per chi le cerca. */}
        {stats.fraction_read != null ? (
          <Kpi
            label={stats.chars_read != null ? t('library.detail.read') : t('library.statsPanel.howMuchBook')}
            value={
              stats.chars_read != null
                ? formatCaratteri(stats.chars_read)
                : `${Math.round((stats.coverage ?? stats.fraction_read) * 100)}%`
            }
            // NON la percentuale di fraction_read: quella e' quanto si e'
            // LETTO e rileggendo supera il 100% — mostrarla come "% del
            // libro" e' proprio l'errore che si vedeva in uso. Qui va la
            // copertura, che dice fin dove si e' arrivati e non supera mai
            // il 100%.
            sub={
              stats.chars_read != null
                ? stats.coverage != null
                  ? t('library.statsPanel.charsReadWithCoverage', { pct: Math.round(stats.coverage * 100) })
                  : t('library.statsPanel.charsRead')
                : t('library.statsPanel.pagesSub', { count: stats.total_pages_read, n: stats.total_pages_read })
            }
          />
        ) : (
          <Kpi label={t('library.statsPanel.pagesRead')} value={String(stats.total_pages_read)} />
        )}
      </div>
      <p className="text-[12px] text-muted-foreground">
        {t('library.statsPanel.readRange', {
          first: formatDate(stats.first_read?.slice(0, 10)) ?? '',
          last: formatDate(stats.last_read?.slice(0, 10)) ?? '',
        })}
      </p>
      {cumulative.length > 1 ? (
        <LineChart points={cumulative} valueSuffix=" h" height={160} />
      ) : (
        <p className="text-[12px] text-muted-foreground">{t('library.statsPanel.needMoreDays')}</p>
      )}
    </div>
  )
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-md border border-border bg-card p-2 text-center">
      <p className="text-[15px] font-semibold">{value}</p>
      <p className="text-[10.5px] text-muted-foreground">{label}</p>
      {sub && <p className="text-[9.5px] text-muted-foreground/70">{sub}</p>}
    </div>
  )
}
