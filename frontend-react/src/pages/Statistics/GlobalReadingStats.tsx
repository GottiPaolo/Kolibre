import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { BarChart } from '@/components/charts/BarChart'
import { PieChart } from '@/components/charts/PieChart'
import { ChartCard, EmptyNote, StatBarRow } from './StatBar'
import { numeroCompatto, useLingua } from '@/lib/i18n'
import { useLibriLetti } from '@/lib/statsQueries'
import type { ReadingSessionRaw } from '@/lib/statsQueries'
import {
  MINUTI_MINIMI_PER_ORA,
  SOGLIA_LIBRO,
  authorDataCoverage,
  authorGenderShare,
  authorNationalityShare,
  authorOccupationShare,
  autoriDeiLibriLetti,
  formatDurationHuman,
  libriLettiPerAutore,
  libriPerDecennioDiNascita,
  oreDellaGiornata,
  tempoPerAutore,
  velocitaPerLibro,
} from './statsCompute'
import { authorCenturyShare } from './statsCompute'

// Le statistiche di lettura DI SEMPRE.
//
// Stanno a parte, in fondo e sotto un'intestazione propria, perché non
// rispondono al periodo scelto in cima: sono le domande che hanno senso solo su
// tutta la storia di lettura, e per cui filtrare per periodo toglierebbe il
// dato invece di affinarlo. «Leggo più veloce di mattina o di sera» non è una
// domanda sull'ultimo mese, e mostrarla accanto a numeri filtrati senza dirlo
// darebbe due scale nella stessa schermata.

const CHART_1 = 'var(--chart-1)'
const CHART_2 = 'var(--chart-2)'

function compatto(n: number): string {
  return numeroCompatto(n)
}

/** Una classifica di libri per velocità, in barre proporzionali. */
function ClassificaVelocita({
  titolo,
  libri,
  nota,
}: {
  titolo: string
  libri: { title: string; author: string; caratteriOra: number }[]
  nota: string
}) {
  const { t } = useLingua()
  const massimo = Math.max(1, ...libri.map((l) => l.caratteriOra))
  return (
    <ChartCard title={titolo}>
      {libri.length === 0 ? (
        <EmptyNote>{t('stats.reading.notEnoughMeasuredReading')}</EmptyNote>
      ) : (
        <div className="flex flex-col gap-2">
          {libri.map((l) => (
            <StatBarRow
              key={l.title}
              label={l.title}
              titoloAzione={`${l.title} — ${l.author}`}
              etichettaLarga
              value={t('stats.reading.charsPerHour', { n: compatto(l.caratteriOra) })}
              percent={Math.round((l.caratteriOra / massimo) * 100)}
              color={CHART_1}
            />
          ))}
        </div>
      )}
      <p className="mt-2 text-[11px] text-muted-foreground/70">{nota}</p>
    </ChartCard>
  )
}

