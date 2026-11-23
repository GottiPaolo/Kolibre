// Le forme restituite da backend/app/api/ingest.py.
//
// **Dal 05/11/2026 arrivano dallo schema** (`schemas_risposte.py`): prima
// erano scritte a mano leggendo il codice Python, perché quei nove endpoint
// non dichiaravano niente e `schema.d.ts` li tipizzava `unknown`.
import type { components } from '@/api/schema'

// I sei formati che Kolibre accetta (EBOOK_EXTENSIONS in
// services/library_scanner.py, lista indicativa di Paolo del 23/11/2026):
// letterale copiato a mano, da tenere allineato. Usato solo per l'hint
// dell'<input accept="...">: il cancello vero sta sul server.
export const INGEST_ACCEPT = '.epub,.pdf,.mobi,.azw3,.txt,.md'

/**
 * Un file in attesa di essere importato, coi metadati letti dal file stesso.
 *
 * `cover_url` è popolato solo per un EPUB che ha una copertina dentro di sé:
 * per un PDF, o per un EPUB senza copertina propria, è `null` — e qui, al
 * contrario dei libri in biblioteca, **non ce n'è una costruita**, quindi la
 * scheda mostra un segnaposto.
 */
export type IngestedBook = components['schemas']['LibroInArretrato']

/** Un file caricato che non è stato preso, col perché scritto per una persona. */
export type IngestRejectedFile = components['schemas']['FileRifiutato']

/**
 * L'esito di un caricamento dal browser.
 *
 * È **parziale per costruzione**: ogni file è indipendente, e uno rifiutato
 * non ferma gli altri. Per questo sono due liste e non un esito.
 */
export type IngestUploadResult = components['schemas']['ArretratiCaricati']
