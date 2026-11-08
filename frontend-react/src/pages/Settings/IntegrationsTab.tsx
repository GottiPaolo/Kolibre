import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, Download, Loader2, NotebookPen, Plug, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  SettingsFeedback,
  SettingsHint,
  SettingsList,
  SettingsListRow,
  SettingsPill,
  SettingsRow,
  SettingsSection,
  SettingsToggle,
} from '@/components/settings/SettingsPrimitives'
import {
  getAutoWikiScrapeSetting,
  loadScraperSettings,
  saveScraperSettings,
  setAutoWikiScrapeSetting,
  type ScraperSettings,
} from '@/lib/scraperSettingsActions'
import { dictionaryErrorDetail, installDictionary, uninstallDictionary, useDictionaries } from '@/lib/dictionaryActions'
import { CalibrePluginDialog, ObsidianPluginDialog } from './DesktopPluginDialogs'
import { numero, useLingua } from '@/lib/i18n'

// Impostazioni ▸ Integrazioni: quello che collega Kolibre a programmi e
// servizi esterni (plugin desktop, Wikipedia, dizionari offline).
//
// "Priorità lingue scraper" resta solo client-side (vedi
// lib/scraperSettingsActions.ts); il toggle auto-wiki invece è collegato al
// backend reale (AppSetting "auto_wiki_scrape") — localStorage ne resta solo
// una cache per il primo paint, sovrascritta dal valore del backend appena
// arriva.
export function IntegrationsTab() {
  const { t } = useLingua()
  const [showCalibre, setShowCalibre] = useState(false)
  const [showObsidian, setShowObsidian] = useState(false)
  const [settings, setSettings] = useState<ScraperSettings>(() => loadScraperSettings())
  const [autoWikiSaveError, setAutoWikiSaveError] = useState(false)

  useEffect(() => {
    getAutoWikiScrapeSetting()
      .then((enabled) => {
        setSettings((prev) => ({ ...prev, autoWikiOnAuthorEdit: enabled }))
        saveScraperSettings({ ...loadScraperSettings(), autoWikiOnAuthorEdit: enabled })
      })
      .catch(() => {
        // Backend irraggiungibile: resta il valore da localStorage già caricato.
      })
  }, [])

  function persist(next: ScraperSettings) {
    setSettings(next)
    saveScraperSettings(next)
  }

  async function toggleAutoWiki(enabled: boolean) {
    persist({ ...settings, autoWikiOnAuthorEdit: enabled })
    setAutoWikiSaveError(false)
    try {
      await setAutoWikiScrapeSetting(enabled)
    } catch {
      persist({ ...settings, autoWikiOnAuthorEdit: !enabled })
      setAutoWikiSaveError(true)
    }
  }

  function shiftLanguage(idx: number, dir: -1 | 1) {
    const target = idx + dir
    if (target < 0 || target >= settings.languages.length) return
    const languages = [...settings.languages]
    ;[languages[idx], languages[target]] = [languages[target], languages[idx]]
    persist({ ...settings, languages })
  }

  function toggleLanguage(idx: number) {
    const languages = settings.languages.map((l, i) => (i === idx ? { ...l, active: !l.active } : l))
    persist({ ...settings, languages })
  }

  return (
    <>
      <SettingsSection
        label={t('settings.integrations.desktopPlugins.label')}
        description={t('settings.integrations.desktopPlugins.description')}
      >
        <SettingsRow name="Calibre" description={t('settings.integrations.desktopPlugins.calibreDescription')}>
          <Button variant="outline" size="sm" onClick={() => setShowCalibre(true)}>
            <Plug className="size-3.5" /> {t('settings.plugins.download')}
          </Button>
        </SettingsRow>

        <SettingsRow name="Obsidian" description={t('settings.integrations.desktopPlugins.obsidianDescription')} last>
          <Button variant="outline" size="sm" onClick={() => setShowObsidian(true)}>
            <NotebookPen className="size-3.5" /> {t('settings.plugins.download')}
          </Button>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection label={t('settings.integrations.wikipedia.label')}>
        <SettingsRow
          name={t('settings.integrations.wikipedia.autoSearchName')}
          description={t('settings.integrations.wikipedia.autoSearchDescription')}
        >
          <SettingsToggle
            label={t('settings.integrations.wikipedia.autoSearchToggle')}
            checked={settings.autoWikiOnAuthorEdit}
            onChange={(next) => void toggleAutoWiki(next)}
          />
        </SettingsRow>

        {autoWikiSaveError && (
          <SettingsFeedback kind="error">{t('settings.integrations.wikipedia.saveError')}</SettingsFeedback>
        )}

        <SettingsRow
          name={t('settings.integrations.wikipedia.preferredLanguagesName')}
          description={t('settings.integrations.wikipedia.preferredLanguagesDescription')}
          stack
          last
        >
          <SettingsList className="w-full">
            {settings.languages.map((lang, idx) => (
              <SettingsListRow key={lang.code}>
                <div className="flex min-w-0 items-center gap-2">
                  <span className="text-[13px] font-medium">{lang.name}</span>
                  <SettingsPill>{lang.code.toUpperCase()}</SettingsPill>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <SettingsToggle
                    label={t('settings.integrations.wikipedia.useLanguage', { name: lang.name })}
                    checked={lang.active}
                    onChange={() => toggleLanguage(idx)}
                  />
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title={t('settings.libraries.connected.moveUp')}
                    disabled={idx === 0}
                    onClick={() => shiftLanguage(idx, -1)}
                  >
                    <ChevronUp className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title={t('settings.libraries.connected.moveDown')}
                    disabled={idx === settings.languages.length - 1}
                    onClick={() => shiftLanguage(idx, 1)}
                  >
                    <ChevronDown className="size-3.5" />
                  </Button>
                </div>
              </SettingsListRow>
            ))}
          </SettingsList>
        </SettingsRow>

        <SettingsHint>{t('settings.integrations.wikipedia.hint')}</SettingsHint>
      </SettingsSection>

      <DictionariesSection />

      {showCalibre && <CalibrePluginDialog onClose={() => setShowCalibre(false)} />}
      {showObsidian && <ObsidianPluginDialog onClose={() => setShowObsidian(false)} />}
    </>
  )
}

