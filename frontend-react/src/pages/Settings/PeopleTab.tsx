import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Trash2, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  SettingsFeedback,
  SettingsHint,
  SettingsInput,
  SettingsList,
  SettingsListRow,
  SettingsRow,
  SettingsSection,
  SettingsToggle,
} from '@/components/settings/SettingsPrimitives'
import { api } from '@/lib/api'
import { messaggioErrore } from '@/lib/messaggiErrore'
import { useLibraries } from '@/lib/queries'
import type { Library } from '@/types/library'
import { useLingua, type Valori } from '@/lib/i18n'

// Chi c'è su questa installazione, e cosa può fare.
//
// I permessi sono due famiglie, e la scheda le tiene separate perché
// rispondono a domande di tipo diverso: quelli dell'ACCOUNT (creare
// biblioteche, creare utenti, …) non dipendono da nessuna biblioteca;
// quelli di una BIBLIOTECA dipendono da quale. Mischiarli in un'unica lista
// di caselle renderebbe incomprensibile perché "modificare" compaia due
// volte con due significati.
//
// Il fondatore appare con le caselle piene e bloccate: sta fuori da ogni
// limitazione, e mostrargliele vuote — pur potendo tutto — sarebbe una
// schermata che mente.

interface Persona {
  id: number
  username: string
  fullname: string | null
  is_admin: boolean
  is_founder: boolean
  can_create_libraries: boolean
  can_create_users: boolean
  can_manage_permissions: boolean
  can_register_devices: boolean
  can_edit_authors: boolean
}

interface Condivisione {
  user_id: number
  username: string
  can_edit: boolean
  can_share: boolean
  can_manage: boolean
}

interface PermessiBiblioteca {
  library: string
  owner: string | null
  owner_id: number | null
  puoi_gestire: boolean
  condivisioni: Condivisione[]
}

// Funzione e non oggetto costante: deve ricalcolarsi al cambio lingua, come
// fixedColumnLabels in lib/libraryColumns.ts.
function permessiAccount(
  t: (chiave: string, valori?: Valori) => string
): { campo: keyof Persona; nome: string; descrizione: string }[] {
  return [
    {
      campo: 'can_create_libraries',
      nome: t('settings.people.permission.createLibraries.name'),
      descrizione: t('settings.people.permission.createLibraries.description'),
    },
    {
      campo: 'can_create_users',
      nome: t('settings.people.permission.createUsers.name'),
      descrizione: t('settings.people.permission.createUsers.description'),
    },
    {
      campo: 'can_manage_permissions',
      nome: t('settings.people.permission.managePermissions.name'),
      descrizione: t('settings.people.permission.managePermissions.description'),
    },
    {
      campo: 'can_register_devices',
      nome: t('settings.people.permission.registerDevices.name'),
      descrizione: t('settings.people.permission.registerDevices.description'),
    },
    {
      campo: 'can_edit_authors',
      nome: t('settings.people.permission.editAuthors.name'),
      descrizione: t('settings.people.permission.editAuthors.description'),
    },
  ]
}

function usePersone() {
  return useQuery({
    queryKey: ['persone'],
    queryFn: async (): Promise<Persona[]> => {
      const { data, error } = await api.GET('/api/users')
      if (error) throw error
      return data as unknown as Persona[]
    },
  })
}

function usePermessiBiblioteca(nome: string | undefined) {
  return useQuery({
    queryKey: ['permessi-biblioteca', nome],
    enabled: !!nome,
    queryFn: async (): Promise<PermessiBiblioteca> => {
      const { data, error } = await api.GET('/api/kolibre/libraries/{name}/permessi', {
        params: { path: { name: nome! } },
      })
      if (error) throw error
      return data as unknown as PermessiBiblioteca
    },
  })
}

