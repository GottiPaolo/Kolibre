// Le lingue di Wikipedia: gli autonimi (il nome della lingua scritto
// nella lingua stessa: Deutsch, English, Italiano…).
//
// L'ORDINE delle lingue nel tasto della pagina autore NON si decide più
// qui (23/11/2026 sera, scelta di Paolo): è l'ordine dell'elenco nelle
// Impostazioni → Integrazioni, così com'è scritto lì. Qui restano solo
// gli autonimi; un codice sconosciuto non sparisce: resta col suo codice.

export const WIKIPEDIA_AUTONYMS: Record<string, string> = {
  ar: 'العربية',
  bg: 'Български',
  ca: 'Català',
  cs: 'Čeština',
  da: 'Dansk',
  de: 'Deutsch',
  el: 'Ελληνικά',
  en: 'English',
  es: 'Español',
  fi: 'Suomi',
  fr: 'Français',
  he: 'עברית',
  hr: 'Hrvatski',
  hu: 'Magyar',
  it: 'Italiano',
  ja: '日本語',
  ko: '한국어',
  la: 'Latina',
  nl: 'Nederlands',
  no: 'Norsk',
  pl: 'Polski',
  pt: 'Português',
  ro: 'Română',
  ru: 'Русский',
  sk: 'Slovenčina',
  sl: 'Slovenščina',
  sr: 'Српски',
  sv: 'Svenska',
  tr: 'Türkçe',
  uk: 'Українська',
  zh: '中文',
}

/** Il nome della lingua nella lingua stessa; un codice ignoto resta codice. */
export function autonym(code: string): string {
  return WIKIPEDIA_AUTONYMS[code] ?? code
}

