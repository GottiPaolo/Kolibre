import json
import os
import sqlite3

from .functions import register_calibre_functions

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

# Label of the always-present, Kolibre-managed "estimated page count" custom
# column (see services/page_counter.py). Distinct from any custom "Pages"
# column a library may already have from real Calibre usage, on purpose.
# Must be exactly "pages" (lowercase) — ProjectTitle's Calibre-page-count
# integration looks up a custom column by this EXACT lookup name, case-
# sensitively, and won't recognize any other label. Si chiamava
# "pagine_stimate" prima che lo si sapesse: la migrazione che rinominava la
# colonna vecchia (e ritirava la sua gemella quando una "pages" esisteva
# gia') e' stata tolta dopo essere girata su tutte le biblioteche — girava
# a ogni costruzione di CalibreLibrary, cioe' a ogni richiesta, per un
# lavoro da fare una volta sola.
PAGE_COUNT_COLUMN_LABEL = "pages"

# Real-Calibre-compliant MIRROR of the column above (2026-09-12):
# stored WITH its leading '#', which is what Calibre Desktop's own "Aggiungi
# colonne personalizzate" dialog requires for a row to be recognized as an
# actual custom column at all — confirmed directly against a real library:
# selecting "pages" (no '#') there and clicking "Modifica" throws "La
# colonna selezionata non è una colonna personalizzata". Renaming
# PAGE_COUNT_COLUMN_LABEL itself to include '#' was ruled out — ProjectTitle
# looks up that exact bare string and won't recognize a '#'-prefixed one —
# so instead this SECOND column mirrors the same value, purely so a human
# opening the same (often zero-copy/externally-shared) library directly in
# Calibre Desktop can see and inspect the estimate. Always written together
# with PAGE_COUNT_COLUMN_LABEL via page_count_fields() below — same value,
# same call, same transaction — so the two can never drift apart. Created
# non-editable (editable=0 in _ensure_calibre_pages_mirror): Kolibre is the
# only writer, and letting Calibre's own metadata editor touch it would
# silently discard that edit on Kolibre's very next recompute (import/
# rescan) with no way for Kolibre to ever notice it happened.
CALIBRE_PAGE_COUNT_COLUMN_LABEL = "#pagine_stimate"

# "Letto": l'unico giudice attendibile di un libro finito e' una persona.
# Vedi _ensure_read_flag_column per il perche' sia binaria e perche' venga
# creata in ogni biblioteca, non solo in quelle nuove.
READ_FLAG_COLUMN_LABEL = "letto"

# Dropped inside a library folder by DELETE /api/kolibre/libraries/{name} —
# see libraries.py's delete_library/_clear_deletion_tombstone and
# models.DeletedLibraryFolder's own docstring. That DB-side tombstone only
# ever stopped sync_library_registry from RE-REGISTERING a deleted folder;
# it did nothing to stop a plain CalibreLibrary(...) call for the same stale
# folder_name (e.g. a cross-library lookup keyed off an old BookHash/
# DeviceBook row) from silently recreating an EMPTY metadata.db at that path
# — bootstrap_library has no DB session to consult that tombstone table, so
# it needs an on-disk marker instead.
DELETED_LIBRARY_MARKER = ".kolibre_deleted"


class LibraryDeletedError(Exception):
    """Raised by bootstrap_library instead of silently recreating a library
    folder the user explicitly deleted (see DELETED_LIBRARY_MARKER)."""


def get_connection(db_path: str) -> sqlite3.Connection:
    """
    Open a sqlite3 connection to a Calibre-compatible metadata.db with the
    PRAGMAs and custom SQL functions Calibre's own schema requires.

    Every access to metadata.db (read or write) must go through this factory —
    opening a bare sqlite3.connect() against the real schema will fail on any
    INSERT/UPDATE that fires books_insert_trg/books_update_trg (they call
    title_sort()/uuid4(), which are not built into SQLite) and on any query
    against the meta/tag_browser_* views (which use sortconcat()/concat()).
    """
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    register_calibre_functions(conn)
    return conn


class LibraryMissingError(Exception):
    """Si e' chiesta una biblioteca che su disco non c'e'.

    Diversa da LibraryDeletedError, che dice "c'era ed e' stata cancellata di
    proposito": questa dice "questo nome non e' mai esistito", ed e' quasi
    sempre un nome sbagliato — un nome VISUALIZZATO usato al posto del nome
    cartella, un riferimento rimasto in una riga vecchia, un refuso in una
    richiesta.
    """


