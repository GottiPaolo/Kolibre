// Azioni di manutenzione per-libreria per la tab Tools (Fase 7,
// "Operazioni di Massa") — backend/app/api/libraries.py. A differenza del
// resto della pagina Ingest, questi due endpoint esistono e funzionano nel
// backend ma non sono mai stati agganciati a NESSUNA UI nel Vue esistente
// (verificato: nessun'occorrenza di "rescan" o "recompute-hashes" in
// App.vue) — solo /recompute-pages lo è, ma in Impostazioni → Librerie
// ("Ricalcola per libreria attiva"), non in Tools; quella pagina non è
// ancora stata migrata, quindi qui viene lasciata dov'è per non duplicarla
// su due pagine diverse. Esposti qui perché corrispondono esattamente alla
// descrizione della sezione ("operazioni che operano sull'intera libreria
// o su gruppi di libri") — vedi il report della Fase 7 per i dettagli.
import { api } from './api'

export async function rescanLibrary(folderName: string): Promise<{ status: string; imported: number }> {
  const { data, error } = await api.POST('/api/kolibre/libraries/{name}/rescan', {
    params: { path: { name: folderName } },
  })
  if (error) throw error
  return data as unknown as { status: string; imported: number }
}

export async function recomputeLibraryHashes(folderName: string): Promise<{ status: string; updated: number }> {
  const { data, error } = await api.POST('/api/kolibre/libraries/{name}/recompute-hashes', {
    params: { path: { name: folderName } },
  })
  if (error) throw error
  return data as unknown as { status: string; updated: number }
}

// ── Cartelle dei libri ────────────────────────────────────────────────
//
// Una biblioteca Calibre tiene i file in `<primo autore>/<titolo> (<id>)`,
// col file di ogni formato chiamato `<titolo> - <primo autore>`. Il percorso
// vero pero' sta nel database: un libro a cui si e' cambiato l'autore
// continua a funzionare anche se resta nella cartella del nome vecchio.
// Continua a funzionare, ma la biblioteca sul disco smette di corrispondere
// ai metadati — e quella e' la cartella che uno apre quando non ha Kolibre
// davanti.

export interface LibroFuoriPosto {
  id: number
  title: string
  author: string
  path: string
  new_path: string
  /** I file dentro la cartella non si chiamano "Titolo - Autore". */
  rename_files: boolean
  /** Perché risulta fuori posto, in una riga. */
  reason: string
  missing: boolean
}

export interface EsitoAnalisiPercorsi {
  /** Quanti libri hanno la cartella intestata all'autore sbagliato. */
  total: number
  /** Di questi, quanti si possono davvero spostare. */
  movable: number
  /** Quanti hanno la cartella mancante sul disco: si segnalano, non si spostano. */
  missing: number
  sample: LibroFuoriPosto[]
  missing_sample: LibroFuoriPosto[]
}

export async function analyzeBookPaths(folderName: string): Promise<EsitoAnalisiPercorsi> {
  const { data, error } = await api.GET('/api/kolibre/libraries/{name}/book-paths', {
    params: { path: { name: folderName } },
  })
  if (error) throw error
  return data as unknown as EsitoAnalisiPercorsi
}

export async function repairBookPaths(
  folderName: string,
  limit: number
): Promise<{ moved: number; remaining: number; failed: { id: number; title: string; error: string }[] }> {
  const { data, error } = await api.POST('/api/kolibre/libraries/{name}/book-paths/repair', {
    params: { path: { name: folderName } },
    body: { limit },
  })
  if (error) throw error
  return data as unknown as { moved: number; remaining: number; failed: { id: number; title: string; error: string }[] }
}
