/**
 * `localStorage` che non può far esplodere la pagina.
 *
 * **Perché esiste.** `localStorage` non è una variabile: è un'API del browser
 * che può *lanciare*. In una finestra privata, con i dati del sito bloccati,
 * o su un profilo irrigidito, anche solo leggerla solleva un `SecurityError`.
 * Metà dei moduli di Kolibre lo avvolgevano in try/catch citando esattamente
 * questo caso, l'altra metà no — e fra i secondi c'erano proprio quelli letti
 * dentro l'inizializzatore di `useState` del guscio dell'app e della pagina
 * iniziale. Lì un'eccezione parte durante il primo render: non si degrada
 * niente, si vede una pagina bianca.
 *
 * Conta più del solito perché Kolibre si usa anche dal telefono, e Safari con
 * «Blocca tutti i cookie» è una configurazione che esiste davvero.
 *
 * **Cosa garantisce.** Niente di questo file lancia mai. Una lettura che non
 * si può fare vale `null`, una scrittura che non si può fare non succede e
 * basta: perdere una preferenza è un fastidio, non partire è un guasto.
 */

export function leggiLocale(chiave: string): string | null {
  try {
    return localStorage.getItem(chiave)
  } catch {
    return null
  }
}

export function scriviLocale(chiave: string, valore: string): void {
  try {
    localStorage.setItem(chiave, valore)
  } catch {
    // Spazio esaurito, o scrittura negata: la preferenza non si ricorda, e
    // chi l'ha appena espressa la vede comunque applicata in questa sessione.
  }
}

export function rimuoviLocale(chiave: string): void {
  try {
    localStorage.removeItem(chiave)
  } catch {
    /* vedi sopra */
  }
}
