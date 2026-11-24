import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, BookOpen, Download, ExternalLink, Loader2, Pencil, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { formatBytes } from '@/lib/format'
import { withBackendUrl } from '@/lib/api'
import type { IngestedBook } from '@/types/ingest'
import type { Library } from '@/types/library'
import { LibraryPickerButton } from '@/components/LibraryPickerButton'
import type { IngestDuplicato } from '@/lib/ingestQueries'
import { useLingua } from '@/lib/i18n'
import { useMe } from '@/lib/settingsActions'
import { DettaglioQualita, PunteggioQualita } from '@/components/Qualita'
import type { RisultatoQualita } from '@/lib/qualitaActions'

interface IngestCardProps {
  item: IngestedBook
  destLibrary: Library | undefined
  libraries: Library[]
  onChangeDestLibrary: (id: number) => void
  onOpenFile: () => void
  // Scarica il file come sta sul disco del server. E' una cosa diversa da
  // «Apri»: quello lo mostra dentro Kolibre (nel lettore, se e' un formato
  // che il lettore conosce), questo se lo porta via — per guardarlo con un
  // altro programma, o per tenerselo prima di scartarlo.
  onDownloadFile: () => void
  onEditMetadata: () => void
  onImport: () => void
  onDiscard: () => void
  importing: boolean
  discarding: boolean
  // Libri della biblioteca di destinazione che somigliano a questo file.
  // Avviso, non blocco: un doppione vero e un'edizione diversa dello stesso
  // titolo si somigliano allo stesso modo, e decidere tocca a chi guarda.
  duplicati?: IngestDuplicato[]
}

