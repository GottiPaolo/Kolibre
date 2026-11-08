// Azioni reali per la tab "Profilo" di Impostazioni (Fase 8) — porting 1:1
// degli endpoint usati da frontend/src/App.vue (loadProfile/saveProfile/
// uploadProfilePhoto/removeProfilePhoto): backend/app/api/users.py espone
// GET+PUT /api/users/me e POST+DELETE /api/users/me/photo, entrambi già
// tipizzati in api/schema.d.ts. File separato da queries.ts (che non va
// toccato, in uso in parallelo da un altro agente) per evitare conflitti.
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export interface Me {
  id: number
  username: string
  fullname?: string | null
  photo_url?: string | null
  is_admin: boolean
  created_at: string
}

export function useMe() {
  return useQuery({
    queryKey: ['users', 'me'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/users/me')
      if (error) throw error
      return data as unknown as Me
    },
  })
}

export interface ProfileUpdatePayload {
  fullname?: string
  username?: string
  password?: string
}

export async function updateProfile(payload: ProfileUpdatePayload): Promise<Me> {
  const { data, error } = await api.PUT('/api/users/me', { body: payload })
  if (error) throw error
  return data as unknown as Me
}

export async function uploadProfilePhoto(file: File): Promise<Me> {
  const { data, error } = await api.POST('/api/users/me/photo', {
    // @ts-expect-error openapi-fetch vuole il body JSON-shaped anche per multipart; il bodySerializer sotto lo trasforma davvero (stesso pattern di lib/authorActions.ts).
    body: { file },
    bodySerializer() {
      const form = new FormData()
      form.append('file', file)
      return form
    },
  })
  if (error) throw error
  return data as unknown as Me
}

export async function removeProfilePhoto(): Promise<Me> {
  const { data, error } = await api.DELETE('/api/users/me/photo')
  if (error) throw error
  return data as unknown as Me
}
