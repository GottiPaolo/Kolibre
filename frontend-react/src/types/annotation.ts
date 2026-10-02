// Porting 1:1 delle forme restituite da backend/app/api/annotations.py
// (_serialize/_serialize_orphan) — quegli endpoint non dichiarano
// response_model, quindi schema.d.ts li tipizza solo `unknown`; questi tipi
// sono stati verificati leggendo il codice Python, non lo schema OpenAPI.
export type HighlightSource = 'web' | 'device' | 'calibre'

export interface Highlight {
  // Number per gli highlight reali, stringa "orphan-<n>" per le
  // OrphanHighlight — vedi is_orphan per distinguerli in modo affidabile.
  id: number | string
  calibre_book_id: number | null
  library: string | null
  text: string
  notes: string
  chapter: string | null
  page: number
  cfi_start: string | null
  cfi_end: string | null
  source: HighlightSource
  device_id: number | null
  device_name: string | null
  position_status: string | null
  color: string | null
  trashed: boolean
  created_at: string | null
  updated_at: string | null
  book_title: string | null
  book_author: string | null
  // I formati del libro, per aprire il lettore giusto: le note non sanno da
  // sole se stanno su un EPUB o su un PDF, e chi apre il lettore deve
  // saperlo PRIMA di chiamare window.open (che Safari consente solo dentro
  // il turno sincrono del click, quindi non c'e' spazio per un fetch).
  book_formats: string[]
  is_orphan: boolean
  // Solo per is_orphan === true — identità stabile (device+local_path) per
  // il raggruppamento, dato che library/calibre_book_id sono sempre null.
  orphan_key?: string
}

// Solo i campi usati dal filtro "Dispositivo" di questa pagina — non il
// DeviceResponse completo (fuori scope, la pagina Dispositivi non è
// ancora stata portata).
export interface AnnotationDevice {
  id: number
  name: string
}
