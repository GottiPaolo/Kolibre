// Il pannello delle impostazioni di lettura, sotto il pulsante della barra.
//
// **Una regola che tiene insieme tutto questo file**: ogni voce qui dentro
// deve cambiare qualcosa che si vede al primo sguardo. E' la regola che ha
// tenuto fuori le cose che su un e-reader esistono e nel browser no — il gamma
// dei caratteri, il kerning a livelli, l'hinting: li' il rasterizzatore e' del
// programma, qui e' del browser, e un cursore che non fa niente e' peggio di
// un cursore che non c'e'.
//
// Stessa ragione per cui le scelte sono segmentate e non a cursore dove i
// valori sensati sono pochi: tre bottoni si leggono, un cursore da tre tacche
// si deve interpretare.
//
// E non ci sono impostazioni per singolo libro: e' la differenza fra «so
// perche' questo libro si vede cosi'» e il non saperlo piu'.
import { Columns2, Minus, Plus, RectangleVertical, X } from 'lucide-react'
import { useLingua } from '@/lib/i18n'
import {
  FONT_SCALE_MAX,
  FONT_SCALE_MIN,
  INTERLINEA_MAX,
  INTERLINEA_MIN,
  MARGINI_MAX,
  MARGINI_MIN,
  type PageLayout,
} from './EpubReaderSettings'
import { coloriDi, FAMIGLIE, NOMI_CARATTERE, type Carattere, type OverrideColori, type PreferenzeLettura, type Tema } from './EpubTheme'

interface EpubSettingsPanelProps {
  pageLayout: PageLayout
  onPageLayoutChange: (layout: PageLayout) => void
  fontScale: number
  onFontScaleStep: (direction: 1 | -1) => void
  preferenze: PreferenzeLettura
  onPreferenzeChange: (parziali: Partial<PreferenzeLettura>) => void
  sistemaEScuro: boolean
  onClose: () => void
}

const layoutBtnClass =
  'flex flex-1 flex-col items-center gap-1 rounded-md border border-border py-2 text-xs hover:bg-muted data-[active=true]:border-primary data-[active=true]:bg-muted data-[active=true]:text-primary'

// Alcune voci non si spiegano dal nome, e il nome da solo e' peggio che
// niente: «Colori del libro: Di notte» non e' una frase che qualcuno possa
// leggere. Dove serve, una riga sotto dice cosa cambia davvero.
function Riga({ titolo, aiuto, children }: { titolo: string; aiuto?: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="mb-1 text-[11px] text-muted-foreground">{titolo}</div>
      {aiuto && <p className="mb-1.5 text-[10px] leading-snug text-muted-foreground/70">{aiuto}</p>}
      {children}
    </div>
  )
}

const CARATTERI: Carattere[] = ['libro', 'serif', 'palatino', 'times', 'sans', 'leggibile']

/** Scelta fra poche opzioni: tutte visibili, quella attiva evidenziata. */
function Segmenti<T extends string | boolean | null>({
  opzioni,
  valore,
  onChange,
}: {
  opzioni: { v: T; etichetta: string }[]
  valore: T
  onChange: (v: T) => void
}) {
  return (
    <div className="flex gap-1">
      {opzioni.map((o) => (
        <button
          key={String(o.v)}
          type="button"
          data-active={o.v === valore}
          onClick={() => onChange(o.v)}
          className="flex-1 rounded-md border border-border px-1 py-1 text-[11px] hover:bg-muted data-[active=true]:border-primary data-[active=true]:bg-muted data-[active=true]:text-primary"
        >
          {o.etichetta}
        </button>
      ))}
    </div>
  )
}

/** Un valore numerico con meno/più e l'opzione «come il libro». */
function Passo({
  valore,
  testo,
  onStep,
  min,
  max,
}: {
  valore: number
  testo: string
  onStep: (direzione: 1 | -1) => void
  min: number
  max: number
}) {
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => onStep(-1)}
        disabled={valore <= min}
        className="flex size-7 items-center justify-center rounded-md border border-border hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
      >
        <Minus className="size-3.5" />
      </button>
      <span className="flex-1 text-center text-[13px] tabular-nums">{testo}</span>
      <button
        type="button"
        onClick={() => onStep(1)}
        disabled={valore >= max}
        className="flex size-7 items-center justify-center rounded-md border border-border hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
      >
        <Plus className="size-3.5" />
      </button>
    </div>
  )
}

const TEMI: Tema[] = ['sistema', 'chiaro', 'grigio', 'sepia', 'scuro']

