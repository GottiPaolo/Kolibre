import { useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { MODEL_OPTIONS } from './AddDeviceDialog'
import type { Device } from '@/types/device'
import { useDeviceBackups } from '@/lib/deviceQueries'
import { deleteDeviceApi, setDefaultDevice, updateDevice } from '@/lib/deviceActions'
import { useLingua } from '@/lib/i18n'

interface DeviceEditDialogProps {
  device: Device
  onClose: () => void
  onDeleted: () => void
}

// Modale unica "Modifica dispositivo" — porting di showDeviceEditModal nel
// Vue esistente (frontend/src/App.vue, righe 3707-3810: nome, predefinito,
// folder_layout, delete_policy, write_folder_cover, elenco backup,
// eliminazione). Decisione di scope: "Priorità Formati di Invio"
// (editingDevice.supported_formats + shiftDeviceFormat) NON è portata — vedi
// il report finale: DeviceUpdate non ha un campo supported_formats
// (verificato in backend/app/schemas.py), quindi ogni riordino impostato lì
// nel Vue viene perso al primo refresh (list_devices restituisce sempre la
// stessa lista fissa hardcoded) ed è comunque letto SOLO dal flusso "Invia al
// dispositivo" della Libreria, fuori da questa pagina. Riproporre un
// controllo che sembra persistente ma non lo è sarebbe stato peggio che
// ometterlo.
export function DeviceEditDialog({ device, onClose, onDeleted }: DeviceEditDialogProps) {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: backups = [] } = useDeviceBackups(device.id, true)

  const [name, setName] = useState(device.name)
  // Il modello si sbaglia alla registrazione piu' spesso del nome — in uso
  // reale si trovano Mac registrati come "Android Tablet" perche' all'epoca
  // non c'era altro da scegliere — e finora non c'era modo di correggerlo.
  const [model, setModel] = useState(device.model || '')
  const modelloFuoriElenco = !!model && !MODEL_OPTIONS.includes(model)
  const [isDefault, setIsDefault] = useState(device.is_default)
  const [folderLayout, setFolderLayout] = useState(device.folder_layout || 'author')
  const [deletePolicy, setDeletePolicy] = useState(device.delete_policy || 'ask')
  const [writeFolderCover, setWriteFolderCover] = useState(device.write_folder_cover)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['devices'] })
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      await updateDevice(device.id, {
        name,
        model: model.trim() || undefined,
        folder_layout: folderLayout,
        write_folder_cover: writeFolderCover,
        delete_policy: deletePolicy,
      })
      // La spunta "predefinito" non è un campo di DeviceUpdate — si applica
      // solo passando da falso a vero, tramite l'endpoint /set-default
      // dedicato (stesso comportamento — incluso il limite: togliere la
      // spunta a un dispositivo già predefinito non ha alcun effetto, non
      // esiste un modo di "nessun dispositivo predefinito" — del Vue
      // esistente, saveDeviceDetails).
      if (isDefault && !device.is_default) {
        await setDefaultDevice(device.id)
      }
      invalidate()
      onClose()
    } catch {
      setError(t('devices.edit.saveError'))
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!window.confirm(t('devices.edit.confirmDelete', { name: device.name }))) {
      return
    }
    setDeleting(true)
    try {
      await deleteDeviceApi(device.id)
      invalidate()
      onDeleted()
    } catch {
      setError(t('devices.edit.deleteError'))
      setDeleting(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[85vh] max-w-md flex-col overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('devices.edit.title', { name: device.name })}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3.5">
          <Field label={t('devices.field.name')}>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
            />
          </Field>

          <Field label={t('devices.edit.modelLabel')} hint={t('devices.edit.modelHint')}>
            <Select value={modelloFuoriElenco ? '__altro__' : model} onValueChange={(v) => setModel(v === '__altro__' ? '' : v)}>
              <SelectTrigger>
                <SelectValue placeholder={t('devices.edit.modelPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {MODEL_OPTIONS.map((m) => (
                  <SelectItem key={m} value={m}>{m}</SelectItem>
                ))}
                <SelectItem value="__altro__">{t('devices.edit.modelOtherOption')}</SelectItem>
              </SelectContent>
            </Select>
            {(modelloFuoriElenco || model === '') && (
              <input
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={t('devices.edit.modelCustomPlaceholder')}
                className="mt-1.5 w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
              />
            )}
          </Field>

          <label className="flex items-center gap-2 text-[13px] font-medium">
            <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
            {t('devices.edit.setDefaultLabel')}
          </label>

          <Field
            label={t('devices.edit.folderLayoutLabel')}
            hint={t('devices.edit.folderLayoutHint')}
          >
            <Select value={folderLayout} onValueChange={setFolderLayout}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="author">{t('devices.edit.folderLayoutAuthor')}</SelectItem>
                <SelectItem value="flat">{t('devices.edit.folderLayoutFlat')}</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field
            label={t('devices.edit.deletePolicyLabel')}
            hint={t('devices.edit.deletePolicyHint')}
          >
            <Select value={deletePolicy} onValueChange={setDeletePolicy}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">{t('devices.deletePolicy.auto')}</SelectItem>
                <SelectItem value="ask">{t('devices.edit.deletePolicyAskOnDevice')}</SelectItem>
                <SelectItem value="never">{t('devices.deletePolicy.never')}</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <label className="flex items-center gap-2 text-[13px] font-medium">
            <input type="checkbox" checked={writeFolderCover} onChange={(e) => setWriteFolderCover(e.target.checked)} />
            {t('devices.edit.writeFolderCoverLabel')}
          </label>

          <div>
            <div className="mb-1.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
              {t('devices.edit.backupsHeading')}
            </div>
            {backups.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">{t('devices.edit.noBackupsYet')}</p>
            ) : (
              <div className="flex flex-col gap-1">
                {backups.map((b) => (
                  <div
                    key={b.filename}
                    className="flex items-center justify-between rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-[12px]"
                  >
                    <span className="font-mono">{b.filename}</span>
                    <span className="text-muted-foreground">
                      {Math.round(b.size / 1024)} KB · {b.modified_at.slice(0, 16).replace('T', ' ')}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {error && <p className="text-[12px] text-destructive">{error}</p>}
        </div>

        <DialogFooter className="justify-between sm:justify-between">
          <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
            {deleting ? t('devices.edit.deleting') : t('devices.edit.deleteButton')}
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? t('devices.edit.saving') : t('devices.edit.saveButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{label}</div>
      {hint && <p className="mb-1.5 text-[11px] text-muted-foreground">{hint}</p>}
      {children}
    </div>
  )
}
