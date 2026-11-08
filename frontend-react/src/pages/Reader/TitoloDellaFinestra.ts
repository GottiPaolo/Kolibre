// Il nome della finestra di lettura.
//
// **Perche' esiste questo file.** I due lettori web sono due pagine separate
// (reader.html per l'EPUB, pdf-reader.html per il PDF) che non condividono
// nessun componente: senza un posto comune, la regola su come si compone quel
// nome finirebbe scritta due volte e, prima o poi, in due modi diversi.
//
// **A cosa serve il nome della finestra.** E' quello che si legge nella
// linguetta del browser, nel passaggio fra finestre del sistema operativo, e
// quello che il browser propone come nome quando si aggiunge la pagina ai
// preferiti. Con piu' libri aperti, «Kolibre — Lettura» tre volte non dice
// quale sia quale: il titolo del libro, invece, lo dice.

const SEPARATORE = ' — '

/**
 * «Titolo — Autore», con quello che c'e'.
 *
 * Le due parti sono trattate come facoltative perche' lo sono per davvero: un
 * file aperto dall'anteprima dell'importazione puo' non avere ne' l'uno ne'
 * l'altro nei suoi metadati, e un autore senza titolo e' un dato mezzo
 * sbagliato che non vale la pena di mostrare da solo. Quindi:
 * titolo e autore -> «Titolo — Autore»; solo il titolo -> «Titolo»; niente
 * titolo -> il nome generico della pagina, che e' sempre meglio di una
 * linguetta vuota o di un trattino solitario.
 *
 * Gli spazi di troppo si tolgono perche' i metadati veri ne sono pieni (un
 * autore letto da un EPUB arriva spesso come «  Karl Marx\n»), e uno spazio
 * invisibile basterebbe a far comparire il separatore senza niente dopo.
 */
export function titoloDellaFinestra(titolo: string | null | undefined,
                                    autore: string | null | undefined,
                                    ripiego: string): string {
  const t = (titolo || '').trim()
  const a = (autore || '').trim()
  if (!t) return ripiego
  return a ? t + SEPARATORE + a : t
}
