import { useCallback, useEffect, useState } from 'react'
import { leggiLocale, scriviLocale } from './memoriaLocale'

export type BasePresetId =
  | 'sake' | 'museo' | 'carta'
  | 'calibre' | 'foresta' | 'sottobosco' | 'notte' | 'lino' | 'ottone' | 'tipografia'

const PRESET_BASE: readonly BasePresetId[] = [
  'sake', 'museo', 'carta',
  'calibre', 'foresta', 'sottobosco', 'notte', 'lino', 'ottone', 'tipografia',
]

// Quali dei dieci preset sono chiari — serve a decidere in quale delle due
// caselle (chiaro/scuro) finisce uno stile scelto, e quindi quali sono
// chiari e quali scuri.
export const PRESET_CHIARI: readonly BasePresetId[] = ['carta', 'calibre', 'foresta', 'lino', 'tipografia']

// Solo i preset. Il costruttore di temi personalizzati è stato tolto il
// 03/10/2026 perché era grezzo, malfunzionante e stonava con l'eleganza del
// resto: un valore "custom:N" rimasto nel localStorage di un'installazione
// precedente non supera più `eVariante` e si ricade sul predefinito —
// degrada, non rompe.
export type StyleVariant = BasePresetId

/**
 * v3: non si sceglie UNO stile, si sceglie una COPPIA — uno chiaro e uno
 * scuro — piu' la regola che decide quale dei due e' attivo.
 *
 * Il motivo e' diventato concreto con dieci stili invece di tre: la scelta
 * naturale non e' piu' "quale mi piace" ma "quale di giorno e quale di
 * notte". `adattivo` lascia decidere al sistema operativo; spento, decide
 * `attivo`.
 */
export interface SceltaStile {
  chiaro: StyleVariant
  scuro: StyleVariant
  /** Segue il tema chiaro/scuro del sistema operativo. */
  adattivo: boolean
  /** Quale dei due e' attivo quando `adattivo` e' spento. */
  attivo: 'chiaro' | 'scuro'
}

const STORAGE_KEY = 'kolibre_style_variant'
const STORAGE_KEY_V3 = 'kolibre_style_pair_v3'

const PREDEFINITA: SceltaStile = { chiaro: 'carta', scuro: 'sake', adattivo: false, attivo: 'scuro' }

function eVariante(v: unknown): v is StyleVariant {
  return typeof v === 'string' && (PRESET_BASE as readonly string[]).includes(v)
}

/**
 * Legge la scelta salvata, migrando dalla forma vecchia (un solo stile).
 *
 * La migrazione non butta niente: lo stile che l'utente aveva scelto finisce
 * nella casella giusta — chiaro o scuro a seconda di cosa e' — e diventa
 * quello attivo. L'altra casella prende un valore ragionevole. Chi non tocca
 * piu' niente continua a vedere esattamente quello che vedeva.
 */
function leggiScelta(): SceltaStile {
  try {
    const grezzo = leggiLocale(STORAGE_KEY_V3)
    if (grezzo) {
      const p = JSON.parse(grezzo) as Partial<SceltaStile>
      return {
        chiaro: eVariante(p.chiaro) ? p.chiaro : PREDEFINITA.chiaro,
        scuro: eVariante(p.scuro) ? p.scuro : PREDEFINITA.scuro,
        adattivo: !!p.adattivo,
        attivo: p.attivo === 'chiaro' ? 'chiaro' : 'scuro',
      }
    }
  } catch {
    // localStorage illeggibile (finestra privata, dati del sito bloccati):
    // si riparte dalla scelta predefinita invece di non partire.
  }
  const vecchio = leggiLocale(STORAGE_KEY)
  if (eVariante(vecchio)) {
    const chiaro = (PRESET_CHIARI as readonly string[]).includes(vecchio)
    return chiaro
      ? { ...PREDEFINITA, chiaro: vecchio, attivo: 'chiaro' }
      : { ...PREDEFINITA, scuro: vecchio, attivo: 'scuro' }
  }
  return PREDEFINITA
}

