import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueries, useQuery } from '@tanstack/react-query'
import { AlertTriangle, BookOpen, Plus, RefreshCw, Save, Smartphone } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useDevices } from '@/lib/deviceQueries'
import { api } from '@/lib/api'
import type { DeviceFlaggedBook } from '@/types/device'
import { relativeTimeFrom } from '@/lib/deviceFormat'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { cn } from '@/lib/utils'
import { useLingua } from '@/lib/i18n'
import { AddDeviceDialog } from './AddDeviceDialog'
import { ListError } from '@/components/ListError'

// Porting di activePage === 'devices' nel Vue esistente (frontend/src/
// App.vue, righe 1291-1320): griglia di card compatte invece della vecchia
// tabella (redesign già presente nel Vue, qui riprodotto direttamente).
export function DevicesPage() {
  const { t } = useLingua()
  useSetPageHeader(t('devices.pageTitle'))
  const navigate = useNavigate()
  const { data: devices = [], isLoading, isError, refetch } = useDevices()
  const [showAdd, setShowAdd] = useState(false)

  // Conteggio "da rivedere" per ogni card. Nessun endpoint di lista lo
  // restituisce insieme ai dispositivi (list_devices non lo calcola) — a
  // differenza del Vue esistente, che mostrava questo badge SOLO se quel
  // dispositivo era già stato aperto in questa sessione (deviceFlaggedBooks
  // si popolava esclusivamente dentro openDeviceTab, mai qui), interroghiamo
  // qui /flagged-books per ciascun dispositivo così il conteggio è sempre
  // corretto fin dal primo caricamento — un miglioramento deliberato, non
  // solo un porting 1:1 (vedi il report finale).
  // Qual è l'ultima versione del plugin, cioè quella che il server
  // distribuisce. Il confronto con quella installata su ciascun dispositivo è
  // l'unico modo per sapere chi è indietro senza andarlo a guardare a mano
  // (29/09/2026). L'endpoint esisteva già: lo usa il plugin stesso per
  // chiedersi se aggiornarsi.
  const { data: ultimaVersione } = useQuery({
    queryKey: ['versione-plugin-koreader'],
    queryFn: async (): Promise<string | null> => {
      const { data, error } = await api.GET('/api/tools/plugins/koreader/version')
      if (error) throw error
      return (data as unknown as { version?: string }).version ?? null
    },
  })
  const indietro = ultimaVersione
    ? devices.filter((d) => d.plugin_version && d.plugin_version !== ultimaVersione)
    : []
  const senzaVersione = devices.filter((d) => !d.plugin_version)

  const flaggedQueries = useQueries({
    queries: devices.map((d) => ({
      queryKey: ['device-flagged-books', d.id],
      queryFn: async () => {
        const { data, error } = await api.GET('/api/devices/{device_id}/flagged-books', {
          params: { path: { device_id: d.id } },
        })
        if (error) throw error
        return data as unknown as DeviceFlaggedBook[]
      },
    })),
  })

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <Button onClick={() => setShowAdd(true)}>
          <Plus className="size-3.5" /> {t('devices.list.addButton')}
        </Button>
      </div>

      {/* Compare SOLO quando c'è qualcosa da dire: un dispositivo indietro, o
          uno di cui non si conosce la versione. Prima c'era anche quando andava
          tutto bene, e diceva «tutti i dispositivi sono aggiornati» — una riga
          che si impara a non leggere, e che occupa esattamente il posto in cui
          deve saltare all'occhio l'avviso vero. Scelta del 02/10/2026. */}
      {!isLoading && devices.length > 0 && ultimaVersione &&
        (indietro.length > 0 || senzaVersione.length > 0) && (
        <div
          className={cn(
            'flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2 text-[12.5px]',
            indietro.length > 0
              ? 'border-[var(--warning)]/40 bg-[var(--warning-soft)]'
              // Versione sconosciuta: è un'incertezza, non un guasto.
              : 'border-border text-muted-foreground'
          )}
        >
          <span>
            {t('devices.list.pluginLatestVersionPrefix')} <b>v{ultimaVersione}</b>
          </span>
          {indietro.length > 0 && (
            <span>
              {t('devices.list.outdatedPrefix')}{' '}
              <b>{indietro.map((d) => `${d.name} (v${d.plugin_version})`).join(', ')}</b> {t('devices.list.outdatedSuffix')}
            </span>
          )}
          {senzaVersione.length > 0 && (
            <span>{t('devices.list.versionUnknownNotice', { count: senzaVersione.length, n: senzaVersione.length })}</span>
          )}
        </div>
      )}

      {isLoading && <p className="text-muted-foreground">{t('common.loading')}</p>}

      {/* L'errore PRIMA del vuoto: senza, una richiesta fallita finiva nel
          ramo "devices.length === 0" e diceva "Nessun dispositivo
          configurato" — indistinguibile dalla verità. */}
      {!isLoading && isError && <ListError what={t('devices.list.errorSubject')} onRetry={() => void refetch()} />}

      {!isLoading && !isError && devices.length === 0 && (
        <div className="rounded-md border border-dashed border-border p-10 text-center text-muted-foreground">
          {t('devices.list.empty')}
        </div>
      )}

      {!isLoading && devices.length > 0 && (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4">
          {devices.map((d, idx) => {
            const flaggedCount = flaggedQueries[idx]?.data?.length ?? 0
            return (
              <button
                key={d.id}
                onClick={() => navigate(`/dispositivi/${d.id}`)}
                className={cn(
                  'flex flex-col gap-3 rounded-md border border-border bg-card p-4 text-left transition-colors hover:border-muted-foreground/50 hover:bg-accent/40',
                  d.is_default && 'border-l-4 border-l-[var(--positive)]'
                )}
              >
                <div className="flex items-center gap-2.5">
                  <Smartphone className={cn('size-4 shrink-0', d.is_default ? 'text-[var(--positive)]' : 'text-primary')} />
                  <span className="font-semibold">{d.name}</span>
                  {d.plugin_version && (
                    <Badge variant="outline" title={t('devices.pluginVersionTitle')}>
                      v{d.plugin_version}
                    </Badge>
                  )}
                  {d.is_default && (
                    <span className="ml-auto shrink-0 text-[10px] font-bold tracking-wide text-[var(--positive)]">
                      {t('devices.badge.default')}
                    </span>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-3 text-[12px] text-muted-foreground">
                  {d.last_seen_at && (
                    <span title={t('devices.lastSeenTitle', { time: d.last_seen_at })}>
                      {t('devices.seenPrefix', { time: relativeTimeFrom(d.last_seen_at, t) })}
                    </span>
                  )}
                  <span className="inline-flex items-center gap-1">
                    <RefreshCw className="size-3" /> {d.last_sync_at || t('devices.never')}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Save className="size-3" /> {d.last_backup_at || t('devices.never')}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <BookOpen className="size-3" /> {t('devices.bookCount', { count: d.books.length, n: d.books.length })}
                  </span>
                  {flaggedCount > 0 && (
                    <span className="inline-flex items-center gap-1 text-[var(--warning)]">
                      <AlertTriangle className="size-3" /> {t('devices.flaggedCount', { n: flaggedCount })}
                    </span>
                  )}
                </div>
              </button>
            )
          })}
        </div>
      )}

      {showAdd && <AddDeviceDialog onClose={() => setShowAdd(false)} />}
    </div>
  )
}
