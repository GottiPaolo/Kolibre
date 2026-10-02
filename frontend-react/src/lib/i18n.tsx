import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import it from '@/locales/it.json'
import en from '@/locales/en.json'

// Le due lingue di Kolibre.
//
// **Perché scritto in casa e non react-i18next.** Servono due lingue, nessun
// namespace, nessun caricamento a richiesta, e le regole di plurale di
// italiano e inglese sono la stessa: una forma per l'uno, una per tutto il
// resto. react-i18next porterebbe un albero di macchinari per coprire casi che
// Kolibre non ha, e questo file sta in centoventi righe. Se un giorno
// servissero lingue con plurali veri — polacco, russo, arabo — la sostituzione
// è una riscrittura di questo file solo, perché tutto il resto del programma
// vede unicamente `t()`.
//
// **I cataloghi sono due JSON con le stesse chiavi.** L'italiano è la lingua in
// cui il programma è stato scritto, quindi `it.json` è anche la fonte: una
// chiave che manca in `en.json` ricade sull'italiano invece di mostrare la
// chiave grezza, perché una frase nella lingua sbagliata è leggibile e
// `libreria.vuota.titolo` no.

export type Lingua = 'it' | 'en'

export const LINGUE: { id: Lingua; nome: string }[] = [
  { id: 'it', nome: 'Italiano' },
  { id: 'en', nome: 'English' },
]

const CHIAVE = 'kolibre_lingua'

const CATALOGHI: Record<Lingua, Record<string, string>> = { it, en }

/**
 * La lingua di partenza: quella scelta, altrimenti quella del browser,
 * altrimenti l'italiano.
 *
 * Il browser viene consultato una volta sola, alla prima apertura: dopo
 * comanda la scelta esplicita, anche quando è uguale al predefinito — chi ha
 * scelto «Italiano» su un browser inglese non deve ritrovarsi l'inglese al
 * primo svuotamento della cache del browser.
 */
export function leggiLingua(): Lingua {
  try {
    const salvata = localStorage.getItem(CHIAVE)
    if (salvata === 'it' || salvata === 'en') return salvata
  } catch {
    // Finestra privata o dati del sito bloccati: si decide dal browser.
  }
  return (navigator.language || '').toLowerCase().startsWith('en') ? 'en' : 'it'
}

export function scriviLingua(lingua: Lingua): void {
  try {
    localStorage.setItem(CHIAVE, lingua)
  } catch {
    // Non poter ricordare la scelta non deve impedire di farla.
  }
}

/**
 * I valori da infilare nei segnaposto di una frase.
 *
 * `{nome}` dentro il testo, `{ nome: 'Ada Lovelace' }` qui. Numeri e stringhe
 * soltanto: un segnaposto che accetta JSX trasforma il catalogo in codice, e
 * un traduttore non deve poter rompere la pagina.
 */
export type Valori = Record<string, string | number>

/**
 * Sceglie fra singolare e plurale.
 *
 * Nel catalogo le due forme stanno su una chiave sola, separate da ` | `:
 * «{n} libro | {n} libri». Si usa passando `count`. Lo zero prende il plurale,
 * come in entrambe le lingue («nessun libro» è una frase diversa, e si scrive
 * come tale dove serve).
 */
function scegliForma(testo: string, valori?: Valori): string {
  if (!valori || !('count' in valori) || !testo.includes(' | ')) return testo
  const [uno, molti] = testo.split(' | ')
  return Number(valori.count) === 1 ? uno : molti
}

function riempi(testo: string, valori?: Valori): string {
  if (!valori) return testo
  return testo.replace(/\{(\w+)\}/g, (intero, chiave) =>
    chiave in valori ? String(valori[chiave]) : intero
  )
}

