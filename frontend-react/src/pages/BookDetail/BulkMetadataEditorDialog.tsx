import { useMemo, useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { CustomColumn } from '@/types/library'
import { bulkUpdateBooksMetadata } from '@/lib/bookActions'
import { useAuthors, useCustomColumns } from '@/lib/queries'
import { proposteAutore } from '@/lib/authorNames'
import { useLingua, type Valori } from '@/lib/i18n'

// Stessa lista di MetadataEditorDialog.tsx — duplicata qui invece di
// importata per non introdurre un accoppiamento tra i due dialog per una
// costante di 6 righe. Funzione e non oggetto costante, stesso motivo di
// fixedColumnLabels in libraryColumns.ts: deve ricalcolarsi al cambio lingua.
function languageOptions(t: (chiave: string, valori?: Valori) => string) {
  return [
    { value: '', label: '—' },
    { value: 'ita', label: t('library.metadata.lang.italian') },
    { value: 'eng', label: t('library.metadata.lang.english') },
    { value: 'fra', label: t('library.metadata.lang.french') },
    { value: 'deu', label: t('library.metadata.lang.german') },
    { value: 'spa', label: t('library.metadata.lang.spanish') },
  ]
}

// Sentinella "non modificare" — distinta da '' (che per lingua/testo libero
// è un valore reale: "campo vuoto") e da 'none' (che per valutazione/bool/
// enumerazione significa "azzera il campo"). Senza una sentinella separata,
// un campo lasciato "com'era" finirebbe per sovrascrivere ogni libro
// selezionato con un valore vuoto anche quando l'utente non l'ha toccato.
const UNCHANGED = '__unchanged__'

// Colonne personalizzate "a scelta" (select, come in MetadataEditorDialog):
// usano la sentinella UNCHANGED + 'none' per "azzera", stesso schema del
// campo Valutazione qui sotto. Le altre (testo/numero/data) usano invece
// stringa vuota = non modificare, come il campo Editore — coerente col resto
// di questo file, a costo di non poter *azzerare* in blocco quei campi (va
// bene: è un limite accettato, e azzerare in blocco testo/numero/date non
// è mai servito finora).
function isSelectCustomColumn(col: CustomColumn): boolean {
  return col.datatype === 'rating' || col.datatype === 'bool' || col.datatype === 'enumeration'
}

function defaultCustomValue(col: CustomColumn): string {
  return isSelectCustomColumn(col) ? UNCHANGED : ''
}

// Il minimo che serve per scrivere: un id e la libreria in cui vive. Non un
// `Book` intero perché la selezione arriva anche dalla pagina di un autore,
// dove i libri sono la versione ridotta di /authors/{name}/books — e dove,
// per giunta, possono venire da librerie DIVERSE (quella pagina è una vista
// globale su tutto il server).
export interface BulkMetadataTarget {
  id: number
  library: string
}

interface BulkMetadataEditorDialogProps {
  targets: BulkMetadataTarget[]
  onClose: () => void
  // `campiScritti` sono i campi davvero applicati: serve a chi ha aperto la
  // finestra per reagire a COSA è cambiato — la pagina di un autore, dopo
  // un rinomino, deve spostarsi sul nome nuovo (vedi AuthorDetailPage).
  onSaved: (librerieToccate: string[], campiScritti: Record<string, unknown>) => void
}

// Modifica metadati in blocco stile Calibre: solo i campi che l'utente tocca
// qui vengono applicati a TUTTI i libri selezionati, gli altri campi restano
// invariati per ciascun libro — a differenza di MetadataEditorDialog (un
// libro solo, tutti i campi sempre inviati). I tag sono additivi/sottrattivi
// e non sostitutivi: in blocco "aggiungi questo tag" è l'operazione che
// serve, mentre "sostituisci i tag di tutti" cancellerebbe informazione a
// ogni uso.
//
// La scrittura è UNA richiesta per libreria coinvolta (quasi sempre una
// sola), non una per libro: il giro su tutti i libri lo fa il server dentro
// una transazione — vedi CalibreLibrary.bulk_update_books.
export function BulkMetadataEditorDialog({ targets, onClose, onSaved }: BulkMetadataEditorDialogProps) {
  const { t } = useLingua()
  // Le colonne personalizzate sono definite libreria per libreria: con una
  // selezione che ne attraversa più d'una non esiste un insieme comune da
  // mostrare, e la scheda si nasconde (vedi sotto).
  const librerie = Array.from(new Set(targets.map((t) => t.library)))
  const unaSolaLibreria = librerie.length === 1
  const { data: customColumns = [] } = useCustomColumns(unaSolaLibreria ? librerie[0] : undefined)
  const { data: autoriEsistenti = [] } = useAuthors()

  const [tab, setTab] = useState('standard')
  const [author, setAuthor] = useState('')
  const [series, setSeries] = useState('')
  const [rating, setRating] = useState(UNCHANGED)
  const [publisher, setPublisher] = useState('')
  const [language, setLanguage] = useState(UNCHANGED)
  const [tagsToAdd, setTagsToAdd] = useState('')
  const [tagsToRemove, setTagsToRemove] = useState('')
  // Letto/scritto tramite getCustomValue/setCustomValue sotto invece di un
  // default calcolato in useState: customColumns arriva da una query che
  // potrebbe non essere ancora pronta al primo render (cache fredda), un
  // default statico al mount la mancherebbe.
  const [customValues, setCustomValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const proposte = useMemo(
    () => proposteAutore(author, autoriEsistenti.map((a) => a.name)),
    [author, autoriEsistenti]
  )

  function getCustomValue(col: CustomColumn): string {
    return customValues[col.label] ?? defaultCustomValue(col)
  }
  function setCustomValue(label: string, v: string) {
    setCustomValues((prev) => ({ ...prev, [label]: v }))
  }

  function listaTag(testo: string) {
    return testo
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
  }
  const newTags = listaTag(tagsToAdd)
  const goneTags = listaTag(tagsToRemove)
  const customTouched = customColumns.some((col) => getCustomValue(col) !== defaultCustomValue(col))
  const touchedAny =
    author.trim() !== '' ||
    series.trim() !== '' ||
    rating !== UNCHANGED ||
    publisher.trim() !== '' ||
    language !== UNCHANGED ||
    newTags.length > 0 ||
    goneTags.length > 0 ||
    customTouched

  function campiDaScrivere(): Record<string, unknown> {
    const fields: Record<string, unknown> = {}
    if (author.trim() !== '') fields.author = author.trim()
    if (series.trim() !== '') fields.series = series.trim()
    if (rating !== UNCHANGED) fields.rating = rating === 'none' ? null : Number(rating)
    if (publisher.trim() !== '') fields.publisher = publisher.trim()
    if (language !== UNCHANGED) fields.language = language || null
    for (const col of customColumns) {
      const v = getCustomValue(col)
      if (v === defaultCustomValue(col)) continue
      const key = `#${col.label}`
      if (col.datatype === 'bool') {
        fields[key] = v === 'none' ? null : v === 'true'
      } else if (col.datatype === 'int' || col.datatype === 'float' || col.datatype === 'rating') {
        fields[key] = v === 'none' ? null : Number(v)
      } else if (col.datatype === 'enumeration') {
        fields[key] = v === 'none' ? null : v
      } else {
        fields[key] = v
      }
    }
    return fields
  }

  async function handleApply() {
    setSaving(true)
    setError(null)
    const fields = campiDaScrivere()
    // Una richiesta per libreria: gli id di Calibre sono unici solo
    // all'interno della propria libreria, quindi una lista mescolata
    // scriverebbe sul libro sbagliato.
    const perLibreria = new Map<string, number[]>()
    for (const t of targets) perLibreria.set(t.library, [...(perLibreria.get(t.library) ?? []), t.id])

    const results = await Promise.allSettled(
      Array.from(perLibreria.entries()).map(([library, ids]) =>
        bulkUpdateBooksMetadata(library, ids, { fields, tagsAdd: newTags, tagsRemove: goneTags })
      )
    )
    const failed = results.filter((r) => r.status === 'rejected').length
    if (failed > 0) {
      setError(
        librerie.length > 1
          ? t('library.metadata.bulkSaveFailedMulti', { n: failed, total: librerie.length })
          : t('library.metadata.bulkSaveFailed')
      )
      setSaving(false)
    } else {
      onSaved(librerie, fields)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('library.metadata.bulkEditTitle', { n: targets.length })}</DialogTitle>
        </DialogHeader>
        <p className="text-[12.5px] text-muted-foreground">
          {t('library.metadata.bulkEditHint', { n: targets.length })}
        </p>

        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="standard">{t('library.metadata.standardTab')}</TabsTrigger>
            <TabsTrigger value="custom">{t('library.metadata.customTab')}</TabsTrigger>
          </TabsList>

          <TabsContent value="standard" className="grid grid-cols-1 gap-3">
            {/* Primo campo perché è il motivo per cui questa finestra esiste:
                un autore scritto male ("Rossi Mario") da correggere su
                tutti i suoi libri in una volta. */}
            <Field label={t('library.field.author')}>
              <input
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
                placeholder={t('library.metadata.notModify')}
                autoComplete="off"
                list="bulk-metadata-authors"
                className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
              />
              <datalist id="bulk-metadata-authors">
                {proposte.map((p) => (
                  <option key={p} value={p} />
                ))}
              </datalist>
              {author.trim() !== '' && (
                // Avviso e non divieto: sostituire l'autore SOSTITUISCE
                // l'elenco completo, quindi su un libro a quattro mani il
                // coautore sparisce. Chi corregge un nome invertito quasi
                // sempre non ha coautori in mezzo, ma deve poterlo sapere
                // prima.
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {t('library.metadata.authorReplaceWarning')}
                </p>
              )}
            </Field>

            <Field label={t('library.field.series')}>
              <input
                value={series}
                onChange={(e) => setSeries(e.target.value)}
                placeholder={t('library.metadata.notModify')}
                autoComplete="off"
                className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
              />
            </Field>

            <Field label={t('library.field.rating')}>
              <Select value={rating} onValueChange={setRating}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={UNCHANGED}>{t('library.metadata.notModify')}</SelectItem>
                  <SelectItem value="none">—</SelectItem>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <SelectItem key={n} value={String(n)}>
                      {'★'.repeat(n)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <Field label={t('library.field.publisher')}>
              <input
                value={publisher}
                onChange={(e) => setPublisher(e.target.value)}
                placeholder={t('library.metadata.notModify')}
                autoComplete="off"
                className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
              />
            </Field>

            <Field label={t('library.field.language')}>
              <Select value={language} onValueChange={setLanguage}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={UNCHANGED}>{t('library.metadata.notModify')}</SelectItem>
                  {languageOptions(t).map((l) => (
                    <SelectItem key={l.value || '__none__'} value={l.value}>
                      {l.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <Field label={t('library.metadata.addTagsLabel')}>
              <input
                value={tagsToAdd}
                onChange={(e) => setTagsToAdd(e.target.value)}
                placeholder={t('library.metadata.addTagsPlaceholder')}
                autoComplete="off"
                className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
              />
            </Field>

            <Field label={t('library.metadata.removeTagsLabel')}>
              <input
                value={tagsToRemove}
                onChange={(e) => setTagsToRemove(e.target.value)}
                placeholder={t('library.metadata.removeTagsPlaceholder')}
                autoComplete="off"
                className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
              />
            </Field>
          </TabsContent>

          <TabsContent value="custom" className="grid grid-cols-1 gap-3">
            {!unaSolaLibreria && (
              <p className="text-[12.5px] text-muted-foreground">
                {t('library.metadata.multiLibraryCustomColumnsNotice', { n: librerie.length })}
              </p>
            )}
            {unaSolaLibreria && customColumns.length === 0 && (
              <p className="text-[12.5px] text-muted-foreground">{t('library.metadata.noCustomColumns')}</p>
            )}
            {customColumns.map((col) => {
              const value = getCustomValue(col)
              return (
                <Field key={col.label} label={col.name}>
                  {col.datatype === 'rating' ? (
                    <Select value={value} onValueChange={(v) => setCustomValue(col.label, v)}>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={UNCHANGED}>{t('library.metadata.notModify')}</SelectItem>
                        <SelectItem value="none">—</SelectItem>
                        {[1, 2, 3, 4, 5].map((n) => (
                          <SelectItem key={n} value={String(n)}>
                            {'★'.repeat(n)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : col.datatype === 'bool' ? (
                    <Select value={value} onValueChange={(v) => setCustomValue(col.label, v)}>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={UNCHANGED}>{t('library.metadata.notModify')}</SelectItem>
                        <SelectItem value="none">—</SelectItem>
                        <SelectItem value="true">{t('common.yes')}</SelectItem>
                        <SelectItem value="false">{t('common.no')}</SelectItem>
                      </SelectContent>
                    </Select>
                  ) : col.datatype === 'enumeration' ? (
                    <Select value={value} onValueChange={(v) => setCustomValue(col.label, v)}>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={UNCHANGED}>{t('library.metadata.notModify')}</SelectItem>
                        <SelectItem value="none">—</SelectItem>
                        {(Array.isArray(col.display?.enum_values) ? (col.display.enum_values as string[]) : []).map((opt) => (
                          <SelectItem key={opt} value={opt}>
                            {opt}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : col.datatype === 'datetime' ? (
                    <input
                      value={value}
                      onChange={(e) => setCustomValue(col.label, e.target.value)}
                      type="date"
                      placeholder={t('library.metadata.notModify')}
                      className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
                    />
                  ) : (
                    <input
                      value={value}
                      onChange={(e) => setCustomValue(col.label, e.target.value)}
                      type={col.datatype === 'int' || col.datatype === 'float' ? 'number' : 'text'}
                      placeholder={t('library.metadata.notModify')}
                      autoComplete="off"
                      className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
                    />
                  )}
                </Field>
              )
            })}
          </TabsContent>
        </Tabs>

        {error && <p className="text-[12.5px] text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleApply} disabled={saving || !touchedAny}>
            {saving ? t('library.metadata.applying') : t('library.metadata.apply')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  )
}
