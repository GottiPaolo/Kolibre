// Impostazioni → Integrazioni → Dizionari: elenco/installazione dizionari
// StarDict locali (stardict_service.py) — vedi anche dictionaryActions per il
// perché (offline, nella lingua vera della parola, non l'inglese di Wiktionary).
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { messaggioErrore } from './messaggiErrore'

export interface DictionaryInfo {
  lang: string
  display_name: string
  attribution: string
  installed: boolean
  bookname: string | null
  wordcount: number | null
}

export async function getDictionaries(): Promise<DictionaryInfo[]> {
  const { data, error } = await api.GET('/api/kolibre/dictionaries')
  if (error) throw error
  return (data as unknown as { items: DictionaryInfo[] }).items
}

export function useDictionaries() {
  return useQuery({ queryKey: ['dictionaries'], queryFn: getDictionaries })
}

export async function installDictionary(lang: string): Promise<void> {
  const { error } = await api.POST('/api/kolibre/dictionaries/{lang}/install', {
    params: { path: { lang } },
  })
  if (error) throw error
}

export async function uninstallDictionary(lang: string): Promise<void> {
  const { error } = await api.DELETE('/api/kolibre/dictionaries/{lang}', {
    params: { path: { lang } },
  })
  if (error) throw error
}

export interface WordLookupResult {
  definition: string
  source: string
}

// Usata dal popup di selezione testo del reader web (ReaderPage.tsx) per
// mostrare la definizione di una parola PRIMA che l'utente scelga se
// aggiungerla al vocabolario — endpoint senza side-effect (non crea/aggiorna
// nessuna riga), a differenza di /api/kolibre/vocabulary/{id}/fetch-definition
// che invece opera su una entry già salvata. Ritorna null sia per "non
// trovata" (404) sia per un errore di rete: è solo un'anteprima, non deve
// mai bloccare la lettura.
export async function lookupWord(word: string): Promise<WordLookupResult | null> {
  try {
    const { data, error } = await api.GET('/api/kolibre/dictionaries/lookup', { params: { query: { word } } })
    if (error) return null
    return data as unknown as WordLookupResult
  } catch {
    return null
  }
}

// Terza copia dello stesso estrattore: anche lei delega al modulo unico.
export function dictionaryErrorDetail(err: unknown, fallback: string, stato?: number): string {
  return messaggioErrore(err, fallback, stato)
}
