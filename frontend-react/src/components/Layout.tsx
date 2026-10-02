import { Suspense, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Library, Settings, ChevronLeft, Menu } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { BookActionsProvider } from '@/lib/bookActionsContext'
import { PageHeaderProvider, usePageHeader } from '@/lib/pageHeaderContext'
import { SettingsDialogProvider, useSettingsDialog } from '@/lib/settingsDialogContext'
import { SettingsDialogHost } from '@/components/settings/SettingsDialogHost'
import { ConnectionStatus } from '@/components/ConnectionStatus'
import { useScrollMemory } from '@/lib/useScrollMemory'
import { Toaster } from '@/components/Toaster'
import { cn } from '@/lib/utils'
import { useStyleVariant } from '@/lib/useStyleVariant'
import { useIsDesktop } from '@/lib/useMediaQuery'
import { useMe } from '@/lib/settingsActions'
import { withBackendUrl } from '@/lib/backendUrl'
import { KolibreLogo } from '@/components/KolibreLogo'
import { loadSidebarLayout, SIDEBAR_PAGE_DEFS, type SidebarPageId } from '@/lib/sidebarLayout'
import { useLingua } from '@/lib/i18n'
import { leggiLocale, scriviLocale } from '@/lib/memoriaLocale'

const SIDEBAR_STORAGE_KEY = 'kolibre_sidebar_collapsed'

// Percorsi delle voci gestibili dal costruttore sidebar di Impostazioni ▸
// Aspetto (vedi lib/sidebarLayout.ts) — Libreria e Impostazioni restano
// fisse (prima/ultima) e non fanno parte di quell'elenco.
const SIDEBAR_PAGE_PATHS: Record<SidebarPageId, string> = {
  authors: '/autori',
  series: '/serie',
  entities: '/entita',
  annotations: '/annotazioni',
  devices: '/dispositivi',
  statistics: '/statistiche',
  interventions: '/interventi',
  ingest: '/importa',
  vocabulary: '/vocabolario',
}

const navItemClass = (collapsed: boolean, active: boolean) =>
  cn(
    'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13.5px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
    collapsed && 'justify-center px-0',
    active && 'bg-primary/15 text-primary hover:bg-primary/15 hover:text-primary'
  )

function NavItem({ to, label, icon: Icon, collapsed }: { to: string; label: string; icon: typeof Library; collapsed: boolean }) {
  return (
    <NavLink to={to} end={to === '/'} className={({ isActive }) => navItemClass(collapsed, isActive)}>
      <Icon className="size-4 shrink-0" />
      {!collapsed && <span className="whitespace-nowrap">{label}</span>}
    </NavLink>
  )
}

// Impostazioni non è più una pagina ma una modale sovrapposta (stile
// Obsidian, vedi components/settings/SettingsDialog.tsx): la voce resta
// dov'era nella barra laterale, ma apre la modale invece di navigare.
function NavButton({
  label,
  icon: Icon,
  collapsed,
  active,
  onClick,
}: {
  label: string
  icon: typeof Library
  collapsed: boolean
  active: boolean
  onClick: () => void
}) {
  return (
    <button type="button" onClick={onClick} className={cn(navItemClass(collapsed, active), 'w-full text-left')}>
      <Icon className="size-4 shrink-0" />
      {!collapsed && <span className="whitespace-nowrap">{label}</span>}
    </button>
  )
}

export function Layout() {
  // Il provider sta qui fuori dal guscio vero e proprio perché lo usano sia
  // la voce "Impostazioni" nella barra laterale sia le pagine dentro
  // <Outlet/> (la rotta /impostazioni, tenuta viva per i preferiti).
  return (
    <SettingsDialogProvider>
      <LayoutShell />
      <SettingsDialogHost />
      {/* Non disegna nulla finché il server risponde — vedi il file. */}
      <ConnectionStatus />
      <Toaster />
    </SettingsDialogProvider>
  )
}

