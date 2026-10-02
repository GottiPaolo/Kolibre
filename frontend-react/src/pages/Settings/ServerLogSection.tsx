import { useState } from 'react'
import { ClipboardCopy, Loader2, ScrollText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SettingsHint, SettingsRow, SettingsSection } from '@/components/settings/SettingsPrimitives'
import { api } from '@/lib/api'
import { useLingua } from '@/lib/i18n'

// Il log del server, a portata di mano.
//
// L'endpoint esisteva da sempre (GET /api/tools/logs, le ultime 100 righe)
// ma non lo chiamava nessuno: per leggerlo bisognava farsi un token a mano
// con curl. Due volte in una sola giornata di lavoro un problema reale si e'
// fermato li' — "non riesce a scaricare sul Kindle", "ricalcolo non
// riuscito" — e ogni volta e' costato un giro di richieste in piu' solo per
// arrivare alla riga che diceva cosa fosse successo.
//
// Nessun aggiornamento automatico: un log che si ricarica da solo mentre lo
// si legge e' piu' fastidioso che utile. Si preme, si guarda.
export function ServerLogSection() {
  const { t } = useLingua()
  const [righe, setRighe] = useState<string[] | null>(null)
  const [caricamento, setCaricamento] = useState(false)
  const [errore, setErrore] = useState<string | null>(null)
  const [copiato, setCopiato] = useState(false)

  async function carica() {
    setCaricamento(true)
    setErrore(null)
    try {
      const { data, error } = await api.GET('/api/tools/logs', {})
      if (error) throw error
      const elenco = (data as unknown as string[]) ?? []
      setRighe(elenco.map((r) => r.replace(/\n$/, '')))
    } catch {
      setErrore(t('settings.serverLog.loadError'))
    } finally {
      setCaricamento(false)
    }
  }

  async function copia() {
    if (!righe) return
    try {
      await navigator.clipboard.writeText(righe.join('\n'))
      setCopiato(true)
      setTimeout(() => setCopiato(false), 2000)
    } catch {
      // Senza permesso per gli appunti resta la selezione a mano: il
      // riquadro qui sotto e' testo normale, selezionabile.
    }
  }

  return (
    <SettingsSection label={t('settings.serverLog.label')}>
      <SettingsRow
        name={t('settings.serverLog.rowName')}
        description={t('settings.serverLog.rowDescription')}
        last={!righe}
      >
        <div className="flex gap-1.5">
          {righe && righe.length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => void copia()}>
              <ClipboardCopy className="size-3.5" />
              {copiato ? t('settings.serverLog.copied') : t('settings.serverLog.copy')}
            </Button>
          )}
          <Button variant="outline" size="sm" disabled={caricamento} onClick={() => void carica()}>
            {caricamento ? <Loader2 className="size-3.5 animate-spin" /> : <ScrollText className="size-3.5" />}
            {righe ? t('settings.serverLog.refresh') : t('settings.serverLog.show')}
          </Button>
        </div>
      </SettingsRow>

      {errore && <p className="pt-3 text-[12.5px] text-destructive">{errore}</p>}

      {righe && righe.length === 0 && (
        <p className="pt-3 text-[12.5px] text-muted-foreground">{t('settings.serverLog.empty')}</p>
      )}

      {righe && righe.length > 0 && (
        // Le righe piu' RECENTI in alto: chi apre un log dopo un errore
        // cerca l'ultima cosa successa, non la prima.
        <pre className="mt-3.5 max-h-[340px] overflow-auto rounded-md border border-border bg-[var(--surface-sunken,var(--card))] p-2.5 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
          {[...righe].reverse().join('\n')}
        </pre>
      )}

      <SettingsHint>{t('settings.serverLog.hint')}</SettingsHint>
    </SettingsSection>
  )
}
