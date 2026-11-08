import { cn } from '@/lib/utils'
import type { PillTone } from '@/lib/deviceFormat'

// Porting della classe .device-status-pill (+ .pill-sage/.pill-gold/
// .pill-accent/.pill-muted) di frontend/src/style.css — vedi deviceFormat.ts
// per la mappatura dei toni sui token del design system React.
const TONE_CLASSES: Record<PillTone, string> = {
  positive: 'text-[var(--positive)] border-[var(--positive)] bg-[var(--positive-soft)]',
  warning: 'text-[var(--warning)] border-[var(--warning)] bg-[var(--warning-soft)]',
  destructive: 'text-destructive border-destructive/60 bg-destructive/10',
  muted: 'text-muted-foreground border-border bg-muted',
}

interface DeviceStatusPillProps {
  label: string
  tone: PillTone
  title?: string
  className?: string
}

export function DeviceStatusPill({ label, tone, title, className }: DeviceStatusPillProps) {
  return (
    <span
      title={title}
      className={cn(
        'inline-block rounded-full border px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap',
        TONE_CLASSES[tone],
        className
      )}
    >
      {label}
    </span>
  )
}
