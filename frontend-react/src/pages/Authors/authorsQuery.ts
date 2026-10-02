import { containsFolded, foldAccents } from '@/lib/foldAccents'
import type { AuthorSummary } from '@/types/author'
import type { SortCriterion } from '@/pages/Library/sort'
import type { Valori } from '@/lib/i18n'

// Un piccolo linguaggio di ricerca per gli autori.
//
// Prima la casella cercava solo dentro il nome. Serviva qualcosa di piu'
// perche' il pannello laterale rende cliccabili i metadati: premendo
// "italiana" nella nazionalita' di un autore ci si aspetta di vedere gli
// italiani, e per dirlo serve un modo di scrivere "nazionalita = italiana".
//
// Deliberatamente PIU' PICCOLO di quello della libreria
// (lib/libraryQuery.ts): niente or/not/parentesi. I campi di un autore sono
// sei e quasi tutti a valore unico; una grammatica intera qui sarebbe stata
// piu' da imparare che da usare. Le clausole si sommano con la congiunzione,
// che e' quello che si vuole nove volte su dieci — "donne italiane".
//
// Se un giorno servisse di piu', il posto giusto e' allargare QUESTO file,
// non far scrivere all'utente due linguaggi diversi in due pagine.

export type CampoAutore = 'genere' | 'nazionalita' | 'mestiere' | 'epoca' | 'stato'

// Nomi del piccolo linguaggio di ricerca (genere:, nazionalita:, ecc.) — chi
// li digita nella casella usa queste parole in qualunque lingua stia
// l'interfaccia: sono sintassi, non testo da tradurre, come i nomi dei campi
// in lib/libraryQuery.ts.
export const ETICHETTE_CAMPO: Record<CampoAutore, string> = {
  genere: 'Genere',
  nazionalita: 'Nazionalità',
  mestiere: 'Mestiere',
  epoca: 'Epoca',
  stato: 'Stato',
}

const CAMPI = Object.keys(ETICHETTE_CAMPO) as CampoAutore[]

// Etichetta MOSTRATA per un campo (tooltip del pannello laterale) — questa
// invece va tradotta, a differenza della sintassi sopra: qui il nome del
// campo è solo testo visibile, non qualcosa che l'utente digita.
export function etichettaCampo(campo: CampoAutore, t: (chiave: string, valori?: Valori) => string): string {
  switch (campo) {
    case 'genere':
      return t('authors.field.gender')
    case 'nazionalita':
      return t('authors.field.nationality')
    case 'mestiere':
      return t('authors.field.occupation')
    case 'epoca':
      return t('authors.field.era')
    case 'stato':
      return t('authors.field.status')
  }
}

// `campo:"valore"` oppure `campo:valore` (senza spazi), piu' il testo libero.
const TOKEN = /([a-zà-ù_]+):"([^"]*)"|([a-zà-ù_]+):(\S+)|(\S+)/gi

interface Clausola {
  campo: CampoAutore | null
  valore: string
}

function analizza(query: string): Clausola[] {
  const fuori: Clausola[] = []
  for (const m of (query || '').matchAll(TOKEN)) {
    const campo = (m[1] ?? m[3] ?? '').toLowerCase()
    const valore = m[2] ?? m[4] ?? m[5] ?? ''
    if (!valore) continue
    if (campo && (CAMPI as string[]).includes(campo)) {
      fuori.push({ campo: campo as CampoAutore, valore })
    } else {
      // Un campo che non esiste non e' un errore: e' testo. Chi cerca
      // "Rossi:" non deve vedere zero risultati per due punti di troppo.
      fuori.push({ campo: null, valore: campo ? `${campo}:${valore}` : valore })
    }
  }
  return fuori
}

/** Il secolo di nascita, come "XIX" — la stessa nozione della colonna Epoca. */
export function secoloDi(birth_date: string | null | undefined): string | null {
  const anno = Number(String(birth_date ?? '').slice(0, 4))
  if (!anno) return null
  const secolo = Math.floor((anno - 1) / 100) + 1
  const romani = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X',
    'XI', 'XII', 'XIII', 'XIV', 'XV', 'XVI', 'XVII', 'XVIII', 'XIX', 'XX', 'XXI']
  return romani[secolo] ?? String(secolo)
}

export function statoDi(a: AuthorSummary): string | null {
  if (a.death_date) return 'deceduto'
  if (a.birth_date) return 'vivente'
  return null
}

