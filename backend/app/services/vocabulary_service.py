import os
import sqlite3
from datetime import datetime

from sqlalchemy.orm import Session

from .. import models


def process_vocabulary_db(db_path: str, user_id: int, device_id: int, db: Session) -> dict:
    """
    Parses a KOReader vocabulary_builder.sqlite3 file (uploaded wholesale as
    part of the device backup — see devices.py's upload_device_backup, same
    call site as stats_service.process_statistics_db) into VocabularyEntry
    rows.

    Real schema, confirmed against a production device file (KOReader has
    no separate id column on `vocabulary` — `word` itself is the primary
    key):
        CREATE TABLE vocabulary (
            word TEXT NOT NULL UNIQUE, title_id INTEGER,
            create_time INTEGER NOT NULL, review_time INTEGER,
            due_time INTEGER NOT NULL, review_count INTEGER NOT NULL DEFAULT 0,
            prev_context TEXT, next_context TEXT,
            streak_count INTEGER NOT NULL DEFAULT 0, highlight TEXT,
            PRIMARY KEY(word)
        )
        CREATE TABLE title (id INTEGER NOT NULL UNIQUE, name TEXT UNIQUE,
            filter INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(id))

    No watermark, same as process_statistics_db: the whole file is re-read
    on every backup, upserting by (device_id, word) — cheap (this table
    stays small, tens to low hundreds of rows even for a heavy reader) and
    means an edited/re-reviewed word always reflects the device's latest
    state rather than a stale first-seen snapshot.
    """
    summary = {"words_added": 0, "words_updated": 0}
    if not os.path.exists(db_path):
        return summary

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM title")
        titles = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute(
            "SELECT word, title_id, create_time, review_time, due_time, "
            "review_count, prev_context, next_context, streak_count, highlight "
            "FROM vocabulary"
        )
        rows = cursor.fetchall()

        for (word, title_id, create_time, review_time, due_time,
             review_count, prev_context, next_context, streak_count, highlight) in rows:
            book_title = titles.get(title_id)
            existing = db.query(models.VocabularyEntry).filter(
                models.VocabularyEntry.device_id == device_id,
                models.VocabularyEntry.word == word,
            ).first()
            if existing:
                existing.book_title = book_title
                existing.context_before = prev_context
                existing.context_after = next_context
                existing.highlight = highlight
                existing.review_time = datetime.utcfromtimestamp(review_time) if review_time else None
                existing.due_time = datetime.utcfromtimestamp(due_time) if due_time else None
                existing.review_count = review_count or 0
                existing.streak_count = streak_count or 0
                summary["words_updated"] += 1
            else:
                db.add(models.VocabularyEntry(
                    user_id=user_id, device_id=device_id, word=word,
                    book_title=book_title, context_before=prev_context, context_after=next_context,
                    highlight=highlight,
                    create_time=datetime.utcfromtimestamp(create_time),
                    review_time=datetime.utcfromtimestamp(review_time) if review_time else None,
                    due_time=datetime.utcfromtimestamp(due_time) if due_time else None,
                    review_count=review_count or 0, streak_count=streak_count or 0,
                ))
                summary["words_added"] += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        conn.close()
    return summary
