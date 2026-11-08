// Righe di consegna rimaste senza libro: il server crede di avere un libro
// su un lettore, ma in biblioteca quel libro non c'è più.
//
// Non è il difetto delle note vedove (quelle sono annotazioni senza libro):
// queste sono le righe che dicono «questo file è su questo lettore», e
// restano indietro quando un libro esce da Calibre per una strada che non
// passa da Kolibre — cancellato da Calibre desktop, perso in uno
// spostamento di biblioteca. Il conto dei libri del dispositivo resta
// gonfio, e nessuno lo contraddice: il lettore non ha modo di sapere che in
// biblioteca è stato cancellato.
//
// L'azione principale è FAR CANCELLARE IL FILE DAL LETTORE (decisione di
// Paolo, 03/11/2026: un libro che la biblioteca non ha più non ha valore
// là). «Dimentica soltanto» resta accanto, per chi quel file lo vuole
// tenere — e diventa l'unica possibile nei due casi in cui la cancellazione
// non si può chiedere: quando il file è la copia di un libro ancora in
// biblioteca, e quando il lettore ha la politica «mai cancellare».
//
// Il libro non ha più né titolo né autore da mostrare — in biblioteca non
// esiste —, quindi la riga si riconosce dal nome del file che il lettore ha
// riportato: è l'unica cosa leggibile che resta, ed è anche quella che dice
// di che libro si trattava.
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Clock, Loader2, Smartphone, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { components } from '@/api/schema'
import { toast } from '@/lib/toast'
import { useLingua, type Valori } from '@/lib/i18n'

/**
 * **Dal 05/11/2026 arriva dallo schema.** Il tipo scritto a mano si fermava
 * a dieci campi su dodici: mancavano `created_at` e `updated_at`, che la
 * risposta porta da sempre — e sono la sola cosa che dice *da quanto* quella
 * riga è indietro.
 */
export type RigaSenzaLibro = components['schemas']['RigaSenzaLibro']

const CHIAVE = ['interventi', 'righe-senza-libro']

async function leggiRighe() {
  const { data, error } = await api.GET('/api/kolibre/interventions/device-books-gone', {})
  if (error) throw error
  return data.righe
}

async function dimentica(ids: number[]): Promise<number> {
  const { data, error } = await api.POST('/api/kolibre/interventions/device-books-gone/forget', {
    body: { ids },
  })
  if (error) throw error
  return data.dimenticate
}

// Il tipo scritto a mano ne dichiarava tre di quattro: `dimenticabili`
// c'era nella risposta e non qui, e porta gli id delle righe rifiutate —
// cioè l'unica cosa che su quelle righe si può ancora fare.
async function cancellaDalLettore(ids: number[]) {
  const { data, error } = await api.POST(
    '/api/kolibre/interventions/device-books-gone/delete-on-device',
    { body: { ids } }
  )
  if (error) throw error
  return data
}

/** Il nome del file, che è quanto resta per riconoscere il libro. */
function nomeFile(percorso: string | null): string | null {
  if (!percorso) return null
  const pezzi = percorso.split('/')
  return pezzi[pezzi.length - 1] || percorso
}

/** Perché su questa riga la cancellazione non si può chiedere, se non si può. */
function motivoNonCancellabile(r: RigaSenzaLibro): 'libroVivo' | 'politica' | null {
  if (r.percorso_di_un_libro_vivo) return 'libroVivo'
  if (r.delete_policy === 'never') return 'politica'
  return null
}

