"""Per-line cleanup transforms: garbage/HTML/whitespace stripping, numbered-
heading promotion + depth-locking, emphasis stripping, list-bullet
normalization, cross-ref repair, page-span/ref stripping, and Marker-pollution
removal.

Each is a pure text→text function; `cleanup_markdown` orchestrates them
and `_cleanup` re-exports them (the test suite + `_cleanup_diagnose` /
`_heading_normalize` / `_fragments` import them). Regex table lives in
`_cleanup_regexes.py`.
"""

from __future__ import annotations

import html
import re

from ._cleanup_regexes import (
    _WHITESPACE_RUN_RE,
    CIRCLED_SUBLABEL_LIST_RE,
    CONTROL_CHAR_RE,
    CROSS_REF_BROKEN_RE,
    DANGLING_PAGE_LINK_TAIL_RE,
    EMPHASIS_MARKER_RE,
    HEADING_HASH_RE,
    HEADING_NUM_RE,
    HEADING_PAGE_LINK_RE,
    HEADING_PAGE_SPAN_RE,
    HTML_INLINE_TAG_RE,
    LIST_ALPHA_RE,
    LIST_O_RE,
    LIST_ROMAN_RE,
    MULTI_SPACE_RE,
    NON_ASCII_CHAR_RE,
    NUMBERED_SECTION_HEADING_RE,
    PAGE_REF_RE,
    PAGE_SPAN_RE,
)

_FENCE_SPLIT_RE = re.compile(r"(```.*?```)", re.DOTALL)
_SHATTER_RUN_RE = re.compile(r"\*{4,}")
_HR_ONLY_RE = re.compile(r"^\s*\*{3,}\s*$")  # a markdown thematic break (HR)


def collapse_shattered_emphasis(text: str) -> str:
    """Collapse runs of 4+ consecutive asterisks to `**` OUTSIDE fenced code.

    A run of four or more `*` is never valid markdown — `**` is bold, `***`
    is bold-italic, `****` is nothing. Backends emit it when adjacent runs
    each carry the same emphasis: Marker doubles bold on bold-styled PDF text
    (`****Sales:****`), and markdownify renders Canvas's nested
    `<strong><b>…</b></strong>` quiz stems as `****incorrectly****`. Either
    way the four-marker pileup is converter debris, always-correct to collapse
    (same category as `decode_html_entities`) — not authorial structure.

    A line that is *only* asterisks is a horizontal rule and is left intact;
    `***` bold-italic and `**` bold (3 or fewer) are never touched.
    """
    if "****" not in text:
        return text
    parts = _FENCE_SPLIT_RE.split(text)
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2:  # fenced block — leave verbatim
            out.append(part)
            continue
        out.append(
            "\n".join(
                line if _HR_ONLY_RE.match(line) else _SHATTER_RUN_RE.sub("**", line)
                for line in part.split("\n")
            )
        )
    return "".join(out)


def decode_html_entities(text: str) -> str:
    """Decode HTML entities (`&lt;` `&amp;` `&gt;` `&#x20;` …) OUTSIDE fenced code.

    Backends leave entities in the extracted markdown (Docling especially), so a
    spec reads `T3 &lt; 34F` / `A &amp; B` instead of `T3 < 34F` / `A & B` —
    garbled for an LLM/RAG. `html.unescape` is always correct on extracted
    content (the source had the literal char), which makes this a genuinely
    universal cleanup, not a per-doc heuristic. Fenced code blocks are preserved
    so a literal entity inside a code example survives verbatim. Runs before any
    mermaid blocks exist (cleanup precedes vision), so only source code fences
    are at stake.
    """
    if "&" not in text:
        return text
    parts = _FENCE_SPLIT_RE.split(text)
    return "".join(p if i % 2 else html.unescape(p) for i, p in enumerate(parts))


def strip_marker_pollution(text: str) -> str:
    """Strip Marker-injected TOC wrapping from a heading text.

    Patterns:
    - ``<span id="page-X-Y"></span>`` (whitespace-tolerant) — removed
    - ``[label](#page-X-Y)`` well-formed link — replaced with ``label``
    - ``](#page-X-Y)`` orphan tail (broken-markup fallback) — removed
    - Resulting whitespace runs collapsed; surrounding whitespace trimmed

    Bold / italic markers (``**``, ``_``) preserved — they're semantic.

    Runs in cleanup (before normalize) so both the LLM input and the
    rendered markdown get clean heading text.
    """
    text = HEADING_PAGE_SPAN_RE.sub("", text)
    text = HEADING_PAGE_LINK_RE.sub(r"\1", text)
    text = DANGLING_PAGE_LINK_TAIL_RE.sub("", text)
    text = _WHITESPACE_RUN_RE.sub(" ", text).strip()
    return text


