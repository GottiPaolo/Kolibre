// Notifiche transitorie, al posto dei window.alert.
//
// Perché un emitter a livello di modulo e non un hook/context: metà delle
// chiamate arrivano da posti che non sono componenti React — un `.catch()`
// dentro lib/readerActions.ts, il gestore di un voce di menu contestuale,
// una funzione in bookActionsContext. Un hook lì non si può usare. Questo
// invece si chiama da qualsiasi punto del codice, esattamente come faceva
// window.alert, e per chi scrive il codice il cambio è una sola parola.
//
// Perché sostituire window.alert: bloccava l'interazione con tutta la
// pagina finché non si premeva OK, su telefono copriva lo schermo e faceva
// perdere il punto in cui si era, e conviveva con i messaggi inline usati
// dal resto dell'app — due linguaggi diversi per la stessa cosa a seconda
// di quale pagina ti trovavi davanti.

export type ToastKind = 'error' | 'success' | 'info'

export interface Toast {
  id: number
  kind: ToastKind
  text: string
}

type Listener = (toasts: Toast[]) => void

let toasts: Toast[] = []
const listeners = new Set<Listener>()
let nextId = 1

// Gli errori restano più a lungo: vanno letti, non solo notati.
const DURATION_MS: Record<ToastKind, number> = {
  error: 8000,
  success: 4000,
  info: 5000,
}

function emit() {
  for (const listener of listeners) listener(toasts)
}

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener)
  listener(toasts)
  return () => listeners.delete(listener)
}

export function dismissToast(id: number): void {
  toasts = toasts.filter((t) => t.id !== id)
  emit()
}

function push(kind: ToastKind, text: string): void {
  const id = nextId++
  // Niente doppioni consecutivi identici: un'operazione in blocco che
  // fallisce su venti libri produceva venti alert in fila da chiudere a
  // mano. Qui il secondo messaggio uguale rinfresca il primo.
  if (toasts.some((t) => t.text === text && t.kind === kind)) return
  toasts = [...toasts, { id, kind, text }]
  emit()
  window.setTimeout(() => dismissToast(id), DURATION_MS[kind])
}

export const toast = {
  error: (text: string) => push('error', text),
  success: (text: string) => push('success', text),
  info: (text: string) => push('info', text),
}
