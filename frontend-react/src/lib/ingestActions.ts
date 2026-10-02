// Porting 1:1 degli endpoint reali usati da frontend/src/App.vue per la
// sezione Ingest (uploadIngestFiles, importIngest) — backend/app/api/ingest.py.
// upload e get-file richiedono auth (get_current_user_flexible: header
// Authorization O ?token=), import-book no (verificato: nessun
// Depends(auth...) nella sua firma) — il client `api` inietta comunque
// l'header su ogni richiesta, non fa differenza.
import { api, withBackendUrl } from './api'
import { ensureAuthToken } from './auth'
import type { IngestedBook, IngestRejectedFile } from '@/types/ingest'

export interface IngestUploadResponse {
  staged: IngestedBook[]
  rejected: IngestRejectedFile[]
}

// Multipart con più file sotto lo stesso campo 'files' — stesso pattern di
// uploadAuthorPhoto in authorActions.ts (bodySerializer forza il body reale
// a FormData; openapi-fetch vuole comunque un body "JSON-shaped" a livello
// di tipi, da cui il cast qui sotto).
export async function uploadIngestFiles(files: File[]): Promise<IngestUploadResponse> {
  const { data, error } = await api.POST('/api/kolibre/ingest/upload', {
    // @ts-expect-error vedi commento sopra — il vero body arriva da bodySerializer
    body: { files },
    bodySerializer() {
      const form = new FormData()
      files.forEach((file) => form.append('files', file))
      return form
    },
  })
  if (error) throw error
  return data as unknown as IngestUploadResponse
}

export interface ImportIngestPayload {
  id: number
  library?: string
  title?: string
  author?: string
  // Tutti opzionali: se omessi il backend ricade sul valore già presente
  // sulla riga IngestedBook (auto-estratto in staging) — vedi
  // IngestImportRequest in schemas.py.
  description?: string | null
  tags?: string[] | null
  series?: string | null
  series_index?: number | null
  language?: string | null
  isbn?: string | null
}

// Backend claim-atomico sulla riga (status pending -> importing) prima di
// muovere il file: un 409 significa che è già in importazione o non più
// disponibile (es. doppio click, o già importato da un'altra richiesta) —
// il chiamante lo intercetta per aggregare "N falliti" invece di un errore
// generico.
export async function importIngestBook(payload: ImportIngestPayload): Promise<{ book_id: number }> {
  const { data, error } = await api.POST('/api/kolibre/ingest/import-book', {
    body: payload,
  })
  if (error) throw error
  return data as unknown as { book_id: number }
}

// "Scarta" reale (DELETE /{id}/ingest — vedi ingest.py::discard_ingest_item):
// a differenza del vecchio "Scarta Tutti" (solo frontend, il file restava
// davvero sul disco), questo elimina il file sorgente E la riga di
// staging — irreversibile, va confermato dal chiamante prima di invocarlo.
export async function discardIngestItem(id: number): Promise<void> {
  const { error } = await api.DELETE('/api/kolibre/ingest/{id}', {
    params: { path: { id } },
  })
  if (error) throw error
}

// URL diretto al file grezzo in staging (ingest.py: /{id}/file), per
// l'apertura in una nuova scheda — la controparte di downloadFormatUrl in
// bookActions.ts, ma senza il web reader dedicato (reader.html/pdf-reader.html
// non sono ancora stati portati in questo frontend: vedi ImportTab.tsx per
// la decisione). Serve il token in query perché window.open() non può
// impostare un header Authorization.
export async function ingestFileUrl(id: number): Promise<string> {
  const token = await ensureAuthToken()
  const query = token ? `?token=${encodeURIComponent(token)}` : ''
  return withBackendUrl(`/api/kolibre/ingest/${id}/file${query}`)
}
