// Ricorda dove si era arrivati scorrendo, e ci riporta tornando indietro.
//
// Il problema: aprire un autore (o un libro) e poi tornare all'elenco
// riportava sempre in cima. Su seicento autori o milleduecento libri,
// ritrovare il punto in cui si era voleva dire riscorrere tutto ogni volta.
//
// Perché un hook nostro e non <ScrollRestoration> di React Router: quel
// componente ripristina lo scroll della FINESTRA, mentre qui la finestra non
// scorre mai. Scorrono contenitori interni — il riquadro dentro <main> per
// le pagine normali, e i due contenitori virtualizzati di Libreria, che
// hanno un loro scroll indipendente. Sono tre elementi diversi, e vanno
// ricordati separatamente.
//
// La chiave è il PERCORSO, non la voce di cronologia. Prima era
// location.key, e sembrava più preciso: si ripristinava solo tornando
// davvero indietro sulla stessa voce. Il difetto e' che quasi nessuno torna
// così. Si torna alla Libreria premendo "Libreria" nella barra laterale,
// che e' una navigazione NUOVA con una chiave nuova — e allora non
// ripristinava niente, cioe' esattamente il caso che si voleva risolvere.
//
// Con il percorso come chiave, l'elenco riappare dov'era da qualunque parte
// ci si arrivi: pulsante "Torna a...", voce nella barra laterale, tasto
// indietro del browser. Il prezzo e' che anche arrivandoci da tutt'altra
// pagina si riprende dal punto di prima invece che dall'inizio — che poi e'
// come si comporta la maggior parte delle applicazioni, e nel dubbio e' il
// comportamento meno irritante: chi vuole l'inizio ci arriva scorrendo su,
// chi voleva il suo punto non deve ritrovarselo daccapo ogni volta.
import { useLayoutEffect, type RefObject } from 'react'
import { useLocation } from 'react-router-dom'

// In memoria e non in sessionStorage: è una comodità del momento, non un
// dato. Un ricaricamento della pagina riparte da capo, ed è accettabile.
// La mappa è piccola (una voce per pagina visitata) e si azzera da sola a
// ogni avvio dell'app.
const positions = new Map<string, number>()

/**
 * @param ref        contenitore che scorre
 * @param containerId nome stabile del contenitore: distingue due riquadri
 *                    scorrevoli presenti nella stessa schermata
 */
