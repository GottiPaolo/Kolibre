import { cn } from '@/lib/utils'

/**
 * Il colibrì di Kolibre, colorato dal tema.
 *
 * Il logo originale è dipinto in quattro tonalità dello stesso rosso:
 * contorno, campitura piena (corpo, copertina del libro), campitura chiara
 * (le ali interne) e finestre bianche. Finché resta un'immagine quei rossi
 * sono fissi, e con un tema verde o blu stonano.
 *
 * Qui il disegno è scomposto in quattro maschere — una per tonalità, estratte
 * una volta dal PNG originale — e ognuna viene riempita con un
 * colore ricavato dal tema. La forma resta esattamente quella originale:
 * cambiano solo i colori.
 *
 * **Due tentativi prima di questo, e a cosa sono serviti.** Il primo usava un
 * filtro SVG che mappava la luminosità sull'opacità: eleganza matematica, un
 * logo semitrasparente a tinta unica. Il secondo scomponeva in tre fasce ma
 * con pesi morbidi, che le impastavano di nuovo. Il criterio e' venuto fuori
 * guardando le prove vere: fra queste tonalita' gli stacchi netti sono un
 * pregio, non un difetto. Le fasce ora sono quattro e nette.
 *
 * **Perché questi quattro colori.** Uno solo è scelto — `--primary` — e gli
 * altri tre ne discendono: il contorno è lo stesso colore spinto verso quello
 * del testo, la campitura chiara è lo stesso colore diluito nel fondo delle
 * schede, le finestre sono quel fondo. Così il rapporto fra le tonalità resta
 * quello del logo originale in qualunque tema, e un tema che cambia solo il
 * colore primario ricolora il logo per intero senza sapere che il logo
 * esiste. Sui temi scuri il contorno resta scuro invece di invertirsi in
 * chiaro: l'inversione era leggibile ma faceva un altro logo.
 */
const LIVELLI = [
  // Dal più chiaro al più scuro: il contorno va disegnato per ultimo, sopra
  // le campiture, come in qualunque disegno a china.
  { file: 'kolibre_finestre.png', colore: 'var(--card)' },
  { file: 'kolibre_chiaro.png', colore: 'color-mix(in srgb, var(--primary) 35%, var(--card))' },
  { file: 'kolibre_pieno.png', colore: 'var(--primary)' },
  { file: 'kolibre_tratto.png', colore: 'color-mix(in srgb, var(--primary) 55%, var(--foreground))' },
]

export function KolibreLogo({ className }: { className?: string }) {
  return (
    <span className={cn('relative inline-block shrink-0 align-middle', className)} aria-label="Kolibre" role="img">
      {LIVELLI.map((livello) => (
        <span
          key={livello.file}
          aria-hidden
          className="absolute inset-0"
          style={{
            backgroundColor: livello.colore,
            // La maschera ritaglia il colore secondo l'opacità del PNG:
            // è il PNG a dare la forma, il tema a dare la tinta.
            maskImage: `url(/logo/${livello.file})`,
            WebkitMaskImage: `url(/logo/${livello.file})`,
            maskSize: 'contain',
            WebkitMaskSize: 'contain',
            maskRepeat: 'no-repeat',
            WebkitMaskRepeat: 'no-repeat',
            maskPosition: 'center',
            WebkitMaskPosition: 'center',
          }}
        />
      ))}
    </span>
  )
}
