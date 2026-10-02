// Funzioni pure e di scrittura per la pagina Annotazioni — porting 1:1 dei
// payload/endpoint reali usati da frontend/src/App.vue e
// frontend/src/utils/highlightHelpers.js. File separato da bookActions.ts
// per evitare conflitti di merge con altre pagine in lavorazione in
// parallelo.
import JSZip from 'jszip'
import { api } from './api'
import { t, type Valori } from './i18n'
import type { Highlight } from '@/types/annotation'

// Funzione e non una costante, come fixedColumnLabels in lib/libraryColumns.ts:
// le label sono testo visibile e devono ricalcolarsi al cambio lingua.
// "Calibre" è un nome di prodotto, non si traduce.
export function highlightSourceBadges(
  t: (chiave: string, valori?: Valori) => string
): Record<string, { icon: string; label: string }> {
  return {
    web: { icon: '🌐', label: t('annotations.source.web') },
    device: { icon: '📱', label: t('annotations.source.device') },
    calibre: { icon: '📚', label: 'Calibre' },
  }
}

// Un'evidenziazione 'device' porta con sé QUALE dispositivo (device_name,
// serializzato dal backend) — usarlo al posto della label generica
// "Dispositivo" quando c'è, così si vede a colpo d'occhio da quale device
// viene ogni nota invece di doverlo indovinare.
export function highlightSourceBadge(
  hl: Highlight,
  t: (chiave: string, valori?: Valori) => string
): { icon: string; label: string } {
  if (hl.source === 'device' && hl.device_name) {
    return { icon: '📱', label: hl.device_name }
  }
  const badges = highlightSourceBadges(t)
  return badges[hl.source] ?? badges.web
}

// Un highlight 'device' ottiene un cfi_start apribile solo dopo la
// conversione lazy del backend (services/highlight_position.py); quando è
// già stata tentata e fallita (position_status === 'failed') non c'è nessun
// punto a cui saltare. Un'evidenziazione orfana (is_orphan) è un caso
// permanente più forte: non esiste ancora nessun libro, non solo una
// posizione irrisolta — va accoppiata da Dispositivi ▸ Da rivedere.
export function highlightPositionUnavailable(hl: Highlight): boolean {
  return (
    hl.is_orphan ||
    (hl.source === 'device' &&
      !hl.cfi_start &&
      (hl.position_status === 'failed' || hl.position_status === 'libro_assente'))
  )
}

export function highlightUnavailableReason(hl: Highlight, t: (chiave: string, valori?: Valori) => string): string {
  if (hl.is_orphan) {
    return t('annotations.highlight.unassociatedNote')
  }
  // Terzo caso, distinto dagli altri due: il libro c'era e non c'è più. Non
  // è una conversione difettosa e "Ritenta conversioni fallite" non servirebbe
  // a niente — serve ridare un libro alla nota.
  if (hl.position_status === 'libro_assente') {
    return t('annotations.highlight.bookGone')
  }
  return t('annotations.highlight.unresolvedPosition')
}

// I libri reali si raggruppano su library+calibre_book_id (evita collisioni
// di id tra librerie diverse); gli orfani non hanno né l'uno né l'altro,
// quindi usano orphan_key (device+local_path, già calcolato dal backend).
export function highlightGroupKey(hl: Highlight): string {
  return hl.is_orphan ? `orphan:${hl.orphan_key}` : `book:${hl.library}:${hl.calibre_book_id}`
}

function realId(hl: Highlight): number {
  return typeof hl.id === 'number' ? hl.id : Number(hl.id)
}

// Gli orfani arrivano dalla lista come id stringa "orphan-<n>", ma vivono
// nella tabella/route separata /annotations/orphans/{id} con un id numerico.
function orphanId(hl: Highlight): number {
  return Number(String(hl.id).replace(/^orphan-/, ''))
}

export async function updateHighlightColor(hl: Highlight, color: string): Promise<void> {
  const { error } = hl.is_orphan
    ? await api.PUT('/api/kolibre/annotations/orphans/{id}', { params: { path: { id: orphanId(hl) } }, body: { color } })
    : await api.PUT('/api/kolibre/annotations/{id}', { params: { path: { id: realId(hl) } }, body: { color } })
  if (error) throw error
}

export async function updateHighlightNotes(hl: Highlight, notes: string): Promise<void> {
  const { error } = hl.is_orphan
    ? await api.PUT('/api/kolibre/annotations/orphans/{id}', { params: { path: { id: orphanId(hl) } }, body: { notes } })
    : await api.PUT('/api/kolibre/annotations/{id}', { params: { path: { id: realId(hl) } }, body: { notes } })
  if (error) throw error
}

/**
 * Salva l'ancora che il lettore ha ritrovato cercando il testo.
 *
 * Senza, quella ricerca — che percorre tutto il libro — si rifarebbe a OGNI
 * apertura della nota: e' la lentezza che si avvertiva aprendo una nota
 * nel lettore. Il server la scrive solo su una nota che un'ancora non ce
 * l'ha, quindi non puo' mai sovrascrivere una posizione esatta.
 */
