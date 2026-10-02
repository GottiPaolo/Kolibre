'use strict';
// Kolibre — Obsidian plugin.
// Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
// NOTICE files in the Kolibre repository.

var obsidian = require('obsidian');
const { t } = require('./kolibre_lingua.js');

// ── Constants ─────────────────────────────────────────────────────────────

// Joins nested chapter levels into one string — the SAME separator the
// KOReader community patch (github.com/koreader/koreader/issues/12480,
// `table.concat(self.ui.toc:getFullTocTitleByPage(item.page), " ▸ ")`) and
// Kolibre's own web reader (see frontend/src/ReaderView.vue's
// chapterPathForCfi) both already use, so both highlight sources parse
// identically here with a single piece of logic, no per-source branching.
const SEPARATOR = ' ▸ ';

// L'id NON e' sempre un numero: le evidenziazioni dei libri non accoppiati
// arrivano dal server con id "orphan-<n>" (vedi export_annotations in
// backend/app/api/annotations.py, ramo degli OrphanHighlight). Con \d+ qui
// il plugin SCRIVEVA "<!-- kolibre-hl:orphan-12 -->" e poi non lo
// RILEGGEVA: quegli id non finivano mai fra quelli gia' importati, e ogni
// sincronizzazione riaggiungeva le stesse note in coda, all'infinito. Era
// anche il motivo per cui le note dei libri non accoppiati perdevano
// l'ordinamento per pagina: un blocco non riconosciuto veniva scambiato
// per testo scritto a mano, e mergeSectionBlocks in quel caso ripiega
// sull'accodamento invece di inserire in ordine.
const MARKER_RE = /<!--\s*kolibre-hl:([A-Za-z0-9_-]+)\s*-->/;
const PAGE_IN_BLOCK_RE = /📄\s*p\.(\d+)/;

const DEFAULT_BOOK_HEADER = t('obsidian.template.default_header');

const DEFAULT_SETTINGS = {
    serverUrl: 'http://localhost:8081',
    username: '',
    // Salvata localmente (stesso data.json del plugin, già sede di authToken)
    // così il plugin può rinnovare da solo l'accesso quando authToken scade
    // (7 giorni, vedi backend/app/auth.py::ACCESS_TOKEN_EXPIRE_MINUTES)
    // invece di richiedere un login manuale ogni volta — difetto riscontrato
    // in uso: ogni tanto la connessione salta e tocca riaccedere a mano.
    password: '',
    authToken: '',
    outputFolder: 'Libri',
    filenameTemplate: '{{title}}',
    bookHeaderTemplate: DEFAULT_BOOK_HEADER,
};

// ── Utility ───────────────────────────────────────────────────────────────

