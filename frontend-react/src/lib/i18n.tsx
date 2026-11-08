import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import it from '@/locales/it.json'
import en from '@/locales/en.json'
import { leggiLingua, scriviLingua, type Lingua } from './linguaScelta'
import { salvaPreferenze } from './preferenzeUtente'

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
// **I cataloghi sono due JSON con le stesse chiavi**, e la rete è
// l'**inglese**: una chiave che manca ricade sulla frase inglese invece di
// mostrare il proprio nome, perché una frase nella lingua sbagliata è
// leggibile e `libreria.vuota.titolo` no. L'italiano è la lingua in cui il
// programma è stato scritto, ma dal 07/10/2026 non è più la rete — vedi
// `traduci` più sotto per il perché: con l'italiano sotto, una chiave che
// mancava in inglese non si vedeva.

// Il tipo vive in `linguaScelta.ts`, con la funzione che decide: era scritto
// in due posti, ed e' esattamente il genere di doppione che questo giro di
// lavoro serve a togliere.
export type { Lingua }
// Rimandate da qui perche' meta' del programma le importa da `i18n`, ed e' il
// posto dove si va a cercarle. Vivono in `linguaScelta.ts`, con la funzione
// che decide quale delle tre fonti ha ragione.
export { leggiLingua, scriviLingua } from './linguaScelta'

// L'inglese per primo perche' e' il predefinito: l'elenco di una scelta
// comincia da quello che si ottiene senza scegliere.
export const LINGUE: { id: Lingua; nome: string }[] = [
  { id: 'en', nome: 'English' },
  { id: 'it', nome: 'Italiano' },
]

const CATALOGHI: Record<Lingua, Record<string, string>> = { it, en }

/**
 * La lingua di partenza: quella scelta, altrimenti quella del browser,
 * altrimenti **l'inglese**.
 *
 * Il browser viene consultato una volta sola, alla prima apertura: dopo
 * comanda la scelta esplicita, anche quando è uguale al predefinito — chi ha
 * scelto «Italiano» su un browser inglese non deve ritrovarsi l'inglese al
 * primo svuotamento della cache del browser.
 *
 * **Perché l'inglese e non l'italiano** (cambiato il 07/10/2026). La regola
 * era «se il browser dice inglese, inglese; altrimenti italiano»: giusta per
 * un impianto italiano, sbagliata per un programma che si scarica. Un
 * tedesco, un francese, uno spagnolo aprivano Kolibre e lo trovavano in
 * italiano — non nella loro lingua, e nemmeno in quella che tutti leggono.
 * Ora l'italiano si prende chi ha il browser in italiano, e tutti gli altri
 * hanno l'inglese.
 */
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
  // **L'inglese come rete**, dal 07/10/2026: una chiave non ancora tradotta
  // mostra la frase inglese, non il suo nome. Una frase nella lingua
  // sbagliata si legge, «libreria.vuota.titolo» no.
  //
  // Era l'italiano, ed e' la stessa inversione del predefinito qui sopra: con
  // l'italiano come rete, una chiave che manca in inglese non si vedeva —
  // restava in italiano e sembrava a posto. Ora si vede il contrario, e si
  // vede subito, perche' la rete e' la lingua che quasi tutti leggono.
  const testo = CATALOGHI[lingua]?.[chiave] ?? CATALOGHI.en[chiave] ?? chiave
  return riempi(scegliForma(testo, valori), valori)
}

interface Contesto {
  lingua: Lingua
  /**
   * **La persona ha scelto.** Salva in questo browser *e* sul server, perche'
   * una scelta vale su ogni client: chi sceglie l'italiano sul portatile deve
   * trovare l'italiano sul telefono.
   */
  cambiaLingua: (l: Lingua) => void
  /**
   * **Ci si allinea a una scelta gia' fatta**, che il server ci ha appena
   * detto. Non e' una scelta nuova, quindi NON si rimanda al server: farlo
   * vorrebbe dire riscrivergli quello che ci ha appena mandato, a ogni
   * apertura di pagina. Non e' per l'interfaccia — la usa solo
   * `useAllineaLaLingua`.
   */
  allineaLingua: (l: Lingua) => void
  t: (chiave: string, valori?: Valori) => string
}

const ContestoLingua = createContext<Contesto | null>(null)

export function ProviderLingua({ children }: { children: ReactNode }) {
  const [lingua, setLingua] = useState<Lingua>(() => leggiLingua())

  const allineaLingua = useCallback((l: Lingua) => {
    scriviLingua(l)
    setLingua(l)
    // L'attributo `lang` del documento non è decorativo: lo leggono i lettori
    // di schermo per scegliere la pronuncia, e la sillabazione del browser.
    document.documentElement.lang = l
  }, [])

  const cambiaLingua = useCallback((l: Lingua) => {
    allineaLingua(l)
    // E sul server, perché è una scelta della PERSONA e non di questo
    // schermo: vedi lib/preferenzeUtente.ts. Non si aspetta — la lingua è
    // già cambiata sotto gli occhi di chi ha cliccato.
    void salvaPreferenze({ lingua: l })
  }, [allineaLingua])

  const valore = useMemo<Contesto>(
    () => ({ lingua, cambiaLingua, allineaLingua, t: (chiave, valori) => traduci(lingua, chiave, valori) }),
    [lingua, cambiaLingua, allineaLingua]
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
