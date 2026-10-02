// Editor ricorsivo dell'albero di filtri AND/OR (chart builder v3, nato per
// avere la stessa potenza di grafidinamici). Stessa idea del query
// builder di quel progetto (gruppi annidabili, regole per dimensione con
// operatore adatto al tipo), ma primitivi propri (Button/select/input già
// in uso nel resto di Statistiche) invece dell'HTML/CSS di grafidinamici —
// nessun ispettore JSON, nessuna dipendenza nuova.
import { Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ReadingSessionRaw } from '@/lib/statsQueries'
import { useLingua, type Valori } from '@/lib/i18n'
import {
  datePresetLabels,
  dimensionMeta,
  distinctLevels,
  emptyFilterGroup,
  nextId,
  type CategoricalDimension,
  type DatePreset,
  type FilterDimension,
  type FilterDimensionType,
  type FilterGroup,
  type FilterRule,
  type FilterRuleBetween,
  type FilterRuleCategorical,
  type FilterRuleContains,
  type FilterRuleDatePreset,
  type FilterRuleDateRange,
  type FilterRuleNumeric,
} from './filterTree'

type Traduci = (chiave: string, valori?: Valori) => string

function defaultRuleForDimension(dimension: FilterDimension, meta: Record<FilterDimension, { label: string; type: FilterDimensionType }>): FilterRule {
  const m = meta[dimension]
  if (m.type === 'categorical') {
    return { kind: 'rule', id: nextId('rule'), dimension: dimension as CategoricalDimension, op: 'in', values: [] }
  }
  if (m.type === 'datetime') {
    return { kind: 'rule', id: nextId('rule'), dimension: 'start_time', op: 'preset', preset: 'last30' }
  }
  return { kind: 'rule', id: nextId('rule'), dimension: dimension as 'duration_seconds' | 'pages_read', op: 'gt', value: 0 }
}

export function FilterTreeEditor({
  group,
  onChange,
  raw,
  isRoot = false,
  onRemove,
}: {
  group: FilterGroup
  onChange: (next: FilterGroup) => void
  raw: ReadingSessionRaw[]
  isRoot?: boolean
  onRemove?: () => void
}) {
  const { t } = useLingua()
  const meta = dimensionMeta(t)

  function updateChild(index: number, next: FilterRule | FilterGroup) {
    const children = group.children.slice()
    children[index] = next
    onChange({ ...group, children })
  }

  function removeChild(index: number) {
    const children = group.children.slice()
    children.splice(index, 1)
    onChange({ ...group, children })
  }

  return (
    <div className={isRoot ? 'flex flex-col gap-2' : 'flex flex-col gap-2 border-l-2 border-border/70 pl-3'}>
      <div className="flex items-center gap-2">
        <LogicToggle value={group.logic} onChange={(logic) => onChange({ ...group, logic })} t={t} />
        {!isRoot && onRemove && (
          <Button variant="ghost" size="icon-sm" onClick={onRemove} title={t('stats.filterTree.deleteGroup')}>
            <Trash2 className="size-3.5 text-destructive" />
          </Button>
        )}
      </div>

      {group.children.length === 0 && (
        <p className="text-[11px] text-muted-foreground">{t('stats.filterTree.noRules')}</p>
      )}

      <div className="flex flex-col gap-2">
        {group.children.map((child, i) =>
          child.kind === 'group' ? (
            <FilterTreeEditor
              key={child.id}
              group={child}
              onChange={(next) => updateChild(i, next)}
              raw={raw}
              onRemove={() => removeChild(i)}
            />
          ) : (
            <RuleRow key={child.id} rule={child} onChange={(next) => updateChild(i, next)} onRemove={() => removeChild(i)} raw={raw} meta={meta} />
          )
        )}
      </div>

      <div className="flex gap-1.5">
        <Button
          variant="outline"
          size="xs"
          onClick={() => onChange({ ...group, children: [...group.children, defaultRuleForDimension('author', meta)] })}
        >
          {t('stats.filterTree.addRule')}
        </Button>
        <Button variant="outline" size="xs" onClick={() => onChange({ ...group, children: [...group.children, emptyFilterGroup()] })}>
          {t('stats.filterTree.addGroup')}
        </Button>
      </div>
    </div>
  )
}

