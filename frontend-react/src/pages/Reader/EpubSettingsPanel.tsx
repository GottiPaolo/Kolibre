// Popover impostazioni di lettura (layout pagina, dimensione testo),
// ancorato sotto il pulsante "Impostazioni" della toolbar del reader —
// stesso stile bordo/ombra/rounded dei popup di evidenziazione
// (EpubHighlightPopup.tsx), ma senza coordinate calcolate dal testo
// selezionato: il pulsante che lo apre sta sempre nello stesso punto.
import { Columns2, Minus, Plus, RectangleVertical, X } from 'lucide-react'
import { useLingua } from '@/lib/i18n'
import { FONT_SCALE_MAX, FONT_SCALE_MIN, type PageLayout } from './EpubReaderSettings'

interface EpubSettingsPanelProps {
  pageLayout: PageLayout
  onPageLayoutChange: (layout: PageLayout) => void
  fontScale: number
  onFontScaleStep: (direction: 1 | -1) => void
  onClose: () => void
}

const layoutBtnClass =
  'flex flex-1 flex-col items-center gap-1 rounded-md border border-border py-2 text-xs hover:bg-muted data-[active=true]:border-primary data-[active=true]:bg-muted data-[active=true]:text-primary'

export function EpubSettingsPanel({
  pageLayout,
  onPageLayoutChange,
  fontScale,
  onFontScaleStep,
  onClose,
}: EpubSettingsPanelProps) {
  const { t } = useLingua()
  return (
    <div
      className="absolute top-3 right-3 z-30 w-[240px] rounded-lg border border-border bg-popover p-3 text-popover-foreground shadow-lg"
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs font-bold tracking-wide text-muted-foreground uppercase">{t('reader.settings.title')}</span>
        <button type="button" onClick={onClose} aria-label={t('reader.settings.closeAriaLabel')} className="text-muted-foreground hover:text-foreground">
          <X className="size-4" />
        </button>
      </div>

      <div className="mb-3">
        <div className="mb-1.5 text-[11px] text-muted-foreground">{t('reader.settings.pageLayout')}</div>
        <div className="flex gap-2">
          <button type="button" data-active={pageLayout === 'single'} onClick={() => onPageLayoutChange('single')} className={layoutBtnClass}>
            <RectangleVertical className="size-4" />
            {t('reader.settings.layoutSingle')}
          </button>
          <button type="button" data-active={pageLayout === 'double'} onClick={() => onPageLayoutChange('double')} className={layoutBtnClass}>
            <Columns2 className="size-4" />
            {t('reader.settings.layoutDouble')}
          </button>
        </div>
      </div>

      <div>
        <div className="mb-1.5 text-[11px] text-muted-foreground">{t('reader.settings.fontSize')}</div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onFontScaleStep(-1)}
            disabled={fontScale <= FONT_SCALE_MIN}
            aria-label={t('reader.settings.decreaseFontSize')}
            className="flex size-7 items-center justify-center rounded-md border border-border hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
          >
            <Minus className="size-3.5" />
          </button>
          <span className="flex-1 text-center text-[13px] tabular-nums">{fontScale}%</span>
          <button
            type="button"
            onClick={() => onFontScaleStep(1)}
            disabled={fontScale >= FONT_SCALE_MAX}
            aria-label={t('reader.settings.increaseFontSize')}
            className="flex size-7 items-center justify-center rounded-md border border-border hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
          >
            <Plus className="size-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}
