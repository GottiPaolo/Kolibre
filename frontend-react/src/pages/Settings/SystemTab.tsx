import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Keyboard, Plus, X, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  SettingsFeedback,
  SettingsHint,
  SettingsInput,
  SettingsRow,
  SettingsSection,
} from '@/components/settings/SettingsPrimitives'
import { LargeLibrarySection } from './LargeLibrarySection'
import { ServerLogSection } from './ServerLogSection'
import {
  COMMAND_REGISTRY,
  commandBindings,
  commandHasOverride,
  commandLabel,
  computeConflicts,
  exportShortcuts,
  formatKeyCombo,
  importShortcutsFromFile,
  loadShortcutOverrides,
  normalizeKeyCombo,
  persistShortcutOverrides,
  type ShortcutOverrides,
} from '@/lib/shortcutRegistry'
import { useLingua } from '@/lib/i18n'

const SEARCH_BY_KEY_SENTINEL = '__search_by_key__'

// Marcatore interno (non mostrato) per distinguere l'esito d'errore
// dell'import da quello di successo: il testo vero si traduce al momento
// del rendering, vedi più sotto.
const IMPORT_ERROR = '__import_error__'

// Impostazioni ▸ Sistema (Fase 8) — porting della UI di gestione scorciatoie
// da tastiera di frontend/src/App.vue (settingsActiveTab === 'system', righe
// ~2407-2486): ricerca per nome o per combinazione premuta, chip per binding
// con "✕" singolo, aggiunta di una nuova combinazione, ripristino al default,
// import/export JSON. Vedi lib/shortcutRegistry.ts per la decisione di scope:
// qui si personalizzano e persistono i binding, ma nessun comando è ancora
// eseguibile premendo i tasti nell'app reale (nessun dispatcher globale —
// richiederebbe toccare Layout.tsx e più pagine già migrate, fuori scope per
// una tab di Impostazioni). Il limite è detto all'utente nel SettingsHint in
// fondo alla prima sezione: senza, configurerebbe tasti che non fanno nulla
// senza saperlo.
// Quale Kolibre sta girando.
//
// Stava in fondo alla barra laterale insieme all'orario di build: serviva
// durante lo sviluppo per capire a colpo d'occhio se un deploy fosse andato a
// buon fine. In un programma che altri installeranno quell'angolo risponde a
// una domanda piu' utile — con quale account sto guardando — e la versione, che
// serve ancora, sta qui dove si guardano le cose del server.
//
// Il valore lo cuoce il build, da KOLIBRE_VERSION in .env: su una
// versione rilasciata e' pulito, "1.0.0"; su un build fatto dopo il tag porta
// anche la distanza e il commit, che e' esattamente l'informazione che serve
// per capire che NON si sta guardando una versione rilasciata.
function VersioneSection() {
  const { t } = useLingua()
  const { data } = useQuery({
    queryKey: ['versione-kolibre'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/version')
      if (error) throw error
      return data as unknown as { version: string }
    },
  })
  return (
    <SettingsSection label={t('settings.system.version.label')}>
      <SettingsRow name="Kolibre" description={t('settings.system.version.rowDescription')} last>
        <span className="font-mono text-[12.5px] tabular-nums text-foreground">{data?.version ?? '—'}</span>
      </SettingsRow>
    </SettingsSection>
  )
}

