import { useEffect, useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import type { Device } from '@/types/device'
import { downloadKoreaderPlugin, guessPluginServerUrl } from '@/lib/pluginDownloadActions'
import { useLingua } from '@/lib/i18n'

interface KoreaderPluginDialogProps {
  device: Device
  onClose: () => void
}

// Porting di pluginDownloadDevice/confirmDownloadPlugin in
// frontend/src/App.vue (righe ~6422-6441, modale a righe ~1543/2272): scarica
// lo zip del plugin KOReader (backend/app/api/tools.py::download_koreader_plugin)
// già configurato con il token di QUESTO dispositivo e l'indirizzo del
// server, così l'utente non deve scrivere nulla a mano su KOReader.
export function KoreaderPluginDialog({ device, onClose }: KoreaderPluginDialogProps) {
  const { t } = useLingua()
  const [serverUrl, setServerUrl] = useState('')
  const [loadingGuess, setLoadingGuess] = useState(true)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    guessPluginServerUrl().then((url) => {
      if (mounted) {
        setServerUrl(url)
        setLoadingGuess(false)
      }
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
      await downloadKoreaderPlugin(device.id, serverUrl.trim())
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
          <DialogTitle>{t('settings.koreader.download.title', { name: device.name })}</DialogTitle>
        </DialogHeader>

        <p className="text-[12.5px] text-muted-foreground">{t('settings.koreader.download.description')}</p>

        <label className="flex flex-col gap-1 text-[11px] font-medium text-muted-foreground">
          {t('settings.koreader.download.urlLabel')}
          <input
            value={serverUrl}
            onChange={(e) => setServerUrl(e.target.value)}
            placeholder="http://192.168.1.10:8081"
            disabled={loadingGuess}
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
