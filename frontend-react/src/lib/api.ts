import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from '@/api/schema'
import { authHeaders, clearAuthToken } from './auth'
import { baseUrl, withBackendUrl } from './backendUrl'

export const api = createClient<paths>({ baseUrl })

// Re-esportato per compatibilità con i moduli che già lo importano da qui
// (la definizione vera vive in backendUrl.ts, per evitare un import
// circolare con auth.ts).
export { withBackendUrl }

// Inietta l'header Authorization su ogni richiesta (login silenzioso se
// serve — vedi auth.ts) e, su 401, scarta il token in memoria così la
// richiesta successiva rifà il login invece di ripetere lo stesso 401.
const authMiddleware: Middleware = {
  async onRequest({ request }) {
    const headers = await authHeaders()
    for (const [key, value] of Object.entries(headers)) {
      request.headers.set(key, value)
    }
    return request
  },
  async onResponse({ response }) {
    if (response.status === 401) clearAuthToken()
    return response
  },
}

api.use(authMiddleware)
