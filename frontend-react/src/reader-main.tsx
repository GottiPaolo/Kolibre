import './nodePolyfills'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import { ReaderPage } from './pages/Reader/ReaderPage'
import { leggiLingua, ProviderLingua } from './lib/i18n'

// Finestra separata (apertura via window.open, non passa da router.tsx):
// ha bisogno del suo ProviderLingua, non lo eredita da main.tsx.
document.documentElement.lang = leggiLingua()

// useStyleVariant() (tema avanzato) usa useQuery internamente — senza questo
// provider React Query lancia "No QueryClient set" al primo render e la
// finestra del reader resta bianca, senza altro errore visibile (bug reale,
// presente da quando il tema avanzato ha aggiunto useStyleVariant a
// ReaderPage senza che questo entry point separato da App.tsx venisse
// aggiornato di conseguenza).
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('reader-app')!).render(
  <StrictMode>
    <ProviderLingua>
      <QueryClientProvider client={queryClient}>
        <ReaderPage />
      </QueryClientProvider>
    </ProviderLingua>
  </StrictMode>
)
