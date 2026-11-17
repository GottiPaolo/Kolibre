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
// copiare a mano un token è una buona idea: è una credenziale che non scade,
// si incolla male, resta negli appunti, finisce in un messaggio.
//
// **Come funziona: un invito.** Qui — nel sito, dove si è già entrati — nasce
// un codice usa e getta. Lo si porta nel programma, il programma lo scambia
// con un token suo, e il codice è bruciato. La password non passa mai per il
// programma, e la credenziale che resta non è stata copiata da nessuno a mano.
//
// **Il verso conta, ed è cambiato il 17/11/2026.** Il giorno prima andava al
// contrario: il programma bussava, e qui compariva una riga da confermare.
// Paolo l'ha fermato: «non mi piace l'idea che qualsiasi client può mandarmi
// una richiesta… tutto deve partire dal server». Il difetto di quel verso non
// era il codice — era che chiunque raggiungesse il server poteva far comparire
// qualcosa da confermare in questa pagina, che è precisamente il modo di far
// confermare a una persona la cosa sbagliata. In questo verso non c'è niente
// da confermare: nessuno che non sia già dentro può far nascere niente.
//
// **Il codice si vede una volta sola**, e non è prudenza di stile: in database
// c'è soltanto la sua impronta, quindi da quel momento il server non è in
// grado di ridirlo nemmeno volendo. È la stessa regola dei token delle
// applicazioni (Impostazioni ▸ Token delle applicazioni), per la stessa
// ragione. Chi lo perde ne fa un altro: un clic.
//
// **Si può fare anche senza questa pagina**, ed è l'altra richiesta di Paolo
// dello stesso giorno: «il collegamento di nuovi device dovrebbe poter essere
// effettuato anche senza frontend». Dal terminale del server,
// `python3 -m backend.app.invita`. Il comando è scritto qui sotto nella
// finestra, perché il posto in cui uno si chiede «e senza il sito?» è questo.
//
// **Dove si spegne un programma collegato:** Impostazioni ▸ Token delle
// applicazioni, che è l'elenco di tutti i token dell'account — non qui, perché
// un programma non è un dispositivo e non ha una scheda fra i lettori.
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Link2, Loader2, Terminal, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { api } from '@/lib/api'
import { copiaNegliAppunti } from '@/lib/appunti'
import { toast } from '@/lib/toast'
import { messaggioErrore } from '@/lib/messaggiErrore'
import { useLingua } from '@/lib/i18n'

type Invito = {
  id: number
  name: string | null
  origin: string
  status: string
  created_at: string | null
  expires_at: string | null
  redeemed_at: string | null
  client_name: string | null
  platform: string | null
  ip: string | null
}

type InvitoNato = {
  id: number
  code: string
  name: string | null
  expires_at: string
  expires_in_seconds: number
}

// Il comando da terminale, scritto per intero. Non è tradotto e non è
// composto a pezzi: è una riga da copiare, e una riga da copiare che cambia
// con la lingua è una riga che qualcuno copierà sbagliata.
const COMANDO = 'docker compose exec backend python3 -m backend.app.invita'

// Ogni quanto si richiede l'elenco. Un invito vive un quarto d'ora e chi
// guarda questa finestra sta aspettando che un programma lo usi: cinque
// secondi fanno comparire da sé la riga «è stato usato». React Query non
// interroga mentre la finestra non è in primo piano
// (`refetchIntervalInBackground` è falso per difetto), quindi questa finestra
// lasciata aperta in un'altra scheda non chiede niente.
const OGNI = 5000

