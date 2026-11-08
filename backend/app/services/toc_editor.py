"""
Real TOC (table of contents) read/write for EPUB (NCX navMap) and PDF
(outline). The EPUB side follows the same shape as Calibre's own "Edit ToC"
engine (src/calibre/ebooks/oeb/polish/toc.py in the calibre source):
NCX found via the OPF manifest's `application/x-dtbncx+xml` media-type,
navPoint ids as a monotonically increasing counter, playOrder written (never
read back in), content/@src omitted when there's no destination. Unlike
Calibre's own tree/Node model, entries here are a flat list of
`{title, dest, level}` dicts (level = 0-based nesting depth) — simpler, and
matches the frontend TOC editor's flat, indentable list UI.
"""

import os
import posixpath
import re
import secrets
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from pypdf import PdfReader, PdfWriter
from ..logging_utils import log_message

NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
NCX = {"ncx": NCX_NS}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}


def edit_pdf_toc(pdf_path: str, new_toc: list) -> bool:
    """
    Rewrites the outline of a PDF using pypdf.
    new_toc is a list of dicts: [{'title': 'Capitolo I', 'page': 5}, ...]
    """
    if not os.path.exists(pdf_path):
        return False
    try:
        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        writer.append(reader)

        for item in new_toc:
            page_num = int(item.get('page', 1)) - 1
            writer.add_outline_item(item.get('title', 'Capitolo'), max(0, page_num))

        # Write to a sibling temp file and swap it in, exactly like the EPUB
        # branch below. Opening pdf_path "wb" directly TRUNCATES the only copy
        # of the book before a single byte is written: any failure in
        # writer.write (or the process dying mid-write) left a 0-byte or
        # half-written PDF where the book used to be, and the `except` below
        # would dutifully report False having already destroyed it.
        temp_pdf = pdf_path + ".temp"
        try:
            with open(temp_pdf, "wb") as f:
                writer.write(f)
            os.replace(temp_pdf, pdf_path)
        except Exception:
            if os.path.exists(temp_pdf):
                os.remove(temp_pdf)
            raise
        return True
    except Exception as e:
        log_message("warning", "toc", f"Error editing PDF TOC: {e}")
        return False


def get_pdf_page_count(pdf_path: str) -> int:
    if not os.path.exists(pdf_path):
        return 0
    try:
        return len(PdfReader(pdf_path).pages)
    except Exception:
        return 0


def get_pdf_toc(pdf_path: str) -> list:
    """Returns a flat [{title, dest, level, valid}] list from a PDF's existing
    outline (dest = 1-based page number as a string; valid = page number
    actually falls within the document, the "green checkmark" signal the
    two-panel TOC editor shows per entry)."""
    if not os.path.exists(pdf_path):
        return []
    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        entries = []

        def walk(outline, level):
            for item in outline:
                if isinstance(item, list):
                    walk(item, level + 1)
                    continue
                try:
                    page_num = reader.get_destination_page_number(item) + 1
                except Exception:
                    page_num = 1
                entries.append({
                    "title": item.title, "dest": str(page_num), "level": level,
                    "valid": 1 <= page_num <= total_pages,
                })

        walk(reader.outline, 0)
        return entries
    except Exception as e:
        log_message("warning", "toc", f"Error reading PDF TOC: {e}")
        return []


def _find_opf_path(z: zipfile.ZipFile) -> str:
    container = z.read("META-INF/container.xml")
    root = ET.fromstring(container)
    rootfile = root.find(".//c:rootfile", CONTAINER_NS)
    return rootfile.attrib["full-path"]


def _find_ncx_path(z: zipfile.ZipFile, opf_path: str):
    opf_dir = os.path.dirname(opf_path)
    opf_root = ET.fromstring(z.read(opf_path))
    for item in opf_root.findall(".//opf:manifest/opf:item", OPF_NS):
        if item.attrib.get("media-type") == "application/x-dtbncx+xml":
            href = item.attrib["href"]
            return os.path.normpath(os.path.join(opf_dir, href)).replace(os.sep, "/") if opf_dir else href
    return None


