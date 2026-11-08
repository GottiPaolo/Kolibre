// Chi ha ragione sulla lingua: il browser, il server, o il sistema.
//
// **Perché una funzione a parte, e pura.** Da quando la lingua è una
// preferenza della persona e vive sul server (04/11/2026, vedi
// `backend/app/services/preferenze_utente.py`), ci sono **tre** fonti che
// possono dire qualcosa, e non concordano sempre:
//
//   * questo browser, che ha una copia locale per poter disegnare la prima
//     schermata senza aspettare la rete;
//   * il server, che è la verità — ma arriva dopo;
//   * il sistema (`navigator.language`), che è l'unica fonte quando la
//     persona non ha mai scelto.
//
// Metterle d'accordo è una decisione a tre casi, e i casi difficili non si
// vedono guardando il codice che li esegue: si vedono guardando una tabella.
// Per questo la decisione sta qui, senza React e senza rete, e la sua prova
// (la prova «lingua_scelta») può interrogarla direttamente.

export type Lingua = 'it' | 'en'

// ── Le tre fonti ─────────────────────────────────────────────────────────
//
// Stanno qui, accanto alla funzione che le mette d'accordo, e non in
// `i18n.tsx` che e' il file del tradurre. Il motivo tecnico e' banale (un
// file che esporta un componente non dovrebbe esportare anche funzioni), ma
// quello vero e' che si leggono meglio vicine a chi le usa.

const CHIAVE = 'kolibre_lingua'

/**
 * La lingua **salvata in questo browser**, o `null` se non c'e'.
 *
 * Separata da `linguaDelSistema` perche' `decidiLaLingua` ha bisogno di
 * sapere la differenza: «ha scelto l'italiano» e «ha un browser italiano»
 * sono due cose diverse, e confonderle trasforma un indovinello in una
 * scelta.
 */
export function linguaSalvata(): Lingua | null {
  try {
    const salvata = localStorage.getItem(CHIAVE)
    if (salvata === 'it' || salvata === 'en') return salvata
  } catch {
    // Finestra privata o dati del sito bloccati: non c'e' niente di salvato.
  }
  return null
}

/** Quella che suggerisce il sistema. E' un ripiego, non una scelta. */
export function linguaDelSistema(): Lingua {
  return (navigator.language || '').toLowerCase().startsWith('it') ? 'it' : 'en'
}

/**
 * La lingua con cui disegnare **adesso**, senza aspettare la rete.
 *
 * La usa `main.tsx` prima di qualunque render, ed e' la ragione per cui la
 * copia locale esiste: aspettare il server vorrebbe dire un lampo di inglese
 * prima dell'italiano.
 */
export function leggiLingua(): Lingua {
  return linguaSalvata() ?? linguaDelSistema()
}

export function scriviLingua(lingua: Lingua): void {
  try {
    localStorage.setItem(CHIAVE, lingua)
  } catch {
    // Non poter ricordare la scelta non deve impedire di farla.
  }
}


export interface StatoDellaLingua {
  /** Quella salvata in questo browser, o `null` se non c'è. */
  nelBrowser: Lingua | null
  /** Quella che la persona ha scelto, secondo il server. `null` = non ha scelto. */
  sulServer: Lingua | null
  /** Quella che il sistema suggerisce. C'è sempre: è un ripiego, non una scelta. */
  dalSistema: Lingua
}

export interface Decisione {
  /** La lingua da usare adesso. */
  lingua: Lingua
  /** Da mandare al server, se c'è una scelta che lui non conosce. */
  daMandareAlServer: Lingua | null
  /** Da salvare in questo browser, se la scelta della persona qui non c'era. */
  daSalvareNelBrowser: Lingua | null
  /** Perché, in una parola — serve ai log e alla prova. */
  motivo: 'il server comanda' | 'la scelta locale sale' | 'lo dice il sistema'
}

/**
 * Chi vince, e cosa va scritto dove.
 *
 * I tre casi, e il ragionamento di ciascuno:
 *
 * 1. **Il server ha una scelta** → comanda lui, sempre, anche se questo
 *    browser ne aveva un'altra. È il senso di avere una verità: chi ha
 *    scelto l'italiano su un portatile deve trovare l'italiano sul telefono.
 *    Se la copia locale è diversa (o manca), si allinea.
 *
 * 2. **Il server non ha niente e il browser sì** → quella scelta **sale**.
 *    È il caso di chiunque usi Kolibre da prima di questo cambiamento: la
 *    scelta fatta mesi fa in questo browser diventa la scelta della persona,
 *    senza che nessuno la debba rifare. Senza questo passaggio, il primo
 *    client nuovo la sovrascriverebbe col suo ripiego.
 *
 * 3. **Nessuno ha niente** → si parla la lingua del sistema, e **non si
 *    scrive niente da nessuna parte**. È la parte che si sbaglia facilmente:
 *    salvare il ripiego lo trasformerebbe in una scelta, e da quel momento
 *    un tedesco si porterebbe dietro per sempre l'inglese che gli abbiamo
 *    indovinato — con la differenza che nessuno saprebbe più che era un
 *    indovinello. Un ripiego deve restare ripiego.
 */
export function decidiLaLingua(stato: StatoDellaLingua): Decisione {
  if (stato.sulServer) {
    return {
      lingua: stato.sulServer,
      daMandareAlServer: null,
      daSalvareNelBrowser: stato.nelBrowser === stato.sulServer ? null : stato.sulServer,
      motivo: 'il server comanda',
    }
  }
  if (stato.nelBrowser) {
    return {
      lingua: stato.nelBrowser,
      daMandareAlServer: stato.nelBrowser,
      daSalvareNelBrowser: null,
      motivo: 'la scelta locale sale',
    }
  }
  return {
    lingua: stato.dalSistema,
    daMandareAlServer: null,
    daSalvareNelBrowser: null,
    motivo: 'lo dice il sistema',
  }
}
