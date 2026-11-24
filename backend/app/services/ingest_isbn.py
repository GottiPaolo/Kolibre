"""
Le voci da ISBN si completano in sottofondo (24/11/2026).

**Il difetto** (Paolo: «messo in attesa un libro con ISBN da ingest: la
pagina non deve rimanere bloccata, deve procedere in background»).
`POST /ingest/isbn` faceva tutto dentro la richiesta: chiedeva i metadati a
Open Library e al feed di Google per ogni ISBN e scaricava le copertine una
alla volta, e solo dopo rispondeva. Il dialogo restava su «lavorando» per
tutto quel tempo.

**Adesso** la rotta crea subito le voci (titolo = ISBN) e risponde; qui un
thread chiede le fonti e completa le voci una per una. Finche' una voce e'
in `in_ricerca()` l'elenco dell'ingest la mostra «sto cercando» e si
rinfresca da solo.

**In memoria, di proposito.** L'insieme delle voci in ricerca vive nel
processo: se il server si riavvia a meta', le voci restano col titolo
uguale all'ISBN — la stessa voce vuota che nasce quando nessuna fonte
conosce l'ISBN, che si completa a mano. Una colonna nel database per un
lavoro di qualche secondo sarebbe una migrazione per niente.
"""

import os
import threading

from .. import config, database, models
from ..logging_utils import log_message
from . import metadata_scraper

_in_ricerca: set = set()
_lucchetto = threading.Lock()
_ultimo_thread = None


def in_ricerca(item_id: int) -> bool:
    with _lucchetto:
        return item_id in _in_ricerca


def avvia(voci: dict) -> None:
    """`voci` = {isbn: id della voce}. Parte un thread e torna subito."""
    global _ultimo_thread
    if not voci:
        return
    with _lucchetto:
        _in_ricerca.update(voci.values())
    _ultimo_thread = threading.Thread(target=_completa, args=(dict(voci),), daemon=True)
    _ultimo_thread.start()


def aspetta(timeout: float = 30.0) -> None:
    """Per le prove: aspetta che l'ultimo giro finisca."""
    if _ultimo_thread is not None:
        _ultimo_thread.join(timeout)


def _completa(voci: dict) -> None:
    db = database.SessionLocal()
    try:
        try:
            trovati = metadata_scraper.fetch_metadata_by_isbn(list(voci))
        except Exception as e:
            log_message("warning", "ingest", f"ISBN lookup failed in the background: {e}")
            trovati = {}
        for isbn, item_id in voci.items():
            try:
                _completa_una(db, item_id, isbn, trovati.get(isbn))
            except Exception as e:
                db.rollback()
                log_message("warning", "ingest", f"Completing the entry for ISBN {isbn} failed: {e}")
            finally:
                with _lucchetto:
                    _in_ricerca.discard(item_id)
    finally:
        with _lucchetto:
            for item_id in voci.values():
                _in_ricerca.discard(item_id)
        db.close()


def _completa_una(db, item_id: int, isbn: str, meta) -> None:
    item = db.query(models.IngestedBook).filter(models.IngestedBook.id == item_id).first()
    # Scartata nel frattempo, o gia' importata: non si tocca.
    if item is None or item.status != "pending":
        return
    if meta:
        # Solo i campi che la persona non ha gia' cambiato: il titolo vale
        # come «non toccato» finche' e' ancora l'ISBN.
        if item.title == isbn and meta.get("title"):
            item.title = meta["title"]
            item.filename = meta["title"]
        if not item.author and meta.get("author"):
            item.author = meta["author"]
        if not item.description and meta.get("description"):
            item.description = meta["description"]
        if not item.pubdate and meta.get("pubdate"):
            item.pubdate = meta["pubdate"]
        if not item.cover_path and meta.get("cover_url"):
            immagine = metadata_scraper.download_cover(meta["cover_url"])
            if immagine:
                os.makedirs(config.INGEST_COVERS_DIR, exist_ok=True)
                cover_path = os.path.join(config.INGEST_COVERS_DIR, f"{item.id}.jpg")
                try:
                    with open(cover_path, "wb") as f:
                        f.write(immagine)
                    item.cover_path = cover_path
                except OSError as e:
                    log_message("warning", "ingest", f"Saving the cover failed for ISBN {isbn}: {e}")
    db.commit()
    log_message("info", "ingest",
                f"Entry from ISBN {isbn} completed: "
                + ("metadata from the sources" if meta else "no source knows it, to be filled in by hand"))
