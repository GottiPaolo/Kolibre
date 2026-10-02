// Helper di formattazione/etichette per la Fase 5 (Dispositivi) — porting
// 1:1 delle mappe status→label del Vue esistente (frontend/src/App.vue:
// DEVICE_BOOK_STATUS_INFO, DELETE_POLICY_LABELS, SYNC_OUTCOME_INFO,
// flaggedReasonLabel, deviceBookLibraryLabel, relativeTimeFrom/
// formatDateTime/_parseUtcDate). File separato da format.ts (condiviso con
// altre pagine, non va toccato) per evitare conflitti di merge.
import { formatDate } from './format'
import type { DeviceFlaggedBook } from '@/types/device'
import type { Library } from '@/types/library'
import type { Valori } from './i18n'

type Traduci = (chiave: string, valori?: Valori) => string

// I "toni" mappano 1:1 le classi .pill-sage/.pill-gold/.pill-accent/
// .pill-muted del Vue esistente sui token del design system React
// (--positive/--warning/--destructive/muted-foreground) — vedi
// frontend-react/src/index.css. pill-accent (errore/rifiutato) usa qui
// --destructive invece di riusare il colore "accent" di marca come faceva
// il Vue: il design system React ha già un token semantico dedicato agli
// errori, più corretto di quello che il Vue doveva riciclare.
export type PillTone = 'positive' | 'warning' | 'destructive' | 'muted'

// Funzione e non un oggetto costante: deve ricalcolarsi al cambio lingua,
// stesso motivo di fixedColumnLabels in libraryColumns.ts. Le CHIAVI (status
// server-driven: 'synced', 'pending_send'…) restano invariate: sono quelle
// che arrivano dal backend, solo l'etichetta mostrata è tradotta.
function deviceBookStatusInfoMap(t: Traduci): Record<string, { label: string; tone: PillTone }> {
  return {
    synced: { label: t('devices.status.synced'), tone: 'positive' },
    pending_send: { label: t('devices.status.pendingSend'), tone: 'warning' },
    send_failed: { label: t('devices.status.sendFailed'), tone: 'destructive' },
    pending_delete: { label: t('devices.status.pendingDelete'), tone: 'warning' },
    delete_declined: { label: t('devices.status.deleteDeclined'), tone: 'destructive' },
    removed_by_device: { label: t('devices.status.removedByDevice'), tone: 'muted' },
  }
}

export function deviceBookStatusInfo(status: string | null | undefined, t: Traduci): { label: string; tone: PillTone } {
  const info = deviceBookStatusInfoMap(t)
  return (status && info[status]) || { label: status || '—', tone: 'muted' }
}

function deletePolicyLabelsMap(t: Traduci): Record<string, string> {
  return { auto: t('devices.deletePolicy.auto'), ask: t('devices.deletePolicy.ask'), never: t('devices.deletePolicy.never') }
}
export function deletePolicyLabel(policy: string | null | undefined, t: Traduci): string {
  const labels = deletePolicyLabelsMap(t)
  return (policy && labels[policy]) || policy || '—'
}

function syncOutcomeInfoMap(t: Traduci): Record<string, { label: string; tone: PillTone }> {
  return {
    ok: { label: t('devices.syncOutcome.ok'), tone: 'positive' },
    partial: { label: t('devices.syncOutcome.partial'), tone: 'warning' },
    error: { label: t('devices.syncOutcome.error'), tone: 'destructive' },
    open: { label: t('devices.syncOutcome.open'), tone: 'muted' },
    abandoned: { label: t('devices.syncOutcome.abandoned'), tone: 'muted' },
  }
}
export function syncOutcomeInfo(outcome: string | null | undefined, t: Traduci): { label: string; tone: PillTone } {
  const info = syncOutcomeInfoMap(t)
  return (outcome && info[outcome]) || { label: outcome || '—', tone: 'muted' }
}

