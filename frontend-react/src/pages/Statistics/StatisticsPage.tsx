import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LineChart, Settings2, Library as LibraryIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useLibraries } from '@/lib/queries'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { useLingua } from '@/lib/i18n'
import { LibraryStatsTab } from './LibraryStatsTab'
import { ReadingStatsTab } from './ReadingStatsTab'
import { ChartConfigDialog } from './ChartConfigDialog'
import { useChartVisibility } from './chartConfig'

// L'ambito "tutte le biblioteche", come lo scrive il server (vedi
// stats_service.AMBITO_TUTTE).
const TUTTE = '*'

export function StatisticsPage() {
  const { t } = useLingua()
  const navigate = useNavigate()
  const { data: libraries } = useLibraries()
  const [activeLibraryId, setActiveLibraryId] = useState<number | null>(null)
  const activeLibrary = useMemo(
    () => libraries?.find((l) => l.id === activeLibraryId) ?? libraries?.[0],
    [libraries, activeLibraryId]
  )

  const [tab, setTab] = useState<'library' | 'reading'>('reading')
  const [showConfig, setShowConfig] = useState(false)
  const visibility = useChartVisibility()

  // La lettura non ha una biblioteca, il catalogo sì.
  //
  // Erano entrambe legate al menù in cima, e per la lettura era sbagliato:
  // quanto ho letto in vita mia non è una proprietà di una cartella, e sui dati
  // reali la lettura e il catalogo stanno in posti diversi — la biblioteca
  // personale ha le sessioni, il magazzino ha i libri. Il menù costringeva a
  // scegliere fra una storia ricca e un catalogo ricco, e nessuna delle due
  // scelte rispondeva alla domanda. Dal 01/10/2026 la scheda Lettura è sempre
  // su tutte le biblioteche e il menù non la riguarda più; la scheda Libreria
  // resta per forza su UNA, perché un catalogo unico non esiste.
  useSetPageHeader(
    tab === 'library'
      ? activeLibrary
        ? t('stats.pageTitle.library', { name: activeLibrary.name })
        : t('stats.pageTitle.default')
      : t('stats.pageTitle.reading')
  )

  return (
    <Tabs value={tab} onValueChange={(v) => setTab(v as 'library' | 'reading')} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <TabsList>
          <TabsTrigger value="reading">{t('stats.tab.reading')}</TabsTrigger>
          <TabsTrigger value="library">{t('stats.tab.library')}</TabsTrigger>
        </TabsList>

        {/* Il menù compare solo dove ha un effetto. Lasciarlo visibile sulla
            scheda Lettura, inerte, farebbe credere che i numeri lì siano di una
            biblioteca sola. */}
        {tab === 'library' && libraries && libraries.length > 1 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm">
                <LibraryIcon className="size-3.5" />
                {activeLibrary?.name}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {libraries.map((lib) => (
                <DropdownMenuItem key={lib.id} onSelect={() => setActiveLibraryId(lib.id)}>
                  {lib.name}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        <Button
          variant="outline"
          size="sm"
          className="ml-auto"
          onClick={() =>
            navigate(
              tab === 'library' && activeLibrary
                ? `/statistiche/grafici?library=${encodeURIComponent(activeLibrary.folder_name)}`
                : `/statistiche/grafici?library=${encodeURIComponent(TUTTE)}`
            )
          }
        >
          <LineChart className="size-3.5" />
          {t('stats.customCharts')}
        </Button>

        <Button variant="outline" size="sm" onClick={() => setShowConfig(true)}>
          <Settings2 className="size-3.5" />
          {t('stats.configureCharts')}
        </Button>
      </div>

      <TabsContent value="reading">
        {/* Sempre TUTTE: vedi il commento sopra. */}
        <ReadingStatsTab libraryFolder={TUTTE} visibility={visibility} />
      </TabsContent>
      <TabsContent value="library">
        <LibraryStatsTab libraryFolder={activeLibrary?.folder_name} visibility={visibility} />
      </TabsContent>

      {showConfig && (
        <ChartConfigDialog isVisible={visibility.isVisible} toggle={visibility.toggle} onClose={() => setShowConfig(false)} />
      )}
    </Tabs>
  )
}
