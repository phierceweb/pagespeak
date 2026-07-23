"""Pure text-defect detectors for `pagespeak audit`.

Each detector is a `text -> list[AuditFinding]` function flagging one
conversion-defect shape seen in converted markdown (see `docs/audit.md`):
collapsed wide tables, stray HTML table debris, U+FFFD encoding artifacts,
undecoded HTML entities, shattered emphasis runs, and duplicated junk
headings. Detectors only report — fixing belongs to the pipeline (or is a
known wall, as with duplicate scaffold headings).

File-context checks (need a real path on disk) live in `_audit.py`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# A cell holding this many <br>-joined lines is a collapsed sheet, not a
# legitimate multi-line cell — the sole collapsed-table signal. Calibrated
# so real multi-line spec/list cells (~22 <br> max) stay below and genuine
# whole-sheet collapses (35+) stay above. An empty-row-run signal was tried
# and removed: redundant on real collapses (which always also produce a
# mega-cell), and on its own it false-flagged authored-blank tables.
_BR_BLOB_MIN = 30
_DUP_HEADING_MIN = 4  # identical headings in one file before warning
_DUP_HEADING_EXCLUDE = frozenset({"subsections"})  # splitter furniture

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TABLE_TAG_RE = re.compile(r"</?(?:td|tr|table|tbody|thead|th)\b", re.IGNORECASE)
_EMPTY_ATTR_TAG_RE = re.compile(r'<[^>\n]*=""\s*>')
_ANGLE_LINK_TARGET_RE = re.compile(r"\]\(<[^>\n]*>\)")  # [t](<path with spaces.md>)
_ENTITY_RE = re.compile(
    r"&(?:amp|lt|gt|quot|apos|nbsp|ndash|mdash|lsquo|rsquo|ldquo|rdquo|"
    r"hellip|copy|reg|trade|deg|times|plusmn|middot|bull|sect|para|"
    r"#\d+|#x[0-9a-fA-F]+);"
)
# A column is the label column of a key-value table when at least this many
# cells — and this share of its non-empty cells — are colon-terminated.
_LABEL_COL_MIN = 3
_LABEL_COL_RATIO = 0.5
# An interior `…x: y…` inside a label-column cell = a second label merged in.
# Colon-space is required, so times (10:30) and URLs never match.
_MERGED_LABEL_RE = re.compile(r"\S:\s+\S")
_ALIGNMENT_CELL_RE = re.compile(r"^:?-{3,}:?$|^$")
_SHATTER_RE = re.compile(r"\*{4,}")
_HR_LINE_RE = re.compile(r"\s*\*+\s*$")
_HEADING_RE = re.compile(r"(#{1,6})\s+(.+?)\s*$")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")  # a documented tag/entity in `code`


@dataclass(frozen=True)
class AuditFinding:
    """One detected defect: which check fired, where, and why."""

    check: str
    severity: str  # "error" | "warning"
    line: int  # 1-based line of the (first) occurrence
    message: str


def _fenced_lines(lines: list[str]) -> set[int]:
    """0-based indices of lines inside ``` fences, delimiters included."""
    fenced: set[int] = set()
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced.add(i)
            in_fence = not in_fence
            continue
        if in_fence:
            fenced.add(i)
    return fenced


def _prose_lines(text: str) -> list[tuple[int, str]]:
    """(1-based line number, line) pairs outside fenced code, with inline
    `code` spans blanked. A tag or entity DOCUMENTED in inline code
    (`` `<td>` ``, `` `&amp;lt;` `` — common in HTML/markdown manuals) is
    verbatim content, not a defect, exactly like a fenced code block.

    Spans blank to a single space, never to the empty string: bold-wrapped
    inline code (``**`⌘ + S`**``) would otherwise fuse into ``****`` and read
    as shattered emphasis."""
    lines = text.splitlines()
    fenced = _fenced_lines(lines)
    return [
        (i + 1, _INLINE_CODE_RE.sub(" ", line)) for i, line in enumerate(lines) if i not in fenced
    ]


def check_collapsed_table(text: str) -> list[AuditFinding]:
    """Wide-table collapse: a whole sheet `<br>`-joined into ONE cell — the
    shape where Marker jams every row of a table into a single mega-cell. A
    cell holding `_BR_BLOB_MIN`+ `<br>` is the unambiguous signal; see the
    constant for why this is the *sole* signal (an empty-row-run heuristic was
    tried and removed)."""
    findings: list[AuditFinding] = []
    for lineno, line in _prose_lines(text):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        worst = max(
            (len(_BR_RE.findall(cell)) for cell in stripped.strip("|").split("|")),
            default=0,
        )
        if worst >= _BR_BLOB_MIN:
            findings.append(
                AuditFinding(
                    check="collapsed_table",
                    severity="error",
                    line=lineno,
                    message=f"table cell holding {worst} <br>-joined lines (collapsed sheet)",
                )
            )
    return findings


def check_html_fragment(text: str) -> list[AuditFinding]:
    """Broken HTML table debris in prose (the `e<5v< td=\"\">` shape)."""
    findings: list[AuditFinding] = []
    for lineno, line in _prose_lines(text):
        line = _ANGLE_LINK_TARGET_RE.sub("]()", line)
        match = _TABLE_TAG_RE.search(line) or _EMPTY_ATTR_TAG_RE.search(line)
        if match:
            findings.append(
                AuditFinding(
                    check="html_fragment",
                    severity="error",
                    line=lineno,
                    message=f"stray HTML table debris: {match.group(0)!r}",
                )
            )
    return findings


