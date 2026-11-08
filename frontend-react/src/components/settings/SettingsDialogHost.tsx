import { Suspense, useEffect, useState } from 'react'
import { lazyWithReload } from '@/lib/lazyWithReload'
import { useSettingsDialog } from '@/lib/settingsDialogContext'

// La modale Impostazioni è montata da Layout, quindi su OGNI pagina dell'app:
// importarla direttamente trascinerebbe tutte e sette le schede (temi,
// librerie, scorciatoie, dizionari…) dentro la chunk iniziale, disfacendo il
// code-splitting per pagina. Qui viene caricata al primo momento in cui
// serve davvero, cioè quando si aprono le Impostazioni.
//
// Una volta caricata resta montata: smontarla alla chiusura farebbe sparire
// la modale di colpo, senza l'animazione di uscita di Radix.
const SettingsDialog = lazyWithReload(() =>
  import('./SettingsDialog').then((m) => ({ default: m.SettingsDialog }))
)

export function SettingsDialogHost() {
  const { open } = useSettingsDialog()
  const [everOpened, setEverOpened] = useState(false)

  useEffect(() => {
    if (open) setEverOpened(true)
  }, [open])

  if (!everOpened) return null

  return (
    <Suspense fallback={null}>
      <SettingsDialog />
    </Suspense>
  )
}
