// Da «come voglio leggere» al foglio di stile che epub.js inietta nel libro.
//
// Funzione pura di proposito: `temaPerEpubJs` non tocca niente, prende le
// preferenze e restituisce l'oggetto che `rendition.themes.default()` vuole —
// `{selettore: {proprieta': valore}}`. Cosi' si puo' provare senza un browser,
// e tutto il ragionamento sul CSS sta in un posto solo invece che sparso nel
// mezzo del ciclo di rendering.
//
// **Perche' quasi tutto ha `!important`.** Il foglio di stile che scriviamo
// arriva PRIMA di quello del libro nell'ordine della cascata, e gli editori
// mettono volentieri `font-family` e `color` direttamente sugli elementi. Senza
// `!important` un'impostazione funzionerebbe su un libro e non sul successivo,
// che e' il modo peggiore di avere un'impostazione.

export type Tema = 'sistema' | 'chiaro' | 'sepia' | 'grigio' | 'scuro'
export type OverrideColori = 'mai' | 'scuro' | 'sempre'
// I nomi vecchi ('serif', 'sans', 'leggibile') restano quelli: sono salvati
// in localStorage da chi legge gia', e rinominarli vorrebbe dire rimettere
// tutti su «come il libro» senza dirglielo. Quello che cambia e' come si
// presentano — col nome del carattere vero, scritto in quel carattere.
export type Carattere = 'libro' | 'serif' | 'palatino' | 'times' | 'sans' | 'leggibile'

export interface PreferenzeLettura {
  tema: Tema
  /** Se i colori del libro vengono sovrascritti dal tema. */
  overrideColori: OverrideColori
  carattere: Carattere
  /** Altezza di riga. `null` = come l'ha voluta l'editore. */
  interlinea: number | null
  /** Quanto spazio lasciare ai lati, in percentuale della larghezza. */
  margini: number
  /** `null` = come l'ha voluta l'editore. */
  giustificato: boolean | null
  sillabazione: boolean
}

interface ColoriTema {
  sfondo: string
  testo: string
  link: string
}

// Cinque temi, non di piu'. Ognuno deve essere una risposta a una domanda
// diversa — luce piena, sera, carta, poca luce — non una variazione di tinta.
const COLORI: Record<Exclude<Tema, 'sistema'>, ColoriTema> = {
  chiaro: { sfondo: '#ffffff', testo: '#1a1a1a', link: '#1e5fbf' },
  // Il grigio chiaro esiste perche' il bianco pieno su uno schermo luminoso
  // stanca: e' la via di mezzo fra il bianco e il sepia per chi il sepia non
  // lo sopporta.
  grigio: { sfondo: '#e9e8e4', testo: '#24241f', link: '#1b5296' },
  sepia: { sfondo: '#f4ecd8', testo: '#3a2f1f', link: '#8a4b1e' },
  scuro: { sfondo: '#16181c', testo: '#c7cbd1', link: '#7aa7e8' },
}

// Non si spediscono webfont dentro l'iframe del libro: sono tutti caratteri
// di sistema, presenti ovunque, e un carattere che non arriva e' peggio di
// uno che non si e' scelto. Ogni voce ha il suo ripiego per le piattaforme
// dove il primo nome non c'e'.
export const FAMIGLIE: Record<Exclude<Carattere, 'libro'>, string> = {
  serif: "Georgia, 'Iowan Old Style', serif",
  // Il piu' «da libro» dei caratteri di sistema: asse umanistico, grazie
  // sottili. Su Windows si chiama Palatino Linotype, altrove Book Antiqua.
  palatino: "Palatino, 'Palatino Linotype', 'Book Antiqua', 'URW Palladio L', serif",
  times: "'Times New Roman', Times, 'Liberation Serif', serif",
  sans: "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
  // Non e' un carattere «per dislessia»: e' semplicemente piu' largo e con
  // l'occhio medio piu' grande, quindi regge meglio i corpi piccoli.
  leggibile: "Verdana, Tahoma, 'DejaVu Sans', sans-serif",
}

/** Il nome da mostrare, scritto nel carattere stesso. Non si traduce. */
export const NOMI_CARATTERE: Record<Exclude<Carattere, 'libro'>, string> = {
  serif: 'Georgia',
  palatino: 'Palatino',
  times: 'Times New Roman',
  sans: 'Sistema',
  leggibile: 'Verdana',
}

export const PREFERENZE_PREDEFINITE: PreferenzeLettura = {
  tema: 'sistema',
  // 'scuro' e non 'sempre': di giorno i colori che l'editore ha scelto sono
  // spesso voluti (un titolo colorato, un riquadro), e toglierli sempre
  // impoverisce il libro. Di notte invece un libro che dichiara sfondo bianco
  // produce una pagina abbagliante dentro un tema scuro, ed e' il caso in cui
  // sovrascrivere e' l'unica risposta sensata.
  overrideColori: 'scuro',
  carattere: 'libro',
  interlinea: null,
  margini: 6,
  giustificato: null,
  sillabazione: true,
}