function LayoutShell() {
  const { t } = useLingua()
  const { open: settingsOpen, openSettings } = useSettingsDialog()
  const [collapsed, setCollapsed] = useState(() => leggiLocale(SIDEBAR_STORAGE_KEY) === '1')
  // Applica subito lo stile di default ("sake") — il selettore vero e
  // proprio vive in Impostazioni ▸ Aspetto.
  useStyleVariant()
  const location = useLocation()
  const { data: me } = useMe()
  // `?t=` con l'id: la foto sta su un URL fisso per utente, quindi dopo un
  // cambio il browser mostrerebbe quella vecchia dalla cache.
  const fotoProfilo = me?.photo_url ? withBackendUrl(`${me.photo_url}?t=${me.id}`) : null

  // Sotto "md" la sidebar diventa un drawer a comparsa (fuori schermo di
  // default, aperto dall'hamburger in topbar) invece della barra
  // comprimibile — i due modi non convivono sullo stesso breakpoint, quindi
  // "collapsed" (solo desktop) va ignorato per il rendering (etichette
  // nascoste ecc.) quando siamo in modalità drawer, altrimenti un utente che
  // ha compresso la barra su desktop e poi apre l'app su tablet si
  // ritroverebbe un drawer largo ma senza etichette.
  // Il contenitore che scorre davvero per quasi tutte le pagine (Autori,
  // Serie, Annotazioni...): ricordarne la posizione è ciò che fa tornare
  // "indietro" al punto in cui si era, invece che in cima.
  const pageScrollRef = useRef<HTMLDivElement>(null)
  useScrollMemory(pageScrollRef, 'pagina')

  const isDesktop = useIsDesktop()
  const effectiveCollapsed = collapsed && isDesktop
  const [drawerOpen, setDrawerOpen] = useState(false)
  useEffect(() => {
    if (isDesktop) setDrawerOpen(false)
  }, [isDesktop])
  // Letto una sola volta al mount (come collapsed sopra): il
  // costruttore drag-and-drop in Impostazioni ▸ Aspetto scrive sulla stessa
  // chiave, ma un cambiamento lì si riflette qui al prossimo reload, non a
  // caldo — nessun altro stato in questo file è reattivo tra tab diverse.
  const [sidebarLayout] = useState(() => loadSidebarLayout())

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev
      scriviLocale(SIDEBAR_STORAGE_KEY, next ? '1' : '0')
      return next
    })
  }

  return (
    // h-screen + overflow-hidden (non min-h-screen): senza un'altezza fissa
    // sul contenitore, una pagina con contenuto più alto del viewport (es.
    // Autori con molti autori) faceva crescere l'intero documento e
    // scorrere la PAGINA — la sidebar qui sotto è "static" da md in su (non
    // "fixed"), quindi scorreva via insieme al resto invece di restare
    // ferma. Ora è il contenitore scrollabile dentro <main> (sotto) a
    // scorrere da solo, la sidebar (e la Topbar) restano fuori da quel
    // flusso e quindi sempre visibili — difetto riscontrato in uso.
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      {/* Backdrop del drawer mobile: chiude al tap fuori, mai presente da
          md in su (lì la sidebar non è mai "aperta/chiusa" come overlay). */}
      {drawerOpen && (
        <div
          onClick={() => setDrawerOpen(false)}
          aria-hidden="true"
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
        />
      )}

      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-[224px] shrink-0 flex-col border-r border-border bg-sidebar px-3 py-5 transition-transform duration-200 md:static md:z-auto md:translate-x-0 md:transition-[width]',
          drawerOpen ? 'translate-x-0' : '-translate-x-full',
          collapsed ? 'md:w-[60px] md:px-2' : 'md:w-[224px]'
        )}
      >
        <div className={cn('flex items-center gap-2 px-2 pb-5', effectiveCollapsed && 'justify-center px-0')}>
          <KolibreLogo className="size-9" />
          {!effectiveCollapsed && <span className="font-serif text-[17px] font-semibold whitespace-nowrap">Kolibre</span>}
        </div>

        {/* Chiude il drawer alla navigazione (click su una voce) — no-op sopra
            "md", dove drawerOpen resta sempre false. */}
        <nav className="flex flex-col gap-0.5" onClick={() => setDrawerOpen(false)}>
          <NavItem to="/" label={t('nav.library')} icon={Library} collapsed={effectiveCollapsed} />
          {sidebarLayout.map((entry, i) =>
            entry.type === 'separator' ? (
              <div key={`sep-${i}`} className="my-1.5 border-t border-border/60" />
            ) : (
              <NavItem
                key={entry.id}
                to={SIDEBAR_PAGE_PATHS[entry.id]}
                label={t(SIDEBAR_PAGE_DEFS[entry.id].labelKey)}
                icon={SIDEBAR_PAGE_DEFS[entry.id].icon}
                collapsed={effectiveCollapsed}
              />
            )
          )}
          <div className="h-4" />
          <NavButton
            label={t('nav.settings')}
            icon={Settings}
            collapsed={effectiveCollapsed}
            active={settingsOpen}
            onClick={() => openSettings()}
          />
        </nav>

        {/* In fondo sta CHI sta usando il programma, non quale build gira.
            Prima c'erano la versione e l'orario di build: servivano durante
            lo sviluppo per capire a colpo d'occhio se un deploy fosse andato
            a buon fine, e sono rimasti li' per abitudine. In un programma
            multiutente quell'angolo risponde a una domanda piu'
            utile — «con quale account sto guardando questa biblioteca?» —
            e la versione, che serve ancora, vive in Impostazioni ▸ Sistema.

            Cliccabile: porta al proprio profilo, che e' dove si cambiano
            nome, foto e password. */}
        <div className={cn('mt-auto flex items-center gap-2 px-1.5 pt-2.5', effectiveCollapsed && 'justify-center px-0')}>
          <button
            onClick={() => openSettings('profilo')}
            title={me ? t('nav.profileTitle', { user: me.username }) : t('nav.profile')}
            className={cn(
              'flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-1 text-left transition-colors hover:bg-accent',
              effectiveCollapsed && 'flex-none justify-center px-0'
            )}
          >
            {fotoProfilo ? (
              <img src={fotoProfilo} alt="" className="size-6 shrink-0 rounded-full object-cover" />
            ) : (
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-medium text-muted-foreground">
                {(me?.username ?? '?').slice(0, 1).toUpperCase()}
              </span>
            )}
            {!effectiveCollapsed && (
              <span className="truncate text-[12px] text-foreground/90">{me?.username ?? '—'}</span>
            )}
          </button>
          {/* Comprimi/espandi: concetto solo desktop, nel drawer mobile non
              esiste (il drawer è sempre a larghezza piena quando aperto). */}
          <button
            onClick={toggleCollapsed}
            aria-label="Comprimi/espandi barra laterale"
            className="hidden size-6 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-foreground md:flex"
          >
            <ChevronLeft className={cn('size-3.5 transition-transform', collapsed && 'rotate-180')} />
          </button>
        </div>
      </aside>

      <PageHeaderProvider>
        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <Topbar onOpenDrawer={() => setDrawerOpen(true)} />

          {/* id usato da ChartBuilderPage per uno scrollTo mirato (window.
              scrollTo non avrebbe più effetto: la finestra stessa non
              scorre più, solo questo contenitore). */}
          {/* `relative` non e' decorativo: senza, un discendente in
              `position: absolute` che non ha nessun antenato posizionato prende
              come blocco contenitore il DOCUMENTO, e `overflow` qui non lo
              ritaglia — il documento si allunga fino a contenerlo e si scorre
              oltre la fine della pagina, portandosi via anche la barra
              laterale. Capitava con la classe `sr-only` di Tailwind, che e'
              `position: absolute`: il « (oggi )» del Calendario di Lettura
              stava a 1.945px e regalava 1.046px di scorrimento fantasma
              (misurato il 01/10/2026 su Chromium e WebKit, identico).
              Con `relative` ogni assoluto senza antenato posizionato si ancora
              qui, e ci scorre dentro. */}
          <div ref={pageScrollRef} id="page-scroll-container" className="relative flex-1 overflow-y-auto p-4 md:p-7">
            {/* mode="popLayout" (not "wait"): the outgoing page's exit fade and
                the incoming page's enter fade now run at the same time
                instead of sequentially — "wait" was forcing every navigation
                to sit through the full exit animation before the new page
                even mounted, adding a fixed ~320ms (2 × the 0.16s
                transition) before its own Suspense fallback/data fetch could
                even start. popLayout pulls the exiting element out of
                document flow (position: absolute) while it fades, so the
                incoming page can take its place immediately without a
                layout jump. initial={false} also skips the enter animation
                on the very first paint of the app — nothing to cross-fade
                from yet, so it was pure added delay before first content. */}
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.div
                key={location.pathname}

                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.16, ease: [0.4, 0, 0.2, 1] }}
              >
                {/* Provider unico per l'app: i dialoghi azione-libro (metadati,
                    TOC, converti, elimina, copia...) vivono qui una sola volta,
                    così sia il context-menu della tabella Libreria sia la
                    pagina Dettaglio libro possono aprirli senza duplicare
                    stato — vedi src/lib/bookActionsContext.tsx. */}
                <BookActionsProvider>
                  {/* Le pagine sono caricate con React.lazy (vedi router.tsx):
                      questo Suspense copre il breve intervallo di download
                      della chunk alla navigazione, prima che React monti la
                      pagina vera e propria. */}
                  <Suspense fallback={<p className="text-muted-foreground">{t('nav.loading')}</p>}>
                    <Outlet />
                  </Suspense>
                </BookActionsProvider>
              </motion.div>
            </AnimatePresence>
          </div>
        </main>
      </PageHeaderProvider>
    </div>
  )
}

// Niente pulsanti/ricerca duplicata qui — solo il nome della pagina/libreria
// corrente, impostato dalla pagina stessa (useSetPageHeader). La ricerca
// vera vive già nel toolbar della pagina Libreria.
function Topbar({ onOpenDrawer }: { onOpenDrawer: () => void }) {
  const { t } = useLingua()
  const header = usePageHeader()
  return (
    <div className="flex items-center gap-2 border-b border-border px-4 py-3.5 md:px-7">
      {/* Hamburger: solo sotto "md", dove la sidebar è un drawer e non è
          altrimenti raggiungibile. */}
      <button
        onClick={onOpenDrawer}
        aria-label={t('nav.openMenu')}
        className="-ml-1 flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground md:hidden"
      >
        <Menu className="size-4.5" />
      </button>
      <h1 className="font-serif text-[16px] font-semibold">{header}</h1>
    </div>
  )
}
