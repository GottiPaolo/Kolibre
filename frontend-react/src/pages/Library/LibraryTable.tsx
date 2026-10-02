import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DeviceBookColumnState } from '@/lib/deviceFormat'
import type { Book, CustomColumn } from '@/types/library'
import type { SortCriterion } from './sort'
import { renderCellValue } from './sort'
import { formatBytes, formatDate, isoLocale, ratingStars } from '@/lib/format'
import { columnWidth,
  rowHeight, MIN_COLUMN_WIDTH } from '@/lib/libraryColumns'
import { withBackendUrl } from '@/lib/api'
import { useBookActions } from '@/lib/bookActionsContext'
import { useAuthors } from '@/lib/queries'
import { errorDetail } from '@/lib/librarySettingsActions'
import { BookContextMenu } from '@/components/BookContextMenu'
import { BulkBookContextMenu } from '@/components/BulkBookContextMenu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  ContextMenu,
  ContextMenuCheckboxItem,
  ContextMenuContent,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import { toast } from '@/lib/toast'
import { useScrollMemory } from '@/lib/useScrollMemory'
import { useLingua } from '@/lib/i18n'

// Colonne con editing inline sulla riga selezionata (vedi LibraryRow e i
// *CellEditor* più sotto): 'rating'/'author' sono le due colonne native
// storiche, `#<label>` è qualunque colonna personalizzata (l'editor esatto
// usato dipende dal suo CustomColumn.datatype — vedi il dispatch in
// LibraryRow).
type EditableField = 'rating' | 'author' | `#${string}`

interface ColumnDef {
  id: string
  label: string
}

// Modificatori tastiera al momento del click su una riga — un tipo
// strutturale invece di React.MouseEvent perché deve valere anche per la
// selezione via tastiera (frecce), che non ha un evento mouse da passare.
export type SelectModifiers = { shiftKey?: boolean; metaKey?: boolean; ctrlKey?: boolean }

interface LibraryTableProps {
  books: Book[]
  columns: ColumnDef[]
  allColumns: ColumnDef[]
  visibleColumnIds: string[]
  columnWidths: Record<string, number>
  sortCriteria: SortCriterion[]
  onSortClick: (colId: string, shiftKey: boolean) => void
  selectedBookId: number | null
  onSelectBook: (book: Book, modifiers?: SelectModifiers) => void
  // Selezione multipla (Cmd/Shift-click) per le azioni bulk del menu
  // contestuale (elimina/invia-rimuovi dispositivo/modifica metadati in
  // blocco — vedi BulkBookContextMenu). Opzionale: il picker di
  // accoppiamento dispositivo (BookPickerDialog, interactive=false) non la
  // passa, e la tabella ricade semplicemente su { selectedBookId } come
  // prima — vedi effectiveSelectedIds più sotto.
  selectedIds?: Set<number>
  customColumns: CustomColumn[]
  onReorderColumns: (newOrder: string[]) => void
  onResizeColumn: (colId: string, width: number) => void
  onToggleColumn: (colId: string) => void
  // false nel picker di accoppiamento dispositivo (BookPickerDialog): quel
  // contesto riusa la tabella Libreria per la sola scelta di un libro, il
  // menu contestuale con "Elimina"/azioni distruttive non ha senso lì e
  // sarebbe un rischio reale, non solo rumore visivo.
  interactive?: boolean
  // Percentuale di avanzamento per calibre_book_id (colonna "Avanzamento"),
  // già combinata tra dispositivi lato backend (vedi useReadingProgress —
  // ReadingPosition è una singola posizione "vincente" per libro, l'ultimo
  // dispositivo che ha scritto, stile kosync). Nessuna combinazione da fare
  // qui: un libro assente dalla mappa è semplicemente "non ancora iniziato".
  progressByBookId?: Record<number, number>
  // Stato per le colonne dinamiche "Su: <dispositivo>" (una per device
  // registrato, colId `device-<id>`) — vedi LibraryPage per il calcolo.
  deviceStatusByBookId?: Record<number, Record<number, DeviceBookColumnState>>
}

// Colonne numeriche "vere" (allineate a destra, cifre tabellari) — le
// colonne rating (native o personalizzate) NON rientrano qui: sono stelle,
// non numeri, restano allineate a sinistra come nel resto della tabella.
function isNumericColumn(colId: string, customColumns: CustomColumn[]): boolean {
  if (colId === 'size' || colId === 'series_index') return true
  if (colId.startsWith('#')) {
    const col = customColumns.find((c) => c.label === colId.slice(1))
    return col?.datatype === 'int' || col?.datatype === 'float'
  }
  return false
}

