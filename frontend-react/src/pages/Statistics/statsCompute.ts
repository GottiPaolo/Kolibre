// Porting diretto delle computed della dashboard Statistiche in
// frontend/src/App.vue (righe ~4991-5945): funzioni pure, nessuno stato,
// così StatisticsPage e le sue tab possono richiamarle dentro useMemo senza
// duplicare la logica di aggregazione. Un test di fedeltà riga per riga con
// l'originale è nel report di questa fase, non qui.
import type { ReadingSessionRaw, ReadingStatsSummary, TimelineEntry } from '@/lib/statsQueries'
import type { Valori } from '@/lib/i18n'
import { isoLocale } from '@/lib/format'

type Traduci = (chiave: string, valori?: Valori) => string

export function formatDurationHuman(totalSeconds: number): string {
  const mins = Math.round((totalSeconds || 0) / 60)
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

// Le statistiche di CATALOGO non si calcolano piu' qui: le conta il server
// (stats_service.panoramica_biblioteca, GET /stats/library-overview). Il
// browser le ricavava dai libri, e per farlo doveva scaricare il catalogo
// intero — quasi sei megabyte su una biblioteca da 5.843 libri, per un paio
// di chilobyte di conteggi. Sono state SPOSTATE, non duplicate: qui non ne
// resta nessuna copia.
//
// Resta invece tutto quello che sta sotto, che deriva dalle sessioni di
// lettura e non dal catalogo.

export interface CountDatum {
  label: string
  count: number
  percent: number
}

// ── Statistiche Lettura — derivate da stats/raw + stats/timeline ──

// Funzioni e non array costanti: devono ricalcolarsi al cambio lingua,
// stesso motivo di fixedColumnLabels in lib/libraryColumns.ts.
export function weekdayLabels(t: Traduci): string[] {
  return [
    t('stats.reading.weekday.mon'),
    t('stats.reading.weekday.tue'),
    t('stats.reading.weekday.wed'),
    t('stats.reading.weekday.thu'),
    t('stats.reading.weekday.fri'),
    t('stats.reading.weekday.sat'),
    t('stats.reading.weekday.sun'),
  ]
}

export function monthLabels(t: Traduci): string[] {
  return [
    t('stats.reading.month.jan'),
    t('stats.reading.month.feb'),
    t('stats.reading.month.mar'),
    t('stats.reading.month.apr'),
    t('stats.reading.month.may'),
    t('stats.reading.month.jun'),
    t('stats.reading.month.jul'),
    t('stats.reading.month.aug'),
    t('stats.reading.month.sep'),
    t('stats.reading.month.oct'),
    t('stats.reading.month.nov'),
    t('stats.reading.month.dec'),
  ]
}

// Settimana Lunedì-first (YYYY-MM-DD), offset in settimane intere dalla
// corrente — negativo va indietro, positivo avanti.
export function weekDates(offset: number): string[] {
  const now = new Date()
  const monday = new Date(now)
  const dow = (monday.getDay() + 6) % 7 // 0 = lunedì
  monday.setDate(monday.getDate() - dow + offset * 7)
  monday.setHours(0, 0, 0, 0)
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday)
    d.setDate(d.getDate() + i)
    return isoLocale(d)
  })
}

export interface StackedDataset {
  label: string
  data: number[]
}

// Top-8-libri-per-tempo-nel-periodo + bucket "Altro" per il resto — stessa
// logica di App.vue::_buildStackedByBookDatasets, così un pugno di libri
// dominanti non trasforma l'istogramma in un arcobaleno illeggibile con
// decine di libri letti.
/**
 * Le due unità con cui si può misurare la lettura.
 *
 * Non sono interscambiabili e la differenza è il motivo per cui si sceglie:
 * i minuti dicono quanto TEMPO hai dato a un libro, i caratteri quanto ne hai
 * PERCORSO. Un saggio riletto tre volte sullo stesso capitolo e un romanzo
 * divorato occupano gli stessi minuti e un numero di caratteri molto diverso.
 * Distinzione introdotta il 01/10/2026 sugli istogrammi.
 */