function sanitizeFilename(name) {
    return name.replace(/[/\\:*?"<>|#[\]^]/g, '_').trim().slice(0, 200);
}

function applyFilenameTemplate(template, book) {
    return sanitizeFilename(
        template
            .replace(/\{\{\s*title\s*\}\}/gi, book.title || 'Senza titolo')
            .replace(/\{\{\s*authors?\s*\}\}/gi, book.author || 'Sconosciuto')
            .trim()
    );
}

/**
 * Apply the book header template, replacing all supported variables.
 * Supported: {{title}}, {{author}}, {{date}}, {{year}}, {{filename}}.
 */
function applyHeaderTemplate(template, bookData, filenameBase) {
    const today = new Date().toLocaleDateString('it-IT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
    });
    const year = String(new Date().getFullYear());
    return template
        .replace(/\{\{\s*title\s*\}\}/gi, bookData.title || 'Senza titolo')
        .replace(/\{\{\s*authors?\s*\}\}/gi, bookData.author || 'Sconosciuto')
        .replace(/\{\{\s*date\s*\}\}/gi, today)
        .replace(/\{\{\s*year\s*\}\}/gi, year)
        .replace(/\{\{\s*filename\s*\}\}/gi, filenameBase || sanitizeFilename(bookData.title || 'nota'));
}

/**
 * Parse a chapter string into a heading path array.
 * "Parte 1 ▸ Capitolo 2 ▸ Sezione" → ["Parte 1", "Capitolo 2", "Sezione"]
 * "Capitolo semplice"               → ["Capitolo semplice"]
 * null / ""                         → []
 *
 * If the first element fuzzy-matches the book title, it's dropped (some
 * TOCs include the book title itself as the root node).
 */
function parseChapterPath(chapter, bookTitle) {
    if (!chapter) return [];
    const parts = chapter.split(SEPARATOR).map(s => s.trim()).filter(Boolean);
    if (parts.length > 1 && bookTitle) {
        const norm = s => s.toLowerCase().replace(/[^a-z0-9]/g, '');
        const first = norm(parts[0]);
        const title = norm(bookTitle);
        if (first === title || title.startsWith(first) || first.startsWith(title)) {
            parts.shift();
        }
    }
    return parts;
}

/**
 * Where a highlight came from, for the metadata line below — 'device' with
 * a still-registered device gets its real name; 'device' with no name
 * (device deleted since) and 'calibre'/'web' get a fixed generic label.
 * Matches backend/app/api/annotations.py::export_annotations's own
 * source/device_name fields.
 */
function formatHighlightSource(hl) {
    if (hl.source === 'device') return `📱 ${hl.device_name || t('obsidian.source.device')}`;
    if (hl.source === 'calibre') return `📚 ${t('obsidian.source.calibre')}`;
    return `🌐 ${t('obsidian.source.web')}`;
}

/**
 * One highlight block, WITHOUT the trailing "***" separator (callers join
 * blocks with that explicitly — keeps this function a pure formatter, and
 * keeps the separator convention in exactly one place: joinBlocks below).
 *
 * If there's no note, the whole "*✍🏻 Nota:*" line (label included) is
 * omitted — never an empty note label.
 */
function formatHighlightBlock(hl) {
    const dt = new Date(hl.created_at);
    const dateStr = isNaN(dt.getTime()) ? '' : dt.toLocaleString('it-IT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
    const pageSegment = hl.page ? `📄 p.${hl.page} · ` : '';
    const sourceSegment = ` · ${formatHighlightSource(hl)}`;
    const text = (hl.text || '').replace(/\r\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();

    let block = `*${t('obsidian.block.highlight_label')} ${pageSegment}🗓 ${dateStr}${sourceSegment}*\n\n"${text}"\n`;
    if (hl.note && hl.note.trim()) {
        block += `\n*✍🏻 ${t('obsidian.block.note_label')}*\n${hl.note.trim()}\n`;
    }
    block += `\n<!-- kolibre-hl:${hl.id} -->`;
    return block;
}

// Every block gets its OWN trailing separator — including the last one in a
// section (right before the next heading) and the very last one in the
// whole file. An earlier version only put "***" BETWEEN blocks, which
// silently dropped the separator exactly where a section had just one
// highlight, or at the end of the file — reported after real use.
function joinBlocks(blocks) {
    return blocks.map(b => `${b}\n\n***`).join('\n\n');
}

/**
 * Normalizes each highlight's chapter path, inheriting missing ancestor
 * levels for "bare" (single-level) paths from whatever full path came
 * before it in page order. Needed because the web reader's own
 * chapter-path resolver (ReaderView.vue::chapterPathForCfi) faithfully
 * reports the EPUB's real table of contents — and real EPUBs aren't
 * always consistently nested. Confirmed on a real book ("La Rivoluzione
 * russa" di Victor Serge): roman-numeral sub-chapters "I.", "IV." etc. are
 * nested under their part heading in the TOC for SOME entries but not
 * others, so the very same highlight source can report
 * "1. La Rivoluzione russa ▸ VIII." for one highlight and a bare "VIII."
 * for another right next to it in the book. Without this, a bare path
 * would render as its OWN unrelated top-level heading instead of nesting
 * under the part it actually belongs to.
 *
 * A bare path is NOT always a stray leaf, though — on the same real book,
 * "2. Trent'anni dopo la Rivoluzione russa" shows up bare once (it's the
 * FIRST highlight of that new part, before any of ITS OWN sub-chapters
 * have produced a full path yet) and would otherwise get wrongly nested
 * as a child of part 1. First pass over the whole book collects every
 * label ever seen as the FIRST element of a longer path elsewhere — that
 * set is data-driven proof a label is a genuine top-level heading, not a
 * text-shape guess — and a bare path matching one of those always starts
 * a fresh top-level context instead of inheriting.
 *
 * `sortedHighlights` MUST already be in page order — the second pass is a
 * sequential scan, not a lookup. Returns a parallel array of resolved path
 * arrays (same length/order as the input), never mutates the highlights.
 */
function resolveChapterHeadings(sortedHighlights, bookTitle) {
    const rawPaths = sortedHighlights.map(hl => parseChapterPath(hl.chapter, bookTitle));

    const knownTopLevels = new Set();
    for (const path of rawPaths) {
        if (path.length > 1) knownTopLevels.add(path[0]);
    }

    let currentPath = [];
    const resolved = [];
    for (const path of rawPaths) {
        if (path.length > 1) {
            currentPath = path;
        } else if (path.length === 1) {
            if (currentPath.length === 0 || knownTopLevels.has(path[0])) {
                // Nothing to inherit from yet, or this exact label is
                // independently confirmed elsewhere to be a real top-level
                // heading — never force it under whatever chapter happened
                // to be open.
                currentPath = path;
            } else {
                // Bare leaf while we already have ancestry open — inherit
                // every level above the leaf from the current context,
                // replacing only the deepest one.
                currentPath = currentPath.slice(0, -1).concat(path);
            }
        }
        // path.length === 0 (no chapter at all) intentionally leaves
        // currentPath untouched rather than resetting it — an untagged
        // highlight in the middle of a chapter shouldn't evict the chapter
        // context for the next real one.
        resolved.push(path.length === 0 ? [] : currentPath);
    }
    return resolved;
}

// ── Grouping ──────────────────────────────────────────────────────────────

/** Groups raw exported highlights by book (library + title), shared by both the incremental and the full-reimport flow. */
function groupHighlightsByBook(highlights) {
    const books = {};
    for (const hl of highlights) {
        const key = `${hl.library}::${hl.book_title}`;
        if (!books[key]) {
            books[key] = { title: hl.book_title, author: hl.book_author, highlights: [] };
        }
        books[key].highlights.push(hl);
    }
    return books;
}

/**
 * Groups sorted highlights into sections by (already resolved, see
 * resolveChapterHeadings) chapter path — `resolvedPaths` must be a
 * parallel array, same length/order as `highlights`. Global grouping by
 * exact path, not just adjacency: a chapter revisited later in page order
 * still folds into its original section instead of creating a duplicate.
 */
function groupByChapterPath(highlights, resolvedPaths) {
    const sections = [];
    const keyToIndex = new Map();
    for (let i = 0; i < highlights.length; i++) {
        const path = resolvedPaths[i];
        const key = path.length ? path.join(SEPARATOR) : '__none__';
        if (!keyToIndex.has(key)) {
            keyToIndex.set(key, sections.length);
            sections.push({
                key,
                headings: path.length ? path : [t('obsidian.block.no_chapter_heading')],
                highlights: [],
            });
        }
        sections[keyToIndex.get(key)].highlights.push(highlights[i]);
    }
    return sections;
}

// ── New file ──────────────────────────────────────────────────────────────

function buildNewFile(bookData, settings, filenameBase) {
    const { highlights } = bookData;
    const sorted = [...highlights].sort((a, b) => (a.page || Infinity) - (b.page || Infinity));
    const resolvedPaths = resolveChapterHeadings(sorted, bookData.title);
    const sections = groupByChapterPath(sorted, resolvedPaths);

    const headerTemplate = (settings && settings.bookHeaderTemplate != null)
        ? settings.bookHeaderTemplate
        : DEFAULT_BOOK_HEADER;

    let md = '';
    if (headerTemplate.trim()) {
        md = applyHeaderTemplate(headerTemplate, bookData, filenameBase);
        if (!md.endsWith('\n\n')) {
            if (!md.endsWith('\n')) md += '\n';
            md += '\n';
        }
    }

    // Prefix-aware: a section whose path shares a leading run with the
    // previously written one only gets the DIVERGING levels re-emitted —
    // the alternative (re-emitting every level for every section, as this
    // used to do) is exactly what produced the same top-level heading
    // repeated once per distinct child, confirmed on a real book with
    // several sub-chapters under the same part.
    let openPath = [];
    for (const section of sections) {
        const path = section.headings;
        let commonLen = 0;
        while (commonLen < path.length && commonLen < openPath.length && path[commonLen] === openPath[commonLen]) {
            commonLen++;
        }
        for (let lvl = commonLen; lvl < path.length; lvl++) {
            md += `${'#'.repeat(lvl + 1)} ${path[lvl]}\n\n`;
        }
        openPath = path;
        md += joinBlocks(section.highlights.map(formatHighlightBlock)) + '\n\n';
    }
    return md.trimEnd() + '\n';
}

// ── Incremental update ────────────────────────────────────────────────────

/**
 * Every highlight ID already present anywhere in the file (as a
 * <!-- kolibre-hl:ID --> marker) — the whole "what's new" filter, no
 * separate per-book timestamp tracking needed at all.
 */
function extractImportedIds(fileContent) {
    const ids = new Set();
    const re = new RegExp(MARKER_RE.source, 'g');
    let m;
    while ((m = re.exec(fileContent)) !== null) {
        ids.add(m[1]);
    }
    return ids;
}

/**
 * Merges new highlights into one section's raw text (everything between its
 * heading line and the next heading / EOF), inserting each new block in
 * page order relative to the highlight blocks already there.
 *
 * Blocks are delimited by a "***" line. A block containing a
 * <!-- kolibre-hl:ID --> marker is a real highlight block (page-sortable);
 * any other block is free-form user content. As long as the section is a
 * *pure* sequence of highlight blocks (nothing hand-written mixed in after
 * the first one), new highlights are inserted at their correct page
 * position. If the user has written something of their own in between
 * highlight blocks, that section falls back to appending new highlights at
 * the end instead — reordering around unknown hand-written content risks
 * corrupting it, appending never does. A leading preamble (anything BEFORE
 * the first highlight block) is always left exactly where it is.
 */
function mergeSectionBlocks(existingSectionText, newHighlights) {
    const rawChunks = existingSectionText.split(/\n\*\*\*\n/).map(c => c.trim()).filter(Boolean);
    const parsed = rawChunks.map(raw => {
        const idMatch = raw.match(MARKER_RE);
        if (!idMatch) return { kind: 'other', raw };
        const pageMatch = raw.match(PAGE_IN_BLOCK_RE);
        return { kind: 'highlight', id: idMatch[1], page: pageMatch ? parseInt(pageMatch[1], 10) : Infinity, raw };
    });

    let firstHighlightIdx = parsed.findIndex(p => p.kind === 'highlight');
    if (firstHighlightIdx === -1) firstHighlightIdx = parsed.length;
    const preamble = parsed.slice(0, firstHighlightIdx);
    const rest = parsed.slice(firstHighlightIdx);
    const hasInterleavedOther = rest.some(p => p.kind === 'other');

    const newBlocks = newHighlights.map(hl => ({
        kind: 'highlight',
        id: String(hl.id),
        page: hl.page || Infinity,
        raw: formatHighlightBlock(hl),
    }));

    const merged = hasInterleavedOther
        ? rest.concat(newBlocks) // can't safely reorder around hand-written content — append only
        : rest.concat(newBlocks).sort((a, b) => a.page - b.page); // stable sort (ES2019+): ties keep original relative order

    const allBlocks = preamble.concat(merged);
    return joinBlocks(allBlocks.map(b => b.raw));
}

/** Every markdown heading line in a file, in document order, with its level and line index. */
function parseHeadingLines(fileContent) {
    const lines = fileContent.split('\n');
    const headings = [];
    for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(/^(#+)\s+(.*)$/);
        if (m) headings.push({ level: m[1].length, text: m[2].trimEnd(), lineIndex: i });
    }
    return { lines, headings };
}

/**
 * Finds the line index of the heading matching the FULL ancestor chain in
 * `targetPath` — not just the leaf text. Walks the heading list keeping a
 * stack of open ancestors per level (exactly how buildNewFile itself
 * writes them), so two DIFFERENT chapters that happen to share a leaf
 * label (confirmed on a real book: both "1. La Rivoluzione russa" and
 * "2. Trent'anni dopo" have their own child "I." and "IV.") never get
 * confused with each other. Returns -1 if that exact chain doesn't exist.
 */
function findHeadingByPath(headingList, targetPath) {
    let stack = [];
    for (const h of headingList) {
        stack = stack.slice(0, h.level - 1);
        stack[h.level - 1] = h.text;
        if (h.level === targetPath.length && targetPath.every((t, i) => stack[i] === t)) {
            return h.lineIndex;
        }
    }
    return -1;
}

/** First line index at or after `headingLineIdx + 1` whose heading level is <= `level` (i.e. where that heading's own content ends), or EOF. */
function findSectionEnd(lines, headingLineIdx, level) {
    for (let i = headingLineIdx + 1; i < lines.length; i++) {
        const m = lines[i].match(/^(#+)\s/);
        if (m && m[1].length <= level) return i;
    }
    return lines.length;
}

/**
 * Applies mergeSectionBlocks to the right slice of the WHOLE file for one
 * chapter-path section. Finds the LONGEST already-existing ancestor prefix
 * of `headings` (by full chain, see findHeadingByPath) rather than just
 * looking for the exact leaf: a partial match gets only the missing
 * deeper levels inserted right after that ancestor's own existing content
 * (never blindly appended at EOF when the ancestor already exists — doing
 * that used to recreate the exact "repeated parent heading" bug on every
 * incremental update instead of just on the very first build). No match
 * at all falls back to creating the whole chain fresh at EOF, as before.
 */
function insertSection(fileContent, headings, newHighlights) {
    if (!newHighlights.length) return fileContent;
    const { lines, headings: headingList } = parseHeadingLines(fileContent);

    let matchLevel = 0;
    let matchLineIdx = -1;
    for (let lvl = headings.length; lvl >= 1; lvl--) {
        const idx = findHeadingByPath(headingList, headings.slice(0, lvl));
        if (idx !== -1) {
            matchLevel = lvl;
            matchLineIdx = idx;
            break;
        }
    }

    if (matchLevel === headings.length) {
        const sectionEndIdx = findSectionEnd(lines, matchLineIdx, matchLevel);
        const before = lines.slice(0, matchLineIdx + 1).join('\n');
        const sectionText = lines.slice(matchLineIdx + 1, sectionEndIdx).join('\n');
        const after = lines.slice(sectionEndIdx).join('\n');
        const mergedSection = mergeSectionBlocks(sectionText, newHighlights);
        const content = before + '\n\n' + mergedSection + '\n\n' + (after || '');
        return content.replace(/\n{3,}/g, '\n\n\n').trimEnd() + '\n';
    }

    let addition = '';
    for (let lvl = matchLevel; lvl < headings.length; lvl++) {
        addition += '#'.repeat(lvl + 1) + ' ' + headings[lvl] + '\n\n';
    }
    addition += joinBlocks(newHighlights.map(formatHighlightBlock));

    const insertAt = matchLevel === 0 ? lines.length : findSectionEnd(lines, matchLineIdx, matchLevel);
    const before = lines.slice(0, insertAt).join('\n');
    const after = lines.slice(insertAt).join('\n');
    const content = before.trimEnd() + '\n\n' + addition + '\n\n' + after;
    return content.replace(/\n{3,}/g, '\n\n\n').trimEnd() + '\n';
}


/** Appends only the highlights not already present (by ID marker) into an
 * existing file, section by section. Returns { content, added }. */
function mergeHighlights(existingContent, bookData) {
    // La ripulitura dei duplicati lasciati dal vecchio bug di MARKER_RE e'
    // stata tolta dopo essere girata su tutto il vault: girava a ogni sync
    // di ogni nota per un lavoro da fare una volta sola.

    const alreadyImported = extractImportedIds(existingContent);
    const trulyNew = bookData.highlights.filter(hl => !alreadyImported.has(String(hl.id)));
    if (trulyNew.length === 0) {
        return { content: existingContent, added: 0 };
    }

    // resolveChapterHeadings needs to scan ALL of the book's highlights
    // (old + new) in page order, not just the new ones — a new "bare"
    // chapter path (see resolveChapterHeadings' own docstring) must be
    // able to inherit ancestry from an ALREADY-imported highlight that
    // came before it, not only from other new ones landing in this same
    // batch.
    const allSorted = [...bookData.highlights].sort((a, b) => (a.page || Infinity) - (b.page || Infinity));
    const allResolvedPaths = resolveChapterHeadings(allSorted, bookData.title);
    const newIds = new Set(trulyNew.map(hl => String(hl.id)));
    const sorted = [];
    const resolvedPaths = [];
    for (let i = 0; i < allSorted.length; i++) {
        if (newIds.has(String(allSorted[i].id))) {
            sorted.push(allSorted[i]);
            resolvedPaths.push(allResolvedPaths[i]);
        }
    }
    const sections = groupByChapterPath(sorted, resolvedPaths);

    let content = existingContent;
    for (const section of sections) {
        content = insertSection(content, section.headings, section.highlights);
    }
    return { content, added: trulyNew.length };
}

// ── Folder suggestion ─────────────────────────────────────────────────────

class FolderSuggest extends obsidian.AbstractInputSuggest {
    constructor(app, inputEl, onSelect) {
        super(app, inputEl);
        // Hooking selection via the documented onSelect() registration
        // instead of overriding selectSuggestion() directly: AbstractInputSuggest
        // has its OWN internal selectSuggestion implementation (added in the
        // Obsidian API well after this pattern was common in older plugin
        // examples) that setValue()s the input and closes the popup itself —
        // overriding it here silently shadowed that internal wiring, so a
        // click/Enter on a suggestion never actually landed (reported
        // directly: "mostra i suggerimenti ma non mi fa confermare").
        if (onSelect) {
            this.onSelect((folder) => {
                this.setValue(folder);
                this.inputEl.dispatchEvent(new Event('input', { bubbles: true }));
                onSelect(folder);
                this.close();
            });
        }
    }

    getSuggestions(query) {
        const folders = [];
        const lowerQuery = query.toLowerCase();
        const collect = (folder) => {
            for (const child of (folder.children || [])) {
                if (child instanceof obsidian.TFolder) {
                    if (child.path.toLowerCase().includes(lowerQuery)) {
                        folders.push(child.path);
                    }
                    collect(child);
                }
            }
        };
        collect(this.app.vault.getRoot());
        return folders.slice(0, 20);
    }

    renderSuggestion(folder, el) {
        el.createEl('span', { text: folder });
    }
}

// ── Import summary modal ──────────────────────────────────────────────────

class ImportSummaryModal extends obsidian.Modal {
    constructor(app, results) {
        super(app);
        this.results = results;
    }
    onOpen() {
        const { contentEl } = this;
        const { newFiles, updatedFiles, totalAdded } = this.results;
        contentEl.createEl('h2', { text: t('obsidian.import_summary.title') });
        contentEl.createEl('p', { text: t('obsidian.import_summary.total', { count: totalAdded }) });
        if (newFiles.length > 0) {
            contentEl.createEl('h3', { text: t('obsidian.import_summary.new_files_heading', { count: newFiles.length }) });
            const ul = contentEl.createEl('ul');
            for (const f of newFiles) ul.createEl('li', { text: t('obsidian.import_summary.file_line', { title: f.title, count: f.count }) });
        }
        if (updatedFiles.length > 0) {
            contentEl.createEl('h3', { text: t('obsidian.import_summary.updated_files_heading', { count: updatedFiles.length }) });
            const ul = contentEl.createEl('ul');
            for (const f of updatedFiles) ul.createEl('li', { text: t('obsidian.import_summary.file_line_added', { title: f.title, count: f.count }) });
        }
        if (newFiles.length === 0 && updatedFiles.length === 0) {
            contentEl.createEl('p', { text: t('obsidian.import_summary.no_changes') });
        }
        const closeBtn = contentEl.createEl('button', { text: t('obsidian.common.close'), cls: 'mod-cta' });
        closeBtn.style.marginTop = '16px';
        closeBtn.onclick = () => this.close();
    }
    onClose() {
        this.contentEl.empty();
    }
}

// ── Confirm modal ─────────────────────────────────────────────────────────

/**
 * Generic yes/no confirmation — used before the destructive full-reimport
 * command (see reimportAllHighlights). onConfirm only ever fires from the
 * "confirm" button; closing the modal any other way (Annulla, Esc, click
 * outside) never calls it.
 */
class ConfirmModal extends obsidian.Modal {
    constructor(app, { title, message, confirmText, onConfirm }) {
        super(app);
        this.title = title;
        this.message = message;
        this.confirmText = confirmText;
        this.onConfirm = onConfirm;
    }
    onOpen() {
        const { contentEl } = this;
        contentEl.createEl('h2', { text: this.title });
        contentEl.createEl('p', { text: this.message });
        const row = contentEl.createEl('div');
        row.style.display = 'flex';
        row.style.justifyContent = 'flex-end';
        row.style.gap = '8px';
        row.style.marginTop = '16px';
        const cancelBtn = row.createEl('button', { text: t('obsidian.common.cancel') });
        cancelBtn.onclick = () => this.close();
        const confirmBtn = row.createEl('button', { text: this.confirmText, cls: 'mod-warning' });
        confirmBtn.onclick = () => {
            this.close();
            this.onConfirm();
        };
    }
    onClose() {
        this.contentEl.empty();
    }
}

// ── Settings tab ──────────────────────────────────────────────────────────

class KolibreSettingTab extends obsidian.PluginSettingTab {
    constructor(app, plugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display() {
        const { containerEl } = this;
        containerEl.empty();
        containerEl.createEl('h2', { text: 'Kolibre Highlights' });

        containerEl.createEl('h3', { text: t('obsidian.settings.section_login') });

        new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.server_url_name'))
            .setDesc(t('obsidian.settings.server_url_desc'))
            .addText(text => text
                .setPlaceholder('http://192.168.1.100:8081')
                .setValue(this.plugin.settings.serverUrl)
                .onChange(async v => {
                    this.plugin.settings.serverUrl = v.trim().replace(/\/$/, '');
                    await this.plugin.saveSettings();
                }));

        new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.username_name'))
            .addText(text => text
                .setValue(this.plugin.settings.username)
                .onChange(async v => {
                    this.plugin.settings.username = v.trim();
                    await this.plugin.saveSettings();
                }));

        new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.password_name'))
            .setDesc(t('obsidian.settings.password_desc'))
            .addText(text => {
                text.inputEl.type = 'password';
                text.setValue(this.plugin.settings.password || '');
                text.onChange(async v => {
                    this.plugin.settings.password = v;
                    await this.plugin.saveSettings();
                });
            });

        const testSetting = new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.login_test_name'))
            .setDesc(this.plugin.settings.authToken
                ? t('obsidian.settings.already_logged_in')
                : t('obsidian.settings.login_prompt'));

        testSetting.addButton(btn => {
            btn.setButtonText(t('obsidian.common.login'));
            btn.onClick(async () => {
                btn.setDisabled(true);
                btn.setButtonText(t('obsidian.settings.login_in_progress'));
                try {
                    const token = await this.plugin.login(this.plugin.settings.username, this.plugin.settings.password || '');
                    this.plugin.settings.authToken = token;
                    await this.plugin.saveSettings();
                    testSetting.descEl.style.color = 'var(--color-green)';
                    testSetting.setDesc(t('obsidian.settings.login_success'));
                } catch (err) {
                    testSetting.descEl.style.color = 'var(--color-red)';
                    testSetting.setDesc('✗ ' + err.message);
                } finally {
                    btn.setDisabled(false);
                    btn.setButtonText(t('obsidian.common.login'));
                }
            });
        });

        containerEl.createEl('h3', { text: t('obsidian.settings.section_output') });

        new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.output_folder_name'))
            .setDesc(t('obsidian.settings.output_folder_desc'))
            .addText(text => {
                text.setPlaceholder('Libri')
                    .setValue(this.plugin.settings.outputFolder)
                    .onChange(async v => {
                        this.plugin.settings.outputFolder = v.trim().replace(/^\/|\/$/g, '');
                        await this.plugin.saveSettings();
                    });
                new FolderSuggest(this.app, text.inputEl, async (folder) => {
                    this.plugin.settings.outputFolder = folder.replace(/^\/|\/$/g, '');
                    text.setValue(folder);
                    await this.plugin.saveSettings();
                });
            });

        new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.filename_template_name'))
            .setDesc(t('obsidian.settings.filename_template_desc'))
            .addText(text => text
                .setPlaceholder('{{title}}')
                .setValue(this.plugin.settings.filenameTemplate)
                .onChange(async v => {
                    this.plugin.settings.filenameTemplate = v.trim() || '{{title}}';
                    await this.plugin.saveSettings();
                }));

        containerEl.createEl('h3', { text: t('obsidian.settings.section_header_template') });
        const headerDesc = containerEl.createEl('p', { cls: 'setting-item-description' });
        headerDesc.innerHTML = t('obsidian.settings.header_template_desc');

        const headerSetting = new obsidian.Setting(containerEl).setName(t('obsidian.settings.header_template_name'));
        headerSetting.addTextArea(ta => {
            ta.setPlaceholder(DEFAULT_BOOK_HEADER);
            ta.setValue(this.plugin.settings.bookHeaderTemplate ?? DEFAULT_BOOK_HEADER);
            ta.inputEl.rows = 5;
            ta.inputEl.style.fontFamily = 'var(--font-monospace, monospace)';
            ta.inputEl.style.width = '100%';
            ta.onChange(async v => {
                this.plugin.settings.bookHeaderTemplate = v;
                await this.plugin.saveSettings();
            });
        });

        containerEl.createEl('h3', { text: t('obsidian.settings.section_updates') });

        const aggiornamento = new obsidian.Setting(containerEl)
            .setName(t('obsidian.settings.plugin_version_name'))
            .setDesc(t('obsidian.settings.plugin_version_desc', { version: this.plugin.manifest.version }));

        aggiornamento.addButton(btn => {
            btn.setButtonText(t('obsidian.settings.check_update_button'));
            btn.onClick(async () => {
                btn.setDisabled(true);
                btn.setButtonText(t('obsidian.settings.checking_updates'));
                try {
                    const disponibile = await this.plugin.versioneSulServer();
                    if (!this.plugin._versioneMaggiore(disponibile, this.plugin.manifest.version)) {
                        aggiornamento.descEl.style.color = '';
                        aggiornamento.setDesc(t('obsidian.settings.already_latest', { version: this.plugin.manifest.version }));
                        return;
                    }
                    aggiornamento.setDesc(t('obsidian.settings.update_found_installing', { version: disponibile }));
                    // Da qui in poi gira il codice nuovo: questa scheda
                    // viene distrutta insieme al plugin vecchio, e non c'e'
                    // niente di utile da scrivere dopo.
                    await this.plugin.controllaAggiornamenti();
                } catch (err) {
                    aggiornamento.descEl.style.color = 'var(--color-red)';
                    aggiornamento.setDesc('✗ ' + err.message);
                } finally {
                    btn.setDisabled(false);
                    btn.setButtonText(t('obsidian.settings.check_update_button'));
                }
            });
        });
    }
}

// ── Main plugin ───────────────────────────────────────────────────────────

class KolibreHighlightsPlugin extends obsidian.Plugin {

    async onload() {
        await this.loadSettings();
        this.addSettingTab(new KolibreSettingTab(this.app, this));
        this.addCommand({
            id: 'kolibre-import-highlights',
            name: t('obsidian.command.import'),
            callback: () => this.importHighlights(),
        });
        this.addCommand({
            id: 'kolibre-reimport-all',
            name: t('obsidian.command.reimport_all'),
            callback: () => this.reimportAllHighlights(),
        });
        this.addCommand({
            id: 'kolibre-update-plugin',
            name: t('obsidian.command.check_update'),
            callback: () => this.controllaAggiornamenti(),
        });
    }

    async loadSettings() {
        this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    }

    async saveSettings() {
        await this.saveData(this.settings);
    }

    // ── HTTP helpers ────────────────────────────────────────────────────

    async login(username, password) {
        const url = `${this.settings.serverUrl}/token`;
        let resp;
        try {
            resp = await obsidian.requestUrl({
                url, method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
                throw: false,
            });
        } catch (err) {
            throw new Error(t('obsidian.error.unreachable', { url, message: err.message }));
        }
        if (resp.status !== 200) {
            throw new Error(t('obsidian.error.bad_credentials', { status: resp.status }));
        }
        return resp.json.access_token;
    }

    /**
     * Any Kolibre call that needs the current authToken — wraps
     * obsidian.requestUrl and, on a 401 (the 7-day token expired, see
     * DEFAULT_SETTINGS' own comment), transparently re-logs in with the
     * saved username/password and retries ONCE with the fresh token before
     * giving up. Without this every expiry meant a manual trip to
     * Impostazioni to re-enter credentials — a real defect seen in use.
     * Falls through to the original 401 response untouched if no password
     * is saved (older installs, or a user who deliberately left it blank)
     * or the re-login itself fails (e.g. password changed server-side).
     */
    async authenticatedRequest(opts) {
        const doRequest = () => obsidian.requestUrl({
            ...opts,
            headers: { ...(opts.headers || {}), 'Authorization': `Bearer ${this.settings.authToken}` },
            throw: false,
        });
        let resp = await doRequest();
        if (resp.status === 401 && this.settings.username && this.settings.password) {
            try {
                const token = await this.login(this.settings.username, this.settings.password);
                this.settings.authToken = token;
                await this.saveSettings();
                resp = await doRequest();
            } catch (_) {
                // Re-login itself failed (server down, password changed…) —
                // fall through with the original 401, same error message
                // as before this fix.
            }
        }
        return resp;
    }

    async fetchHighlights() {
        const resp = await this.authenticatedRequest({
            url: `${this.settings.serverUrl}/api/kolibre/annotations/export`,
        });
        if (resp.status === 401) {
            throw new Error(t('obsidian.error.session_expired'));
        }
        if (resp.status !== 200) {
            throw new Error(t('obsidian.error.fetch_failed', { status: resp.status }));
        }
        return resp.json;
    }

    // ── Vault helpers ─────────────────────────────────────────────────────

    async ensureFolder(folderPath) {
        if (!folderPath) return;
        const parts = folderPath.split('/');
        let current = '';
        for (const part of parts) {
            current = current ? `${current}/${part}` : part;
            if (!this.app.vault.getAbstractFileByPath(current)) {
                try { await this.app.vault.createFolder(current); } catch (_) { /* already exists */ }
            }
        }
    }

    // ── Aggiornamento del plugin dal server ──────────────────────────────
    //
    // Stessa idea del plugin KOReader: il server sa quale versione ha in
    // casa e sa servire i file uno per uno, quindi il plugin puo'
    // riscriversi da solo invece di farsi reinstallare a mano ogni volta.
    //
    // Tre cautele, tutte per lo stesso motivo — qui si sta sovrascrivendo
    // il codice che sta girando:
    //
    // 1. si scarica TUTTO prima di scrivere QUALSIASI cosa. Una connessione
    //    che cade a meta' lascerebbe altrimenti un plugin fatto di due
    //    versioni diverse, che e' peggio di uno vecchio;
    // 2. ogni file viene confrontato con l'impronta dichiarata dal server:
    //    un download troncato arriva lo stesso come HTTP 200, e un main.js
    //    tagliato a meta' e' un plugin che non si carica piu';
    // 3. `data.json` non e' nell'elenco del server (vedi il manifest lato
    //    backend): le impostazioni di questo vault, token compreso, non si
    //    toccano.

    /** Confronta "1.2.10" e "1.3.0" come numeri, non come testo. */
    _versioneMaggiore(candidata, corrente) {
        const pezzi = (v) => String(v || '0').split('.').map((n) => parseInt(n, 10) || 0);
        const a = pezzi(candidata);
        const b = pezzi(corrente);
        for (let i = 0; i < Math.max(a.length, b.length); i++) {
            const x = a[i] || 0;
            const y = b[i] || 0;
            if (x !== y) return x > y;
        }
        return false;
    }

    async _impronta(arrayBuffer) {
        const digest = await crypto.subtle.digest('SHA-256', arrayBuffer);
        return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('');
    }

    /**
     * La versione DAVVERO installata, letta dal manifest.json sul disco.
     *
     * Non `this.manifest.version`: Obsidian tiene in memoria i manifest dei
     * plugin e li rilegge all'avvio, non quando un plugin viene spento e
     * riacceso. Dopo un auto-aggiornamento `this.manifest` resta quindi
     * quello VECCHIO — il plugin si ritrovava a credersi la versione di
     * prima, riproporre l'aggiornamento, riscaricarlo, ricaricarsi, e
     * ricominciare. Difetto riscontrato in uso: il plugin si credeva ancora
     * alla 1.0.4 e continuava ad aggiornarsi da solo.
     */
    async versioneInstallata() {
        try {
            const grezzo = await this.app.vault.adapter.read(`${this.manifest.dir}/manifest.json`);
            const v = JSON.parse(grezzo).version;
            if (v) return String(v);
        } catch (err) {
            // Manifest illeggibile: meglio quello in memoria di niente.
        }
        return this.manifest.version;
    }

    /** La versione sul server, o null se non si riesce a chiedere. */
    async versioneSulServer() {
        const url = `${this.settings.serverUrl}/api/tools/plugins/obsidian/version`;
        const resp = await obsidian.requestUrl({ url, throw: false });
        if (resp.status !== 200) throw new Error(t('obsidian.error.server_responded', { status: resp.status }));
        return resp.json && resp.json.version;
    }

    /**
     * Scarica e installa l'ultima versione. Torna la versione installata,
     * o null se non c'era niente da fare.
     */
    async aggiornaPlugin(forza = false) {
        if (!this.settings.serverUrl) throw new Error(t('obsidian.error.not_configured'));
        const base = `${this.settings.serverUrl}/api/tools/plugins/obsidian`;

        const manifest = await obsidian.requestUrl({ url: `${base}/manifest`, throw: false });
        if (manifest.status !== 200) throw new Error(t('obsidian.error.server_responded', { status: manifest.status }));
        const { version, files, checksums } = manifest.json || {};
        if (!version || !Array.isArray(files) || files.length === 0) {
            throw new Error(t('obsidian.error.invalid_file_list'));
        }
        if (!forza && !this._versioneMaggiore(version, await this.versioneInstallata())) return null;

        const scaricati = [];
        for (const rel of files) {
            const resp = await obsidian.requestUrl({ url: `${base}/file/${rel}`, throw: false });
            if (resp.status !== 200) throw new Error(t('obsidian.error.file_fetch_failed', { file: rel, status: resp.status }));
            const dati = resp.arrayBuffer;
            const atteso = (checksums || {})[rel];
            if (atteso) {
                // La lunghezza si controlla sempre, ed e' il controllo che
                // prende il caso reale: una connessione che cade a meta'
                // consegna comunque un HTTP 200 con un corpo corto.
                if (dati.byteLength !== atteso.size) {
                    throw new Error(t('obsidian.error.incomplete_download', { file: rel, actual: dati.byteLength, expected: atteso.size }));
                }
                // L'impronta e' un controllo in piu', non l'unico: se
                // l'ambiente non offre crypto.subtle si rinuncia a questa
                // invece di rinunciare all'aggiornamento.
                if (crypto && crypto.subtle && await this._impronta(dati) !== atteso.sha256) {
                    throw new Error(t('obsidian.error.checksum_mismatch', { file: rel }));
                }
            }
            scaricati.push({ rel, dati });
        }

        // Solo adesso si scrive: da qui in poi non si torna indietro.
        const cartella = this.manifest.dir;
        for (const { rel, dati } of scaricati) {
            await this.app.vault.adapter.writeBinary(`${cartella}/${rel}`, dati);
        }
        return version;
    }

    /**
     * Il giro completo come lo vede l'utente: controlla, aggiorna, e
     * ricarica il plugin. Il ricaricamento e' l'ultima istruzione utile di
     * questa funzione: da li' in poi sta girando il codice NUOVO.
     */
    async controllaAggiornamenti(silenzioso = false) {
        try {
            const versione = await this.aggiornaPlugin();
            if (!versione) {
                if (!silenzioso) {
                    new obsidian.Notice(t('obsidian.notice.update_already_current', { version: await this.versioneInstallata() }));
                }
                return;
            }
            new obsidian.Notice(t('obsidian.notice.update_installed_reloading', { version: versione }), 6000);
            // Nota: dopo il ricaricamento `this.manifest` di Obsidian resta
            // la versione VECCHIA finche' non si riavvia Obsidian. E' per
            // questo che il confronto qui sopra legge il manifest dal disco:
            // altrimenti il plugin si riaggiornerebbe all'infinito.
            // Il ricaricamento ha un try/catch suo: i file NUOVI sono gia'
            // sul disco, quindi se fallisce l'aggiornamento e' comunque
            // riuscito e va detto cosi'. Metterlo insieme al resto farebbe
            // comparire "aggiornamento non riuscito" dopo un aggiornamento
            // perfettamente riuscito, e chi legge riproverebbe a vuoto.
            try {
                const id = this.manifest.id;
                await this.app.plugins.disablePlugin(id);
                await this.app.plugins.enablePlugin(id);
            } catch (err) {
                new obsidian.Notice(t('obsidian.notice.reload_failed', { version: versione }), 10000);
            }
        } catch (err) {
            if (!silenzioso) new obsidian.Notice(t('obsidian.notice.update_failed', { message: err.message }), 8000);
        }
    }

    // ── Core import logic ────────────────────────────────────────────────

    async importHighlights() {
        if (!this.settings.serverUrl || !this.settings.authToken) {
            new obsidian.Notice(t('obsidian.notice.not_configured'));
            return;
        }

        const notice = new obsidian.Notice(t('obsidian.notice.importing'), 0);
        try {
            const highlights = await this.fetchHighlights();
            if (!highlights || highlights.length === 0) {
                notice.hide();
                new obsidian.Notice(t('obsidian.notice.no_highlights_found'), 5000);
                return;
            }

            const books = groupHighlightsByBook(highlights);

            const folder = this.settings.outputFolder || 'Libri';
            await this.ensureFolder(folder);

            const newFiles = [];
            const updatedFiles = [];
            let totalAdded = 0;

            for (const bookData of Object.values(books)) {
                const template = this.settings.filenameTemplate || '{{title}}';
                const basename = applyFilenameTemplate(template, bookData);
                const filename = `${folder}/${basename}.md`;
                const existing = this.app.vault.getAbstractFileByPath(filename);

                if (!existing) {
                    const content = buildNewFile(bookData, this.settings, basename);
                    await this.app.vault.create(filename, content);
                    newFiles.push({ title: bookData.title, count: bookData.highlights.length });
                    totalAdded += bookData.highlights.length;
                } else {
                    const currentContent = await this.app.vault.read(existing);
                    const { content, added } = mergeHighlights(currentContent, bookData);
                    if (added > 0) {
                        await this.app.vault.modify(existing, content);
                        updatedFiles.push({ title: bookData.title, count: added });
                        totalAdded += added;
                    }
                }
            }

            notice.hide();
            if (totalAdded === 0) {
                new obsidian.Notice(t('obsidian.notice.nothing_new'), 5000);
            } else {
                new ImportSummaryModal(this.app, { newFiles, updatedFiles, totalAdded }).open();
            }
        } catch (err) {
            notice.hide();
            new obsidian.Notice(t('obsidian.notice.generic_error', { message: err.message }), 10000);
            console.error('[Kolibre] Import error:', err);
        }
    }

    /**
     * Entry point for the destructive command — only ever shows the
     * confirmation, never touches the vault itself. See ConfirmModal and
     * _runFullReimport (the part that actually writes files, only reached
     * from the modal's own confirm button).
     */
    async reimportAllHighlights() {
        if (!this.settings.serverUrl || !this.settings.authToken) {
            new obsidian.Notice(t('obsidian.notice.not_configured'));
            return;
        }
        new ConfirmModal(this.app, {
            title: t('obsidian.reimport.title'),
            message: t('obsidian.reimport.message'),
            confirmText: t('obsidian.reimport.confirm_button'),
            onConfirm: () => this._runFullReimport(),
        }).open();
    }

    /**
     * Unlike importHighlights, always rebuilds each book's file from
     * scratch with buildNewFile() and always vault.modify()/create()s it —
     * mergeHighlights (which preserves hand-written content) is never
     * called here on purpose, that's the whole point of this command. The
     * <!-- kolibre-hl:ID --> markers buildNewFile still writes mean a
     * later regular "Importa evidenziazioni" run keeps working correctly
     * (dedup by marker) on the files this just rewrote.
     */
    async _runFullReimport() {
        const notice = new obsidian.Notice(t('obsidian.notice.full_reimporting'), 0);
        try {
            const highlights = await this.fetchHighlights();
            if (!highlights || highlights.length === 0) {
                notice.hide();
                new obsidian.Notice(t('obsidian.notice.no_highlights_found'), 5000);
                return;
            }

            const books = groupHighlightsByBook(highlights);
            const folder = this.settings.outputFolder || 'Libri';
            await this.ensureFolder(folder);

            const newFiles = [];
            let totalAdded = 0;

            for (const bookData of Object.values(books)) {
                const template = this.settings.filenameTemplate || '{{title}}';
                const basename = applyFilenameTemplate(template, bookData);
                const filename = `${folder}/${basename}.md`;
                const existing = this.app.vault.getAbstractFileByPath(filename);
                const content = buildNewFile(bookData, this.settings, basename);

                if (existing) {
                    await this.app.vault.modify(existing, content);
                } else {
                    await this.app.vault.create(filename, content);
                }
                newFiles.push({ title: bookData.title, count: bookData.highlights.length });
                totalAdded += bookData.highlights.length;
            }

            notice.hide();
            new ImportSummaryModal(this.app, { newFiles, updatedFiles: [], totalAdded }).open();
        } catch (err) {
            notice.hide();
            new obsidian.Notice(t('obsidian.notice.generic_error', { message: err.message }), 10000);
            console.error('[Kolibre] Full reimport error:', err);
        }
    }
}

module.exports = KolibreHighlightsPlugin;
