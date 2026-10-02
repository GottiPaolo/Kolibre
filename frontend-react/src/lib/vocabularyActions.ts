// Vocabulary Builder centralizzato (/api/kolibre/vocabulary — backend/app/api/vocabulary.py):
// unisce le parole salvate da ogni dispositivo KOReader con quelle aggiunte
// dal reader web in un'unica lista, con id composito "device:N" / "web:N".
// Usata sia dal popup di selezione parola nel reader (ReaderPage.tsx) per
// l'azione "Aggiungi al vocabolario", sia dalla futura pagina centralizzata.
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export interface VocabularyItem {
  id: string
  source: 'device' | 'web'
  source_label: string
  word: string
  highlight: string | null
  book_title: string | null
  library: string | null
  calibre_book_id: number | null
  context_before: string | null
  context_after: string | null
  create_time: string | null
  definition: string | null
  definition_source: string | null
  definition_fetched_at: string | null
}

export async function listVocabulary(): Promise<VocabularyItem[]> {
  const { data, error } = await api.GET('/api/kolibre/vocabulary')
  if (error) throw error
  return (data as unknown as { items: VocabularyItem[] }).items
}

export function useVocabulary() {
  return useQuery({ queryKey: ['vocabulary'], queryFn: listVocabulary })
}

export interface AddWordPayload {
  library: string
  calibre_book_id: number
  word: string
  highlight?: string | null
  context_before?: string | null
  context_after?: string | null
  definition?: string | null
  definition_source?: string | null
  // Il backend accetta un body libero (`payload: dict`, vedi vocabulary.py)
  // senza schema Pydantic dedicato — openapi-typescript lo tipizza quindi
  // come record generico: l'index signature qui rende AddWordPayload
  // assegnabile a quel tipo mantenendo comunque i campi noti sopra.
  [key: string]: unknown
}

export async function addWordToVocabulary(payload: AddWordPayload): Promise<VocabularyItem> {
  const { data, error } = await api.POST('/api/kolibre/vocabulary', { body: payload })
  if (error) throw error
  return data as unknown as VocabularyItem
}

export async function fetchVocabularyDefinition(id: string): Promise<VocabularyItem> {
  const { data, error } = await api.POST('/api/kolibre/vocabulary/{composite_id}/fetch-definition', {
    params: { path: { composite_id: id } },
  })
  if (error) throw error
  return data as unknown as VocabularyItem
}

// ── Vocabolari che sono la copia di un altro ─────────────────────────────
//
// KOReader tiene una riga per parola PER DISPOSITIVO, quindi due lettori
// possono legittimamente avere vocabolari propri e la sovrapposizione non è
// di per sé un difetto. Lo diventa quando i due hanno lo stesso
// vocabulary_builder.sqlite3 perché qualcuno li ha sincronizzati fra loro —
// ed è esattamente quello che ha già prodotto 743 sessioni di lettura mai
// avvenute su un dispositivo reale.
//
// Stava dentro la scheda di ogni singolo dispositivo, che è il posto
// sbagliato: la sovrapposizione è una relazione FRA due lettori, e
// chiedersela uno alla volta significava non vederla mai tutta.
export interface SovrapposizioneDispositivo {
  id: number
  nome: string
  parole: number
  in_comune: { id: number; nome: string; parole: number }[]
}

export function useSovrapposizioniVocabolario() {
  return useQuery({
    queryKey: ['vocabolario-sovrapposizioni'],
    queryFn: async (): Promise<SovrapposizioneDispositivo[]> => {
      const { data, error } = await api.GET('/api/kolibre/vocabulary/sovrapposizioni')
      if (error) throw error
      return (data as unknown as { dispositivi: SovrapposizioneDispositivo[] }).dispositivi
    },
  })
}
