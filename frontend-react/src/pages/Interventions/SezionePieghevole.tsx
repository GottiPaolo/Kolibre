import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, type LucideIcon } from 'lucide-react'

// Una voce della pagina Interventi: titolo, quante cose aspettano, e il
// contenuto solo se lo si chiede.
//
// Chiusa di preimpostazione, e non e' un dettaglio: aprendo la pagina si
// vedeva una sola sezione — quella dei doppioni — occupare tutta la
// finestra, e le altre nemmeno esistevano. Una pagina che elenca il lavoro
// in sospeso deve prima dire QUANTO ce n'e' e di che tipo; il dettaglio
// viene dopo, su richiesta, una cosa per volta.
//
// Il numero sta nell'intestazione proprio perche' e' l'informazione che
// serve a chiusa: si apre la pagina, si legge "3 doppioni, 6 note senza
// libro", e si decide da dove cominciare.

export function SezionePieghevole({
  titolo,
  icona: Icona,
  quante,
  descrizione,
  apertaDiDefault = false,
  children,
}: {
  titolo: string
  icona: LucideIcon
  /** Quante cose aspettano. `null` quando non si sa ancora. */
  quante: number | null
  descrizione?: string
  apertaDiDefault?: boolean
  children: ReactNode
}) {
  const [aperta, setAperta] = useState(apertaDiDefault)
  const Freccia = aperta ? ChevronDown : ChevronRight

  return (
    <section className="rounded-md border border-border bg-card">
      <button
        onClick={() => setAperta((a) => !a)}
        aria-expanded={aperta}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-left hover:bg-accent/40"
      >
        <Freccia className="size-4 shrink-0 text-muted-foreground" />
        <Icona className="size-4 shrink-0 text-muted-foreground" />
        <span className="text-[14px] font-semibold">{titolo}</span>
        {quante !== null && quante > 0 && (
          <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[11.5px] tabular-nums text-primary">
            {quante}
          </span>
        )}
        {descrizione && !aperta && (
          <span className="min-w-0 flex-1 truncate text-[12px] text-muted-foreground">{descrizione}</span>
        )}
      </button>
      {aperta && <div className="border-t border-border px-4 py-3.5">{children}</div>}
    </section>
  )
}
