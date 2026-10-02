// Apertura del reader web (EPUB/PDF) in una finestra dedicata — porting 1:1
// di readBookWeb/openPdfReaderWeb/readIngestBookWeb in frontend/src/App.vue
// (righe ~4756-4838). Il `token` in query string non serve alle fetch del
// reader stesso (autentica via authHeaders(), come il resto dell'app), ma
// resta per parità/robustezza — vedi il commento sull'endpoint reading-
// position in schema.d.ts, che lo accetta come alternativa all'header.
import { ensureAuthToken } from './auth'
import { toast } from '@/lib/toast'
import { t } from '@/lib/i18n'

// Proporzioni di una pagina, non di una finestra di applicazione: piu' alta
// che larga e non troppo grande, cosi' la riga di testo resta corta e si legge
// davvero. 1000x800 era orizzontale e su un EPUB produceva righe lunghissime.
// La larghezza sta anche sotto la soglia oltre la quale epub.js aprirebbe la
// doppia pagina da solo, quindi si parte in pagina singola senza imporlo.
// `popup=yes` insieme alle dimensioni e' cio' che convince il browser ad
// aprire una FINESTRA e non una scheda: senza, Chrome e Safari su macOS
// aprono una scheda a tutto schermo e le dimensioni vengono ignorate del
// tutto (difetto riscontrato in uso: la finestra ridotta non si apriva). Le
// altre voci (noopener/menubar/toolbar a no) rafforzano la stessa cosa.
//
// Resta un limite del browser e non del codice: Safari con "apri le pagine
// in schede invece che in finestre" impostato su "sempre" ignora tutto
// comunque. In quel caso l'impostazione sta in Safari > Impostazioni >
// Generali > "Apri le pagine in schede", da mettere su "automaticamente".
// Esportate: le usa anche ReaderPage per riprovare il ridimensionamento
// dall'interno quando il sistema ha ignorato queste features (app web).
export const READER_WIDTH = 720
export const READER_HEIGHT = 1000

/**
 * Dimensioni E posizione: la finestra nasce al centro dello schermo invece
 * che nell'angolo dove il browser la metterebbe.
 *
 * Calcolato al momento dell'apertura e non costante, perche' dipende dallo
 * schermo che si sta usando — su un portatile collegato a un monitor esterno
 * i due sono diversi. `availWidth/Height` esclude dock e barra dei menu.
 */
function readerWindowFeatures(): string {
  const w = Math.min(READER_WIDTH, window.screen.availWidth)
  const h = Math.min(READER_HEIGHT, window.screen.availHeight)
  const left = Math.max(0, Math.round((window.screen.availWidth - w) / 2))
  const top = Math.max(0, Math.round((window.screen.availHeight - h) / 2))
  return `popup=yes,width=${w},height=${h},left=${left},top=${top},menubar=no,toolbar=no,location=no,status=no`
}

// Safari/iOS blocca window.open() se non avviene SINCRONAMENTE dentro il
// gestore dell'evento click originale — un solo `await` (anche uno che si
// risolve subito, come ensureAuthToken() a caldo) rompe quella catena e la
// finestra viene bloccata in silenzio (window.open restituisce null, mai
// controllato prima d'ora). Desktop/Android sono più permissivi, motivo per
// cui il sintomo si notava solo su iPhone. Fix: aprire la finestra vuota
// PRIMA di qualunque await, navigarla via location.href una volta pronto
// l'URL reale — lo stesso oggetto Window resta valido, il browser non lo
// considera più "popup non richiesto" perché è già stato aperto nel turno
// sincrono del click.
function openReaderWindow(windowName: string): Window | null {
  return window.open('about:blank', windowName, readerWindowFeatures())
}

function navigateReaderWindow(win: Window | null): boolean {
  if (!win) {
    toast.error(t('reader.popupBlocked'))
    return false
  }
  return true
}

// Volutamente più larga del tipo Book completo (types/library.ts): FulltextSearchResult
// e i risultati orfani/annotazioni non hanno tutti i campi di un Book reale,
// solo id/title/formats servono davvero qui.
interface ReadableBook {
  id: number
  title: string
  formats: string[]
}

function preferredReaderFormat(formats: string[]): 'EPUB' | 'PDF' | null {
  if (formats.includes('EPUB')) return 'EPUB'
  if (formats.includes('PDF')) return 'PDF'
  return null
}

export async function openBookInReader(
  book: ReadableBook,
  library: string,
  opts?: { cfi?: string; searchTerm?: string; notaTesto?: string; notaId?: string | number }
): Promise<boolean> {
  const format = preferredReaderFormat(book.formats)
  if (!format) return false

  const win = openReaderWindow(`kolibre-reader-${book.id}`)
  const token = await ensureAuthToken()
  if (!navigateReaderWindow(win)) return true

  const params = new URLSearchParams({
    bookId: String(book.id),
    library,
    format,
    title: book.title || '',
    token: token || '',
  })
  // Deep-link solo per l'EPUB: il reader PDF non ha alcun concetto di CFI.
  if (format === 'EPUB') {
    if (opts?.cfi) params.set('cfi', opts.cfi)
    if (opts?.searchTerm) params.set('searchTerm', opts.searchTerm)
    // Il testo di una nota: il lettore lo usa SOLO come ripiego, quando
    // l'ancora non porta da nessuna parte utile (vedi ReaderPage). Tagliato,
    // perche' finisce in una query string e le prime frasi bastano a
    // ritrovare il passo.
    if (opts?.notaTesto) params.set('notaTesto', opts.notaTesto.slice(0, 300))
    // Quale nota: il lettore deve poter controllare se il segno di QUESTA
    // e' comparso, non se ne e' comparso uno qualsiasi nel libro.
    if (opts?.notaId != null) params.set('notaId', String(opts.notaId))
  }
  const entry = format === 'EPUB' ? 'reader.html' : 'pdf-reader.html'
  win!.location.href = `/${entry}?${params.toString()}`
  return true
}

// Click su un formato specifico (badge "EPUB"/"PDF" nella pagina Dettagli
// libro) — a differenza di openBookInReader non sceglie il formato
// preferito, apre esattamente quello cliccato (stesso comportamento di
// bookDetailOpenFormat in App.vue: EPUB e PDF hanno ciascuno il proprio
// reader dedicato, altri formati non hanno un web reader).
export async function openBookFormatInReader(book: ReadableBook, library: string, format: string): Promise<boolean> {
  if (format !== 'EPUB' && format !== 'PDF') return false
  const win = openReaderWindow(`kolibre-reader-${book.id}`)
  const token = await ensureAuthToken()
  if (!navigateReaderWindow(win)) return true

  const params = new URLSearchParams({
    bookId: String(book.id),
    library,
    format,
    title: book.title || '',
    token: token || '',
  })
  const entry = format === 'EPUB' ? 'reader.html' : 'pdf-reader.html'
  win!.location.href = `/${entry}?${params.toString()}`
  return true
}

export async function openIngestBookInReader(staging: { id: number; title: string; formats: string[] }): Promise<boolean> {
  const format = preferredReaderFormat(staging.formats)
  if (!format) return false

  const win = openReaderWindow(`kolibre-ingest-reader-${staging.id}`)
  const token = await ensureAuthToken()
  if (!navigateReaderWindow(win)) return true

  const params = new URLSearchParams({
    ingestId: String(staging.id),
    format,
    title: staging.title || '',
    token: token || '',
  })
  const entry = format === 'EPUB' ? 'reader.html' : 'pdf-reader.html'
  win!.location.href = `/${entry}?${params.toString()}`
  return true
}
