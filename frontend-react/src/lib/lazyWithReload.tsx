import { lazy } from 'react'
import type { ComponentType } from 'react'

// Avvolge un import() dinamico (pagine in router.tsx, modale Impostazioni in
// SettingsDialogHost.tsx): un chunk con hash nel nome (es.
// AuthorsPage-abc123.js) che non esiste più sul server — tipico subito dopo
// un nuovo build/deploy, con una scheda già aperta sulla build precedente —
// fa fallire il fetch. Il fallback SPA lato server/nginx risponde con
// index.html (text/html) al posto del JS mancante, e React mostra l'errore
// grezzo del browser ("... is not a valid JavaScript MIME type") invece di
// recuperare. Un solo reload automatico scarica la build fresca (nuovo
// index.html → nuovi hash corretti); se fallisce ANCHE dopo, l'errore è
// reale e va propagato, non ricaricato all'infinito — da qui il timestamp
// in sessionStorage.
export function lazyWithReload<T extends { default: ComponentType<unknown> }>(loader: () => Promise<T>) {
  return lazy(() =>
    loader().catch((err) => {
      const key = 'kolibre_chunk_reload_at'
      const last = Number(sessionStorage.getItem(key) || 0)
      if (Date.now() - last > 10_000) {
        sessionStorage.setItem(key, String(Date.now()))
        window.location.reload()
        return new Promise<T>(() => {}) // il reload sta per sostituire il documento, non risolvere mai
      }
      throw err
    })
  )
}
