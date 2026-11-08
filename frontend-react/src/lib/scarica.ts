// Far scaricare un file al browser, senza aprire finestre.
//
// **Il difetto che questo file chiude** (segnalato da Paolo il 04/11/2026:
// «questo tasto però ad ora mi apre una nuova finestra vuota senza motivo»).
// Scaricare con `window.open(url)` chiede al browser una finestra nuova e
// *poi* le fa scaricare un file. La finestra non serve a niente — non c'e'
// niente da mostrare — ma resta aperta e vuota, perche' il browser non ha un
// documento da chiuderle sopra. Con un libro e' fastidioso; con dieci libri
// selezionati sarebbero dieci finestre vuote, e Safari ne blocca anche
// qualcuna per sospetto popup.
//
// **Come si fa invece.** Si costruisce un collegamento, gli si dà un click, e
// si butta. Il browser scarica nella pagina dove si è, senza navigare e senza
// finestre.
//
// **Perche' questo funziona, e dove sta la parte che non e' qui.** Un
// collegamento cliccato scarica invece di aprire soltanto se il server
// dichiara il file come allegato (`Content-Disposition: attachment`), e lo
// dichiara: tutti e tre gli endpoint che si usano qui rispondono con un
// `FileResponse` che ha un `filename` (i libri, i file in attesa di
// importazione, lo zip dei backup di un dispositivo). Cioe' il lavoro lo fa
// il server, e il client non deve sapere niente del contenuto.
//
// **Perche' NON si scarica in memoria.** Altrove nel progetto il download
// passa per `fetch` + blob (`pluginDownloadActions.ts`,
// `annotationActions.ts`), ed è giusto la': quei file sono piccoli e
// l'indirizzo vuole un'intestazione di autenticazione che un collegamento non
// può portare. Qui no: un libro può essere un PDF da trecento megabyte, e
// tenerlo tutto in memoria per riconsegnarlo al disco e' uno spreco che si
// paga su un telefono. L'indirizzo porta il token nella sua query proprio per
// questo (vedi `downloadFormatUrl`).

/** Quanto si aspetta fra un file e il successivo, in un gruppo. */
const PAUSA_FRA_FILE_MS = 300

/**
 * Fa scaricare un indirizzo. `nome`, quando c'e', e' il nome proposto — ma
 * conta solo se l'indirizzo e' della stessa origine della pagina: altrimenti
 * il browser lo ignora per sicurezza e tiene quello che dice il server, che
 * e' comunque quello giusto.
 */
export function scaricaIndirizzo(url: string, nome?: string): void {
  const a = document.createElement('a')
  a.href = url
  if (nome) a.download = nome
  // Fuori dalla vista ma nel documento: un collegamento staccato dal
  // documento non riceve il click in tutti i browser.
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

/**
 * Fa scaricare piu' indirizzi, uno dopo l'altro.
 *
 * **Perche' con una pausa in mezzo.** Dieci click nello stesso istante
 * sembrano al browser un tentativo di inondare chi guarda, e Safari e Chrome
 * ne lasciano passare uno e scartano gli altri in silenzio — che e' il modo
 * peggiore di sbagliare, perche' l'utente crede di aver scaricato dieci libri
 * e ne trova uno. Trecento millisecondi bastano a farli contare come richieste
 * distinte.
 *
 * Restituisce quando ha chiesto l'ultimo, non quando sono arrivati: quando un
 * file e' arrivato lo sa solo il browser, e non lo dice.
 */
export async function scaricaIndirizzi(urls: string[]): Promise<void> {
  for (let i = 0; i < urls.length; i++) {
    scaricaIndirizzo(urls[i])
    if (i < urls.length - 1) {
      await new Promise((risolvi) => setTimeout(risolvi, PAUSA_FRA_FILE_MS))
    }
  }
}
