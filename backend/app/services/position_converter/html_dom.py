"""
Minimal HTML-to-tree parser + shared DOM helpers for the xpointer<->CFI
converter (see core.py for the entry point). Built on Python's stdlib
html.parser rather than strict XML parsing on purpose: real-world EPUB
chapter XHTML regularly has unescaped named entities (&nbsp; and friends)
that choke a strict XML parser but that HTMLParser(convert_charrefs=True)
handles natively — same lenient-parsing choice already made elsewhere in
this codebase for chapter content (see services/toc_editor.py's own
HTMLParser subclasses).

The resulting tree mirrors the shape the ported algorithm (xpointer_utils,
cfi_utils, chapter_text_index) expects, which was itself designed around a
cheerio/htmlparser2 DOM (BookOrbit's CfiNode) — type/name/data/attribs/
parent/children.
"""

from html.parser import HTMLParser

# HTML5 void elements: handle_starttag for these never gets a matching
# handle_endtag, so they must never be pushed onto the open-element stack.
_VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class Node:
    __slots__ = ("type", "name", "data", "attribs", "parent", "children")

    def __init__(self, type, name=None, data=None, attribs=None):  # noqa: A002 - mirrors CfiNode.type
        self.type = type
        self.name = name
        self.data = data
        self.attribs = attribs or {}
        self.parent = None
        self.children = []

    def __repr__(self):
        if self.type == "text":
            return f"Text({self.data!r})"
        return f"<{self.name}>"


def is_text_node(node):
    return node is not None and node.type in ("text", "cdata")


def is_element_node(node):
    return node is not None and node.type in ("tag", "script", "style")


def get_document_element(root):
    """
    If given the tree's root, returns its element child (the document
    element, e.g. <html>). If given any other node, walks UP until the
    parent is the root, returning that top-most non-root ancestor. Same
    node either way once resolved — this dual behavior matches how the
    ported algorithm calls it both with the parsed root and with arbitrary
    descendants (cfi.utils.ts::getDocumentElement).
    """
    if root.type == "root":
        for child in root.children or []:
            if is_element_node(child):
                return child
        return None
    current = root
    while current.parent is not None and current.parent.type != "root":
        current = current.parent
    return current


def utf16_length(ch: str) -> int:
    """UTF-16 code-unit length of one Python (i.e. Unicode code point) character."""
    return 2 if ord(ch) > 0xFFFF else 1


def utf16_str_length(s: str) -> int:
    """
    UTF-16 code-unit length of a whole string. Needed because CFI/browser
    Range offsets are always UTF-16 code units, but Python strings are
    already code-point sequences — `len()` alone under-counts any astral
    character (emoji etc.) by one unit each.
    """
    return sum(utf16_length(c) for c in s)


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self._stack = [self.root]

    def _current(self):
        return self._stack[-1]

    def _append_tag(self, tag, attrs):
        node = Node("tag", name=tag.lower(), attribs=dict(attrs))
        parent = self._current()
        node.parent = parent
        parent.children.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._append_tag(tag, attrs)
        if tag.lower() not in _VOID_ELEMENTS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._append_tag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        # Lenient on purpose: real-world chapter XHTML occasionally has an
        # unmatched/mismatched end tag. Pop back to the nearest matching
        # open element if found; otherwise ignore the stray end tag rather
        # than raising, same tolerance toc_editor.py's own parsers apply.
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].name == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        if not data:
            return
        node = Node("text", data=data)
        parent = self._current()
        node.parent = parent
        parent.children.append(node)

    def handle_comment(self, data):
        # Un commento non è testo né elemento (is_text_node/is_element_node
        # sono entrambi False per lui), quindi non riceve mai un proprio
        # indirizzo CFI — ma è comunque un fratello vero nel DOM del browser,
        # che non fonde MAI in un unico Text node il testo che lo precede e
        # quello che lo segue. Se qui non venisse rappresentato affatto (come
        # prima di questo fix), cfi_utils.index_child_nodes vedrebbe quei due
        # pezzi di testo come adiacenti e li unirebbe in un solo chunk
        # indicizzato — un CFI valido ma che punta vicino al testo giusto,
        # non esattamente su di esso (o, più a valle nello stesso elemento,
        # con gli indici di elementi/testi successivi disallineati). Vedi
        # index_child_nodes per la metà del fix che usa questo nodo.
        node = Node("comment", data=data)
        parent = self._current()
        node.parent = parent
        parent.children.append(node)


def parse_html_document(xhtml: str) -> Node:
    """Parses one chapter's XHTML into a Node tree rooted at a synthetic 'root' node."""
    builder = _TreeBuilder()
    builder.feed(xhtml)
    builder.close()
    return builder.root
