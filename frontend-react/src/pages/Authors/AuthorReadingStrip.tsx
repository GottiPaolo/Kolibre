import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { numeroCompatto, useLingua } from '@/lib/i18n'

// Quanto e' stato letto di questo autore, in una riga sola.
//
// La scheda di un autore non conteneva un solo dato di lettura, mentre
// quella di un libro ne ha un pannello intero: si sapeva tutto della sua
// vita e niente del tempo passato insieme.
//
// Resta pero' una scelta discussa: la scheda di un autore vuole essere
// informativa e oggettiva, non personalizzata sulle letture di chi la
// guarda. Sta qui a una condizione: che resti UNA STRISCIA SOBRIA,
// dichiaratamente removibile o spostabile. Per questo vive in un file suo
// con un endpoint suo: toglierla e' cancellare due file, non districare del
// codice da due pagine.
//
// Sobria vuol dire anche che sparisce quando non ha niente da dire: di un
// autore mai letto non mostra una fila di zeri.

interface Statistiche {
  books_owned: number
  books_read: number
  books_marked_read: number
  total_time_seconds: number
  chars_read: number
  sessions: number
  first_read: string | null
  last_read: string | null
  highlights: number
}

function durata(secondi: number): string {
  const ore = Math.floor(secondi / 3600)
  if (ore >= 1) return `${ore} h`
  const minuti = Math.round(secondi / 60)
  return `${minuti} min`
}

function caratteri(n: number): string {
  return numeroCompatto(n)
}

function Voce({ etichetta, valore }: { etichetta: string; valore: string }) {
  return (
    <span className="whitespace-nowrap">
      <span className="tabular-nums text-foreground">{valore}</span>
      <span className="text-muted-foreground"> {etichetta}</span>
    </span>
  )
}

export function AuthorReadingStrip({ name, library }: { name: string; library?: string | null }) {
  const { t } = useLingua()
  const { data } = useQuery({
    queryKey: ['author-reading-stats', name, library ?? null],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/kolibre/authors/{name}/reading-stats', {
        params: { path: { name }, query: library ? { library } : {} },
      })
      if (error) throw error
      return data as unknown as Statistiche
    },
    enabled: !!name,
  })

  if (!data) return null
  const maiLetto = data.total_time_seconds === 0 && data.books_marked_read === 0 && data.highlights === 0
  if (maiLetto) return null

  const voci: { etichetta: string; valore: string }[] = []
  if (data.total_time_seconds > 0) voci.push({ etichetta: t('authors.readingStrip.readingTime'), valore: durata(data.total_time_seconds) })
  // "letti" e' la spunta umana quando c'e', altrimenti i libri con almeno
  // una sessione: due domande diverse, e non ha senso mostrarle entrambe.
  if (data.books_marked_read > 0) {
    voci.push({
      etichetta: t('authors.readingStrip.markedRead', { count: data.books_marked_read, total: data.books_owned }),
      valore: String(data.books_marked_read),
    })
  } else if (data.books_read > 0) {
    voci.push({
      etichetta: t('authors.readingStrip.opened', { count: data.books_read, total: data.books_owned }),
      valore: String(data.books_read),
    })
  }
  if (data.chars_read > 0) voci.push({ etichetta: t('authors.readingStrip.charactersRead'), valore: caratteri(data.chars_read) })
  if (data.highlights > 0) {
    voci.push({
      etichetta: t('authors.readingStrip.highlights', { count: data.highlights, n: data.highlights }),
      valore: String(data.highlights),
    })
  }

  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-y border-border py-2 text-[12.5px]">
      {voci.map((v) => (
        <Voce key={v.etichetta} etichetta={v.etichetta} valore={v.valore} />
      ))}
      {data.first_read && data.last_read && (
        <span className="whitespace-nowrap text-muted-foreground">
          {t('authors.readingStrip.dateRange', { from: formatDate(data.first_read), to: formatDate(data.last_read) })}
        </span>
      )}
    </div>
  )
}
