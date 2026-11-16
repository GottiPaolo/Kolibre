// Il punto in cui un programma viene fatto entrare.
//
// **Da zero: che cos'è un «client» qui.** Non un lettore come un Kindle, ma un
// programma che gira su un computer — il client nativo di Kolibre, uno script
// — e che per parlare col server ha bisogno di una credenziale.
//
// **Perché non gli si dà la password.** Perché finirebbe scritta da qualche
// parte sul computer: è il difetto che il plugin Obsidian aveva, che
// conservava la password dentro il vault (cioè dentro la cartella che si
// sincronizza fra computer, a volte in un repository git). E perché nemmeno
// copiare a mano un token è una buona idea: si incolla male, resta negli
// appunti, finisce in un messaggio.
//
// **Come funziona invece.** Il programma chiede al server un codice di sei
// caratteri e lo mostra nella sua finestra. Qui — nel sito, dove si è già
// entrati — la richiesta compare da sé, con quel codice. Si confronta, si
// conferma, e il programma riceve il token da sé. Nessuno copia niente.
//
// **Perché il codice si mostra in grande, e non c'è solo un pulsante.** La
// rotta con cui un programma bussa risponde a chiunque raggiunga il server —
// deve, perché chi bussa non ha ancora credenziali. Quindi la richiesta che
// compare qui potrebbe non essere la propria. La difesa è il codice: quelle
// sei lettere sono sullo schermo di chi sta aspettando, e un pulsante
// «conferma» da solo non le farebbe guardare. Per lo stesso motivo si mostra
// **l'indirizzo** da cui la richiesta arriva: è la sola cosa che il server sa
// e che la richiesta non può raccontarsi da sola.
//
// **Dove si spegne un programma collegato:** Impostazioni ▸ Token delle
// applicazioni, che è l'elenco di tutti i token dell'account — non qui, perché
// un programma non è un dispositivo e non ha una scheda fra i lettori.
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Link2, Loader2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { api } from '@/lib/api'
import { toast } from '@/lib/toast'
import { messaggioErrore } from '@/lib/messaggiErrore'
import { useLingua } from '@/lib/i18n'

type Richiesta = {
  id: number
  code: string
  client_name: string
  platform: string | null
  ip: string | null
  created_at: string | null
  expires_at: string | null
}

// Ogni quanto si richiede l'elenco. Un codice vive cinque minuti e chi lo
// aspetta sta guardando lo schermo: tre secondi sono il tempo che fa sembrare
// la richiesta «comparsa da sé». React Query non interroga mentre la finestra
// non è in primo piano (`refetchIntervalInBackground` è falso per difetto),
// quindi una pagina lasciata aperta in un'altra scheda non chiede niente.
const OGNI = 3000

export function useRichiesteDiAccoppiamento() {
  return useQuery({
    queryKey: ['richieste-accoppiamento'],
    queryFn: async (): Promise<Richiesta[]> => {
      const { data, error } = await api.GET('/api/pairing/requests')
      if (error) throw error
      return data.items as Richiesta[]
    },
    refetchInterval: OGNI,
  })
}

