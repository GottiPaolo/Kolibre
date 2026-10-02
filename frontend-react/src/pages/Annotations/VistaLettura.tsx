import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { numero, useLingua } from '@/lib/i18n'
import { Passaggio, type AzioniPassaggio } from './Passaggio'
import type { Highlight } from '@/types/annotation'

// Vista A — Lettura continua.
//
// Una colonna sola, misura da lettura, nessun riquadro: il passaggio è la
// pagina, e il libro gli sta a margine invece di incorniciarlo. Serve a
// RISCOPRIRE — scorrere e inciampare in qualcosa che si era dimenticato — e
// per questo non prova anche a far trovare: per trovare c'è la ricerca, che
// qui filtra lo stesso elenco.
//
// Si carica a scaglioni. Sui dati veri sono 1.019 passaggi di 394 caratteri
// mediani: disegnarli tutti insieme è un muro di DOM per una pagina che si
// guarda dall'alto. Il bottone dice quanti ne restano, perché «carica altro»
// senza un numero non lascia decidere se vale la pena.

const SCAGLIONE = 60

export function VistaLettura({
  passaggi,
  azioni,
  cerca,
  mostraLibro = true,
}: {
  passaggi: Highlight[]
  azioni: (h: Highlight) => AzioniPassaggio
  cerca?: string
  mostraLibro?: boolean
}) {
  const { t } = useLingua()
  const [quanti, setQuanti] = useState(SCAGLIONE)

  // Cambiando filtro o ricerca si riparte dall'inizio: restare a «ne mostro
  // 300» su un elenco appena diventato di dodici è una finestra sbagliata.
  useEffect(() => setQuanti(SCAGLIONE), [passaggi])

  if (passaggi.length === 0) return null
  const mostrati = passaggi.slice(0, quanti)
  const restanti = passaggi.length - mostrati.length

  return (
    <div className="flex flex-col">
      {mostrati.map((h) => (
        <div key={h.id} className="border-b border-border/60 py-6 first:pt-1">
          <Passaggio highlight={h} taglia="grande" cerca={cerca} mostraLibro={mostraLibro} {...azioni(h)} />
        </div>
      ))}

      {restanti > 0 && (
        <div className="flex items-center gap-3 py-5">
          <Button variant="outline" size="sm" onClick={() => setQuanti((q) => q + SCAGLIONE)}>
            {t('annotations.readingView.showMore', { n: Math.min(SCAGLIONE, restanti) })}
          </Button>
          <span className="text-[12px] text-muted-foreground">
            {t('annotations.readingView.shownOf', { shown: mostrati.length, total: numero(passaggi.length) })}
          </span>
        </div>
      )}
    </div>
  )
}
