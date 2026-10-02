import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

// Lo spazio in alto (ex barra di ricerca decorativa, mai realmente
// funzionante) ora mostra un titolo di pagina — es. il nome della libreria
// attiva — impostato dalla pagina corrente stessa via useSetPageHeader.
const PageHeaderContext = createContext<{ header: string; setHeader: (h: string) => void } | null>(null)

export function PageHeaderProvider({ children }: { children: ReactNode }) {
  const [header, setHeader] = useState('')
  return <PageHeaderContext.Provider value={{ header, setHeader }}>{children}</PageHeaderContext.Provider>
}

export function usePageHeader() {
  const ctx = useContext(PageHeaderContext)
  if (!ctx) throw new Error('usePageHeader deve essere usato dentro <PageHeaderProvider>')
  return ctx.header
}

export function useSetPageHeader(title: string) {
  const ctx = useContext(PageHeaderContext)
  if (!ctx) throw new Error('useSetPageHeader deve essere usato dentro <PageHeaderProvider>')
  useEffect(() => {
    ctx.setHeader(title)
  }, [ctx, title])
}