export type Misura = 'minuti' | 'caratteri'

/** Il valore di una sessione nella misura scelta. */
export function valoreSessione(s: ReadingSessionRaw, misura: Misura): number {
  return misura === 'caratteri' ? s.chars_read || 0 : Math.round(s.duration_seconds / 60)
}

/** L'unità dell'asse Y della misura scelta, come la vuole BarChart. */
export function unitaMisura(misura: Misura): 'car' | 'min' {
  return misura === 'caratteri' ? 'car' : 'min'
}

export function buildStackedByBookDatasets(
  dayKeys: string[],
  sessions: ReadingSessionRaw[],
  keyFn: (s: ReadingSessionRaw) => string,
  t: Traduci,
  misura: Misura = 'minuti'
): StackedDataset[] {
  const other = t('stats.other')
  const inPeriod = sessions.filter((s) => dayKeys.includes(keyFn(s)))
  // Le serie si scelgono SEMPRE sul tempo, anche quando si mostrano i
  // caratteri: altrimenti cambiando misura cambierebbero anche i libri in
  // legenda, e due viste dello stesso periodo smetterebbero di essere
  // confrontabili proprio nel momento in cui le si confronta.
  const totals: Record<string, number> = {}
  for (const s of inPeriod) totals[s.book_title] = (totals[s.book_title] || 0) + s.duration_seconds
  const top = Object.entries(totals)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([t]) => t)
  const hasOther = Object.keys(totals).length > top.length
  const seriesNames = hasOther ? [...top, other] : top

  return seriesNames.map((name) => ({
    label: name,
    data: dayKeys.map((key) =>
      inPeriod
        .filter((s) => keyFn(s) === key && (name === other ? !top.includes(s.book_title) : s.book_title === name))
        .reduce((sum, s) => sum + valoreSessione(s, misura), 0)
    ),
  }))
}

/**
 * I lunedì delle ultime `quante` settimane, dal più vecchio al più recente.
 *
 * Serve all'istogramma delle settimane: quello dei giorni risponde a «com'è
 * andata questa settimana», e per sapere se stai leggendo più o meno di un mese
 * fa non serve a niente — bisogna cambiare settimana sette volte e ricordarsi
 * i numeri.
 */
export function weekStarts(quante: number): string[] {
  const oggi = new Date()
  // Lunedì come primo giorno, come in weekDates: getDay() dà 0 per domenica.
  const lunedi = new Date(oggi)
  lunedi.setDate(oggi.getDate() - ((oggi.getDay() + 6) % 7))
  const out: string[] = []
  for (let i = quante - 1; i >= 0; i--) {
    const d = new Date(lunedi)
    d.setDate(lunedi.getDate() - i * 7)
    out.push(dataLocale(d))
  }
  return out
}

/** Il lunedì della settimana di una data 'YYYY-MM-DD'. */
export function inizioSettimanaDi(data: string): string {
  const [y, m, g] = data.split('-').map(Number)
  const d = new Date(y, m - 1, g)
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7))
  return dataLocale(d)
}

/** Etichetta breve per una settimana: "6 ott". */
export function etichettaSettimana(inizio: string, t: Traduci): string {
  const [, m, g] = inizio.split('-').map(Number)
  return `${g} ${monthLabels(t)[m - 1].toLowerCase()}`
}

