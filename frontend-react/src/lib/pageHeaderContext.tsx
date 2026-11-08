import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

// Lo spazio in alto (ex barra di ricerca decorativa, mai realmente
// funzionante) mostra il titolo della pagina — es. il nome della libreria
// attiva — impostato dalla pagina corrente stessa via useSetPageHeader.
//
// Il titolo puo' anche ESSERE un selettore. Nella Libreria il titolo e' il
// nome della biblioteca attiva, e la barra degli attrezzi ne teneva un menu'
// a tendina con lo stesso nome dentro: due posti per la stessa cosa, a dieci
// centimetri uno dall'altro. Ora le voci arrivano qui e il titolo si apre.
//
// **Due contesti e non uno** perche' il valore scritto cambia identita' a ogni
// cambio di titolo: se chi scrive leggesse dallo stesso oggetto, il suo
// effetto si riattiverebbe a ogni scrittura e non finirebbe mai. Lo scrittore
// e' `setStato` di useState, che React garantisce stabile.

export interface VoceTitolo {
  id: string | number
  nome: string
}

interface StatoTitolo {
  header: string
  voci: VoceTitolo[]
  scegli: (id: string | number) => void
}

const VUOTO: StatoTitolo = { header: '', voci: [], scegli: () => {} }

const LeggiTitolo = createContext<StatoTitolo>(VUOTO)
const ScriviTitolo = createContext<((s: StatoTitolo) => void) | null>(null)

export function PageHeaderProvider({ children }: { children: ReactNode }) {
  const [stato, setStato] = useState<StatoTitolo>(VUOTO)
  return (
    <ScriviTitolo.Provider value={setStato}>
      <LeggiTitolo.Provider value={stato}>{children}</LeggiTitolo.Provider>
    </ScriviTitolo.Provider>
  )
}

export function usePageHeader(): StatoTitolo {
  return useContext(LeggiTitolo)
}

/**
 * Imposta il titolo della pagina, e facoltativamente le alternative fra cui
 * scegliere toccandolo.
 *
 * `voci` e `onScegli` possono cambiare identita' a ogni render senza che il
 * loro contenuto cambi — un `.map()` nel corpo del componente lo fa sempre.
 * Metterli fra le dipendenze dell'effetto vorrebbe dire riscrivere lo stato
 * del titolo a ogni render, cioe' un ciclo. Si confronta quindi la loro
 * FIRMA, e i valori veri viaggiano in un ref.
 */
export function useSetPageHeader(title: string, voci?: VoceTitolo[], onScegli?: (id: string | number) => void) {
  const scrivi = useContext(ScriviTitolo)
  if (!scrivi) throw new Error('useSetPageHeader deve essere usato dentro <PageHeaderProvider>')
  const ultimi = useRef({ voci, onScegli })
  ultimi.current = { voci, onScegli }
  const firma = (voci ?? []).map((v) => `${v.id}\u0000${v.nome}`).join('\u0001')
  useEffect(() => {
    scrivi({
      header: title,
      voci: ultimi.current.voci ?? [],
      scegli: (id) => ultimi.current.onScegli?.(id),
    })
  }, [scrivi, title, firma])
}
