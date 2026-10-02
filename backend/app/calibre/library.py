import base64
import json
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from . import book_paths, query_sql
from .connection import get_connection, bootstrap_library, CALIBRE_PAGE_COUNT_COLUMN_LABEL
from .functions import author_to_author_sort, authors_to_string, string_to_authors
from .write_queue import register_op


def _now_iso() -> str:
    """
    Calibre-compatible `last_modified` value. Unlike `timestamp`/`pubdate`
    (plain `CURRENT_TIMESTAMP`, no offset), the real Calibre schema's
    `last_modified` DEFAULT is `'2000-01-01 00:00:00+00:00'` — an explicit
    UTC offset suffix, which real Calibre itself always writes and expects
    when comparing "which side is newer" across machines/timezones. No
    server-side write ever stamped this column before now: sat frozen al
    valore di default dello schema per ogni libro che Kolibre stesso creava
    o modificava, per sempre.

    Microsecond precision, not whole seconds: real Calibre Desktop's own
    Metadata.last_modified always carries microseconds (verified directly —
    it is NOT limited to the schema default literal's whole-second
    appearance). Questo serviva al confronto bidirezionale del plugin
    Calibre, che distingueva "cambiato dall'ultima sincronizzazione" per
    disuguaglianza stretta: due modifiche nello stesso SECONDO di orologio
    (successo davvero in una prova automatica, e plausibile in una
    migrazione fatta da uno script) sarebbero state indistinguibili. Quel
    confronto non c'e' piu' dal 28/09/2026 — la precisione resta perche'
    e' comunque quella che Calibre scrive, e toglierla renderebbe una
    biblioteca Kolibre diversa da una sua.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f+00:00")

# Real Calibre custom-column datatypes we know how to create a value table for,
# mapped to the SQLite storage type of that table's `value` column. `enumeration`
# is Calibre's real name for what the frontend UI calls "enum" (predefined choices).
CUSTOM_COLUMN_SQL_TYPE = {
    "text": "TEXT",
    "enumeration": "TEXT",
    "datetime": "TEXT",
    "float": "REAL",
    "rating": "REAL",
    "int": "INTEGER",
    "bool": "BOOL",
}


# Process-wide cache for list_books(), keyed by db_path -> (cached_at, books).
# Every route handler creates its own throw-away CalibreLibrary instance
# (`CalibreLibrary(config.library_path(library))`), so a per-instance cache
# attribute would never hit — this has to live at module level to actually
# be shared across requests.
#
# Short TTL, not event-driven invalidation: two event-driven signals were
# tried and both proved unreliable when directly tested against a real
# library under get_connection()'s own settings (journal_mode=WAL,
# synchronous=NORMAL) — os.path.getmtime(metadata.db) doesn't necessarily
# move on a write (it lands in metadata.db-wal until SQLite happens to
# checkpoint), and `PRAGMA data_version` — nominally SQLite's own
# purpose-built signal for exactly this — did NOT reflect a write made by a
# separate connection/process in direct testing here either (each
# request opens a brand-new connection via get_connection(), and WAL
# auto-checkpoints when the last connection to the file closes, which
# resets the version bookkeeping between separate short-lived connections
# in a way that made it useless as a "did anything change" signal in
# practice). Rather than trust either untested-in-production mechanism for
# something that would fail silently (stale data with no error), a small
# TTL bounds staleness to a constant, predictable window with zero
# per-write bookkeeping anywhere — the exact same "TTL, not read-time
# invalidation" choice this codebase already made for the stats cache
# (models.py's StatsCache, refreshed on a background loop). Long enough to
# collapse a realistic burst of near-simultaneous requests for the same
# library (a page load firing several API calls, or a KOReader dashboard
# opening catalog + sections + discover back to back), short enough that a
# book just added/edited shows up well within what a human would notice.
_LIST_BOOKS_CACHE_TTL_SECONDS = 5
_LIST_BOOKS_CACHE: dict[str, tuple[float, list]] = {}


def purge_expired_book_lists() -> int:
    """
    Butta via le liste scadute. Restituisce quante voci ha liberato.

    Il TTL diceva soltanto "non usare piu' questa voce": la voce restava
    pero' nel dizionario finche' qualcuno non la sovrascriveva, cioe' fino
    alla lettura successiva DI QUELLA libreria. Su una biblioteca grande non
    e' un dettaglio — misurato: 224 MB trattenuti per una libreria da
    100.000 libri, e altrettanti per ogni altra libreria visitata una volta
    sola. Un server con otto biblioteche grandi teneva occupato piu' di un
    gigabyte per liste che nessuno avrebbe piu' letto.

    Costa niente: il dizionario ha una voce per libreria, non per libro.
    """
    adesso = time.monotonic()
    scadute = [k for k, (quando, _) in _LIST_BOOKS_CACHE.items()
               if adesso - quando >= _LIST_BOOKS_CACHE_TTL_SECONDS]
    for k in scadute:
        del _LIST_BOOKS_CACHE[k]
    return len(scadute)


def _rimetti_a_posto(spostamenti: list) -> None:
    """
    Riporta indietro quello che e' gia' stato spostato o rinominato sul
    disco, quando la transazione che doveva registrarlo non e' andata a
    buon fine.

    Spostare file e aggiornare il database non possono essere un'unica
    operazione atomica: il disco non partecipa alla transazione di SQLite.
    L'ordine scelto e' "sposta, poi registra, poi conferma", e questo e' il
    rimedio per l'unico caso in cui quell'ordine lascia il mondo storto —
    file gia' spostati e database che non lo sa.

    `spostamenti` e' l'elenco ORDINATO delle operazioni fatte, e si annulla
    al contrario: prima torna indietro la cartella, poi i file al suo
    interno — che solo a quel punto tornano a essere raggiungibili al
    percorso da cui erano partiti. Annullare solo il trasloco della
    cartella, e non i rinomini dentro, lascerebbe il libro illeggibile:
    `data.name` tornerebbe al nome vecchio, il file sul disco no.
    """
    for origine, destinazione in reversed(spostamenti):
        try:
            if os.path.exists(destinazione) and not os.path.exists(origine):
                os.makedirs(os.path.dirname(origine), exist_ok=True)
                shutil.move(destinazione, origine)
        except OSError:
            # Qui non si puo' fare altro che lasciare traccia: sollevare
            # coprirebbe l'errore vero che ci ha portati in questo ramo.
            logging.getLogger("kolibre.calibre").exception(
                "Non sono riuscito a riportare indietro %s", destinazione
            )


def _pulisci_cartelle_vuote(spostamenti: list, radice: str) -> None:
    """Toglie le cartelle d'autore rimaste vuote dopo un trasloco.

    Solo se vuote e solo dentro la biblioteca: una cartella d'autore con
    ancora dei libri dentro (l'autore aveva altri titoli) non si tocca.
    """
    for origine, _ in spostamenti:
        cartella_autore = os.path.dirname(origine)
        try:
            if (
                os.path.isdir(cartella_autore)
                and os.path.abspath(cartella_autore).startswith(os.path.abspath(radice) + os.sep)
                and not os.listdir(cartella_autore)
            ):
                os.rmdir(cartella_autore)
        except OSError:
            pass


def dimentica_lista_libri(db_path: str) -> None:
    """
    Butta via la lista in cache di UNA libreria, subito.

    REGOLA: ogni metodo di questa classe che fa conn.commit() la chiama
    prima di uscire. Non e' una precauzione, e' l'unica cosa che tiene in
    piedi la cache: `list_books` tiene l'elenco per cinque secondi, e in
    quei cinque secondi chi rilegge dopo aver scritto riceve i valori di
    PRIMA. Su sedici metodi di scrittura lo faceva solo update_book, e
    nemmeno lui fino a ieri.
    
    Si notava poco perche' quasi tutte le scritture arrivano da una modale
    che si chiude, e la chiusura fa passare l'attimo. Si e' visto con la
    spunta "letto" — che si preme e si guarda nello stesso istante — e poi
    scrivendo la prova dei doppioni, dove registrare un formato e
    rileggerlo subito dopo restituiva un libro senza formati.

    Il TTL da solo va bene per una scrittura su un libro singolo (si
    riguarda quel libro, non l'elenco). Non va bene per una modifica di
    massa: si correggono trecento libri e per i cinque secondi successivi
    l'elenco continua a mostrare i dati vecchi — cioe' esattamente la
    schermata che si sta guardando per controllare se la modifica ha
    funzionato.
    """
    _LIST_BOOKS_CACHE.pop(db_path, None)


class CalibreLibrary:
    """Accessor for a single Calibre-compatible library folder (one metadata.db)."""

    def __init__(self, path: str, crea: bool = False):
        """`crea=True` solo da chi sta davvero creando una biblioteca.

        Vedi bootstrap_library: aprire un nome inesistente non deve piu'
        produrre una biblioteca vuota."""
        self.path = path
        self.db_path = os.path.join(path, "metadata.db")
        bootstrap_library(self.db_path, crea=crea)

    def _connect(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    @staticmethod
    def _is_normalized_column(conn: sqlite3.Connection, col_id: int) -> bool:
        """
        Real Calibre custom columns come in two physical shapes: a simple
        `custom_column_N(book, value)` table for plain/non-multiple columns
        (what our own create_custom_column always builds), or — for
        normalized/is_multiple columns such as an "enumeration" created by
        Calibre Desktop itself — a tags-like pair: `custom_column_N(id, value)`
        holding the distinct values plus `books_custom_column_N_link(book,
        value)` linking books to them. We must detect which shape a given
        column actually uses before querying it, since a genuinely
        Calibre-authored library (unlike ones we create ourselves) can contain
        the normalized shape.
        """
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (f"books_custom_column_{col_id}_link",),
        ).fetchone()
        return row is not None

    @classmethod
    def _read_custom_value(cls, conn: sqlite3.Connection, col_id: int, book_id: int):
        if cls._is_normalized_column(conn, col_id):
            row = conn.execute(
                f"SELECT cc.value AS value FROM books_custom_column_{col_id}_link l "
                f"JOIN custom_column_{col_id} cc ON cc.id = l.value WHERE l.book = ? LIMIT 1",
                (book_id,),
            ).fetchone()
        else:
            row = conn.execute(
                f"SELECT value FROM custom_column_{col_id} WHERE book = ?", (book_id,)
            ).fetchone()
        return row["value"] if row else None

    @classmethod
    def _write_custom_value(cls, conn: sqlite3.Connection, col_id: int, book_id: int, value) -> None:
        if cls._is_normalized_column(conn, col_id):
            conn.execute(f"DELETE FROM books_custom_column_{col_id}_link WHERE book = ?", (book_id,))
            if value is not None and value != "":
                conn.execute(
                    f"INSERT INTO custom_column_{col_id} (value) VALUES (?) "
                    "ON CONFLICT(value) DO NOTHING",
                    (value,),
                )
                value_row = conn.execute(
                    f"SELECT id FROM custom_column_{col_id} WHERE value = ?", (value,)
                ).fetchone()
                conn.execute(
                    f"INSERT INTO books_custom_column_{col_id}_link (book, value) VALUES (?, ?)",
                    (book_id, value_row["id"]),
                )
        elif value is None:
            # "Unset" for a non-normalized column is the absence of a row —
            # not a NULL value. Some real Calibre-authored columns (e.g. a
            # numeric "Pagine" column) declare `value` NOT NULL, so inserting
            # NULL here isn't just semantically wrong, it raises an
            # IntegrityError for any book that never had this field set.
            conn.execute(f"DELETE FROM custom_column_{col_id} WHERE book = ?", (book_id,))
        else:
            conn.execute(
                f"INSERT INTO custom_column_{col_id} (book, value) VALUES (?, ?) "
                "ON CONFLICT(book) DO UPDATE SET value=excluded.value",
                (book_id, value),
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    # Separators for the aggregated identifiers_str subquery in list_books —
    # \x1e/\x1f (ASCII record/unit separator) rather than something printable
    # like "|"/"=", since an identifier val is free text and could plausibly
    # contain either of those (a URL-shaped "val", for instance).
    _ID_PAIR_SEP = "\x1e"
    _ID_KV_SEP = "\x1f"

    def list_books(self) -> list[dict]:
        """Cached wrapper around _list_books_uncached — see _LIST_BOOKS_CACHE's
        own comment for the TTL invalidation strategy. Always returns a FRESH
        top-level list (the book dicts themselves are shared/reused across
        calls, never mutated by any known caller — see _list_books_uncached's
        own result) so a caller doing `books = lib.list_books();
        books.sort(...)` (several already do, e.g. browse_catalog/opds.py)
        can never scramble the cached order for the next request; only a
        `.append()`/`.sort()` etc. on an individual book dict would be
        unsafe, and nothing does that today."""
        purge_expired_book_lists()
        cached = _LIST_BOOKS_CACHE.get(self.db_path)
        if cached is not None and (time.monotonic() - cached[0]) < _LIST_BOOKS_CACHE_TTL_SECONDS:
            return list(cached[1])

        books = self._list_books_uncached()
        _LIST_BOOKS_CACHE[self.db_path] = (time.monotonic(), books)
        return list(books)

    def _list_books_uncached(self) -> list[dict]:
        """
        Was an N+1 query pattern: per book, a separate query for formats, an
        os.path.exists() filesystem stat for the cover, and PER CUSTOM COLUMN
        two more queries (one of which — "is this column normalized?" —
        depends only on the column's schema, not the book, so it returned
        the exact same answer 1200 times for nothing). For a 1200-book
        library with the 3 custom columns a typical Kolibre library has,
        that's ~9600 separate round trips for one page load — cheap on a
        local SSD, but each of those costs real milliseconds instead of
        microseconds on a Docker bind-mounted volume, which is where this
        was reported as "davvero davvero lento". Replaced with: the
        normalized-or-not check done once per column (not per book), and
        formats/custom-column values fetched with one query each covering
        every book at once, then joined onto each book from an in-memory
        dict — same total data, a constant number of queries regardless of
        library size instead of one (or two) per book.
        """
        conn = self._connect()
        try:
            rows = conn.execute(self._books_select_sql() + " ORDER BY b.id").fetchall()
            return self._build_books(conn, rows)
        finally:
            conn.close()

    def _books_select_sql(self) -> str:
        """La SELECT dei libri, senza ORDER BY ne' LIMIT: la usano sia la
        lettura completa sia quella a pagine (list_books_page)."""
        return f"""
                SELECT b.id, b.title, b.path, b.timestamp, b.series_index, b.has_cover,
                       b.sort AS title_sort, b.author_sort, b.uuid, b.pubdate, b.last_modified,
                       (SELECT GROUP_CONCAT(name, '{self._ID_PAIR_SEP}') FROM (
                            SELECT a.name AS name FROM books_authors_link bal
                            JOIN authors a ON a.id = bal.author
                            WHERE bal.book = b.id ORDER BY bal.id)) AS author_str,
                       (SELECT name FROM series WHERE id = (
                            SELECT series FROM books_series_link WHERE book = b.id LIMIT 1)) AS series,
                       (SELECT GROUP_CONCAT(name, ', ') FROM tags
                            WHERE id IN (SELECT tag FROM books_tags_link WHERE book = b.id)) AS tag_str,
                       (SELECT name FROM publishers WHERE id = (
                            SELECT publisher FROM books_publishers_link WHERE book = b.id LIMIT 1)) AS publisher,
                       (SELECT lang_code FROM languages WHERE id = (
                            SELECT lang_code FROM books_languages_link WHERE book = b.id
                            ORDER BY item_order LIMIT 1)) AS language,
                       (SELECT rating FROM ratings WHERE id = (
                            SELECT rating FROM books_ratings_link WHERE book = b.id LIMIT 1)) AS rating_raw,
                       (SELECT GROUP_CONCAT(type || '{self._ID_KV_SEP}' || val, '{self._ID_PAIR_SEP}')
                            FROM identifiers WHERE book = b.id) AS identifiers_str,
                       (SELECT text FROM comments WHERE book = b.id) AS description,
                       -- La somma dei formati: e' la "Dimensione" che la
                       -- tabella mostra, e serve per potercisi ordinare
                       -- anche quando la biblioteca e' impaginata.
                       (SELECT COALESCE(SUM(uncompressed_size), 0) FROM data WHERE book = b.id) AS dimensione
                FROM books b
                """

    def _build_books(self, conn, rows, solo_ids: "Optional[list]" = None) -> list[dict]:
        """Da righe grezze ai dizionari completi. `solo_ids` restringe le
        query di contorno (formati, colonne personalizzate) ai libri di
        questa pagina: senza, impaginare non servirebbe a niente — si
        leggerebbe comunque l'intera tabella `data` a ogni pagina."""
        # Stessa esclusione di list_custom_columns, e per lo stesso motivo:
        # senza, ogni libro si portava dietro un campo in piu' con un valore
        # gia' presente in un altro campo — peso inutile su una biblioteca
        # grande, oltre che confusione.
        custom_cols = conn.execute(
            "SELECT id, label FROM custom_columns WHERE mark_for_delete = 0 AND label != ?",
            (CALIBRE_PAGE_COUNT_COLUMN_LABEL,),
        ).fetchall()

        # One query total for every book's formats, instead of one query
        # PER book (data has no index concern here: it's already scanned
        # in full either way, just once now instead of N times).
        dove = ""
        parametri: list = []
        if solo_ids is not None:
            dove = f" WHERE book IN ({','.join('?' * len(solo_ids))})"
            parametri = list(solo_ids)

        formats_by_book: dict[int, list[dict]] = {}
        for r in conn.execute("SELECT book, format, name, uncompressed_size AS size FROM data" + dove, parametri):
            formats_by_book.setdefault(r["book"], []).append(dict(r))

        # One pair of queries PER COLUMN (not per book): the normalized
        # check is schema-level and identical for every book, so it's
        # computed once here instead of matching the old code's habit of
        # asking the same question 1200 times per column.
        custom_values_by_col: dict[int, dict[int, object]] = {}
        for col in custom_cols:
            col_id = col["id"]
            values: dict[int, object] = {}
            if self._is_normalized_column(conn, col_id):
                query = (
                    f"SELECT l.book AS book, cc.value AS value FROM books_custom_column_{col_id}_link l "
                    f"JOIN custom_column_{col_id} cc ON cc.id = l.value"
                    + (dove.replace("book IN", "l.book IN") if solo_ids is not None else "")
                )
            else:
                query = f"SELECT book, value FROM custom_column_{col_id}" + dove
            for r in conn.execute(query, parametri):
                # setdefault, not [] =, to match the old per-book query's
                # own "LIMIT 1"/first-row semantics for the normalized
                # (potentially multi-row-per-book) case.
                values.setdefault(r["book"], r["value"])
            custom_values_by_col[col_id] = values

        books = []
        for row in rows:
            book = dict(row)
            # Multi-author: joined for display with Calibre's own
            # authors_to_string (' & ' between authors, a literal '&'
            # inside one name escaped as '&&'), from an ORDER BY bal.id
            # subquery so the original author order survives the trip.
            author_str = book.pop("author_str")
            book["author"] = authors_to_string(author_str.split(self._ID_PAIR_SEP)) if author_str else None
            tag_str = book.pop("tag_str")
            book["tags"] = [t.strip() for t in tag_str.split(",")] if tag_str else []
            # Calibre's real native rating is stored 0-10 (2 units per
            # star, half-star granularity) — Kolibre's own UI has no
            # half-star support anywhere, so this rounds to a plain 0-5
            # star count, matching the convention already used for
            # custom rating-type columns everywhere else in this app.
            rating_raw = book.pop("rating_raw")
            book["rating"] = round(rating_raw / 2) if rating_raw else None
            identifiers_str = book.pop("identifiers_str")
            book["identifiers"] = (
                dict(pair.split(self._ID_KV_SEP, 1) for pair in identifiers_str.split(self._ID_PAIR_SEP))
                if identifiers_str else {}
            )
            formats = formats_by_book.get(book["id"], [])
            book["formats"] = [f["format"] for f in formats]
            book["size"] = sum(f["size"] for f in formats)
            # Most callers only check this field's truthiness, but at
            # least one (library_transfer.py's "Copia nella biblioteca")
            # actually opens the file at this path to copy the cover, so
            # it must stay a real, usable path — just built from string
            # concatenation instead of an os.path.exists() syscall per
            # book. Every real consumer of this path (get_cover_path(),
            # the copy-to-library code above) already re-checks
            # existence itself before opening anything, so skipping the
            # check here (trusting Calibre's own has_cover flag instead)
            # changes no behavior, only removes a per-book syscall.
            book["cover_path"] = (
                os.path.join(self.path, book["path"], "cover.jpg")
                if book["has_cover"] and book["path"] else None
            )
            for col in custom_cols:
                book[f"#{col['label']}"] = custom_values_by_col[col["id"]].get(book["id"])
            books.append(book)
        return books

    # Colonne su cui SQLite sa ordinare da solo. Sono quelle che stanno
    # nella riga del libro o in una sottoquery della SELECT: ordinare per
    # avanzamento di lettura o per stato del dispositivo non si puo' qui,
    # perche' quei dati vivono in app.db e non in metadata.db — l'interfaccia
    # lo dichiara invece di ordinare per finta.
    _ORDINAMENTI = {
        "title": "b.sort",
        "author": "b.author_sort",
        "series": "series",
        "date_added": "b.timestamp",
        "pubdate": "b.pubdate",
        "last_modified": "b.last_modified",
        "rating": "rating_raw",
        "id": "b.id",
        # Stanno in metadata.db come tutto il resto: non c'era motivo di
        # lasciarli fuori, e in modalita' impaginata erano due colonne su cui
        # la tabella semplicemente non si lasciava ordinare.
        "size": "dimensione",
        "series_index": "b.series_index",
    }

    def count_books(self) -> int:
        conn = self._connect()
        try:
            return conn.execute("SELECT COUNT(*) AS c FROM books").fetchone()["c"]
        finally:
            conn.close()

    def list_books_page(
        self, limit: int, offset: int = 0, sort: str = "date_added",
        order: str = "desc", q: str = "",
    ) -> tuple:
        """
        Una pagina di libri, filtrata e ordinata da SQLite. Restituisce
        (libri, totale_che_corrisponde).

        Esiste perche' leggere tutto non regge oltre una certa taglia:
        misurato su 100.000 libri, `list_books()` impiega 7 secondi e 285 MB
        di memoria, e la risposta HTTP pesa 66 MB. Qui le sottoquery per
        autore, serie, tag e identificativi girano solo sulle righe della
        pagina, e le query di contorno sono ristrette agli stessi id.

        `q` e' il linguaggio di ricerca completo, lo stesso che si scrive
        nella barra sotto la soglia di impaginazione: campi (`tags:`,
        `publisher:`, `#colonna:`), corrispondenza esatta con `=`, `and`,
        `or`, `not` e parentesi. La traduzione in SQL sta in query_sql.py.
        Prima qui c'era un LIKE su titolo/autore/serie, e su una biblioteca
        grande la ricerca smetteva di funzionare proprio dove serviva:
        `tags:"=filosofia"` veniva cercato alla lettera, e il Navigatore
        Biblioteca — che scrive esattamente quelle stringhe — non filtrava
        piu' niente.
        """
        colonna = self._ORDINAMENTI.get(sort, self._ORDINAMENTI["date_added"])
        direzione = "DESC" if str(order).lower() == "desc" else "ASC"
        conn = self._connect()
        try:
            dove, parametri = "", []
            if q and q.strip():
                colonne_custom = {
                    r["label"]: {"id": r["id"], "normalized": bool(r["normalized"])}
                    for r in conn.execute(
                        "SELECT id, label, normalized FROM custom_columns WHERE mark_for_delete = 0"
                    ).fetchall()
                }
                filtro, parametri = query_sql.where_da_query(q, colonne_custom)
                if filtro:
                    dove = f"WHERE {filtro}"

            totale = conn.execute(
                f"SELECT COUNT(*) AS c FROM books b {dove}", parametri
            ).fetchone()["c"]

            # NULLS LAST a mano: SQLite mette i NULL sempre per primi, e una
            # pagina che si apre su venti righe vuote sembra un errore.
            rows = conn.execute(
                f"{self._books_select_sql()} {dove} "
                f"ORDER BY ({colonna} IS NULL), {colonna} {direzione}, b.id {direzione} "
                f"LIMIT ? OFFSET ?",
                parametri + [int(limit), max(0, int(offset))],
            ).fetchall()
            libri = self._build_books(conn, rows, solo_ids=[r["id"] for r in rows])
            return libri, totale
        finally:
            conn.close()

    # ── I valori distinti dei campi, coi conteggi ────────────────────────
    #
    # Il Navigatore Biblioteca costruiva il suo albero dai libri CARICATI:
    # sopra la soglia di impaginazione erano duecento, e l'albero elencava i
    # valori di quella pagina spacciandoli per quelli della biblioteca. Da
    # qui arrivano invece quelli veri, contati da SQLite sull'intera query
    # corrente — un GROUP BY per tabella di collegamento, non un'andata e
    # ritorno di 5.841 libri per contare sette campi.
    #
    # Gli stessi campi fissi del Navigatore (`buildFieldDefs` nel frontend)
    # piu' le colonne personalizzate non-data. Le colonne `is_multiple`
    # (tag-like) hanno la loro tabella di collegamento come autori e tag; le
    # altre tengono il valore in una tabella per colonna.
    _CAMPI_MULTIVALORE = {
        "tags": ("books_tags_link", "tag", "tags", "name"),
        "author": ("books_authors_link", "author", "authors", "name"),
        "publisher": ("books_publishers_link", "publisher", "publishers", "name"),
        "language": ("books_languages_link", "lang_code", "languages", "lang_code"),
    }

    def valori_dei_campi(self, q: str = "", limite_per_campo: int = 500) -> dict:
        """
        {chiave_campo: [{valore, libri}, ...]} sui libri che corrispondono a
        `q`. Le chiavi sono le stesse del Navigatore: tags, author, series,
        formats, publisher, language, rating, e "#etichetta" per ogni colonna
        personalizzata.

        `limite_per_campo` esiste perche' un campo puo' avere piu' valori che
        libri — 4.982 autori distinti su 5.841 libri — e un elenco cosi' non
        e' navigabile comunque: si tagliano i meno frequenti, e il chiamante
        sa quanti ne mancano dal totale dichiarato.
        """
        conn = self._connect()
        try:
            colonne_custom = {
                r["label"]: {"id": r["id"], "normalized": bool(r["normalized"]), "datatype": r["datatype"]}
                for r in conn.execute(
                    "SELECT id, label, normalized, datatype FROM custom_columns WHERE mark_for_delete = 0"
                ).fetchall()
            }
            dove, parametri = "", []
            if q and q.strip():
                filtro, parametri = query_sql.where_da_query(
                    q, {k: {"id": v["id"], "normalized": v["normalized"]} for k, v in colonne_custom.items()}
                )
                if filtro:
                    dove = f"WHERE {filtro}"
            # Una sola volta: gli id che la query seleziona. Tutti i conteggi
            # qui sotto si appoggiano a questa, invece di ripetere il filtro
            # (e le sue sottoquery) sette volte.
            selezionati = f"SELECT b.id FROM books b {dove}"

            risultato = {}

            def conta(chiave, sql):
                righe = conn.execute(sql, parametri).fetchall()
                risultato[chiave] = [
                    {"valore": str(r["valore"]), "libri": r["libri"]}
                    for r in righe if r["valore"] not in (None, "")
                ]

            for chiave, (legame, colonna_legame, tabella, colonna_valore) in self._CAMPI_MULTIVALORE.items():
                conta(chiave, f"""
                    SELECT v.{colonna_valore} AS valore, COUNT(*) AS libri
                    FROM {legame} l JOIN {tabella} v ON v.id = l.{colonna_legame}
                    WHERE l.book IN ({selezionati})
                    GROUP BY v.{colonna_valore} ORDER BY libri DESC LIMIT {int(limite_per_campo)}
                """)

            conta("series", f"""
                SELECT s.name AS valore, COUNT(*) AS libri
                FROM books_series_link l JOIN series s ON s.id = l.series
                WHERE l.book IN ({selezionati})
                GROUP BY s.name ORDER BY libri DESC LIMIT {int(limite_per_campo)}
            """)
            conta("formats", f"""
                SELECT d.format AS valore, COUNT(*) AS libri FROM data d
                WHERE d.book IN ({selezionati})
                GROUP BY d.format ORDER BY libri DESC LIMIT {int(limite_per_campo)}
            """)
            conta("rating", f"""
                SELECT r.rating / 2 AS valore, COUNT(*) AS libri
                FROM books_ratings_link l JOIN ratings r ON r.id = l.rating
                WHERE l.book IN ({selezionati})
                GROUP BY r.rating ORDER BY valore DESC LIMIT 10
            """)

            for etichetta, colonna in colonne_custom.items():
                if colonna["datatype"] == "datetime":
                    continue
                tabella = f"custom_column_{colonna['id']}"
                if colonna["normalized"]:
                    sql = f"""
                        SELECT v.value AS valore, COUNT(*) AS libri
                        FROM books_{tabella}_link l JOIN {tabella} v ON v.id = l.value
                        WHERE l.book IN ({selezionati})
                        GROUP BY v.value ORDER BY libri DESC LIMIT {int(limite_per_campo)}
                    """
                else:
                    sql = f"""
                        SELECT v.value AS valore, COUNT(*) AS libri FROM {tabella} v
                        WHERE v.book IN ({selezionati})
                        GROUP BY v.value ORDER BY libri DESC LIMIT {int(limite_per_campo)}
                    """
                try:
                    conta(f"#{etichetta}", sql)
                except sqlite3.Error:
                    # Una colonna personalizzata con una forma che non
                    # conosciamo non deve far cadere tutto l'albero.
                    risultato[f"#{etichetta}"] = []

            return risultato
        finally:
            conn.close()

    def get_identifiers(self, book_id: int) -> dict:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT type, val FROM identifiers WHERE book = ?", (book_id,)).fetchall()
            return {r["type"]: r["val"] for r in rows}
        finally:
            conn.close()

    def get_book(self, book_id: int) -> Optional[dict]:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_book_author(self, book_id: int) -> Optional[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT a.name FROM books_authors_link bal JOIN authors a ON a.id = bal.author "
                "WHERE bal.book = ? ORDER BY bal.id",
                (book_id,),
            ).fetchall()
            return authors_to_string([r["name"] for r in rows]) if rows else None
        finally:
            conn.close()

    def list_book_paths(self) -> set:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT path FROM books WHERE path != ''").fetchall()
            return {r["path"] for r in rows}
        finally:
            conn.close()

    def get_formats(self, book_id: int) -> list[dict]:
        conn = self._connect()
        try:
            return self._get_formats(conn, book_id)
        finally:
            conn.close()

    @staticmethod
    def _get_formats(conn: sqlite3.Connection, book_id: int) -> list[dict]:
        rows = conn.execute(
            "SELECT format, uncompressed_size AS size, name FROM data WHERE book = ?",
            (book_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_format_file_path(self, book_id: int, fmt: str) -> Optional[str]:
        conn = self._connect()
        try:
            book_row = conn.execute("SELECT path FROM books WHERE id = ?", (book_id,)).fetchone()
            if not book_row or not book_row["path"]:
                return None
            data_row = conn.execute(
                "SELECT name FROM data WHERE book = ? AND format = ?", (book_id, fmt.upper())
            ).fetchone()
            if not data_row:
                return None
            file_path = os.path.join(self.path, book_row["path"], f"{data_row['name']}.{fmt.lower()}")
            return file_path if os.path.exists(file_path) else None
        finally:
            conn.close()

    def get_description(self, book_id: int) -> Optional[str]:
        """Untruncated companion to the excerpt api/books.py's list_books()
        sends in bulk — a single targeted query, not the full list_books()
        machinery, since this only ever needs one book's comments text."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT text FROM comments WHERE book = ?", (book_id,)).fetchone()
            return row["text"] if row else None
        finally:
            conn.close()

    def get_cover_path(self, book_id: int) -> Optional[str]:
        conn = self._connect()
        try:
            row = conn.execute("SELECT path, has_cover FROM books WHERE id = ?", (book_id,)).fetchone()
            if not row or not row["has_cover"]:
                return None
            return self._cover_fs_path(row["path"])
        finally:
            conn.close()

    def _cover_fs_path(self, relative_book_path: str) -> Optional[str]:
        if not relative_book_path:
            return None
        cover_fs_path = os.path.join(self.path, relative_book_path, "cover.jpg")
        return cover_fs_path if os.path.exists(cover_fs_path) else None

    def get_custom_column_value(self, book_id: int, label: str):
        conn = self._connect()
        try:
            col = conn.execute("SELECT id FROM custom_columns WHERE label = ?", (label,)).fetchone()
            if not col:
                return None
            return self._read_custom_value(conn, col["id"], book_id)
        finally:
            conn.close()

    def list_custom_columns(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                # mark_for_delete: e' il modo con cui Calibre ritira una
                # colonna — la tabella resta sul disco ma la colonna non si
                # mostra piu'. Kolibre le mostrava lo stesso, quindi una
                # colonna ritirata da Calibre Desktop continuava a comparire
                # qui (e una ritirata da noi sarebbe rimasta visibile).
                # Fuori anche la colonna specchio (#pagine_stimate): esiste
                # SOLO perche' Calibre Desktop la riconosca come colonna
                # personalizzata vera, e porta lo stesso identico valore di
                # `pages`. Qui dentro non aggiunge niente — mostrava due
                # volte lo stesso numero, ed era il difetto riscontrato
                # in uso: in una biblioteca che in Calibre non si apre mai
                # e' un doppione e basta. Vedi CALIBRE_PAGE_COUNT_COLUMN_LABEL.
                "SELECT id, label, name, datatype, display FROM custom_columns "
                "WHERE mark_for_delete = 0 AND label != ? ORDER BY id",
                (CALIBRE_PAGE_COUNT_COLUMN_LABEL,),
            ).fetchall()
            cols = []
            for r in rows:
                col = dict(r)
                try:
                    col["display"] = json.loads(col["display"]) if col["display"] else {}
                except (TypeError, ValueError):
                    col["display"] = {}
                cols.append(col)
            return cols
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Writes — call these through CalibreWriteQueue.submit(), not directly,
    # to guarantee they never run concurrently against the same metadata.db.
    # ------------------------------------------------------------------

    @staticmethod
    def _link_authors(conn: sqlite3.Connection, book_id: int, author_str: str) -> str:
        """
        Replaces a book's author links with the (possibly multiple) authors
        in `author_str`, split exactly like Calibre does ('&' separates two
        authors, '&&' escapes a literal ampersand inside one name — see
        functions.string_to_authors). Each name is upserted into `authors`
        and linked in input order; books_authors_link's autoincrement ids
        preserve that order, which is what list_books' ordered read joins
        back together. Returns the combined author_sort (per-author sorts
        joined with ' & ', matching what real Calibre writes into
        books.author_sort for multi-author books).
        """
        conn.execute("DELETE FROM books_authors_link WHERE book = ?", (book_id,))
        sorts = []
        for name in string_to_authors(author_str or ""):
            sort = author_to_author_sort(name)
            conn.execute(
                "INSERT INTO authors (name, sort) VALUES (?, ?) ON CONFLICT(name) DO NOTHING",
                (name, sort),
            )
            row = conn.execute("SELECT id FROM authors WHERE name = ?", (name,)).fetchone()
            conn.execute(
                "INSERT INTO books_authors_link (book, author) VALUES (?, ?)",
                (book_id, row["id"]),
            )
            sorts.append(sort)
        # Same cleanup Calibre's own clean_standard_field does after a
        # relink: an author left with zero books would otherwise linger in
        # the Autori page forever with a count of 0.
        conn.execute("DELETE FROM authors WHERE id NOT IN (SELECT author FROM books_authors_link)")
        return " & ".join(sorts)

    def insert_book(self, title: str, author: str, has_cover: bool = False, timestamp: Optional[str] = None) -> int:
        """
        Inserts a bare book row (books_insert_trg fills sort/uuid). `path` is left
        at its schema default ('') — the caller computes the on-disk folder name
        (which conventionally embeds this book's id, e.g. "Autore/Titolo (id)")
        only after this returns, then calls update_book(book_id, {"path": ...}).

        `timestamp` is Calibre's real "Aggiunto"/"date added" field — distinct
        from `last_modified` (when the ROW was last edited). Left unset, it
        falls back to the schema's own `CURRENT_TIMESTAMP` default (now),
        which is correct for a book created fresh in Kolibre itself, but the
        Calibre-plugin upload path passes the source book's real Calibre
        `timestamp` here so a pushed library doesn't show today's date as
        every book's "Aggiunto" (reported directly: it showed the migration
        date instead of Calibre's own).
        """
        conn = self._connect()
        try:
            author_sort = " & ".join(author_to_author_sort(n) for n in string_to_authors(author or ""))
            if timestamp:
                cur = conn.execute(
                    "INSERT INTO books (title, author_sort, has_cover, last_modified, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (title, author_sort, int(has_cover), _now_iso(), timestamp),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO books (title, author_sort, has_cover, last_modified) VALUES (?, ?, ?, ?)",
                    (title, author_sort, int(has_cover), _now_iso()),
                )
            book_id = cur.lastrowid
            self._link_authors(conn, book_id, author)
            conn.commit()
            return book_id
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def add_format(self, book_id: int, fmt: str, size_bytes: int, name: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO data (book, format, uncompressed_size, name) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(book, format) DO UPDATE SET uncompressed_size=excluded.uncompressed_size, name=excluded.name",
                (book_id, fmt.upper(), size_bytes, name),
            )
            conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), book_id))
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def set_identifier(self, book_id: int, id_type: str, value: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO identifiers (book, type, val) VALUES (?, ?, ?) "
                "ON CONFLICT(book, type) DO UPDATE SET val=excluded.val",
                (book_id, id_type, value),
            )
            conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), book_id))
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def set_identifiers(self, book_id: int, identifiers: dict) -> None:
        """Replaces the ENTIRE identifier set for a book in one go (delete +
        insert) — unlike set_identifier above, which only upserts a single
        type. The metadata editor shows/edits several rows at once (isbn,
        google, amazon, ...), so a save has to express "this is now the
        complete set" including removals, not just upsert whatever's present."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM identifiers WHERE book = ?", (book_id,))
            for id_type, value in (identifiers or {}).items():
                if id_type and value:
                    conn.execute(
                        "INSERT INTO identifiers (book, type, val) VALUES (?, ?, ?)",
                        (book_id, id_type, value),
                    )
            conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), book_id))
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def set_book_tags(self, book_id: int, tags: list) -> None:
        """Replaces the entire tag set for a book by name — same upsert-by-
        name + repoint-links pattern update_book already uses for `author`."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM books_tags_link WHERE book = ?", (book_id,))
            for name in tags or []:
                name = (name or "").strip()
                if not name:
                    continue
                conn.execute("INSERT INTO tags (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (name,))
                tag_row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
                conn.execute(
                    "INSERT INTO books_tags_link (book, tag) VALUES (?, ?) ON CONFLICT(book, tag) DO NOTHING",
                    (book_id, tag_row["id"]),
                )
            conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), book_id))
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def set_book_series(self, book_id: int, series_name: str, series_index: float = None) -> None:
        """books_series_link has UNIQUE(book) — a book belongs to at most one
        series, so this is delete+insert-or-nothing rather than a multi-row
        replace like set_book_tags."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM books_series_link WHERE book = ?", (book_id,))
            series_name = (series_name or "").strip()
            if series_name:
                conn.execute("INSERT INTO series (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (series_name,))
                series_row = conn.execute("SELECT id FROM series WHERE name = ?", (series_name,)).fetchone()
                conn.execute(
                    "INSERT INTO books_series_link (book, series) VALUES (?, ?)",
                    (book_id, series_row["id"]),
                )
            if series_index is not None:
                conn.execute("UPDATE books SET series_index = ? WHERE id = ?", (series_index, book_id))
            conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), book_id))
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def set_rating(self, book_id: int, stars) -> None:
        """
        books_ratings_link has UNIQUE(book) — same delete+insert-or-nothing
        shape as set_book_series. `stars` is Kolibre's own 0-5 display scale
        (matching every rating-type custom column already in this app);
        Calibre's real `ratings.rating` column stores 0-10 (CHECK(rating > -1
        AND rating < 11) in schema.sql — 2 units per star), so it's doubled
        here before writing. `ratings` has UNIQUE(rating) — like `series`'
        upsert-by-name, this upserts by VALUE instead (ON CONFLICT DO NOTHING
        since the row is just a shared value, nothing else to update).
        """
        conn = self._connect()
        try:
            conn.execute("DELETE FROM books_ratings_link WHERE book = ?", (book_id,))
            if stars:
                raw = round(float(stars) * 2)
                # Fuori scala si ignora, non si esplode. La colonna ha un
                # CHECK(rating > -1 AND rating < 11) e un valore fuori
                # intervallo solleva IntegrityError: dentro il caricamento di
                # un libro dal plugin Calibre, quell'eccezione faceva fallire
                # l'INTERO libro per via di un campo solo — sproporzionato,
                # e per giunta su un dato accessorio. Un cliente che manda
                # gia' la scala 0-10 di Calibre invece delle stelle finisce
                # esattamente qui.
                if not 0 <= raw <= 10:
                    logging.getLogger("kolibre.calibre").warning(
                        "Valutazione fuori scala per il libro %s: %s stelle (%s grezzo), ignorata",
                        book_id, stars, raw,
                    )
                    conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), book_id))
                    conn.commit()
                    dimentica_lista_libri(self.db_path)
                    return
                conn.execute("INSERT INTO ratings (rating) VALUES (?) ON CONFLICT(rating) DO NOTHING", (raw,))
                rating_row = conn.execute("SELECT id FROM ratings WHERE rating = ?", (raw,)).fetchone()
                conn.execute(
                    "INSERT INTO books_ratings_link (book, rating) VALUES (?, ?)",
                    (book_id, rating_row["id"]),
                )
            conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), book_id))
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def set_publisher(self, book_id: int, name: str) -> None:
        """books_publishers_link has UNIQUE(book) — one publisher per book,
        matching real Calibre's own schema constraint."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM books_publishers_link WHERE book = ?", (book_id,))
            name = (name or "").strip()
            if name:
                conn.execute("INSERT INTO publishers (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (name,))
                pub_row = conn.execute("SELECT id FROM publishers WHERE name = ?", (name,)).fetchone()
                conn.execute(
                    "INSERT INTO books_publishers_link (book, publisher) VALUES (?, ?)",
                    (book_id, pub_row["id"]),
                )
            conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), book_id))
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def set_language(self, book_id: int, lang_code: str) -> None:
        """books_languages_link's schema supports multiple languages per book
        (UNIQUE(book, lang_code), with item_order) — this replaces the whole
        set with at most one entry, since the editor UI exposes a single
        select for now (see PROJECT plan: multi-language stays a future
        extension, the schema is already ready for it when that happens)."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM books_languages_link WHERE book = ?", (book_id,))
            lang_code = (lang_code or "").strip()
            if lang_code:
                conn.execute("INSERT INTO languages (lang_code) VALUES (?) ON CONFLICT(lang_code) DO NOTHING", (lang_code,))
                lang_row = conn.execute("SELECT id FROM languages WHERE lang_code = ?", (lang_code,)).fetchone()
                conn.execute(
                    "INSERT INTO books_languages_link (book, lang_code, item_order) VALUES (?, ?, 0)",
                    (book_id, lang_row["id"]),
                )
            conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), book_id))
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def set_comments(self, book_id: int, text: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO comments (book, text) VALUES (?, ?) "
                "ON CONFLICT(book) DO UPDATE SET text=excluded.text",
                (book_id, text),
            )
            conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), book_id))
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def set_cover(self, book_id: int, image_b64: str) -> None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT path FROM books WHERE id = ?", (book_id,)).fetchone()
            if not row or not row["path"]:
                return
            folder = os.path.join(self.path, row["path"])
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "cover.jpg"), "wb") as f:
                f.write(base64.b64decode(image_b64))
            conn.execute(
                "UPDATE books SET has_cover = 1, last_modified = ? WHERE id = ?", (_now_iso(), book_id)
            )
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def remove_format(self, book_id: int, fmt: str) -> None:
        """
        Removes a single format from a book: the `data` row and the actual
        file on disk. Refuses to remove the book's only remaining format —
        that would leave a book with no content file, which the ingest/import
        flow never produces on purpose; delete the whole book instead.
        """
        conn = self._connect()
        try:
            remaining = conn.execute("SELECT COUNT(*) AS c FROM data WHERE book = ?", (book_id,)).fetchone()["c"]
            if remaining <= 1:
                raise ValueError("Impossibile eliminare l'unico formato rimasto: elimina l'intero libro invece.")
            row = conn.execute(
                "SELECT name FROM data WHERE book = ? AND format = ?", (book_id, fmt.upper())
            ).fetchone()
            if not row:
                return
            book_row = conn.execute("SELECT path FROM books WHERE id = ?", (book_id,)).fetchone()
            conn.execute("DELETE FROM data WHERE book = ? AND format = ?", (book_id, fmt.upper()))
            conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), book_id))
            conn.commit()
            if book_row and book_row["path"]:
                file_path = os.path.join(self.path, book_row["path"], f"{row['name']}.{fmt.lower()}")
                if os.path.exists(file_path):
                    os.remove(file_path)
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def touch_last_modified(self, book_id: int) -> None:
        """
        For writers that live outside this class entirely — the TOC editor
        (backend/app/api/books.py) edits the EPUB/PDF file directly on disk,
        bypassing every method here, so it has no other way to record that
        the book changed.
        """
        conn = self._connect()
        try:
            conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), book_id))
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def update_book(self, book_id: int, fields: dict) -> None:
        # "timestamp" (real "date added") is included so a retroactive fix
        # can correct it after the fact — a normal create always sets it via
        # insert_book's own `timestamp` kwarg instead, never through here.
        # "pubdate" (real "Data di pubblicazione", distinct from timestamp)
        # was never writable at all before — Calibre's own plugin push now
        # sends it, and this is the only path that can persist it.
        allowed_columns = {"title", "path", "series_index", "has_cover", "timestamp", "pubdate"}
        set_clauses = []
        values = []
        for key, value in fields.items():
            if key in allowed_columns:
                if key == "series_index" and value in (None, ""):
                    # books.series_index is NOT NULL DEFAULT 1.0 in the real
                    # Calibre schema — a caller clearing the "N. Serie" field
                    # (empty string) or explicitly sending null (e.g. after
                    # clearing a series name too) used to hit a raw
                    # IntegrityError/500 instead of just resetting to the
                    # same default Calibre itself uses for "no real value".
                    value = 1.0
                set_clauses.append(f"{key} = ?")
                values.append(value)
        conn = self._connect()
        spostamenti, traslochi = [], []
        try:
            if "author" in fields:
                # `author` isn't a books column, it's a relation
                # (books_authors_link, one row per author) — relink and keep
                # author_sort in sync, exactly like insert_book does when a
                # book is first created.
                author_sort = self._link_authors(conn, book_id, fields["author"] or "")
                set_clauses.append("author_sort = ?")
                values.append(author_sort)

            if fields:
                # Stamped unconditionally whenever this is called with any
                # field at all — including a custom-column-only update
                # (e.g. just "#pages"), which otherwise leaves
                # set_clauses empty and would never touch last_modified.
                set_clauses.append("last_modified = ?")
                values.append(_now_iso())

            if set_clauses:
                values.append(book_id)
                conn.execute(f"UPDATE books SET {', '.join(set_clauses)} WHERE id = ?", values)

            custom_field_keys = {k for k in fields if k.startswith("#")}
            if custom_field_keys:
                cols_by_label = {
                    r["label"]: r["id"]
                    for r in conn.execute("SELECT id, label FROM custom_columns").fetchall()
                }
                for key in custom_field_keys:
                    col_id = cols_by_label.get(key[1:])
                    if col_id is None:
                        continue
                    self._write_custom_value(conn, col_id, book_id, fields[key])

            # Cambiato l'autore o il titolo, il libro va anche SPOSTATO:
            # prima restava nella cartella del nome vecchio, e la biblioteca
            # sul disco smetteva di corrispondere ai metadati. Sono gli stessi
            # due campi su cui Calibre ricostruisce il percorso
            # (`update_path = name in {'title', 'authors'}`).
            #
            # `path` esplicito nei campi significa invece "mettilo ESATTAMENTE
            # qui" — e' come l'importazione registra la cartella appena
            # creata, e li' non c'e' niente da ricalcolare.
            if ("author" in fields or "title" in fields) and "path" not in fields:
                mossa = self._porta_a_posto(
                    conn, book_id,
                    titolo=fields.get("title"),
                    autore=fields.get("author"),
                )
                spostamenti.extend(mossa["annulla"])
                if mossa["mossa"]:
                    traslochi.append(mossa["mossa"])
            conn.commit()
        except Exception:
            _rimetti_a_posto(spostamenti)
            raise
        finally:
            conn.close()
        # L'elenco dei libri e' in cache per cinque secondi (vedi
        # _LIST_BOOKS_CACHE): senza dimenticarlo, chi rilegge subito dopo
        # aver salvato riceve i valori di PRIMA della modifica. Non si
        # notava quando l'unico modo di modificare era il pannello dei
        # metadati, che si chiude e fa passare un attimo; e' saltato fuori
        # con la spunta "letto", che si preme e guarda nello stesso istante.
        # bulk_update_books e il rinomino d'autore lo facevano gia': mancava
        # solo qui.
        dimentica_lista_libri(self.db_path)
        _pulisci_cartelle_vuote(traslochi, self.path)

    def bulk_update_books(
        self,
        book_ids: list,
        fields: Optional[dict] = None,
        tags_add: Optional[list] = None,
        tags_remove: Optional[list] = None,
    ) -> int:
        """
        Applica gli STESSI campi a molti libri in una sola transazione.

        Esiste per non ripetere N volte il giro completo di update_book +
        set_publisher + set_language + ... : ognuno di quelli apre la sua
        connessione e fa il suo commit, e un rinomino d'autore su tutti i
        libri di un autore (il caso da cui nasce questa funzione: "Rossi
        Mario" da correggere in "Mario Rossi") ne farebbe centinaia. Qui c'e'
        una connessione sola e un commit solo: o passa tutto o non passa
        niente, che per una modifica di massa e' anche la semantica giusta.

        `fields` usa le stesse chiavi del PUT su un libro singolo — author,
        series, series_index, publisher, language, rating, description,
        pubdate e le colonne personalizzate come "#etichetta". Una chiave
        assente NON viene toccata; una chiave presente con valore None
        AZZERA quel campo (e' la distinzione che il dialog di modifica in
        blocco fa vedere come "Non modificare" contro "—").

        I tag, a differenza di tutto il resto, sono additivi/sottrattivi e
        non sostitutivi: `tags_add` e `tags_remove` agiscono sull'insieme
        che ogni libro ha gia', perche' in blocco "metti anche questo tag"
        e' l'operazione che serve, mentre "sostituisci i tag di tutti con
        questi" cancellerebbe informazione a ogni uso.

        Torna il numero di libri effettivamente toccati.
        """
        fields = dict(fields or {})
        tags_add = [t.strip() for t in (tags_add or []) if (t or "").strip()]
        tags_remove = [t.strip() for t in (tags_remove or []) if (t or "").strip()]
        if not book_ids or (not fields and not tags_add and not tags_remove):
            return 0

        # Estratti da `fields` prima del ciclo: sono relazioni, non colonne
        # di `books`, e ognuna ha la sua tabella di collegamento. Stessa
        # separazione che fa l'endpoint PUT sul libro singolo, con la stessa
        # sentinella per distinguere "chiave assente" da "chiave a None".
        _unset = object()
        series_name = fields.pop("series", _unset)
        series_index = fields.pop("series_index", _unset)
        publisher = fields.pop("publisher", _unset)
        language = fields.pop("language", _unset)
        description = fields.pop("description", _unset)
        rating = fields.pop("rating", _unset)
        author = fields.pop("author", _unset)

        allowed_columns = {"title", "pubdate", "timestamp"}
        colonne_semplici = {k: v for k, v in fields.items() if k in allowed_columns}
        custom_keys = [k for k in fields if k.startswith("#")]

        conn = self._connect()
        spostamenti, traslochi = [], []
        try:
            cols_by_label = {}
            if custom_keys:
                cols_by_label = {
                    r["label"]: r["id"]
                    for r in conn.execute("SELECT id, label FROM custom_columns").fetchall()
                }

            adesso = _now_iso()
            toccati = 0
            for book_id in book_ids:
                if not conn.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
                    # Un libro cancellato mentre il dialog era aperto non
                    # deve far fallire tutta la modifica di massa.
                    continue

                set_clauses = [f"{k} = ?" for k in colonne_semplici]
                values = list(colonne_semplici.values())
                if author is not _unset:
                    set_clauses.append("author_sort = ?")
                    values.append(self._link_authors(conn, book_id, author or ""))
                set_clauses.append("last_modified = ?")
                values.append(adesso)
                values.append(book_id)
                conn.execute(f"UPDATE books SET {', '.join(set_clauses)} WHERE id = ?", values)

                # Il rinomino di un autore su tutti i suoi libri e' il caso
                # tipico di questa funzione: i file devono seguirlo, o la
                # biblioteca sul disco resta intestata al nome sbagliato.
                if author is not _unset or "title" in colonne_semplici:
                    mossa = self._porta_a_posto(
                        conn, book_id,
                        titolo=colonne_semplici.get("title"),
                        autore=None if author is _unset else (author or ""),
                    )
                    spostamenti.extend(mossa["annulla"])
                    if mossa["mossa"]:
                        traslochi.append(mossa["mossa"])

                if series_name is not _unset:
                    self._set_one_linked(conn, "series", "series", "name", book_id, series_name)
                if series_index is not _unset:
                    # NOT NULL DEFAULT 1.0 nello schema Calibre: svuotare il
                    # campo significa tornare al default, non scrivere NULL.
                    conn.execute(
                        "UPDATE books SET series_index = ? WHERE id = ?",
                        (1.0 if series_index in (None, "") else series_index, book_id),
                    )
                if publisher is not _unset:
                    self._set_one_linked(conn, "publishers", "publisher", "name", book_id, publisher)
                if language is not _unset:
                    self._set_language_linked(conn, book_id, language)
                if rating is not _unset:
                    self._set_rating_linked(conn, book_id, rating)
                if description is not _unset:
                    conn.execute(
                        "INSERT INTO comments (book, text) VALUES (?, ?) "
                        "ON CONFLICT(book) DO UPDATE SET text=excluded.text",
                        (book_id, description or ""),
                    )
                for key in custom_keys:
                    col_id = cols_by_label.get(key[1:])
                    if col_id is not None:
                        self._write_custom_value(conn, col_id, book_id, fields[key])

                for nome in tags_add:
                    conn.execute("INSERT INTO tags (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (nome,))
                    riga = conn.execute("SELECT id FROM tags WHERE name = ?", (nome,)).fetchone()
                    conn.execute(
                        "INSERT INTO books_tags_link (book, tag) VALUES (?, ?) ON CONFLICT(book, tag) DO NOTHING",
                        (book_id, riga["id"]),
                    )
                for nome in tags_remove:
                    conn.execute(
                        "DELETE FROM books_tags_link WHERE book = ? AND tag IN "
                        "(SELECT id FROM tags WHERE name = ?)",
                        (book_id, nome),
                    )
                toccati += 1

            # Una sola volta alla fine, non per libro: sono scansioni di
            # tabella intera, e ripeterle a ogni giro trasformerebbe una
            # modifica su mille libri in mille scansioni.
            if author is not _unset:
                conn.execute("DELETE FROM authors WHERE id NOT IN (SELECT author FROM books_authors_link)")
            for nome in tags_remove:
                # Solo i tag che questa operazione ha staccato, non tutti gli
                # orfani della libreria: ripulire l'intera tabella sarebbe un
                # effetto collaterale fuori dalla selezione su cui l'utente ha
                # detto di agire.
                conn.execute(
                    "DELETE FROM tags WHERE name = ? AND id NOT IN (SELECT tag FROM books_tags_link)",
                    (nome,),
                )
            conn.commit()
            dimentica_lista_libri(self.db_path)
        except Exception:
            _rimetti_a_posto(spostamenti)
            raise
        finally:
            conn.close()
        _pulisci_cartelle_vuote(traslochi, self.path)
        return toccati

    def _porta_a_posto(self, conn, book_id: int, titolo=None, autore=None):
        """
        Porta cartella e file del libro nella forma che userebbe Calibre, e
        registra il nuovo percorso nella transazione aperta. Torna
        (origine, destinazione) se ha spostato la cartella, None altrimenti.

        Fa le stesse due cose che fa `update_path` di Calibre, e nello stesso
        ordine: prima rinomina i file dei formati dentro la cartella
        (`Titolo - Autore.est`), poi sposta la cartella
        (`Primo autore/Titolo (id)`). L'ordine conta: rinominare dopo aver
        spostato vorrebbe dire due operazioni da annullare invece di una, se
        la seconda fallisce.

        `titolo` e `autore` sono quelli NUOVI quando si sta salvando una
        modifica (nella transazione aperta possono non essere ancora
        leggibili in modo affidabile); omessi, si leggono dal database — che
        e' il caso della riparazione retroattiva.

        Non tocca niente in tre casi in cui muoversi farebbe piu' danno che
        bene: il percorso e' gia' giusto (il caso normale); la cartella di
        partenza non esiste (riscrivere `books.path` lo farebbe puntare a un
        posto altrettanto inesistente); la destinazione e' gia' occupata (non
        si sovrascrive mai niente).
        """
        # `annulla` e' l'elenco ordinato di TUTTO quello che si tocca sul
        # disco (rinomini dei file, poi trasloco della cartella): serve a
        # riportare indietro ogni cosa se la transazione non si chiude.
        esito = {"mossa": None, "file_rinominati": 0, "bloccato": None, "annulla": []}
        riga = conn.execute("SELECT path, title FROM books WHERE id = ?", (book_id,)).fetchone()
        if not riga or not riga["path"]:
            return esito
        if titolo is None:
            titolo = riga["title"]
        if autore is None:
            autore = self._autore_di(conn, book_id)

        origine = os.path.join(self.path, riga["path"])
        if not os.path.isdir(origine):
            esito["bloccato"] = "la cartella del libro non esiste sul disco"
            return esito

        formati = [
            r["format"] for r in conn.execute("SELECT format FROM data WHERE book = ?", (book_id,)).fetchall()
        ]
        rinomini = self._rinomina_file_formati(conn, book_id, origine, titolo, autore, formati)
        esito["file_rinominati"] = len(rinomini)
        esito["annulla"].extend(rinomini)

        nuovo = book_paths.percorso_corretto(riga["path"], autore, book_id, titolo)
        if not nuovo:
            return esito
        destinazione = os.path.join(self.path, nuovo)
        if os.path.exists(destinazione):
            # Non si sovrascrive mai niente. Va detto a chi ha chiesto la
            # riparazione, non contato come lavoro fatto: altrimenti il
            # libro risulterebbe sistemato e resterebbe li' per sempre.
            esito["bloccato"] = f"la cartella di destinazione esiste gia': {nuovo}"
            return esito
        os.makedirs(os.path.dirname(destinazione), exist_ok=True)
        shutil.move(origine, destinazione)
        conn.execute("UPDATE books SET path = ? WHERE id = ?", (nuovo, book_id))
        esito["mossa"] = (origine, destinazione)
        esito["annulla"].append((origine, destinazione))
        return esito

    @staticmethod
    def _autore_di(conn, book_id: int) -> str:
        riga = conn.execute(
            "SELECT group_concat(a.name, ' & ') AS autore FROM ("
            "  SELECT a2.name FROM books_authors_link l JOIN authors a2 ON a2.id = l.author "
            "  WHERE l.book = ? ORDER BY l.id) AS a",
            (book_id,),
        ).fetchone()
        return (riga["autore"] if riga else "") or ""

    def _rinomina_file_formati(self, conn, book_id: int, cartella: str, titolo: str, autore: str, formati: list) -> list:
        """
        I file dentro la cartella si chiamano `Titolo - Autore.est`, come in
        Calibre. Kolibre finora ci lasciava il nome del file caricato
        ("9788804xxxxx_ebook.epub"), che e' la seconda differenza che si vede
        aprendo la cartella.

        Il rinomino e' per formato e best-effort: se un file non si riesce a
        rinominare si lascia stare quel formato — `data.name` continua a dire
        il vero, e il libro resta leggibile. Meglio una cartella a meta'
        strada di un libro che non si apre.
        """
        if not formati:
            return []
        fatti = []
        atteso = book_paths.nome_file_canonico(titolo, autore, formati)
        for fmt in formati:
            riga = conn.execute(
                "SELECT name FROM data WHERE book = ? AND format = ?", (book_id, fmt)
            ).fetchone()
            if not riga or riga["name"] == atteso:
                continue
            estensione = fmt.lower()
            vecchio = os.path.join(cartella, f"{riga['name']}.{estensione}")
            nuovo = os.path.join(cartella, f"{atteso}.{estensione}")
            if not os.path.isfile(vecchio) or os.path.exists(nuovo):
                continue
            try:
                os.rename(vecchio, nuovo)
            except OSError:
                continue
            conn.execute(
                "UPDATE data SET name = ? WHERE book = ? AND format = ?", (atteso, book_id, fmt)
            )
            fatti.append((vecchio, nuovo))
        return fatti

    def percorsi_fuori_posto(self) -> list:
        """
        I libri che non stanno dove Calibre li metterebbe — per cartella o
        per nome dei file.

        Sola lettura: guarda e riferisce, non muove niente. Serve sia alla
        pagina di manutenzione (per dire QUANTI e QUALI prima di toccare
        qualcosa) sia alla riparazione stessa, che lavora su questo elenco.
        """
        conn = self._connect()
        try:
            righe = conn.execute(
                "SELECT b.id, b.title, b.path, "
                "  (SELECT group_concat(a.name, ' & ') FROM ("
                "     SELECT a2.name FROM books_authors_link l2 JOIN authors a2 ON a2.id = l2.author "
                "     WHERE l2.book = b.id ORDER BY l2.id) AS a) AS autore "
                "FROM books b WHERE b.path IS NOT NULL AND b.path != ''"
            ).fetchall()
            formati_per_libro = {}
            nomi_per_libro = {}
            for r in conn.execute("SELECT book, format, name FROM data").fetchall():
                formati_per_libro.setdefault(r["book"], []).append(r["format"])
                nomi_per_libro.setdefault(r["book"], set()).add(r["name"])
        finally:
            conn.close()

        fuori = []
        for riga in righe:
            autore = riga["autore"] or ""
            nuovo = book_paths.percorso_corretto(riga["path"], autore, riga["id"], riga["title"])
            formati = formati_per_libro.get(riga["id"], [])
            nome_atteso = book_paths.nome_file_canonico(riga["title"], autore, formati) if formati else ""
            file_da_rinominare = bool(nome_atteso) and nomi_per_libro.get(riga["id"], set()) != {nome_atteso}
            if not nuovo and not file_da_rinominare:
                continue
            origine = os.path.join(self.path, riga["path"])
            fuori.append({
                "id": riga["id"],
                "title": riga["title"],
                "author": autore,
                "path": riga["path"],
                "new_path": nuovo or riga["path"],
                "rename_files": file_da_rinominare,
                "reason": book_paths.motivo(riga["path"], autore, riga["title"]) if nuovo
                          else "nome dei file diverso da quello di Calibre",
                # Un libro la cui cartella non esiste non si puo' sistemare:
                # lo diciamo qui invece di farlo sparire in silenzio dal
                # conteggio, perche' e' un problema diverso (file mancanti)
                # che merita di essere visto.
                "missing": not os.path.isdir(origine),
            })
        return fuori

    def ripara_percorsi(self, book_ids: Optional[list] = None, limite: int = 0) -> dict:
        """
        Porta i libri nella forma che userebbe Calibre: cartella del primo
        autore, titolo traslitterato e troncato, file chiamati
        `Titolo - Autore`.

        Idempotente e riprendibile: rifarla non fa danni, e interromperla a
        meta' lascia sistemati quelli gia' fatti e intatti gli altri — quindi
        basta rilanciarla. Ogni libro e' una transazione a se', cosi' un
        singolo caso storto (permessi, cartella sparita) non annulla il
        lavoro riuscito sugli altri.
        """
        da_fare = [v for v in self.percorsi_fuori_posto() if not v["missing"]]
        if book_ids is not None:
            voluti = set(book_ids)
            da_fare = [v for v in da_fare if v["id"] in voluti]
        # Quanti ce n'erano PRIMA di tagliare al blocco: e' questo il numero
        # che serve a chi chiama per sapere se deve richiamare ancora.
        # Contandoli dopo il taglio, "ne restano" valeva sempre zero appena
        # finito un blocco pieno, e chi stava sistemando duemila libri si
        # fermava ai primi duecento — riscontrato in uso.
        totale = len(da_fare)
        if limite:
            da_fare = da_fare[:limite]

        sistemati, falliti = 0, []
        for voce in da_fare:
            conn = self._connect()
            esito = None
            try:
                esito = self._porta_a_posto(conn, voce["id"])
                if esito["bloccato"]:
                    # I file possono essere gia' stati rinominati prima che
                    # il trasloco risultasse impossibile: quel lavoro e'
                    # riuscito e va confermato, o `data.name` finirebbe a
                    # dire una cosa diversa da quello che c'e' sul disco.
                    if esito["file_rinominati"]:
                        conn.commit()
                    else:
                        conn.rollback()
                    falliti.append({"id": voce["id"], "title": voce["title"], "error": esito["bloccato"]})
                    continue
                conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now_iso(), voce["id"]))
                conn.commit()
                sistemati += 1
            except Exception as exc:
                if esito and esito["annulla"]:
                    _rimetti_a_posto(esito["annulla"])
                falliti.append({"id": voce["id"], "title": voce["title"], "error": str(exc)[:200]})
                continue
            finally:
                conn.close()
            if esito["mossa"]:
                _pulisci_cartelle_vuote([esito["mossa"]], self.path)

        if sistemati:
            dimentica_lista_libri(self.db_path)
        return {"moved": sistemati, "failed": falliti, "remaining": totale - sistemati - len(falliti)}

    # ------------------------------------------------------------------
    # Scritture su relazione riusabili dentro una transazione gia' aperta.
    # I metodi pubblici qui sopra (set_publisher, set_rating, ...) fanno la
    # stessa cosa ma ognuno con connessione e commit propri: questi sono la
    # versione che bulk_update_books puo' chiamare N volte restando dentro
    # un'unica transazione.
    # ------------------------------------------------------------------

    @staticmethod
    def _set_one_linked(conn, tabella: str, colonna_link: str, colonna_valore: str, book_id: int, valore) -> None:
        """Relazione "al piu' uno" per libro (publishers, series): la tabella
        di collegamento ha UNIQUE(book), quindi si cancella e si reinserisce."""
        conn.execute(f"DELETE FROM books_{tabella}_link WHERE book = ?", (book_id,))
        valore = (valore or "").strip()
        if not valore:
            return
        conn.execute(
            f"INSERT INTO {tabella} ({colonna_valore}) VALUES (?) ON CONFLICT({colonna_valore}) DO NOTHING",
            (valore,),
        )
        riga = conn.execute(f"SELECT id FROM {tabella} WHERE {colonna_valore} = ?", (valore,)).fetchone()
        conn.execute(
            f"INSERT INTO books_{tabella}_link (book, {colonna_link}) VALUES (?, ?)",
            (book_id, riga["id"]),
        )

    @staticmethod
    def _set_language_linked(conn, book_id: int, lang_code) -> None:
        conn.execute("DELETE FROM books_languages_link WHERE book = ?", (book_id,))
        lang_code = (lang_code or "").strip()
        if not lang_code:
            return
        conn.execute("INSERT INTO languages (lang_code) VALUES (?) ON CONFLICT(lang_code) DO NOTHING", (lang_code,))
        riga = conn.execute("SELECT id FROM languages WHERE lang_code = ?", (lang_code,)).fetchone()
        conn.execute(
            "INSERT INTO books_languages_link (book, lang_code, item_order) VALUES (?, ?, 0)",
            (book_id, riga["id"]),
        )

    @staticmethod
    def _set_rating_linked(conn, book_id: int, stars) -> None:
        """Stessa conversione di set_rating: 0-5 lato Kolibre, 0-10 in Calibre."""
        conn.execute("DELETE FROM books_ratings_link WHERE book = ?", (book_id,))
        if not stars:
            return
        raw = round(float(stars) * 2)
        conn.execute("INSERT INTO ratings (rating) VALUES (?) ON CONFLICT(rating) DO NOTHING", (raw,))
        riga = conn.execute("SELECT id FROM ratings WHERE rating = ?", (raw,)).fetchone()
        conn.execute("INSERT INTO books_ratings_link (book, rating) VALUES (?, ?)", (book_id, riga["id"]))

    def create_custom_column(self, label: str, name: str, datatype: str, display: Optional[dict] = None) -> int:
        if datatype not in CUSTOM_COLUMN_SQL_TYPE:
            raise ValueError(
                f"Tipo di colonna non supportato: {datatype!r} (validi: {sorted(CUSTOM_COLUMN_SQL_TYPE)})"
            )
        conn = self._connect()
        try:
            if conn.execute("SELECT id FROM custom_columns WHERE label = ?", (label,)).fetchone():
                raise ValueError(f"Colonna personalizzata '{label}' già esistente")
            cur = conn.execute(
                "INSERT INTO custom_columns (label, name, datatype, is_multiple, normalized, display) "
                "VALUES (?, ?, ?, 0, 0, ?)",
                (label, name, datatype, json.dumps(display or {})),
            )
            col_id = cur.lastrowid
            sql_type = CUSTOM_COLUMN_SQL_TYPE[datatype]
            conn.execute(
                f"CREATE TABLE custom_column_{col_id} "
                f"(id INTEGER PRIMARY KEY, book INTEGER NOT NULL, value {sql_type}, UNIQUE(book))"
            )
            conn.commit()
            return col_id
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    def delete_custom_column(self, label: str) -> None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT id FROM custom_columns WHERE label = ?", (label,)).fetchone()
            if not row:
                return
            conn.execute(f"DROP TABLE IF EXISTS custom_column_{row['id']}")
            conn.execute("DELETE FROM custom_columns WHERE id = ?", (row["id"],))
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

    # Le tabelle delle entita' e la colonna che le collega ai libri. Stesse
    # quattro di services/entita.py, ripetute qui perche' questo modulo non
    # deve dipendere dai servizi: e' il contrario che vale.
    _ENTITA_ORFANE = {
        "autori": ("authors", "books_authors_link", "author"),
        "serie": ("series", "books_series_link", "series"),
        "tag": ("tags", "books_tags_link", "tag"),
        "editori": ("publishers", "books_publishers_link", "publisher"),
    }

    def pulisci_entita_orfane(self, tipo: str) -> dict:
        """
        Toglie le voci che non hanno piu' nessun libro.

        Restano indietro da ogni accorpamento: unendo "eleuthera" in
        "elèuthera", i libri passano alla seconda e la prima resta nella
        tabella `publishers` senza piu' collegamenti. Calibre Desktop fa
        questa pulizia per conto suo dopo ogni modifica; Kolibre scrive sulle
        stesse tabelle ma non lo faceva, e quelle righe si accumulavano.

        Si vedeva: la pagina Entita' continuava a proporre di accorpare
        "eleuthera (0 libri)" in "elèuthera (10 libri)", cioe' un'unione gia'
        fatta — riscontrato in uso il 29/09/2026.

        Cancella SOLO righe senza alcun collegamento: una voce a zero libri
        non e' un dato di nessuno, e' il residuo di un'operazione finita.
        """
        if tipo not in self._ENTITA_ORFANE:
            raise ValueError(f"Tipo di entita' sconosciuto: {tipo!r}")
        tabella, legame, chiave = self._ENTITA_ORFANE[tipo]
        conn = self._connect()
        try:
            orfane = [
                (r["id"], r["name"] if "name" in r.keys() else r[1])
                for r in conn.execute(
                    f"SELECT * FROM {tabella} v "
                    f"WHERE NOT EXISTS (SELECT 1 FROM {legame} l WHERE l.{chiave} = v.id)"
                ).fetchall()
            ]
            for id_voce, _nome in orfane:
                conn.execute(f"DELETE FROM {tabella} WHERE id = ?", (id_voce,))
            conn.commit()
        finally:
            conn.close()
        if orfane:
            logging.info("Pulite %d voci senza libri da %s", len(orfane), tabella)
        dimentica_lista_libri(self.db_path)
        return {"tolte": len(orfane), "nomi": [n for _id, n in orfane[:50]]}

    def rinomina_entita(self, tipo: str, da: list, a: str) -> dict:
        """
        Scrive la grafia giusta NELLA tabella dell'entita'.

        Serve perche' riscrivere il valore su ogni libro non basta quando le
        due grafie differiscono solo per le maiuscole. Le colonne `name` di
        authors, series, tags e publishers sono dichiarate `COLLATE NOCASE`
        con `UNIQUE(name)`: per SQLite "Aa. Vv." e "AA. VV." sono lo stesso
        nome. Quindi il percorso normale di scrittura di un libro —
        INSERT ... ON CONFLICT(name) DO NOTHING, poi SELECT id WHERE name = ?
        — ritrova la riga con la grafia VECCHIA, ricollega il libro a quella,
        e il nome non cambia mai. L'unione dichiarava di essere riuscita
        senza aver fatto niente: riscontrato il 30/09/2026, provando ad
        unire "Aa. Vv." in "AA. VV." su una biblioteca reale.

        Non si e' corretto il percorso di scrittura dei libri, e di proposito:
        li' la grafia arriva dai metadati di un file, e "j.r.r. tolkien"
        importato da un epub sciatto non deve riscrivere l'autore di tutta la
        biblioteca. Calibre si comporta allo stesso modo — tiene la grafia che
        ha, e la cambia solo quando glielo si chiede. Questo metodo E'
        quel "glielo si chiede": lo chiama l'unione delle entita', dove la
        grafia di destinazione l'ha scelta una persona.

        Se ESISTONO davvero due righe distinte (grafie che differiscono per
        piu' delle maiuscole, e i libri erano stati riscritti a meta'), i
        libri passano sulla riga di destinazione e la vecchia se ne va.
        """
        if tipo not in self._ENTITA_ORFANE:
            raise ValueError(f"Tipo di entita' sconosciuto: {tipo!r}")
        tabella, legame, chiave = self._ENTITA_ORFANE[tipo]
        a = (a or "").strip()
        if not a:
            return {"rinominate": 0, "unite": 0}
        rinominate = 0
        unite = 0
        conn = self._connect()
        try:
            for vecchio in da or []:
                vecchio = (vecchio or "").strip()
                if not vecchio or vecchio == a:
                    continue
                # `COLLATE BINARY` sovrascrive il NOCASE della colonna: qui
                # serve il confronto ESATTO, altrimenti si ritrova se' stessi.
                riga = conn.execute(
                    f"SELECT id FROM {tabella} WHERE name = ? COLLATE BINARY", (vecchio,)
                ).fetchone()
                if riga is None:
                    continue
                gemella = conn.execute(
                    f"SELECT id FROM {tabella} WHERE name = ? COLLATE BINARY", (a,)
                ).fetchone()
                if gemella is not None and gemella["id"] != riga["id"]:
                    # Due righe vere. I collegamenti si spostano con OR IGNORE
                    # perche' un libro potrebbe averle entrambe e la UNIQUE
                    # sul legame rifiuterebbe il doppione: quello che resta
                    # indietro lo cancella la riga dopo.
                    conn.execute(
                        f"UPDATE OR IGNORE {legame} SET {chiave} = ? WHERE {chiave} = ?",
                        (gemella["id"], riga["id"]),
                    )
                    conn.execute(f"DELETE FROM {legame} WHERE {chiave} = ?", (riga["id"],))
                    conn.execute(f"DELETE FROM {tabella} WHERE id = ?", (riga["id"],))
                    unite += 1
                    continue
                conn.execute(f"UPDATE {tabella} SET name = ? WHERE id = ?", (a, riga["id"]))
                if tipo == "autori":
                    # `series` ha un trigger che ricalcola sort da solo, gli
                    # autori no: il loro sort e' "Cognome, Nome" e va rifatto
                    # a mano, altrimenti resta ordinato per la grafia vecchia.
                    conn.execute(
                        "UPDATE authors SET sort = ? WHERE id = ?",
                        (author_to_author_sort(a), riga["id"]),
                    )
                rinominate += 1
            conn.commit()
        finally:
            conn.close()
        if rinominate or unite:
            logging.info(
                "%s: %d grafie corrette e %d righe unite verso '%s'",
                tabella, rinominate, unite, a,
            )
        dimentica_lista_libri(self.db_path)
        return {"rinominate": rinominate, "unite": unite}

    def delete_book(self, book_id: int) -> None:
        """
        Deletes the DB rows AND the book's own folder (and format files
        inside it) on disk — unlike remove_format (single format, deletes
        its own file as it goes), this used to only ever touch the
        database, leaving every deleted book's directory orphaned on disk
        forever. Also removes the author's own directory if this was their
        last book in this library (reported directly: browsing the library
        folder showed empty author directories left behind after deleting
        all of an author's books).

        E toglie la riga di questo libro dall'indice full-text, che vive in
        `fulltext.db` accanto a metadata.db ed e' a tutti gli effetti un
        terzo pezzo del libro su disco. Finora non la toglieva nessuno:
        `remove_book_index` esisteva gia' e non era chiamata da nessuna
        parte, quindi l'indice conservava il testo integrale di ogni libro
        cancellato — su una biblioteca reale due libri cancellati stanno
        ancora li' dentro, in un file da 1,9 GB. Non si notava perche' /search
        scarta le corrispondenze che non ritrova nel catalogo: il danno era
        silenzioso, cioe' spazio occupato per sempre e un conteggio
        "indicizzati" piu' alto del catalogo stesso.
        """
        conn = self._connect()
        try:
            book_row = conn.execute("SELECT path FROM books WHERE id = ?", (book_id,)).fetchone()
            for col in conn.execute("SELECT id FROM custom_columns").fetchall():
                if self._is_normalized_column(conn, col["id"]):
                    conn.execute(f"DELETE FROM books_custom_column_{col['id']}_link WHERE book = ?", (book_id,))
                else:
                    conn.execute(f"DELETE FROM custom_column_{col['id']} WHERE book = ?", (book_id,))
            conn.execute("DELETE FROM data WHERE book = ?", (book_id,))
            conn.execute("DELETE FROM comments WHERE book = ?", (book_id,))
            conn.execute("DELETE FROM identifiers WHERE book = ?", (book_id,))
            conn.execute("DELETE FROM books_authors_link WHERE book = ?", (book_id,))
            conn.execute("DELETE FROM books_tags_link WHERE book = ?", (book_id,))
            conn.execute("DELETE FROM books_series_link WHERE book = ?", (book_id,))
            conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
            # Same orphan cleanup _link_authors does after a relink — a
            # deleted book's now-bookless authors shouldn't linger at count 0.
            conn.execute("DELETE FROM authors WHERE id NOT IN (SELECT author FROM books_authors_link)")
            conn.commit()
        finally:
            conn.close()
        dimentica_lista_libri(self.db_path)

        # Disk cleanup only after the DB commit succeeds — the database stays
        # the source of truth; a book must never end up still-listed with its
        # files already gone, only the reverse (files lingering briefly) is
        # tolerable and gets caught by the check below on the next delete.
        if book_row and book_row["path"]:
            book_dir = os.path.join(self.path, book_row["path"])
            if os.path.isdir(book_dir):
                shutil.rmtree(book_dir, ignore_errors=True)
            author_dir = os.path.dirname(book_dir)
            if (
                os.path.isdir(author_dir)
                and os.path.normpath(author_dir) != os.path.normpath(self.path)
                and not os.listdir(author_dir)
            ):
                os.rmdir(author_dir)

        # Import locale e non in cima al file: `calibre/` non importa nulla da
        # `services/` — e' la direzione sbagliata della dipendenza, e tenerla
        # qui dentro evita di invertire la stratificazione per una riga sola.
        # Non bloccante di proposito: l'indice e' una comodita' ricostruibile
        # con "Reindicizza", il catalogo no, e un errore qui non deve far
        # fallire una cancellazione gia' avvenuta nel database.
        try:
            from ..services import fulltext_index

            fulltext_index.remove_book_index(self.path, book_id)
        except Exception as exc:  # pragma: no cover - difensivo
            logging.getLogger("kolibre.calibre").warning(
                "Indice full-text non ripulito per il libro %s: %s", book_id, exc
            )


