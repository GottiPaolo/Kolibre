// Appunti: come stanno le note di Kolibre fuori da Kolibre.
//
// **Da zero.** Il plugin Obsidian tiene nel vault un file per libro, con
// dentro un blocco per evidenziazione, e Paolo ci scrive attorno. Il server
// non può guardare in quella cartella né scriverci: è il plugin che
// **racconta** cosa ha, quando Paolo gli chiede di sincronizzare. Questa
// pagina mostra l'ultimo racconto, e permette di dare le istruzioni che il
// plugin eseguirà al giro dopo — bloccare un libro, rifarlo da zero,
// decidere un conflitto.
//
// **Niente tasto «aggiorna».** La fotografia cambia solo quando il plugin
// racconta, cioè quando si premé il comando *in Obsidian*: un tasto nel
// browser non può farla cambiare, e tornando da Obsidian la pagina si
// rilegge già da sé. L'unica cosa informativa è quando è stato l'ultimo
// racconto, e quella c'è.
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Clock, NotebookPen } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { toast } from '@/lib/toast'
import { useLingua } from '@/lib/i18n'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { relativeTimeFrom } from '@/lib/deviceFormat'
import { ListError } from '@/components/ListError'
import {
  CHIAVE_APPUNTI,
  cambiaIlBlocco,
  chiediIlRifacimento,
  fetchStatoDegliAppunti,
  type LibroNegliAppunti,
} from '@/lib/appuntiActions'
import { TabellaDeiLibri } from './TabellaDeiLibri'

export function AppuntiPage() {
  const { t } = useLingua()
  useSetPageHeader(t('appunti.pageTitle'))
  const queryClient = useQueryClient()

  // Quale vault si sta guardando. Nullo vuol dire «quello che ha raccontato
  // più di recente», che è la risposta giusta quando ce n'è uno solo — cioè
  // quasi sempre. Il selettore compare solo se ce ne sono due, perché
  // altrimenti la pagina nasconderebbe un vault in silenzio.
  const [clienteScelto, setClienteScelto] = useState<number | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: [...CHIAVE_APPUNTI, clienteScelto],
    queryFn: () => fetchStatoDegliAppunti(clienteScelto),
  })

  // Una decisione presa qui cambia lo stato di un libro, quindi dopo ogni
  // decisione si rilegge: non si indovina il nuovo stato dal vecchio, lo dice
  // il server — che è l'unico a sapere, per esempio, che un rifacimento
  // chiude anche i conflitti di quel libro.
  const decidi = useMutation({
    mutationFn: async (azione: () => Promise<void>) => azione(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHIAVE_APPUNTI }),
    onError: (err: unknown) => toast.error(t('appunti.errore.decisione', { message: messaggio(err) })),
  })

  if (isError) return <ListError what={t('appunti.pageTitle').toLowerCase()} onRetry={() => refetch()} />
  if (isLoading || !data) return <div className="p-4 text-[13px] text-muted-foreground">{t('nav.loading')}</div>

  const { cliente, clienti, riassunto, libri } = data
  if (!cliente) return <NessunClient />

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-3 p-4">
      {/* Chi ha raccontato, e QUANDO. La data non è un ornamento: il server
          non sa cosa c'è nel vault adesso, sa cosa c'era quando il plugin
          gliel'ha detto. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border bg-card p-2.5">
        <NotebookPen className="size-4 shrink-0 text-muted-foreground" />
        <span className="text-[13.5px] font-medium">{cliente.nome || t('appunti.cliente.senzaNome')}</span>
        <span className="inline-flex items-center gap-1 text-[12px] text-muted-foreground">
          <Clock className="size-3.5" />
          {t('appunti.cliente.visto', { quando: relativeTimeFrom(cliente.visto_il, t) })}
        </span>
        <span className="text-[12px] text-muted-foreground">
          {t('appunti.cliente.conti', { file: cliente.file_visti, note: cliente.note_viste })}
        </span>
        {clienti.length > 1 && (
          <div className="ml-auto flex items-center gap-1">
            {clienti.map((c) => (
              <Button
                key={c.id}
                size="sm"
                variant={c.id === cliente.id ? 'secondary' : 'ghost'}
                onClick={() => setClienteScelto(c.id)}
              >
                {c.nome || t('appunti.cliente.senzaNome')}
              </Button>
            ))}
          </div>
        )}
      </div>

      {riassunto.istruzioni_in_attesa > 0 && (
        <p className="rounded-md border border-primary/30 bg-primary/5 px-2.5 py-2 text-[12.5px]">
          {t('appunti.istruzioniInAttesa', { count: riassunto.istruzioni_in_attesa })}
        </p>
      )}

      <TabellaDeiLibri
        libri={libri}
        inCorso={decidi.isPending}
        onBlocco={(libro, bloccato) =>
          decidi.mutate(() =>
            cambiaIlBlocco({
              library: libro.library || '',
              calibre_book_id: libro.calibre_book_id as number,
              titolo: libro.titolo,
              bloccato,
            })
          )
        }
        onRifacimento={(libro: LibroNegliAppunti, annulla) =>
          decidi.mutate(() =>
            chiediIlRifacimento({
              library: libro.library || '',
              calibre_book_id: libro.calibre_book_id as number,
              titolo: libro.titolo,
              annulla,
            })
          )
        }
      />

      <p className="text-[12px] text-muted-foreground">
        {t('appunti.pieDiPagina', { count: riassunto.da_guardare })}
      </p>
    </div>
  )
}

// Nessun client è una risposta, non un errore: nessuno ha mai raccontato
// niente. La voce nella barra laterale in questo caso non si vede nemmeno,
// quindi qui ci si arriva solo per indirizzo diretto — o perché la voce è
// stata messa a mano in Impostazioni — e allora va spiegato cosa manca.
function NessunClient() {
  const { t } = useLingua()
  return (
    <div className="mx-auto w-full max-w-2xl p-4">
      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold">
          <NotebookPen className="size-4 text-muted-foreground" />
          {t('appunti.nessunClient.titolo')}
        </h2>
        <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
          {t('appunti.nessunClient.spiegazione')}
        </p>
      </div>
    </div>
  )
}

function messaggio(err: unknown): string {
  if (err && typeof err === 'object' && 'detail' in err) return String((err as { detail: unknown }).detail)
  return err instanceof Error ? err.message : String(err)
}
