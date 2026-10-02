import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, Loader2, Plus, RotateCcw, Settings, Trash2, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  SettingsFeedback,
  SettingsHint,
  SettingsInput,
  SettingsList,
  SettingsListRow,
  SettingsPill,
  SettingsRow,
  SettingsSection,
} from '@/components/settings/SettingsPrimitives'
import { useLibraries } from '@/lib/queries'
import { formatBytes, formatDate } from '@/lib/format'
import type { Library } from '@/types/library'
import {
  errorDetail,
  purgeTrashedLibrary,
  reorderLibraries,
  restoreTrashedLibrary,
  savePageCountSettings,
  useTrashedLibraries,
  usePageCountSettings,
  type PageCountSettings,
  type TrashedLibrary,
} from '@/lib/librarySettingsActions'
import { CreateLibraryDialog } from './CreateLibraryDialog'
import { ImportLibraryDialog } from './ImportLibraryDialog'
import { LibraryEditDialog } from './LibraryEditDialog'
import { useLingua } from '@/lib/i18n'

// Impostazioni ▸ Librerie: le librerie Calibre collegate e come si contano
// le pagine. Solo configurazione — le azioni che girano su molti libri
// (incluso il ricalcolo delle pagine, che prima stava proprio qui in mezzo
// alle impostazioni di conteggio) sono in Impostazioni ▸ Operazioni di massa.
export function LibrariesTab() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: libraries = [], isLoading } = useLibraries()

  const [showCreate, setShowCreate] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [editingLibrary, setEditingLibrary] = useState<Library | null>(null)
  const [reorderingId, setReorderingId] = useState<number | null>(null)
  const [reorderError, setReorderError] = useState<string | null>(null)

  async function moveLibrary(index: number, dir: -1 | 1) {
    const target = index + dir
    if (target < 0 || target >= libraries.length) return
    const next = [...libraries]
    ;[next[index], next[target]] = [next[target], next[index]]
    setReorderingId(next[target].id)
    setReorderError(null)
    try {
      await reorderLibraries(next.map((l) => l.id))
      await queryClient.invalidateQueries({ queryKey: ['libraries'] })
    } catch (err) {
      setReorderError(errorDetail(err, t('settings.libraries.connected.reorderError')))
    } finally {
      setReorderingId(null)
    }
  }

  return (
    <>
      <SettingsSection
        label={t('settings.libraries.connected.label')}
        description={t('settings.libraries.connected.description')}
      >
        {isLoading && <p className="py-3 text-[12.5px] text-muted-foreground">{t('common.loading')}</p>}

        {!isLoading && libraries.length === 0 && (
          <p className="py-3 text-[12.5px] text-muted-foreground">{t('settings.libraries.connected.empty')}</p>
        )}

        {libraries.length > 0 && (
          <SettingsList className="mt-3">
            {libraries.map((lib, idx) => (
              <SettingsListRow key={lib.id}>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-medium">{lib.name}</span>
                    {idx === 0 && <SettingsPill tone="ok">{t('settings.libraries.connected.default')}</SettingsPill>}
                  </div>
                  <div className="mt-1 text-[11.5px] text-muted-foreground">
                    {t('settings.libraries.connected.stats', {
                      books: lib.books_count,
                      authors: lib.authors_count,
                      size: formatBytes(lib.size_bytes),
                    })}
                  </div>
                  <div className="mt-0.5 truncate font-mono text-[11px] text-[var(--text-faint)]">{lib.path}</div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title={t('settings.libraries.connected.moveUp')}
                    disabled={idx === 0 || reorderingId !== null}
                    onClick={() => void moveLibrary(idx, -1)}
                  >
                    {reorderingId === lib.id ? <Loader2 className="size-3.5 animate-spin" /> : <ChevronUp className="size-3.5" />}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title={t('settings.libraries.connected.moveDown')}
                    disabled={idx === libraries.length - 1 || reorderingId !== null}
                    onClick={() => void moveLibrary(idx, 1)}
                  >
                    <ChevronDown className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title={t('settings.libraries.connected.settingsTitle')}
                    onClick={() => setEditingLibrary(lib)}
                  >
                    <Settings className="size-3.5" />
                  </Button>
                </div>
              </SettingsListRow>
            ))}
          </SettingsList>
        )}

        {reorderError && <SettingsFeedback kind="error">{reorderError}</SettingsFeedback>}

        <SettingsRow description={t('settings.libraries.connected.addDescription')} last>
          <Button variant="outline" size="sm" onClick={() => setShowImport(true)}>
            <Upload className="size-3.5" /> {t('settings.libraries.connected.importExisting')}
          </Button>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="size-3.5" /> {t('settings.libraries.connected.newLibrary')}
          </Button>
        </SettingsRow>
      </SettingsSection>

      <PageCountSection />

      <TrashSection />

      {showCreate && <CreateLibraryDialog onClose={() => setShowCreate(false)} />}
      {showImport && <ImportLibraryDialog onClose={() => setShowImport(false)} />}
      {editingLibrary && <LibraryEditDialog library={editingLibrary} onClose={() => setEditingLibrary(null)} />}
    </>
  )
}

