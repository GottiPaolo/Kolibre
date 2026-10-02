import { useMemo } from 'react'
import { ChevronRight, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Book } from '@/types/library'
import { buildBrowserTree, countActiveFilters, type FieldDef } from '@/lib/libraryQuery'
import { useLingua } from '@/lib/i18n'

interface NavigatorDrawerProps {
  open: boolean
  onClose: () => void
  searchText: string
  onSearchTextChange: (value: string) => void
  fieldDefs: FieldDef[]
  books: Book[]
  expandedFields: Set<string>
  onToggleExpand: (key: string) => void
  onCycleFilter: (def: FieldDef, value: string, additive: boolean) => void
  onClear: () => void
  // I valori contati dal server sull'intera biblioteca. Quando manca (o la
  // richiesta non è ancora arrivata) si ricade sul conteggio dai libri
  // caricati, che è quello che il Navigatore ha sempre fatto.
  valoriDalServer?: Record<string, { valore: string; libri: number }[]>
}

export function NavigatorDrawer({
  open,
  onClose,
  searchText,
  onSearchTextChange,
  fieldDefs,
  books,
  expandedFields,
  onToggleExpand,
  onCycleFilter,
  onClear,
  valoriDalServer,
}: NavigatorDrawerProps) {
  const { t } = useLingua()
  const tree = useMemo(
    () => buildBrowserTree(books, fieldDefs, searchText, valoriDalServer),
    [books, fieldDefs, searchText, valoriDalServer]
  )
  const activeCount = useMemo(() => countActiveFilters(searchText, fieldDefs), [searchText, fieldDefs])

  if (!open) return null

  return (
    <div className="absolute top-0 left-0 bottom-0 z-10 flex w-[300px] flex-col gap-3 overflow-y-auto border-r border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-semibold">{t('library.navigator.toggle')}</span>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X className="size-4" />
        </button>
      </div>

      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground">{t('library.navigator.quickFilterLabel')}</label>
        <input
          value={searchText}
          onChange={(e) => onSearchTextChange(e.target.value)}
          placeholder={t('library.navigator.quickFilterPlaceholder')}
          className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
        />
      </div>

      <button
        onClick={onClear}
        disabled={activeCount === 0}
        className="self-start text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:opacity-40 disabled:hover:no-underline"
      >
        {t('library.navigator.clear')} {activeCount > 0 ? `(${activeCount})` : ''}
      </button>

      <div className="flex flex-col gap-0.5">
        {tree.map(({ def, values }) => {
          const isExpanded = expandedFields.has(def.key)
          return (
            <div key={def.key} className="border-b border-border/50 pb-1.5">
              <button
                onClick={() => onToggleExpand(def.key)}
                className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1.5 text-left text-[12.5px] font-medium hover:bg-accent"
              >
                <ChevronRight className={cn('size-3.5 shrink-0 transition-transform', isExpanded && 'rotate-90')} />
                {def.label}
                <span className="ml-auto text-[10.5px] text-muted-foreground">{values.length}</span>
              </button>
              {isExpanded && (
                <div className="mt-0.5 flex flex-col gap-0.5 pl-5">
                  {values.map((v) => (
                    <button
                      key={v.value}
                      onClick={(e) => onCycleFilter(def, v.value, e.metaKey || e.ctrlKey)}
                      className={cn(
                        'flex items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-[12px]',
                        v.state === 'include' && 'bg-primary/15 text-primary',
                        v.state === 'exclude' && 'text-destructive line-through',
                        v.state === 'none' && 'hover:bg-accent'
                      )}
                    >
                      <span className="truncate">{v.display}</span>
                      <span className="ml-auto text-[10.5px] text-muted-foreground">{v.count}</span>
                    </button>
                  ))}
                  {values.length === 0 && <div className="px-1.5 py-1 text-[11.5px] text-muted-foreground">{t('library.navigator.noValues')}</div>}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