function specialCell(
  book: Book,
  colId: string,
  progressPercent: number | undefined,
  deviceStatus: Record<number, DeviceBookColumnState> | undefined,
  customColumns: CustomColumn[],
  t: (chiave: string, valori?: Record<string, string | number>) => string
) {
  // Colonna rating personalizzata: stessa resa a stelline colorate della
  // colonna nativa "Valutazione" qui sotto — prima finiva nel ramo generico
  // di renderCellValue come testo piatto '★★★☆☆' senza colore.
  if (colId.startsWith('#')) {
    const col = customColumns.find((c) => c.label === colId.slice(1))
    if (col?.datatype === 'rating') {
      const value = book[colId]
      if (value === null || value === undefined || value === '') return <span className="text-muted-foreground">—</span>
      return <span className="text-[var(--warning)] tracking-wide">{'★'.repeat(Number(value))}</span>
    }
  }
  if (colId === 'cover')
    return book.cover_url ? (
      // h-full: la copertina riempie la riga, che e' stata alzata apposta
      // per lei (vedi rowHeight). object-contain e non object-cover: meglio
      // un margine ai lati che un ritaglio, visto che le proporzioni delle
      // copertine vere non sono tutte identiche.
      <img src={withBackendUrl(book.cover_url)} alt="" loading="lazy" className="h-full w-full rounded-sm object-contain" />
    ) : (
      <div className="h-full w-full rounded-sm bg-muted" />
    )
  if (colId === 'size') return formatBytes(book.size)
  if (colId === 'date_added') return formatDate(book.date_added)
  if (colId === 'rating') {
    const stars = ratingStars(book.rating)
    if (stars === '—') return <span className="text-muted-foreground">—</span>
    return <span className="text-[var(--warning)] tracking-wide">{stars}</span>
  }
  if (colId === 'formats') {
    if (!book.formats?.length) return <span className="text-muted-foreground">—</span>
    return (
      <div className="flex flex-wrap gap-1">
        {book.formats.map((f) => (
          <span
            key={f}
            className="rounded-full bg-muted px-2 py-0.5 text-[10.5px] font-semibold text-muted-foreground"
          >
            {f}
          </span>
        ))}
      </div>
    )
  }
  if (colId === 'progress') {
    if (progressPercent == null) return <span className="text-muted-foreground">—</span>
    return (
      <div className="flex w-full items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary" style={{ width: `${progressPercent}%` }} />
        </div>
        <span className="shrink-0 text-[11px] text-muted-foreground">{progressPercent}%</span>
      </div>
    )
  }
  if (colId.startsWith('device-')) {
    const deviceId = Number(colId.slice('device-'.length))
    const state = deviceStatus?.[deviceId]
    if (state === 'on') return <span className="text-primary" title={t('library.device.onDevice')}>✓</span>
    if (state === 'queued')
      return (
        <span className="text-[var(--warning)]" title={t('library.device.queued')}>
          ⏳
        </span>
      )
    if (state === 'pending_delete')
      return (
        <span className="text-destructive" title={t('library.device.pendingDelete')}>
          🗑
        </span>
      )
    return <span className="text-muted-foreground">–</span>
  }
  return null
}

// Picker compatto per la valutazione, aperto direttamente al montaggio
// (nessun secondo click sul trigger): stessa lista di opzioni (5 stelle +
// "—") del Select "Valutazione" in MetadataEditorDialog, per coerenza
// visiva. Si chiude su Escape/click fuori/selezione — onOpenChange(false)
// copre tutti e tre i casi, radix se ne occupa da solo.
function RatingCellEditor({
  value,
  onCommit,
  onCancel,
}: {
  value: number | null
  onCommit: (rating: number | null) => void
  onCancel: () => void
}) {
  return (
    <div onClick={(e) => e.stopPropagation()}>
      <Select
        defaultOpen
        value={value != null ? String(value) : 'none'}
        onOpenChange={(open) => {
          if (!open) onCancel()
        }}
        onValueChange={(v) => onCommit(v === 'none' ? null : Number(v))}
      >
        <SelectTrigger className="h-6 w-full border-none bg-transparent px-0 py-0 shadow-none">
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
    </div>
  )
}

// Input inline con autocomplete via <datalist> (stesso pattern del campo
// Autore in MetadataEditorDialog) — la datalist condivisa è renderizzata
// una sola volta in LibraryTable (id "library-authors-datalist"), non per
// riga: un <datalist> è referenziabile per id da qualunque punto del DOM.
// Blur = "click fuori" quindi annulla; solo Invio salva (committedRef
// distingue i due casi quando Invio fa perdere il focus all'input).
function AuthorCellEditor({
  value,
  onCommit,
  onCancel,
}: {
  value: string
  onCommit: (author: string) => void
  onCancel: () => void
}) {
  const [text, setText] = useState(value)
  const inputRef = useRef<HTMLInputElement>(null)
  const committedRef = useRef(false)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  return (
    <input
      ref={inputRef}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          committedRef.current = true
          onCommit(text)
        } else if (e.key === 'Escape') {
          e.preventDefault()
          onCancel()
        }
      }}
      onBlur={() => {
        if (!committedRef.current) onCancel()
      }}
      list="library-authors-datalist"
      autoComplete="off"
      className="w-full rounded-sm border border-primary bg-background px-1.5 py-0.5 text-[12.5px] text-foreground outline-none"
    />
  )
}

