// Spia di connessione — visibile SOLO quando il server non risponde.
//
// Scelta esplicita: nessun indicatore sempre acceso che dica
// "sei connesso" (rumore per una cosa che è vera il 99,9% del tempo), ma un
// avviso quando NON lo sei. Prima non c'era nulla: con il backend spento
// ogni pagina mostrava semplicemente il suo vuoto — "Nessun libro",
// "Nessun autore trovato", "Nessun dispositivo configurato" — e da telefono
// era indistinguibile da un dato vero.
//
// Come capisce che siamo offline: non fa polling a vuoto. Resta in ascolto
// sulla cache di React Query e si sveglia solo quando una query FALLISCE;
// a quel punto interroga /api/kolibre/version (l'unico endpoint senza
// autenticazione, esiste apposta per questo) finché non risponde. Appena
// risponde, l'avviso sparisce e le query in errore vengono rilanciate, così
// l'app si ripara da sola senza che si debba ricaricare la pagina.
import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { WifiOff } from 'lucide-react'
import { withBackendUrl } from '@/lib/backendUrl'
import { useLingua } from '@/lib/i18n'

const PING_INTERVAL_MS = 5000

async function serverIsReachable(): Promise<boolean> {
  try {
    const res = await fetch(withBackendUrl('/api/kolibre/version'), { cache: 'no-store' })
    return res.ok
  } catch {
    return false
  }
}

export function ConnectionStatus() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const [offline, setOffline] = useState(false)
  // Un solo ciclo di ping alla volta, qualunque sia il numero di query che
  // falliscono insieme (con il backend spento falliscono tutte in blocco).
  const pollingRef = useRef(false)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined

    async function check() {
      const reachable = await serverIsReachable()
      if (cancelled) return
      setOffline(!reachable)
      if (reachable) {
        pollingRef.current = false
        // Tornati su: rilancia ciò che nel frattempo è diventato stantio,
        // così le pagine aperte si ripopolano senza ricaricare.
        void queryClient.refetchQueries({ type: 'all', stale: true })
        return
      }
      timer = window.setTimeout(check, PING_INTERVAL_MS)
    }

    // Una query fallita è il solo trigger: finché tutto va, questo
    // componente non fa una singola richiesta di rete.
    const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
      if (event.query.state.status !== 'error' || pollingRef.current) return
      pollingRef.current = true
      void check()
    })

    return () => {
      cancelled = true
      pollingRef.current = false
      unsubscribe()
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [queryClient])

  if (!offline) return null

  return (
    <div
      role="status"
      className="fixed inset-x-0 bottom-0 z-50 flex items-center justify-center gap-2 border-t border-destructive/40 bg-destructive/15 px-4 py-2 text-[13px] text-destructive-foreground backdrop-blur"
    >
      <WifiOff className="size-4 shrink-0" />
      <span>{t('common.connection.offline')}</span>
    </div>
  )
}
