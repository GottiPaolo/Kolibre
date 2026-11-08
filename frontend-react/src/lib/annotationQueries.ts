// Hook di lettura per la pagina Annotazioni — file separato da queries.ts
// (invece di aggiungerci gli hook) per evitare conflitti di merge con altre
// pagine in lavorazione in parallelo.
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export function useAnnotations() {
  return useQuery({
    queryKey: ['annotations'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/annotations')
      if (error) throw error
      return data
    },
  })
}

// Serve per il filtro "Dispositivo" e per i nomi mostrati sui gruppi orfani.
// Di tutto il dispositivo questa pagina usa `id` e `name`: dal 05/11/2026 il
// tipo è però quello intero dello schema e non un ritaglio scritto a mano —
// restringere a due campi un dato che ne porta venti non protegge da niente
// e nasconde cosa c'è davvero nella risposta.
export function useAnnotationDevices() {
  return useQuery({
    queryKey: ['annotation-devices'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/devices')
      if (error) throw error
      return data
    },
  })
}
