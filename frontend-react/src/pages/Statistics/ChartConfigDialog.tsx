import { useMemo } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import { chartConfigs } from './chartConfig'

interface ChartConfigDialogProps {
  isVisible: (id: string) => boolean
  toggle: (id: string) => void
  onClose: () => void
}

// Porting del modale "Configura Grafici Dashboard" del Vue esistente
// (showStatsConfigModal in App.vue) — sole/spunta di visibilità per
// widget, persistita da useChartVisibility (stessa chiave localStorage).
export function ChartConfigDialog({ isVisible, toggle, onClose }: ChartConfigDialogProps) {
  const { t } = useLingua()
  const configs = useMemo(() => chartConfigs(t), [t])
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('stats.chartConfig.title')}</DialogTitle>
        </DialogHeader>
        <p className="text-[12px] text-muted-foreground">
          {t('stats.chartConfig.description')}
        </p>

        <div className="flex max-h-[320px] flex-col gap-2.5 overflow-y-auto">
          <p className="text-[11px] font-semibold tracking-wide text-primary uppercase">{t('stats.chartConfig.libraryCharts')}</p>
          {configs.filter((c) => c.type === 'library').map((c) => (
            <ConfigRow key={c.id} label={c.label} checked={isVisible(c.id)} onChange={() => toggle(c.id)} />
          ))}

          <p className="mt-2 text-[11px] font-semibold tracking-wide text-[var(--chart-2)] uppercase">{t('stats.chartConfig.readingCharts')}</p>
          {configs.filter((c) => c.type === 'reading').map((c) => (
            <ConfigRow key={c.id} label={c.label} checked={isVisible(c.id)} onChange={() => toggle(c.id)} />
          ))}
        </div>

        <DialogFooter>
          <Button onClick={onClose}>{t('stats.chartConfig.confirm')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ConfigRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: () => void }) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-md bg-muted/50 px-3 py-1.5 text-[13px]">
      <span>{label}</span>
      <input type="checkbox" checked={checked} onChange={onChange} className="size-4 accent-primary" />
    </label>
  )
}
