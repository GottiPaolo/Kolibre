import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useLingua } from '@/lib/i18n'
import type { components } from '@/api/schema'
import type { Library } from '@/types/library'

type SchedaDaIsbn = components['schemas']['SchedaDaIsbn']

interface IsbnImportDialogProps {
  destLibrary: Library | undefined
  onClose: () => void
}

// Voci di Ingest SENZA file da uno o più ISBN (22-23/11/2026):
// l'inventario digitale di una libreria fisica — il libro sta sullo
// scaffale, qui se ne vuole la scheda. Flusso a due tempi, per scelta di
// Paolo: ogni ISBN valido diventa una voce in attesa coi metadati delle
// fonti, si rivede e si corregge come ogni arretrato, e all'importazione
// diventa la scheda Calibre senza formati. Un ISBN introvabile va in
// attesa comunque, vuoto; uno già in biblioteca pure, con l'avviso del
// libro che lo occupa — come un file doppione: si decide davanti alla
// scheda.
export function IsbnImportDialog({ destLibrary, onClose }: IsbnImportDialogProps) {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const [testo, setTesto] = useState('')
  const [lavorando, setLavorando] = useState(false)
  const [righe, setRighe] = useState<SchedaDaIsbn[] | null>(null)
  const [errore, setErrore] = useState<string | null>(null)

  async function invia(isbns: string[]) {
    if (!destLibrary || isbns.length === 0) return
    setLavorando(true)
    setErrore(null)
    try {
      const { data, error } = await api.POST('/api/kolibre/ingest/isbn', {
        body: { isbns, library: destLibrary.folder_name },
      })
      if (error) throw error
      setRighe(data.rows)
      if (data.rows.some((r) => r.staged_id != null)) {
        // Le voci nuove stanno in INGEST, non in biblioteca: sono gli
        // elenchi di questa pagina a doversi aggiornare.
        void queryClient.invalidateQueries({ queryKey: ['ingest'] })
        void queryClient.invalidateQueries({ queryKey: ['ingest-page'] })
        void queryClient.invalidateQueries({ queryKey: ['ingest-pagination'] })
        void queryClient.invalidateQueries({ queryKey: ['ingest-duplicati'] })
      }
    } catch (e) {
      setErrore(e instanceof Error ? e.message : String((e as { detail?: string })?.detail ?? e))
    } finally {
      setLavorando(false)
    }
  }

  function descriviEsito(r: SchedaDaIsbn): string {
    switch (r.esito) {
      // Dal 24/11/2026 la voce nasce subito e i metadati li cerca il
      // server in sottofondo: il dialogo non aspetta le fonti.
      case 'in_ricerca': return t('ingest.isbn.esito.inRicerca')
      case 'non_valido': return t('ingest.isbn.esito.nonValido')
      case 'ripetuto': return t('ingest.isbn.esito.ripetuto')
      default: return r.esito
    }
  }

  const create = (righe ?? []).filter((r) => r.staged_id != null).length

  return (
    <Dialog open onOpenChange={(aperto) => !aperto && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('ingest.isbn.title')}</DialogTitle>
        </DialogHeader>

        <p className="text-[12.5px] text-muted-foreground">
          {t('ingest.isbn.explain', { library: destLibrary?.name ?? '—' })}
        </p>

        {righe === null ? (
          <textarea
            value={testo}
            onChange={(e) => setTesto(e.target.value)}
            placeholder={t('ingest.isbn.placeholder')}
            rows={6}
            className="w-full rounded-md border border-border bg-background p-2 font-mono text-[13px]"
            autoFocus
          />
        ) : (
          <div className="max-h-72 space-y-1 overflow-y-auto">
            {righe.map((r, i) => (
              <div key={`${r.isbn}-${i}`} className="rounded border border-border p-2 text-[12.5px]">
                <span className="font-mono">{r.isbn}</span>
                {r.title && r.staged_id != null && <span className="text-muted-foreground"> → {r.title}</span>}
                <div className={r.staged_id != null ? 'text-muted-foreground' : 'text-[var(--warning)]'}>
                  {descriviEsito(r)}
                </div>
                {/* L'avviso del doppione, non un blocco: la voce è in
                    attesa lo stesso, e si decide davanti alla scheda. */}
                {r.existing_title && (
                  <div className="text-[var(--warning)]">
                    {t('ingest.isbn.avvisoGiaInBiblioteca', { title: r.existing_title })}
                  </div>
                )}
              </div>
            ))}
            <div className="pt-1 text-[12px] text-muted-foreground">
              {t('ingest.isbn.summaryStaged', { n: create, library: destLibrary?.name ?? '' })}
            </div>
          </div>
        )}

        {errore && <p className="text-[12.5px] text-destructive">{errore}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t('common.close')}</Button>
          {righe === null && (
            <Button
              disabled={lavorando || !destLibrary || !testo.trim()}
              onClick={() => void invia(testo.split('\n').map((r) => r.trim()).filter(Boolean))}
            >
              {lavorando && <Loader2 className="size-3.5 animate-spin" />}
              {t('ingest.isbn.submit')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
