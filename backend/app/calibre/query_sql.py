"""
Il linguaggio di ricerca della libreria, tradotto in SQL.

Fino a ora quel linguaggio viveva solo nel browser
(frontend-react/src/lib/libraryQuery.ts): la pagina scaricava tutti i libri
e li filtrava in memoria. Va benissimo finche' i libri stanno tutti nel
browser — ma sopra la soglia di impaginazione il browser ne ha in mano
duecento per volta, e il server riceveva solo una stringa da cercare alla
lettera con un LIKE su titolo/autore/serie.

L'effetto era che su una biblioteca grande la ricerca smetteva di
funzionare proprio nel momento in cui serviva: `tags:"=filosofia"` veniva
cercato come se fosse il titolo di un libro, e il Navigatore Biblioteca —
che scrive esattamente quel genere di stringhe — non filtrava piu' niente.
Riscontrato in uso.

Qui c'e' la stessa grammatica (gli stessi token, la stessa precedenza
`not` > `and` > `or`, le stesse virgolette e lo stesso `=` per la
corrispondenza esatta) che pero' invece di dire si'/no su un libro gia'
caricato produce un pezzo di WHERE. Gli accenti si ignorano da entrambe le
parti, come nel browser, usando la funzione SQL kolibre_senza_accenti che
la connessione registra gia'.

La fedelta' fra le due implementazioni e' quello che conta: la stessa query
deve dare lo stesso risultato sotto e sopra la soglia di impaginazione, o
la soglia diventa un confine visibile.
"""

import re
import unicodedata
from typing import List, Optional, Tuple

# Stesso tokenizzatore del browser, carattere per carattere.
_TOKEN_RE = re.compile(
    r'\(|\)|[A-Za-z_#][\w#]*:"(?:[^"\\]|\\.)*"|[A-Za-z_#][\w#]*:[^\s()]+|"(?:[^"\\]|\\.)*"|[^\s()]+'
)
_CAMPO_RE = re.compile(r'^[A-Za-z_#][\w#]*:')

_ALIAS = {
    "tag": "tags",
    "author": "authors",
    "format": "formats",
    "editore": "publisher",
    "lingua": "language",
    "valutazione": "rating",
}


def _senza_accenti(valore: str) -> str:
    scomposto = unicodedata.normalize("NFD", valore or "")
    return "".join(c for c in scomposto if not unicodedata.combining(c)).lower()


def _togli_virgolette(grezzo: str) -> str:
    if len(grezzo) >= 2 and grezzo.startswith('"') and grezzo.endswith('"'):
        return re.sub(r"\\(.)", r"\1", grezzo[1:-1])
    return grezzo


class Nodo:
    """Un pezzo di query. `tipo` in {and, or, not, term, freetext}."""

    def __init__(self, tipo: str, **dati):
        self.tipo = tipo
        self.__dict__.update(dati)


class _Analizzatore:
    def __init__(self, token: List[str]):
        self.token = token
        self.i = 0

    def _guarda(self) -> Optional[str]:
        return self.token[self.i] if self.i < len(self.token) else None

    def _prendi(self) -> Optional[str]:
        t = self._guarda()
        self.i += 1
        return t

    def or_(self) -> Nodo:
        figli = [self.and_()]
        while (self._guarda() or "").lower() == "or":
            self._prendi()
            figli.append(self.and_())
        return figli[0] if len(figli) == 1 else Nodo("or", figli=figli)

    def and_(self) -> Nodo:
        figli = []
        while True:
            prossimo = self._guarda()
            if prossimo is None or prossimo == ")" or prossimo.lower() == "or":
                break
            if prossimo.lower() == "and":
                self._prendi()
                continue
            figli.append(self.not_())
        if not figli:
            return Nodo("freetext", valore="")
        return figli[0] if len(figli) == 1 else Nodo("and", figli=figli)

    def not_(self) -> Nodo:
        if (self._guarda() or "").lower() == "not":
            self._prendi()
            return Nodo("not", figlio=self.atomo())
        return self.atomo()

    def atomo(self) -> Nodo:
        t = self._prendi()
        if t is None:
            return Nodo("freetext", valore="")
        if t == "(":
            n = self.or_()
            if self._guarda() == ")":
                self._prendi()
            return n
        if _CAMPO_RE.match(t):
            sep = t.index(":")
            campo = t[:sep]
            valore = _togli_virgolette(t[sep + 1:])
            esatto = valore.startswith("=")
            return Nodo("term", campo=campo, valore=valore[1:] if esatto else valore, esatto=esatto)
        return Nodo("freetext", valore=_togli_virgolette(t))


def analizza(query: str) -> Optional[Nodo]:
    token = _TOKEN_RE.findall((query or "").strip())
    if not token:
        return None
    return _Analizzatore(token).or_()


# ── Traduzione in SQL ────────────────────────────────────────────────────
#
# Ogni campo diventa un EXISTS sulla sua tabella di collegamento, che e' il
# modo in cui Calibre tiene tag, autori, serie, editori e lingue. `b` e'
# l'alias della tabella books nella query chiamante.

