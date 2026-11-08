// Registro comandi + helper tastiera per la tab "Sistema" di Impostazioni
// (Fase 8) — porting della UI di gestione scorciatoie del Vue esistente
// (frontend/src/App.vue, COMMAND_REGISTRY e dintorni, righe ~9317-9543).
//
// Decisione di scope (vedi report finale): questo file porta SOLO il
// registro dati (id/label/defaultKeys) e le utility di formattazione/
// normalizzazione tasto — NON il dispatcher globale che nel Vue intercetta
// ogni keydown ed esegue `cmd.run()`. Il Vue è una SPA a stato singolo (un
// solo `activePage` ref, un solo `selectedBook` ref: ogni comando chiama
// direttamente funzioni locali dello stesso file); React invece è instradato
// per pagina (react-router) e la maggior parte di queste azioni (editMetadata,
// editTOC, requestSendToDevice, navigateTableRow...) vive oggi come stato
// LOCALE di pagine già migrate (Library/BookDetail), non come funzioni
// globali richiamabili da qui. Wire-are l'esecuzione reale richiederebbe un
// listener globale in components/Layout.tsx (file che non tocco, di
// competenza di un passo successivo) e toccare più pagine già migrate per
// esporre le azioni — fuori scope per "Impostazioni". Questa tab quindi
// permette di consultare/cercare/personalizzare/esportare i binding e li
// persiste in un formato pronto per un futuro dispatcher, ma nessun comando
// è ancora davvero eseguibile premendo i tasti nell'app.
import type { Valori } from './i18n'
import { leggiLocale, scriviLocale } from './memoriaLocale'

export interface ShortcutCommand {
  id: string
  defaultKeys: string[]
}

// Stessi id/etichette/tasti di default del COMMAND_REGISTRY Vue (dove
// l'azione corrispondente esiste concettualmente in React) — utile perché
// un file kolibre-shortcuts.json esportato da un frontend resta interpretabile
// dall'altro (gli id sconosciuti vengono ignorati in silenzio all'importazione,
// vedi importShortcuts sotto, quindi è comunque sicuro anche se in futuro le
// liste divergono).
export const COMMAND_REGISTRY: ShortcutCommand[] = [
  { id: 'focus-search', defaultKeys: ['/'] },
  { id: 'close-overlays', defaultKeys: ['escape'] },
  { id: 'read-book-web', defaultKeys: ['v'] },
  { id: 'edit-metadata', defaultKeys: ['e'] },
  { id: 'edit-toc', defaultKeys: ['t'] },
  { id: 'send-to-default-device', defaultKeys: ['d'] },
  { id: 'download-metadata-covers', defaultKeys: ['mod+d'] },
  { id: 'delete-book', defaultKeys: ['delete', 'backspace'] },
  { id: 'filter-same-author', defaultKeys: ['alt+a'] },
  { id: 'library-nav-down', defaultKeys: ['arrowdown'] },
  { id: 'library-nav-up', defaultKeys: ['arrowup'] },
]

// Stessa chiave del Vue esistente (kolibre_shortcut_overrides) — mappa
// generica id-comando -> lista di combinazioni, indipendente dal frontend
// che la scrive, quindi non c'è motivo di divergere qui (a differenza di
// sidebarLayout.ts, dove il vocabolario di id pagina è invece cambiato).
const STORAGE_KEY = 'kolibre_shortcut_overrides'

export type ShortcutOverrides = Record<string, string[]>

