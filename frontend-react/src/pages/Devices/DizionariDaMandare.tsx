import { useState } from 'react'
import { BookA, Hourglass, Send, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useDictionaries } from '@/lib/dictionaryActions'
import {
  accodaDizionarioPerDispositivo,
  annullaDizionarioPerDispositivo,
  deviceErrorDetail,
} from '@/lib/deviceActions'
import { toast } from '@/lib/toast'
import { useLingua } from '@/lib/i18n'
import type { Device } from '@/types/device'

// I dizionari da mandare a un lettore, dalla scheda del lettore.
//
// **Cos'è cambiato, e perché.** Prima si scaricavano dal dispositivo: il
// plugin aveva una voce di menù «Scarica dizionario italiano», permanente su
// ogni lettore, per un'azione che si fa una volta nella vita del dispositivo
// — e per un solo dizionario, scritto dentro il nome della voce. Chiesto da
// Paolo il 03/11 di rovesciarla: si manda da qui, e per l'italiano come per
// l'inglese.
//
// **Perché dice «in partenza» e non «mandato».** Un server non può
// raggiungere un e-reader: è il lettore che si fa vivo quando è accesso e ha
// la rete. Quindi questo bottone mette in coda, e il dizionario parte alla
// prima sincronizzazione completa del lettore. Chiamarlo «invia» prometterebbe
// una cosa che non succede subito, e il tempo fra le due è un tempo in cui si
// cerca il difetto.
//
// **Si offre solo quello che il server ha installato.** Senza i file, il
// lettore chiederebbe un manifest che risponde 404 e la voce resterebbe in
// coda per sempre; il server rifiuta già quel caso (409), qui semplicemente
// non si mostra un bottone che darebbe errore.
export function DizionariDaMandare({ device, onChange }: { device: Device; onChange: () => void }) {
  const { t } = useLingua()
  const { data: dizionari } = useDictionaries()
  const [inCorso, setInCorso] = useState<string | null>(null)

  const inCoda = device.dizionari_richiesti ?? []
  const installati = (dizionari ?? []).filter((d) => d.installed)
  const nome = (lang: string) => installati.find((d) => d.lang === lang)?.display_name ?? lang
  const daOffrire = installati.filter((d) => !inCoda.includes(d.lang))

  async function manda(lang: string) {
    setInCorso(lang)
    try {
      await accodaDizionarioPerDispositivo(device.id, lang)
      toast.success(t('devices.dictionaries.queued', { name: nome(lang), device: device.name }))
    } catch (e) {
      toast.error(deviceErrorDetail(e, t('devices.dictionaries.queueError')))
    } finally {
      setInCorso(null)
      onChange()
    }
  }

  async function annulla(lang: string) {
    setInCorso(lang)
    try {
      await annullaDizionarioPerDispositivo(device.id, lang)
    } catch (e) {
      toast.error(deviceErrorDetail(e, t('devices.dictionaries.cancelError')))
    } finally {
      setInCorso(null)
      onChange()
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <strong className="inline-flex items-center gap-1 text-foreground">
        <BookA className="h-3 w-3" aria-hidden />
        {t('devices.detail.dictionariesLabel')}
      </strong>

      {inCoda.map((lang) => (
        <span key={lang} className="inline-flex items-center gap-1 text-[var(--warning)]">
          <Hourglass className="h-3 w-3" aria-hidden />
          {t('devices.dictionaries.pending', { name: nome(lang) })}
          <button
            type="button"
            className="ml-0.5 rounded p-0.5 hover:bg-muted disabled:opacity-50"
            title={t('devices.dictionaries.cancel')}
            disabled={inCorso === lang}
            onClick={() => void annulla(lang)}
          >
            <X className="h-3 w-3" aria-hidden />
          </button>
        </span>
      ))}

      {installati.length === 0 ? (
        <span>{t('devices.dictionaries.noneOnServer')}</span>
      ) : (
        daOffrire.map((d) => (
          <Button
            key={d.lang}
            variant="outline"
            size="sm"
            className="h-6 gap-1 px-2 text-[11px]"
            disabled={inCorso === d.lang}
            onClick={() => void manda(d.lang)}
          >
            <Send className="h-3 w-3" aria-hidden />
            {t('devices.dictionaries.send', { name: d.display_name })}
          </Button>
        ))
      )}
    </div>
  )
}
