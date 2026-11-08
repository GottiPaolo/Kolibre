// Il colore di ogni stato, in un posto solo.
//
// Lo usano la tabella (etichette e filtri) e la pagina di un libro: due
// mappe separate si sarebbero scostate al primo stato nuovo, e uno stato
// senza colore non si vede male — si vede **senza bordo**, che è il modo più
// silenzioso di sbagliare. `prove/stati_degli_appunti.py` pretende che ogni
// stato del server abbia la sua voce qui.
export const COLORE_DELLO_STATO: Record<string, string> = {
  conflitto: 'border-destructive/40 bg-destructive/10 text-destructive',
  non_creato: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  non_aggiornato: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  in_attesa: 'border-primary/40 bg-primary/10 text-primary',
  in_pari: 'border-border bg-muted/50 text-muted-foreground',
  cancellato_da_te: 'border-border bg-muted/50 text-muted-foreground',
  bloccato: 'border-border bg-muted/50 text-muted-foreground',
}

/** Lo stato di una singola nota. Stessa ragione, stesso posto. */
export const COLORE_DI_UNA_NOTA: Record<string, string> = {
  conflitto: 'border-destructive/40 bg-destructive/10 text-destructive',
  mai_consegnata: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  da_portare: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  modificata_da_te: 'border-primary/40 bg-primary/10 text-primary',
  togliata_da_te: 'border-border bg-muted/50 text-muted-foreground',
  in_pari: 'border-border bg-muted/50 text-muted-foreground',
}
