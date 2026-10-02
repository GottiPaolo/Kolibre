import { useSetPageHeader } from '@/lib/pageHeaderContext'
import { useLingua } from '@/lib/i18n'

// Pagina segnaposto — sostituita una per una durante la migrazione
// (Fase 1+). Nessuna logica: serve solo perché ogni pagina abbia già un URL
// vero da subito (react-router), invece di aspettare che tutte le pagine
// siano pronte prima di introdurre il routing.
export function Placeholder({ title }: { title: string }) {
  const { t } = useLingua()
  useSetPageHeader(title)
  return (
    <div>
      <h1 className="font-serif text-2xl font-semibold">{title}</h1>
      <p className="mt-2 text-[13px] text-muted-foreground">{t('common.placeholder.comingSoon')}</p>
    </div>
  )
}
