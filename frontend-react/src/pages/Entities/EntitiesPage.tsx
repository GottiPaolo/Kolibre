import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Check, Download, ExternalLink, Globe, Loader2, Merge, Pencil, Search, Trash2, Unlink, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { SortableTableHead } from '@/components/ui/sortable-table-head'
import { sortByCriteria, type Criterio } from '@/lib/tableSort'
import { useRowSelection } from '@/lib/useRowSelection'
import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { useLibraries } from '@/lib/queries'
import { api } from '@/lib/api'
import { startScrapeMissingAuthors } from '@/lib/authorActions'
import { messaggioErrore } from '@/lib/messaggiErrore'
import { toast } from '@/lib/toast'
import { cn } from '@/lib/utils'
import { numero, useLingua, type Valori } from '@/lib/i18n'

// Le entità della biblioteca: autori, serie, tag, editori.
//
// Una pagina a sé e non una sezione di Interventi o una scheda di Operazioni
// di massa, e la ragione è questa: le entità non sono né una decisione in
// sospeso né un ricalcolo, sono un oggetto da curare, e sono quattro con le
// stesse azioni.
//
// Tre cose imparate dal primo giro, il 28/09/2026:
//
//  1. **La destinazione si sceglie.** Prima si poteva unire solo verso il
//     nome proposto, e il nome proposto era "quello con più libri" — che sui
//     casi veri sbagliava: «Gladwell, Malcolm ← Malcolm Gladwell», dove la
//     grafia giusta è la seconda. Ora ogni grafia del gruppo è cliccabile, e
//     il suggerimento guarda Wikipedia invece dei numeri.
//  2. **L'elenco serve a modificare**, non a guardare: da lì si rinomina.
//  3. **Tutte le biblioteche insieme**, perché il disordine dei nomi non si
//     ferma al loro confine — ed è lì che uniformare serve davvero.

// Gli `id` sono identificatori di rotta (finiscono nell'URL dell'endpoint,
// vedi useValori sotto): restano invariati con la lingua, come i nomi dei
// campi del Navigatore Biblioteca. Solo l'etichetta mostrata si traduce,
// vedi etichettaTipo più sotto.
const TIPI_IDS = ['autori', 'serie', 'tag', 'editori'] as const

type TipoId = (typeof TIPI_IDS)[number]

function etichettaTipo(id: TipoId, t: (chiave: string, valori?: Valori) => string): string {
  switch (id) {
    case 'autori':
      return t('entities.type.authors')
    case 'serie':
      return t('entities.type.series')
    case 'tag':
      return t('entities.type.tags')
    case 'editori':
      return t('entities.type.publishers')
  }
}

/** Il valore di `library` che significa "tutte quelle che posso vedere". */
const OVUNQUE = '*'

type StatoDati = 'mai_cercato' | 'non_trovato' | 'parziale' | 'completo'

interface DatiAutore {
  stato: StatoDati
  bio?: boolean
  immagine?: boolean
  anagrafica?: boolean
  /** L'esito grezzo dell'ultimo tentativo: 'no_page', 'blocked', 'error'… */
  esito?: string | null
  cercato_il?: string | null
}

interface Valore {
  id: number | string
  valore: string
  libri: number
  /** Compare in queste biblioteche (solo guardandole tutte insieme). */
  dove?: string[]
  /** Per questa grafia il recupero online ha trovato una voce vera. */
  conosciuto?: boolean
  /** Solo per gli autori: cosa c'è nella scheda e cosa manca. */
  dati?: DatiAutore
}

// Le quattro etichette degli stati, e la ragione per cui i primi due sono
// separati: "mai cercato" e "cercato e non trovato" si somigliano — la scheda
// è vuota in entrambi i casi — ma si trattano in modo opposto.
//
// Funzione e non un oggetto costante, come fixedColumnLabels in
// lib/libraryColumns.ts: deve ricalcolarsi al cambio lingua.
function etichetteStato(t: (chiave: string, valori?: Valori) => string): Record<StatoDati, { nome: string; spiega: string }> {
  return {
    mai_cercato: {
      nome: t('entities.status.neverSearched.name'),
      spiega: t('entities.status.neverSearched.description'),
    },
    non_trovato: {
      nome: t('entities.status.notFound.name'),
      spiega: t('entities.status.notFound.description'),
    },
    parziale: { nome: t('entities.status.partial.name'), spiega: t('entities.status.partial.description') },
    completo: { nome: t('entities.status.complete.name'), spiega: t('entities.status.complete.description') },
  }
}

interface Gruppo {
  suggerito: string
  libri: number
  valori: Valore[]
}

interface ElencoEntita {
  valori: Valore[]
  riepilogo_dati: Partial<Record<StatoDati, number>>
}

// Le tre voci della scheda sono colonne SEPARATE e non tre pallini in una
// cella sola (scelta del 29/09/2026: colonne separate aprono a ordinamenti
// più avanzati). Con una colonna unica si può solo ordinare per "quanto è
// completa"; separate si risponde a "chi ha la
// biografia ma non la foto", che è la domanda da cui parte il lavoro vero.
type ColonnaOrdinabile = 'valore' | 'libri' | 'dove' | 'bio' | 'immagine' | 'anagrafica'

