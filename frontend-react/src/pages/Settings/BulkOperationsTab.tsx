import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Hash, Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { LibraryPickerButton } from '@/components/LibraryPickerButton'
import {
  SettingsFeedback,
  SettingsRow,
  SettingsSection,
} from '@/components/settings/SettingsPrimitives'
import { useLibraries } from '@/lib/queries'
import { rescanLibrary, recomputeLibraryHashes } from '@/lib/libraryToolsActions'
import { errorDetail, recomputeLibraryPageCounts } from '@/lib/librarySettingsActions'
import { BookPathsSection } from './BookPathsSection'
import { useLingua } from '@/lib/i18n'

// "Operazioni di massa" — azioni che toccano molti libri insieme.
//
// Stava nella pagina Importa come seconda tab accanto allo staging dei file
// nuovi: due lavori diversi nello stesso posto, che non c'entrano fra loro.
// Qui sta con le altre azioni sulla libreria. Rispetto alla vecchia ToolsTab
// arriva anche il ricalcolo delle pagine stimate, che prima viveva dentro
// Impostazioni ▸ Librerie mescolato alle IMPOSTAZIONI di conteggio: là resta
// la configurazione (come contare), qui l'azione (ricontale adesso, per
// un'intera libreria).
export function BulkOperationsTab() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data: libraries = [] } = useLibraries()

  const [libraryId, setLibraryId] = useState<number | null>(null)
  const library = useMemo(
    () => libraries.find((l) => l.id === libraryId) ?? libraries[0],
    [libraries, libraryId]
  )

  const [busy, setBusy] = useState<'rescan' | 'hashes' | 'pages' | null>(null)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)


  async function run(
    kind: 'rescan' | 'hashes' | 'pages',
    action: () => Promise<string>,
    fallbackError: string
  ) {
    if (!library) return
    setBusy(kind)
    setMessage(null)
    try {
      setMessage({ kind: 'ok', text: await action() })
    } catch (err) {
      setMessage({ kind: 'error', text: errorDetail(err, fallbackError) })
    } finally {
      setBusy(null)
    }
  }

  const handleRescan = () =>
    run(
      'rescan',
      async () => {
        const res = await rescanLibrary(library!.folder_name)
        await queryClient.invalidateQueries({ queryKey: ['books', library!.folder_name] })
        await queryClient.invalidateQueries({ queryKey: ['libraries'] })
        return res.imported > 0
          ? t('settings.bulkOperations.rescan.success', { count: res.imported, n: res.imported })
          : t('settings.bulkOperations.rescan.none')
      },
      t('settings.bulkOperations.rescan.error')
    )

  const handleHashes = () =>
    run(
      'hashes',
      async () => {
        const res = await recomputeLibraryHashes(library!.folder_name)
        return t('settings.bulkOperations.hashes.success', { count: res.updated, n: res.updated })
      },
      t('settings.bulkOperations.hashes.error')
    )

  const handlePages = () =>
    run(
      'pages',
      async () => {
        const res = await recomputeLibraryPageCounts(library!.folder_name)
        await queryClient.invalidateQueries({ queryKey: ['books', library!.folder_name] })
        await queryClient.invalidateQueries({ queryKey: ['libraries'] })
        return t('settings.bulkOperations.pages.success', { n: res.updated })
      },
      t('settings.bulkOperations.pages.error')
    )



  return (
    <>
      {/* Riordinata il 28/09/2026 perché l'ordine risultasse intuitivo.
          Prima era un elenco unico chiamato "Manutenzione libreria" dove
          quattro azioni molto diverse stavano in fila: cosa facesse ciascuna
          si capiva solo leggendole tutte. Ora sono raggruppate per la
          DOMANDA a cui rispondono —
          "manca qualcosa?", "i conti tornano?", "i file sono al loro
          posto?" — che è il modo in cui ci si arriva davvero, partendo da un
          sintomo e non dal nome dell'operazione.

          Quello che NON sta qui sta in Interventi, ed è la regola fissata
          il 23/09: là ciò che aspetta una decisione, qui i ricalcoli — cose
          che si possono rifare all'infinito senza che nessuno debba
          scegliere niente. */}
      <SettingsSection label={t('settings.bulkOperations.scope.label')}>
        <SettingsRow
          name={t('settings.bulkOperations.scope.library')}
          description={t('settings.bulkOperations.scope.description')}
          last
        >
          <LibraryPickerButton libraries={libraries} value={library} onChange={setLibraryId} />
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        label={t('settings.bulkOperations.missing.label')}
        description={t('settings.bulkOperations.missing.description')}
      >
        <SettingsRow
          name={t('settings.bulkOperations.rescan.name')}
          description={t('settings.bulkOperations.rescan.description')}
          last
        >
          <Button variant="outline" size="sm" disabled={busy !== null || !library} onClick={() => void handleRescan()}>
            {busy === 'rescan' ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
            {t('settings.bulkOperations.rescan.button')}
          </Button>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        label={t('settings.bulkOperations.mismatch.label')}
        description={t('settings.bulkOperations.mismatch.description')}
      >
        <SettingsRow
          name={t('settings.bulkOperations.hashes.name')}
          description={t('settings.bulkOperations.hashes.description')}
        >
          <Button variant="outline" size="sm" disabled={busy !== null || !library} onClick={() => void handleHashes()}>
            {busy === 'hashes' ? <Loader2 className="size-3.5 animate-spin" /> : <Hash className="size-3.5" />}
            {t('settings.bulkOperations.recalculate')}
          </Button>
        </SettingsRow>

        <SettingsRow
          name={t('settings.bulkOperations.pages.name')}
          description={t('settings.bulkOperations.pages.description')}
          last
        >
          <Button variant="outline" size="sm" disabled={busy !== null || !library} onClick={() => void handlePages()}>
            {busy === 'pages' ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
            {t('settings.bulkOperations.recalculate')}
          </Button>
        </SettingsRow>

        {message && <SettingsFeedback kind={message.kind}>{message.text}</SettingsFeedback>}
      </SettingsSection>

      <BookPathsSection />

      {/* La ricerca duplicati stava qui e se n'e' andata il 27/09/2026: da
          quando esiste il motore vero (affinita' sui metadati, poi hash, poi
          qualita') vive nella pagina Interventi, dove si possono anche
          confrontare i due file e decidere. Questa era la versione vecchia —
          confronto testuale, nessuna azione possibile — e tenerne due voleva
          dire far scegliere all'utente fra una buona e una peggiore. */}
    </>
  )
}
