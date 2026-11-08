import './nodePolyfills'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import { ReaderPage } from './pages/Reader/ReaderPage'
import { leggiLingua, ProviderLingua } from './lib/i18n'
import { AuthGate } from './components/AuthGate'
import { ApriNota } from './pages/Reader/ApriNota'

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


// AuthGate anche qui, e non solo in App.tsx.
//
// Il lettore e' una finestra a se' (window.open su reader.html), quindi non
// passava mai dalla porta di login dell'applicazione: senza una sessione
// valida le sue chiamate rispondevano 401 e si vedeva un lettore rotto, senza
// una via d'uscita. Dal browser in cui si usa Kolibre non si notava, perche'
// il token sta in localStorage ed e' della stessa origine; si notava su un
// altro dispositivo, in una finestra privata, o dopo sette giorni.
//
// E' anche cio' che permette di TOGLIERE il token dalla URL del lettore (vedi
// readerActions.ts): finche' l'unico modo di autenticarsi era quello, il token
// doveva viaggiare in query string — ed essendo il JWT della sessione, chiunque
// copiasse quella URL si portava via sette giorni di accesso.
createRoot(document.getElementById('reader-app')!).render(
  <StrictMode>
    <ProviderLingua>
      <QueryClientProvider client={queryClient}>
        <AuthGate>
          <ApriNota>
            <ReaderPage />
          </ApriNota>
        </AuthGate>
      </QueryClientProvider>
    </ProviderLingua>
  </StrictMode>
)
