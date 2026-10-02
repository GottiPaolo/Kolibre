import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { User, LogOut, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  SettingsFeedback,
  SettingsField,
  SettingsInput,
  SettingsRow,
  SettingsSection,
} from '@/components/settings/SettingsPrimitives'
import { withBackendUrl } from '@/lib/api'
import { logout as clearAuthSession, login, clearAuthToken } from '@/lib/auth'
import { useMe, updateProfile, uploadProfilePhoto, removeProfilePhoto } from '@/lib/settingsActions'
import { useLingua } from '@/lib/i18n'

// Impostazioni ▸ Profilo — dati dell'unico account di questa installazione
// (/api/users/me, vedi lib/settingsActions.ts).
//
// La sezione "Account Secondari" del vecchio frontend Vue non è mai stata
// portata: era un mock in memoria senza backend (un solo models.User per
// installazione), con bottoni che non persistevano nulla.
export function ProfileTab() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: me } = useMe()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [editMode, setEditMode] = useState(false)
  const [tempFullname, setTempFullname] = useState('')
  const [tempUsername, setTempUsername] = useState('')
  const [tempNewPassword, setTempNewPassword] = useState('')
  const [tempConfirmPassword, setTempConfirmPassword] = useState('')
  const [saving, setSaving] = useState(false)
  const [uploadingPhoto, setUploadingPhoto] = useState(false)
  const [feedback, setFeedback] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  function enterEditMode() {
    setTempFullname(me?.fullname || me?.username || '')
    setTempUsername(me?.username || '')
    setTempNewPassword('')
    setTempConfirmPassword('')
    setFeedback(null)
    setEditMode(true)
  }

  function cancelEditMode() {
    setTempNewPassword('')
    setTempConfirmPassword('')
    setEditMode(false)
  }

  async function handleSave() {
    if (tempNewPassword && tempNewPassword !== tempConfirmPassword) {
      setFeedback({ kind: 'error', text: t('settings.profile.passwordMismatch') })
      return
    }
    setSaving(true)
    setFeedback(null)
    try {
      await updateProfile({
        fullname: tempFullname,
        username: tempUsername,
        ...(tempNewPassword ? { password: tempNewPassword } : {}),
      })
      // Il token in corso porta dentro di sé il VECCHIO username (è il
      // claim `sub`): se l'username è appena cambiato, da ora in poi non
      // risolve più a nessun utente e ogni richiesta risponderebbe 401.
      // Con una password nuova possiamo rifare il login da qui e proseguire
      // senza che si veda niente; senza, l'unica via onesta è chiudere la
      // sessione e dirlo — meglio di un'app che smette di funzionare.
      const usernameChanged = !!me && tempUsername !== me.username
      if (tempNewPassword) {
        clearAuthToken()
        await login(tempUsername, tempNewPassword)
      } else if (usernameChanged) {
        clearAuthSession()
        setFeedback({ kind: 'ok', text: t('settings.profile.usernameUpdated') })
        window.location.reload()
        return
      }
      await queryClient.invalidateQueries({ queryKey: ['users', 'me'] })
      setTempNewPassword('')
      setTempConfirmPassword('')
      setEditMode(false)
      setFeedback({ kind: 'ok', text: t('settings.profile.saved') })
    } catch {
      setFeedback({ kind: 'error', text: t('settings.profile.saveError') })
    } finally {
      setSaving(false)
    }
  }

  async function handlePhotoChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (file.size > 2_000_000) {
      setFeedback({ kind: 'error', text: t('settings.profile.fileTooLarge') })
      return
    }
    setUploadingPhoto(true)
    setFeedback(null)
    try {
      await uploadProfilePhoto(file)
      await queryClient.invalidateQueries({ queryKey: ['users', 'me'] })
      setFeedback({ kind: 'ok', text: t('settings.profile.photoUpdated') })
    } catch {
      setFeedback({ kind: 'error', text: t('settings.profile.uploadError') })
    } finally {
      setUploadingPhoto(false)
    }
  }

  async function handleRemovePhoto() {
    setFeedback(null)
    try {
      await removeProfilePhoto()
      await queryClient.invalidateQueries({ queryKey: ['users', 'me'] })
      setFeedback({ kind: 'ok', text: t('settings.profile.photoRemoved') })
    } catch {
      setFeedback({ kind: 'error', text: t('settings.profile.removeError') })
    }
  }

  // AuthGate.tsx valuta lo stato di autenticazione solo al mount e nessun
  // canale porta fin lì un logout deciso da qui: ricaricare è il modo più
  // semplice e sicuro per farlo ripartire e mostrare il login vero.
  function handleLogout() {
    clearAuthSession()
    window.location.reload()
  }

  const photoUrl = me?.photo_url ? withBackendUrl(`${me.photo_url}?t=${me.id}`) : null

  return (
    <SettingsSection label={t('settings.profile.sectionLabel')}>
      <SettingsRow
        name={
          <span className="flex items-center gap-3">
            <Avatar photoUrl={photoUrl} />
            <span>
              <span className="block">{me?.fullname || me?.username || '—'}</span>
              <span className="block text-[12px] font-normal text-muted-foreground">@{me?.username}</span>
            </span>
          </span>
        }
      >
        {!editMode && (
          <Button variant="outline" size="sm" onClick={enterEditMode}>
            {t('settings.profile.edit')}
          </Button>
        )}
      </SettingsRow>

      {editMode && (
        <div className="flex flex-col gap-3 border-b border-[var(--border-soft)] py-4">
          <SettingsField label={t('settings.profile.fullNameLabel')}>
            <SettingsInput value={tempFullname} onChange={setTempFullname} />
          </SettingsField>
          <SettingsField label={t('settings.profile.usernameLabel')}>
            <SettingsInput value={tempUsername} onChange={setTempUsername} autoComplete="username" />
          </SettingsField>
          <SettingsField label={t('settings.profile.newPasswordLabel')}>
            <SettingsInput
              type="password"
              value={tempNewPassword}
              onChange={setTempNewPassword}
              placeholder={t('settings.profile.newPasswordPlaceholder')}
              autoComplete="new-password"
            />
          </SettingsField>
          {tempNewPassword && (
            <SettingsField label={t('settings.profile.confirmPasswordLabel')}>
              <SettingsInput
                type="password"
                value={tempConfirmPassword}
                onChange={setTempConfirmPassword}
                autoComplete="new-password"
              />
            </SettingsField>
          )}
          <div className="flex gap-2">
            <Button size="sm" disabled={saving} onClick={() => void handleSave()}>
              {saving ? t('settings.profile.saving') : t('common.save')}
            </Button>
            <Button variant="outline" size="sm" onClick={cancelEditMode}>
              {t('common.cancel')}
            </Button>
          </div>
        </div>
      )}

      <SettingsRow name={t('settings.profile.photoLabel')} description={t('settings.profile.photoDescription')}>
        <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={(e) => void handlePhotoChange(e)} />
        <Button variant="outline" size="sm" disabled={uploadingPhoto} onClick={() => fileInputRef.current?.click()}>
          {uploadingPhoto ? t('settings.profile.photoUploading') : t('settings.profile.photoUpload')}
        </Button>
        {photoUrl && (
          <Button variant="ghost" size="icon-sm" title={t('settings.profile.removePhotoTitle')} onClick={() => void handleRemovePhoto()}>
            <Trash2 className="size-3.5" />
          </Button>
        )}
      </SettingsRow>

      <SettingsRow name={t('settings.profile.logout')} description={t('settings.profile.logoutDescription')} last>
        <Button variant="ghost" size="sm" className="text-destructive" onClick={handleLogout}>
          <LogOut className="size-3.5" /> {t('settings.profile.logout')}
        </Button>
      </SettingsRow>

      {feedback && <SettingsFeedback kind={feedback.kind}>{feedback.text}</SettingsFeedback>}
    </SettingsSection>
  )
}

function Avatar({ photoUrl }: { photoUrl: string | null }) {
  return (
    <span className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-muted">
      {photoUrl ? (
        <img src={photoUrl} alt="" className="size-full object-cover" />
      ) : (
        <User className="size-4 text-muted-foreground" />
      )}
    </span>
  )
}
