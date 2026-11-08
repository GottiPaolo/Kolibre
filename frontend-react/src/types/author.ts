// Le forme restituite da backend/app/api/authors.py.
//
// **Dal 05/11/2026 arrivano dallo schema** (`schemas_risposte.py`): prima
// erano scritte a mano leggendo il codice Python, perché quei quattordici
// endpoint non dichiaravano niente e `schema.d.ts` li tipizzava `unknown`.
//
// I sei campi dell'anagrafica Wikidata (`gender`, `nationality`,
// `birth_date`, `death_date`, `occupations`, `wikidata_qid`) erano copiati
// due volte qui dentro, una per l'elenco e una per la scheda, con gli stessi
// commenti ripetuti. Nel server sono una funzione sola
// (`authors.py::_anagrafica`) e ora anche qui sono un tipo solo.
import type { components } from '@/api/schema'

/** Un autore nell'elenco: quanto se ne possiede, la foto, l'anagrafica. */
export type AuthorSummary = components['schemas']['AutoreInElenco']

/**
 * La scheda di un autore.
 *
 * **I sei campi dell'anagrafica sono facoltativi**, e non per prudenza: per
 * un autore di cui il server non ha nessuna riga la risposta sono sette
 * chiavi e nient'altro — quei sei non compaiono affatto. L'elenco invece li
 * mette comunque, vuoti. Era un'asimmetria che il tipo scritto a mano
 * nascondeva, dichiarandoli presenti in entrambi i casi.
 */
export type AuthorDetail = components['schemas']['SchedaAutore']

/** Un libro di quell'autore, da qualunque biblioteca. */
export type AuthorBook = components['schemas']['LibroDiUnAutore']

/** Una foto candidata, da Wikimedia Commons. */
export type AuthorImageResult = components['schemas']['ImmagineProposta']

/** A che punto è il recupero dei dati degli autori da Wikipedia. */
export type ScrapeJobStatus = components['schemas']['StatoDelRecupero']
