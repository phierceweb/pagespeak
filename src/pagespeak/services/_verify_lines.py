"""Verify checks `line_coverage` and `line_joins`: the source PDF's body lines.

Both need the build's source map, which says which lines are body text: in
the body band, outside every picture and left-out area, not left-out text.

Coverage walks the PDF in page order with a cursor through the output and
places each line with `_verify_line_place`. Joins take consecutive body lines
in one column and look for the end of one followed by the start of the next:
a miss means a line moved or something was inserted inside a sentence.
"""

from __future__ import annotations

import re
from collections import Counter

from ._pdf_lines import PdfLine, PdfPage
from ._source_map import Box, SourceMap
from ._verify_doc import VerifyDoc
from ._verify_finding import CheckResult, VerifyFinding, finding_key
from ._verify_line_place import OutputWords, tokens

_SENTENCE_END_RE = re.compile(r"[.?!:]\W*$")
_PAGE_REF_RE = re.compile(r",?\s*pp?\.\s*\d+(?:\s*[–-]\s*\d+)?\.?\s*$")
_MIN_WORDS = 5  # shorter lines are too common to place
_CELL_REACH = 200  # output words from the line before within which a row's short cells must stand
_JOIN_MIN_CHARS = 45  # a full-width body line, not a label or a short last line
_COLUMN_STEP = 25.0  # points: lines whose left edges round together share a column


def _inside(line: PdfLine, box: Box) -> bool:
    x = (line.box[0] + line.box[2]) / 2
    y = (line.box[1] + line.box[3]) / 2
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def body_lines(page: PdfPage, smap: SourceMap) -> list[PdfLine]:
    """The page's lines a build is expected to carry as text."""
    holes = [p.box for p in smap.pictures_on(page.number)]
    holes += [lo.box for lo in smap.left_out_on(page.number)]
    return [
        line
        for line in page.lines
        if smap.in_body(line.box[1], line.box[3])
        and not smap.text_left_out(line.text)
        and not any(_inside(line, box) for box in holes)
    ]


def _inner(text: str, hyphenated: bool, skip: int = 0) -> list[str]:
    """A line's words worth placing: the halves of a word a hyphen split at either
    end of the line are left out, as the output joins them; `skip` leading words
    reach the second half (a margin label the reader set before it included)."""
    # A printed page reference ("…, p. 130") has no page to point at in the output.
    words = tokens(_PAGE_REF_RE.sub("", text))
    return words[skip : -1 if hyphenated else None]


def _place_cells(out: OutputWords, line: PdfLine, cursor: int, near: int) -> list[int] | None:
    """Table cells on one baseline, each placed as a line of its own. When every
    cell is too short to place, each must stand whole near where the line before
    went; None when a cell is not there."""
    hits: list[int] = []
    short: list[list[str]] = []
    for k, cell in enumerate(line.cells):
        inner = _inner(cell, line.hyphenated and k == len(line.cells) - 1)
        if len(inner) < _MIN_WORDS:
            short += [inner] if inner else []
            continue
        if (found := out.place(inner, cursor, line.page, near=near, line=line.text)) is None:
            return None
        hits += found
    if hits:
        return hits
    spots = [out.nearby(words, near, _CELL_REACH) for words in short]
    placed = [p for p in spots if p is not None]
    return [min(placed)] if placed and len(placed) == len(spots) else None


def _halves(lines: list[PdfLine]) -> list[str]:
    """The first halves of the words a hyphen splits at the ends of these lines."""
    return [words[-1] for line in lines if line.hyphenated and (words := tokens(line.text))]


def _lost(number: int, text: str) -> VerifyFinding:
    key = finding_key("line_coverage", f"p{number}", text)
    message = f"PDF line not in the output: {text}"
    return VerifyFinding("line_coverage", key, f"PDF p{number}", message)


def _turned(page: PdfPage) -> VerifyFinding:
    key = finding_key("line_coverage", "turned", f"p{page.number}")
    message = (
        f"the page is turned {page.rotation}°: text set to read upright on it "
        "reads as sideways type, which is not checked"
    )
    return VerifyFinding("line_coverage", key, f"PDF p{page.number}", message, False)


def _blank(page: PdfPage) -> VerifyFinding:
    key = finding_key("line_coverage", "blank", f"p{page.number}")
    message = "the page's crop box lies outside its media box, so it shows nothing to check"
    return VerifyFinding("line_coverage", key, f"PDF p{page.number}", message, False)


