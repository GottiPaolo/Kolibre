import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookCheck, ClipboardCheck, Library as LibraryIcon, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api } from '@/lib/api'
import { bulkUpdateBooksMetadata } from '@/lib/bookActions'
import { useCustomColumns, useLibraries } from '@/lib/queries'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { READ_FLAG_COLUMN, READ_FLAG_FIELD } from '@/lib/readFlag'
import { OrphanSessionsPanel } from '@/pages/Statistics/OrphanSessionsPanel'
import { useOrphanSessions } from '@/lib/statsQueries'
import { Copy, Highlighter, BookX, MapPinOff } from 'lucide-react'
import { DuplicatesSection, useQuantiDoppioni } from './DuplicatesSection'
import { OrphanNotesPanel, useQuanteOrfane } from './OrphanNotesPanel'
import { WidowedNotesPanel, useQuanteVedove } from './WidowedNotesPanel'
import { NotesWithoutPositionPanel, useQuanteSenzaPosizione } from './NotesWithoutPositionPanel'
import { SezionePieghevole } from './SezionePieghevole'
import { useLingua, type Valori } from '@/lib/i18n'

// La pagina delle cose che aspettano una persona.
//
// Nasce da un difetto riscontrato in uso: il pannello delle sessioni orfane
// stava in cima alle Statistiche di lettura, cioe' davanti agli occhi ogni
// volta che si voleva vedere quanto si era letto. Una coda di lavoro dentro
// un cruscotto e' fastidiosa quando c'e' e invisibile quando serve davvero.
//
// Qui le voci stanno insieme e si vedono quando si e' deciso di occuparsene.
// Ogni sezione sparisce quando non ha niente in sospeso: una pagina vuota
// vuol dire che non c'e' niente da fare, che e' l'informazione principale.

interface Motivo {
  tipo: 'copertura' | 'colonna'
  colonna?: string
  valore: string | number
}

interface Candidato {
  id: number
  title: string
  author: string
  reasons: Motivo[]
}

const NESSUNA_COLONNA = '__nessuna__'

function descriviMotivo(m: Motivo, t: (chiave: string, valori?: Valori) => string): string {
  if (m.tipo === 'copertura') return t('interventions.readBooks.reasonCoverage', { percent: Math.round(Number(m.valore) * 100) })
  return t('interventions.readBooks.reasonColumnValue', { column: m.colonna ?? '', value: m.valore })
}

