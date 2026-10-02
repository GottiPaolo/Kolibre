// Barra alfabetica laterale per la pagina Autori: con qualche centinaio di
// nomi, scorrere fino alla M è una faticata: qui si preme la lettera.
//
// Due scelte che vale la pena spiegare.
//
// 1. Compare solo quando l'elenco è davvero in ordine alfabetico. In vista
//    tabella si può ordinare per numero di libri o per pagine totali, e in
//    quel caso un indice A-Z indicherebbe posizioni che non esistono: la
//    "M" salterebbe a un punto qualsiasi. Meglio non mostrarlo che mentire.
//
// 2. Le lettere senza autori restano visibili ma spente, invece di sparire.
//    Una barra che cambia lunghezza a ogni ricerca è un bersaglio mobile:
//    tenendo le 27 posizioni fisse, la M sta sempre dove ci si aspetta.
import { cn } from '@/lib/utils'
import { useLingua } from '@/lib/i18n'

/** Iniziale normalizzata di un nome: "Émile" → E, "AA. VV." → A, "1984" → #. */
export function authorInitial(name: string): string {
  const first = name.trim().charAt(0)
  if (!first) return '#'
  // NFD + rimozione dei segni diacritici: senza, "Émile" finirebbe sotto #
  // invece che sotto E, e in una libreria italiana non è un caso di scuola.
  const plain = first.normalize('NFD').replace(/\p{Diacritic}/gu, '').toUpperCase()
  return /[A-Z]/.test(plain) ? plain : '#'
}

const LETTERS = ['#', ...Array.from({ length: 26 }, (_, i) => String.fromCharCode(65 + i))]

interface Props {
  /** Iniziali effettivamente presenti nell'elenco mostrato. */
  available: Set<string>
  onJump: (letter: string) => void
}

export function AuthorAlphabetIndex({ available, onJump }: Props) {
  const { t } = useLingua()
  return (
    <nav
      aria-label={t('authors.alphabetIndex.ariaLabel')}
      // sticky, non fixed: deve restare dentro la colonna di destra e
      // scorrere con la pagina fin dove serve, senza sovrapporsi al
      // contenuto né alla barra laterale dell'app.
      className="sticky top-2 flex shrink-0 select-none flex-col items-center gap-px self-start py-1"
    >
      {LETTERS.map((letter) => {
        const enabled = available.has(letter)
        return (
          <button
            key={letter}
            type="button"
            disabled={!enabled}
            onClick={() => onJump(letter)}
            aria-label={t('authors.alphabetIndex.jumpTo', { letter })}
            className={cn(
              'w-5 rounded-sm text-[10.5px] leading-[1.35] font-medium transition-colors',
              enabled
                ? 'text-muted-foreground hover:bg-accent hover:text-primary'
                : 'cursor-default text-muted-foreground/25'
            )}
          >
            {letter}
          </button>
        )
      })}
    </nav>
  )
}
