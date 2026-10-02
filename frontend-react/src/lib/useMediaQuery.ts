import { useEffect, useState } from 'react'

// Soglia allineata al breakpoint "md" di Tailwind (768px, default v4) — la
// stessa usata dalle classi md: in Layout.tsx e nelle pagine Libreria/
// Statistiche/Dispositivi, così la scelta JS (quale componente renderizzare)
// e quella CSS (come si dispone) concordano sempre sullo stesso punto.
const DESKTOP_QUERY = '(min-width: 768px)'

// Serve solo dove il breakpoint deve guidare una scelta React (quale
// componente montare, es. LibraryTable vs LibraryCards) — un puro reflow via
// classi md: non ha bisogno di questo hook.
export function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(DESKTOP_QUERY).matches
  )

  useEffect(() => {
    const mql = window.matchMedia(DESKTOP_QUERY)
    const handler = (e: MediaQueryListEvent) => setIsDesktop(e.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])

  return isDesktop
}
