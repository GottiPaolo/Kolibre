// Popup fluttuante usato in tre modalità dal reader EPUB (ReaderPage.tsx):
//  - selezione di testo nuova → scegli colore + nota opzionale, "Evidenzia".
//  - click su un'evidenziazione esistente → modifica colore/nota; non ha un
//    bottone di conferma, perche' ogni modifica si salva da sola.
//  - selezione di una singola parola (vedi isSingleWord in EpubHelpers.ts) →
//    le due modalità sopra restano invariate, con in più un blocco dizionario
//    (definizione + "Aggiungi al vocabolario") quando `onAddToVocabulary` è
//    passato dal chiamante.
// Porting 1:1 della UI di frontend/src/ReaderView.vue (.reader-selection-popup,
// due blocchi template quasi identici) — qui unificati in un solo componente
// perché la differenza è solo quali azioni/testo meta vengono passati.
import { useEffect, useRef, useState } from 'react'
import type { Estremo, Verso } from './EpubSearch'
import { Link2, Quote, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import { truncate } from './EpubHelpers'
import { limitaScostamento, MARGINE_POPUP } from './TrascinaPopup'
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
  /** Chiamata quando si finisce di scrivere la nota: e' il momento di salvarla. */
  onNoteCommit?: () => void
  onPrimary?: () => void
  primaryLabel?: string
  onDelete?: () => void
  /** Copia il brano come citazione Markdown con il link che lo riapre. */
  onCite?: () => void
  /** Copia l'indirizzo che riapre il libro su questa nota (solo se gia' salvata). */
  onCopyLink?: () => void
  /** Sposta un estremo del brano di una frase. */
  onMoveEdge?: (estremo: Estremo, verso: Verso) => void
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
  onNoteCommit,
  onPrimary,
  primaryLabel,
  onDelete,
  onCite,
  onCopyLink,
  onMoveEdge,
  dictionaryLoading,
  dictionaryDefinition,
  dictionarySource,
  onAddToVocabulary,
  vocabularyAdded,
}: EpubHighlightPopupProps) {
  const { t } = useLingua()
  // Si apre solo chiedendolo: ne' una nota esistente ne' una nuova partono
  // come casella di testo.
  const [modificaNota, setModificaNota] = useState(false)
  // Le due vite del popup: una selezione appena fatta non ha ancora estremi
  // da spostare, ne' una nota, ne' una data.
  const inModifica = !!onMoveEdge

  // ── Il trascinamento ──────────────────────────────────────────────────
  //
  // Il popup si apre sopra o sotto il brano selezionato, e quel brano e'
  // proprio quello che si vuole vedere: in paginata, con la pagina stretta,
  // il pannello copriva il punto su cui si stava lavorando — e spostare gli
  // estremi di una parola alla volta senza vedere le parole non si puo' fare.
  //
  // Si tiene uno SCOSTAMENTO dalla posizione calcolata, non una posizione
  // assoluta: cosi' x/y restano quelli di ReaderPage e qui non si duplica il
  // calcolo di dove il popup starebbe da solo.
  const radice = useRef<HTMLDivElement | null>(null)
  const [scostamento, setScostamento] = useState({ dx: 0, dy: 0 })
  const presa = useRef<{ px: number; py: number; dx: number; dy: number } | null>(null)

  // Una posizione nuova e' un popup nuovo: se si riaggancia a un altro brano
  // lo scostamento di prima non vuol dire piu' niente. Il confronto evita di
  // riscrivere lo stato al montaggio, quando e' gia' zero.
  useEffect(() => {
    setScostamento((p) => (p.dx === 0 && p.dy === 0 ? p : { dx: 0, dy: 0 }))
  }, [x, y])

  function iniziaPresa(e: React.PointerEvent<HTMLDivElement>) {
    presa.current = { px: e.clientX, py: e.clientY, ...scostamento }
    // La cattura del puntatore: tutti i movimenti arrivano a questo elemento
    // anche quando il dito o il cursore ne escono, che e' il caso normale
    // appena si inizia a trascinare. Senza, servirebbero ascoltatori su
    // window e il trascinamento si perderebbe sopra l'iframe del libro.
    e.currentTarget.setPointerCapture(e.pointerId)
    e.preventDefault()
  }

  function muovePresa(e: React.PointerEvent<HTMLDivElement>) {
    const p = presa.current
    const el = radice.current
    if (!p || !el) return
    const r = el.getBoundingClientRect()
    setScostamento(
      limitaScostamento(
        { dx: p.dx + (e.clientX - p.px), dy: p.dy + (e.clientY - p.py) },
        // Il riquadro reso MENO lo scostamento di adesso: cioe' dove il popup
        // starebbe sotto il brano, che e' quello che ReaderPage ha calcolato.
        { left: r.left - scostamento.dx, top: r.top - scostamento.dy },
        { larghezza: r.width, altezza: r.height },
        { larghezza: window.innerWidth, altezza: window.innerHeight },
        MARGINE_POPUP
      )
    )
  }

  function lasciaPresa() {
    presa.current = null
  }

  return (
    <div
      ref={radice}
      // fixed (non absolute): le coordinate sono già calcolate in viewport
      // space da ReaderPage.tsx (contents.window.frameElement.getBoundingClientRect()).
      className="fixed z-20 w-[248px] rounded-lg border border-border bg-popover p-2.5 text-popover-foreground shadow-lg"
      style={{ left: x + scostamento.dx, top: y + scostamento.dy }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {/* L'appiglio. Una barretta e non il pannello intero: dentro ci sono
          otto bersagli piccoli e vicini, e un pannello trascinabile da
          qualunque punto trasforma ogni tocco poco preciso in uno
          spostamento. `touch-none` perche' altrimenti il dito scorre la
          pagina invece di trascinare. */}
      <div
        onPointerDown={iniziaPresa}
        onPointerMove={muovePresa}
        onPointerUp={lasciaPresa}
        onPointerCancel={lasciaPresa}
        title={t('reader.highlight.dragHandle')}
        aria-label={t('reader.highlight.dragHandle')}
        className="-mt-1 mb-1 flex cursor-grab touch-none items-center justify-center py-1 active:cursor-grabbing"
      >
        <div className="h-[3px] w-8 rounded-full bg-border" />
      </div>
      {/* L'ordine e' quello che Paolo ha dettato il 06/10: colori, estremi,
          nota, data e dispositivo, azioni. Non e' un gusto — e' la distanza
          dal gesto: il colore si cambia di continuo, gli estremi ogni tanto,
          la nota si legge, la data non si tocca mai, e le azioni stanno in
          fondo perche' una di loro cancella.

          E il brano evidenziato NON c'e' piu'. Era la riga piu' alta del
          popup e diceva, troncata a 90 caratteri, una cosa che sta scritta
          per intero sulla pagina dietro — evidenziata, per giunta. */}
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
      {/* I quattro movimenti degli estremi, senza etichette: `|` e' il bordo
          dell'evidenziazione, `<` e `>` la direzione in cui lo si spinge.
          Cosi' le prime due agiscono sull'inizio e le altre due sulla fine,
          invece di alternarsi. Il movimento e' di UNA PAROLA — a frasi
          spostava righe intere e per togliere tre parole si rifaceva tutto. */}
      {onMoveEdge && (
        <div className="mb-2 flex items-center justify-center gap-1">
          {([
            ['<|', 'inizio', 'allarga', t('reader.highlight.edge.startWider')],
            ['>|', 'inizio', 'stringe', t('reader.highlight.edge.startShorter')],
            ['|<', 'fine', 'stringe', t('reader.highlight.edge.endShorter')],
            ['|>', 'fine', 'allarga', t('reader.highlight.edge.endWider')],
          ] as const).map(([simbolo, estremo, verso, titolo]) => (
            <button
              key={simbolo}
              type="button"
              onClick={() => onMoveEdge(estremo as Estremo, verso as Verso)}
              title={titolo}
              aria-label={titolo}
              className="flex h-6 flex-1 items-center justify-center rounded-md border border-border font-mono text-[11px] tracking-tighter hover:bg-muted"
            >
              {simbolo}
            </button>
          ))}
        </div>
      )}
      {/* Il dizionario e' l'unico posto dove la parola resta scritta: una
          definizione senza la sua parola non si legge. */}
      {onAddToVocabulary && (
        <div className="mt-2 mb-2 border-t border-border pt-2">
          <div className="mb-1 text-[12px] font-semibold">{truncate(text, 40)}</div>
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
      {/* Lo spazio della nota, e **si scrive schiacciando qui sopra**. La
          matita in fondo non c'e' piu': era un bottone che diceva «apri
          quella cosa li'» quando quella cosa li' poteva aprirsi da sola.
          Scrivere una nota e' l'azione principale di questo pannello, e
          un'azione principale non si delega a un'icona da tre millimetri.

          Quando una nota non c'e' lo spazio resta, con scritto che e' vuoto:
          un popup che cambia altezza a seconda che una nota ci sia o no fa
          ballare i bottoni sotto, e sotto c'e' «Elimina». */}
      {inModifica && (
        modificaNota ? (
          <textarea
            value={note}
            onChange={(e) => onNoteChange(e.target.value)}
            onKeyDown={(e) => {
              // Invio chiude la casella e tiene; Maiusc+Invio va a capo.
              //
              // Esc fa la stessa cosa, e non annulla: da quando non c'e' piu'
              // un «Salva» non esiste piu' un «non salvare», e un tasto che a
              // volte butta via quello che si e' scritto e' peggio di uno che
              // non c'e'. Esc qui si ferma: NON chiude anche il popup,
              // altrimenti un solo tocco uscirebbe da due cose diverse.
              if ((e.key === 'Enter' && !e.shiftKey) || e.key === 'Escape') {
                e.preventDefault()
                e.stopPropagation()
                setModificaNota(false)
                onNoteCommit?.()
              }
            }}
            placeholder={t('reader.highlight.notePlaceholder')}
            rows={2}
            autoFocus
            className="mb-2 w-full resize-none rounded-md border border-border bg-background p-1.5 text-[12px] outline-none focus:border-primary"
          />
        ) : (
          <button
            type="button"
            onClick={() => setModificaNota(true)}
            title={note.trim() ? t('reader.highlight.editNote') : t('reader.highlight.addNote')}
            className={`mb-2 -mx-1 block min-h-[2.1em] w-[calc(100%+0.5rem)] rounded-md px-1 py-0.5 text-left text-[12px] leading-snug whitespace-pre-wrap hover:bg-muted ${
              note.trim() ? '' : 'text-muted-foreground/60 italic'
            }`}
          >
            {note.trim() || t('reader.highlight.noNote')}
          </button>
        )
      )}
      {metaLabel && <div className="mb-1.5 text-[10px] text-muted-foreground/80">{metaLabel}</div>}
      {/* Le azioni in fondo, sulla loro riga e sopra un filo. «Elimina» sta
          lontano da «Copia link» con un margine automatico in mezzo: sono
          due bottoni di testo alti sei millimetri, e uno dei due non si
          disfa. */}
      {(onCite || onCopyLink || onDelete) && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-2">
          {onCite && (
            <button
              type="button"
              onClick={onCite}
              title={t('reader.cite.tooltip')}
              className="flex items-center gap-1 text-[11.5px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              <Quote className="size-3" />
              {t('reader.cite.action')}
            </button>
          )}
          {onCopyLink && (
            <button
              type="button"
              onClick={onCopyLink}
              title={t('reader.highlight.copyLinkTooltip')}
              className="flex items-center gap-1 text-[11.5px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              <Link2 className="size-3" />
              {t('reader.highlight.copyLink')}
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              onClick={onDelete}
              className="ml-auto flex items-center gap-1 text-[11.5px] text-destructive underline-offset-2 hover:underline"
            >
              <Trash2 className="size-3" />
              {t('reader.highlight.delete')}
            </button>
          )}
        </div>
      )}
      {/* Il bottone c'e' solo quando crea qualcosa. In modifica non serve:
          colore e nota si salvano da soli appena cambiano, e il popup si
          chiude cliccando fuori. Un «Salva» su un pannello che salva comunque
          e' una domanda a cui l'utente non puo' rispondere male — quindi non
          va fatta. */}
      {onPrimary && (
        <div className="flex items-center justify-end">
          <Button size="sm" onClick={onPrimary}>
            {primaryLabel}
          </Button>
        </div>
      )}
    </div>
  )
}
