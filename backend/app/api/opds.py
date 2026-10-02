"""Vero feed OPDS (Atom/XML, HTTP Basic Auth) — canale separato dal protocollo
JSON del plugin KOReader (devices.py::browse_catalog/catalog_sections), che
resta invariato. Pensato per client OPDS generici (Moon+ Reader, Marvin, il
browser OPDS nativo di KOReader, ecc.), non per il plugin Kolibre stesso.
Ogni route qui sotto è dietro require_opds_auth, che risponde 404 se il
feed è disattivato (stessa convenzione di device_capabilities: un server
senza la funzione attiva è indistinguibile da uno che non la implementa)."""
import math
import re
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from .. import config, models, database, auth
from ..calibre.library import CalibreLibrary
from ..services import app_settings
from .libraries import library_display_name

router = APIRouter(prefix="/opds", tags=["opds"])

ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("", ATOM_NS)

PAGE_SIZE = 40

_FORMAT_MIME = {
    "EPUB": "application/epub+zip",
    "PDF": "application/pdf",
    "MOBI": "application/x-mobipocket-ebook",
    "AZW": "application/vnd.amazon.ebook",
    "AZW3": "application/vnd.amazon.ebook",
    "FB2": "application/x-fictionbook+xml",
    "CBZ": "application/vnd.comicbook+zip",
    "CBR": "application/vnd.comicbook-rar",
    "TXT": "text/plain",
    "RTF": "application/rtf",
    "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")

basic_auth = HTTPBasic(auto_error=False)


def require_opds_auth(
    credentials: HTTPBasicCredentials = Depends(basic_auth),
    db: Session = Depends(database.get_db),
) -> models.User:
    if not app_settings.is_opds_feed_enabled(db):
        raise HTTPException(status_code=404)

    unauthorized = HTTPException(
        status_code=401,
        detail="Autenticazione richiesta",
        headers={"WWW-Authenticate": 'Basic realm="Kolibre OPDS"'},
    )
    if not credentials:
        raise unauthorized
    user = db.query(models.User).filter(models.User.username == credentials.username).first()
    if not user or not auth.verify_password(credentials.password, user.hashed_password):
        raise unauthorized
    return user


def _format_mime(fmt: str) -> str:
    return _FORMAT_MIME.get(fmt.upper(), "application/octet-stream")


def _atom_datetime(value) -> str:
    if value:
        try:
            dt = datetime.fromisoformat(str(value))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_library_row(db: Session, folder_name: str) -> models.Library:
    row = db.query(models.Library).filter(models.Library.folder_name == folder_name).first()
    if not row:
        raise HTTPException(status_code=404, detail="Libreria non trovata")
    return row


def _list_library_rows(db: Session) -> list:
    return db.query(models.Library).order_by(models.Library.sort_order, models.Library.id).all()


def _sub(parent: ET.Element, tag: str, text: str = None, **attrs) -> ET.Element:
    el = ET.SubElement(parent, f"{{{ATOM_NS}}}{tag}", attrs)
    if text is not None:
        el.text = text
    return el


def _new_feed(feed_id: str, title: str, kind: str, self_href: str) -> ET.Element:
    feed = ET.Element(f"{{{ATOM_NS}}}feed")
    _sub(feed, "id", feed_id)
    _sub(feed, "title", title)
    _sub(feed, "updated", _atom_datetime(None))
    _sub(feed, "link", rel="self", href=self_href,
         type=f"application/atom+xml;profile=opds-catalog;kind={kind}")
    _sub(feed, "link", rel="start", href="/opds",
         type="application/atom+xml;profile=opds-catalog;kind=navigation")
    return feed


def _nav_entry(feed: ET.Element, entry_id: str, title: str, href: str, kind: str) -> None:
    entry = _sub(feed, "entry")
    _sub(entry, "id", entry_id)
    _sub(entry, "title", title)
    _sub(entry, "updated", _atom_datetime(None))
    _sub(entry, "link", rel="subsection", href=href,
         type=f"application/atom+xml;profile=opds-catalog;kind={kind}")


def _book_entry(feed: ET.Element, book: dict, folder_name: str) -> None:
    entry = _sub(feed, "entry")
    entry_id = f"urn:kolibre:{folder_name}:{book['id']}"
    _sub(entry, "id", entry_id)
    _sub(entry, "title", book.get("title") or "Senza titolo")
    _sub(entry, "updated", _atom_datetime(book.get("last_modified") or book.get("timestamp")))
    if book.get("author"):
        author_el = _sub(entry, "author")
        _sub(author_el, "name", book["author"])
    description = book.get("description")
    if description:
        _sub(entry, "summary", _HTML_TAG_RE.sub("", description), type="text")
    for fmt in book.get("formats") or []:
        _sub(
            entry, "link",
            rel="http://opds-spec.org/acquisition",
            href=f"/opds/{folder_name}/books/{book['id']}/download?format={fmt}",
            type=_format_mime(fmt),
        )
    if book.get("has_cover"):
        _sub(
            entry, "link",
            rel="http://opds-spec.org/image/thumbnail",
            href=f"/opds/{folder_name}/books/{book['id']}/cover",
            type="image/jpeg",
        )


