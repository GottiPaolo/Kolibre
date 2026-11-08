import { useEffect, useRef } from 'react'
import {
  COMMAND_REGISTRY,
  commandBindings,
  loadShortcutOverrides,
  normalizeKeyCombo,
} from './shortcutRegistry'

// Esegue davvero le scorciatoie da tastiera.
//
// Il registro dei comandi (shortcutRegistry.ts) e la pagina che permette di
// personalizzarli esistevano gia', ma nessuno ascoltava la tastiera: i
// tasti si potevano configurare e non succedeva niente. Il commento in cima
// a quel file lo dice apertamente, ed e' rimasto vero fino a ora.
//
// Qui non c'e' un dispatcher globale ma un aggancio PER PAGINA: ogni pagina
// dichiara quali comandi sa eseguire, e nient'altro. E' la forma che si
// adatta a React instradato per pagina — le azioni (modifica metadati,
// leggi) vivono nello stato della pagina che ha il libro sotto mano, non in
// una variabile globale come nel vecchio frontend a pagina unica.
//
// `handlers`: { idComando: cosa fare }. Gli id sono quelli di
// COMMAND_REGISTRY ('edit-metadata', 'read-book-web', ...).
export type ShortcutHandlers = Record<string, () => void>

function stoScrivendo(bersaglio: EventTarget | null): boolean {
  const el = bersaglio as HTMLElement | null
  if (!el || !el.tagName) return false
  const tag = el.tagName.toLowerCase()
  return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable
}

export function useShortcuts(handlers: ShortcutHandlers, attive = true): void {
  // I gestori cambiano a ogni render (chiudono sul libro corrente); tenerli
  // in un ref evita di togliere e rimettere l'ascoltatore ogni volta.
  const correnti = useRef(handlers)
  correnti.current = handlers

  useEffect(() => {
    if (!attive) return
    function onKeyDown(e: KeyboardEvent) {
      // Mai mentre si scrive: "e" in una casella di ricerca deve restare
      // una lettera.
      if (stoScrivendo(e.target)) return
      // Mai con una finestra aperta sopra: il tasto che apre la finestra
      // dei metadati non deve riaprirla mentre ci si e' dentro.
      if (document.querySelector('[role="dialog"]')) return
      const combo = normalizeKeyCombo(e)
      if (!combo) return
      // Le personalizzazioni si rileggono a ogni tasto, non al montaggio:
      // cambiarle in Impostazioni ha effetto subito, senza ricaricare.
      const overrides = loadShortcutOverrides()
      for (const cmd of COMMAND_REGISTRY) {
        const azione = correnti.current[cmd.id]
        if (!azione) continue
        if (!commandBindings(overrides, cmd).includes(combo)) continue
        e.preventDefault()
        azione()
        return
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [attive])
}
