import { useCallback, useState } from 'react'
import type { Valori } from './i18n'
import { leggiLocale, scriviLocale } from './memoriaLocale'

// Quale delle tre viste delle annotazioni si sta usando.
//
// Tre e non una perché le tre rispondono a domande diverse, e quale sia la
// domanda vera lo dirà l'uso: la lettura serve a RISCOPRIRE, lo scaffale a
// tornare a un libro, l'indice a RITROVARE un passaggio preciso. Scelta del
// 01/10/2026: si implementano tutte e tre con la possibilità di alternarle,
// per poi tenere quella che all'uso risulta la migliore. Finché la scelta
// non è fatta convivono — e questa chiave è come si ricorda l'ultima.
//
// La scelta resta finché non si cambia, come per la vista degli autori e per
// quella della Libreria.

export type VistaAnnotazioni = 'lettura' | 'scaffale' | 'indice'

const VISTE_IDS: VistaAnnotazioni[] = ['lettura', 'scaffale', 'indice']

// Funzione e non una costante, come fixedColumnLabels in lib/libraryColumns.ts:
// nome e a_cosa_serve sono testo visibile e devono ricalcolarsi al cambio lingua.
export function VISTE(
  t: (chiave: string, valori?: Valori) => string
): { id: VistaAnnotazioni; nome: string; a_cosa_serve: string }[] {
  return [
    { id: 'lettura', nome: t('annotations.view.reading.name'), a_cosa_serve: t('annotations.view.reading.description') },
    { id: 'scaffale', nome: t('annotations.view.shelf.name'), a_cosa_serve: t('annotations.view.shelf.description') },
    { id: 'indice', nome: t('annotations.view.index.name'), a_cosa_serve: t('annotations.view.index.description') },
  ]
}

const CHIAVE = 'kolibre_annotazioni_vista'
const PREDEFINITA: VistaAnnotazioni = 'lettura'

export function leggiVistaAnnotazioni(): VistaAnnotazioni {
  try {
    const salvata = leggiLocale(CHIAVE)
    return VISTE_IDS.includes(salvata as VistaAnnotazioni) ? (salvata as VistaAnnotazioni) : PREDEFINITA
  } catch {
    // Finestra privata o cookie bloccati: la vista di partenza.
    return PREDEFINITA
  }
}

export function scriviVistaAnnotazioni(vista: VistaAnnotazioni): void {
  try {
    scriviLocale(CHIAVE, vista)
  } catch {
    // Non poter ricordare la scelta non deve impedire di farla.
  }
}

export function useVistaAnnotazioni(): [VistaAnnotazioni, (v: VistaAnnotazioni) => void] {
  const [vista, setVista] = useState<VistaAnnotazioni>(() => leggiVistaAnnotazioni())
  const cambia = useCallback((v: VistaAnnotazioni) => {
    scriviVistaAnnotazioni(v)
    setVista(v)
  }, [])
  return [vista, cambia]
}
