// Linguaggio visivo condiviso delle Impostazioni (redesign in stile Obsidian
// approvato sul prototipo): una sola riga-tipo ripetuta ovunque —
// nome + descrizione a sinistra, controllo a destra, filetto sottile tra le
// righe, etichette di sezione in maiuscoletto.
//
// Prima del redesign ogni scheda reinventava i propri titoli, campi e
// spaziature (ProfileTab aveva il suo <Field>/<TextInput>, IntegrationsTab
// <section> con h2 serif, LibrariesTab card con bordi…): stesso contenuto,
// sei stili diversi. Da qui in poi le schede NON scrivono più markup di
// layout proprio — compongono questi mattoni, così l'aspetto resta coerente
// anche quando se ne aggiunge una nuova.
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** Etichetta di gruppo dentro una scheda ("TEMA", "CARATTERI", …). */
export function SettingsSection({
  label,
  description,
  children,
}: {
  label: string
  description?: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col">
      <h3 className="pt-6 pb-0.5 text-[10.5px] font-semibold tracking-[0.09em] text-[var(--text-faint)] uppercase">
        {label}
      </h3>
      {description && <p className="pb-1 text-[12px] leading-relaxed text-muted-foreground">{description}</p>}
      {children}
    </section>
  )
}

/**
 * La riga elementare. `stack` per i controlli larghi (elenchi, editor,
 * gruppi di bottoni) che a destra starebbero stretti: il controllo va sotto
 * al testo invece che accanto.
 */
export function SettingsRow({
  name,
  description,
  children,
  stack = false,
  last = false,
}: {
  name?: ReactNode
  description?: ReactNode
  children?: ReactNode
  stack?: boolean
  last?: boolean
}) {
  return (
    <div
      className={cn(
        'py-3.5',
        !last && 'border-b border-[var(--border-soft)]',
        !stack && 'flex items-center justify-between gap-6'
      )}
    >
      {(name || description) && (
        <div className="min-w-0">
          {name && <div className="text-[13.5px] font-medium">{name}</div>}
          {description && (
            <div className="mt-0.5 max-w-[58ch] text-[12px] leading-relaxed text-muted-foreground">{description}</div>
          )}
        </div>
      )}
      {children && (
        <div className={cn('flex shrink-0 items-center gap-2', stack && 'mt-3 flex-wrap')}>{children}</div>
      )}
    </div>
  )
}

/** Interruttore on/off — sostituisce le checkbox grezze sparse nelle schede. */
export function SettingsToggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  disabled?: boolean
  label: string
}) {
  return (
    <input
      type="checkbox"
      role="switch"
      aria-label={label}
      checked={checked}
      disabled={disabled}
      onChange={(e) => onChange(e.target.checked)}
      className="relative h-[21px] w-[38px] shrink-0 cursor-pointer appearance-none rounded-full border border-border bg-muted transition-colors after:absolute after:top-[2px] after:left-[2px] after:size-[15px] after:rounded-full after:bg-muted-foreground after:transition-transform checked:border-primary checked:bg-primary/20 checked:after:translate-x-[17px] checked:after:bg-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-50"
    />
  )
}

/** Campo di testo della stessa famiglia degli altri controlli. */
export function SettingsInput({
  value,
  onChange,
  type = 'text',
  placeholder,
  autoComplete,
  readOnly,
  className,
  ariaLabel,
}: {
  value: string
  onChange?: (v: string) => void
  type?: string
  placeholder?: string
  autoComplete?: string
  readOnly?: boolean
  className?: string
  ariaLabel?: string
}) {
  return (
    <input
      type={type}
      value={value}
      readOnly={readOnly}
      aria-label={ariaLabel}
      onChange={(e) => onChange?.(e.target.value)}
      placeholder={placeholder}
      autoComplete={autoComplete}
      className={cn(
        'rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary',
        className
      )}
    />
  )
}

/** Campo verticale con etichetta, per i form veri (profilo, modifica libreria). */
export function SettingsField({
  label,
  children,
  className,
}: {
  label: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <label className="text-[11px] font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  )
}

/** Pastiglia di stato: "Installato", "Predefinita", "2 in attesa". */
export function SettingsPill({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: 'neutral' | 'ok' | 'warn'
}) {
  return (
    <span
      className={cn(
        'rounded-full border px-2 py-0.5 text-[11px] whitespace-nowrap',
        tone === 'neutral' && 'border-border text-muted-foreground',
        tone === 'ok' && 'border-[var(--positive)]/40 text-[var(--positive)]',
        tone === 'warn' && 'border-[var(--warning)]/40 text-[var(--warning)]'
      )}
    >
      {children}
    </span>
  )
}

/** Elenco incorniciato (librerie, dispositivi, dizionari). */
export function SettingsList({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('overflow-hidden rounded-lg border border-border', className)}>{children}</div>
}

export function SettingsListRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        'flex items-center justify-between gap-4 border-b border-[var(--border-soft)] bg-background px-3.5 py-3 last:border-b-0',
        className
      )}
    >
      {children}
    </div>
  )
}

/** Nota esplicativa a fondo sezione — il posto dei "perché" lunghi. */
export function SettingsHint({ children }: { children: ReactNode }) {
  return (
    <p className="mt-3 border-t border-[var(--border-soft)] pt-3 text-[11.5px] leading-relaxed text-[var(--text-faint)]">
      {children}
    </p>
  )
}

/** Esito di un'azione: una riga, stesso posto in tutte le schede. */
export function SettingsFeedback({ kind, children }: { kind: 'ok' | 'error'; children: ReactNode }) {
  return (
    <p className={cn('pt-2 text-[12px]', kind === 'error' ? 'text-destructive' : 'text-primary')}>{children}</p>
  )
}
