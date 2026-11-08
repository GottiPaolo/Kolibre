import { useBookActions } from '@/lib/bookActionsContext'
import { useLingua } from '@/lib/i18n'

// Un valore di metadato che porta alla libreria filtrata su di lui.
//
// Stesso aspetto del testo normale finche' non ci si passa sopra: la scheda
// di un libro resta una scheda da leggere, non una fila di collegamenti.
//
// Vive qui e non dentro una pagina perche' lo usano in due: la scheda
// estesa del libro e il pannello laterale della libreria. Erano la stessa
// riga di metadati scritta due volte, ed era gia' successo che una delle
// due restasse indietro.
export function ValoreFiltrabile({ campo, valore }: { campo: string; valore: string }) {
  const actions = useBookActions()
  const { t } = useLingua()
  return (
    <button
      onClick={() => actions.filterByFieldValue(campo, valore)}
      title={t('library.filterableValue.title')}
      className="text-left hover:text-primary hover:underline"
    >
      {valore}
    </button>
  )
}

// L'elenco dei tag, uno cliccabile per volta. Metterli in un blocco solo
// renderebbe cliccabile "economia, filosofia" come se fosse un valore
// unico, che non e' un filtro che esiste.
export function TagFiltrabili({ tags }: { tags: string[] }) {
  return (
    <>
      {tags.map((tag, idx) => (
        <span key={tag}>
          <ValoreFiltrabile campo="tags" valore={tag} />
          {idx < tags.length - 1 && ', '}
        </span>
      ))}
    </>
  )
}
