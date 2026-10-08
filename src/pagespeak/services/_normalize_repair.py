"""Post-LLM heading-hierarchy repair: detect→correct, $0, deterministic.

The `repair` stage runs AFTER heading-normalize (on the frozen
`normalized.md`) and BEFORE vision/split. The LLM leveling pass is
necessary for a flattened hierarchy but inconsistent + paid; this engine
repairs its residual slips with deterministic, surgical passes — never
re-paying the LLM for what a rule can fix.

Mirrors `_cleanup_diagnose`: each pass is ``str -> (rewritten_text,
count)``, conservative, and a no-op (``count 0``) when its defect pattern
is absent. General + structural — keys on heading shape, not content
phrase lists. The heading hierarchy IS the relationship structure the
splitter renders as per-section breadcrumbs, so repairing it is what makes
the RAG sections self-contained yet connected.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from pf_core.log import get_logger

from ._cleanup_diagnose import (
    lock_lettered_subsection_runs_pass,
    lock_numbered_section_depth_pass,
)
from ._fences import apply_outside_fences, fence_flags

logger = get_logger(__name__)

_HEADING_RE = re.compile(r"^(\s*)(#{1,6})\s+(\S.*?)\s*$")
_NUMBER_ONLY_RE = re.compile(r"^\d+$")
_DOUBLED_RE = re.compile(r"^(.+?)\s+\1$")
_SPAN_TAG_RE = re.compile(r"</?span[^>]*>")
# A single repeated word this long is implausible as a real name.
_DOUBLING_MIN_CHARS = 8

# A bare 4-digit heading in this range reads as a year, not a page number.
_YEAR_MIN, _YEAR_MAX = 1000, 2999

# A spaced formula has the same token shape as letter-spaced display text;
# an operator is what tells them apart.
_MATH_TOKENS = frozenset("=+-*/^<>()[]{}|~%") | {"==", "<=", ">=", "!=", "→", "×", "÷", "±"}


def _is_plausible_year(text: str) -> bool:
    """A 4-digit value in a range a document would title a section with."""
    s = text.strip()
    return len(s) == 4 and s.isdigit() and _YEAR_MIN <= int(s) <= _YEAR_MAX


def demote_number_only_headings(text: str) -> tuple[str, int]:
    """Demote a heading whose text is a bare integer (``# 780``) to body.

    These are page numbers a backend (Marker) promoted and the LLM left as
    headings; split otherwise turns each into a meaningless one-line
    section. Numbered SECTIONS (``# 12.1 Foo``, ``# 1.``) are not bare
    integers, so they are kept, and so is a plausible YEAR — a timeline,
    history or annual-report section is legitimately titled ``# 1984``, and
    demoting every one collapses the document into a single section at
    split. Demote = drop the ``#`` markers, keep indent + text (faithful,
    nothing deleted). No-op (``0``) when absent.
    """

    def _demote(line: str) -> str:
        m = _HEADING_RE.match(line)
        if m and _NUMBER_ONLY_RE.match(m.group(3)) and not _is_plausible_year(m.group(3)):
            logger.debug("repair_demote_number_only %r", line)
            return f"{m.group(1)}{m.group(3)}"
        return line

    return apply_outside_fences(text, _demote)


def _is_doubling_artifact(phrase: str) -> bool:
    """A repeated phrase is an extraction artifact, not a reduplicated name.

    `Bora Bora` / `Duran Duran` / `Pago Pago` are single short words repeated —
    real names. An artifact repeats a whole heading, which is multi-word or
    substantially longer.
    """
    p = phrase.strip()
    if len(p) < 2:
        return False
    return len(p.split()) >= 2 or len(p) >= _DOUBLING_MIN_CHARS


def dedupe_doubled_heading_text(text: str) -> tuple[str, int]:
    """Collapse a heading whose text is a phrase repeated twice
    (``## Chapter Summary Chapter Summary`` → ``## Chapter Summary``).

    A Marker/extraction artifact where the heading text is emitted twice.
    Detect = the text is exactly ``P <ws> P`` for a phrase ``P``. A single
    short word is NOT an artifact — ``Bora Bora``, ``Duran Duran``,
    ``Walla Walla`` are real names — so ``P`` must be multi-word or long
    enough that a genuine reduplicated name is implausible. Odd repetitions
    and distinct halves are left alone; one copy is kept at the original
    level. No-op (``0``) when absent.
    """

    def _dedupe(line: str) -> str:
        m = _HEADING_RE.match(line)
        if m:
            d = _DOUBLED_RE.match(m.group(3))
            if d and _is_doubling_artifact(d.group(1)):
                logger.debug("repair_dedupe_doubled %r -> %r", line, d.group(1))
                return f"{m.group(1)}{m.group(2)} {d.group(1)}"
        return line

    return apply_outside_fences(text, _dedupe)


def demote_spaced_letter_headings(text: str) -> tuple[str, int]:
    """Demote a heading whose text is letter-spaced
    (``# S K E L E T A L S Y S T E M``) to body — a decorative divider
    artifact, never a real section.

    Detect = many single-character space-separated tokens (>= 4 and >= 60%
    of tokens), the signature of letter-spaced display text. The singles
    must be LETTERS, and a math operator anywhere vetoes the match — a
    spaced formula (``## f ( x ) = 3 x``) has the same token shape but is
    a real heading. De-spacing can't recover word boundaries (uniform
    spaces), so the faithful fix is to demote (markers dropped, text kept
    verbatim). No-op (``0``) absent.
    """

    def _demote(line: str) -> str:
        m = _HEADING_RE.match(line)
        if m:
            tokens = m.group(3).split()
            singles = sum(1 for t in tokens if len(t) == 1 and t.isalpha())
            has_math = any(t in _MATH_TOKENS for t in tokens)
            if not has_math and singles >= 4 and singles / len(tokens) >= 0.6:
                return f"{m.group(1)}{m.group(3)}"
        return line

    return apply_outside_fences(text, _demote)


def strip_heading_spans(text: str) -> tuple[str, int]:
    """Strip leftover page-anchor span tags from heading TEXT
    (``# <span id="page-31-0"></span>Introduction`` → ``# Introduction``).

    A Marker/PDF artifact the LLM leaves in heading titles, polluting the
    section title / filename / breadcrumb. Only heading lines are cleaned;
    body spans are left intact (they are cross-reference link targets). The
    glued chapter-number artifact (``1Introduction``) is a separate,
    layout-driven issue and is left verbatim. A heading that is *only* a
    span is left unchanged (never produce an empty heading). No-op (``0``)
    when absent.
    """

    def _strip(line: str) -> str:
        m = _HEADING_RE.match(line)
        if m:
            cleaned = _SPAN_TAG_RE.sub("", m.group(3)).strip()
            if cleaned and cleaned != m.group(3):
                return f"{m.group(1)}{m.group(2)} {cleaned}"
        return line

    return apply_outside_fences(text, _strip)


def close_heading_level_gaps(text: str) -> tuple[str, int]:
    """Promote orphan over-deep headings so no heading is more than one level
    below its parent (``## Topic`` → ``#### Task`` with no ``###`` becomes
    ``## Topic`` → ``### Task``).

    The LLM heading-normalize leaves *level-skips* — a heading that jumps >1
    level below the previous — which is malformed nesting that pollutes the
    splitter's section-depth breadcrumbs. This walks the implied outline tree
    and clamps each heading to at most ``parent_output + 1``, cascading the
    shift through the subtree and keeping siblings consistent.

    Conservative by construction: the shallowest/baseline heading keeps its
    level (it is NOT forced to H1), an already-contiguous hierarchy is a no-op,
    and the pass is idempotent. Headings inside fenced code blocks are ignored.
    No-op (``0``) when there are no gaps.
    """
    out: list[str] = []
    n = 0
    stack: list[tuple[int, int]] = []  # (raw_level, output_level) of ancestors
    lines = text.splitlines()
    for line, is_fenced in zip(lines, fence_flags(lines), strict=True):
        m = None if is_fenced else _HEADING_RE.match(line)
        if m:
            raw = len(m.group(2))
            while stack and stack[-1][0] >= raw:
                stack.pop()
            new = min(raw, stack[-1][1] + 1) if stack else raw
            stack.append((raw, new))
            if new != raw:
                out.append(f"{m.group(1)}{'#' * new} {m.group(3)}")
                n += 1
                continue
        out.append(line)
    res = "\n".join(out)
    if text.endswith("\n") and not res.endswith("\n"):
        res += "\n"
    return res, n


# Backend-artifact passes — skipped on structure-faithful reader output
# (the invariant: reconstructed outline headings are trusted, never
# second-guessed). Order: span-strip first (cleans titles), then the demotes.
_ARTIFACT_PASSES: tuple[tuple[str, Callable[[str], tuple[str, int]]], ...] = (
    ("repair_stripped_heading_spans", strip_heading_spans),
    ("repair_demoted_number_only_headings", demote_number_only_headings),
    ("repair_deduped_doubled_heading_text", dedupe_doubled_heading_text),
    ("repair_demoted_spaced_letter_headings", demote_spaced_letter_headings),
)


def repair_headings(
    text: str, *, is_outline_doc: bool = False, authored_headings: bool = False
) -> tuple[str, dict[str, int]]:
    """Detect→correct repair of post-LLM heading slips, on ``normalized.md``.

    Mirrors ``_cleanup_diagnose.apply_heading_demotions`` but runs AFTER the
    heading-normalize LLM, repairing the residual slips it introduces or
    leaves. $0, deterministic, never calls the LLM.

    1. **numbered-depth lock** (reused from cleanup) — the ``N.M`` dot-count
       depth rule. Normalizes the inconsistent levels the LLM leaves on
       numbered sections; skipped on ``authored_headings`` (an HTML page's
       levels are the author's).
    2. **backend-artifact passes** — span-strip, number-only demote,
       doubled-text dedupe, spaced-letter demote. Skipped on outline docs
       (structure-faithful reader output is trusted, never second-guessed).
    3. **level-gap close** — promote orphan over-deep headings so no level is
       skipped. Also skipped on outline docs (a Word author's intentional
       skip is sacrosanct); on PDF/LLM output it closes the gaps the LLM left.

    Returns ``(rewritten_text, per-pass counts)``. Every pass is a no-op when
    its pattern is absent (a clean doc → all-zero, output unchanged).
    """
    counts: dict[str, int] = {}
    if not authored_headings:
        text, n = lock_numbered_section_depth_pass(text)
        counts["repair_locked_numbered_section_depth"] = n
        text, n = lock_lettered_subsection_runs_pass(text)
        counts["repair_locked_lettered_subsection_runs"] = n
    if not is_outline_doc:
        for event, fn in _ARTIFACT_PASSES:
            text, n = fn(text)
            counts[event] = n
        text, n = close_heading_level_gaps(text)
        counts["repair_closed_heading_level_gaps"] = n
    return text, counts


__all__ = [
    "close_heading_level_gaps",
    "dedupe_doubled_heading_text",
    "demote_number_only_headings",
    "demote_spaced_letter_headings",
    "repair_headings",
    "strip_heading_spans",
]
