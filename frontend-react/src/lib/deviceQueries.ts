// Hook di lettura per la pagina Dispositivi.
//
// Dal 05/11/2026 **nessuna asserzione**: le quattro risposte dichiarano la
// loro forma nello schema, quindi il tipo di `data` e' gia' quello giusto e
// non c'e' niente da affermare. Erano quattro `as unknown as`.
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export function useDevices() {
  return useQuery({
    queryKey: ['devices'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/devices')
      if (error) throw error
      return data
    },
  })
}

export function useDeviceFlaggedBooks(deviceId: number | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['device-flagged-books', deviceId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/devices/{device_id}/flagged-books', {
        params: { path: { device_id: deviceId! } },
      })
      if (error) throw error
      return data
    },
    enabled: !!deviceId && enabled,
  })
}

// limit=30 fisso: stesso default usato dal Vue esistente (nessun controllo
// di paginazione nella UI, il backend ne accetta comunque uno più alto se
// servisse in futuro).
export function useDeviceSyncHistory(deviceId: number | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['device-sync-history', deviceId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/devices/{device_id}/sync-history', {
        params: { path: { device_id: deviceId! }, query: { limit: 30 } },
      })
      if (error) throw error
      return data
    },
    enabled: !!deviceId && enabled,
  })
}

export function useDeviceBackups(deviceId: number | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['device-backups', deviceId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/devices/{device_id}/backups', {
        params: { path: { device_id: deviceId! } },
      })
      if (error) throw error
      return data
    },
    enabled: !!deviceId && enabled,
  })
}