// Select generico "valori determinati" per colonne personalizzate di tipo
// enumeration — stesso pattern di RatingCellEditor (opzioni fisse invece di
// libere), valori letti da CustomColumn.display.enum_values.
function EnumCellEditor({
  value,
  options,
  onCommit,
  onCancel,
}: {
  value: string | null
  options: string[]
  onCommit: (v: string | null) => void
  onCancel: () => void
}) {
  return (
    <div onClick={(e) => e.stopPropagation()}>
      <Select
        defaultOpen
        value={value || 'none'}
        onOpenChange={(open) => {
          if (!open) onCancel()
        }}
        onValueChange={(v) => onCommit(v === 'none' ? null : v)}
      >
        <SelectTrigger className="h-6 w-full border-none bg-transparent px-0 py-0 shadow-none">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">—</SelectItem>
          {options.map((opt) => (
            <SelectItem key={opt} value={opt}>
              {opt}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

// Tri-stato (—/Sì/No) per colonne personalizzate booleane — un bool Calibre
// è nullable (mai impostato ≠ No), quindi un semplice checkbox a due stati
// perderebbe la distinzione.
function BoolCellEditor({
  value,
  onCommit,
  onCancel,
}: {
  value: boolean | null
  onCommit: (v: boolean | null) => void
  onCancel: () => void
}) {
  const { t } = useLingua()
  return (
    <div onClick={(e) => e.stopPropagation()}>
      <Select
        defaultOpen
        value={value == null ? 'none' : value ? 'true' : 'false'}
        onOpenChange={(open) => {
          if (!open) onCancel()
        }}
        onValueChange={(v) => onCommit(v === 'none' ? null : v === 'true')}
      >
        <SelectTrigger className="h-6 w-full border-none bg-transparent px-0 py-0 shadow-none">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">—</SelectItem>
          <SelectItem value="true">{t('common.yes')}</SelectItem>
          <SelectItem value="false">{t('common.no')}</SelectItem>
        </SelectContent>
      </Select>
    </div>
  )
}

// Input HTML nativo type="date": offre sia il calendario a scelta rapida
// sia la digitazione diretta della data (comportamento nativo del browser),
// stessa interazione Invio/Escape/blur di AuthorCellEditor. Il chiamante
// (LibraryRow) passa già la data odierna come `value` quando la cella è
// vuota (vedi todayIso), così il calendario si apre sul giorno corrente
// invece che su una data arbitraria/1970.
function DateCellEditor({
  value,
  onCommit,
  onCancel,
}: {
  value: string
  onCommit: (v: string | null) => void
  onCancel: () => void
}) {
  const [text, setText] = useState(value)
  const inputRef = useRef<HTMLInputElement>(null)
  const committedRef = useRef(false)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  return (
    <input
      ref={inputRef}
      type="date"
      value={text}
      onChange={(e) => setText(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          committedRef.current = true
          onCommit(text || null)
        } else if (e.key === 'Escape') {
          e.preventDefault()
          onCancel()
        }
      }}
      onBlur={() => {
        if (!committedRef.current) onCancel()
      }}
      className="w-full rounded-sm border border-primary bg-background px-1.5 py-0.5 text-[12.5px] text-foreground outline-none"
    />
  )
}

// Input numerico per colonne personalizzate int/float — step="1" per int
// (niente decimali), "any" per float.
function NumberCellEditor({
  value,
  step,
  onCommit,
  onCancel,
}: {
  value: string
  step: string
  onCommit: (v: number | null) => void
  onCancel: () => void
}) {
  const [text, setText] = useState(value)
  const inputRef = useRef<HTMLInputElement>(null)
  const committedRef = useRef(false)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  function commit() {
    committedRef.current = true
    const trimmed = text.trim()
    onCommit(trimmed === '' ? null : Number(trimmed))
  }

  return (
    <input
      ref={inputRef}
      type="number"
      step={step}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          commit()
        } else if (e.key === 'Escape') {
          e.preventDefault()
          onCancel()
        }
      }}
      onBlur={() => {
        if (!committedRef.current) onCancel()
      }}
      className="w-full rounded-sm border border-primary bg-background px-1.5 py-0.5 text-right text-[12.5px] text-foreground outline-none tabular-nums"
    />
  )
}

// Testo libero per colonne personalizzate di tipo 'text' — stesso pattern
// di AuthorCellEditor ma senza datalist (nessun elenco di suggerimenti ha
// senso per una colonna personalizzata generica).
function TextCellEditor({
  value,
  onCommit,
  onCancel,
}: {
  value: string
  onCommit: (v: string) => void
  onCancel: () => void
}) {
  const [text, setText] = useState(value)
  const inputRef = useRef<HTMLInputElement>(null)
  const committedRef = useRef(false)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  return (
    <input
      ref={inputRef}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          committedRef.current = true
          onCommit(text)
        } else if (e.key === 'Escape') {
          e.preventDefault()
          onCancel()
        }
      }}
      onBlur={() => {
        if (!committedRef.current) onCancel()
      }}
      autoComplete="off"
      className="w-full rounded-sm border border-primary bg-background px-1.5 py-0.5 text-[12.5px] text-foreground outline-none"
    />
  )
}

// Oggi in formato YYYY-MM-DD (stesso formato di <input type="date">) — usato
// come default quando si apre l'editor di una colonna datetime ancora vuota,
// non come valore già salvato.
function todayIso(): string {
  return isoLocale(new Date())
}

// Estrae il prefisso YYYY-MM-DD da un valore datetime Calibre grezzo (che
// può essere un timestamp completo, es. "2024-05-12T00:00:00+00:00") —
// stessa regex già usata da formatDate in lib/format.ts, qui serve però il
// valore ancora in formato ISO (non italiano) perché è quello che
// <input type="date"> si aspetta.
function toDateInputValue(raw: unknown): string {
  if (typeof raw !== 'string' || !raw) return ''
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(raw)
  return match ? match[1] : ''
}

