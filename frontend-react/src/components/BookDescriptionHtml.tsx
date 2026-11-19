// La descrizione di un libro, resa come HTML — non più testo piatto.
//
// **Perché esiste** (20/11/2026, punto G9). Il campo `comments` di Calibre
// è HTML (`<p>`, `<i>`, `<br>`…) e finora si mostrava con i tag visibili.
// Il SERVER lo consegna già sanificato — ridotto a una lista bianca di tag,
// vedi `backend/app/services/html_sanitizer.py` — e solo per questo qui si
// può usare `dangerouslySetInnerHTML`: questo componente va alimentato
// SOLO col campo `description` dell'elenco libri, mai con testo arrivato
// da altre strade (l'endpoint `GET /{id}/description` è grezzo apposta,
// per l'editor dei metadati).
//
// **Perché è un componente e non due blocchi uguali.** Lo stesso render sta
// nel pannello Quickview e nella scheda del libro: scritto due volte, la
// lista di stili qui sotto divergerebbe alla prima modifica.
//
// **Gli stili li mette il tema, non la descrizione.** Il reset di Tailwind
// appiattisce tutto (anche h1-h4), quindi ogni tag della lista bianca viene
// ristilato qui, sobrio e coerente col pannello: paragrafi spaziati, elenchi
// puntati, citazioni rientrate, titoli tutti alla stessa taglia appena
// sopra il corpo, link col colore primario del tema.
import { useCallback } from 'react'
import { cn } from '@/lib/utils'

export function BookDescriptionHtml({ html, className }: { html: string; className?: string }) {
  // I link si aprono in un'altra scheda, senza consegnare `window.opener`
  // alla pagina di destinazione. Si fa qui con un ref e non nel markup
  // perché il markup arriva dal server come stringa: il sanificatore
  // permette solo `href`, e target/rel sono una politica del CLIENT.
  const applyLinkPolicy = useCallback((el: HTMLDivElement | null) => {
    if (!el) return
    el.querySelectorAll('a').forEach((a) => {
      a.target = '_blank'
      a.rel = 'noopener noreferrer'
    })
  }, [])

  return (
    <div
      ref={applyLinkPolicy}
      className={cn(
        'leading-relaxed',
        '[&_p]:my-2',
        '[&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5',
        '[&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5',
        '[&_li]:my-0.5',
        '[&_blockquote]:my-2 [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground',
        '[&_hr]:my-3 [&_hr]:border-border',
        '[&_a]:text-primary [&_a]:underline [&_a]:underline-offset-2 [&_a:hover]:opacity-80',
        // Tutti i titoli alla stessa taglia, appena sopra il corpo: in un
        // pannello di dettaglio una gerarchia h1→h4 a taglie piene
        // urlerebbe più del titolo del libro stesso.
        '[&_:is(h1,h2,h3,h4)]:mt-3 [&_:is(h1,h2,h3,h4)]:mb-1 [&_:is(h1,h2,h3,h4)]:text-[1.05em] [&_:is(h1,h2,h3,h4)]:font-semibold',
        // Niente margini orfani ai bordi: il contenitore decide gli spazi.
        '[&>:first-child]:mt-0 [&>:last-child]:mb-0',
        className,
      )}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
