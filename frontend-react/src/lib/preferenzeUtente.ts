// Le preferenze della persona, quelle che stanno sul server.
//
// Sono poche di proposito: il criterio sta in
// `docs/inventario-regole-nel-browser.md` e in una riga è *se due client
// dessero risposte diverse, uno dei due sarebbe in torto?* Oggi passa quella
// prova solo la lingua. La dimensione del testo nel lettore, la larghezza di
// una colonna, il formato della data restano in questo browser, perché
// dipendono dallo schermo e dal sistema — e imporre a un telefono le scelte
// fatte su un portatile sarebbe un peggioramento, non un miglioramento.
import { api } from './api'
import type { Lingua } from './linguaScelta'

export interface Preferenze {
  /** `null` vuol dire **non ha scelto**, non «il difetto»: vedi linguaScelta. */
  lingua: Lingua | null
}

/**
 * Le preferenze della persona, o `null` se non si è potuto chiedere.
 *
 * **Perché `null` e non un errore.** Questa chiamata parte all'avvio, cioè
 * nel momento in cui si potrebbe non essere entrati, la rete potrebbe non
 * esserci, o il server potrebbe essere una versione che non conosce ancora
 * questo indirizzo. Nessuno di quei casi è un guasto da mostrare: vogliono
 * dire soltanto «il server non ha niente da dire sulla lingua», e la
 * decisione (`decidiLaLingua`) sa già cosa fare quando il server tace.
 */
export async function leggiPreferenze(): Promise<Preferenze | null> {
  try {
    const { data, error } = await api.GET('/api/users/me/preferenze')
    if (error) return null
    const lingua = (data as unknown as { lingua?: unknown } | null)?.lingua
    return { lingua: lingua === 'it' || lingua === 'en' ? lingua : null }
  } catch {
    return null
  }
}

/**
 * Salva una preferenza, senza far aspettare chi ha cliccato.
 *
 * Non si attende e non si mostra niente: la scelta è **già** applicata in
 * locale quando questa parte, e se il salvataggio non riesce il peggio che
 * succede è che un altro client non la sappia ancora. Bloccare l'interfaccia
 * su una scrittura che non cambia quello che si vede sarebbe pagare un
 * viaggio in rete per niente.
 */
export async function salvaPreferenze(cambi: Partial<Preferenze>): Promise<void> {
  try {
    await api.PUT('/api/users/me/preferenze', { body: cambi as Record<string, unknown> })
  } catch {
    // Vedi sopra: non c'è niente da dire a chi ha cliccato.
  }
}