def _find_spine_hrefs(z: zipfile.ZipFile, opf_path: str) -> list:
    """Manifest hrefs in spine (reading) order, resolved relative to the OPF's own directory."""
    opf_dir = os.path.dirname(opf_path)
    opf_root = ET.fromstring(z.read(opf_path))
    manifest = {
        item.attrib.get("id"): item.attrib.get("href")
        for item in opf_root.findall(".//opf:manifest/opf:item", OPF_NS)
    }
    hrefs = []
    for itemref in opf_root.findall(".//opf:spine/opf:itemref", OPF_NS):
        href = manifest.get(itemref.attrib.get("idref"))
        if href:
            resolved = os.path.normpath(os.path.join(opf_dir, href)).replace(os.sep, "/") if opf_dir else href
            hrefs.append(resolved)
    return hrefs


_ID_ATTR_RE = re.compile(r'\bid=["\']([^"\']+)["\']')


def list_epub_destinations(epub_path: str) -> list:
    """Every spine document in reading order with the anchor ids found inside
    it — feeds the TOC editor's "change destination" picker, so it only ever
    offers destinations that actually exist in the book (the same source of
    truth _epub_dest_valid checks entries against). hrefs are returned
    relative to the NCX's own directory, not the OPF's — NCX content/@src is
    resolved against the NCX's location, and the two directories aren't
    always the same, so this must match or a picked destination would write
    back a broken path (caught in testing before this shipped)."""
    if not os.path.exists(epub_path):
        return []
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            opf_path = _find_opf_path(z)
            ncx_path = _find_ncx_path(z, opf_path)
            ncx_dir = os.path.dirname(ncx_path) if ncx_path else os.path.dirname(opf_path)
            out = []
            for href in _find_spine_hrefs(z, opf_path):
                try:
                    content = z.read(href).decode("utf-8", errors="ignore")
                    anchors = _ID_ATTR_RE.findall(content)
                except KeyError:
                    anchors = []
                rel_href = posixpath.relpath(href, ncx_dir) if ncx_dir else href
                out.append({"href": rel_href, "anchors": anchors})
            return out
    except Exception as e:
        log_message("warning", "toc", f"Error listing EPUB destinations: {e}")
        return []


def get_epub_file_content(epub_path: str, href: str) -> bytes:
    """
    Raw bytes of one spine document, relative to the NCX's own directory
    (same base as every other href in this module) — used to render the real
    chapter in the interactive destination picker's preview pane. Rendered
    standalone (no base URL fixups for its own relative CSS/image links), so
    styling/images from the original file won't load; the text — the only
    thing click-to-select-a-destination actually needs — renders fine.
    """
    if not os.path.exists(epub_path):
        return b""
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            opf_path = _find_opf_path(z)
            ncx_path = _find_ncx_path(z, opf_path)
            ncx_dir = os.path.dirname(ncx_path) if ncx_path else os.path.dirname(opf_path)
            resolved = os.path.normpath(os.path.join(ncx_dir, href)).replace(os.sep, "/") if ncx_dir else href
            return z.read(resolved)
    except Exception as e:
        log_message("warning", "toc", f"Error reading EPUB file content: {e}")
        return b""


class _PathTrackingParser(HTMLParser):
    """
    Finds the element at `target_path` (a list of 0-based child-element
    indices counted from <body>, matching how the frontend computes a
    clicked element's path from `document.body` via `element.children`) and
    records its tag name plus the exact (line, col) of its opening `<tag`, so
    the caller can splice in an `id="..."` attribute with a plain string
    edit — deliberately not a full parse+reserialize, which would risk
    subtly corrupting the rest of a real content chapter (lost DOCTYPE,
    self-closing tag style, entities, comments).
    """

    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, target_path):
        super().__init__(convert_charrefs=False)
        self.target_path = target_path
        self._in_body = False
        self._path_stack = []  # indices of ancestors, from body's first child down
        self._next_index_stack = [0]  # next sibling index to assign at the current depth
        self.result = None
        self.existing_ids = set()

    def _handle_element(self, tag, attrs, self_closing):
        attrs_dict = dict(attrs)
        if "id" in attrs_dict:
            self.existing_ids.add(attrs_dict["id"])

        if tag == "body":
            if not self_closing:
                self._in_body = True
            return
        if not self._in_body:
            return

        idx = self._next_index_stack[-1]
        self._next_index_stack[-1] += 1
        current_path = self._path_stack + [idx]

        if self.result is None and current_path == self.target_path:
            self.result = {"tag": tag, "pos": self.getpos(), "existing_id": attrs_dict.get("id")}

        if not self_closing and tag not in self.VOID_TAGS:
            self._path_stack.append(idx)
            self._next_index_stack.append(0)

    def handle_starttag(self, tag, attrs):
        self._handle_element(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag, attrs):
        self._handle_element(tag, attrs, self_closing=True)

    def handle_endtag(self, tag):
        if tag == "body":
            self._in_body = False
            return
        if self._in_body and self._path_stack:
            self._path_stack.pop()
            self._next_index_stack.pop()


