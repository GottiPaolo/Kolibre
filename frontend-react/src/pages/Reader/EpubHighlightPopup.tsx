// Popup fluttuante usato in tre modalità dal reader EPUB (ReaderPage.tsx):
//  - selezione di testo nuova → scegli colore + nota opzionale, "Evidenzia".
//  - click su un'evidenziazione esistente → modifica colore/nota, "Elimina"/"Salva".
//  - selezione di una singola parola (vedi isSingleWord in EpubHelpers.ts) →
//    le due modalità sopra restano invariate, con in più un blocco dizionario
//    (definizione + "Aggiungi al vocabolario") quando `onAddToVocabulary` è
//    passato dal chiamante.
// Porting 1:1 della UI di frontend/src/ReaderView.vue (.reader-selection-popup,
// due blocchi template quasi identici) — qui unificati in un solo componente
// perché la differenza è solo quali azioni/testo meta vengono passati.
import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import { truncate } from './EpubHelpers'
import type { HighlightColorOption } from './EpubHelpers'

interface EpubHighlightPopupProps {
  x: number
  y: number
  text: string
  metaLabel?: string
  colors: HighlightColorOption[]
  selectedColor: string
  onColorChange: (color: string) => void
  note: string
  onNoteChange: (note: string) => void
  onCancel: () => void
  onPrimary: () => void
  primaryLabel: string
  onDelete?: () => void
  // Blocco dizionario opzionale (solo per selezioni di una singola parola):
  // passare onAddToVocabulary attiva il rendering del blocco.
  dictionaryLoading?: boolean
  dictionaryDefinition?: string | null
  dictionarySource?: string | null
  onAddToVocabulary?: () => void
  vocabularyAdded?: boolean
}

export function EpubHighlightPopup({
  x,
  y,
  text,
  metaLabel,
  colors,
  selectedColor,
  onColorChange,
  note,
  onNoteChange,
  onCancel,
  onPrimary,
  primaryLabel,
  onDelete,
  dictionaryLoading,
  dictionaryDefinition,
  dictionarySource,
  onAddToVocabulary,
  vocabularyAdded,
}: EpubHighlightPopupProps) {
  const { t } = useLingua()
  return (
    <div
      // fixed (non absolute): le coordinate sono già calcolate in viewport
      // space da ReaderPage.tsx (contents.window.frameElement.getBoundingClientRect()).
      className="fixed z-20 w-[220px] rounded-lg border border-border bg-popover p-2.5 text-popover-foreground shadow-lg"
      style={{ left: x, top: y }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="mb-2 text-[11px] italic text-muted-foreground">“{truncate(text, 90)}”</div>
      {metaLabel && <div className="mb-2 text-[10px] text-muted-foreground/80">{metaLabel}</div>}
      {onAddToVocabulary && (
        <div className="mb-2 border-b border-border pb-2">
          {dictionaryLoading ? (
            <div className="text-[11px] text-muted-foreground">{t('reader.dictionary.loading')}</div>
          ) : dictionaryDefinition ? (
            <>
              <div className="text-[12px] leading-snug">{dictionaryDefinition}</div>
              {dictionarySource && (
                <div className="mt-0.5 text-[10px] text-muted-foreground/70">
                  {t('reader.dictionary.source', { source: dictionarySource })}
                </div>
              )}
            </>
          ) : (
            <div className="text-[11px] text-muted-foreground">{t('reader.dictionary.noDefinition')}</div>
          )}
          <button
            type="button"
            onClick={onAddToVocabulary}
            disabled={vocabularyAdded}
            className="mt-1.5 text-[12px] font-medium text-primary underline-offset-2 hover:underline disabled:cursor-default disabled:text-muted-foreground disabled:no-underline"
          >
            {vocabularyAdded ? t('reader.vocabulary.added') : t('reader.vocabulary.add')}
          </button>
        </div>
      )}
      <div className="mb-2 flex gap-2">
        {colors.map((c) => (
          <button
            key={c.value}
            type="button"
            onClick={() => onColorChange(c.value)}
            aria-label={t('reader.highlight.colorAriaLabel', { color: c.value })}
            className="size-5 shrink-0 rounded-full border-2"
            style={{ backgroundColor: c.hex, borderColor: selectedColor === c.value ? 'var(--foreground)' : 'transparent' }}
          />
        ))}
      </div>
      <textarea
        value={note}
        onChange={(e) => onNoteChange(e.target.value)}
        placeholder={t('reader.highlight.notePlaceholder')}
        rows={2}
        className="mb-2 w-full resize-none rounded-md border border-border bg-background p-1.5 text-[12px] outline-none focus:border-primary"
      />
      <div className="flex items-center justify-end gap-2">
        {onDelete && (
          <button
            type="button"
            onClick={onDelete}
            className="mr-auto flex items-center gap-1 text-[12px] text-destructive underline-offset-2 hover:underline"
          >
            <Trash2 className="size-3" />
            {t('reader.highlight.delete')}
          </button>
        )}
        <Button variant="secondary" size="sm" onClick={onCancel}>
          {onDelete ? t('common.close') : t('common.cancel')}
        </Button>
        <Button size="sm" onClick={onPrimary}>
          {primaryLabel}
        </Button>
      </div>
    </div>
  )
}
