// Dove finisce un indirizzo che non esiste.
//
// **Perché non è «una pagina 404».** Chi ci arriva non ha sbagliato a
// cercare: ci arriva perché ha cliccato un collegamento vecchio, o perché il
// libro di cui aveva salvato l'indirizzo è stato cancellato. Una pagina che
// dice «404 Not Found» tratta quella persona come se avesse digitato male, e
// le lascia un vicolo chiuso.
//
// Quindi fa tre cose, in questo ordine:
//  1. dice **cosa è successo in parole normali** — e distingue «questo
//     indirizzo non esiste» da «questa cosa non c'è più», perché sono due
//     fatti diversi e portano a due gesti diversi;
//  2. porta **dove si voleva andare**, non a una home generica: se
//     l'indirizzo nomina un libro, offre la biblioteca; se nomina un
//     dispositivo, i dispositivi;
//  3. **non assomiglia a un guasto**. Nessun rosso, nessun triangolo di
//     avviso: un collegamento vecchio non è un programma rotto, e spaventare
//     chi legge è un costo senza ritorno.
import { Link, useLocation } from 'react-router-dom'
import { Compass } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'

/** La sezione che l'indirizzo sembrava cercare, se se ne riconosce una. */
function sezioneRiconosciuta(percorso: string): { dove: string; chiave: string } | null {
  // Si guarda il primo pezzo dell'indirizzo, non tutto: `/libri/9999` è un
  // libro che non c'è, e la risposta utile è la biblioteca — non la home.
  const primo = percorso.split('/').filter(Boolean)[0]
  const mappa: Record<string, { dove: string; chiave: string }> = {
    libri: { dove: '/', chiave: 'book' },
    autori: { dove: '/autori', chiave: 'author' },
    serie: { dove: '/serie', chiave: 'series' },
    dispositivi: { dove: '/dispositivi', chiave: 'device' },
    annotazioni: { dove: '/annotazioni', chiave: 'annotation' },
    statistiche: { dove: '/statistiche', chiave: 'stats' },
  }
  return (primo && mappa[primo]) || null
}

export function IndirizzoSbagliato() {
  const { t } = useLingua()
  const { pathname } = useLocation()
  const sezione = sezioneRiconosciuta(pathname)

  return (
    <div className="mx-auto flex max-w-[460px] flex-col items-center gap-4 px-4 py-16 text-center">
      <Compass className="size-8 text-muted-foreground/60" />
      <h1 className="font-serif text-[22px] font-semibold">
        {sezione ? t(`notFound.title.${sezione.chiave}`) : t('notFound.title.generic')}
      </h1>
      <p className="text-[13px] leading-relaxed text-muted-foreground">
        {sezione ? t(`notFound.body.${sezione.chiave}`) : t('notFound.body.generic')}
      </p>
      {/* L'indirizzo si mostra, piccolo: a chi non serve non dà fastidio, e a
          chi sta cercando di capire cosa ha incollato serve davvero. */}
      <code className="max-w-full truncate rounded bg-muted px-2 py-1 text-[11px] text-muted-foreground">
        {pathname}
      </code>
      <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
        {sezione && (
          <Button asChild size="sm">
            <Link to={sezione.dove}>{t(`notFound.goTo.${sezione.chiave}`)}</Link>
          </Button>
        )}
        <Button asChild size="sm" variant={sezione ? 'outline' : 'default'}>
          <Link to="/">{t('notFound.goHome')}</Link>
        </Button>
      </div>
    </div>
  )
}