def resolve_or_create_anchor(epub_path: str, href: str, child_path: list) -> str:
    """
    Given a click-derived `child_path` (element-index path from <body>,
    computed identically on the frontend), returns the id to use as an
    anchor: the element's own id if it already has one, otherwise a freshly
    minted one, spliced into the raw file text at the exact character
    position of the opening tag — a surgical string edit, not a re-parse/
    re-serialize of the whole file, so nothing else in the chapter changes.
    """
    if not os.path.exists(epub_path):
        return None
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            opf_path = _find_opf_path(z)
            ncx_path = _find_ncx_path(z, opf_path)
            ncx_dir = os.path.dirname(ncx_path) if ncx_path else os.path.dirname(opf_path)
            resolved = os.path.normpath(os.path.join(ncx_dir, href)).replace(os.sep, "/") if ncx_dir else href
            raw_bytes = z.read(resolved)

        text = raw_bytes.decode("utf-8", errors="ignore")
        parser = _PathTrackingParser(child_path)
        parser.feed(text)

        if not parser.result:
            return None
        if parser.result["existing_id"]:
            return parser.result["existing_id"]

        new_id = f"kolibre-anchor-{secrets.token_hex(4)}"
        while new_id in parser.existing_ids:
            new_id = f"kolibre-anchor-{secrets.token_hex(4)}"

        line, col = parser.result["pos"]
        lines = text.splitlines(keepends=True)
        offset = sum(len(l) for l in lines[:line - 1]) + col
        tag = parser.result["tag"]
        m = re.match(r"<" + re.escape(tag) + r"\b", text[offset:offset + len(tag) + 1])
        if not m:
            return None
        insert_at = offset + m.end()
        new_text = text[:insert_at] + f' id="{new_id}"' + text[insert_at:]

        temp_epub = epub_path + ".temp"
        with zipfile.ZipFile(epub_path, "r") as zin:
            with zipfile.ZipFile(temp_epub, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = new_text.encode("utf-8") if item.filename == resolved else zin.read(item.filename)
                    zout.writestr(item, data)
        os.replace(temp_epub, epub_path)
        return new_id
    except Exception as e:
        log_message("warning", "toc", f"Error resolving/creating anchor: {e}")
        return None


class _HeadingScanner(HTMLParser):
    """Collects every h1..h{max_level} in document order, with its text and
    (if present) existing id."""

    def __init__(self, max_level):
        super().__init__(convert_charrefs=True)
        self.max_level = max_level
        self.headings = []  # [{level, text, existing_id, pos}]
        self._current = None

    def handle_starttag(self, tag, attrs):
        if re.fullmatch(r"h[1-6]", tag):
            level = int(tag[1])
            if level <= self.max_level:
                self._current = {"level": level, "text": "", "existing_id": dict(attrs).get("id"), "pos": self.getpos(), "tag": tag}

    def handle_data(self, data):
        if self._current is not None:
            self._current["text"] += data

    def handle_endtag(self, tag):
        if self._current is not None and tag == self._current["tag"]:
            self._current["text"] = " ".join(self._current["text"].split())
            if self._current["text"]:
                self.headings.append(self._current)
            self._current = None


def generate_toc_from_headings(epub_path: str, max_level: int) -> list:
    """
    "Genera il Sommario dalle Intestazioni" (max_level=1: solo h1) / "da
    tutte le intestazioni" (max_level=6): walks every spine file in order,
    collects h1..h{max_level}, and assigns each an anchor id (reusing one
    that's already there; minting+injecting a new one otherwise — same
    surgical text-splice as resolve_or_create_anchor, batched per file).
    Returns a flat [{title, dest, level}] list — this does NOT save the
    book's NCX by itself, it only builds the list the TOC editor's tree
    then shows for review before the user hits Salva.
    """
    if not os.path.exists(epub_path):
        return []
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            opf_path = _find_opf_path(z)
            ncx_path = _find_ncx_path(z, opf_path)
            ncx_dir = os.path.dirname(ncx_path) if ncx_path else os.path.dirname(opf_path)
            spine_hrefs = _find_spine_hrefs(z, opf_path)
            file_bytes = {href: z.read(href) for href in spine_hrefs}

        entries = []
        modified = {}
        for href in spine_hrefs:
            text = file_bytes[href].decode("utf-8", errors="ignore")
            scanner = _HeadingScanner(max_level)
            scanner.feed(text)
            if not scanner.headings:
                continue

            lines = text.splitlines(keepends=True)
            # Insert furthest-in-the-file first so earlier offsets stay valid.
            for h in sorted(scanner.headings, key=lambda x: x["pos"], reverse=True):
                anchor_id = h["existing_id"]
                if not anchor_id:
                    existing_ids = set(_ID_ATTR_RE.findall(text))
                    anchor_id = f"kolibre-anchor-{secrets.token_hex(4)}"
                    while anchor_id in existing_ids:
                        anchor_id = f"kolibre-anchor-{secrets.token_hex(4)}"
                    line, col = h["pos"]
                    offset = sum(len(l) for l in lines[:line - 1]) + col
                    m = re.match(r"<" + re.escape(h["tag"]) + r"\b", text[offset:offset + len(h["tag"]) + 1])
                    if m:
                        insert_at = offset + m.end()
                        text = text[:insert_at] + f' id="{anchor_id}"' + text[insert_at:]
                        lines = text.splitlines(keepends=True)
                h["anchor_id"] = anchor_id

            modified[href] = text
            rel_href = posixpath.relpath(href, ncx_dir) if ncx_dir else href
            for h in sorted(scanner.headings, key=lambda x: x["pos"]):
                entries.append({
                    "title": h["text"],
                    "dest": f"{rel_href}#{h['anchor_id']}",
                    "level": h["level"] - 1,
                })

        if modified:
            temp_epub = epub_path + ".temp"
            with zipfile.ZipFile(epub_path, "r") as zin:
                with zipfile.ZipFile(temp_epub, "w", zipfile.ZIP_DEFLATED) as zout:
                    for item in zin.infolist():
                        data = modified[item.filename].encode("utf-8") if item.filename in modified else zin.read(item.filename)
                        zout.writestr(item, data)
            os.replace(temp_epub, epub_path)

        return entries
    except Exception as e:
        log_message("warning", "toc", f"Error generating TOC from headings: {e}")
        return []


_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def generate_toc_from_files(epub_path: str) -> list:
    """"Genera il Sommario dai File": one top-level entry per spine file, no
    anchor needed (a bare file href always resolves), title from the file's
    own <title> tag or a prettified filename otherwise."""
    if not os.path.exists(epub_path):
        return []
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            opf_path = _find_opf_path(z)
            ncx_path = _find_ncx_path(z, opf_path)
            ncx_dir = os.path.dirname(ncx_path) if ncx_path else os.path.dirname(opf_path)
            entries = []
            for href in _find_spine_hrefs(z, opf_path):
                try:
                    content = z.read(href).decode("utf-8", errors="ignore")
                except KeyError:
                    content = ""
                m = _TITLE_TAG_RE.search(content)
                title = " ".join(m.group(1).split()) if m and m.group(1).strip() else None
                if not title:
                    base = os.path.splitext(os.path.basename(href))[0]
                    title = base.replace("_", " ").replace("-", " ").strip().capitalize() or href
                rel_href = posixpath.relpath(href, ncx_dir) if ncx_dir else href
                entries.append({"title": title, "dest": rel_href, "level": 0})
            return entries
    except Exception as e:
        log_message("warning", "toc", f"Error generating TOC from files: {e}")
        return []


def _epub_dest_valid(z: zipfile.ZipFile, ncx_dir: str, dest: str) -> bool:
    """A destination is valid if its file part exists in the zip and, when an
    anchor is given, that anchor id is actually present in the file — this is
    the "green checkmark" signal the two-panel TOC editor shows per entry."""
    if not dest:
        return True  # a section header with no destination isn't "broken"
    file_part, _, anchor = dest.partition("#")
    if not file_part:
        return True  # anchor-only dest (rare); nothing reliable to check against
    resolved = os.path.normpath(os.path.join(ncx_dir, file_part)).replace(os.sep, "/") if ncx_dir else file_part
    if resolved not in z.namelist():
        return False
    if anchor:
        try:
            content = z.read(resolved).decode("utf-8", errors="ignore")
        except KeyError:
            return False
        if f'id="{anchor}"' not in content and f"id='{anchor}'" not in content:
            return False
    return True


def get_epub_toc(epub_path: str) -> list:
    """Returns a flat [{title, dest, level, valid}] list parsed from the
    EPUB's NCX navMap, or [] if there is no NCX (e.g. a nav.xhtml-only EPUB3
    book — not yet supported)."""
    if not os.path.exists(epub_path):
        return []
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            opf_path = _find_opf_path(z)
            ncx_path = _find_ncx_path(z, opf_path)
            if not ncx_path:
                return []
            ncx_dir = os.path.dirname(ncx_path)
            ncx_root = ET.fromstring(z.read(ncx_path))
            nav_map = ncx_root.find("ncx:navMap", NCX)
            if nav_map is None:
                return []

            entries = []

            def walk(node, level):
                for nav_point in node.findall("ncx:navPoint", NCX):
                    label_el = nav_point.find("ncx:navLabel/ncx:text", NCX)
                    content_el = nav_point.find("ncx:content", NCX)
                    dest = content_el.attrib.get("src", "") if content_el is not None else ""
                    entries.append({
                        "title": (label_el.text or "").strip() if label_el is not None else "",
                        "dest": dest,
                        "level": level,
                        "valid": _epub_dest_valid(z, ncx_dir, dest),
                    })
                    walk(nav_point, level + 1)

            walk(nav_map, 0)
            return entries
    except Exception as e:
        log_message("warning", "toc", f"Error reading EPUB TOC: {e}")
        return []


def set_epub_toc(epub_path: str, entries: list) -> bool:
    """Rebuilds the EPUB's NCX navMap from a flat [{title, dest, level}] list, replacing whatever was there."""
    if not os.path.exists(epub_path):
        return False
    try:
        with zipfile.ZipFile(epub_path, "r") as zin:
            opf_path = _find_opf_path(zin)
            ncx_path = _find_ncx_path(zin, opf_path)
            if not ncx_path:
                return False
            ncx_root = ET.fromstring(zin.read(ncx_path))

        ET.register_namespace("", NCX_NS)
        nav_map = ncx_root.find("ncx:navMap", NCX)
        if nav_map is None:
            return False
        for child in list(nav_map):
            nav_map.remove(child)

        # parents[level] = the navPoint (or navMap, for level -1) that owns the
        # next entry at that level; a new entry always starts a fresh subtree,
        # so every deeper level recorded so far becomes stale once we add it.
        parents = {-1: nav_map}
        counter = 0
        for entry in entries:
            level = max(0, int(entry.get("level", 0) or 0))
            parent_level = level - 1
            while parent_level not in parents:
                parent_level -= 1
            counter += 1
            nav_point = ET.SubElement(parents[parent_level], f"{{{NCX_NS}}}navPoint", {
                "id": f"num_{counter}", "playOrder": str(counter),
            })
            nav_label = ET.SubElement(nav_point, f"{{{NCX_NS}}}navLabel")
            text_el = ET.SubElement(nav_label, f"{{{NCX_NS}}}text")
            text_el.text = entry.get("title", "")
            dest = entry.get("dest")
            if dest:
                ET.SubElement(nav_point, f"{{{NCX_NS}}}content", {"src": dest})
            parents = {lvl: node for lvl, node in parents.items() if lvl < level}
            parents[level] = nav_point

        new_ncx_bytes = ET.tostring(ncx_root, encoding="utf-8", xml_declaration=True)

        temp_epub = epub_path + ".temp"
        with zipfile.ZipFile(epub_path, "r") as zin:
            with zipfile.ZipFile(temp_epub, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = new_ncx_bytes if item.filename == ncx_path else zin.read(item.filename)
                    zout.writestr(item, data)
        os.replace(temp_epub, epub_path)
        return True
    except Exception as e:
        log_message("warning", "toc", f"Error writing EPUB TOC: {e}")
        return False
