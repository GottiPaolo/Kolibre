import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { PieChart } from '@/components/charts/PieChart'
import { ChartCard, EmptyNote, StatBarRow } from './StatBar'
import { api } from '@/lib/api'
import { useAuthors } from '@/lib/queries'
import { useBookActions } from '@/lib/bookActionsContext'
import { useLingua } from '@/lib/i18n'
import {
  authorCenturyShare,
  authorDataCoverage,
  authorGenderShare,
  authorNationalityShare,
  authorOccupationShare,
  livingAuthorsShare,
} from './statsCompute'
import type { useChartVisibility } from './chartConfig'

const ACCENT = 'var(--chart-1)'
const SAGE = 'var(--chart-2)'
const GOLD = 'var(--chart-3)'

// Le percentuali sopra sono calcolate SUL NOTO. Senza dire quanto sia il
// noto, "6% donne" e "6% donne, ma di un terzo non sappiamo nulla" avrebbero
// lo stesso aspetto — e sono due affermazioni molto diverse.
function Copertura({ c }: { c: { booksKnown: number; booksTotal: number; percent: number } }) {
  const { t } = useLingua()
  if (c.percent >= 99.5) return null
  return (
    <p className="mt-1 text-[11px] text-muted-foreground/70">
      {t('stats.library.coverage', { known: c.booksKnown, total: c.booksTotal, percent: c.percent.toFixed(0) })}
    </p>
  )
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-card p-3 text-center">
      <p className="text-[18px] font-semibold">{value}</p>
      <p className="text-[10.5px] text-muted-foreground">{label}</p>
    </div>
  )
}

interface Voce {
  label: string
  count: number
  percent: number
}

interface Panoramica {
  total_books: number
  unique_authors: number
  unique_series: number
  metadata_percent: number
  formats: { format: string; count: number; percent: number }[]
  format_storage: { format: string; bytesLabel: string; percent: number }[]
  top_authors: { name: string; count: number; percent: number }[]
  top_series: { name: string; count: number; percent: number }[]
  page_buckets: Voce[]
  author_pages: { name: string; pages: number; percent: number }[]
  author_storage: { name: string; bytesLabel: string; percent: number }[]
  ratings: Voce[]
  languages: Voce[]
  tags: Voce[]
}

interface LibraryStatsTabProps {
  libraryFolder: string | undefined
  visibility: ReturnType<typeof useChartVisibility>
}

