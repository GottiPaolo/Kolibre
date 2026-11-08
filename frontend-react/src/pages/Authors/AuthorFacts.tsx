// Anagrafica dell'autore: elenco in lettura, campi in modifica.
//
// Non e' piu' un pannello a se': sta dentro la scheda dell'autore, sopra la
// biografia, e si modifica insieme a tutto il resto con l'unica matita della
// scheda. Due riquadri distinti con due matite diverse erano due modi di fare
// la stessa cosa nello stesso posto.
import type { AuthorDetail } from '@/types/author'
import { useLingua, type Valori } from '@/lib/i18n'

/** Bozza modificabile: tutto testo, anche le liste (separate da ";"). */
export interface FactsDraft {
  gender: string
  nationality: string
  birth_date: string
  death_date: string
  occupations: string
}

export function draftFromAuthor(a: AuthorDetail): FactsDraft {
  return {
    gender: a.gender ?? '',
    nationality: (a.nationality ?? []).join('; '),
    birth_date: a.birth_date ?? '',
    death_date: a.death_date ?? '',
    occupations: (a.occupations ?? []).join('; '),
  }
}

export function draftToFields(d: FactsDraft): Record<string, string | string[]> {
  const lista = (s: string) => s.split(';').map((x) => x.trim()).filter(Boolean)
  return {
    gender: d.gender,
    nationality: lista(d.nationality),
    birth_date: d.birth_date,
    death_date: d.death_date,
    occupations: lista(d.occupations),
  }
}

// Valori che Wikidata usa davvero per la proprieta' P21, nell'etichetta
// italiana che salviamo. I primi due coprono il 98% della biblioteca reale.
const GENERI = ['maschio', 'femmina', 'uomo transgender', 'donna transgender', 'intersessualità', 'non binario']

// Etichetta leggibile per un valore GENERI — il valore salvato (es.
// 'maschio') resta quello di Wikidata, invariato: solo il testo mostrato
// cambia con la lingua.
function genderLabel(value: string, t: (chiave: string, valori?: Valori) => string): string {
  switch (value) {
    case 'maschio':
      return t('authors.facts.gender.male')
    case 'femmina':
      return t('authors.facts.gender.female')
    case 'uomo transgender':
      return t('authors.facts.gender.transMale')
    case 'donna transgender':
      return t('authors.facts.gender.transFemale')
    case 'intersessualità':
      return t('authors.facts.gender.intersex')
    case 'non binario':
      return t('authors.facts.gender.nonBinary')
    default:
      return value
  }
}

/**
 * M e F al posto di "maschio"/"femmina", come chiesto: in un elenco di dati
 * anagrafici una lettera basta e non ruba spazio. Tutto il resto resta per
 * esteso — abbreviare "uomo transgender" significherebbe inventare una sigla
 * che nessuno riconosce, e per un caso raro non vale la pena.
 */
export function genderShort(gender: string | null | undefined, t: (chiave: string, valori?: Valori) => string): string | null {
  if (!gender) return null
  const g = gender.trim().toLowerCase()
  if (g === 'maschio') return 'M'
  if (g === 'femmina') return 'F'
  return genderLabel(g, t)
}

/**
 * Data leggibile: intera quando c'e' per intero, altrimenti quello che c'e'.
 *
 * Qui si era ridotto tutto all'anno, per compattezza. Ma la data completa e'
 * un'informazione in piu' che il dato gia' contiene, e toglierla per
 * guadagnare cinque caratteri non conviene: quando la data c'e' per intero
 * si mostra per intero.
 *
 * Wikidata conserva anche date parziali (solo l'anno, o anno e mese): in quei
 * casi si mostra la parte nota invece di inventare un 1° gennaio.
 */
export function formatDate(d: string | null | undefined): string | null {
  if (!d) return null
  const completa = d.match(/^(-?\d{4})-(\d{2})-(\d{2})/)
  if (completa) {
    const [, a, m, g] = completa
    return `${g}/${m}/${a}`
  }
  const annoMese = d.match(/^(-?\d{4})-(\d{2})/)
  if (annoMese) return `${annoMese[2]}/${annoMese[1]}`
  const soloAnno = d.match(/^(-?\d{1,4})/)
  return soloAnno ? soloAnno[1] : d
}

