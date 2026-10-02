// Funzioni di scrittura per la Fase 5 (Dispositivi) — porting 1:1 dei
// payload/endpoint reali usati da frontend/src/App.vue (addDevice,
// saveDeviceDetails, confirmDeleteDevice, setAsDefaultDevice,
// _queueDeviceBookRow, _deviceBookRowAction, pairDeviceBookRow,
// deleteFlaggedBook, queueFlaggedBookAction, bulkDeleteFlaggedBooks,
// downloadDeviceBackups) contro backend/app/api/devices.py. File separato da
// bookActions.ts per evitare conflitti di merge con altre pagine in
// lavorazione in parallelo.
import { api, withBackendUrl } from './api'
import { ensureAuthToken } from './auth'
import { messaggioErrore } from './messaggiErrore'
import type { Device, DeviceCreatedResponse } from '@/types/device'

// Molti di questi endpoint accettano un dict libero lato backend (nessun
// response_model/request body Pydantic — verificato in devices.py) e
// rispondono con HTTPException(detail=...) sugli errori applicativi (404,
// 400): stesso estrattore già introdotto per l'Ingest (Fase 7), qui
// duplicato invece di importato per non creare una dipendenza incrociata
// tra fasi lavorate in parallelo.
// La duplicazione citata qui sopra è finita: le tre copie dell'estrattore
// delegano tutte a lib/messaggiErrore.ts, dove sta anche la regola sui
// permessi — "non hai i permessi" invece di "errore" (28/09/2026).
export function deviceErrorDetail(err: unknown, fallback: string, stato?: number): string {
  return messaggioErrore(err, fallback, stato)
}

export async function registerDevice(name: string, model: string): Promise<DeviceCreatedResponse> {
  const { data, error } = await api.POST('/api/devices/register', {
    body: { name, model },
  })
  if (error) throw error
  return data as unknown as DeviceCreatedResponse
}

export interface DeviceUpdatePayload {
  name?: string
  model?: string
  folder_layout?: string
  write_folder_cover?: boolean
  delete_policy?: string
}

export async function updateDevice(deviceId: number, payload: DeviceUpdatePayload): Promise<Device> {
  const { data, error } = await api.PUT('/api/devices/{device_id}', {
    params: { path: { device_id: deviceId } },
    body: payload,
  })
  if (error) throw error
  return data as unknown as Device
}

export async function deleteDeviceApi(deviceId: number): Promise<void> {
  const { error } = await api.DELETE('/api/devices/{device_id}', {
    params: { path: { device_id: deviceId } },
  })
  if (error) throw error
}

export async function setDefaultDevice(deviceId: number): Promise<void> {
  const { error } = await api.POST('/api/devices/{device_id}/set-default', {
    params: { path: { device_id: deviceId } },
  })
  if (error) throw error
}

// "Resetta a stato di dispositivo" (task #266) — seconda delle tre conferme:
// l'admin approva qui la richiesta che il plugin ha creato sul device
// target. requestId nel body (non solo deviceId nel path) per evitare di
// confermare per sbaglio una richiesta già sostituita da una più recente
// (vedi devices.py::confirm_device_restore_request).
export async function confirmDeviceRestore(deviceId: number, requestId: number): Promise<void> {
  const { error } = await api.POST('/api/devices/{device_id}/restore-request/confirm', {
    params: { path: { device_id: deviceId } },
    body: { request_id: requestId },
  })
  if (error) throw error
}

export async function cancelDeviceRestore(deviceId: number): Promise<void> {
  const { error } = await api.DELETE('/api/devices/{device_id}/restore-request', {
    params: { path: { device_id: deviceId } },
  })
  if (error) throw error
}

export interface QueueBookForDevicePayload {
  calibre_book_id: number
  library: string
  format: string
  action: 'queued_download' | 'queued_delete'
  // Il body di /queue non ha un modello Pydantic (dict libero lato backend
  // — verificato in devices.py), quindi la firma OpenAPI generata è
  // { [key: string]: unknown }: la index signature qui sotto rende questa
  // interfaccia assegnabile a quella firma senza un cast ad ogni chiamata.
  [key: string]: unknown
}

