"""
EPUB CFI generation over html_dom.Node trees, mirroring the real epub.js
CFI model (frontend/node_modules/epubjs/src/epubcfi.js) exactly: same child
indexing scheme (virtual before/first/last/after, text runs chunked
between elements), same part/offset encoding. Offsets are UTF-16 code
units, matching browser DOM Range semantics (see html_dom.utf16_str_length
for why that needs an explicit helper in Python).

Ported from BookOrbit's cfi.utils.ts — forward direction only (building a
CFI from a resolved DOM point/range). The inverse (parsing an existing CFI
back into DOM points, needed only for CFI->xpointer sync) is out of scope
here; see xpointer_utils.py's own docstring for the same scoping note.
"""

import re

from .html_dom import Node, get_document_element, is_element_node, is_text_node, utf16_str_length

_CFI_RE = re.compile(r"^epubcfi\((.*)\)$")
_ESCAPE_RE = re.compile(r"[\^\[\]\(\),;=]")


class CfiPart:
    __slots__ = ("index", "id", "offset")

    def __init__(self, index, id=None, offset=None):  # noqa: A002 - mirrors CfiPart.id
        self.index = index
        self.id = id
        self.offset = offset


class RangePoint:
    __slots__ = ("node", "offset")

    def __init__(self, node, offset):
        self.node = node
        self.offset = offset


def escape_cfi(value: str) -> str:
    return _ESCAPE_RE.sub(lambda m: "^" + m.group(0), value)


def wrap_cfi(value: str) -> str:
    return value if _CFI_RE.match(value) else f"epubcfi({value})"


def unwrap_cfi(value: str) -> str:
    match = _CFI_RE.match(value)
    return match.group(1) if match else value


def _part_to_string(part: CfiPart) -> str:
    out = f"/{part.index}"
    if part.id:
        out += f"[{escape_cfi(part.id)}]"
    if part.offset is not None and part.index % 2 == 1:
        out += f":{part.offset}"
    return out


def _parts_to_string(parts) -> str:
    return "".join(_part_to_string(p) for p in parts)


def _is_indexed_element(value) -> bool:
    return isinstance(value, Node) and is_element_node(value)


def index_child_nodes(node):
    """
    Builds the CFI "indexed children" view of one element: text-node runs
    are merged into lists (a chunk), an explicit None slot is inserted
    between two elements that have no text between them (a real, empty
    text position CFI still needs to be able to address), and the whole
    thing is bracketed with virtual 'before'/'after' (and, when the first/
    last real child is an element, 'first'/'last') markers — exactly
    epub.js/foliate's own child-indexing model, not naive DOM-child
    numbering.

    Iterates the RAW `node.children` (text/element/comment, not just the
    text/element ones that actually get a CFI slot): a comment is invisible
    to epub.js's own indexing, same as here, but unlike two text nodes with
    nothing at all between them, text on either side of a comment is never
    one contiguous DOM Text node in the browser — it never coalesces text
    across ANY other sibling, comments included. Skipping comments out of
    the iteration entirely (instead of just out of the emitted `nodes`)
    would make two genuinely separate text runs look adjacent and merge
    them into one CFI-addressed chunk, shifting every offset/index computed
    from it — see html_dom.py's own handle_comment for how the comment node
    this relies on gets into the tree in the first place.

    Two text runs left unmerged this way (a comment between them, so
    `prev_was_text` is False but the last EMITTED slot is still a text
    chunk) still need a None gap between them, same as two adjacent
    elements: CFI text/element indices must alternate odd/even by array
    position alone (see _part_to_string), so two text slots back-to-back
    with no gap would land the second one on an even (element) index.
    """
    nodes = []
    prev_was_text = False
    for child in node.children or []:
        if is_text_node(child):
            last = nodes[-1] if nodes else None
            if prev_was_text and isinstance(last, list):
                last.append(child)
            elif prev_was_text and is_text_node(last):
                nodes[-1] = [last, child]
            else:
                if isinstance(last, list) or is_text_node(last):
                    nodes.append(None)
                nodes.append(child)
            prev_was_text = True
        elif is_element_node(child):
            last = nodes[-1] if nodes else None
            if _is_indexed_element(last):
                nodes.append(None)
            nodes.append(child)
            prev_was_text = False
        else:
            # Commento (o altro nodo che epub.js non indicizza affatto): non
            # riceve uno slot, ma interrompe comunque l'adiacenza testuale.
            prev_was_text = False

    if nodes and _is_indexed_element(nodes[0]):
        nodes.insert(0, "first")
    if nodes and _is_indexed_element(nodes[-1]):
        nodes.append("last")
    nodes.insert(0, "before")
    nodes.append("after")
    return nodes


