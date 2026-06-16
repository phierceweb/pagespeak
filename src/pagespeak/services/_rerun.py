"""Cache invalidation for `--rerun-from <stage>` and `pagespeak invalidate`.

Thin shim over `pf_core.pipeline.cache`. Stages map to cache files.
Cascade rule: bust the target stage's OWN cache (whether
structural or content-keyed) plus every DOWNSTREAM stage's STRUCTURAL
files. Downstream content-keyed caches (`.vision-cache/`,
`.heading-normalize-cache/`, `.decoration-cache/`) self-invalidate via
their phash / content-hash key and are PRESERVED across cascade. Missing
files are silent no-ops.

Binds the pagespeak-specific stage registry and preserves the
positional-arg public API.

Pipeline order:
    ingest → cleanup → decorations → normalize → repair → structure → vision → split

The `decorations` stage covers phash deduplication and decoration
stripping, so users can rerun that step independently without
re-running the full ingest backend.

Structural files per stage (mtime-gated; cascade busts):
    ingest      : <stem>.raw.md, images/, chunks/, manifest.json
    cleanup     : <stem>.cleaned.md
    decorations : (none — content-keyed only)
    normalize   : <stem>.normalized.md
    repair      : <stem>.repaired.md  (post-LLM deterministic heading repair)
    structure   : <stem>.structured.md (holistic doc-level passes; flat-source rebalance)
    vision      : <stem>.visioned.md (post-inject + TOC)
    split       : sections/, INDEX.md

Content-keyed caches per stage (key encodes validity; cascade preserves):
    decorations: .decoration-cache/
    normalize  : .heading-normalize-cache/
    vision     : .vision-cache/
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, get_args

from pf_core.pipeline.cache import (
    StageDefinition,
    StageRegistry,
)
from pf_core.pipeline.cache import (
    files_to_invalidate as _files_to_invalidate,
)
from pf_core.pipeline.cache import (
    invalidate_caches as _invalidate_caches,
)

RerunStage = Literal[
    "ingest", "cleanup", "decorations", "normalize", "repair", "structure", "vision", "split"
]
RERUN_STAGES: tuple[str, ...] = get_args(RerunStage)

PAGESPEAK_REGISTRY = StageRegistry(
    stages=(
        StageDefinition(
            name="ingest",
            structural_files=(
                "{stem}.raw.md",
                "images",
                "chunks",
                "manifest.json",
            ),
        ),
        StageDefinition(
            name="cleanup",
            structural_files=("{stem}.cleaned.md",),
        ),
        StageDefinition(
            name="decorations",
            content_keyed_files=(".decoration-cache",),
        ),
        StageDefinition(
            name="normalize",
            structural_files=("{stem}.normalized.md",),
            content_keyed_files=(".heading-normalize-cache",),
        ),
        StageDefinition(
            name="repair",
            structural_files=("{stem}.repaired.md",),
        ),
        StageDefinition(
            name="structure",
            structural_files=("{stem}.structured.md",),
        ),
        StageDefinition(
            name="vision",
            structural_files=("{stem}.visioned.md",),
            content_keyed_files=(".vision-cache",),
        ),
        StageDefinition(
            name="split",
            structural_files=("sections", "INDEX.md"),
        ),
    ),
)


def files_to_invalidate(output_dir: Path, stage: RerunStage, source_stem: str) -> list[Path]:
    """All files to delete for `--rerun-from <stage>`.

    Rule: bust the target stage's own content-keyed cache AND every
    structural file from the target stage onward. Downstream stages'
    content-keyed caches are PRESERVED — they self-invalidate.
    """
    if stage not in RERUN_STAGES:
        raise ValueError(f"unknown rerun stage: {stage!r}. Valid: {RERUN_STAGES}")
    paths: list[Path] = _files_to_invalidate(
        output_dir,
        stage=stage,
        registry=PAGESPEAK_REGISTRY,
        source_stem=source_stem,
    )
    return paths


def invalidate_caches(output_dir: Path, stage: RerunStage, source_stem: str) -> list[Path]:
    """Delete caches per the cascade rule. Returns the list of paths
    that actually existed and were removed."""
    if stage not in RERUN_STAGES:
        raise ValueError(f"unknown rerun stage: {stage!r}. Valid: {RERUN_STAGES}")
    deleted: list[Path] = _invalidate_caches(
        output_dir,
        stage=stage,
        registry=PAGESPEAK_REGISTRY,
        source_stem=source_stem,
    )
    return deleted


__all__ = [
    "PAGESPEAK_REGISTRY",
    "RERUN_STAGES",
    "RerunStage",
    "files_to_invalidate",
    "invalidate_caches",
]
