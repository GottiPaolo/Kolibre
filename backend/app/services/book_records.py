"""
Kolibre-side bookkeeping for a book that is about to stop existing at a given
(library, calibre_book_id) — either deleted outright, or moved to another
library by "copia ed elimina l'originale".

Calibre's own metadata.db knows nothing about reading positions, sessions,
highlights, per-device state or hashes: those live only in app.db, keyed by
(library, calibre_book_id). Whoever removes a book from Calibre therefore has
to say what happens to that half, and there is exactly one right answer per
case — which is why this lives here and not inlined at each call site. It used
to be inlined in books.py's delete_book only, and library_transfer.py (the
move) simply didn't do it: the moved book kept its progress, sessions and
highlights pinned to a source id that no longer resolved, every device holding
it was never told to drop its copy, and the endpoint answered 200.
"""

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from .. import models

# Rows keyed by (library, calibre_book_id) that represent work the USER did —
# they follow the book on a move, and are dropped on a real delete.
_READING_MODELS = (
    models.ReadingPosition,
    models.ReadingSession,
    models.StatsHashPairing,
    models.BookHashHistory,
)


def release_book(
    db: Session,
    library: str,
    calibre_book_id: int,
    migrate_to: Optional[Tuple[str, int]] = None,
) -> None:
    """
    Detaches every app.db row from (library, calibre_book_id). Does NOT commit —
    the caller decides when, so this can join an existing transaction.

    migrate_to=(target_library, target_book_id): the book still exists, just
    somewhere else, so reading data is repointed instead of dropped. Safe
    against collisions only because the target id is always freshly inserted
    by the copy that precedes the delete.

    Highlights are the one exception on the delete path: they are authored
    content, and deleting a book shouldn't silently destroy notes the user
    wrote. They're left dangling on purpose (same call as delete_library's
    cascade), and migrated on the move path where a valid new home exists.
    """
    for model in _READING_MODELS:
        q = db.query(model).filter(
            model.library == library, model.calibre_book_id == calibre_book_id
        )
        if migrate_to:
            q.update(
                {"library": migrate_to[0], "calibre_book_id": migrate_to[1]},
                synchronize_session=False,
            )
        else:
            q.delete(synchronize_session=False)

    highlights = db.query(models.Highlight).filter(
        models.Highlight.library == library,
        models.Highlight.calibre_book_id == calibre_book_id,
    )
    if migrate_to:
        highlights.update(
            {"library": migrate_to[0], "calibre_book_id": migrate_to[1]},
            synchronize_session=False,
        )

    # The live hash always goes: it points at a file under the OLD library
    # path. On a move the target book got its own BookHash when its copy was
    # written (library_transfer's upsert_book_hash), so there is nothing to
    # carry over — and leaving this row would make the same hash resolve to
    # two books, one of which is gone.
    db.query(models.BookHash).filter(
        models.BookHash.library == library,
        models.BookHash.calibre_book_id == calibre_book_id,
    ).delete(synchronize_session=False)

    # 'pending_delete' rather than a row deletion, in both cases: it's what
    # makes _build_removes tell every device holding this book to remove its
    # local copy on the next sync (same status the manual "Elimina da
    # dispositivo" action queues). On a move the device re-downloads the
    # book under its new library, which is the correct end state.
    db.query(models.DeviceBook).filter(
        models.DeviceBook.library == library,
        models.DeviceBook.calibre_book_id == calibre_book_id,
    ).update({"status": "pending_delete", "last_error": None}, synchronize_session=False)

    flagged = db.query(models.DeviceFlaggedBook).filter(
        models.DeviceFlaggedBook.candidate_library == library,
        models.DeviceFlaggedBook.candidate_calibre_book_id == calibre_book_id,
    )
    if migrate_to:
        flagged.update(
            {"candidate_library": migrate_to[0], "candidate_calibre_book_id": migrate_to[1]},
            synchronize_session=False,
        )
    else:
        flagged.update({
            "candidate_library": None,
            "candidate_calibre_book_id": None,
            "candidate_title": None,
            "candidate_author": None,
        }, synchronize_session=False)
