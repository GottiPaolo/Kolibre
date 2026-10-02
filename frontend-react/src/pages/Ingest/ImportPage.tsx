import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { useLingua } from '@/lib/i18n'
import { ImportTab } from './ImportTab'

// Una pagina sola: lo staging dei file da importare.
//
// Qui accanto c'era una seconda tab, "Operazioni di Massa" (rianalisi
// libreria, ricalcolo hash, ricerca duplicati): azioni di manutenzione che
// con l'importazione di file nuovi non c'entravano nulla se non il fatto di
// essere finite nello stesso posto. Ora vivono in Impostazioni ▸ Operazioni
// di massa (vedi pages/Settings/BulkOperationsTab.tsx), insieme alle altre
// azioni sulla libreria.
export function ImportPage() {
  const { t } = useLingua()
  useSetPageHeader(t('ingest.pageTitle'))
  return <ImportTab />
}