export function LibriScomparsiPanel() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const [inCorso, setInCorso] = useState<number[]>([])

  const { data: righe = [] } = useQuery({ queryKey: CHIAVE, queryFn: leggiRighe })

  // Anche l'elenco dei dispositivi cambia: è da lì che si legge "quanti
  // libri ha questo lettore".
  const ricarica = () => {
    void queryClient.invalidateQueries({ queryKey: CHIAVE })
    void queryClient.invalidateQueries({ queryKey: ['devices'] })
  }

  const rimuovo = useMutation({
    mutationFn: cancellaDalLettore,
    onSuccess: (esito) => {
      if (esito.in_coda > 0) {
        toast.success(t('interventions.devicesGone.queued', { count: esito.in_coda, n: esito.in_coda }))
      }
      // I rifiuti non sono un errore, ma vanno detti: chi ha premuto non
      // poteva saperlo dall'elenco.
      if (esito.rifiutate > 0) {
        toast.info(t('interventions.devicesGone.refusedLiveBook', { n: esito.rifiutate }))
      }
      if (esito.rifiutate_politica > 0) {
        toast.info(t('interventions.devicesGone.refusedPolicy', { n: esito.rifiutate_politica }))
      }
      ricarica()
    },
    onError: () => toast.error(t('interventions.devicesGone.queueFailed')),
    onSettled: () => setInCorso([]),
  })

  const dimentico = useMutation({
    mutationFn: dimentica,
    onSuccess: (quante) => {
      toast.success(t('interventions.devicesGone.forgotten', { count: quante, n: quante }))
      ricarica()
    },
    onError: () => toast.error(t('interventions.devicesGone.forgetFailed')),
    onSettled: () => setInCorso([]),
  })

  if (righe.length === 0) return null

  const occupato = rimuovo.isPending || dimentico.isPending

  // Un utente può avere più lettori, e la riga da buttare su uno non dice
  // niente sull'altro: si tengono separati.
  const perLettore = new Map<string, RigaSenzaLibro[]>()
  for (const r of righe) {
    const elenco = perLettore.get(r.device_name) ?? []
    elenco.push(r)
    perLettore.set(r.device_name, elenco)
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[12.5px] text-muted-foreground">
        {t('interventions.devicesGone.explanation')}
      </p>

      {[...perLettore.entries()].map(([lettore, suoi]) => {
        // «Toglile tutte dal lettore» ha senso solo se c'è qualcosa da
        // togliere: un gruppo di sole righe non cancellabili non deve
        // mostrare un pulsante che rifiuterebbe tutto.
        const cancellabili = suoi.filter((r) => !motivoNonCancellabile(r) && r.status !== 'pending_delete')
        return (
          <div key={lettore} className="rounded-md border border-border/70">
            <div className="flex items-center gap-2 border-b border-border/70 px-2.5 py-1.5">
              <Smartphone className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="text-[12.5px] font-medium">{lettore}</span>
              <span className="text-[11.5px] text-muted-foreground">
                {t('interventions.devicesGone.rowCount', { count: suoi.length, n: suoi.length })}
              </span>
              {cancellabili.length > 0 && (
                <Button
                  size="sm"
                  variant="outline"
                  className="ml-auto"
                  disabled={occupato}
                  onClick={() => {
                    setInCorso(cancellabili.map((r) => r.id))
                    rimuovo.mutate(cancellabili.map((r) => r.id))
                  }}
                >
                  <Trash2 className="size-3.5" />
                  {t('interventions.devicesGone.deleteAll', { n: cancellabili.length })}
                </Button>
              )}
            </div>

            <div className="flex flex-col divide-y divide-border/60">
              {suoi.map((r) => (
                <Riga
                  key={r.id}
                  riga={r}
                  inCorso={occupato && inCorso.includes(r.id)}
                  disattivato={occupato}
                  onCancella={() => {
                    setInCorso([r.id])
                    rimuovo.mutate([r.id])
                  }}
                  onDimentica={() => {
                    setInCorso([r.id])
                    dimentico.mutate([r.id])
                  }}
                  t={t}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Riga({
  riga, inCorso, disattivato, onCancella, onDimentica, t,
}: {
  riga: RigaSenzaLibro
  inCorso: boolean
  disattivato: boolean
  onCancella: () => void
  onDimentica: () => void
  t: (chiave: string, valori?: Valori) => string
}) {
  const nome = nomeFile(riga.device_path)
  const motivo = motivoNonCancellabile(riga)
  const giaInCoda = riga.status === 'pending_delete'
  // Le etichette di stato esistono solo per gli stati che vale la pena
  // leggere; "sincronizzato" è il caso normale e dirlo sarebbe rumore.
  const stato = riga.status === 'synced' ? null : t(`interventions.devicesGone.status.${riga.status}`)

  return (
    <div className="flex items-center gap-2 px-2.5 py-1.5">
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12.5px]" title={riga.device_path ?? undefined}>
          {nome ?? <span className="text-muted-foreground">{t('interventions.devicesGone.noPath')}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground">
          <span>
            {t('interventions.devicesGone.rowLabel', {
              library: riga.library,
              id: riga.calibre_book_id,
              format: riga.format,
            })}
          </span>
          {stato && <span>· {stato}</span>}
          {motivo === 'libroVivo' && (
            <span className="text-[var(--text-faint)]" title={t('interventions.devicesGone.sharedPathHelp')}>
              · {t('interventions.devicesGone.sharedPath')}
            </span>
          )}
          {motivo === 'politica' && (
            <span className="text-[var(--text-faint)]" title={t('interventions.devicesGone.policyNeverHelp')}>
              · {t('interventions.devicesGone.policyNever')}
            </span>
          )}
        </div>
      </div>

      {giaInCoda ? (
        <span className="flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground"
              title={t('interventions.devicesGone.waitingHelp')}>
          <Clock className="size-3.5" />
          {t('interventions.devicesGone.waiting')}
        </span>
      ) : (
        !motivo && (
          <Button size="sm" variant="outline" disabled={disattivato} onClick={onCancella}>
            {inCorso && <Loader2 className="size-3.5 animate-spin" />}
            {t('interventions.devicesGone.deleteOne')}
          </Button>
        )
      )}
      <Button size="sm" variant="ghost" disabled={disattivato} onClick={onDimentica}>
        {t('interventions.devicesGone.forgetOne')}
      </Button>
    </div>
  )
}

/** Quante righe aspettano: serve all'intestazione, che si legge da chiusa. */
export function useQuantiLibriScomparsi(): number | null {
  const { data } = useQuery({ queryKey: CHIAVE, queryFn: leggiRighe })
  return data ? data.length : null
}
