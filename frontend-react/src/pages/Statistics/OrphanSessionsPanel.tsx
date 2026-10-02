import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Link2, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useOrphanSessions, type OrphanReadingSessionRow } from '@/lib/statsQueries'
import { pairOrphanSessions, discardOrphanSessions } from '@/lib/statsActions'
import { useLingua, type Valori } from '@/lib/i18n'
import { formatDurationHuman } from './statsCompute'
import { BookPickerDialog } from '@/pages/Devices/BookPickerDialog'
import type { Book } from '@/types/library'

type Traduci = (chiave: string, valori?: Valori) => string

interface OrphanGroup {
  md5: string
  title: string
  authors: string
  sessionCount: number
  totalDuration: number
  lastSeen: string
}

// Le 866 righe grezze di OrphanReadingSession (una per sessione) sono
// inutili da mostrare una a una — quasi sempre sono decine/centinaia di
// sessioni per lo stesso libro (lo stesso md5 non risolto si ripete ad ogni
// sync). Un utente deve accoppiare per LIBRO, non per sessione: si
// raggruppa qui, client-side, esattamente come chartBuilderCompute.ts fa
// per le dimensioni categoriche — nessun endpoint di aggregazione dedicato,
// i dati sono già tutti scaricati da useOrphanSessions.
function groupByMd5(sessions: OrphanReadingSessionRow[], t: Traduci): OrphanGroup[] {
  const groups = new Map<string, OrphanGroup>()
  for (const s of sessions) {
    const g = groups.get(s.md5)
    if (g) {
      g.sessionCount += 1
      g.totalDuration += s.duration
      if (s.start_time > g.lastSeen) g.lastSeen = s.start_time
    } else {
      groups.set(s.md5, {
        md5: s.md5,
        title: s.title || t('stats.orphanSessions.unknownTitle'),
        authors: s.authors || t('stats.orphanSessions.unknownAuthor'),
        sessionCount: 1,
        totalDuration: s.duration,
        lastSeen: s.start_time,
      })
    }
  }
  return Array.from(groups.values()).sort((a, b) => b.totalDuration - a.totalDuration)
}

