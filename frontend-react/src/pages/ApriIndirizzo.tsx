// La rotta `/k/*`: apre un indirizzo condivisibile.
//
// **Cos'è un indirizzo condivisibile.** `/k/libreria/i-miserabili-39e1f730`
// è il tipo di indirizzo che finisce dentro un appunto di Obsidian e ci resta
// per anni. Non è un indirizzo interno dell'applicazione: non contiene
// numeri di riga del database, e sopravvive a un libro rinominato, a una
// biblioteca reimportata, a due note fuse in una.
//
// **Questa pagina non lo interpreta: lo chiede al server.** È deliberato, ed
// è la ragione per cui esiste il file `backend/app/api/link.py`. Capire a
// cosa punta un indirizzo è una regola sui dati — quale libro ha quell'uuid,
// quella nota esiste ancora, e in mancanza di quella cosa cosa si apre al
// posto suo — e quella regola vale identica per il browser, per il plugin
// Obsidian e per un client Windows o Android che un giorno ci sarà. Scritta
// qui andrebbe riscritta in ognuno, e divergerebbe.
//
// Quindi il lavoro di questo file è piccolo e di proposito: chiede, e va
// dove il server dice.
//
// **Il caso che merita una pagina e non un salto.** Quando la cosa indicata
// non c'è più, il server risponde comunque con un ripiego — nota sparita
// apre il libro, libro sparito apre la biblioteca. Mandare lì direttamente
// sarebbe disorientante: si è cliccato un link a un passo preciso e si
// finisce su una scheda, senza sapere perché. Quindi si spiega, e si lascia
// aprire il ripiego con un clic.

import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useLingua } from '@/lib/i18n'
import type { components } from '@/api/schema'

type Risolto = components['schemas']['LinkRisolto']

// I motivi che il server può dare, e i ripieghi che può proporre. Sono
// elenchi chiusi e scritti qui di proposito: `t()` non ha un ripiego, quindi
// una chiave che manca si vedrebbe come il suo nome dentro la pagina. Un
// motivo nuovo lato server, finché non ha la sua frase, cade su quella
// generica invece di stampare `link.broken.pippo`.
const MOTIVI = [
  'nota_sparita', 'libro_sparito', 'libro_ambiguo',
  'biblioteca_sparita', 'biblioteca_ambigua', 'indirizzo_senza_libro',
] as const
const RIPIEGHI = ['libro', 'biblioteca'] as const

function chiaveDelMotivo(motivo: string | null | undefined): string {
  return (MOTIVI as readonly string[]).includes(motivo ?? '')
    ? `link.broken.${motivo}`
    : 'link.broken.generico'
}

function chiaveDelRipiego(ripiego: string | null | undefined): string {
  return (RIPIEGHI as readonly string[]).includes(ripiego ?? '')
    ? `link.broken.apri.${ripiego}`
    : 'link.broken.apri.generico'
}

/** Il lettore è un'altra pagina HTML, non una rotta di questa applicazione:
 *  ci si va cambiando indirizzo, non navigando. */
function eIlLettore(dove: string): boolean {
  return dove.startsWith('/reader.html') || dove.startsWith('/pdf-reader.html')
}

export function ApriIndirizzo() {
  const { t } = useLingua()
  const location = useLocation()
  const navigate = useNavigate()
  const [esito, setEsito] = useState<{ stato: 'chiedo' } | { stato: 'rotto'; risolto: Risolto } | { stato: 'nostro-no' }>(
    { stato: 'chiedo' },
  )

  // Solo il percorso, senza l'eventuale query: un indirizzo condivisibile non
  // ne ha una, e quello che qualcuno ci attacca (un `?utm=` incollato
  // insieme) non è parte dell'identità. Il server lo butterebbe comunque.
  const percorso = location.pathname

  useEffect(() => {
    let annullato = false
    ;(async () => {
      const { data, error } = await api.GET('/api/kolibre/link/risolvi', {
        params: { query: { percorso } },
      })
      if (annullato) return
      if (error || !data) {
        setEsito({ stato: 'nostro-no' })
        return
      }
      if (data.trovato && data.apri) {
        if (eIlLettore(data.apri)) window.location.assign(data.apri)
        // `replace`: l'indirizzo condivisibile non deve restare nella
        // cronologia, altrimenti il tasto «indietro» ci torna sopra e questa
        // pagina rimanda avanti di nuovo, in un andirivieni senza uscita.
        else navigate(data.apri, { replace: true })
        return
      }
      setEsito({ stato: 'rotto', risolto: data })
    })()
    return () => {
      annullato = true
    }
  }, [percorso, navigate])

  if (esito.stato === 'chiedo') {
    return <p className="text-muted-foreground">{t('link.resolving')}</p>
  }

  if (esito.stato === 'nostro-no') {
    return (
      <div className="flex flex-col items-start gap-2">
        <h2 className="text-lg font-medium">{t('link.notOurs.title')}</h2>
        <p className="text-sm text-muted-foreground">{t('link.notOurs.hint')}</p>
        <p className="font-mono text-[13px] text-muted-foreground">{percorso}</p>
      </div>
    )
  }

  const { risolto } = esito
  return (
    <div className="flex flex-col items-start gap-3">
      <h2 className="text-lg font-medium">{t('link.broken.title')}</h2>
      <p className="text-sm text-muted-foreground">{t(chiaveDelMotivo(risolto.motivo))}</p>
      <p className="font-mono text-[13px] text-muted-foreground">{percorso}</p>
      {risolto.apri && risolto.ripiego && (
        <Button
          onClick={() => {
            const dove = risolto.apri as string
            if (eIlLettore(dove)) window.location.assign(dove)
            else navigate(dove, { replace: true })
          }}
        >
          {t(chiaveDelRipiego(risolto.ripiego))}
        </Button>
      )}
    </div>
  )
}
