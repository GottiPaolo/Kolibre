import { useMemo } from 'react'
import { ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useLingua, type Valori } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { VistaLettura } from './VistaLettura'
import type { AzioniPassaggio } from './Passaggio'
import type { Highlight } from '@/types/annotation'

// Vista B — Scaffale.
//
// Si parte dal libro e non dal passaggio: «tutte quelle del libro che ho
// appena finito» è una domanda frequente quanto «quel passaggio che ricordo»,
// e nell'elenco piatto non aveva risposta. Il numero è la cosa che si cerca da
// lontano, quindi è il pezzo più grande della scheda; l'assaggio in corsivo
// dice di che sapore sono senza dover entrare.
//
// Per AUTORE oltre che per libro: è quello che faceva il vecchio «raggruppa
// per», e toglierlo con il riordino sarebbe stato perdere una funzione invece
// che sostituirla.
//
// Misurato sui dati veri, ed è il motivo della coda in fondo: in una
// biblioteca reale da 67 libri, uno ha 246 passaggi e 34 ne hanno uno solo. Una
// griglia che li mostrasse tutti uguali racconterebbe una biblioteca che non
// esiste.

export type ChiaveScaffale = 'libro' | 'autore'

interface Scheda {
  chiave: string
  titolo: string
  sotto: string | null
  quanti: number
  conNota: number
  assaggio: string
}

function costruisci(
  passaggi: Highlight[],
  per: ChiaveScaffale,
  t: (chiave: string, valori?: Valori) => string
): Scheda[] {
  const mappa = new Map<string, Highlight[]>()
  for (const h of passaggi) {
    const k = (per === 'libro' ? h.book_title : h.book_author) || t('annotations.book.untitled')
    const gruppo = mappa.get(k)
    if (gruppo) gruppo.push(h)
    else mappa.set(k, [h])
  }
  return [...mappa.entries()]
    .map(([chiave, items]) => ({
      chiave,
      titolo: chiave,
      // Sotto il titolo l'altra chiave, quando è una sola: su un libro è
      // l'autore, su un autore è il libro se ne ha uno — «3 libri» altrimenti.
      sotto:
        per === 'libro'
          ? items[0]?.book_author || null
          : (() => {
              const libri = new Set(items.map((h) => h.book_title))
              return libri.size === 1
                ? [...libri][0]
                : t('annotations.shelf.bookCount', { count: libri.size, n: libri.size })
            })(),
      quanti: items.length,
      conNota: items.filter((h) => h.notes.trim()).length,
      assaggio: (items.find((h) => h.text.length > 60) ?? items[0])?.text ?? '',
    }))
    .sort((a, b) => b.quanti - a.quanti || a.titolo.localeCompare(b.titolo))
}

export function VistaScaffale({
  passaggi,
  azioni,
  per,
  onPer,
  aperto,
  onApri,
  cerca,
}: {
  passaggi: Highlight[]
  azioni: (h: Highlight) => AzioniPassaggio
  cerca?: string
  per: ChiaveScaffale
  onPer: (p: ChiaveScaffale) => void
  aperto: string | null
  onApri: (chiave: string | null) => void
}) {
  const { t } = useLingua()
  const schede = useMemo(() => costruisci(passaggi, per, t), [passaggi, per, t])
  const dentro = useMemo(
    () =>
      aperto === null
        ? []
        : passaggi.filter((h) => ((per === 'libro' ? h.book_title : h.book_author) || t('annotations.book.untitled')) === aperto),
    [passaggi, per, aperto, t]
  )

  if (aperto !== null) {
    return (
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline gap-3">
          <Button variant="ghost" size="sm" onClick={() => onApri(null)}>
            <ArrowLeft className="size-3.5" />
            {t('annotations.view.shelf.name')}
          </Button>
          <h2 className="font-serif text-[18px] text-foreground">{aperto}</h2>
          <span className="text-[12px] text-muted-foreground">
            {dentro.length} {t('annotations.count.passages', { count: dentro.length, n: dentro.length })}
          </span>
        </div>
        {/* Dentro un libro il titolo è già nell'intestazione: ripeterlo su ogni
            passaggio sarebbe la stessa riga stampata cinquanta volte. */}
        <VistaLettura passaggi={dentro} azioni={azioni} cerca={cerca} mostraLibro={false} />
      </div>
    )
  }

  const unaSola = schede.filter((s) => s.quanti === 1).length

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
        {t('annotations.shelf.groupBy')}
        {(['libro', 'autore'] as const).map((k) => (
          <Button key={k} variant={per === k ? 'secondary' : 'ghost'} size="xs" onClick={() => onPer(k)}>
            {k === 'libro' ? t('annotations.field.book') : t('annotations.field.author')}
          </Button>
        ))}
        <span className="ml-2">
          {schede.length}{' '}
          {per === 'libro'
            ? t('annotations.count.books', { count: schede.length, n: schede.length })
            : t('annotations.count.authors', { count: schede.length, n: schede.length })}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {schede.map((s) => (
          <button
            key={s.chiave}
            type="button"
            onClick={() => onApri(s.chiave)}
            className={cn(
              'flex min-h-[172px] flex-col gap-2.5 rounded-lg border border-border bg-card p-4 text-left',
              'hover:border-primary/50 hover:bg-accent/40'
            )}
          >
            <span className="flex items-baseline gap-2">
              <span className="font-serif text-[24px] leading-none font-semibold tabular-nums text-primary">{s.quanti}</span>
              {s.conNota > 0 && (
                <span className="text-[11px] text-muted-foreground">{t('annotations.shelf.withNote', { n: s.conNota })}</span>
              )}
            </span>
            <span className="flex flex-col gap-0.5">
              <span className="line-clamp-2 font-serif text-[14.5px] leading-tight text-foreground">{s.titolo}</span>
              {s.sotto && <span className="truncate text-[11.5px] text-muted-foreground">{s.sotto}</span>}
            </span>
            <span className="line-clamp-4 flex-1 font-serif text-[12.5px] leading-[1.5] text-muted-foreground/90 italic">
              {s.assaggio}
            </span>
          </button>
        ))}
      </div>

      {unaSola > 0 && (
        <p className="text-[12px] text-muted-foreground">
          {t('annotations.shelf.singlePassageNotice.prefix')} <b className="font-medium text-foreground">{unaSola}</b>{' '}
          {t('annotations.shelf.singlePassageNotice.suffix', { count: unaSola, n: unaSola })}
        </p>
      )}
    </div>
  )
}