export function peakHoursBuckets(sessions: ReadingSessionRaw[], t: Traduci): CountDatum[] {
  const LABELS = {
    morning: t('stats.reading.peakHours.morning'),
    afternoon: t('stats.reading.peakHours.afternoon'),
    evening: t('stats.reading.peakHours.evening'),
    night: t('stats.reading.peakHours.night'),
  }
  const buckets: Record<string, number> = {
    [LABELS.morning]: 0,
    [LABELS.afternoon]: 0,
    [LABELS.evening]: 0,
    [LABELS.night]: 0,
  }
  for (const s of sessions) {
    const hour = new Date(s.start_time).getHours()
    if (hour >= 6 && hour < 12) buckets[LABELS.morning] += s.duration_seconds
    else if (hour >= 12 && hour < 18) buckets[LABELS.afternoon] += s.duration_seconds
    else if (hour >= 18) buckets[LABELS.evening] += s.duration_seconds
    else buckets[LABELS.night] += s.duration_seconds
  }
  const total = Object.values(buckets).reduce((a, b) => a + b, 0) || 1
  return Object.entries(buckets).map(([label, secs]) => ({ label, count: secs, percent: Math.round((secs / total) * 100) }))
}




/**
 * Da quanti giorni di fila si legge.
 *
 * Due dettagli che sembrano pedanteria e non lo sono:
 *
 * 1. Se OGGI non si e' ancora letto, la striscia si conta da IERI. Senza,
 *    chi legge tutte le sere si vedeva "0 giorni" ogni mattina fino alla
 *    prima pagina della giornata: una striscia viva raccontata come
 *    interrotta, che e' il modo peggiore di dare un numero del genere. Si
 *    azzera solo quando saltano DUE giorni, che e' quando e' davvero rotta.
 *
 * 2. La data di oggi si prende in ora LOCALE, non con toISOString(), che
 *    torna la data UTC. In Italia d'estate fra mezzanotte e le due di notte
 *    l'UTC e' ancora il giorno prima: leggendo all'una la sessione finiva in
 *    un giorno e il confronto nell'altro.
 */
function dataLocale(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export function currentStreakDays(sessions: ReadingSessionRaw[]): number {
  const giorniLetti = new Set(sessions.map((s) => s.date))
  const d = new Date()
  if (!giorniLetti.has(dataLocale(d))) d.setDate(d.getDate() - 1)
  let streak = 0
  while (giorniLetti.has(dataLocale(d))) {
    streak++
    d.setDate(d.getDate() - 1)
  }
  return streak
}

export function readingSpeedPagesPerHour(summary: ReadingStatsSummary | null | undefined): number {
  if (!summary || !summary.total_time_seconds) return 0
  return Math.round(summary.total_pages / (summary.total_time_seconds / 3600))
}

/**
 * Velocità di lettura in caratteri all'ora — l'unica che si possa
 * confrontare fra libri, dispositivi e impostazioni di carattere diverse
 * (una "pagina" di KOReader dipende dal corpo del carattere: vedi il report
 * sulle statistiche).
 *
 * Divide sul tempo delle SOLE sessioni che hanno un conteggio caratteri, non
 * sul tempo totale: mescolare i caratteri di alcune sessioni con le ore di
 * tutte darebbe una velocità sistematicamente troppo bassa.
 *
 * `null` quando non c'è abbastanza materiale, così chi mostra il dato può
 * ricadere sulle pagine invece di scrivere uno zero che sembra una misura.
 */
export function readingSpeedCharsPerHour(summary: ReadingStatsSummary | null | undefined): number | null {
  if (!summary || !summary.total_chars || !summary.chars_time_seconds) return null
  return Math.round(summary.total_chars / (summary.chars_time_seconds / 3600))
}



export interface HeatmapDay {
  date: string
  minutes: number
  value: 0 | 1 | 2 | 3 | 4
}

export function buildHeatmapDays(timeline: TimelineEntry[], days = 365): HeatmapDay[] {
  const byDate: Record<string, number> = {}
  for (const r of timeline) byDate[r.date] = r.total_seconds
  const maxSecs = Math.max(1, ...Object.values(byDate), 0)
  const result: HeatmapDay[] = []
  const today = new Date()
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(d.getDate() - i)
    const dateStr = isoLocale(d)
    const secs = byDate[dateStr] || 0
    const ratio = secs / maxSecs
    const value = secs === 0 ? 0 : ratio > 0.75 ? 4 : ratio > 0.5 ? 3 : ratio > 0.25 ? 2 : 1
    result.push({ date: dateStr, minutes: Math.round(secs / 60), value })
  }
  return result
}