function LogicToggle({ value, onChange, t }: { value: 'and' | 'or'; onChange: (v: 'and' | 'or') => void; t: Traduci }) {
  return (
    <div className="inline-flex rounded-md border border-border p-0.5 text-[11px]">
      {(['and', 'or'] as const).map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={`rounded-sm px-2 py-0.5 font-medium ${
            value === v ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          {v === 'and' ? t('stats.filterTree.logic.and') : t('stats.filterTree.logic.or')}
        </button>
      ))}
    </div>
  )
}

function RuleRow({
  rule,
  onChange,
  onRemove,
  raw,
  meta,
}: {
  rule: FilterRule
  onChange: (r: FilterRule) => void
  onRemove: () => void
  raw: ReadingSessionRaw[]
  meta: Record<FilterDimension, { label: string; type: FilterDimensionType }>
}) {
  const { t } = useLingua()
  const allDimensions = Object.keys(meta) as FilterDimension[]
  return (
    <div className="flex flex-wrap items-start gap-1.5 rounded-md border border-border bg-background p-2">
      <select
        value={rule.dimension}
        onChange={(e) => onChange(defaultRuleForDimension(e.target.value as FilterDimension, meta))}
        className="rounded-md border border-border bg-background px-1.5 py-1 text-[12px]"
      >
        {allDimensions.map((d) => (
          <option key={d} value={d}>
            {meta[d].label}
          </option>
        ))}
      </select>

      <RuleValueEditor rule={rule} onChange={onChange} raw={raw} />

      <Button variant="ghost" size="icon-sm" onClick={onRemove} title={t('stats.filterTree.deleteRule')} className="ml-auto">
        <X className="size-3.5 text-muted-foreground" />
      </Button>
    </div>
  )
}

function OpSelect<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value as T)} className="rounded-md border border-border bg-background px-1.5 py-1 text-[12px]">
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

function NumberField({ value, unit, onChange }: { value: number; unit: string; onChange: (v: number) => void }) {
  return (
    <div className="flex items-center gap-1">
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        className="w-full rounded-md border border-border bg-background px-2 py-1 text-[12px] outline-none focus:border-primary"
      />
      <span className="text-[11px] text-muted-foreground">{unit}</span>
    </div>
  )
}

// Lista di checkbox scrollabile per la selezione dei "livelli" (valori
// distinti reali) di una dimensione categorica — stesso pattern minimale
// già in uso altrove in Statistiche (ConfigRow in ChartConfigDialog.tsx).
function LevelPicker({ options, selected, onChange }: { options: string[]; selected: string[]; onChange: (v: string[]) => void }) {
  const { t } = useLingua()
  function toggle(value: string) {
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value])
  }

  if (options.length === 0) return <p className="text-[11px] text-muted-foreground">{t('stats.filterTree.noValuesAvailable')}</p>

  return (
    <div className="flex max-h-28 flex-col gap-0.5 overflow-y-auto rounded-md border border-border bg-background p-1.5">
      {options.map((opt) => (
        <label key={opt} className="flex items-center gap-1.5 rounded px-1 py-0.5 text-[12px] hover:bg-muted/50">
          <input type="checkbox" checked={selected.includes(opt)} onChange={() => toggle(opt)} className="size-3.5 shrink-0 accent-primary" />
          <span className="truncate">{opt}</span>
        </label>
      ))}
    </div>
  )
}

function RuleValueEditor({ rule, onChange, raw }: { rule: FilterRule; onChange: (r: FilterRule) => void; raw: ReadingSessionRaw[] }) {
  const { t } = useLingua()
  const meta = dimensionMeta(t)[rule.dimension]

  if (meta.type === 'categorical') {
    const dimension = rule.dimension as CategoricalDimension
    const op = (rule as FilterRuleCategorical | FilterRuleContains).op
    return (
      <div className="flex min-w-48 flex-1 flex-col gap-1.5">
        <OpSelect
          value={op}
          options={[
            { value: 'in', label: t('stats.filterTree.op.in') },
            { value: 'contains', label: t('stats.filterTree.op.contains') },
          ]}
          onChange={(nextOp) =>
            onChange(
              nextOp === 'in'
                ? { kind: 'rule', id: rule.id, dimension, op: 'in', values: [] }
                : { kind: 'rule', id: rule.id, dimension, op: 'contains', text: '' }
            )
          }
        />
        {op === 'in' ? (
          <LevelPicker
            options={distinctLevels(raw, dimension)}
            selected={(rule as FilterRuleCategorical).values}
            onChange={(values) => onChange({ kind: 'rule', id: rule.id, dimension, op: 'in', values })}
          />
        ) : (
          <input
            value={(rule as FilterRuleContains).text}
            onChange={(e) => onChange({ kind: 'rule', id: rule.id, dimension, op: 'contains', text: e.target.value })}
            placeholder={t('stats.filterTree.containedTextPlaceholder')}
            className="w-full rounded-md border border-border bg-background px-2 py-1 text-[12px] outline-none focus:border-primary"
          />
        )}
      </div>
    )
  }

  if (meta.type === 'datetime') {
    const op = (rule as FilterRuleDateRange | FilterRuleDatePreset).op
    const presetLabels = datePresetLabels(t)
    return (
      <div className="flex min-w-48 flex-1 flex-col gap-1.5">
        <OpSelect
          value={op}
          options={[
            { value: 'range', label: t('stats.filterTree.op.customRange') },
            { value: 'preset', label: t('stats.filterTree.op.presetPeriod') },
          ]}
          onChange={(nextOp) =>
            onChange(
              nextOp === 'range'
                ? { kind: 'rule', id: rule.id, dimension: 'start_time', op: 'range', from: null, to: null }
                : { kind: 'rule', id: rule.id, dimension: 'start_time', op: 'preset', preset: 'last30' }
            )
          }
        />
        {op === 'range' ? (
          <div className="grid grid-cols-2 gap-1.5">
            <input
              type="date"
              value={(rule as FilterRuleDateRange).from ?? ''}
              onChange={(e) => onChange({ ...(rule as FilterRuleDateRange), from: e.target.value || null })}
              className="rounded-md border border-border bg-background px-2 py-1 text-[12px] outline-none focus:border-primary"
            />
            <input
              type="date"
              value={(rule as FilterRuleDateRange).to ?? ''}
              onChange={(e) => onChange({ ...(rule as FilterRuleDateRange), to: e.target.value || null })}
              className="rounded-md border border-border bg-background px-2 py-1 text-[12px] outline-none focus:border-primary"
            />
          </div>
        ) : (
          <select
            value={(rule as FilterRuleDatePreset).preset}
            onChange={(e) => onChange({ ...(rule as FilterRuleDatePreset), preset: e.target.value as DatePreset })}
            className="rounded-md border border-border bg-background px-1.5 py-1 text-[12px]"
          >
            {(Object.keys(presetLabels) as DatePreset[]).map((p) => (
              <option key={p} value={p}>
                {presetLabels[p]}
              </option>
            ))}
          </select>
        )}
      </div>
    )
  }

  // numerico: duration_seconds | pages_read
  const dimension = rule.dimension as 'duration_seconds' | 'pages_read'
  const isDuration = dimension === 'duration_seconds'
  const toDisplay = (v: number) => (isDuration ? Math.round(v / 60) : v)
  const toStored = (v: number) => (isDuration ? Math.round(v * 60) : v)
  const unit = isDuration ? 'min' : t('stats.filterTree.unit.pages')
  const op = (rule as FilterRuleNumeric | FilterRuleBetween).op

  return (
    <div className="flex min-w-48 flex-1 flex-col gap-1.5">
      <OpSelect
        value={op}
        options={[
          { value: 'gt', label: t('stats.filterTree.op.gt') },
          { value: 'lt', label: t('stats.filterTree.op.lt') },
          { value: 'eq', label: t('stats.filterTree.op.eq') },
          { value: 'between', label: t('stats.filterTree.op.between') },
        ]}
        onChange={(nextOp) =>
          onChange(
            nextOp === 'between'
              ? { kind: 'rule', id: rule.id, dimension, op: 'between', min: 0, max: 0 }
              : { kind: 'rule', id: rule.id, dimension, op: nextOp, value: 0 }
          )
        }
      />
      {op === 'between' ? (
        <div className="grid grid-cols-2 gap-1.5">
          <NumberField
            unit={unit}
            value={toDisplay((rule as FilterRuleBetween).min)}
            onChange={(v) => onChange({ ...(rule as FilterRuleBetween), min: toStored(v) })}
          />
          <NumberField
            unit={unit}
            value={toDisplay((rule as FilterRuleBetween).max)}
            onChange={(v) => onChange({ ...(rule as FilterRuleBetween), max: toStored(v) })}
          />
        </div>
      ) : (
        <NumberField
          unit={unit}
          value={toDisplay((rule as FilterRuleNumeric).value)}
          onChange={(v) => onChange({ ...(rule as FilterRuleNumeric), value: toStored(v) })}
        />
      )}
    </div>
  )
}
