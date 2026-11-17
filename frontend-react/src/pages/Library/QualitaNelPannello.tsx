// La qualità dell'EPUB nel pannello dei dettagli della Libreria.
//
// **È un campo facoltativo** (Paolo, 17/11/2026): sta fra quelli che si
// accendono e si spengono da Impostazioni ▸ Libreria, e **nasce spento**. Un
// campo nuovo che compare da sé nel pannello di tutti è esattamente la cosa
// contro cui «non fissa» sta spingendo — si accende una volta e resta.
//
// **Solo il numero, senza colore.** Il perché sta in `PunteggioQualita`: qui
// c'è un libro solo, non c'è niente con cui confrontare quel numero, e il
// colore direbbe «questo è un brutto libro» a chi sta guardando la sua scheda.
// In Interventi, dove si scorre una tabella di mille righe, il colore resta.
//
// **Il numero porta al dettaglio**, come chiede Paolo: si apre la scheda del
// libro, dove il dettaglio per parametro c'è dietro una cosa chiusa. Qui no:
// questo pannello è una colonna strettissima accanto alla tabella, e un
// elenco di dimensioni e difetti lì dentro la farebbe traboccare.
//
// **Perché è un componente e non un caso dello switch** di
// `renderQuickviewField`: quella è una funzione pura, e questo campo ha
// bisogno di un hook — la qualità non arriva col libro, si chiede a parte
// (non è nel tipo `Book`, non è fra le colonne della tabella, e l'API dei
// libri non la manda).
import { useNavigate } from 'react-router-dom'
import { PunteggioQualita } from '@/components/Qualita'
import { useQualitaDiUnLibro } from '@/lib/qualitaActions'
import { useLingua } from '@/lib/i18n'
import type { Book } from '@/types/library'

export function QualitaNelPannello({
  book,
  libraryFolder,
}: {
  book: Book
  libraryFolder: string | undefined
}) {
  const { t } = useLingua()
  const navigate = useNavigate()
  const { data, isLoading } = useQualitaDiUnLibro(libraryFolder, book.id)

  // Finché non si sa, e quando quel libro non è mai stato analizzato, la riga
  // non c'è: un «—» che compare e poi diventa un numero fa sfarfallare il
  // pannello a ogni libro che si seleziona.
  if (isLoading || !data || data.esito === 'mai') return null

  if (data.esito === 'fallita') {
    return (
      <>
        <dt className="text-muted-foreground">{t('library.detail.qualita')}</dt>
        <dd className="text-[var(--warning)]" title={data.motivo || undefined}>
          {t('library.detail.qualitaFallita')}
        </dd>
      </>
    )
  }

  return (
    <>
      <dt className="text-muted-foreground">{t('library.detail.qualita')}</dt>
      <dd>
        <button
          type="button"
          // La biblioteca viaggia nello `state`, come in tutti gli altri
          // posti che navigano a un libro — vedi il commento in
          // BookDetailPage.tsx.
          onClick={() => navigate(`/libri/${book.id}`, { state: { libraryFolder } })}
          className="hover:underline"
          title={t('library.detail.qualitaApriScheda')}
        >
          <PunteggioQualita
            punteggio={data.risultato.punteggio}
            pronto={data.risultato.pronto}
            senzaColore
          />
        </button>
      </dd>
    </>
  )
}
