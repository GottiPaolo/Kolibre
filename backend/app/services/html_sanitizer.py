"""Sanificatore HTML con lista bianca per le descrizioni dei libri.

**Perché esiste** (20/11/2026, punto G9 della revisione del 19/11). Il campo
`comments` di Calibre arriva come HTML (`<p>`, `<i>`, `<br>`…), e la webapp
lo mostrava come testo piatto, con i tag visibili. Per mostrarlo formattato
il frontend lo mette in `dangerouslySetInnerHTML`, e questo è sicuro solo se
il server garantisce che nell'HTML non ci sia niente di eseguibile: le
descrizioni possono arrivare da EPUB scaricati, da scraping di metadati, da
biblioteche importate — non sono testo fidato.

**La strategia è una lista bianca, non una lista nera**: tutto quello che
non è esplicitamente permesso cade. Nessuna dipendenza nuova: il parser è
`html.parser.HTMLParser` della libreria standard (il progetto ha un punto
aperto sulle versioni dei requisiti e non si aggiunge nulla finché non si
chiude).

**La lista bianca** — proposta del 20/11/2026, **ratificata da Paolo il
22/11/2026** (niente immagini; un link senza href valido resta solo testo).
Resta aperta solo la questione descrizione intera vs estratto da 400
caratteri nell'elenco:

- **Tag permessi**: `p`, `br`, `b`, `strong`, `i`, `em`, `u`, `s`, `sub`,
  `sup`, `blockquote`, `ul`, `ol`, `li`, `hr`, `h1`-`h4`, `a`. Sono i tag
  di struttura e di enfasi che Calibre stesso produce nel suo editor dei
  commenti. I titoli h1-h4 passano **senza declassamento**: il reset di
  Tailwind li appiattisce comunque, e il pannello li ristila tutti alla
  stessa taglia modesta — declassarli qui non cambierebbe niente nella resa.
- **Attributi**: SOLO `href` su `a`, e solo con schema `http:`/`https:`
  (anche un indirizzo relativo cade: in una descrizione non punta a niente
  di nostro). Qualunque altro schema — `javascript:` in testa, ma anche
  `data:`, `vbscript:`, `file:` — fa cadere l'attributo e resta il solo
  testo del link. Il frontend aggiunge `target="_blank"` e
  `rel="noopener noreferrer"` ai link dopo il render.
- **Niente `img`**: un'immagine remota in una descrizione è un faro di
  tracciamento — il server dell'immagine vede IP e orario di chi apre il
  pannello. Niente `style`/`class`/`id` su nessun tag: il tema del pannello
  comanda, e `style` è anche una via di fuga (url(), expression…).
- **Tag fuori lista**: cade il TAG, resta il TESTO interno — un
  `<span style="...">corsivo</span>` diventa testo nudo. Eccezione:
  `script`, `style`, `iframe`, `object`, `embed` cadono CON il contenuto,
  perché il loro contenuto non è prosa ma codice o parametri.
- **Commenti HTML, processing instruction, dichiarazioni**: via.
- **Entità**: il parser le scioglie (`convert_charrefs=True`) e qui si
  ri-escapano una volta sola — `&amp;` resta `&amp;`, mai `&amp;amp;`.

**L'output è ben formato**: i tag aperti e mai chiusi vengono richiusi in
coda, i tag chiusi fuori ordine vengono riallineati chiudendo fino al tag
giusto. È quello che serve perché il frammento non possa «mangiarsi» il
resto della pagina che lo ospita.

**Dove si usa**: solo al confine dell'API che serve la webapp
(`books.py::list_books`). L'OPDS si spoglia i tag per conto suo, il plugin
KOReader non riceve descrizioni, e `GET /books/{id}/description` resta
grezzo apposta: è la sorgente dell'editor dei metadati, e dargli una copia
sanificata farebbe riscrivere in Calibre una versione impoverita a ogni
salvataggio.
"""

import re
from html import escape
from html.parser import HTMLParser
from typing import Optional

# I tag che passano. Vedi il docstring del modulo per il perché di ogni
# assenza notevole (img, span, div, table…).
ALLOWED_TAGS = frozenset({
    "p", "br", "b", "strong", "i", "em", "u", "s", "sub", "sup",
    "blockquote", "ul", "ol", "li", "hr", "h1", "h2", "h3", "h4", "a",
})

# Vuoti per definizione HTML: non vanno mai sulla pila dei tag aperti,
# altrimenti la richiusura finale produrrebbe un `</br>` inventato.
_VOID_TAGS = frozenset({"br", "hr"})

