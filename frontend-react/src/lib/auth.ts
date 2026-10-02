// Replica del meccanismo placeholder già in uso in frontend/src/App.vue
// (stessa chiave localStorage AUTH_CREDS_KEY) — con due differenze reali:
// 1. Login silenzioso vero anche in produzione: usare `withBackendUrl('/token')`
//    invece di un path relativo. Un path relativo funzionava solo in dev
//    (proxy Vite) — in produzione il nginx di frontend-react non fa reverse
//    proxy verso il backend (vedi backendUrl.ts), quindi un fetch a
//    "/token" colpiva il proprio nginx invece del backend: try_files lo
//    faceva ricadere sull'index.html della SPA (200 OK, corpo HTML), e
//    `res.json()` lanciava un errore di parsing mai catturato — ogni
//    richiesta autenticata falliva silenziosamente, libreria compresa.
// 2. Se non c'è una sessione valida si arriva a una vera schermata di login
//    — vedi AuthGate.tsx — invece di un fallimento invisibile con app vuota.
//
// Cosa si conserva fra un reload e l'altro è cambiato, ed è una scelta di
// sicurezza: PRIMA qui finivano username e password IN CHIARO, più un
// DEFAULT_CREDS con utente e password cablato nel bundle. Due problemi:
// chiunque avesse accesso al codice servito conosceva le credenziali di
// default, e qualunque script che riuscisse a girare in questa origine
// (il caso reale: gli script dentro un EPUB, vedi ReaderPage.tsx) poteva
// leggere la password vera e riusarla ovunque, per sempre.
// ORA si conserva solo il JWT: dura 7 giorni (ACCESS_TOKEN_EXPIRE_MINUTES),
// scade da solo, non è riutilizzabile per cambiare la password e non dice
// nulla su quali altre credenziali la persona usi altrove.
import { withBackendUrl } from './backendUrl'

// Chiave nuova, non la vecchia 'kolibre_auth_creds': così la password
// salvata dalle versioni precedenti viene abbandonata invece che riletta —
// e la rimuoviamo attivamente al primo avvio, sotto.
const AUTH_TOKEN_KEY = 'kolibre_auth_token'
const LEGACY_CREDS_KEY = 'kolibre_auth_creds'

function readStoredToken(): string | null {
  try {
    // Pulizia una tantum: la password in chiaro di una versione precedente
    // non deve sopravvivere su un browser già usato.
    localStorage.removeItem(LEGACY_CREDS_KEY)
    return localStorage.getItem(AUTH_TOKEN_KEY)
  } catch {
    // localStorage può lanciare (finestra privata, cookie di terze parti
    // bloccati): si resta senza sessione persistente, non si spacca l'app.
    return null
  }
}

function writeStoredToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(AUTH_TOKEN_KEY, token)
    else localStorage.removeItem(AUTH_TOKEN_KEY)
  } catch {
    /* vedi sopra */
  }
}

export function logout(): void {
  writeStoredToken(null)
  authToken = null
}

let authToken: string | null = null
let pendingLogin: Promise<string | null> | null = null

// Usata sia dal login silenzioso sia da un submit esplicito di AuthGate —
// stessa chiamata, `withBackendUrl` la rende corretta in dev e produzione.
// Aggiorna anche il token in memoria: senza, un login manuale riuscito da
// AuthGate lasciava `authToken` a null, e la primissima richiesta reale
// dell'app rifaceva da capo un secondo login silenzioso ridondante.
export async function login(username: string, password: string): Promise<string | null> {
  const body = new URLSearchParams({ username, password })
  try {
    const res = await fetch(withBackendUrl('/token'), { method: 'POST', body })
    if (!res.ok) return null
    const data = (await res.json()) as { access_token: string; token_type: string }
    authToken = data.access_token
    writeStoredToken(authToken)
    return authToken
  } catch {
    // Rete irraggiungibile o risposta non-JSON — mai lasciare che un
    // fallimento di login diventi un'eccezione non gestita che spacca ogni
    // richiesta a valle (era esattamente questo il bug reale sopra).
    return null
  }
}

// Token dalla memoria, altrimenti da localStorage. Non c'è più un "login
// silenzioso" che rigioca le credenziali salvate: se il token manca o è
// scaduto si passa dalla schermata di accesso, una volta a settimana.
// `pendingLogin` resta per il caso in cui più richieste partano insieme
// mentre un login esplicito è in volo.
export async function ensureAuthToken(): Promise<string | null> {
  if (authToken) return authToken
  if (pendingLogin) {
    authToken = await pendingLogin
    return authToken
  }
  authToken = readStoredToken()
  return authToken
}

// Scarta il token OVUNQUE, memoria e localStorage. Chiamata dal middleware
// su 401: tenere quello salvato significherebbe rileggere allo giro dopo lo
// stesso token scaduto che ha appena prodotto il 401 — un ciclo infinito in
// cui AuthGate non mostra mai la schermata di accesso, perché
// ensureAuthToken continuerebbe a restituire qualcosa.
export function clearAuthToken(): void {
  authToken = null
  writeStoredToken(null)
}

// Token già in memoria, senza await. Serve a costruire gli URL passati a
// window.open: un `await` prima di window.open fa scattare il blocco popup
// di Safari/Firefox, che considera "iniziata dall'utente" solo una finestra
// aperta nello stesso tick del click. A quel punto l'app ha per forza già
// fatto login (non si arriva a un pulsante "Scarica" senza aver caricato la
// libreria), quindi il token c'è: null significa sessione scaduta, e il
// download risponderà 401 come qualunque altra richiesta.
export function currentAuthToken(): string | null {
  return authToken
}

export async function authHeaders(): Promise<Record<string, string>> {
  const token = await ensureAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}
