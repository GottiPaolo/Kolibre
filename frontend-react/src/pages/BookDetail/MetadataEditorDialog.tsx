import { useEffect, useMemo, useState } from 'react'
import { Cloud } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { Book } from '@/types/library'
import { useAuthors, useBookDescription, useBooks, useCustomColumns } from '@/lib/queries'
import { proposteAutore } from '@/lib/authorNames'
import { updateBookMetadata, searchMetadataOnline } from '@/lib/bookActions'
import { withBackendUrl } from '@/lib/api'
import { identifierRowsFromDict, identifierRowsToDict, identifierTypeOptions, type IdentifierRow } from '@/lib/identifiers'
import { useBookActions } from '@/lib/bookActionsContext'
import { useLingua, type Valori } from '@/lib/i18n'

// Nomi delle lingue nella lingua dell'interfaccia — non nella lingua stessa
// (l'italiano non diventa "Italian" passando a inglese): e' una scelta,
// coerente con authors.detail.langEnglish/langItalian che fa lo stesso.
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

interface MetadataEditorDialogProps {
  book: Book
  libraryFolder: string
  onClose: () => void
  onSaved: () => void
  onRequestOnlineSearch: () => void
}

export function MetadataEditorDialog({ book, libraryFolder, onClose, onSaved, onRequestOnlineSearch }: MetadataEditorDialogProps) {
  const { t } = useLingua()
  const { showMetadataSearchResults } = useBookActions()
  const descriptionQuery = useBookDescription(libraryFolder, book.id)
  const { data: customColumns = [] } = useCustomColumns(libraryFolder)

  // Suggerimenti per l'autocomplete: Autore è cross-libreria (stesso elenco
  // della pagina Autori), Serie/Editore sono derivati dai libri già in
  // cache di QUESTA libreria (nessun endpoint dedicato, stesso principio
  // già usato per la pagina Serie) — via <datalist>, nessuna libreria
  // aggiuntiva necessaria.
  const { data: authors = [] } = useAuthors()
  const { data: libraryBooks = [] } = useBooks(libraryFolder)
  const seriesOptions = useMemo(
    () => Array.from(new Set(libraryBooks.map((b) => b.series).filter((s): s is string => !!s))).sort((a, b) => a.localeCompare(b, 'it')),
    [libraryBooks]
  )
  const publisherOptions = useMemo(
    () => Array.from(new Set(libraryBooks.map((b) => b.publisher).filter((p): p is string => !!p))).sort((a, b) => a.localeCompare(b, 'it')),
    [libraryBooks]
  )

  const [tab, setTab] = useState('standard')
  const [title, setTitle] = useState(book.title)
  const [author, setAuthor] = useState(book.author)
  const [series, setSeries] = useState(book.series ?? '')
  const [seriesIndex, setSeriesIndex] = useState(book.series_index != null ? String(book.series_index) : '')
  const [tagsText, setTagsText] = useState(book.tags.join(', '))
  const [identifierRows, setIdentifierRows] = useState<IdentifierRow[]>(() => identifierRowsFromDict(book.identifiers))
  const [publisher, setPublisher] = useState(book.publisher ?? '')
  const [language, setLanguage] = useState(book.language ?? '')
  // pubdate arriva già come solo-data YYYY-MM-DD (vedi format.ts) — stesso
  // formato atteso da <input type="date">, nessuna conversione necessaria.
  // Scrivibile da tempo lato backend (CalibreLibrary.update_book,
  // allowed_columns include "pubdate") ma senza UI che lo inviasse mai.
  const [pubdate, setPubdate] = useState(book.pubdate ?? '')
  // Valutazione nativa Calibre (books_ratings_link, distinta da un'eventuale
  // colonna personalizzata di tipo rating) — nel Vue esistente era una delle
  // colonne modificabili inline in tabella (saveEdit); qui è l'unico posto
  // dove modificarla, dato che la tabella React è sola-lettura. Il backend
  // (set_rating) supporta già questo campo, semplicemente nessuna UI lo
  // inviava mai.
  const [rating, setRating] = useState(book.rating != null ? String(book.rating) : '')
  const [description, setDescription] = useState(book.description ?? '')
  // Le colonne personalizzate non si catturano al montaggio: `customColumns`
  // arriva da una query, e a cache fredda al primo render è vuota. Prima il
  // valore iniziale veniva calcolato lì una volta sola, quindi restava {}, e
  // al salvataggio il ciclo sulle colonne (nel frattempo arrivate) le trovava
  // tutte "non impostate" e mandava `null` per ognuna: i valori del libro
  // sparivano senza che nessuno li avesse toccati. Il dialogo gemello
  // (BulkMetadataEditorDialog) evita la stessa trappola e lo spiega.
  //
  // Qui si tiene traccia di cosa l'utente ha toccato davvero: quello che non
  // ha toccato non viene scritto affatto, quindi non può essere azzerato per
  // errore — e svuotare un campo resta un tocco, quindi cancellare funziona.
  const [customValues, setCustomValues] = useState<Record<string, string>>({})
  const [customToccate, setCustomToccate] = useState<Set<string>>(() => new Set())

  function valoreColonna(col: { label: string; datatype: string }): string {
    if (customToccate.has(col.label)) return customValues[col.label] ?? ''
    const v = book[`#${col.label}`]
    if (v === null || v === undefined) return ''
    // 'datetime' può arrivare come timestamp Calibre completo
    // ("2024-05-12T10:30:00+00:00") — <input type="date"> vuole solo
    // YYYY-MM-DD, stessa estrazione già usata per pubdate/formatDate.
    return col.datatype === 'datetime' ? String(v).slice(0, 10) : String(v)
  }
  const [saving, setSaving] = useState(false)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Il testo bulk è troncato a 400 caratteri (vedi backend/app/api/books.py)
  // — sostituire con quello completo appena arriva, PRIMA che si possa
  // salvare, altrimenti un salvataggio che tocca solo il titolo
  // troncherebbe la descrizione reale sul DB (bug storico già corretto nel
  // Vue esistente, commento a saveMetadata/editMetadata).
  useEffect(() => {
    if (descriptionQuery.data !== undefined && descriptionQuery.data !== null) {
      setDescription(descriptionQuery.data)
    }
  }, [descriptionQuery.data])

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const fields: Record<string, unknown> = {
        title,
        author,
        series: series || null,
        series_index: seriesIndex ? Number(seriesIndex) : null,
        tags: tagsText.split(',').map((t) => t.trim()).filter(Boolean),
        identifiers: identifierRowsToDict(identifierRows),
        publisher: publisher || null,
        language: language || null,
        description,
        rating: rating ? Number(rating) : null,
        pubdate: pubdate || null,
      }
      for (const col of customColumns) {
        // Solo le colonne toccate: vedi il commento su customToccate.
        if (!customToccate.has(col.label)) continue
        const v = customValues[col.label]
        const unset = v === undefined || v === ''
        if (col.datatype === 'bool') {
          fields[`#${col.label}`] = unset ? null : v === 'true'
        } else if (col.datatype === 'int' || col.datatype === 'float' || col.datatype === 'rating') {
          fields[`#${col.label}`] = unset ? null : Number(v)
        } else {
          fields[`#${col.label}`] = unset ? null : v
        }
      }
      await updateBookMetadata(libraryFolder, book.id, fields)
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('library.metadata.saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  async function handleOnlineSearch() {
    setSearching(true)
    setError(null)
    try {
      const candidates = await searchMetadataOnline(libraryFolder, book.id)
      onClose()
      if (candidates.length === 0) {
        onRequestOnlineSearch()
      } else {
        showMetadataSearchResults(book, libraryFolder, candidates)
      }
    } catch {
      setError(t('library.metadata.onlineSearchFailed'))
      setSearching(false)
    }
  }

  function updateIdentifierRow(idx: number, patch: Partial<IdentifierRow>) {
    setIdentifierRows((rows) => rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  const descriptionLoading = descriptionQuery.isLoading

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-6xl">
        <DialogHeader>
          <DialogTitle>{t('library.detail.editMetadata')}</DialogTitle>
        </DialogHeader>

        {/* La copertina, che mancava: e' il modo piu' rapido per accorgersi
            di stare modificando il libro sbagliato — succede aprendo la
            finestra da una riga selezionata per errore, o dopo una ricerca
            che ha cambiato l'ordine sotto le mani. Titolo e autore da soli
            non bastano, perche' in una biblioteca ci sono piu' edizioni
            dello stesso libro. */}
        <div className="flex items-center gap-3 rounded-md border border-border bg-muted/30 p-2.5">
          <div className="h-20 w-14 shrink-0 overflow-hidden rounded bg-muted">
            {book.cover_url ? (
              <img src={withBackendUrl(book.cover_url)} alt="" className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-[10px] text-muted-foreground">
                {t('library.metadata.noneCover')}
              </div>
            )}
          </div>
          <div className="min-w-0">
            <p className="truncate font-serif text-[14px] font-medium">{book.title}</p>
            <p className="truncate text-[12px] text-muted-foreground">{book.author || '—'}</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {book.formats?.length ? book.formats.join(' · ') : t('library.metadata.noFormat')}
            </p>
          </div>
        </div>

        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="standard">{t('library.metadata.standardTab')}</TabsTrigger>
            <TabsTrigger value="custom">{t('library.metadata.customTab')}</TabsTrigger>
          </TabsList>

          <TabsContent
            value="standard"
            className="grid max-h-[65vh] grid-cols-1 gap-x-4 gap-y-3 overflow-y-auto pr-1 sm:grid-cols-2"
          >
            <Field label={t('library.field.title')}>
              <Input value={title} onChange={setTitle} />
            </Field>
            <Field label={t('library.field.author')}>
              <Input value={author} onChange={setAuthor} list="metadata-authors-datalist" />
            </Field>

            <Field label={t('library.field.identifiers')} className="sm:col-span-2">
              <div className="grid grid-cols-1 gap-x-3 gap-y-1.5 sm:grid-cols-2">
                {identifierRows.map((row, idx) => (
                  <div key={idx} className="flex gap-1.5">
                    <Select value={row.type} onValueChange={(v) => updateIdentifierRow(idx, { type: v })}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {identifierTypeOptions(row.type).map((t) => (
                          <SelectItem key={t} value={t}>
                            {t}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <input
                      value={row.value}
                      onChange={(e) => updateIdentifierRow(idx, { value: e.target.value })}
                      className="flex-1 rounded-md border border-border bg-background px-2 py-1 text-[12.5px] outline-none focus:border-primary"
                    />
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => setIdentifierRows((rows) => rows.filter((_, i) => i !== idx))}
                    >
                      ✕
                    </Button>
                  </div>
                ))}
              </div>
              <Button
                variant="outline"
                size="sm"
                className="mt-1.5"
                onClick={() => setIdentifierRows((rows) => [...rows, { type: 'isbn', value: '' }])}
              >
                + {t('library.metadata.addIdentifier')}
              </Button>
            </Field>

            <div className="grid grid-cols-[1fr_6rem_9rem] gap-3">
              <Field label={t('library.metadata.seriesLabel')}>
                <Input value={series} onChange={setSeries} list="metadata-series-datalist" />
              </Field>
              <Field label={t('library.field.seriesIndex')}>
                <Input value={seriesIndex} onChange={setSeriesIndex} type="number" />
              </Field>
              <Field label={t('library.metadata.pubdateLabel')}>
                <Input value={pubdate} onChange={setPubdate} type="date" />
              </Field>
            </div>

            <div className="grid grid-cols-[1fr_8rem_8rem] gap-3">
              <Field label={t('library.field.publisher')}>
                <Input value={publisher} onChange={setPublisher} list="metadata-publisher-datalist" />
              </Field>
              <Field label={t('library.field.language')}>
                <Select value={language} onValueChange={setLanguage}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {languageOptions(t).map((l) => (
                      <SelectItem key={l.value} value={l.value}>
                        {l.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label={t('library.field.rating')}>
                <Select value={rating || 'none'} onValueChange={(v) => setRating(v === 'none' ? '' : v)}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">—</SelectItem>
                    {[1, 2, 3, 4, 5].map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        {'★'.repeat(n)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </div>

            <Field label={t('library.metadata.tagsCommaLabel')} className="sm:col-span-2">
              <Input value={tagsText} onChange={setTagsText} />
            </Field>

            <Field label={t('library.field.description')} className="sm:col-span-2">
              {descriptionLoading ? (
                <div className="rounded-md border border-border bg-muted/40 px-2.5 py-4 text-center text-[12px] text-muted-foreground">
                  {t('library.metadata.loadingFullText')}
                </div>
              ) : (
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={7}
                  className="w-full resize-none rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
                />
              )}
            </Field>
          </TabsContent>

          <TabsContent
            value="custom"
            className="grid max-h-[65vh] grid-cols-1 gap-x-4 gap-y-3 overflow-y-auto pr-1 sm:grid-cols-2"
          >
            {customColumns.length === 0 && (
              <p className="text-[12.5px] text-muted-foreground sm:col-span-2">
                {t('library.metadata.noCustomColumns')}
              </p>
            )}
            {customColumns.map((col) => {
              const value = valoreColonna(col)
              const setValue = (v: string) => {
                setCustomValues((values) => ({ ...values, [col.label]: v }))
                setCustomToccate((toccate) => new Set(toccate).add(col.label))
              }
              return (
                <Field key={col.label} label={col.name}>
                  {col.datatype === 'rating' ? (
                    <Select value={value || 'none'} onValueChange={(v) => setValue(v === 'none' ? '' : v)}>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">—</SelectItem>
                        {[1, 2, 3, 4, 5].map((n) => (
                          <SelectItem key={n} value={String(n)}>
                            {'★'.repeat(n)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : col.datatype === 'bool' ? (
                    <Select value={value || 'none'} onValueChange={(v) => setValue(v === 'none' ? '' : v)}>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">—</SelectItem>
                        <SelectItem value="true">{t('common.yes')}</SelectItem>
                        <SelectItem value="false">{t('common.no')}</SelectItem>
                      </SelectContent>
                    </Select>
                  ) : col.datatype === 'enumeration' ? (
                    <Select value={value || 'none'} onValueChange={(v) => setValue(v === 'none' ? '' : v)}>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">—</SelectItem>
                        {(Array.isArray(col.display?.enum_values) ? (col.display.enum_values as string[]) : []).map((opt) => (
                          <SelectItem key={opt} value={opt}>
                            {opt}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : col.datatype === 'datetime' ? (
                    <Input value={value} onChange={setValue} type="date" />
                  ) : (
                    <Input value={value} onChange={setValue} type={col.datatype === 'int' || col.datatype === 'float' ? 'number' : 'text'} />
                  )}
                </Field>
              )
            })}
          </TabsContent>
        </Tabs>

        {error && <p className="text-[12.5px] text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={handleOnlineSearch} disabled={searching || descriptionLoading}>
            <Cloud className="size-3.5" />
            {searching ? t('library.metadata.searchingShort') : t('library.metadata.downloadMetadataAndCovers')}
          </Button>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleSave} disabled={saving || descriptionLoading}>
            {saving ? t('library.metadata.saving') : t('common.save')}
          </Button>
        </DialogFooter>

        <datalist id="metadata-authors-datalist">
          {proposteAutore(author, authors.map((a) => a.name)).map((p) => (
            <option key={p} value={p} />
          ))}
        </datalist>
        <datalist id="metadata-series-datalist">
          {seriesOptions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
        <datalist id="metadata-publisher-datalist">
          {publisherOptions.map((p) => (
            <option key={p} value={p} />
          ))}
        </datalist>
      </DialogContent>
    </Dialog>
  )
}

function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <label className="mb-1 block text-[11px] font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  )
}

function Input({
  value,
  onChange,
  type = 'text',
  list,
}: {
  value: string
  onChange: (v: string) => void
  type?: string
  list?: string
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      list={list}
      autoComplete="off"
      className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
    />
  )
}
