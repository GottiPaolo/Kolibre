// Porting delle operazioni sull'albero TOC da frontend/src/App.vue. Il
// modello dati è deliberatamente lo stesso: un array FLAT con un campo
// `level` (profondità 0-based) per riga — non un vero albero nested, stessa
// convenzione usata lato server in toc_editor.py::set_epub_toc. `_key` è un
// id stabile lato client (gli indici array cambiano ad ogni insert/remove/
// riordino, quindi selezione/collapse non possono usarlo).
export interface TocRow {
  title: string
  dest: string
  level: number
  _key: number
  valid?: boolean
}

export function subtreeEnd(items: TocRow[], idx: number): number {
  const level = items[idx].level
  let end = idx + 1
  while (end < items.length && items[end].level > level) end++
  return end
}

export function findIndexByKey(items: TocRow[], key: number): number {
  return items.findIndex((it) => it._key === key)
}

export function hasChildrenAt(items: TocRow[], idx: number): boolean {
  return idx + 1 < items.length && items[idx + 1].level > items[idx].level
}

function findPrevSiblingStart(items: TocRow[], idx: number): number {
  const level = items[idx].level
  let i = idx - 1
  while (i >= 0 && items[i].level > level) i--
  return i >= 0 && items[i].level === level ? i : -1
}

export function moveSubtreeUp(items: TocRow[], key: number): TocRow[] {
  const idx = findIndexByKey(items, key)
  if (idx === -1) return items
  const end = subtreeEnd(items, idx)
  const prevStart = findPrevSiblingStart(items, idx)
  if (prevStart === -1) return items
  return [...items.slice(0, prevStart), ...items.slice(idx, end), ...items.slice(prevStart, idx), ...items.slice(end)]
}

export function moveSubtreeDown(items: TocRow[], key: number): TocRow[] {
  const idx = findIndexByKey(items, key)
  if (idx === -1) return items
  const level = items[idx].level
  const end = subtreeEnd(items, idx)
  if (end >= items.length || items[end].level !== level) return items
  const nextEnd = subtreeEnd(items, end)
  return [...items.slice(0, idx), ...items.slice(end, nextEnd), ...items.slice(idx, end), ...items.slice(nextEnd)]
}

// Indent/outdent spostano l'intero sottoalbero — i figli restano figli.
export function indentSubtree(items: TocRow[], key: number): TocRow[] {
  const idx = findIndexByKey(items, key)
  if (idx <= 0) return items
  const end = subtreeEnd(items, idx)
  return items.map((it, i) => (i >= idx && i < end ? { ...it, level: it.level + 1 } : it))
}

export function outdentSubtree(items: TocRow[], key: number): TocRow[] {
  const idx = findIndexByKey(items, key)
  if (idx === -1 || items[idx].level === 0) return items
  const end = subtreeEnd(items, idx)
  return items.map((it, i) => (i >= idx && i < end ? { ...it, level: it.level - 1 } : it))
}

export function indentSelection(items: TocRow[], keys: Iterable<number>): TocRow[] {
  let result = items
  for (const key of keys) result = indentSubtree(result, key)
  return result
}

export function outdentSelection(items: TocRow[], keys: Iterable<number>): TocRow[] {
  let result = items
  for (const key of keys) result = outdentSubtree(result, key)
  return result
}

// Rimuove solo la voce: i figli sono promossi di un livello (non
// cancellati) — per cancellare anche i figli va selezionata ogni voce.
export function removeEntry(items: TocRow[], key: number): TocRow[] {
  const idx = findIndexByKey(items, key)
  if (idx === -1) return items
  const end = subtreeEnd(items, idx)
  const promotedChildren = items.slice(idx + 1, end).map((c) => ({ ...c, level: c.level - 1 }))
  return [...items.slice(0, idx), ...promotedChildren, ...items.slice(end)]
}

export function removeSelection(items: TocRow[], keys: Iterable<number>): TocRow[] {
  let result = items
  for (const key of keys) result = removeEntry(result, key)
  return result
}

// Appiattisce il sottoalbero di una voce: ogni discendente diventa un
// fratello della voce stessa (stesso level), l'ordine resta invariato.
export function flattenEntry(items: TocRow[], key: number): TocRow[] {
  const idx = findIndexByKey(items, key)
  if (idx === -1) return items
  const end = subtreeEnd(items, idx)
  const level = items[idx].level
  const flattened = items.slice(idx, end).map((it) => ({ ...it, level }))
  return [...items.slice(0, idx), ...flattened, ...items.slice(end)]
}

export function flattenWhole(items: TocRow[]): TocRow[] {
  return items.map((it) => ({ ...it, level: 0 }))
}

export function insertAbove(items: TocRow[], key: number, entry: Omit<TocRow, 'level'>): TocRow[] {
  const idx = findIndexByKey(items, key)
  if (idx === -1) return [...items, { ...entry, level: 0 }]
  return [...items.slice(0, idx), { ...entry, level: items[idx].level }, ...items.slice(idx)]
}

export function insertBelow(items: TocRow[], key: number, entry: Omit<TocRow, 'level'>): TocRow[] {
  const idx = findIndexByKey(items, key)
  if (idx === -1) return [...items, { ...entry, level: 0 }]
  const end = subtreeEnd(items, idx)
  return [...items.slice(0, end), { ...entry, level: items[idx].level }, ...items.slice(end)]
}

export function insertInside(items: TocRow[], key: number, entry: Omit<TocRow, 'level'>): TocRow[] {
  const idx = findIndexByKey(items, key)
  if (idx === -1) return [...items, { ...entry, level: 0 }]
  return [...items.slice(0, idx + 1), { ...entry, level: items[idx].level + 1 }, ...items.slice(idx + 1)]
}

export function insertAtEnd(items: TocRow[], entry: Omit<TocRow, 'level'>): TocRow[] {
  return [...items, { ...entry, level: 0 }]
}

// Righe visibili tenendo conto delle voci collassate — usato sia per il
// rendering sia per il range di selezione Shift+click (che opera
// sull'elenco visibile, non su tutto l'array).
export function computeVisibleRows(items: TocRow[], collapsedKeys: Set<number>): TocRow[] {
  const result: TocRow[] = []
  let hideBelowLevel: number | null = null
  for (const item of items) {
    if (hideBelowLevel !== null) {
      if (item.level > hideBelowLevel) continue
      hideBelowLevel = null
    }
    result.push(item)
    if (collapsedKeys.has(item._key)) hideBelowLevel = item.level
  }
  return result
}