export async function salvaAncoraRitrovata(id: number, cfi: string): Promise<void> {
  const { error } = await api.PUT('/api/kolibre/annotations/{id}', {
    params: { path: { id } },
    body: { cfi_start: cfi } as unknown as Record<string, unknown>,
  })
  if (error) throw error
}

/**
 * Chiede conferma prima di mandare un'evidenziazione nel Cestino.
 *
 * Il bottone diceva "Elimina" e partiva al primo clic. Che l'azione sia
 * reversibile — va nel Cestino, da dove si ripristina — non basta: su una
 * pagina che mostra centinaia di righe un clic sbagliato si deve prima
 * NOTARE, e poi si deve sapere dove andare a cercare. Chiesto il 01/10/2026,
 * in maiuscolo.
 *
 * Vive qui e non nelle due pagine che la chiamano perché due conferme scritte
 * separatamente diventano due conferme che dicono cose diverse.
 *
 * Il messaggio dice la verità, cioè che si recupera: una conferma che minaccia
 * l'irreparabile dove non c'è insegna a cliccare "ok" senza leggere, e il
 * giorno che la minaccia è vera non la si legge comunque. Riporta anche
 * l'inizio del testo, che è la cosa che fa accorgere di aver preso la riga
 * sbagliata.
 */
export function confermaCestino(hl: Highlight): boolean {
  const testo = (hl.text || '').replace(/\s+/g, ' ').trim()
  const anteprima = testo.length > 120 ? `${testo.slice(0, 120)}…` : testo
  return window.confirm(
    t('annotations.highlight.confirmTrash.question') +
      (anteprima ? `\n\n«${anteprima}»` : '') +
      '\n\n' +
      t('annotations.highlight.confirmTrash.hint')
  )
}

export async function trashHighlight(hl: Highlight): Promise<void> {
  const { error } = hl.is_orphan
    ? await api.DELETE('/api/kolibre/annotations/orphans/{id}', { params: { path: { id: orphanId(hl) } } })
    : await api.DELETE('/api/kolibre/annotations/{id}', { params: { path: { id: realId(hl) } } })
  if (error) throw error
}

export async function restoreHighlight(hl: Highlight): Promise<void> {
  const { error } = hl.is_orphan
    ? await api.POST('/api/kolibre/annotations/orphans/{id}/restore', { params: { path: { id: orphanId(hl) } } })
    : await api.POST('/api/kolibre/annotations/{id}/restore', { params: { path: { id: realId(hl) } } })
  if (error) throw error
}

export async function purgeHighlight(hl: Highlight): Promise<void> {
  const { error } = hl.is_orphan
    ? await api.DELETE('/api/kolibre/annotations/orphans/{id}', {
        params: { path: { id: orphanId(hl) }, query: { permanent: true } },
      })
    : await api.DELETE('/api/kolibre/annotations/{id}', {
        params: { path: { id: realId(hl) }, query: { permanent: true } },
      })
  if (error) throw error
}

export interface NewAnnotationPayload {
  calibre_book_id: number
  library: string
  text: string
  comment?: string | null
  color: string | null
}

export async function createAnnotation(payload: NewAnnotationPayload): Promise<Highlight> {
  const { data, error } = await api.POST('/api/kolibre/annotations', { body: payload })
  if (error) throw error
  return data as unknown as Highlight
}

// "Ritenta conversioni CFI fallite" — position_status='failed' non è mai
// ritentato automaticamente (vedi il docstring del backend), quindi questo
// è l'unico modo per rimettere in coda quelle righe dopo aver corretto
// l'EPUB sottostante. Ritorna il conteggio di righe rimesse in coda.
export async function retryFailedPositions(): Promise<number> {
  const { data, error } = await api.POST('/api/kolibre/annotations/retry-failed-positions', {})
  if (error) throw error
  return (data as unknown as { status: string; reset: number }).reset
}

