import { useState } from 'react'
import { Check, GripVertical, X, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  SettingsHint,
  SettingsRow,
  SettingsSection,
} from '@/components/settings/SettingsPrimitives'
import { useStyleVariant, PRESET_CHIARI, type StyleVariant } from '@/lib/useStyleVariant'
import { LINGUE, useLingua, type Valori } from '@/lib/i18n'
import { SIDEBAR_PAGE_DEFS, useSidebarLayoutBuilder, type SidebarPageId } from '@/lib/sidebarLayout'
import { leggiLocale, scriviLocale } from '@/lib/memoriaLocale'

// Tab "Aspetto" di Impostazioni (Fase 8) — porting di
// settingsActiveTab === 'aspect' in frontend/src/App.vue (righe ~1986-2183).
//
// Decisioni di scope (il Vue e il React NON condividono lo stesso sistema
// di theming, vedi frontend-react/src/index.css e useStyleVariant.ts):
// - "Tema Base" (dark/light) + "Colore di Accento" (7 swatch) + textarea
//   CSS custom → sostituiti dai 3 stili GIÀ implementati in React (Sake/
//   Museo/Carta, data-style su <html>): sono preset completi (non un
//   base+accento componibile), quindi qui si SCEGLIE tra loro invece di
//   riesporre gli stessi controlli Vue. Non esisteva ancora nessuno
//   switcher visibile in UI per questi 3 stili (verificato: useStyleVariant()
//   è già chiamato in Layout.tsx solo per applicare l'attributo, il suo
//   setter non era ancora usato da nessuna parte) — questa è la prima
//   interfaccia reale.
// - Textarea "Personalizzazioni CSS Avanzate" NON portata: nessun
//   equivalente nel design system Tailwind/shadcn attuale, e un override
//   CSS libero rischierebbe di rompere componenti condivisi.
// - "Dimensione Cover" / "Dimensione Caratteri" / "Densità Tabella" / "Stile
//   Menu Sidebar" (standard/compatto) NON portati: nel Vue pilotano variabili
//   CSS globali che non esistono più in questa forma; il collapse della
//   sidebar React è già un controllo diretto nella sidebar stessa
//   (kolibre_sidebar_collapsed in Layout.tsx), non un'impostazione qui.
// - "Formato Data": persistito qui (vedi DateFormatSection sotto) ma
//   NON ancora collegato a lib/format.ts — quel file è condiviso da tutte
//   le pagine già migrate e con un commento esplicito "non va toccato" per
//   evitare conflitti di merge (vedi lib/deviceFormat.ts); il collegamento
//   reale è quindi un passo successivo, deliberatamente rinviato.
//   Il limite è dichiarato all'utente nella nota della sezione "Date".
// - Il costruttore sidebar (sezione "Barra laterale") è invece la parte
//   reale e funzionante di questa tab — vedi lib/sidebarLayout.ts per la
//   forma esatta del dato persistito.
// - Il costruttore campi del pannello Quickview (prima qui) si è spostato
//   in Impostazioni ▸ Librerie ▸ modifica libreria: dipende dalle colonne
//   personalizzate, che sono per-libreria, non un'unica impostazione
//   globale — vedi lib/quickviewFieldLayout.ts.
export function AspectTab() {
  return (
    <>
      <LinguaSection />
      <StyleSection />
      <DateFormatSection />
      <SidebarBuilderSection />
    </>
  )
}

