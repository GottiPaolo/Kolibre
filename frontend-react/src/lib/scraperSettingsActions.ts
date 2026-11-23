// Impostazioni "Wikipedia & Scraper" della tab Integrazioni (Fase 8, parte
// 2) — porting da frontend/src/App.vue (settingsAutoWiki/scraperLanguages/
// shiftLanguage, righe ~4536-4562 e ~8071-8078).
//
// `autoWikiOnAuthorEdit` è ora un'impostazione backend reale (AppSetting
// "auto_wiki_scrape", vedi backend/app/services/app_settings.py +
// api/settings.py): quando attiva, ogni volta che un autore compare per la
// prima volta nel database (ingest, upload/aggiornamento plugin Calibre,
// copia libro, rescan libreria, modifica manuale) parte in background un
// tentativo di scrape Wikipedia — vedi
// backend/app/services/author_ingest_hook.py e i suoi call site. Le
// funzioni getAutoWikiScrapeSetting/setAutoWikiScrapeSetting sotto
// leggono/scrivono quel flag; localStorage resta solo una cache per il
// primo paint (IntegrationsTab la sovrascrive col valore reale del backend
// appena arriva).
//
// `scraperLanguages`: dal 23/11/2026 le lingue ATTIVE di questa lista sono
// un'impostazione backend reale (AppSetting "wikipedia_bio_languages", rotte
// GET/PUT /settings/wikipedia-languages): lo scraper le percorre tutte e la
// pagina autore mostra un pannello per lingua. localStorage resta la cache
// del primo paint, più nomi e ordine della lista nella UI (l'ordine dei
// PANNELLI invece è alfabetico per autonimo: lib/wikipediaLanguages.ts).
import { api } from './api'
import { leggiLocale, scriviLocale } from './memoriaLocale'

export interface ScraperLanguage {
  code: string
  name: string
  active: boolean
}

export interface ScraperSettings {
  autoWikiOnAuthorEdit: boolean
  languages: ScraperLanguage[]
}

const STORAGE_KEY = 'kolibre_scraper_settings_v1'

const DEFAULT_SETTINGS: ScraperSettings = {
  autoWikiOnAuthorEdit: true,
  languages: [
    { code: 'it', name: 'Italiano', active: true },
    { code: 'en', name: 'English', active: true },
    { code: 'fr', name: 'Français', active: false },
    { code: 'de', name: 'Deutsch', active: false },
    { code: 'es', name: 'Español', active: false },
  ],
}

function isValidLanguageList(value: unknown): value is ScraperLanguage[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(
      (l) =>
        l &&
        typeof l === 'object' &&
        typeof (l as ScraperLanguage).code === 'string' &&
        typeof (l as ScraperLanguage).name === 'string' &&
        typeof (l as ScraperLanguage).active === 'boolean'
    )
  )
}

export function loadScraperSettings(): ScraperSettings {
  try {
    const raw = leggiLocale(STORAGE_KEY)
    if (!raw) return DEFAULT_SETTINGS
    const parsed = JSON.parse(raw) as Partial<ScraperSettings>
    return {
      autoWikiOnAuthorEdit:
        typeof parsed.autoWikiOnAuthorEdit === 'boolean'
          ? parsed.autoWikiOnAuthorEdit
          : DEFAULT_SETTINGS.autoWikiOnAuthorEdit,
      languages: isValidLanguageList(parsed.languages) ? parsed.languages : DEFAULT_SETTINGS.languages,
    }
  } catch {
    return DEFAULT_SETTINGS
  }
}

export function saveScraperSettings(settings: ScraperSettings): void {
  scriviLocale(STORAGE_KEY, JSON.stringify(settings))
}

export async function getAutoWikiScrapeSetting(): Promise<boolean> {
  const { data, error } = await api.GET('/api/kolibre/settings/auto-wiki-scrape')
  if (error) throw error
  return data.enabled
}

export async function setAutoWikiScrapeSetting(enabled: boolean): Promise<boolean> {
  const { data, error } = await api.PUT('/api/kolibre/settings/auto-wiki-scrape', {
    body: { enabled },
  })
  if (error) throw error
  return data.enabled
}

export async function getWikipediaLanguagesSetting(): Promise<string[]> {
  const { data, error } = await api.GET('/api/kolibre/settings/wikipedia-languages')
  if (error) throw error
  return data.languages
}

export async function setWikipediaLanguagesSetting(languages: string[]): Promise<string[]> {
  const { data, error } = await api.PUT('/api/kolibre/settings/wikipedia-languages', {
    body: { languages },
  })
  if (error) throw error
  return data.languages
}
