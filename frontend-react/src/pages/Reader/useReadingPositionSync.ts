// La SCRITTURA della posizione di lettura verso il server, estratta da
// ReaderPage.tsx (revisione del 19/11, punto A3) SENZA cambiare
// comportamento: il salvataggio con debounce a ogni 'relocated' e lo
// svuotamento con keepalive quando la finestra sta morendo. La LETTURA
// della posizione salvata resta nel mount della pagina, intrecciata com'e'
// con le mire (nota, ricerca, CFI) e con l'indice delle locations.
import { useRef } from 'react'
import { putReadingPosition } from '@/lib/readingPositionActions'
import type { Valori } from '@/lib/i18n'

interface ParametriPosizione {
  library: string
  bookId: number
  /** Anteprima pre-importazione: nessuna posizione da salvare. */
  isIngestPreview: boolean
  t: (chiave: string, valori?: Valori) => string
  showSaveError: (msg: string) => void
}

export function useReadingPositionSync({
  library,
  bookId,
  isIngestPreview,
  t,
  showSaveError,
}: ParametriPosizione) {
  const savePositionTimerRef = useRef<number | undefined>(undefined)
  const lastKnownCfiRef = useRef<string | null>(null)
  const lastKnownPercentageRef = useRef<number | null>(null)

  function scheduleSavePosition(cfi: string, percentage: number) {
    lastKnownCfiRef.current = cfi
    lastKnownPercentageRef.current = percentage
    if (savePositionTimerRef.current) window.clearTimeout(savePositionTimerRef.current)
    // Debounced rather than on every single page turn — flipping through
    // several pages quickly (or holding an arrow key) would otherwise fire
    // one PUT per page for no real benefit, since only the LAST one before
    // the reader closes/idles actually matters.
    savePositionTimerRef.current = window.setTimeout(() => {
      putReadingPosition(library, bookId, { cfi, percentage }).catch(() => {
        showSaveError(t('reader.save.positionFailed'))
      })
    }, 2000)
  }

  // keepalive so this specific save has a real chance of reaching the
  // server even as the page starts unloading — browsers otherwise cancel
  // in-flight fetches once teardown begins.
  function flushReadingPosition() {
    if (isIngestPreview) return
    if (savePositionTimerRef.current) window.clearTimeout(savePositionTimerRef.current)
    const cfi = lastKnownCfiRef.current
    const percentage = lastKnownPercentageRef.current
    if (cfi && percentage != null) {
      putReadingPosition(library, bookId, { cfi, percentage }, { keepalive: true }).catch(() => {
        // best-effort — the window is closing, nothing more we can do
      })
    }
  }

  return {
    // Chiamata dal gestore 'relocated' del mount, a ogni cambio pagina.
    scheduleSavePosition,
    // Chiamata su beforeunload/pagehide/visibilitychange e nella cleanup
    // del mount: i listener restano nella pagina, che possiede il ciclo
    // di vita del libro.
    flushReadingPosition,
  }
}
