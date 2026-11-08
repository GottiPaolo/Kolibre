// «Copia il link»: un bottone solo, per libri, autori, note e biblioteche.
//
// **Perché è un componente e non tre bottoni.** Il gesto è identico in tre
// posti (la scheda di un libro, quella di un autore, una nota) e ha quattro
// pezzi che è facile scrivere in modo diverso ogni volta: chiedere
// l'indirizzo al server, copiarlo con il ripiego che serve su una rete di
// casa in http, confermare che è andata, e dire che cosa è andato storto
// quando non si può fare. Scritti tre volte diventano tre comportamenti
// diversi alla prima modifica — è lo stesso difetto che altrove ha prodotto
// la stessa regola in tre punti del frontend.
//
// **Perché l'indirizzo lo chiede al server e non lo compone qui.** È la
// regola di casa: comporre quell'indirizzo vuol dire sapere l'uuid del
// libro, quanti caratteri bastano perché sia univoco, come un titolo diventa
// uno slug e con quale nome questa installazione si raggiunge da fuori.
// Sono tutte cose del server, e un secondo client (il plugin Obsidian, un
// client Windows) deve ottenere lo stesso indirizzo senza riscriverle.
//
// **Perché chiede al clic e non all'apertura della pagina.** Un bottone che
// quasi nessuno premerà non deve costare un giro di rete a ogni scheda
// aperta.

import { useState } from 'react'
import { Check, Share2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { copiaNegliAppunti } from '@/lib/appunti'
import { useLingua } from '@/lib/i18n'

export type SorgenteDelLink =
  | { tipo: 'libro'; id: number; library?: string }
  | { tipo: 'nota'; id: number }
  | { tipo: 'autore'; nome: string }
  | { tipo: 'biblioteca'; library: string }

type Risposta = { percorso: string; base?: string | null; indirizzo?: string | null }

async function chiediIlLink(sorgente: SorgenteDelLink): Promise<{ dato?: Risposta; stato?: number }> {
  // Quattro indirizzi distinti invece di uno con un parametro `tipo`: il
  // client tipizzato vuole percorsi letterali, e quattro chiamate chiare si
  // leggono meglio di una condizionale che costruisce una stringa.
  if (sorgente.tipo === 'libro') {
    const { data, response } = await api.GET('/api/kolibre/link/di-un-libro', {
      params: { query: { id: sorgente.id, library: sorgente.library } },
    })
    return { dato: data as Risposta | undefined, stato: response?.status }
  }
  if (sorgente.tipo === 'nota') {
    const { data, response } = await api.GET('/api/kolibre/link/di-una-nota', {
      params: { query: { id: sorgente.id } },
    })
    return { dato: data as Risposta | undefined, stato: response?.status }
  }
  if (sorgente.tipo === 'autore') {
    const { data, response } = await api.GET('/api/kolibre/link/di-un-autore', {
      params: { query: { nome: sorgente.nome } },
    })
    return { dato: data as Risposta | undefined, stato: response?.status }
  }
  const { data, response } = await api.GET('/api/kolibre/link/di-una-biblioteca', {
    params: { query: { library: sorgente.library } },
  })
  return { dato: data as Risposta | undefined, stato: response?.status }
}

export function BottoneCopiaLink({
  sorgente,
  variant = 'outline',
  size = 'sm',
  soloIcona = false,
  className,
}: {
  sorgente: SorgenteDelLink
  variant?: 'default' | 'outline' | 'ghost'
  size?: 'default' | 'sm' | 'icon'
  soloIcona?: boolean
  className?: string
}) {
  const { t } = useLingua()
  const [stato, setStato] = useState<'fermo' | 'chiedo' | 'fatto' | 'errore'>('fermo')
  const [perche, setPerche] = useState('')

  async function copia() {
    setStato('chiedo')
    setPerche('')
    const { dato, stato: codice } = await chiediIlLink(sorgente)
    if (!dato) {
      setStato('errore')
      // 409 vuol dire «esiste ma non ha un indirizzo»: una nota di un libro
      // non ancora accoppiato. È una spiegazione diversa da «non trovato», e
      // la differenza serve — una si risolve accoppiando il libro.
      setPerche(codice === 409 ? t('link.copy.noBook') : t('link.copy.notFound'))
      return
    }
    // `indirizzo` manca solo se il server non ha potuto ricavare con quale
    // nome lo si raggiunge: allora si copia il percorso, che è comunque
    // l'unica parte che vale su ogni installazione.
    const daCopiare = dato.indirizzo || dato.percorso
    if (await copiaNegliAppunti(daCopiare)) {
      setStato('fatto')
      setTimeout(() => setStato('fermo'), 2000)
    } else {
      setStato('errore')
      setPerche(t('link.copy.failed'))
    }
  }

  const etichetta =
    stato === 'fatto' ? t('link.copy.done') : stato === 'chiedo' ? t('link.copy.working') : t('link.copy.label')

  return (
    <span className="inline-flex items-center gap-2">
      <Button
        variant={variant}
        size={soloIcona ? 'icon' : size}
        className={className}
        onClick={copia}
        disabled={stato === 'chiedo'}
        title={t('link.copy.hint')}
        aria-label={t('link.copy.label')}
      >
        {stato === 'fatto' ? <Check /> : <Share2 />}
        {!soloIcona && etichetta}
      </Button>
      {stato === 'errore' && perche && (
        <span className="text-[13px] text-destructive">{perche}</span>
      )}
    </span>
  )
}
