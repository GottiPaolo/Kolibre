// Due versioni dello stesso brano, e cosa è cambiato fra l'una e l'altra.
//
// **A cosa serve.** Nella pagina di un libro degli Appunti un brano può
// esistere in due versioni: quella di Kolibre e quella che sta nel tuo
// vault, perché l'hai corretto a mano o perché è cambiato da tutte due le
// parti. Vederle affiancate non basta: su un brano di tre righe la
// differenza può essere una virgola, e cercarla a occhio è il modo di non
// trovarla. Qui le due versioni si confrontano **parola per parola** e
// quello che è cambiato si può evidenziare.
//
// **Perché per parole e non per lettere.** Un confronto per lettere su un
// testo in prosa produce isole di caratteri sparse dentro le parole —
// illeggibile. Per parole, una correzione di refuso evidenzia la parola
// corretta, che è l'unità che si legge.
//
// Niente librerie: l'algoritmo è la sottosequenza comune più lunga (LCS),
// venti righe, e per brani di qualche riga costa niente. Una libreria di
// diff sarebbe più codice da scaricare che codice da scrivere.

export type PezzoDiDifferenza = {
  /** `uguale` sta in tutte due, `tolto` solo a sinistra, `aggiunto` solo a destra. */
  tipo: 'uguale' | 'tolto' | 'aggiunto'
  testo: string
}

/**
 * Spezza in parole **tenendo gli spazi**: ricomponendo i pezzi si riottiene
 * il testo originale carattere per carattere, che è la proprietà che rende
 * questo confronto mostrabile senza riscrivere il brano.
 */
export function inParole(testo: string): string[] {
  return (testo || '').split(/(\s+)/).filter((p) => p !== '')
}

/**
 * Le differenze fra due testi, in ordine di lettura.
 *
 * Con `null` o stringa vuota da una parte sola, l'altra risulta tutta
 * aggiunta (o tolta): è la verità, e non un caso da trattare a parte.
 */
export function differenzaDiParole(sinistra: string | null | undefined,
                                   destra: string | null | undefined): PezzoDiDifferenza[] {
  const a = inParole(sinistra ?? '')
  const b = inParole(destra ?? '')

  // Tabella della sottosequenza comune più lunga. a.length e b.length sono
  // il numero di parole di un brano: qualche decina, non serve altro.
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }

  const fuori: PezzoDiDifferenza[] = []
  const aggiungi = (tipo: PezzoDiDifferenza['tipo'], testo: string) => {
    const ultimo = fuori[fuori.length - 1]
    // I pezzi contigui dello stesso tipo si uniscono: così un periodo
    // riscritto è un blocco solo e non una collana di parole.
    if (ultimo && ultimo.tipo === tipo) ultimo.testo += testo
    else fuori.push({ tipo, testo })
  }

  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      aggiungi('uguale', a[i])
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      aggiungi('tolto', a[i])
      i++
    } else {
      aggiungi('aggiunto', b[j])
      j++
    }
  }
  while (i < a.length) aggiungi('tolto', a[i++])
  while (j < b.length) aggiungi('aggiunto', b[j++])
  return fuori
}

/** Vero quando i due testi sono lo stesso testo: niente da mostrare affiancato. */
export function nessunaDifferenza(pezzi: PezzoDiDifferenza[]): boolean {
  return pezzi.every((p) => p.tipo === 'uguale')
}
