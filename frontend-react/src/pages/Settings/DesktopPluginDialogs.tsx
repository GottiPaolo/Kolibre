import { useEffect, useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import {
  downloadCalibrePlugin,
  downloadObsidianPlugin,
  fetchCurrentUsername,
  guessBackendPort,
  guessFrontendPort,
  guessPluginServerUrl,
} from '@/lib/pluginDownloadActions'
import { useLingua } from '@/lib/i18n'

interface CloseableProps {
  onClose: () => void
}

// Porting di calibrePluginDownloadOpen/confirmDownloadCalibrePlugin in
// frontend/src/App.vue (modale righe ~3279-3304, azione ~6450-6479).
export function CalibrePluginDialog({ onClose }: CloseableProps) {
  const { t } = useLingua()
  const [host, setHost] = useState(window.location.hostname)
  const [backendPort, setBackendPort] = useState('')
  const [frontendPort, setFrontendPort] = useState('')
  const [username, setUsername] = useState('')
  const [ready, setReady] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    Promise.all([guessBackendPort(), guessFrontendPort(), fetchCurrentUsername()]).then(([backend, frontend, user]) => {
      if (!mounted) return
      setBackendPort(String(backend))
      setFrontendPort(String(frontend))
      setUsername(user)
      setReady(true)
    })
    return () => {
      mounted = false
    }
  }, [])

  async function handleDownload() {
    if (!host.trim() || !backendPort.trim()) return
    setDownloading(true)
    setError(null)
    try {
      await downloadCalibrePlugin(host.trim(), backendPort.trim(), frontendPort.trim(), username)
      onClose()
    } catch {
      setError(t('settings.plugins.downloadError'))
      setDownloading(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('settings.integrations.calibre.title')}</DialogTitle>
        </DialogHeader>

        <p className="text-[12.5px] text-muted-foreground">{t('settings.integrations.calibre.description')}</p>

        <div className="flex gap-2">
          <label className="flex flex-1 flex-col gap-1 text-[11px] font-medium text-muted-foreground">
            {t('settings.integrations.calibre.hostLabel')}
            <input
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="192.168.1.10"
              disabled={!ready}
              className="rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
            />
          </label>
          <label className="flex w-24 flex-col gap-1 text-[11px] font-medium text-muted-foreground">
            {t('settings.integrations.calibre.backendPortLabel')}
            <input
              value={backendPort}
              onChange={(e) => setBackendPort(e.target.value)}
              placeholder="8081"
              disabled={!ready}
              className="rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
            />
          </label>
          <label className="flex w-24 flex-col gap-1 text-[11px] font-medium text-muted-foreground">
            {t('settings.integrations.calibre.frontendPortLabel')}
            <input
              value={frontendPort}
              onChange={(e) => setFrontendPort(e.target.value)}
              placeholder="8080"
              disabled={!ready}
              className="rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
            />
          </label>
        </div>

        {error && <p className="text-[12.5px] text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => void handleDownload()} disabled={downloading || !host.trim() || !backendPort.trim()}>
            {downloading ? t('settings.plugins.downloading') : t('settings.plugins.download')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// Porting di obsidianPluginDownloadOpen/confirmDownloadObsidianPlugin in
// frontend/src/App.vue (modale righe ~3307-3322, azione ~6483-6501).
export function ObsidianPluginDialog({ onClose }: CloseableProps) {
  const { t } = useLingua()
  const [serverUrl, setServerUrl] = useState('')
  const [username, setUsername] = useState('')
  const [ready, setReady] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    Promise.all([guessPluginServerUrl(), fetchCurrentUsername()]).then(([url, user]) => {
      if (!mounted) return
      setServerUrl(url)
      setUsername(user)
      setReady(true)
    })
    return () => {
      mounted = false
    }
  }, [])

  async function handleDownload() {
    if (!serverUrl.trim()) return
    setDownloading(true)
    setError(null)
    try {
      await downloadObsidianPlugin(serverUrl.trim(), username)
      onClose()
    } catch {
      setError(t('settings.plugins.downloadError'))
      setDownloading(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('settings.integrations.obsidian.title')}</DialogTitle>
        </DialogHeader>

        <p className="text-[12.5px] text-muted-foreground">{t('settings.integrations.obsidian.description')}</p>

        <label className="flex flex-col gap-1 text-[11px] font-medium text-muted-foreground">
          {t('settings.integrations.obsidian.urlLabel')}
          <input
            value={serverUrl}
            onChange={(e) => setServerUrl(e.target.value)}
            placeholder="http://192.168.1.10:8081"
            disabled={!ready}
            className="rounded-md border border-border bg-background px-2.5 py-1.5 font-mono text-[12.5px] text-foreground outline-none focus:border-primary"
          />
        </label>

        {error && <p className="text-[12.5px] text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => void handleDownload()} disabled={downloading || !serverUrl.trim()}>
            {downloading ? t('settings.plugins.downloading') : t('settings.plugins.download')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