// L'altezza di riga la calcola rowHeight() in lib/libraryColumns.ts: e'
// 36 px finche' la copertina non e' fra le colonne mostrate, e cresce
// quanto basta a mostrarla intera quando lo e'. Resta comunque UGUALE per
// tutte le righe, che e' quello che serve alla virtualizzazione (react-
// virtual deve sapere quanto spazio riservare alle righe non ancora
// disegnate, senza doverle misurare una per una).

// Larghezza della colonnina di numerazione righe a sinistra: sono piccoli
// numeri di conteggio, non una colonna uguale alle altre — costante
// fissa fuori dal sistema colonne (columnWidths/allColumns): non è
// riordinabile, ridimensionabile o nascondibile come le colonne vere.
const ROW_NUMBER_WIDTH = 34

// Una riga isolata in React.memo — senza questo, digitare nella ricerca (che
// crea un nuovo array `books` ad ogni tasto) forzerebbe React a rieseguire
// il render di OGNI riga della libreria, incluso l'intero albero del menu
// contestuale (submenu "Copia nella biblioteca"/"Libri simili", elenco
// formati…) anche per righe il cui contenuto non è affatto cambiato. Con
// una libreria di centinaia/migliaia di libri questo era il vero motivo
// della lentezza segnalata, non la quantità di dati in sé.
const LibraryRow = memo(function LibraryRow({
  book,
  rowNumber,
  columns,
  columnWidths,
  customColumns,
  isSelected,
  isFocused,
  selectionSize,
  selectedBooksForMenu,
  totalWidth,
  rowH,
  interactive,
  progressPercent,
  deviceStatus,
  onSelectBook,
  editingField,
  onStartEdit,
  onCommitRating,
  onCommitAuthor,
  onCommitCustom,
  onCancelEdit,
}: {
  book: Book
  rowNumber: number
  columns: ColumnDef[]
  /** Uguale per tutte le righe, calcolata dalla tabella: vedi rowHeight. */
  rowH: number
  columnWidths: Record<string, number>
  customColumns: CustomColumn[]
  // Fa parte della selezione corrente (singola o multipla) — pilota
  // l'evidenziazione della riga. Distinto da isFocused: con una
  // multiselezione attiva TUTTE le righe selezionate sono isSelected, ma
  // solo l'ultima toccata è isFocused (editing inline, navigazione a
  // frecce, scroll-to-index).
  isSelected: boolean
  isFocused: boolean
  selectionSize: number
  // Elenco dei libri attualmente selezionati, da passare a
  // BulkBookContextMenu quando questa riga fa parte di una multiselezione —
  // calcolato una volta sola in LibraryTable (non per riga).
  selectedBooksForMenu: Book[]
  totalWidth: number
  interactive: boolean
  progressPercent: number | undefined
  deviceStatus: Record<number, DeviceBookColumnState> | undefined
  onSelectBook: (book: Book, modifiers?: SelectModifiers) => void
  // null per ogni riga tranne quella selezionata durante un editing attivo
  // — resta un riferimento primitivo stabile per le altre righe, così il
  // memo qui sotto non le rimonta ad ogni tasto/click sull'editor.
  editingField: EditableField | null
  onStartEdit: (book: Book, field: EditableField) => void
  onCommitRating: (book: Book, rating: number | null) => void
  onCommitAuthor: (book: Book, author: string) => void
  onCommitCustom: (book: Book, colId: string, value: string | number | boolean | null) => void
  onCancelEdit: () => void
}) {
  const { t } = useLingua()
  const isMultiSelected = isSelected && selectionSize > 1
  const row = (
    <div
      role="row"
      aria-selected={isSelected}
      onClick={(e) => onSelectBook(book, e)}
      // Click destro su una riga NON selezionata: la selezione collassa su
      // questa sola riga prima di aprire il menu (stesso comportamento di
      // Explorer/Finder) — senza, tasto destro su un libro fuori da una
      // multiselezione attiva mostrerebbe il menu bulk sui libri sbagliati.
      // Righe già selezionate (singole o multiple) restano invariate.
      onContextMenu={() => {
        if (!isSelected) onSelectBook(book)
      }}
      style={{ width: totalWidth, height: rowH }}
      className={cn(
        'flex cursor-pointer border-b border-border/60 transition-colors hover:bg-accent/60',
        // Righe a colori alternati: su una tabella lunga sono l'unica cosa
        // che permette di seguire una riga fino in fondo senza perderla.
        // Sfumatissime di proposito (2,5%) — devono aiutare l'occhio, non
        // disegnare una scacchiera; e restano sotto sia alla selezione sia
        // al passaggio del mouse, che devono continuare a vincere.
        rowNumber % 2 === 0 && 'bg-muted/25',
        isSelected && 'bg-primary/10 hover:bg-primary/10'
      )}
    >
      <div
        onClick={(e) => {
          e.stopPropagation()
          onSelectBook(book, e)
        }}
        style={{ width: ROW_NUMBER_WIDTH, minWidth: ROW_NUMBER_WIDTH }}
        className="flex shrink-0 items-center justify-start pl-2 text-[10px] tabular-nums text-muted-foreground/60 select-none"
      >
        {rowNumber}
      </div>
      {columns.map((col) => {
        const customCol = col.id.startsWith('#') ? customColumns.find((c) => c.label === col.id.slice(1)) : undefined
        const editable = isFocused && selectionSize <= 1 && interactive && (col.id === 'rating' || col.id === 'author' || !!customCol)
        const content = specialCell(book, col.id, progressPercent, deviceStatus, customColumns, t) ?? renderCellValue(book, col.id, customColumns)

        let cellBody = content
        if (editable && editingField === col.id) {
          if (col.id === 'rating') {
            cellBody = <RatingCellEditor value={book.rating} onCommit={(rating) => onCommitRating(book, rating)} onCancel={onCancelEdit} />
          } else if (col.id === 'author') {
            cellBody = <AuthorCellEditor value={book.author} onCommit={(author) => onCommitAuthor(book, author)} onCancel={onCancelEdit} />
          } else if (customCol) {
            // Colonna personalizzata: l'editor dipende dal suo datatype
            // (una modalità di editing diversa per ogni tipo di colonna) —
            // valori determinati → select, date → calendario con default
            // odierno, int/float → input numerico, bool → tri-stato, testo
            // libero altrimenti.
            const raw = book[col.id]
            if (customCol.datatype === 'rating') {
              cellBody = (
                <RatingCellEditor
                  value={typeof raw === 'number' ? raw : null}
                  onCommit={(v) => onCommitCustom(book, col.id, v)}
                  onCancel={onCancelEdit}
                />
              )
            } else if (customCol.datatype === 'bool') {
              cellBody = (
                <BoolCellEditor
                  value={raw == null ? null : Boolean(raw)}
                  onCommit={(v) => onCommitCustom(book, col.id, v)}
                  onCancel={onCancelEdit}
                />
              )
            } else if (customCol.datatype === 'enumeration') {
              const enumValues = Array.isArray(customCol.display?.enum_values) ? (customCol.display.enum_values as string[]) : []
              cellBody = (
                <EnumCellEditor
                  value={typeof raw === 'string' ? raw : null}
                  options={enumValues}
                  onCommit={(v) => onCommitCustom(book, col.id, v)}
                  onCancel={onCancelEdit}
                />
              )
            } else if (customCol.datatype === 'datetime') {
              cellBody = (
                <DateCellEditor
                  value={toDateInputValue(raw) || todayIso()}
                  onCommit={(v) => onCommitCustom(book, col.id, v)}
                  onCancel={onCancelEdit}
                />
              )
            } else if (customCol.datatype === 'int' || customCol.datatype === 'float') {
              cellBody = (
                <NumberCellEditor
                  value={raw != null ? String(raw) : ''}
                  step={customCol.datatype === 'int' ? '1' : 'any'}
                  onCommit={(v) => onCommitCustom(book, col.id, v)}
                  onCancel={onCancelEdit}
                />
              )
            } else {
              cellBody = (
                <TextCellEditor
                  value={raw != null ? String(raw) : ''}
                  onCommit={(v) => onCommitCustom(book, col.id, v)}
                  onCancel={onCancelEdit}
                />
              )
            }
          }
        } else if (editable) {
          // Solo la riga selezionata riceve l'affordance clic-per-modificare
          // — le altre righe restano di sola lettura, il click le seleziona
          // e basta (comportamento invariato). stopPropagation evita che il
          // click "riapra" anche onSelectBook/focus dello scroll container.
          cellBody = (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onStartEdit(book, col.id as EditableField)
              }}
              className={cn(
                'w-full truncate bg-transparent p-0 decoration-dotted underline-offset-2 outline-none hover:underline',
                isNumericColumn(col.id, customColumns) ? 'text-right' : 'text-left'
              )}
            >
              {content}
            </button>
          )
        }

        return (
          <div
            key={col.id}
            role="cell"
            data-col-id={col.id}
            style={{ width: columnWidth(col.id, columnWidths), minWidth: columnWidth(col.id, columnWidths) }}
            className={cn(
              'flex items-center truncate px-3',
              col.id === 'cover' && 'justify-center px-1',
              col.id.startsWith('device-') && 'justify-center px-1',
              col.id === 'title' && 'font-serif font-medium',
              col.id === 'author' && 'text-[12.5px] text-muted-foreground',
              isNumericColumn(col.id, customColumns) && 'justify-end text-right tabular-nums'
            )}
          >
            {cellBody}
          </div>
        )
      })}
    </div>
  )
  if (!interactive) return row
  if (isMultiSelected) return <BulkBookContextMenu books={selectedBooksForMenu}>{row}</BulkBookContextMenu>
  return <BookContextMenu book={book}>{row}</BookContextMenu>
})

