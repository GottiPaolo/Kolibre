import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { numero, useLingua } from '@/lib/i18n'
import { ChartCard, EmptyNote, StatBarRow } from './StatBar'

// I libri più evidenziati.
//
// Si chiamava "Libri che ti hanno fatto fermare": un titolo che prova a dire
// cosa il numero SIGNIFICA, e che quindi lo interpreta al posto di chi guarda.
// Rinominato il 01/10/2026 — il pannello conta evidenziazioni, e dirlo è
// più utile che suggerire perché ce ne siano tante.
//
// Il tempo misura quanto un libro ti ha trattenuto, non quanto ti ha
// coinvolto: uno letto in otto ore senza una sottolineatura e uno letto in
// otto ore con novanta sono due esperienze diverse, e il cruscotto le
// raccontava identiche. Le annotazioni erano l'unico dato di lettura che
// non entrava nelle statistiche in nessuna forma.
//
// Normalizzata per lunghezza, altrimenti sarebbe la classifica dei libri
// lunghi: un saggio breve fittissimo di note deve poter battere un romanzo
// di mille pagine con tre sottolineature.

interface Libro {
  title: string
  author: string
  highlights: number
  chars_read: number
  per_100k: number
}

interface Risposta {
  books: Libro[]
  books_total: number
  books_without_denominator: number
  highlights_total: number
}

export function AnnotationIntensity({ libraryFolder }: { libraryFolder: string | undefined }) {
  const { t } = useLingua()
  const { data } = useQuery({
    queryKey: ['intensita-annotazioni', libraryFolder],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/stats/annotation-intensity', {
        params: { query: { library: libraryFolder, limit: 10 } },
      })
      if (error) throw error
      return data as unknown as Risposta
    },
    enabled: !!libraryFolder,
  })

  if (!data || data.highlights_total === 0) return null
  const massimo = Math.max(1, ...data.books.map((b) => b.per_100k))

  return (
    <ChartCard title={t('stats.annotationIntensity.title')}>
      <div className="flex flex-col gap-2">
        {data.books.map((b) => (
          <StatBarRow
            key={`${b.title}-${b.author}`}
            label={b.title}
            value={t('stats.annotationIntensity.per100k', { n: numero(b.per_100k) })}
            percent={Math.round((b.per_100k / massimo) * 100)}
            color="var(--chart-2)"
          />
        ))}
        {data.books.length === 0 && <EmptyNote>{t('stats.annotationIntensity.emptyNote')}</EmptyNote>}
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground/70">
        {t('stats.annotationIntensity.note')}
        {data.books_without_denominator > 0 && (
          <> {t('stats.annotationIntensity.excludedNote', { count: data.books_without_denominator, n: data.books_without_denominator })}</>
        )}
      </p>
    </ChartCard>
  )
}
