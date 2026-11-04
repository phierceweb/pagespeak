"""Verify check `printed_titles`: figure and table titles printed in the source PDF.

Each title must reach the output, start no more output lines than PDF lines,
sit in page order, and (a figure's) have a picture near it. A title is a line
starting a capitalised `Figure`/`Fig.`/`Table` and a number that goes on as a
caption does: line end, punctuation, or a capitalised word. `Figure 6.9 shows`,
`figure 3.2b).` and `Figure 4.1a–c,` are references wrapped to a line start;
a `(continued)` title repeats one already counted. Alt text never counts as
the title arriving: after vision it is a generated caption, which names the
title whether or not the printed one survived. Nor does a reference in the
text ("shown in Figure 2.1"): a label away from a line start counts only when
the printed title's first words follow it (a title of one or two words ending
there), or the PDF prints the label bare. A label written as a link counts as
its text. A list of figures or tables carries no title, in the PDF or the output.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Callable
from dataclasses import dataclass

from ._fences import fence_flags, fenced_blocks
from ._image_refs import replace_image_refs
from ._pdf_lines import PdfLine, PdfPage
from ._verify_doc import VerifyDoc, split_frontmatter
from ._verify_finding import CheckResult, VerifyFinding, finding_key

_LABEL_RE = re.compile(r"(figure|fig\.|table)\s+(\d+(?:[.\-–]\d+)*[a-z]?)\b", re.IGNORECASE)
_LEADER_RE = re.compile(r"(?:\. ?){4,}|…{2,}")  # a list-of-figures entry
_MD_PREFIX_RE = re.compile(r"^(?:[\s>#*_|+-]|<[^>]*>)*")
_CONTINUED_RE = re.compile(r"\(\s*continued\s*\)|\bcontinued\W*$", re.IGNORECASE)
_SPACED_DASH_RE = re.compile(r"^\s+[–-]\s+")  # "Figure 1.1 – The tower"; "4.1a–c" is a range
_PICTURE_REACH = 20  # non-blank output lines between a figure's caption and its picture
_LEAD_WORDS = 3  # of a title's words, those that must follow its label away from a line start
_WORD_RE = re.compile(r"[^\W_]+")
_PAGE_AT_END_RE = re.compile(r"[\s|]\s*\d{1,4}[\s|*_]*$")
_LETTER_RE = re.compile(r"[^\W\d_]")
_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\([^)]*\)")
_TITLE_END = ".:;)|*_"  # what may follow a short title's last word where it arrives mid-line


@dataclass
class _Printed:
    page: int
    lines: int
    worded: bool = False  # the title line carries words past the label
    lead: tuple[str, ...] = ()  # the title's first words after the label


def _lead(text: str) -> tuple[str, ...]:
    return tuple(w.casefold() for w in _WORD_RE.findall(text)[:_LEAD_WORDS])


def _follows(rest: str, want: tuple[str, ...]) -> bool:
    """`rest`, the text after a label, opens with the printed title's first
    words; a title shorter than `_LEAD_WORDS` must also end there, or prose
    naming it ("Table 3 results show") would pass for its caption."""
    words = list(_WORD_RE.finditer(rest))[: len(want)]
    if tuple(w.group().casefold() for w in words) != want:
        return False
    if not want or len(want) >= _LEAD_WORDS:
        return True
    tail = rest[words[-1].end() :].lstrip()
    return not tail or tail[0] in _TITLE_END


def _title(text: str, *, anywhere: bool = False) -> tuple[str, str] | None:
    """`Figure 6.9` and the words after it, when `text` opens with a caption-shaped title."""
    match = _LABEL_RE.match(text.strip())
    if match is None or _LEADER_RE.search(text):
        return None
    rest = _SPACED_DASH_RE.sub("", text.strip()[match.end() :], count=1).lstrip(" .:|*_")
    if not anywhere and (
        match.group(1)[0].islower()
        or (rest and (rest[0].islower() or rest[0] in ",;)]–-/"))
        or _CONTINUED_RE.search(rest)
    ):
        return None
    kind = "Table" if match.group(1).lower() == "table" else "Figure"
    return f"{kind} {match.group(2).replace('–', '-')}", rest


def _label(text: str, *, anywhere: bool = False) -> str | None:
    title = _title(text, anywhere=anywhere)
    return None if title is None else title[0]


def _list_entry(text: str) -> str | None:
    """How a line reads as a list-of-figures or -tables entry: "set" with dot
    leaders or a page-number cell, "bare" when the words after its label end in
    a bare number, else None."""
    label = _LABEL_RE.search(text)
    if label is None:
        return None
    if _LEADER_RE.search(text):
        return "set"
    rest = text[label.end() :]
    page = _PAGE_AT_END_RE.search(rest)
    if page is None or _LETTER_RE.search(rest, 0, page.start()) is None:
        return None
    return "set" if page.group().startswith("|") else "bare"


def _list_lines(texts: list[str | None]) -> tuple[set[int], list[int]]:
    """Indexes of list entries, and of lines ending in a bare number with no entry
    beside them: a caption ending in a year or a count, or a one-entry list."""
    shown = [(i, text) for i, text in enumerate(texts) if text is not None and text.strip()]
    kinds = [_list_entry(text) for _, text in shown]
    listed: set[int] = set()
    alone: list[int] = []
    for k, (i, _) in enumerate(shown):
        beside = any(kinds[j] is not None for j in (k - 1, k + 1) if 0 <= j < len(kinds))
        if kinds[k] == "set" or (kinds[k] == "bare" and beside):
            listed.add(i)
        elif kinds[k] == "bare":
            alone.append(i)
    return listed, alone


def _pdf_titles(pages: dict[int, PdfPage], keep: Callable[[PdfLine], bool]) -> dict[str, _Printed]:
    """A title line ending in a bare number is a list entry when the title is
    printed elsewhere without it, else a caption ending in a number."""
    titles: dict[str, _Printed] = {}
    bare: dict[str, _Printed] = {}
    for number in sorted(pages):
        for line in pages[number].lines:
            if not keep(line) or (title := _title(line.text)) is None:
                continue
            shape = _list_entry(" | ".join(line.cells) if len(line.cells) > 1 else line.text)
            if shape == "set":
                continue
            label, rest = title
            into = bare if shape == "bare" else titles
            seen = into.setdefault(label, _Printed(number, 0, lead=_lead(rest)))
            seen.lines += 1
            seen.worded |= len(line.text.split()) > 2
    return dict(sorted({**bare, **titles}.items(), key=lambda item: item[1].page))


@dataclass
class _Output:
    starts: dict[str, list[int]]  # label → output lines it starts (1-based)
    mentions: dict[str, list[tuple[str, int]]]  # label → the text after it and its line
    pictures: list[int]  # lines holding an image
    nonblank: list[int]  # every line with text, to measure distance by

    def arrived_at(self, label: str, printed: _Printed) -> int | None:
        """The first output line the title arrives on, or None. A label printed
        bare leaves no words to look for: any mention of it counts."""
        if starts := self.starts.get(label):
            return starts[0]
        lines = (
            line for rest, line in self.mentions.get(label, []) if _follows(rest, printed.lead)
        )
        return next(lines, None)

    def near_picture(self, line: int) -> bool:
        at = bisect.bisect_left(self.nonblank, line)
        first = self.nonblank[max(0, at - _PICTURE_REACH)]
        last = self.nonblank[min(len(self.nonblank) - 1, at + _PICTURE_REACH)]
        k = bisect.bisect_left(self.pictures, first)
        return k < len(self.pictures) and self.pictures[k] <= last


def _scan_output(doc: VerifyDoc) -> _Output:
    body, offset = split_frontmatter(doc.master_text)
    lines = body.splitlines()
    out = _Output({}, {}, [], [offset + i + 1 for i, line in enumerate(lines) if line.strip()])
    for block in fenced_blocks(lines):  # a diagram's Mermaid transcription stands with its picture
        if block.info.lower().startswith("mermaid"):
            end = len(lines) - 1 if block.end is None else block.end
            out.pictures += range(offset + block.start + 1, offset + end + 2)
    read: list[tuple[str, bool] | None] = []
    for line, fenced in zip(lines, fence_flags(lines), strict=True):
        if fenced:
            read.append(None)
            continue
        text, refs = replace_image_refs(line, lambda _ref: " ")
        read.append((_LINK_RE.sub(r"\1", text), bool(refs)))
    listed, alone = _list_lines([None if entry is None else entry[0] for entry in read])
    for i, entry in enumerate(read):
        if entry is None:
            continue
        text, picture = entry
        number = offset + i + 1
        if picture:
            out.pictures.append(number)
        if i in listed:
            continue  # a list of figures names titles; it does not carry them
        if (label := _label(_MD_PREFIX_RE.sub("", text))) is not None:
            out.starts.setdefault(label, []).append(number)
        for match in _LABEL_RE.finditer(text):
            if (found := _label(match.group(0), anywhere=True)) is not None:
                out.mentions.setdefault(found, []).append((text[match.end() :], number))
    for i in alone:  # a one-entry list: its title starts another line too
        number, entry = offset + i + 1, read[i]
        label = None if entry is None else _label(_MD_PREFIX_RE.sub("", entry[0]))
        if label is not None and any(line != number for line in out.starts.get(label, [])):
            _forget(out, number)
    out.pictures.sort()
    return out


def _forget(out: _Output, number: int) -> None:
    """Drop what output line `number` contributed: it lists a title, not carries it."""
    out.starts = {k: [n for n in v if n != number] for k, v in out.starts.items()}
    out.starts = {k: v for k, v in out.starts.items() if v}
    out.mentions = {k: [m for m in v if m[1] != number] for k, v in out.mentions.items()}


def _in_order(pages: list[int]) -> set[int]:
    """Indexes of a longest run of `pages` that never goes backwards."""
    tails: list[int] = []
    tail_at: list[int] = []
    parent = [-1] * len(pages)
    for i, page in enumerate(pages):
        k = bisect.bisect_right(tails, page)
        if k == len(tails):
            tails.append(page)
            tail_at.append(i)
        else:
            tails[k], tail_at[k] = page, i
        parent[i] = tail_at[k - 1] if k else -1
    kept: set[int] = set()
    i = tail_at[-1] if tail_at else -1
    while i != -1:
        kept.add(i)
        i = parent[i]
    return kept


def _misplaced(order: list[tuple[int, int, str]]) -> list[str]:
    """Labels whose page is more than one page off the run around them."""
    pages = [page for _, page, _ in order]
    kept = sorted(_in_order(pages))
    out: list[str] = []
    for i, (_, page, label) in enumerate(order):
        if i in kept:
            continue
        k = bisect.bisect_left(kept, i)
        before = pages[kept[k - 1]] if k else None
        after = pages[kept[k]] if k < len(kept) else None
        if (before is not None and page < before - 1) or (after is not None and page > after + 1):
            out.append(label)
    return out


def _finding(
    kind: str, label: str, where: str, message: str, blocking: bool = True
) -> VerifyFinding:
    key = finding_key("printed_titles", kind, label)
    return VerifyFinding("printed_titles", key, where, message, blocking)


def check_printed_titles(
    doc: VerifyDoc,
    pages: dict[int, PdfPage],
    *,
    keep: Callable[[PdfLine], bool],
    strict: bool = True,
) -> CheckResult:
    """`keep` drops lines that are not body text (running heads, left-out art).
    Without `strict` (no source map to place the pictures), a bare missing label
    is a note: it may be printed inside the art a converter cropped whole."""
    printed = _pdf_titles(pages, keep)
    out = _scan_output(doc)
    name = doc.master.name
    findings: list[VerifyFinding] = []
    for label, seen in printed.items():
        starts = out.starts.get(label, [])
        line = out.arrived_at(label, seen)
        if line is None:
            message = (
                f"{label} is printed on PDF page {seen.page} but appears nowhere in the output"
            )
            blocking = strict or seen.worded
            findings.append(_finding("missing", label, f"PDF p{seen.page}", message, blocking))
        if len(starts) > seen.lines:
            message = f"{label} starts {len(starts)} output lines, {seen.lines} in the PDF"
            findings.append(_finding("repeated", label, f"{name}:{starts[1]}", message))
        # A bare label named mid-line is a cross-reference, not the caption.
        caption = line if starts or seen.lead else None
        if label.startswith("Figure") and caption is not None and not out.near_picture(caption):
            message = f"no picture within {_PICTURE_REACH} lines of {label}'s caption"
            findings.append(_finding("picture", label, f"{name}:{caption}", message))
    order = sorted(
        (starts[0], printed[label].page, label)
        for label, starts in out.starts.items()
        if label in printed
    )
    for label in _misplaced(order):
        line = out.starts[label][0]
        message = f"{label} (PDF page {printed[label].page}) sits among titles from other pages"
        findings.append(_finding("order", label, f"{name}:{line}", message))
    return CheckResult("printed_titles", tuple(findings))
