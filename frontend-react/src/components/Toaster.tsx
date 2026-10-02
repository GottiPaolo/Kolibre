// Il posto dove compaiono le notifiche di lib/toast.ts. Montato una volta
// sola in Layout; non disegna nulla quando non c'è niente da dire.
//
// In basso a destra e non al centro: le azioni che generano questi messaggi
// partono quasi sempre da un menu contestuale o da una riga di tabella, e un
// riquadro al centro dello schermo farebbe perdere di vista la cosa su cui
// si stava lavorando — che era metà del problema dei window.alert.
import { useEffect, useState } from 'react'
import { AlertTriangle, Check, Info, X } from 'lucide-react'
import { subscribeToasts, dismissToast, type Toast, type ToastKind } from '@/lib/toast'
import { cn } from '@/lib/utils'
import { useLingua } from '@/lib/i18n'

const ICONS: Record<ToastKind, typeof Check> = {
  error: AlertTriangle,
  success: Check,
  info: Info,
}

const TONE: Record<ToastKind, string> = {
  error: 'border-destructive/40 bg-destructive/10 text-destructive',
  success: 'border-border bg-card text-foreground',
  info: 'border-border bg-card text-foreground',
}

export function Toaster() {
  const { t: traduci } = useLingua()
  const [toasts, setToasts] = useState<Toast[]>([])
  useEffect(() => subscribeToasts(setToasts), [])

  if (toasts.length === 0) return null

  return (
    <div
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2"
      role="status"
      aria-live="polite"
    >
      {toasts.map((t) => {
        const Icon = ICONS[t.kind]
        return (
          <div
            key={t.id}
            className={cn(
              'pointer-events-auto flex items-start gap-2.5 rounded-md border px-3 py-2.5 text-[13px] shadow-lg backdrop-blur',
              TONE[t.kind]
            )}
          >
            <Icon className="mt-0.5 size-4 shrink-0" />
            <span className="min-w-0 flex-1 break-words">{t.text}</span>
            <button
              type="button"
              onClick={() => dismissToast(t.id)}
              className="shrink-0 rounded-sm opacity-60 transition-opacity hover:opacity-100"
              aria-label={traduci('common.close')}
            >
              <X className="size-3.5" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