export function PeopleTab() {
  const { t } = useLingua()
  const PERMESSI_ACCOUNT = permessiAccount(t)
  const queryClient = useQueryClient()
  const { data: persone = [], isLoading } = usePersone()
  const { data: biblioteche = [] } = useLibraries()

  const [nuovoNome, setNuovoNome] = useState('')
  const [nuovaPassword, setNuovaPassword] = useState('')
  const [creando, setCreando] = useState(false)
  const [esito, setEsito] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [bibliotecaScelta, setBibliotecaScelta] = useState<Library | undefined>(undefined)

  const biblioteca = bibliotecaScelta ?? biblioteche[0]
  const { data: permessi } = usePermessiBiblioteca(biblioteca?.folder_name)

  async function creaPersona() {
    if (!nuovoNome.trim() || !nuovaPassword) return
    setCreando(true)
    setEsito(null)
    try {
      const { error, response } = await api.POST('/api/users', {
        body: { username: nuovoNome.trim(), password: nuovaPassword },
      })
      // Il server dice già perché ("Il tuo account non può creare utenti.",
      // "Esiste già un utente con questo nome"): scrivere un messaggio nostro
      // vorrebbe dire indovinare fra due cause diverse.
      if (error) {
        setEsito({ kind: 'error', text: messaggioErrore(error, t('entities.error.generic'), response?.status) })
        return
      }
      setNuovoNome('')
      setNuovaPassword('')
      setEsito({ kind: 'ok', text: t('settings.people.createSuccess') })
      await queryClient.invalidateQueries({ queryKey: ['persone'] })
    } catch {
      setEsito({ kind: 'error', text: t('entities.error.noResponse') })
    } finally {
      setCreando(false)
    }
  }

  async function cambiaPermesso(persona: Persona, campo: keyof Persona, valore: boolean) {
    try {
      const { error, response } = await api.PUT('/api/users/{user_id}/permessi', {
        params: { path: { user_id: persona.id } },
        body: { [campo]: valore },
      })
      if (error) {
        setEsito({ kind: 'error', text: messaggioErrore(error, t('entities.error.generic'), response?.status) })
        return
      }
      await queryClient.invalidateQueries({ queryKey: ['persone'] })
    } catch {
      setEsito({ kind: 'error', text: t('entities.error.noResponse') })
    }
  }

  async function cancellaPersona(persona: Persona) {
    if (!window.confirm(t('settings.people.deleteConfirm', { name: persona.username }))) return
    try {
      const { error, response } = await api.DELETE('/api/users/{user_id}', {
        params: { path: { user_id: persona.id } },
      })
      if (error) {
        setEsito({ kind: 'error', text: messaggioErrore(error, t('entities.error.generic'), response?.status) })
        return
      }
      await queryClient.invalidateQueries({ queryKey: ['persone'] })
    } catch {
      setEsito({ kind: 'error', text: t('entities.error.noResponse') })
    }
  }

  async function cambiaCondivisione(userId: number, campi: Partial<Condivisione>, revoca = false) {
    if (!biblioteca) return
    try {
      const { error, response } = await api.PUT('/api/kolibre/libraries/{name}/permessi', {
        params: { path: { name: biblioteca.folder_name } },
        body: { user_id: userId, ...campi, revoca },
      })
      if (error) {
        setEsito({ kind: 'error', text: messaggioErrore(error, t('entities.error.generic'), response?.status) })
        return
      }
      await queryClient.invalidateQueries({ queryKey: ['permessi-biblioteca'] })
      await queryClient.invalidateQueries({ queryKey: ['libraries'] })
    } catch {
      setEsito({ kind: 'error', text: t('entities.error.noResponse') })
    }
  }

  if (isLoading) return <p className="pt-4 text-[12.5px] text-muted-foreground">{t('common.loading')}</p>

  const condivisePerUtente = new Map(permessi?.condivisioni.map((c) => [c.user_id, c]) ?? [])

  return (
    <>
      <SettingsSection label={t('settings.people.label')} description={t('settings.people.description')}>
        <SettingsList>
          {persone.map((persona) => (
            <SettingsListRow key={persona.id}>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="text-[13px] font-medium">
                  {persona.username}
                  {persona.is_founder && (
                    <span className="ml-2 rounded border border-[var(--positive)]/40 px-1 py-px text-[10px] font-semibold text-[var(--positive)]">
                      {t('settings.people.founderBadge')}
                    </span>
                  )}
                </span>
                <span className="text-[11.5px] text-muted-foreground">
                  {persona.is_founder
                    ? t('settings.people.founderDescription')
                    : PERMESSI_ACCOUNT.filter((p) => persona[p.campo]).map((p) => p.nome).join(' · ') || t('settings.people.noPermissions')}
                </span>
              </div>
              {!persona.is_founder && (
                <Button
                  variant="ghost"
                  size="xs"
                  className="text-destructive hover:text-destructive"
                  onClick={() => void cancellaPersona(persona)}
                  title={t('settings.people.deleteUserTitle')}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              )}
            </SettingsListRow>
          ))}
        </SettingsList>

        <SettingsRow name={t('settings.people.newUserName')} description={t('settings.people.newUserDescription')} stack>
          <div className="flex flex-wrap items-center gap-2">
            <SettingsInput
              value={nuovoNome}
              onChange={setNuovoNome}
              placeholder={t('settings.people.usernamePlaceholder')}
              ariaLabel={t('common.auth.username')}
            />
            <SettingsInput
              value={nuovaPassword}
              onChange={setNuovaPassword}
              type="password"
              placeholder={t('settings.people.passwordPlaceholder')}
              autoComplete="new-password"
              ariaLabel={t('common.auth.password')}
            />
            <Button size="sm" disabled={creando || !nuovoNome.trim() || !nuovaPassword} onClick={() => void creaPersona()}>
              {creando ? <Loader2 className="size-3.5 animate-spin" /> : <UserPlus className="size-3.5" />}
              {t('settings.people.create')}
            </Button>
          </div>
        </SettingsRow>
        {esito && <SettingsFeedback kind={esito.kind}>{esito.text}</SettingsFeedback>}
      </SettingsSection>

      <SettingsSection
        label={t('settings.people.accountPermissions.label')}
        description={t('settings.people.accountPermissions.description')}
      >
        {persone.map((persona) => (
          <SettingsRow key={persona.id} name={persona.username} stack>
            <div className="flex flex-col gap-1.5">
              {PERMESSI_ACCOUNT.map((permesso) => (
                <label key={permesso.campo} className="flex items-center gap-2.5 text-[12.5px]">
                  <SettingsToggle
                    checked={persona.is_founder || Boolean(persona[permesso.campo])}
                    disabled={persona.is_founder}
                    onChange={(next) => void cambiaPermesso(persona, permesso.campo, next)}
                    label={t('settings.people.toggleLabel', { permission: permesso.nome, username: persona.username })}
                  />
                  <span>
                    {permesso.nome}
                    <span className="ml-1.5 text-[11.5px] text-muted-foreground">{permesso.descrizione}</span>
                  </span>
                </label>
              ))}
            </div>
          </SettingsRow>
        ))}
      </SettingsSection>

      <SettingsSection
        label={t('settings.people.sharing.label')}
        description={t('settings.people.sharing.description')}
      >
        <SettingsRow name={t('settings.bulkOperations.scope.library')} description={t('settings.people.sharing.libraryRowDescription')}>
          <select
            value={biblioteca?.folder_name ?? ''}
            onChange={(e) => setBibliotecaScelta(biblioteche.find((l) => l.folder_name === e.target.value))}
            className="rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
          >
            {biblioteche.map((l) => (
              <option key={l.id} value={l.folder_name}>
                {l.name}
              </option>
            ))}
          </select>
        </SettingsRow>

        {permessi && (
          <>
            <SettingsRow name={t('settings.people.sharing.ownerRowName')} description={t('settings.people.sharing.ownerRowDescription')}>
              <span className="text-[12.5px]">{permessi.owner ?? t('settings.people.sharing.noOwner')}</span>
            </SettingsRow>

            {persone
              .filter((p) => p.id !== permessi.owner_id && !p.is_founder)
              .map((persona) => {
                const condivisa = condivisePerUtente.get(persona.id)
                return (
                  <SettingsRow key={persona.id} name={persona.username} stack>
                    <div className="flex flex-wrap items-center gap-4 text-[12.5px]">
                      <label className="flex items-center gap-2">
                        <SettingsToggle
                          checked={!!condivisa}
                          disabled={!permessi.puoi_gestire}
                          onChange={(next) =>
                            void cambiaCondivisione(persona.id, next ? { can_edit: false } : {}, !next)
                          }
                          label={t('settings.people.sharing.accessLabel', { name: persona.username })}
                        />
                        {t('settings.people.sharing.canRead')}
                      </label>
                      <label className="flex items-center gap-2">
                        <SettingsToggle
                          checked={!!condivisa?.can_edit}
                          disabled={!condivisa || !permessi.puoi_gestire}
                          onChange={(next) =>
                            void cambiaCondivisione(persona.id, {
                              can_edit: next,
                              can_share: condivisa?.can_share,
                              can_manage: condivisa?.can_manage,
                            })
                          }
                          label={t('settings.people.sharing.editLabel', { name: persona.username })}
                        />
                        {t('settings.people.sharing.canEdit')}
                      </label>
                      <label className="flex items-center gap-2">
                        <SettingsToggle
                          checked={!!condivisa?.can_share}
                          disabled={!condivisa || !permessi.puoi_gestire}
                          onChange={(next) =>
                            void cambiaCondivisione(persona.id, {
                              can_edit: condivisa?.can_edit,
                              can_share: next,
                              can_manage: condivisa?.can_manage,
                            })
                          }
                          label={t('settings.people.sharing.shareLabel', { name: persona.username })}
                        />
                        {t('settings.people.sharing.canShare')}
                      </label>
                      <label className="flex items-center gap-2">
                        <SettingsToggle
                          checked={!!condivisa?.can_manage}
                          disabled={!condivisa || !permessi.puoi_gestire}
                          onChange={(next) =>
                            void cambiaCondivisione(persona.id, {
                              can_edit: condivisa?.can_edit,
                              can_share: condivisa?.can_share,
                              can_manage: next,
                            })
                          }
                          label={t('settings.people.sharing.manageLabel', { name: persona.username })}
                        />
                        {t('settings.people.sharing.canManage')}
                      </label>
                    </div>
                  </SettingsRow>
                )
              })}
            {!permessi.puoi_gestire && (
              <SettingsHint>{t('settings.people.sharing.readOnlyHint')}</SettingsHint>
            )}
          </>
        )}
      </SettingsSection>
    </>
  )
}