// ── Statistiche sugli autori (dati Wikidata) ─────────────────────────────
//
// Sono PESATE SUI LIBRI, non sul numero di autori. Le due cose rispondono a
// domande diverse e la seconda inganna: un autore con quindici volumi e uno
// con un opuscolo contano uguale, e "chi sta nella mia libreria" finisce per
// somigliare poco a "che cosa leggo". Misurato sulla biblioteca reale, la
// differenza è vistosa.
//
// Ogni funzione ignora gli autori senza il dato invece di contarli come
// "ignoto": la percentuale che restituisce è quindi calcolata SUL NOTO, e il
// chiamante mostra separatamente quanta parte della libreria è coperta —
// altrimenti "6% donne" e "6% donne, ma di un terzo non sappiamo nulla"
// avrebbero lo stesso aspetto.

export interface AuthorFacetSlice {
  label: string
  books: number
  percent: number
}

interface AuthorLike {
  book_count: number
  gender: string | null
  nationality: string[]
  birth_date: string | null
  death_date: string | null
  occupations: string[]
}

function facet(authors: AuthorLike[], valuesOf: (a: AuthorLike) => string[], limit?: number): AuthorFacetSlice[] {
  const byLabel = new Map<string, number>()
  let known = 0
  for (const a of authors) {
    const values = valuesOf(a)
    if (values.length === 0) continue
    known += a.book_count
    // Un autore con più cittadinanze conta per ciascuna: la somma delle fette
    // può superare il totale, ed è corretto così (Emma Goldman è russa E
    // statunitense, non mezza di ciascuna).
    for (const v of values) byLabel.set(v, (byLabel.get(v) ?? 0) + a.book_count)
  }
  const out = [...byLabel.entries()]
    .map(([label, books]) => ({ label, books, percent: known ? (books / known) * 100 : 0 }))
    .sort((x, y) => y.books - x.books)
  return limit ? out.slice(0, limit) : out
}

export function authorGenderShare(authors: AuthorLike[]): AuthorFacetSlice[] {
  return facet(authors, (a) => (a.gender ? [a.gender] : []))
}

export function authorNationalityShare(authors: AuthorLike[], limit = 10): AuthorFacetSlice[] {
  return facet(authors, (a) => a.nationality, limit)
}

export function authorOccupationShare(authors: AuthorLike[], limit = 10): AuthorFacetSlice[] {
  return facet(authors, (a) => a.occupations, limit)
}

/** Secolo di nascita, come "XIX secolo". Dice l'epoca di ciò che si legge. */
export function authorCenturyShare(authors: AuthorLike[], t: Traduci): AuthorFacetSlice[] {
  const romano = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII',
    'XIII', 'XIV', 'XV', 'XVI', 'XVII', 'XVIII', 'XIX', 'XX', 'XXI']
  // I secoli vanno in ordine di tempo, e per saperlo bisogna ricordarsi il
  // NUMERO: ordinare le etichette come testo mette il IX prima del V e il
  // XVI prima del XX, perché in ordine alfabetico è così che stanno i
  // numeri romani. Difetto visto guardando il grafico.
  const numeroDi = new Map<string, number>()
  return facet(authors, (a) => {
    const m = a.birth_date?.match(/^(-?\d{1,4})/)
    if (!m) return []
    const anno = parseInt(m[1], 10)
    if (!Number.isFinite(anno) || anno <= 0) return []
    const secolo = Math.floor((anno - 1) / 100) + 1
    const etichetta = romano[secolo]
      ? t('stats.library.century', { roman: romano[secolo] })
      : t('stats.library.centuryOrdinal', { n: secolo })
    numeroDi.set(etichetta, secolo)
    return [etichetta]
  }).sort((x, y) => (numeroDi.get(x.label) ?? 0) - (numeroDi.get(y.label) ?? 0))
}