export function AuthorFactsList({ author }: { author: AuthorDetail }) {
  const { t } = useLingua()
  const voci: Array<[string, string | null]> = [
    [t('authors.field.gender'), genderShort(author.gender, t)],
    [t('authors.field.nationality'), (author.nationality ?? []).join(' · ') || null],
    [t('authors.field.birth'), formatDate(author.birth_date)],
    // Nato e senza data di morte e' vivo, non un dato mancante.
    [t('authors.field.death'), formatDate(author.death_date) ?? (author.birth_date ? t('authors.field.living') : null)],
    [t('authors.facts.occupation'), (author.occupations ?? []).join(' · ') || null],
  ]
  const presenti = voci.filter(([, v]) => v)
  if (presenti.length === 0) return null

  return (
    <dl className="grid grid-cols-[92px_1fr] gap-x-3 gap-y-0.5 text-[13px]">
      {presenti.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

interface FormProps {
  draft: FactsDraft
  onChange: (next: FactsDraft) => void
}

export function AuthorFactsForm({ draft, onChange }: FormProps) {
  const { t } = useLingua()
  const set = (k: keyof FactsDraft) => (v: string) => onChange({ ...draft, [k]: v })
  return (
    <div className="flex flex-col gap-1.5">
      <Riga label={t('authors.field.gender')}>
        <select
          value={GENERI.includes(draft.gender) || !draft.gender ? draft.gender : '__altro'}
          onChange={(e) => set('gender')(e.target.value === '__altro' ? draft.gender : e.target.value)}
          className="w-full rounded-md border border-border bg-background px-2 py-1 text-[12.5px] outline-none focus:border-primary"
        >
          <option value="">—</option>
          {GENERI.map((g) => (
            <option key={g} value={g}>
              {g === 'maschio' ? `M — ${genderLabel(g, t)}` : g === 'femmina' ? `F — ${genderLabel(g, t)}` : genderLabel(g, t)}
            </option>
          ))}
          {/* Un valore arrivato da Wikidata che non e' nell'elenco resta
              selezionabile invece di sparire dal menu e venire sostituito in
              silenzio al primo salvataggio. */}
          {draft.gender && !GENERI.includes(draft.gender) && <option value="__altro">{draft.gender}</option>}
        </select>
      </Riga>

      <Riga label={t('authors.field.nationality')}>
        <Testo value={draft.nationality} onChange={set('nationality')} placeholder={t('authors.facts.nationalityPlaceholder')} />
      </Riga>
      <Riga label={t('authors.field.birth')}>
        <Data value={draft.birth_date} onChange={set('birth_date')} t={t} />
      </Riga>
      <Riga label={t('authors.field.death')}>
        <Data value={draft.death_date} onChange={set('death_date')} placeholder={t('authors.facts.deathPlaceholder')} t={t} />
      </Riga>
      <Riga label={t('authors.facts.occupation')}>
        <Testo value={draft.occupations} onChange={set('occupations')} placeholder={t('authors.facts.occupationsPlaceholder')} />
      </Riga>
    </div>
  )
}

function Riga({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid grid-cols-[92px_1fr] items-center gap-3 text-[12.5px]">
      <span className="text-muted-foreground">{label}</span>
      {children}
    </label>
  )
}

const campoClass =
  'w-full rounded-md border border-border bg-background px-2 py-1 text-[12.5px] outline-none focus:border-primary'

function Testo({
  value, onChange, placeholder,
}: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={campoClass} />
  )
}

const DATA_COMPLETA = /^\d{4}-\d{2}-\d{2}$/

/**
 * Calendario quando la data e' completa (o assente), campo di testo quando
 * non lo e'.
 *
 * Perche' non sempre il calendario: Wikidata conserva anche date parziali —
 * "1821" per chi ha solo l'anno noto, e nella biblioteca reale ce ne sono.
 * Un <input type="date"> non puo' contenere "1821": mostrerebbe vuoto e al
 * primo salvataggio cancellerebbe l'anno che avevamo. Meglio un campo di
 * testo che conserva quello che c'e', con il calendario dove serve davvero.
 */
function Data({
  value, onChange, placeholder, t,
}: { value: string; onChange: (v: string) => void; placeholder?: string; t: (chiave: string) => string }) {
  const parziale = !!value && !DATA_COMPLETA.test(value)
  if (parziale) {
    return (
      <div className="flex items-center gap-2">
        <input value={value} onChange={(e) => onChange(e.target.value)} className={campoClass} />
        <span className="shrink-0 text-[11px] text-muted-foreground">{t('authors.facts.partialDate')}</span>
      </div>
    )
  }
  return (
    <input
      type="date"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={campoClass}
    />
  )
}