def _xml_response(feed: ET.Element) -> Response:
    body = ET.tostring(feed, encoding="utf-8", xml_declaration=True)
    return Response(content=body, media_type="application/atom+xml; charset=utf-8")


def _library_acquisition_entries(feed: ET.Element, folder_name: str) -> None:
    _nav_entry(feed, f"urn:kolibre:{folder_name}:all", "Tutti i libri",
               f"/opds/{folder_name}/all", "acquisition")
    _nav_entry(feed, f"urn:kolibre:{folder_name}:recent", "Aggiunti di recente",
               f"/opds/{folder_name}/recent", "acquisition")


@router.get("")
def opds_root(db: Session = Depends(database.get_db), _user: models.User = Depends(require_opds_auth)):
    libs = _list_library_rows(db)
    if len(libs) == 1:
        folder_name = libs[0].folder_name
        feed = _new_feed("urn:kolibre:root", library_display_name(db, folder_name), "acquisition", "/opds")
        _library_acquisition_entries(feed, folder_name)
        return _xml_response(feed)

    feed = _new_feed("urn:kolibre:root", "Kolibre", "navigation", "/opds")
    for lib in libs:
        _nav_entry(feed, f"urn:kolibre:{lib.folder_name}", library_display_name(db, lib.folder_name),
                   f"/opds/{lib.folder_name}", "navigation")
    return _xml_response(feed)


@router.get("/{folder_name}")
def opds_library(
    folder_name: str,
    db: Session = Depends(database.get_db),
    _user: models.User = Depends(require_opds_auth),
):
    _get_library_row(db, folder_name)
    feed = _new_feed(f"urn:kolibre:{folder_name}", library_display_name(db, folder_name),
                      "navigation", f"/opds/{folder_name}")
    _library_acquisition_entries(feed, folder_name)
    return _xml_response(feed)


def _acquisition_feed(
    db: Session,
    folder_name: str,
    variant: str,
    title: str,
    page: int,
    sort_key,
    reverse: bool,
) -> Response:
    _get_library_row(db, folder_name)
    lib = CalibreLibrary(config.library_path(folder_name))
    books = lib.list_books()
    books.sort(key=sort_key, reverse=reverse)

    total_pages = max(1, math.ceil(len(books) / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    page_books = books[start:start + PAGE_SIZE]

    self_href = f"/opds/{folder_name}/{variant}?page={page}"
    feed = _new_feed(f"urn:kolibre:{folder_name}:{variant}", title, "acquisition", self_href)
    if page > 1:
        _sub(feed, "link", rel="previous", href=f"/opds/{folder_name}/{variant}?page={page - 1}",
             type="application/atom+xml;profile=opds-catalog;kind=acquisition")
    if page < total_pages:
        _sub(feed, "link", rel="next", href=f"/opds/{folder_name}/{variant}?page={page + 1}",
             type="application/atom+xml;profile=opds-catalog;kind=acquisition")
    for book in page_books:
        _book_entry(feed, book, folder_name)
    return _xml_response(feed)


@router.get("/{folder_name}/all")
def opds_all(
    folder_name: str,
    page: int = Query(1, ge=1),
    db: Session = Depends(database.get_db),
    _user: models.User = Depends(require_opds_auth),
):
    return _acquisition_feed(
        db, folder_name, "all", "Tutti i libri", page,
        sort_key=lambda b: ((b.get("author") or ""), (b.get("title") or "")),
        reverse=False,
    )


@router.get("/{folder_name}/recent")
def opds_recent(
    folder_name: str,
    page: int = Query(1, ge=1),
    db: Session = Depends(database.get_db),
    _user: models.User = Depends(require_opds_auth),
):
    return _acquisition_feed(
        db, folder_name, "recent", "Aggiunti di recente", page,
        sort_key=lambda b: (b.get("timestamp") or ""),
        reverse=True,
    )


@router.get("/{folder_name}/books/{book_id}/download")
def opds_download(
    folder_name: str,
    book_id: int,
    format: str = Query(...),
    db: Session = Depends(database.get_db),
    _user: models.User = Depends(require_opds_auth),
):
    _get_library_row(db, folder_name)
    lib = CalibreLibrary(config.library_path(folder_name))
    file_path = lib.get_format_file_path(book_id, format)
    if not file_path:
        raise HTTPException(status_code=404, detail="Formato non trovato")
    return FileResponse(file_path, filename=f"{book_id}.{format.lower()}", media_type=_format_mime(format))


@router.get("/{folder_name}/books/{book_id}/cover")
def opds_cover(
    folder_name: str,
    book_id: int,
    db: Session = Depends(database.get_db),
    _user: models.User = Depends(require_opds_auth),
):
    _get_library_row(db, folder_name)
    lib = CalibreLibrary(config.library_path(folder_name))
    cover_path = lib.get_cover_path(book_id)
    if not cover_path:
        raise HTTPException(status_code=404, detail="Copertina non trovata")
    return FileResponse(cover_path, media_type="image/jpeg")