// Dizionari StarDict locali (stardict_service.py) — stessa idea di KOReader:
// un dizionario vero, offline, installato esplicitamente, usato dalla
// scheda "Cerca definizione" del Vocabolario (DeviceVocabularyTable.tsx)
// PRIMA di ripiegare sul lookup online in inglese.
function DictionariesSection() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: dictionaries = [], isLoading } = useDictionaries()
  const [busyLang, setBusyLang] = useState<string | null>(null)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  async function invalidate() {
    await queryClient.invalidateQueries({ queryKey: ['dictionaries'] })
  }

  async function handleInstall(lang: string, displayName: string) {
    setBusyLang(lang)
    setMessage(null)
    try {
      await installDictionary(lang)
      await invalidate()
      setMessage({ kind: 'ok', text: t('settings.integrations.dictionaries.installed', { name: displayName }) })
    } catch (err) {
      setMessage({ kind: 'error', text: dictionaryErrorDetail(err, t('settings.integrations.dictionaries.installError')) })
    } finally {
      setBusyLang(null)
    }
  }

  async function handleUninstall(lang: string, displayName: string) {
    setBusyLang(lang)
    setMessage(null)
    try {
      await uninstallDictionary(lang)
      await invalidate()
      setMessage({ kind: 'ok', text: t('settings.integrations.dictionaries.removed', { name: displayName }) })
    } catch (err) {
      setMessage({ kind: 'error', text: dictionaryErrorDetail(err, t('settings.integrations.dictionaries.removeError')) })
    } finally {
      setBusyLang(null)
    }
  }

  return (
    <SettingsSection
      label={t('settings.integrations.dictionaries.label')}
      description={t('settings.integrations.dictionaries.description')}
    >
      {isLoading && <p className="py-3 text-[12.5px] text-muted-foreground">{t('common.loading')}</p>}

      {dictionaries.length > 0 && (
        <SettingsList className="mt-3">
          {dictionaries.map((d) => (
            <SettingsListRow key={d.lang}>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium">{d.display_name}</span>
                  {d.installed && (
                    <SettingsPill tone="ok">
                      {d.wordcount != null ? numero(d.wordcount) : '?'} {t('settings.integrations.dictionaries.words')}
                    </SettingsPill>
                  )}
                </div>
                <div className="mt-1 text-[11.5px] text-muted-foreground">{d.attribution}</div>
              </div>
              {d.installed ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive"
                  disabled={busyLang !== null}
                  onClick={() => void handleUninstall(d.lang, d.display_name)}
                >
                  {busyLang === d.lang ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
                  {t('settings.integrations.dictionaries.remove')}
                </Button>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busyLang !== null}
                  onClick={() => void handleInstall(d.lang, d.display_name)}
                >
                  {busyLang === d.lang ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <Download className="size-3.5" />
                  )}
                  {t('settings.integrations.dictionaries.install')}
                </Button>
              )}
            </SettingsListRow>
          ))}
        </SettingsList>
      )}

      {message && <SettingsFeedback kind={message.kind}>{message.text}</SettingsFeedback>}

      <SettingsHint>{t('settings.integrations.dictionaries.hint')}</SettingsHint>
    </SettingsSection>
  )
}
