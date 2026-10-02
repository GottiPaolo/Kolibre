"""
Come Calibre nomina cartelle e file di un libro — porting fedele.

Non una ricostruzione a memoria: le funzioni qui sotto ricalcano riga per
riga `construct_path_name` / `construct_file_name` (calibre/db/backend.py),
`ascii_filename` (calibre/utils/filenames.py) e `sanitize_file_name`
(calibre/__init__.py), verificate sul sorgente di Calibre e poi confrontate
con una biblioteca Calibre vera (vedi la prova che ricalcola i percorsi di
tutti i libri e li confronta con quelli scritti da Calibre stesso).

Le tre regole che contano, e che prima Kolibre non seguiva:

1. la cartella porta il nome del PRIMO autore, non di tutti
   (`cache.py`: `author = self._field_for('authors', book_id, ...)[0]`);
   un libro a quattro mani sta sotto uno solo dei due;
2. i nomi sono traslitterati in ASCII: "Émile Zola" diventa la cartella
   "Emile Zola". E' il motivo per cui in una biblioteca nata in Calibre non
   si trova un solo accento nei nomi di cartella;
3. autore e titolo vengono TRONCATI, perche' un titolo lungo piu' del
   limite genererebbe percorsi che certi dischi non accettano.

Il limite dipende dal sistema, come in Calibre: 40 su Windows, 100 altrove.

La traslitterazione usa il pacchetto `unidecode`, che e' lo stesso lavoro
del modulo che Calibre si porta dentro (entrambi discendono dalle tabelle
di Text::Unidecode). Su tutto l'alfabeto latino i due concordano; su
scritture lontane (cirillico, greco, CJK) le tabelle possono essersi mosse
fra una versione e l'altra, ed e' il motivo per cui la riparazione
retroattiva (vedi book_paths.py) non si fida ciecamente di questo modulo
per decidere se una cartella gia' esistente e' sbagliata.
"""

# Derivato da Calibre (https://calibre-ebook.com), Copyright (C) Kovid Goyal,
# GNU General Public License v3. I punti esatti da cui vengono le singole
# funzioni sono citati nei commenti qui sotto, con file e numero di riga.
#
# È la ragione per cui Kolibre nel suo insieme è AGPL-3.0: vedi NOTICE.
#
# Non sono un'imitazione né una ricostruzione a memoria, e non possono
# diventarlo: il loro criterio di correttezza è produrre lo STESSO identico
# risultato di Calibre, perché da quel risultato dipendono l'ordinamento e i
# nomi delle cartelle sul disco. Una biblioteca Kolibre deve potersi aprire in
# Calibre Desktop senza conversioni.

import os
import re

from unidecode import unidecode

from .functions import string_to_authors

# calibre/db/backend.py: PATH_LIMIT = 40 if iswindows else 100
PATH_LIMIT = 40 if os.name == "nt" else 100

# calibre/db/constants.py
BOOK_ID_PATH_TEMPLATE = " ({})"

# calibre/db/backend.py
WINDOWS_RESERVED_NAMES = frozenset(
    "CON PRN AUX NUL COM1 COM2 COM3 COM4 COM5 COM6 COM7 COM8 COM9 "
    "LPT1 LPT2 LPT3 LPT4 LPT5 LPT6 LPT7 LPT8 LPT9".split()
)

# calibre/__init__.py: _filename_sanitize_unicode — l'unione dei caratteri
# vietati da Windows, macOS e Linux, piu' i caratteri di controllo.
_VIETATI = frozenset('\\|?*<":>+/') | frozenset(chr(c) for c in range(32))

SCONOSCIUTO = "Unknown"


def sanitize_file_name(name: str, substitute: str = "_") -> str:
    """calibre/__init__.py::sanitize_file_name."""
    uno = "".join(substitute if c in _VIETATI else c for c in name)
    uno = re.sub(r"\s", " ", uno).strip()
    base, estensione = os.path.splitext(uno)
    uno = re.sub(r"^\.+$", "_", base)
    uno = uno.replace("..", substitute)
    uno += estensione
    # Windows non accetta un nome che finisce con punto o spazio.
    if uno and uno[-1] in (".", " "):
        uno = uno[:-1] + "_"
    # Un nome che inizia con un punto e' nascosto su Unix.
    if uno.startswith("."):
        uno = "_" + uno[1:]
    return uno


def ascii_filename(orig: str, substitute: str = "_") -> str:
    """calibre/utils/filenames.py::ascii_filename."""
    orig = unidecode(orig or "").replace("?", "_")
    ans = "".join(x if ord(x) >= 32 else substitute for x in orig)
    return sanitize_file_name(ans, substitute=substitute)


def autore_di_cartella(autore: str) -> str:
    """Il solo autore che Calibre usa per il percorso: il primo."""
    nomi = string_to_authors(autore or "")
    return nomi[0] if nomi else (autore or "")


def construct_path_name(book_id: int, title: str, author: str) -> str:
    """calibre/db/backend.py::construct_path_name. Torna `Autore/Titolo (id)`."""
    pezzo_id = BOOK_ID_PATH_TEMPLATE.format(book_id)
    limite = PATH_LIMIT - (len(pezzo_id) // 2) - 2
    autore = ascii_filename(author)[:limite]
    titolo = ascii_filename((title or "").lstrip())[:limite].rstrip()
    if not titolo:
        titolo = SCONOSCIUTO[:limite]
    while autore and autore[-1] in (" ", "."):
        autore = autore[:-1]
    if not autore:
        autore = ascii_filename(SCONOSCIUTO)
    if autore.upper() in WINDOWS_RESERVED_NAMES:
        autore += "w"
    return f"{autore}/{titolo}{pezzo_id}"


def construct_file_name(title: str, author: str, extlen: int = 10) -> str:
    """
    calibre/db/backend.py::construct_file_name — il nome del FILE dentro la
    cartella, senza estensione: "Titolo - Autore".

    `extlen` e' la lunghezza dell'estensione piu' lunga fra i formati del
    libro piu' uno (Calibre passa 10 quando non ce ne sono); viene comunque
    portato ad almeno 14, che e' quanto serve per "ORIGINAL_EPUB".
    """
    extlen = max(extlen, 14)
    limite = (PATH_LIMIT - (extlen // 2) - 2) if os.name == "nt" else ((PATH_LIMIT - extlen - 2) // 2)
    if limite < 5:
        raise ValueError(f"Estensione troppo lunga: {extlen}")
    autore = ascii_filename(author)[:limite]
    titolo = ascii_filename((title or "").lstrip())[:limite].rstrip()
    if not titolo:
        titolo = SCONOSCIUTO[:limite]
    nome = titolo + " - " + autore
    while nome.endswith("."):
        nome = nome[:-1]
    return nome or ascii_filename(SCONOSCIUTO)


def lunghezza_estensione(formati) -> int:
    """Lo stesso `extlen` che Calibre calcola dai formati di un libro."""
    lunghezze = [len(f) for f in (formati or []) if f]
    return (max(lunghezze) + 1) if lunghezze else 10


def percorso_per_libro(book_id: int, title: str, author: str) -> str:
    """`construct_path_name` con l'autore gia' ridotto al primo, e con i
    separatori del sistema su cui giriamo."""
    rel = construct_path_name(book_id, title, autore_di_cartella(author))
    return rel.replace("/", os.sep) if os.sep != "/" else rel
