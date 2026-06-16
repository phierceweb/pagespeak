"""Template-frontmatter strip — Phase 3 step in the assembly pipeline.

Some DOCX templates (enterprise / gov / regulated docs) start with
3-5 KB of boilerplate before the first real heading: revision history
table, artifact rationale, instructional text, original Word TOC with
`(#_Toc352250146)` anchors. This module detects ≥2 of those patterns
in the leading content and drops everything up to the first `# H1`.

Runs in Phase 3 (post-backend), not inside the backend, so `raw.md` stays
unmodified backend output and `--strip-frontmatter` can toggle between runs
without re-ingesting.

Internal API: imported by `orchestrators/_dispatch.py`. Not re-exported
from `pagespeak.__init__` — keep these symbols in-package.
"""

from __future__ import annotations

import re

from pf_core.log import get_logger

logger = get_logger(__name__)

_FIRST_H1_RE = re.compile(r"^#\s+\S.*$", re.MULTILINE)
_FRONTMATTER_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Word auto-TOC anchors — `(#_Toc352250146)` shape. Word-specific.
    re.compile(r"\(#_Toc\d+\)"),
    # Revision-history table header — case-insensitive cell-by-cell.
    re.compile(
        r"\|\s*Date\s*\|\s*Version\s*\|\s*Description\s*\|\s*Author\s*\|",
        re.IGNORECASE,
    ),
    # Template placeholder text — `<Project Name>`, `<Month>`, `<#.#>`.
    re.compile(r"<(?:Project Name|Month|Year|#\.#)>"),
    # Instructional-text phrases — literal substrings.
    re.compile(r"\bDelete all [Ii]nstructional [Tt]ext\b"),
    re.compile(r"\bPlace latest revisions at top of table\b"),
    re.compile(r"\bArtifact Rationale\b"),
    re.compile(r"\bRemove blank rows\b"),
)


def count_frontmatter_patterns(text: str) -> int:
    """How many distinct frontmatter patterns match in `text`. Used both
    to gate the strip (need ≥2) and to log diagnostics."""
    return sum(1 for p in _FRONTMATTER_PATTERNS if p.search(text))


def strip_template_frontmatter(markdown: str) -> tuple[str, int]:
    """Drop content before the first `# H1` heading IF the lead matches
    ≥2 frontmatter patterns. Returns `(stripped, dropped_chars)`.
    `dropped_chars=0` means no strip — either pattern threshold not met
    or no `# H1` found."""
    h1 = _FIRST_H1_RE.search(markdown)
    if h1 is None:
        return markdown, 0
    h1_pos = h1.start()
    if h1_pos == 0:
        return markdown, 0
    lead = markdown[:h1_pos]
    if count_frontmatter_patterns(lead) < 2:
        return markdown, 0
    return markdown[h1_pos:], h1_pos
