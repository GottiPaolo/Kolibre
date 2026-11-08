// Quali voci della barra laterale si vedono, e perché.
//
// **Due regole, e una vince sull'altra.**
//
// 1. Una voce che oggi non porta da nessuna parte non si mostra. «Appunti»
//    esiste perché un client (il plugin Obsidian) racconta cosa tiene nel
//    vault: se nessun client ha mai raccontato niente, quella pagina non ha
//    nulla da dire — come Dispositivi non ha senso per chi non ha lettori.
// 2. **Ma una voce che hai messo tu**, da Impostazioni ▸ Aspetto, resta.
//
// La seconda vince sempre, e la regola l'ha scritta Paolo il 06/11/2026:
// «se una persona si mette la pagina appunti nell'aspetto delle impostazioni
// allora questa deve rimanere visibile». Era appena succeso il contrario —
// per un difetto del server, ma quello che si vede in quel caso è un
// programma che non dà ascolto. L'automatismo serve a non proporti una
// stanza vuota, non a chiuderti una porta che hai aperto tu.
//
// **Perché sta in un file suo, senza dipendenze.** Queste due funzioni non
// chiedono niente a nessuno: una legge una chiave di `localStorage`, l'altra
// confronta due insiemi. Tenendole qui si possono provare per quello che
// sono (`prove/voci_della_barra.ts`), invece di dover trascinare React e il
// client delle API dentro una prova che riguarda due insiemi. Quello che è
// difficile da provare, in una barra laterale, non dà errori: dà una voce in
// meno, e chi l'ha persa non sa nemmeno di doverla cercare.
import { leggiLocale } from './memoriaLocale'

/** Dove vive il layout scelto dalla persona. Lo legge anche `sidebarLayout.ts`. */
export const CHIAVE_LAYOUT = 'kolibre_sidebar_layout_v1'

/**
 * Le voci che la persona ha scelto **lei**, aprendo il costruttore.
 *
 * Si riconoscono da una cosa sola: esiste un layout salvato. Quel layout si
 * scrive solo quando si tocca Impostazioni ▸ Aspetto, quindi quello che c'è
 * dentro è una scelta e non un valore di fabbrica.
 *
 * `idValidi` serve a non prendere per scelta un id che non è una pagina:
 * un layout salvato da una versione futura, o manomesso a mano, non deve far
 * comparire voci che non esistono.
 */
export function vociScelteAMano<T extends string>(idValidi: readonly T[]): Set<T> {
  try {
    const raw = leggiLocale(CHIAVE_LAYOUT)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return new Set()
    const validi = new Set<string>(idValidi)
    return new Set(
      parsed
        .filter((e) => e && e.type === 'page' && typeof e.id === 'string' && validi.has(e.id))
        .map((e) => e.id as T)
    )
  } catch {
    return new Set()
  }
}

/**
 * Quali voci nascondere, date le due regole.
 *
 * **Nel dubbio si mostra**: finché la risposta del server non è arrivata, o
 * se la domanda è fallita, non si nasconde niente. Nascondere una pagina per
 * un errore di rete sarebbe peggio che mostrarne una vuota.
 */
export function vociDaNascondere<T extends string>(
  appunti: { nessunClient: boolean; inAttesa: boolean; fallita: boolean },
  scelteAMano: Set<T>
): Set<T> {
  const nascoste = new Set<T>()
  if (appunti.nessunClient && !appunti.inAttesa && !appunti.fallita) {
    nascoste.add('appunti' as T)
  }
  for (const scelta of scelteAMano) nascoste.delete(scelta)
  return nascoste
}
