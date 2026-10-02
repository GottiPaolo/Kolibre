import { useState } from 'react'
import { Pencil } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { highlightPositionUnavailable, highlightSourceBadge, highlightUnavailableReason } from '@/lib/annotationActions'
import { useLingua } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import type { Highlight } from '@/types/annotation'

// Un passaggio evidenziato, come lo mostrano tutte e tre le viste.
//
// Una presentazione sola per tre viste, e non tre: lo stesso passaggio visto
// da posti diversi deve avere lo stesso aspetto, e tre copie diventerebbero
// tre aspetti diversi alla prima modifica. Cambia il CONTORNO — l'elenco, la
// griglia, l'indice — non il passaggio.
//
// Misurato prima di disegnarlo: su dati reali il testo mediano di un'annotazione
// è di 394 caratteri, il terzo quartile 682, il massimo 7.528. Sono paragrafi,
// non frasi: da qui il serif, la misura di riga contenuta e il niente intorno.
//
// I capitoli lunghissimi — «TITOLO ▸ PARTE QUARTA … ▸ III • NOME DEL
// CAPITOLO» — sono catene costruite apposta da chi esporta (01/10/2026),
// non un difetto: si mostrano come sono, su una riga che tronca, e per intero
// nel titolo del tag. Nessuna logica che provi a interpretarli.

/**
 * Spezza un testo attorno alle occorrenze di `ago`, per poterle marcare.
 *
 * Senza, la ricerca dice QUALI passaggi contengono la parola ma lascia a chi
 * guarda il compito di ritrovarla dentro quattrocento caratteri — che è il
 * lavoro che la ricerca dovrebbe aver tolto. Confronto senza maiuscole, come
 * quello che ha filtrato l'elenco: marcare solo le occorrenze identiche
 * lascerebbe fuori proprio quelle che il filtro ha accettato.
 */
function spezza(testo: string, ago: string): { pezzo: string; marcato: boolean }[] {
  const cercato = ago.trim()
  if (!cercato) return [{ pezzo: testo, marcato: false }]
  const fuori: { pezzo: string; marcato: boolean }[] = []
  const basso = testo.toLowerCase()
  const agoBasso = cercato.toLowerCase()
  let da = 0
  for (;;) {
    const i = basso.indexOf(agoBasso, da)
    if (i === -1) break
    if (i > da) fuori.push({ pezzo: testo.slice(da, i), marcato: false })
    fuori.push({ pezzo: testo.slice(i, i + cercato.length), marcato: true })
    da = i + cercato.length
  }
  if (da < testo.length) fuori.push({ pezzo: testo.slice(da), marcato: false })
  return fuori
}

function Marcato({ testo, cerca }: { testo: string; cerca?: string }) {
  if (!cerca?.trim()) return <>{testo}</>
  return (
    <>
      {spezza(testo, cerca).map((t, i) =>
        t.marcato ? (
          <mark key={i} className="rounded-[2px] bg-primary/25 px-0.5 text-foreground">
            {t.pezzo}
          </mark>
        ) : (
          <span key={i}>{t.pezzo}</span>
        )
      )}
    </>
  )
}

export interface AzioniPassaggio {
  onToggleTrash: () => void
  onPurge: () => void
  onNotesChange: (notes: string) => void
  onOpenBook?: () => void
}

interface PassaggioProps extends AzioniPassaggio {
  highlight: Highlight
  /** Il libro e l'autore sopra il passaggio. Si spengono dove il contorno li dice già. */
  mostraLibro?: boolean
  /** `grande` per la vista Lettura e per il dettaglio dell'Indice. */
  taglia?: 'normale' | 'grande'
  /** Il testo cercato, da marcare dentro il passaggio e dentro la nota. */
  cerca?: string
}