function oraBreve(quando: string | null) {
  if (!quando) return null
  const d = new Date(quando)
  return Number.isNaN(d.getTime())
    ? null
    : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

function RigaRichiesta({ richiesta }: { richiesta: Richiesta }) {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const [inCorso, setInCorso] = useState(false)

  async function rispondi(confermo: boolean) {
    setInCorso(true)
    try {
      const indirizzo = confermo
        ? '/api/pairing/requests/{request_id}/confirm'
        : '/api/pairing/requests/{request_id}/refuse'
      const { error } = await api.POST(indirizzo, {
        params: { path: { request_id: richiesta.id } },
      })
      if (error) throw error
      toast.success(
        confermo
          ? t('devices.pairing.confirmed', { name: richiesta.client_name })
          : t('devices.pairing.refused')
      )
      void queryClient.invalidateQueries({ queryKey: ['richieste-accoppiamento'] })
      // L'elenco dei token dell'account: il programma appena collegato ne ha
      // uno nuovo, e quella pagina è dove si spegne.
      void queryClient.invalidateQueries({ queryKey: ['token-applicazione'] })
    } catch (e) {
      toast.error(
        messaggioErrore(
          e,
          confermo ? t('devices.pairing.confirmFailed') : t('devices.pairing.refuseFailed')
        )
      )
    } finally {
      setInCorso(false)
    }
  }

  const scade = oraBreve(richiesta.expires_at)

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border border-border bg-background px-3 py-2.5">
      {/* Il codice è la cosa che si guarda: grande, spaziato, in un carattere
          a larghezza fissa perché sei caratteri da confrontare uno per uno si
          leggono meglio allineati. */}
      <code className="rounded bg-muted px-2.5 py-1 font-mono text-[18px] font-semibold tracking-[0.2em]">
        {richiesta.code}
      </code>
      <div className="flex min-w-0 flex-col">
        {/* Testo scritto dal programma: si mostra come testo e non lo si
            interpreta. React lo scrive, non lo esegue; il server l'ha già
            tagliato e ripulito dagli «a capo». */}
        <span className="truncate text-[13px] font-medium">{richiesta.client_name}</span>
        <span className="text-[11.5px] text-muted-foreground">
          {[richiesta.platform, richiesta.ip && t('devices.pairing.fromAddress', { ip: richiesta.ip }),
            scade && t('devices.pairing.expiresAt', { time: scade })]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <Button variant="ghost" size="sm" disabled={inCorso} onClick={() => void rispondi(false)}>
          <X className="size-3.5" /> {t('devices.pairing.refuse')}
        </Button>
        <Button size="sm" disabled={inCorso} onClick={() => void rispondi(true)}>
          {inCorso ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
          {t('devices.pairing.confirm')}
        </Button>
      </div>
    </div>
  )
}

/**
 * Le richieste che aspettano, in cima alla pagina dei dispositivi.
 *
 * **Non c'è quando non c'è niente.** Un riquadro che dice «nessun programma
 * sta chiedendo di collegarsi» occuperebbe per sempre il posto in cui deve
 * saltare all'occhio quello vero — è la stessa scelta dell'avviso delle
 * versioni del plugin, qui sopra nella stessa pagina. Chi vuole collegare un
 * programma senza aspettare passa dal pulsante «Collega un client».
 */
export function RichiesteInAttesa() {
  const { t } = useLingua()
  const { data: richieste = [] } = useRichiesteDiAccoppiamento()
  if (richieste.length === 0) return null
  return (
    <div className="flex flex-col gap-2 rounded-md border border-[var(--warning)]/40 bg-[var(--warning-soft)] p-3">
      <div className="flex items-baseline gap-2">
        <span className="text-[13px] font-semibold">{t('devices.pairing.waitingTitle')}</span>
        <span className="text-[12px] text-muted-foreground">{t('devices.pairing.matchHint')}</span>
      </div>
      {richieste.map((r) => (
        <RigaRichiesta key={r.id} richiesta={r} />
      ))}
    </div>
  )
}

/** Il pulsante e la finestra che spiegano come si fa. */
export function CollegaUnClientDialog({ onClose }: { onClose: () => void }) {
  const { t } = useLingua()
  const { data: richieste = [], isLoading } = useRichiesteDiAccoppiamento()
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>
            <Link2 className="mr-1.5 inline size-4" /> {t('devices.pairing.dialogTitle')}
          </DialogTitle>
        </DialogHeader>
        <p className="text-[13px] text-muted-foreground">{t('devices.pairing.how')}</p>
        <div className="flex flex-col gap-2">
          {richieste.map((r) => (
            <RigaRichiesta key={r.id} richiesta={r} />
          ))}
          {!isLoading && richieste.length === 0 && (
            // Qui la riga «non c'è niente» serve, al contrario che in pagina:
            // questa finestra l'ha aperta qualcuno che sta aspettando, e il
            // silenzio sarebbe indistinguibile da un guasto.
            <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-[13px] text-muted-foreground">
              {t('devices.pairing.none')}
            </p>
          )}
        </div>
        <p className="text-[12px] text-muted-foreground">{t('devices.pairing.whereToRevoke')}</p>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
