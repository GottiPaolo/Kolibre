// Dove sono arrivato NEL LIBRO, non nel file aperto.
//
// Un EPUB non e' un documento: e' una raccolta di file (copertina,
// frontespizio, dedica, capitolo 1, capitolo 2...). epub.js sa dire su quale
// pagina del file corrente si e' — `displayed.page / displayed.total` — e
// quel numero riparte da 1 a ogni file. Misurato su un libro vero (128
// pagine girate, finestra 600x800): 28 etichette distinte in tutto, di cui
// 21 ripetute; «pagina 1 di 5» compare su 9 pagine diverse del libro e
// «pagina 1 di 1» su 5. Chi legge pensa di avere in mano UN libro, e quel
// numero gli racconta di un file che non ha mai visto.
//
// Il numero di qui invece e' contato su tutto il libro, usando l'indice che
// epub.js costruisce comunque (`book.locations`): fette di testo di lunghezza
// uguale, 1600 caratteri l'una — l'ordine di grandezza di una pagina di
// carta. Due conseguenze da sapere:
//   - la fetta non e' la pagina sullo schermo, percio' girando pagina il
//     numero puo' avanzare di 1 o di 2 su uno schermo largo, e restare fermo
//     su uno stretto. In compenso e' lo STESSO numero su ogni schermo e con
//     ogni dimensione del carattere;
//   - e' la stessa unita' con cui si registra la pagina di
//     un'evidenziazione (pseudoPageForCfi in EpubHelpers.ts), che e' quella
//     che finisce nelle note esportate su Obsidian («p. 63»). Per questo
//     quella funzione passa da qui: i due numeri non possono divergere.

export interface PosizioneNelLibro {
  /** Pagina contata su tutto il libro, da 1 a `totale`. */
  pagina: number
  /** Quante fette ha il libro intero. */
  totale: number
  /** Avanzamento in centesimi, per la barra e per l'etichetta. */
  percento: number
}

/**
 * `frazione` e' quella che da' epub.js (0 = inizio, 1 = fine), `totaleLocation`
 * e' `book.locations.total`.
 *
 * Restituisce null quando il conto non si puo' fare: indice non ancora
 * generato (total 0 o undefined) o frazione non numerica. Null vuol dire
 * «non lo so», e va mostrato come tale — una percentuale finta ferma a zero
 * mentre l'indice si costruisce direbbe che sono all'inizio del libro, che
 * e' falso proprio quando si riapre un libro a meta'.
 */
export function posizioneNelLibro(frazione: number, totaleLocation: number): PosizioneNelLibro | null {
  if (!Number.isFinite(frazione) || !Number.isFinite(totaleLocation)) return null
  const totale = Math.floor(totaleLocation)
  if (totale < 1) return null
  const f = Math.min(1, Math.max(0, frazione))
  return {
    pagina: Math.min(totale, Math.max(1, Math.round(f * totale))),
    totale,
    // Troncata, non arrotondata: 99,6% arrotondato fa 100%, e «100%» su un
    // libro che ha ancora pagine davanti e' l'unico errore che si nota.
    percento: Math.floor(f * 100),
  }
}
