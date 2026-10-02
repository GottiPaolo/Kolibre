// Tipi per la Fase 5 (Dispositivi) — porting dei payload reali restituiti da
// backend/app/api/devices.py (list_devices, flagged-books, sync-history,
// backups). Molti endpoint non hanno un response_model FastAPI (restituiscono
// dict/list "a mano"), quindi qui i tipi sono scritti a mano invece che
// generati — stesso approccio già usato per gli altri campi "unknown" nello
// schema OpenAPI generato (vedi lib/queries.ts, `data as unknown as X`).

export type DeviceBookStatus =
  | 'synced'
  | 'pending_send'
  | 'send_failed'
  | 'pending_delete'
  | 'delete_declined'
  | 'removed_by_device'

// Una riga di DeviceBook come restituita dentro Device.books da GET
// /api/devices (list_devices) — NON lo stesso oggetto del modello DB, è già
// arricchito con titolo/autore/hash_verified/avanzamento/note.
export interface DeviceBookRow {
  id: number
  calibre_book_id: number
  library: string
  format: string
  book_title: string | null
  book_author: string | null
  cover_url: string | null
  hash_verified: boolean
  status: DeviceBookStatus
  created_at: string | null
  device_pages: number | null
  device_path: string | null
  requested_by: string | null
  last_error: string | null
  progress_percent: number
  highlights_count: number
}

export interface DeviceSyncQueueEntry {
  id: number
  calibre_book_id: number
  library: string
  action: 'queued_download' | 'queued_delete'
  format: string
}

export interface Device {
  id: number
  name: string
  model: string | null
  is_default: boolean
  last_sync_at: string | null
  last_backup_at: string | null
  last_seen_at: string | null
  plugin_version: string | null
  delete_policy: string
  backup_file_count: number
  // list_devices restituisce sempre la stessa lista fissa (vedi il backend:
  // hardcoded, non per-dispositivo) — nessun campo la persiste davvero (non
  // esiste in DeviceUpdate), quindi qui è trattata come puro dato di
  // visualizzazione, non editabile in modo significativo (vedi il report).
  supported_formats: string[]
  folder_layout: string
  write_folder_cover: boolean
  books: DeviceBookRow[]
  sync_queue: DeviceSyncQueueEntry[]
  // Spazio del volume che ospita i libri, in byte, misurato dal plugin
  // KOReader a ogni handshake dalla v0.6.15. Con un plugin più vecchio
  // restano null e la scheda dice "non riportato dal dispositivo" — che fino
  // al 28/09/2026 era l'unica cosa che si è mai vista, perché il campo
  // esisteva e nessuno lo riempiva.
  storage_used?: number | null
  storage_total?: number | null
  storage_available?: number | null
  pending_restore_request: DeviceRestoreRequest | null
}

// "Resetta a stato di dispositivo" (task #266) — vedi
// devices.py::_serialize_restore_request. status: 'pending_admin' (creata
// dal plugin, in attesa di conferma admin) | 'confirmed_admin' (admin ha
// confermato, in attesa che il plugin confermi a sua volta) — 'done' non
// compare mai qui, list_devices la esclude (vedi _get_open_restore_request).
export interface DeviceRestoreRequest {
  id: number
  source_device_id: number
  source_device_name: string | null
  status: 'pending_admin' | 'confirmed_admin'
  requested_at: string | null
  confirmed_at: string | null
}

// Risposta di POST /api/devices/register (schemas.DeviceResponse) — l'unico
// punto in cui device_token è visibile (non più restituito da GET /api/devices).
export interface DeviceCreatedResponse {
  id: number
  name: string
  model: string
  hardware_id?: string | null
  is_default: boolean
  device_token: string
  last_sync_at?: string | null
  last_backup_at?: string | null
  storage_used?: number | null
  folder_layout: string
  write_folder_cover: boolean
  plugin_version?: string | null
  last_seen_at?: string | null
  delete_policy: string
}

export type FlaggedMatchStatus = 'flagged_started' | 'no_candidate' | string
export type FlaggedPendingAction = 'delete' | 'overwrite' | null

export interface DeviceFlaggedBook {
  id: number
  local_path: string
  local_title: string | null
  local_author: string | null
  match_status: FlaggedMatchStatus
  local_percent_read: number | null
  local_highlights_count: number | null
  candidate_library: string | null
  candidate_calibre_book_id: number | null
  candidate_title: string | null
  candidate_author: string | null
  flagged_at: string | null
  pending_action: FlaggedPendingAction
}

export type SyncOutcome = 'ok' | 'partial' | 'error' | 'open' | 'abandoned' | string

export interface DeviceSyncHistoryEntry {
  id: number
  session_id: string | null
  started_at: string | null
  finished_at: string | null
  outcome: SyncOutcome
  plugin_version: string | null
  trigger: string | null
  books_reported: number | null
  downloads_requested: number | null
  downloads_ok: number | null
  downloads_failed: number | null
  deletes_requested: number | null
  deletes_done: number | null
  deletes_declined: number | null
  removed_by_device: number | null
  pages_reported: number | null
  detail_json: string | null
}

export interface DeviceBackup {
  filename: string
  size: number
  modified_at: string
}

// Da GET /api/devices/{device_id}/vocabulary — vocabulary builder KOReader,
// nessun campo definizione: KOReader non la salva mai (verificato su file di
// produzione reali, vedi vocabulary_service.py).
export interface DeviceVocabularyEntry {
  id: number
  word: string
  highlight: string | null
  book_title: string | null
  context_before: string | null
  context_after: string | null
  create_time: string | null
  review_time: string | null
  due_time: string | null
  review_count: number
  streak_count: number
  // Popolati solo da una richiesta esplicita ("Cerca definizione") — vedi
  // dictionary_service.py, mai riempiti automaticamente all'import.
  definition: string | null
  definition_source: string | null
  definition_fetched_at: string | null
}
