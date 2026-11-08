import { useCallback, useEffect, useState } from 'react'
import { leggiLocale, rimuoviLocale, scriviLocale } from './memoriaLocale'

// Quali autori si guardano: tutti, o quelli di una biblioteca sola.
//
// La scelta resta finché non si cambia, e vale in due posti che devono
// dire la stessa cosa: l'elenco degli autori e la scheda del singolo
// autore. Se valesse solo sull'elenco, scegliendo "autori di X" e aprendone
// uno ci si troverebbe davanti anche i suoi libri che in X non ci sono — e
// il filtro sembrerebbe rotto invece che parziale.
//
// `null` = tutte le biblioteche.

const CHIAVE = 'kolibre_autori_biblioteca'
const EVENTO = 'kolibre-autori-biblioteca'

export function leggiAmbitoAutori(): string | null {
  try {
    return leggiLocale(CHIAVE) || null
  } catch {
    // Finestra privata o cookie bloccati: si lavora su tutte, che è il
    // comportamento di sempre.
    return null
  }
}

export function scriviAmbitoAutori(folder: string | null): void {
  try {
    if (folder) scriviLocale(CHIAVE, folder)
    else rimuoviLocale(CHIAVE)
  } catch {
    // Non poter ricordare la scelta non deve impedire di farla.
  }
  // Un evento nostro, non "storage": quello scatta solo nelle ALTRE schede,
  // mai in quella che ha scritto — e qui serve proprio che le due pagine
  // aperte in questa scheda si accorgano del cambio.
  window.dispatchEvent(new CustomEvent(EVENTO))
}

/** La scelta corrente, che si aggiorna da sola quando qualcuno la cambia. */
export function useAmbitoAutori(): [string | null, (folder: string | null) => void] {
  const [ambito, setAmbito] = useState<string | null>(() => leggiAmbitoAutori())

  useEffect(() => {
    const aggiorna = () => setAmbito(leggiAmbitoAutori())
    window.addEventListener(EVENTO, aggiorna)
    window.addEventListener('storage', aggiorna)
    return () => {
      window.removeEventListener(EVENTO, aggiorna)
      window.removeEventListener('storage', aggiorna)
    }
  }, [])

  const cambia = useCallback((folder: string | null) => {
    scriviAmbitoAutori(folder)
    setAmbito(folder)
  }, [])

  return [ambito, cambia]
}

// ── Tabella o griglia ────────────────────────────────────────────────────
//
// La scelta resta finché non si cambia, come già fa la Libreria (vedi
// loadViewMode in lib/libraryColumns.ts). Chiesto il 01/10/2026: chi lavora
// in tabella ci lavora sempre, e ritrovare la griglia a ogni apertura
// significa rifare lo stesso clic ogni volta.
//
// Chiave separata da quella della Libreria, di proposito: le due pagine hanno
// viste diverse — la Libreria ne ha tre, qui sono due — e soprattutto non c'è
// motivo perché scegliere la tabella dei libri debba decidere anche quella
// degli autori.

export type VistaAutori = 'grid' | 'table'

const CHIAVE_VISTA = 'kolibre_autori_vista'

export function leggiVistaAutori(): VistaAutori {
  try {
    return leggiLocale(CHIAVE_VISTA) === 'table' ? 'table' : 'grid'
  } catch {
    // Finestra privata o cookie bloccati: la griglia, che è il comportamento
    // di sempre.
    return 'grid'
  }
}

export function scriviVistaAutori(vista: VistaAutori): void {
  try {
    scriviLocale(CHIAVE_VISTA, vista)
  } catch {
    // Non poter ricordare la scelta non deve impedire di farla.
  }
}

/** La vista corrente, che si ricorda da sé. */
export function useVistaAutori(): [VistaAutori, (v: VistaAutori) => void] {
  const [vista, setVista] = useState<VistaAutori>(() => leggiVistaAutori())
  const cambia = useCallback((v: VistaAutori) => {
    scriviVistaAutori(v)
    setVista(v)
  }, [])
  return [vista, cambia]
}