export function SystemTab() {
  const { t } = useLingua()
  const [overrides, setOverrides] = useState<ShortcutOverrides>(() => loadShortcutOverrides())
  const [searchQuery, setSearchQuery] = useState('')
  const [searchCombo, setSearchCombo] = useState<string | null>(null)
  const [captureCommandId, setCaptureCommandId] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const conflicts = useMemo(() => computeConflicts(overrides), [overrides])

  const filtered = useMemo(() => {
    if (searchCombo) return COMMAND_REGISTRY.filter((cmd) => commandBindings(overrides, cmd).includes(searchCombo))
    const q = searchQuery.trim().toLowerCase()
    return q ? COMMAND_REGISTRY.filter((cmd) => commandLabel(cmd.id, t).toLowerCase().includes(q)) : COMMAND_REGISTRY
  }, [searchQuery, searchCombo, overrides, t])

  function commit(next: ShortcutOverrides) {
    setOverrides(next)
    persistShortcutOverrides(next)
  }

  function addBinding(cmdId: string, combo: string) {
    const cmd = COMMAND_REGISTRY.find((c) => c.id === cmdId)
    if (!cmd) return
    const current = commandBindings(overrides, cmd).slice()
    if (!current.includes(combo)) current.push(combo)
    commit({ ...overrides, [cmdId]: current })
  }

  function removeBinding(cmdId: string, combo: string) {
    const cmd = COMMAND_REGISTRY.find((c) => c.id === cmdId)
    if (!cmd) return
    commit({ ...overrides, [cmdId]: commandBindings(overrides, cmd).filter((k) => k !== combo) })
  }

  function resetCommand(cmdId: string) {
    const next = { ...overrides }
    delete next[cmdId]
    commit(next)
  }

  // Modalità cattura: il PROSSIMO keydown (ovunque nella pagina) viene
  // consumato come binding invece di propagarsi — attivo solo mentre
  // questa tab è montata e captureCommandId è impostato.
  useEffect(() => {
    if (!captureCommandId) return
    function onKeyDown(e: KeyboardEvent) {
      e.preventDefault()
      if (e.key === 'Escape') {
        setCaptureCommandId(null)
        return
      }
      const combo = normalizeKeyCombo(e)
      if (combo) {
        if (captureCommandId === SEARCH_BY_KEY_SENTINEL) {
          setSearchCombo(combo)
        } else {
          addBinding(captureCommandId!, combo)
        }
      }
      setCaptureCommandId(null)
    }
    window.addEventListener('keydown', onKeyDown, true)
    return () => window.removeEventListener('keydown', onKeyDown, true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [captureCommandId, overrides])

  function clearSearch() {
    setSearchQuery('')
    setSearchCombo(null)
  }

  async function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    try {
      const imported = await importShortcutsFromFile(file)
      commit(imported)
      setFeedback(t('settings.system.shortcuts.imported'))
    } catch {
      setFeedback(IMPORT_ERROR)
    }
  }

  const searchingByKey = captureCommandId === SEARCH_BY_KEY_SENTINEL

  return (
    <>
      <VersioneSection />
      <LargeLibrarySection />
      <ServerLogSection />

      <SettingsSection
        label={t('settings.system.shortcuts.label')}
        description={t('settings.system.shortcuts.description')}
      >
        <SettingsRow
          name={t('settings.system.shortcuts.findCommandName')}
          description={
            searchingByKey
              ? t('settings.system.shortcuts.searchingByKeyDescription')
              : t('settings.system.shortcuts.searchDescription')
          }
        >
          <div className="relative w-[220px]">
            <SettingsInput
              className="w-full"
              ariaLabel={t('settings.system.shortcuts.searchAriaLabel')}
              value={searchQuery}
              onChange={(v) => {
                setSearchQuery(v)
                setSearchCombo(null)
              }}
              placeholder={searchCombo ? '' : t('settings.system.shortcuts.searchPlaceholder')}
            />
            {/* Il chip copre l'input invece di sostituirlo: la ricerca per
                combinazione e quella per nome condividono lo stesso campo. */}
            {searchCombo && (
              <span className="absolute top-1/2 left-2 flex -translate-y-1/2 items-center gap-1.5 rounded-md border border-border bg-sidebar px-2 py-0.5 text-[12px]">
                {formatKeyCombo(searchCombo, t)}
                <button title={t('settings.system.shortcuts.cancelSearchTitle')} className="text-muted-foreground" onClick={clearSearch}>
                  <X className="size-3" />
                </button>
              </span>
            )}
          </div>
          <Button
            variant={searchingByKey ? 'default' : 'outline'}
            size="icon-sm"
            title={t('settings.system.shortcuts.searchByComboTitle')}
            onClick={() => setCaptureCommandId(SEARCH_BY_KEY_SENTINEL)}
          >
            <Keyboard className="size-3.5" />
          </Button>
        </SettingsRow>

        <SettingsRow
          name={t('settings.system.shortcuts.backupName')}
          description={t('settings.system.shortcuts.backupDescription')}
          last
        >
          <input ref={fileInputRef} type="file" accept="application/json" className="hidden" onChange={(e) => void handleImportFile(e)} />
          <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
            {t('settings.system.shortcuts.import')}
          </Button>
          <Button variant="outline" size="sm" onClick={() => exportShortcuts(overrides)}>
            {t('settings.system.shortcuts.export')}
          </Button>
        </SettingsRow>

        {feedback && (
          <SettingsFeedback kind={feedback === IMPORT_ERROR ? 'error' : 'ok'}>
            {feedback === IMPORT_ERROR ? t('settings.system.shortcuts.importError') : feedback}
          </SettingsFeedback>
        )}

        <SettingsHint>{t('settings.system.shortcuts.hint')}</SettingsHint>
      </SettingsSection>

      <SettingsSection label={t('settings.system.commands.label')}>
        {filtered.map((cmd, idx) => {
          const bindings = commandBindings(overrides, cmd)
          const capturing = captureCommandId === cmd.id
          return (
            <SettingsRow key={cmd.id} name={commandLabel(cmd.id, t)} last={idx === filtered.length - 1}>
              <div className="flex flex-wrap items-center justify-end gap-1.5">
                {bindings.map((combo) => {
                  const conflicting = conflicts[cmd.id]?.has(combo)
                  return (
                    <span
                      key={combo}
                      title={conflicting ? t('settings.system.commands.conflictTitle') : ''}
                      className={`inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[11.5px] ${
                        conflicting ? 'border-destructive text-destructive' : 'border-border'
                      }`}
                    >
                      {formatKeyCombo(combo, t)}
                      <button
                        title={t('settings.system.commands.removeComboTitle')}
                        onClick={() => removeBinding(cmd.id, combo)}
                        className="opacity-70 hover:opacity-100"
                      >
                        <X className="size-3" />
                      </button>
                    </span>
                  )
                })}

                {capturing ? (
                  <Button variant="outline" size="xs" onClick={() => setCaptureCommandId(null)}>
                    {t('settings.system.commands.capturing')}
                  </Button>
                ) : (
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    title={t('settings.system.commands.addComboTitle')}
                    onClick={() => setCaptureCommandId(cmd.id)}
                  >
                    <Plus className="size-3" />
                  </Button>
                )}

                {commandHasOverride(overrides, cmd) && (
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    title={t('settings.system.commands.resetTitle')}
                    onClick={() => resetCommand(cmd.id)}
                  >
                    <RotateCcw className="size-3" />
                  </Button>
                )}
              </div>
            </SettingsRow>
          )
        })}

        {filtered.length === 0 && (
          <p className="py-3 text-[12.5px] text-muted-foreground">{t('settings.system.commands.noMatch')}</p>
        )}
      </SettingsSection>
    </>
  )
}
