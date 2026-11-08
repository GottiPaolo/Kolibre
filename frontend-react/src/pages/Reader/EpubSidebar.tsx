// Pannello laterale del reader EPUB — 3 schede (Sommario / Cerca / Note),
// porting 1:1 di frontend/src/ReaderView.vue (.reader-toc). ReaderPage.tsx
// resta proprietario di quale scheda è aperta e di tutta la logica di
// navigazione (goToTocItem/goToSearchResult/goToHighlightAndEdit) — questo
// componente è puramente di presentazione.
import { useState, type RefObject } from 'react'
import type { NavItem } from 'epubjs'
import { Link2, ChevronDown, ChevronRight } from 'lucide-react'
import type { Highlight, RealHighlight } from '@/types/annotation'
import { useLingua } from '@/lib/i18n'
import { colorHex, highlightMatchHtml, truncate } from './EpubHelpers'
import type { EpubSearchMatch, SidebarTab } from './EpubTypes'
import { cn } from '@/lib/utils'

interface EpubSidebarProps {
  tab: SidebarTab
  /** Annotazioni che esistono ma non si riescono a mostrare sulla pagina. */
  nonPosizionate?: number
  inAttesa?: number
  tocItems: NavItem[]
  /** href della voce in cui ci si trova: viene messa in evidenza. */
  currentTocHref?: string | null
  onGoToToc: (item: NavItem) => void
  searchQuery: string
  /** Il campo di ricerca, per portarci il fuoco da fuori (Cmd/Ctrl+F). */
  searchInputRef?: RefObject<HTMLInputElement | null>
  onSearchQueryChange: (value: string) => void
  onSubmitSearch: () => void
  searching: boolean
  searchResults: EpubSearchMatch[]
  onGoToSearchResult: (cfi: string) => void
  // Solo le evidenziazioni vere: il lettore disegna e apre quelle, e
  // un'annotazione orfana non ha un CFI da raggiungere.
  highlights: RealHighlight[]
  /** Copia l'indirizzo che riapre il libro su quella nota. */
  onCopyHighlightLink?: (h: Highlight) => void
  onGoToHighlight: (highlight: RealHighlight) => void
}

