// Costruttore drag-and-drop della sidebar per la tab "Aspetto" di
// Impostazioni (Fase 8) — porting del concetto (non del codice, che in
// frontend/src/App.vue è legato a mutation-in-place di ref Vue) del builder
// sidebarLayout/SIDEBAR_PAGE_DEFS/onSidebarBuilderDragStart/
// DropToStructure/DropToAvailable (righe ~10157-10306 di App.vue).
//
// Elenco voci gestibili: NON è lo stesso di quello Vue (tags/authors/series/
// annotations/devices/statistics/ingest/tools, 8 voci) perché la sidebar
// React reale (components/Layout.tsx: NAV_ITEMS/NAV_ITEMS_DEVICES/
// NAV_ITEMS_BOTTOM, file che NON tocco) oggi ha solo 6 voci gestibili:
// - "Tag" non esiste affatto come voce/pagina in React (nessuna route/nav-item).
// - "Operazioni di Massa" (tools) non è una voce di sidebar separata in
//   React: è una tab dentro /importa (vedi pages/Ingest/ImportPage.tsx),
//   quindi "ingest" la rappresenta già entrambe.
// Libreria (sempre prima) e Impostazioni (sempre ultima) restano fisse e
// NON fanno parte di questo builder, come nel Vue.
import { useCallback, useMemo, useRef, useState } from 'react'
import { Users, ListTree, Highlighter, Smartphone, BarChart3, Upload, Languages, ClipboardCheck, Tags, type LucideIcon } from 'lucide-react'
import { leggiLocale, scriviLocale } from './memoriaLocale'

export type SidebarPageId =
  | 'authors' | 'series' | 'annotations' | 'devices' | 'statistics' | 'ingest' | 'vocabulary'
  | 'interventions' | 'entities'

export interface SidebarPageDef {
  /** Chiave di catalogo, non testo: la barra laterale deve cambiare lingua
   *  insieme al resto, e questa mappa è una costante di modulo. */
  labelKey: string
  icon: LucideIcon
}

export const SIDEBAR_PAGE_DEFS: Record<SidebarPageId, SidebarPageDef> = {
  authors: { labelKey: 'nav.authors', icon: Users },
  series: { labelKey: 'nav.series', icon: ListTree },
  entities: { labelKey: 'nav.entities', icon: Tags },
  annotations: { labelKey: 'nav.annotations', icon: Highlighter },
  devices: { labelKey: 'nav.devices', icon: Smartphone },
  statistics: { labelKey: 'nav.statistics', icon: BarChart3 },
  ingest: { labelKey: 'nav.ingest', icon: Upload },
  vocabulary: { labelKey: 'nav.vocabulary', icon: Languages },
  interventions: { labelKey: 'nav.interventions', icon: ClipboardCheck },
}

const ALL_PAGE_IDS = Object.keys(SIDEBAR_PAGE_DEFS) as SidebarPageId[]

// Forma persistita — un array ordinato di voci "pagina" o "separatore".
// Deliberatamente SENZA una `key` (quella è un dettaglio di render/drag,
// rigenerato ad ogni load, mai salvato — stessa scelta del Vue esistente)
// e SENZA un flag "hidden": una pagina è visibile sse è presente
// nell'array, esattamente come per sidebarBuilderAvailable nel Vue.
export type SidebarLayoutEntry = { type: 'page'; id: SidebarPageId } | { type: 'separator' }

// Chiave localStorage dedicata a React, indipendente da quella del Vue
// esistente (che è 'kolibre_sidebar_layout_v2', con un vocabolario di id
// diverso — vedi sopra) — deliberatamente NON condivisa, per evitare che un
// valore salvato da un frontend venga letto (e frainteso) dall'altro.
const STORAGE_KEY = 'kolibre_sidebar_layout_v1'

// Rispecchia l'attuale raggruppamento visivo di Layout.tsx (NAV_ITEMS /
// sezione "Dispositivi" / NAV_ITEMS_BOTTOM) usando due separatori — un
// punto di partenza ragionevole, non un contratto: quando Layout.tsx verrà
// aggiornato per leggere davvero questo layout, è lecito trattare i
// separatori come semplici divisori invece che come intestazioni di gruppo.
function defaultSidebarLayout(): SidebarLayoutEntry[] {
  return [
    { type: 'page', id: 'authors' },
    { type: 'page', id: 'series' },
    { type: 'page', id: 'entities' },
    { type: 'page', id: 'annotations' },
    { type: 'page', id: 'vocabulary' },
    { type: 'separator' },
    { type: 'page', id: 'devices' },
    { type: 'page', id: 'statistics' },
    { type: 'page', id: 'interventions' },
    { type: 'separator' },
    { type: 'page', id: 'ingest' },
  ]
}

