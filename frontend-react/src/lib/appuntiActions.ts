// Gli appunti fuori da Kolibre: cosa c'è nel vault, e le tre decisioni.
//
// **Da zero.** Il plugin Obsidian tiene un file per libro, e Paolo ci scrive
// attorno. Il server non può guardare dentro quel vault né scriverci: il
// plugin sincronizza quando glielo si chiede. Quindi quello che si decide in
// questa pagina **non è un'azione, è un'istruzione**: il plugin la riceve al
// prossimo giro e la esegue, e fino a quel momento il libro resta «in
// attesa». La pagina lo deve dire, altrimenti chi blocca un libro si aspetta
// che succeda subito.
//
// Il calcolo degli stati sta sul server (`services/appunti_nel_vault.py`,
// quarantasei prove): qui non si ricalcola niente, si mostra.
import type { components } from '@/api/schema'
import { api } from './api'

export type StatoDegliAppunti = components['schemas']['StatoDegliAppunti']
export type LibroNegliAppunti = components['schemas']['LibroNegliAppunti']
export type ConflittoDiAppunti = components['schemas']['ConflittoDiAppunti']
export type ClienteDegliAppunti = components['schemas']['ClienteDegliAppunti']
export type RiassuntoDegliAppunti = components['schemas']['RiassuntoDegliAppunti']
export type DettaglioDiUnLibro = components['schemas']['DettaglioDiUnLibro']
export type NotaNegliAppunti = components['schemas']['NotaNegliAppunti']

/** La chiave della cache: la pagina rilegge da qui dopo ogni decisione. */
export const CHIAVE_APPUNTI = ['appunti', 'stato'] as const

/** Gli stati, dal più urgente al più tranquillo: lo stesso ordine del server. */
export const STATI = ['conflitto', 'non_creato', 'non_aggiornato', 'in_attesa', 'in_pari', 'cancellato_da_te', 'bloccato'] as const
export type StatoDiUnLibro = (typeof STATI)[number]

/**
 * I tre stati che hanno bisogno di una decisione o di un giro del plugin: li
 * conta il server in `riassunto.da_guardare`, e la tabella li ordina per
 * primi.
 *
 * `cancellato_da_te` e `bloccato` non ci sono di proposito: sono **quiete
 * voluta**, decisioni da ricordare e non cose da fare.
 */
export const DA_GUARDARE: StatoDiUnLibro[] = ['conflitto', 'non_creato', 'non_aggiornato']

/**
 * Lo stato di una singola nota dentro il vault — quello che mostra la pagina
 * di un libro, riga per riga.
 *
 * La coppia che conta è `mai_consegnata` / `togliata_da_te`: tutte due
 * vogliono dire «non è nel file», ma la prima chiede di essere scritta e la
 * seconda chiede di essere lasciata in pace.
 */
export const STATI_DI_UNA_NOTA = ['conflitto', 'mai_consegnata', 'da_portare',
  'modificata_da_te', 'togliata_da_te', 'in_pari'] as const
export type StatoDiUnaNota = (typeof STATI_DI_UNA_NOTA)[number]

/**
 * L'indirizzo della pagina di un libro.
 *
 * La biblioteca e l'id stanno nella **query** e non nel percorso: il nome di
 * una biblioteca e' il nome vero di una cartella, e in un percorso andrebbe
 * codificato due volte (lo si e' gia' imparato con gli indirizzi
 * condivisibili). Un file non ancora accoppiato non ha un id e si indica col
 * titolo, che e' la sola cosa che lo distingue.
 */
export function indirizzoDelLibro(l: LibroNegliAppunti): string {
  const q = new URLSearchParams({ library: l.library ?? '' })
  if (l.calibre_book_id != null) q.set('id', String(l.calibre_book_id))
  else if (l.titolo) q.set('titolo', l.titolo)
  return `/appunti/libro?${q.toString()}`
}

/** Le note di un libro, una per una, con lo stato di ognuna nel vault. */
export async function fetchLibroDegliAppunti(
  libro: { library: string; calibre_book_id?: number | null; titolo?: string | null },
  cliente?: number | null
): Promise<DettaglioDiUnLibro> {
  const query = {
    library: libro.library,
    ...(libro.calibre_book_id != null
      ? { calibre_book_id: libro.calibre_book_id }
      // Un file non ancora accoppiato non ha un id: lo distingue solo il
      // titolo, che è la stessa chiave con cui il plugin raggruppa i file.
      : libro.titolo
        ? { titolo: libro.titolo }
        : {}),
    ...(cliente != null ? { cliente } : {}),
  }
  const { data, error } = await api.GET('/api/kolibre/appunti/libro', { params: { query } })
  if (error) throw error
  return data
}

/**
 * Lo stato di un vault. Senza `cliente` si guarda quello che ha raccontato
 * più di recente.
 *
 * **La fotografia è dell'account, non del token con cui la si chiede**: qui
 * legge il browser, non il plugin. Il 06/11/2026 non era così, e la pagina
 * non vedeva nessun client — il server cercava il client del token della
 * richiesta, che per il browser è un token di sessione, mentre la
 * fotografia l'aveva raccontata il plugin col suo.
 */
export async function fetchStatoDegliAppunti(cliente?: number | null): Promise<StatoDegliAppunti> {
  const { data, error } = await api.GET('/api/kolibre/appunti/stato', {
    params: { query: cliente != null ? { cliente } : {} },
  })
  if (error) throw error
  return data
}

/**
 * Solo «c'è un client». La chiede la barra laterale a ogni pagina, ed è una
 * rotta a parte dal server proprio per questo: far calcolare lo stato di
 * tutti i libri per sapere se mostrare una voce di menu sarebbe lavoro
 * buttato.
 */
export async function fetchClienteDegliAppunti(): Promise<ClienteDegliAppunti | null> {
  const { data, error } = await api.GET('/api/kolibre/appunti/cliente')
  if (error) throw error
  return data.cliente ?? null
}

export async function cambiaIlBlocco(libro: {
  library: string
  calibre_book_id: number
  titolo?: string | null
  bloccato: boolean
}): Promise<void> {
  const { error } = await api.PUT('/api/kolibre/appunti/blocco', { body: libro })
  if (error) throw error
}

export async function chiediIlRifacimento(libro: {
  library: string
  calibre_book_id: number
  titolo?: string | null
  annulla?: boolean
}): Promise<void> {
  const { error } = await api.PUT('/api/kolibre/appunti/rifai', { body: libro })
  if (error) throw error
}

export async function decidiIlConflitto(scelta: {
  id_durevole: string
  scelta?: 'kolibre' | 'mio'
  annulla?: boolean
}): Promise<void> {
  const { error } = await api.PUT('/api/kolibre/appunti/conflitto', { body: scelta })
  if (error) throw error
}
