"""Output provenance frontmatter.

Emits a YAML ``---`` block stamping each conversion artifact (the
whole-doc markdown and every split section file) with where it came
from — source type, human label, source file. This is the enabler for a
multi-source RAG database: when a textbook chapter, a lecture outline,
and a lab activity all cover the same topic, the consumer can tag each
retrieved chunk by origin instead of treating them as interchangeable.

Distinct from ``_frontmatter.py``, which *strips* template frontmatter
out of DOCX *input*. This module *emits* provenance frontmatter into
*output*. Emission is opt-in: nothing is written unless the caller
supplies ``source_type`` or ``source_label``.
"""

from __future__ import annotations

import json
import re

# Filename-stem cleaning: collapse `_`/`-` separators and whitespace runs.
_SEPARATOR_RE = re.compile(r"[_\-]+")
_WHITESPACE_RE = re.compile(r"\s+")


def clean_source_label(stem: str) -> str:
    """Derive a human source label from a filename stem.

    Conservative cleaning only: `_`/`-` separators and runs of whitespace
    collapse to single spaces, then the ends are stripped. Casing and all
    other punctuation are preserved, so descriptive stems survive intact
    (``"Vendor Pro-C 2"`` → ``"Vendor Pro C 2"``, ``"Sample_Manual"`` →
    ``"Sample Manual"``).

    It deliberately does NOT strip version / language cruft
    (``"V5 - EN"``, ``"v2.0"``) or rewrite casing — over-stripping mangles
    more labels than it fixes, and a cryptic stem (``"AB_CD_1234567_…"``)
    is better surfaced honestly than guessed at. Pass an explicit
    ``source_label`` to override a poor stem.

    Returns the original stem (stripped) if cleaning would empty it.
    """
    cleaned = _WHITESPACE_RE.sub(" ", _SEPARATOR_RE.sub(" ", stem)).strip()
    return cleaned or stem.strip()


def build_frontmatter(fields: dict[str, object]) -> str:
    """Return a YAML ``---`` frontmatter block for the given ordered fields,
    or ``""`` if every value is ``None``.

    Insertion order is preserved; ``None`` values are skipped. Values are
    JSON-encoded (YAML 1.2 is a JSON superset) so colons, quotes, or
    backslashes can't corrupt the block. The block ends with a blank line so
    a caller can prepend it directly: ``build_frontmatter(...) + markdown``.

    Reusable across output formats — QTI uses it for rich per-quiz provenance
    (course / exam / quiz_id / …), and `build_provenance_frontmatter` is a
    thin wrapper for the base source-tagging triple.
    """
    items = [(key, value) for key, value in fields.items() if value is not None]
    if not items:
        return ""
    body = "".join(f"{key}: {json.dumps(value)}\n" for key, value in items)
    return f"---\n{body}---\n\n"


def build_provenance_frontmatter(
    *,
    source_type: str | None = None,
    source_label: str | None = None,
    source_file: str | None = None,
) -> str:
    """Return a YAML frontmatter block (``---`` … ``---`` + trailing blank
    line) for the given provenance fields, or ``""`` when none is warranted.

    Emission is opt-in on ``source_type`` / ``source_label``: if BOTH are
    ``None`` the result is ``""`` (``source_file`` alone never triggers a
    block, so conversions run without the provenance flags are byte-for-byte
    unchanged). When triggered, every non-``None`` field is included.

    Values are JSON-encoded (YAML 1.2 is a JSON superset), so labels
    containing colons, quotes, or backslashes can't corrupt the block.

    The returned block ends with a blank line so a caller can prepend it
    directly: ``build_provenance_frontmatter(...) + markdown``.
    """
    if source_type is None and source_label is None:
        return ""
    return build_frontmatter(
        {
            "source_type": source_type,
            "source_label": source_label,
            "source_file": source_file,
        }
    )
