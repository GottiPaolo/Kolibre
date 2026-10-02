import { useEffect, useRef, useState } from 'react'
import { useLingua } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { Passaggio, type AzioniPassaggio } from './Passaggio'
import type { Highlight } from '@/types/annotation'

// Vista C — Indice e dettaglio.
//
// Elenco stretto a sinistra, passaggio intero a destra: è la forma che risponde
// a «quell'annotazione che ricordo». L'elenco mostra due righe per voce —
// abbastanza per riconoscerla, non abbastanza da doverla leggere — e il
// dettaglio non taglia niente.
//
// Sotto `lg` le due colonne tornano una: due colonne su un telefono sono due
// schermate, e quella di destra non si vedrebbe mai. Lì l'elenco diventa un
// elenco, e toccare una voce apre il passaggio sotto di essa.
//
// La selezione segue i filtri: se la voce aperta esce dal risultato della
// ricerca, si apre la prima rimasta invece di lasciare a destra un passaggio
// che a sinistra non c'è più.

export function VistaIndice({
  passaggi,
  azioni,
  cerca,
}: {
  passaggi: Highlight[]
  azioni: (h: Highlight) => AzioniPassaggio
  cerca?: string
}) {
  const { t } = useLingua()
  const [sceltoId, setSceltoId] = useState<string | number | null>(null)
  const elenco = useRef<HTMLDivElement>(null)

  const scelto = passaggi.find((h) => h.id === sceltoId) ?? passaggi[0] ?? null

  useEffect(() => {
    if (scelto && scelto.id !== sceltoId) setSceltoId(scelto.id)
  }, [scelto, sceltoId])

  // Tornando in cima all'elenco quando cambia il filtro: restare a metà di un
  // elenco che non è più lo stesso elenco disorienta e basta.
  useEffect(() => {
    elenco.current?.scrollTo({ top: 0 })
  }, [passaggi])

  if (passaggi.length === 0) return null

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(300px,380px)_1fr]">
      <div
        ref={elenco}
        className="max-h-[70vh] min-w-0 overflow-y-auto rounded-lg border border-border lg:max-h-[calc(100vh-240px)]"
      >
        {passaggi.map((h) => {
          const attivo = scelto?.id === h.id
          return (
            <button
              key={h.id}
              type="button"
              onClick={() => setSceltoId(h.id)}
              aria-current={attivo ? 'true' : undefined}
              className={cn(
                'flex w-full flex-col gap-1 border-b border-border/50 border-l-2 px-3.5 py-3 text-left last:border-b-0',
                attivo ? 'border-l-primary bg-accent/50' : 'border-l-transparent hover:bg-accent/25'
              )}
            >
              <span className="flex items-baseline gap-2">
                <span className="min-w-0 flex-1 truncate font-serif text-[12.5px] text-foreground">
                  {h.book_title || t('annotations.book.untitled')}
                </span>
                {h.page != null && (
                  <span className="shrink-0 text-[10.5px] tabular-nums text-muted-foreground/70">
                    {t('annotations.book.pageAbbrev', { page: h.page })}
                  </span>
                )}
              </span>
              <span className="line-clamp-2 font-serif text-[12.5px] leading-[1.45] text-muted-foreground">
                {h.text}
              </span>
              {h.notes.trim() && (
                <span className="truncate text-[11px] text-primary/80">{h.notes}</span>
              )}
            </button>
          )
        })}
      </div>

      {scelto && (
        <div className="min-w-0 self-start rounded-lg border border-border bg-card p-6">
          <Passaggio highlight={scelto} taglia="grande" cerca={cerca} {...azioni(scelto)} />
        </div>
      )}
    </div>
  )
}