// ── Export client-side (Markdown/HTML) ──
// GET /api/kolibre/annotations/export esiste lato backend ma serve solo al
// plugin Obsidian (raggruppa diversamente, sempre e comunque per libro); la
// pagina Annotazioni del Vue ha sempre generato il file lato browser dagli
// stessi highlight già filtrati/mostrati a schermo — portato 1:1 qui.
function escapeHtml(s: string | null | undefined): string {
  const map: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }
  return String(s ?? '').replace(/[&<>"]/g, (c) => map[c])
}

function slugFilename(s: string | null | undefined): string {
  return String(s || 'annotazioni').replace(/[^a-z0-9\- _]/gi, '').trim().replace(/\s+/g, '_').slice(0, 80) || 'annotazioni'
}

function triggerBrowserDownload(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

interface ExportGroup {
  title: string
  author: string
  items: Highlight[]
}

// Raggruppa sempre per libro (stessa chiave usata a schermo), indipendente
// dalla modalità di raggruppamento attualmente selezionata sulla pagina —
// l'export organizza sempre per libro, solo la vista in pagina varia.
function groupHighlightsForExport(list: Highlight[]): ExportGroup[] {
  const map = new Map<string, ExportGroup>()
  for (const h of list) {
    const key = highlightGroupKey(h)
    if (!map.has(key)) {
      map.set(key, {
        title: h.is_orphan
          ? t('annotations.highlight.unpairedTitle', { title: h.book_title || '' })
          : h.book_title || t('annotations.highlight.unknownTitle'),
        author: h.is_orphan
          ? h.device_name || t('annotations.highlight.unknownDevice')
          : h.book_author || t('annotations.highlight.unknownAuthor'),
        items: [],
      })
    }
    map.get(key)!.items.push(h)
  }
  return Array.from(map.values())
}

function exportGroupToMarkdown(g: ExportGroup): string {
  let out = `# ${g.title}\n\n*${g.author}*\n\n`
  for (const h of g.items) {
    out += `> ${h.text}\n\n`
    if (h.notes) out += `**${t('annotations.export.noteLabel')}:** ${h.notes}\n\n`
    const meta = [highlightSourceBadge(h, t).label, h.chapter, h.created_at].filter(Boolean).join(' · ')
    out += `_${meta}_\n\n---\n\n`
  }
  return out
}

function exportGroupToHtml(g: ExportGroup): string {
  let out = `<h1>${escapeHtml(g.title)}</h1><p><em>${escapeHtml(g.author)}</em></p>`
  for (const h of g.items) {
    out += `<blockquote>${escapeHtml(h.text)}</blockquote>`
    if (h.notes) out += `<p><strong>${escapeHtml(t('annotations.export.noteLabel'))}:</strong> ${escapeHtml(h.notes)}</p>`
    const meta = [highlightSourceBadge(h, t).label, h.chapter, h.created_at].filter(Boolean).join(' · ')
    out += `<p><small>${escapeHtml(meta)}</small></p><hr/>`
  }
  return out
}

// "multi" produceva un download browser per libro (a.click() in loop): Chrome
// e Firefox permettono solo il primo download automatico di una sequenza e
// bloccano silenziosamente gli altri finché l'utente non concede un permesso
// esplicito — da qui il bug "scarica un solo file invece di tutti". Un unico
// file .zip aggira il limite: resta un solo download reale, un file per
// libro al suo interno.
export async function exportAnnotations(
  list: Highlight[],
  format: 'md' | 'html',
  scope: 'single' | 'multi'
): Promise<{ groupCount: number }> {
  const groups = groupHighlightsForExport(list)
  const isHtml = format === 'html'
  const ext = isHtml ? 'html' : 'md'
  const mime = isHtml ? 'text/html' : 'text/markdown'
  const render = isHtml ? exportGroupToHtml : exportGroupToMarkdown

  if (scope === 'multi') {
    const zip = new JSZip()
    const usedNames = new Set<string>()
    for (const g of groups) {
      const base = slugFilename(g.title)
      let name = `${base}.${ext}`
      let n = 2
      while (usedNames.has(name)) name = `${base}_${n++}.${ext}`
      usedNames.add(name)
      zip.file(name, render(g))
    }
    const blob = await zip.generateAsync({ type: 'blob' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'annotazioni_kolibre.zip'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } else {
    const combined = groups.map(render).join(isHtml ? '<hr/>' : '\n\n')
    triggerBrowserDownload('annotazioni_kolibre.' + ext, combined, mime)
  }
  return { groupCount: groups.length }
}

// ── Note vedove ──
//
// Una nota "vedova" è accoppiata a un libro che nella libreria non c'è più:
// né accoppiata né orfana, il terzo stato (vedi il backend,
// services/widowed_highlights.py). Succede cancellando un libro — Kolibre
// lascia le note di proposito, perché sono roba scritta da te — e capita
// spesso quando il libro viene cancellato per essere corretto e reimportato,
// nel qual caso lo stesso testo è ancora lì sotto un altro id. Il server lo
// ritrova cercando il testo delle note nell'indice full-text.

export interface WidowedGroup {
  library: string
  calibre_book_id: number
  count: number
  chapters: string[]
  samples: string[]
}

export interface WidowedCandidate {
  library: string
  calibre_book_id: number
  title: string | null
  authors: string | null
  matches: number
}

export async function fetchWidowedGroups(): Promise<WidowedGroup[]> {
  const { data, error } = await api.GET('/api/kolibre/annotations/widowed', {})
  if (error) throw error
  return (data as unknown as { groups: WidowedGroup[] }).groups
}

export async function fetchWidowedSuggestions(
  library: string,
  calibreBookId: number
): Promise<{ searched: number; candidates: WidowedCandidate[] }> {
  const { data, error } = await api.GET('/api/kolibre/annotations/widowed/suggestions', {
    params: { query: { library, calibre_book_id: calibreBookId } },
  })
  if (error) throw error
  return data as unknown as { searched: number; candidates: WidowedCandidate[] }
}

export async function repairWidowedGroup(
  group: WidowedGroup,
  target: WidowedCandidate
): Promise<number> {
  const { data, error } = await api.POST('/api/kolibre/annotations/widowed/repair', {
    body: {
      library: group.library,
      calibre_book_id: group.calibre_book_id,
      target_library: target.library,
      target_book_id: target.calibre_book_id,
    },
  })
  if (error) throw error
  return (data as unknown as { moved: number }).moved
}