/** I valori di un autore per un campo. Lista perche' le cittadinanze e i
 *  mestieri sono piu' d'uno. */
function valoriDi(a: AuthorSummary, campo: CampoAutore): string[] {
  switch (campo) {
    case 'genere':
      return a.gender ? [a.gender] : []
    case 'nazionalita':
      return a.nationality ?? []
    case 'mestiere':
      return a.occupations ?? []
    case 'epoca': {
      const s = secoloDi(a.birth_date)
      return s ? [s] : []
    }
    case 'stato': {
      const s = statoDi(a)
      return s ? [s] : []
    }
  }
}

export function filtraAutori(autori: AuthorSummary[], query: string): AuthorSummary[] {
  const clausole = analizza(query)
  if (clausole.length === 0) return autori
  return autori.filter((a) =>
    clausole.every((c) => {
      if (c.campo === null) return containsFolded(a.name, c.valore)
      // Corrispondenza esatta sul valore, non "contiene": i metadati degli
      // autori sono etichette chiuse che arrivano da Wikidata, e cliccando
      // "italiana" non si vogliono anche gli "italiana-statunitense".
      const cercato = foldAccents(c.valore).toLowerCase()
      return valoriDi(a, c.campo).some((v) => foldAccents(v).toLowerCase() === cercato)
    })
  )
}

/** La clausola che rappresenta un valore, virgolettata se contiene spazi. */
export function clausolaPer(campo: CampoAutore, valore: string): string {
  return /\s/.test(valore) ? `${campo}:"${valore}"` : `${campo}:${valore}`
}

/**
 * Aggiunge una clausola alla ricerca corrente, o la toglie se c'era gia'.
 *
 * Toglierla e' la meta' che di solito manca: cliccando due volte sullo
 * stesso valore ci si aspetta di tornare indietro, non di ritrovarsi la
 * stessa clausola scritta due volte.
 */
export function conClausola(query: string, campo: CampoAutore, valore: string): string {
  const clausola = clausolaPer(campo, valore)
  const attuale = (query || '').trim()
  if (!attuale) return clausola
  const pezzi = attuale.match(TOKEN) ?? []
  const senza = pezzi.filter((p) => p.toLowerCase() !== clausola.toLowerCase())
  if (senza.length !== pezzi.length) return senza.join(' ')
  return `${attuale} ${clausola}`
}

// ── Ordinamento ─────────────────────────────────────────────────────────

/**
 * Il valore su cui ordinare, per colonna. `null` vuol dire "non lo
 * sappiamo", ed e' diverso da zero o da stringa vuota: i campi che
 * arrivano da Wikidata mancano per parecchi autori, e devono finire in
 * fondo in ENTRAMBI i versi — altrimenti invertendo l'ordine si ottiene una
 * schermata di trattini.
 */
function valoreOrdinamento(a: AuthorSummary, chiave: string): string | number | null {
  switch (chiave) {
    case 'name':
      return a.name
    case 'book_count':
      return a.book_count
    case 'total_pages':
      return a.total_pages
    case 'gender':
      return a.gender
    case 'nationality':
      return a.nationality[0] ?? null
    case 'occupations':
      return a.occupations[0] ?? null
    case 'birth_date':
      return a.birth_date
    case 'death_date':
      return a.death_date
    default:
      return null
  }
}

const mancante = (v: string | number | null) => v === null || v === undefined || v === ''

/** Confronto su piu' criteri in fila: il primo che non pareggia decide. */
export function confrontaAutori(a: AuthorSummary, b: AuthorSummary, criteri: SortCriterion[]): number {
  for (const { key, order } of criteri) {
    const av = valoreOrdinamento(a, key)
    const bv = valoreOrdinamento(b, key)
    if (mancante(av) && mancante(bv)) continue
    if (mancante(av)) return 1
    if (mancante(bv)) return -1
    const cmp =
      typeof av === 'number' && typeof bv === 'number'
        ? av - bv
        : String(av).localeCompare(String(bv), 'it')
    if (cmp !== 0) return order === 'asc' ? cmp : -cmp
  }
  // A parita' di tutto, il nome: senza, due autori identici su ogni campo
  // si scambierebbero di posto ad ogni riordino.
  return a.name.localeCompare(b.name, 'it')
}