# ----------------------------------------------------------------------
# Write-queue op registrations (see calibre/write_queue.py). payload keys
# match the keyword args of the corresponding CalibreLibrary method.
# ----------------------------------------------------------------------

@register_op("insert_book")
def _op_insert_book(library_path: str, payload: dict) -> int:
    return CalibreLibrary(library_path).insert_book(**payload)


@register_op("add_format")
def _op_add_format(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).add_format(**payload)


@register_op("remove_format")
def _op_remove_format(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).remove_format(**payload)


@register_op("set_identifier")
def _op_set_identifier(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).set_identifier(**payload)


@register_op("set_identifiers")
def _op_set_identifiers(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).set_identifiers(**payload)


@register_op("set_book_tags")
def _op_set_book_tags(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).set_book_tags(**payload)


@register_op("set_book_series")
def _op_set_book_series(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).set_book_series(**payload)


@register_op("set_rating")
def _op_set_rating(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).set_rating(**payload)


@register_op("set_publisher")
def _op_set_publisher(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).set_publisher(**payload)


@register_op("set_language")
def _op_set_language(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).set_language(**payload)


@register_op("set_comments")
def _op_set_comments(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).set_comments(**payload)


@register_op("set_cover")
def _op_set_cover(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).set_cover(**payload)


@register_op("update_book")
def _op_update_book(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).update_book(payload["book_id"], payload["fields"])


