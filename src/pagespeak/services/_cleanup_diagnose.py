"""Detect→correct dispatch for whole-document heading cleanup.

Instead of ``cleanup_markdown`` hard-coding an unconditional sequence of demote
passes ("brute force down a single path"), the assembled document is
run through an ordered **registry** of named passes. Each pass is
itself diagnosis-driven: it scans the whole text, acts only on its own
specific defect pattern, and returns the text unchanged with count 0
when that pattern is absent — a no-op by its own diagnosis.

Adding a new whole-document cleanup defect = register one pass here;
``cleanup_markdown`` does not change. The pass functions live in
``_cleanup`` and are reused verbatim as the mechanical fixers; this
module owns only the ordered registry and the apply loop.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from ._cleanup import (
    demote_front_matter_headings,
    demote_recurring_scaffold_headings,
    demote_toc_outline_headings,
    demote_toc_phantom_headings,
    lock_numbered_section_depth,
    strip_emphasis_from_heading,
)
from ._fragments import demote_orphan_fragments
from ._heading_sanity import demote_prose_heading
from ._listish_headings import (
    demote_listish_bare_int_headings,
    demote_listish_dotted_int_headings,
)

_HEADING_RE = re.compile(r"^(\s*)(#{1,6})\s+(\S.*?)\s*$")


def demote_empty_shell_headings(text: str) -> tuple[str, int]:
    """Demote a bodyless heading immediately followed by another heading
    at the SAME or a SHALLOWER level — a redundant shell.

    A general, language-agnostic pass. Pattern:
    a backend (typically Marker) promotes a running-header / number-only
    line into a heading sitting directly above the section's real title,
    with nothing between them — at the same level::

        # Chapter 1                       <- shell (page header)
        # Getting Started with the Tool   <- the real chapter title

    or at a deeper level than the title (Marker sized the shell's font
    smaller than the title's)::

        #### Chapter 10                   <- shell
        # Working with Components         <- the real chapter title

    Diagnosis (purely structural — no content/phrase/word signal):

    * line ``i`` is a heading at level ``L``; AND
    * the next non-blank line ``j`` is also a heading; AND
    * ``level(j) <= L`` (same level, or shallower).

    The safety property is the **strictly-deeper exception**: when the
    successor is *deeper* (``level(j) > L``) the heading at ``i`` is a
    legitimate section parent introducing a child with no preamble
    (``# Part I`` → ``## Chapter 1``; ``## 1.1`` → ``### 1.1.1`` — a
    parent whose only content is subsections) — those are NEVER
    touched. A real parent is always *shallower* than what it
    introduces; a bodyless heading whose structure moves sideways
    (same level) or *up* (shallower) introduced no section — it is an
    orphan / page-header shell. The shell at ``i`` is demoted to plain
    text (markers dropped, indent + text kept — faithful, nothing
    deleted); the real heading at ``j`` is kept.

    Decisions are taken from the original scan then applied, so a run
    ``# A`` / ``# B`` / ``# C`` (C has body) demotes A and B and keeps
    C. Returns ``(rewritten_text, demoted_count)``; a no-op (``count
    0``) when the pattern is absent (e.g. the structure-faithful reader
    output, which has a single ``#`` title and no second heading).
    """
    lines = text.splitlines()
    levels: dict[int, int] = {}
    for idx, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            levels[idx] = len(m.group(2))

    demote: set[int] = set()
    for i in sorted(levels):
        # Next non-blank line after i must BE the next heading j
        # (nothing but blanks between) at the same or a shallower
        # level. A strictly-deeper successor = legitimate parent→child;
        # never demote that.
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j in levels and levels[j] <= levels[i]:
            demote.add(i)

    if not demote:
        return text, 0

    out: list[str] = []
    for idx, line in enumerate(lines):
        if idx in demote:
            m = _HEADING_RE.match(line)
            out.append(f"{m.group(1)}{m.group(3)}" if m else line)
        else:
            out.append(line)
    res = "\n".join(out)
    if text.endswith("\n") and not res.endswith("\n"):
        res += "\n"
    return res, len(demote)


def lock_numbered_section_depth_pass(text: str) -> tuple[str, int]:
    """Whole-text numbered-section depth lock.

    The engine's FIRST pass: a deterministic *promote* (re-levels an
    existing ``#…`` heading with an ``N.M[.O]`` prefix to its
    dot-count depth). Runs before the emphasis-strip / prose-demote /
    demote passes — the load-bearing "promotes before demotes" order.
    Delegates per-line to the validated
    ``_cleanup.lock_numbered_section_depth`` (no-op on any non-``#``
    or non-``N.M`` line).
    """
    out: list[str] = []
    n = 0
    for line in text.splitlines():
        new = lock_numbered_section_depth(line)
        if new != line:
            n += 1
        out.append(new)
    res = "\n".join(out)
    if text.endswith("\n") and not res.endswith("\n"):
        res += "\n"
    return res, n


def strip_heading_emphasis_pass(text: str) -> tuple[str, int]:
    """Whole-text heading-emphasis strip.

    The first engine pass: scan every line, delegate to the validated
    ``_cleanup.strip_emphasis_from_heading`` (acts only on ``#``-prefixed
    lines; bold/italic inside a heading is redundant — a no-op when the
    heading has no ``**``/``__``). Runs before prose-demote so that pass
    sees emphasis-stripped titles. Unconditional — emphasis in a heading
    is always redundant, regardless of doc type.
    """
    out: list[str] = []
    n = 0
    for line in text.splitlines():
        new = strip_emphasis_from_heading(line)
        if new != line:
            n += 1
        out.append(new)
    res = "\n".join(out)
    if text.endswith("\n") and not res.endswith("\n"):
        res += "\n"
    return res, n


def demote_prose_headings(text: str) -> tuple[str, int]:
    """Whole-text prose-shaped-heading demotion.

    A registered detect→correct pass: scan every line, delegate the
    per-line decision to the validated
    ``_heading_sanity.demote_prose_heading`` (a real heading is left
    untouched — it only demotes a heading whose title is sentence/
    caption/fragment-shaped), count the lines it changed. Skipped by
    the caller on outline-promoted docs (their reconstructed section
    titles are legitimately sentence-shaped).
    """
    out: list[str] = []
    n = 0
    for line in text.splitlines():
        new = demote_prose_heading(line)
        if new != line:
            n += 1
        out.append(new)
    res = "\n".join(out)
    if text.endswith("\n") and not res.endswith("\n"):
        res += "\n"
    return res, n


# Ordered registry: (log_event, pass_fn). Order is load-bearing — each pass
# operates on the previous pass's output (TOC-phantom demotes change the
# heading set that recurring-scaffold then counts). A pass fn is
# ``str -> (rewritten_text, demoted_count)`` and is conservative: it demotes
# only its detected pattern, returning ``(text, 0)`` when absent.
HEADING_DEMOTE_PASSES: tuple[tuple[str, Callable[[str], tuple[str, int]]], ...] = (
    # Front-matter first: it demotes the whole pre-first-chapter region
    # (title page, copyright, TOC) in a book, which removes TOC entries the
    # later toc-phantom pass would otherwise re-scan.
    ("cleanup_demoted_front_matter_headings", demote_front_matter_headings),
    # Detailed-TOC chapter headings (a `# Chapter N` sitting above
    # bulleted `- N.N <title> <page>` section lines) — the front-of-book
    # Contents Marker promotes to H1. Runs after front-matter (which clears
    # the pre-first-chapter region) and before toc-phantom (which keys on a
    # page-suffix twin these bare `Chapter N` labels don't have).
    ("cleanup_demoted_toc_outline_headings", demote_toc_outline_headings),
    ("cleanup_demoted_toc_phantom_headings", demote_toc_phantom_headings),
    ("cleanup_demoted_empty_shell_headings", demote_empty_shell_headings),
    ("cleanup_demoted_recurring_scaffold", demote_recurring_scaffold_headings),
    ("cleanup_demoted_listish_bare_int_headings", demote_listish_bare_int_headings),
    # Single-dot `N.` sibling of the bare-int pass — demotes `#### 1. Click
    # the button.` step headings when the doc uses `N.` predominantly as a
    # plain-text list (document-relative count). Same outline-skip.
    ("cleanup_demoted_listish_dotted_int_headings", demote_listish_dotted_int_headings),
    # orphan-fragments runs LAST: it keys off the document's deepest
    # present heading level, so it must see the structure the earlier
    # demotes leave behind. Outline-skipped (below) like the other
    # backend-second-guessing passes — Marker margin junk is its target,
    # never a reconstructed outline heading.
    ("cleanup_demoted_orphan_fragments", demote_orphan_fragments),
)

# Passes that second-guess BACKEND-promoted (Marker) headings and so are
# skipped on structure-faithful reader output (the invariant:
# reconstructed flattened-outline headings are trusted, never demoted).
_OUTLINE_SKIP_EVENTS = frozenset(
    {
        "cleanup_demoted_front_matter_headings",
        "cleanup_demoted_toc_outline_headings",
        "cleanup_demoted_empty_shell_headings",
        "cleanup_demoted_listish_bare_int_headings",
        "cleanup_demoted_listish_dotted_int_headings",
        "cleanup_demoted_orphan_fragments",
    }
)


def apply_heading_demotions(
    text: str, *, is_outline_doc: bool = False
) -> tuple[str, dict[str, int]]:
    """Run the detect→correct heading passes in load-bearing order.

    1. **numbered-depth lock** — the deterministic structural promote,
       first; structural promotes must precede demotes. ``N.M``
       dot-count depth is the sole language-agnostic structural-depth rule.
    2. **emphasis-strip** (unconditional) — so the prose pass sees
       clean titles.
    3. **prose-demote** — only when ``not is_outline_doc`` (the
       skip protecting a reconstructed flattened doc's legitimately
       sentence-shaped section titles).
    4. **registry demotes** — TOC-phantom → empty-shell (bodyless
       heading + same-or-shallower successor) → recurring-scaffold →
       listish-bare-int → orphan-fragments (short margin-junk codes at
       the deepest level). Empty-shell, bare-int, and orphan-fragments
       are skipped when ``is_outline_doc`` (the invariant —
       reconstructed structure-faithful headings are trusted, never
       second-guessed).

    Returns ``(rewritten_text, counts)`` mapping each pass's log-event
    name to the number of heading lines it changed (0 when its pattern
    was absent). Each pass is conservative and a no-op when clean.
    """
    counts: dict[str, int] = {}
    text, n = lock_numbered_section_depth_pass(text)
    counts["cleanup_locked_numbered_section_depth"] = n
    text, n = strip_heading_emphasis_pass(text)
    counts["cleanup_stripped_heading_emphasis"] = n
    if not is_outline_doc:
        text, n = demote_prose_headings(text)
        counts["cleanup_demoted_prose_headings"] = n
    for event, pass_fn in HEADING_DEMOTE_PASSES:
        # Empty-shell shares the invariant with prose-demote: a
        # reconstructed flattened-outline doc's section headings were
        # rebuilt from the source structure and must be trusted, never
        # second-guessed. The shell heuristic targets BACKEND-promoted
        # (Marker) page-header shells, not reconstructed headings — skip
        # it on outline docs. (It stays in the registry tuple so its
        # load-bearing position, after TOC-phantom, is preserved for
        # the non-outline path.)
        if is_outline_doc and event in _OUTLINE_SKIP_EVENTS:
            continue
        text, n = pass_fn(text)
        counts[event] = n
    return text, counts
