import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import { hasChildrenAt, findIndexByKey, type TocRow } from './tocTree'

interface SingleEntryActions {
  onMoveUp: () => void
  onMoveDown: () => void
  onIndent: () => void
  onOutdent: () => void
  onChangeDestination: () => void
  onRemove: () => void
  onInsertAbove: () => void
  onInsertBelow: () => void
  onInsertInside: () => void
  onFlatten: () => void
}

interface TocActionsPanelProps {
  items: TocRow[]
  selectedKeys: Set<number>
  single: SingleEntryActions
  onIndentSelection: () => void
  onOutdentSelection: () => void
  onRemoveSelection: () => void
  onCreateFromScratch: () => void
  onGenerate: (mode: 'major_headings' | 'all_headings' | 'files') => void
  onFlattenWhole: () => void
  format: 'EPUB' | 'PDF'
}

export function TocActionsPanel({
  items,
  selectedKeys,
  single,
  onIndentSelection,
  onOutdentSelection,
  onRemoveSelection,
  onCreateFromScratch,
  onGenerate,
  onFlattenWhole,
  format,
}: TocActionsPanelProps) {
  const { t } = useLingua()
  if (selectedKeys.size > 1) {
    return (
      <div className="flex flex-col gap-1.5">
        <p className="text-[11px] font-medium text-muted-foreground">{t('library.toc.selectedCount', { n: selectedKeys.size })}</p>
        <Button variant="outline" size="sm" onClick={onIndentSelection}>
          → {t('library.toc.indent')}
        </Button>
        <Button variant="outline" size="sm" onClick={onOutdentSelection}>
          ← {t('library.toc.outdent')}
        </Button>
        <Button variant="destructive" size="sm" onClick={onRemoveSelection}>
          🗑 {t('library.toc.removeSelection')}
        </Button>
      </div>
    )
  }

  if (selectedKeys.size === 1) {
    const key = [...selectedKeys][0]
    const idx = findIndexByKey(items, key)
    const entry = items[idx]
    const canOutdent = entry.level > 0
    const canFlatten = hasChildrenAt(items, idx)
    return (
      <div className="flex flex-col gap-1.5">
        <p className="truncate text-[11px] font-medium text-muted-foreground">{entry.title || t('library.metadata.untitled')}</p>
        <Button variant="outline" size="sm" onClick={single.onMoveUp}>
          ▲ {t('library.toc.moveUp')}
        </Button>
        <Button variant="outline" size="sm" onClick={single.onMoveDown}>
          ▼ {t('library.toc.moveDown')}
        </Button>
        <Button variant="outline" size="sm" onClick={single.onOutdent} disabled={!canOutdent}>
          ← {t('library.toc.outdent')}
        </Button>
        <Button variant="outline" size="sm" onClick={single.onIndent}>
          → {t('library.toc.indent')}
        </Button>
        <Button variant="outline" size="sm" onClick={single.onChangeDestination}>
          ✏️ {t('library.toc.changeDestination')}
        </Button>
        <div className="my-1 h-px bg-border" />
        <Button variant="outline" size="sm" onClick={single.onInsertInside}>
          + {t('library.toc.newEntryInside')}
        </Button>
        <Button variant="outline" size="sm" onClick={single.onInsertAbove}>
          + {t('library.toc.newEntryAbove')}
        </Button>
        <Button variant="outline" size="sm" onClick={single.onInsertBelow}>
          + {t('library.toc.newEntryBelow')}
        </Button>
        <Button variant="outline" size="sm" onClick={single.onFlatten} disabled={!canFlatten}>
          ⇤ {t('library.toc.flattenEntry')}
        </Button>
        <div className="my-1 h-px bg-border" />
        <Button variant="destructive" size="sm" onClick={single.onRemove}>
          🗑 {t('library.toc.removeEntry')}
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-[11px] font-medium text-muted-foreground">{t('library.toc.noSelection')}</p>
      <Button variant="outline" size="sm" onClick={onCreateFromScratch}>
        + {t('library.toc.createNewEntry')}
      </Button>
      {format === 'EPUB' && (
        <>
          <div className="my-1 h-px bg-border" />
          <p className="text-[11px] text-muted-foreground">{t('library.toc.generateAutomatically')}</p>
          <Button variant="outline" size="sm" onClick={() => onGenerate('major_headings')}>
            {t('library.toc.generateMajorHeadings')}
          </Button>
          <Button variant="outline" size="sm" onClick={() => onGenerate('all_headings')}>
            {t('library.toc.generateAllHeadings')}
          </Button>
          <Button variant="outline" size="sm" onClick={() => onGenerate('files')}>
            {t('library.toc.generateOnePerFile')}
          </Button>
        </>
      )}
      <div className="my-1 h-px bg-border" />
      <Button variant="outline" size="sm" onClick={onFlattenWhole} disabled={items.length === 0}>
        {t('library.toc.flattenWhole')}
      </Button>
    </div>
  )
}
