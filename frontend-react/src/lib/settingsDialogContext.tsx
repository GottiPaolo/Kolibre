import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

// Le Impostazioni non sono più una pagina con tab orizzontali ma una modale
// sovrapposta all'app (redesign in stile Obsidian approvato sul prototipo):
// serve quindi uno stato globale, perché ad aprirla sono più punti — la voce
// nella barra laterale, la scorciatoia Cmd/Ctrl+, e la rotta /impostazioni tenuta
// viva per i preferiti già salvati (vedi router.tsx).
export type SettingsPaneId =
  | 'profilo'
  | 'persone'
  | 'aspetto'
  | 'librerie'
  | 'massa'
  | 'dispositivi'
  | 'integrazioni'
  | 'sistema'

interface SettingsDialogValue {
  open: boolean
  pane: SettingsPaneId
  openSettings: (pane?: SettingsPaneId) => void
  setPane: (pane: SettingsPaneId) => void
  closeSettings: () => void
}

const SettingsDialogContext = createContext<SettingsDialogValue | null>(null)

export function SettingsDialogProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [pane, setPane] = useState<SettingsPaneId>('profilo')

  const openSettings = useCallback((next?: SettingsPaneId) => {
    if (next) setPane(next)
    setOpen(true)
  }, [])

  const closeSettings = useCallback(() => setOpen(false), [])

  // Cmd+, su macOS / Ctrl+, altrove: la scorciatoia che qualunque app con
  // impostazioni modali usa, Obsidian compreso. Ignorata mentre si sta
  // scrivendo in un campo, per non rubare la virgola a chi digita.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== ',' || !(e.metaKey || e.ctrlKey)) return
      const el = e.target as HTMLElement | null
      if (el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))) return
      e.preventDefault()
      setOpen((prev) => !prev)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const value = useMemo(
    () => ({ open, pane, openSettings, setPane, closeSettings }),
    [open, pane, openSettings, closeSettings]
  )

  return <SettingsDialogContext.Provider value={value}>{children}</SettingsDialogContext.Provider>
}

export function useSettingsDialog() {
  const ctx = useContext(SettingsDialogContext)
  if (!ctx) throw new Error('useSettingsDialog deve essere usato dentro <SettingsDialogProvider>')
  return ctx
}