export function EpubSettingsPanel({
  pageLayout,
  onPageLayoutChange,
  fontScale,
  onFontScaleStep,
  preferenze,
  onPreferenzeChange,
  sistemaEScuro,
  onClose,
}: EpubSettingsPanelProps) {
  const { t } = useLingua()

  const interlinea = preferenze.interlinea
  function passoInterlinea(direzione: 1 | -1) {
    // Dal «come il libro» si entra a 1.5, che e' il valore comodo: il primo
    // tocco deve dare un risultato visibile, non uno scarto di un decimo.
    if (interlinea == null) {
      onPreferenzeChange({ interlinea: 1.5 })
      return
    }
    const prossima = Math.round((interlinea + direzione * 0.1) * 10) / 10
    onPreferenzeChange({ interlinea: Math.min(INTERLINEA_MAX, Math.max(INTERLINEA_MIN, prossima)) })
  }

  return (
    <div
      className="absolute top-3 right-3 z-30 max-h-[85vh] w-[254px] overflow-y-auto rounded-lg border border-border bg-popover p-3 text-popover-foreground shadow-lg"
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs font-bold tracking-wide text-muted-foreground uppercase">{t('reader.settings.title')}</span>
        <button type="button" onClick={onClose} aria-label={t('reader.settings.closeAriaLabel')} className="text-muted-foreground hover:text-foreground">
          <X className="size-4" />
        </button>
      </div>

      <Riga titolo={t('reader.settings.pageLayout')}>
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
      </Riga>

      <Riga titolo={t('reader.settings.fontSize')}>
        <Passo valore={fontScale} testo={`${fontScale}%`} onStep={onFontScaleStep} min={FONT_SCALE_MIN} max={FONT_SCALE_MAX} />
      </Riga>

      <Riga titolo={t('reader.settings.theme')}>
        <div className="flex gap-1.5">
          {TEMI.map((tema) => {
            const c = coloriDi(tema, sistemaEScuro)
            return (
              <button
                key={tema}
                type="button"
                onClick={() => onPreferenzeChange({ tema })}
                title={t(`reader.settings.theme.${tema}`)}
                aria-label={t(`reader.settings.theme.${tema}`)}
                data-active={preferenze.tema === tema}
                className="flex h-8 flex-1 items-center justify-center rounded-md border-2 text-[10px] font-semibold data-[active=false]:border-border data-[active=true]:border-primary"
                style={{ backgroundColor: c.sfondo, color: c.testo }}
              >
                {t(`reader.settings.theme.${tema}.short`)}
              </button>
            )
          })}
        </div>
      </Riga>

      {/* Tre stati e non un interruttore: di giorno i colori che l'editore ha
          scelto sono spesso voluti, di notte un libro che dichiara sfondo
          bianco produce una pagina abbagliante dentro un tema scuro. Il
          valore di mezzo e' quello che serve quasi sempre, ed e' il
          predefinito. */}
      <Riga titolo={t('reader.settings.overrideColors')} aiuto={t('reader.settings.overrideColors.help')}>
        <Segmenti<OverrideColori>
          opzioni={[
            { v: 'mai', etichetta: t('reader.settings.overrideColors.never') },
            { v: 'scuro', etichetta: t('reader.settings.overrideColors.dark') },
            { v: 'sempre', etichetta: t('reader.settings.overrideColors.always') },
          ]}
          valore={preferenze.overrideColori}
          onChange={(overrideColori) => onPreferenzeChange({ overrideColori })}
        />
      </Riga>

      {/* Ogni carattere scritto NEL carattere: e' l'unico modo di sceglierne
          uno senza provarli tutti. Erano quattro bottoni che dicevano «Serif»
          e «Sans», cioe' due categorie e non due caratteri. */}
      <Riga titolo={t('reader.settings.font')}>
        <div className="flex flex-col gap-1">
          {CARATTERI.map((c) => (
            <button
              key={c}
              type="button"
              data-active={preferenze.carattere === c}
              onClick={() => onPreferenzeChange({ carattere: c })}
              style={c === 'libro' ? undefined : { fontFamily: FAMIGLIE[c] }}
              className="rounded-md border border-border px-2 py-1 text-left text-[13px] hover:bg-muted data-[active=true]:border-primary data-[active=true]:bg-muted data-[active=true]:text-primary"
            >
              {c === 'libro' ? t('reader.settings.asInBook') : NOMI_CARATTERE[c]}
            </button>
          ))}
        </div>
      </Riga>

      <Riga titolo={t('reader.settings.lineHeight')}>
        <Passo
          valore={interlinea ?? INTERLINEA_MIN}
          testo={interlinea == null ? t('reader.settings.asInBook') : interlinea.toFixed(1)}
          onStep={passoInterlinea}
          min={interlinea == null ? INTERLINEA_MIN - 1 : INTERLINEA_MIN}
          max={INTERLINEA_MAX}
        />
        {interlinea != null && (
          <button
            type="button"
            onClick={() => onPreferenzeChange({ interlinea: null })}
            className="mt-1 w-full text-[10px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            {t('reader.settings.backToBook')}
          </button>
        )}
      </Riga>

      <Riga titolo={t('reader.settings.margins')}>
        <Passo
          valore={preferenze.margini}
          testo={`${preferenze.margini}%`}
          onStep={(d) => onPreferenzeChange({ margini: Math.min(MARGINI_MAX, Math.max(MARGINI_MIN, preferenze.margini + d * 2)) })}
          min={MARGINI_MIN}
          max={MARGINI_MAX}
        />
      </Riga>

      <Riga titolo={t('reader.settings.alignment')}>
        <Segmenti<boolean | null>
          opzioni={[
            { v: null, etichetta: t('reader.settings.asInBook') },
            { v: false, etichetta: t('reader.settings.alignment.left') },
            { v: true, etichetta: t('reader.settings.alignment.justify') },
          ]}
          valore={preferenze.giustificato}
          onChange={(giustificato) => onPreferenzeChange({ giustificato })}
        />
      </Riga>

      {/* In italiano con il testo giustificato e' la differenza fra righe
          leggibili e righe piene di buchi. Funziona solo se il libro dichiara
          la sua lingua: il browser sceglie il dizionario da li'. */}
      <Riga titolo={t('reader.settings.hyphenation')} aiuto={t('reader.settings.hyphenation.help')}>
        <Segmenti<boolean>
          opzioni={[
            { v: false, etichetta: t('common.no') },
            { v: true, etichetta: t('common.yes') },
          ]}
          valore={preferenze.sillabazione}
          onChange={(sillabazione) => onPreferenzeChange({ sillabazione })}
        />
      </Riga>
    </div>
  )
}
