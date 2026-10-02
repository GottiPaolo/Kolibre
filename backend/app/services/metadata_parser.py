import os
import re
import zipfile
import xml.etree.ElementTree as ET
from ..logging_utils import log_message


def parse_epub_metadata(epub_path: str) -> dict:
    metadata = {
        "title": os.path.splitext(os.path.basename(epub_path))[0],
        "author": "Autore Sconosciuto",
        "description": "",
        "tags": [],
        "series": None,
        "series_index": None,
        "language": None,
        "isbn": None,
        "cover_bytes": None,
        "cover_ext": None,
    }
    if not os.path.exists(epub_path):
        return metadata
    try:
        with zipfile.ZipFile(epub_path, 'r') as z:
            try:
                container_data = z.read("META-INF/container.xml")
                root = ET.fromstring(container_data)
                ns = {'ns': 'urn:oasis:names:tc:opendocument:xmlns:container'}
                rootfile = root.find('.//ns:rootfile', ns)
                opf_path = rootfile.attrib.get('full-path') if rootfile is not None else None
            except Exception:
                opf_path = None

            if not opf_path:
                opf_path = next((name for name in z.namelist() if name.endswith('.opf')), None)

            if opf_path:
                opf_data = z.read(opf_path)
                opf_root = ET.fromstring(opf_data)
                ns_opf = {
                    'opf': 'http://www.idpf.org/2007/opf',
                    'dc': 'http://purl.org/dc/elements/1.1/'
                }

                title_el = opf_root.find('.//dc:title', ns_opf)
                if title_el is not None and title_el.text:
                    metadata["title"] = title_el.text.strip()

                creator_el = opf_root.find('.//dc:creator', ns_opf)
                if creator_el is not None and creator_el.text:
                    metadata["author"] = creator_el.text.strip()

                desc_el = opf_root.find('.//dc:description', ns_opf)
                if desc_el is not None and desc_el.text:
                    metadata["description"] = desc_el.text.strip()

                subject_els = opf_root.findall('.//dc:subject', ns_opf)
                metadata["tags"] = [s.text.strip() for s in subject_els if s.text]

                lang_el = opf_root.find('.//dc:language', ns_opf)
                if lang_el is not None and lang_el.text:
                    metadata["language"] = lang_el.text.strip()

                # calibre:series/calibre:series_index — the de facto convention
                # any calibre-exported EPUB uses (no dedicated dc:* equivalent
                # exists), so this only fires for books that passed through
                # calibre at some point, same as everywhere else in Kolibre
                # that reads/writes series.
                for meta_el in opf_root.findall('.//opf:meta', ns_opf):
                    name = meta_el.attrib.get('name')
                    if name == 'calibre:series' and meta_el.attrib.get('content'):
                        metadata["series"] = meta_el.attrib['content'].strip()
                    elif name == 'calibre:series_index' and meta_el.attrib.get('content'):
                        try:
                            metadata["series_index"] = float(meta_el.attrib['content'])
                        except ValueError:
                            pass

                # dc:identifier — prefer one explicitly tagged as ISBN (the
                # opf:scheme attribute), otherwise fall back to any identifier
                # whose text is a plausible bare ISBN-10/13 (digits/X, 10 or 13
                # long after stripping hyphens/spaces) rather than an internal
                # UUID/URN Calibre also stores there.
                isbn_candidate = None
                for id_el in opf_root.findall('.//dc:identifier', ns_opf):
                    if not id_el.text:
                        continue
                    text = id_el.text.strip()
                    scheme = (
                        id_el.attrib.get('{http://www.idpf.org/2007/opf}scheme')
                        or id_el.attrib.get('scheme')
                        or ''
                    )
                    stripped = re.sub(r'[\s-]', '', text)
                    if 'isbn' in scheme.lower():
                        isbn_candidate = stripped
                        break
                    if isbn_candidate is None and re.fullmatch(r'\d{9}[\dXx]|\d{13}', stripped):
                        isbn_candidate = stripped
                if isbn_candidate:
                    metadata["isbn"] = isbn_candidate

                # Cover image: EPUB3 marks it with manifest item
                # properties="cover-image"; EPUB2 instead points to it via
                # <meta name="cover" content="<manifest-item-id>"/>. Try both,
                # EPUB3 first since it's unambiguous (no id indirection needed).
                cover_href = None
                manifest_items = {}
                for item in opf_root.findall('.//opf:manifest/opf:item', ns_opf):
                    item_id = item.attrib.get('id')
                    href = item.attrib.get('href')
                    manifest_items[item_id] = href
                    props = item.attrib.get('properties', '')
                    if cover_href is None and 'cover-image' in props.split():
                        cover_href = href
                if not cover_href:
                    cover_meta = opf_root.find('.//opf:meta[@name="cover"]', ns_opf)
                    cover_id = cover_meta.attrib.get('content') if cover_meta is not None else None
                    if cover_id:
                        cover_href = manifest_items.get(cover_id)

                if cover_href:
                    # href is relative to the OPF file's own directory, not the
                    # zip root (e.g. "OEBPS/content.opf" + href "images/cover.jpg").
                    opf_dir = os.path.dirname(opf_path)
                    cover_zip_path = os.path.normpath(os.path.join(opf_dir, cover_href)).replace('\\', '/')
                    try:
                        metadata["cover_bytes"] = z.read(cover_zip_path)
                        metadata["cover_ext"] = os.path.splitext(cover_zip_path)[1].lower() or '.jpg'
                    except KeyError:
                        pass
    except Exception as e:
        log_message("warning", "metadata", f"Error parsing EPUB: {e}")
    return metadata


def parse_pdf_metadata(pdf_path: str) -> dict:
    from pypdf import PdfReader

    # No cover extraction for PDF: unlike EPUB, a PDF has no dedicated
    # "cover image" concept in its metadata — the closest proxy (rendering
    # page 1 to a raster image) needs a PDF rendering stack (e.g.
    # pdf2image+poppler) this backend doesn't otherwise depend on, for a
    # result that's often not a real cover anyway (many PDFs start with a
    # title/copyright text page, not an illustration).
    metadata = {
        "title": os.path.splitext(os.path.basename(pdf_path))[0],
        "author": "Autore Sconosciuto",
        "description": "",
        "tags": [],
        "series": None,
        "series_index": None,
        "language": None,
        "isbn": None,
        "cover_bytes": None,
        "cover_ext": None,
    }
    if not os.path.exists(pdf_path):
        return metadata
    try:
        reader = PdfReader(pdf_path)
        info = reader.metadata
        if info:
            if info.title:
                metadata["title"] = info.title
            if info.author:
                metadata["author"] = info.author
    except Exception as e:
        log_message("warning", "metadata", f"Error parsing PDF: {e}")
    return metadata
