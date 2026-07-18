"""`to_markdown` setup helpers: preset/flag resolution + dir-mode input.

The preset/default resolution, the dir-mode stem/input resolution, and
the run-timestamp helper. `_dispatch` re-exports `resolve_dir_mode_stem`
(the CLI imports it) and uses the rest internally. Self-contained: no
dependency back on `_dispatch`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..services._cleanup import CleanupLevel
from ..services._heading_normalize import NormalizeMode
from ..services._normalize_decision import NormalizeModeOption
from ..services._presets import resolve_preset
from ._context import PipelineContext

# Original to_markdown defaults for the preset-controlled flags.
# Used when no preset is set and the caller didn't pass a value.
_DEFAULT_CLEANUP: CleanupLevel = "basic"
_DEFAULT_SPLIT_SECTIONS = False
_DEFAULT_NESTED_SPLIT = False
# default to splitting on EVERY heading (numbered + un-numbered
# semantic), depth 1+. min_level=1 avoids bundling semantic subsections
# into a numbered parent (which yields oversized catch-all sections unfit
# for RAG); min_body_chars drops shells so it doesn't over-fragment.
# Direct `split_into_sections(min_level=None)` (numbered-only) is unchanged.
_DEFAULT_SPLIT_MIN_LEVEL: int | None = 1
_DEFAULT_NORMALIZE_HEADINGS = False
_DEFAULT_NORMALIZE_HEADINGS_MODE: NormalizeMode = "heuristic"
_DEFAULT_STRIP_FRONTMATTER = False
_DEFAULT_PROVENANCE = False


def _now_utc_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolved_flags_from_ctx(ctx: PipelineContext) -> dict[str, Any]:
    """The `resolved_flags` block stamped into `<output>/.pagespeak-run.json`,
    built from the fully-resolved context so re-run drift is a one-line file
    diff. Every value is a resolved `ctx` field, so the recorded flags match
    exactly what the pipeline ran."""
    return {
        "cleanup": ctx.cleanup,
        "cross_refs": ctx.cross_refs,
        "diagrams": ctx.diagrams,
        "vision_backend": ctx.vision_backend,
        "vision_model": ctx.vision_model,
        "vision_concurrency": ctx.vision_concurrency,
        "vision_cache_only": ctx.vision_cache_only,
        "preserve_alt": ctx.preserve_alt,
        "force_ocr": ctx.force_ocr,
        "device": ctx.device,
        "page_range": ctx.page_range,
        "html_base_url": ctx.html_base_url,
        "split_sections": ctx.split_sections,
        "nested_split": ctx.nested_split,
        "split_min_level": ctx.split_min_level,
        "split_max_level": ctx.split_max_level,
        "split_target_kb": ctx.split_target_kb,
        "english_only": ctx.english_only,
        "min_body_chars": ctx.min_body_chars,
        "regenerate_toc": ctx.regenerate_toc,
        "decoration_threshold": ctx.decoration_threshold,
        "decoration_hamming_distance": ctx.decoration_hamming_distance,
        "pdf_backend": ctx.pdf_backend,
        "repair_tables": ctx.repair_tables,
        "docx_backend": ctx.docx_backend,
        "docx_outline_heading_depth": ctx.docx_outline_heading_depth,
        "normalize_headings": ctx.normalize_headings,
        "normalize_headings_mode": ctx.normalize_headings_mode,
        "normalize_headings_model": ctx.normalize_headings_model,
        "strip_frontmatter": ctx.strip_frontmatter,
        "provenance": ctx.provenance,
        "source_type": ctx.source_type,
        "source_label": ctx.source_label,
    }


def _apply_preset_and_defaults(
    *,
    preset: str | None,
    cleanup: CleanupLevel | None,
    split_sections: bool | None,
    nested_split: bool | None,
    split_min_level: int | None,
    normalize_headings: bool | None,
    normalize_headings_mode: NormalizeModeOption | None,
    strip_frontmatter: bool | None,
    provenance: bool | None,
) -> tuple[CleanupLevel, bool, bool, int | None, bool, NormalizeModeOption, bool, bool]:
    """Resolve the preset-controlled flags. Explicit kwargs (non-None)
    win over preset values; preset values win over the original
    to_markdown defaults. Returns the resolved tuple.

    `split_min_level` is naturally None-able (None == "numbered headings
    only"), so it doesn't get the "user explicitly None" case — the only
    way to get the preset's value is to omit the kwarg entirely (which
    leaves it as None at this layer too). Acceptable trade-off; preset
    users opt out of `split_min_level` by passing 0 or a real depth.
    """
    if preset is not None:
        p = resolve_preset(preset)
        return (
            cleanup if cleanup is not None else p.cleanup,
            split_sections if split_sections is not None else p.split_sections,
            nested_split if nested_split is not None else p.nested_split,
            split_min_level if split_min_level is not None else p.split_min_level,
            normalize_headings if normalize_headings is not None else p.normalize_headings,
            normalize_headings_mode
            if normalize_headings_mode is not None
            else p.normalize_headings_mode,
            strip_frontmatter if strip_frontmatter is not None else p.strip_frontmatter,
            provenance if provenance is not None else p.provenance,
        )
    return (
        cleanup if cleanup is not None else _DEFAULT_CLEANUP,
        split_sections if split_sections is not None else _DEFAULT_SPLIT_SECTIONS,
        nested_split if nested_split is not None else _DEFAULT_NESTED_SPLIT,
        split_min_level if split_min_level is not None else _DEFAULT_SPLIT_MIN_LEVEL,
        normalize_headings if normalize_headings is not None else _DEFAULT_NORMALIZE_HEADINGS,
        normalize_headings_mode
        if normalize_headings_mode is not None
        else _DEFAULT_NORMALIZE_HEADINGS_MODE,
        strip_frontmatter if strip_frontmatter is not None else _DEFAULT_STRIP_FRONTMATTER,
        provenance if provenance is not None else _DEFAULT_PROVENANCE,
    )


def resolve_dir_mode_stem(input_dir: Path) -> str:
    """Resolve the bare doc stem from a dir-mode input directory.

    Globs for exactly one ``<stem>.raw.md`` and strips the double extension.
    This is the canonical site for stem extraction — both
    ``_resolve_directory_input`` and the CLI use it so the logic lives in
    exactly one place.

    Args:
        input_dir: The directory to inspect.

    Returns:
        The bare stem string (e.g. ``"doc"`` from ``"doc.raw.md"``).

    Raises:
        FileNotFoundError: No ``<stem>.raw.md`` found in the directory.
        ValueError: Multiple ``<stem>.raw.md`` files found.
    """
    raw_candidates = sorted(input_dir.glob("*.raw.md"))
    if not raw_candidates:
        raise FileNotFoundError(
            f"No <stem>.raw.md found in {input_dir}. "
            "Run `pagespeak ingest` first to produce the raw markdown checkpoint."
        )
    if len(raw_candidates) > 1:
        names = [p.name for p in raw_candidates]
        raise ValueError(
            f"Multiple .raw.md files found in {input_dir}: {names}. "
            "Pass the specific file as input instead of the directory."
        )
    return raw_candidates[0].name[: -len(".raw.md")]


def _resolve_directory_input(
    src_dir: Path,
    out: Path | None,
) -> tuple[Path, Path, str]:
    """Resolve directory-input mode.

    When ``to_markdown`` receives a directory, it must contain exactly one
    ``<stem>.raw.md`` file.  Returns ``(raw_md_path, out_dir, doc_stem)``
    where ``doc_stem`` is the bare stem (e.g. ``"doc"`` from ``"doc.raw.md"``).

    The caller substitutes ``doc_stem`` for ``src.stem`` wherever path names
    are constructed so that e.g. ``cleaned.md`` / ``normalized.md`` use the
    correct basename rather than the double-extension ``"<stem>.raw"``.

    Raises:
        FileNotFoundError: no ``.raw.md`` found.
        ValueError: multiple ``.raw.md`` found, or ``output_dir`` was
            supplied and doesn't match the input directory.
    """
    if out is not None and out.resolve() != src_dir.resolve():
        raise ValueError(
            "In directory-mode, output_dir must equal the input directory or be omitted. "
            f"Got input={src_dir}, output_dir={out}"
        )

    doc_stem = resolve_dir_mode_stem(src_dir)
    raw_md = src_dir / f"{doc_stem}.raw.md"
    return raw_md, src_dir, doc_stem
