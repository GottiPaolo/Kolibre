import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { createLibrary, errorDetail } from '@/lib/librarySettingsActions'
import { useLingua } from '@/lib/i18n'

interface CreateLibraryDialogProps {
  onClose: () => void
}

// Porting di showAddLibraryPrompt/createNewLibrary in frontend/src/App.vue
// (righe ~3325-3355, ~7968-7989). Il modale originale offriva anche una
// scelta di icona (allowedIconChoices/newLibraryEmoji) — omessa qui: GET
// /api/kolibre/libraries (backend/app/api/libraries.py::list_libraries)
// calcola l'icona SOLO dalla posizione in ordine ("library" se prima
// libreria, "archive" per tutte le altre) e non esiste alcun campo `icon` a
// livello di modello/endpoint di creazione — la scelta dell'utente nel Vue
// esistente non veniva mai inviata al backend e si perdeva al primo reload
// (verificato: create_library legge solo `name` dal payload). Riproporla
// qui sarebbe un controllo che sembra funzionare ma non fa nulla; vedi il
// report della fase per la stessa scelta fatta sul modale di modifica.
export function CreateLibraryDialog({ onClose }: CreateLibraryDialogProps) {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCreate() {
    if (!name.trim()) return
    setSaving(true)
    setError(null)
    try {
      await createLibrary(name.trim())
      await queryClient.invalidateQueries({ queryKey: ['libraries'] })
      onClose()
    } catch (err) {
      setError(errorDetail(err, t('settings.libraries.create.error')))
      setSaving(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('settings.libraries.create.title')}</DialogTitle>
        </DialogHeader>

        <label className="flex flex-col gap-1 text-[11px] font-medium text-muted-foreground">
          {t('settings.libraries.create.nameLabel')}
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('settings.libraries.create.namePlaceholder')}
            autoFocus
            className="rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] text-foreground outline-none focus:border-primary"
          />
        </label>

        {error && <p className="text-[12.5px] text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => void handleCreate()} disabled={saving || !name.trim()}>
            {saving ? t('settings.libraries.create.creating') : t('settings.libraries.create.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
