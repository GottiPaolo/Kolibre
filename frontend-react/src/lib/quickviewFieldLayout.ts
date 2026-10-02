// Costruttore drag-and-drop per i campi del pannello Quickview — PER
// LIBRERIA (non globale): i metadati che si possono mostrare includono le
// colonne personalizzate, che dipendono dalla libreria attiva tanto quanto
// i libri stessi — un'impostazione unica per tutta l'app non avrebbe senso
// (le colonne di una libreria non esistono nelle altre). Vive quindi nel
// dialogo "Impostazioni libreria" (Settings/LibraryEditDialog.tsx), non più
// in Impostazioni ▸ Aspetto — stesso motivo per cui le colonne personalizzate
// stesse vivono lì. Stesso pattern drag-and-drop nativo di sidebarLayout.ts,
// ma un'unica lista con show/hide per riga (ogni voce esiste sempre, va solo
// mostrata/nascosta e ordinata) — qui però la lista mischia TRE "kind" di
// voce: campi fissi (sempre gli stessi 12), colonne personalizzate (una per
// colonna della libreria) e presenza sui dispositivi registrati (una per
// dispositivo — stessa informazione della colonna "Su: <nome>" già in
// tabella, NON la colonna personalizzata Calibre che capita di avere un nome
// simile: è una confusione già capitata in uso — vedi il campo "kindle" più
// sotto, quello è un kind: 'custom' come qualunque altra colonna). Tutte e
// tre interlacciabili liberamente nell'ordine.
import { useCallback, useRef, useState } from 'react'
import type { CustomColumn } from '@/types/library'
import type { Valori } from './i18n'
import { leggiLocale, scriviLocale } from './memoriaLocale'

export type QuickviewFixedFieldId =
  | 'series' | 'publisher' | 'language' | 'tags' | 'identifiers'
  | 'formats' | 'size' | 'date_added' | 'pubdate' | 'last_modified' | 'uuid' | 'rating'

// Stesse etichette delle colonne della tabella (lib/libraryColumns.ts) tranne
// "size", qui più corta ("Dimensione" invece di "Dimensione (Mb)"): funzione
// e non oggetto costante, come fixedColumnLabels, per ricalcolarsi al
// cambio lingua — vedi l'uso in Settings/LibraryEditDialog.tsx.
export function quickviewFieldDefs(t: (chiave: string, valori?: Valori) => string): Record<QuickviewFixedFieldId, { label: string }> {
  return {
    series: { label: t('library.field.series') },
    publisher: { label: t('library.field.publisher') },
    language: { label: t('library.field.language') },
    tags: { label: t('library.field.tags') },
    identifiers: { label: t('library.field.id') },
    formats: { label: t('library.field.formats') },
    size: { label: t('library.field.sizeShort') },
    date_added: { label: t('library.field.dateAdded') },
    pubdate: { label: t('library.field.published') },
    last_modified: { label: t('library.field.lastModified') },
    uuid: { label: t('library.field.uuid') },
    rating: { label: t('library.field.rating') },
  }
}

const ALL_FIXED_FIELD_IDS: QuickviewFixedFieldId[] = [
  'series', 'publisher', 'language', 'tags', 'identifiers',
  'formats', 'size', 'date_added', 'pubdate', 'last_modified', 'uuid', 'rating',
]

// Sottoinsieme minimo di Device che serve qui (id + name per etichetta e
// lookup) — evita di importare il tipo Device completo (con campi
// dispositivo-specifici che non servono a questo modulo) da types/device.ts.
export interface QuickviewDeviceInfo {
  id: number
  name: string
}

// Union discriminata su `kind` (non un semplice `id: string`) apposta: così
// TypeScript restringe `id` a QuickviewFixedFieldId quando kind === 'fixed'
// nei siti di rendering, senza bisogno di cast manuali.
export type QuickviewFieldEntry =
  | { kind: 'fixed'; id: QuickviewFixedFieldId; visible: boolean }
  | { kind: 'custom'; id: string; visible: boolean }
  | { kind: 'device'; id: string; visible: boolean } // id = String(device.id)

function storageKey(libraryFolder: string): string {
  return `kolibre_quickview_fields_v2:${libraryFolder}`
}

function descriptionStorageKey(libraryFolder: string): string {
  return `kolibre_quickview_description_visible_v2:${libraryFolder}`
}

function defaultQuickviewFieldLayout(
  customColumns: CustomColumn[],
  devices: QuickviewDeviceInfo[]
): QuickviewFieldEntry[] {
  return [
    ...ALL_FIXED_FIELD_IDS.map((id): QuickviewFieldEntry => ({ kind: 'fixed', id, visible: true })),
    ...customColumns.map((c): QuickviewFieldEntry => ({ kind: 'custom', id: c.label, visible: true })),
    ...devices.map((d): QuickviewFieldEntry => ({ kind: 'device', id: String(d.id), visible: true })),
  ]
}