function sistemaEScuro(): boolean {
  return typeof window !== 'undefined'
    && !!window.matchMedia?.('(prefers-color-scheme: dark)').matches
}

// Applica lo stile scelto come attributo sulla radice — il meccanismo dei
// mockup HTML approvati. Chiamato una volta per documento (Layout.tsx per l'app
// principale, ReaderPage.tsx/PdfReaderPage.tsx perché aprono come finestre
// separate con un proprio <html>) — ognuno risolve e applica il proprio
// stato in modo indipendente, stessa ragione per cui data-style era già
// impostato in ognuno di questi punti prima di questa estensione.
export function useStyleVariant() {
  const [scelta, setSceltaState] = useState<SceltaStile>(leggiScelta)
  const [scuroDiSistema, setScuroDiSistema] = useState(sistemaEScuro)

  // La migrazione dalla forma vecchia si scrive una volta sola, al primo
  // avvio dopo l'aggiornamento. Senza, la chiave vecchia resterebbe l'unica
  // salvata e verrebbe ri-migrata ad ogni caricamento: funziona, ma lo stato
  // vero resta implicito — e chi apre le Impostazioni vedrebbe una coppia
  // che da nessuna parte risulta essere stata scelta.
  useEffect(() => {
    if (leggiLocale(STORAGE_KEY_V3)) return
    try {
      scriviLocale(STORAGE_KEY_V3, JSON.stringify(scelta))
    } catch {
      // Spazio non scrivibile: si continua a migrare al volo ad ogni avvio.
    }
    // Solo al montaggio: e' una migrazione, non una sincronizzazione.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Il sistema puo' cambiare tema mentre l'app e' aperta (al tramonto, su
  // macOS con "automatico"): senza questo, "segui il sistema" seguirebbe
  // solo al caricamento della pagina, che non e' seguire.
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const aggiorna = (e: MediaQueryListEvent) => setScuroDiSistema(e.matches)
    mq.addEventListener('change', aggiorna)
    return () => mq.removeEventListener('change', aggiorna)
  }, [])

  const scuroAttivo = scelta.adattivo ? scuroDiSistema : scelta.attivo === 'scuro'
  const variant: StyleVariant = scuroAttivo ? scelta.scuro : scelta.chiaro

  // Un attributo sull'elemento radice, e tutto il resto lo fa il CSS: ogni
  // preset è un blocco di token in index.css sotto [data-style="…"].
  useEffect(() => {
    document.documentElement.setAttribute('data-style', variant)
  }, [variant])

  const setScelta = useCallback((prossima: SceltaStile) => {
    scriviLocale(STORAGE_KEY_V3, JSON.stringify(prossima))
    // Si tiene aggiornata anche la chiave vecchia: le finestre del lettore
    // aperte prima di un aggiornamento leggono ancora quella, e cosi' non
    // tornano a Sake sotto gli occhi di chi sta leggendo.
    scriviLocale(
      STORAGE_KEY,
      (prossima.adattivo ? (sistemaEScuro() ? prossima.scuro : prossima.chiaro)
        : prossima.attivo === 'scuro' ? prossima.scuro : prossima.chiaro)
    )
    setSceltaState(prossima)
  }, [])

  /** Comodo per chi vuole solo cambiare lo stile attivo. */
  const setVariant = useCallback((next: StyleVariant) => {
    setSceltaState((prec) => {
      const chiaro = (PRESET_CHIARI as readonly string[]).includes(next)
      const prossima: SceltaStile = chiaro
        ? { ...prec, chiaro: next, adattivo: false, attivo: 'chiaro' }
        : { ...prec, scuro: next, adattivo: false, attivo: 'scuro' }
      scriviLocale(STORAGE_KEY_V3, JSON.stringify(prossima))
      scriviLocale(STORAGE_KEY, next)
      return prossima
    })
  }, [])

  return { variant, scelta, setScelta, setVariant, scuroAttivo }
}