def _confronto(espressione: str, valore: str, esatto: bool) -> Tuple[str, list]:
    ago = _senza_accenti(valore)
    if esatto:
        return f"kolibre_senza_accenti({espressione}) = ?", [ago]
    return f"kolibre_senza_accenti({espressione}) LIKE ?", [f"%{ago}%"]


def _esiste(tabella_link: str, colonna_link: str, tabella: str, colonna: str,
            valore: str, esatto: bool) -> Tuple[str, list]:
    cond, par = _confronto(f"x.{colonna}", valore, esatto)
    return (
        f"EXISTS (SELECT 1 FROM {tabella_link} l JOIN {tabella} x ON x.id = l.{colonna_link} "
        f"WHERE l.book = b.id AND {cond})",
        par,
    )


def _termine(campo: str, valore: str, esatto: bool, colonne_custom: dict) -> Tuple[str, list]:
    nome = _ALIAS.get(campo.lower(), campo.lower())

    if nome == "tags":
        return _esiste("books_tags_link", "tag", "tags", "name", valore, esatto)
    if nome == "authors":
        return _esiste("books_authors_link", "author", "authors", "name", valore, esatto)
    if nome == "series":
        return _esiste("books_series_link", "series", "series", "name", valore, esatto)
    if nome == "publisher":
        return _esiste("books_publishers_link", "publisher", "publishers", "name", valore, esatto)
    if nome == "language":
        return _esiste("books_languages_link", "lang_code", "languages", "lang_code", valore, esatto)
    if nome == "formats":
        cond, par = _confronto("d.format", valore, esatto)
        return f"EXISTS (SELECT 1 FROM data d WHERE d.book = b.id AND {cond})", par
    if nome == "title":
        return _confronto("b.title", valore, esatto)
    if nome == "rating":
        # Il browser confronta le STELLE (0-5), Calibre memorizza 0-10.
        cond, par = _confronto("CAST(x.rating / 2 AS TEXT)", valore, esatto)
        return (
            f"EXISTS (SELECT 1 FROM books_ratings_link l JOIN ratings x ON x.id = l.rating "
            f"WHERE l.book = b.id AND {cond})",
            par,
        )

    if nome.startswith("#"):
        info = colonne_custom.get(nome[1:])
        if not info:
            # Un campo che non esiste non corrisponde a niente, come nel
            # browser (findDef non lo trova e il termine e' falso).
            return "0", []
        col_id, normalizzata = info["id"], info["normalized"]
        if normalizzata:
            cond, par = _confronto("x.value", valore, esatto)
            return (
                f"EXISTS (SELECT 1 FROM books_custom_column_{col_id}_link l "
                f"JOIN custom_column_{col_id} x ON x.id = l.value "
                f"WHERE l.book = b.id AND {cond})",
                par,
            )
        cond, par = _confronto("CAST(x.value AS TEXT)", valore, esatto)
        return (
            f"EXISTS (SELECT 1 FROM custom_column_{col_id} x WHERE x.book = b.id AND {cond})",
            par,
        )

    return "0", []


def _testo_libero(valore: str) -> Tuple[str, list]:
    """Come nel browser: titolo, autore o tag."""
    if not valore:
        return "1", []
    ago = f"%{_senza_accenti(valore)}%"
    return (
        "(kolibre_senza_accenti(b.title) LIKE ? "
        " OR EXISTS (SELECT 1 FROM books_authors_link l JOIN authors x ON x.id = l.author "
        "            WHERE l.book = b.id AND kolibre_senza_accenti(x.name) LIKE ?) "
        " OR EXISTS (SELECT 1 FROM books_tags_link l JOIN tags x ON x.id = l.tag "
        "            WHERE l.book = b.id AND kolibre_senza_accenti(x.name) LIKE ?))",
        [ago, ago, ago],
    )


def _in_sql(nodo: Nodo, colonne_custom: dict) -> Tuple[str, list]:
    if nodo.tipo == "and":
        pezzi, par = [], []
        for f in nodo.figli:
            s, p = _in_sql(f, colonne_custom)
            pezzi.append(s)
            par += p
        return "(" + " AND ".join(pezzi) + ")", par
    if nodo.tipo == "or":
        pezzi, par = [], []
        for f in nodo.figli:
            s, p = _in_sql(f, colonne_custom)
            pezzi.append(s)
            par += p
        return "(" + " OR ".join(pezzi) + ")", par
    if nodo.tipo == "not":
        s, p = _in_sql(nodo.figlio, colonne_custom)
        return f"(NOT {s})", p
    if nodo.tipo == "term":
        return _termine(nodo.campo, nodo.valore, nodo.esatto, colonne_custom)
    return _testo_libero(nodo.valore)


def where_da_query(query: str, colonne_custom: dict) -> Tuple[str, list]:
    """
    Traduce una query del linguaggio della libreria in un pezzo di WHERE.

    `colonne_custom`: {etichetta: {"id": n, "normalized": bool}} — serve per
    sapere in quale tabella vive ogni colonna personalizzata.

    Torna ("", []) per una query vuota: nessun filtro.
    """
    nodo = analizza(query)
    if nodo is None:
        return "", []
    sql, parametri = _in_sql(nodo, colonne_custom)
    if sql in ("1", "(1)"):
        return "", []
    return sql, parametri
