import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { dimenticaVocabolario } from '@/lib/deviceActions'
import { useSovrapposizioniVocabolario, type SovrapposizioneDispositivo } from '@/lib/vocabularyActions'
import { useLingua } from '@/lib/i18n'

// Il riquadro che dice quali dispositivi hanno le stesse identiche parole.
//
// Compare solo quando c'è qualcosa da dire: senza sovrapposizioni non occupa
// spazio. Il numero si vede PRIMA di decidere — è l'unica differenza fra una
// pulizia e una cancellazione alla cieca — e togliere resta una scelta di chi
// guarda, mai un'iniziativa del sistema.
export function SovrapposizioniPanel() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: dispositivi = [] } = useSovrapposizioniVocabolario()
  const [conferma, setConferma] = useState<number | null>(null)
  const [pulendo, setPulendo] = useState(false)
  const [esito, setEsito] = useState<string | null>(null)

  const conDoppie = dispositivi.filter((d) => d.in_comune.length > 0)
  if (conDoppie.length === 0) return null

  async function pulisci(d: SovrapposizioneDispositivo) {
    setPulendo(true)
    try {
      const tolte = await dimenticaVocabolario(d.id)
      setEsito(t('vocabulary.overlap.forgotten', { n: tolte, name: d.nome }))
      setConferma(null)
      await queryClient.invalidateQueries({ queryKey: ['vocabulary'] })
      await queryClient.invalidateQueries({ queryKey: ['vocabolario-sovrapposizioni'] })
    } catch {
      setEsito(t('vocabulary.overlap.error'))
    } finally {
      setPulendo(false)
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border border-[var(--warning)]/40 bg-[var(--warning-soft)] p-3 text-[12.5px]">
      <p className="leading-relaxed">
        {t('vocabulary.overlap.intro.before')}
        <b>{t('vocabulary.overlap.intro.bold')}</b>
        {t('vocabulary.overlap.intro.after')}
      </p>
      {conDoppie.map((d) => (
        <div key={d.id} className="flex flex-col gap-1.5 border-t border-[var(--warning)]/25 pt-2">
          <p className="leading-relaxed">
            <b>{d.nome}</b> — <b className="tabular-nums">{d.parole}</b> {t('vocabulary.overlap.wordsIncluding')}{' '}
            {d.in_comune.map((r) => t('vocabulary.overlap.alsoOn', { n: r.parole, device: r.nome })).join(', ')}.
          </p>
          {conferma !== d.id ? (
            <Button variant="outline" size="xs" className="self-start" onClick={() => setConferma(d.id)}>
              {t('vocabulary.overlap.forgetButton', { name: d.nome })}
            </Button>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <span>
                {t('vocabulary.overlap.confirm.before')} <b className="tabular-nums">{d.parole}</b>{' '}
                {t('vocabulary.overlap.confirm.after', { name: d.nome })}
              </span>
              <Button variant="destructive" size="xs" disabled={pulendo} onClick={() => void pulisci(d)}>
                {pulendo ? t('authors.scrape.inProgress') : t('vocabulary.overlap.confirmButton')}
              </Button>
              <Button variant="ghost" size="xs" onClick={() => setConferma(null)}>
                {t('common.cancel')}
              </Button>
            </div>
          )}
        </div>
      ))}
      {esito && <p className="text-muted-foreground">{esito}</p>}
    </div>
  )
}
