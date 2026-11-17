// La qualità dei libri di una biblioteca, in tabella.
//
// Risponde a due domande diverse, e le tiene separate perché lo sono (vedi
// backend/app/services/qualita_epub.py): «questo libro è fatto bene?» e «il
// lettore lo apre così com'è?». Un libro sano impacchettato male prende un
// voto alto e non si apre; mostrarlo come scadente nasconderebbe l'unica
// cosa da fare, che è reimpacchettarlo.
//
// Il numero sulla testa della sezione conta i libri che CHIEDONO qualcosa —
// quelli che non si aprono e quelli che non si è potuto misurare — non i
// libri con un voto basso: un voto basso è un fatto, non un lavoro in
// sospeso, e una pagina di cose da fare che elenca mille libri mediocri non
// la guarda più nessuno.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowDown, ArrowUp, Loader2, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { DettaglioQualita, PunteggioQualita, nomeDimensione } from '@/components/Qualita'
import {
  useAnalizzaQualita,
  useQualitaDettaglio,
  useQualitaLibri,
  useQualitaStato,
} from '@/lib/qualitaActions'
import { useLingua } from '@/lib/i18n'

// Il prefisso con cui si chiede al server di ordinare per una dimensione.
// Le dimensioni NON si elencano qui: si ricavano dai dati (la misura può
// aggiungerne, e porta la sua versione), quindi la chiave si compone col nome
// che arriva. Il server la risolve allo stesso modo — vedi
// `api/qualita.py::_valore_da_ordinare`.
const PREFISSO_DIMENSIONE = 'dimensioni.'

/**
 * Un'intestazione che ordina, con la freccia del verso.
 *
 * **La freccia non è un ornamento.** Fino al 17/11/2026 ordinavano tre
 * colonne su otto e nessuna diceva di essere quella attiva: con tre si
 * indovinava, con otto no — si clicca e non si sa che cosa si è cliccato.
 *
 * Non si riusa `SortableTableHead` perché quello disegna il `<TableHead>` del
 * componente `Table`, e questa tabella è un `<table>` suo: infilarcelo
 * vorrebbe dire rifare il markup della tabella per una freccia.
 */