export function EpubSidebar({
  tab,
  tocItems,
  currentTocHref,
  onGoToToc,
  searchQuery,
  searchInputRef,
  onSearchQueryChange,
  onSubmitSearch,
  searching,
  searchResults,
  onGoToSearchResult,
  highlights,
  onCopyHighlightLink,
  nonPosizionate,
  inAttesa,
  onGoToHighlight,
}: EpubSidebarProps) {
  const { t } = useLingua()
  // href dei nodi con sottolivelli attualmente espansi — vuoto di default:
  // il primo livello (sempre visibile) resta comunque navigabile, mentre un
  // sommario molto annidato (Parte > Capitolo > Sezione) non si apre tutto
  // insieme come un muro di testo.
  const [expandedToc, setExpandedToc] = useState<Set<string>>(() => new Set())

  function toggleTocExpanded(href: string) {
    setExpandedToc((prev) => {
      const next = new Set(prev)
      if (next.has(href)) next.delete(href)
      else next.add(href)
      return next
    })
  }

  function renderTocItems(items: NavItem[], depth: number) {
    return items.map((item) => {
      const hasChildren = !!item.subitems && item.subitems.length > 0
      const isExpanded = expandedToc.has(item.href)
      // Il confronto e' sul file, non sull'href completo: il sommario porta
      // spesso un'ancora ("parte3.xhtml#cap7") mentre la posizione corrente
      // conosce solo il documento. Vedi tocEntryForHref in EpubHelpers.
      const isCurrent = !!currentTocHref && currentTocHref.split('#')[0] === item.href.split('#')[0]
      return (
        <div key={item.href}>
          <div
            onClick={() => onGoToToc(item)}
            style={{ paddingLeft: 6 + depth * 14 }}
            className={cn(
              'flex cursor-pointer items-center gap-1 rounded-md py-2 pr-1.5 text-[13px] hover:bg-muted',
              isCurrent && 'font-semibold text-primary'
            )}
          >
            {hasChildren ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  toggleTocExpanded(item.href)
                }}
                aria-label={isExpanded ? t('reader.sidebar.toc.collapse') : t('reader.sidebar.toc.expand')}
                className="flex size-4 shrink-0 items-center justify-center text-muted-foreground hover:text-foreground"
              >
                {isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
              </button>
            ) : (
              <span className="size-4 shrink-0" />
            )}
            <span className="truncate">{item.label.trim()}</span>
          </div>
          {hasChildren && isExpanded && renderTocItems(item.subitems!, depth + 1)}
        </div>
      )
    })
  }

  if (!tab) return null

  return (
    <div className="w-[260px] shrink-0 overflow-y-auto border-r border-border bg-card p-3">
      {tab === 'toc' && (
        <>
          <div className="mb-2 text-xs font-bold tracking-wide text-muted-foreground uppercase">{t('reader.toc.title')}</div>
          {renderTocItems(tocItems, 0)}
          {tocItems.length === 0 && <div className="px-1.5 py-2 text-xs text-muted-foreground">{t('reader.sidebar.toc.empty')}</div>}
        </>
      )}

      {tab === 'search' && (
        <>
          <div className="mb-2 text-xs font-bold tracking-wide text-muted-foreground uppercase">{t('reader.search.title')}</div>
          <form
            className="mb-2"
            onSubmit={(e) => {
              e.preventDefault()
              onSubmitSearch()
            }}
          >
            <input
              ref={searchInputRef}
              value={searchQuery}
              onChange={(e) => onSearchQueryChange(e.target.value)}
              type="text"
              placeholder={t('common.search.placeholder')}
              autoFocus
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[13px] outline-none focus:border-primary"
            />
          </form>
          {searching && <div className="px-1.5 py-2 text-xs text-muted-foreground">{t('reader.sidebar.search.searching')}</div>}
          {!searching && searchQuery && searchResults.length === 0 && (
            <div className="px-1.5 py-2 text-xs text-muted-foreground">{t('reader.sidebar.search.noResults')}</div>
          )}
          {searchResults.map((r, idx) => (
            <div
              key={idx}
              onClick={() => onGoToSearchResult(r.cfi)}
              className="cursor-pointer rounded-md px-1.5 py-2 text-[12px] leading-tight hover:bg-muted"
              // eslint-disable-next-line react/no-danger -- estratto già escapato in highlightMatchHtml, solo <strong> iniettato
              dangerouslySetInnerHTML={{ __html: highlightMatchHtml(r.excerpt, searchQuery) }}
            />
          ))}
        </>
      )}

      {tab === 'notes' && (
        <>
          <div className="mb-2 text-xs font-bold tracking-wide text-muted-foreground uppercase">
            {t('reader.sidebar.notes.heading', { count: highlights.length })}
          </div>
          {/* Una nota appena arrivata da un dispositivo non ha ancora il suo
              punto: il server lo calcola in sottofondo. E' un'attesa, non un
              guasto, e si dice in tono diverso — neutro, non d'allarme. */}
          {!!inAttesa && inAttesa > 0 && (
            <div className="mb-2 rounded-md border border-border px-2 py-1.5 text-[11.5px] leading-snug text-muted-foreground">
              {t('reader.sidebar.notes.pending', { count: inAttesa, n: inAttesa })}
            </div>
          )}
          {/* Un'annotazione che non si riesce a posizionare c'e' lo stesso:
              prima non compariva da nessuna parte e sembrava persa. */}
          {!!nonPosizionate && nonPosizionate > 0 && (
            <div className="mb-2 rounded-md border border-[var(--warning)]/40 px-2 py-1.5 text-[11.5px] leading-snug text-[var(--warning)]">
              {t('reader.sidebar.notes.unplaced', { count: nonPosizionate, n: nonPosizionate })}
            </div>
          )}
          {highlights.map((h) => {
            // "Posizionabile" dice se la nota ha un'ancora, e serve ancora a
            // mostrarla diversa (pallino vuoto, testo sbiadito). Ma NON decide
            // piu' se e' cliccabile: senza ancora resta il ripiego che cerca il
            // testo della nota nel libro, e proprio le note che ne hanno piu'
            // bisogno erano le sole da cui non lo si poteva chiedere — il ramo
            // esisteva in goToHighlightAndEdit ed era irraggiungibile da qui.
            const posizionabile = !!h.cfi_start
            return (
            <div
              key={h.id}
              onClick={() => onGoToHighlight(h)}
              title={posizionabile ? undefined : t('reader.sidebar.notes.noAnchorTitle')}
              className={`group flex items-start gap-2 rounded-md cursor-pointer hover:bg-muted px-1.5 py-2 text-[12px] leading-tight ${
                posizionabile ? '' : 'opacity-60'
              }`}
            >
              <span
                className={`mt-0.5 size-2.5 shrink-0 rounded-full ${posizionabile ? '' : 'ring-1 ring-current'}`}
                style={{ backgroundColor: posizionabile ? colorHex(h.color) : 'transparent' }}
              />
              <span className="min-w-0 flex-1">
                “{truncate(h.text, 80)}”
                {h.notes && <em className="text-muted-foreground not-italic"> — {h.notes}</em>}
              </span>
              {/* Il link sta sulla riga e non dentro un menu: e' l'azione che
                  porta la nota fuori da Kolibre, ed e' quella per cui si apre
                  questo pannello quando si sta scrivendo altrove.
                  `stopPropagation` perche' la riga intera e' cliccabile e
                  porterebbe al passaggio invece di copiare. */}
              {onCopyHighlightLink && h.id != null && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onCopyHighlightLink(h) }}
                  title={t('reader.highlight.copyLinkTooltip')}
                  aria-label={t('reader.highlight.copyLink')}
                  className="mt-0.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100 hover:text-foreground"
                >
                  <Link2 className="size-3.5" />
                </button>
              )}
            </div>
            )
          })}
          {highlights.length === 0 && <div className="px-1.5 py-2 text-xs text-muted-foreground">{t('reader.sidebar.notes.empty')}</div>}
        </>
      )}
    </div>
  )
}
