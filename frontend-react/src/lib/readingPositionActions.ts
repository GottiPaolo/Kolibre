// Posizione di lettura — condiviso tra il reader EPUB e quello PDF (Fase 9).
// Stessa tabella ReadingPosition "ultima posizione universale" già usata da
// KOSync (dispositivi) e dal bulk /books/reading-progress della Libreria —
// vedi il commento sull'endpoint in schema.d.ts: `cfi` torna valorizzato
// solo se l'ULTIMA scrittura è arrivata da un web reader (altrimenti è uno
// xpointer/numero di pagina KOReader, inutile a epub.js) — chi legge deve
// sempre saper ripiegare su `percentage` quando `cfi` è null. Il reader PDF
// non ha alcun concetto di CFI: manda sempre e solo `percentage`.
import { api } from './api'

export interface ReadingPosition {
  percentage: number
  cfi: string | null
}

export async function getReadingPosition(library: string, bookId: number): Promise<ReadingPosition | null> {
  const { data, error } = await api.GET('/api/kolibre/books/{id}/reading-position', {
    params: { path: { id: bookId }, query: { library } },
  })
  if (error) throw error
  return data as unknown as ReadingPosition | null
}

export async function putReadingPosition(
  library: string,
  bookId: number,
  position: ReadingPosition,
  opts?: { keepalive?: boolean }
): Promise<void> {
  const { error } = await api.PUT('/api/kolibre/books/{id}/reading-position', {
    params: { path: { id: bookId }, query: { library } },
    body: position as unknown as Record<string, unknown>,
    ...(opts?.keepalive ? { keepalive: true } : {}),
  })
  if (error) throw error
}
