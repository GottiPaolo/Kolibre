import { X } from 'lucide-react'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { useSettingsDialog, type SettingsPaneId } from '@/lib/settingsDialogContext'
import { ProfileTab } from '@/pages/Settings/ProfileTab'
import { PeopleTab } from '@/pages/Settings/PeopleTab'
import { AspectTab } from '@/pages/Settings/AspectTab'
import { LibrariesTab } from '@/pages/Settings/LibrariesTab'
import { BulkOperationsTab } from '@/pages/Settings/BulkOperationsTab'
import { DevicesSettingsTab } from '@/pages/Settings/DevicesSettingsTab'
import { IntegrationsTab } from '@/pages/Settings/IntegrationsTab'
import { SystemTab } from '@/pages/Settings/SystemTab'
import { useLingua, type Valori } from '@/lib/i18n'

// Guscio delle Impostazioni: modale sovrapposta all'app con barra laterale di
// categorie e contenuto verticale, al posto della vecchia pagina con sei tab
// orizzontali (redesign in stile Obsidian approvato sul prototipo).
//
// Le categorie sono raggruppate invece che in fila: con sette voci piatte
// bisogna leggerle tutte per capire dove sta una cosa, mentre i gruppi
// ("Contenuti", "Collegamenti", …) restringono la ricerca a colpo d'occhio.
interface PaneDef {
  id: SettingsPaneId
  label: string
  title: string
  subtitle: string
  Component: () => React.JSX.Element
}

// Funzione e non oggetto costante: deve ricalcolarsi al cambio lingua, come
// fixedColumnLabels in lib/libraryColumns.ts.
function groups(t: (chiave: string, valori?: Valori) => string): { group: string; panes: PaneDef[] }[] {
  return [
    {
      group: t('settings.nav.group.general'),
      panes: [
        {
          id: 'profilo',
          label: t('settings.nav.profile.label'),
          title: t('settings.nav.profile.title'),
          subtitle: t('settings.nav.profile.subtitle'),
          Component: ProfileTab,
        },
        {
          id: 'persone',
          label: t('settings.nav.people.label'),
          title: t('settings.nav.people.title'),
          subtitle: t('settings.nav.people.subtitle'),
          Component: PeopleTab,
        },
        {
          id: 'aspetto',
          label: t('settings.nav.aspect.label'),
          title: t('settings.nav.aspect.title'),
          subtitle: t('settings.nav.aspect.subtitle'),
          Component: AspectTab,
        },
      ],
    },
    {
      group: t('settings.nav.group.content'),
      panes: [
        {
          id: 'librerie',
          label: t('settings.nav.libraries.label'),
          title: t('settings.nav.libraries.title'),
          subtitle: t('settings.nav.libraries.subtitle'),
          Component: LibrariesTab,
        },
        {
          id: 'massa',
          label: t('settings.nav.bulkOperations.label'),
          title: t('settings.nav.bulkOperations.title'),
          subtitle: t('settings.nav.bulkOperations.subtitle'),
          Component: BulkOperationsTab,
        },
      ],
    },
    {
      group: t('settings.nav.group.connections'),
      panes: [
        {
          id: 'dispositivi',
          label: t('settings.nav.devices.label'),
          title: t('settings.nav.devices.title'),
          subtitle: t('settings.nav.devices.subtitle'),
          Component: DevicesSettingsTab,
        },
        {
          id: 'integrazioni',
          label: t('settings.nav.integrations.label'),
          title: t('settings.nav.integrations.title'),
          subtitle: t('settings.nav.integrations.subtitle'),
          Component: IntegrationsTab,
        },
      ],
    },
    {
      group: t('settings.nav.group.advanced'),
      panes: [
        {
          id: 'sistema',
          label: t('settings.nav.system.label'),
          title: t('settings.nav.system.title'),
          subtitle: t('settings.nav.system.subtitle'),
          Component: SystemTab,
        },
      ],
    },
  ]
}

export function SettingsDialog() {
  const { t } = useLingua()
  const { open, pane, setPane, closeSettings } = useSettingsDialog()
  const GROUPS = groups(t)
  const ALL_PANES = GROUPS.flatMap((g) => g.panes)
  const active = ALL_PANES.find((p) => p.id === pane) ?? ALL_PANES[0]
  const ActivePane = active.Component

  return (
    <Dialog open={open} onOpenChange={(next) => !next && closeSettings()}>
      <DialogContent
        showCloseButton={false}
        // Azzera padding/gap/larghezza del DialogContent generico: qui il
        // layout è una griglia a tutta altezza, non una scheda con contenuto.
        // Su telefono occupa tutto lo schermo (come fa Obsidian sul suo
        // mobile): con così poco spazio una finestrella con i margini
        // intorno toglierebbe righe utili senza dare nulla in cambio.
        className="grid h-screen w-screen max-w-none grid-cols-1 grid-rows-[auto_1fr] gap-0 overflow-hidden rounded-none p-0 sm:h-[min(700px,calc(100vh-4rem))] sm:w-[min(1060px,calc(100%-2rem))] sm:grid-cols-[218px_1fr] sm:grid-rows-1 sm:rounded-xl"
      >
        <DialogTitle className="sr-only">{t('settings.nav.title')}</DialogTitle>

        <nav
          aria-label={t('settings.nav.ariaLabel')}
          className="flex gap-1.5 overflow-x-auto border-b border-border bg-sidebar p-2.5 sm:flex-col sm:gap-0.5 sm:overflow-x-visible sm:overflow-y-auto sm:border-r sm:border-b-0 sm:p-2.5"
        >
          <h2 className="hidden px-2.5 pt-1.5 pb-3 font-serif text-[15px] font-semibold sm:block">{t('settings.nav.title')}</h2>
          {GROUPS.map(({ group, panes }) => (
            <div key={group} className="contents sm:block">
              <div className="hidden px-2.5 pt-3.5 pb-1 text-[10px] font-semibold tracking-[0.09em] text-[var(--text-faint)] uppercase sm:block">
                {group}
              </div>
              {panes.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  aria-current={p.id === pane}
                  onClick={() => setPane(p.id)}
                  className={cn(
                    'shrink-0 rounded-md px-2.5 py-1.5 text-left text-[13px] whitespace-nowrap transition-colors sm:w-full',
                    p.id === pane
                      ? 'bg-primary/15 font-medium text-primary'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="flex min-w-0 flex-col">
          <header className="flex items-baseline justify-between gap-4 border-b border-border px-5 pt-4 pb-3 sm:px-6 sm:pt-5">
            <div className="min-w-0">
              <h1 className="font-serif text-[21px] font-semibold">{active.title}</h1>
              <p className="mt-0.5 max-w-[52ch] text-[12.5px] text-muted-foreground">{active.subtitle}</p>
            </div>
            <button
              type="button"
              onClick={closeSettings}
              aria-label={t('settings.nav.closeAriaLabel')}
              className="shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          </header>

          {/* key: rimonta il contenuto cambiando categoria, così lo scroll
              riparte dall'alto e nessuna scheda eredita lo stato di un'altra. */}
          <div key={active.id} className="min-h-0 flex-1 overflow-y-auto px-5 pt-0 pb-7 sm:px-6">
            <ActivePane />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
