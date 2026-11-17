// La versione del plugin KOReader installata su un dispositivo, messa dove si
// guarda quel dispositivo.
//
// **Da zero: che cos'è il plugin, e perché la sua versione conta.** Il plugin
// è il pezzo di Kolibre che gira dentro KOReader, sul lettore: scarica i
// libri, manda indietro le annotazioni, le posizioni di lettura e le
// statistiche. Il server ne distribuisce una copia, e ogni lettore ha quella
// che si è installato — che può essere più vecchia. Un lettore indietro non si
// rompe: semplicemente non sa fare le cose aggiunte dopo, e quando qualcosa
// «non funziona su quel Kindle» è la prima domanda da farsi.
//
// **Perché sta qui e non in cima alla pagina** (Paolo, 17/11/2026). Fino a
// stamattina era un riquadro in testa all'elenco dei dispositivi, che
// elencava i nomi dei lettori indietro. Paolo lo trova invasivo, e ha chiesto
// che stia «dentro la scheda del singolo dispositivo, come per la patch».
//
// Non è solo una questione di gusto, ed è la stessa ragione per cui le patch
// (`PatchInfo.tsx`) sono fatte così: **l'informazione riguarda un
// dispositivo**, e un riquadro in cima la stacca dalla cosa di cui parla —
// per sapere quale dei quattro lettori è indietro si legge un elenco di nomi
// in alto e poi lo si cerca fra le schede sotto. Nella scheda, invece, non
// c'è niente da cercare: la riga è già accanto al nome. E un avviso in cima
// occupa esattamente il posto in cui deve saltare all'occhio l'avviso vero.
//
// Il confronto è **«più vecchio», non «diverso»**: un lettore con una
// versione più nuova di quella del server — cioè Paolo mentre prova la
// prossima — non va annunciato come indietro, con l'invito ad aggiornarsi a
// una versione precedente. Lo fa `eIndietro` in `lib/versioni`, che confronta
// numero per numero e non come testo (come testo «0.9.0» viene dopo
// «0.10.0»). Vedi la prova `versioni_dei_plugin`.
import { useQuery } from '@tanstack/react-query'
import { Puzzle, RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
import { eIndietro } from '@/lib/versioni'
import { cn } from '@/lib/utils'
import { useLingua } from '@/lib/i18n'
import type { Device } from '@/types/device'

/**
 * Qual è l'ultima versione del plugin, cioè quella che il server distribuisce.
 *
 * È un hook perché la chiedono in due posti — la griglia dei dispositivi e la
 * scheda di uno — e react-query la richiede una volta sola per tutti.
 * L'endpoint esisteva già: lo usa il plugin stesso per chiedersi se
 * aggiornarsi.
 */
export function useUltimaVersioneDelPlugin() {
  return useQuery({
    queryKey: ['versione-plugin-koreader'],
    queryFn: async (): Promise<string | null> => {
      const { data, error } = await api.GET('/api/tools/plugins/koreader/version')
      if (error) throw error
      return data.version ?? null
    },
  })
}

/**
 * La pastiglia con la versione, per la scheda nella griglia.
 *
 * Tre stati, e ognuno dice una cosa diversa:
 *   - **aggiornato**: la versione, in grigio. Non è una buona notizia da
 *     annunciare, è un dato da poter leggere;
 *   - **indietro**: la versione e quella a cui arrivare, nel colore
 *     dell'avviso. Le due insieme perché «v0.19.0» da solo non dice niente a
 *     chi non ricorda a memoria dove è arrivato il server;
 *   - **sconosciuta**: un plugin troppo vecchio non la dichiara. È
 *     un'incertezza, non un guasto, quindi grigia — ma c'è, perché prima
 *     questa scheda non diceva niente e il riquadro in cima diceva «di N
 *     dispositivi non si conosce la versione». Toltolo, quella frase non
 *     avrebbe più avuto un posto.
 */
export function VersioneSullaScheda({ device }: { device: Device }) {
  const { t } = useLingua()
  const { data: ultima } = useUltimaVersioneDelPlugin()

  if (!device.plugin_version) {
    return (
      <span
        className="inline-flex items-center gap-1 text-muted-foreground"
        title={t('devices.pluginVersionUnknownTitle')}
      >
        <Puzzle className="size-3" /> {t('devices.pluginVersionUnknown')}
      </span>
    )
  }

  const indietro = !!ultima && eIndietro(device.plugin_version, ultima)
  return (
    <span
      className={cn('inline-flex items-center gap-1', indietro && 'text-[var(--warning)]')}
      title={
        indietro
          ? t('devices.pluginVersionOutdatedTitle', { latest: ultima as string })
          : t('devices.pluginVersionTitle')
      }
    >
      {indietro ? <RefreshCw className="size-3" /> : <Puzzle className="size-3" />}
      {indietro ? `v${device.plugin_version} → v${ultima}` : `v${device.plugin_version}`}
    </span>
  )
}

/**
 * La riga per la scheda di un dispositivo, accanto a quella delle patch e con
 * la stessa forma: un'etichetta e il suo valore.
 */
export function VersioneNelDettaglio({ device }: { device: Device }) {
  const { t } = useLingua()
  const { data: ultima } = useUltimaVersioneDelPlugin()
  const indietro = !!device.plugin_version && !!ultima && eIndietro(device.plugin_version, ultima)

  return (
    <div>
      <strong className="text-foreground">{t('devices.detail.pluginLabel')}</strong>{' '}
      {!device.plugin_version ? (
        t('devices.pluginVersionUnknown')
      ) : indietro ? (
        <span className="inline-flex items-center gap-1 text-[var(--warning)]">
          <RefreshCw className="size-3.5" />
          {t('devices.detail.pluginOutdated', {
            installed: device.plugin_version,
            latest: ultima as string,
          })}
        </span>
      ) : (
        <>
          v{device.plugin_version}
          {ultima && ` — ${t('devices.detail.pluginUpToDate')}`}
        </>
      )}
    </div>
  )
}