export function traduci(lingua: Lingua, chiave: string, valori?: Valori): string {
  // L'italiano come rete: una chiave non ancora tradotta mostra la frase
  // italiana, non il suo nome. Una frase nella lingua sbagliata si legge,
  // «libreria.vuota.titolo» no.
  const testo = CATALOGHI[lingua]?.[chiave] ?? CATALOGHI.it[chiave] ?? chiave
  return riempi(scegliForma(testo, valori), valori)
}

interface Contesto {
  lingua: Lingua
  cambiaLingua: (l: Lingua) => void
  t: (chiave: string, valori?: Valori) => string
}

const ContestoLingua = createContext<Contesto | null>(null)

export function ProviderLingua({ children }: { children: ReactNode }) {
  const [lingua, setLingua] = useState<Lingua>(() => leggiLingua())

  const cambiaLingua = useCallback((l: Lingua) => {
    scriviLingua(l)
    setLingua(l)
    // L'attributo `lang` del documento non è decorativo: lo leggono i lettori
    // di schermo per scegliere la pronuncia, e la sillabazione del browser.
    document.documentElement.lang = l
  }, [])

  const valore = useMemo<Contesto>(
    () => ({ lingua, cambiaLingua, t: (chiave, valori) => traduci(lingua, chiave, valori) }),
    [lingua, cambiaLingua]
  )

  return <ContestoLingua.Provider value={valore}>{children}</ContestoLingua.Provider>
}

/** `const { t } = useLingua()` — l'unica cosa che il resto del programma vede. */
export function useLingua(): Contesto {
  const c = useContext(ContestoLingua)
  if (!c) throw new Error('useLingua va usato dentro ProviderLingua')
  return c
}

// Numeri e date non sono "testo da tradurre", ma seguono la lingua lo stesso:
// in italiano ventimilioni si scrive 20.360.092 e in inglese 20,360,092, e un
// numero scritto con le convenzioni sbagliate si legge male o si legge storto.
// Prima erano 41 chiamate a toLocaleString('it-IT') sparse in dodici file.
//
// en-GB e non en-US: l'unica differenza che conta qui è l'ordine di giorno e
// mese, e il resto del programma scrive le date col giorno davanti.
const LOCALI: Record<Lingua, string> = { it: 'it-IT', en: 'en-GB' }

export function localeDi(lingua: Lingua): string {
  return LOCALI[lingua]
}

/** Un numero come lo scrive la lingua attiva. Vedi `t` qui sotto per il perché
 *  legge la lingua dalla memoria invece che dal contesto. */
export function numero(n: number, opzioni?: Intl.NumberFormatOptions): string {
  return n.toLocaleString(LOCALI[leggiLingua()], opzioni)
}

/**
 * Un numero grande scritto corto: «1,2 M» in italiano, «1.2M» in inglese.
 *
 * Un conteggio di caratteri si legge solo abbreviato — «1.203.918» non dice
 * niente a nessuno. Erano cinque copie della stessa funzione sparse fra
 * grafici e pannelli, tutte con `.replace('.', ',')` cablato: in inglese
 * quella virgola si legge come separatore di migliaia, quindi «1,2 M»
 * sembrava un numero mille volte più piccolo.
 */
export function numeroCompatto(n: number): string {
  if (n >= 1_000_000) return `${numero(n / 1_000_000, { maximumFractionDigits: 1, minimumFractionDigits: 1 })} M`
  if (n >= 1_000) return `${numero(Math.round(n / 1000))} K`
  return numero(n)
}

/**
 * La lingua corrente FUORI da un componente React.
 *
 * Serve ai moduli di `lib/` che costruiscono messaggi senza stare in un albero
 * di componenti — le azioni, i messaggi di errore, gli export. Legge dalla
 * memoria invece che dal contesto: è la stessa fonte, e l'alternativa sarebbe
 * passare `t` attraverso venti funzioni che non hanno altro motivo di
 * conoscerlo.
 */
export function t(chiave: string, valori?: Valori): string {
  return traduci(leggiLingua(), chiave, valori)
}
