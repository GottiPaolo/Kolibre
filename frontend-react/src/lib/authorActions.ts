// Porting 1:1 degli endpoint reali usati da frontend/src/App.vue per la
// pagina Autori. Nessuno di questi richiede auth lato backend (verificato:
// authors.py non importa il modulo auth) — il client `api` inietta comunque
// l'header, non fa differenza.
import { api } from './api'
import type { AuthorDetail, AuthorImageResult } from '@/types/author'

/**
 * Correzione manuale dei dati di un autore. Accetta la biografia e
 * l'anagrafica (genere, nazionalita', nascita, morte, occupazione): un campo
 * assente non viene toccato, un campo presente e vuoto viene azzerato — ed e'
 * il modo per dire "questo riprendilo da Wikidata al prossimo giro".
 */
export async function updateAuthorFields(
  name: string,
  fields: Record<string, string | string[]>
): Promise<AuthorDetail> {
  const { data, error } = await api.PUT('/api/kolibre/authors/{name}', {
    params: { path: { name } },
    body: fields as never,
  })
  if (error) throw error
  return data as unknown as AuthorDetail
}

export async function updateAuthorBio(name: string, fields: { bio_it?: string; bio_en?: string }): Promise<AuthorDetail> {
  const { data, error } = await api.PUT('/api/kolibre/authors/{name}', {
    params: { path: { name } },
    body: fields,
  })
  if (error) throw error
  return data as unknown as AuthorDetail
}

export async function refreshAuthorFromWikipedia(name: string): Promise<AuthorDetail> {
  const { data, error } = await api.POST('/api/kolibre/authors/{name}/refresh', {
    params: { path: { name } },
  })
  if (error) throw error
  return data as unknown as AuthorDetail
}

export async function refreshAuthorFromWikipediaUrl(
  name: string,
  url: string,
  targetLang: 'it' | 'en'
): Promise<AuthorDetail> {
  const { data, error } = await api.POST('/api/kolibre/authors/{name}/refresh-from-url', {
    params: { path: { name } },
    body: { url, target_lang: targetLang },
  })
  if (error) throw error
  return data as unknown as AuthorDetail
}

export async function searchAuthorImages(query: string): Promise<AuthorImageResult[]> {
  const { data, error } = await api.GET('/api/kolibre/authors/image-search', {
    params: { query: { q: query } },
  })
  if (error) throw error
  return data as unknown as AuthorImageResult[]
}

export async function setAuthorPhotoFromUrl(name: string, url: string): Promise<AuthorDetail> {
  const { data, error } = await api.POST('/api/kolibre/authors/{name}/photo-from-url', {
    params: { path: { name } },
    body: { url },
  })
  if (error) throw error
  return data as unknown as AuthorDetail
}

export async function uploadAuthorPhoto(name: string, file: File): Promise<AuthorDetail> {
  const { data, error } = await api.POST('/api/kolibre/authors/{name}/photo', {
    params: { path: { name } },
    // @ts-expect-error openapi-fetch vuole il body JSON-shaped anche per multipart; il bodySerializer sotto lo trasforma davvero.
    body: { file },
    bodySerializer() {
      const form = new FormData()
      form.append('file', file)
      return form
    },
  })
  if (error) throw error
  return data as unknown as AuthorDetail
}

export async function deleteAuthorPhoto(name: string): Promise<void> {
  const { error } = await api.DELETE('/api/kolibre/authors/{name}/photo', {
    params: { path: { name } },
  })
  if (error) throw error
}

export async function resetAuthorData(name: string): Promise<void> {
  const { error } = await api.DELETE('/api/kolibre/authors/{name}', {
    params: { path: { name } },
  })
  if (error) throw error
}

// --- Recupero Wikipedia di massa ---------------------------------------
//
// Il giro vive sul server (backend/app/services/author_scrape_job.py), non
// più come ciclo in questa pagina: sopravvive a cambio pagina, ricarica e
// chiusura del browser, e la guardia "ce n'è già uno in corso" sta in un
// posto che il rimontaggio di un componente non può azzerare.

export interface ScrapeJobStatus {
  running: boolean
  total: number
  processed: number
  current: string | null
  /** Autori per cui la richiesta è andata storta (rete, limite di richieste). */
  failed: string[]
  /** Autori per cui Wikipedia semplicemente non ha una voce: non è un guasto. */
  not_found: string[]
  /** Voce trovata, ma nessuna foto né su Wikipedia né su Wikidata. */
  no_image: string[]
  /** Autori non riprovati perché già completi o ancora in attesa. */
  skipped: number
  /** Il giro si è fermato da solo perché Wikipedia stava rifiutando. */
  stopped_early: boolean
  /** Prima di questo istante non ha senso ritentare (ISO, UTC). */
  blocked_until: string | null
  started_at: string | null
  finished_at: string | null
}

export async function startScrapeMissingAuthors(force: boolean): Promise<'started' | 'nothing_to_do'> {
  const { data, error } = await api.POST('/api/kolibre/authors/scrape-missing', {
    params: { query: { force } },
  })
  if (error) throw error
  return (data as { status: 'started' | 'nothing_to_do' }).status
}

export async function fetchScrapeAuthorsStatus(): Promise<ScrapeJobStatus> {
  const { data, error } = await api.GET('/api/kolibre/authors/scrape-status', {})
  if (error) throw error
  return data as unknown as ScrapeJobStatus
}
