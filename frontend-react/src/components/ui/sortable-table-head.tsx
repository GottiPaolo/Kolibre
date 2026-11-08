import { ArrowDown, ArrowUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { TableHead } from './table'

interface SortableTableHeadProps<K extends string> {
  label: string
  sortKey: K
  active: boolean
  order: 'asc' | 'desc'
  onClick: (key: K) => void
  className?: string
  /** Il posto di questa colonna fra i criteri: 1 comanda, 2 e oltre decidono le
   *  parita' e hanno la freccia piu' pallida. Omesso (o 1) si comporta come una
   *  tabella a criterio singolo. */
  livello?: number
}

// Intestazione tabella cliccabile per ordinare — porting semplificato del
// pattern già usato in pages/Library/LibraryTable.tsx, per le tabelle
// dispositivo (poche colonne, nessun bisogno di multi-criterio/shift+click).
export function SortableTableHead<K extends string>({ label, sortKey, active, order, onClick, className, livello }: SortableTableHeadProps<K>) {
  const secondario = active && (livello ?? 1) > 1
  return (
    <TableHead
      role="columnheader"
      onClick={() => onClick(sortKey)}
      className={`cursor-pointer select-none hover:text-foreground ${className ?? ''}`}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active && (
          // La colonna che comanda ha la freccia piena, quelle che decidono le
          // parita' ce l'hanno piu' pallida. C'era anche il numero del posto
          // accanto alla freccia: tolto il 02/10/2026 perche' era rumore
          // visivo e non serviva davvero — l'ordine dei criteri si vede
          // meglio guardando le righe che leggendo un due in corpo nove, e
          // l'opacita' basta a dire quale comanda.
          <span className={cn('inline-flex items-center', secondario && 'opacity-45')}>
            {order === 'asc' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />}
          </span>
        )}
      </span>
    </TableHead>
  )
}
