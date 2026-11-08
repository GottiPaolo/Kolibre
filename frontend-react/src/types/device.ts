// Le forme restituite da backend/app/api/devices.py.
//
// **Dal 05/11/2026 arrivano dallo schema** (`schemas_risposte.py`): prima
// erano scritte a mano leggendo il codice Python, perché quei quarantasei
// endpoint non dichiaravano niente e `schema.d.ts` li tipizzava `unknown`.
//
// Quel file di API ha **due pubblici** e due autenticazioni: `/api/devices`
// lo chiama il portale col token della persona, e `/api/kolibre/devices` lo
// chiama il plugin KOReader col token permanente del dispositivo. Qui ci
// sono solo le prime: le altre non passano mai per il browser — il loro
// client è scritto in Lua e vive su un e-reader.
import type { components } from '@/api/schema'

/** Una riga dello stato desiderato di un lettore, con titolo e avanzamento. */
export type DeviceBookRow = components['schemas']['LibroSulDispositivo']

/** La stessa riga, ridotta, con un verbo al posto dello stato. */
export type DeviceSyncQueueEntry = components['schemas']['LibroInCodaPerIlDispositivo']

/**
 * Un lettore come lo vede il portale — **senza il token**, che si vede una
 * volta sola appena registrato.
 *
 * Tre coppie di campi dicono cose che sembrano uguali e non lo sono, e il
 * perché sta nello schema: `patches` con `patches_riportate`, i tre
 * `storage_*` che sono `null` e non zero con un plugin che non li misura, e
 * `dizionari_richiesti` che è una **coda** e non l'elenco degli installati.
 */
export type Device = components['schemas']['DispositivoInElenco']

/** Lo stato di una userpatch su un dispositivo. `assente` non è un errore. */
export type DevicePatchStato = components['schemas']['PatchSulDispositivo']

/** «Rimetti su questo lettore il backup di quell'altro»: tre conferme. */
export type DeviceRestoreRequest = components['schemas']['RichiestaDiRipristino']

/**
 * Il dispositivo **nudo**: la riga del database e nient'altro.
 *
 * La rispondono `POST /register`, `PUT /{id}` e `POST /{id}/set-default`
 * (`schemas.DeviceResponse`), e **non** è la riga arricchita dell'elenco —
 * niente libri, niente patch, niente coda, niente spazio sul disco. In
 * compenso porta `device_token`, che in nessun'altra risposta si vede.
 *
 * Fino al 05/11/2026 il frontend credeva che la modifica di un dispositivo
 * rispondesse la riga arricchita: lo diceva un tipo scritto a mano, e
 * un'asserzione lo rendeva vero per il compilatore. Nessuno se n'era
 * accorto perché quel valore di ritorno non viene mai letto — ed è
 * esattamente il genere di bugia che un client generato dallo schema
 * prenderebbe per buona.
 */
export type DeviceNudo = components['schemas']['DeviceResponse']

/** Un file sul lettore che non si è accoppiato a nessun libro. */
export type DeviceFlaggedBook = components['schemas']['LibroDaRivedere']

/** Una sessione di sincronizzazione finita, o abbandonata dal server. */
export type DeviceSyncHistoryEntry = components['schemas']['SincronizzazioneNelloStorico']

/** Un file del backup di un lettore, come sta sul server. */
export type DeviceBackup = components['schemas']['FileDiBackup']

/**
 * Cosa risponde un'azione su un file «da rivedere»: **due forme**.
 *
 * Accodare un'eliminazione o una sovrascrittura dice `pending_action` (il
 * lettore può essere spento: il file lo tocca lui alla prossima
 * sincronizzazione). Accoppiare invece si applica subito — non tocca nessun
 * file — e dice quante annotazioni orfane ha spostato sul libro scelto.
 */
export type EsitoAzioneDaRivedere =
  | components['schemas']['AzioneAccodata']
  | components['schemas']['OrfaneMigrate']