/** Quanta parte della libreria ha il dato: la percentuale sopra è calcolata su questa. */
export function authorDataCoverage(authors: AuthorLike[], field: 'gender' | 'nationality' | 'birth_date'): {
  booksKnown: number
  booksTotal: number
  percent: number
} {
  let known = 0
  let total = 0
  for (const a of authors) {
    total += a.book_count
    const ok = field === 'nationality' ? a.nationality.length > 0 : !!a[field]
    if (ok) known += a.book_count
  }
  return { booksKnown: known, booksTotal: total, percent: total ? (known / total) * 100 : 0 }
}

/** Autori nati e senza data di morte: viventi. Pesato sui libri. */
export function livingAuthorsShare(authors: AuthorLike[]): { books: number; percent: number } {
  let viventi = 0
  let noti = 0
  for (const a of authors) {
    if (!a.birth_date) continue
    noti += a.book_count
    if (!a.death_date) viventi += a.book_count
  }
  return { books: viventi, percent: noti ? (viventi / noti) * 100 : 0 }
}

// ── Statistiche di lettura globali ───────────────────────────────────────
//
// "Globali" vuol dire DI SEMPRE, non dell'ultimo periodo: sono le domande che
// hanno senso solo su tutta la storia di lettura, e per cui filtrare per
// periodo toglierebbe il dato invece di affinarlo. Leggi più veloce di mattina
// o di sera non è una domanda sull'ultimo mese.

/** Quanti minuti servono perché la velocità di un'ora sia un dato e non rumore. */
export const MINUTI_MINIMI_PER_ORA = 60
/**
 * Quanto materiale serve perché la velocità di un libro sia confrontabile.
 *
 * **Un'ora**, alzata da dieci minuti il 01/10/2026.
 * La soglia dei caratteri resta, ma ora fa un altro mestiere: con un'ora di
 * lettura il campione è già abbondante, e quel numero serve solo a escludere i
 * libri di cui non si SA quanti caratteri si sono letti. Ce n'è uno vero nei
 * dati — due ore e cinquantasette minuti con zero caratteri noti — che senza
 * questo filtro comparirebbe primo fra i più lenti a zero caratteri all'ora,
 * che non è una lettura lenta: è un dato mancante travestito da misura.
 */
export const SOGLIA_LIBRO = { minuti: 60, caratteri: 10000 }

export interface SecchioOra {
  ora: number
  secondi: number
  caratteri: number
  /** Caratteri all'ora. `null` quando il campione è troppo piccolo. */
  velocita: number | null
}

/**
 * Le ventiquattro ore del giorno, sommando tutta la storia di lettura.
 *
 * Due letture dello stesso secchio: quanto leggi a quell'ora (caratteri) e
 * quanto vai veloce quando leggi a quell'ora (caratteri/ora). La prima è una
 * fotografia delle abitudini, la seconda prova a dire qualcosa sulla testa.
 *
 * `velocita` è `null` sotto MINUTI_MINIMI_PER_ORA, e non è prudenza
 * eccessiva: misurato su dati reali, le ore con poco materiale danno
 * 23.000 e 38.000 caratteri/ora contro un intervallo reale di 63.000-91.000.
 * Mostrarle farebbe sembrare che alle due di notte legga tre volte più
 * lentamente, quando il dato è «alle due di notte ha letto cinquanta minuti
 * in tutto, una volta».
 */
export function oreDellaGiornata(sessions: ReadingSessionRaw[]): SecchioOra[] {
  const secondi = new Array(24).fill(0)
  const caratteri = new Array(24).fill(0)
  for (const s of sessions) {
    const h = new Date(s.start_time).getHours()
    secondi[h] += s.duration_seconds
    caratteri[h] += s.chars_read || 0
  }
  return secondi.map((sec, ora) => ({
    ora,
    secondi: sec,
    caratteri: caratteri[ora],
    velocita:
      sec >= MINUTI_MINIMI_PER_ORA * 60 && caratteri[ora] > 0
        ? Math.round(caratteri[ora] / (sec / 3600))
        : null,
  }))
}

