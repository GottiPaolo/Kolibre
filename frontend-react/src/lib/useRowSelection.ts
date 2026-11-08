import { useCallback, useRef, useState } from 'react'

// Selezione multipla con supporto shift+click per intervallo (stile
// Calibre/Explorer) — click semplice fa toggle della singola riga,
// shift+click seleziona tutto l'intervallo tra l'ultima riga toccata e
// quella corrente. `orderedIds` deve essere l'ordine visivo corrente
// (post-filtro/sort) perché l'intervallo si calcola sugli indici lì dentro.
//
// `lastToggled` è un ref, non uno state: è pura contabilità interna (mai
// letto per il render), tenerlo fuori da useState permette a `selectOnly`/
// `clear` di restare referenzialmente stabili (deps vuote) tra un render e
// l'altro — utile ai chiamanti che passano questi callback fino a righe di
// tabella memoizzate (vedi LibraryTable/LibraryRow).
export function useRowSelection(orderedIds: number[]) {
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const lastToggledRef = useRef<number | null>(null)

  const toggle = useCallback(
    (id: number, event?: { shiftKey?: boolean }) => {
      const lastToggled = lastToggledRef.current
      if (event?.shiftKey && lastToggled != null) {
        const from = orderedIds.indexOf(lastToggled)
        const to = orderedIds.indexOf(id)
        if (from !== -1 && to !== -1) {
          setSelected((prev) => {
            const next = new Set(prev)
            const [start, end] = from <= to ? [from, to] : [to, from]
            const shouldSelect = !next.has(id)
            for (let i = start; i <= end; i++) {
              if (shouldSelect) next.add(orderedIds[i])
              else next.delete(orderedIds[i])
            }
            return next
          })
          // L'ancora NON si sposta su una shift-estensione — resta quella
          // dell'ultimo click "semplice" (stile Explorer/Finder), altrimenti
          // shift-click ripetuti in sequenza calcolano l'intervallo ogni
          // volta dall'ultima riga shift-cliccata invece che da quella di
          // partenza, producendo intervalli sbagliati/imprevedibili — bug
          // riscontrato in uso: con Shift la selezione di intervalli non
          // funzionava.
          return
        }
      }
      setSelected((prev) => {
        const next = new Set(prev)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
      lastToggledRef.current = id
    },
    [orderedIds]
  )

  // Selezione "esclusiva": sostituisce l'intera selezione con un solo id —
  // usato per il click semplice (senza Cmd/Shift), che in Explorer/Finder
  // resetta sempre la selezione multipla. A differenza di un setSelected
  // diretto dal chiamante, aggiorna anche lastToggled: senza, un successivo
  // shift+click userebbe come ancora l'ultimo id toccato con toggle/shift,
  // non l'ultima riga effettivamente cliccata.
  const selectOnly = useCallback((id: number) => {
    setSelected(new Set([id]))
    lastToggledRef.current = id
  }, [])

  const clear = useCallback(() => {
    setSelected(new Set())
    lastToggledRef.current = null
  }, [])

  return { selected, toggle, selectOnly, clear, setSelected }
}
