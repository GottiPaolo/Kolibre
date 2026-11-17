import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueries } from '@tanstack/react-query'
import { AlertTriangle, BookOpen, Link2, Plus, RefreshCw, Save, Smartphone } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useDevices } from '@/lib/deviceQueries'
import { api } from '@/lib/api'
import { relativeTimeFrom } from '@/lib/deviceFormat'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { cn } from '@/lib/utils'
import { useLingua } from '@/lib/i18n'
import { AddDeviceDialog } from './AddDeviceDialog'
import { CollegaUnClientDialog } from './CollegaUnClient'
import { PatchRiepilogo } from './PatchInfo'
import { VersioneSullaScheda } from './VersionePlugin'
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
  const [showCollega, setShowCollega] = useState(false)

  // Conteggio "da rivedere" per ogni card. Nessun endpoint di lista lo
  // restituisce insieme ai dispositivi (list_devices non lo calcola) — a
  // differenza del Vue esistente, che mostrava questo badge SOLO se quel
  // dispositivo era già stato aperto in questa sessione (deviceFlaggedBooks
  // si popolava esclusivamente dentro openDeviceTab, mai qui), interroghiamo
  // qui /flagged-books per ciascun dispositivo così il conteggio è sempre
  // corretto fin dal primo caricamento — un miglioramento deliberato, non
  // solo un porting 1:1 (vedi il report finale).
  const flaggedQueries = useQueries({
    queries: devices.map((d) => ({
      queryKey: ['device-flagged-books', d.id],
      queryFn: async () => {
        const { data, error } = await api.GET('/api/devices/{device_id}/flagged-books', {
          params: { path: { device_id: d.id } },
        })
        if (error) throw error
        return data
      },
    })),
  })

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end gap-2">
        {/* Un programma non e' un lettore: non si «registra» con un
            modello e un nome, si fa entrare con un invito — un codice usa e
            getta che nasce qui dentro. Dal 17/11/2026 e' la sola strada: non
            esiste piu' nessuna rotta con cui un programma possa chiedere di
            entrare da se'. Vedi `CollegaUnClient.tsx`. */}
        <Button variant="outline" onClick={() => setShowCollega(true)}>
          <Link2 className="size-3.5" /> {t('devices.pairing.button')}
        </Button>
        <Button onClick={() => setShowAdd(true)}>
          <Plus className="size-3.5" /> {t('devices.list.addButton')}
        </Button>
      </div>

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
                  {/* La versione del plugin e le patch, una accanto
                      all'altra: sono la stessa domanda — «che cosa sa fare
                      questo lettore?» — e dal 17/11/2026 stanno tutt'e due
                      qui dentro invece che in un riquadro in cima alla
                      pagina. Vedi `VersionePlugin.tsx`. */}
                  <VersioneSullaScheda device={d} />
                  <PatchRiepilogo device={d} />
                </div>
              </button>
            )
          })}
        </div>
      )}

      {showAdd && <AddDeviceDialog onClose={() => setShowAdd(false)} />}
      {showCollega && <CollegaUnClientDialog onClose={() => setShowCollega(false)} />}
    </div>
  )
}
