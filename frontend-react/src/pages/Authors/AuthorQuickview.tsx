import { ArrowRight, Users, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { withBackendUrl } from '@/lib/api'
import { formatDate } from '@/lib/format'
import type { AuthorSummary } from '@/types/author'
import { etichettaCampo, secoloDi, statoDi, type CampoAutore } from './authorsQuery'
import { numero, useLingua } from '@/lib/i18n'

// Il pannello laterale dell'autore, gemello di quello della libreria.
//
// Prima cliccare una riga apriva la scheda dell'autore: si perdeva il posto
// nell'elenco, e per confrontare due autori bisognava andare avanti e
// indietro. Ora la riga apre questo, la scheda resta a un clic di distanza,
// e con le frecce si scorre l'elenco vedendo cambiare il pannello.
//
// I metadati sono cliccabili e aggiungono una clausola alla ricerca —
// stessa idea di ValoreFiltrabile nella libreria, con la differenza che qui
// il filtro resta DENTRO la pagina Autori invece di portare altrove: da un
// autore italiano si vogliono gli altri autori italiani, non i loro libri.

function Riga({
  etichetta,
  children,
}: {
  etichetta: string
  children: React.ReactNode
}) {
  return (
    <>
      <dt className="text-muted-foreground">{etichetta}</dt>
      <dd className="min-w-0">{children}</dd>
    </>
  )
}

function Filtrabile({
  campo,
  valore,
  attivo,
  onFiltra,
}: {
  campo: CampoAutore
  valore: string
  attivo: boolean
  onFiltra: (campo: CampoAutore, valore: string) => void
}) {
  const { t } = useLingua()
  return (
    <button
      onClick={() => onFiltra(campo, valore)}
      title={
        attivo
          ? t('authors.quickview.removeFilter', { field: etichettaCampo(campo, t), value: valore })
          : t('authors.quickview.showOnly', { value: valore })
      }
      className={
        attivo
          ? 'text-left text-primary underline underline-offset-2'
          : 'text-left hover:text-primary hover:underline'
      }
    >
      {valore}
    </button>
  )
}

export function AuthorQuickview({
  author,
  query,
  onFiltra,
  onApri,
  onChiudi,
}: {
  author: AuthorSummary
  /** La ricerca corrente: serve solo a mostrare quali valori sono già filtrati. */
  query: string
  onFiltra: (campo: CampoAutore, valore: string) => void
  onApri: (name: string) => void
  onChiudi: () => void
}) {
  const { t } = useLingua()
  const attivo = (campo: CampoAutore, valore: string) =>
    query.toLowerCase().includes(`${campo}:`) &&
    query.toLowerCase().includes(valore.toLowerCase())

  const secolo = secoloDi(author.birth_date)
  const stato = statoDi(author)

  return (
    <aside data-pannello="autore" className="flex w-[300px] shrink-0 flex-col gap-3 overflow-y-auto border-l border-border p-3.5">
      <div className="flex items-start gap-2">
        <h2 className="min-w-0 flex-1 font-serif text-[16px] leading-tight font-semibold">{author.name}</h2>
        <Button variant="ghost" size="icon-sm" onClick={onChiudi} title={t('authors.quickview.closePanel')}>
          <X className="size-3.5" />
        </Button>
      </div>

      <div className="mx-auto size-[120px] shrink-0 overflow-hidden rounded-full bg-muted">
        {author.photo_url ? (
          <img src={withBackendUrl(author.photo_url)} alt="" className="size-full object-cover" />
        ) : (
          <div className="flex size-full items-center justify-center">
            <Users className="size-8 text-muted-foreground/40" />
          </div>
        )}
      </div>

      <dl className="grid grid-cols-[86px_1fr] gap-x-2.5 gap-y-1.5 text-[12.5px]">
        <Riga etichetta={t('authors.field.bookCount')}>{author.book_count}</Riga>
        <Riga etichetta={t('authors.field.pages')}>{numero(author.total_pages)}</Riga>

        {author.gender && (
          <Riga etichetta={t('authors.field.gender')}>
            <Filtrabile campo="genere" valore={author.gender} attivo={attivo('genere', author.gender)} onFiltra={onFiltra} />
          </Riga>
        )}

        {author.nationality.length > 0 && (
          <Riga etichetta={t('authors.field.nationality')}>
            {/* Una per volta, non tutte in blocco: "italiana, francese" non
                e' una cittadinanza che si possa filtrare. */}
            {author.nationality.map((n, i) => (
              <span key={n}>
                {i > 0 && ', '}
                <Filtrabile campo="nazionalita" valore={n} attivo={attivo('nazionalita', n)} onFiltra={onFiltra} />
              </span>
            ))}
          </Riga>
        )}

        {author.occupations.length > 0 && (
          <Riga etichetta={t('authors.field.occupation')}>
            {author.occupations.map((m, i) => (
              <span key={m}>
                {i > 0 && ', '}
                <Filtrabile campo="mestiere" valore={m} attivo={attivo('mestiere', m)} onFiltra={onFiltra} />
              </span>
            ))}
          </Riga>
        )}

        {author.birth_date && <Riga etichetta={t('authors.field.birth')}>{formatDate(author.birth_date)}</Riga>}
        {author.death_date && <Riga etichetta={t('authors.field.death')}>{formatDate(author.death_date)}</Riga>}

        {stato && (
          <Riga etichetta={t('authors.field.status')}>
            <Filtrabile campo="stato" valore={stato} attivo={attivo('stato', stato)} onFiltra={onFiltra} />
          </Riga>
        )}

        {secolo && (
          <Riga etichetta={t('authors.field.era')}>
            <Filtrabile campo="epoca" valore={secolo} attivo={attivo('epoca', secolo)} onFiltra={onFiltra} />
            <span className="text-muted-foreground"> {t('authors.quickview.century')}</span>
          </Riga>
        )}
      </dl>

      <Button variant="outline" size="sm" className="mt-1" onClick={() => onApri(author.name)}>
        {t('authors.quickview.openCard')}
        <ArrowRight className="size-3.5" />
      </Button>
    </aside>
  )
}