// Gli swatch sono sfondo / barra laterale / accento, cioè le tre superfici
// che si riconoscono a colpo d'occhio. I valori duplicano quelli di
// index.css per la stessa ragione di BASE_PRESET_TOKENS: un preset non
// attivo non è leggibile con getComputedStyle.
const STYLE_OPTIONS: { id: StyleVariant; label: string; descriptionKey: string; swatch: [string, string, string] }[] = [
  { id: 'sake', label: 'Sake', descriptionKey: 'settings.aspect.style.sake', swatch: ['#121011', '#17140f', '#c05a46'] },
  { id: 'museo', label: 'Museo', descriptionKey: 'settings.aspect.style.museo', swatch: ['#0f1113', '#121416', '#4c7a8c'] },
  { id: 'carta', label: 'Carta', descriptionKey: 'settings.aspect.style.carta', swatch: ['#f3ede2', '#ece3d3', '#7a2f2f'] },
  { id: 'calibre', label: 'Calibre', descriptionKey: 'settings.aspect.style.calibre', swatch: ['#fbfbfc', '#f2f4f6', '#2b6cb0'] },
  { id: 'foresta', label: 'Foresta', descriptionKey: 'settings.aspect.style.foresta', swatch: ['#f4f2e9', '#ebe8db', '#4a6b3d'] },
  { id: 'sottobosco', label: 'Sottobosco', descriptionKey: 'settings.aspect.style.sottobosco', swatch: ['#121612', '#0f130f', '#7fa86a'] },
  { id: 'notte', label: 'Notte', descriptionKey: 'settings.aspect.style.notte', swatch: ['#0a0a0b', '#0d0d0f', '#6d8cff'] },
  { id: 'lino', label: 'Lino', descriptionKey: 'settings.aspect.style.lino', swatch: ['#faf8f4', '#f4f1ea', '#2f4858'] },
  { id: 'ottone', label: 'Ottone', descriptionKey: 'settings.aspect.style.ottone', swatch: ['#14110d', '#100e0a', '#c9a227'] },
  { id: 'tipografia', label: 'Tipografia', descriptionKey: 'settings.aspect.style.tipografia', swatch: ['#ffffff', '#f4f4f4', '#c8241c'] },
]

// La lingua sta in Aspetto e non in una scheda sua: e' una preferenza su come
// il programma si presenta, come lo stile e il formato delle date, non una
// configurazione del server. Per prima fra le sezioni perche' e' quella che
// cambia tutte le altre.
//
// Due bottoni e non un menu': le lingue sono due, e un menu' per due voci
// nasconde meta' di quello che c'e'. Diventera' un menu' oltre le tre.
function LinguaSection() {
  const { lingua, cambiaLingua, t } = useLingua()
  return (
    <SettingsSection label={t('settings.aspect.lang.section')}>
      <SettingsRow
        name={t('settings.aspect.lang.name')}
        description={t('settings.aspect.lang.description')}
        last
      >
        <div className="flex gap-1">
          {LINGUE.map((l) => (
            <Button
              key={l.id}
              variant={lingua === l.id ? 'secondary' : 'ghost'}
              size="sm"
              aria-pressed={lingua === l.id}
              onClick={() => cambiaLingua(l.id)}
            >
              {lingua === l.id && <Check className="size-3.5" />}
              {l.nome}
            </Button>
          ))}
        </div>
      </SettingsRow>
    </SettingsSection>
  )
}