@register_op("bulk_update_books")
def _op_bulk_update_books(library_path: str, payload: dict) -> int:
    return CalibreLibrary(library_path).bulk_update_books(**payload)


@register_op("ripara_percorsi")
def _op_ripara_percorsi(library_path: str, payload: dict) -> dict:
    return CalibreLibrary(library_path).ripara_percorsi(
        book_ids=payload.get("book_ids"), limite=payload.get("limite") or 0
    )


@register_op("delete_book")
def _op_delete_book(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).delete_book(payload["book_id"])


@register_op("create_custom_column")
def _op_create_custom_column(library_path: str, payload: dict) -> int:
    return CalibreLibrary(library_path).create_custom_column(**payload)


@register_op("delete_custom_column")
def _op_delete_custom_column(library_path: str, payload: dict) -> None:
    CalibreLibrary(library_path).delete_custom_column(**payload)




@register_op("pulisci_entita_orfane")
def _op_pulisci_entita_orfane(library_path: str, payload: dict) -> dict:
    return CalibreLibrary(library_path).pulisci_entita_orfane(payload["tipo"])


@register_op("rinomina_entita")
def _op_rinomina_entita(library_path: str, payload: dict) -> dict:
    return CalibreLibrary(library_path).rinomina_entita(
        payload["tipo"], payload["da"], payload["a"]
    )
