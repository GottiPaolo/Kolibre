// Esegue tante operazioni poche per volta, invece di tutte insieme.
//
// Il motivo e' concreto: la pagina Ingest importava con
// `Promise.all(tutti.map(...))`, cioe' una richiesta HTTP per ogni libro,
// tutte nello stesso istante. Su dieci file non si nota; su tremila sono
// tremila richieste simultanee — il browser ne apre sei per volta e mette
// le altre in coda, ma il server riceve comunque una raffica che passa
// tutta dalla coda di scrittura su metadata.db, e la pagina resta senza
// alcun segno di vita finche' non hanno finito tutte.
//
// Poche per volta invece: il server respira, e soprattutto si sa a che
// punto si e'. `onProgress` viene chiamato dopo ogni operazione finita.
export async function aBatch<T, R>(
  elementi: T[],
  operazione: (e: T) => Promise<R>,
  opts: { concorrenza?: number; onProgress?: (fatti: number, totale: number) => void; fermati?: () => boolean } = {}
): Promise<R[]> {
  const concorrenza = Math.max(1, opts.concorrenza ?? 4)
  const risultati: R[] = new Array(elementi.length)
  let prossimo = 0
  let fatti = 0

  async function operaio() {
    while (prossimo < elementi.length) {
      if (opts.fermati?.()) return
      const i = prossimo++
      risultati[i] = await operazione(elementi[i])
      opts.onProgress?.(++fatti, elementi.length)
    }
  }

  await Promise.all(Array.from({ length: Math.min(concorrenza, elementi.length) }, operaio))
  return risultati
}
