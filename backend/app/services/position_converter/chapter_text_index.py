"""
Collapsed-text index over a chapter DOM, approximating how crengine builds
its text nodes (whitespace runs collapse to a single space, leading
whitespace after block boundaries drops). Every collapsed CODE POINT maps
back to its raw text node + UTF-16 offset, so positions can be translated
between:
- crengine xpointer offsets (code points in the collapsed view of a text run)
- browser/CFI offsets (UTF-16 code units in the raw text nodes)
Synthetic separators are inserted between blocks for search quality; they
map to no raw position and are skipped when resolving range endpoints.

Ported from BookOrbit's chapter-text-index.ts, with one intentional
simplification: the original keeps a parallel `cpByUtf16` index purely to
translate between UTF-16 and code-point offsets INTO its own `collapsed`
string, because JS strings are UTF-16-indexed. Python strings are already
code-point sequences, so `self.collapsed` can be indexed/sliced/regex-
matched directly by code point — no equivalent translation layer is
needed here. Offsets into the RAW text nodes still have to be tracked in
UTF-16 units (html_dom.utf16_str_length) since that's what the CFI/browser
Range consumer downstream expects.
"""

import re
import unicodedata

from .html_dom import get_document_element, is_element_node, is_text_node, utf16_length, utf16_str_length

_BLOCK_ELEMENTS = frozenset(
    [
        "address", "article", "aside", "blockquote", "body", "caption", "dd", "div", "dl", "dt",
        "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
        "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table", "tbody", "td",
        "tfoot", "th", "thead", "tr", "ul",
    ]
)

_WHITESPACE_RE = re.compile(r"\s")


