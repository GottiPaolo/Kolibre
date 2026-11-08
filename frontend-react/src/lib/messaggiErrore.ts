import { t } from './i18n'
// Cosa dire quando una richiesta non riesce.
//
// Scelta del 28/09/2026: invece di dare «errore» si dice all'utente che NON
// ha i permessi per fare qualcosa. La differenza non è di tono: "errore"
// descrive il programma, "non hai il permesso" descrive la situazione — e
// solo il secondo dice anche cosa fare (chiedere a qualcuno, o smettere di
// provare).
//
// Il backend il messaggio giusto lo manda già: ogni rifiuto per permessi
// risponde 403 con un `detail` scritto in italiano ("Non puoi modificare la
// biblioteca 'Classici'."). Quello che mancava era usarlo: metà dei punti di
// chiamata scriveva un proprio "Errore durante…" e buttava via il detail.

/** Il corpo d'errore che FastAPI restituisce: `{"detail": "..."}`. */
function dettaglio(err: unknown): string | null {
  if (err && typeof err === 'object' && 'detail' in err) {
    const d = (err as { detail?: unknown }).detail
    if (typeof d === 'string' && d.trim()) return d
    // Gli errori di validazione di FastAPI hanno un detail a lista: non è
    // roba da mostrare a una persona, e fingere di no sarebbe peggio.
  }
  return null
}

/**
 * Il messaggio da mostrare.
 *
 * `stato` è opzionale ma vale la pena passarlo dove si ha
 * (`response.status` di openapi-fetch): senza `detail`, è l'unica cosa che
 * distingue "non ti è permesso" da "è andato storto".
 */
export function messaggioErrore(err: unknown, ripiego: string, stato?: number): string {
  const detto = dettaglio(err)
  if (detto) return detto
  // Da catalogo e non letterali: e' il modulo da cui passano tutti i messaggi
  // d'errore del frontend, quindi queste tre frasi comparivano in italiano in
  // un'interfaccia inglese ogni volta che il backend rispondeva senza
  // `detail`. (Il `detail` del backend e' italiano per scelta documentata e
  // non si risolve da qui.)
  if (stato === 403) return t('common.error.forbidden')
  if (stato === 401) return t('common.error.sessionExpired')
  if (stato === 404) return t('common.error.notFound')
  return ripiego
}
