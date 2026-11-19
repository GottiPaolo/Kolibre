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

# Le due colonne delle pagine RITIRATE, e di cui qui non resta piu' codice
# dal 20/11/2026 (revisione del 19/11, punto B4): nessuna biblioteca le ha
# piu', verificato sul server prima di togliere la pulizia automatica.
# La STORIA pero' va saputa, perche' spiega la convenzione di `pages`:
#
#   * `#pagine_stimate`, la GEMELLA (12/09 → 07/11/2026): portava lo stesso
#     identico numero di `pages`, creata credendo che Calibre Desktop non
#     riconoscesse `pages` come colonna personalizzata. Interrogando Calibre
#     con la sua API si e' visto il contrario — e che il `#` nell'etichetta
#     era contro la convenzione di Calibre (le etichette vere sono nude:
#     `pages`, `letto`).
#   * `pagine_stimate`, l'ANTENATA (prima versione di Kolibre): stessa stima
#     ma con la formula vecchia, rimasta piena dove una `pages` esisteva
#     gia' quando la migrazione di rinominamento girava.
#
# Entrambe venivano cancellate all'apertura di ogni biblioteca, ma solo dopo
# aver dimostrato che `pages` copriva ogni loro valore (cancellare e'
# irreversibile). Fatto su tutte le biblioteche reali, quel codice e' stato
# tolto: un controllo a ogni apertura per un lavoro ormai finito.

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
    `letto` o `pages`) continua a girare sempre: e' l'altra meta'
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
        raise LibraryMissingError(f"No library in {library_dir}")
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


# I nomi che queste tre colonne avevano prima del 07/11/2026, quando erano
# in italiano dentro un programma che si pubblica in inglese. Il nome
# VISIBILE si cambia senza muovere un dato: e' una riga in custom_columns, e
# nessuno lo cerca per nome. L'etichetta — `pages`, `letto` — invece NON
# si tocca: e' l'identificatore con cui si scrivono le
# ricerche di Calibre (`#letto:true`), quindi cambiarla romperebbe le
# ricerche salvate di chi le ha; e `pages` in piu' e' cercata parola per
# parola da Project Title.
#
# **Perche' solo se e' ancora quello di prima.** Il nome di una colonna e'
# modificabile a mano da Calibre Desktop: chi l'ha rinominata ha fatto una
# scelta, e un automatismo non annulla una scelta. Quindi il rinominamento
# scatta solo quando trova ESATTAMENTE il nome vecchio — in tutti gli altri
# casi non fa niente, compreso il caso normale in cui ha gia' quello nuovo.
# La descrizione che Calibre Desktop mostra sotto la colonna. In un posto
# solo perche' la scrivono in due: chi crea la colonna e chi la rinomina.
_DESCRIZIONE_LETTO = "Ticked by hand when the book has been finished."

_NOMI_DI_PRIMA = {
    "pages": ("Pagine (stimate)",),
    "letto": ("Letto",),
}


def _rinomina_se_e_ancora_quello_di_prima(conn, label, nome_nuovo, display_nuovo=None):
    """
    Porta il nome visibile della colonna a quello nuovo, una volta sola.

    Gira a ogni apertura di biblioteca, come i controlli qui sotto: una
    SELECT su una riga per colonna, della stessa forma di quelle che gia'
    ci sono. L'UPDATE parte al massimo una volta per biblioteca, e mai se
    il nome non e' piu' quello di prima.
    """
    riga = conn.execute(
        "SELECT name FROM custom_columns WHERE label = ?", (label,)
    ).fetchone()
    if riga is None or riga["name"] not in _NOMI_DI_PRIMA.get(label, ()):
        return
    if display_nuovo is None:
        conn.execute("UPDATE custom_columns SET name = ? WHERE label = ?",
                     (nome_nuovo, label))
    else:
        conn.execute("UPDATE custom_columns SET name = ?, display = ? WHERE label = ?",
                     (nome_nuovo, json.dumps(display_nuovo), label))


def _ensure_page_count_column(conn: sqlite3.Connection) -> None:
    _ensure_project_title_pages_column(conn)
    _rinomina_se_e_ancora_quello_di_prima(conn, PAGE_COUNT_COLUMN_LABEL, "Pages (estimated)")


def _ensure_project_title_pages_column(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id FROM custom_columns WHERE label = ?", (PAGE_COUNT_COLUMN_LABEL,)
    ).fetchone()
    if row:
        return row["id"]
    conn.execute(
        "INSERT INTO custom_columns (label, name, datatype, is_multiple, normalized, display) "
        "VALUES (?, 'Pages (estimated)', 'int', 0, 0, '{}')",
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
        _rinomina_se_e_ancora_quello_di_prima(
            conn, READ_FLAG_COLUMN_LABEL, "Read", {"description": _DESCRIZIONE_LETTO})
        return
    conn.execute(
        "INSERT INTO custom_columns (label, name, datatype, is_multiple, normalized, display) "
        "VALUES (?, 'Read', 'bool', 0, 0, ?)",
        (
            READ_FLAG_COLUMN_LABEL,
            json.dumps({"description": _DESCRIZIONE_LETTO}),
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
    update_book()-ready {field_key: value} per la colonna delle pagine.

    Una sola colonna dal 07/11/2026: la gemella `#pagine_stimate` e' stata
    ritirata (la storia sta nel commento in testa a questo file, sotto
    PAGE_COUNT_COLUMN_LABEL). Resta una funzione invece di un
    dizionario scritto a mano in ognuno dei cinque punti che la chiamano,
    perche' il nome del campo lo deve sapere un posto solo.

    Every existing call site already gates on `pages is not None` before
    calling this; not re-checked here to keep this a pure dict builder.
    """
    return {f"#{PAGE_COUNT_COLUMN_LABEL}": pages}


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
