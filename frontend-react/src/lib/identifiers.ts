export interface IdentifierRow {
  type: string
  value: string
}

// L'elenco precedente aveva cinque voci. La biblioteca reale ne usa oltre
// venti: censite sui 1.216 libri di produzione, per numero di libri —
// isbn 815, google 477, goodreads 446, oclc 358, viaf 349, lccn 336,
// isni 331, mobi-asin 242, amazon 74. Con un menu a cinque voci, aprire
// l'editor su un libro con un `lccn` mostrava un campo tipo VUOTO: il valore
// restava in memoria e non si perdeva salvando, ma era invisibile e
// inspiegabile.
export const IDENTIFIER_TYPES = [
  'isbn', 'issn', 'ean', 'doi',
  'google', 'goodreads', 'amazon', 'amazon_it', 'mobi-asin', 'asin', 'kobo',
  'oclc-worldcat', 'oclc-owi', 'lccn', 'viaf_author_id', 'isni', 'lc_authority_name',
  'openlibrary', 'wikidata', 'uuid', 'url', 'custom',
] as const

/**
 * L'elenco da mostrare in un menu per UNA riga: i tipi noti, piu' il tipo
 * della riga stessa se e' uno che non conosciamo. Serve a non far sparire
 * dalla vista un identificativo solo perche' non l'avevamo previsto — e a
 * non trasformarlo silenziosamente in qualcos'altro.
 */
export function identifierTypeOptions(current: string): string[] {
  const noti = IDENTIFIER_TYPES as readonly string[]
  return current && !noti.includes(current) ? [current, ...noti] : [...noti]
}

/** Indirizzo consultabile per gli identificativi che ne hanno uno. */
export function identifierUrl(type: string, value: string): string | null {
  const v = encodeURIComponent(value.trim())
  switch (type) {
    case 'isbn': return `https://openlibrary.org/isbn/${v}`
    case 'google': return `https://books.google.com/books?id=${v}`
    case 'goodreads': return `https://www.goodreads.com/book/show/${v}`
    case 'openlibrary': return `https://openlibrary.org/books/${v}`
    case 'wikidata': return `https://www.wikidata.org/wiki/${v}`
    case 'viaf_author_id': return `https://viaf.org/viaf/${v}`
    case 'isni': return `https://isni.org/isni/${v.replace(/\s/g, '')}`
    case 'lccn': return `https://lccn.loc.gov/${v}`
    case 'oclc-worldcat': return `https://worldcat.org/oclc/${v}`
    case 'doi': return `https://doi.org/${v}`
    case 'url': return value
    default: return null
  }
}

export function identifierRowsFromDict(dict: Record<string, string> | null | undefined): IdentifierRow[] {
  return Object.entries(dict ?? {}).map(([type, value]) => ({ type, value }))
}

export function identifierRowsToDict(rows: IdentifierRow[]): Record<string, string> {
  const dict: Record<string, string> = {}
  for (const row of rows) {
    if (row.type && row.value) dict[row.type] = row.value
  }
  return dict
}
