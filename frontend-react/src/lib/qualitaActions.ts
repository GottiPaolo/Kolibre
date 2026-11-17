// La qualità degli EPUB: leggere i punteggi, accendere la misura, chiederla.
//
// Il server misura ogni EPUB e risponde a DUE domande (vedi
// backend/app/services/qualita_epub.py): `pronto` dice se il lettore apre il
// file così com'è, `punteggio` dice quanto è fatto bene. Sono indipendenti —
// un libro sano impacchettato male ha 99 e non si apre — e qui dentro non si
// mescolano mai in un numero solo.
//
// **Le dimensioni e i difetti non sono elencati da nessuna parte nel
// frontend**, ed è voluto: la misura cambia (ogni risultato porta la sua
// `versione`), e un elenco scritto qui obbligherebbe a toccare il browser a
// ogni regola nuova. Si legge quello che arriva e si ignora quello che non si
// conosce; le etichette hanno una traduzione se c'è, altrimenti si mostra il
// nome che manda il server.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type { components } from '@/api/schema'

export type QualitaStato = components['schemas']['QualitaStato']
export type QualitaRiga = components['schemas']['QualitaRiga']

/** Un difetto, così come lo scrive la misura. */
export interface DifettoDiQualita {
  codice: string
  dimensione?: string
  /** 3 grave, 2 media, 1 lieve. */
  gravita?: number
  /** Se il lettore NON apre il file per colpa di questo difetto. */
  blocca?: boolean
  /** «auto» uno script, «ia» serve leggere il testo, «no» non si sistema. */
  sistemabile?: string
  testo?: string
  /** Dove sta: file, voce d'indice, risorsa. Al massimo dieci. */
  dove?: string[]
}

/** Il risultato intero della misura. Volutamente lasco: vedi sopra. */
export interface RisultatoQualita {
  versione?: string
  leggibile?: boolean
  pronto?: boolean
  si_sistema_da_solo?: boolean
  punteggio?: number
  dimensioni?: Record<string, number>
  misure?: Record<string, unknown>
  difetti?: DifettoDiQualita[]
  errore_analisi?: string | null
}

export function useQualitaStato(libraryFolder: string | undefined, attivo = true) {
  return useQuery({
    queryKey: ['qualita-stato', libraryFolder],
    enabled: attivo && !!libraryFolder,
    // Mentre la coda gira lo stato cambia da solo: senza questo, chi guarda
    // vede un numero fermo e crede che si sia impuntata.
    refetchInterval: (q) => ((q.state.data as QualitaStato | undefined)?.in_corso ? 2000 : false),
    queryFn: async (): Promise<QualitaStato> => {
      const { data, error } = await api.GET('/api/kolibre/qualita/status', {
        params: { query: { library: libraryFolder! } },
      })
      if (error) throw error
      return data
    },
  })
}

export function useQualitaLibri(
  libraryFolder: string | undefined,
  opzioni: { ordina?: string; verso?: string; solo?: string } = {},
  attivo = true,
) {
  const { ordina = 'punteggio', verso = 'asc', solo = 'tutti' } = opzioni
  return useQuery({
    queryKey: ['qualita-libri', libraryFolder, ordina, verso, solo],
    enabled: attivo && !!libraryFolder,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/qualita/libri', {
        params: { query: { library: libraryFolder!, ordina, verso, solo } },
      })
      if (error) throw error
      return data
    },
  })
}

/** Il risultato intero di un libro: si chiede solo quando si apre il dettaglio. */
export function useQualitaDettaglio(libraryFolder: string | undefined, bookId: number | null) {
  return useQuery({
    queryKey: ['qualita-dettaglio', libraryFolder, bookId],
    enabled: !!libraryFolder && bookId != null,
    queryFn: async (): Promise<RisultatoQualita> => {
      const { data, error } = await api.GET('/api/kolibre/qualita/libri/{book_id}', {
        params: { path: { book_id: bookId! }, query: { library: libraryFolder! } },
      })
      if (error) throw error
      // `as unknown as` e non un cast diretto: lo schema dichiara i difetti
      // come oggetti liberi (la misura può aggiungere campi), e TypeScript
      // non lascia passare da «oggetto libero» a una forma con campi
      // obbligatori senza dire che lo si sta facendo apposta.
      return data as unknown as RisultatoQualita
    },
  })
}

/**
 * La qualità di un libro per la sua scheda, con i tre esiti distinti.
 *
 * **Perché non si riusa `useQualitaDettaglio`.** Quello lancia l'errore e
 * perde il codice della risposta, e qui il codice è l'informazione: il server
 * risponde **404 se quel libro non è mai stato analizzato** e **409 se
 * l'analisi è fallita**, col motivo. Sono due cose diverse, e trattarle
 * uguale vuol dire che un libro rotto sembra uno non ancora guardato — la
 * scheda direbbe «—» su un file che non si apre.
 *
 * I tre esiti:
 *   - `mai` — nessuno l'ha ancora misurato. La scheda non dice niente.
 *   - `fallita` — misurato e non riuscito, con `motivo`.
 *   - `ok` — c'è il risultato.
 */
export type QualitaDiUnLibro =
  | { esito: 'mai' }
  | { esito: 'fallita'; motivo: string }
  | { esito: 'ok'; risultato: RisultatoQualita }

export function useQualitaDiUnLibro(libraryFolder: string | undefined, bookId: number | null) {
  return useQuery({
    queryKey: ['qualita-di-un-libro', libraryFolder, bookId],
    enabled: !!libraryFolder && bookId != null,
    queryFn: async (): Promise<QualitaDiUnLibro> => {
      const { data, error, response } = await api.GET('/api/kolibre/qualita/libri/{book_id}', {
        params: { path: { book_id: bookId! }, query: { library: libraryFolder! } },
      })
      if (response.status === 404) return { esito: 'mai' }
      if (response.status === 409) {
        const detail = (error as { detail?: string } | undefined)?.detail
        return { esito: 'fallita', motivo: detail || '' }
      }
      if (error) throw error
      return { esito: 'ok', risultato: data as unknown as RisultatoQualita }
    },
    // Un 404 qui è una risposta, non un guasto: non si ritenta.
    retry: false,
  })
}

export async function accendiQualita(libraryFolder: string, acceso: boolean) {
  const { error } = await api.PUT('/api/kolibre/qualita/settings', {
    params: { query: { library: libraryFolder } },
    body: { enabled: acceso },
  })
  if (error) throw error
}

export function useAnalizzaQualita(libraryFolder: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (forza: boolean) => {
      const { error } = await api.POST('/api/kolibre/qualita/analizza', {
        params: { query: { library: libraryFolder! } },
        body: { forza },
      })
      if (error) throw error
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['qualita-stato', libraryFolder] })
      queryClient.invalidateQueries({ queryKey: ['qualita-libri', libraryFolder] })
    },
  })
}