function useInviti(attivo: boolean) {
  return useQuery({
    queryKey: ['inviti-accoppiamento'],
    queryFn: async (): Promise<Invito[]> => {
      const { data, error } = await api.GET('/api/pairing/invites')
      if (error) throw error
      return data.items as Invito[]
    },
    enabled: attivo,
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

/** Una riga dell'elenco: un invito e com'è andata. */
function RigaInvito({ invito }: { invito: Invito }) {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const [inCorso, setInCorso] = useState(false)

  async function revoca() {
    setInCorso(true)
    try {
      const { error } = await api.POST('/api/pairing/invites/{invite_id}/revoke', {
        params: { path: { invite_id: invito.id } },
      })
      if (error) throw error
      toast.success(t('devices.pairing.revoked'))
      void queryClient.invalidateQueries({ queryKey: ['inviti-accoppiamento'] })
    } catch (e) {
      toast.error(messaggioErrore(e, t('devices.pairing.revokeFailed')))
    } finally {
      setInCorso(false)
    }
  }

  // Lo stato in una riga, con le cose che si vogliono sapere di ciascuno: di
  // uno che aspetta, quando scade; di uno usato, da chi e da dove — che è la
  // sola cosa che il programma non si è raccontata da sé.
  const dettaglio =
    invito.status === 'redeemed'
      ? [
          invito.client_name,
          invito.ip && t('devices.pairing.fromAddress', { ip: invito.ip }),
          oraBreve(invito.redeemed_at) &&
            t('devices.pairing.redeemedAt', { time: oraBreve(invito.redeemed_at) as string }),
        ]
      : [
          invito.origin === 'terminal' ? t('devices.pairing.fromTerminal') : null,
          invito.status === 'pending' && oraBreve(invito.expires_at)
            ? t('devices.pairing.expiresAt', { time: oraBreve(invito.expires_at) as string })
            : null,
        ]

  const colore =
    invito.status === 'pending'
      ? 'text-[var(--warning)]'
      : invito.status === 'redeemed'
        ? 'text-[var(--positive)]'
        : 'text-muted-foreground'

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border bg-background px-3 py-2">
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-[13px] font-medium">
          {/* Il nome che Paolo ha scritto, se l'ha scritto; altrimenti quello
              dichiarato dal programma al riscatto. Testo, non interpretato:
              React lo scrive e non lo esegue, e il server l'ha già tagliato e
              ripulito dagli «a capo». */}
          {invito.name || invito.client_name || t('devices.pairing.unnamed')}
        </span>
        <span className="text-[11.5px] text-muted-foreground">
          {dettaglio.filter(Boolean).join(' · ')}
        </span>
      </div>
      <span className={`ml-auto shrink-0 text-[11.5px] font-semibold ${colore}`}>
        {t(`devices.pairing.status.${invito.status}`)}
      </span>
      {invito.status === 'pending' && (
        <Button variant="ghost" size="sm" disabled={inCorso} onClick={() => void revoca()}>
          {inCorso ? <Loader2 className="size-3.5 animate-spin" /> : <X className="size-3.5" />}
          {t('devices.pairing.revoke')}
        </Button>
      )}
    </div>
  )
}

/** Il pulsante «Collega un client» apre questa. */
export function CollegaUnClientDialog({ onClose }: { onClose: () => void }) {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const [nome, setNome] = useState('')
  const [nato, setNato] = useState<InvitoNato | null>(null)
  const { data: inviti = [] } = useInviti(true)

  const crea = useMutation({
    mutationFn: async (): Promise<InvitoNato> => {
      const { data, error } = await api.POST('/api/pairing/invites', {
        body: { name: nome.trim() || undefined },
      })
      if (error) throw error
      return data as InvitoNato
    },
    onSuccess: (dato) => {
      setNato(dato)
      setNome('')
      void queryClient.invalidateQueries({ queryKey: ['inviti-accoppiamento'] })
    },
    onError: (e) => toast.error(messaggioErrore(e, t('devices.pairing.createFailed'))),
  })

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>
            <Link2 className="mr-1.5 inline size-4" /> {t('devices.pairing.dialogTitle')}
          </DialogTitle>
        </DialogHeader>
        <p className="text-[13px] text-muted-foreground">{t('devices.pairing.how')}</p>

        <div className="flex items-center gap-2">
          <input
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            placeholder={t('devices.pairing.namePlaceholder')}
            aria-label={t('devices.pairing.nameLabel')}
            maxLength={60}
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] outline-none"
          />
          <Button disabled={crea.isPending} onClick={() => crea.mutate()}>
            {crea.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Link2 className="size-3.5" />}
            {t('devices.pairing.create')}
          </Button>
        </div>
        {/* Il nome non è obbligatorio, ma dire a che cosa serve lo rende
            desiderabile: è quello che si leggerà fra sei mesi nell'elenco dei
            token, cioè quando si dovrà decidere se spegnerlo. */}
        <p className="-mt-1 text-[11.5px] text-muted-foreground">{t('devices.pairing.nameWhy')}</p>

        {nato && (
          <div className="rounded-md border border-[var(--warning)]/40 bg-[var(--warning-soft)] p-3">
            <p className="mb-2 text-[12.5px]">{t('devices.pairing.codeOnce')}</p>
            <div className="flex flex-wrap items-center gap-2">
              {/* Grande, spaziato, a larghezza fissa: dieci caratteri da
                  riscrivere su un altro schermo si leggono uno per uno, e
                  l'alfabeto esclude già le lettere che si confondono (niente
                  0/O, 1/I/L, 8/B). */}
              <code className="rounded bg-background px-3 py-1.5 font-mono text-[20px] font-semibold tracking-[0.18em]">
                {nato.code}
              </code>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  void copiaNegliAppunti(nato.code).then((fatto) =>
                    fatto
                      ? toast.success(t('devices.pairing.copied'))
                      : toast.error(t('devices.pairing.copyFailed'))
                  )
                }}
              >
                <Copy className="size-3.5" /> {t('devices.pairing.copy')}
              </Button>
              {oraBreve(nato.expires_at) && (
                <span className="text-[12px] text-muted-foreground">
                  {t('devices.pairing.expiresAt', { time: oraBreve(nato.expires_at) as string })}
                </span>
              )}
            </div>
          </div>
        )}

        {inviti.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-semibold text-muted-foreground">
              {t('devices.pairing.listTitle')}
            </span>
            {inviti.map((i) => (
              <RigaInvito key={i.id} invito={i} />
            ))}
          </div>
        )}

        {/* Il terminale, scritto qui e non in un documento: il posto in cui
            uno si chiede «e se il sito non c'è?» è il sito. */}
        <div className="rounded-md border border-dashed border-border px-3 py-2">
          <p className="mb-1.5 flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <Terminal className="size-3.5" /> {t('devices.pairing.alsoFromTerminal')}
          </p>
          <code
            className="block cursor-pointer break-all rounded bg-muted px-2 py-1 font-mono text-[11.5px]"
            onClick={() => {
              void copiaNegliAppunti(COMANDO).then((fatto) => {
                if (fatto) toast.success(t('devices.pairing.copied'))
              })
            }}
          >
            {COMANDO}
          </code>
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
