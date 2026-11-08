import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Loader2, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { SortableTableHead } from '@/components/ui/sortable-table-head'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { formatDateTime } from '@/lib/deviceFormat'
import { sortByAccessor } from '@/lib/tableSort'
import { dictionaryErrorDetail } from '@/lib/dictionaryActions'
import { fetchVocabularyDefinition, useVocabulary, type VocabularyItem } from '@/lib/vocabularyActions'
import { useLingua, type Lingua, type Valori } from '@/lib/i18n'

type Traduci = (chiave: string, valori?: Valori) => string
import { SovrapposizioniPanel } from './SovrapposizioniPanel'

type SortKey = 'word' | 'source_label' | 'create_time'

// Da dove viene una parola. Per un dispositivo è il nome che gli ha dato chi
// l'ha registrato — dato dell'utente, non si traduce. Per il lettore web è
// un'etichetta d'interfaccia, e il server la manda vuota apposta (vedi
// api/vocabulary.py): la scrive qui chi conosce la lingua.
function etichettaOrigine(v: VocabularyItem, t: Traduci): string {
  return v.source === 'web' ? t('annotations.device.webReader') : v.source_label
}

// Ordinare per origine deve seguire quello che si LEGGE nella colonna, non
// il campo grezzo: altrimenti le parole del lettore web, che hanno
// source_label vuoto, finiscono tutte in testa qualunque sia la lingua.
function accessori(t: Traduci): Record<SortKey, (v: VocabularyItem) => string | number> {
  return {
    word: (v) => v.word || '',
    source_label: (v) => etichettaOrigine(v, t),
    create_time: (v) => v.create_time || '',
  }
}

// La Wikizionario giusta è quella della lingua in cui si sta leggendo
// l'interfaccia: con l'inglese, «it.wiktionary.org» portava a una pagina
// quasi sempre inesistente.
function wiktionaryUrl(word: string, lingua: Lingua) {
  return `https://${lingua}.wiktionary.org/wiki/${encodeURIComponent(word)}`
}