export function IngestCard({
  item,
  destLibrary,
  libraries,
  onChangeDestLibrary,
  onOpenFile,
  onDownloadFile,
  onEditMetadata,
  onImport,
  onDiscard,
  importing,
  discarding,
  duplicati,
}: IngestCardProps) {
  const { t } = useLingua()
  // Il proprietario del file si mostra solo all'amministratore (21/11/2026):
  // è l'unico che vede le righe di tutti, quindi l'unico per cui la
  // distinzione dice qualcosa — un utente normale vede già solo le sue.
  const { data: me } = useMe()
  // Il dettaglio della qualità si apre su richiesta: qui si sta scegliendo
  // se importare un file, e il numero basta per quasi tutti. Chi deve
  // scegliere fra due versioni dello stesso libro apre e guarda da dove
  // viene quel numero.
  const [qualitaAperta, setQualitaAperta] = useState(false)
  const qualita = item.qualita as RisultatoQualita | null | undefined
  return (
    <div className="flex items-start gap-4 rounded-lg border border-border bg-card p-3">
      {/* Copertina reale solo per EPUB con cover-image nel manifest OPF
          (vedi services/metadata_parser.py) — placeholder generico altrimenti
          (PDF, o un EPUB senza copertina propria). */}
      <div className="flex aspect-[2/3] w-14 shrink-0 items-center justify-center overflow-hidden rounded border border-border bg-muted text-muted-foreground">
        {item.cover_url ? (
          <img src={withBackendUrl(item.cover_url)} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <BookOpen className="size-5" />
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="truncate font-serif text-[15px] font-semibold">{item.title}</div>
        <div className="truncate text-[13px] text-muted-foreground">{t('ingest.card.byAuthor', { author: item.author })}</div>
        <div className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted-foreground">
          {/* La voce senza file dice cos'è, al posto di formato e peso:
              «0 B» sembrerebbe un file rotto, e non lo è. */}
          {item.record_only ? (
            <span className="rounded border border-border px-1 py-0.5 font-medium italic">
              {t('library.card.soloScheda')}
            </span>
          ) : (
            <>
              {item.formats.map((fmt) => (
                <span key={fmt} className="rounded border border-border px-1 py-0.5 font-medium">
                  {fmt}
                </span>
              ))}
              <span>{formatBytes(item.size)}</span>
              {/* Formato fuori dalla lista di Kolibre (23/11/2026): la voce
                  compare apposta — così la si vede e la si scarta dal sito —
                  ma non si può importare. */}
              {!item.supported && (
                <span className="rounded border border-destructive/50 px-1 py-0.5 font-medium text-destructive">
                  {t('ingest.card.unsupportedBadge')}
                </span>
              )}
            </>
          )}
          {/* Le pagine, contate in sottofondo appena il file è arrivato
              (come la qualità): servono a scegliere fra due copie simili
              prima di importare. Per un formato che non si sa leggere non
              ci saranno mai. */}
          {item.pages != null && (
            <>
              <span className="text-muted-foreground/60">·</span>
              <span>{t('ingest.card.pagesN', { n: item.pages })}</span>
            </>
          )}
          {/* Voce da ISBN: titolo, autore e copertina li sta cercando il
              server in sottofondo (24/11/2026). L'elenco si rinfresca da
              solo finché ce n'è una (useIngestPage). */}
          {item.in_ricerca && (
            <>
              <span className="text-muted-foreground/60">·</span>
              <span className="italic">{t('ingest.card.inRicerca')}</span>
            </>
          )}
          {/* Proprietario (solo per l'admin): «senza proprietario» sono le
              righe di prima della colonna, o i file messi a mano nella
              radice di ingest — mai attribuiti per deduzione. */}
          {me?.is_admin && (
            <>
              <span className="text-muted-foreground/60">·</span>
              <span>
                {item.owner_username
                  ? t('ingest.card.ownerLabel', { owner: item.owner_username })
                  : t('ingest.card.ownerNone')}
              </span>
            </>
          )}
          {/* La qualità del file, misurata appena il file è arrivato. Per un
              PDF non c'è e non ci sarà: si misurano solo gli EPUB. */}
          {item.qualita_punteggio != null && (
            <>
              <span className="text-muted-foreground/60">·</span>
              <span>{t('ingest.card.qualitaLabel')}</span>
              <PunteggioQualita punteggio={item.qualita_punteggio} pronto={qualita?.pronto} />
              <button
                type="button"
                onClick={() => setQualitaAperta((a) => !a)}
                className="text-primary hover:underline"
              >
                {qualitaAperta ? t('qualita.nascondiButton') : t('qualita.dettagliButton')}
              </button>
            </>
          )}
        </div>
        {qualitaAperta && qualita && (
          <div className="mt-1 rounded border border-border bg-muted/30 p-2">
            <DettaglioQualita risultato={qualita} />
          </div>
        )}
        {duplicati && duplicati.length > 0 && (
          <div className="mt-0.5 flex items-start gap-1.5 text-[11.5px] text-[var(--warning)]">
            <AlertTriangle className="mt-px size-3.5 shrink-0" />
            <span className="text-muted-foreground">
              {t('ingest.card.maybeAlreadyHave')}{' '}
              <span className="text-foreground">
                {/* Formati, pagine e qualità del libro già in casa:
                    accostati al file qui sopra sono il metro per scegliere
                    quale copia tenere. Il titolo si APRE (22/11/2026,
                    spunto di Paolo): porta al dettaglio del doppione, dove
                    la sua qualità si guarda per intero nel pannello. */}
                {duplicati.map((d, i) => {
                  const dentro = [
                    d.formats.length ? d.formats.join(', ') : null,
                    d.pages != null ? t('ingest.card.pagesN', { n: d.pages }) : null,
                    d.qualita_punteggio != null
                      ? `${t('ingest.card.qualitaLabel')} ${d.qualita_punteggio}`
                      : null,
                  ].filter(Boolean).join(', ')
                  return (
                    <Fragment key={d.id}>
                      {i > 0 && ' · '}
                      <Link
                        to={`/libri/${d.id}?library=${encodeURIComponent(destLibrary?.folder_name ?? '')}`}
                        className="underline decoration-dotted underline-offset-2 hover:text-primary"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {d.title}
                      </Link>
                      {dentro ? ` (${dentro})` : ''}
                    </Fragment>
                  )
                })}
              </span>
              {t('ingest.card.importAnywayHint')}
            </span>
          </div>
        )}

        <div className="mt-1 flex items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground">{t('ingest.card.destinationLabel')}</span>
          <LibraryPickerButton libraries={libraries} value={destLibrary} onChange={onChangeDestLibrary} size="sm" />
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-1.5">
        {/* Una voce senza file (record_only) non ha niente da aprire o
            scaricare: i due bottoni non ci sono, invece di fallire. */}
        {!item.record_only && (
          <>
            <Button variant="outline" size="sm" onClick={onOpenFile} title={t('ingest.card.openFileTitle')}>
              <ExternalLink className="size-3.5" />
              {t('ingest.card.openFileButton')}
            </Button>
            <Button variant="outline" size="sm" onClick={onDownloadFile} title={t('ingest.card.downloadTitle')}>
              <Download className="size-3.5" />
              {t('ingest.card.downloadButton')}
            </Button>
          </>
        )}
        <Button variant="outline" size="sm" onClick={onEditMetadata}>
          <Pencil className="size-3.5" />
          {t('ingest.card.metadataButton')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onDiscard}
          disabled={discarding || importing}
          className="text-destructive hover:text-destructive"
          title={t('ingest.card.discardTitle')}
        >
          {discarding ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
          {t('ingest.card.discardButton')}
        </Button>
        {/* Un formato fuori lista non si importa: il bottone lo dice al
            passaggio del mouse invece di sparire — il divieto si capisce
            solo se si vede. Il rifiuto vero sta comunque sul server. */}
        <div title={!item.supported ? t('ingest.card.unsupportedHint') : undefined}>
          <Button size="sm" onClick={onImport} disabled={importing || !destLibrary || !item.supported}>
            {importing ? <Loader2 className="size-3.5 animate-spin" /> : null}
            {t('ingest.card.importButton')}
          </Button>
        </div>
      </div>
    </div>
  )
}
