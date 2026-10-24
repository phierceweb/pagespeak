"""Demote the table-of-contents and title-page lines a PDF backend promoted to
headings: TOC entries with a printed page number, the headings before a
book's first chapter, and a detailed TOC's chapter labels.

`cleanup_markdown` + `_cleanup_diagnose` drive these and `_cleanup`
re-exports them. Regex table lives in `_cleanup_regexes.py`.
"""

from __future__ import annotations

import re

from ._cleanup_regexes import (
    _TOC_NUM_PREFIX_RE,
    HEADING_HASH_RE,
    TOC_PAGE_NUM_SUFFIX_RE,
)
from ._fences import fence_flags


def _toc_match_key(content: str) -> str:
    """Normalise a heading's text for TOC-twin comparison: drop the
    trailing page number, a leading section-number prefix, collapse
    whitespace, casefold. Empty result ⇒ no usable key."""
    core = TOC_PAGE_NUM_SUFFIX_RE.sub("", content).strip()
    core = _TOC_NUM_PREFIX_RE.sub("", core)
    return re.sub(r"\s+", " ", core).strip().casefold()


def demote_toc_phantom_headings(text: str) -> tuple[str, int]:
    """Demote TOC entries a PDF backend promoted to headings.

    A front-of-book TOC line styled like a heading (``## 1.1 Introduction to the
    Topic 2``) becomes one, and the splitter writes a section file for it beside
    the real section's. A heading is demoted (``#`` markers dropped, indent and
    text kept) when it ends in a page number of at most four digits and its
    match key (`_toc_match_key`) also belongs to a heading without one, so
    ``## Section 2020`` stays unless a plain ``Section`` heading exists. Fenced
    lines are neither candidates nor twins. Returns ``(text, demoted_count)``.
    """
    lines = text.splitlines()
    fenced = fence_flags(lines)
    clean_keys = _clean_heading_keys(lines, fenced)
    demoted = 0
    out: list[str] = []
    for line, is_fenced in zip(lines, fenced, strict=True):
        content = None if is_fenced else _toc_entry(line)
        if content is None or _toc_match_key(content) not in clean_keys:
            out.append(line)
            continue
        out.append(line[: len(line) - len(line.lstrip())] + content)
        demoted += 1
    result = "\n".join(out)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result, demoted


def _heading_text(line: str) -> str | None:
    m = HEADING_HASH_RE.match(line.strip())
    return m.groups()[1] if m else None


def _toc_entry(line: str) -> str | None:
    """A heading's text when it ends in a page number."""
    content = _heading_text(line)
    return content if content is not None and TOC_PAGE_NUM_SUFFIX_RE.search(content) else None


def _clean_heading_keys(lines: list[str], fenced: list[bool]) -> set[str]:
    """Match keys of the headings with no page number: the twins a TOC entry needs."""
    keys = {
        _toc_match_key(content)
        for line, is_fenced in zip(lines, fenced, strict=True)
        if not is_fenced
        and (content := _heading_text(line)) is not None
        and not TOC_PAGE_NUM_SUFFIX_RE.search(content)
    }
    keys.discard("")
    return keys


# Front-matter demote tuning. A book = several H1 chapters; the front
# matter (title page, copyright/credits, TOC) is always a minority of the
# document's headings.
_FRONT_MATTER_MIN_H1 = 3
_FRONT_MATTER_MAX_FRACTION = 0.30


def demote_front_matter_headings(text: str) -> tuple[str, int]:
    """Demote the headings that precede the first chapter of a book.

    A PDF textbook's title page, copyright page and table of contents sit
    before the first chapter, and Marker promotes their lines (title, author,
    copyright and TOC lines) to headings the splitter emits as junk sections.
    The first H1 is taken as the first chapter; every heading before it loses
    its ``#`` markers, its text kept. It applies only to a book: at least
    ``_FRONT_MATTER_MIN_H1`` H1s, with the headings before the first H1 fewer
    than ``_FRONT_MATTER_MAX_FRACTION`` of all headings. Returns
    ``(text, demoted_count)``.
    """
    lines = text.splitlines()
    _fenced = fence_flags(lines)
    heading_idxs: list[int] = []
    h1_idxs: list[int] = []
    for i, line in enumerate(lines):
        m = None if _fenced[i] else HEADING_HASH_RE.match(line.strip())
        if not m:
            continue
        heading_idxs.append(i)
        if len(m.group(1)) == 1:
            h1_idxs.append(i)

    if len(h1_idxs) < _FRONT_MATTER_MIN_H1:
        return text, 0
    first_h1 = h1_idxs[0]
    pre = [i for i in heading_idxs if i < first_h1]
    if not pre:
        return text, 0
    if len(pre) >= len(heading_idxs) * _FRONT_MATTER_MAX_FRACTION:
        return text, 0

    out = list(lines)
    demoted = 0
    for i in pre:
        m = re.match(r"^(\s*)#{1,6}\s+(.*)$", lines[i])
        if m:
            out[i] = f"{m.group(1)}{m.group(2)}"
            demoted += 1
    result = "\n".join(out)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result, demoted


# TOC-outline demote tuning. A detailed table of contents lists each chapter
# heading above a run of `- N.N <title> <page>` section lines; a real chapter
# heading sits above prose. Two such lines is enough signal to call it a TOC.
_TOC_OUTLINE_LINE_RE = re.compile(r"^\s*-\s+\d+\.\d+[a-z]?\s+\S.*?\d{1,4}\s*$")
_TOC_OUTLINE_MIN_LINES = 2


def demote_toc_outline_headings(text: str) -> tuple[str, int]:
    """Demote a book's detailed-table-of-contents chapter headings.

    A detailed Contents lists each chapter as a heading (``# Chapter 1``) above
    its section lines (``- 1.1 Introduction to the Topic 2``: number, title,
    page). A heading is demoted (``#`` dropped, text kept) when its body holds at
    least ``_TOC_OUTLINE_MIN_LINES`` such lines; a real chapter sits above prose
    and is never touched. Books only (``>= _FRONT_MATTER_MIN_H1`` H1s). Returns
    ``(text, demoted_count)``.
    """
    lines = text.splitlines()
    _fenced = fence_flags(lines)
    heading_idxs: list[int] = []
    h1_count = 0
    for i, line in enumerate(lines):
        m = None if _fenced[i] else HEADING_HASH_RE.match(line.strip())
        if m:
            heading_idxs.append(i)
            if len(m.group(1)) == 1:
                h1_count += 1

    if h1_count < _FRONT_MATTER_MIN_H1:
        return text, 0

    demote: set[int] = set()
    for k, i in enumerate(heading_idxs):
        nxt = heading_idxs[k + 1] if k + 1 < len(heading_idxs) else len(lines)
        toc_lines = sum(1 for j in range(i + 1, nxt) if _TOC_OUTLINE_LINE_RE.match(lines[j]))
        if toc_lines >= _TOC_OUTLINE_MIN_LINES:
            demote.add(i)

    if not demote:
        return text, 0

    out = list(lines)
    for i in demote:
        m = re.match(r"^(\s*)#{1,6}\s+(.*)$", lines[i])
        if m:
            out[i] = f"{m.group(1)}{m.group(2)}"
    result = "\n".join(out)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result, len(demote)