export function loadShortcutOverrides(): ShortcutOverrides {
  try {
    const raw = leggiLocale(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? (parsed as ShortcutOverrides) : {}
  } catch {
    return {}
  }
}

export function persistShortcutOverrides(overrides: ShortcutOverrides): void {
  scriviLocale(STORAGE_KEY, JSON.stringify(overrides))
}

export function commandBindings(overrides: ShortcutOverrides, cmd: ShortcutCommand): string[] {
  return overrides[cmd.id] ?? cmd.defaultKeys
}

// L'etichetta mostrata all'utente, tradotta — vedi il campo `label` sopra,
// che resta inalterato (in italiano) perché è solo ciò che importShortcuts/
// computeConflicts eccetera trattano come dato interno quando serve una
// stringa di fallback; non si legge più direttamente per il rendering o la
// ricerca (vedi SystemTab.tsx), così la UI resta coerente col cambio lingua
// senza dover riscrivere l'ordine/id del registro.
export function commandLabel(id: string, t: (chiave: string, valori?: Valori) => string): string {
  switch (id) {
    case 'focus-search':
      return t('settings.shortcut.focusSearch')
    case 'close-overlays':
      return t('settings.shortcut.closeOverlays')
    case 'read-book-web':
      return t('settings.shortcut.readBookWeb')
    case 'edit-metadata':
      return t('settings.shortcut.editMetadata')
    case 'edit-toc':
      return t('settings.shortcut.editToc')
    case 'send-to-default-device':
      return t('settings.shortcut.sendToDefaultDevice')
    case 'download-metadata-covers':
      return t('settings.shortcut.downloadMetadataCovers')
    case 'delete-book':
      return t('settings.shortcut.deleteBook')
    case 'filter-same-author':
      return t('settings.shortcut.filterSameAuthor')
    case 'library-nav-down':
      return t('settings.shortcut.libraryNavDown')
    case 'library-nav-up':
      return t('settings.shortcut.libraryNavUp')
    default:
      return id
  }
}

export function commandHasOverride(overrides: ShortcutOverrides, cmd: ShortcutCommand): boolean {
  if (!Object.prototype.hasOwnProperty.call(overrides, cmd.id)) return false
  return JSON.stringify(overrides[cmd.id].slice().sort()) !== JSON.stringify(cmd.defaultKeys.slice().sort())
}

// { commandId: Set(combo in conflitto) } — un binding condiviso da >1
// comando viene segnalato ma non bloccato, stesso approccio "warn but
// allow" del Vue esistente.
export function computeConflicts(overrides: ShortcutOverrides): Record<string, Set<string>> {
  const byCombo: Record<string, string[]> = {}
  for (const cmd of COMMAND_REGISTRY) {
    for (const combo of commandBindings(overrides, cmd)) {
      ;(byCombo[combo] ??= []).push(cmd.id)
    }
  }
  const byCommand: Record<string, Set<string>> = {}
  for (const [combo, ids] of Object.entries(byCombo)) {
    if (ids.length < 2) continue
    for (const id of ids) {
      ;(byCommand[id] ??= new Set()).add(combo)
    }
  }
  return byCommand
}

const IS_MAC = navigator.platform.toUpperCase().includes('MAC')

// "mod" è un concetto cross-platform unico (Cmd su Mac, Ctrl altrove) —
// stessa semplificazione di Obsidian, un solo default per binding invece di
// due paralleli Windows/Mac da mantenere.
export function normalizeKeyCombo(e: KeyboardEvent): string | null {
  const parts: string[] = []
  if (e.metaKey || e.ctrlKey) parts.push('mod')
  if (e.altKey) parts.push('alt')
  if (e.shiftKey) parts.push('shift')
  let key = e.key.toLowerCase()
  if (['control', 'meta', 'alt', 'shift'].includes(key)) return null // un modificatore da solo non è una combinazione
  // Con Alt premuto, macOS compone e.key nel carattere del layer Option
  // (Alt+A → "å", Alt+N → "˜", ...): un binding "alt+a" non corrisponderebbe
  // mai a quanto riportato dall'evento. e.code identifica il tasto FISICO
  // ("KeyA"/"Digit1") indipendentemente dai modificatori — per lettere/cifre
  // è esattamente l'identità su cui vogliamo chiavare il binding.
  if (e.altKey && /^(Key[A-Z]|Digit[0-9])$/.test(e.code || '')) {
    key = e.code.slice(e.code.startsWith('Key') ? 3 : 5).toLowerCase()
  }
  parts.push(key === ' ' ? 'space' : key)
  return parts.join('+')
}

// Funzione e non oggetto costante: deve ricalcolarsi al cambio lingua, come
// fixedColumnLabels in lib/libraryColumns.ts. I simboli (⌘ ⌥ ⇧ ↑ ↓ ← → ⌫ ↵)
// non passano per t(): sono grafici, non parole in una lingua.
function keyDisplayNames(t: (chiave: string, valori?: Valori) => string): Record<string, string> {
  return {
    mod: IS_MAC ? '⌘' : t('settings.shortcut.key.ctrl'),
    alt: IS_MAC ? '⌥' : t('settings.shortcut.key.alt'),
    shift: '⇧',
    arrowup: '↑',
    arrowdown: '↓',
    arrowleft: '←',
    arrowright: '→',
    delete: t('settings.shortcut.key.delete'),
    backspace: '⌫',
    escape: t('settings.shortcut.key.escape'),
    enter: '↵',
    space: t('settings.shortcut.key.space'),
  }
}

export function formatKeyCombo(combo: string, t: (chiave: string, valori?: Valori) => string): string {
  const names = keyDisplayNames(t)
  return combo
    .split('+')
    .map((p) => names[p] || p.toUpperCase())
    .join(IS_MAC ? '' : '+')
}

export function exportShortcuts(overrides: ShortcutOverrides): void {
  const blob = new Blob([JSON.stringify(overrides, null, 2)], { type: 'application/json' })
  const objectUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objectUrl
  a.download = 'kolibre-shortcuts.json'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(objectUrl), 2000)
}

export async function importShortcutsFromFile(file: File): Promise<ShortcutOverrides> {
  const parsed = JSON.parse(await file.text())
  const validIds = new Set(COMMAND_REGISTRY.map((c) => c.id))
  return Object.fromEntries(
    Object.entries(parsed).filter(([id, keys]) => validIds.has(id) && Array.isArray(keys))
  ) as ShortcutOverrides
}