export function LibraryTable({
  books,
  columns,
  allColumns,
  visibleColumnIds,
  columnWidths,
  sortCriteria,
  onSortClick,
  selectedBookId,
  onSelectBook,
  selectedIds,
  customColumns,
  onReorderColumns,
  onResizeColumn,
  onToggleColumn,
  interactive = true,
  progressByBookId = {},
  deviceStatusByBookId = {},
}: LibraryTableProps) {
  const { t } = useLingua()
  const [draggedColId, setDraggedColId] = useState<string | null>(null)
  const [dragOverColId, setDragOverColId] = useState<string | null>(null)
  const resizeRef = useRef<{ colId: string; startX: number; startWidth: number } | null>(null)
  const justResizedRef = useRef(false)
  const headerRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  // Libreria ha il suo contenitore di scroll, indipendente da quello di
  // Layout: va ricordato a parte, o tornando da un dettaglio libro si
  // ripartirebbe comunque dalla prima riga.
  useScrollMemory(scrollRef, 'libreria-tabella')

  const totalWidth = useMemo(() => columns.reduce((sum, c) => sum + columnWidth(c.id, columnWidths), 0), [columns, columnWidths])
  // Alta quanto serve alla copertina, quando c'e' — vedi rowHeight.
  const rowH = useMemo(() => rowHeight(columns.map((c) => c.id), columnWidths), [columns, columnWidths])

  // Ricade su { selectedBookId } quando il chiamante non passa selectedIds
  // (il picker di accoppiamento dispositivo, interactive=false — vedi
  // BookPickerDialog): lì la multiselezione non ha senso, la riga
  // selezionata resta esattamente quella di prima.
  const effectiveSelectedIds = useMemo(
    () => selectedIds ?? (selectedBookId != null ? new Set([selectedBookId]) : new Set<number>()),
    [selectedIds, selectedBookId]
  )
  // Calcolato una volta per l'intera tabella (non per riga): passato a
  // BulkBookContextMenu solo dalle righe che ne fanno effettivamente parte.
  const selectedBooksForMenu = useMemo(
    () => books.filter((b) => effectiveSelectedIds.has(b.id)),
    [books, effectiveSelectedIds]
  )

  // Chiamato sempre (regole degli hook): usato solo se interactive, il
  // provider è comunque disponibile ovunque (avvolge l'intero <Outlet/> in
  // Layout.tsx), quindi non c'è bisogno di guardia condizionale qui.
  const actions = useBookActions()

  // Elenco cross-libreria per la datalist di autocomplete dell'editor
  // Autore — stessa fonte (e stesso <datalist>-based approach) del campo
  // Autore in MetadataEditorDialog.
  const { data: authors = [] } = useAuthors()

  // Editing inline: al massimo una cella alla volta, sempre sulla riga
  // selezionata (vedi editingField in LibraryRow). Nessuno stato locale del
  // valore in edit qui: vive dentro RatingCellEditor/AuthorCellEditor,
  // altrimenti ogni tasto premuto nell'input Autore rirenderizzerebbe
  // LibraryTable e quindi (props diverse) ogni riga — lo stesso problema di
  // performance che il memo su LibraryRow esiste per evitare.
  const [editingCell, setEditingCell] = useState<{ bookId: number; field: EditableField } | null>(null)

  // Cambiare riga selezionata (freccette, click su un'altra riga, tasto
  // Esc) esce sempre da un editing in corso — un editor aperto non deve
  // "seguire" la selezione su un altro libro.
  useEffect(() => {
    setEditingCell(null)
  }, [selectedBookId])

  const handleStartEdit = useCallback((book: Book, field: EditableField) => {
    setEditingCell({ bookId: book.id, field })
  }, [])

  const handleCancelEdit = useCallback(() => setEditingCell(null), [])

  const handleCommitRating = useCallback(
    (book: Book, rating: number | null) => {
      setEditingCell(null)
      if (rating === book.rating) return
      actions.updateBookField(book, { rating }).catch((e) => toast.error(errorDetail(e, t('library.error.saveRating'))))
    },
    [actions, t]
  )

  const handleCommitAuthor = useCallback(
    (book: Book, author: string) => {
      setEditingCell(null)
      const trimmed = author.trim()
      if (!trimmed || trimmed === book.author) return
      actions.updateBookField(book, { author: trimmed }).catch((e) => toast.error(errorDetail(e, t('library.error.saveAuthor'))))
    },
    [actions, t]
  )

  const handleCommitCustom = useCallback(
    (book: Book, colId: string, value: string | number | boolean | null) => {
      setEditingCell(null)
      if (value === book[colId]) return
      actions
        .updateBookField(book, { [colId]: value })
        .catch((e) => toast.error(errorDetail(e, t('library.error.saveField'))))
    },
    [actions, t]
  )

  const virtualizer = useVirtualizer({
    count: books.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowH,
    overscan: 12,
  })

  // Accendendo o ridimensionando la copertina l'altezza cambia: senza
  // rimisurare, react-virtual continuerebbe a posizionare le righe con
  // quella vecchia e si accavallerebbero.
  useEffect(() => {
    virtualizer.measure()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowH])

  // Scroll iniziale sulla riga già selezionata all'apertura della tabella
  // (es. selezione ripristinata tornando indietro dalla pagina Autore) — solo
  // al mount (deps vuote): la navigazione a freccette/click gestisce già da
  // sola lo scroll per ogni cambio successivo, qui serve solo "riprendere da
  // dove si era rimasti".
  useEffect(() => {
    if (selectedBookId == null) return
    const idx = books.findIndex((b) => b.id === selectedBookId)
    if (idx !== -1) virtualizer.scrollToIndex(idx, { align: 'auto' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Il div che porta il focus da tastiera per la navigazione a freccette —
  // dato al container che scrolla (non alla riga) perché con la
  // virtualizzazione le righe fuori schermo non esistono nel DOM: spostare
  // il focus riga per riga non funzionerebbe appena si esce dal viewport.
  function handleRowSelect(book: Book, modifiers?: SelectModifiers) {
    onSelectBook(book, modifiers)
    scrollRef.current?.focus()
  }

  function handleTableKeyDown(e: React.KeyboardEvent) {
    if (books.length === 0) return
    // Una cella è in editing (input di testo/numero/data, o un Select
    // aperto): le scorciatoie a singola lettera (i/e/v/t) e la navigazione a
    // frecce/Canc non devono intercettare i tasti, altrimenti scrivere una
    // "i"/"e" dentro l'editor apriva un'azione (dettaglio libro/editor
    // metadati) invece di comporre il testo — difetto riscontrato in uso —
    // e le frecce spostavano la riga selezionata via da sotto un editing in
    // corso. editingCell è già lo stato che traccia esattamente questo.
    if (editingCell) return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const currentIndex = books.findIndex((b) => b.id === selectedBookId)
      // Option/Alt+freccia salta direttamente a inizio/fine tabella (come
      // Cmd+Freccia in molte app Mac). Combinabile con
      // Shift per selezionare l'intero intervallo fino a lì, stesso
      // meccanismo di Shift+click/Shift+freccia sotto.
      const nextIndex = e.altKey
        ? e.key === 'ArrowUp'
          ? 0
          : books.length - 1
        : currentIndex === -1
          ? 0
          : Math.min(books.length - 1, Math.max(0, currentIndex + (e.key === 'ArrowDown' ? 1 : -1)))
      // Shift+freccia estende l'intervallo di un passo per volta, stesso
      // meccanismo (e stessa ancora fissa) di shift+click — vedi
      // useRowSelection.toggle. Senza Shift resta selezione singola, come
      // prima.
      onSelectBook(books[nextIndex], e.shiftKey ? { shiftKey: true } : undefined)
      virtualizer.scrollToIndex(nextIndex, { align: 'auto' })
      return
    }
    // Scorciatoie da tastiera sulla riga selezionata — disattive nel picker
    // di accoppiamento dispositivo (interactive=false), stessa ragione del
    // menu contestuale disattivato lì: azioni come "elimina" non hanno
    // senso in quel contesto.
    if (!interactive) return
    const selected = books.find((b) => b.id === selectedBookId)
    if (!selected) return
    if (e.key === 'i' || e.key === 'I') {
      e.preventDefault()
      actions.openBookDetail(selected)
    } else if (e.key === 'v' || e.key === 'V') {
      e.preventDefault()
      actions.readBook(selected)
    } else if (e.key === 'e' || e.key === 'E') {
      e.preventDefault()
      actions.editMetadata(selected)
    } else if (e.key === 't' || e.key === 'T') {
      e.preventDefault()
      actions.editToc(selected)
    } else if ((e.metaKey || e.ctrlKey) && (e.key === 'd' || e.key === 'D')) {
      e.preventDefault()
      actions.downloadMetadataAndCovers(selected)
    } else if (e.altKey && e.code === 'KeyA') {
      // Su Alt, macOS compone e.key nel carattere del layer Option (Alt+A →
      // "å"), quindi non corrisponderebbe mai a 'a': e.code identifica il
      // tasto fisico indipendentemente dai modificatori (stesso escamotage
      // di normalizeKeyCombo in lib/shortcutRegistry.ts).
      e.preventDefault()
      actions.similarByAuthor(selected)
    } else if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault()
      // Canc con una multiselezione attiva elimina tutti i libri
      // selezionati insieme — stesso menu bulk richiamabile da tasto destro,
      // vedi BulkBookContextMenu. Se la riga a fuoco non fa parte della
      // selezione multipla (caso limite: navigazione a frecce dopo un
      // Cmd-click altrove) si eliminia comunque solo quella, coerente col
      // resto delle scorciatoie sopra.
      if (effectiveSelectedIds.size > 1 && effectiveSelectedIds.has(selected.id)) {
        actions.confirmBulkDeleteBooks(books.filter((b) => effectiveSelectedIds.has(b.id)))
      } else {
        actions.confirmDeleteBook(selected)
      }
    }
  }

  function handleResizeStart(colId: string, e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    resizeRef.current = { colId, startX: e.clientX, startWidth: columnWidth(colId, columnWidths) }
    const onMove = (moveEvt: MouseEvent) => {
      if (!resizeRef.current) return
      const delta = moveEvt.clientX - resizeRef.current.startX
      const next = Math.max(MIN_COLUMN_WIDTH, resizeRef.current.startWidth + delta)
      onResizeColumn(resizeRef.current.colId, next)
    }
    const onUp = () => {
      resizeRef.current = null
      justResizedRef.current = true
      window.setTimeout(() => {
        justResizedRef.current = false
      }, 0)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  function handleAutoFit(colId: string) {
    // Con la virtualizzazione solo le righe visibili sono nel DOM in un
    // dato momento — l'auto-fit misura quindi il contenuto attualmente a
    // schermo, non l'intera libreria (limite noto, accettabile: il caso
    // d'uso è "adatta alla larghezza di quello che vedo").
    const cells = document.querySelectorAll<HTMLElement>(`[data-col-id="${colId}"]`)
    let max = 0
    cells.forEach((cell) => {
      max = Math.max(max, cell.scrollWidth)
    })
    if (max > 0) onResizeColumn(colId, Math.max(MIN_COLUMN_WIDTH, max + 8))
  }

  function handleSortClick(colId: string, e: React.MouseEvent) {
    if (justResizedRef.current) return
    onSortClick(colId, e.shiftKey)
  }

  const virtualItems = virtualizer.getVirtualItems()

  return (
    <div role="table" className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-border text-[13px] text-foreground">
      <div ref={headerRef} role="rowgroup" className="overflow-x-hidden">
        <ContextMenu>
          <ContextMenuTrigger asChild>
            <div role="row" className="flex border-b border-border bg-muted/40" style={{ width: totalWidth }}>
              <div
                aria-hidden
                style={{ width: ROW_NUMBER_WIDTH, minWidth: ROW_NUMBER_WIDTH }}
                className="shrink-0 border-r border-border"
              />
              {columns.map((col) => {
                const rank = sortCriteria.findIndex((c) => c.key === col.id)
                const order = rank !== -1 ? sortCriteria[rank].order : null
                return (
                  <div
                    key={col.id}
                    role="columnheader"
                    draggable
                    onDragStart={() => setDraggedColId(col.id)}
                    onDragOver={(e) => {
                      e.preventDefault()
                      setDragOverColId(col.id)
                    }}
                    onDragEnd={() => {
                      setDraggedColId(null)
                      setDragOverColId(null)
                    }}
                    onDrop={(e) => {
                      e.preventDefault()
                      if (draggedColId && draggedColId !== col.id) {
                        const ids = columns.map((c) => c.id)
                        const from = ids.indexOf(draggedColId)
                        const to = ids.indexOf(col.id)
                        const next = [...ids]
                        next.splice(from, 1)
                        next.splice(to, 0, draggedColId)
                        onReorderColumns(next)
                      }
                      setDraggedColId(null)
                      setDragOverColId(null)
                    }}
                    onClick={(e) => handleSortClick(col.id, e)}
                    style={{ width: columnWidth(col.id, columnWidths), minWidth: columnWidth(col.id, columnWidths) }}
                    className={cn(
                      'relative flex cursor-pointer items-center border-r border-border py-2 pl-3 text-left text-[10.5px] font-semibold tracking-wide text-muted-foreground uppercase select-none',
                      dragOverColId === col.id && 'bg-accent',
                      (col.id === 'cover' || col.id.startsWith('device-')) && 'justify-center px-1 text-center',
                      isNumericColumn(col.id, customColumns) && 'justify-end text-right'
                    )}
                  >
                    <span className="inline-flex items-center gap-1">
                      {col.label}
                      {order === 'asc' && <ArrowUp className="size-3" />}
                      {order === 'desc' && <ArrowDown className="size-3" />}
                    </span>
                    <div
                      onMouseDown={(e) => handleResizeStart(col.id, e)}
                      onDoubleClick={(e) => {
                        e.stopPropagation()
                        handleAutoFit(col.id)
                      }}
                      className="absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-primary/40"
                    />
                  </div>
                )
              })}
            </div>
          </ContextMenuTrigger>
          <ContextMenuContent>
            <ContextMenuLabel>{t('library.columns.visible')}</ContextMenuLabel>
            <ContextMenuSeparator />
            {allColumns.map((col) => (
              <ContextMenuCheckboxItem
                key={col.id}
                checked={visibleColumnIds.includes(col.id)}
                disabled={col.id === 'title'}
                onCheckedChange={() => onToggleColumn(col.id)}
                onSelect={(e) => e.preventDefault()}
              >
                {col.label}
              </ContextMenuCheckboxItem>
            ))}
          </ContextMenuContent>
        </ContextMenu>
      </div>

      <div
        ref={scrollRef}
        role="rowgroup"
        tabIndex={0}
        onKeyDown={handleTableKeyDown}
        className="min-h-0 flex-1 overflow-auto focus:outline-none"
        onScroll={(e) => {
          if (headerRef.current) headerRef.current.scrollLeft = e.currentTarget.scrollLeft
        }}
      >
        {books.length === 0 ? (
          <div className="px-3 py-8 text-center text-muted-foreground">{t('library.empty.noMatch')}</div>
        ) : (
          <div style={{ height: virtualizer.getTotalSize(), width: totalWidth, position: 'relative' }}>
            {virtualItems.map((virtualRow) => {
              const book = books[virtualRow.index]
              return (
                <div key={book.id} style={{ position: 'absolute', top: 0, left: 0, transform: `translateY(${virtualRow.start}px)` }}>
                  <LibraryRow
                    book={book}
                    rowNumber={virtualRow.index + 1}
                    columns={columns}
                    columnWidths={columnWidths}
                    customColumns={customColumns}
                    isSelected={effectiveSelectedIds.has(book.id)}
                    isFocused={selectedBookId === book.id}
                    selectionSize={effectiveSelectedIds.size}
                    selectedBooksForMenu={selectedBooksForMenu}
                    totalWidth={totalWidth}
                    rowH={rowH}
                    interactive={interactive}
                    progressPercent={progressByBookId[book.id]}
                    deviceStatus={deviceStatusByBookId[book.id]}
                    onSelectBook={handleRowSelect}
                    editingField={selectedBookId === book.id && editingCell?.bookId === book.id ? editingCell.field : null}
                    onStartEdit={handleStartEdit}
                    onCommitRating={handleCommitRating}
                    onCommitAuthor={handleCommitAuthor}
                    onCommitCustom={handleCommitCustom}
                    onCancelEdit={handleCancelEdit}
                  />
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Datalist condivisa per l'autocomplete dell'editor Autore inline
          (vedi AuthorCellEditor) — un solo elemento per l'intera tabella,
          referenziato per id da qualunque input, non serve per riga. */}
      <datalist id="library-authors-datalist">
        {authors.map((a) => (
          <option key={a.name} value={a.name} />
        ))}
      </datalist>
    </div>
  )
}