// Vocabulary Builder centralizzato: unisce le parole di ogni dispositivo
// KOReader ("Vocabolario" nella pagina del singolo dispositivo, vedi
// DeviceVocabularyTable.tsx) con quelle aggiunte dal reader web (popup di
// selezione parola, vedi ReaderPage.tsx) in un'unica lista — invece di dover
// aprire ogni dispositivo separatamente per ritrovare le proprie parole.
// Stessa scheda "flashcard" (definizione sopra, esempio sotto) della pagina
// dispositivo, qui con in più la provenienza (dispositivo/web) e un link al
// libro quando conosciuto (solo per le parole aggiunte dal reader web, che
// nascono già dentro un libro Kolibre — vedi WebVocabularyEntry nel backend).
export function VocabularyPage() {
  const { t, lingua } = useLingua()
  useSetPageHeader(t('vocabulary.pageTitle'))
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: vocabulary = [], isLoading } = useVocabulary()

  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('create_time')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [selected, setSelected] = useState<VocabularyItem | null>(null)
  const [fetchingDefinition, setFetchingDefinition] = useState(false)
  const [definitionError, setDefinitionError] = useState<string | null>(null)

  async function handleFetchDefinition(entry: VocabularyItem) {
    setFetchingDefinition(true)
    setDefinitionError(null)
    try {
      const result = await fetchVocabularyDefinition(entry.id)
      setSelected((prev) => (prev && prev.id === entry.id ? { ...prev, ...result } : prev))
      await queryClient.invalidateQueries({ queryKey: ['vocabulary'] })
    } catch (err) {
      setDefinitionError(dictionaryErrorDetail(err, t('vocabulary.definition.notFound')))
    } finally {
      setFetchingDefinition(false)
    }
  }

  function handleSelectRow(entry: VocabularyItem) {
    setSelected(entry)
    setDefinitionError(null)
    if (!entry.definition) {
      void handleFetchDefinition(entry)
    }
  }

  function handleSortClick(key: SortKey) {
    if (key === sortKey) {
      setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortOrder('asc')
    }
  }

  function openBook(entry: VocabularyItem) {
    if (!entry.library || !entry.calibre_book_id) return
    navigate(`/libri/${entry.calibre_book_id}`, { state: { libraryFolder: entry.library } })
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return vocabulary
    return vocabulary.filter(
      (v) =>
        v.word.toLowerCase().includes(q) ||
        (v.highlight || '').toLowerCase().includes(q) ||
        (v.book_title || '').toLowerCase().includes(q) ||
        etichettaOrigine(v, t).toLowerCase().includes(q)
    )
  }, [vocabulary, search, t])

  const sorted = useMemo(() => sortByAccessor(filtered, accessori(t), sortKey, sortOrder), [filtered, sortKey, sortOrder, t])

  return (
    <div className="space-y-3">
      {/* I vocabolari copiati fra due lettori si vedono qui, non piu' dentro
          la scheda del singolo dispositivo: la sovrapposizione e' una
          relazione FRA due, e uno alla volta non si vedeva mai tutta. */}
      <SovrapposizioniPanel />

      <div className="relative max-w-[280px]">
        <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground/70" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('vocabulary.search.placeholder')}
          className="w-full rounded-md border border-border bg-background py-1.5 pr-2.5 pl-7 text-[13px] outline-none focus:border-primary"
        />
      </div>

      {isLoading ? (
        <p className="text-[12px] text-muted-foreground">{t('common.loading')}</p>
      ) : sorted.length === 0 ? (
        <p className="text-[12px] text-muted-foreground">
          {vocabulary.length === 0 ? t('vocabulary.empty.none') : t('vocabulary.empty.noMatch')}
        </p>
      ) : (
        <div className="overflow-y-auto rounded-md border border-border">
          <Table>
            <TableHeader className="sticky top-0 bg-card">
              <TableRow>
                <SortableTableHead label={t('vocabulary.column.term')} sortKey="word" active={sortKey === 'word'} order={sortOrder} onClick={handleSortClick} />
                <TableHead>{t('vocabulary.column.book')}</TableHead>
                <SortableTableHead
                  label={t('vocabulary.column.source')}
                  sortKey="source_label"
                  active={sortKey === 'source_label'}
                  order={sortOrder}
                  onClick={handleSortClick}
                />
                <SortableTableHead
                  label={t('vocabulary.column.encountered')}
                  sortKey="create_time"
                  active={sortKey === 'create_time'}
                  order={sortOrder}
                  onClick={handleSortClick}
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((v) => (
                <TableRow key={v.id} className="cursor-pointer" onClick={() => handleSelectRow(v)}>
                  <TableCell className="font-medium">{v.highlight || v.word}</TableCell>
                  <TableCell>
                    {v.library && v.calibre_book_id ? (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          openBook(v)
                        }}
                        className="text-primary hover:underline"
                      >
                        {v.book_title || t('vocabulary.openBook')}
                      </button>
                    ) : (
                      <span className="text-muted-foreground">{v.book_title || '—'}</span>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">
                    {v.source === 'web' ? '🌐 ' : '📱 '}
                    {etichettaOrigine(v, t)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">{formatDateTime(v.create_time)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
        {selected && (
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                {selected.highlight || selected.word}
                <a
                  href={wiktionaryUrl(selected.word, lingua)}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={t('vocabulary.wiktionary.searchTitle')}
                  className="text-muted-foreground hover:text-foreground"
                >
                  <ExternalLink className="size-3.5" />
                </a>
              </DialogTitle>
            </DialogHeader>
            {/* Definizione — la parte principale della scheda, in cima (stessa struttura di DeviceVocabularyTable.tsx). */}
            <div className="flex flex-col gap-1.5">
              {fetchingDefinition && !selected.definition && (
                <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
                  <Loader2 className="size-3.5 animate-spin" /> {t('vocabulary.definition.loading')}
                </p>
              )}
              {selected.definition && (
                <>
                  <p className="text-[14px] leading-relaxed">{selected.definition}</p>
                  <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                    <span>{t('vocabulary.definition.source', { source: selected.definition_source ?? '' })}</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void handleFetchDefinition(selected)}
                      disabled={fetchingDefinition}
                    >
                      {fetchingDefinition ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />}
                      {t('vocabulary.definition.refresh')}
                    </Button>
                  </div>
                </>
              )}
              {!fetchingDefinition && !selected.definition && (
                <div className="flex flex-col gap-1.5">
                  {definitionError && <p className="text-[12.5px] text-muted-foreground">{definitionError}</p>}
                  <Button variant="outline" size="sm" className="self-start" onClick={() => void handleFetchDefinition(selected)}>
                    <Search className="size-3.5" /> {t('vocabulary.definition.search')}
                  </Button>
                </div>
              )}
            </div>

            {/* Esempio + provenienza — sotto la definizione. */}
            <div className="flex flex-col gap-1 border-t border-border pt-2.5">
              {(selected.context_before || selected.context_after) && (
                <p className="text-[13px] leading-relaxed text-muted-foreground">
                  {selected.context_before}
                  <span className="font-medium text-foreground">{selected.highlight || selected.word}</span>
                  {selected.context_after}
                </p>
              )}
              <p className="text-[11px] text-muted-foreground">
                {selected.source === 'web' ? '🌐 ' : '📱 '}
                {etichettaOrigine(selected, t)}
                {selected.book_title ? ` · ${selected.book_title}` : ''} · {formatDateTime(selected.create_time)}
              </p>
            </div>
          </DialogContent>
        )}
      </Dialog>
    </div>
  )
}
