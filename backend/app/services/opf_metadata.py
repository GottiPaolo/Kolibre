"""
Embeds a Calibre custom-column value into an EPUB's own OPF metadata, as
<meta name="calibre:user_metadata:#label" content="...json...">  — the
format real Calibre writes when it saves a book to disk, reverse-engineered
from the real Calibre source:
serialize_user_metadata (ebooks/metadata/opf2.py) for the meta tag itself,
and add_custom_field (library/field_metadata.py) for the field-metadata
dict shape. Kolibre isn't real Calibre and never runs its save-to-disk
pipeline, so this never happened before — ProjectTitle (a KOReader plugin)
reads exactly this embedded metadata, not Kolibre's own metadata.db, so
without this a "pages" custom column is invisible to it no matter how
correct Kolibre's own database is.

Unlike toc_editor.py's NCX rewriting (a genuine structural rebuild, where
round-tripping the whole subtree through ElementTree is unavoidable), this
only ever needs to insert/replace ONE self-contained <meta> element inside
<metadata> — done as a surgical text edit on the OPF's raw bytes instead of
parsing/reserializing the whole document, so every other namespace prefix,
attribute, and whitespace convention already in the file survives
untouched (a full ElementTree round-trip risks silently renaming prefixes
like dc: to ns0: on every unrelated element in the file).
"""

import json
import os
import re
import zipfile
from typing import Optional

from .toc_editor import _find_opf_path
from ..calibre.connection import PAGE_COUNT_COLUMN_LABEL
from ..logging_utils import log_message

_STALE_META_RE_TEMPLATE = r'<meta\b[^>]*name=["\']{label}["\'][^>]*/?>(?:\s*</meta>)?'


