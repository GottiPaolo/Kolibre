// Hook di lettura per la Fase 5 (Dispositivi) — file separato da queries.ts
// (non va toccato: condiviso con altre pagine/fasi già in produzione) per
// evitare conflitti di merge con l'agente in lavorazione in parallelo sulla
// Fase 7.
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { Device, DeviceBackup, DeviceFlaggedBook, DeviceSyncHistoryEntry } from '@/types/device'

export function useDevices() {
  return useQuery({
    queryKey: ['devices'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/devices')
      if (error) throw error
      return data as unknown as Device[]
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
      return data as unknown as DeviceFlaggedBook[]
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
      return data as unknown as DeviceSyncHistoryEntry[]
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
      return data as unknown as DeviceBackup[]
    },
    enabled: !!deviceId && enabled,
  })
}
