import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { importLibrary, errorDetail } from '@/lib/librarySettingsActions'
import { useLingua } from '@/lib/i18n'

interface ImportLibraryDialogProps {
  onClose: () => void
}

// Porting di showImportPrompt/verifyAndImportCalibreLibrary in
// frontend/src/App.vue (righe ~3358-3401, ~7990-8014). Import zero-copy
// reale (backend/app/api/libraries.py::import_library crea un symlink verso
// `path`, non copia nulla). Due parti del modale originale sono state
// tolte:
//  - la scelta icona (allowedIconChoices) — stessa ragione di
//    CreateLibraryDialog, l'icona non è mai persistita dal backend;
//  - il "Navigatore Cartelle del Server" (mockSubdirectories/
//    navigateMockPath) — era client-side mock puro: nessun endpoint di
//    filesystem-browsing esiste nel backend (verificato su tutti gli
//    api/*.py), l'elenco di cartelle proposto non rifletteva mai il
//    filesystem reale del server. Qui il percorso è un campo di testo
//    semplice, con un placeholder d'esempio invece di un browser fittizio.
export function ImportLibraryDialog({ onClose }: ImportLibraryDialogProps) {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleImport() {
    if (!name.trim() || !path.trim()) return
    setSaving(true)
    setError(null)
    try {
      await importLibrary(name.trim(), path.trim())
      await queryClient.invalidateQueries({ queryKey: ['libraries'] })
      onClose()
    } catch (err) {
      setError(errorDetail(err, t('settings.libraries.import.error')))
      setSaving(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('settings.libraries.import.title')}</DialogTitle>
        </DialogHeader>

        <p className="text-[12.5px] text-muted-foreground">{t('settings.libraries.import.description')}</p>

        <label className="flex flex-col gap-1 text-[11px] font-medium text-muted-foreground">
          {t('settings.libraries.import.nameLabel')}
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('settings.libraries.import.namePlaceholder')}
            autoFocus
            className="rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] text-foreground outline-none focus:border-primary"
          />
        </label>

        <label className="flex flex-col gap-1 text-[11px] font-medium text-muted-foreground">
          {t('settings.libraries.import.pathLabel')}
          <input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="/dati/CalibreLibrary"
            className="rounded-md border border-border bg-background px-2.5 py-1.5 font-mono text-[12.5px] text-foreground outline-none focus:border-primary"
          />
        </label>

        {error && <p className="text-[12.5px] text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => void handleImport()} disabled={saving || !name.trim() || !path.trim()}>
            {saving ? t('settings.libraries.import.importing') : t('settings.libraries.import.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
