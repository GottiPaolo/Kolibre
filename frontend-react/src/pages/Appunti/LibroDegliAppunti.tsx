// Un libro, e tutte le sue evidenziazioni una per una.
//
// **Cosa risponde questa pagina.** La tabella dice *come sta* un libro; qui
// si vede *perché*: quale nota non è mai arrivata nel vault, quale hai
// togliato a mano, quale è cambiata in Kolibre e sta per essere riportata,
// quale è in conflitto. È la vista «vedere le note una per una» che Paolo ha
// scelto fra le tre azioni.
//
// Le note stanno **in ordine di pagina**, non di urgenza: qui il contesto è
// il libro, non l'elenco delle cose da fare, e una nota la si cerca per dove
// stava nel libro.
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowUpRight, ChevronDown, ChevronRight, EyeOff, RefreshCw, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { toast } from '@/lib/toast'
import { useLingua } from '@/lib/i18n'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { ListError } from '@/components/ListError'
import {
  CHIAVE_APPUNTI,
  cambiaIlBlocco,
  chiediIlRifacimento,
  decidiIlConflitto,
  fetchLibroDegliAppunti,
  type NotaNegliAppunti,
} from '@/lib/appuntiActions'
import { foldAccents } from '@/lib/foldAccents'
import { STATI_DI_UNA_NOTA, type StatoDiUnaNota } from '@/lib/appuntiActions'
import { COLORE_DELLO_STATO, COLORE_DI_UNA_NOTA } from './coloriDegliStati'
import { ConflittoDaDecidere } from './ConflittoDaDecidere'
import { ConfrontoDeiDueTesti } from './ConfrontoDeiDueTesti'
import { ConfermaIlRifacimento } from './ConfermaIlRifacimento'