def bootstrap_library(db_path: str, crea: bool = False) -> None:
    """Prepara la biblioteca; la CREA solo se glielo si chiede.

    `crea=False` di preimpostazione, e non e' un dettaglio: prima questa
    funzione creava sempre, e chiunque aprisse `CalibreLibrary(percorso)` su
    un nome inesistente si ritrovava una biblioteca nuova, vuota e silenziosa.
    E' cosi' che su un impianto reale e' nata una biblioteca fantasma:
    cancellata il 22/07, il suo metadata.db risultava ricreato il
    12/09 — bastava una richiesta con il nome visualizzato invece del nome
    cartella, in uno qualsiasi delle decine di punti che aprono una
    biblioteca, e nessuno se ne accorgeva perche' non falliva niente.

    Creare una biblioteca e' un gesto esplicito: lo fanno la creazione e
    l'importazione, che passano `crea=True`. Tutto il resto, se il nome non
    esiste, deve fallire e dirlo.

    La RIPARAZIONE di una biblioteca che esiste (colonne mancanti, come
    `letto` o `pagine_stimate`) continua a girare sempre: e' l'altra meta'
    del lavoro di questa funzione, e non ha niente a che vedere con la
    creazione.
    """
    library_dir = os.path.dirname(db_path)
    if os.path.exists(os.path.join(library_dir, DELETED_LIBRARY_MARKER)):
        raise LibraryDeletedError(
            f"Library folder was explicitly deleted: {library_dir}"
        )
    is_new = not os.path.exists(db_path) or os.path.getsize(db_path) == 0
    if is_new and not crea:
        raise LibraryMissingError(f"Nessuna biblioteca in {library_dir}")
    os.makedirs(library_dir, exist_ok=True)
    conn = get_connection(db_path)
    try:
        if is_new:
            with open(SCHEMA_PATH, "r") as f:
                conn.executescript(f.read())
            # Nessuna colonna dimostrativa: vedi la nota in fondo al file.
        # Unlike the two demo columns above, the page-counter column must exist
        # in EVERY library, including ones whose metadata.db already existed
        # before this feature did (e.g. an imported Calibre library) — so this
        # check runs unconditionally, not just for a freshly created schema.
        _ensure_page_count_column(conn)
        _ensure_read_flag_column(conn)
        conn.commit()
    finally:
        conn.close()


def _ensure_page_count_column(conn: sqlite3.Connection) -> None:
    pages_col_id = _ensure_project_title_pages_column(conn)
    _ensure_calibre_pages_mirror(conn, pages_col_id)


def _ensure_project_title_pages_column(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id FROM custom_columns WHERE label = ?", (PAGE_COUNT_COLUMN_LABEL,)
    ).fetchone()
    if row:
        return row["id"]
    conn.execute(
        "INSERT INTO custom_columns (label, name, datatype, is_multiple, normalized, display) "
        "VALUES (?, 'Pagine (stimate)', 'int', 0, 0, '{}')",
        (PAGE_COUNT_COLUMN_LABEL,),
    )
    col_id = conn.execute(
        "SELECT id FROM custom_columns WHERE label = ?", (PAGE_COUNT_COLUMN_LABEL,)
    ).fetchone()[0]
    conn.execute(
        f"CREATE TABLE custom_column_{col_id} "
        "(id INTEGER PRIMARY KEY, book INTEGER NOT NULL, value INTEGER, UNIQUE(book))"
    )
    return col_id


def _ensure_calibre_pages_mirror(conn: sqlite3.Connection, source_col_id: int) -> None:
    if conn.execute(
        "SELECT 1 FROM custom_columns WHERE label = ?", (CALIBRE_PAGE_COUNT_COLUMN_LABEL,)
    ).fetchone():
        return
    conn.execute(
        "INSERT INTO custom_columns (label, name, datatype, editable, is_multiple, normalized, display) "
        "VALUES (?, 'Pagine (stima Kolibre)', 'int', 0, 0, 0, ?)",
        (
            CALIBRE_PAGE_COUNT_COLUMN_LABEL,
            json.dumps({"description": "Stima calcolata da Kolibre — sola lettura, gestita automaticamente."}),
        ),
    )
    mirror_id = conn.execute(
        "SELECT id FROM custom_columns WHERE label = ?", (CALIBRE_PAGE_COUNT_COLUMN_LABEL,)
    ).fetchone()[0]
    conn.execute(
        f"CREATE TABLE custom_column_{mirror_id} "
        "(id INTEGER PRIMARY KEY, book INTEGER NOT NULL, value INTEGER, UNIQUE(book))"
    )
    # One-time backfill from the already-populated ProjectTitle column, so
    # existing estimates show up immediately in Calibre Desktop instead of
    # waiting for the next rescan/recompute to touch every book again.
    conn.execute(
        f"INSERT INTO custom_column_{mirror_id} (book, value) "
        f"SELECT book, value FROM custom_column_{source_col_id}"
    )


