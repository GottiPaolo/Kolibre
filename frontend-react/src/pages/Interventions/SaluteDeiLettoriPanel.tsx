// Il legame fra il server e i lettori: un controllo che si chiede.
//
// **Perché questa voce si comporta diversamente da tutte le altre di questa
// pagina.** Le altre contano qualcosa a ogni apertura — note senza libro,
// doppioni, libri che sembrano letti. Questa no: per sapere se un'impronta
// descrive ancora il suo file bisogna aprire il file, e sono 8217 file in 24
// secondi sull'impianto di Paolo. Aprire la pagina Interventi non può costare
// 24 secondi di lettura disco, e non servirebbe: il risultato non cambia da
// solo fra un'apertura e l'altra.
//
// Quindi: un pulsante che lancia il controllo, l'avanzamento mentre gira, e
// l'esito che resta. L'esito vive nel server (non in questa pagina), quindi
// chiudere la finestra non lo perde e due schede vedono la stessa cosa.
//
// **Ogni riparazione chiede conferma** — deciso da Paolo il 04/11/2026. Anche
// quella sicura: riscrivere un'impronta non si vede da nessuna parte, e una
// cosa che non si vede va chiesta prima, non dopo.
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, AlertTriangle, Loader2, RefreshCw, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { components } from '@/api/schema'
import { toast } from '@/lib/toast'
import { useLingua } from '@/lib/i18n'

// **Dal 05/11/2026 questi tipi arrivano dallo schema.** Erano scritti a mano,
// e con una semplificazione che costava: `da_ricalcolare` e `senza_file`
// erano **lo stesso tipo** con quattro campi facoltativi, mentre nel server
// sono due forme distinte — un'impronta da rifare porta sempre `registrata`,
// `vera` e `verified`, una riga senza file porta sempre `in_biblioteca`, e
// nessuna delle due porta i campi dell'altra. Unirle rendeva facoltativo
// tutto e non diceva più quale campo contare su quale riga.
type ImprontaDaRifare = components['schemas']['ImprontaDaRifare']
type RigaSenzaFile = components['schemas']['RigaSenzaFile']

export type StatoSalute = components['schemas']['StatoDelLegame']

const CHIAVE = ['interventi', 'salute-dei-lettori']

async function leggiStato() {
  const { data, error } = await api.GET('/api/kolibre/interventions/device-link', {})
  if (error) throw error
  return data
}

/** Le tre coordinate che bastano a ritrovare una riga lato server — e sono
 *  le stesse per entrambe le forme, che è il motivo per cui le due
 *  riparazioni possono condividere questa funzione. */
function coordinate(v: ImprontaDaRifare | RigaSenzaFile) {
  return { library: v.library, calibre_book_id: v.calibre_book_id, format: v.format }
}

export function useSaluteDeiLettori() {
  return useQuery({
    queryKey: CHIAVE,
    queryFn: leggiStato,
    // Mentre il controllo gira si richiede l'avanzamento; quando è fermo non
    // si chiede più niente, perché non cambia da sé.
    refetchInterval: (query) => (query.state.data?.in_corso ? 700 : false),
  })
}

