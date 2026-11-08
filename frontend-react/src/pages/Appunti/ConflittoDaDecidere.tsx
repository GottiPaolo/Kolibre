// Un brano cambiato in tutte due le parti, e la scelta.
//
// **Perché questa cosa esiste.** Il plugin aggiorna un blocco quando la nota
// cambia in Kolibre, e lascia stare quello che Paolo ha scritto. Ma se lo
// stesso brano è cambiato da tutte due le parti — lui ha corretto un refuso
// nel vault, e intanto è arrivata una risincronizzazione dal lettore —
// nessuno dei due programmi può decidere chi ha ragione. Qui si vedono
// affiancati e si dice quale vince; il plugin lo esegue al prossimo giro.
import { ArrowUpRight, Check, Loader2, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'
import type { ConflittoDiAppunti } from '@/lib/appuntiActions'
import { ConfrontoDeiDueTesti } from './ConfrontoDeiDueTesti'

export function ConflittoDaDecidere({
  conflitto,
  inCorso,
  onScegli,
}: {
  conflitto: ConflittoDiAppunti
  inCorso: boolean
  onScegli: (scelta: 'kolibre' | 'mio' | null) => void
}) {
  const { t } = useLingua()
  const deciso = conflitto.scelta

  return (
    <div className="rounded-md border border-border bg-background p-2.5">
      {/* I due testi affiancati, con le differenze in luce: a sinistra
          l'originale di Kolibre, a destra quella che sta nel tuo vault. */}
      <ConfrontoDeiDueTesti
        inKolibre={conflitto.nel_server}
        nelVault={conflitto.nel_vault}
        evidenzia={deciso === 'mio' ? 'vault' : deciso === 'kolibre' ? 'kolibre' : null}
      />

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {deciso ? (
          <>
            <span className="inline-flex items-center gap-1 text-[12px] text-muted-foreground">
              <Check className="size-3.5 text-primary" />
              {deciso === 'mio' ? t('appunti.conflitto.decisoMio') : t('appunti.conflitto.decisoKolibre')}
            </span>
            <Button size="sm" variant="ghost" disabled={inCorso} onClick={() => onScegli(null)}>
              {inCorso ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCcw className="size-3.5" />}
              {t('appunti.conflitto.annullaScelta')}
            </Button>
          </>
        ) : (
          <>
            <Button size="sm" variant="outline" disabled={inCorso} onClick={() => onScegli('mio')}>
              {t('appunti.conflitto.tieniIlMio')}
            </Button>
            <Button size="sm" variant="outline" disabled={inCorso} onClick={() => onScegli('kolibre')}>
              {t('appunti.conflitto.prendiKolibre')}
            </Button>
          </>
        )}
        {conflitto.link && (
          <a
            href={conflitto.link}
            className="ml-auto inline-flex items-center gap-1 text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            {t('appunti.conflitto.apriInKolibre')}
            <ArrowUpRight className="size-3.5" />
          </a>
        )}
      </div>
    </div>
  )
}