def strip_garbage_chars(text: str, *, aggressive: bool = False) -> str:
    """Strip control characters always; additionally strip all non-ASCII when aggressive.

    `basic` mode (default) only removes invisible control characters that
    sometimes survive from PDF font tables. Real Unicode content (en-dashes,
    smart quotes, `©`, `®`, etc.) is preserved.

    `aggressive` mode strips everything outside printable ASCII + tab/newline.
    Use only on documents you know are ASCII-only — otherwise you'll mangle
    typographic content (e.g. `6–10 Kirby Street` becomes `610 Kirby Street`).
    """
    pattern = NON_ASCII_CHAR_RE if aggressive else CONTROL_CHAR_RE
    return pattern.sub("", text)


def strip_html_inline_tags(text: str) -> str:
    """Remove `<i>`, `<b>`, `<strong>` tags Marker preserves from styled PDF text."""
    return HTML_INLINE_TAG_RE.sub("", text)


def collapse_multi_space(text: str) -> str:
    """Collapse runs of 2+ whitespace chars to a single space.

    A utility, not applied by the default pipeline: the author's internal
    spacing is preserved verbatim because a mid-line space run never
    breaks markdown. `cleanup_markdown` only normalizes leading /
    trailing whitespace (the markdown-breaking cases).
    """
    return MULTI_SPACE_RE.sub(" ", text)


def promote_numbered_heading(line: str) -> str:
    """Promote a numbered-text line to a markdown heading.

    `1.4.1. Triggers` -> `### 1.4.1. Triggers` (depth = number of dots in the
    cleaned number + 1, capped at 6). Existing #-prefixed headings are
    whitespace-normalized but keep their declared depth.

    Requires a trailing period on the number (`1. Foo`, not `1 Foo`) so we
    don't promote sentences that happen to start with a digit, or copyright-page
    printing-sequence rows like `10 9 8 7 6 5 4 3 2 1`.
    """
    stripped = line.strip()
    if stripped.startswith("#"):
        m = HEADING_HASH_RE.match(stripped)
        if not m:
            return line
        hashes, content = m.groups()
        depth = max(1, min(len(hashes), 6))
        content = content.strip("* ").strip()
        return f"{'#' * depth} {content}"

    m = HEADING_NUM_RE.match(stripped)
    if not m:
        return line
    num, title = m.groups()
    num_clean = num.rstrip(".")
    # Single-dot plaintext patterns (`1.`, `5.`) are almost always list
    # items, quiz answers, or procedural steps — NOT section headings.
    # Don't promote. Multi-dot patterns (`1.1`, `1.1.1`) are
    # unambiguously hierarchical and still promoted. Backend-emitted
    # headings (`## 1. Foo`) are handled by the existing-heading branch
    # above and aren't affected by this guard. fixes
    # over-promotion of docling list items to H1.
    if num_clean.count(".") == 0:
        return line
    depth = min(num_clean.count(".") + 1, 6)
    title = title.strip("* ").strip()
    return f"{'#' * depth} {num_clean}. {title}"


def lock_numbered_section_depth(line: str) -> str:
    """Force a multi-dot numbered heading to its natural depth.

    `1.1` → H2, `1.1.1` → H3, `1.1.1.1` → H4 (capped at H6). A single
    trailing lowercase letter marks a textbook subsection one level
    deeper: `2.3a` → H3 (one deeper than `2.3` → H2). `3.5GHz` (uppercase
    unit) and `2.3ab` (two letters) are NOT subsections — left untouched.

    `N.M`-style numeric prefixes are unambiguously textbook section
    headings, and the dot count is the natural depth signal. Some
    backends tag them inconsistently (docling: everything H2 regardless
    of dots; Marker: varies by font size), and the LLM normalize pass
    has occasionally demoted them to H4+ as well. This rule re-locks
    the depth deterministically from the numeric prefix.

    Single-dot patterns (`1.`, `5.`) do NOT match — those are list
    items / quiz answers, handled separately by
    `promote_numbered_heading`'s single-dot guard.

    The dot count is a language-agnostic structural depth signal: it
    deterministically fixes `N.M`-numbered section depth for any
    document, so the LLM normalize pass only has to handle the harder
    cases (recurring scaffold demote, non-numbered titles).
    """
    m = NUMBERED_SECTION_HEADING_RE.match(line)
    if not m:
        return line
    leading, body = m.groups()
    prefix_m = re.match(r"^(\d+(?:\.\d+)+)([a-z])?", body)
    if not prefix_m:
        return line  # defensive; regex above already required multi-dot
    depth = prefix_m.group(1).count(".") + 1
    if prefix_m.group(2):  # letter-suffixed subsection (`2.3a`) is one deeper
        depth += 1
    depth = min(depth, 6)
    return f"{leading}{'#' * depth} {body}"


