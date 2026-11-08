// Ricerca nel testo di un capitolo, tollerante come serve a un libro vero.
//
// **Perche' non basta quella del motore.** epub.js ne offre due e sbagliano
// entrambe, in modi diversi: `section.find()` fa `indexOf` su UN SOLO nodo di
// testo per volta, quindi qualunque frase che attraversi un corsivo o un
// rimando di nota non si trova mai; `section.search()` concatena cinque nodi
// consecutivi — meglio — ma usa ancora `indexOf` sul testo grezzo, quindi non
// tollera ne' la spaziatura ne' la sillabazione.
//
// E non e' un dettaglio estetico: questa ricerca e' il ripiego con cui si
// ritrova un'evidenziazione che ha perso l'ancora. Il server ci riesce (la sua
// `search_normalized` costruisce una regex `token\s+token` sul testo collassato
// di tutto il capitolo) e il lettore no — ed e' il motivo per cui una nota
// risulta ancorata nella pagina Annotazioni e poi nel reader "non si trova".
//
// **Le quattro tolleranze**, tutte prese da casi reali:
//
//  1. **Attraversa gli elementi.** Il capitolo intero diventa una stringa sola,
//     con una mappa che riporta ogni carattere al suo nodo di testo. Un
//     `<em>` in mezzo alla frase smette di essere un muro.
//  2. **La spaziatura non conta.** Nel file c'e' un ritorno a capo dove la
//     query ha uno spazio: ogni spazio diventa `\s+`.
//  3. **La sillabazione dell'editore.** Un testo giustificato e' pieno di
//     soft hyphen invisibili: cercando "parola" il file contiene `pa­ro­la`.
//     Ogni carattere e' separato dal successivo da una sequenza opzionale di
//     caratteri invisibili. E' il trucco del viewer di Calibre
//     (`src/pyj/read_book/search_worker.pyj`, `text_to_regex`), ed e' una
//     riga di regex che risolve un problema che altrimenti non si risolve.
//  4. **Accenti, maiuscole e virgolette.** "perche" trova "perché", le
//     virgolette dritte trovano quelle curve, i trattini si equivalgono.
//
// **La piega e' garantita uno-a-uno**, al contrario di `lib/foldAccents.ts`:
// quella passa per NFD e puo' cambiare la lunghezza della stringa, il che qui
// sfaserebbe la mappa carattere → nodo e farebbe puntare le evidenziazioni al
// posto sbagliato. Qui si piega un carattere per volta e, se il risultato non
// e' lungo esattamente uno, si tiene l'originale.

import type Section from 'epubjs/types/section'
import type { EpubSearchMatch } from './EpubTypes'

/** Soft hyphen, zero-width space, ZWNJ, ZWJ: invisibili, e in mezzo alle parole. */
const INVISIBILI = '[\\u00AD\\u200B\\u200C\\u200D]*'

const VIRGOLETTE_SEMPLICI = "'‘’ʼ"
const VIRGOLETTE_DOPPIE = '"“”«»'
const TRATTINI = '-‐‑–—'

const CARATTERI_PER_ESTRATTO = 60

/** Minuscolo e senza accenti, ma SEMPRE un carattere solo. */
function piega(ch: string): string {
  const senzaAccento = ch.normalize('NFD').replace(/\p{Diacritic}/gu, '')
  const base = senzaAccento.length === 1 ? senzaAccento : ch
  const minuscolo = base.toLowerCase()
  return minuscolo.length === 1 ? minuscolo : base
}

