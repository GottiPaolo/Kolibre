import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { FolderTree, Loader2, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  SettingsFeedback,
  SettingsHint,
  SettingsRow,
  SettingsSection,
} from '@/components/settings/SettingsPrimitives'
import {
  analyzeBookPaths,
  repairBookPaths,
  type EsitoAnalisiPercorsi,
  type LibroFuoriPosto,
} from '@/lib/libraryToolsActions'
import { errorDetail } from '@/lib/librarySettingsActions'
import { useLibraries } from '@/lib/queries'
import { useLingua } from '@/lib/i18n'

// Quanti libri per richiesta. Spostare una cartella dentro lo stesso disco
// costa quasi niente, ma su una biblioteca di rete puo' costare: a blocchi
// la pagina puo' dire a che punto e', e un'interruzione non lascia niente a
// meta' (l'operazione e' idempotente — si rilancia e riprende da dove era).
const BLOCCO = 200

// Quanti esempi mostrare in tutto. Servono a far capire cosa sta per
// succedere ai file, non a elencare la biblioteca.
const ESEMPI = 8

interface PerBiblioteca {
  folder: string
  nome: string
  esito: EsitoAnalisiPercorsi
}

// "Cartelle dei libri" — verifica della struttura e migrazione.
//
// Kolibre ora nomina cartelle e file esattamente come Calibre (cartella del
// PRIMO autore, nomi traslitterati e troncati, file "Titolo - Autore"). Le
// biblioteche esistenti pero' portano ancora la vecchia convenzione, e i
// libri a cui si e' cambiato l'autore prima di questo lavoro sono rimasti
// nella cartella del nome vecchio.
//
// A differenza delle altre azioni di questa pagina, guarda TUTTE le
// biblioteche e non quella scelta nel selettore: una migrazione che
// bisogna ricordarsi di lanciare una volta per biblioteca e' una
// migrazione che resta a meta'.
export function BookPathsSection() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: libraries = [] } = useLibraries()
  const [risultati, setRisultati] = useState<PerBiblioteca[] | null>(null)
  const [fase, setFase] = useState<'ferma' | 'analisi' | 'riparazione'>('ferma')
  const [inCorso, setInCorso] = useState('')
  const [sistemati, setSistemati] = useState(0)
  const [messaggio, setMessaggio] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const daSistemare = (risultati ?? []).reduce((n, r) => n + r.esito.movable, 0)
  const mancanti = (risultati ?? []).reduce((n, r) => n + r.esito.missing, 0)
  const esempi: { voce: LibroFuoriPosto; biblioteca: string }[] = []
  for (const r of risultati ?? []) {
    for (const voce of r.esito.sample) {
      if (esempi.length < ESEMPI) esempi.push({ voce, biblioteca: r.nome })
    }
  }

  async function analizza() {
    setFase('analisi')
    setMessaggio(null)
    setRisultati(null)
    setSistemati(0)
    const trovati: PerBiblioteca[] = []
    try {
      for (const lib of libraries) {
        setInCorso(lib.name)
        trovati.push({ folder: lib.folder_name, nome: lib.name, esito: await analyzeBookPaths(lib.folder_name) })
      }
      setRisultati(trovati)
    } catch (err) {
      setMessaggio({ kind: 'error', text: errorDetail(err, t('settings.bookPaths.error.check')) })
    } finally {
      setInCorso('')
      setFase('ferma')
    }
  }

  async function ripara() {
    if (!risultati) return
    setFase('riparazione')
    setMessaggio(null)
    let fatti = 0
    let falliti = 0
    try {
      for (const r of risultati) {
        if (r.esito.movable === 0) continue
        setInCorso(r.nome)
        // Si va avanti finche' il server dice che ne restano: il conteggio
        // dell'analisi e' solo una fotografia del momento, e nel frattempo
        // la biblioteca puo' essere cambiata.
        for (;;) {
          const esito = await repairBookPaths(r.folder, BLOCCO)
          fatti += esito.moved
          falliti += esito.failed.length
          setSistemati(fatti)
          if (esito.moved === 0 || esito.remaining <= 0) break
        }
        await queryClient.invalidateQueries({ queryKey: ['books', r.folder] })
      }
      setMessaggio({
        kind: falliti > 0 ? 'error' : 'ok',
        text:
          falliti > 0
            ? t('settings.bookPaths.result.partial', { fixed: fatti, failed: falliti })
            : fatti > 0
              ? t('settings.bookPaths.result.done', { fixed: fatti })
              : t('settings.bookPaths.result.none'),
      })
      await analizza()
    } catch (err) {
      setMessaggio({ kind: 'error', text: errorDetail(err, t('settings.bookPaths.error.fix')) })
      setFase('ferma')
    } finally {
      setInCorso('')
    }
  }

  return (
    <SettingsSection label={t('settings.bookPaths.label')}>
      <SettingsRow
        name={t('settings.bookPaths.verifyStructure.name')}
        description={t('settings.bookPaths.verifyStructure.description')}
        last={!risultati}
      >
        <Button variant="outline" size="sm" disabled={fase !== 'ferma' || libraries.length === 0} onClick={() => void analizza()}>
          {fase === 'analisi' ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />}
          {fase === 'analisi' ? t('settings.bookPaths.checking', { name: inCorso }) : t('settings.bookPaths.check')}
        </Button>
      </SettingsRow>

      {risultati && daSistemare === 0 && mancanti === 0 && (
        <SettingsFeedback kind="ok">
          {libraries.length > 1
            ? t('settings.bookPaths.allLibrariesOk', { count: libraries.length })
            : t('settings.bookPaths.allBooksOk')}
        </SettingsFeedback>
      )}

      {risultati && daSistemare > 0 && (
        <SettingsRow
          name={t('settings.bookPaths.toFix.title', { n: daSistemare })}
          description={t('settings.bookPaths.toFix.description')}
          last={mancanti === 0}
        >
          <Button size="sm" disabled={fase !== 'ferma'} onClick={() => void ripara()}>
            {fase === 'riparazione' ? <Loader2 className="size-3.5 animate-spin" /> : <FolderTree className="size-3.5" />}
            {fase === 'riparazione'
              ? t('settings.bookPaths.fixingProgress', { name: inCorso, count: sistemati })
              : t('settings.bookPaths.fixButton', { n: daSistemare })}
          </Button>
        </SettingsRow>
      )}

      {/* Il dettaglio per biblioteca solo quando ce n'è più d'una e c'è
          qualcosa da dire: con una sola, il totale qui sopra basta. */}
      {risultati && libraries.length > 1 && daSistemare > 0 && (
        <div className="flex flex-col gap-0.5 pt-3.5 text-[12px]">
          {risultati.map((r) => (
            <div key={r.folder} className="flex justify-between gap-3">
              <span className={r.esito.movable > 0 ? '' : 'text-muted-foreground'}>{r.nome}</span>
              <span className="text-muted-foreground">
                {r.esito.movable > 0
                  ? t('settings.bookPaths.perLibrary.toFix', { n: r.esito.movable })
                  : t('settings.bookPaths.perLibrary.ok')}
              </span>
            </div>
          ))}
        </div>
      )}

      {esempi.length > 0 && (
        <div className="flex flex-col gap-1 pt-3.5">
          {esempi.map(({ voce, biblioteca }) => (
            <div key={`${biblioteca}-${voce.id}`} className="rounded-md border border-[var(--border-soft)] px-2.5 py-1.5 text-[12px]">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-medium">{voce.title}</span>
                <span className="text-[11px] text-muted-foreground">{voce.reason}</span>
              </div>
              {/* Il percorso vecchio e quello nuovo uno sopra l'altro: è la
                  sola cosa che dice davvero cosa sta per succedere ai file. */}
              <div className="mt-0.5 font-mono text-[11px] break-all text-muted-foreground">
                {voce.path}
                {voce.new_path !== voce.path && (
                  <>
                    <br />→ {voce.new_path}
                  </>
                )}
              </div>
              {voce.rename_files && (
                <div className="mt-0.5 text-[11px] text-muted-foreground">
                  {t('settings.bookPaths.example.alsoRenames', {
                    title: voce.title,
                    author: voce.author.split('&')[0].trim(),
                  })}
                </div>
              )}
            </div>
          ))}
          {daSistemare > esempi.length && (
            <p className="text-[11.5px] text-muted-foreground">
              {t('settings.bookPaths.example.andMore', { n: daSistemare - esempi.length })}
            </p>
          )}
        </div>
      )}

      {risultati && mancanti > 0 && (
        <SettingsFeedback kind="error">{t('settings.bookPaths.missing', { n: mancanti })}</SettingsFeedback>
      )}

      {messaggio && <SettingsFeedback kind={messaggio.kind}>{messaggio.text}</SettingsFeedback>}

      <SettingsHint>
        {t('settings.bookPaths.hint.before')}
        <em>{t('settings.bookPaths.hint.emphasis')}</em>
        {t('settings.bookPaths.hint.after')}
      </SettingsHint>
    </SettingsSection>
  )
}