def strip_emphasis_from_heading(line: str) -> str:
    """Strip `**` / `__` bold-emphasis markers from heading lines.

    Marker promotes PDF-styled bold headings into markdown headings but
    leaves the bold delimiters in place — producing eyesores like
    ``# **2. Callouts``, ``## **Important Safety Instructions``,
    ``### **1.1.1. API``. The bold is redundant inside a heading (the
    heading itself is already visually prominent), so just remove the
    markers and collapse the resulting whitespace.

    Only affects lines starting with `#` (1-6 hashes). Body content
    with bold passes through unchanged so prose-level emphasis stays
    intact.
    """
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return line
    # Only treat as a heading if the `#` run is 1-6 followed by a space.
    m = re.match(r"^(\s*#{1,6}\s+)(.*)$", line)
    if not m:
        return line
    prefix, content = m.group(1), m.group(2)
    cleaned_content = EMPHASIS_MARKER_RE.sub("", content)
    # Collapse any double-spaces left over from a mid-text `**` removal.
    cleaned_content = re.sub(r"\s{2,}", " ", cleaned_content).strip()
    return prefix + cleaned_content


def normalize_list_bullet(line: str) -> str:
    """Convert PDF-letter-bullets (`- o`, `- a.`, `- ii.`) to nested `-` bullets,
    and strip the redundant `N.` ordinal markitdown stacks on circled ⓐ/ⓑ/ⓒ
    sub-part labels (`1. ⓐ …` → `ⓐ …`)."""
    line = CIRCLED_SUBLABEL_LIST_RE.sub(r"\1\2", line)
    line = LIST_O_RE.sub(r"\1  - \2", line)
    line = LIST_ALPHA_RE.sub(r"\1  - \2) \3", line)
    line = LIST_ROMAN_RE.sub(r"\1    - \2) \3", line)
    return line


def repair_broken_cross_ref(text: str) -> str:
    """Repair `Se[e Foo](#page-X-Y)` -> `[See Foo](#page-X-Y)`.

    Marker occasionally captures a leading character into the link bracket.
    The fix: detect a stray `[` that's glued to the preceding chars (no space)
    and merge them all inside the bracket. Refs preceded by a space (healthy
    prose like `see [Foo](#page-X-Y)`) are left alone.
    """

    def _replace(match: re.Match[str]) -> str:
        label = match.group(1)
        page_anchor = match.group(2)
        if "[" not in label:
            # Clean ref with no stray bracket — the regex's `\[?` consumed the
            # real opening bracket; nothing to repair.
            return match.group(0)
        bracket_pos = label.index("[")
        if bracket_pos > 0 and label[bracket_pos - 1] == " ":
            # Healthy: prose followed by a clean `[label](...)`. Don't merge.
            return match.group(0)
        label = label.replace("[", "")
        return f"[{label}](#{page_anchor})"

    return CROSS_REF_BROKEN_RE.sub(_replace, text)


def unescape_underscores(text: str) -> str:
    r"""`\_` -> `_` for readability."""
    return text.replace("\\_", "_")


def strip_page_spans(text: str) -> str:
    """Remove `<span id="page-X-Y"></span>` cross-ref-target anchors."""
    return PAGE_SPAN_RE.sub("", text)


def strip_page_refs(text: str) -> str:
    """Rewrite `[label](#page-X-Y)` -> `label`, dropping the broken anchor.

    Companion to `strip_page_spans`: under `cleanup="aggressive"` we strip the
    `<span id="page-X-Y">` targets, which orphans every `[label](#page-X-Y)`
    reference. With `cross_refs="strip"` we also drop the refs themselves,
    keeping the visible text.

    Only matches Marker's `#page-X-Y` anchor format. Real `#section-name`
    anchors are preserved.
    """
    return PAGE_REF_RE.sub(r"\1", text)
