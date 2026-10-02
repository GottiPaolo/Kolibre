"""
crengine XPointer utilities (KOReader EPUB positions), matching lvtinydom's
toStringV2 serialization: /body/DocFragment[N]/body/.../p[k]/text()[t].offset
- element steps are 1-based among SAME-NAME element siblings; [k] is emitted
  only when more than one same-named sibling exists
- text() steps are 1-based among text-node children; [t] only when more than
  one exists
- offsets count Unicode CODE POINTS in crengine's (whitespace-collapsed)
  text node

Ported from BookOrbit's xpointer.utils.ts (only the forward, xpointer->CFI
direction this project needs — see chapter_text_index.py/core.py for why
the CFI->xpointer inverse and buildXPointer* helpers were left out).
"""

import re

from .html_dom import get_document_element, is_element_node

_XPOINTER_RE = re.compile(r"^/body/DocFragment(?:\[(\d+)\])?(.*)$")
_STEP_RE = re.compile(r"^([A-Za-z][\w:-]*)(?:\[(\d+)\])?$")
_TEXT_STEP_RE = re.compile(r"^text\(\)(?:\[(\d+)\])?$")


class XPointerStep:
    __slots__ = ("name", "index")

    def __init__(self, name, index):
        self.name = name
        self.index = index

    def __eq__(self, other):
        return isinstance(other, XPointerStep) and self.name == other.name and self.index == other.index

    def __repr__(self):
        return f"XPointerStep({self.name!r}, {self.index})"


class ParsedXPointer:
    __slots__ = ("doc_fragment_index", "steps", "text_index", "offset")

    def __init__(self, doc_fragment_index, steps, text_index, offset):
        self.doc_fragment_index = doc_fragment_index
        self.steps = steps
        self.text_index = text_index
        self.offset = offset

    def __repr__(self):
        return (
            f"ParsedXPointer(doc_fragment_index={self.doc_fragment_index}, steps={self.steps}, "
            f"text_index={self.text_index}, offset={self.offset})"
        )


def parse_xpointer(raw: str):
    if not raw:
        return None
    match = _XPOINTER_RE.match(raw.strip())
    if not match:
        return None
    doc_fragment_index = int(match.group(1)) if match.group(1) else 1

    rest = match.group(2) or ""
    offset = None
    offset_match = re.search(r"\.(\d+)$", rest)
    if offset_match:
        offset = int(offset_match.group(1))
        rest = rest[: -len(offset_match.group(0))]

    steps = []
    text_index = None
    for segment in rest.split("/"):
        if not segment:
            continue
        text_match = _TEXT_STEP_RE.match(segment)
        if text_match:
            text_index = int(text_match.group(1)) if text_match.group(1) else 1
            continue
        if text_index is not None:
            # A step after a text() segment is malformed (text() is always terminal).
            return None
        step_match = _STEP_RE.match(segment)
        if not step_match:
            return None
        steps.append(XPointerStep(step_match.group(1), int(step_match.group(2)) if step_match.group(2) else 1))

    if offset is not None and text_index is None:
        # crengine can emit element-level offsets (rare); treat as first text node.
        text_index = 1

    return ParsedXPointer(doc_fragment_index, steps, text_index, offset)


def resolve_xpointer_element(root, steps):
    """
    Resolves the element path of a parsed xpointer against a chapter
    document. The first step (usually "body") is resolved among the
    document element's children, mirroring crengine's DocFragment > body
    nesting.
    """
    document_element = get_document_element(root)
    if document_element is None:
        return None
    current = document_element

    for step in steps:
        children = [
            child
            for child in (current.children or [])
            if is_element_node(child) and (child.name or "").lower() == step.name.lower()
        ]
        idx = step.index - 1
        if idx < 0 or idx >= len(children):
            return None
        current = children[idx]
    return current