export interface VelocitaLibro {
  title: string
  author: string
  caratteri: number
  secondi: number
  caratteriOra: number
}

/**
 * La velocità di lettura per libro, solo per i libri su cui ha senso misurarla.
 *
 * La soglia non è cautela, è il dato: su una biblioteca reale la durata MEDIANA è di
 * un minuto — 67 libri su 103 stanno sotto i dieci minuti, perché aprire un
 * libro e chiuderlo conta come leggerlo. Senza soglia la classifica dei "più
 * veloci" sarebbe l'elenco dei libri aperti per sbaglio, dove un minuto e
 * mezzo di indice vale 300.000 caratteri/ora.
 *
 * A un'ora ne restano diciannove su centotré, e la conseguenza va detta a chi
 * guarda invece che nascosta: due classifiche da dieci su diciannove libri sono
 * quasi lo stesso elenco al contrario. Per questo la scheda dichiara sempre
 * quanti libri superano la soglia.
 */
export function velocitaPerLibro(sessions: ReadingSessionRaw[]): VelocitaLibro[] {
  const per = new Map<string, { author: string; caratteri: number; secondi: number }>()
  for (const s of sessions) {
    const v = per.get(s.book_title) ?? { author: s.author, caratteri: 0, secondi: 0 }
    v.caratteri += s.chars_read || 0
    v.secondi += s.duration_seconds
    per.set(s.book_title, v)
  }
  const out: VelocitaLibro[] = []
  for (const [title, v] of per) {
    if (v.secondi < SOGLIA_LIBRO.minuti * 60 || v.caratteri < SOGLIA_LIBRO.caratteri) continue
    out.push({ title, author: v.author, caratteri: v.caratteri, secondi: v.secondi,
      caratteriOra: Math.round(v.caratteri / (v.secondi / 3600)) })
  }
  return out.sort((a, b) => b.caratteriOra - a.caratteriOra)
}

/** Il tempo passato con ogni autore, i primi `quanti` e il resto accorpato. */
export function tempoPerAutore(sessions: ReadingSessionRaw[], t: Traduci, quanti = 10): CountDatum[] {
  const per = new Map<string, number>()
  for (const s of sessions) per.set(s.author, (per.get(s.author) ?? 0) + s.duration_seconds)
  const ordinati = [...per.entries()].sort((a, b) => b[1] - a[1])
  const totale = ordinati.reduce((sum, [, v]) => sum + v, 0) || 1
  const primi = ordinati.slice(0, quanti)
  const resto = ordinati.slice(quanti)
  const fette = primi.map(([label, count]) => ({ label, count, percent: Math.round((count / totale) * 100) }))
  // "Altri N autori" e non un troncamento silenzioso: su una torta, nascondere
  // la coda fa sembrare che i dieci nomi siano tutto quello che hai letto.
  if (resto.length) {
    const somma = resto.reduce((sum, [, v]) => sum + v, 0)
    fette.push({
      label: t('stats.reading.otherAuthors', { n: resto.length }),
      count: somma,
      percent: Math.round((somma / totale) * 100),
    })
  }
  return fette
}

// ── Dai libri finiti all'anagrafica di chi li ha scritti ──────────────────

/** Un libro spuntato come letto, come lo manda GET /stats/libri-letti. */
export interface LibroLetto {
  library: string
  book_id: number
  title: string
  author: string
  autori: string[]
  pages: number
  decade: string | null
  language: string | null
  rating: number | null
  author_birth_year: number | null
  author_death_year: number | null
  author_gender: string | null
  author_nationality: string | null
  author_occupations: string[]
}

/**
 * Raggruppa i libri finiti per autore, nella forma che le funzioni di facet
 * degli autori già sanno leggere.
 *
 * Perché riusarle invece di riscriverle: la scheda Libreria risponde già a
 * «chi c'è nella mia libreria» con queste stesse funzioni, e la domanda qui è
 * la stessa su un insieme diverso — «chi ho FINITO». Due implementazioni della
 * stessa misura su due insiemi diversi sarebbero due occasioni di divergere.
 */