export function GlobalReadingStats({ sessions }: { sessions: ReadingSessionRaw[] }) {
  const { t } = useLingua()
  const { data: letti } = useLibriLetti()
  const [epoca, setEpoca] = useState<'secolo' | 'decennio'>('decennio')

  const ore = useMemo(() => oreDellaGiornata(sessions), [sessions])
  const velocita = useMemo(() => velocitaPerLibro(sessions), [sessions])
  const sogliaInParole = t('stats.reading.thresholdNote', {
    n: velocita.length,
    threshold: SOGLIA_LIBRO.minuti === 60 ? t('stats.reading.oneHour') : t('stats.reading.minutesThreshold', { n: SOGLIA_LIBRO.minuti }),
  })
  // Quando i libri che superano la soglia sono meno di venti, le due
  // classifiche pescano dallo stesso mucchio e si sovrappongono. Dirlo è
  // meglio che lasciar credere che siano due insiemi diversi.
  const sovrapposte = velocita.length > 0 && velocita.length < 20 ? ` ${t('stats.reading.overlapNote')}` : ''
  const autoriTempo = useMemo(() => tempoPerAutore(sessions, t, 10), [sessions, t])

  // Memorizzato e non `letti?.libri ?? []` scritto sul posto: quel `[]` è un
  // array nuovo ad ogni render, e tutti i useMemo che lo guardano
  // ricalcolerebbero sempre.
  const libri = useMemo(() => letti?.libri ?? [], [letti])
  const autoriLetti = useMemo(() => autoriDeiLibriLetti(libri), [libri])
  const perAutore = useMemo(() => libriLettiPerAutore(libri, 10), [libri])
  const nascite = useMemo(
    () => (epoca === 'decennio' ? libriPerDecennioDiNascita(libri, t) : authorCenturyShare(autoriLetti, t)),
    [epoca, libri, autoriLetti, t]
  )
  const mestieri = useMemo(() => authorOccupationShare(autoriLetti, 12), [autoriLetti])
  const nazioni = useMemo(() => authorNationalityShare(autoriLetti, 10), [autoriLetti])
  const generi = useMemo(() => authorGenderShare(autoriLetti), [autoriLetti])
  const coperturaGenere = useMemo(() => authorDataCoverage(autoriLetti, 'gender'), [autoriLetti])

  // Le ore con poco materiale restano fuori dalla velocità, non a zero: una
  // barra a zero direbbe "a quell'ora leggi lentissimo" invece di "a
  // quell'ora hai letto venti minuti in tutto".
  const oreConVelocita = ore.filter((o) => o.velocita != null)
  const oreEscluse = ore.filter((o) => o.secondi > 0 && o.velocita == null).length

  if (sessions.length === 0) return null

  return (
    <div className="flex flex-col gap-3">
      <div>
        <h3 className="font-serif text-[15px] font-semibold">{t('stats.reading.allTime.title')}</h3>
        <p className="text-[12px] text-muted-foreground">
          {t('stats.reading.allTime.subtitle')}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <ChartCard title={t('stats.reading.charsByHourOfDay')}>
          <BarChart
            labels={ore.map((o) => String(o.ora).padStart(2, '0'))}
            datasets={[{ label: t('stats.reading.chars'), data: ore.map((o) => o.caratteri) }]}
            yUnit="car"
            height={200}
            showLegend={false}
          />
        </ChartCard>

        <ChartCard title={t('stats.reading.speedByHourOfDay')}>
          {oreConVelocita.length > 0 ? (
            <BarChart
              labels={oreConVelocita.map((o) => String(o.ora).padStart(2, '0'))}
              datasets={[{ label: t('stats.reading.charsPerHour'), data: oreConVelocita.map((o) => o.velocita) }]}
              yUnit="car"
              height={200}
              showLegend={false}
            />
          ) : (
            <EmptyNote>{t('stats.reading.noHourSpeedData')}</EmptyNote>
          )}
          <p className="mt-2 text-[11px] text-muted-foreground/70">
            {t('stats.reading.minHourNote', { n: MINUTI_MINIMI_PER_ORA })}
            {oreEscluse > 0 && <> {t('stats.reading.excludedHours', { count: oreEscluse, n: oreEscluse })}</>}
          </p>
        </ChartCard>

        <ClassificaVelocita
          titolo={t('stats.reading.fastestBooks.title')}
          libri={velocita.slice(0, 10)}
          nota={`${sogliaInParole}${sovrapposte}`}
        />
        <ClassificaVelocita
          titolo={t('stats.reading.slowestBooks.title')}
          libri={[...velocita].reverse().slice(0, 10)}
          nota={t('stats.reading.slowestBooksNote')}
        />

        <ChartCard title={t('stats.reading.topAuthorsByTime.title')}>
          {autoriTempo.length > 0 ? (
            <PieChart
              labels={autoriTempo.map((a) => a.label)}
              data={autoriTempo.map((a) => a.count)}
              height={240}
              valueFormatter={formatDurationHuman}
            />
          ) : (
            <EmptyNote>{t('stats.library.noData')}</EmptyNote>
          )}
        </ChartCard>

        <ChartCard title={t('stats.reading.booksFinishedByAuthor.title')}>
          {perAutore.length > 0 ? (
            <div className="flex flex-col gap-2">
              {perAutore.map((a) => (
                <StatBarRow
                  key={a.label}
                  label={a.label}
                  etichettaLarga
                  value={t('stats.library.bookCount', { count: a.count, n: a.count })}
                  percent={a.percent}
                  color={CHART_2}
                />
              ))}
            </div>
          ) : (
            <EmptyNote>{t('stats.reading.noFinishedBooks')}</EmptyNote>
          )}
          <p className="mt-2 text-[11px] text-muted-foreground/70">
            {t('stats.reading.finishedBooksNote')}
            {libri.length > 0 && ` ${t('stats.reading.finishedBooksCount', { books: libri.length, authors: autoriLetti.length })}`}
          </p>
        </ChartCard>

        <ChartCard
          title={t('stats.reading.booksByAuthorBirth.title')}
          action={
            <div className="flex items-center gap-1">
              <Button variant={epoca === 'decennio' ? 'secondary' : 'ghost'} size="xs" onClick={() => setEpoca('decennio')}>
                {t('stats.reading.decades')}
              </Button>
              <Button variant={epoca === 'secolo' ? 'secondary' : 'ghost'} size="xs" onClick={() => setEpoca('secolo')}>
                {t('stats.reading.centuries')}
              </Button>
            </div>
          }
        >
          {nascite.length > 0 ? (
            <BarChart
              labels={nascite.map((n) => n.label)}
              datasets={[{ label: t('stats.reading.finishedBooksLabel'), data: nascite.map((n) => n.books) }]}
              height={220}
              showLegend={false}
            />
          ) : (
            <EmptyNote>{t('stats.reading.noBirthDateData')}</EmptyNote>
          )}
          {letti && letti.senza_anagrafica.length > 0 && (
            <p className="mt-2 text-[11px] text-muted-foreground/70">
              {t('stats.reading.missingBirthDate', { count: letti.senza_anagrafica.length, n: letti.senza_anagrafica.length })}
            </p>
          )}
        </ChartCard>

        <ChartCard title={t('stats.reading.occupationOfFinished.title')}>
          {mestieri.length > 0 ? (
            <div className="flex flex-col gap-2">
              {mestieri.map((m) => (
                <StatBarRow
                  key={m.label}
                  label={m.label}
                  value={t('stats.library.bookCount', { count: m.books, n: m.books })}
                  percent={Math.round(m.percent)}
                  color={CHART_1}
                />
              ))}
            </div>
          ) : (
            <EmptyNote>{t('stats.reading.noOccupationData')}</EmptyNote>
          )}
          <p className="mt-2 text-[11px] text-muted-foreground/70">
            {t('stats.reading.occupationNote')}
          </p>
        </ChartCard>

        <ChartCard title={t('stats.reading.nationalityOfFinished.title')}>
          {nazioni.length > 0 ? (
            <div className="flex flex-col gap-2">
              {nazioni.map((n) => (
                <StatBarRow
                  key={n.label}
                  label={n.label}
                  value={t('stats.library.bookCount', { count: n.books, n: n.books })}
                  percent={Math.round(n.percent)}
                  color={CHART_2}
                />
              ))}
            </div>
          ) : (
            <EmptyNote>{t('stats.reading.noNationalityData')}</EmptyNote>
          )}
          <p className="mt-2 text-[11px] text-muted-foreground/70">
            {t('stats.reading.nationalityNote')}
          </p>
        </ChartCard>

        <ChartCard title={t('stats.reading.genderOfFinished.title')}>
          {generi.length > 0 ? (
            <div className="flex flex-col gap-2">
              {generi.map((g) => (
                <StatBarRow
                  key={g.label}
                  label={g.label}
                  value={`${t('stats.library.bookCount', { count: g.books, n: g.books })} · ${Math.round(g.percent)}%`}
                  percent={Math.round(g.percent)}
                  color={CHART_1}
                />
              ))}
            </div>
          ) : (
            <EmptyNote>{t('stats.reading.noGenderData')}</EmptyNote>
          )}
          {/* La percentuale è calcolata sul NOTO, quindi un'unica barra dice
              sempre 100%: senza questa riga sembrerebbe una certezza invece di
              un «di quelli che sappiamo». */}
          <p className="mt-2 text-[11px] text-muted-foreground/70">
            {t('stats.reading.genderCoverage', { known: coperturaGenere.booksKnown, total: coperturaGenere.booksTotal })}
          </p>
        </ChartCard>
      </div>
    </div>
  )
}
