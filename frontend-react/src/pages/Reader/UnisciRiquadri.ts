// Da «un rettangolo per ogni riquadro del browser» a «una fascia per riga».
//
// **Il problema.** `marks-pane` disegna un rettangolo per ogni voce di
// `Range.getClientRects()`. Il browser ne restituisce uno per ogni pezzo di
// testo contiguo dentro un elemento diverso: un corsivo, un rimando di nota,
// un trattino invisibile a meta' parola spezzano la stessa riga in due, tre,
// cinque riquadri. Il risultato si legge come quello che e' — una fila di
// rettangoli colorati indipendenti — invece che come un segno tirato sopra
// al testo.
//
// E lo stesso vale per la sottolineatura, che e' la stessa classe: una riga
// sola diventava tre trattini con due buchi in mezzo.
//
// **Cosa fa.** Raggruppa i riquadri per riga, ne fa uno per riga, e chiude i
// buchi fra una riga e l'altra quando sono dell'ordine dell'interlinea. Non
// li chiude quando sono grandi: fra due paragrafi, o attraverso
// un'illustrazione, lo spazio vuoto e' vuoto davvero.
//
// Funzione pura, perche' e' aritmetica su rettangoli e si puo' sbagliare in
// silenzio: una riga unita male non si vede fino a che non capita il libro
// giusto.

export interface Riquadro {
  left: number
  top: number
  width: number
  height: number
}

/** Quanto due riquadri si sovrappongono in verticale. Negativo = sono distanti. */
function sovrapposizioneVerticale(a: Riquadro, b: Riquadro): number {
  return Math.min(a.top + a.height, b.top + b.height) - Math.max(a.top, b.top)
}

/**
 * Lo stesso rigo di testo: si sovrappongono per piu' di meta' del piu' basso
 * **e** si toccano anche in orizzontale.
 *
 * La seconda meta' non e' pignoleria, e' il difetto che ha prodotto questa
 * riga. In impaginato il libro e' disposto a colonne — una per pagina, due in
 * pagina doppia — e le colonne stanno **affiancate**: la terza riga della
 * pagina 4 e la terza riga della pagina 5 hanno la stessa altezza esatta.
 * Guardando solo la verticale venivano prese per lo stesso rigo e saldate in
 * una fascia unica larga quanto tutte e due le pagine, che e' il «si
 * deforma» segnalato da Paolo il 06/10.
 *
 * La tolleranza e' mezza riga: copre lo spazio fra due parole o fra due
 * elementi attaccati, e non arriva mai a coprire lo stacco fra due colonne.
 */
function stessaRiga(a: Riquadro, b: Riquadro): boolean {
  if (sovrapposizioneVerticale(a, b) <= 0.5 * Math.min(a.height, b.height)) return false
  const tolleranza = 0.5 * Math.min(a.height, b.height)
  const distanza = Math.max(a.left, b.left) - Math.min(a.left + a.width, b.left + b.width)
  return distanza <= tolleranza
}

function abbraccia(a: Riquadro, b: Riquadro): Riquadro {
  const left = Math.min(a.left, b.left)
  const top = Math.min(a.top, b.top)
  const right = Math.max(a.left + a.width, b.left + b.width)
  const bottom = Math.max(a.top + a.height, b.top + b.height)
  return { left, top, width: right - left, height: bottom - top }
}

/**
 * Quanto di un buco fra due righe si puo' chiudere, in multipli dell'altezza
 * della riga. 0,8 copre l'interlinea normale (anche 2,0) senza saldare due
 * paragrafi, che distano molto di piu'.
 */
const BUCO_MASSIMO = 0.8

export function unisciRiquadri(grezzi: readonly Riquadro[]): Riquadro[] {
  const buoni = grezzi.filter((r) => r.width > 0 && r.height > 0)
  if (buoni.length <= 1) return buoni.map((r) => ({ ...r }))

  // Per riga, e dentro la riga da sinistra: l'ordine di `getClientRects()` e'
  // quello del documento, che con un corsivo annidato non e' l'ordine visivo.
  const ordinati = [...buoni].sort((a, b) => a.top - b.top || a.left - b.left)

  const righe: Riquadro[] = []
  for (const r of ordinati) {
    const ultima = righe[righe.length - 1]
    if (ultima && stessaRiga(ultima, r)) {
      righe[righe.length - 1] = abbraccia(ultima, r)
    } else {
      righe.push({ ...r })
    }
  }

  // I buchi fra una riga e l'altra: si chiudono allungando la riga di sopra,
  // non spostando quella di sotto — cosi' il bordo superiore di ogni riga
  // resta dove il browser l'ha messo.
  //
  // Anche qui vale la colonna: due righe consecutive si saldano solo se stanno
  // una sopra l'altra DAVVERO, cioe' si sovrappongono in orizzontale. L'ultima
  // riga di una colonna e la prima della successiva sono consecutive nel testo
  // ma lontane sullo schermo, e allungare la prima fin giu' disegnerebbe una
  // fascia in mezzo al niente.
  for (let i = 0; i < righe.length - 1; i++) {
    const sopra = righe[i]
    const sotto = righe[i + 1]
    const buco = sotto.top - (sopra.top + sopra.height)
    const incolonnate =
      Math.min(sopra.left + sopra.width, sotto.left + sotto.width) > Math.max(sopra.left, sotto.left)
    if (incolonnate && buco > 0 && buco <= BUCO_MASSIMO * Math.max(sopra.height, sotto.height)) {
      sopra.height += buco
    }
  }

  return righe
}

// ─────────────────────────────────────────────────────────────────────────
// L'innesto in epub.js
//
// `marks-pane` non si puo' configurare: `Highlight.render()` chiama il suo
// `filteredRanges()` e disegna quello che torna. Quindi si sostituisce quel
// metodo — una volta sola, all'avvio del lettore.
//
// Si innesta sul pacchetto `marks-pane`, che e' lo stesso modulo che epub.js
// importa (`managers/views/iframe.js`); per questo e' passato da dipendenza
// implicita a dipendenza dichiarata. `Underline` eredita da `Highlight`,
// quindi una sola sostituzione serve tutte e due — ed e' il motivo per cui
// anche la sottolineatura smette di essere fatta di trattini.
//
// Se qualcosa va storto si torna al comportamento originale invece di far
// sparire le evidenziazioni: un segno brutto e' meglio di nessun segno.
// ─────────────────────────────────────────────────────────────────────────
import { Highlight } from 'marks-pane'

let innestato = false

export function unisciIRiquadriDeiSegni() {
  if (innestato) return
  innestato = true
  const originale = Highlight.prototype.filteredRanges
  Highlight.prototype.filteredRanges = function (this: { range: Range }) {
    try {
      const grezzi = Array.from(this.range.getClientRects(), (r) => ({
        left: r.left,
        top: r.top,
        width: r.width,
        height: r.height,
      }))
      return unisciRiquadri(grezzi)
    } catch {
      return originale.call(this)
    }
  }
}
