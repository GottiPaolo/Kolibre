// Comparatore generico per tabelle con ordinamento a click sull'intestazione
// (pattern semplificato, criterio singolo, rispetto a pages/Library/sort.ts
// che supporta multi-criterio con shift+click — qui non serve, sono tabelle
// da poche decine di righe, non migliaia come la Libreria).
export function sortByAccessor<T, K extends string>(
  rows: T[],
  accessors: Record<K, (row: T) => string | number>,
  key: K,
  order: 'asc' | 'desc'
): T[] {
  const accessor = accessors[key]
  return [...rows].sort((a, b) => {
    const av = accessor(a)
    const bv = accessor(b)
    if (av === bv) return 0
    const cmp = av < bv ? -1 : 1
    return order === 'asc' ? cmp : -cmp
  })
}

/** Un criterio di ordinamento: la colonna e il verso. */
export type Criterio<K extends string> = { chiave: K; verso: 'asc' | 'desc' }

/**
 * Ordina per piu' criteri in fila, dal piu' recente al piu' vecchio.
 *
 * Perche' serve, e non e' un vezzo: ordinando per "ha la biografia" si ottengono
 * due blocchi, si' e no, e **dentro** ciascuno l'ordine e' quello che c'era
 * prima. Se poi si ordina per "ha la foto", a parita' di foto ci si aspetta di
 * ritrovare l'ordinamento appena scelto, non di perderlo: "chi ha la foto ma non
 * la biografia" e' una domanda che si fa a due colonne, e con un criterio solo
 * non si puo' fare. Chiesto il 30/09/2026 sulla pagina Entita'.
 *
 * `criteri[0]` e' il piu' recente e comanda; gli altri decidono le parita', in
 * ordine. L'ultima parola la ha `base`, cosi' che il risultato non dipenda
 * dall'ordine in cui le righe sono arrivate: un ordinamento che a parita' totale
 * lascia fare al caso cambia sotto gli occhi di chi guarda ogni volta che i dati
 * si ricaricano.
 */
export function sortByCriteria<T, K extends string>(
  rows: T[],
  accessors: Record<K, (row: T) => string | number>,
  criteri: Criterio<K>[],
  base: (row: T) => string | number
): T[] {
  return [...rows].sort((a, b) => {
    for (const { chiave, verso } of criteri) {
      const accessor = accessors[chiave]
      const av = accessor(a)
      const bv = accessor(b)
      if (av !== bv) {
        const cmp = av < bv ? -1 : 1
        return verso === 'asc' ? cmp : -cmp
      }
    }
    const ab = base(a)
    const bb = base(b)
    if (ab === bb) return 0
    return ab < bb ? -1 : 1
  })
}
