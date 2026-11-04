"""Verify checks on the master's shape.

`structure` notes skipped heading levels, headings with no body and no
subheadings, and table rows with more cells than their header (a renderer
drops the extra cells) — quality signals, never a reason to refuse delivery.
`outline` holds the headings against the source PDF's bookmarks.
"""

from __future__ import annotations

import difflib
import re

from ._fences import fence_flags
from ._pdf_lines import OutlineEntry
from ._verify_doc import VerifyDoc, split_frontmatter
from ._verify_finding import CheckResult, VerifyFinding, finding_key
from ._verify_split import title_key

_HEADING_RE = re.compile(r"^(#{1,6})\s+(\S.*?)\s*$")
_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_PIPE_RE = re.compile(r"(?<!\\)\|")
_NON_WORD_RE = re.compile(r"[\W_]+")
_CLOSE = 0.9  # how alike a bookmark and a heading must be once spacing is set aside


def _note(kind: str, text: str, where: str, message: str) -> VerifyFinding:
    return VerifyFinding("structure", finding_key("structure", kind, text), where, message, False)


def _heading_notes(
    lines: list[str], fenced: list[bool], name: str, offset: int
) -> list[VerifyFinding]:
    heads = [
        (i, len(m.group(1)), m.group(2))
        for i, (line, f) in enumerate(zip(lines, fenced, strict=True))
        if not f and (m := _HEADING_RE.match(line))
    ]
    notes: list[VerifyFinding] = []
    for k, (i, level, text) in enumerate(heads):
        where = f"{name}:{offset + i + 1}"
        if k and level > heads[k - 1][1] + 1:
            message = f"H{heads[k - 1][1]} followed by H{level}: {text}"
            notes.append(_note("skip", text, where, message))
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        has_child = k + 1 < len(heads) and heads[k + 1][1] > level
        if not has_child and not any(lines[j].strip() for j in range(i + 1, end)):
            notes.append(
                _note("empty", text, where, f"heading with no body and no subheadings: {text}")
            )
    return notes


def _table_notes(
    lines: list[str], fenced: list[bool], name: str, offset: int
) -> list[VerifyFinding]:
    notes: list[VerifyFinding] = []
    i = 0
    while i < len(lines) - 1:
        if (
            fenced[i]
            or not lines[i].lstrip().startswith("|")
            or not _SEPARATOR_RE.match(lines[i + 1].strip())
        ):
            i += 1
            continue
        width = len(_PIPE_RE.findall(lines[i].strip())) - 1
        j = i + 2
        while j < len(lines) and lines[j].lstrip().startswith("|"):
            cells = len(_PIPE_RE.findall(lines[j].strip())) - 1
            if cells > width:
                row = lines[j].strip()
                message = f"table row has {cells} cells under a {width}-cell header: {row[:160]}"
                notes.append(_note("table", row, f"{name}:{offset + j + 1}", message))
            j += 1
        i = j
    return notes


def check_structure(doc: VerifyDoc) -> CheckResult:
    body, offset = split_frontmatter(doc.master_text)
    lines = body.splitlines()
    fenced = fence_flags(lines)
    name = doc.master.name
    notes = _heading_notes(lines, fenced, name, offset) + _table_notes(lines, fenced, name, offset)
    return CheckResult("structure", tuple(notes))


def _plain(text: str) -> str:
    """A title's letters and digits only: bookmarks run words together ("Frontand")."""
    return _NON_WORD_RE.sub("", title_key(text))


def _matches(key: str, heading: str) -> bool:
    if key == heading or key in heading or (heading in key and len(heading) >= 0.6 * len(key)):
        return True
    close = difflib.SequenceMatcher(None, key, heading, autojunk=False)
    return close.real_quick_ratio() >= _CLOSE and close.ratio() >= _CLOSE


def check_outline(
    doc: VerifyDoc, outline: list[OutlineEntry], *, claimed_pages: set[int] | None
) -> CheckResult:
    """Notes for bookmarks on pages the build read that no heading carries.
    Never blocking: a build may rename a heading on purpose, and lost content is
    line coverage's to find."""
    if not outline:
        return CheckResult("outline", skipped="the source PDF has no bookmark outline")
    body, _ = split_frontmatter(doc.master_text)
    lines = body.splitlines()
    heads = {
        _plain(m.group(2))
        for line, f in zip(lines, fence_flags(lines), strict=True)
        if not f and (m := _HEADING_RE.match(line))
    }
    text = _NON_WORD_RE.sub("", body.casefold())
    findings: list[VerifyFinding] = []
    for entry in outline:
        key = _plain(entry.title)
        if not key or (claimed_pages is not None and entry.page not in claimed_pages):
            continue
        if key in heads or any(_matches(key, h) for h in heads):
            continue
        where = f"PDF p{entry.page}" if entry.page else "PDF outline"
        if key in text:
            message = f"outline entry {entry.title!r} is in the text but not a heading"
            findings.append(_outline_finding("not_heading", entry.title, where, message))
        else:
            message = f"outline entry {entry.title!r} appears nowhere in the output"
            findings.append(_outline_finding("missing", entry.title, where, message))
    return CheckResult("outline", tuple(findings))


def _outline_finding(kind: str, title: str, where: str, message: str) -> VerifyFinding:
    return VerifyFinding("outline", finding_key("outline", kind, title), where, message, False)
