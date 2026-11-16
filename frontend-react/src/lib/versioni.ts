// Confrontare due versioni di un plugin.
//
// **Perché un file per due funzioni.** La pagina Dispositivi chiedeva «è
// indietro?» con un `!==`, cioè *diverso* e non *più vecchio*: un
// dispositivo con una versione più NUOVA del server — chi sviluppa, mentre
// prova — veniva annunciato come indietro, con l'invito ad aggiornarsi a una
// versione precedente. E un confronto come testo sbaglia da solo appena un
// plugin passa la nona versione minore: `'0.9.0' > '0.10.0'` è vero per le
// stringhe, quindi un plugin alla 0.9.0 risulterebbe aggiornato per sempre.
//
// Sta qui e non dentro la pagina perché i plugin sono tre — KOReader,
// Calibre, Obsidian — e la stessa domanda si farà per tutti. Il guardiano è
// la prova `versioni_dei_plugin`.

/** I numeri di una versione, o `null` se quella stringa non è una versione. */
function pezzi(v: string | null | undefined): number[] | null {
  if (typeof v !== 'string') return null
  const parti = v.trim().split('.')
  if (parti.length === 0 || parti[0] === '') return null
  const numeri = parti.map((p) => Number(p))
  // **Tutto o niente**: `dev`, `1.5.0-beta` o una stringa vuota non sono
  // versioni confrontabili, e inventare un ordine per loro vorrebbe dire
  // dare un verdetto su una cosa che non si sa.
  if (numeri.some((n) => !Number.isInteger(n) || n < 0)) return null
  return numeri
}

/**
 * -1 se `a` viene prima di `b`, 1 se dopo, 0 se sono la stessa versione.
 *
 * Le lunghezze diverse si confrontano riempiendo di zeri: `1.5` e `1.5.0`
 * sono la stessa versione scritta in due modi, e il plugin Calibre la
 * propria la dichiara come una tupla di tre numeri.
 *
 * Torna 0 anche quando una delle due non è una versione: chi chiama deve
 * usare `eIndietro`, che quel caso lo tratta a parte.
 */
export function confrontaVersioni(a: string | null | undefined, b: string | null | undefined): number {
  const x = pezzi(a)
  const y = pezzi(b)
  if (!x || !y) return 0
  const quanti = Math.max(x.length, y.length)
  for (let i = 0; i < quanti; i++) {
    const d = (x[i] ?? 0) - (y[i] ?? 0)
    if (d !== 0) return d < 0 ? -1 : 1
  }
  return 0
}

/**
 * `true` solo quando si **sa** che l'installata è più vecchia di quella che
 * il server distribuisce.
 *
 * Nel dubbio risponde `false`, ed è la parte che conta: un dispositivo che
 * non ha mai dichiarato la propria versione non è indietro, è sconosciuto —
 * e la pagina lo dice con una frase sua, invece di affermare una cosa che
 * nessuno sa.
 */
export function eIndietro(installata: string | null | undefined,
                          distribuita: string | null | undefined): boolean {
  if (!pezzi(installata) || !pezzi(distribuita)) return false
  return confrontaVersioni(installata, distribuita) < 0
}