export function InterventionsPage() {
  const { t } = useLingua()
  useSetPageHeader(t('interventions.pageTitle'))
  const queryClient = useQueryClient()
  const { data: libraries } = useLibraries()
  const [libraryId, setLibraryId] = useState<number | null>(null)
  const library = useMemo(
    () => libraries?.find((l) => l.id === libraryId) ?? libraries?.[0],
    [libraries, libraryId]
  )
  const folder = library?.folder_name

  // Gli id dei libri sono id Calibre, cioè per biblioteca: gli stessi numeri
  // esistono anche nell'altra. Cambiando biblioteca senza svuotare, i
  // checkbox restavano spuntati su libri mai visti e «Segna come letti (5)»
  // ne marcava cinque sbagliati. Al cambio di COLONNA la selezione si
  // svuotava già; al cambio di biblioteca no.
  useEffect(() => {
    setScelti(new Set())
  }, [folder])

  const { data: customColumns = [] } = useCustomColumns(folder)
  // Le colonne da cui ha senso dedurre "letto": non quella di Kolibre (e'
  // la destinazione) e non quelle numeriche, che non dicono niente sul
  // fatto che un libro sia finito.
  const colonneUtili = customColumns.filter(
    (c) => c.label !== READ_FLAG_COLUMN && ['enumeration', 'text', 'datetime', 'bool'].includes(c.datatype)
  )

  const [colonna, setColonna] = useState<string>(NESSUNA_COLONNA)
  const [valori, setValori] = useState('')
  const [scelti, setScelti] = useState<Set<number>>(new Set())
  const quantiDoppioni = useQuantiDoppioni(folder)
  const quanteVedove = useQuanteVedove()
  const quanteOrfane = useQuanteOrfane()
  const quanteSenzaPosizione = useQuanteSenzaPosizione()
  const [salvando, setSalvando] = useState(false)
  const [esito, setEsito] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['interventi-letti', folder, colonna, valori],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/interventions/books-to-mark-read', {
        params: {
          query: {
            library: folder,
            ...(colonna !== NESSUNA_COLONNA ? { column: colonna } : {}),
            ...(valori.trim() ? { values: valori.trim() } : {}),
          },
        },
      })
      if (error) throw error
      return data as unknown as { candidates: Candidato[]; already_marked: number }
    },
    enabled: !!folder,
  })

  const candidati = data?.candidates ?? []

  function commuta(id: number) {
    setScelti((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  async function confermaScelti() {
    if (!folder || scelti.size === 0) return
    setSalvando(true)
    setEsito(null)
    try {
      const quanti = scelti.size
      await bulkUpdateBooksMetadata(folder, [...scelti], { fields: { [READ_FLAG_FIELD]: true } })
      setScelti(new Set())
      setEsito(t('interventions.readBooks.markedAsRead', { count: quanti, n: quanti }))
      queryClient.invalidateQueries({ queryKey: ['interventi-letti'] })
      queryClient.invalidateQueries({ queryKey: ['books', folder] })
      queryClient.invalidateQueries({ queryKey: ['books-page', folder] })
    } catch {
      setEsito(t('interventions.readBooks.markFailed'))
    }
    setSalvando(false)
  }

  // Vale per la pagina intera: prima guardava solo i libri da spuntare, e
  // con note e doppioni in attesa diceva comunque "niente in sospeso".
  const { data: sessioniOrfane } = useOrphanSessions()

  const nienteDaFare =
    !isLoading &&
    candidati.length === 0 &&
    (quantiDoppioni ?? 0) === 0 &&
    (quanteVedove ?? 0) === 0 &&
    (quanteOrfane ?? 0) === 0 &&
    (sessioniOrfane?.count ?? 0) === 0

  return (
    <div className="flex flex-col gap-5">
      {libraries && libraries.length > 1 && library && (
        <div className="flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm">
                <LibraryIcon className="size-3.5" />
                {library.name}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {libraries.map((lib) => (
                <DropdownMenuItem key={lib.id} onSelect={() => setLibraryId(lib.id)}>
                  {lib.name}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}

      {/* Riordinata il 28/09/2026: le voci stanno per SOGGETTO — prima i
          libri, poi le annotazioni, poi le letture — invece che nell'ordine
          in cui sono nate. Chi apre questa pagina arriva da un sintomo ("ho
          visto un doppione", "una nota non si apre"), e il sintomo ha sempre
          un soggetto.

          Ogni voce resta chiusa e mostra quante cose aspettano: la pagina
          deve prima dire QUANTO lavoro c'e' e di che tipo, il dettaglio
          viene su richiesta. Con le sezioni aperte i doppioni occupavano da
          soli tutta la finestra e le altre voci non si vedevano nemmeno. */}
      <h2 className="text-[10.5px] font-semibold tracking-[0.09em] text-[var(--text-faint)] uppercase">
        {t('interventions.page.bookHeading')}
      </h2>
      <SezionePieghevole
        titolo={t('interventions.duplicates.sectionTitle')}
        icona={Copy}
        quante={quantiDoppioni}
        descrizione={t('interventions.duplicates.sectionDescription')}
      >
        <DuplicatesSection libraryFolder={folder} />
      </SezionePieghevole>

      <SezionePieghevole
        titolo={t('interventions.readBooks.sectionTitle')}
        icona={BookCheck}
        quante={candidati.length}
        descrizione={t('interventions.readBooks.sectionDescription')}
      >
        <p className="mb-3 text-[12.5px] text-muted-foreground">
          {t('interventions.readBooks.explainIntro')}
          <em> {t('interventions.readBooks.explainEmphasis')}</em>
          {t('interventions.readBooks.explainOutro')}
        </p>

        {colonneUtili.length > 0 && (
          <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md bg-muted/40 p-2.5">
            <span className="text-[12px] text-muted-foreground">{t('interventions.readBooks.deduceFromColumn')}</span>
            <Select value={colonna} onValueChange={(v) => { setColonna(v); setScelti(new Set()) }}>
              <SelectTrigger className="h-7 w-[240px] text-[12px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NESSUNA_COLONNA}>{t('interventions.readBooks.noColumnOption')}</SelectItem>
                {colonneUtili.map((c) => (
                  <SelectItem key={c.label} value={c.label}>
                    {c.name} (#{c.label})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {colonna !== NESSUNA_COLONNA && (
              <input
                value={valori}
                onChange={(e) => setValori(e.target.value)}
                placeholder={t('interventions.readBooks.valuesPlaceholder')}
                className="h-7 min-w-[280px] flex-1 rounded-md border border-border bg-background px-2 text-[12px] outline-none focus:border-primary"
              />
            )}
          </div>
        )}

        {isLoading && <p className="text-[13px] text-muted-foreground">{t('common.loading')}</p>}

        {nienteDaFare && (
          <p className="text-[13px] text-muted-foreground">
            {t('interventions.readBooks.noneToConfirm')}
            {data?.already_marked
              ? ` ${t('interventions.readBooks.alreadyMarkedSuffix', { count: data.already_marked, n: data.already_marked })}`
              : '.'}
          </p>
        )}

        {candidati.length > 0 && (
          <>
            <div className="mb-2.5 flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                onClick={() => void confermaScelti()}
                disabled={scelti.size === 0 || salvando}
              >
                {salvando ? <Loader2 className="size-3.5 animate-spin" /> : <BookCheck className="size-3.5" />}
                {t('interventions.readBooks.markAsReadButton', { n: scelti.size })}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setScelti(new Set(candidati.map((c) => c.id)))}
              >
                {t('interventions.readBooks.selectAllButton', { n: candidati.length })}
              </Button>
              {scelti.size > 0 && (
                <Button variant="ghost" size="sm" onClick={() => setScelti(new Set())}>
                  {t('interventions.readBooks.deselectButton')}
                </Button>
              )}
            </div>

            <div className="flex max-h-[520px] flex-col gap-1 overflow-y-auto">
              {candidati.map((c) => (
                <label
                  key={c.id}
                  className="flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5 text-[13px] hover:bg-accent"
                >
                  <input
                    type="checkbox"
                    checked={scelti.has(c.id)}
                    onChange={() => commuta(c.id)}
                    className="mt-1 shrink-0"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{c.title}</span>
                    <span className="block truncate text-[12px] text-muted-foreground">
                      {c.author} · {c.reasons.map((r) => descriviMotivo(r, t)).join(' · ')}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </>
        )}

        {esito && <p className="mt-2.5 text-[12.5px] text-muted-foreground">{esito}</p>}
      </SezionePieghevole>

      <h2 className="mt-1 text-[10.5px] font-semibold tracking-[0.09em] text-[var(--text-faint)] uppercase">
        {t('interventions.page.annotationHeading')}
      </h2>
      {/* Due stati diversi, e tenerli separati e' il punto: le VEDOVE hanno
          un libro che non esiste piu' e si ricollegano da qui; le ORFANE non
          ne hanno mai avuto uno e si accoppiano dalla scheda del
          dispositivo. */}
      <SezionePieghevole
        titolo={t('interventions.widowed.sectionTitle')}
        icona={BookX}
        quante={quanteVedove}
        descrizione={t('interventions.widowed.sectionDescription')}
      >
        <WidowedNotesPanel />
      </SezionePieghevole>

      <SezionePieghevole
        titolo={t('interventions.orphanNotes.sectionTitle')}
        icona={Highlighter}
        quante={quanteOrfane}
        descrizione={t('interventions.orphanNotes.sectionDescription')}
      >
        <OrphanNotesPanel />
      </SezionePieghevole>

      <SezionePieghevole
        titolo={t('interventions.notesWithoutPosition.sectionTitle')}
        icona={MapPinOff}
        quante={quanteSenzaPosizione}
        descrizione={t('interventions.notesWithoutPosition.sectionDescription')}
      >
        <NotesWithoutPositionPanel />
      </SezionePieghevole>


      {/* Il pannello delle sessioni orfane si nasconde da solo quando non ha
          niente da dire, quindi anche il suo titolo di gruppo deve sparire:
          un'intestazione sopra il vuoto e' peggio dell'assenza del gruppo. */}
      {(sessioniOrfane?.count ?? 0) > 0 && (
        <>
          <h2 className="mt-1 text-[10.5px] font-semibold tracking-[0.09em] text-[var(--text-faint)] uppercase">
            {t('interventions.page.readingHeading')}
          </h2>
          <OrphanSessionsPanel />
        </>
      )}

      {nienteDaFare && (
        <div className="flex items-center gap-2 rounded-md border border-dashed border-border px-4 py-6 text-[13px] text-muted-foreground">
          <ClipboardCheck className="size-4" />
          {t('interventions.page.emptyState')}
        </div>
      )}
    </div>
  )
}
