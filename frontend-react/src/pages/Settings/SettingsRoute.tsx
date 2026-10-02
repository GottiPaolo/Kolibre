import { useEffect } from 'react'
import { Navigate } from 'react-router-dom'
import { useSettingsDialog } from '@/lib/settingsDialogContext'

// Le Impostazioni non sono più una pagina: sono una modale sovrapposta
// all'app (vedi components/settings/SettingsDialog.tsx). La rotta resta viva
// solo per non rompere i preferiti già salvati su /impostazioni — apre la
// modale e riporta l'indirizzo alla Libreria, che è ciò che si vede dietro.
export function SettingsRoute() {
  const { openSettings } = useSettingsDialog()

  useEffect(() => {
    openSettings()
  }, [openSettings])

  return <Navigate to="/" replace />
}
