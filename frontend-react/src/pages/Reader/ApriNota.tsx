// Apre il lettore partendo da `?nota=<id>` e basta.
//
// **Perche' un link porta l'id e non la posizione.** Non e' un risparmio di
// caratteri: e' quello che fa invecchiare bene il link. Un CFI e' una
// coordinata congelata nel momento in cui lo copi — se il libro viene
// riscaricato, riconvertito o sostituito con un'altra edizione, quella
// coordinata non risolve piu' e il link porta all'inizio del libro. Peggio: se
// l'ancora di quella nota viene RIPARATA piu' tardi (succede: vedi
// `copreIlTesto` in ReaderPage.tsx), un link che porta il vecchio CFI resta
// fermo sull'errore mentre la nota, nel database, e' gia' a posto.
//
// Portando l'identita' invece della coordinata, ogni link gia' scritto in un
// appunto punta sempre a dove la nota sta ADESSO.
//
// **Dove sta questo passaggio, e perche' li'.** Dentro `AuthGate` e prima di
// `ReaderPage`: un link del genere nasce per essere aperto da un browser che
// magari non ha una sessione — un altro computer, una finestra privata, o
// semplicemente sette giorni dopo. L'ordine e' quindi: si verifica l'accesso,
// si chiede di accedere se manca, e solo dopo si va a cercare dov'e' la nota.
//
// **Perche' si riscrive la query invece di passare i dati per props.**
// `ReaderPage` legge i suoi parametri da `window.location.search`, una volta
// sola, in modo sincrono. Riscrivere l'indirizzo con `replaceState` prima di
// montarlo significa non toccare `ReaderPage`, e in piu' un ricaricamento
// della pagina continua a funzionare. L'indirizzo breve resta quello salvato
// nell'appunto: qui si espande solo quello visibile dopo l'apertura.

import { useEffect, useState, type ReactNode } from 'react'
import { api } from '@/lib/api'
import { useLingua } from '@/lib/i18n'

interface NotaRisolta {
  calibre_book_id?: number | null
  library?: string | null
  book_title?: string | null
  book_formats?: string[] | null
  cfi_start?: string | null
  text?: string | null
}

/** Il formato da aprire: EPUB se c'e', altrimenti PDF, altrimenti si prova EPUB. */
function formatoDa(formati: string[] | null | undefined): string {
  const f = (formati ?? []).map((x) => x.toUpperCase())
  if (f.includes('EPUB')) return 'EPUB'
  if (f.includes('PDF')) return 'PDF'
  return 'EPUB'
}

export function ApriNota({ children }: { children: ReactNode }) {
  const { t } = useLingua()
  const params = new URLSearchParams(window.location.search)
  const idNota = params.get('nota')
  // Un indirizzo che ha gia' il libro non ha bisogno di risolvere niente:
  // e' il caso normale di tutti i link interni dell'applicazione.
  const daRisolvere = !!idNota && !params.get('bookId')

  const [stato, setStato] = useState<'risolvo' | 'pronto' | 'errore'>(daRisolvere ? 'risolvo' : 'pronto')

  useEffect(() => {
    if (!daRisolvere) return
    let annullato = false
    ;(async () => {
      try {
        const { data, error } = await api.GET('/api/kolibre/annotations/{id}', {
          params: { path: { id: Number(idNota) } },
        })
        if (annullato) return
        const nota = (data ?? null) as NotaRisolta | null
        if (error || !nota?.calibre_book_id) {
          setStato('errore')
          return
        }

        const q = new URLSearchParams({
          bookId: String(nota.calibre_book_id),
          library: nota.library || 'default',
          format: formatoDa(nota.book_formats),
          notaId: String(idNota),
        })
        if (nota.book_title) q.set('title', nota.book_title)
        if (nota.cfi_start) q.set('cfi', nota.cfi_start)
        // Il testo va passato comunque, anche quando il CFI c'e': e' il
        // ripiego che il lettore usa gia' quando l'ancora non risolve o copre
        // solo un pezzo del brano.
        const testo = (nota.text || '').replace(/\s+/g, ' ').trim()
        if (testo.length >= 12) q.set('notaTesto', testo)

        window.history.replaceState(null, '', `${window.location.pathname}?${q.toString()}`)
        setStato('pronto')
      } catch {
        if (!annullato) setStato('errore')
      }
    })()
    return () => { annullato = true }
  }, [daRisolvere, idNota])

  if (stato === 'risolvo') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
        {t('reader.openNote.resolving')}
      </div>
    )
  }

  if (stato === 'errore') {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-2 bg-background px-6 text-center">
        <div className="text-foreground">{t('reader.openNote.notFound')}</div>
        <div className="text-[13px] text-muted-foreground">{t('reader.openNote.notFoundHint')}</div>
      </div>
    )
  }

  return <>{children}</>
}
