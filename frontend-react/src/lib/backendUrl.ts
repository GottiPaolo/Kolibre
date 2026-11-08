import { currentAuthToken } from './auth'

// Estratto in un modulo proprio (non dentro api.ts) per evitare un import
// circolare: sia api.ts sia auth.ts hanno bisogno di questo, e auth.ts è
// già importato DA api.ts (per iniettare l'header Authorization).
//
// Dal 01/10/2026 questo modulo importa a sua volta `currentAuthToken` da
// auth.ts, quindi un ciclo c'è: auth → backendUrl → auth. È innocuo e
// deliberato — nessuno dei due usa l'altro mentre il modulo viene valutato,
// solo dentro funzioni chiamate dopo, e i binding ESM sono vivi. Rifarlo con
// una registrazione (`registraLettoreToken`) sarebbe più pulito a vedersi ma
// introdurrebbe un guasto peggiore: se qualcuno importasse backendUrl senza
// passare da auth, il token non verrebbe registrato e le immagini
// smetterebbero di caricarsi in silenzio.
const BACKEND_PORT = import.meta.env.VITE_BACKEND_PORT || '8081'

// Base URL di produzione: il nuovo nginx di frontend-react non fa reverse
// proxy verso il backend (a differenza di quello di frontend/, che lo fa —
// vedi frontend/nginx.conf) — CORS è già aperto (allow_origins="*" +
// allow_credentials=True in backend/app/main.py), quindi il browser chiama
// il backend direttamente. In dev, invece, il proxy di vite.config.ts si
// occupa di '/api'/'/token' e questa costante resta stringa vuota (relativa),
// stesso principio già usato da frontend/vite.config.js.
export const baseUrl = import.meta.env.DEV
  ? ''
  : `${window.location.protocol}//${window.location.hostname}:${BACKEND_PORT}`

// Le rotte che servono IMMAGINI e font, e che dal 01/10/2026 vogliono un
// token. Un `<img src>` non puo' allegare un header `Authorization`, e lo
// stesso vale per un `url()` dentro una regola @font-face: l'unico posto dove
// la credenziale puo' viaggiare e' la query. Il backend le accetta da li'
// (`auth.utente_o_dispositivo`), ed e' lo stesso meccanismo gia' usato dai
// download aperti con window.open.
//
// Prima erano senza autenticazione del tutto: chiunque raggiungesse il server
// poteva sfogliare le copertine di tutta la biblioteca senza accedere, e gli
// id sono sequenziali.
//
// Il prezzo, detto: un token in query finisce nei log del server e nella
// cronologia del browser. Per un'immagine e' un compromesso accettabile; per
// qualunque altra cosa si continua a usare l'header.
const ROTTE_CON_TOKEN = /\/(cover|photo|file)(\/thumbnail)?(\?|$)/

export function withBackendUrl(path: string): string {
  if (path.startsWith('http')) return path
  const completo = `${baseUrl}${path}`
  if (!ROTTE_CON_TOKEN.test(path)) return completo
  const token = currentAuthToken()
  if (!token) return completo
  return `${completo}${completo.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
}
