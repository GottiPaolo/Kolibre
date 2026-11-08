// Le forme restituite da backend/app/api/annotations.py.
//
// **Dal 05/11/2026 arrivano dallo schema** (`schemas_risposte.py`): prima
// erano scritte a mano leggendo il codice Python, perché quegli endpoint non
// dichiaravano niente e `schema.d.ts` li tipizzava `unknown`.
//
// L'elenco mette in UNA lista due cose diverse — le evidenziazioni, che
// stanno su un libro della biblioteca, e le **orfane**, arrivate da un
// dispositivo per un file che non si è accoppiato a nessun libro. Si
// distinguono per `is_orphan`, e il server adesso le dichiara come unione
// discriminata: chi legge può restringere invece di indovinare. La
// differenza più insidiosa è l'`id`, che è un numero per le prime e la
// stringa `"orphan-<n>"` per le seconde.
import type { components } from '@/api/schema'

export type HighlightSource = 'web' | 'device' | 'calibre'

/** Un'evidenziazione su un libro della biblioteca. */
export type RealHighlight = components['schemas']['Evidenziazione']
/** Un'annotazione arrivata da un dispositivo, senza un libro a cui legarsi. */
export type OrphanHighlight = components['schemas']['EvidenziazioneOrfana']

/**
 * Quello che l'elenco restituisce davvero: le due forme mescolate.
 *
 * I campi che esistono in una sola delle due (`book_formats` sulle vere,
 * `orphan_key` sulle orfane) si leggono dopo aver guardato `is_orphan` —
 * che è esattamente il controllo che il codice faceva già, e che adesso il
 * compilatore sa.
 */
export type Highlight = RealHighlight | OrphanHighlight

/**
 * Il dispositivo come lo porta `GET /api/devices`.
 *
 * Era un'interfaccia di due campi scritta a mano «perché solo quelli
 * servono». Dal 05/11/2026 l'elenco dichiara la sua forma, e questo è un
 * alias dello stesso tipo che usa la pagina Dispositivi: due copie dello
 * stesso dato diventano due dati diversi alla prima modifica.
 */
export type AnnotationDevice = components['schemas']['DispositivoInElenco']
