// Hook di lettura per la pagina Annotazioni — file separato da queries.ts
// (invece di aggiungerci gli hook) per evitare conflitti di merge con altre
// pagine in lavorazione in parallelo.
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { AnnotationDevice, Highlight } from '@/types/annotation'

export function useAnnotations() {
  return useQuery({
    queryKey: ['annotations'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/annotations')
      if (error) throw error
      return data as unknown as Highlight[]
    },
  })
}

// Solo per il filtro "Dispositivo" e per i nomi mostrati sui gruppi orfani —
// nessun altro campo del device serve in questa pagina (la pagina
// Dispositivi vera è un'altra fase, non ancora portata).
export function useAnnotationDevices() {
  return useQuery({
    queryKey: ['annotation-devices'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/devices')
      if (error) throw error
      return data as unknown as AnnotationDevice[]
    },
  })
}
