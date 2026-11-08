// Download plugin desktop/device (Fase 8, parte 2 — tab Dispositivi e
// Integrazioni) — porting da frontend/src/App.vue (downloadMockPlugin/
// confirmDownloadPlugin, downloadCalibrePlugin/confirmDownloadCalibrePlugin,
// downloadObsidianPlugin/confirmDownloadObsidianPlugin, guessPluginServerUrl/
// guessFrontendPort/triggerBlobDownload, righe ~6369-6501). Backend reale:
// backend/app/api/tools.py (server-port/frontend-port/plugins/calibre/
// plugins/obsidian/plugins/koreader) — verificato, non mock.
//
// Le tre zip sono servite come FileResponse binaria: openapi-fetch tenterebbe
// di fare JSON.parse del corpo, quindi qui si usa un fetch grezzo verso
// withBackendUrl(...) — stesso schema già usato da bookActions.ts::
// convertBookFormat per lo stesso motivo.
import { authHeaders, ensureAuthToken } from './auth'
import { withBackendUrl } from './backendUrl'
import { t } from './i18n'

let cachedServerPort: number | null = null
// Indirizzo LAN-raggiungibile del backend da suggerire all'utente prima del
// download: BACKEND_URL/baseUrl nel browser è spesso "localhost", che un
// KOReader/Calibre/Obsidian su un'altra macchina non può raggiungere — vedi
// config.PUBLIC_BACKEND_PORT lato server.
export async function guessBackendPort(): Promise<number> {
  if (cachedServerPort === null) {
    try {
      const res = await fetch(withBackendUrl('/api/tools/server-port'))
      cachedServerPort = res.ok ? ((await res.json()) as { port: number }).port : 8081
    } catch {
      cachedServerPort = 8081
    }
  }
  return cachedServerPort
}

export async function guessPluginServerUrl(): Promise<string> {
  const port = await guessBackendPort()
  return `${window.location.protocol}//${window.location.hostname}:${port}`
}

let cachedFrontendPort: number | null = null
export async function guessFrontendPort(): Promise<number> {
  if (cachedFrontendPort === null) {
    try {
      const res = await fetch(withBackendUrl('/api/tools/frontend-port'))
      cachedFrontendPort = res.ok ? ((await res.json()) as { port: number }).port : 8080
    } catch {
      cachedFrontendPort = 8080
    }
  }
  return cachedFrontendPort
}

async function downloadBlob(url: string, filename: string, withAuth: boolean): Promise<void> {
  const res = await fetch(url, withAuth ? { headers: await authHeaders() } : undefined)
  if (!res.ok) throw new Error(t('settings.plugins.httpError', { status: res.status }))
  const blob = await res.blob()
  const objectUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objectUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(objectUrl), 2000)
}

// device_id + server_url pre-configurano gconfig.lua col device_token —
// niente altro da scaricare/impostare a mano su KOReader. L'endpoint
// richiede un utente autenticato (proprietario del dispositivo): a
// differenza del Vue esistente (che non poteva allegare un header e passava
// ?token= in query), qui il download passa per fetch(), quindi l'header
// Authorization funziona normalmente.
export async function downloadKoreaderPlugin(deviceId: number, serverUrl: string): Promise<void> {
  const params = new URLSearchParams({ device_id: String(deviceId), server_url: serverUrl })
  await downloadBlob(withBackendUrl(`/api/tools/plugins/koreader?${params.toString()}`), 'kolibre.koplugin.zip', true)
}

// server_url/frontend_url/username/token sono tutti opzionali: quando
// presenti il backend li scrive in kolibre_preconfig.json dentro lo zip,
// così il plugin Calibre si autoconfigura al primo avvio (login già
// effettuato). `token` in query serve a due cose diverse che per fortuna
// coincidono: è il JWT da imprimere nel plugin scaricato, ed è anche quello
// che autentica QUESTA richiesta da quando /api/tools richiede un utente
// (get_current_user_flexible legge sia l'header sia ?token=). L'header lo
// mandiamo comunque, così l'URL resta valido anche se un domani il token
// impresso e quello di sessione dovessero divergere.
export async function downloadCalibrePlugin(
  host: string,
  backendPort: string,
  frontendPort: string,
  username: string
): Promise<void> {
  const serverUrl = `http://${host}:${backendPort}`
  const frontendUrl = frontendPort ? `http://${host}:${frontendPort}` : ''
  const token = await ensureAuthToken()
  const params = new URLSearchParams({
    server_url: serverUrl,
    frontend_url: frontendUrl,
    username,
    token: token || '',
  })
  await downloadBlob(withBackendUrl(`/api/tools/plugins/calibre?${params.toString()}`), 'kolibre_sync.zip', true)
}

// Stessa logica del plugin Calibre, ma scrive un data.json reale (Obsidian
// legge le impostazioni plugin da lì) invece di una risorsa indiretta.
export async function downloadObsidianPlugin(serverUrl: string, username: string): Promise<void> {
  const token = await ensureAuthToken()
  const params = new URLSearchParams({ server_url: serverUrl, username, token: token || '' })
  await downloadBlob(withBackendUrl(`/api/tools/plugins/obsidian?${params.toString()}`), 'kolibre-highlights.zip', true)
}

// Username dell'utente loggato, per precompilare il campo nei plugin
// scaricati — nessun hook condiviso lo espone ancora (queries.ts non va
// toccato, la tab Profilo è di competenza dell'altro agente in parallelo),
// quindi qui è una chiamata diretta e "usa e getta", non un hook react-query.
export async function fetchCurrentUsername(): Promise<string> {
  try {
    const res = await fetch(withBackendUrl('/api/users/me'), { headers: await authHeaders() })
    if (!res.ok) return ''
    const data = (await res.json()) as { username?: string }
    return typeof data.username === 'string' ? data.username : ''
  } catch {
    return ''
  }
}