export function SaluteDeiLettoriPanel() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: stato, isLoading } = useSaluteDeiLettori()
  const [conferma, setConferma] = useState<'rifai' | 'dimentica' | null>(null)

  const avvia = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/kolibre/interventions/device-link/check', {})
      if (error) throw error
      return data
    },
    onSuccess: (esito) => {
      if (!esito.avviato) toast.info(t('interventions.deviceLink.alreadyRunning'))
      void queryClient.invalidateQueries({ queryKey: CHIAVE })
    },
    onError: () => toast.error(t('interventions.deviceLink.checkFailed')),
  })

  const rifai = useMutation({
    mutationFn: async (voci: ImprontaDaRifare[]) => {
      const { data, error } = await api.POST('/api/kolibre/interventions/device-link/recompute', {
        body: { voci: voci.map(coordinate) },
      })
      if (error) throw error
      return data
    },
    onSuccess: (e) => {
      // I tre esiti si dicono separati: «rifatte 5» con 2 già a posto è una
      // cosa, «rifatte 5, 2 non riuscite» è un'altra, e confonderle
      // nasconderebbe proprio i casi da guardare.
      if (e.rifatte > 0) toast.success(t('interventions.deviceLink.recomputed', { n: e.rifatte }))
      if (e.gia_a_posto > 0) toast.info(t('interventions.deviceLink.alreadyFine', { n: e.gia_a_posto }))
      if (e.non_riuscite.length > 0) {
        toast.error(t('interventions.deviceLink.recomputeFailed', { n: e.non_riuscite.length }))
      }
      void queryClient.invalidateQueries({ queryKey: CHIAVE })
      void queryClient.invalidateQueries({ queryKey: ['devices'] })
    },
    onError: () => toast.error(t('interventions.deviceLink.recomputeFailed', { n: 0 })),
  })

  const dimentica = useMutation({
    mutationFn: async (voci: RigaSenzaFile[]) => {
      const { data, error } = await api.POST('/api/kolibre/interventions/device-link/forget-missing', {
        body: { voci: voci.map(coordinate) },
      })
      if (error) throw error
      return data
    },
    onSuccess: (e) => {
      if (e.tolte > 0) toast.success(t('interventions.deviceLink.forgotten', { n: e.tolte }))
      if (e.tornate > 0) toast.info(t('interventions.deviceLink.filesBack', { n: e.tornate }))
      void queryClient.invalidateQueries({ queryKey: CHIAVE })
    },
    onError: () => toast.error(t('interventions.deviceLink.forgetFailed')),
  })

  if (isLoading || !stato) return null

  const daRifare = stato.da_ricalcolare
  const senzaFile = stato.senza_file
  const nonRic = stato.non_riconoscibili
  const maiFatto = !stato.iniziato && !stato.in_corso
  const nienteDaFare = !maiFatto && !stato.in_corso
    && daRifare.length === 0 && senzaFile.length === 0 && nonRic.length === 0

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[12.5px] text-muted-foreground">
        {t('interventions.deviceLink.explanation')}
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => avvia.mutate()} disabled={stato.in_corso}>
          {stato.in_corso ? <Loader2 className="size-3.5 animate-spin" /> : <Activity className="size-3.5" />}
          {stato.in_corso ? t('interventions.deviceLink.running') : t('interventions.deviceLink.check')}
        </Button>
        {stato.in_corso && (
          <span className="text-[12px] text-muted-foreground tabular-nums">
            {t('interventions.deviceLink.progress', {
              n: stato.fatti, total: stato.totale,
              library: stato.biblioteca ?? '—',
            })}
          </span>
        )}
        {!stato.in_corso && stato.finito && (
          <span className="text-[12px] text-muted-foreground">
            {t('interventions.deviceLink.lastRun', {
              when: new Date(stato.finito + 'Z').toLocaleString(),
            })}
          </span>
        )}
      </div>

      {maiFatto && (
        <p className="text-[12.5px] text-muted-foreground">
          {t('interventions.deviceLink.neverRun')}
        </p>
      )}

      {nienteDaFare && (
        <p className="text-[12.5px] text-[var(--positive,inherit)]">
          {t('interventions.deviceLink.allWell')}
        </p>
      )}

      {stato.biblioteche_illeggibili.length > 0 && (
        <div className="flex items-start gap-2 rounded-md border border-border bg-muted/40 p-2.5">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-[var(--warning)]" />
          <p className="text-[12px] text-muted-foreground">
            {t('interventions.deviceLink.unreadableLibraries', {
              libraries: stato.biblioteche_illeggibili.join(', '),
            })}
          </p>
        </div>
      )}

      {/* 1. Le impronte da rifare: la riparazione sicura. */}
      {daRifare.length > 0 && (
        <section className="flex flex-col gap-2 rounded-md border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-[13px] font-medium">
              {t('interventions.deviceLink.stale.title', { n: daRifare.length })}
            </h3>
            {conferma === 'rifai' ? (
              <div className="flex items-center gap-1.5">
                <span className="text-[12px] text-muted-foreground">
                  {t('interventions.deviceLink.stale.confirm', { n: daRifare.length })}
                </span>
                <Button size="sm" disabled={rifai.isPending}
                  onClick={() => { setConferma(null); rifai.mutate(daRifare) }}>
                  {rifai.isPending ? <Loader2 className="size-3.5 animate-spin" /> : null}
                  {t('common.confirm')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConferma(null)}>
                  {t('common.cancel')}
                </Button>
              </div>
            ) : (
              <Button size="sm" variant="outline" onClick={() => setConferma('rifai')}>
                <RefreshCw className="size-3.5" />
                {t('interventions.deviceLink.stale.action')}
              </Button>
            )}
          </div>
          <p className="text-[12px] text-muted-foreground">
            {t('interventions.deviceLink.stale.explain')}
          </p>
          <ul className="flex flex-col gap-1">
            {daRifare.slice(0, 20).map((v) => (
              <li key={`${v.library}-${v.calibre_book_id}-${v.format}`}
                className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
                <span className="font-medium">{v.title || t('interventions.deviceLink.noTitle')}</span>
                <span className="text-[11px] text-muted-foreground">
                  {v.library} · {v.format} · #{v.calibre_book_id}
                </span>
                {/* Un'impronta «verificata» che sbaglia è peggio di una
                    forzata a mano da un accoppiamento: quella è imprecisa
                    per scelta, questa dichiara una certezza che non ha. */}
                {v.verified && (
                  <span className="text-[11px] text-[var(--warning)]">
                    {t('interventions.deviceLink.stale.claimedVerified')}
                  </span>
                )}
              </li>
            ))}
            {daRifare.length > 20 && (
              <li className="text-[11px] text-muted-foreground">
                {t('interventions.deviceLink.andMore', { n: daRifare.length - 20 })}
              </li>
            )}
          </ul>
        </section>
      )}

      {/* 2. Quello che NON si ripara da qui, e si dice perché. */}
      {nonRic.length > 0 && (
        <section className="flex flex-col gap-2 rounded-md border border-border p-3">
          <h3 className="text-[13px] font-medium">
            {t('interventions.deviceLink.unresolved.title', { n: nonRic.length })}
          </h3>
          <p className="text-[12px] text-muted-foreground">
            {t('interventions.deviceLink.unresolved.explain')}
          </p>
          <ul className="flex flex-col gap-1">
            {nonRic.slice(0, 20).map((v) => (
              <li key={v.id} className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
                <span className="font-medium">{v.device_name || `#${v.id}`}</span>
                <span className="text-[11px] text-muted-foreground">
                  {v.device_path || `${v.library} · #${v.calibre_book_id}`}
                </span>
                <span className={v.ha_identita ? 'text-[11px] text-muted-foreground' : 'text-[11px] text-[var(--warning)]'}>
                  {v.ha_identita
                    ? t('interventions.deviceLink.unresolved.hasIdentity')
                    : t('interventions.deviceLink.unresolved.noIdentity')}
                </span>
              </li>
            ))}
            {nonRic.length > 20 && (
              <li className="text-[11px] text-muted-foreground">
                {t('interventions.deviceLink.andMore', { n: nonRic.length - 20 })}
              </li>
            )}
          </ul>
        </section>
      )}

      {/* 3. Le righe che parlano di file che non ci sono. */}
      {senzaFile.length > 0 && (
        <section className="flex flex-col gap-2 rounded-md border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-[13px] font-medium">
              {t('interventions.deviceLink.missing.title', { n: senzaFile.length })}
            </h3>
            {conferma === 'dimentica' ? (
              <div className="flex items-center gap-1.5">
                <span className="text-[12px] text-muted-foreground">
                  {t('interventions.deviceLink.missing.confirm', { n: senzaFile.length })}
                </span>
                <Button size="sm" disabled={dimentica.isPending}
                  onClick={() => { setConferma(null); dimentica.mutate(senzaFile) }}>
                  {dimentica.isPending ? <Loader2 className="size-3.5 animate-spin" /> : null}
                  {t('common.confirm')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConferma(null)}>
                  {t('common.cancel')}
                </Button>
              </div>
            ) : (
              <Button size="sm" variant="outline" onClick={() => setConferma('dimentica')}>
                <Trash2 className="size-3.5" />
                {t('interventions.deviceLink.missing.action')}
              </Button>
            )}
          </div>
          <p className="text-[12px] text-muted-foreground">
            {t('interventions.deviceLink.missing.explain')}
          </p>
          <ul className="flex flex-col gap-1">
            {senzaFile.slice(0, 20).map((v) => (
              <li key={`${v.library}-${v.calibre_book_id}-${v.format}`}
                className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
                <span className="font-medium">{v.title || t('interventions.deviceLink.noTitle')}</span>
                <span className="text-[11px] text-muted-foreground">
                  {v.library} · {v.format} · #{v.calibre_book_id}
                </span>
                {!v.in_biblioteca && (
                  <span className="text-[11px] text-muted-foreground">
                    {t('interventions.deviceLink.missing.notInLibrary')}
                  </span>
                )}
              </li>
            ))}
            {senzaFile.length > 20 && (
              <li className="text-[11px] text-muted-foreground">
                {t('interventions.deviceLink.andMore', { n: senzaFile.length - 20 })}
              </li>
            )}
          </ul>
        </section>
      )}
    </div>
  )
}
