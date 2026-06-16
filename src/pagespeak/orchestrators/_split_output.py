"""Section-file writing + output provenance frontmatter for the split phase.

Two shapes:

- **Quiz** (`source_type == "quiz"`, e.g. the Top Hat backend): the doc is a
  `# title` + `## Question N` quiz, so it splits with rich per-question
  frontmatter (`quiz` / `quiz_id` / `question_number` / `question_type`) via
  `backends._qti_split`, the same machinery the Canvas QTI fan-out uses.
- **Generic** (everything else): when provenance is on (`c.provenance`,
  preset-controlled — or a source flag set), per-section files are stamped
  with source tags + an auto-derived `source_label` + breadcrumb locators;
  `source_type` is omitted when not supplied. Off → byte-for-byte unchanged.

Either way the master doc gets the matching frontmatter prepended.
"""

from __future__ import annotations

from ..models._models import IngestResult
from ._context import PipelineContext


def write_sections(c: PipelineContext, result: IngestResult) -> None:
    """Write `sections/` (when enabled) and prepend master-doc frontmatter.

    Sets `c.section_count` and mutates `result.markdown` in place (the master
    doc is written from it downstream). A no-op frontmatter (no source flags,
    non-quiz) leaves the markdown byte-for-byte unchanged.
    """
    source_file = f"{c.effective_stem}.md" if c.dir_mode else c.src.name
    if c.source_type == "quiz":
        _write_quiz(c, result, source_file)
    else:
        _write_generic(c, result, source_file)


def _write_quiz(c: PipelineContext, result: IngestResult, source_file: str) -> None:
    from ..backends._qti_split import quiz_master_frontmatter, split_quiz_doc

    if c.split_sections and c.out is not None:
        written = split_quiz_doc(
            result.markdown,
            c.out / "sections",
            source_type=c.source_type,
            source_label=c.source_label,
        )
        c.section_count = len(written)
    master = quiz_master_frontmatter(
        result.markdown,
        source_type=c.source_type,
        source_label=c.source_label,
        source_file=source_file,
    )
    if master:
        result.markdown = master + result.markdown


def _doc_title(markdown: str) -> str | None:
    """The document's first `# ` H1, or None."""
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _write_generic(c: PipelineContext, result: IngestResult, source_file: str) -> None:
    """Generic (non-quiz) docs: when provenance is on, emit RICH per-section
    frontmatter (source tags + doc_title + section breadcrumb / number /
    level) — the research-backed locator set for multi-source RAG. On when
    `c.provenance` (preset-controlled) OR a source flag is set; off → byte-
    for-byte unchanged. With no explicit `source_label`, it's auto-derived
    from the cleaned filename stem; `source_type` is omitted when None."""
    from ..services._provenance import build_frontmatter, clean_source_label

    enabled = c.provenance or c.source_type is not None or c.source_label is not None
    provenance: dict[str, object] | None = None
    if enabled:
        label = (
            c.source_label if c.source_label is not None else clean_source_label(c.effective_stem)
        )
        provenance = {
            "source_type": c.source_type,
            "source_label": label,
            "source_file": source_file,
            "doc_title": _doc_title(result.markdown),
        }

    if c.split_sections and c.out is not None:
        from ..services._split import DEFAULT_MIN_BODY_CHARS, split_into_sections

        effective_min_body = (
            DEFAULT_MIN_BODY_CHARS if c.min_body_chars is None else c.min_body_chars
        )
        written = split_into_sections(
            result.markdown,
            c.out / "sections",
            nested=c.nested_split,
            source_name=source_file,
            min_level=c.split_min_level,
            min_body_chars=effective_min_body,
            provenance=provenance,
            # Root every section breadcrumb at the doc name → INDEX.md so
            # each split chunk self-identifies its source doc (the in-chunk
            # cross-contamination fix for a multi-doc RAG DB). Always on when
            # splitting. An explicit `source_label` wins (the authoritative
            # name); else the title-cased filename slug — the RELIABLE doc
            # identity. (NOT the first `# H1`: it is often a section, not a
            # title — a generic "Introduction" or "Overview", or absent — so
            # it roots at the wrong thing.)
            doc_title=c.source_label or clean_source_label(c.effective_stem).title(),
            english_only=c.english_only,
        )
        c.section_count = len(written)

    # Whole-doc master frontmatter: source tags + doc_title (+ section_count
    # when sections were written).
    if provenance is not None:
        master_fields = dict(provenance)
        if c.split_sections and c.out is not None:
            master_fields["section_count"] = c.section_count
        master = build_frontmatter(master_fields)
        result.markdown = master + result.markdown