function Intestazione({
  etichetta,
  chiave,
  ordina,
  verso,
  onClick,
  className,
}: {
  etichetta: string
  chiave: string
  ordina: string
  verso: string
  onClick: (chiave: string) => void
  className?: string
}) {
  const attiva = ordina === chiave
  return (
    <th className={`py-1 ${className ?? 'text-left'}`}>
      <button
        type="button"
        onClick={() => onClick(chiave)}
        className="inline-flex items-center gap-1 hover:underline"
      >
        {etichetta}
        {attiva &&
          (verso === 'asc' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
      </button>
    </th>
  )
}

/** Quanti libri chiedono qualcosa. `null` finché non si sa. */
export function useQuantiLibriDaGuardare(libraryFolder: string | undefined): number | null {
  const { data } = useQualitaStato(libraryFolder)
  if (!data || !data.enabled) return null
  return data.non_pronti + data.errori
}

const FILTRI = [
  ['tutti', 'interventions.qualita.filterAll'],
  ['non_pronti', 'interventions.qualita.filterNotReady'],
  ['errori', 'interventions.qualita.filterErrors'],
] as const

export function QualitaPanel({ libraryFolder }: { libraryFolder: string | undefined }) {
  const { t } = useLingua()
  const navigate = useNavigate()
  const [solo, setSolo] = useState<string>('tutti')
  const [ordina, setOrdina] = useState<string>('punteggio')
  const [verso, setVerso] = useState<string>('asc')
  const [aperto, setAperto] = useState<number | null>(null)

  const { data: stato } = useQualitaStato(libraryFolder)
  const { data, isLoading } = useQualitaLibri(libraryFolder, { ordina, verso, solo })
  const dettaglio = useQualitaDettaglio(libraryFolder, aperto)
  const analizza = useAnalizzaQualita(libraryFolder)

  if (stato && !stato.enabled) {
    return <p className="p-3 text-[12.5px] text-muted-foreground">{t('interventions.qualita.disabled')}</p>
  }

  const libri = data?.libri ?? []
  // Le colonne delle dimensioni si ricavano dai dati, non da un elenco
  // scritto qui: la misura cambia nel tempo e porta la sua versione.
  const dimensioni = Array.from(
    new Set(libri.flatMap((l) => Object.keys((l.dimensioni ?? {}) as Record<string, number>))),
  )

  function cambiaOrdine(chiave: string) {
    if (ordina === chiave) {
      setVerso((v) => (v === 'asc' ? 'desc' : 'asc'))
      return
    }
    setOrdina(chiave)
    // **Il verso di partenza dice che cosa si sta cercando.** Su un
    // punteggio o una dimensione si cercano i libri che chiedono qualcosa,
    // quindi il più basso per primo; sui difetti si cerca chi ne ha di più,
    // quindi il contrario; su un testo, l'ordine alfabetico. Partire sempre
    // da «crescente» vorrebbe dire che la colonna dei difetti si apre su
    // mille libri con zero difetti — un clic che sembra non aver fatto
    // niente.
    setVerso(chiave === 'difetti' ? 'desc' : 'asc')
  }

  return (
    <div className="flex flex-col gap-2 p-3">
      <div className="flex flex-wrap items-center gap-2">
        {FILTRI.map(([chiave, etichetta]) => (
          <button
            key={chiave}
            type="button"
            onClick={() => setSolo(chiave)}
            className={`rounded border px-2 py-0.5 text-[11.5px] ${
              solo === chiave ? 'border-foreground bg-foreground text-background' : 'border-border text-muted-foreground'
            }`}
          >
            {t(etichetta)}
          </button>
        ))}
        <span className="flex-1" />
        {stato?.in_corso && stato.progresso && (
          <span className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            {t('interventions.qualita.running', {
              fatti: stato.progresso.fatti,
              totale: stato.progresso.totale,
            })}
          </span>
        )}
        {!!stato?.da_rifare && !stato.in_corso && (
          <span className="text-[11.5px] text-muted-foreground">
            {t('interventions.qualita.queued', { n: stato.da_rifare })}
          </span>
        )}
        <Button
          variant="outline"
          size="sm"
          disabled={analizza.isPending || !libraryFolder}
          onClick={() => analizza.mutate(true)}
          title={t('interventions.qualita.analyzeTitle')}
        >
          {analizza.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          {t('interventions.qualita.analyzeButton')}
        </Button>
      </div>

      {isLoading ? (
        <p className="text-[12.5px] text-muted-foreground">
          <Loader2 className="mr-1 inline size-3 animate-spin" />
        </p>
      ) : libri.length === 0 ? (
        <p className="text-[12.5px] text-muted-foreground">{t('interventions.qualita.empty')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr className="border-b border-border">
                <Intestazione
                  etichetta={t('interventions.qualita.columnTitle')}
                  chiave="titolo" ordina={ordina} verso={verso} onClick={cambiaOrdine}
                />
                <Intestazione
                  etichetta={t('interventions.qualita.columnAuthor')}
                  chiave="autore" ordina={ordina} verso={verso} onClick={cambiaOrdine}
                />
                <Intestazione
                  etichetta={t('interventions.qualita.columnScore')}
                  chiave="punteggio" ordina={ordina} verso={verso} onClick={cambiaOrdine}
                  className="text-right"
                />
                {dimensioni.map((d) => (
                  <Intestazione
                    key={d}
                    etichetta={nomeDimensione(t, d)}
                    chiave={`${PREFISSO_DIMENSIONE}${d}`}
                    ordina={ordina} verso={verso} onClick={cambiaOrdine}
                    className="text-right font-normal normal-case"
                  />
                ))}
                <Intestazione
                  etichetta={t('interventions.qualita.columnDefects')}
                  chiave="difetti" ordina={ordina} verso={verso} onClick={cambiaOrdine}
                  className="text-right"
                />
              </tr>
            </thead>
            <tbody>
              {libri.map((l) => {
                const dim = (l.dimensioni ?? {}) as Record<string, number>
                const apertoQui = aperto === l.id
                return (
                  <tr
                    key={l.id}
                    className="cursor-pointer border-b border-border/50 align-top hover:bg-muted/40"
                    onClick={() => setAperto(apertoQui ? null : l.id)}
                  >
                    <td className="max-w-[22rem] py-1">
                      {/* Il titolo porta alla scheda del libro, il resto
                          della riga apre il dettaglio qui sotto. Due gesti
                          diversi sulla stessa riga perché servono a due
                          momenti diversi: «che cosa gli manca» si guarda
                          senza perdere la tabella, «questo libro cos'è» no.
                          Lo `stopPropagation` è quello che tiene separate le
                          due cose: senza, un clic sul titolo aprirebbe anche
                          il dettaglio, che resterebbe aperto al ritorno.
                          La biblioteca viaggia nello `state`, come negli
                          altri nove posti che navigano a un libro — vedi il
                          commento in BookDetailPage.tsx. */}
                      <button
                        type="button"
                        className="block max-w-full truncate text-left hover:underline"
                        title={t('interventions.qualita.openBook')}
                        onClick={(e) => {
                          e.stopPropagation()
                          navigate(`/libri/${l.id}`, { state: { libraryFolder } })
                        }}
                      >
                        {l.title}
                      </button>
                      {apertoQui && (
                        <div className="my-2 rounded border border-border bg-muted/30 p-2">
                          {dettaglio.isLoading ? (
                            <Loader2 className="size-3 animate-spin" />
                          ) : dettaglio.data ? (
                            <DettaglioQualita risultato={dettaglio.data} />
                          ) : (
                            <span className="text-muted-foreground">
                              {l.errore ?? t('qualita.erroreAnalisi')}
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="max-w-[14rem] truncate py-1 text-muted-foreground">{l.author}</td>
                    <td className="py-1 text-right">
                      <PunteggioQualita punteggio={l.punteggio} pronto={l.pronto} />
                    </td>
                    {dimensioni.map((d) => (
                      <td key={d} className="py-1 text-right tabular-nums text-muted-foreground">
                        {dim[d] ?? '—'}
                      </td>
                    ))}
                    <td className="py-1 text-right tabular-nums text-muted-foreground">{l.difetti}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
