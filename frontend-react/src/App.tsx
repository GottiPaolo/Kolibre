import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import { router } from './router'
import { AuthGate } from './components/AuthGate'

// Default di React Query (staleTime 0, refetchOnWindowFocus true) fanno
// ripartire un fetch di rete ad ogni singolo mount/focus — su una libreria
// reale di centinaia di libri questo significa ri-scaricare e ri-renderizzare
// l'intera tabella ogni volta che si torna sulla pagina o si cambia tab.
// I dati di una libreria personale non cambiano al secondo: un minuto di
// freshness elimina quasi tutti i refetch superflui senza percepire dati
// stantii.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        <RouterProvider router={router} />
      </AuthGate>
    </QueryClientProvider>
  )
}
