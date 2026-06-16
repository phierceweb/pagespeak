"""Deterministic heuristic heading-level assignment + the structural filter.

Numbering-based shape rules — `Chapter N` → L1, `N.M` → L2, `N.M.O` → L3 — the
free/fast/no-LLM normalize path, plus `_select_structural_headings` (which
headings the LLM prompt sees). `_heading_normalize.py` re-exports
`_select_structural_headings` for `_normalize_decision`. Helpers only
duck-type `_HeadingRecord` (read `.text`/`.level`/`.clean_text`), so it's
imported under TYPE_CHECKING only — no import cycle.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._heading_normalize import _HeadingRecord


_CHAPTER_PREFIX_RE = re.compile(r"^Chapter\s+\d+\b", re.IGNORECASE)

_NUMBERED_SECTION_RE = re.compile(r"^\d+(?:\.\d+)+\b")

_PAGE_SUFFIX_RE = re.compile(r"\bp\.\s*\d+\s*$", re.IGNORECASE)

_TRAILING_PAGE_NUMBER_RE = re.compile(r"\b\d{2,}\s*$")


def _is_structural_heading(text: str) -> bool:
    """Heuristic: is this heading a chapter or numbered subsection that
    deserves to be in the LLM prompt?

    Filtered OUT:
    - `<title>, p. 32` (front-matter TOC entry)
    - `Chapter 1 Introduction 31` / `1.1 Foo 32` (trailing standalone
      page number after a real title — TOC entry)
    - `# 1. Cyclic changes in activity. Each month...` (quiz-answer
      sentence-headings — `# N. <sentence>` pattern, no nested numbering)
    - Anything else without a Chapter or numbered prefix

    Filtered IN:
    - `Chapter N` and `Chapter N <title>` (Marker promotes the chapter
      heading; the trailing-page-number filter only fires when there's
      a *title* between the chapter number and the page number, so
      `Chapter 14` (no title) is correctly kept).
    - `1.1 Foo`, `1.1.2 Bar`, `2.5.7 Baz` (any multi-part numbered)
    """
    text = text.strip()
    if _PAGE_SUFFIX_RE.search(text):
        return False
    chap = _CHAPTER_PREFIX_RE.match(text)
    if chap:
        rest = text[chap.end() :].strip()
        return not (rest and _TRAILING_PAGE_NUMBER_RE.search(rest))
    num = _NUMBERED_SECTION_RE.match(text)
    if num:
        rest = text[num.end() :].strip()
        return not (rest and _TRAILING_PAGE_NUMBER_RE.search(rest))
    return False


def _select_structural_headings(
    headings: list[_HeadingRecord],
) -> list[_HeadingRecord]:
    # use clean_text so the Chapter / N.M regex patterns see the
    # actual heading content, not Marker's TOC-link wrapping. Without
    # cleaning, a heading like `<[span id="page-26-0"></span>**Chapter 5](#page-26-0) Chemical Messengers`
    # never matched the `^Chapter \d+` pattern and got incorrectly dropped
    # from the structural-filter set.
    return [h for h in headings if _is_structural_heading(h.clean_text)]


def _heuristic_levels(headings: list[_HeadingRecord]) -> dict[int, int]:
    """Assign heading levels using numbering-based shape rules. Free, fast,
    deterministic. Returns `{1-based-idx: new_level}` for every heading
    whose new level differs from `current_level` (matches the LLM-path
    convention so `_apply_levels` skips no-op rewrites cleanly).

    Rules (in priority order):

    1. **Chapter detection.** Lines matching `_CHAPTER_PREFIX_RE`
       (`Chapter <N> <title>`) → level 1. A flattened extraction:
       `#### Chapter 1 Introduction` becomes `# Chapter 1 Introduction`.
    2. **Numbered subsection depth = dot count.** Multi-part numbered
       headings (`N.M`, `N.M.O`, ...) get level = `dots + 1`, capped at
       6. So `1.1` → L2, `1.1.1` → L3, `1.1.1.1` → L4, etc.
    3. **Bare numbered chapter** (`<N>. Title` with no further dots)
       → level 1. Some textbooks emit chapters as `1. Introduction`
       rather than `Chapter 1 Introduction`; treat both shapes the same.
    4. Anything that filters through but matches none of the above — leave
       at its current level (no rewrite emitted).

    Out of scope: backmatter (References / Index / Bibliography),
    frontmatter (Preface / Foreword), unnumbered semantic headings inside
    a numbered section. Rarely needed in practice; LLM mode handles
    them when invoked explicitly.
    """
    levels: dict[int, int] = {}
    for idx, h in enumerate(headings, start=1):
        new_level = _heuristic_level_for(h.text)
        if new_level is None:
            continue
        if new_level != h.level:
            levels[idx] = new_level
    return levels


def _heuristic_level_for(text: str) -> int | None:
    """Return the heuristic-assigned level for a single heading text, or
    `None` if no rule fires. Pure / no I/O — pulled out so tests can pin
    individual rules without constructing `_HeadingRecord` objects."""
    text = text.strip()
    # Rule 1: `Chapter N <title>` → L1
    if _CHAPTER_PREFIX_RE.match(text):
        return 1
    # Rule 2: multi-part numbered (1.1, 1.1.1, ...) → L = dots + 1
    multi = _NUMBERED_SECTION_RE.match(text)
    if multi:
        # multi.group() is the numeric prefix, e.g. "1.1" or "1.1.1"
        dots = multi.group().count(".")
        return min(dots + 1, 6)
    # Rule 3: bare numbered chapter (`1. <title>` with no further dots)
    bare = _BARE_NUMBERED_CHAPTER_RE.match(text)
    if bare:
        return 1
    return None


_BARE_NUMBERED_CHAPTER_RE = re.compile(r"^\d+\.\s+\S")