export function Passaggio({
  highlight,
  mostraLibro = true,
  taglia = 'normale',
  cerca,
  onToggleTrash,
  onPurge,
  onNotesChange,
  onOpenBook,
}: PassaggioProps) {
  const { t } = useLingua()
  const [bozza, setBozza] = useState(highlight.notes)
  const [apertoNota, setApertoNota] = useState(false)
  const badge = highlightSourceBadge(highlight, t)
  const senzaPosizione = highlightPositionUnavailable(highlight)
  const grande = taglia === 'grande'

  function apriNota() {
    setBozza(highlight.notes)
    setApertoNota(true)
  }

  // Chiudere in qualunque modo salva la bozza: stessa semantica del textarea
  // in linea di prima, che non aveva un annulla.
  function chiudiNota() {
    if (bozza !== highlight.notes) onNotesChange(bozza)
    setApertoNota(false)
  }

  return (
    <article className="group/passo flex min-w-0 flex-col gap-2.5">
      {mostraLibro && (
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <button
            type="button"
            onClick={() => onOpenBook?.()}
            className="font-serif text-[14px] text-foreground hover:text-primary"
          >
            {highlight.book_title || t('annotations.book.untitled')}
          </button>
          {highlight.book_author && (
            <span className="text-[11.5px] text-muted-foreground">{highlight.book_author}</span>
          )}
        </div>
      )}

      {/* `whitespace-pre-wrap`: gli a-capo dentro un'evidenziazione sono quelli
          del libro, e toglierli incolla insieme versi e dialoghi. */}
      <blockquote
        className={cn(
          'min-w-0 font-serif whitespace-pre-wrap text-foreground',
          grande ? 'max-w-[62ch] text-[17px] leading-[1.62]' : 'max-w-[72ch] text-[14.5px] leading-[1.6]'
        )}
      >
        <Marcato testo={highlight.text} cerca={cerca} />
      </blockquote>

      {highlight.notes.trim() && (
        <p
          className={cn(
            'min-w-0 border-l-2 border-primary pl-3 whitespace-pre-wrap text-[var(--nota)]',
            grande ? 'max-w-[62ch] text-[13.5px] leading-[1.55]' : 'max-w-[72ch] text-[12.5px] leading-[1.5]'
          )}
          style={{ ['--nota' as string]: 'color-mix(in srgb, var(--primary) 45%, var(--foreground))' }}
        >
          <Marcato testo={highlight.notes} cerca={cerca} />
        </p>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground/80">
        {highlight.chapter && (
          <span className="max-w-[46ch] truncate" title={highlight.chapter}>
            {highlight.chapter}
          </span>
        )}
        {highlight.page != null && (
          <span className="tabular-nums">{t('annotations.book.pageAbbrev', { page: highlight.page })}</span>
        )}
        <span title={badge.label}>{badge.label}</span>
        <span className="tabular-nums">{highlight.created_at ?? '—'}</span>

        {/* Le azioni compaiono passandoci sopra: su una pagina che mostra
            centinaia di passaggi, quattro comandi sempre accesi sotto ognuno
            sono più inchiostro del testo che dovrebbero servire. Restano
            raggiungibili da tastiera (focus-within). */}
        <span className="ml-auto flex items-center gap-2 opacity-0 transition-opacity group-hover/passo:opacity-100 focus-within:opacity-100">
          <button type="button" onClick={apriNota} className="inline-flex items-center gap-1 hover:text-foreground">
            <Pencil className="size-3" />
            {highlight.notes.trim() ? t('annotations.note.label') : t('annotations.note.addLabel')}
          </button>
          {senzaPosizione ? (
            <span title={highlightUnavailableReason(highlight, t)} className="cursor-not-allowed opacity-60">
              {t('annotations.action.openInReader')}
            </span>
          ) : (
            <button type="button" onClick={() => onOpenBook?.()} className="text-primary hover:underline">
              {t('annotations.action.openInReader')}
            </button>
          )}
          {highlight.trashed ? (
            <>
              <button type="button" onClick={onToggleTrash} className="hover:text-foreground">
                {t('annotations.action.restore')}
              </button>
              <button type="button" onClick={onPurge} className="font-medium text-destructive hover:underline">
                {t('annotations.action.purge')}
              </button>
            </>
          ) : (
            <button type="button" onClick={onToggleTrash} className="text-destructive hover:underline">
              {t('annotations.action.delete')}
            </button>
          )}
        </span>
      </div>

      {apertoNota && (
        <Dialog open onOpenChange={(open) => !open && chiudiNota()}>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>{t('annotations.note.label')}</DialogTitle>
            </DialogHeader>
            <textarea
              rows={5}
              autoFocus
              value={bozza}
              onChange={(e) => setBozza(e.target.value)}
              placeholder={t('annotations.note.placeholder')}
              className="w-full resize-none rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
            />
            <DialogFooter>
              <Button onClick={chiudiNota}>{t('common.save')}</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </article>
  )
}