# Questi cadono CON tutto quello che contengono: dentro non c'è prosa ma
# codice (script/style) o parametri di incorporamento (iframe/object/embed).
_DROP_WITH_CONTENT = frozenset({"script", "style", "iframe", "object", "embed"})

# Gli unici schemi con cui un href sopravvive. Il controllo è sullo schema
# ESPLICITO: un href senza schema (relativo) cade anche lui, perché in una
# descrizione di libro non può puntare a niente di legittimo nostro.
_SAFE_HREF = re.compile(r"^https?://", re.IGNORECASE)

class _WhitelistSanitizer(HTMLParser):
    """Riscrive l'HTML tenendo solo la lista bianca, richiudendo i tag.

    Gli handler di commenti, processing instruction e dichiarazioni non
    sono ridefiniti: quelli ereditati non emettono niente, che è esattamente
    il comportamento voluto (cadono).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._stack: list[str] = []  # tag permessi attualmente aperti
        # Profondità dentro i tag che cadono col contenuto. Per script e
        # style il parser entra in modalità CDATA e il contenuto arriva
        # come un unico blocco di dati fino al tag di chiusura; per
        # iframe/object/embed l'interno viene analizzato normalmente, e il
        # contatore copre anche gli annidamenti.
        self._suppressed = 0

    # ── tag ──────────────────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if self._suppressed:
            if tag in _DROP_WITH_CONTENT:
                self._suppressed += 1
            return
        if tag in _DROP_WITH_CONTENT:
            self._suppressed = 1
            return
        if tag not in ALLOWED_TAGS:
            return  # il tag cade, il testo interno continuerà a passare
        if tag in _VOID_TAGS:
            self._out.append(f"<{tag}>")
            return
        rendered = ""
        if tag == "a":
            # SOLO href, e solo http/https. `attrs` può portare la stessa
            # chiave due volte: si prende la prima, come fa il browser.
            href = next((v for k, v in attrs if k == "href" and v), None)
            if href and _SAFE_HREF.match(href.strip()):
                rendered = f' href="{escape(href.strip(), quote=True)}"'
        self._out.append(f"<{tag}{rendered}>")
        self._stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        # `<br/>`, `<hr/>`… — e un eventuale `<p/>` diventa `<p></p>`.
        if self._suppressed or tag in _DROP_WITH_CONTENT:
            return
        if tag in _VOID_TAGS:
            self._out.append(f"<{tag}>")
            return
        if tag not in ALLOWED_TAGS:
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._suppressed:
            if tag in _DROP_WITH_CONTENT:
                self._suppressed -= 1
            return
        if tag in _VOID_TAGS or tag not in ALLOWED_TAGS:
            return
        if tag not in self._stack:
            return  # chiusura orfana: via
        # Chiusure fuori ordine (`<b><i></b>`): si richiude fino al tag
        # giusto, così l'output resta ben formato.
        while self._stack:
            top = self._stack.pop()
            self._out.append(f"</{top}>")
            if top == tag:
                break

    # ── testo ────────────────────────────────────────────────────────

    def handle_data(self, data: str) -> None:
        if self._suppressed:
            return
        # Il parser ha già sciolto le entità: qui si ri-escapa UNA volta,
        # quindi niente doppio escape. `quote=False`: nel testo le
        # virgolette sono innocue.
        self._out.append(escape(data, quote=False))

    # ── risultato ────────────────────────────────────────────────────

    def result(self) -> str:
        self.close()
        # I tag rimasti aperti si richiudono in coda, dal più interno.
        while self._stack:
            self._out.append(f"</{self._stack.pop()}>")
        return "".join(self._out)


def sanitize_description(html: Optional[str]) -> Optional[str]:
    """La descrizione di un libro, ridotta alla lista bianca qui sopra.

    `None` e stringa vuota passano invariati. Una descrizione SENZA nessun
    tag (scritta come testo semplice nell'editor dei metadati di Kolibre,
    che salva da una textarea) viene trattata da testo: le righe vuote
    diventano cambi di paragrafo e gli a-capo singoli `<br>`, perché una
    volta resa come HTML i suoi `\\n` non varrebbero più niente.
    """
    if not html:
        return html
    if "<" not in html:
        return _plain_text_to_html(html)
    parser = _WhitelistSanitizer()
    parser.feed(html)
    return parser.result()


def _plain_text_to_html(text: str) -> str:
    """Testo semplice → paragrafi. Escape prima, tag nostri dopo."""
    paragraphs = re.split(r"\n\s*\n", text.strip())
    rendered = [
        "<p>" + escape(p, quote=False).replace("\n", "<br>") + "</p>"
        for p in paragraphs if p.strip()
    ]
    return "".join(rendered)
