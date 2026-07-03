"""`PipelineContext` — the state every phase reads and mutates.

The sequencer hands one of these to each `Phase.run`. It carries the
fully-resolved config, the derived paths, and the mutable
`IngestResult`. Phases mutate `ctx.result.markdown` and write their
checkpoint file; nothing is threaded as a bare return value.

This is a data container only — no behaviour. `to_markdown()` builds
it (preamble), the sequencer runs phases against it, `to_markdown()`
drains it (teardown).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models._models import IngestResult
from ..services._cleanup import CleanupLevel, CrossRefs
from ..services._normalize_decision import NormalizeModeOption


@dataclass
class PipelineContext:
    """Resolved config + derived paths + mutable conversion state."""

    # --- source / output identity --------------------------------------
    src: Path
    out: Path | None
    dir_mode: bool
    doc_stem: str | None
    effective_stem: str
    suffix: str
    source_format: str

    # --- checkpoint paths (None when out is None) ----------------------
    raw_md_path: Path | None
    cleaned_md_path: Path | None
    normalized_md_path: Path | None
    repaired_md_path: Path | None
    structured_md_path: Path | None
    visioned_md_path: Path | None

    # --- resolved flags ------------------------------------------------
    diagrams: bool
    vision_backend: str | None
    vision_model: str | None
    vision_concurrency: int | None
    vision_cache_only: bool
    preserve_alt: bool
    force_ocr: bool
    device: str | None
    page_range: str | list[int] | None
    html_base_url: str | None
    cleanup: CleanupLevel
    cross_refs: CrossRefs
    split_sections: bool
    nested_split: bool
    split_min_level: int | None
    split_max_level: int | None
    split_target_kb: int | None
    min_body_chars: int | None
    english_only: bool
    regenerate_toc: bool
    decoration_threshold: int | None
    decoration_hamming_distance: int | None
    pdf_backend: str
    pdf_backend_kwargs: dict[str, Any] | None
    # Opt-in (`--repair-tables`): after a Marker PDF ingest, splice Docling's
    # clean grid over any `<br>`-collapsed table. Marker-PDF only; off by
    # default (never runs Docling unless asked). Runs as an ingest sub-step.
    repair_tables: bool
    docx_backend: str
    docx_outline_heading_depth: int
    normalize_headings: bool
    normalize_headings_mode: NormalizeModeOption
    normalize_headings_model: str | None
    strip_frontmatter: bool
    # Output provenance (opt-in). Emitted on the whole-doc markdown and
    # every section file — the multi-source RAG enabler (tag each chunk by
    # origin). Triggered when `provenance` is True (preset-controlled; on
    # for rag-default) OR `source_type`/`source_label` is set. When on but
    # no explicit `source_label`, it's auto-derived from the cleaned
    # filename stem; `source_type` is omitted from the block when None.
    provenance: bool
    source_type: str | None
    source_label: str | None

    # --- run control ---------------------------------------------------
    # The resolved `--from` start phase, if any. `CleanupPhase` consults it
    # to skip its resume-from-cleaned shortcut when cleanup is the explicit
    # start phase: `--from cleanup` means "run cleanup", not "reuse the
    # cached cleaned.md" (which would make per-stage iteration a no-op).
    start_phase: str | None = None

    # --- mutable conversion state --------------------------------------
    result: IngestResult | None = None
    diagrams_handoff: dict[str, Any] = field(default_factory=dict)
    section_count: int | None = None

    @property
    def do_normalize(self) -> bool:
        """Normalize runs only when requested AND there's an output dir."""
        return self.normalize_headings and self.out is not None

    @property
    def do_vision(self) -> bool:
        """Vision runs only with diagrams on, images present, output dir."""
        return (
            self.diagrams
            and self.result is not None
            and bool(self.result.images)
            and self.out is not None
        )


__all__ = ["PipelineContext"]