def _xml_escape_attr(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _build_field_metadata(col_id: int, label: str, name: str, datatype: str, display: Optional[dict], value) -> dict:
    """
    Same shape Calibre's own custom-column definitions use
    (library/field_metadata.py::add_custom_field), with #value#/#extra#
    merged in (opf2.py::serialize_user_metadata's own get_all_user_metadata
    source) — the exact two pieces real Calibre reads back out of a file.
    """
    return {
        "table": f"custom_column_{col_id}",
        "column": "value",
        "datatype": datatype,
        "is_multiple": {},
        "kind": "field",
        "name": name,
        "search_terms": [f"#{label}"],
        "label": label,
        "colnum": col_id,
        "display": display or {},
        "is_custom": True,
        "is_category": False,
        "link_column": "value",
        "category_sort": "value",
        "is_csp": False,
        "is_editable": True,
        "#value#": value,
        "#extra#": None,
    }


def embed_custom_column(
    epub_path: str, col_id: int, label: str, name: str, datatype: str, display: Optional[dict], value,
) -> bool:
    """
    Best-effort: returns False (never raises) on anything from a missing
    file to a malformed/unexpected OPF — callers treat this purely as a
    nice-to-have alongside the metadata.db write, never load-bearing for it.
    Idempotent: replaces a stale meta tag for the same column if one already
    exists (safe to call again on every recompute).
    """
    if not os.path.exists(epub_path) or value is None:
        return False
    try:
        with zipfile.ZipFile(epub_path, "r") as zin:
            opf_path = _find_opf_path(zin)
            opf_text = zin.read(opf_path).decode("utf-8")

        meta_name = f"calibre:user_metadata:#{label}"
        fm = _build_field_metadata(col_id, label, name, datatype, display, value)
        content = json.dumps(fm, ensure_ascii=False)
        new_meta_tag = f'<meta name="{meta_name}" content="{_xml_escape_attr(content)}"/>'

        stale_re = re.compile(_STALE_META_RE_TEMPLATE.format(label=re.escape(meta_name)))
        opf_text = stale_re.sub("", opf_text)

        if "</metadata>" not in opf_text:
            return False
        opf_text = opf_text.replace("</metadata>", new_meta_tag + "</metadata>", 1)
        new_opf_bytes = opf_text.encode("utf-8")

        temp_epub = epub_path + ".temp"
        with zipfile.ZipFile(epub_path, "r") as zin:
            with zipfile.ZipFile(temp_epub, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = new_opf_bytes if item.filename == opf_path else zin.read(item.filename)
                    zout.writestr(item, data)
        os.replace(temp_epub, epub_path)
        return True
    except Exception:
        return False


def embed_page_count(library_path: str, epub_path: str, fmt: str, pages: int,
                     *, book_id: Optional[int] = None) -> bool:
    """
    One-line wrapper for count_pages' two call sites (ingest.py, and
    libraries.py's recompute-pages maintenance loop): looks up the "pages"
    custom column's real definition (id/name/display — always present,
    _ensure_page_count_column bootstraps it for every library) and embeds
    it. Only EPUB has an OPF to embed into — pdf/mobi/azw3/txt are silently
    skipped here (not an error: count_pages' own database write already
    happened regardless, this is strictly additive).

    **`book_id`: a che serve, e perche' sta qui dentro.** Incorporare il
    conteggio ricostruisce lo zip e lo rimette al suo posto con
    `os.replace`: il file sul disco diventa un altro file, con un'altra
    lunghezza, mentre `data.uncompressed_size` nel database di Calibre ha
    ancora quella di prima. Da quel momento il peso che Kolibre dichiara —
    nell'elenco dei libri e nel totale di una biblioteca — e' quello di un
    file che non esiste piu', e **non torna giusto da solo**. Dandoci il
    `book_id` quella riga si ridichiara qui, nello stesso posto in cui il
    file viene riscritto: e' la stessa ragione per cui l'impronta si calcola
    dentro `chiudi_i_formati` e non nei chiamanti — una regola scritta in
    tre posti prima o poi si perde in uno (vedi
    `prove/impronta_dopo_la_scrittura.py`, che racconta la volta in cui e'
    successo).

    Senza `book_id` il peso non si aggiorna, e si dice nel registro: il
    parametro e' facoltativo perche' un chiamante nuovo non deve rompersi,
    non perche' sia opzionale nel senso di «indifferente».

    **Una scrittura diretta, e perche' qui si puo'.** Tutte le altre
    scritture su `metadata.db` passano dalla coda (`calibre/write_queue.py`),
    che le serializza per non incontrare mai SQLITE_BUSY. Questa no, perche'
    questa funzione e' sincrona e la coda e' asincrona, e farla passare da
    la' vorrebbe dire spostare la regola nei chiamanti, cioe' il difetto che
    sta chiudendo. L'eccezione e' contenuta: e' un UPDATE su una riga, subito
    dopo una riscrittura di file che e' durata ordini di grandezza di piu', e
    le connessioni di Calibre hanno `busy_timeout=30000` (connection.py),
    quindi al massimo aspetta il suo turno invece di fallire.
    """
    if (fmt or "").upper() != "EPUB":
        return False
    from ..calibre.library import CalibreLibrary  # local import: avoids a hard dependency cycle at module load time
    lib = CalibreLibrary(library_path)
    cols = lib.list_custom_columns()
    col = next((c for c in cols if c["label"] == PAGE_COUNT_COLUMN_LABEL), None)
    if not col:
        return False
    scritto = embed_custom_column(
        epub_path, col["id"], col["label"], col["name"], col["datatype"], col["display"], pages)
    if scritto:
        _ridichiara_il_peso(lib, library_path, epub_path, fmt, book_id)
    return scritto


def _ridichiara_il_peso(lib, library_path: str, epub_path: str, fmt: str,
                        book_id: Optional[int]) -> None:
    """
    Il peso del file appena riscritto, nel database di Calibre.

    Best-effort per scelta: il conteggio pagine **e' stato incorporato**, e
    un numero di byte che non si riesce a scrivere non deve annullare quel
    risultato ne' fermare l'ingresso di un libro. Ma non in silenzio — un
    peso sbagliato che nessuno segnala e' il difetto da cui nasce questa
    funzione.
    """
    if book_id is None:
        log_message("warning", "metadata",
                    f"Page count embedded in '{epub_path}' but the declared file size was not "
                    "refreshed: the caller passed no book_id")
        return
    try:
        peso = os.path.getsize(epub_path)
    except OSError as e:
        log_message("warning", "metadata",
                    f"Page count embedded in '{epub_path}' but its size could not be read: {e}")
        return
    try:
        if not lib.update_format_size(book_id, fmt, peso):
            log_message("warning", "metadata",
                        f"Page count embedded in '{epub_path}' but book {book_id} has no "
                        f"{fmt.upper()} row in the library's data table, so no size was refreshed")
    except Exception as e:
        log_message("warning", "metadata",
                    f"Page count embedded in '{epub_path}' but refreshing the declared file "
                    f"size failed: {e}")