/** I colori veri, risolvendo 'sistema' con la preferenza del sistema. */
export function coloriDi(tema: Tema, sistemaEScuro: boolean): ColoriTema {
  if (tema === 'sistema') return sistemaEScuro ? COLORI.scuro : COLORI.chiaro
  return COLORI[tema]
}

/** Se il tema risolto e' scuro — serve a decidere l'override dei colori. */
export function temaEScuro(tema: Tema, sistemaEScuro: boolean): boolean {
  return tema === 'scuro' || (tema === 'sistema' && sistemaEScuro)
}

export function temaPerEpubJs(p: PreferenzeLettura, sistemaEScuro: boolean): Record<string, Record<string, string>> {
  const c = coloriDi(p.tema, sistemaEScuro)
  const scuro = temaEScuro(p.tema, sistemaEScuro)
  const sovrascrivi = p.overrideColori === 'sempre' || (p.overrideColori === 'scuro' && scuro)

  const regole: Record<string, Record<string, string>> = {
    // `html` e `body` insieme: epub.js azzera lo sfondo del body a
    // trasparente, e senza forzarlo qui si vedrebbe attraverso.
    html: { background: `${c.sfondo} !important` },
    body: {
      background: `${c.sfondo} !important`,
      color: `${c.testo} !important`,
      // I margini laterali stanno sul body e non sul contenitore di epub.js:
      // cosi' valgono anche in doppia pagina, dove il contenitore e' uno solo
      // e i margini finirebbero ai due estremi invece che attorno a ogni colonna.
      'padding-left': `${p.margini}% !important`,
      'padding-right': `${p.margini}% !important`,
    },
  }

  if (sovrascrivi) {
    // Il selettore universale e' la stessa scelta del viewer di Calibre
    // (`apply_colors` in settings.pyj). Serve perche' i colori dell'editore
    // possono stare su qualunque elemento, anche in stile inline.
    regole['*'] = {
      color: `${c.testo} !important`,
      'background-color': 'transparent !important',
      'border-color': `${c.testo} !important`,
    }
    // I link vanno rialzati DOPO il selettore universale, che altrimenti li
    // appiattirebbe sul colore del testo e li renderebbe invisibili.
    regole['a, a *'] = { color: `${c.link} !important` }
    // Le immagini non vanno colorate: `*` con background trasparente le
    // lascia stare, ma un bordo colorato su una figura si vede.
    regole['img, svg, video'] = { 'border-color': 'transparent !important' }
  } else {
    regole['a, a *'] = { color: `${c.link} !important` }
  }

  if (p.carattere !== 'libro') {
    const famiglia = FAMIGLIE[p.carattere]
    // Non sul solo `body`: gli editori mettono `font-family` sui paragrafi.
    // Esclusi i monospaziati, che in un libro sono codice o versi allineati e
    // cambiarli rompe l'allineamento.
    regole['body, p, div, span, li, td, th, h1, h2, h3, h4, h5, h6, blockquote'] = {
      'font-family': `${famiglia} !important`,
    }
    regole['code, pre, kbd, samp'] = { 'font-family': 'ui-monospace, Menlo, Consolas, monospace !important' }
  }

  if (p.interlinea != null) {
    regole['body, p, li, blockquote'] = {
      ...(regole['body, p, li, blockquote'] ?? {}),
      'line-height': `${p.interlinea} !important`,
    }
  }

  if (p.giustificato != null) {
    regole['body, p, li'] = {
      ...(regole['body, p, li'] ?? {}),
      'text-align': `${p.giustificato ? 'justify' : 'left'} !important`,
    }
  }

  // La sillabazione va messa comunque, anche senza giustificazione: con il
  // testo a bandiera riduce comunque i buchi a fine riga. Ma conta soprattutto
  // in italiano giustificato, dove senza si leggono righe con voragini.
  //
  // `hyphens: auto` funziona SOLO se il documento dichiara la lingua: il
  // browser sceglie il dizionario di sillabazione da `lang`. Se il libro non
  // la dichiara, questa regola non fa niente — ed e' giusto cosi', meglio
  // niente che sillabare l'italiano con le regole dell'inglese.
  regole['body, p, li, blockquote'] = {
    ...(regole['body, p, li, blockquote'] ?? {}),
    hyphens: p.sillabazione ? 'auto !important' : 'manual !important',
    '-webkit-hyphens': p.sillabazione ? 'auto !important' : 'manual !important',
  }

  return regole
}
