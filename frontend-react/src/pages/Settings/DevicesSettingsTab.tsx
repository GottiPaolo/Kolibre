import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Check, Copy, Download, Loader2, RefreshCw, Smartphone } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  SettingsFeedback,
  SettingsHint,
  SettingsList,
  SettingsListRow,
  SettingsPill,
  SettingsRow,
  SettingsSection,
  SettingsToggle,
} from '@/components/settings/SettingsPrimitives'
import { useDevices } from '@/lib/deviceQueries'
import { api } from '@/lib/api'
import { errorDetail } from '@/lib/librarySettingsActions'
import {
  getOpdsFeedEnabled,
  getWebReaderTracking,
  setOpdsFeedEnabled,
  setWebReaderTracking,
} from '@/lib/opdsSettingsActions'
import { guessPluginServerUrl } from '@/lib/pluginDownloadActions'
import type { Device } from '@/types/device'
import { KoreaderPluginDialog } from './KoreaderPluginDialog'
import { useLingua } from '@/lib/i18n'

// Impostazioni ▸ Dispositivi: solo ciò che è configurazione — il plugin
// KOReader da scaricare per un dispositivo, il ricalcolo delle statistiche e
// il feed OPDS.
//
// Decisione di scope (porting di settingsActiveTab === 'devices' in
// frontend/src/App.vue): la tab del vecchio Vue era in gran parte una SECONDA
// lista dispositivi (nome, modello, ultima sync, backup, formati) — dati che
// la pagina Dispositivi già migrata (pages/Devices/DevicesPage.tsx e
// DeviceDetailPage.tsx) mostra in modo più ricco e con azioni reali.
// Duplicarla qui pari pari avrebbe significato due liste dispositivi diverse
// nella stessa app, una delle quali sempre "indietro": da qui il rimando a
// quella pagina invece della copia.
export function DevicesSettingsTab() {
  const { t } = useLingua()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: devices = [], isLoading } = useDevices()
  const [pluginDevice, setPluginDevice] = useState<Device | null>(null)
  const [recomputing, setRecomputing] = useState(false)
  // Sotto quanti secondi una sessione non conta. Zero = nessun filtro.
  const [soglia, setSoglia] = useState<number | null>(null)
  const [salvandoSoglia, setSalvandoSoglia] = useState(false)
  const [recomputeMessage, setRecomputeMessage] = useState<string | null>(null)
  const [opdsEnabled, setOpdsEnabledState] = useState<boolean | null>(null)
  const [opdsSaveError, setOpdsSaveError] = useState(false)
  const [opdsCopied, setOpdsCopied] = useState(false)
  const [opdsFeedUrl, setOpdsFeedUrl] = useState<string | null>(null)

  useEffect(() => {
    getOpdsFeedEnabled()
      .then(setOpdsEnabledState)
      .catch(() => setOpdsEnabledState(false))
    // Il feed vive sul backend (BACKEND_PORT), non sull'origine della pagina:
    // in produzione il frontend è servito da nginx su una porta diversa
    // (frontend-react/nginx.conf non fa da reverse proxy verso il backend),
    // quindi window.location.origin sarebbe l'indirizzo sbagliato — stesso
    // problema/stessa soluzione già usata per il download del plugin
    // KOReader (guessPluginServerUrl, risolve la porta reale via
    // /api/tools/server-port).
    guessPluginServerUrl()
      .then(setOpdsFeedUrl)
      .catch(() => setOpdsFeedUrl(window.location.origin))
  }, [])

  async function toggleOpdsFeed(enabled: boolean) {
    setOpdsEnabledState(enabled)
    setOpdsSaveError(false)
    try {
      await setOpdsFeedEnabled(enabled)
    } catch {
      setOpdsEnabledState(!enabled)
      setOpdsSaveError(true)
    }
  }

  function handleCopyOpdsUrl() {
    if (!opdsFeedUrl) return
    navigator.clipboard.writeText(`${opdsFeedUrl}/opds`).then(() => {
      setOpdsCopied(true)
      setTimeout(() => setOpdsCopied(false), 2000)
    })
  }

  // Il refresh statistiche di fondo (main.py::_refresh_stats_loop) gira solo
  // all'avvio del server e poi ogni 24h — un rescan/ricalcolo hash che
  // risolve libri prima orfani non fa ripartire da sola la rilettura dei
  // backup già salvati. Senza riavviare il server o rifare un backup dal
  // dispositivo, l'utente resta a guardare statistiche mancanti per un
  // giorno intero senza nessun modo per forzarlo — questo bottone espone
  // esattamente quello che fa il loop di fondo, a comando.
  async function handleRecomputeStats() {
    setRecomputing(true)
    setRecomputeMessage(null)
    try {
      const { data, error } = await api.POST('/api/kolibre/stats/recompute', {})
      if (error) throw error
      const result = data as unknown as { devices_processed: number; sessions_added: number; libraries_refreshed: number }
      // Chiavi separate ('stats-summary'/'stats-raw'/'stats-timeline', vedi
      // statsQueries.ts) — 'stats' da solo non le invaliderebbe, il match a
      // prefisso di React Query è per elemento d'array, non per sottostringa.
      await queryClient.invalidateQueries({ predicate: (q) => typeof q.queryKey[0] === 'string' && q.queryKey[0].startsWith('stats-') })
      setRecomputeMessage(
        t('settings.devices.stats.recomputeSuccess', {
          added: result.sessions_added,
          devices: result.devices_processed,
          libraries: result.libraries_refreshed,
        })
      )
    } catch (err) {
      // NON "errore di rete" e basta: questo catch prende anche le risposte
      // non-2xx del server (poco sopra c'e' `throw error`), e chiamare
      // "rete" un 500 manda a cercare il problema dalla parte sbagliata —
      // successo davvero, con mezz'ora persa a indagare la connessione.
      setRecomputeMessage(errorDetail(err, t('settings.devices.stats.recomputeError')))
    } finally {
      setRecomputing(false)
    }
  }

  // null finché il backend non risponde: un interruttore che parte spento e
  // poi salta su da solo e' peggio di uno che compare un istante dopo.
  const [webReaderTracking, setWebReaderTrackingState] = useState<boolean | null>(null)
  const [webReaderError, setWebReaderError] = useState(false)

  useEffect(() => {
    // Se la richiesta fallisce si mostra SPENTO, che e' anche il predefinito
    // del server: nel dubbio, un interruttore che raccoglie dati non va
    // disegnato acceso. Prima il ripiego era `true`, cioe' la vecchia
    // preimpostazione scritta a mano in un secondo posto.
    getWebReaderTracking().then(setWebReaderTrackingState).catch(() => setWebReaderTrackingState(false))
  }, [])

  useEffect(() => {
    api
      .GET('/api/kolibre/settings/stats-session-threshold', {})
      .then(({ data }) => setSoglia((data as unknown as { seconds: number })?.seconds ?? 0))
      .catch(() => setSoglia(0))
  }, [])

  async function salvaSoglia(secondi: number) {
    setSoglia(secondi)
    setSalvandoSoglia(true)
    try {
      await api.PUT('/api/kolibre/settings/stats-session-threshold', { body: { seconds: secondi } })
      // I numeri del cruscotto vengono da una cache che il server ha appena
      // rifatto: senza questo resterebbero quelli di prima.
      queryClient.invalidateQueries({ queryKey: ['stats-summary'] })
      queryClient.invalidateQueries({ queryKey: ['stats-raw'] })
      queryClient.invalidateQueries({ queryKey: ['stats-timeline'] })
    } catch {
      // Silenzioso: il valore mostrato resta quello scelto, e riaprendo la
      // pagina si vede quello vero.
    }
    setSalvandoSoglia(false)
  }

  async function toggleWebReaderTracking(enabled: boolean) {
    const precedente = webReaderTracking
    setWebReaderTrackingState(enabled)
    setWebReaderError(false)
    try {
      await setWebReaderTracking(enabled)
    } catch {
      setWebReaderTrackingState(precedente)
      setWebReaderError(true)
    }
  }

  // L'esito del ricalcolo è un unico messaggio di testo: qui serve solo per
  // colorarlo come errore invece che come conferma.
  const recomputeFailed = recomputeMessage === t('settings.devices.stats.networkErrorLegacy')

  return (
    <>
      <SettingsSection
        label={t('settings.devices.webReader.label')}
        description={t('settings.devices.webReader.description')}
      >
        <SettingsRow
          name={t('settings.devices.webReader.rowName')}
          description={
            webReaderTracking === false
              ? t('settings.devices.webReader.excludedDescription')
              : t('settings.devices.webReader.includedDescription')
          }
        >
          <SettingsToggle
            label={t('settings.devices.webReader.toggleLabel')}
            checked={webReaderTracking ?? true}
            onChange={(next) => void toggleWebReaderTracking(next)}
          />
        </SettingsRow>
        {webReaderError && (
          <SettingsFeedback kind="error">{t('settings.devices.webReader.saveError')}</SettingsFeedback>
        )}
      </SettingsSection>

      <SettingsSection
        label={t('settings.devices.plugin.label')}
        description={t('settings.devices.plugin.description')}
      >
        {isLoading && <p className="py-3 text-[12.5px] text-muted-foreground">{t('common.loading')}</p>}

        {!isLoading && devices.length === 0 && (
          <p className="py-3 text-[12.5px] text-muted-foreground">{t('settings.devices.plugin.empty')}</p>
        )}

        {devices.length > 0 && (
          <SettingsList className="mt-3">
            {devices.map((d) => (
              <SettingsListRow key={d.id}>
                <div className="flex min-w-0 items-center gap-3">
                  <Smartphone className="size-4 shrink-0 text-primary" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-medium">{d.name}</span>
                      {d.plugin_version && (
                        <SettingsPill tone="ok">
                          {t('settings.devices.plugin.versionPill', { version: d.plugin_version })}
                        </SettingsPill>
                      )}
                    </div>
                    <div className="mt-1 text-[11.5px] text-muted-foreground">
                      {d.model || t('settings.devices.plugin.noModel')}
                    </div>
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={() => setPluginDevice(d)}>
                  <Download className="size-3.5" /> {t('settings.devices.plugin.download')}
                </Button>
              </SettingsListRow>
            ))}
          </SettingsList>
        )}

        <SettingsRow
          name={t('settings.devices.plugin.manageName')}
          description={t('settings.devices.plugin.manageDescription')}
          last
        >
          <Button variant="outline" size="sm" onClick={() => navigate('/dispositivi')}>
            {t('settings.devices.plugin.goToDevices')} <ArrowRight className="size-3.5" />
          </Button>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection label={t('settings.devices.stats.label')}>
        <SettingsRow
          name={t('settings.devices.stats.recomputeName')}
          description={t('settings.devices.stats.recomputeDescription')}
          last
        >
          <Button variant="outline" size="sm" onClick={() => void handleRecomputeStats()} disabled={recomputing}>
            {recomputing ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
            {t('settings.bulkOperations.recalculate')}
          </Button>
        </SettingsRow>

        {recomputeMessage && (
          <SettingsFeedback kind={recomputeFailed ? 'error' : 'ok'}>{recomputeMessage}</SettingsFeedback>
        )}

        <SettingsRow
          name={t('settings.devices.stats.ignoreShorterName')}
          description={t('settings.devices.stats.ignoreShorterDescription')}
        >
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={0}
              max={3600}
              step={10}
              value={soglia ?? 0}
              onChange={(e) => setSoglia(Number(e.target.value))}
              onBlur={(e) => void salvaSoglia(Number(e.target.value))}
              className="w-20 rounded-md border border-border bg-background px-2 py-1 text-[13px] tabular-nums outline-none focus:border-primary"
            />
            <span className="text-[12px] text-muted-foreground">
              {t('settings.devices.stats.secondsLabel')}
              {salvandoSoglia ? t('settings.devices.stats.saving') : ''}
            </span>
          </div>
        </SettingsRow>

        <SettingsHint>{t('settings.devices.stats.hint')}</SettingsHint>
      </SettingsSection>

      <SettingsSection label={t('settings.devices.opds.label')}>
        {opdsEnabled === null ? (
          <p className="py-3 text-[12.5px] text-muted-foreground">{t('common.loading')}</p>
        ) : (
          <>
            <SettingsRow
              name={t('settings.devices.opds.feedName')}
              description={t('settings.devices.opds.feedDescription')}
              last={!opdsEnabled}
            >
              <SettingsToggle
                label={t('settings.devices.opds.toggleLabel')}
                checked={opdsEnabled}
                onChange={(v) => void toggleOpdsFeed(v)}
              />
            </SettingsRow>

            {opdsSaveError && <SettingsFeedback kind="error">{t('settings.devices.opds.saveError')}</SettingsFeedback>}

            {opdsEnabled && (
              <SettingsRow
                name={t('settings.devices.opds.addressName')}
                description={t('settings.devices.opds.addressDescription')}
                stack
                last
              >
                <div className="flex w-full items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px]">
                    {opdsFeedUrl ? `${opdsFeedUrl}/opds` : t('common.loading')}
                  </code>
                  <Button variant="outline" size="sm" onClick={handleCopyOpdsUrl} disabled={!opdsFeedUrl}>
                    {opdsCopied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                    {opdsCopied ? t('settings.devices.opds.copied') : t('settings.devices.opds.copy')}
                  </Button>
                </div>
              </SettingsRow>
            )}
          </>
        )}

        <SettingsHint>{t('settings.devices.opds.hint')}</SettingsHint>
      </SettingsSection>

      {pluginDevice && <KoreaderPluginDialog device={pluginDevice} onClose={() => setPluginDevice(null)} />}
    </>
  )
}
