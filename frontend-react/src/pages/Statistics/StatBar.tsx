import type { ReactNode } from 'react'

// Riga "etichetta + barra proporzionale + valore" — porting della classe
// .stats-bar-row del Vue esistente (App.vue, sezione statistiche),
// riusata da tutti i widget a barre di questa pagina invece di ripetere lo
// stesso markup in ognuno.
// `onClick` rende la riga un punto di PARTENZA invece che un vicolo cieco:
// cliccando "filosofia" nel grafico dei tag si finisce nella Libreria
// filtrata su quel tag, cliccando un autore sulla sua scheda. E' il
// guadagno di navigabilita' piu' grande della pagina e costa poco, perche'
// il meccanismo di filtro esisteva gia' (vedi ValoreFiltrabile).
//
// Chi non passa onClick ottiene la riga di prima, non cliccabile: le
// categorie che non corrispondono a un filtro vero — "Corto (< 150 pag)",
// "Non valutato" — non devono fingere di esserlo.
export function StatBarRow({
  label,
  value,
  percent,
  color,
  onClick,
  titoloAzione,
  etichettaLarga,
}: {
  label: string
  value: string
  percent: number
  color: string
  onClick?: () => void
  titoloAzione?: string
  /** Per le righe che portano TITOLI invece di categorie: "Individualismo:
   *  qu…" in 112px non è un'etichetta, è un indovinello. Resta un'opzione e
   *  non il nuovo valore di sempre, perché una colonna più larga toglie spazio
   *  alla barra, e per "scrittore" o "Italia" 112px bastano. */
  etichettaLarga?: boolean
}) {
  const larghezza = etichettaLarga ? 'w-52' : 'w-28'
  const etichetta = onClick ? (
    <button
      onClick={onClick}
      title={titoloAzione ?? label}
      className={`${larghezza} shrink-0 truncate text-left text-muted-foreground hover:text-primary hover:underline`}
    >
      {label}
    </button>
  ) : (
    <span className={`${larghezza} shrink-0 truncate text-muted-foreground`} title={label}>
      {label}
    </span>
  )
  return (
    <div className="flex items-center gap-2 text-[12px]">
      {etichetta}
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, percent))}%`, backgroundColor: color }} />
      </div>
      <span className="w-16 shrink-0 text-right tabular-nums text-foreground">{value}</span>
    </div>
  )
}

// Riga "etichetta + titolo (libro/autore/anno) + valore" per la sezione
// Record: a differenza di StatBarRow non c'è una percentuale da mostrare
// (sono singoli primati, non una distribuzione), quindi niente barra.
export function RecordRow({ label, title, value }: { label: string; title: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/50 py-2 last:border-0 last:pb-0">
      <div className="min-w-0">
        <p className="text-[10.5px] tracking-wide text-muted-foreground uppercase">{label}</p>
        <p className="truncate text-[13px] font-medium" title={title}>
          {title}
        </p>
      </div>
      <span className="shrink-0 tabular-nums text-[13px] text-foreground">{value}</span>
    </div>
  )
}

export function ChartCard({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="mb-2.5 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
        {action}
      </div>
      {children}
    </div>
  )
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="text-[12px] text-muted-foreground">{children}</p>
}
