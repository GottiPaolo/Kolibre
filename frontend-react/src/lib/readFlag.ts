// "Letto": la colonna con cui Kolibre sa se un libro e' stato finito.
//
// Il nome vive qui e non sparso nelle pagine perche' e' una colonna
// personalizzata di Calibre come le altre — il backend la crea in ogni
// biblioteca (vedi connection.py::_ensure_read_flag_column) e da li' in poi
// e' modificabile, ordinabile e filtrabile dal codice generico che gia'
// gestisce le colonne personalizzate, senza casi speciali.
//
// Perche' esista una colonna invece di dedurlo dalle statistiche: nessuna
// misura automatica sa che un libro l'hai finito su carta, o che l'hai
// abbandonato e non lo riprenderai. La copertura puo' suggerire, non
// decidere.

import type { Book } from '@/types/library'

export const READ_FLAG_COLUMN = 'letto'

/** La chiave con cui il valore viaggia nei metadati: `#letto`. */
export const READ_FLAG_FIELD = `#${READ_FLAG_COLUMN}`

/**
 * Se il libro risulta letto. Un valore mai impostato e' "non letto": non
 * c'e' un terzo stato, per scelta — la domanda e' una sola.
 */
export function risultaLetto(book: Book | undefined): boolean {
  if (!book) return false
  const v = (book as Record<string, unknown>)[READ_FLAG_FIELD]
  // Calibre tiene i bool come 0/1 in SQLite, ma il valore puo' arrivare gia'
  // convertito a booleano: si accettano entrambe le forme.
  return v === true || v === 1
}
