import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useLingua } from '@/lib/i18n'
import type { Book } from '@/types/library'
import { useBookToc } from '@/lib/queries'
import { saveBookToc, generateBookToc } from '@/lib/bookActions'
import {
  computeVisibleRows,
  findIndexByKey,
  flattenEntry,
  flattenWhole,
  hasChildrenAt,
  indentSelection,
  indentSubtree,
  insertAbove,
  insertAtEnd,
  insertBelow,
  insertInside,
  moveSubtreeDown,
  moveSubtreeUp,
  outdentSelection,
  outdentSubtree,
  removeEntry,
  removeSelection,
  type TocRow,
} from './tocTree'
import { TocActionsPanel } from './TocActionsPanel'
import { TocDestinationPicker } from './TocDestinationPicker'

interface TocEditorDialogProps {
  book: Book
  libraryFolder: string
  onClose: () => void
}

export function TocEditorDialog({ book, libraryFolder, onClose }: TocEditorDialogProps) {
  const { t } = useLingua()
  const tocQuery = useBookToc(libraryFolder, book.id, true)
  const [items, setItems] = useState<TocRow[] | null>(null)
  const [selectedKeys, setSelectedKeys] = useState<Set<number>>(new Set())
  const [anchorKey, setAnchorKey] = useState<number | null>(null)
  const [collapsedKeys, setCollapsedKeys] = useState<Set<number>>(new Set())
  const [editingKey, setEditingKey] = useState<number | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [destinationPicker, setDestinationPicker] = useState<
    { mode: 'edit'; forKey: number } | { mode: 'create'; insertAt: 'above' | 'below' | 'inside' | 'end'; relativeKey: number | null } | null
  >(null)
  const keyCounter = useRef(0)

  useEffect(() => {
    if (tocQuery.data && items === null) {
      const withKeys = tocQuery.data.entries.map((e) => ({ ...e, _key: ++keyCounter.current }))
      setItems(withKeys)
    }
  }, [tocQuery.data, items])

  const format = tocQuery.data?.format ?? 'EPUB'
  const visibleRows = useMemo(() => (items ? computeVisibleRows(items, collapsedKeys) : []), [items, collapsedKeys])

  function handleRowClick(key: number, e: React.MouseEvent) {
    if (e.shiftKey && anchorKey !== null) {
      const visIdx = (k: number) => visibleRows.findIndex((r) => r._key === k)
      const from = visIdx(anchorKey)
      const to = visIdx(key)
      if (from !== -1 && to !== -1) {
        const [lo, hi] = from < to ? [from, to] : [to, from]
        setSelectedKeys(new Set(visibleRows.slice(lo, hi + 1).map((r) => r._key)))
        return
      }
    }
    if (e.metaKey || e.ctrlKey) {
      setSelectedKeys((prev) => {
        const next = new Set(prev)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return next
      })
      setAnchorKey(key)
      return
    }
    setSelectedKeys(new Set([key]))
    setAnchorKey(key)
  }

  function toggleCollapse(key: number) {
    setCollapsedKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function startRename(row: TocRow) {
    setEditingKey(row._key)
    setEditingTitle(row.title)
  }

  function commitRename() {
    if (editingKey === null || !items) return
    setItems(items.map((it) => (it._key === editingKey ? { ...it, title: editingTitle } : it)))
    setEditingKey(null)
  }

  const singleKey = selectedKeys.size === 1 ? [...selectedKeys][0] : null

  function newEntry(title: string, dest: string) {
    return { _key: ++keyCounter.current, title, dest, valid: true }
  }

  function openPickerForNew(insertAt: 'above' | 'below' | 'inside' | 'end') {
    setDestinationPicker({ mode: 'create', insertAt, relativeKey: singleKey })
  }

  function applyDestination(dest: string, title: string) {
    if (!items || !destinationPicker) return
    if (destinationPicker.mode === 'edit') {
      setItems(items.map((it) => (it._key === destinationPicker.forKey ? { ...it, dest, title, valid: true } : it)))
    } else {
      const entry = newEntry(title || t('library.toc.newEntryDefaultTitle'), dest)
      const { insertAt, relativeKey } = destinationPicker
      if (relativeKey === null || insertAt === 'end') {
        setItems(insertAtEnd(items, entry))
      } else if (insertAt === 'above') {
        setItems(insertAbove(items, relativeKey, entry))
      } else if (insertAt === 'below') {
        setItems(insertBelow(items, relativeKey, entry))
      } else {
        setItems(insertInside(items, relativeKey, entry))
      }
    }
    setDestinationPicker(null)
  }

  async function handleGenerate(mode: 'major_headings' | 'all_headings' | 'files') {
    try {
      const entries = await generateBookToc(libraryFolder, book.id, mode)
      setItems(entries.map((e) => ({ ...e, _key: ++keyCounter.current })))
      setSelectedKeys(new Set())
    } catch {
      setError(t('library.toc.generateFailed'))
    }
  }

  async function handleSave() {
    if (!items) return
    setSaving(true)
    setError(null)
    try {
      await saveBookToc(libraryFolder, book.id, format, items)
      onClose()
    } catch {
      setError(t('library.toc.saveFailed'))
      setSaving(false)
    }
  }

  const entryActionsFor = (key: number) => ({
    onMoveUp: () => items && setItems(moveSubtreeUp(items, key)),
    onMoveDown: () => items && setItems(moveSubtreeDown(items, key)),
    onIndent: () => items && setItems(indentSubtree(items, key)),
    onOutdent: () => items && setItems(outdentSubtree(items, key)),
    onChangeDestination: () => setDestinationPicker({ mode: 'edit', forKey: key }),
    onRemove: () => {
      if (!items) return
      setItems(removeEntry(items, key))
      setSelectedKeys(new Set())
    },
    onInsertAbove: () => openPickerForNew('above'),
    onInsertBelow: () => openPickerForNew('below'),
    onInsertInside: () => openPickerForNew('inside'),
    onFlatten: () => items && setItems(flattenEntry(items, key)),
  })

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-6xl">
        <DialogHeader>
          <DialogTitle>{t('library.toc.editTitle', { title: book.title })}</DialogTitle>
        </DialogHeader>

        {tocQuery.isLoading && <p className="text-[12.5px] text-muted-foreground">{t('library.toc.loadingToc')}</p>}

        {items && (
          <div className="flex h-[380px] gap-3">
            <div className="flex-1 overflow-y-auto rounded-md border border-border">
              {visibleRows.length === 0 && (
                <p className="p-4 text-center text-[12.5px] text-muted-foreground">{t('library.toc.noEntries')}</p>
              )}
              {visibleRows.map((row) => {
                const idx = findIndexByKey(items, row._key)
                const hasChildren = hasChildrenAt(items, idx)
                return (
                  <div
                    key={row._key}
                    onClick={(e) => handleRowClick(row._key, e)}
                    style={{ paddingLeft: 8 + row.level * 20 }}
                    className={cn(
                      'flex cursor-default items-center gap-1.5 border-b border-border/40 py-1 pr-2 text-[12.5px] select-none hover:bg-accent/60',
                      selectedKeys.has(row._key) && 'bg-primary/10 hover:bg-primary/10'
                    )}
                  >
                    {hasChildren ? (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          toggleCollapse(row._key)
                        }}
                        className="shrink-0 text-muted-foreground"
                      >
                        {collapsedKeys.has(row._key) ? <ChevronRight className="size-3.5" /> : <ChevronDown className="size-3.5" />}
                      </button>
                    ) : (
                      <span className="w-3.5 shrink-0" />
                    )}
                    <span className="shrink-0" title={row.valid === false ? t('library.toc.destinationInvalid') : t('library.toc.destinationValid')}>
                      {row.valid === false ? '⚠️' : '✅'}
                    </span>
                    {editingKey === row._key ? (
                      <input
                        autoFocus
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onBlur={commitRename}
                        onKeyDown={(e) => e.key === 'Enter' && commitRename()}
                        className="min-w-0 flex-1 rounded border border-primary bg-background px-1 py-0.5"
                      />
                    ) : (
                      <span className="min-w-0 flex-1 truncate" onDoubleClick={() => startRename(row)}>
                        {row.title || t('library.metadata.untitled')}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>

            <div className="w-[220px] shrink-0 overflow-y-auto">
              <TocActionsPanel
                items={items}
                selectedKeys={selectedKeys}
                single={singleKey !== null ? entryActionsFor(singleKey) : entryActionsFor(-1)}
                onIndentSelection={() => setItems(indentSelection(items, selectedKeys))}
                onOutdentSelection={() => setItems(outdentSelection(items, selectedKeys))}
                onRemoveSelection={() => {
                  setItems(removeSelection(items, selectedKeys))
                  setSelectedKeys(new Set())
                }}
                onCreateFromScratch={() => openPickerForNew(singleKey ? 'below' : 'end')}
                onGenerate={handleGenerate}
                onFlattenWhole={() => setItems(flattenWhole(items))}
                format={format}
              />
            </div>
          </div>
        )}

        {error && <p className="text-[12.5px] text-destructive">{error}</p>}

        <DialogFooter className="justify-between sm:justify-between">
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setCollapsedKeys(new Set())}>
              {t('library.toc.expandAll')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => items && setCollapsedKeys(new Set(items.filter((_, i) => hasChildrenAt(items, i)).map((it) => it._key)))}
            >
              {t('library.toc.collapseAll')}
            </Button>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleSave} disabled={saving || !items}>
              {saving ? t('library.metadata.saving') : t('common.save')}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>

      {destinationPicker && (
        <TocDestinationPicker
          libraryFolder={libraryFolder}
          bookId={book.id}
          format={format}
          mode={destinationPicker.mode}
          initialTitle={destinationPicker.mode === 'edit' && items ? items.find((it) => it._key === destinationPicker.forKey)?.title ?? '' : ''}
          onCancel={() => setDestinationPicker(null)}
          onApply={applyDestination}
        />
      )}
    </Dialog>
  )
}
