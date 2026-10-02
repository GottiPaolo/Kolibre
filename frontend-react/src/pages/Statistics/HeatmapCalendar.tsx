import { useLingua } from '@/lib/i18n'
import type { HeatmapDay } from './statsCompute'

const LEVEL_COLORS = ['var(--muted)', 'var(--chart-2)', 'var(--chart-2)', 'var(--chart-1)', 'var(--chart-1)']
const LEVEL_OPACITY = [1, 0.35, 0.6, 0.75, 1]

// Griglia di attività giornaliera (365 giorni), porting del blocco
// .heatmap-grid del Vue esistente — stessa scala 0-4 già calcolata da
// buildHeatmapDays, qui solo la resa visiva a celle colorate con tooltip
// nativo (title) sul valore del giorno.
export function HeatmapCalendar({ days }: { days: HeatmapDay[] }) {
  const { t } = useLingua()
  return (
    <div>
      <div className="overflow-x-auto">
        <div className="grid w-max grid-flow-col grid-rows-7 gap-[3px]">
          {days.map((day) => (
            <div
              key={day.date}
              title={t('stats.heatmap.dayTitle', { date: day.date, n: day.minutes })}
              className="size-[11px] rounded-[2px]"
              style={{ backgroundColor: LEVEL_COLORS[day.value], opacity: LEVEL_OPACITY[day.value] }}
            />
          ))}
        </div>
      </div>
      <div className="mt-3 flex items-center justify-end gap-1.5 text-[11px] text-muted-foreground">
        <span>{t('stats.heatmap.less')}</span>
        {[0, 1, 2, 3, 4].map((level) => (
          <div key={level} className="size-[11px] rounded-[2px]" style={{ backgroundColor: LEVEL_COLORS[level], opacity: LEVEL_OPACITY[level] }} />
        ))}
        <span>{t('stats.heatmap.more')}</span>
      </div>
    </div>
  )
}
