import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, GripVertical, Loader2, RotateCcw, Trash2 } from 'lucide-react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCustomColumns } from '@/lib/queries'
import { useFulltextStatus } from '@/lib/fulltextActions'
import { formatBytes } from '@/lib/format'
import { useDevices } from '@/lib/deviceQueries'
import type { CustomColumn, CustomColumnDatatype, Library } from '@/types/library'
import { useQuickviewFieldLayoutBuilder, quickviewFieldDefs, type QuickviewDeviceInfo } from '@/lib/quickviewFieldLayout'
import {
  createCustomColumn,
  deleteCustomColumnFor,
  deleteLibrary,
  errorDetail,
  setLibraryFulltextEnabled,
} from '@/lib/librarySettingsActions'
import { useLingua, type Valori } from '@/lib/i18n'

interface LibraryEditDialogProps {
  library: Library
  onClose: () => void
}

function datatypeOptions(t: (chiave: string, valori?: Valori) => string): { value: CustomColumnDatatype; label: string }[] {
  return [
    { value: 'text', label: t('settings.library.edit.columns.datatype.text') },
    { value: 'float', label: t('settings.library.edit.columns.datatype.number') },
    { value: 'rating', label: t('settings.library.edit.columns.datatype.stars') },
    { value: 'datetime', label: t('settings.library.edit.columns.datatype.date') },
    { value: 'enumeration', label: t('settings.library.edit.columns.datatype.enum') },
  ]
}

