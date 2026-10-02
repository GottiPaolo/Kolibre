import html

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import config, database
from .libraries import biblioteca_scrivibile, default_library_param
from ..calibre.library import CalibreLibrary
from ..logging_utils import log_message
from ..services import app_settings, fulltext_index

router = APIRouter(prefix="/api/kolibre/fulltext", tags=["fulltext"])


@router.get("/settings")
def get_fulltext_settings(library: str = Depends(default_library_param), db: Session = Depends(database.get_db)):
    return {"enabled": app_settings.is_fulltext_enabled(db, library)}


@router.put("/settings")
def set_fulltext_settings(payload: dict, library: str = Depends(biblioteca_scrivibile), db: Session = Depends(database.get_db)):
    enabled = bool(payload.get("enabled", True))
    app_settings.set_fulltext_enabled(db, library, enabled)
    return {"enabled": enabled}


@router.get("/status")
def get_fulltext_status(library: str = Depends(default_library_param), db: Session = Depends(database.get_db)):
    lib = CalibreLibrary(config.library_path(library))
    total = len(lib.list_books())
    percorso = config.library_path(library)
    status = fulltext_index.get_status(percorso)
    tetto_gb = app_settings.get_fulltext_limit_gb(db)
    dimensione = fulltext_index.index_size_bytes(percorso)
    return {
        "enabled": app_settings.is_fulltext_enabled(db, library),
        "indexed": status["indexed"],
        "total": total,
        "progress": status["progress"],
        # L'indice contiene il testo di ogni libro e cresce senza un limite
        # naturale (~1,6 MB a libro): quanto pesa e quanto puo' pesare sono
        # due numeri che vanno detti, non scoperti quando il disco e' pieno.
        "size_bytes": dimensione,
        "limit_gb": tetto_gb,
        "limit_reached": bool(tetto_gb) and dimensione >= tetto_gb * 1e9,
    }


@router.post("/reindex")
def reindex_fulltext(
    library: str = Depends(biblioteca_scrivibile),
    force: bool = False,
    db: Session = Depends(database.get_db),
):
    """`force=true` rifà l'indice da zero; di default i libri già indicizzati
    e non più modificati vengono saltati (vedi reindex_library_async)."""
    lib = CalibreLibrary(config.library_path(library))
    tetto = int(app_settings.get_fulltext_limit_gb(db) * 1e9)
    started = fulltext_index.reindex_library_async(
        config.library_path(library), lib, force=force, max_bytes=tetto
    )
    if not started:
        raise HTTPException(status_code=409, detail="Una reindicizzazione è già in corso per questa libreria")
    log_message("info", "fulltext", f"Started full-text reindex for library '{library}' (force={force})")
    return {"status": "started"}


# FTS5's snippet() wraps matches in \x01/\x02 (chosen precisely because real
# book text won't contain raw control characters) — the raw snippet text is
# HTML-escaped first (defense in depth: extraction strips tags but shouldn't
# be trusted to be perfectly clean), THEN the markers become real <b> tags,
# so nothing from the book's own content can inject markup into the result
# the frontend renders with v-html.
def _snippet_to_html(raw: str) -> str:
    escaped = html.escape(raw)
    return escaped.replace("\x01", "<b>").replace("\x02", "</b>")


@router.get("/search")
def search_fulltext(q: str, library: str = Depends(default_library_param), limit: int = 40, db: Session = Depends(database.get_db)):
    if not app_settings.is_fulltext_enabled(db, library):
        raise HTTPException(status_code=400, detail="Ricerca full-text non abilitata per questa libreria")
    q = (q or "").strip()
    if not q:
        return {"results": []}

    lib = CalibreLibrary(config.library_path(library))
    matches = fulltext_index.search(config.library_path(library), q, limit=limit)
    books_by_id = {b["id"]: b for b in lib.list_books()}

    results = []
    for m in matches:
        book = books_by_id.get(m["book_id"])
        if not book:
            continue
        results.append({
            "id": book["id"],
            "title": book["title"],
            "author": book["author"],
            "format": m["format"],
            # Sempre valorizzato: senza copertina sul disco risponde quella
            # costruita da titolo e autore (books.py::_copertina_costruita).
            "cover_url": f"/api/kolibre/books/{book['id']}/cover?library={library}",
            "snippet_html": _snippet_to_html(m["snippet"]),
        })
    return {"results": results}