export function useScrollMemory(ref: RefObject<HTMLElement | null>, containerId: string): void {
  const { pathname } = useLocation()
  const memoryKey = `${pathname}:${containerId}`

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return

    // Il ripristino va fatto quando il contenuto ha già un'altezza: assegnare
    // uno scrollTop a un contenitore ancora vuoto non fa nulla, il browser lo
    // riporta a 0. Un paio di frame bastano quando i dati sono in cache, ma
    // non quando la lista sta ancora arrivando dalla rete — quindi si
    // riprova finché il contenitore non è abbastanza alto, con un tetto:
    // se entro un secondo non lo è, si rinuncia in silenzio invece di
    // strappare la pagina sotto le dita di chi nel frattempo sta già
    // scorrendo per conto suo.
    const saved = positions.get(memoryKey)
    let raf = 0
    let attempts = 0
    let vigilanza = 0
    const MAX_ATTEMPTS = 60 // ~1s a 60 fps
    // Finestra entro cui si continua a inseguire la posizione mentre il
    // contenuto cresce. Un secondo di tentativi a raffica non basta quando
    // l'altezza cambia DOPO: nella pagina Autori ogni scheda ha una foto, e
    // le foto arrivano quando arrivano — la lista si allunga a pezzi per
    // parecchi secondi, e chi era a meta' elenco si ritrovava piu' in alto
    // di dov'era, o in cima. Si smette al primo scorrimento vero
    // dell'utente, che ha sempre ragione (vedi onScroll).
    const FINESTRA_MS = 6000
    const scadenza = Date.now() + FINESTRA_MS
    let rinunciato = false
    // Vero mentre siamo NOI a spostare lo scorrimento. Serve perche'
    // assegnare scrollTop genera un evento di scroll identico a quello di un
    // dito: senza distinguerli, il nostro stesso ripristino verrebbe
    // scambiato per "l'utente ha scorso" e spegnerebbe subito il rimedio.
    let applicando = false

    function applica() {
      const el2 = ref.current
      if (!el2 || saved === undefined || rinunciato) return false
      if (el2.scrollHeight - el2.clientHeight >= saved) {
        applicando = true
        el2.scrollTop = saved
        requestAnimationFrame(() => {
          applicando = false
        })
        return true
      }
      return false
    }

    if (saved) {
      const tryRestore = () => {
        if (applica()) return
        if (++attempts < MAX_ATTEMPTS) raf = requestAnimationFrame(tryRestore)
      }
      raf = requestAnimationFrame(tryRestore)

      // Il contenuto che si allunga PIU' TARDI (le foto degli autori, i dati
      // che arrivano a pezzi) rimette la posizione dov'era, finche' la
      // finestra non scade.
      //
      // Un controllo a intervallo e non un ResizeObserver: l'osservatore va
      // agganciato a un nodo, e il nodo del contenuto React lo sostituisce
      // cambiando pagina — verificato, si restava agganciati a un elemento
      // staccato e la ricrescita non arrivava mai. L'altezza del contenitore
      // invece e' una proprieta' che si puo' guardare senza sapere chi la
      // produce, ed e' una lettura da niente ripetuta quaranta volte.
      vigilanza = window.setInterval(() => {
        if (rinunciato || Date.now() > scadenza) {
          window.clearInterval(vigilanza)
          vigilanza = 0
          return
        }
        applica()
      }, 150)
    }

    // Si registra a ogni scroll invece che allo smontaggio: quando React
    // smonta il componente il contenitore è già andato, e leggerne lo
    // scrollTop restituirebbe 0 — cioè esattamente il bug che stiamo
    // togliendo.
    const onScroll = () => {
      // Un azzeramento FORZATO dal browser, non un gesto: il contenuto si e'
      // accorciato al punto da non poter piu' contenere la posizione di
      // prima, E ci si trova esattamente contro il fondo. Servono entrambe
      // le condizioni — con la sola prima, filtrare la lista (che la
      // accorcia per davvero) farebbe scambiare per forzatura uno
      // scorrimento vero, e il punto raggiunto dentro i risultati filtrati
      // andrebbe perso.
      //
      // E' la firma di due situazioni diverse che capitano in fila: aprire
      // il dettaglio di un autore (il contenitore condiviso di Layout
      // sopravvive alla navigazione e si svuota) e tornare indietro su una
      // lista che deve ancora allungarsi mentre arrivano le foto.
      const previous = positions.get(memoryKey)
      const reach = el.scrollHeight - el.clientHeight
      const azzeramentoForzato = previous !== undefined && previous > reach && el.scrollTop >= reach

      // Ha scorso l'utente: smettiamo di inseguire la posizione vecchia, sia
      // con i tentativi a raffica sia rimettendocela quando il contenuto
      // cresce. Non vale se lo scorrimento e' nostro (applicando) ne' se e'
      // il browser che azzera: in quel secondo caso e' proprio il momento in
      // cui il rimedio serve, e spegnerlo qui sarebbe spegnerlo sempre.
      if (!applicando && !azzeramentoForzato) {
        if (raf) {
          cancelAnimationFrame(raf)
          raf = 0
        }
        rinunciato = true
        if (vigilanza) {
          window.clearInterval(vigilanza)
          vigilanza = 0
        }
      }

      // Non registrare l'azzeramento: cancellerebbe la posizione buona un
      // istante prima di lasciare la pagina.
      if (azzeramentoForzato) return
      positions.set(memoryKey, el.scrollTop)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      el.removeEventListener('scroll', onScroll)
      if (raf) cancelAnimationFrame(raf)
      if (vigilanza) window.clearInterval(vigilanza)
    }
  }, [ref, memoryKey])
}
