// Copiare negli appunti, anche dove `navigator.clipboard` non c'e'.
//
// **Il motivo per cui questo file esiste.** L'API moderna degli appunti e'
// disponibile solo in un «contesto sicuro»: HTTPS, oppure `localhost`. Kolibre
// gira tipicamente su una rete di casa a un indirizzo come
// `http://192.168.1.10:5566` — che non e' nessuno dei due. Li'
// `navigator.clipboard` e' semplicemente **`undefined`**, e un
// `navigator.clipboard.writeText(...)` lancia un TypeError.
//
// Quindi il ripiego non e' una precauzione per browser vecchi: e' il caso
// NORMALE per chi usa Kolibre come e' pensato.
//
// Il ripiego e' il vecchio trucco: una `<textarea>` fuori dallo schermo, la si
// seleziona, `document.execCommand('copy')`. E' deprecato e continua a
// funzionare ovunque; l'unico vincolo e' che deve partire da un gesto
// dell'utente — un clic su un bottone lo e'.

/**
 * Copia `testo` negli appunti. Torna `false` se non c'e' riuscito, cosi' chi
 * chiama puo' dirlo invece di far finta che sia andata.
 */
export async function copiaNegliAppunti(testo: string): Promise<boolean> {
  // Prima la strada buona, quando c'e'.
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(testo)
      return true
    } catch {
      // Permesso negato, o documento non a fuoco: si prova l'altra.
    }
  }

  try {
    const area = document.createElement('textarea')
    area.value = testo
    // Fuori dallo schermo ma NON `display:none` ne' `hidden`: un elemento
    // davvero invisibile non e' selezionabile, e la copia non partirebbe.
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.top = '-1000px'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    area.setSelectionRange(0, testo.length)
    const fatto = document.execCommand('copy')
    document.body.removeChild(area)
    return fatto
  } catch {
    return false
  }
}
