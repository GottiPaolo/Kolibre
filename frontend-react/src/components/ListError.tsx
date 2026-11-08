// Stato "non ci sono riuscito" per le liste.
//
// Prima, in tutto il frontend, `isError` compariva zero volte: ogni pagina
// gestiva "sto caricando" e "ho finito", mai il fallimento. Con il backend
// spento (o una libreria non leggibile, o un 500) la richiesta falliva e si
// finiva nel ramo "lista vuota", che mostra "Nessun libro" / "Nessun autore
// trovato" / "Nessun dispositivo configurato". Da telefono è esattamente
// quello che si vedrebbe con una libreria davvero vuota — l'app mentiva.
//
// Deliberatamente sobrio: un rigo, un motivo e un pulsante per riprovare.
// Il "server irraggiungibile" vero e proprio lo dice ConnectionStatus, una
// volta sola per tutta l'app, invece di ripeterlo in ogni lista.
import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useLingua } from '@/lib/i18n'

interface ListErrorProps {
  /** Cosa non è stato possibile caricare, al plurale: "i libri", "gli autori". */
  what: string
  onRetry?: () => void
}

export function ListError({ what, onRetry }: ListErrorProps) {
  const { t } = useLingua()
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <AlertTriangle className="size-6 text-destructive" />
      <div>
        <p className="text-[14px] font-medium">{t('common.listError.message', { what })}</p>
        <p className="mt-1 text-[13px] text-muted-foreground">
          {t('common.listError.hint')}
        </p>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  )
}
