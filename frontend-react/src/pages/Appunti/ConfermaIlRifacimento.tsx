// «Rifallo da zero»: la domanda prima di farlo.
//
// **Perché non è un pulsante e basta.** Rifare il file di un libro lo
// riscrive dalle note di Kolibre, e quello che hai scritto *dentro* quei
// blocchi non c'è più. È il senso del comando, non un effetto collaterale —
// ma è anche l'unica azione di questa pagina che butta via del tuo, quindi
// va detto prima e non dopo.
//
// La conferma c'era nella prima versione della pagina, in riga sotto il
// libro; riscrivendo la pagina a tabella è andata persa (06/11/2026), e con
// lei la frase che diceva cosa si perde. La verifica delle traduzioni l'ha
// trovata come chiave mai più usata: un testo che nessuno mostra è un testo
// che qualcuno non legge più.
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'

export function ConfermaIlRifacimento({
  titoloDelLibro,
  aperta,
  onChiudi,
  onConferma,
}: {
  titoloDelLibro?: string | null
  aperta: boolean
  onChiudi: () => void
  onConferma: () => void
}) {
  const { t } = useLingua()
  return (
    <Dialog open={aperta} onOpenChange={(v) => !v && onChiudi()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('appunti.rifai.titolo', { titolo: titoloDelLibro || '' })}</DialogTitle>
        </DialogHeader>
        <p className="text-[13px] leading-relaxed">{t('appunti.rifai.avviso')}</p>
        <DialogFooter>
          <Button variant="ghost" onClick={onChiudi}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              onChiudi()
              onConferma()
            }}
          >
            {t('appunti.rifai.confermo')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
