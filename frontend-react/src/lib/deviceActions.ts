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
import { scaricaIndirizzo } from './scarica'
import type { DeviceNudo, EsitoAzioneDaRivedere } from '@/types/device'

// Questi endpoint accettano un dict libero lato backend (nessun modello
// Pydantic sul corpo della richiesta — la **risposta** invece la dichiarano
// dal 05/11/2026) e rispondono con HTTPException(detail=...) sugli errori
// applicativi (404, 400): stesso estrattore già introdotto per l'Ingest.
// La duplicazione citata qui sopra è finita: le tre copie dell'estrattore
// delegano tutte a lib/messaggiErrore.ts, dove sta anche la regola sui
// permessi — "non hai i permessi" invece di "errore" (28/09/2026).
export function deviceErrorDetail(err: unknown, fallback: string, stato?: number): string {
  return messaggioErrore(err, fallback, stato)
}

export async function registerDevice(name: string, model: string): Promise<DeviceNudo> {
  const { data, error } = await api.POST('/api/devices/register', {
    body: { name, model },
  })
  if (error) throw error
  return data
}

export interface DeviceUpdatePayload {
  name?: string
  model?: string
  folder_layout?: string
  write_folder_cover?: boolean
  delete_policy?: string
}

// `DeviceNudo` e non la riga dell'elenco: questo indirizzo risponde la riga
// del database, senza libri ne' patch ne' coda. Chi chiama non lo legge — e
// per questo la bugia di prima era invisibile.
export async function updateDevice(deviceId: number, payload: DeviceUpdatePayload): Promise<DeviceNudo> {
  const { data, error } = await api.PUT('/api/devices/{device_id}', {
    params: { path: { device_id: deviceId } },
    body: payload,
  })
  if (error) throw error
  return data
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

// «Manda un dizionario a questo lettore». Non è un invio ma una coda: un
// server non può raggiungere un e-reader, è il lettore che si fa vivo quando
// è accesso e ha la rete (vedi accoda_dizionario_per_dispositivo). Il
// dizionario parte alla sua prima sincronizzazione completa.
export async function accodaDizionarioPerDispositivo(deviceId: number, lang: string): Promise<void> {
  const { error } = await api.POST('/api/devices/{device_id}/dictionaries', {
    params: { path: { device_id: deviceId } },
    body: { lang },
  })
  if (error) throw error
}

// Toglie dalla coda un dizionario non ancora partito. Non disinstalla niente
// dal lettore: quello che è già là resta là.
export async function annullaDizionarioPerDispositivo(deviceId: number, lang: string): Promise<void> {
  const { error } = await api.DELETE('/api/devices/{device_id}/dictionaries/{lang}', {
    params: { path: { device_id: deviceId, lang } },
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
) {
  const { data, error } = await api.POST('/api/devices/{device_id}/books/{book_row_id}/pair', {
    params: { path: { device_id: deviceId, book_row_id: rowId } },
    body: payload,
  })
  if (error) throw error
  return data
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
  // Le **due forme** che questo indirizzo risponde: accodare un'azione
  // dice `pending_action`, accoppiare dice quante annotazioni orfane ha
  // spostato. Lo schema le dichiara come unione, e chi chiama guarda il
  // campo che lo riguarda — era lo stesso controllo, con un tipo scritto a
  // mano al posto di quello del server.
  payload: QueueFlaggedActionPayload
) {
  const { data, error } = await api.POST('/api/devices/{device_id}/flagged-books/{flagged_id}/action', {
    params: { path: { device_id: deviceId, flagged_id: flaggedId } },
    body: payload,
  })
  if (error) throw error
  return data
}

/**
 * Quante annotazioni orfane ha spostato un'azione su un file da rivedere.
 *
 * E' il controllo che il codice faceva già (`data.migrated_highlights || 0`),
 * con la differenza che adesso il compilatore sa che quel campo esiste in
 * **una sola** delle due forme che l'indirizzo risponde: accodare non sposta
 * niente, perché non ha ancora fatto niente. Prima lo nascondeva
 * un'asserzione scritta a mano.
 *
 * **Si guarda il tipo del valore e non la presenza della chiave.** Un
 * `'migrated_highlights' in esito` non restringe niente qui: questi tipi
 * portano un indice `[key: string]: unknown` (lo genera `extra="allow"` nel
 * modello Pydantic, che è quello che permette a un campo nuovo del server di
 * arrivare senza rompere il client), e con quell'indice la chiave *può*
 * esistere su entrambe le forme — quindi il compilatore dà `unknown`.
 * Misurato, non temuto: è lo stesso indice che il 05/11/2026 aveva fatto
 * cancellare un tipo intero da un `Omit`. Un `typeof` invece è un controllo
 * vero anche a tempo di esecuzione, ed è l'unico onesto quando il campo
 * potrebbe portare qualunque cosa.
 */
export function noteSpostate(esito: EsitoAzioneDaRivedere): number {
  const quante = esito.migrated_highlights
  return typeof quante === 'number' ? quante : 0
}

export async function bulkDeleteFlaggedBooks(deviceId: number, ids: number[]): Promise<void> {
  const { error } = await api.POST('/api/devices/{device_id}/flagged-books/bulk-action', {
    params: { path: { device_id: deviceId } },
    body: { action: 'delete', ids },
  })
  if (error) throw error
}

// Scarica lo zip dei backup del dispositivo. Non il blob-download "anti
// auto-estrazione Safari" usato per i plugin: qui il file è già un .zip vero e
// proprio destinato a essere aperto/estratto dall'utente, non un asset da
// servire "as-is". download_device_backups usa get_current_user_flexible
// (header o ?token=), quindi serve il token corrente anche qui.
// Era un window.open, che lasciava una finestra vuota aperta (vedi lib/scarica.ts).
export async function downloadDeviceBackups(deviceId: number): Promise<void> {
  const token = await ensureAuthToken()
  scaricaIndirizzo(withBackendUrl(`/api/devices/${deviceId}/backups/download?token=${token || ''}`))
}

/** Dimentica il vocabolario di UN dispositivo, tenendo tutto il resto. */
export async function dimenticaVocabolario(deviceId: number): Promise<number> {
  const { data, error } = await api.DELETE('/api/devices/{device_id}/vocabulary', {
    params: { path: { device_id: deviceId } },
  })
  if (error) throw error
  return data.parole_tolte
}