// Le voci che questo browser ha gia' visto almeno una volta.
//
// Serve perche' "una pagina e' visibile sse e' presente nell'array" ha un
// buco: una pagina NUOVA non e' presente in nessun layout salvato prima che
// esistesse, quindi nascerebbe invisibile proprio a chi usa gia' il
// programma — e non c'e' modo di distinguerla da una che l'utente aveva
// tolto apposta. Tenendo da parte quali id gli sono gia' stati offerti, la
// differenza si vede: gli id mai visti si aggiungono in fondo una volta
// sola, e da li' in poi toglierli e' una scelta che resta.
const KNOWN_KEY = 'kolibre_sidebar_pagine_note_v1'

function leggiNote(): SidebarPageId[] {
  try {
    const raw = leggiLocale(KNOWN_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((id) => ALL_PAGE_IDS.includes(id)) : []
  } catch {
    return []
  }
}

function scriviNote(): void {
  try {
    scriviLocale(KNOWN_KEY, JSON.stringify(ALL_PAGE_IDS))
  } catch {
    // Non poter ricordare non deve impedire di mostrare la pagina.
  }
}

export function loadSidebarLayout(): SidebarLayoutEntry[] {
  try {
    const raw = leggiLocale(STORAGE_KEY)
    if (!raw) {
      scriviNote()
      return defaultSidebarLayout()
    }
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return defaultSidebarLayout()
    const cleaned: SidebarLayoutEntry[] = parsed.filter(
      (e): e is SidebarLayoutEntry =>
        e && (e.type === 'separator' || (e.type === 'page' && ALL_PAGE_IDS.includes(e.id)))
    )
    if (cleaned.length === 0) return defaultSidebarLayout()

    // Chi aveva gia' un layout salvato prima che una pagina esistesse se la
    // vede comparire in fondo, una volta sola.
    const note = leggiNote()
    const presenti = new Set(cleaned.filter((e) => e.type === 'page').map((e) => e.id))
    const nuove = ALL_PAGE_IDS.filter((id) => !note.includes(id) && !presenti.has(id))
    scriviNote()
    return nuove.length > 0
      ? [...cleaned, ...nuove.map((id) => ({ type: 'page' as const, id }))]
      : cleaned
  } catch {
    return defaultSidebarLayout()
  }
}

function persistSidebarLayout(entries: SidebarLayoutEntry[]): void {
  scriviLocale(STORAGE_KEY, JSON.stringify(entries))
}

type DragPayload = { from: 'available'; id: SidebarPageId } | { from: 'structure'; index: number }

// Hook di stato+azioni per il builder — la UI (AspectTab.tsx) resta un
// componente di sola presentazione. Persiste su ogni modifica (le modifiche
// "si applicano subito", stesso comportamento del Vue esistente: nessun
// pulsante "Salva" separato per questa sezione).
export function useSidebarLayoutBuilder() {
  const [layout, setLayout] = useState<SidebarLayoutEntry[]>(() => loadSidebarLayout())
  const dragged = useRef<DragPayload | null>(null)

  const commit = useCallback((next: SidebarLayoutEntry[]) => {
    setLayout(next)
    persistSidebarLayout(next)
  }, [])

  const available = useMemo(() => {
    const used = new Set(layout.filter((e) => e.type === 'page').map((e) => (e as { id: SidebarPageId }).id))
    return ALL_PAGE_IDS.filter((id) => !used.has(id))
  }, [layout])

  const dragStart = useCallback((payload: DragPayload) => {
    dragged.current = payload
  }, [])

  // targetIndex = posizione di inserimento nell'array ATTUALE, prima di
  // rimuovere l'elemento trascinato — se si sposta un elemento dentro la
  // struttura stessa, rimuoverlo per primo può far scalare l'indice di
  // destinazione, corretto qui sotto (stessa logica di onSidebarBuilderDropToStructure nel Vue).
  const dropToStructure = useCallback(
    (targetIndex: number) => {
      const payload = dragged.current
      dragged.current = null
      if (!payload) return
      if (payload.from === 'available') {
        const next = layout.slice()
        next.splice(targetIndex, 0, { type: 'page', id: payload.id })
        commit(next)
      } else {
        const next = layout.slice()
        const [moved] = next.splice(payload.index, 1)
        const adjustedTarget = payload.index < targetIndex ? targetIndex - 1 : targetIndex
        next.splice(adjustedTarget, 0, moved)
        commit(next)
      }
    },
    [layout, commit]
  )

  const dropToAvailable = useCallback(() => {
    const payload = dragged.current
    dragged.current = null
    if (!payload || payload.from !== 'structure') return
    const next = layout.slice()
    next.splice(payload.index, 1)
    commit(next)
  }, [layout, commit])

  const addSeparator = useCallback(() => {
    commit([...layout, { type: 'separator' }])
  }, [layout, commit])

  const removeEntry = useCallback(
    (index: number) => {
      const next = layout.slice()
      next.splice(index, 1)
      commit(next)
    },
    [layout, commit]
  )

  const reset = useCallback(() => {
    commit(defaultSidebarLayout())
  }, [commit])

  return { layout, available, dragStart, dropToStructure, dropToAvailable, addSeparator, removeEntry, reset }
}
