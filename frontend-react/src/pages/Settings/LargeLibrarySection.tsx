// I due limiti delle biblioteche grandi, dichiarati invece che nascosti.
//
// Sono in Sistema e non dentro la singola libreria perche' riguardano il
// comportamento del server, non il contenuto di una biblioteca: la soglia
// dipende da quanto e' veloce la macchina, e il tetto dell'indice dallo
// spazio del disco.
import { useEffect, useState } from 'react'

import { SettingsInput, SettingsRow, SettingsSection } from '@/components/settings/SettingsPrimitives'
import { toast } from '@/lib/toast'
import {
  getAuthorsPagination,
  getFulltextLimitGb,
  getIngestPagination,
  getLibraryPagination,
  setAuthorsPagination,
  setFulltextLimitGb,
  setIngestPagination,
  setLibraryPagination,
  type LibraryPagination,
} from '@/lib/opdsSettingsActions'
import { numero, useLingua, type Valori } from '@/lib/i18n'

// Funzione e non oggetto costante: deve ricalcolarsi al cambio lingua, come
// fixedColumnLabels in lib/libraryColumns.ts.
function modi(t: (chiave: string, valori?: Valori) => string): Array<{ id: LibraryPagination['mode']; label: string; spiega: string }> {
  return [
    { id: 'auto', label: t('settings.system.largeLibrary.mode.auto.label'), spiega: t('settings.system.largeLibrary.mode.auto.explain') },
    { id: 'always', label: t('settings.system.largeLibrary.mode.always.label'), spiega: t('settings.system.largeLibrary.mode.always.explain') },
    { id: 'never', label: t('settings.system.largeLibrary.mode.never.label'), spiega: t('settings.system.largeLibrary.mode.never.explain') },
  ]
}