export async function queueBookForDevice(deviceId: number, payload: QueueBookForDevicePayload): Promise<void> {
  const { error } = await api.POST('/api/devices/{device_id}/queue', {
    params: { path: { device_id: deviceId } },
    body: payload,
  })
  if (error) throw error
}

export async function cancelDeviceBookAction(deviceId: number, rowId: number): Promise<void> {
  const { error } = await api.POST('/api/devices/{device_id}/books/{book_row_id}/cancel', {
    params: { path: { device_id: deviceId, book_row_id: rowId } },
  })
  if (error) throw error
}

export async function acknowledgeDeviceBookRemoval(deviceId: number, rowId: number): Promise<void> {
  const { error } = await api.POST('/api/devices/{device_id}/books/{book_row_id}/acknowledge-removal', {
    params: { path: { device_id: deviceId, book_row_id: rowId } },
  })
  if (error) throw error
}

export interface PairDeviceBookPayload {
  library: string
  calibre_book_id: number
  format: string
  [key: string]: unknown
}

export async function pairDeviceBookRow(
  deviceId: number,
  rowId: number,
  payload: PairDeviceBookPayload
): Promise<{ migrated_highlights: number }> {
  const { data, error } = await api.POST('/api/devices/{device_id}/books/{book_row_id}/pair', {
    params: { path: { device_id: deviceId, book_row_id: rowId } },
    body: payload,
  })
  if (error) throw error
  return data as unknown as { migrated_highlights: number }
}

export async function deleteFlaggedBook(deviceId: number, flaggedId: number): Promise<void> {
  const { error } = await api.DELETE('/api/devices/{device_id}/flagged-books/{flagged_id}', {
    params: { path: { device_id: deviceId, flagged_id: flaggedId } },
  })
  if (error) throw error
}

export interface QueueFlaggedActionPayload {
  action: 'delete' | 'overwrite' | 'pair'
  library?: string
  calibre_book_id?: number
  format?: string
  [key: string]: unknown
}

export async function queueFlaggedBookAction(
  deviceId: number,
  flaggedId: number,
  payload: QueueFlaggedActionPayload
): Promise<{ pending_action?: string; migrated_highlights?: number }> {
  const { data, error } = await api.POST('/api/devices/{device_id}/flagged-books/{flagged_id}/action', {
    params: { path: { device_id: deviceId, flagged_id: flaggedId } },
    body: payload,
  })
  if (error) throw error
  return data as unknown as { pending_action?: string; migrated_highlights?: number }
}

export async function bulkDeleteFlaggedBooks(deviceId: number, ids: number[]): Promise<void> {
  const { error } = await api.POST('/api/devices/{device_id}/flagged-books/bulk-action', {
    params: { path: { device_id: deviceId } },
    body: { action: 'delete', ids },
  })
  if (error) throw error
}

// Scarica lo zip dei backup del dispositivo — window.open diretto (come nel
// Vue esistente), non il blob-download "anti auto-estrazione Safari" usato
// per i plugin: qui il file è già un .zip vero e proprio destinato a essere
// aperto/estratto dall'utente, non un asset da servire "as-is".
// download_device_backups usa get_current_user_flexible (header o
// ?token=), quindi serve il token corrente anche qui.
export async function downloadDeviceBackups(deviceId: number): Promise<void> {
  const token = await ensureAuthToken()
  window.open(withBackendUrl(`/api/devices/${deviceId}/backups/download?token=${token || ''}`), '_blank')
}

/** Dimentica il vocabolario di UN dispositivo, tenendo tutto il resto. */
export async function dimenticaVocabolario(deviceId: number): Promise<number> {
  const { data, error } = await api.DELETE('/api/devices/{device_id}/vocabulary', {
    params: { path: { device_id: deviceId } },
  })
  if (error) throw error
  return (data as unknown as { parole_tolte: number }).parole_tolte
}