def normalize_for_search(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", normalized).strip()


def _escape_regexp(value: str) -> str:
    return re.sub(r"[.*+?^${}()|\[\]\\]", lambda m: "\\" + m.group(0), value)


class TextRunPart:
    __slots__ = ("node", "raw_length")

    def __init__(self, node, raw_length):
        self.node = node
        self.raw_length = raw_length


class TextRun:
    __slots__ = ("parts", "parent", "run_index", "run_count", "collapsed_start", "collapsed_length")

    def __init__(self, parts, parent):
        self.parts = parts
        self.parent = parent
        self.run_index = 0
        self.run_count = 0
        self.collapsed_start = 0
        self.collapsed_length = 0


class RawPoint:
    __slots__ = ("node", "offset")

    def __init__(self, node, offset):
        self.node = node
        self.offset = offset


class SearchMatch:
    __slots__ = ("start_cp", "end_cp", "distance")

    def __init__(self, start_cp, end_cp, distance):
        self.start_cp = start_cp
        self.end_cp = end_cp
        self.distance = distance


class _BuildState:
    __slots__ = ("collapsed_points", "run_by_point", "raw_offset_by_point", "at_boundary", "last_was_space", "separator_pending")

    def __init__(self):
        self.collapsed_points = []
        self.run_by_point = []
        self.raw_offset_by_point = []
        self.at_boundary = True
        self.last_was_space = False
        self.separator_pending = False


class ChapterTextIndex:
    def __init__(self, root):
        state = _BuildState()
        runs = []
        self._run_info_by_node = {}

        document_element = get_document_element(root)
        body = None
        if document_element is not None:
            body = next(
                (
                    c
                    for c in (document_element.children or [])
                    if is_element_node(c) and (c.name or "").lower() == "body"
                ),
                None,
            )
        body = body or document_element
        if body is not None:
            self._walk_element(body, state, runs)

        self.runs = runs
        self.collapsed = "".join(state.collapsed_points)
        self.collapsed_cp_length = len(state.collapsed_points)
        self._run_by_point = state.run_by_point
        self._raw_offset_by_point = state.raw_offset_by_point

        self._runs_by_parent = {}
        for run in runs:
            self._runs_by_parent.setdefault(run.parent, []).append(run)
        for run_list in self._runs_by_parent.values():
            for i, run in enumerate(run_list):
                run.run_index = i + 1
                run.run_count = len(run_list)

    # -- build ------------------------------------------------------------

    def _walk_element(self, element, state, runs):
        children = element.children or []
        i = 0
        n = len(children)
        while i < n:
            child = children[i]
            if is_text_node(child):
                parts = []
                while i < n and is_text_node(children[i]):
                    parts.append(children[i])
                    i += 1
                self._emit_run(parts, element, state, runs)
                continue
            if is_element_node(child):
                is_block = (child.name or "").lower() in _BLOCK_ELEMENTS
                if is_block:
                    state.at_boundary = True
                    state.separator_pending = len(state.collapsed_points) > 0
                self._walk_element(child, state, runs)
                if is_block:
                    state.at_boundary = True
                    state.separator_pending = len(state.collapsed_points) > 0
            i += 1

    def _emit_run(self, part_nodes, parent, state, runs):
        run = TextRun(
            parts=[TextRunPart(node, utf16_str_length(node.data or "")) for node in part_nodes],
            parent=parent,
        )
        run.collapsed_start = len(state.collapsed_points)
        run_idx = len(runs)
        emitted_any = False
        raw_concat_offset = 0

        for part in run.parts:
            self._run_info_by_node[part.node] = (run, raw_concat_offset)
            raw = part.node.data or ""
            for cp in raw:
                cp_len = utf16_length(cp)
                if _WHITESPACE_RE.match(cp):
                    if not state.at_boundary and not state.last_was_space:
                        state.collapsed_points.append(" ")
                        state.run_by_point.append(run_idx)
                        state.raw_offset_by_point.append(raw_concat_offset)
                        state.last_was_space = True
                        if not emitted_any:
                            run.collapsed_start = len(state.collapsed_points) - 1
                            emitted_any = True
                else:
                    if state.separator_pending:
                        state.collapsed_points.append(" ")
                        state.run_by_point.append(-1)
                        state.raw_offset_by_point.append(-1)
                        state.separator_pending = False
                    if not emitted_any:
                        run.collapsed_start = len(state.collapsed_points)
                        emitted_any = True
                    state.collapsed_points.append(cp)
                    state.run_by_point.append(run_idx)
                    state.raw_offset_by_point.append(raw_concat_offset)
                    state.at_boundary = False
                    state.last_was_space = False
                raw_concat_offset += cp_len

        run.collapsed_length = (len(state.collapsed_points) - run.collapsed_start) if emitted_any else 0
        runs.append(run)

    # -- lookups ------------------------------------------------------------

    def runs_of_parent(self, element):
        return self._runs_by_parent.get(element, [])

    def first_run_within(self, element):
        """First text run inside the element (any depth), for chapter/element-level hints."""
        if is_text_node(element):
            info = self._run_info_by_node.get(element)
            return info[0] if info else None
        for child in element.children or []:
            found = self.first_run_within(child)
            if found:
                return found
        return None

    def run_of_text_node(self, node):
        info = self._run_info_by_node.get(node)
        return info[0] if info else None

    def collapsed_for_run_offset(self, run: TextRun, cp_offset: int) -> int:
        return run.collapsed_start + max(0, min(cp_offset, run.collapsed_length))

    def start_point_from_collapsed(self, cp_index: int):
        """Inclusive start point: resolves the collapsed cp index to (raw text node, UTF-16 offset)."""
        i = max(0, min(cp_index, self.collapsed_cp_length - 1))
        while i < self.collapsed_cp_length and self._run_by_point[i] < 0:
            i += 1
        if i >= self.collapsed_cp_length:
            return None
        return self._raw_point_at(i)

    def end_point_from_collapsed(self, cp_index_exclusive: int):
        """Exclusive end point: maps to just after the last collapsed cp of the range."""
        i = min(cp_index_exclusive, self.collapsed_cp_length) - 1
        while i >= 0 and self._run_by_point[i] < 0:
            i -= 1
        if i < 0:
            return None
        point = self._raw_point_at(i)
        if not point:
            return None
        cp_len = utf16_length(self.collapsed[i])
        return RawPoint(point.node, point.offset + cp_len)

    def _raw_point_at(self, cp_index: int):
        run_idx = self._run_by_point[cp_index]
        if run_idx < 0:
            return None
        run = self.runs[run_idx]
        raw_offset = self._raw_offset_by_point[cp_index]
        for part in run.parts:
            if raw_offset <= part.raw_length:
                if raw_offset == part.raw_length and part is not run.parts[-1]:
                    raw_offset = 0
                    continue
                return RawPoint(part.node, raw_offset)
            raw_offset -= part.raw_length
        return None

    def collapsed_from_node_point(self, node, utf16_offset: int):
        """Maps a raw (text node, UTF-16 offset) to the collapsed cp index at or after it."""
        info = self._run_info_by_node.get(node)
        if not info:
            return None
        run, raw_start = info
        target = raw_start + utf16_offset
        lo, hi = run.collapsed_start, run.collapsed_start + run.collapsed_length
        while lo < hi:
            mid = (lo + hi) // 2
            if self._raw_offset_by_point[mid] < target:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def run_offset_of_collapsed(self, cp_index: int, run: TextRun) -> int:
        """Run-relative crengine offset (code points) for a collapsed cp index."""
        return max(0, min(cp_index, run.collapsed_start + run.collapsed_length) - run.collapsed_start)

    def run_at_collapsed(self, cp_index: int, direction: str = "forward"):
        i = max(0, min(cp_index, self.collapsed_cp_length - 1))
        if direction == "forward":
            while i < self.collapsed_cp_length and self._run_by_point[i] < 0:
                i += 1
            if i >= self.collapsed_cp_length:
                return None
        else:
            while i >= 0 and self._run_by_point[i] < 0:
                i -= 1
            if i < 0:
                return None
        return self.runs[self._run_by_point[i]]

    def extract_collapsed(self, start_cp: int, end_cp_exclusive: int) -> str:
        start = max(0, start_cp)
        end = min(end_cp_exclusive, self.collapsed_cp_length)
        return self.collapsed[start:end]

    def search_normalized(self, needle: str, hint_cp):
        """
        Whitespace-tolerant search of the normalized needle in the
        collapsed text. Returns the match nearest to the hint (collapsed
        cp index), if any.
        """
        normalized = normalize_for_search(needle)
        if not normalized:
            return None
        tokens = [_escape_regexp(t) for t in normalized.split(" ")]
        try:
            regex = re.compile(r"\s+".join(tokens))
        except re.error:
            return None

        best = None
        for match in regex.finditer(self.collapsed):
            start_cp = match.start()
            end_cp = match.end()
            distance = None if hint_cp is None else abs(start_cp - hint_cp)
            candidate = SearchMatch(start_cp, end_cp, distance)
            if best is None:
                best = candidate
                if hint_cp is None:
                    break
            elif distance is not None and best.distance is not None and distance < best.distance:
                best = candidate
        return best