export function LargeLibrarySection() {
  const { t } = useLingua()
  const MODI = modi(t)
  const [pag, setPag] = useState<LibraryPagination | null>(null)
  const [ing, setIng] = useState<LibraryPagination | null>(null)
  const [aut, setAut] = useState<LibraryPagination | null>(null)
  const [tetto, setTetto] = useState<string>('')

  useEffect(() => {
    void getLibraryPagination().then(setPag)
    void getIngestPagination().then(setIng)
    void getAuthorsPagination().then(setAut)
    void getFulltextLimitGb().then((g) => setTetto(String(g)))
  }, [])

  async function salvaIngest(next: Partial<LibraryPagination>) {
    if (!ing) return
    const precedente = ing
    setIng({ ...ing, ...next } as LibraryPagination)
    try {
      setIng(await setIngestPagination({ ...ing, ...next }))
    } catch {
      setIng(precedente)
      toast.error(t('settings.system.largeLibrary.saveGenericError'))
    }
  }

  async function salvaAutori(next: Partial<LibraryPagination>) {
    if (!aut) return
    const precedente = aut
    setAut({ ...aut, ...next } as LibraryPagination)
    try {
      setAut(await setAuthorsPagination({ ...aut, ...next }))
    } catch {
      setAut(precedente)
      toast.error(t('settings.system.largeLibrary.saveGenericError'))
    }
  }

  async function salvaPaginazione(next: Partial<LibraryPagination>) {
    if (!pag) return
    const precedente = pag
    setPag({ ...pag, ...next } as LibraryPagination)
    try {
      setPag(await setLibraryPagination({ ...pag, ...next }))
    } catch {
      setPag(precedente)
      toast.error(t('settings.system.largeLibrary.saveGenericError'))
    }
  }

  async function salvaTetto() {
    const n = Number(tetto.replace(',', '.'))
    if (Number.isNaN(n) || n < 0) {
      toast.error(t('settings.system.largeLibrary.capInvalid'))
      return
    }
    try {
      setTetto(String(await setFulltextLimitGb(n)))
    } catch {
      toast.error(t('settings.system.largeLibrary.capGenericError'))
    }
  }

  return (
    <SettingsSection
      label={t('settings.system.largeLibrary.label')}
      description={t('settings.system.largeLibrary.description')}
    >
      <SettingsRow
        name={t('settings.system.largeLibrary.libraryPagination.name')}
        description={
          pag?.mode === 'auto'
            ? t('settings.system.largeLibrary.libraryPagination.auto', { threshold: numero(pag.threshold) })
            : pag?.mode === 'always'
              ? t('settings.system.largeLibrary.libraryPagination.always')
              : t('settings.system.largeLibrary.libraryPagination.never')
        }
        stack
      >
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {MODI.map((m) => (
            <button
              key={m.id}
              type="button"
              title={m.spiega}
              onClick={() => void salvaPaginazione({ mode: m.id })}
              className={
                'rounded-md border px-2.5 py-1 text-[12px] ' +
                (pag?.mode === m.id
                  ? 'border-primary bg-primary/15 text-primary'
                  : 'border-border hover:bg-accent/40')
              }
            >
              {m.label}
            </button>
          ))}
        </div>
      </SettingsRow>

      {pag?.mode === 'auto' && (
        <SettingsRow name={t('settings.system.largeLibrary.thresholdName')} description={t('settings.system.largeLibrary.thresholdDescription')}>
          <SettingsInput
            value={String(pag.threshold)}
            ariaLabel={t('settings.system.largeLibrary.thresholdAriaLabel')}
            className="w-28 text-right"
            onChange={(v) => setPag({ ...pag, threshold: Number(v) || 0 })}
            type="number"
          />
        </SettingsRow>
      )}

      {pag && pag.mode !== 'never' && (
        <SettingsRow name={t('settings.system.largeLibrary.pageSizeName')} description={t('settings.system.largeLibrary.pageSizeDescription')}>
          <SettingsInput
            value={String(pag.page_size)}
            ariaLabel={t('settings.system.largeLibrary.pageSizeAriaLabel')}
            className="w-28 text-right"
            onChange={(v) => setPag({ ...pag, page_size: Number(v) || 0 })}
            type="number"
          />
        </SettingsRow>
      )}

      {pag && pag.mode !== 'never' && (
        <SettingsRow name="" description="" last>
          <button
            type="button"
            onClick={() => void salvaPaginazione({})}
            className="rounded-md border border-border px-2.5 py-1 text-[12px] hover:bg-accent/40"
          >
            {t('settings.system.largeLibrary.saveThresholdAndSize')}
          </button>
        </SettingsRow>
      )}

      <SettingsRow
        name={t('settings.system.largeLibrary.ingestPagination.name')}
        description={
          ing?.mode === 'never'
            ? t('settings.system.largeLibrary.ingestPagination.never')
            : ing?.mode === 'always'
              ? t('settings.system.largeLibrary.ingestPagination.always')
              : t('settings.system.largeLibrary.ingestPagination.auto', {
                  threshold: numero(ing?.threshold ?? 200),
                  pageSize: numero(ing?.page_size ?? 100),
                })
        }
        stack
      >
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {MODI.map((m) => (
            <button
              key={m.id}
              type="button"
              title={m.spiega}
              onClick={() => void salvaIngest({ mode: m.id })}
              className={
                'rounded-md border px-2.5 py-1 text-[12px] ' +
                (ing?.mode === m.id ? 'border-primary bg-primary/15 text-primary' : 'border-border hover:bg-accent/40')
              }
            >
              {m.label}
            </button>
          ))}
          {ing?.mode === 'auto' && (
            <>
              <SettingsInput
                value={String(ing.threshold)}
                ariaLabel={t('settings.system.largeLibrary.ingestPagination.thresholdAriaLabel')}
                className="w-24 text-right"
                onChange={(v) => setIng({ ...ing, threshold: Number(v) || 0 })}
              />
              <button
                type="button"
                onClick={() => void salvaIngest({})}
                className="rounded-md border border-border px-2.5 py-1 text-[12px] hover:bg-accent/40"
              >
                {t('settings.system.largeLibrary.saveThreshold')}
              </button>
            </>
          )}
        </div>
      </SettingsRow>

      <SettingsRow
        name={t('settings.system.largeLibrary.authorsPagination.name')}
        description={
          aut?.mode === 'never'
            ? t('settings.system.largeLibrary.authorsPagination.never')
            : aut?.mode === 'always'
              ? t('settings.system.largeLibrary.authorsPagination.always')
              : t('settings.system.largeLibrary.authorsPagination.auto', {
                  threshold: numero(aut?.threshold ?? 500),
                  pageSize: numero(aut?.page_size ?? 200),
                })
        }
        stack
      >
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {MODI.map((m) => (
            <button
              key={m.id}
              type="button"
              title={m.spiega}
              onClick={() => void salvaAutori({ mode: m.id })}
              className={
                'rounded-md border px-2.5 py-1 text-[12px] ' +
                (aut?.mode === m.id ? 'border-primary bg-primary/15 text-primary' : 'border-border hover:bg-accent/40')
              }
            >
              {m.label}
            </button>
          ))}
          {aut?.mode === 'auto' && (
            <>
              <SettingsInput
                value={String(aut.threshold)}
                ariaLabel={t('settings.system.largeLibrary.authorsPagination.thresholdAriaLabel')}
                className="w-24 text-right"
                onChange={(v) => setAut({ ...aut, threshold: Number(v) || 0 })}
              />
              <button
                type="button"
                onClick={() => void salvaAutori({})}
                className="rounded-md border border-border px-2.5 py-1 text-[12px] hover:bg-accent/40"
              >
                {t('settings.system.largeLibrary.saveThreshold')}
              </button>
            </>
          )}
        </div>
      </SettingsRow>

      <SettingsRow
        name={t('settings.system.largeLibrary.fulltextCap.name')}
        description={t('settings.system.largeLibrary.fulltextCap.description')}
        last
      >
        <div className="flex items-center gap-2">
          <SettingsInput
            value={tetto}
            ariaLabel={t('settings.system.largeLibrary.fulltextCap.ariaLabel')}
            className="w-24 text-right"
            onChange={setTetto}
          />
          <span className="text-[12px] text-muted-foreground">GB</span>
          <button
            type="button"
            onClick={() => void salvaTetto()}
            className="rounded-md border border-border px-2.5 py-1 text-[12px] hover:bg-accent/40"
          >
            {t('common.save')}
          </button>
        </div>
      </SettingsRow>
    </SettingsSection>
  )
}
