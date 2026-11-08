// Scrittura per Statistiche, separata da statsQueries.ts (lettura) — stessa
// convenzione già in uso per Annotazioni (annotationQueries.ts/
// annotationActions.ts) e per il chart builder (chartBuilderActions.ts).
import { api } from './api'

export interface PairOrphanSessionsResult {
  status: string
  sessions_migrated: number
  sessions_already_resolved: number
}

// "Accoppia manualmente" per le sessioni di lettura orfane — vedi
// backend/app/api/stats.py::pair_orphan_sessions. Globale per md5: risolve
// in un colpo tutte le sessioni orfane con questo hash (di qualunque
// dispositivo) E ogni futuro upload che riporti lo stesso md5, non solo
// questo import storico.
export async function pairOrphanSessions(md5: string, library: string, calibreBookId: number): Promise<PairOrphanSessionsResult> {
  const { data, error } = await api.POST('/api/kolibre/stats/orphan-sessions/pair', {
    body: { md5, library, calibre_book_id: calibreBookId },
  })
  if (error) throw error
  return data as unknown as PairOrphanSessionsResult
}

export interface DiscardOrphanSessionsResult {
  status: string
  sessions_discarded: number
}

// "Scarta" per le sessioni di lettura orfane — complemento di
// pairOrphanSessions: per un titolo probabile che semplicemente non vale la
// pena tracciare nelle statistiche (non un'ipotesi sbagliata da correggere).
// Permanente: backend/app/api/stats.py::discard_orphan_sessions ricorda la
// decisione per md5, così un futuro sync dello stesso hash non la riproduce.
export async function discardOrphanSessions(md5: string): Promise<DiscardOrphanSessionsResult> {
  const { data, error } = await api.POST('/api/kolibre/stats/orphan-sessions/discard', {
    body: { md5 },
  })
  if (error) throw error
  return data as unknown as DiscardOrphanSessionsResult
}