// Spiega PERCHÉ una riga 'flagged_started' non è stata toccata in automatico.
export function flaggedReasonLabel(f: DeviceFlaggedBook, t: Traduci): string {
  if (f.match_status === 'no_candidate') return t('devices.flagged.reason.noCandidate')
  const parts: string[] = []
  if (typeof f.local_percent_read === 'number' && f.local_percent_read > 0) {
    parts.push(t('devices.flagged.reason.percentRead', { percent: Math.round(f.local_percent_read * 100) }))
  }
  if (f.local_highlights_count) {
    parts.push(t('devices.flagged.reason.notesCount', { count: f.local_highlights_count, n: f.local_highlights_count }))
  }
  return parts.length
    ? t('devices.flagged.reason.alreadyStarted', { details: parts.join(', ') })
    : t('devices.flagged.reason.alreadyOpened')
}

// Nome libreria a partire dallo slug (folder_name) salvato su DeviceBook.library
// — fallback allo slug grezzo se non corrisponde a nessuna libreria nota
// (es. libreria eliminata dopo l'invio del libro al dispositivo).
export function deviceBookLibraryLabel(libraries: Library[], slug: string | null | undefined): string {
  const lib = libraries.find((l) => l.folder_name === slug)
  return lib ? lib.name : slug || '—'
}

// I timestamp del backend sono UTC naive ("YYYY-MM-DD HH:MM:SS" o ISO senza
// timezone) — forziamo la Z perché Date li interpreti come UTC, non locali
// (stesso fix di _parseUtcDate nel Vue esistente, altrimenti "visto X min fa"
// sarebbe sistematicamente sbagliato dell'offset del fuso orario locale).
function parseUtcDate(s: string | null | undefined): Date | null {
  if (!s) return null
  let iso = s.includes('T') ? s : s.replace(' ', 'T')
  if (!/(Z|[+-]\d\d:?\d\d)$/.test(iso)) iso += 'Z'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? null : d
}

export function relativeTimeFrom(dateStr: string | null | undefined, t: Traduci): string {
  const d = parseUtcDate(dateStr)
  if (!d) return ''
  const diffSec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000))
  if (diffSec < 60) return t('devices.time.now')
  const min = Math.floor(diffSec / 60)
  if (min < 60) return t('devices.time.minutesAgo', { min })
  const hours = Math.floor(min / 60)
  if (hours < 24) return t('devices.time.hoursAgo', { hours })
  return t('devices.time.daysAgo', { days: Math.floor(hours / 24) })
}

export function formatDateTime(dateStr: string | null | undefined): string {
  const d = parseUtcDate(dateStr)
  if (!d) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  const datePart = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  return `${formatDate(datePart)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function pickPreferredDeviceFormat(formats: string[]): string | undefined {
  return formats.includes('EPUB') ? 'EPUB' : formats[0]
}

// Stato "binario" per la colonna dinamica per-dispositivo della tabella
// Libreria ("Su: <nome>") e per decidere Invia/Rimuovi nel menu contestuale
// libro — porting del checkmark/clessidra del Vue esistente (bookIsOnDevice/
// bookIsQueuedForDevice), adattato ai nostri stati reali di DeviceBookRow.status
// (il Vue aveva una coda separata, qui è già tutto in un'unica riga con status).
// 'pending_delete' tenuto distinto da 'on': serve un'icona apposita per un
// libro che è sul dispositivo ma in attesa di essere rimosso, complementare
// della clessidra — prima veniva mostrato con la stessa spunta di un libro
// sincronizzato normale, perdendo l'informazione che sta per sparire.
export type DeviceBookColumnState = 'on' | 'queued' | 'pending_delete' | 'off'
export function deviceBookColumnState(status: string): DeviceBookColumnState {
  if (status === 'pending_delete') return 'pending_delete'
  if (status === 'synced' || status === 'delete_declined') return 'on'
  if (status === 'pending_send' || status === 'send_failed') return 'queued'
  return 'off' // removed_by_device
}
