// Domain types per Autori/Serie — scritti a mano sulla base dei campi reali
// prodotti da backend/app/api/authors.py (nessun response_model dichiarato,
// quindi schema.d.ts non porta forma tipizzata per questi endpoint).

export interface AuthorSummary {
  name: string
  book_count: number
  total_pages: number
  photo_url: string | null
  /** Etichetta italiana di P21 su Wikidata: "maschio", "femmina", … */
  gender: string | null
  /** P27. Piu' valori per chi ha cambiato paese, e stati storici ("Regno d'Italia"). */
  nationality: string[]
  /** ISO; puo' essere anche solo l'anno. */
  birth_date: string | null
  /** null anche per i viventi — non e' un dato mancante. */
  death_date: string | null
  /** P106. Il campo piu' utile per capire CHE COSA si legge. */
  occupations: string[]
  wikidata_qid: string | null
}

export interface AuthorDetail {
  name: string
  bio_it: string | null
  bio_en: string | null
  wikipedia_url_it: string | null
  wikipedia_url_en: string | null
  photo_url: string | null
  last_scraped_at: string | null
  /** Etichetta italiana di P21 su Wikidata: "maschio", "femmina", … */
  gender: string | null
  /** P27. Piu' valori per chi ha cambiato paese, e stati storici ("Regno d'Italia"). */
  nationality: string[]
  /** ISO; puo' essere anche solo l'anno. */
  birth_date: string | null
  /** null anche per i viventi — non e' un dato mancante. */
  death_date: string | null
  /** P106. Il campo piu' utile per capire CHE COSA si legge. */
  occupations: string[]
  wikidata_qid: string | null
}

export interface AuthorBook {
  id: number
  title: string
  cover_url: string | null
  library: string
}

export interface AuthorImageResult {
  title: string
  thumb_url: string
  url: string
}