// `libraryFolder` è undefined solo nel breve istante prima che la libreria
// attiva sia nota (vedi LibraryPage.tsx: activeLibrary?.folder_name) — in
// quel caso non c'è nulla da leggere/scrivere, si torna semplicemente
// all'elenco predefinito senza toccare localStorage.
export function loadQuickviewFieldLayout(
  libraryFolder: string | undefined,
  customColumns: CustomColumn[],
  devices: QuickviewDeviceInfo[]
): QuickviewFieldEntry[] {
  if (!libraryFolder) return defaultQuickviewFieldLayout(customColumns, devices)
  const customLabels = new Set(customColumns.map((c) => c.label))
  const deviceIds = new Set(devices.map((d) => String(d.id)))
  try {
    const raw = leggiLocale(storageKey(libraryFolder))
    if (!raw) return defaultQuickviewFieldLayout(customColumns, devices)
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return defaultQuickviewFieldLayout(customColumns, devices)
    const cleaned: QuickviewFieldEntry[] = parsed.filter((e): e is QuickviewFieldEntry => {
      if (!e || typeof e.visible !== 'boolean' || typeof e.id !== 'string') return false
      if (e.kind === 'fixed') return ALL_FIXED_FIELD_IDS.includes(e.id as QuickviewFixedFieldId)
      if (e.kind === 'custom') return customLabels.has(e.id)
      if (e.kind === 'device') return deviceIds.has(e.id)
      return false
    })
    // Un campo/colonna/dispositivo mancante nel salvato (nuovo campo fisso
    // introdotto in un aggiornamento, colonna personalizzata creata dopo
    // l'ultima modifica dell'ordine, o dispositivo registrato dopo) va
    // comunque mostrato, in coda — altrimenti sparirebbe silenziosamente.
    // Una colonna/dispositivo poi RIMOSSO è già stato scartato dal filter
    // sopra (customLabels/deviceIds).
    const seenFixed = new Set(cleaned.filter((e) => e.kind === 'fixed').map((e) => e.id))
    for (const id of ALL_FIXED_FIELD_IDS) {
      if (!seenFixed.has(id)) cleaned.push({ kind: 'fixed', id, visible: true })
    }
    const seenCustom = new Set(cleaned.filter((e) => e.kind === 'custom').map((e) => e.id))
    for (const c of customColumns) {
      if (!seenCustom.has(c.label)) cleaned.push({ kind: 'custom', id: c.label, visible: true })
    }
    const seenDevice = new Set(cleaned.filter((e) => e.kind === 'device').map((e) => e.id))
    for (const d of devices) {
      if (!seenDevice.has(String(d.id))) cleaned.push({ kind: 'device', id: String(d.id), visible: true })
    }
    return cleaned.length > 0 ? cleaned : defaultQuickviewFieldLayout(customColumns, devices)
  } catch {
    return defaultQuickviewFieldLayout(customColumns, devices)
  }
}

function persistQuickviewFieldLayout(libraryFolder: string, entries: QuickviewFieldEntry[]): void {
  scriviLocale(storageKey(libraryFolder), JSON.stringify(entries))
}

export function loadQuickviewDescriptionVisible(libraryFolder: string | undefined): boolean {
  if (!libraryFolder) return true
  return leggiLocale(descriptionStorageKey(libraryFolder)) !== 'false'
}

function persistQuickviewDescriptionVisible(libraryFolder: string, visible: boolean): void {
  scriviLocale(descriptionStorageKey(libraryFolder), String(visible))
}

export function useQuickviewFieldLayoutBuilder(
  libraryFolder: string,
  customColumns: CustomColumn[],
  devices: QuickviewDeviceInfo[]
) {
  const [layout, setLayout] = useState<QuickviewFieldEntry[]>(() =>
    loadQuickviewFieldLayout(libraryFolder, customColumns, devices)
  )
  const [descriptionVisible, setDescriptionVisible] = useState<boolean>(() =>
    loadQuickviewDescriptionVisible(libraryFolder)
  )
  const draggedIndex = useRef<number | null>(null)

  const commit = useCallback(
    (next: QuickviewFieldEntry[]) => {
      setLayout(next)
      persistQuickviewFieldLayout(libraryFolder, next)
    },
    [libraryFolder]
  )

  const dragStart = useCallback((index: number) => {
    draggedIndex.current = index
  }, [])

  const dropTo = useCallback(
    (targetIndex: number) => {
      const from = draggedIndex.current
      draggedIndex.current = null
      if (from === null || from === targetIndex) return
      const next = layout.slice()
      const [moved] = next.splice(from, 1)
      const adjustedTarget = from < targetIndex ? targetIndex - 1 : targetIndex
      next.splice(adjustedTarget, 0, moved)
      commit(next)
    },
    [layout, commit]
  )

  const toggleVisible = useCallback(
    (index: number) => {
      const next = layout.slice()
      next[index] = { ...next[index], visible: !next[index].visible }
      commit(next)
    },
    [layout, commit]
  )

  const toggleDescriptionVisible = useCallback(() => {
    setDescriptionVisible((prev) => {
      const next = !prev
      persistQuickviewDescriptionVisible(libraryFolder, next)
      return next
    })
  }, [libraryFolder])

  const reset = useCallback(() => {
    commit(defaultQuickviewFieldLayout(customColumns, devices))
    setDescriptionVisible(true)
    persistQuickviewDescriptionVisible(libraryFolder, true)
  }, [commit, customColumns, devices, libraryFolder])

  return { layout, descriptionVisible, dragStart, dropTo, toggleVisible, toggleDescriptionVisible, reset }
}
