import { useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useLingua } from '@/lib/i18n'
import {
  confermaCestino,
  purgeHighlight,
  restoreHighlight,
  trashHighlight,
  updateHighlightNotes,
} from '@/lib/annotationActions'
import { useAnnotations } from '@/lib/annotationQueries'
import { openBookInReader } from '@/lib/readerActions'
import { Passaggio } from '@/pages/Annotations/Passaggio'
import type { Book } from '@/types/library'
import type { Highlight } from '@/types/annotation'

interface HighlightsPanelProps {
  book: Book
  libraryFolder: string
}

// Elenco evidenziazioni del libro nella pagina Dettaglio (aggiunto il
// 2026-08-16) — riusa la stessa card della pagina Annotazioni
// (stesse azioni: ricolora/nota/cestina/apri nel reader), filtrando
// client-side la lista globale già in cache di useAnnotations() dato che
// il backend non espone un filtro per singolo libro (solo il conteggio,
// via /books/{id}/stats). Renderizza null se il libro non ha ancora
// nessuna evidenziazione — nessun pannello vuoto da mostrare.
export function HighlightsPanel({ book, libraryFolder }: HighlightsPanelProps) {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: highlights = [] } = useAnnotations()

  const bookHighlights = useMemo(
    () =>
      highlights
        .filter((h) => !h.trashed && h.library === libraryFolder && h.calibre_book_id === book.id)
        .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '')),
    [highlights, libraryFolder, book.id]
  )

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['annotations'] })
  }


  async function handleNotesChange(hl: Highlight, notes: string) {
    await updateHighlightNotes(hl, notes)
    invalidate()
  }

  async function handleToggleTrash(hl: Highlight) {
    // Stessa conferma della pagina Annotazioni, stessa funzione: è lo stesso
    // bottone sulla stessa evidenziazione, visto da un'altra pagina.
    if (!hl.trashed && !confermaCestino(hl)) return
    if (hl.trashed) await restoreHighlight(hl)
    else await trashHighlight(hl)
    invalidate()
  }

  async function handlePurge(hl: Highlight) {
    if (!window.confirm(t('library.highlights.confirmPurge'))) return
    await purgeHighlight(hl)
    invalidate()
  }


  function handleOpenBook(hl: Highlight) {
    if (hl.calibre_book_id == null || hl.library == null) return
    openBookInReader({ id: hl.calibre_book_id, title: hl.book_title || '', formats: hl.book_formats || [] }, hl.library, {
      cfi: hl.cfi_start ?? undefined,
      // Vedi AnnotationsPage: il testo e' il ripiego quando l'ancora non
      // regge, e costa una stringa in piu' nell'URL.
      notaTesto: hl.text || undefined,
      notaId: hl.id,
    })
  }

  if (bookHighlights.length === 0) return null

  return (
    <div>
      <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
        {t('library.highlights.heading', { n: bookHighlights.length })}
      </h3>
      {/* Stesso componente della pagina Annotazioni: e' lo stesso passaggio
          visto da un altro posto, e due presentazioni diventerebbero due
          aspetti diversi alla prima modifica. Il libro non si ripete, perche'
          qui siamo gia' dentro la sua scheda. */}
      <div className="flex flex-col">
        {bookHighlights.map((hl) => (
          <div key={hl.id} className="border-b border-border/60 py-4 first:pt-0 last:border-b-0">
            <Passaggio
              highlight={hl}
              mostraLibro={false}
              onToggleTrash={() => void handleToggleTrash(hl)}
              onPurge={() => void handlePurge(hl)}
              onNotesChange={(notes) => void handleNotesChange(hl, notes)}
              onOpenBook={() => handleOpenBook(hl)}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
