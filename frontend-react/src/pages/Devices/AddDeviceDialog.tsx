import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { registerDevice } from '@/lib/deviceActions'
import { useLingua } from '@/lib/i18n'

// Che cosa E' questo lettore. Elenco allargato il 28/09/2026: c'erano tre
// modelli e "Altro", e mancavano proprio quelli in uso reale — un Boox e un
// computer, che finivano registrati come "Android Tablet" solo perche'
// all'epoca non c'era nient'altro da scegliere.
//
// Esportato perche' lo usa anche la finestra di modifica: il modello si
// sbaglia alla registrazione piu' spesso di quanto si sbagli il nome, e
// finora non c'era modo di correggerlo dopo.
//
// NON tradotto di proposito (vedi STATO_DISPOSITIVO in libraryQuery.ts per lo
// stesso principio): questi testi sono il VALORE letterale che registerDevice/
// updateDevice salvano in device.model sul backend (un campo stringa libero,
// non un codice enum) e che poi viene confrontato qui stesso ('Altro') e in
// DeviceEditDialog (MODEL_OPTIONS.includes(model)) per decidere se mostrare il
// campo "a mano". Tradurli romperebbe quel confronto per ogni dispositivo già
// registrato cambiando lingua, e cambierebbe anche il dato salvato per i
// dispositivi nuovi in modo diverso a seconda della lingua attiva al momento
// della registrazione — vedi il report finale.
export const MODEL_OPTIONS = [
  'KOReader su Amazon Kindle',
  'KOReader su Kobo',
  'KOReader su Onyx Boox',
  'KOReader su PocketBook',
  'KOReader su Android',
  'KOReader su computer (macOS, Linux, Windows)',
  'Altro',
]

interface AddDeviceDialogProps {
  onClose: () => void
}

// Porting di showAddDeviceModal + registeredDeviceToken nel Vue esistente:
// due passaggi nello stesso dialog invece di due modali separati — form di
// registrazione, poi (una volta sola, il token non viene più mostrato)
// il token da copiare nel plugin KOReader.
export function AddDeviceDialog({ onClose }: AddDeviceDialogProps) {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [model, setModel] = useState(MODEL_OPTIONS[0])
  const [customModel, setCustomModel] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [token, setToken] = useState<string | null>(null)

  const isCustomModel = model === 'Altro'
  const effectiveModel = isCustomModel ? customModel.trim() : model

  async function handleRegister() {
    if (!name.trim() || !effectiveModel) return
    setSaving(true)
    setError(null)
    try {
      const created = await registerDevice(name.trim(), effectiveModel)
      queryClient.invalidateQueries({ queryKey: ['devices'] })
      setToken(created.device_token)
    } catch {
      setError(t('devices.add.registerError'))
    } finally {
      setSaving(false)
    }
  }

  if (token) {
    return (
      <Dialog open onOpenChange={(open) => !open && onClose()}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t('devices.add.registeredTitle')}</DialogTitle>
          </DialogHeader>
          <p className="text-[13px] text-muted-foreground">{t('devices.add.tokenInstructions')}</p>
          <input
            readOnly
            value={token}
            onClick={(e) => e.currentTarget.select()}
            className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 font-mono text-[12px] outline-none"
          />
          <DialogFooter>
            <Button onClick={onClose}>{t('devices.add.done')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('devices.add.title')}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-[11px] font-medium text-muted-foreground">
            {t('devices.field.name')}
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('devices.add.namePlaceholder')}
              autoFocus
              className="rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] text-foreground outline-none focus:border-primary"
            />
          </label>
          <label className="flex flex-col gap-1 text-[11px] font-medium text-muted-foreground">
            {t('devices.add.modelLabel')}
            <Select value={model} onValueChange={setModel}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MODEL_OPTIONS.map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          {isCustomModel && (
            <label className="flex flex-col gap-1 text-[11px] font-medium text-muted-foreground">
              {t('devices.add.customModelLabel')}
              <input
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                placeholder={t('devices.add.customModelPlaceholder')}
                autoFocus
                className="rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] text-foreground outline-none focus:border-primary"
              />
            </label>
          )}
          {error && <p className="text-[12px] text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleRegister} disabled={saving || !name.trim() || !effectiveModel}>
            {saving ? t('devices.add.registering') : t('devices.add.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