def _ensure_read_flag_column(conn: sqlite3.Connection) -> None:
    """
    "Letto": la colonna con cui Kolibre sa se un libro e' stato finito.

    Perche' esiste, visto che il tempo di lettura c'e' gia': perche' nessuna
    misura automatica sa che un libro l'hai finito su carta, o che l'hai
    abbandonato a pagina 300 e non lo riprenderai. "Completato" non era mai
    stato definito, e il contatore sul cruscotto lo dimostrava — dopo 193
    ore di lettura vera diceva due, perche' si appoggiava a ReadingPosition,
    una tabella che non era stata pensata per fare da giudice.

    Binaria e non a stati multipli (non letto / in lettura / letto) per
    scelta: la domanda vera e' una sola, e ogni stato in piu' e' una
    decisione in piu' da prendere per ogni libro. Chi vuole la sfumatura ha
    gia' il tempo di lettura e la copertura, che la raccontano meglio di
    un'etichetta.

    Come la colonna delle pagine, va creata in OGNI biblioteca e non solo in
    quelle nuove — una biblioteca importata da Calibre esisteva prima di
    questa funzione — quindi il controllo gira ad ogni apertura.

    L'etichetta e' nuda ('letto', non '#letto'): e' la convenzione vera di
    Calibre, la stessa che hanno le colonne gestite a mano in una
    biblioteca reale (stato_lettura, data_fine_lettura, crossreading).
    Nessun valore viene assegnato qui: la spunta resta un gesto umano.
    """
    if conn.execute(
        "SELECT 1 FROM custom_columns WHERE label = ?", (READ_FLAG_COLUMN_LABEL,)
    ).fetchone():
        return
    conn.execute(
        "INSERT INTO custom_columns (label, name, datatype, is_multiple, normalized, display) "
        "VALUES (?, 'Letto', 'bool', 0, 0, ?)",
        (
            READ_FLAG_COLUMN_LABEL,
            json.dumps({"description": "Spuntato a mano quando il libro e' stato finito."}),
        ),
    )
    col_id = conn.execute(
        "SELECT id FROM custom_columns WHERE label = ?", (READ_FLAG_COLUMN_LABEL,)
    ).fetchone()[0]
    conn.execute(
        f"CREATE TABLE custom_column_{col_id} "
        "(id INTEGER PRIMARY KEY, book INTEGER NOT NULL, value BOOL, UNIQUE(book))"
    )


def page_count_fields(pages) -> dict:
    """
    update_book()-ready {field_key: value} for BOTH page-count columns at
    once — PAGE_COUNT_COLUMN_LABEL (ProjectTitle) and
    CALIBRE_PAGE_COUNT_COLUMN_LABEL (real-Calibre-compliant mirror) — so
    every call site stays a single write and the two can never drift apart.
    Every existing call site already gates on `pages is not None` before
    calling this; not re-checked here to keep this a pure dict builder.
    """
    return {
        f"#{PAGE_COUNT_COLUMN_LABEL}": pages,
        f"#{CALIBRE_PAGE_COUNT_COLUMN_LABEL}": pages,
    }


# Le due colonne dimostrative (rating, read_status) che ogni biblioteca
# nuova si portava dietro dalla Fase 1 non vengono piu' create. Non erano
# una funzione, erano un esempio rimasto acceso:
#
# - `rating` duplicava la valutazione VERA di Calibre (books_ratings_link),
#   e compariva due volte nel Navigatore, una come colonna nativa e una come
#   colonna personalizzata, senza che niente distinguesse le due;
# - `read_status` prometteva uno stato di lettura che nessuno scriveva mai.
#   Ora quel mestiere ce l'ha `letto` (vedi _ensure_read_flag_column), che e'
#   binaria, sta in ogni biblioteca e viene davvero usata.
#
# Misurato su biblioteche reali prima di toglierle: presenti in due
# biblioteche su quattro, valorizzate su ZERO libri in entrambe. Nessun dato
# a rischio, ed e' esattamente il motivo per cui si tolgono solo dalle
# biblioteche NUOVE: quelle esistenti si lasciano come sono, perche' una
# colonna vuota che non da' fastidio vale meno del rischio di cancellare
# quella di qualcuno che invece l'aveva riempita.
