// La qualità dell'EPUB nella scheda di un libro.
//
// **Da zero: che cos'è il punteggio di qualità.** Il server apre l'EPUB e lo
// misura: quanto è fatto bene l'indice, la struttura, le immagini, i metadati.
// Ne esce un numero da 0 a 100 e un elenco di difetti con un nome
// (`toc_scarno`, e così via). Serve a rispondere a «questo file è fatto bene?»
// — che è una domanda diversa da «il lettore lo apre?», e per questo il «non
// pronto» sta accanto al numero invece di abbassarlo.
//
// **Come si mostra qui, e perché così** (Paolo, 17/11/2026): **solo il numero,
// da 0 a 100, senza colori**. Il colore serve a scorrere una tabella di mille
// righe cercando i libri scadenti — in Interventi infatti resta. Qui c'è un
// libro solo: non c'è niente con cui confrontare quel numero, e un colore
// direbbe «questo è un brutto libro» a chi sta guardando la sua scheda.
//
// **E il dettaglio per parametro NON sta in vista**, sempre su sua richiesta:
// sta dietro una cosa chiusa, che si apre quando serve. La scheda di un libro
// risponde a «che libro è», non a «perché il suo punteggio è 72».
//
// **I tre esiti sono tre, non due.** Il server risponde 404 se quel libro non
// è mai stato analizzato e 409 se l'analisi è fallita. Trattarli uguale vuol
// dire che un file che non si apre sembra uno non ancora guardato — e il primo
// è l'unico dei due su cui c'è qualcosa da fare.
import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { DettaglioQualita, PunteggioQualita } from '@/components/Qualita'
import { useQualitaDiUnLibro } from '@/lib/qualitaActions'
import { useLingua } from '@/lib/i18n'

export function QualitaDelLibro({
  libraryFolder,
  bookId,
}: {
  libraryFolder: string | undefined
  bookId: number | null
}) {
  const { t } = useLingua()
  const [aperto, setAperto] = useState(false)
  const { data, isLoading } = useQualitaDiUnLibro(libraryFolder, bookId)

  // Finché non si sa, questa riga non c'è: un «—» che compare e poi diventa
  // un numero fa sfarfallare la scheda a ogni apertura.
  if (isLoading || !data) return null

  // **Mai analizzato: non si dice niente.** Non è un'informazione sul libro,
  // è un'informazione su di noi — e una riga «qualità: non disponibile» in
  // mezzo ai metadati sembra un dato mancante del libro.
  if (data.esito === 'mai') return null

  if (data.esito === 'fallita') {
    return (
      <>
        <dt className="text-muted-foreground">{t('library.detail.qualita')}</dt>
        <dd className="text-[var(--warning)]" title={data.motivo || undefined}>
          {t('library.detail.qualitaFallita')}
        </dd>
      </>
    )
  }

  const risultato = data.risultato
  return (
    <>
      <dt className="text-muted-foreground">{t('library.detail.qualita')}</dt>
      <dd>
        <div className="flex items-center gap-2">
          <PunteggioQualita punteggio={risultato.punteggio} pronto={risultato.pronto} senzaColore />
          <button
            type="button"
            onClick={() => setAperto((a) => !a)}
            className="inline-flex items-center gap-0.5 text-[11.5px] text-muted-foreground hover:text-foreground"
            aria-expanded={aperto}
          >
            {aperto ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
            {t(aperto ? 'library.detail.qualitaChiudi' : 'library.detail.qualitaApri')}
          </button>
        </div>
        {aperto && (
          <div className="mt-2 max-w-[32rem] rounded-md border border-border bg-muted/30 p-2.5">
            <DettaglioQualita risultato={risultato} />
          </div>
        )}
      </dd>
    </>
  )
}
