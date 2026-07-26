"""Document-relative demotion of integer-prefixed list headings.

A backend (Marker) sometimes promotes a plain-text numbered list item into
a heading. The two passes here decide — per document, from counts, never
from a word/phrase list — whether the document's integer-prefix convention
is "section headings" or "a numbered list", and demote the mis-promoted
heading-form lines only when the convention is list-like.

- ``demote_listish_bare_int_headings`` — bare integers (``# 19 Pair
  remotes`` vs plain ``19 Press and hold``).
- ``demote_listish_dotted_int_headings`` — single-dot integers
  (``#### 1. Click the button.`` vs plain ``1. Click the button.``).

Single-dot only: ``N.M`` / ``N.M.O`` multi-dot prefixes are unambiguously
textbook section headings (depth-locked by
``_cleanup.lock_numbered_section_depth``) and are excluded from both the
count and the demote. Both passes are OUTLINE-SKIPPED by the engine — the
structure-faithful DOCX reader's reconstructed headings are trusted, never
second-guessed (the invariant).
"""

from __future__ import annotations

import re

from ._fences import fence_flags

# Bare-integer-led lines: an integer NOT followed by a dot (so N.M / N.
# multi-dot sections are excluded), then whitespace + text. Heading form
# `# 19 Pair remotes` vs plain form `19 Press and hold`.
_BARE_INT_HEADING_RE = re.compile(r"^(\s*)#{1,6}\s+(\d+(?!\.)\s+\S.*?)\s*$")
_BARE_INT_PLAIN_RE = re.compile(r"^\s*\d+(?!\.)\s+\S")

# Single-dot integer-led lines: `N.` NOT followed by another digit (so
# `N.M` multi-dot sections are excluded), then whitespace + text. Heading
# form `#### 1. Click the button.` vs plain form `1. Click the button.`.
_DOTTED_INT_HEADING_RE = re.compile(r"^(\s*)#{1,6}\s+(\d+\.(?!\d)\s+\S.*?)\s*$")
_DOTTED_INT_PLAIN_RE = re.compile(r"^\s*\d+\.(?!\d)\s+\S")

# A mis-promoted step sits INSIDE its list — a plain `N.` sibling within
# this many lines. A real numbered section is surrounded by body, with the
# doc's plain `N.` lines (a panel legend, steps elsewhere) pages away.
_LIST_CONTEXT_WINDOW = 8

# Trailing markdown link: `[text](url)` — unwrapped before the terminal-
# punctuation test so `3. [Import the files.](#page-...)` reads as `.`.
_TRAILING_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)\s*$")


def _step_punctuated(line: str) -> bool:
    """A `N.` heading whose title ends `.` or `:` is an instruction, not a
    section name."""
    title = line.strip().rstrip("*").strip()
    m = _TRAILING_LINK_RE.search(title)
    if m:
        title = m.group(1).strip()
    return title.endswith((".", ":"))


_ANY_HEADING_LEVEL_RE = re.compile(r"^\s*(#{1,6})\s+\S")


def _owns_children(lines: list[str], idx: int) -> bool:
    """True when the next heading after ``lines[idx]`` is deeper — the
    candidate is a parent, and a mis-promoted step never owns children."""
    m = _ANY_HEADING_LEVEL_RE.match(lines[idx])
    if not m:
        return False
    level = len(m.group(1))
    for ln in lines[idx + 1 :]:
        nxt = _ANY_HEADING_LEVEL_RE.match(ln)
        if nxt:
            return len(nxt.group(1)) > level
    return False


