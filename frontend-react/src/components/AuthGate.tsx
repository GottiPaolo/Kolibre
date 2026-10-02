import { useEffect, useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { ensureAuthToken, login } from '@/lib/auth'
import { KolibreLogo } from '@/components/KolibreLogo'
import { useLingua } from '@/lib/i18n'

// Gate a livello di app: prova prima il login silenzioso (stesse
// credenziali placeholder del Vue esistente, se già presenti in
// localStorage per QUESTA origine); se fallisce — credenziali di default
// sbagliate, o nessuna credenziale salvata perché questo frontend vive su
// un'origine diversa (porta separata) e quindi NON condivide il
// localStorage del Vue esistente — mostra una schermata di login reale
// invece di un fallimento invisibile con app vuota.
export function AuthGate({ children }: { children: ReactNode }) {
  const { t } = useLingua()
  const [status, setStatus] = useState<'checking' | 'authenticated' | 'needs-login'>('checking')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    ensureAuthToken().then((token) => setStatus(token ? 'authenticated' : 'needs-login'))
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    const token = await login(username, password)
    setSubmitting(false)
    if (token) {
      // `login` ha già salvato il token: da qui non passa più nessuna
      // credenziale verso localStorage.
      setStatus('authenticated')
    } else {
      setError(t('common.auth.invalidCredentials'))
    }
  }

  if (status === 'checking') {
    return <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">{t('common.auth.checking')}</div>
  }

  if (status === 'needs-login') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <form onSubmit={handleSubmit} className="w-full max-w-xs space-y-4 rounded-xl border border-border bg-card p-6">
          <div className="flex items-center gap-2">
            <KolibreLogo className="size-6" />
            <span className="font-serif text-[17px] font-semibold">Kolibre</span>
          </div>
          <div className="space-y-2">
            <input
              autoFocus
              placeholder={t('common.auth.username')}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
            />
            <input
              type="password"
              placeholder={t('common.auth.password')}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
            />
          </div>
          {error && <p className="text-[12.5px] text-destructive">{error}</p>}
          <Button type="submit" className="w-full" disabled={submitting || !username || !password}>
            {submitting ? t('common.auth.loggingIn') : t('common.auth.login')}
          </Button>
        </form>
      </div>
    )
  }

  return <>{children}</>
}