def check_line_coverage(doc: VerifyDoc, pages: dict[int, PdfPage], smap: SourceMap) -> CheckResult:
    out = OutputWords.of(doc)
    cursor = 0
    halves: list[str] = []
    findings: list[VerifyFinding] = []
    for number in sorted(pages):
        if pages[number].rotation and pages[number].sideways:
            findings.append(_turned(pages[number]))
        left, low, right, high = pages[number].box
        if right <= left or high <= low:
            findings.append(_blank(pages[number]))
        placed: list[int] = []
        lines = body_lines(pages[number], smap)
        # A first or second word that ends a word a hyphen split on this page or the
        # last, as the output joins it; the reader need not set the two lines together.
        open_halves, halves = halves + _halves(lines), _halves(lines)
        for line in lines:
            lead = tokens(line.text)[:2]
            skip = next(
                (k + 1 for k, w in enumerate(lead) if any(h + w in out.at for h in open_halves)), 0
            )
            inner = _inner(line.text, line.hyphenated, skip)
            if len(inner) < _MIN_WORDS:
                continue
            near = placed[-1] if placed else cursor
            hits = out.place(inner, cursor, number, near=near, line=line.text)
            if hits is None and line.cells:
                hits = _place_cells(out, line, cursor, near)
            if hits is None:
                findings.append(_lost(number, line.text))
            elif hits:
                placed.append(sorted(hits)[len(hits) // 2])
        if placed:
            cursor = max(cursor, sorted(placed)[len(placed) // 2])
    reported = {f.key for f in findings}
    for number, text in dict.fromkeys(out.overruled()):
        if (lost := _lost(number, text)).key not in reported:
            findings.append(lost)
    return CheckResult("line_coverage", tuple(findings))


def _body_style(pages: dict[int, PdfPage], smap: SourceMap) -> tuple[str, int] | None:
    """The font and size most body text is set in."""
    weight: Counter[tuple[str, int]] = Counter()
    for page in pages.values():
        for line in body_lines(page, smap):
            weight[(line.font, round(line.size))] += len(line.text)
    return weight.most_common(1)[0][0] if weight else None


def _beside(out: OutputWords, run: list[str], before: list[str], after: list[str]) -> bool:
    """Four words across a join in a row, beside one more word of either line
    (`before` or `after` them): four words alone recur elsewhere in a book."""
    for p in out.where.get(tuple(run), []):
        if (before and p > 0 and out.words[p - 1] == before[0]) or (
            after and out.words[p + 4 : p + 5] == after
        ):
            return True
    return False


def _joined(a: PdfLine, b: PdfLine, out: OutputWords) -> bool:
    ta, tb = tokens(a.text), tokens(b.text)
    if len(ta) < 3 or len(tb) < 3:
        return True
    if a.hyphenated:
        whole = [ta[-2], ta[-1] + tb[0], *tb[1:3]]
        if _beside(out, whole, ta[-3:-2], tb[3:4]):
            return True
        if _beside(out, ta[-3:] + tb[:1], ta[-4:-3], tb[1:2]):  # a real hyphen kept: "well- known"
            return True
    elif _beside(out, ta[-2:] + tb[:2], ta[-3:-2], tb[2:3]):
        return True
    # The two readers spaced a word differently, or split a label from its number.
    return out.holds_letters(ta[-3:] + tb[:3])


def _goes_on(a: PdfLine, body: list[PdfLine], every: list[PdfLine]) -> bool:
    """Whether more of `a`'s row sits to its right, short of its column's right edge."""
    right = max(line.box[2] for line in body if abs(line.box[0] - a.box[0]) <= 20)
    return any(
        c is not a and abs(c.base - a.base) < 1.0 and a.box[2] < c.box[0] < right for c in every
    )


def check_line_joins(doc: VerifyDoc, pages: dict[int, PdfPage], smap: SourceMap) -> CheckResult:
    out = OutputWords.of(doc)
    style = _body_style(pages, smap)
    findings: list[VerifyFinding] = []
    for number in sorted(pages):
        every = body_lines(pages[number], smap)
        body = [
            line
            for line in every
            if (line.font, round(line.size)) == style and len(line.text) > _JOIN_MIN_CHARS
        ]
        body.sort(key=lambda line: (round(line.box[0] / _COLUMN_STEP), -line.base))
        for a, b in zip(body, body[1:], strict=False):
            if abs(a.box[0] - b.box[0]) > 20 or not 0 < a.base - b.base < 1.6 * a.size:
                continue
            if _SENTENCE_END_RE.search(a.text):
                continue  # after a sentence end a float may sit between, or b open a column
            if _goes_on(a, body, every):
                continue  # the row carries on past a gap the reader cut it at (a step-number badge)
            if _joined(a, b, out):
                continue
            key = finding_key("line_joins", f"p{number}", a.text[-40:], b.text[:40])
            message = f"PDF lines not joined in the output: …{a.text[-50:]} | {b.text[:50]}…"
            findings.append(VerifyFinding("line_joins", key, f"PDF p{number}", message))
    return CheckResult("line_joins", tuple(findings))