def check_replacement_char(text: str) -> list[AuditFinding]:
    """U+FFFD replacement characters — encoding damage (`[�]` for Ω)."""
    total = text.count("�")
    if not total:
        return []
    first = next(i + 1 for i, line in enumerate(text.splitlines()) if "�" in line)
    return [
        AuditFinding(
            check="replacement_char",
            severity="error",
            line=first,
            message=f"{total} occurrence(s) of U+FFFD (encoding damage)",
        )
    ]


def check_html_entity(text: str) -> list[AuditFinding]:
    """Undecoded HTML entities outside code fences (cleanup regression)."""
    findings: list[AuditFinding] = []
    for lineno, line in _prose_lines(text):
        hits = _ENTITY_RE.findall(line)
        if hits:
            findings.append(
                AuditFinding(
                    check="html_entity",
                    severity="error",
                    line=lineno,
                    message=f"{len(hits)} undecoded HTML entit{'y' if len(hits) == 1 else 'ies'}",
                )
            )
    return findings


def check_shattered_emphasis(text: str) -> list[AuditFinding]:
    """Emphasis-marker pileups (`**CO****2**`) from shattered runs."""
    findings: list[AuditFinding] = []
    for lineno, line in _prose_lines(text):
        if _HR_LINE_RE.fullmatch(line):  # a `****` line is a horizontal rule
            continue
        if _SHATTER_RE.search(line):
            findings.append(
                AuditFinding(
                    check="shattered_emphasis",
                    severity="error",
                    line=lineno,
                    message="4+ consecutive emphasis markers (shattered run)",
                )
            )
    return findings


def _table_rows(run: list[tuple[int, str]]) -> list[tuple[int, list[str]]]:
    """(lineno, cells) per data row of one pipe-table run; alignment rows
    (`--- / :---:`) are dropped so their colons never read as labels."""
    rows: list[tuple[int, list[str]]] = []
    for lineno, line in run:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(_ALIGNMENT_CELL_RE.match(c) for c in cells):
            continue
        rows.append((lineno, cells))
    return rows


def check_misaligned_table(text: str) -> list[AuditFinding]:
    """Wide-table misalignment: two labels merged into one label-column cell —
    the shape a wide multi-column spec sheet takes when extraction drifts the
    cell boundaries, landing values under the wrong label (wrong data for any
    consumer, unlike a collapse, which is at least self-consistent).

    Scoped to key-value tables: a column qualifies as the label column when
    most of its cells are colon-terminated; only there does an interior
    `label: more text` read as a merged label rather than prose."""
    findings: list[AuditFinding] = []
    run: list[tuple[int, str]] = []
    prose = _prose_lines(text)
    for lineno, line in [*prose, (0, "")]:  # sentinel flushes the last run
        if line.strip().startswith("|"):
            run.append((lineno, line))
            continue
        rows = _table_rows(run)
        run = []
        if len(rows) < _LABEL_COL_MIN:
            continue
        ncols = max(len(cells) for _, cells in rows)
        for j in range(ncols):
            col = [cells[j] for _, cells in rows if j < len(cells) and cells[j]]
            labels = sum(1 for cell in col if cell.endswith(":"))
            if labels < _LABEL_COL_MIN or labels < _LABEL_COL_RATIO * len(col):
                continue
            for ln, cells in rows:
                if j >= len(cells) or not _MERGED_LABEL_RE.search(cells[j]):
                    continue
                # Only a real misalignment when the row carries data that could
                # be sitting under the wrong label. A blank form / worksheet row
                # (every other cell empty) is authored structure, not spillover.
                if any(k != j and other.strip() for k, other in enumerate(cells)):
                    findings.append(
                        AuditFinding(
                            check="misaligned_table",
                            # warning, not error: a value under the wrong label is
                            # real RAG noise, but it is NOT auto-fixable — Marker and
                            # Docling reproduce it identically (ambiguous multi-line
                            # cell geometry in the source PDF). Report for a human,
                            # like duplicate_heading; a backend swap cannot repair it.
                            severity="warning",
                            line=ln,
                            message=f"two labels merged in one cell: {cells[j][:60]!r}",
                        )
                    )
    return sorted(findings, key=lambda f: f.line)


def check_duplicate_heading(text: str) -> list[AuditFinding]:
    """The same heading text repeated many times in one document — the
    recurring-scaffold shape (a numbered-procedure manual's `Important note:`
    ×12). Report-only: automated demotion hit a known wall, so a human
    decides."""
    counts: Counter[str] = Counter()
    first_seen: dict[str, tuple[int, str]] = {}
    for lineno, line in _prose_lines(text):
        match = _HEADING_RE.match(line)
        if not match:
            continue
        title = match.group(2)
        key = title.casefold()
        if key in _DUP_HEADING_EXCLUDE:
            continue
        counts[key] += 1
        first_seen.setdefault(key, (lineno, title))
    findings: list[AuditFinding] = []
    for key, n in counts.items():
        if n >= _DUP_HEADING_MIN:
            lineno, title = first_seen[key]
            findings.append(
                AuditFinding(
                    check="duplicate_heading",
                    severity="warning",
                    line=lineno,
                    message=f'heading "{title}" appears {n} times',
                )
            )
    return findings


_TEXT_CHECKS = (
    check_collapsed_table,
    check_misaligned_table,
    check_html_fragment,
    check_replacement_char,
    check_html_entity,
    check_shattered_emphasis,
    check_duplicate_heading,
)


def run_text_checks(text: str) -> list[AuditFinding]:
    """Run every pure text detector; findings in detector order."""
    findings: list[AuditFinding] = []
    for check in _TEXT_CHECKS:
        findings.extend(check(text))
    return findings
