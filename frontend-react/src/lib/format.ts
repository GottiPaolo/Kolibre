// Una cifra decimale sotto i 10, nessuna sopra: "4,8 GB" e "312 MB" si
// leggono, "4582 MB" e "4,80 GB" no. Il salto a GB serve da quando si
// misurano biblioteche intere (una biblioteca reale arriva a 4,5 GB) e lo
// spazio di un lettore, non piu' solo il singolo file.
export function formatBytes(bytes: number): string {
  if (!bytes) return '0 MB'
  const mb = bytes / (1024 * 1024)
  if (mb >= 1024) {
    const gb = mb / 1024
    return `${gb.toFixed(gb >= 10 ? 0 : 1)} GB`
  }
  return `${mb.toFixed(mb >= 10 ? 0 : 1)} MB`
}

// I 3 campi data fissi (date_added/pubdate/last_modified) arrivano già
// come solo-data (YYYY-MM-DD, vedi backend/app/api/books.py). Le colonne
// personalizzate 'datetime' invece possono ancora arrivare come timestamp
// Calibre completo ("2024-05-12T10:30:00+00:00" o con spazio) — stesso
// caso che la riparazione una tantum lato server ha gia' sistemato sulle
// biblioteche esistenti, e che questo troncamento copre comunque a ogni
// lettura. Match via regex invece di uno split('-') ingenuo, che si
// rompeva su un offset timezone negativo ("-05:00") in coda al valore.
/**
 * La data di un `Date` come la vede il CALENDARIO LOCALE: `YYYY-MM-DD`.
 *
 * Non `toISOString().slice(0, 10)`, che è quello che c'era prima in sei punti
 * e che converte in UTC. Un `Date` costruito sulla mezzanotte locale, in un
 * fuso a est di Greenwich, in UTC è il giorno PRIMA: l'istogramma settimanale
 * etichettava ogni barra con il giorno sbagliato, sempre, non solo a volte.
 *
 * E attorno al cambio dell'ora legale l'offset cambia di un'ora, quindi due
 * giorni locali diversi finivano sulla stessa data UTC: la mappa dell'anno
 * disegnava il 29/03/2026 due volte e perdeva un giorno — in React, due
 * elementi con la stessa chiave.
 */
export function isoLocale(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(dateStr)
  if (!match) return dateStr
  const [, y, m, d] = match
  return `${d}/${m}/${y}`
}

export function ratingStars(rating: number | null | undefined): string {
  if (!rating) return '—'
  return '★'.repeat(rating) + '☆'.repeat(Math.max(0, 5 - rating))
}