// Porting di openLibrarySettings/showLibraryEditModal/libraryEditTab in
// frontend/src/App.vue (righe ~3494-3645, ~6214-6244, ~7443-7585). Il
// modale originale aveva 4 tab (Aspect/Access/Other/Colonne); qui ne
// restano 2, per una ragione precisa spiegata punto per punto nel report
// della fase:
//  - "Aspect" (rinomina libreria + scelta icona) e "Access" (utenti con
//    visibilità sulla libreria) non hanno MAI persistito nulla lato server:
//    saveLibraryDetails nel Vue esistente aggiorna solo lo stato locale
//    `libraries.value[idx]` per nome/icona/visibleUsers, e il commento
//    stesso del backend lo confirma ("name/icon/visibleUsers still only
//    update local state"). list_libraries inoltre calcola SEMPRE icon e
//    visibleUsers lato server (icon dalla posizione, visibleUsers come
//    lista fissa cablata nel codice) — qualunque valore scelto qui veniva
//    silenziosamente sovrascritto al primo reload. Riproporli qui sarebbe
//    UI che finge di fare qualcosa che non fa.
//  - "Other" conteneva solo il toggle full-text — spostato dentro
//    "Generale" qui sotto, è l'UNICA parte di questo modale realmente
//    persistita server-side (PUT /api/kolibre/fulltext/settings).
export function LibraryEditDialog({ library, onClose }: LibraryEditDialogProps) {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: customColumns = [], isLoading: columnsLoading } = useCustomColumns(library.folder_name)
  // Non filtrati per libreria: un dispositivo non appartiene a nessuna
  // libreria in particolare (solo la SUA presenza sui libri lo è) — stessa
  // lista di device usata per le colonne "Su: <nome>" in LibraryPage.tsx.
  const { data: devices = [] } = useDevices()

  const [fulltextEnabled, setFulltextEnabled] = useState(library.fulltextEnabled)
  // Quanto costa e quanto copre l'indice: due numeri che l'endpoint
  // /status dava da sempre e che non leggeva nessuno.
  const { data: statoFulltext } = useFulltextStatus(library.folder_name, fulltextEnabled)
  const [savingFulltext, setSavingFulltext] = useState(false)

  const [newLabel, setNewLabel] = useState('')
  const [newName, setNewName] = useState('')
  const [newDatatype, setNewDatatype] = useState<CustomColumnDatatype>('text')
  const [newEnumValues, setNewEnumValues] = useState(t('settings.library.edit.columns.enumDefaultValues'))
  const [creatingColumn, setCreatingColumn] = useState(false)
  const [deletingLabel, setDeletingLabel] = useState<string | null>(null)
  // Conferma in due passi, come per "Elimina biblioteca" qui sopra. Un solo
  // click sul cestino cancellava la colonna E il suo contenuto per ogni
  // libro della libreria, senza chiedere niente e senza modo di tornare
  // indietro — il pattern giusto era già scritto trenta righe più su.
  const [confirmColumnLabel, setConfirmColumnLabel] = useState<string | null>(null)
  const [columnsMessage, setColumnsMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)

  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deletingLibrary, setDeletingLibrary] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  async function invalidateColumns() {
    await queryClient.invalidateQueries({ queryKey: ['custom-columns', library.folder_name] })
    await queryClient.invalidateQueries({ queryKey: ['books', library.folder_name] })
  }

  async function handleFulltextToggle(next: boolean) {
    setFulltextEnabled(next)
    setSavingFulltext(true)
    try {
      await setLibraryFulltextEnabled(library.folder_name, next)
      await queryClient.invalidateQueries({ queryKey: ['libraries'] })
    } catch {
      setFulltextEnabled(!next)
    } finally {
      setSavingFulltext(false)
    }
  }

  async function handleCreateColumn() {
    const label = newLabel.trim().replace(/^#/, '')
    if (!label || !newName.trim()) {
      setColumnsMessage({ kind: 'error', text: t('settings.library.edit.columns.invalidInput') })
      return
    }
    setCreatingColumn(true)
    setColumnsMessage(null)
    try {
      const enumValues =
        newDatatype === 'enumeration'
          ? newEnumValues
              .split(',')
              .map((v) => v.trim())
              .filter(Boolean)
          : undefined
      await createCustomColumn(library.folder_name, label, newName.trim(), newDatatype, enumValues)
      await invalidateColumns()
      setColumnsMessage({ kind: 'success', text: t('settings.library.edit.columns.created', { label }) })
      setNewLabel('')
      setNewName('')
    } catch (err) {
      setColumnsMessage({ kind: 'error', text: errorDetail(err, t('settings.library.edit.columns.createError')) })
    } finally {
      setCreatingColumn(false)
    }
  }

  async function handleDeleteColumn(label: string) {
    setDeletingLabel(label)
    setColumnsMessage(null)
    try {
      await deleteCustomColumnFor(library.folder_name, label)
      await invalidateColumns()
      setColumnsMessage({ kind: 'success', text: t('settings.library.edit.columns.removed', { label }) })
    } catch (err) {
      setColumnsMessage({ kind: 'error', text: errorDetail(err, t('settings.library.edit.columns.removeError')) })
    } finally {
      setDeletingLabel(null)
      setConfirmColumnLabel(null)
    }
  }

  async function handleDeleteLibrary() {
    setDeletingLibrary(true)
    setDeleteError(null)
    try {
      await deleteLibrary(library.folder_name)
      await queryClient.invalidateQueries({ queryKey: ['libraries'] })
      onClose()
    } catch (err) {
      setDeleteError(errorDetail(err, t('settings.library.edit.delete.error')))
      setDeletingLibrary(false)
    }
  }


  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('settings.library.edit.title', { name: library.name })}</DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="general">
          <TabsList>
            <TabsTrigger value="general">{t('settings.library.edit.tabs.general')}</TabsTrigger>
            <TabsTrigger value="columns">{t('settings.library.edit.tabs.columns')}</TabsTrigger>
            <TabsTrigger value="quickview">{t('settings.library.edit.tabs.quickview')}</TabsTrigger>
          </TabsList>

          <TabsContent value="general" className="flex flex-col gap-3 pt-2">
            <div className="rounded-md border border-border bg-muted/30 p-3 text-[12.5px]">
              <p className="font-medium">{library.name}</p>
              <p className="mt-0.5 font-mono text-[11.5px] text-muted-foreground">{library.path}</p>
            </div>

            <label className="flex items-center gap-2.5 text-[13px]">
              <input
                type="checkbox"
                checked={fulltextEnabled}
                disabled={savingFulltext}
                onChange={(e) => void handleFulltextToggle(e.target.checked)}
                className="size-4 accent-primary"
              />
              {t('settings.library.edit.fulltext.label')}
            </label>
            <p className="pl-6 text-[11.5px] leading-relaxed text-muted-foreground">
              {t('settings.library.edit.fulltext.description')}
            </p>

            {fulltextEnabled && statoFulltext && (
              <p className="pl-6 text-[11.5px] leading-relaxed text-muted-foreground">
                {t('settings.library.edit.fulltext.status.countPrefix')}
                <b className="tabular-nums text-foreground">{statoFulltext.indexed}</b>
                {t('settings.library.edit.fulltext.status.booksOfSuffix')}
                <b className="tabular-nums text-foreground">{statoFulltext.total}</b>
                {t('settings.library.edit.fulltext.status.forSuffix')}
                <b className="tabular-nums text-foreground">{formatBytes(statoFulltext.size_bytes)}</b>
                {statoFulltext.limit_gb > 0 && (
                  <>{t('settings.library.edit.fulltext.status.availableSuffix', { gb: statoFulltext.limit_gb })}</>
                )}
                .
                {statoFulltext.limit_reached && (
                  <span className="text-[var(--warning)]">
                    {' '}
                    {t('settings.library.edit.fulltext.status.limitReached')}
                  </span>
                )}
                {statoFulltext.progress?.running && (
                  <>
                    {' '}
                    {t('settings.library.edit.fulltext.status.indexingProgress', {
                      done: statoFulltext.progress.done,
                      total: statoFulltext.progress.total,
                    })}
                  </>
                )}
              </p>
            )}

            <div className="mt-2 rounded-md border border-destructive/30 bg-destructive/5 p-3">
              <p className="mb-2 text-[12.5px] font-medium text-destructive">{t('settings.library.edit.delete.label')}</p>
              {!confirmDelete ? (
                <Button variant="destructive" size="sm" onClick={() => setConfirmDelete(true)}>
                  <Trash2 className="size-3.5" /> {t('settings.library.edit.delete.button')}
                </Button>
              ) : (
                <div className="flex flex-col gap-2">
                  <p className="flex items-start gap-1.5 text-[12px] text-destructive">
                    <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                    {t('settings.library.edit.delete.confirmText', { name: library.name })}
                  </p>
                  {deleteError && <p className="text-[12px] text-destructive">{deleteError}</p>}
                  <div className="flex gap-2">
                    <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)} disabled={deletingLibrary}>
                      {t('common.cancel')}
                    </Button>
                    <Button variant="destructive" size="sm" onClick={() => void handleDeleteLibrary()} disabled={deletingLibrary}>
                      {deletingLibrary ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
                      {t('settings.library.edit.delete.confirmButton')}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </TabsContent>

          <TabsContent value="columns" className="flex flex-col gap-3 pt-2">
            {columnsLoading && <p className="text-[12.5px] text-muted-foreground">{t('common.loading')}</p>}

            {!columnsLoading && customColumns.length === 0 && (
              <p className="text-[12.5px] text-muted-foreground">{t('settings.library.edit.columns.empty')}</p>
            )}

            {customColumns.length > 0 && (
              <div className="flex max-h-44 flex-col gap-1.5 overflow-y-auto rounded-md border border-border p-2">
                {customColumns.map((col) => (
                  <div key={col.id} className="flex items-center justify-between gap-2 rounded-md px-1.5 py-1 text-[12.5px]">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-medium">#{col.label}</span>
                      <span className="text-muted-foreground">{col.name}</span>
                      <Badge variant="outline">{col.datatype}</Badge>
                    </div>
                    {confirmColumnLabel === col.label ? (
                      <div className="flex items-center gap-1.5">
                        <span className="text-[11.5px] text-destructive">
                          {t('settings.library.edit.columns.confirmDeleteValues')}
                        </span>
                        <Button variant="ghost" size="sm" onClick={() => setConfirmColumnLabel(null)} disabled={deletingLabel === col.label}>
                          {t('common.cancel')}
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => void handleDeleteColumn(col.label)}
                          disabled={deletingLabel === col.label}
                        >
                          {deletingLabel === col.label ? <Loader2 className="size-3 animate-spin" /> : <Trash2 className="size-3" />}
                          {t('settings.library.edit.columns.delete')}
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        className="text-destructive"
                        onClick={() => setConfirmColumnLabel(col.label)}
                        title={t('settings.library.edit.columns.removeTitle')}
                      >
                        <Trash2 className="size-3" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}


            <div className="flex flex-col gap-2 border-t border-border pt-3">
              <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                {t('settings.library.edit.columns.newColumnLabel')}
              </p>
              <div className="flex flex-wrap gap-2">
                <input
                  value={newLabel}
                  onChange={(e) => setNewLabel(e.target.value)}
                  placeholder={t('settings.library.edit.columns.keyPlaceholder')}
                  className="w-24 rounded-md border border-border bg-background px-2 py-1.5 font-mono text-[12px]"
                />
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder={t('settings.library.edit.columns.labelPlaceholder')}
                  className="flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px]"
                />
                <Select value={newDatatype} onValueChange={(v) => setNewDatatype(v as CustomColumnDatatype)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {datatypeOptions(t).map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {newDatatype === 'enumeration' && (
                <input
                  value={newEnumValues}
                  onChange={(e) => setNewEnumValues(e.target.value)}
                  placeholder={t('settings.library.edit.columns.enumPlaceholder')}
                  className="rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px]"
                />
              )}
              <div>
                <Button size="sm" onClick={() => void handleCreateColumn()} disabled={creatingColumn}>
                  {creatingColumn ? <Loader2 className="size-3.5 animate-spin" /> : null}
                  {t('settings.library.edit.columns.addButton')}
                </Button>
              </div>
            </div>

            {columnsMessage && (
              <p className={columnsMessage.kind === 'success' ? 'text-[12px] text-primary' : 'text-[12px] text-destructive'}>
                {columnsMessage.text}
              </p>
            )}
          </TabsContent>

          <TabsContent value="quickview" className="pt-2">
            <QuickviewFieldBuilderSection libraryFolder={library.folder_name} customColumns={customColumns} devices={devices} />
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// Costruttore drag-and-drop dei campi del pannello Quickview (Libreria) —
// per libreria (non più una scheda globale in Impostazioni ▸ Aspetto):
// la lista mischia i 12 campi fissi (sempre gli stessi), le colonne
// personalizzate DI QUESTA libreria e la presenza sui dispositivi
// registrati — vedi lib/quickviewFieldLayout.ts per il perché. Stesso
// stile visivo del costruttore sidebar in AspectTab.tsx.
function QuickviewFieldBuilderSection({
  libraryFolder,
  customColumns,
  devices,
}: {
  libraryFolder: string
  customColumns: CustomColumn[]
  devices: QuickviewDeviceInfo[]
}) {
  const { t } = useLingua()
  const { layout, descriptionVisible, dragStart, dropTo, toggleVisible, toggleDescriptionVisible, reset } =
    useQuickviewFieldLayoutBuilder(libraryFolder, customColumns, devices)
  const customColumnsByLabel = new Map(customColumns.map((c) => [c.label, c]))
  const devicesById = new Map(devices.map((d) => [String(d.id), d]))
  // Solo feedback visivo (opacità sulla riga trascinata, riga sopra cui si
  // sta passando evidenziata) — la logica di riordino vera vive nell'hook
  // (dragStart/dropTo), questo stato locale non la influenza in alcun modo.
  // Senza, il trascinamento nativo HTML5 non dà nessun segnale finché non si
  // rilascia: confusionale, come emerso in uso.
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null)
  const [overIndex, setOverIndex] = useState<number | null>(null)

  function endDrag() {
    setDraggingIndex(null)
    setOverIndex(null)
  }

  return (
    <div>
      <p className="mb-3 max-w-xl text-[11px] text-muted-foreground">
        {t('settings.library.quickview.description')}
      </p>

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={() => {
          dropTo(layout.length)
          endDrag()
        }}
        className={`flex max-h-72 flex-col gap-1 overflow-y-auto rounded-md border border-dashed p-2 transition-colors ${
          draggingIndex !== null ? 'border-primary/40 bg-primary/5' : 'border-border bg-muted/20'
        }`}
      >
        {layout.map((entry, idx) => {
          const label =
            entry.kind === 'fixed'
              ? quickviewFieldDefs(t)[entry.id].label
              : entry.kind === 'device'
                ? t('library.field.onDevice', { name: devicesById.get(entry.id)?.name ?? entry.id })
                : customColumnsByLabel.get(entry.id)?.name ?? entry.id
          return (
            <div
              key={`${entry.kind}:${entry.id}`}
              draggable
              onDragStart={() => {
                dragStart(idx)
                setDraggingIndex(idx)
              }}
              onDragEnter={() => setOverIndex(idx)}
              onDragOver={(e) => e.preventDefault()}
              onDragEnd={endDrag}
              onDrop={(e) => {
                e.stopPropagation()
                dropTo(idx)
                endDrag()
              }}
              className={`flex cursor-grab items-center gap-2 rounded-md border px-2.5 py-1.5 text-[12.5px] transition-[opacity,border-color] ${
                draggingIndex === idx
                  ? 'border-border bg-card opacity-40'
                  : overIndex === idx && draggingIndex !== null
                    ? 'border-primary bg-primary/10'
                    : 'border-border bg-card'
              }`}
            >
              <GripVertical className="size-3.5 shrink-0 text-muted-foreground" />
              <button
                onClick={() => toggleVisible(idx)}
                title={entry.visible ? t('settings.library.quickview.hide') : t('settings.library.quickview.show')}
                className={`flex size-4 shrink-0 items-center justify-center rounded-sm border ${
                  entry.visible ? 'border-primary bg-primary text-primary-foreground' : 'border-border'
                }`}
              >
                {entry.visible && <Check className="size-3" />}
              </button>
              <span className={`flex-1 ${entry.visible ? '' : 'text-muted-foreground'}`}>{label}</span>
              {entry.kind === 'custom' && (
                <span className="font-mono text-[10.5px] text-muted-foreground">#{entry.id}</span>
              )}
            </div>
          )
        })}
        <div className="mt-1 flex items-center gap-2 border-t border-border px-2.5 pt-2 text-[12.5px]">
          <button
            onClick={toggleDescriptionVisible}
            title={descriptionVisible ? t('settings.library.quickview.hide') : t('settings.library.quickview.show')}
            className={`flex size-4 shrink-0 items-center justify-center rounded-sm border ${
              descriptionVisible ? 'border-primary bg-primary text-primary-foreground' : 'border-border'
            }`}
          >
            {descriptionVisible && <Check className="size-3" />}
          </button>
          <span className={descriptionVisible ? '' : 'text-muted-foreground'}>
            {t('settings.library.quickview.descriptionLabel')}{' '}
            <span className="text-muted-foreground">{t('settings.library.quickview.descriptionAlwaysLast')}</span>
          </span>
        </div>
      </div>

      <Button variant="outline" size="sm" className="mt-3" onClick={reset}>
        <RotateCcw className="size-3.5" />
        {t('settings.library.quickview.resetOrder')}
      </Button>
    </div>
  )
}