function escapeRegex(ch: string): string {
  return ch.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

interface Pezzo {
  nodo: Text
  /** Posizione del primo carattere di questo nodo dentro la stringa unica. */
  inizio: number
}

interface IndiceCapitolo {
  /** Il capitolo come una stringa sola, piegata. Stessa lunghezza del grezzo. */
  piegato: string
  /** Lo stesso testo non piegato, per gli estratti leggibili. */
  grezzo: string
  pezzi: Pezzo[]
}

function indicizza(doc: Document): IndiceCapitolo {
  const pezzi: Pezzo[] = []
  const grezzo: string[] = []
  const piegato: string[] = []
  let lunghezza = 0

  const walker = doc.createTreeWalker(doc.body ?? doc, NodeFilter.SHOW_TEXT, null)
  let nodo = walker.nextNode() as Text | null
  while (nodo) {
    const testo = nodo.data
    if (testo.length > 0) {
      pezzi.push({ nodo, inizio: lunghezza })
      grezzo.push(testo)
      // Carattere per carattere, non `[...testo].map`: le coppie surrogate
      // vanno lasciate stare, e piegandole si cambierebbe la lunghezza.
      let p = ''
      for (let i = 0; i < testo.length; i++) p += piega(testo[i])
      piegato.push(p)
      lunghezza += testo.length
    }
    nodo = walker.nextNode() as Text | null
  }
  return { piegato: piegato.join(''), grezzo: grezzo.join(''), pezzi }
}

/** Il nodo e l'offset a cui corrisponde una posizione nella stringa unica. */
function posizione(pezzi: Pezzo[], indice: number): { nodo: Text; offset: number } | null {
  if (pezzi.length === 0) return null
  let basso = 0
  let alto = pezzi.length - 1
  while (basso < alto) {
    const mezzo = Math.ceil((basso + alto) / 2)
    if (pezzi[mezzo].inizio <= indice) basso = mezzo
    else alto = mezzo - 1
  }
  const pezzo = pezzi[basso]
  const offset = indice - pezzo.inizio
  // Un indice oltre la fine dell'ultimo nodo non e' una posizione valida.
  if (offset > pezzo.nodo.data.length) return null
  return { nodo: pezzo.nodo, offset }
}

/** La regex tollerante, o `null` se la query non ha niente di cercabile. */
export function regexDaQuery(query: string): RegExp | null {
  let piegata = ''
  for (let i = 0; i < query.length; i++) piegata += piega(query[i])
  piegata = piegata.trim()
  if (piegata.length < 2) return null

  const parti: string[] = []
  let ultimoEraSpazio = false
  for (const ch of piegata) {
    if (/\s/.test(ch)) {
      // Spazi consecutivi nella query non devono diventare `\s+\s+`, che
      // pretenderebbe due gruppi di spazi distinti nel testo.
      if (!ultimoEraSpazio) parti.push('\\s+')
      ultimoEraSpazio = true
      continue
    }
    ultimoEraSpazio = false
    if (VIRGOLETTE_SEMPLICI.includes(ch)) parti.push(`[${VIRGOLETTE_SEMPLICI}]`)
    else if (VIRGOLETTE_DOPPIE.includes(ch)) parti.push(`[${VIRGOLETTE_DOPPIE}]`)
    else if (TRATTINI.includes(ch)) parti.push(`[${TRATTINI}]`)
    else parti.push(escapeRegex(ch))
  }
  if (parti.length === 0) return null

  try {
    return new RegExp(parti.join(INVISIBILI), 'g')
  } catch {
    return null
  }
}

/**
 * Cerca `query` nel capitolo gia' caricato di `section`.
 *
 * Il documento deve essere gia' disponibile (`section.load()` fatto): questa
 * funzione non carica niente, come le due di epub.js che sostituisce.
 */
export function cercaNellaSezione(section: Section, query: string, massimo = 200): EpubSearchMatch[] {
  const doc = (section as unknown as { document?: Document }).document
  if (!doc) return []
  const regex = regexDaQuery(query)
  if (!regex) return []

  const { piegato, grezzo, pezzi } = indicizza(doc)
  if (!piegato) return []

  const risultati: EpubSearchMatch[] = []
  let m: RegExpExecArray | null
  while ((m = regex.exec(piegato)) !== null && risultati.length < massimo) {
    // Una corrispondenza vuota farebbe girare a vuoto il ciclo per sempre.
    if (m[0].length === 0) { regex.lastIndex++; continue }

    const da = posizione(pezzi, m.index)
    const a = posizione(pezzi, m.index + m[0].length)
    if (!da || !a) continue

    try {
      const range = doc.createRange()
      range.setStart(da.nodo, da.offset)
      range.setEnd(a.nodo, a.offset)
      const cfi = (section as unknown as { cfiFromRange(r: Range): string }).cfiFromRange(range)
      if (!cfi) continue

      const inizioEstratto = Math.max(0, m.index - CARATTERI_PER_ESTRATTO)
      const fineEstratto = Math.min(grezzo.length, m.index + m[0].length + CARATTERI_PER_ESTRATTO)
      const estratto = (inizioEstratto > 0 ? '…' : '')
        + grezzo.slice(inizioEstratto, fineEstratto).replace(/\s+/g, ' ').trim()
        + (fineEstratto < grezzo.length ? '…' : '')

      risultati.push({ cfi, excerpt: estratto })
    } catch {
      // Un Range che il documento rifiuta non deve far cadere tutta la ricerca.
    }
  }
  return risultati
}

// ─────────────────────────────────────────────────────────────────────────
// Spostare un estremo di un intervallo di una frase per volta
//
// Serve a «Estendi»: la prima versione riapriva la selezione sul brano e
// chiedeva di rifarla a mano. Non serviva a niente — se devi riselezionare
// tutto, «estendi» non fa nulla che «elimina e rifai» non facesse gia'. E non
// si capiva nemmeno quale estremo si stesse muovendo.
//
// Qui invece si muove UN estremo per volta, di UNA frase per volta, e lo si
// vede subito perche' l'evidenziazione si ridisegna a ogni passo. Niente
// maniglie da trascinare, quindi niente eventi nuovi da intercettare dentro
// l'iframe — che e' il muro su cui si erano fermati pinch e frecce ai bordi.
//
// Una frase e non una parola perche' e' l'unita' con cui si pensa leggendo:
// «prendi anche la frase dopo» e' una cosa che si vuole davvero, «prendi anche
// la parola dopo» quasi mai.
// ─────────────────────────────────────────────────────────────────────────

// ── Confini di PAROLA ────────────────────────────────────────────────────
//
// A frasi il passo era troppo grosso: una frase di un libro vero sono righe
// intere, e per togliere tre parole in fondo si finiva a rifare la selezione.
//
// La punteggiatura sta con la parola che la precede, e solo ANDANDO AVANTI:
// allargando la fine si prende «parola,» per intero, perche' nessuno vuole
// un'evidenziazione che finisce prima della virgola. Allargando l'inizio
// invece non si tira dentro la punteggiatura della frase precedente, che
// apparterrebbe a un'altra proposizione.

/** Dove finisce una parola, punteggiatura attaccata inclusa. */
const FINE_PAROLA = /[^\s]+[.,;:!?…»"'\u201D\u2019)\]]*/g

/** Gli indici dove COMINCIA una parola. */
function iniziParola(testo: string): number[] {
  const out: number[] = []
  const re = /\S+/g
  let m: RegExpExecArray | null
  while ((m = re.exec(testo)) !== null) out.push(m.index)
  return out
}

/** Gli indici dove FINISCE una parola, con la sua punteggiatura. */
function finiParola(testo: string): number[] {
  const out: number[] = []
  FINE_PAROLA.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = FINE_PAROLA.exec(testo)) !== null) {
    if (m[0].length === 0) { FINE_PAROLA.lastIndex++; continue }
    out.push(m.index + m[0].length)
  }
  return out
}

