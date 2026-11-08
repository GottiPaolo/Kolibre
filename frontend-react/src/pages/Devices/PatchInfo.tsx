import { Check, CircleDashed, Puzzle, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLingua } from '@/lib/i18n'
import type { Device, DevicePatchStato } from '@/types/device'

// Le userpatch di KOReader, sulla scheda del dispositivo.
//
// **Cos'è una userpatch, in una riga**: un file Lua che KOReader esegue a
// ogni avvio, per fargli fare qualcosa che non fa. Le nostre si installano
// dal plugin, dal dispositivo (Strumenti → Patch per KOReader), e la prima
// è una misura dei caratteri per pagina.
//
// **Perché serve vederlo da qui.** Una patch si installa sul dispositivo e
// da lì non si vede più: non c'è un posto che dica «su quel Kindle c'è, su
// quel Kobo no», e dopo una modifica alla patch non c'è modo di sapere quale
// versione sta girando dove. È la domanda che Paolo ha posto il 03/11.
//
// Il verdetto arriva già fatto dal server (confronto delle impronte, vedi
// services/patch_koreader.py): qui si disegna, non si decide.

const COLORE: Record<DevicePatchStato['stato'], string> = {
  aggiornata: 'text-[var(--positive)]',
  da_aggiornare: 'text-[var(--warning)]',
  assente: 'text-muted-foreground',
}

function Icona({ stato, className }: { stato: DevicePatchStato['stato']; className?: string }) {
  if (stato === 'aggiornata') return <Check className={className} />
  if (stato === 'da_aggiornare') return <RefreshCw className={className} />
  return <CircleDashed className={className} />
}

/** Una riga per patch, con nome e stato: per la scheda di un dispositivo. */
export function PatchElenco({ device }: { device: Device }) {
  const { t } = useLingua()

  if (!device.patches_riportate) {
    return (
      <div>
        <strong className="text-foreground">{t('devices.detail.patchesLabel')}</strong>{' '}
        {t('devices.patches.notReported')}
      </div>
    )
  }
  if (device.patches.length === 0) {
    return (
      <div>
        <strong className="text-foreground">{t('devices.detail.patchesLabel')}</strong>{' '}
        {t('devices.patches.none')}
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <strong className="text-foreground">{t('devices.detail.patchesLabel')}</strong>
      {device.patches.map((p) => (
        <span
          key={p.file}
          className={cn('inline-flex items-center gap-1', COLORE[p.stato])}
          title={
            p.descrizione +
            (p.stato === 'assente'
              ? `\n\n${t('devices.patches.installTitle')}`
              : p.stato === 'da_aggiornare'
                ? `\n\n${t('devices.patches.outdatedTitle')}`
                : '')
          }
        >
          <Icona stato={p.stato} className="size-3.5" />
          {p.nome} — {t(`devices.patches.${p.stato}`)}
        </span>
      ))}
    </div>
  )
}

/** Il riassunto in una voce sola, per la griglia dei dispositivi. */
export function PatchRiepilogo({ device }: { device: Device }) {
  const { t } = useLingua()
  // Un plugin che non le riporta non fa comparire niente: la pagina ha già
  // il riquadro che avvisa dei plugin da aggiornare, e due avvisi per la
  // stessa causa sono rumore.
  if (!device.patches_riportate || device.patches.length === 0) return null

  const daAggiornare = device.patches.filter((p) => p.stato === 'da_aggiornare').length
  const installate = device.patches.filter((p) => p.stato !== 'assente').length
  const stato: DevicePatchStato['stato'] =
    daAggiornare > 0 ? 'da_aggiornare' : installate > 0 ? 'aggiornata' : 'assente'

  return (
    <span
      className={cn('inline-flex items-center gap-1', COLORE[stato])}
      title={device.patches.map((p) => `${p.nome}: ${t(`devices.patches.${p.stato}`)}`).join('\n')}
    >
      <Puzzle className="size-3" />
      {daAggiornare > 0
        ? t('devices.patches.cardOutdated', { quante: daAggiornare })
        : t('devices.patches.cardAll', { installate, totale: device.patches.length })}
    </span>
  )
}