function StyleSection() {
  const { t } = useLingua()
  const { scelta, setScelta, scuroAttivo } = useStyleVariant()

  const chiari = STYLE_OPTIONS.filter((o) => (PRESET_CHIARI as readonly string[]).includes(o.id))
  const scuri = STYLE_OPTIONS.filter((o) => !(PRESET_CHIARI as readonly string[]).includes(o.id))

  function Griglia({ opzioni, scelto, onScegli }: {
    opzioni: typeof STYLE_OPTIONS
    scelto: StyleVariant
    onScegli: (id: StyleVariant) => void
  }) {
    return (
      <div className="grid w-full gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {opzioni.map((opt) => {
          const selected = scelto === opt.id
          return (
            <button
              key={opt.id}
              onClick={() => onScegli(opt.id)}
              className={`flex flex-col gap-2 rounded-lg border p-3 text-left transition-colors ${
                selected ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/40'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex gap-1">
                  {opt.swatch.map((c, i) => (
                    <span key={i} className="size-3.5 rounded-full border border-border/50" style={{ background: c }} />
                  ))}
                </div>
                {selected && <Check className="size-3.5 text-primary" />}
              </div>
              <div>
                <div className="text-[13px] font-medium">{opt.label}</div>
                <div className="text-[11px] text-muted-foreground">{t(opt.descriptionKey)}</div>
              </div>
            </button>
          )
        })}
      </div>
    )
  }

  return (
    <SettingsSection label={t('settings.aspect.style.section')}>
      {/* Non si sceglie UNO stile ma una coppia: con dieci stili la domanda
          vera non e' piu' "quale mi piace" ma "quale di giorno e quale di
          notte". */}
      <SettingsRow
        name={t('settings.aspect.style.ruleName')}
        description={t('settings.aspect.style.ruleDescription')}
        stack
      >
        <div className="flex w-full flex-col gap-2.5">
          <label className="flex items-center gap-2.5 text-[13px]">
            <input
              type="checkbox"
              checked={scelta.adattivo}
              onChange={(e) => setScelta({ ...scelta, adattivo: e.target.checked })}
              className="size-4 accent-primary"
            />
            {t('settings.aspect.style.followSystem')}
          </label>
          {scelta.adattivo ? (
            <p className="pl-6 text-[11.5px] leading-relaxed text-muted-foreground">
              {t('settings.aspect.style.systemNow', {
                modo: scuroAttivo ? t('settings.aspect.style.darkWord') : t('settings.aspect.style.lightWord'),
                stile: etichettaDi(scuroAttivo ? scelta.scuro : scelta.chiaro, t),
              })}
            </p>
          ) : (
            <div className="flex items-center gap-1.5 pl-6">
              {(['chiaro', 'scuro'] as const).map((quale) => (
                <button
                  key={quale}
                  onClick={() => setScelta({ ...scelta, attivo: quale })}
                  className={`rounded-md border px-2.5 py-1 text-[12.5px] transition-colors ${
                    scelta.attivo === quale ? 'border-primary bg-primary/10 text-foreground' : 'border-border text-muted-foreground hover:bg-muted/40'
                  }`}
                >
                  {quale === 'chiaro' ? t('settings.aspect.style.lightWord') : t('settings.aspect.style.darkWord')}
                </button>
              ))}
            </div>
          )}
        </div>
      </SettingsRow>

      <SettingsRow name={t('settings.aspect.style.light')} description={t('settings.aspect.style.lightDescription')} stack>
        <Griglia opzioni={chiari} scelto={scelta.chiaro} onScegli={(id) => setScelta({ ...scelta, chiaro: id })} />
      </SettingsRow>

      <SettingsRow name={t('settings.aspect.style.dark')} description={t('settings.aspect.style.darkDescription')} stack last>
        <Griglia opzioni={scuri} scelto={scelta.scuro} onScegli={(id) => setScelta({ ...scelta, scuro: id })} />
      </SettingsRow>

      <SettingsHint>
        {t('settings.aspect.style.hint')}
      </SettingsHint>
    </SettingsSection>
  )
}

function etichettaDi(id: StyleVariant, t: (chiave: string, valori?: Valori) => string): string {
  return STYLE_OPTIONS.find((o) => o.id === id)?.label ?? t('settings.aspect.style.customFallback')
}
const DATE_FORMAT_STORAGE_KEY = 'kolibre_date_format_setting'
type DateFormatId = 'YYYY-MM-DD' | 'DD/MM/YYYY' | 'MM/DD/YYYY'
const DATE_FORMAT_OPTIONS: { id: DateFormatId; label: string }[] = [
  { id: 'YYYY-MM-DD', label: 'ISO — 2026-07-07' },
  { id: 'DD/MM/YYYY', label: 'Day first — 07/07/2026' },
  { id: 'MM/DD/YYYY', label: 'Month first — 07/07/2026' },
]

function loadDateFormatSetting(): DateFormatId {
  const raw = leggiLocale(DATE_FORMAT_STORAGE_KEY)
  return raw === 'DD/MM/YYYY' || raw === 'MM/DD/YYYY' ? raw : 'YYYY-MM-DD'
}

function DateFormatSection() {
  const { t } = useLingua()
  const [format, setFormat] = useState<DateFormatId>(() => loadDateFormatSetting())

  function handleChange(next: DateFormatId) {
    setFormat(next)
    scriviLocale(DATE_FORMAT_STORAGE_KEY, next)
  }

  return (
    <SettingsSection label={t('settings.aspect.date.section')}>
      <SettingsRow name={t('settings.aspect.date.name')} description={t('settings.aspect.date.description')} last>
        <Select value={format} onValueChange={(v) => handleChange(v as DateFormatId)}>
          <SelectTrigger className="w-52">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DATE_FORMAT_OPTIONS.map((opt) => (
              <SelectItem key={opt.id} value={opt.id}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SettingsRow>

      <SettingsHint>
        {t('settings.aspect.date.hint')}
      </SettingsHint>
    </SettingsSection>
  )
}

function SidebarBuilderSection() {
  const { t } = useLingua()
  const { layout, available, dragStart, dropToStructure, dropToAvailable, addSeparator, removeEntry, reset } =
    useSidebarLayoutBuilder()

  return (
    <SettingsSection label={t('settings.aspect.sidebar.section')}>
      <SettingsRow
        name={t('settings.aspect.sidebar.name')}
        description={t('settings.aspect.sidebar.description')}
        stack
      >
        <div className="grid w-full gap-3 sm:grid-cols-2">
          <div className="min-w-0">
            <div className="mb-1.5 text-[10.5px] font-semibold tracking-wide text-muted-foreground uppercase">
              {t('settings.aspect.sidebar.available')}
            </div>
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => dropToAvailable()}
              className="flex min-h-[52px] flex-col gap-1 rounded-lg border border-dashed border-border bg-muted/20 p-2"
            >
              {available.map((id) => {
                const def = SIDEBAR_PAGE_DEFS[id]
                const Icon = def.icon
                return (
                  <div
                    key={id}
                    draggable
                    onDragStart={() => dragStart({ from: 'available', id })}
                    className="flex cursor-grab items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-[12.5px]"
                  >
                    <GripVertical className="size-3.5 shrink-0 text-muted-foreground" />
                    <Icon className="size-3.5 shrink-0" />
                    {t(def.labelKey)}
                  </div>
                )
              })}
              {available.length === 0 && (
                <div className="p-1.5 text-[11px] text-muted-foreground">{t('settings.aspect.sidebar.allUsed')}</div>
              )}
            </div>
          </div>

          <div className="min-w-0">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-[10.5px] font-semibold tracking-wide text-muted-foreground uppercase">
                {t('settings.aspect.sidebar.structure')}
              </span>
              <button className="text-[11px] text-primary hover:underline" onClick={addSeparator}>
                {t('settings.aspect.sidebar.addSeparator')}
              </button>
            </div>
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => dropToStructure(layout.length)}
              className="flex min-h-[52px] flex-col gap-1 rounded-lg border border-dashed border-border bg-muted/20 p-2"
            >
              {layout.map((entry, idx) => (
                <div
                  key={idx}
                  draggable
                  onDragStart={() => dragStart({ from: 'structure', index: idx })}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.stopPropagation()
                    dropToStructure(idx)
                  }}
                  className={`flex cursor-grab items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-[12.5px] ${
                    entry.type === 'separator' ? 'bg-muted/40 text-muted-foreground' : 'bg-card'
                  }`}
                >
                  <GripVertical className="size-3.5 shrink-0 text-muted-foreground" />
                  {entry.type === 'separator' ? (
                    <span className="flex-1">{t('settings.aspect.sidebar.separator')}</span>
                  ) : (
                    <>
                      <PageIcon id={entry.id} />
                      <span className="flex-1">{t(SIDEBAR_PAGE_DEFS[entry.id].labelKey)}</span>
                    </>
                  )}
                  <button
                    title={t('settings.aspect.sidebar.remove')}
                    onClick={() => removeEntry(idx)}
                    className="text-muted-foreground hover:text-foreground"
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              ))}
              {layout.length === 0 && (
                <div className="p-1.5 text-[11px] text-muted-foreground">
                  {t('settings.aspect.sidebar.none')}
                </div>
              )}
            </div>
          </div>
        </div>
      </SettingsRow>

      <SettingsRow name={t('settings.aspect.sidebar.resetName')} description={t('settings.aspect.sidebar.resetDescription')} last>
        <Button variant="outline" size="sm" onClick={reset}>
          <RotateCcw className="size-3.5" />
          {t('settings.aspect.sidebar.reset')}
        </Button>
      </SettingsRow>

      <SettingsHint>
        {t('settings.aspect.sidebar.hint')}
      </SettingsHint>
    </SettingsSection>
  )
}

function PageIcon({ id }: { id: SidebarPageId }) {
  const Icon = SIDEBAR_PAGE_DEFS[id].icon
  return <Icon className="size-3.5 shrink-0" />
}