/** Fine frase. Il punto va seguito da spazio o fine testo: «2.500» non lo e'. */
const FINE_FRASE = /[.!?;:…»"'”’]+(?=\s|$)/g

export type Estremo = 'inizio' | 'fine'
export type Verso = 'allarga' | 'stringe'

/** L'indice, nella stringa unica del capitolo, di un punto (nodo + offset). */
function indiceDi(pezzi: Pezzo[], nodo: Node, offset: number): number | null {
  for (const p of pezzi) {
    if (p.nodo === nodo) return p.inizio + offset
  }
  return null
}

/** Dove FINISCONO le frasi. Sono le posizioni buone per l'estremo destro. */
function fini(testo: string): number[] {
  const out: number[] = []
  FINE_FRASE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = FINE_FRASE.exec(testo)) !== null) out.push(m.index + m[0].length)
  if (out[out.length - 1] !== testo.length) out.push(testo.length)
  return out
}

/**
 * Dove COMINCIANO le frasi. Non sono i fini.
 *
 * Fra la fine di una frase e l'inizio della successiva c'e' lo spazio, e
 * confonderli e' l'errore che faceva tornare «allarga dall'inizio» alla FINE
 * della frase precedente invece che al suo inizio — cioe' non allargava
 * affatto.
 */
function inizi(testo: string): number[] {
  const out = [0]
  for (const f of fini(testo)) {
    let i = f
    while (i < testo.length && /\s/.test(testo[i])) i++
    if (i < testo.length && i !== out[out.length - 1]) out.push(i)
  }
  return out
}

