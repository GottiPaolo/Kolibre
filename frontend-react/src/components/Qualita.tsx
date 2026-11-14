// Come si mostra la qualità di un EPUB: il punteggio, e il perché.
//
// Due regole, e vengono dal modo in cui il server misura (vedi
// backend/app/services/qualita_epub.py):
//
// 1. **«Non pronto» non è un punteggio basso.** Sono due domande diverse: se
//    il lettore apre il file così com'è, e quanto è fatto bene dentro. Un
//    libro sano impacchettato male ha 99 e non si apre, e mostrarlo come un
//    libro scadente nasconderebbe l'unica cosa da fare — reimpacchettarlo. Il
//    numero resta quello che è, e il «non pronto» gli sta accanto.
// 2. **Niente elenchi di dimensioni o di difetti scritti qui.** La misura
//    cambia nel tempo e ogni risultato porta la sua versione: si disegna
//    quello che arriva. Una dimensione nuova compare da sola; una che non ha
//    traduzione si mostra col nome che manda il server, che è sempre meglio
//    di non mostrarla.
import { AlertTriangle, Bot, Check, Wrench } from 'lucide-react'
import { useLingua } from '@/lib/i18n'
import type { DifettoDiQualita, RisultatoQualita } from '@/lib/qualitaActions'

/** Il colore del punteggio. Tre fasce, scelte guardando la distribuzione
 *  vera su 1139 libri: mediana 85, un quarto sotto 70. */
function tono(punteggio: number): string {
  if (punteggio >= 85) return 'text-[var(--success,theme(colors.emerald.600))]'
  if (punteggio >= 60) return 'text-foreground'
  return 'text-destructive'
}

export function PunteggioQualita({
  punteggio,
  pronto,
  grande = false,
}: {
  punteggio: number | null | undefined
  pronto?: boolean | null
  grande?: boolean
}) {
  const { t } = useLingua()
  if (punteggio == null) {
    return <span className="text-muted-foreground">—</span>
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`${grande ? 'text-base' : 'text-[13px]'} font-semibold tabular-nums ${tono(punteggio)}`}>
        {punteggio}
      </span>
      {pronto === false && (
        <span
          className="inline-flex items-center gap-1 rounded border border-[var(--warning)] px-1 py-px text-[10.5px] font-medium text-[var(--warning)]"
          title={t('qualita.nonProntoTitle')}
        >
          <AlertTriangle className="size-3" />
          {t('qualita.nonPronto')}
        </span>
      )}
    </span>
  )
}

/** Il nome di una dimensione, tradotto se lo conosciamo. */
export function nomeDimensione(t: (k: string) => string, chiave: string): string {
  const tradotto = t(`qualita.dimensione.${chiave}`)
  return tradotto === `qualita.dimensione.${chiave}` ? chiave : tradotto
}

function BarraDimensione({ chiave, valore }: { chiave: string; valore: number }) {
  const { t } = useLingua()
  return (
    <div className="flex items-center gap-2">
      <span className="w-28 shrink-0 text-[11.5px] text-muted-foreground">{nomeDimensione(t, chiave)}</span>
      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <span
          className="block h-full rounded-full bg-foreground/70"
          style={{ width: `${Math.max(0, Math.min(100, valore))}%` }}
        />
      </span>
      <span className="w-8 shrink-0 text-right text-[11.5px] tabular-nums text-muted-foreground">{valore}</span>
    </div>
  )
}

function Difetto({ difetto }: { difetto: DifettoDiQualita }) {
  const { t } = useLingua()
  // Chi lo sistema: è l'informazione che decide cosa farne, più della
  // gravità. «auto» uno script, «ia» serve leggere il testo, «no» nessuno.
  const Icona = difetto.sistemabile === 'auto' ? Wrench : difetto.sistemabile === 'ia' ? Bot : Check
  const chiaveNome = `qualita.difetto.${difetto.codice}`
  const nome = t(chiaveNome)
  return (
    <li className="flex items-start gap-1.5">
      <Icona className={`mt-0.5 size-3 shrink-0 ${difetto.blocca ? 'text-destructive' : 'text-muted-foreground'}`} />
      <span>
        <span className={difetto.blocca ? 'font-medium text-destructive' : 'font-medium text-foreground'}>
          {nome === chiaveNome ? difetto.codice : nome}
        </span>
        {difetto.testo && <span className="text-muted-foreground"> — {difetto.testo}</span>}
        {difetto.dove && difetto.dove.length > 0 && (
          <span className="text-muted-foreground/80"> ({difetto.dove.slice(0, 3).join(', ')}
            {difetto.dove.length > 3 ? ' …' : ''})</span>
        )}
      </span>
    </li>
  )
}

export function DettaglioQualita({ risultato }: { risultato: RisultatoQualita | undefined }) {
  const { t } = useLingua()
  if (!risultato) return null
  const dimensioni = Object.entries(risultato.dimensioni ?? {})
  const difetti = risultato.difetti ?? []
  return (
    <div className="flex flex-col gap-2.5 text-[12px]">
      {dimensioni.length > 0 && (
        <div className="flex flex-col gap-1">
          {dimensioni.map(([chiave, valore]) => (
            <BarraDimensione key={chiave} chiave={chiave} valore={Number(valore)} />
          ))}
        </div>
      )}
      {difetti.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {difetti.map((d) => (
            <Difetto key={d.codice} difetto={d} />
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground">{t('qualita.nessunDifetto')}</p>
      )}
      {risultato.versione && (
        <p className="text-[10.5px] text-muted-foreground/70">{t('qualita.versione', { v: risultato.versione })}</p>
      )}
    </div>
  )
}
