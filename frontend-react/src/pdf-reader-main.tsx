import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import { PdfReaderPage } from './pages/Reader/PdfReaderPage'
import { leggiLingua, ProviderLingua } from './lib/i18n'

// Finestra separata (apertura via window.open, non passa da router.tsx):
// ha bisogno del suo ProviderLingua, non lo eredita da main.tsx.
document.documentElement.lang = leggiLingua()

// Stesso bug reale di reader-main.tsx: useStyleVariant() usa useQuery, e
// senza provider React Query lancia "No QueryClient set" al primo render —
// pagina bianca, nessun altro errore visibile.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('pdf-reader-app')!).render(
  <StrictMode>
    <ProviderLingua>
      <QueryClientProvider client={queryClient}>
        <PdfReaderPage />
      </QueryClientProvider>
    </ProviderLingua>
  </StrictMode>
)