def demote_listish_bare_int_headings(text: str) -> tuple[str, int]:
    """Demote bare-integer headings (`# 19 Pair remotes`) when the doc
    uses bare integers predominantly as a PLAIN-TEXT numbered list
    (procedure steps) — the heading-form ones are a minority mis-promoted
    from the step list.

    Document-relative, language-agnostic (no word/phrase list): count
    bare-integer HEADING lines (H) vs bare-integer PLAIN lines (P). When
    ``P > H`` (and ``H >= 1``) the doc's bare-integer convention is
    "list/steps", so the H heading-form lines are mis-promoted steps →
    demote each to plain text (markers dropped, indent+text kept). When
    bare integers are used CONSISTENTLY as headings (``H >= P`` — a
    paper's ``# 1 Introduction`` … ``# 4 Conclusion``, labels
    ``#### 32 in / 32 out``) it is a no-op: the doc's section convention.
    ``N.M[.K]`` sections are never bare-int (the dot is excluded), so
    real numbered sections are untouched. No-op (``0``) when there are
    no bare-int headings or the doc is heading-dominant.
    """
    lines = text.splitlines()
    _fenced = fence_flags(lines)
    heading_idx = [
        i for i, ln in enumerate(lines) if not _fenced[i] and _BARE_INT_HEADING_RE.match(ln)
    ]
    plain = sum(1 for ln in lines if _BARE_INT_PLAIN_RE.match(ln))
    if not heading_idx or plain <= len(heading_idx):
        return text, 0
    demote = set(heading_idx)
    out = []
    for idx, line in enumerate(lines):
        m = _BARE_INT_HEADING_RE.match(line) if idx in demote else None
        out.append(f"{m.group(1)}{m.group(2)}" if m else line)
    res = "\n".join(out)
    if text.endswith("\n") and not res.endswith("\n"):
        res += "\n"
    return res, len(demote)


def demote_listish_dotted_int_headings(text: str) -> tuple[str, int]:
    """Demote single-dot integer headings (`#### 1. Click the button.`)
    when the doc uses `N.` predominantly as a PLAIN-TEXT numbered list
    (procedure steps) — the heading-form ones are mis-promoted steps.

    The single-dot sibling of ``demote_listish_bare_int_headings`` and
    its exact philosophy: count `N.` HEADING lines (H) vs `N.` PLAIN
    lines (P). When ``P > H`` (and ``H >= 1``) the doc's `N.` convention
    is "list/steps" → demote each heading-form `N.` to plain text
    (markers dropped, indent + the `N. …` text kept, so the surrounding
    list renders). When `N.` is used CONSISTENTLY as headings (``H >= P``
    — a manual's ``#### 1. Connect`` … ``#### 4. Configure`` section
    spine) it is a no-op: that is the doc's section convention.

    Why this and not a per-heading shape rule: a short numbered heading
    ending in a period (`### 1. Open.`) is structurally identical whether
    it is a real section or a step — so it cannot be classified in
    isolation (see ``_heading_sanity`` which deliberately keeps it). The
    document-relative count is the signal that separates them.

    A candidate must ALSO be step-like in itself: either step-punctuated
    (title ends `.` or `:`; `?` excluded so numbered FAQ headings stay) or
    sitting within ``_LIST_CONTEXT_WINDOW`` lines of a plain `N.` sibling.
    An unpunctuated candidate owning a deeper next heading is exempt from
    the proximity trigger — it is a parent. Punctuation outranks that
    exemption, since a mis-promoted step lands at an arbitrary level.

    Multi-dot ``N.M[.O]`` prefixes are excluded (the dot is followed by a
    digit) — those are real numbered sections, depth-locked elsewhere.
    No-op (``0``) when there are no `N.` headings or the doc is
    heading-dominant.
    """
    lines = text.splitlines()
    _fenced = fence_flags(lines)
    heading_idx = [
        i for i, ln in enumerate(lines) if not _fenced[i] and _DOTTED_INT_HEADING_RE.match(ln)
    ]
    plain_idx = [i for i, ln in enumerate(lines) if _DOTTED_INT_PLAIN_RE.match(ln)]
    if not heading_idx or len(plain_idx) <= len(heading_idx):
        return text, 0
    demote = {
        h
        for h in heading_idx
        if _step_punctuated(lines[h])
        or (
            not _owns_children(lines, h)
            and any(abs(p - h) <= _LIST_CONTEXT_WINDOW for p in plain_idx)
        )
    }
    if not demote:
        return text, 0
    out = []
    for idx, line in enumerate(lines):
        m = _DOTTED_INT_HEADING_RE.match(line) if idx in demote else None
        out.append(f"{m.group(1)}{m.group(2)}" if m else line)
    res = "\n".join(out)
    if text.endswith("\n") and not res.endswith("\n"):
        res += "\n"
    return res, len(demote)


__all__ = [
    "demote_listish_bare_int_headings",
    "demote_listish_dotted_int_headings",
]
