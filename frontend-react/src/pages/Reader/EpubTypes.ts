// Colma alcune lacune reali dei tipi bundle di epubjs (derivati da
// DefinitelyTyped, non sempre allineati al JS effettivo in
// node_modules/epubjs/lib/*.js — verificato leggendo quel sorgente, non solo
// il .d.ts):
//  - Locations non dichiara `total` (numero di "location" generate) benché
//    locations.js lo imposti davvero (usato per la pagina pseudo-numerica di
//    un'evidenziazione, vedi pseudoPageForCfi in EpubHelpers.ts).
//  - Section.load() è tipizzato per restituire `Document` ma in realtà
//    restituisce una Promise (core.defer().promise) — usato dalla ricerca
//    client-side nel libro.
//  - Section.find() è tipizzato per restituire `Element[]` ma in realtà
//    restituisce `{ cfi, excerpt }[]`.
//  - Rendition.getContents() è tipizzato per restituire una singola
//    `Contents`, ma il manager la implementa restituendo `Contents[]` (una
//    per ogni view attualmente renderizzata — più di una in spread doppio).
import type Book from 'epubjs/types/book'
import type Section from 'epubjs/types/section'
import type { Contents, Rendition } from 'epubjs'
import type { Highlight } from '@/types/annotation'

export interface EpubSearchMatch {
  cfi: string
  excerpt: string
}

export function locationsTotal(book: Book): number {
  return (book.locations as unknown as { total: number }).total
}

export function loadSectionDocument(section: Section, request: Function): Promise<unknown> {
  return section.load(request) as unknown as Promise<unknown>
}

export function findInSection(section: Section, query: string): EpubSearchMatch[] {
  return section.find(query) as unknown as EpubSearchMatch[]
}

export function renditionContentsList(rendition: Rendition): Contents[] {
  return rendition.getContents() as unknown as Contents[]
}

// null = nessun pannello aperto (sidebar chiusa).
export type SidebarTab = 'toc' | 'search' | 'notes' | null

export interface SelectionPopupState {
  visible: boolean
  x: number
  y: number
  cfiRange: string | null
  text: string
}

export const EMPTY_SELECTION_POPUP: SelectionPopupState = { visible: false, x: 0, y: 0, cfiRange: null, text: '' }

export interface HighlightPopupState {
  visible: boolean
  x: number
  y: number
  highlight: Highlight | null
}

export const EMPTY_HIGHLIGHT_POPUP: HighlightPopupState = { visible: false, x: 0, y: 0, highlight: null }