def _child_matches(indexed, node) -> bool:
    if isinstance(indexed, list):
        return node in indexed
    return indexed is node


def _node_text_length(node) -> int:
    return utf16_str_length(node.data) if node.data else 0


def node_to_parts(node, offset=None):
    """
    Builds the full CFI part chain (root..node), foliate/epub.js
    `nodeToParts` style: for a node inside a merged text-run chunk, the
    caller's offset (within just that one text node) gets re-based to be
    relative to the START of the whole merged chunk, since that's the
    unit CFI addresses.
    """
    parent = node.parent
    if parent is None:
        raise ValueError("Cannot build CFI for node without parent")

    indexed = index_child_nodes(parent)
    index = next((i for i, c in enumerate(indexed) if _child_matches(c, node)), -1)
    if index < 0:
        raise ValueError("Cannot locate node in parent CFI index")

    adjusted_offset = offset
    chunk = indexed[index]
    if isinstance(chunk, list) and offset is not None:
        total = 0
        for child in chunk:
            if child is node:
                total += offset
                break
            total += _node_text_length(child)
        adjusted_offset = total

    part = CfiPart(index=index)
    node_id = (node.attribs or {}).get("id")
    if node_id:
        part.id = node_id
    if adjusted_offset is not None:
        part.offset = adjusted_offset

    document_element = get_document_element(node)
    if parent is not document_element and parent.type != "root":
        return node_to_parts(parent) + [part]
    return [part]


def _build_range(from_parts, to_parts) -> str:
    parent, start, end = [], [], []
    push_to_parent = True
    length = max(len(from_parts), len(to_parts))

    for i in range(length):
        a = from_parts[i] if i < len(from_parts) else None
        b = to_parts[i] if i < len(to_parts) else None
        push_to_parent = push_to_parent and (
            a is not None and b is not None and a.index == b.index and not a.offset and not b.offset
        )
        if push_to_parent:
            if a is not None:
                parent.append(a)
        else:
            if a is not None:
                start.append(a)
            if b is not None:
                end.append(b)

    return wrap_cfi(f"{_parts_to_string(parent)},{_parts_to_string(start)},{_parts_to_string(end)}")


def join_cfi_indirection(*parts: str) -> str:
    return wrap_cfi("!".join(unwrap_cfi(p) for p in parts))


def spine_cfi_for_chapter_index(chapter_index: int) -> str:
    """
    The mandatory package-document "spine" step: a real CFI's base
    component needs (at least) two steps — a fixed /6 (the package
    document's "spine" element, per the actual EPUB CFI spec) followed by
    the spine item's own even-numbered index. Confirmed directly against
    the real epub.js parser (frontend/node_modules/epubjs/src/epubcfi.js:
    `cfi.spinePos = cfi.base.steps[1].index`) — omitting /6/ (as an earlier
    version of this project's Calibre-annotation-import code did) makes
    EpubCFI.parse() throw outright.
    """
    return wrap_cfi(f"/6/{(chapter_index + 1) * 2}")


def cfi_from_range_points(start: RangePoint, end: RangePoint) -> str:
    start_parts = node_to_parts(start.node, start.offset)
    end_parts = node_to_parts(end.node, end.offset)
    return _build_range(start_parts, end_parts)


def cfi_from_point(point: RangePoint) -> str:
    return wrap_cfi(_parts_to_string(node_to_parts(point.node, point.offset)))