export function LibroDegliAppunti() {
  const { t } = useLingua()
  const [params] = useSearchParams()
  const queryClient = useQueryClient()

  const library = params.get('library') ?? ''
  const id = params.get('id')
  const titolo = params.get('titolo')
  const chiave = useMemo(
    () => ({
      library,
      calibre_book_id: id != null ? Number(id) : null,
      titolo,
    }),
    [library, id, titolo]
  )

  const [cerca, setCerca] = useState('')
  const [chiedeIlRifacimento, setChiedeIlRifacimento] = useState(false)
  const [statiScelti, setStatiScelti] = useState<Set<StatoDiUnaNota>>(new Set())

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['appunti', 'libro', library, id, titolo],
    queryFn: () => fetchLibroDegliAppunti(chiave),
  })

  // La ricerca guarda il brano, la tua nota del lettore e il capitolo, e
  // ignora accenti e maiuscole come quella della Libreria: in un libro di
  // duecento note, ritrovarne una vuol dire ricordarsi una parola.
  const noteMostrate = useMemo(() => {
    const righe = data?.note ?? []
    const ago = foldAccents(cerca.trim())
    return righe.filter((n) => {
      if (statiScelti.size > 0 && !statiScelti.has(n.stato as StatoDiUnaNota)) return false
      if (!ago) return true
      const dove = `${n.testo ?? ''} ${n.nota ?? ''} ${(n.chapter_path ?? []).join(' ')}`
      return foldAccents(dove).includes(ago)
    })
  }, [data, cerca, statiScelti])

  useSetPageHeader(data?.libro.titolo || t('appunti.pageTitle'))

  const decidi = useMutation({
    mutationFn: async (azione: () => Promise<void>) => azione(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['appunti', 'libro'] })
      queryClient.invalidateQueries({ queryKey: CHIAVE_APPUNTI })
    },
    onError: (err: unknown) => toast.error(t('appunti.errore.decisione', { message: messaggio(err) })),
  })

  if (isError) return <ListError what={t('appunti.pageTitle').toLowerCase()} onRetry={() => refetch()} />
  if (isLoading || !data) return <div className="p-4 text-[13px] text-muted-foreground">{t('nav.loading')}</div>

  const { libro, note } = data
  const accoppiato = libro.calibre_book_id != null && !!libro.library

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button asChild size="sm" variant="ghost">
          <Link to="/appunti">
            <ArrowLeft className="size-3.5" />
            {t('appunti.libro.torna')}
          </Link>
        </Button>
        <Badge variant="outline" className={COLORE_DELLO_STATO[libro.stato] ?? ''}>
          {t(`appunti.stato.${libro.stato}`)}
        </Badge>
        <span className="text-[12px] text-muted-foreground">
          {t('appunti.riga.conti', { nel_vault: libro.nel_vault, totali: libro.note_totali })}
        </span>
        {accoppiato && (
          <div className="ml-auto flex items-center gap-1">
            <Button size="sm" variant="ghost" disabled={decidi.isPending}
              onClick={() => {
                if (!libro.da_rifare) { setChiedeIlRifacimento(true); return }
                decidi.mutate(() =>
                  chiediIlRifacimento({
                    library: libro.library || '',
                    calibre_book_id: libro.calibre_book_id as number,
                    titolo: libro.titolo,
                    annulla: true,
                  })
                )
              }}>
              <RefreshCw className={'size-3.5 ' + (libro.da_rifare ? 'text-primary' : '')} />
              {libro.da_rifare ? t('appunti.azione.annullaRifacimento') : t('appunti.azione.rifallo')}
            </Button>
            <Button size="sm" variant="ghost" disabled={decidi.isPending}
              onClick={() =>
                decidi.mutate(() =>
                  cambiaIlBlocco({
                    library: libro.library || '',
                    calibre_book_id: libro.calibre_book_id as number,
                    titolo: libro.titolo,
                    bloccato: libro.stato !== 'bloccato',
                  })
                )
              }>
              <EyeOff className={'size-3.5 ' + (libro.stato === 'bloccato' ? 'text-primary' : '')} />
              {libro.stato === 'bloccato' ? t('appunti.azione.riprendi') : t('appunti.azione.nonMandarlo')}
            </Button>
          </div>
        )}
      </div>

      {libro.percorso ? (
        <div className="text-[12px] text-muted-foreground">
          {t('appunti.riga.file')} <code className="rounded bg-muted px-1 py-0.5">{libro.percorso}</code>
        </div>
      ) : (
        <div className="text-[12px] text-muted-foreground">{t('appunti.riga.nessunFile')}</div>
      )}

      <FiltriDelleNote
        note={note}
        cerca={cerca}
        onCerca={setCerca}
        statiScelti={statiScelti}
        onStato={(stato) =>
          setStatiScelti((v) => {
            const nuovo = new Set(v)
            if (nuovo.has(stato)) nuovo.delete(stato)
            else nuovo.add(stato)
            return nuovo
          })
        }
        mostrate={noteMostrate.length}
      />

      <ConfermaIlRifacimento
        titoloDelLibro={libro.titolo}
        aperta={chiedeIlRifacimento}
        onChiudi={() => setChiedeIlRifacimento(false)}
        onConferma={() =>
          decidi.mutate(() =>
            chiediIlRifacimento({
              library: libro.library || '',
              calibre_book_id: libro.calibre_book_id as number,
              titolo: libro.titolo,
              annulla: false,
            })
          )
        }
      />

      <div className="flex flex-col gap-1.5">
        {noteMostrate.length === 0 && (
          <p className="rounded-lg border border-border bg-card p-3 text-[13px] text-muted-foreground">
            {t('appunti.libro.nessunaNota')}
          </p>
        )}
        {noteMostrate.map((n) => (
          <RigaDiUnaNota
            key={n.id_durevole}
            nota={n}
            inCorso={decidi.isPending}
            onScegli={(scelta) =>
              decidi.mutate(() =>
                decidiIlConflitto(
                  scelta === null
                    ? { id_durevole: n.id_durevole, annulla: true }
                    : { id_durevole: n.id_durevole, scelta }
                )
              )
            }
          />
        ))}
      </div>
    </div>
  )
}

/**
 * La barra della pagina: cerca nel brano, nella tua nota e nel capitolo, e
 * filtra per stato.
 *
 * I filtri mostrano i conteggi, quindi fanno anche da riassunto: con
 * duecento note in un libro, «quante ne ho modificate io» è una domanda che
 * si fa guardando, non contando.
 */
