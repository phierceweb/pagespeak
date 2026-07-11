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
from pathlib import Path
from typing import Any

from ._run_record import RUN_RECORD_FILENAME, file_sha256

# Filename-stem cleaning: collapse `_`/`-` separators and whitespace runs.
_SEPARATOR_RE = re.compile(r"[_\-]+")
_WHITESPACE_RE = re.compile(r"\s+")
# source_id slugging: anything non-alphanumeric collapses to a single `-`.
_SOURCE_ID_RE = re.compile(r"[^a-z0-9]+")


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


def source_id_from_name(name: str) -> str:
    """Stable machine slug of a source filename: stem lowercased, non-alnum
    runs collapsed to `-`. The cross-conversion join key for one source work
    (stays constant however the out-dir is named)."""
    stem = Path(name).stem if name else ""
    return _SOURCE_ID_RE.sub("-", stem.lower()).strip("-")


def _read_run_record(out: Path | None) -> dict[str, Any] | None:
    """The out-dir's run record as a dict, or None when absent/unreadable."""
    if out is None:
        return None
    record_path = out / RUN_RECORD_FILENAME
    if not record_path.is_file():
        return None
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def _identity_from_record(record: dict[str, Any] | None) -> dict[str, str] | None:
    """The original-source identity a run record knows: the persisted
    `source_identity` block when present, else rebuilt from a non-checkpoint
    `input` entry. None when the record only knows a `.raw.md` checkpoint."""
    if record is None:
        return None
    block = record.get("source_identity")
    if isinstance(block, dict):
        result: dict[str, str] = {
            key: value
            for key, value in block.items()
            if key in ("file", "source_id", "sha256") and isinstance(value, str)
        }
        if "source_id" in result or "sha256" in result:
            return result
    input_name = record.get("input")
    if not isinstance(input_name, str) or input_name.endswith(".raw.md"):
        return None
    rebuilt: dict[str, str] = {"file": input_name}
    slug = source_id_from_name(input_name)
    if slug:
        rebuilt["source_id"] = slug
    recorded_sha = record.get("input_sha256")
    if isinstance(recorded_sha, str):
        rebuilt["sha256"] = recorded_sha
    return rebuilt


def resolve_source_identity(
    src: Path, out: Path | None, *, dir_mode: bool
) -> tuple[str | None, str | None]:
    """`(source_id, source_sha256)` of the ORIGINAL source document.

    File mode: derived from `src` directly. Dir mode: the run record's
    persisted `source_identity` block (survives re-runs), falling back to a
    non-checkpoint `input` entry; unrecoverable → (None, None) rather than
    mislabeling the book.
    """
    if not dir_mode:
        try:
            sha: str | None = file_sha256(src)
        except OSError:
            sha = None
        return source_id_from_name(src.name) or None, sha
    identity = _identity_from_record(_read_run_record(out))
    if identity is None:
        return None, None
    return identity.get("source_id"), identity.get("sha256")


def persistable_source_identity(
    src: Path, out: Path | None, *, dir_mode: bool
) -> dict[str, str] | None:
    """The `source_identity` block for this run's record. File mode derives it
    from the input; dir mode carries the prior record's knowledge forward —
    so the original source identity survives any number of dir-mode re-runs
    (each of which records the raw checkpoint as its literal `input`)."""
    if dir_mode:
        return _identity_from_record(_read_run_record(out))
    source_id, sha = resolve_source_identity(src, out, dir_mode=False)
    if source_id is None and sha is None:
        return None
    block: dict[str, str] = {"file": src.name}
    if source_id is not None:
        block["source_id"] = source_id
    if sha is not None:
        block["sha256"] = sha
    return block


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