/** Il primo valore di `lista` maggiore di `da`, o `null`. */
function dopo(lista: number[], da: number): number | null {
  for (const v of lista) if (v > da) return v
  return null
}

/** L'ultimo valore di `lista` minore di `da`, o `null`. */
function prima(lista: number[], da: number): number | null {
  let out: number | null = null
  for (const v of lista) {
    if (v >= da) break
    out = v
  }
  return out
}

/**
 * Sposta un estremo di `range` di una frase, e restituisce il Range nuovo.
 *
 * `null` quando non c'e' piu' niente da prendere in quella direzione, o
 * quando l'intervallo si ridurrebbe a niente: il chiamante puo' spegnere il
 * bottone invece di far premere a vuoto.
 */
/**
 * Come `spostaEstremoDiUnaFrase` ma di una parola. E' quella che usa il
 * lettore: il passo a frasi restava troppo grosso per aggiustare un brano.
 */
export function spostaEstremoDiUnaParola(
  doc: Document,
  range: Range,
  estremo: Estremo,
  verso: Verso,
): Range | null {
  const { grezzo, pezzi } = indicizza(doc)
  const da = indiceDi(pezzi, range.startContainer, range.startOffset)
  const a = indiceDi(pezzi, range.endContainer, range.endOffset)
  if (da == null || a == null) return null

  let nuovoDa = da
  let nuovoA = a
  if (estremo === 'fine') {
    const lista = finiParola(grezzo)
    const prossimo = verso === 'allarga' ? dopo(lista, a) : prima(lista, a)
    if (prossimo == null) return null
    nuovoA = prossimo
  } else {
    const lista = iniziParola(grezzo)
    const corrente = prima(lista, da + 1) ?? 0
    const prossimo = verso === 'allarga' ? prima(lista, corrente) : dopo(lista, corrente)
    if (prossimo == null) return null
    nuovoDa = prossimo
  }
  if (nuovoA - nuovoDa < 1) return null
  if (nuovoDa === da && nuovoA === a) return null

  const inizio = posizione(pezzi, nuovoDa)
  const fine = posizione(pezzi, nuovoA)
  if (!inizio || !fine) return null
  try {
    const nuovo = doc.createRange()
    nuovo.setStart(inizio.nodo, inizio.offset)
    nuovo.setEnd(fine.nodo, fine.offset)
    return nuovo
  } catch {
    return null
  }
}

export function spostaEstremoDiUnaFrase(
  doc: Document,
  range: Range,
  estremo: Estremo,
  verso: Verso,
): Range | null {
  const { grezzo, pezzi } = indicizza(doc)
  const da = indiceDi(pezzi, range.startContainer, range.startOffset)
  const a = indiceDi(pezzi, range.endContainer, range.endOffset)
  if (da == null || a == null) return null

  let nuovoDa = da
  let nuovoA = a
  if (estremo === 'fine') {
    const lista = fini(grezzo)
    const prossimo = verso === 'allarga' ? dopo(lista, a) : prima(lista, a)
    if (prossimo == null) return null
    nuovoA = prossimo
  } else {
    const lista = inizi(grezzo)
    // Si parte dall'inizio della frase in cui l'estremo si trova: se e' in
    // mezzo a una frase, il primo passo lo porta al suo confine, che e' quello
    // che ci si aspetta.
    const corrente = prima(lista, da + 1) ?? 0
    const prossimo = verso === 'allarga' ? prima(lista, corrente) : dopo(lista, corrente)
    if (prossimo == null) return null
    nuovoDa = prossimo
  }
  // Un intervallo deve restare un intervallo: se gli estremi si incrociano o
  // si toccano, quel bottone non ha piu' niente da fare.
  if (nuovoA - nuovoDa < 2) return null
  if (nuovoDa === da && nuovoA === a) return null

  const inizio = posizione(pezzi, nuovoDa)
  const fine = posizione(pezzi, nuovoA)
  if (!inizio || !fine) return null
  try {
    const nuovo = doc.createRange()
    nuovo.setStart(inizio.nodo, inizio.offset)
    nuovo.setEnd(fine.nodo, fine.offset)
    return nuovo
  } catch {
    return null
  }
}
