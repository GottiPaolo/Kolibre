// Interruttore del feed OPDS standard (Atom/XML, Basic Auth) — vedi
// backend/app/api/opds.py + services/app_settings.py (chiave "opds_feed").
// Canale separato dal protocollo JSON del plugin KOReader: questo flag
// controlla solo se le route sotto /opds rispondono 404 o servono il feed.
import { api } from './api'
import type { components } from '@/api/schema'

export async function getOpdsFeedEnabled(): Promise<boolean> {
  const { data, error } = await api.GET('/api/kolibre/settings/opds-feed')
  if (error) throw error
  return data.enabled
}

export async function setOpdsFeedEnabled(enabled: boolean): Promise<boolean> {
  const { data, error } = await api.PUT('/api/kolibre/settings/opds-feed', {
    body: { enabled },
  })
  if (error) throw error
  return data.enabled
}

// ── Reader web: conta come dispositivo di lettura? ───────────────────────
//
// SPENTO di default dal 01/10/2026: il reader web si usa quasi sempre per
// consultare, non per leggere. Vedi il commento su
// WEB_READER_TRACKING_KEY in backend/app/services/app_settings.py per i due
// danni che contarlo provoca — statistiche sporche, e il segnalibro del Kindle
// riportato indietro.

export async function getWebReaderTracking(): Promise<boolean> {
  const { data, error } = await api.GET('/api/kolibre/settings/web-reader-tracking')
  if (error) throw error
  return data.enabled
}

export async function setWebReaderTracking(enabled: boolean): Promise<boolean> {
  const { data, error } = await api.PUT('/api/kolibre/settings/web-reader-tracking', {
    body: { enabled },
  })
  if (error) throw error
  return data.enabled
}

// ── Biblioteche grandi ───────────────────────────────────────────────────
//
// Due limiti che conviene dichiarare invece di scoprire: da quanti libri in
// su la pagina Libreria passa alle pagine, e quanto puo' crescere l'indice
// full-text. Vedi il commento su LIBRARY_PAGINATION_KEY e FULLTEXT_LIMIT_KEY
// in backend/app/services/app_settings.py per i numeri misurati che stanno
// dietro ai valori di default.

/**
 * Da quanti elementi in su una pagina si divide in pagine, e quanto grandi.
 *
 * **Dal 05/11/2026 arriva dallo schema.** La stessa forma per tutte e tre le
 * pagine che ce l'hanno (Libreria, Arretrati, Autori), con tre soglie
 * diverse perché pesano in modo diverso.
 *
 * Il nome resta `LibraryPagination` perché lo usano tre file, ma non è solo
 * della libreria: nel server si chiama `ImpostazionePaginazione`.
 */
export type LibraryPagination = components['schemas']['ImpostazionePaginazione']

export async function getLibraryPagination(): Promise<LibraryPagination> {
  const { data, error } = await api.GET('/api/kolibre/settings/library-pagination')
  if (error) throw error
  return data
}

export async function setLibraryPagination(value: Partial<LibraryPagination>): Promise<LibraryPagination> {
  const { data, error } = await api.PUT('/api/kolibre/settings/library-pagination', { body: value })
  if (error) throw error
  return data
}

export async function getFulltextLimitGb(): Promise<number> {
  const { data, error } = await api.GET('/api/kolibre/settings/fulltext-limit')
  if (error) throw error
  return data.max_gb
}

export async function setFulltextLimitGb(maxGb: number): Promise<number> {
  const { data, error } = await api.PUT('/api/kolibre/settings/fulltext-limit', { body: { max_gb: maxGb } })
  if (error) throw error
  return data.max_gb
}

export async function getIngestPagination(): Promise<LibraryPagination> {
  const { data, error } = await api.GET('/api/kolibre/settings/ingest-pagination')
  if (error) throw error
  return data
}

export async function setIngestPagination(value: Partial<LibraryPagination>): Promise<LibraryPagination> {
  const { data, error } = await api.PUT('/api/kolibre/settings/ingest-pagination', { body: value })
  if (error) throw error
  return data
}

export async function getAuthorsPagination(): Promise<LibraryPagination> {
  const { data, error } = await api.GET('/api/kolibre/settings/authors-pagination')
  if (error) throw error
  return data
}

export async function setAuthorsPagination(value: Partial<LibraryPagination>): Promise<LibraryPagination> {
  const { data, error } = await api.PUT('/api/kolibre/settings/authors-pagination', { body: value })
  if (error) throw error
  return data
}