/** Le tre colonne della scheda autore, nell'ordine in cui compaiono. */
function colonneScheda(t: (chiave: string, valori?: Valori) => string) {
  return [
    { chiave: 'bio' as const, etichetta: t('entities.column.bio') },
    { chiave: 'immagine' as const, etichetta: t('entities.column.photo') },
    { chiave: 'anagrafica' as const, etichetta: t('entities.column.data') },
  ]
}

// Tre stati per cella, non due: "manca" e "cercato e non c'era" si vedono
// uguali — la cella è vuota — ma solo il primo vale la pena di ricercarlo.
// L'ordinamento li tiene distinti, e mette per primo ciò su cui si può fare
// qualcosa.
function statoCella(v: Valore, campo: 'bio' | 'immagine' | 'anagrafica'): 0 | 1 | 2 {
  if (v.dati?.[campo]) return 2 // c'è
  if ((v.dati?.stato ?? 'mai_cercato') === 'mai_cercato') return 0 // mai cercato
  return 1 // cercato, non trovato
}

const ACCESSORI: Record<ColonnaOrdinabile, (v: Valore) => string | number> = {
  // localeCompare non si può usare dentro sortByCriteria (confronta valori,
  // non coppie): la chiave minuscola basta per un elenco di nomi propri, e
  // tiene "Álvaro" vicino ad "Alvaro" invece che in fondo.
  valore: (v) => v.valore.toLowerCase(),
  libri: (v) => v.libri,
  dove: (v) => (v.dove ?? []).join(', '),
  bio: (v) => statoCella(v, 'bio'),
  immagine: (v) => statoCella(v, 'immagine'),
  anagrafica: (v) => statoCella(v, 'anagrafica'),
}

function useValori(tipo: TipoId, library: string) {
  return useQuery({
    queryKey: ['entita', tipo, library],
    queryFn: async (): Promise<ElencoEntita> => {
      const { data, error } = await api.GET('/api/kolibre/entita/{tipo}', {
        params: { path: { tipo }, query: { library } },
      })
      if (error) throw error
      return data as unknown as ElencoEntita
    },
  })
}

function useAffini(tipo: TipoId, library: string) {
  return useQuery({
    queryKey: ['entita-affini', tipo, library],
    queryFn: async (): Promise<Gruppo[]> => {
      const { data, error } = await api.GET('/api/kolibre/entita/{tipo}/affini', {
        params: { path: { tipo }, query: { library } },
      })
      if (error) throw error
      return (data as unknown as { gruppi: Gruppo[] }).gruppi
    },
  })
}

type CoppiaDistinta = {
  valori: string[]
  deciso_da: string | null
  deciso_il: string | null
}

/** Le coppie che qualcuno ha dichiarato essere cose diverse.
 *
 *  Non dipende da `library`: «Berta e Berto sono due persone» è un'affermazione
 *  sul mondo, non su una cartella. */
function useDistinti(tipo: TipoId) {
  return useQuery({
    queryKey: ['entita-distinti', tipo],
    queryFn: async (): Promise<CoppiaDistinta[]> => {
      const { data, error } = await api.GET('/api/kolibre/entita/{tipo}/distinti', {
        params: { path: { tipo } },
      })
      if (error) throw error
      return (data as unknown as { coppie: CoppiaDistinta[] }).coppie
    },
  })
}

