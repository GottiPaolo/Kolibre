// Azioni per la tab Impostazioni → Librerie (Fase 8, parte 2) — porting da
// frontend/src/App.vue (createNewLibrary/verifyAndImportCalibreLibrary/
// moveLibrary/confirmDeleteLibrary/saveLibraryDetails/addCustomColumn/
// deleteCustomColumn/repairDateCustomColumns/savePageCountSettings/
// recomputePageCounts, righe ~6196-8020 e ~7402-7441). File separato da
// queries.ts (non toccabile: condiviso con altre pagine/fasi già in
// produzione) per evitare conflitti di merge con l'agente in lavorazione in
// parallelo sulle altre tab di Impostazioni.
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { messaggioErrore } from './messaggiErrore'
import type { CustomColumnDatatype } from '@/types/library'

export interface PageCountSettings {
  mode: 'words' | 'chars'
  words_per_page: number
  chars_per_page: number
}

export async function createLibrary(name: string): Promise<void> {
  const { error } = await api.POST('/api/kolibre/libraries', { body: { name } })
  if (error) throw error
}

// Zero-copy: il backend punta a `path` con un symlink, non copia nulla —
// vedi backend/app/api/libraries.py::import_library. Nessun endpoint di
// filesystem-browsing esiste (verificato: nessuna occorrenza di
// os.listdir/browse in nessun altro api/*.py) — il "Navigatore Cartelle del
// Server" del Vue esistente era client-side mock (mockSubdirectories,
// nessuna vera lettura del filesystem), quindi qui il percorso è un campo di
// testo semplice, non un browser fittizio (vedi ImportLibraryDialog e il
// report della fase).
export async function importLibrary(name: string, path: string): Promise<void> {
  const { error } = await api.POST('/api/kolibre/libraries/import', { body: { name, path } })
  if (error) throw error
}

export async function reorderLibraries(order: number[]): Promise<void> {
  const { error } = await api.PUT('/api/kolibre/libraries/order', { body: { order } })
  if (error) throw error
}

export async function deleteLibrary(folderName: string): Promise<void> {
  const { error } = await api.DELETE('/api/kolibre/libraries/{name}', { params: { path: { name: folderName } } })
  if (error) throw error
}

export async function recomputeLibraryPageCounts(folderName: string): Promise<{ status: string; updated: number }> {
  const { data, error } = await api.POST('/api/kolibre/libraries/{name}/recompute-pages', {
    params: { path: { name: folderName } },
  })
  if (error) throw error
  return data as unknown as { status: string; updated: number }
}

export async function recomputeBookPageCount(bookId: number, folderName: string): Promise<{ status: string; pages: number }> {
  const { data, error } = await api.POST('/api/kolibre/books/{id}/recompute-pages', {
    params: { path: { id: bookId }, query: { library: folderName } },
  })
  if (error) throw error
  return data as unknown as { status: string; pages: number }
}

// Impostazioni globali (non per-libreria) — backend/app/api/settings.py.
export async function getPageCountSettings(): Promise<PageCountSettings> {
  const { data, error } = await api.GET('/api/kolibre/settings/page-count')
  if (error) throw error
  return data as unknown as PageCountSettings
}

export async function savePageCountSettings(settings: PageCountSettings): Promise<PageCountSettings> {
  const { data, error } = await api.PUT('/api/kolibre/settings/page-count', { body: { ...settings } })
  if (error) throw error
  return data as unknown as PageCountSettings
}

// Hook di lettura, definito qui (non in queries.ts, non toccabile) seguendo
// lo stesso schema con cui DevicesPage.tsx già usa useQuery con una queryFn
// inline per dati non ancora coperti da un hook condiviso.
export function usePageCountSettings() {
  return useQuery({ queryKey: ['page-count-settings'], queryFn: getPageCountSettings })
}

// L'unica impostazione del vecchio modale "Impostazioni libreria" che sia
// mai stata davvero persistita server-side (vedi saveLibraryDetails nel Vue
// esistente, che confronta wasFulltextEnabled/isNowFulltextEnabled prima di
// chiamare questo endpoint) — nome/icona/accesso utenti nello stesso modale
// restano solo locali anche lì, non è una regressione di questo porting
// (dettagli nel report).
export async function setLibraryFulltextEnabled(folderName: string, enabled: boolean): Promise<void> {
  const { error } = await api.PUT('/api/kolibre/fulltext/settings', {
    params: { query: { library: folderName } },
    body: { enabled },
  })
  if (error) throw error
}

export async function createCustomColumn(
  folderName: string,
  label: string,
  name: string,
  datatype: CustomColumnDatatype,
  enumValues?: string[]
): Promise<void> {
  const { error } = await api.POST('/api/kolibre/custom-columns', {
    params: { query: { library: folderName } },
    body: {
      label,
      name,
      datatype,
      display: enumValues ? { enum_values: enumValues } : undefined,
    },
  })
  if (error) throw error
}

export async function deleteCustomColumnFor(folderName: string, label: string): Promise<void> {
  const { error } = await api.DELETE('/api/kolibre/custom-columns/{label}', {
    params: { path: { label }, query: { library: folderName } },
  })
  if (error) throw error
}

export interface TrashedLibrary {
  id: string
  folder_name: string
  deleted_at: string | null
  size_bytes: number
}

// Il cestino esisteva solo lato filesystem (_trash_libraries, popolato da
// delete_library/import_library) senza alcun modo di agire su di esso — vedi
// backend/app/api/libraries.py, i tre nuovi endpoint GET/trash/{id}/restore/
// DELETE aggiunti insieme a queste azioni.
export async function getTrashedLibraries(): Promise<TrashedLibrary[]> {
  const { data, error } = await api.GET('/api/kolibre/libraries/trash')
  if (error) throw error
  return (data as unknown as { items: TrashedLibrary[] }).items
}

export function useTrashedLibraries() {
  return useQuery({ queryKey: ['libraries-trash'], queryFn: getTrashedLibraries })
}

export async function restoreTrashedLibrary(id: string): Promise<{ status: string; folder_name: string }> {
  const { data, error } = await api.POST('/api/kolibre/libraries/trash/{entry}/restore', {
    params: { path: { entry: id } },
  })
  if (error) throw error
  return data as unknown as { status: string; folder_name: string }
}

export async function purgeTrashedLibrary(id: string): Promise<void> {
  const { error } = await api.DELETE('/api/kolibre/libraries/trash/{entry}', { params: { path: { entry: id } } })
  if (error) throw error
}

// Delega al modulo unico dei messaggi (lib/messaggiErrore.ts): il nome resta
// perché lo usano una ventina di punti, ma la regola su cosa dire sta in un
// posto solo — compresa quella sui permessi, che prima non c'era.
export function errorDetail(err: unknown, fallback: string, stato?: number): string {
  return messaggioErrore(err, fallback, stato)
}
