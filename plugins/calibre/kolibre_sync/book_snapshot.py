#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Turns one local Calibre book (given its db.new_api and book_id) into the
plain dict shape UploadWorker/client.upload_book expect. Factored out of
main_dialog.py's upload_current_library so the single-book "send to
library" context-menu action (send_to_library.py) can build the exact same
payload for one book without duplicating ~30 lines of Metadata-object
plumbing, or importing a dialog-hosting module just to reach it.
"""

from calibre.utils.date import is_date_undefined

# Columns Kolibre itself creates/computes and owns the value of (never a real
# user-authored column) — "Kolibre è la fonte di verità": pushing a LOCAL
# Calibre edit of one of these back to the server would let a stale value
# clobber what Kolibre just computed. Excluded here (the ONLY path that
# builds an upload/update payload from a local book) so every caller —
# bulk upload, single-book send, incremental "Rileva variazioni" — is
# covered without repeating the filter at each call site. The opposite
# direction (Kolibre -> Calibre, writing the server's value into a local
# column) is untouched elsewhere, since exporting the authoritative value
# down is exactly the point. Extend this set as more system-managed columns
# appear (e.g. future per-device boolean columns).
SYSTEM_MANAGED_CUSTOM_COLUMN_LABELS = {'pages'}


def serialize_custom_value(datatype, value):
    if value is None:
        return None
    if datatype == 'datetime' and hasattr(value, 'isoformat'):
        return value.isoformat()
    if datatype in ('int',):
        return int(value)
    if datatype == 'rating':
        # Calibre stores ratings — native AND custom columns of this type
        # alike — on a 0-10 scale (2 units per star; schema.sql's `ratings`
        # table has CHECK(rating > -1 AND rating < 11)), never pre-divided
        # by Calibre's own API. Kolibre's own rating UI (native column and
        # every custom rating-type column) is a plain 0-5 star count, so a
        # value read straight off a real Calibre column needs this /2 to
        # land on the right star count instead of showing double.
        return float(value) / 2
    if datatype == 'float':
        return float(value)
    if datatype == 'bool':
        return bool(value)
    return str(value)


# Calibre's own viewer always prefixes start_cfi/end_cfi with these exact two
# extra steps ("/2/4") before its real chapter-local path — verified against
# 71 real annotations across 5 different books (all identical prefix) by
# resolving both forms with the real epubjs CFI engine against the actual
# downloaded EPUBs: with the prefix kept, EpubCFI.toRange() either can't find
# a start container at all or lands on the wrong paragraph; stripped, it
# resolves to exactly the stored highlighted text every time. Likely an
# artifact of Calibre's internal viewer wrapping the loaded chapter in its
# own extra element (a fixed, constant offset, not something scaling with
# document depth), which our own /6/{offset}! spine indirection already
# supersedes — the real "reach body" step is re-added explicitly below.
_CALIBRE_VIEWER_CFI_PREFIX = '/2/4'


def _strip_calibre_viewer_prefix(chapter_cfi: str) -> str:
    if chapter_cfi.startswith(_CALIBRE_VIEWER_CFI_PREFIX):
        return chapter_cfi[len(_CALIBRE_VIEWER_CFI_PREFIX):]
    return chapter_cfi


def calibre_annotations_for_book(db, book_id: int):
    """
    Highlights made in Calibre Desktop's OWN built-in e-book viewer (never
    Kolibre's web reader or KOReader) live in Calibre's native `annotations`
    table, read via db.new_api.all_annotations_for_book() — nothing in this
    plugin looked at it before. The stored start_cfi/end_cfi are relative to
    the current spine document only, not a complete/standalone CFI, and (see
    _strip_calibre_viewer_prefix) carry Calibre's own constant viewer prefix
    that must be dropped, not kept.

    The full, real epub.js-compatible CFI needs the package-document "spine"
    step (a fixed /6, per the actual EPUB CFI spec — see epubjs' own
    epubcfi.js: `cfi.spinePos = cfi.base.steps[1].index`, i.e. the base
    component MUST have two steps, /6 then the spine item) followed by a
    `!` indirection separator, the real "reach body" step (/4, since body is
    always html's second child), and finally Calibre's own chapter-local
    path with its viewer prefix stripped. An earlier version of this
    function omitted the /6/ step and the `!` entirely — verified directly
    against the real epubjs library (frontend/node_modules/epubjs) that the
    old form made EpubCFI.parse() throw, so every Calibre-imported highlight
    was silently unopenable. A later fix added those back but kept Calibre's
    raw start_cfi/end_cfi verbatim, still resolving to the wrong node (or no
    node at all) because of the unstripped prefix. uuid is used as annot_id
    so the server can dedup instead of creating a new highlight every sync.
    """
    annotations = []
    try:
        entries = db.new_api.all_annotations_for_book(book_id)
    except Exception:
        return annotations
    for entry in entries:
        annot = entry.get('annotation') or {}
        if annot.get('type') != 'highlight':
            continue
        spine_index = annot.get('spine_index')
        start_cfi = annot.get('start_cfi')
        if spine_index is None or not start_cfi:
            continue
        end_cfi = annot.get('end_cfi') or start_cfi
        offset = 2 * (spine_index + 1)
        annotations.append({
            'annot_id': annot.get('uuid'),
            'text': annot.get('highlighted_text') or '',
            'comment': annot.get('notes') or None,
            'cfi_start': f'epubcfi(/6/{offset}!/4{_strip_calibre_viewer_prefix(start_cfi)})',
            'cfi_end': f'epubcfi(/6/{offset}!/4{_strip_calibre_viewer_prefix(end_cfi)})',
            # Calibre's own highlight-creation timestamp (ISO8601 + "Z",
            # confirmed against a real entry via calibre-debug) — never
            # forwarded before this, so the server had no way to know when
            # a highlight was actually made here, only when it happened to
            # sync (same class of bug as KOReader's own a.datetime, see
            # main.lua and library_transfer.py's own comments on it).
            'timestamp': annot.get('timestamp'),
        })
    return annotations


def snapshot_book_for_upload(db, book_id: int, selected_columns=None, pages_column: str = None):
    """
    Returns the upload-ready dict for one book, or None if it has no format
    on disk (Kolibre requires at least one, see the "libri senza file"
    checkbox in dialogs.py::UploadOptionsDialog for why that's a real
    limitation, not an oversight here).
    """
    mi = db.get_metadata(book_id)
    format_paths = {}
    for fmt in db.formats(book_id) or []:
        path = db.format_abspath(book_id, fmt)
        if path:
            format_paths[fmt] = path
    if not format_paths:
        return None

    custom_values = {}
    for col in selected_columns or []:
        if col['label'] in SYSTEM_MANAGED_CUSTOM_COLUMN_LABELS:
            continue
        value = mi.get(f"#{col['label']}", None)
        if value not in (None, '', []):
            custom_values[f"#{col['label']}"] = serialize_custom_value(col['datatype'], value)

    pages_estimate = None
    if pages_column:
        raw_pages = mi.get(f"#{pages_column}", None)
        if isinstance(raw_pages, int) and raw_pages > 0:
            pages_estimate = raw_pages

    return {
        'local_book_id': book_id,
        'title': mi.title or 'Senza titolo',
        'author': ' & '.join(mi.authors) if mi.authors else 'Autore Sconosciuto',
        'series_index': mi.series_index if mi.series else None,
        'identifiers': dict(mi.identifiers) if mi.identifiers else {},
        'publisher': mi.publisher or None,
        'tags': list(mi.tags) if mi.tags else [],
        'series': mi.series or None,
        'comments': mi.comments or None,
        # Calibre's own "Lingua" field — was never read/sent at all (found
        # investigating a real report that a push from Calibre didn't seem
        # to preserve every metadata field). mi.languages is a list (Calibre
        # schema supports multiple), but the server's set_language only
        # writes a single value (see backend/app/calibre/library.py's own
        # docstring: the editor UI exposes one select for now) — same
        # single-language assumption already baked into the server side,
        # just never fed from this end.
        'language': mi.languages[0] if mi.languages else None,
        'custom_values': custom_values,
        'pages_estimate': pages_estimate,
        'format_paths': format_paths,
        'cover_path': db.cover(book_id, as_path=True),
        'last_modified': mi.last_modified,
        # Calibre's real "Aggiunto"/date-added field — was never sent at
        # all, so a pushed book's Kolibre-side `timestamp` always fell back
        # to the schema default (the moment of THIS insert), showing the
        # migration date instead of when it was actually added in Calibre.
        'timestamp': mi.timestamp.isoformat() if mi.timestamp else None,
        # Calibre's native "Valutazione"/rating field — never a custom
        # column, so it's read straight off `mi` here rather than through
        # the selected_columns loop above. Same 0-10-to-0-5 scale as
        # serialize_custom_value's 'rating' branch (mi.rating is 0-10, same
        # as the DB column — Calibre's own display code divides by 2 too).
        'rating': (mi.rating / 2) if mi.rating else None,
        # Calibre's real "Data di pubblicazione" — distinct from `timestamp`
        # ("Aggiunto") and never read/sent before. Guarded with
        # is_date_undefined: an unset pubdate isn't None, it's Calibre's own
        # sentinel UNDEFINED_DATE (year 101) — sending that verbatim would
        # populate every book without a real pubdate with a fake one.
        'pubdate': mi.pubdate.isoformat() if mi.pubdate and not is_date_undefined(mi.pubdate) else None,
        # Highlights made in Calibre Desktop's own viewer — see
        # calibre_annotations_for_book's docstring for why these need
        # reconstruction and how dedup works server-side.
        'calibre_annotations': calibre_annotations_for_book(db, book_id),
    }