// Banner + dialog di gestione per le sessioni di lettura "orfane" (vedi
// backend/app/models.py::OrphanReadingSession) — un md5 riportato da un
// device KOReader che non risolve a nessun libro reale, spesso perché il
// file server-side è stato riscritto (embed pagine/copertina/metadati)
// dopo che il device aveva già calcolato il proprio hash sulla copia
// vecchia (vedi BookHashHistory) E quel cambiamento è avvenuto PRIMA che
// quel meccanismo di storico esistesse — in quel caso non c'è più nulla da
// recuperare automaticamente, va accoppiato a mano una volta (vedi
// StatsHashPairing). Riusa BookPickerDialog, lo stesso già in uso per
// "Accoppia manualmente" nella pagina Dispositivi.
export function OrphanSessionsPanel() {
  const { t } = useLingua()
  const queryClient = useQueryClient()
  const { data } = useOrphanSessions()
  const [showManage, setShowManage] = useState(false)
  // L'intero gruppo (non solo l'md5): serve sia per il titolo del dialog sia
  // per pre-riempire la ricerca del BookPickerDialog (la barra di ricerca
  // parte di default col titolo del libro), senza ripetere un
  // groups.find() due volte per la stessa informazione.
  const [pairingGroup, setPairingGroup] = useState<OrphanGroup | null>(null)
  const [pairingError, setPairingError] = useState<string | null>(null)
  const [pairingBusy, setPairingBusy] = useState(false)
  // Bottone "Scarta" separato da pairingGroup: le due azioni non condividono
  // stato (scartare non apre il BookPickerDialog) e possono essere in corso
  // per righe diverse senza interferire.
  const [discardingMd5, setDiscardingMd5] = useState<string | null>(null)
  const [discardError, setDiscardError] = useState<string | null>(null)

  const groups = useMemo(() => groupByMd5(data?.sessions ?? [], t), [data, t])

  if (!data || data.count === 0) return null

  async function handlePick(book: Book, libraryFolder: string) {
    if (!pairingGroup) return
    setPairingBusy(true)
    setPairingError(null)
    try {
      await pairOrphanSessions(pairingGroup.md5, libraryFolder, book.id)
      setPairingGroup(null)
      queryClient.invalidateQueries({ queryKey: ['stats-orphan-sessions'] })
      queryClient.invalidateQueries({ predicate: (q) => typeof q.queryKey[0] === 'string' && q.queryKey[0].startsWith('stats-') })
    } catch {
      setPairingError(t('stats.orphanSessions.pairFailed'))
    } finally {
      setPairingBusy(false)
    }
  }

  // "Scarta": per un titolo che non va accoppiato a nessun libro (non è
  // un'ipotesi sbagliata da correggere, va solo ignorato) — permanente,
  // quindi richiede conferma esplicita prima di procedere.
  async function handleDiscard(g: OrphanGroup) {
    if (!window.confirm(t('stats.orphanSessions.discardConfirm', { title: g.title, count: g.sessionCount, n: g.sessionCount }))) {
      return
    }
    setDiscardingMd5(g.md5)
    setDiscardError(null)
    try {
      await discardOrphanSessions(g.md5)
      queryClient.invalidateQueries({ queryKey: ['stats-orphan-sessions'] })
      queryClient.invalidateQueries({ predicate: (q) => typeof q.queryKey[0] === 'string' && q.queryKey[0].startsWith('stats-') })
    } catch {
      setDiscardError(t('stats.orphanSessions.discardFailed'))
    } finally {
      setDiscardingMd5(null)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setShowManage(true)}
        className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-left text-[12.5px] text-amber-700 transition-colors hover:bg-amber-500/15 dark:text-amber-400"
      >
        <AlertTriangle className="size-4 shrink-0" />
        <span>
          {t('stats.orphanSessions.banner', {
            n: data.count,
            titles: t('stats.orphanSessions.titleCount', { count: groups.length, n: groups.length }),
          })}
        </span>
        <span className="ml-auto shrink-0 underline">{t('stats.orphanSessions.manage')}</span>
      </button>

      {showManage && (
        <Dialog open onOpenChange={(open) => !open && setShowManage(false)}>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{t('stats.orphanSessions.dialogTitle')}</DialogTitle>
            </DialogHeader>
            <p className="text-[12px] text-muted-foreground">
              {t('stats.orphanSessions.dialogInstructions')}
            </p>
            <div className="flex max-h-[55vh] flex-col gap-1.5 overflow-y-auto">
              {groups.map((g) => (
                <div key={g.md5} className="flex items-center gap-3 rounded-md border border-border bg-card p-2.5">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium">{g.title}</p>
                    <p className="truncate text-[11.5px] text-muted-foreground">
                      {t('stats.orphanSessions.sessionsSummary', {
                        authors: g.authors,
                        n: g.sessionCount,
                        duration: formatDurationHuman(g.totalDuration),
                      })}
                    </p>
                  </div>
                  <Button size="sm" variant="outline" onClick={() => setPairingGroup(g)}>
                    <Link2 className="size-3.5" />
                    {t('stats.orphanSessions.pair')}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={discardingMd5 === g.md5}
                    onClick={() => handleDiscard(g)}
                  >
                    <XCircle className="size-3.5" />
                    {t('stats.orphanSessions.discard')}
                  </Button>
                </div>
              ))}
            </div>
            {pairingError && <p className="text-[12px] text-destructive">{pairingError}</p>}
            {discardError && <p className="text-[12px] text-destructive">{discardError}</p>}
          </DialogContent>
        </Dialog>
      )}

      {pairingGroup && (
        <BookPickerDialog
          title={
            pairingBusy
              ? t('stats.orphanSessions.pairingInProgress')
              : t('stats.orphanSessions.pairDialogTitle', { title: pairingGroup.title })
          }
          onClose={() => !pairingBusy && setPairingGroup(null)}
          onSelect={handlePick}
          initialQuery={pairingGroup.title}
        />
      )}
    </>
  )
}