// Impostazioni globali (non per-libreria) della stima pagine per i formati
// reflowable. Il ricalcolo vero e proprio sui libri già in catalogo è
// un'operazione di massa e vive lì (BulkOperationsTab).
function PageCountSection() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: settings, isLoading } = usePageCountSettings()
  const [draft, setDraft] = useState<PageCountSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const current = draft ?? settings

  async function handleSave() {
    if (!current) return
    setSaving(true)
    setMessage(null)
    try {
      setDraft(await savePageCountSettings(current))
      await queryClient.invalidateQueries({ queryKey: ['page-count-settings'] })
      setMessage({ kind: 'ok', text: t('settings.libraries.pageCount.saved') })
    } catch (err) {
      setMessage({ kind: 'error', text: errorDetail(err, t('settings.libraries.pageCount.saveError')) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <SettingsSection label={t('settings.libraries.pageCount.label')}>
      {isLoading && <p className="py-3 text-[12.5px] text-muted-foreground">{t('common.loading')}</p>}

      {current && (
        <>
          <SettingsRow
            name={t('settings.libraries.pageCount.modeName')}
            description={t('settings.libraries.pageCount.modeDescription')}
          >
            <Select value={current.mode} onValueChange={(v) => setDraft({ ...current, mode: v as 'words' | 'chars' })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="words">{t('settings.libraries.pageCount.byWords')}</SelectItem>
                <SelectItem value="chars">{t('settings.libraries.pageCount.byChars')}</SelectItem>
              </SelectContent>
            </Select>
          </SettingsRow>

          <SettingsRow
            name={
              current.mode === 'chars'
                ? t('settings.libraries.pageCount.charsPerPage')
                : t('settings.libraries.pageCount.wordsPerPage')
            }
            description={
              current.mode === 'chars'
                ? t('settings.libraries.pageCount.charsHint')
                : t('settings.libraries.pageCount.wordsHint')
            }
            last
          >
            <SettingsInput
              type="number"
              className="w-24"
              ariaLabel={
                current.mode === 'chars'
                  ? t('settings.libraries.pageCount.charsPerPage')
                  : t('settings.libraries.pageCount.wordsPerPage')
              }
              value={String(current.mode === 'chars' ? current.chars_per_page : current.words_per_page)}
              onChange={(v) => {
                const value = Number(v) || 0
                setDraft(
                  current.mode === 'chars' ? { ...current, chars_per_page: value } : { ...current, words_per_page: value }
                )
              }}
            />
            <Button variant="outline" size="sm" disabled={saving} onClick={() => void handleSave()}>
              {saving ? <Loader2 className="size-3.5 animate-spin" /> : null}
              {t('common.save')}
            </Button>
          </SettingsRow>

          {message && <SettingsFeedback kind={message.kind}>{message.text}</SettingsFeedback>}

          <SettingsHint>{t('settings.libraries.pageCount.hint')}</SettingsHint>
        </>
      )}
    </SettingsSection>
  )
}

// Cestino librerie: una libreria eliminata viene spostata in _trash_libraries
// invece che cancellata (vedi delete_library in libraries.py). La sezione
// compare solo quando c'è davvero qualcosa dentro.
function TrashSection() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: items = [], isLoading } = useTrashedLibraries()
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  async function handleRestore(item: TrashedLibrary) {
    setMessage(null)
    try {
      await restoreTrashedLibrary(item.id)
      await queryClient.invalidateQueries({ queryKey: ['libraries-trash'] })
      await queryClient.invalidateQueries({ queryKey: ['libraries'] })
      setMessage({ kind: 'ok', text: t('settings.libraries.trash.restored', { name: item.folder_name }) })
    } catch (err) {
      setMessage({ kind: 'error', text: errorDetail(err, t('settings.libraries.trash.restoreError')) })
    }
  }

  async function handlePurge(item: TrashedLibrary) {
    setMessage(null)
    try {
      await purgeTrashedLibrary(item.id)
      await queryClient.invalidateQueries({ queryKey: ['libraries-trash'] })
      setMessage({ kind: 'ok', text: t('settings.libraries.trash.purged', { name: item.folder_name }) })
    } catch (err) {
      setMessage({ kind: 'error', text: errorDetail(err, t('settings.libraries.trash.purgeError')) })
    }
  }

  if (!isLoading && items.length === 0) return null

  return (
    <SettingsSection
      label={t('settings.libraries.trash.label')}
      description={t('settings.libraries.trash.description')}
    >
      {isLoading && <p className="py-3 text-[12.5px] text-muted-foreground">{t('common.loading')}</p>}

      {items.length > 0 && (
        <SettingsList className="mt-3">
          {items.map((item) => (
            <TrashRow
              key={item.id}
              item={item}
              onRestore={() => void handleRestore(item)}
              onPurge={() => void handlePurge(item)}
            />
          ))}
        </SettingsList>
      )}

      {message && <SettingsFeedback kind={message.kind}>{message.text}</SettingsFeedback>}
    </SettingsSection>
  )
}

function TrashRow({ item, onRestore, onPurge }: { item: TrashedLibrary; onRestore: () => void; onPurge: () => void }) {
  const { t } = useLingua()
  const [confirmPurge, setConfirmPurge] = useState(false)

  return (
    <SettingsListRow className="flex-col items-stretch gap-2.5">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="text-[13px] font-medium">{item.folder_name}</div>
          <div className="mt-1 text-[11.5px] text-muted-foreground">
            {item.deleted_at && <>{t('settings.libraries.trash.deletedOn', { date: formatDate(item.deleted_at) })}</>}
            {formatBytes(item.size_bytes)}
          </div>
        </div>
        {!confirmPurge && (
          <div className="flex shrink-0 items-center gap-1">
            <Button variant="outline" size="sm" onClick={onRestore}>
              <RotateCcw className="size-3.5" /> {t('settings.libraries.trash.restore')}
            </Button>
            <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setConfirmPurge(true)}>
              <Trash2 className="size-3.5" /> {t('settings.libraries.trash.delete')}
            </Button>
          </div>
        )}
      </div>

      {confirmPurge && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-2.5">
          <p className="mb-2 text-[12px] text-destructive">
            {t('settings.libraries.trash.confirmText', { name: item.folder_name })}
          </p>
          <div className="flex gap-2">
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                onPurge()
                setConfirmPurge(false)
              }}
            >
              {t('settings.libraries.trash.deleteForever')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setConfirmPurge(false)}>
              {t('common.cancel')}
            </Button>
          </div>
        </div>
      )}
    </SettingsListRow>
  )
}