export function EntitiesPage() {
  const { t } = useLingua()
  useSetPageHeader(t('entities.pageTitle'))
  const queryClient = useQueryClient()
  const { data: biblioteche = [] } = useLibraries()

  // Tutte insieme è il default: è il modo in cui questa pagina serve davvero.
  const [library, setLibrary] = useState<string>(OVUNQUE)
  const [tipo, setTipo] = useState<TipoId>('autori')
  const [ricerca, setRicerca] = useState('')
  const [occupato, setOccupato] = useState<string | null>(null)

  // La destinazione scelta a mano per un gruppo, quando è diversa da quella
  // suggerita. Chiave: il nome suggerito, che identifica il gruppo.
  const [destinazione, setDestinazione] = useState<Record<string, string>>({})
  // La voce dell'elenco che si sta rinominando, e il testo in corso.
  const [inModifica, setInModifica] = useState<string | null>(null)
  const [nuovoNome, setNuovoNome] = useState('')

  // Quale stato della scheda si sta guardando, o tutti.
  const [filtroStato, setFiltroStato] = useState<StatoDati | null>(null)
  const [recuperoInCorso, setRecuperoInCorso] = useState(false)
  const [pulizia, setPulizia] = useState(false)
  // Se mostrare l'elenco dei rifiuti. Chiuso di preimpostazione: è un archivio
  // da consultare quando serve, non una cosa da avere sempre davanti.
  const [mostraDistinti, setMostraDistinti] = useState(false)
  // I criteri di ordinamento, dal più recente al più vecchio. Non uno solo,
  // perché scegliere una colonna nuova non deve buttare via quella di prima:
  // ordinando per biografia no/sì e poi per immagine no/sì, a parità di
  // immagine l'ordine precedente va preservato (scelta del 30/09/2026). "Chi
  // ha la foto ma non la biografia" è una domanda a due colonne, e con un
  // criterio solo non si può fare.
  const [criteri, setCriteri] = useState<Criterio<ColonnaOrdinabile>[]>([
    { chiave: 'valore', verso: 'asc' },
  ])

  const ETICHETTE_STATO = useMemo(() => etichetteStato(t), [t])
  const COLONNE_SCHEDA = useMemo(() => colonneScheda(t), [t])

  const { data: elenco, isLoading } = useValori(tipo, library)
  const valori = useMemo(() => elenco?.valori ?? [], [elenco])
  const riepilogo = elenco?.riepilogo_dati ?? {}
  const { data: gruppi = [], isLoading: caricaGruppi } = useAffini(tipo, library)
  const { data: distinti = [] } = useDistinti(tipo)

  const filtrati = useMemo(() => {
    const q = ricerca.trim().toLowerCase()
    let elenco = valori
    if (filtroStato) elenco = elenco.filter((v) => (v.dati?.stato ?? 'mai_cercato') === filtroStato)
    if (q) elenco = elenco.filter((v) => v.valore.toLowerCase().includes(q))
    // L'ultima parola la ha il nome: è l'ordine con cui il server manda
    // l'elenco, e a parità di tutto il resto ci si deve ritrovare quello e non
    // un ordine che cambia a ogni ricarica.
    return sortByCriteria(elenco, ACCESSORI, criteri, (v) => v.valore.toLowerCase())
  }, [valori, ricerca, filtroStato, criteri])

  // La selezione lavora su indici numerici perché `useRowSelection` è scritto
  // così (lo usano anche Libreria e Dispositivi, e ha già lo shift+clic per
  // intervalli). L'indice è quello nell'elenco COMPLETO, non in quello
  // ordinato: altrimenti riordinare una colonna sposterebbe la selezione su
  // righe diverse da quelle scelte.
  const indiceDi = useMemo(() => {
    const m = new Map<string, number>()
    valori.forEach((v, i) => m.set(v.valore, i))
    return m
  }, [valori])
  const idsVisibili = useMemo(
    () => filtrati.map((v) => indiceDi.get(v.valore) ?? -1),
    [filtrati, indiceDi]
  )
  const { selected, toggle, clear } = useRowSelection(idsVisibili)

  // La selezione è fatta di INDICI dentro `valori`: cambiando scheda o
  // biblioteca `valori` diventa un altro elenco e quegli indici restano
  // validi, ma puntano ad altro. Prima la barra delle azioni restava accesa
  // elencando entità mai selezionate, e «Unisci verso …» era a un clic di
  // distanza dal riscrivere i metadati dei libri sull'entità sbagliata.
  useEffect(() => {
    clear()
    setDestinazione({})
    // `clear` cambia identità a ogni render di useRowSelection: metterla fra
    // le dipendenze rifarebbe partire l'effetto in continuazione.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tipo, library])
  const scelti = useMemo(
    () => filtrati.filter((v) => selected.has(indiceDi.get(v.valore) ?? -1)),
    [filtrati, selected, indiceDi]
  )

  // Quanti criteri si tengono. Quattro perché la scheda autore ha tre colonne
  // più il nome: oltre, nessuno ricorda più che ordine ha chiesto, e la pila
  // diventerebbe un registro di clic invece di un ordinamento.
  const MAX_CRITERI = 4

  function ordinaPer(chiave: ColonnaOrdinabile) {
    setCriteri((prec) => {
      // Riclic sulla colonna che già comanda: si gira il verso e la pila resta
      // com'è, altrimenti invertire l'ordine perderebbe i criteri sotto.
      if (prec[0]?.chiave === chiave) {
        return [{ chiave, verso: prec[0].verso === 'asc' ? 'desc' : 'asc' }, ...prec.slice(1)]
      }
      // I nomi si leggono dalla A; i numeri e gli stati interessano dal caso
      // peggiore — "chi ha più libri", "chi non ha dati" — quindi il primo clic
      // su quelle colonne parte dall'alto.
      const verso: 'asc' | 'desc' = chiave === 'valore' ? 'asc' : 'desc'
      // La colonna che passa davanti esce da dov'era: tenerla in due posti
      // vorrebbe dire confrontarla due volte, e il secondo confronto non
      // deciderebbe mai niente.
      const resto = prec.filter((c) => c.chiave !== chiave)
      return [{ chiave, verso }, ...resto].slice(0, MAX_CRITERI)
    })
  }

  /** Il posto di una colonna fra i criteri: 0 se non c'è, 1 se comanda. */
  const livelloDi = (chiave: ColonnaOrdinabile) =>
    criteri.findIndex((c) => c.chiave === chiave) + 1

  // Il recupero dati usa gli endpoint che esistono già per la pagina Autori:
  // senza `force` prende i mai cercati più quelli la cui attesa è scaduta
  // (le attese esistono perché ritentare subito un "non trovato" fa solo
  // rifiutare le richieste per tutti gli altri); con `force` rifà tutti.
  async function recupera(force: boolean) {
    setRecuperoInCorso(true)
    try {
      const esito = await startScrapeMissingAuthors(force)
      toast.success(
        esito === 'nothing_to_do'
          ? t('entities.scrape.nothingToDo')
          : t('entities.scrape.started')
      )
    } catch (err) {
      // Il 409 "Un recupero è già in corso" arriva con il suo messaggio: è
      // esattamente quello che serve sapere, e non è un errore.
      toast.error(messaggioErrore(err, t('entities.error.generic')))
    } finally {
      setRecuperoInCorso(false)
    }
  }

  async function scrivi(da: string[], a: string, etichetta: string) {
    setOccupato(etichetta)
    try {
      const { data, error, response } = await api.POST('/api/kolibre/entita/{tipo}/unisci', {
        params: { path: { tipo }, query: { library } },
        body: { da, a },
      })
      // Il messaggio del server è già scritto per una persona ("Non puoi
      // modificare la biblioteca 'Narrativa'."): mostrarlo com'è dice molto
      // più di un "non riuscito" nostro.
      if (error) {
        toast.error(messaggioErrore(error, t('entities.error.generic'), response?.status))
        return
      }
      const esito = data as unknown as { libri_toccati: number; grafie_corrette?: number }
      const toccati = esito.libri_toccati
      // Un'unione può non toccare nessun libro e riuscire comunque: succede
      // quando la voce vecchia era già rimasta senza libri, o quando le due
      // grafie differiscono solo per le maiuscole. Dire "0 libri riscritti" a
      // chi ha appena visto il nome cambiare suonerebbe come un errore.
      toast.success(
        toccati > 0
          ? t('entities.merge.rewritten', { count: toccati, n: toccati, name: a })
          : t('entities.merge.spellingFixed', { name: a })
      )
      await queryClient.invalidateQueries({ queryKey: ['entita'] })
      await queryClient.invalidateQueries({ queryKey: ['entita-affini'] })
      await queryClient.invalidateQueries({ queryKey: ['books'] })
    } catch {
      toast.error(t('entities.error.noResponse'))
    } finally {
      setOccupato(null)
    }
  }

  async function unisci(gruppo: Gruppo) {
    const scelta = destinazione[gruppo.suggerito] ?? gruppo.suggerito
    const da = gruppo.valori.map((v) => v.valore).filter((v) => v !== scelta)
    if (!da.length) return
    if (
      !window.confirm(
        `${t('entities.merge.confirmTitle', { count: da.length, n: da.length, name: scelta })}\n\n${da.join('\n')}\n\n` +
          t('entities.merge.confirmNote')
      )
    )
      return
    await scrivi(da, scelta, gruppo.suggerito)
  }

  async function rinomina(vecchio: string) {
    const a = nuovoNome.trim()
    if (!a || a === vecchio) {
      setInModifica(null)
      return
    }
    const esisteGia = valori.some((v) => v.valore === a)
    if (
      esisteGia &&
      !window.confirm(t('entities.rename.confirmMerge', { name: a, old: vecchio }))
    )
      return
    setInModifica(null)
    await scrivi([vecchio], a, vecchio)
  }

  /**
   * «Questi non sono la stessa cosa.»
   *
   * Il rovescio dell'unione, e serve quanto lei: l'algoritmo riconosce che due
   * grafie si somigliano, non che siano la stessa persona. Senza un posto dove
   * ricordare il no, la coppia torna a ogni apertura della pagina, e una coda
   * di lavoro che non si accorcia si smette di guardare.
   */
  async function segnaDistinti(gruppo: Gruppo) {
    const valori = gruppo.valori.map((v) => v.valore)
    setOccupato(gruppo.suggerito)
    try {
      const { error, response } = await api.POST('/api/kolibre/entita/{tipo}/distinti', {
        params: { path: { tipo } },
        body: { valori },
      })
      if (error) {
        toast.error(messaggioErrore(error, t('entities.error.generic'), response?.status))
        return
      }
      toast.success(
        valori.length === 2
          ? t('entities.distinct.markedTwo', { a: valori[0], b: valori[1] })
          : t('entities.distinct.markedMany', { n: valori.length })
      )
      await queryClient.invalidateQueries({ queryKey: ['entita-affini'] })
      await queryClient.invalidateQueries({ queryKey: ['entita-distinti'] })
    } catch {
      toast.error(t('entities.error.noResponse'))
    } finally {
      setOccupato(null)
    }
  }

  /** Torna a proporre una coppia: il rifiuto era sbagliato. */
  async function annullaDistinti(valori: string[]) {
    const { error, response } = await api.POST('/api/kolibre/entita/{tipo}/distinti/annulla', {
      params: { path: { tipo } },
      body: { valori },
    })
    if (error) {
      toast.error(messaggioErrore(error, t('entities.error.generic'), response?.status))
      return
    }
    toast.success(t('entities.distinct.restored'))
    await queryClient.invalidateQueries({ queryKey: ['entita-affini'] })
    await queryClient.invalidateQueries({ queryKey: ['entita-distinti'] })
  }

  /** Unisce le righe selezionate verso quella cliccata. */
  async function unisciSelezionati(destinazione: string) {
    const da = scelti.map((v) => v.valore).filter((v) => v !== destinazione)
    if (!da.length) return
    if (
      !window.confirm(
        `${t('entities.merge.confirmSelected', { count: da.length, n: da.length, name: destinazione })}\n\n${da.join('\n')}`
      )
    )
      return
    await scrivi(da, destinazione, destinazione)
    clear()
  }

  /** Solo per le serie: toglierle dai libri, o trasformarle in tag. */
  async function sciogliSelezionate(inTag: boolean) {
    const serie = scelti.map((v) => v.valore)
    if (!serie.length) return
    const quante = serie.length === 1 ? t('entities.series.quantitySingle') : t('entities.series.quantityMany', { n: serie.length })
    if (
      !window.confirm(
        inTag
          ? t('entities.series.confirmToTag', { quantity: quante })
          : t('entities.series.confirmDissolve', { quantity: quante })
      )
    )
      return
    setOccupato('serie')
    try {
      const { data, error, response } = await api.POST('/api/kolibre/entita/serie/sciogli', {
        params: { query: { library } },
        body: { serie, in_tag: inTag },
      })
      if (error) {
        toast.error(messaggioErrore(error, t('entities.error.generic'), response?.status))
        return
      }
      const toccati = (data as unknown as { libri_toccati: number }).libri_toccati
      toast.success(t('entities.series.updatedCount', { count: toccati, n: toccati }))
      clear()
      await queryClient.invalidateQueries({ queryKey: ['entita'] })
      await queryClient.invalidateQueries({ queryKey: ['entita-affini'] })
      await queryClient.invalidateQueries({ queryKey: ['books'] })
    } catch {
      toast.error(t('entities.error.noResponse'))
    } finally {
      setOccupato(null)
    }
  }

  /** Toglie le voci rimaste senza libri dopo gli accorpamenti. */
  async function pulisciOrfane() {
    setPulizia(true)
    try {
      const { data, error, response } = await api.POST('/api/kolibre/entita/{tipo}/pulisci', {
        params: { path: { tipo }, query: { library } },
      })
      if (error) {
        toast.error(messaggioErrore(error, t('entities.error.generic'), response?.status))
        return
      }
      const tolte = (data as unknown as { tolte: number }).tolte
      toast.success(t('entities.cleanup.removedCount', { count: tolte, n: tolte }))
      await queryClient.invalidateQueries({ queryKey: ['entita'] })
      await queryClient.invalidateQueries({ queryKey: ['entita-affini'] })
    } catch {
      toast.error(t('entities.error.noResponse'))
    } finally {
      setPulizia(false)
    }
  }

  const senzaLibri = useMemo(() => valori.filter((v) => v.libri === 0), [valori])

  const nomeBiblioteca = (folder: string) =>
    biblioteche.find((l) => l.folder_name === folder)?.name ?? folder

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {TIPI_IDS.map((id) => (
          <button
            key={id}
            onClick={() => {
              setTipo(id)
              setDestinazione({})
            }}
            className={cn(
              'rounded-md border px-3 py-1.5 text-[12.5px] transition-colors',
              tipo === id ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-accent'
            )}
          >
            {etichettaTipo(id, t)}
          </button>
        ))}

        <select
          value={library}
          onChange={(e) => {
            setLibrary(e.target.value)
            setDestinazione({})
          }}
          className="ml-auto rounded-md border border-border bg-background px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary"
        >
          <option value={OVUNQUE}>{t('entities.library.all')}</option>
          {biblioteche.map((l) => (
            <option key={l.id} value={l.folder_name}>
              {l.name}
            </option>
          ))}
        </select>
      </div>

      <section className="flex flex-col gap-2">
        <h2 className="font-serif text-[15px] font-semibold">{t('entities.similarity.heading')}</h2>
        {caricaGruppi ? (
          <p className="text-[12.5px] text-muted-foreground">{t('entities.similarity.loading')}</p>
        ) : gruppi.length === 0 ? (
          <p className="text-[12.5px] text-muted-foreground">
            {t('entities.similarity.noneFound', { total: numero(valori.length) })}
          </p>
        ) : (
          <>
            <p className="text-[12px] text-muted-foreground">
              {t('entities.similarity.groupCount', { count: gruppi.length, n: gruppi.length })} {t('entities.similarity.instructions')}
            </p>
            <div className="flex flex-col gap-1.5">
              {gruppi.map((gruppo) => {
                const scelta = destinazione[gruppo.suggerito] ?? gruppo.suggerito
                return (
                  <div
                    key={gruppo.suggerito}
                    className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-border bg-card px-3 py-2.5"
                  >
                    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
                      {gruppo.valori.map((v) => {
                        const tenuta = v.valore === scelta
                        return (
                          <button
                            key={v.valore}
                            type="button"
                            title={
                              tenuta
                                ? t('entities.similarity.keptTitle')
                                : t('entities.similarity.keepInsteadTitle', { value: v.valore, current: scelta })
                            }
                            onClick={() =>
                              setDestinazione((prec) => ({ ...prec, [gruppo.suggerito]: v.valore }))
                            }
                            className={cn(
                              'inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[12.5px] transition-colors',
                              tenuta
                                ? 'border-primary bg-primary/10 font-medium text-primary'
                                : 'border-border text-muted-foreground line-through hover:bg-accent hover:no-underline'
                            )}
                          >
                            {tenuta && <Check className="size-3.5 shrink-0" />}
                            {v.valore}
                            {v.conosciuto && (
                              <Globe
                                className="size-3 shrink-0 opacity-70"
                                aria-label={t('entities.foundOnline')}
                              />
                            )}
                            <span className="tabular-nums opacity-60">{v.libri}</span>
                          </button>
                        )
                      })}
                    </div>
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={occupato === gruppo.suggerito}
                      onClick={() => void unisci(gruppo)}
                    >
                      {occupato === gruppo.suggerito ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <Merge className="size-3.5" />
                      )}
                      {t('entities.similarity.mergeInto', { name: scelta })}
                    </Button>
                    {/* Il rovescio dell'unione. Accanto a lei e non in un menù:
                        su un gruppo sbagliato è l'azione giusta, e cercarla
                        costerebbe più che ignorare il suggerimento — che è
                        appunto quello che si finisce per fare. */}
                    <Button
                      size="xs"
                      variant="ghost"
                      disabled={occupato === gruppo.suggerito}
                      title={t('entities.similarity.markDistinctTitle')}
                      onClick={() => void segnaDistinti(gruppo)}
                    >
                      <Unlink className="size-3.5" />
                      {t('entities.similarity.markDistinct')}
                    </Button>
                  </div>
                )
              })}
            </div>
          </>
        )}

        {/* L'archivio dei rifiuti. Non è decorativo: un "no" dato per sbaglio
            nasconde una coppia per sempre, e senza un posto dove vederlo non
            ci sarebbe modo di accorgersene. */}
        {distinti.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <button
              type="button"
              onClick={() => setMostraDistinti((v) => !v)}
              className="self-start text-[12px] text-muted-foreground underline decoration-dotted hover:text-foreground"
            >
              {t('entities.distinct.pairCount', { count: distinti.length, n: distinti.length })}
              {' — '}{mostraDistinti ? t('entities.distinct.hide') : t('entities.distinct.show')}
            </button>
            {mostraDistinti && (
              <div className="flex flex-col gap-1 rounded-md border border-border bg-card px-3 py-2">
                {distinti.map((c) => (
                  <div
                    key={c.valori.join('|')}
                    className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]"
                  >
                    <span className="flex-1">
                      {c.valori[0]} <span className="text-muted-foreground">≠</span> {c.valori[1]}
                      {c.deciso_da && (
                        <span className="text-muted-foreground"> · {c.deciso_da}</span>
                      )}
                    </span>
                    <Button size="xs" variant="ghost" onClick={() => void annullaDistinti(c.valori)}>
                      {t('entities.distinct.reproposeButton')}
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* Lo stato delle schede autore. Solo per gli autori: sono l'unica
          entità di cui Kolibre scarichi dei dati.

          Le quattro caselle sono anche il filtro dell'elenco qui sotto: il
          numero da solo dice quanto lavoro c'è, cliccarlo dice quale. */}
      {tipo === 'autori' && (
        <section className="flex flex-col gap-2">
          <h2 className="font-serif text-[15px] font-semibold">{t('entities.authorCards.heading')}</h2>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(ETICHETTE_STATO) as StatoDati[]).map((stato) => {
              const quanti = riepilogo[stato] ?? 0
              const attivo = filtroStato === stato
              return (
                <button
                  key={stato}
                  type="button"
                  title={ETICHETTE_STATO[stato].spiega}
                  onClick={() => setFiltroStato(attivo ? null : stato)}
                  disabled={quanti === 0}
                  className={cn(
                    'flex min-w-[150px] flex-1 flex-col gap-0.5 rounded-md border px-3 py-2 text-left transition-colors',
                    attivo ? 'border-primary bg-primary/10' : 'border-border hover:bg-accent',
                    quanti === 0 && 'opacity-45'
                  )}
                >
                  <span className="text-[17px] font-semibold tabular-nums">{numero(quanti)}</span>
                  <span className="text-[12px] text-muted-foreground">{ETICHETTE_STATO[stato].nome}</span>
                </button>
              )
            })}
          </div>

          <p className="text-[12px] leading-relaxed text-muted-foreground">
            {filtroStato
              ? ETICHETTE_STATO[filtroStato].spiega
              : t('entities.authorCards.defaultHint')}
          </p>

          <div className="flex flex-wrap items-center gap-2">
            <Button size="xs" variant="outline" disabled={recuperoInCorso} onClick={() => void recupera(false)}>
              {recuperoInCorso ? <Loader2 className="size-3.5 animate-spin" /> : <Download className="size-3.5" />}
              {t('entities.authorCards.fetchMissing')}
            </Button>
            <Button size="xs" variant="ghost" disabled={recuperoInCorso} onClick={() => void recupera(true)}>
              {t('entities.authorCards.retryAll')}
            </Button>
            <span className="text-[11.5px] text-muted-foreground">
              {t('entities.authorCards.fetchHint')}
            </span>
          </div>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-serif text-[15px] font-semibold">
            {filtroStato ? ETICHETTE_STATO[filtroStato].nome : t('entities.list.allEntries')}
            {valori.length > 0 && ` (${numero(filtrati.length)})`}
          </h2>
          <div className="relative max-w-[280px] flex-1">
            <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground/70" />
            <input
              value={ricerca}
              onChange={(e) => setRicerca(e.target.value)}
              placeholder={t('common.search.placeholder')}
              className="w-full rounded-md border border-border bg-background py-1.5 pr-2.5 pl-7 text-[13px] outline-none focus:border-primary"
            />
          </div>
        </div>
        <p className="text-[12px] text-muted-foreground">
          {t('entities.list.instructions')}
        </p>

        {/* Le voci rimaste senza libri. Sono il residuo degli accorpamenti —
            Calibre Desktop le pulisce da solo, Kolibre scrive sulle stesse
            tabelle e non lo faceva — e finché restano tornano a galla nei
            suggerimenti. Il numero prima del bottone: si cancella sapendo
            quanto. */}
        {senzaLibri.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--warning)]/40 bg-[var(--warning-soft)] px-3 py-2 text-[12.5px]">
            <span className="flex-1">
              {t('entities.orphan.notice', { count: senzaLibri.length, n: senzaLibri.length })}
            </span>
            <Button size="xs" variant="outline" disabled={pulizia} onClick={() => void pulisciOrfane()}>
              {pulizia ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
              {t('entities.orphan.removeButton')}
            </Button>
          </div>
        )}

        {/* Cosa si può fare su ciò che è selezionato. Compare solo con una
            selezione viva: una barra di azioni sempre presente ma quasi
            sempre inerte si impara a ignorare. */}
        {scelti.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-[12.5px]">
            <span className="flex-1">
              {t('entities.selection.count', { count: scelti.length, n: scelti.length })} ·{' '}
              <span className="text-muted-foreground">{scelti.map((v) => v.valore).join(' · ')}</span>
            </span>

            {scelti.length > 1 && (
              <span className="flex flex-wrap items-center gap-1.5">
                <span className="text-muted-foreground">{t('entities.selection.mergeIntoLabel')}</span>
                {scelti.map((v) => (
                  <Button
                    key={v.valore}
                    size="xs"
                    variant="outline"
                    disabled={occupato !== null}
                    onClick={() => void unisciSelezionati(v.valore)}
                  >
                    <Merge className="size-3.5" />
                    {v.valore}
                  </Button>
                ))}
              </span>
            )}

            {tipo === 'serie' && (
              <span className="flex flex-wrap items-center gap-1.5">
                <Button size="xs" variant="outline" disabled={occupato !== null} onClick={() => void sciogliSelezionate(true)}>
                  {t('entities.series.convertToTag')}
                </Button>
                <Button size="xs" variant="ghost" disabled={occupato !== null} onClick={() => void sciogliSelezionate(false)}>
                  {t('entities.series.dissolve')}
                </Button>
              </span>
            )}

            <Button size="xs" variant="ghost" onClick={clear}>
              <X className="size-3.5" />
            </Button>
          </div>
        )}

        {isLoading ? (
          <p className="text-[12.5px] text-muted-foreground">{t('common.loading')}</p>
        ) : (
          <div className="max-h-[520px] overflow-y-auto rounded-md border border-border">
            <Table>
              <TableHeader className="sticky top-0 bg-card">
                <TableRow>
                  <SortableTableHead
                    label={t('entities.field.name')}
                    sortKey="valore"
                    active={livelloDi('valore') > 0}
                    order={criteri[livelloDi('valore') - 1]?.verso ?? 'asc'}
                    livello={livelloDi('valore')}
                    onClick={ordinaPer}
                  />
                  {tipo === 'autori' &&
                    COLONNE_SCHEDA.map((c) => (
                      <SortableTableHead
                        key={c.chiave}
                        label={c.etichetta}
                        sortKey={c.chiave}
                        active={livelloDi(c.chiave) > 0}
                        order={criteri[livelloDi(c.chiave) - 1]?.verso ?? 'asc'}
                        livello={livelloDi(c.chiave)}
                        onClick={ordinaPer}
                        className="w-16 text-center"
                      />
                    ))}
                  {library === OVUNQUE && (
                    <SortableTableHead
                      label={t('entities.field.where')}
                      sortKey="dove"
                      active={livelloDi('dove') > 0}
                      order={criteri[livelloDi('dove') - 1]?.verso ?? 'asc'}
                      livello={livelloDi('dove')}
                      onClick={ordinaPer}
                      className="w-48"
                    />
                  )}
                  <SortableTableHead
                    label={t('entities.field.books')}
                    sortKey="libri"
                    active={livelloDi('libri') > 0}
                    order={criteri[livelloDi('libri') - 1]?.verso ?? 'asc'}
                    livello={livelloDi('libri')}
                    onClick={ordinaPer}
                    className="w-20 text-right"
                  />
                  <TableHead className="w-14" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtrati.slice(0, 500).map((v) => {
                  const idRiga = indiceDi.get(v.valore) ?? -1
                  const selezionata = selected.has(idRiga)
                  return (
                  <TableRow
                    key={String(v.id)}
                    className={cn('group cursor-pointer', selezionata && 'bg-primary/10 hover:bg-primary/10')}
                    // Clic semplice = solo questa; Cmd/Ctrl per aggiungere,
                    // Shift per un intervallo. Stesso gesto della Libreria e
                    // della tabella dei dispositivi: un utente che ne impara
                    // uno li ha imparati tutti.
                    onClick={(e) => {
                      if (inModifica === v.valore) return
                      if (e.metaKey || e.ctrlKey || e.shiftKey) toggle(idRiga, e)
                      else if (selezionata && selected.size === 1) clear()
                      else {
                        clear()
                        toggle(idRiga)
                      }
                    }}
                    onDoubleClick={() => {
                      setInModifica(v.valore)
                      setNuovoNome(v.valore)
                    }}
                  >
                    <TableCell>
                      {inModifica === v.valore ? (
                        <form
                          className="flex items-center gap-1.5"
                          onSubmit={(e) => {
                            e.preventDefault()
                            void rinomina(v.valore)
                          }}
                        >
                          <input
                            value={nuovoNome}
                            onChange={(e) => setNuovoNome(e.target.value)}
                            onKeyDown={(e) => e.key === 'Escape' && setInModifica(null)}
                            autoFocus
                            className="min-w-[220px] flex-1 rounded-md border border-primary bg-background px-2 py-1 text-[13px] outline-none"
                          />
                          <Button type="submit" size="xs" disabled={occupato === v.valore}>
                            {occupato === v.valore ? <Loader2 className="size-3.5 animate-spin" /> : t('common.save')}
                          </Button>
                          <Button type="button" variant="ghost" size="xs" onClick={() => setInModifica(null)}>
                            <X className="size-3.5" />
                          </Button>
                        </form>
                      ) : (
                        <span className="inline-flex items-center gap-1.5">
                          {v.valore}
                          {v.conosciuto && (
                            <Globe className="size-3 opacity-60" aria-label={t('entities.foundOnline')} />
                          )}
                        </span>
                      )}
                    </TableCell>
                    {tipo === 'autori' &&
                      COLONNE_SCHEDA.map((c) => (
                        <TableCell key={c.chiave} className="text-center">
                          <CellaScheda stato={statoCella(v, c.chiave)} campo={c.etichetta} t={t} />
                        </TableCell>
                      ))}
                    {library === OVUNQUE && (
                      <TableCell className="text-[12px] text-muted-foreground">
                        {(v.dove ?? []).map(nomeBiblioteca).join(', ') || '—'}
                      </TableCell>
                    )}
                    <TableCell className="text-right tabular-nums text-muted-foreground">{v.libri}</TableCell>
                    <TableCell>
                      {inModifica !== v.valore && (
                        <span className="flex items-center justify-end gap-1">
                          {/* La scheda dell'autore, SEMPRE raggiungibile.
                              C'era, dentro il componente a tre pallini, ed e'
                              sparita quando quello ha lasciato il posto alle
                              tre colonne: da allora la riga si poteva
                              selezionare e correggere, ma non aprire (notato
                              il 30/09/2026). Visibile senza passarci sopra,
                              perche' un'uscita che si scopre solo col mouse
                              non e' un'uscita. */}
                          {tipo === 'autori' && (
                            <Link
                              to={`/autori/${encodeURIComponent(v.valore)}`}
                              title={t('entities.list.openCardTitle', { name: v.valore })}
                              onClick={(e) => e.stopPropagation()}
                              className="text-muted-foreground hover:text-foreground"
                            >
                              <ExternalLink className="size-3.5" />
                            </Link>
                          )}
                          <button
                            type="button"
                            title={t('entities.list.fixNameTitle')}
                            onClick={(e) => {
                              e.stopPropagation()
                              setInModifica(v.valore)
                              setNuovoNome(v.valore)
                            }}
                            className="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-foreground"
                          >
                            <Pencil className="size-3.5" />
                          </button>
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                  )
                })}
              </TableBody>
            </Table>
            {filtrati.length > 500 && (
              <p className="border-t border-border px-3 py-2 text-[11.5px] text-muted-foreground">
                {t('entities.list.truncatedNotice', { total: numero(filtrati.length) })}
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

/**
 * Una casella della scheda di un autore: biografia, foto o anagrafica.
 *
 * Tre stati e non due, ed è la ragione per cui questa non è una spunta:
 * "manca" e "cercato, non c'era" lasciano entrambi la cella vuota, ma solo
 * sul primo una ricerca ha senso. Il secondo si distingue da un trattino
 * invece che dal nulla — e l'ordinamento della colonna li tiene separati,
 * portando in cima ciò su cui si può ancora fare qualcosa.
 */
function CellaScheda({ stato, campo, t }: { stato: 0 | 1 | 2; campo: string; t: (chiave: string, valori?: Valori) => string }) {
  if (stato === 2) {
    return <Check className="mx-auto size-3.5 text-[var(--positive)]" aria-label={t('entities.cell.present', { field: campo })} />
  }
  if (stato === 1) {
    return (
      <span className="text-muted-foreground/70" title={t('entities.cell.searchedNotFound', { field: campo })}>
        –
      </span>
    )
  }
  return (
    <span className="text-muted-foreground/40" title={t('entities.cell.neverSearched', { field: campo })}>
      ·
    </span>
  )
}
