import os

from . import metadata_parser

EBOOK_EXTENSIONS = {".epub", ".pdf", ".mobi", ".azw3", ".azw", ".fb2", ".txt"}


def find_unindexed_book_folders(library_path: str, already_indexed_paths: set) -> list:
    """
    Walk a Calibre-style library folder (Author/Title (id)/file.ext, one level
    of author subfolders then one level of book subfolders) and return one
    entry per book folder that is NOT yet referenced by any `books.path` row in
    metadata.db, with all ebook files found inside grouped as that book's
    formats. Used by the "Rescan" tool action (recovering an index for book
    folders that exist on disk but never went through the ingest flow — e.g. a
    library whose metadata.db was lost/reset, or files copied in by hand).
    """
    found = []
    if not os.path.isdir(library_path):
        return found
    for author_dir in sorted(os.listdir(library_path)):
        author_abs = os.path.join(library_path, author_dir)
        if not os.path.isdir(author_abs) or author_dir.startswith('.'):
            continue
        for book_dir in sorted(os.listdir(author_abs)):
            book_abs = os.path.join(author_abs, book_dir)
            if not os.path.isdir(book_abs):
                continue
            rel_dir = os.path.join(author_dir, book_dir)
            if rel_dir in already_indexed_paths:
                continue

            formats = []
            meta = {}
            for fname in sorted(os.listdir(book_abs)):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in EBOOK_EXTENSIONS:
                    continue
                fpath = os.path.join(book_abs, fname)
                if not meta:
                    if ext == '.epub':
                        meta = metadata_parser.parse_epub_metadata(fpath)
                    elif ext == '.pdf':
                        meta = metadata_parser.parse_pdf_metadata(fpath)
                formats.append({
                    "file_name": fname,
                    "format": ext.upper().replace('.', ''),
                    "size_bytes": os.path.getsize(fpath),
                })
            if not formats:
                continue

            found.append({
                "rel_dir": rel_dir,
                "formats": formats,
                "title": meta.get("title") or book_dir.rsplit(" (", 1)[0],
                "author": meta.get("author") or author_dir,
            })
    return found
