// Mettere d'accordo le tre fonti della lingua, una volta per sessione.
//
// In un file a parte e non in `i18n.tsx` per la stessa ragione delle tre
// fonti: `i18n` e' il file del tradurre, e un file che esporta un componente
// non dovrebbe esportare anche ganci e funzioni.
import { useEffect, useRef } from 'react'
import { useLingua } from './i18n'
import { decidiLaLingua, linguaDelSistema, linguaSalvata } from './linguaScelta'
import { leggiPreferenze, salvaPreferenze } from './preferenzeUtente'

/**
 * Mette d'accordo le tre fonti della lingua, una volta per sessione.
 *
 * **Perche' serve un gancio e non basta leggere il server all'avvio.** La
 * prima schermata si disegna prima che la rete risponda — e deve, altrimenti
 * ci sarebbe un lampo di inglese prima dell'italiano. Quindi si parte dalla
 * copia locale e ci si allinea dopo, quando il server dice la sua. Chi decide
 * cosa vince e' `decidiLaLingua`, che non sta qui dentro proprio perche' i
 * suoi tre casi si provano meglio in tabella che a schermo
 * (`prove/lingua_scelta.ts`).
 *
 * Va chiamato da un punto che esiste solo da entrati — oggi `Layout` — perche'
 * prima di entrare il server non ha nessuna preferenza da raccontare.
 *
 * Una volta sola: `useRef` e non una dipendenza, perche' allinearsi a ogni
 * render vorrebbe dire una richiesta per ogni cambio di pagina per sapere
 * una cosa che non cambia.
 */
export function useAllineaLaLingua(): void {
  const { lingua, allineaLingua } = useLingua()
  const giaFatto = useRef(false)
  useEffect(() => {
    if (giaFatto.current) return
    giaFatto.current = true
    void (async () => {
      const preferenze = await leggiPreferenze()
      const decisione = decidiLaLingua({
        nelBrowser: linguaSalvata(),
        sulServer: preferenze?.lingua ?? null,
        dalSistema: linguaDelSistema(),
      })
      if (decisione.daSalvareNelBrowser || decisione.lingua !== lingua) {
        allineaLingua(decisione.lingua)
      }
      if (decisione.daMandareAlServer) {
        void salvaPreferenze({ lingua: decisione.daMandareAlServer })
      }
    })()
  }, [lingua, allineaLingua])
}
