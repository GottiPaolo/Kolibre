// I token con cui le applicazioni parlano col server a nome tuo.
//
// **Perché questa sezione esiste.** Il plugin Obsidian si collegava con nome
// utente e password e poi *conservava la password* nel proprio `data.json` —
// cioè dentro il vault, la cartella che la gente sincronizza fra computer e a
// volte mette in un repository git. Non era una svista: serviva a rinnovare
// l'accesso da sé quando il token di sessione scadeva dopo sette giorni.
//
// Dal 05/11/2026 quelle applicazioni usano un **token proprio**: non scade, e
// si spegne da qui. È questa pagina che rende il cambio una correzione invece
// di uno spostamento del problema — un token che non si può revocare non è
// meglio di una password.
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, KeyRound, Loader2, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SettingsInput, SettingsRow, SettingsSection } from '@/components/settings/SettingsPrimitives'
import { api } from '@/lib/api'
import { toast } from '@/lib/toast'
import { messaggioErrore } from '@/lib/messaggiErrore'
import { useLingua } from '@/lib/i18n'

export function TokenApplicazioniSection() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  // Il token appena creato: si tiene in memoria perché **è l'unica volta che
  // esiste**. Il server ne conserva l'impronta e non è in grado di ridirlo;
  // chiudere questa riga lo perde, ed è il punto di tutto il disegno.
  const [appenaCreato, setAppenaCreato] = useState<{ nome: string; token: string } | null>(null)
  const [inCorso, setInCorso] = useState(false)
  const [nomeNuovo, setNomeNuovo] = useState('')

  const { data: token = [] } = useQuery({
    queryKey: ['token-applicazione'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/users/me/tokens')
      if (error) throw error
      return data.items
    },
  })

  // **Perché questo comando esiste.** Il disegno di partenza era che i token
  // nascessero dalle applicazioni: il plugin Obsidian ne chiede uno da sé
  // quando premi «Accedi», e questa pagina serviva solo a vederli e a
  // spegnerli. Ma un token serve anche a cose che non hanno una finestra di
  // accesso — uno script, il comando che scatta le immagini del README — e
  // per quelle non c'era nessuna strada: la pagina li elencava e non ne
  // faceva. Il riquadro «copialo adesso» qui sotto esisteva già e non veniva
  // mai mostrato, perché nessuno chiamava la creazione.
  async function crea() {
    const nome = nomeNuovo.trim()
    if (!nome) return
    setInCorso(true)
    try {
      const { data, error } = await api.POST('/api/users/me/tokens', { body: { nome } })
      if (error) throw error
      // Si tiene in memoria perché è l'unica volta che il token esiste: il
      // server ne conserva solo l'impronta e non è in grado di ridirlo.
      setAppenaCreato({ nome: data.nome, token: data.token })
      setNomeNuovo('')
      void queryClient.invalidateQueries({ queryKey: ['token-applicazione'] })
    } catch (e) {
      toast.error(messaggioErrore(e, t('settings.tokens.createFailed')))
    } finally {
      setInCorso(false)
    }
  }

  async function revoca(id: number, nome: string) {
    if (!window.confirm(t('settings.tokens.confirmRevoke', { name: nome }))) return
    setInCorso(true)
    try {
      const { error } = await api.DELETE('/api/users/me/tokens/{token_id}', {
        params: { path: { token_id: id } },
      })
      if (error) throw error
      toast.success(t('settings.tokens.revoked', { name: nome }))
      void queryClient.invalidateQueries({ queryKey: ['token-applicazione'] })
    } catch (e) {
      toast.error(messaggioErrore(e, t('settings.tokens.revokeFailed')))
    } finally {
      setInCorso(false)
    }
  }

  return (
    <SettingsSection label={t('settings.tokens.sectionLabel')}>
      <SettingsRow
        name={t('settings.tokens.whatName')}
        description={t('settings.tokens.whatDescription')}
      />

      {token.length === 0 && !appenaCreato && (
        <p className="px-1 py-2 text-[13px] text-muted-foreground">
          {t('settings.tokens.empty')}
        </p>
      )}

      {token.map((riga) => (
        <SettingsRow
          key={riga.id}
          name={riga.nome}
          // «Mai usato» e una data sono due informazioni diverse: la seconda
          // dice che quel token serve, la prima che è stato creato e
          // dimenticato — ed è l'unico modo di accorgersi di un token da
          // spegnere.
          description={
            riga.ultimo_uso_il
              ? t('settings.tokens.lastUsed', { date: new Date(riga.ultimo_uso_il).toLocaleString() })
              : t('settings.tokens.neverUsed')
          }
        >
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive"
            disabled={inCorso}
            onClick={() => void revoca(riga.id, riga.nome)}
          >
            <Trash2 className="size-3.5" /> {t('settings.tokens.revoke')}
          </Button>
        </SettingsRow>
      ))}

      {/* Sempre visibile, anche con l'elenco vuoto: è la riga che risponde
          alla domanda «e io come ne faccio uno?». */}
      <SettingsRow
        name={t('settings.tokens.createName')}
        description={t('settings.tokens.createDescription')}
        last={!appenaCreato}
      >
        <div className="flex items-center gap-2">
          <SettingsInput
            value={nomeNuovo}
            onChange={setNomeNuovo}
            placeholder={t('settings.tokens.namePlaceholder')}
            ariaLabel={t('settings.tokens.createName')}
            className="w-44"
          />
          <Button size="sm" disabled={inCorso || !nomeNuovo.trim()} onClick={() => void crea()}>
            {inCorso ? <Loader2 className="size-3.5 animate-spin" /> : <KeyRound className="size-3.5" />}
            {t('settings.tokens.create')}
          </Button>
        </div>
      </SettingsRow>

      {appenaCreato && (
        <div className="mt-2 rounded-md border border-border bg-muted/40 p-3">
          <p className="mb-2 text-[12.5px] text-muted-foreground">
            {t('settings.tokens.copyNow', { name: appenaCreato.nome })}
          </p>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded bg-background px-2 py-1 text-[12px]">
              {appenaCreato.token}
            </code>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                void navigator.clipboard.writeText(appenaCreato.token)
                toast.success(t('settings.tokens.copied'))
              }}
            >
              <Copy className="size-3.5" /> {t('settings.tokens.copy')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setAppenaCreato(null)}>
              {t('common.close')}
            </Button>
          </div>
        </div>
      )}
    </SettingsSection>
  )
}