function FiltriDelleNote({
  note,
  cerca,
  onCerca,
  statiScelti,
  onStato,
  mostrate,
}: {
  note: NotaNegliAppunti[]
  cerca: string
  onCerca: (v: string) => void
  statiScelti: Set<StatoDiUnaNota>
  onStato: (s: StatoDiUnaNota) => void
  mostrate: number
}) {
  const { t } = useLingua()
  const perStato = useMemo(() => {
    const conti = new Map<string, number>()
    for (const n of note) conti.set(n.stato, (conti.get(n.stato) ?? 0) + 1)
    return conti
  }, [note])

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          id="appunti-cerca-nota"
          value={cerca}
          onChange={(e) => onCerca(e.target.value)}
          placeholder={t('appunti.libro.cerca')}
          className="h-8 w-60 rounded-md border border-border bg-background pl-7 pr-2 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </div>
      {STATI_DI_UNA_NOTA.filter((s) => (perStato.get(s) ?? 0) > 0).map((s) => {
        const attivo = statiScelti.has(s)
        return (
          <button
            key={s}
            type="button"
            onClick={() => onStato(s)}
            className={
              'rounded-full border px-2 py-0.5 text-[12px] transition-colors ' +
              (attivo ? COLORE_DI_UNA_NOTA[s] : 'border-border text-muted-foreground hover:text-foreground')
            }
          >
            {t(`appunti.nota.${s}`)} <span className="opacity-70">{perStato.get(s)}</span>
          </button>
        )
      })}
      <span className="ml-auto text-[12px] text-muted-foreground">
        {t('appunti.tabella.conto', { mostrati: mostrate, totali: note.length })}
      </span>
    </div>
  )
}

function RigaDiUnaNota({
  nota,
  inCorso,
  onScegli,
}: {
  nota: NotaNegliAppunti
  inCorso: boolean
  onScegli: (scelta: 'kolibre' | 'mio' | null) => void
}) {
  const { t } = useLingua()
  const [apertoIlConfronto, setApertoIlConfronto] = useState(false)

  // **Due versioni da confrontare ci sono solo quando il vault ne ha una
  // sua.** Il plugin manda il testo del file solo dove diverge da quello
  // che Kolibre ci aveva scritto, quindi `nel_vault` c'è esattamente per le
  // note che hai toccato tu — e sono quelle per cui un confronto vuol dire
  // qualcosa. Per una nota «cambiata in Kolibre» il vault ha ancora il
  // brano vecchio, ma quel testo il server non ce l'ha: ha solo la sua
  // impronta, e un'impronta non si legge.
  const haDueVersioni = !!nota.nel_vault && nota.stato !== 'conflitto'

  return (
    <div className="rounded-lg border border-border bg-card p-2.5">
      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
        {nota.page != null && <span className="tabular-nums">{t('appunti.nota.pagina', { page: nota.page })}</span>}
        {nota.chapter_path.length > 0 && (
          <span className="truncate" title={nota.chapter_path.join(' ▸ ')}>
            {nota.chapter_path.join(' ▸ ')}
          </span>
        )}
        <Badge variant="outline" className={COLORE_DI_UNA_NOTA[nota.stato] ?? ''}>
          {t(`appunti.nota.${nota.stato}`)}
        </Badge>
        {haDueVersioni && (
          <button
            type="button"
            onClick={() => setApertoIlConfronto((v) => !v)}
            className="inline-flex items-center gap-1 underline-offset-2 hover:text-foreground hover:underline"
          >
            {apertoIlConfronto ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            {apertoIlConfronto ? t('appunti.confronto.chiudi') : t('appunti.confronto.apri')}
          </button>
        )}
        {nota.link && (
          <a
            href={nota.link}
            className="ml-auto inline-flex items-center gap-1 underline-offset-2 hover:text-foreground hover:underline"
          >
            {t('appunti.conflitto.apriInKolibre')}
            <ArrowUpRight className="size-3.5" />
          </a>
        )}
      </div>

      {/* Un conflitto si guarda affiancato e si decide qui; tutti gli altri
          stati hanno una versione sola da mostrare, e mostrarne due uguali
          sarebbe rumore. */}
      {nota.stato === 'conflitto' ? (
        <ConflittoDaDecidere
          conflitto={{
            id_durevole: nota.id_durevole,
            nel_vault: nota.nel_vault,
            nel_server: nota.testo,
            link: null,
            impronta_nel_vault: null,
            impronta_base: null,
            scelta: nota.scelta,
          }}
          inCorso={inCorso}
          onScegli={onScegli}
        />
      ) : apertoIlConfronto ? (
        <ConfrontoDeiDueTesti inKolibre={nota.testo} nelVault={nota.nel_vault} />
      ) : (
        <blockquote className="whitespace-pre-wrap border-l-2 border-border pl-2 text-[13px] leading-relaxed">
          {nota.testo}
        </blockquote>
      )}

      {nota.nota && (
        <p className="mt-1.5 text-[12.5px]">
          <span className="text-muted-foreground">{t('appunti.nota.tuaNota')} </span>
          {nota.nota}
        </p>
      )}
    </div>
  )
}

function messaggio(err: unknown): string {
  if (err && typeof err === 'object' && 'detail' in err) return String((err as { detail: unknown }).detail)
  return err instanceof Error ? err.message : String(err)
}
