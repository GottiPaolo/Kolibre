// L'elenco dei libri e come stanno nel vault: una tabella, cercabile.
//
// **Perché una tabella e non un elenco che si apre.** Con settantanove libri
// annotati la domanda che si fa davvero è «come sta *questo* libro» oppure
// «quali hanno qualcosa da fare»: la prima si risolve cercando, la seconda
// ordinando. Elenchi espandibili non rispondono a nessuna delle due — fanno
// scorrere, aprire, richiudere, e nascondono i conteggi dietro un clic.
//
// Si apre con **tutti** i libri, ordinati per urgenza: niente è nascosto, e
// la ricerca lavora su tutto. Una tabella che parte filtrata è una tabella
// che può non trovare un libro che c'è.
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { EyeOff, RefreshCw, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { SortableTableHead } from '@/components/ui/sortable-table-head'
import { useLingua, type Valori } from '@/lib/i18n'
import { foldAccents } from '@/lib/foldAccents'
import { indirizzoDelLibro, STATI, type LibroNegliAppunti, type StatoDiUnLibro } from '@/lib/appuntiActions'
import { COLORE_DELLO_STATO } from './coloriDegliStati'
import { ConfermaIlRifacimento } from './ConfermaIlRifacimento'

type Colonna = 'titolo' | 'autore' | 'stato' | 'note' | 'dafare'

export function TabellaDeiLibri({
  libri,
  inCorso,
  onBlocco,
  onRifacimento,
}: {
  libri: LibroNegliAppunti[]
  inCorso: boolean
  onBlocco: (libro: LibroNegliAppunti, bloccato: boolean) => void
  onRifacimento: (libro: LibroNegliAppunti, annulla: boolean) => void
}) {
  const { t } = useLingua()
  const navigate = useNavigate()
  const [cerca, setCerca] = useState('')
  const [statiScelti, setStatiScelti] = useState<Set<StatoDiUnLibro>>(new Set())
  const [ordine, setOrdine] = useState<{ colonna: Colonna; crescente: boolean }>({
    colonna: 'stato',
    crescente: true,
  })
  // Il libro per cui si sta chiedendo conferma del rifacimento: e' l'unica
  // azione di questa pagina che butta via qualcosa di tuo.
  const [daRifare, setDaRifare] = useState<LibroNegliAppunti | null>(null)

  const perStato = useMemo(() => {
    const conti = new Map<string, number>()
    for (const l of libri) conti.set(l.stato, (conti.get(l.stato) ?? 0) + 1)
    return conti
  }, [libri])

  const righe = useMemo(() => {
    // La ricerca ignora accenti e maiuscole, come quella della Libreria:
    // cercare «miserables» deve trovare «Les Misérables».
    const ago = foldAccents(cerca.trim())
    const filtrate = libri.filter((l) => {
      if (statiScelti.size > 0 && !statiScelti.has(l.stato as StatoDiUnLibro)) return false
      if (!ago) return true
      return foldAccents(`${l.titolo ?? ''} ${l.autore ?? ''}`).includes(ago)
    })
    const daFare = (l: LibroNegliAppunti) => l.da_decidere + l.mai_consegnate + l.da_portare
    const valore = (l: LibroNegliAppunti): string | number => {
      switch (ordine.colonna) {
        case 'titolo': return foldAccents(l.titolo ?? '')
        case 'autore': return foldAccents(l.autore ?? '')
        case 'note': return l.note_totali
        case 'dafare': return daFare(l)
        // Per stato vuol dire **per urgenza**, non in ordine alfabetico:
        // l'ordine è quello che il server dichiara in ORDINE_DEGLI_STATI.
        case 'stato': return STATI.indexOf(l.stato as StatoDiUnLibro)
      }
    }
    return [...filtrate].sort((a, b) => {
      const va = valore(a)
      const vb = valore(b)
      const verso = ordine.crescente ? 1 : -1
      if (va === vb) return foldAccents(a.titolo ?? '').localeCompare(foldAccents(b.titolo ?? ''))
      return (va > vb ? 1 : -1) * verso
    })
  }, [libri, cerca, statiScelti, ordine])

  const cambiaOrdine = (colonna: Colonna) =>
    setOrdine((o) => ({ colonna, crescente: o.colonna === colonna ? !o.crescente : true }))

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            id="appunti-cerca"
            value={cerca}
            onChange={(e) => setCerca(e.target.value)}
            placeholder={t('appunti.tabella.cerca')}
            className="h-8 w-56 rounded-md border border-border bg-background pl-7 pr-2 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
        {/* I filtri mostrano i conteggi: è il riassunto, e insieme il modo
            di restringere. Niente filtro attivo = tutti. */}
        {STATI.filter((s) => (perStato.get(s) ?? 0) > 0).map((s) => {
          const attivo = statiScelti.has(s)
          return (
            <button
              key={s}
              type="button"
              onClick={() =>
                setStatiScelti((v) => {
                  const nuovo = new Set(v)
                  if (nuovo.has(s)) nuovo.delete(s)
                  else nuovo.add(s)
                  return nuovo
                })
              }
              className={
                'rounded-full border px-2 py-0.5 text-[12px] transition-colors ' +
                (attivo ? COLORE_DELLO_STATO[s] : 'border-border text-muted-foreground hover:text-foreground')
              }
            >
              {t(`appunti.stato.${s}`)} <span className="opacity-70">{perStato.get(s)}</span>
            </button>
          )
        })}
        <span className="ml-auto text-[12px] text-muted-foreground">
          {t('appunti.tabella.conto', { mostrati: righe.length, totali: libri.length })}
        </span>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <Table className="min-w-[620px] text-[13px]">
          <TableHeader>
            <TableRow>
              <SortableTableHead label={t('appunti.tabella.titolo')} sortKey="titolo" active={ordine.colonna === 'titolo'} order={ordine.crescente ? 'asc' : 'desc'} onClick={cambiaOrdine} />
              <SortableTableHead label={t('appunti.tabella.autore')} sortKey="autore" active={ordine.colonna === 'autore'} order={ordine.crescente ? 'asc' : 'desc'} onClick={cambiaOrdine} />
              <SortableTableHead label={t('appunti.tabella.stato')} sortKey="stato" active={ordine.colonna === 'stato'} order={ordine.crescente ? 'asc' : 'desc'} onClick={cambiaOrdine} />
              <SortableTableHead label={t('appunti.tabella.note')} sortKey="note" active={ordine.colonna === 'note'} order={ordine.crescente ? 'asc' : 'desc'} onClick={cambiaOrdine} className="text-right" />
              <SortableTableHead label={t('appunti.tabella.daFare')} sortKey="dafare" active={ordine.colonna === 'dafare'} order={ordine.crescente ? 'asc' : 'desc'} onClick={cambiaOrdine} className="text-right" />
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {righe.map((l) => {
              const accoppiato = l.calibre_book_id != null && !!l.library
              return (
                <TableRow key={`${l.library}/${l.calibre_book_id}/${l.titolo}`}>
                  <TableCell>
                    <button
                      type="button"
                      className="text-left font-medium hover:text-primary hover:underline"
                      onClick={() => navigate(indirizzoDelLibro(l))}
                    >
                      {l.titolo || t('appunti.riga.senzaTitolo')}
                    </button>
                    {l.percorso && (
                      <div className="truncate text-[11.5px] text-muted-foreground" title={l.percorso}>
                        {l.percorso}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{l.autore}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={COLORE_DELLO_STATO[l.stato] ?? ''}>
                      {t(`appunti.stato.${l.stato}`)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {l.nel_vault}/{l.note_totali}
                  </TableCell>
                  {/* Il numero dice QUANTO, il titolo dice di che cosa: le
                      tre voci che lo compongono sono cose diverse, e una
                      colonna in piu' per ognuna renderebbe la tabella
                      illeggibile per un dettaglio che si guarda di rado. */}
                  <TableCell className="text-right tabular-nums" title={scomposizione(l, t)}>
                    {l.da_decidere + l.mai_consegnate + l.da_portare || ''}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right">
                    {accoppiato && (
                      <>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={inCorso}
                          title={l.da_rifare ? t('appunti.azione.annullaRifacimento') : t('appunti.azione.rifalloSpiega')}
                          onClick={() => (l.da_rifare ? onRifacimento(l, true) : setDaRifare(l))}
                        >
                          <RefreshCw className={'size-3.5 ' + (l.da_rifare ? 'text-primary' : '')} />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={inCorso}
                          title={l.stato === 'bloccato' ? t('appunti.azione.riprendi') : t('appunti.azione.nonMandarloSpiega')}
                          onClick={() => onBlocco(l, l.stato !== 'bloccato')}
                        >
                          <EyeOff className={'size-3.5 ' + (l.stato === 'bloccato' ? 'text-primary' : '')} />
                        </Button>
                      </>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
        {righe.length === 0 && (
          <p className="px-2 py-3 text-[13px] text-muted-foreground">{t('appunti.tabella.nessuno')}</p>
        )}
      </div>

      <ConfermaIlRifacimento
        titoloDelLibro={daRifare?.titolo}
        aperta={daRifare !== null}
        onChiudi={() => setDaRifare(null)}
        onConferma={() => daRifare && onRifacimento(daRifare, false)}
      />
    </div>
  )
}

/** Di cosa e' fatto il numero nella colonna «Da fare», piu' quello che la
 *  tabella non conta come lavoro ma vale la pena sapere. */
function scomposizione(l: LibroNegliAppunti, t: (chiave: string, valori?: Valori) => string): string {
  const voci: string[] = []
  if (l.da_decidere > 0) voci.push(t('appunti.riga.daDecidere', { count: l.da_decidere }))
  if (l.mai_consegnate > 0) voci.push(t('appunti.riga.mai', { count: l.mai_consegnate }))
  if (l.da_portare > 0) voci.push(t('appunti.riga.daPortare', { count: l.da_portare }))
  if (l.togliate_da_te > 0) voci.push(t('appunti.riga.togliate', { count: l.togliate_da_te }))
  if (l.modificate_da_te > 0) voci.push(t('appunti.riga.modificateDaTe', { count: l.modificate_da_te }))
  return voci.join('\n')
}

