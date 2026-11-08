// Due versioni dello stesso brano, affiancate, con le differenze in luce.
//
// **A sinistra l'originale di Kolibre, a destra quella che sta nel vault.**
// L'ordine è quello e non un altro: si legge da sinistra a destra, quindi a
// sinistra sta da cosa si parte e a destra dove si è arrivati.
//
// Le due colonne non si limitano a stare vicine: quello che è cambiato è
// evidenziato parola per parola (vedi `lib/differenzaDiParole.ts`), perché
// su tre righe di prosa la differenza può essere una virgola e cercarla a
// occhio è il modo di non trovarla.
import { useMemo } from 'react'
import { useLingua } from '@/lib/i18n'
import { differenzaDiParole, nessunaDifferenza } from '@/lib/differenzaDiParole'

export function ConfrontoDeiDueTesti({
  inKolibre,
  nelVault,
  evidenzia,
}: {
  inKolibre?: string | null
  nelVault?: string | null
  /** Quale delle due va messa in risalto, quando una scelta è già stata fatta. */
  evidenzia?: 'kolibre' | 'vault' | null
}) {
  const { t } = useLingua()
  const pezzi = useMemo(() => differenzaDiParole(inKolibre, nelVault), [inKolibre, nelVault])
  const identici = nessunaDifferenza(pezzi)

  return (
    <div>
      <div className="grid gap-2.5 sm:grid-cols-2">
        <Colonna
          titolo={t('appunti.conflitto.inKolibre')}
          vuoto={!inKolibre}
          evidenziato={evidenzia === 'kolibre'}
          pezzi={pezzi.filter((p) => p.tipo !== 'aggiunto')}
          marca="tolto"
        />
        <Colonna
          titolo={t('appunti.conflitto.nelVault')}
          vuoto={!nelVault}
          evidenziato={evidenzia === 'vault'}
          pezzi={pezzi.filter((p) => p.tipo !== 'tolto')}
          marca="aggiunto"
        />
      </div>
      {/* Due testi che risultano identici dopo tutto questo meritano una
          riga: vuol dire che la differenza sta negli spazi o che il plugin
          non ha mandato una delle due versioni, e senza dirlo sembrerebbe
          che il confronto non funzioni. */}
      {identici && inKolibre && nelVault && (
        <p className="mt-1.5 text-[12px] text-muted-foreground">{t('appunti.confronto.identici')}</p>
      )}
    </div>
  )
}

function Colonna({
  titolo,
  pezzi,
  marca,
  vuoto,
  evidenziato,
}: {
  titolo: string
  pezzi: { tipo: string; testo: string }[]
  marca: 'tolto' | 'aggiunto'
  vuoto: boolean
  evidenziato: boolean
}) {
  const { t } = useLingua()
  return (
    <div>
      <div className="mb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{titolo}</div>
      <div
        className={
          'whitespace-pre-wrap rounded border px-2 py-1.5 text-[13px] leading-relaxed ' +
          (evidenziato ? 'border-primary/50 bg-primary/5' : 'border-border/70 bg-muted/30')
        }
      >
        {vuoto ? (
          <span className="italic text-muted-foreground">{t('appunti.conflitto.testoMancante')}</span>
        ) : (
          pezzi.map((p, i) =>
            p.tipo === marca ? (
              <mark
                key={i}
                className={
                  'rounded-[2px] px-[1px] ' +
                  (marca === 'tolto'
                    ? 'bg-destructive/15 text-destructive'
                    : 'bg-emerald-500/20 text-emerald-800 dark:text-emerald-300')
                }
              >
                {p.testo}
              </mark>
            ) : (
              <span key={i}>{p.testo}</span>
            )
          )
        )}
      </div>
    </div>
  )
}
