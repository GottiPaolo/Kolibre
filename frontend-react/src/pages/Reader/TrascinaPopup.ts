// Il calcolo del trascinamento del popup delle evidenziazioni, a parte dal
// componente perche' e' l'unica cosa qui dentro che si puo' sbagliare in
// silenzio: due sottrazioni invertite e il pannello si incolla al bordo
// opposto, o esce dalla finestra e non si riprende piu'.

export interface Scostamento {
  dx: number
  dy: number
}

export interface Riquadro {
  larghezza: number
  altezza: number
}

/** Dove il popup starebbe senza nessun trascinamento (quello che calcola ReaderPage). */
export interface Base {
  left: number
  top: number
}

export const MARGINE_POPUP = 8

/**
 * Riduce uno scostamento a quello che tiene il popup dentro la finestra.
 *
 * Si trascina, non si butta via: il popup non ha un tasto di chiusura e si
 * chiude cliccando fuori, quindi uno finito oltre il bordo non si potrebbe ne'
 * vedere ne' chiudere — si saprebbe solo che da qualche parte c'e'.
 *
 * Quando la finestra e' piu' piccola del popup piu' i due margini non esiste
 * uno scostamento che rispetti entrambi i lati: in quel caso vince il bordo
 * di partenza (sinistro, alto), perche' e' da li' che si legge.
 */
export function limitaScostamento(
  grezzo: Scostamento,
  base: Base,
  popup: Riquadro,
  finestra: Riquadro,
  margine: number = MARGINE_POPUP
): Scostamento {
  const lungo = (
    valore: number,
    partenza: number,
    quantoDura: number,
    quantoSpazio: number
  ) => {
    const minimo = margine - partenza
    const massimo = quantoSpazio - quantoDura - margine - partenza
    // `massimo < minimo` vuol dire che il popup non ci sta: si tiene il
    // minimo, cioe' il bordo da cui si comincia a leggere.
    if (massimo < minimo) return minimo
    return Math.min(massimo, Math.max(minimo, valore))
  }
  return {
    dx: lungo(grezzo.dx, base.left, popup.larghezza, finestra.larghezza),
    dy: lungo(grezzo.dy, base.top, popup.altezza, finestra.altezza),
  }
}