export function autoriDeiLibriLetti(libri: LibroLetto[]) {
  const per = new Map<string, {
    book_count: number
    gender: string | null
    nationality: string[]
    birth_date: string | null
    death_date: string | null
    occupations: string[]
  }>()
  for (const b of libri) {
    const a = per.get(b.author)
    if (a) {
      a.book_count += 1
      continue
    }
    per.set(b.author, {
      book_count: 1,
      gender: b.author_gender,
      nationality: b.author_nationality ? [b.author_nationality] : [],
      // Le funzioni di facet leggono `birth_date` come testo e ne prendono
      // l'anno: si ricompone la forma che si aspettano.
      birth_date: b.author_birth_year != null ? String(b.author_birth_year) : null,
      death_date: b.author_death_year != null ? String(b.author_death_year) : null,
      occupations: b.author_occupations,
    })
  }
  return [...per.values()]
}

/** Quanti libri finiti per autore, i primi `quanti`. */
export function libriLettiPerAutore(libri: LibroLetto[], quanti = 10): CountDatum[] {
  const per = new Map<string, number>()
  for (const b of libri) per.set(b.author, (per.get(b.author) ?? 0) + 1)
  const ordinati = [...per.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  const massimo = ordinati[0]?.[1] || 1
  return ordinati.slice(0, quanti).map(([label, count]) => ({
    label, count, percent: Math.round((count / massimo) * 100),
  }))
}

/**
 * I libri finiti per decennio di nascita dell'autore.
 *
 * Il gemello a secoli è `authorCenturyShare`, già esistente. Qui a decenni
 * perché sui dati veri i secoli dicono poco: 43 libri nell'Ottocento e 66 nel
 * Novecento sono due barre, e tutto quello che c'è da vedere — che la lettura
 * si concentra sugli anni 1870 e 1900-1920 — sta dentro quelle due.
 */
export function libriPerDecennioDiNascita(libri: LibroLetto[], t: Traduci): AuthorFacetSlice[] {
  const per = new Map<number, number>()
  let noti = 0
  for (const b of libri) {
    if (b.author_birth_year == null) continue
    noti += 1
    const dec = Math.floor(b.author_birth_year / 10) * 10
    per.set(dec, (per.get(dec) ?? 0) + 1)
  }
  return [...per.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([dec, books]) => ({
      label: dec < 0 ? t('stats.reading.yearBC', { year: -dec }) : String(dec),
      books,
      percent: noti ? (books / noti) * 100 : 0,
    }))
}

/** Una riga per libro letto in un giorno, per il calendario. */
export interface LibroDelGiorno {
  title: string
  secondi: number
  caratteri: number
}

/**
 * Che cosa si è letto ogni giorno, libro per libro.
 *
 * È la differenza fra il calendario e la heatmap: la heatmap dice QUANTO con un
 * colore, e per un anno intero è la vista giusta. Un calendario che dicesse
 * anch'esso solo "quanto", in una griglia più grande, sarebbe la stessa
 * informazione con più spazio — che è quello che era. Dentro un giorno c'è
 * posto per i titoli, e il titolo è l'unica cosa che la heatmap non può dare.
 */
export function libriPerGiorno(sessions: ReadingSessionRaw[]): Map<string, LibroDelGiorno[]> {
  const per = new Map<string, Map<string, LibroDelGiorno>>()
  for (const s of sessions) {
    const giorno = per.get(s.date) ?? new Map<string, LibroDelGiorno>()
    const libro = giorno.get(s.book_title) ?? { title: s.book_title, secondi: 0, caratteri: 0 }
    libro.secondi += s.duration_seconds
    libro.caratteri += s.chars_read || 0
    giorno.set(s.book_title, libro)
    per.set(s.date, giorno)
  }
  const out = new Map<string, LibroDelGiorno[]>()
  for (const [giorno, libri] of per) {
    out.set(giorno, [...libri.values()].sort((a, b) => b.secondi - a.secondi))
  }
  return out
}