export function LibraryStatsTab({ libraryFolder, visibility }: LibraryStatsTabProps) {
  const { t } = useLingua()
  const { isVisible } = visibility
  // Ogni barra e' un punto di partenza: si clicca e si finisce nella
  // Libreria filtrata su quel valore, o sulla scheda dell'autore.
  const actions = useBookActions()

  // I conteggi di catalogo arrivano contati dal server. Prima li ricavava
  // il browser dai libri, e per farlo doveva scaricare il catalogo INTERO:
  // quasi sei megabyte su una biblioteca da 5.843 libri, per un paio di
  // chilobyte di risultati — ed era proprio la biblioteca su cui queste
  // statistiche servono di piu'.
  const { data: p, isLoading } = useQuery({
    queryKey: ['library-overview', libraryFolder],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/stats/library-overview', {
        params: { query: { library: libraryFolder } },
      })
      if (error) throw error
      return data as unknown as Panoramica
    },
    enabled: !!libraryFolder,
  })

  // L'anagrafica arriva dall'elenco autori, non dai libri: e' li' che vive
  // (author_metadata), ed e' gia' in cache perche' la pagina Autori la usa.
  // Ristretta alla biblioteca mostrata — senza il parametro sarebbe globale
  // mentre tutto il resto della scheda parla di una biblioteca sola.
  const { data: authors = [] } = useAuthors(libraryFolder)
  const generi = useMemo(() => authorGenderShare(authors), [authors])
  const nazionalita = useMemo(() => authorNationalityShare(authors), [authors])
  const secoli = useMemo(() => authorCenturyShare(authors, t), [authors, t])
  const mestieri = useMemo(() => authorOccupationShare(authors), [authors])
  const viventi = useMemo(() => livingAuthorsShare(authors), [authors])
  const copGenere = useMemo(() => authorDataCoverage(authors, 'gender'), [authors])
  const copNaz = useMemo(() => authorDataCoverage(authors, 'nationality'), [authors])
  const copNascita = useMemo(() => authorDataCoverage(authors, 'birth_date'), [authors])

  if (isLoading || !p) return <p className="text-muted-foreground">{t('common.loading')}</p>

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Kpi label={t('stats.library.kpi.totalBooks')} value={String(p.total_books)} />
        <Kpi label={t('stats.library.kpi.uniqueAuthors')} value={String(p.unique_authors)} />
        <Kpi label={t('stats.library.kpi.seriesCount')} value={String(p.unique_series)} />
        <Kpi label={t('stats.library.kpi.metadataIntegrity')} value={`${p.metadata_percent}%`} />
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {isVisible('formatShare') && (
          <ChartCard title={t('stats.library.chart.formatShare')}>
            {p.formats.length > 0 ? (
              <PieChart labels={p.formats.map((f) => f.format)} data={p.formats.map((f) => f.count)} height={200} />
            ) : (
              <EmptyNote>{t('stats.library.noData')}</EmptyNote>
            )}
          </ChartCard>
        )}

        {isVisible('storageFormat') && (
          <ChartCard title={t('stats.library.chart.storageFormat')}>
            <div className="flex flex-col gap-2">
              {p.format_storage.map((f, i) => (
                <StatBarRow
                  key={f.format}
                  label={f.format}
                  value={f.bytesLabel}
                  percent={f.percent}
                  color={i % 2 === 0 ? GOLD : ACCENT}
                  onClick={() => actions.filterByFieldValue('formats', f.format, libraryFolder)}
                  titoloAzione={t('stats.library.showBooksInFormat', { format: f.format })}
                />
              ))}
              {p.format_storage.length === 0 && <EmptyNote>{t('stats.library.noData')}</EmptyNote>}
            </div>
          </ChartCard>
        )}

        {isVisible('topAuthors') && (
          <ChartCard title={t('stats.library.chart.topAuthorsCard')}>
            <div className="flex flex-col gap-2">
              {p.top_authors.map((a) => (
                <StatBarRow
                  key={a.name}
                  label={a.name}
                  value={t('stats.library.bookCount', { count: a.count, n: a.count })}
                  percent={a.percent}
                  color={SAGE}
                  onClick={() => actions.goToAuthor(a.name)}
                  titoloAzione={t('entities.list.openCardTitle', { name: a.name })}
                />
              ))}
              {p.top_authors.length === 0 && <EmptyNote>{t('stats.library.noData')}</EmptyNote>}
            </div>
          </ChartCard>
        )}

        {isVisible('topSeries') && (
          <ChartCard title={t('stats.library.chart.topSeriesCard')}>
            <div className="flex flex-col gap-2">
              {p.top_series.map((s) => (
                <StatBarRow
                  key={s.name}
                  label={s.name}
                  value={t('stats.library.bookCount', { count: s.count, n: s.count })}
                  percent={s.percent}
                  color={GOLD}
                  onClick={() => actions.filterByFieldValue('series', s.name, libraryFolder)}
                  titoloAzione={t('stats.library.showBooksInSeries', { name: s.name })}
                />
              ))}
              {p.top_series.length === 0 && <EmptyNote>{t('stats.library.noSeriesData')}</EmptyNote>}
            </div>
          </ChartCard>
        )}

        {isVisible('pageCount') && (
          <ChartCard title={t('stats.library.chart.pageCountCard')}>
            <div className="flex flex-col gap-2">
              {p.page_buckets.map((b) => (
                <StatBarRow
                  key={b.label}
                  label={b.label}
                  value={t('stats.library.volumeCount', { count: b.count, n: b.count })}
                  percent={b.percent}
                  color={ACCENT}
                />
              ))}
            </div>
          </ChartCard>
        )}

        {isVisible('pagesPerAuthor') && (
          <ChartCard title={t('stats.library.chart.pagesPerAuthor')}>
            <div className="flex flex-col gap-2">
              {p.author_pages.map((a) => (
                <StatBarRow
                  key={a.name}
                  label={a.name}
                  value={t('stats.library.pagesShort', { n: a.pages })}
                  percent={a.percent}
                  color={SAGE}
                  onClick={() => actions.goToAuthor(a.name)}
                  titoloAzione={t('entities.list.openCardTitle', { name: a.name })}
                />
              ))}
              {p.author_pages.length === 0 && <EmptyNote>{t('stats.library.noPageData')}</EmptyNote>}
            </div>
          </ChartCard>
        )}

        {isVisible('storagePerAuthor') && (
          <ChartCard title={t('stats.library.chart.storagePerAuthor')}>
            <div className="flex flex-col gap-2">
              {p.author_storage.map((a) => (
                <StatBarRow
                  key={a.name}
                  label={a.name}
                  value={a.bytesLabel}
                  percent={a.percent}
                  color={GOLD}
                  onClick={() => actions.goToAuthor(a.name)}
                  titoloAzione={t('entities.list.openCardTitle', { name: a.name })}
                />
              ))}
              {p.author_storage.length === 0 && <EmptyNote>{t('stats.library.noData')}</EmptyNote>}
            </div>
          </ChartCard>
        )}

        {isVisible('ratingDistribution') && (
          <ChartCard title={t('stats.library.chart.ratingDistribution')}>
            <div className="flex flex-col gap-2">
              {p.ratings.map((b) => (
                <StatBarRow
                  key={b.label}
                  label={b.label === 'Non valutato' ? t('stats.library.unrated') : '★'.repeat(Number(b.label))}
                  value={String(b.count)}
                  percent={b.percent}
                  color={ACCENT}
                />
              ))}
            </div>
          </ChartCard>
        )}

        {isVisible('languageDistribution') && (
          <ChartCard title={t('stats.library.chart.languageDistribution')}>
            {p.languages.length > 0 ? (
              <PieChart labels={p.languages.map((l) => l.label)} data={p.languages.map((l) => l.count)} height={200} />
            ) : (
              <EmptyNote>{t('stats.library.noData')}</EmptyNote>
            )}
          </ChartCard>
        )}

        {isVisible('authorGender') && (
          <ChartCard title={t('stats.library.chart.authorGender')}>
            <div className="flex flex-col gap-2">
              {generi.map((g) => (
                <StatBarRow key={g.label} label={g.label} value={t('stats.library.bookCount', { count: g.books, n: g.books })} percent={g.percent} color={ACCENT} />
              ))}
              {generi.length === 0 && <EmptyNote>{t('stats.library.noAuthorData')}</EmptyNote>}
              {generi.length > 0 && <Copertura c={copGenere} />}
            </div>
          </ChartCard>
        )}

        {isVisible('authorNationality') && (
          <ChartCard title={t('stats.library.chart.authorNationality')}>
            <div className="flex flex-col gap-2">
              {nazionalita.map((n) => (
                <StatBarRow key={n.label} label={n.label} value={t('stats.library.bookCount', { count: n.books, n: n.books })} percent={n.percent} color={SAGE} />
              ))}
              {nazionalita.length === 0 && <EmptyNote>{t('stats.library.noData')}</EmptyNote>}
              {nazionalita.length > 0 && <Copertura c={copNaz} />}
            </div>
          </ChartCard>
        )}

        {isVisible('authorCentury') && (
          <ChartCard title={t('stats.library.chart.authorCentury')}>
            <div className="flex flex-col gap-2">
              {secoli.map((s) => (
                <StatBarRow key={s.label} label={s.label} value={t('stats.library.bookCount', { count: s.books, n: s.books })} percent={s.percent} color={GOLD} />
              ))}
              {secoli.length === 0 && <EmptyNote>{t('stats.library.noData')}</EmptyNote>}
              {secoli.length > 0 && (
                <>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    {t('stats.library.livingAuthorsPercent', { percent: viventi.percent.toFixed(0) })}
                  </p>
                  <Copertura c={copNascita} />
                </>
              )}
            </div>
          </ChartCard>
        )}

        {isVisible('authorOccupation') && (
          <ChartCard title={t('stats.library.chart.authorOccupation')}>
            <div className="flex flex-col gap-2">
              {mestieri.map((m) => (
                <StatBarRow key={m.label} label={m.label} value={t('stats.library.bookCount', { count: m.books, n: m.books })} percent={m.percent} color={ACCENT} />
              ))}
              {mestieri.length === 0 && <EmptyNote>{t('stats.library.noData')}</EmptyNote>}
            </div>
          </ChartCard>
        )}

        {isVisible('topTags') && (
          <ChartCard title={t('stats.library.chart.topTags')}>
            <div className="flex flex-col gap-2">
              {p.tags.map((tag) => (
                <StatBarRow
                  key={tag.label}
                  label={tag.label}
                  value={String(tag.count)}
                  percent={tag.percent}
                  color={GOLD}
                  onClick={() => actions.filterByFieldValue('tags', tag.label, libraryFolder)}
                  titoloAzione={t('stats.library.showBooksWithTag', { tag: tag.label })}
                />
              ))}
              {p.tags.length === 0 && <EmptyNote>{t('stats.library.noTags')}</EmptyNote>}
            </div>
          </ChartCard>
        )}
      </div>
    </div>
  )
}
