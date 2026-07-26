"""The concrete pipeline phases.

Each class is one pipeline stage: it reads its input checkpoint, runs its
transforms, and writes its output checkpoint (with internal resume). The
sequencer drives them in order and supports single-phase execution.

Phase order (`services._rerun.RERUN_STAGES` minus the `decorations` sub-step):
    ingest → cleanup → normalize → repair → structure → vision → split
"""

from __future__ import annotations

from pathlib import Path

from pf_core.log import get_logger

from ..models._models import IngestResult
from ._context import PipelineContext
from ._phase import Phase
from ._resume import _try_resume_from_checkpoint, _try_resume_from_cleaned

logger = get_logger(__name__)


# Suffix tables — imported at module load from the ingest module.
from ._ingest import MARKDOWN_SUFFIXES as _MARKDOWN_SUFFIXES  # noqa: E402
from ._ingest import MARKITDOWN_SUFFIXES as _MARKITDOWN_SUFFIXES  # noqa: E402
from ._ingest import PDF_SUFFIXES as _PDF_SUFFIXES  # noqa: E402
from ._ingest import unsupported_format_error  # noqa: E402


def _require_result(ctx: PipelineContext) -> IngestResult:
    """Phases after ingest assume the result exists. Make that explicit
    for mypy and fail loudly if the sequencer ran them out of order."""
    if ctx.result is None:
        raise RuntimeError("phase ran before ingest produced a result")
    return ctx.result


def _load_input(c: PipelineContext, checkpoint: Path | None) -> None:
    """Hydrate `c.result` from this phase's INPUT checkpoint when an earlier
    phase didn't run (single-phase / `--from` start); no-op in a full run."""
    if c.result is not None:
        return
    if checkpoint is None or not checkpoint.exists():
        raise RuntimeError(
            f"cannot start this phase: required input checkpoint missing: {checkpoint}. "
            "Run the upstream phase(s) first."
        )
    images_dir = c.out / "images" if c.out is not None else None
    images = sorted(images_dir.glob("*")) if images_dir and images_dir.exists() else []
    c.result = IngestResult(
        markdown=checkpoint.read_text(encoding="utf-8"),
        images=images,
        source_format=c.source_format,
    )


def _maybe_repair_tables(c: PipelineContext, markdown: str) -> str:
    """Opt-in (`--repair-tables`) ingest sub-step: replace `<br>`-collapsed
    mega-cells with Docling's grid for the same PDF page. Marker-PDF only."""
    if not c.repair_tables or c.pdf_backend != "marker" or c.suffix not in _PDF_SUFFIXES:
        return markdown
    from ..services._table_repair import repair_tables_in_markdown

    try:
        repaired, records = repair_tables_in_markdown(markdown, str(c.src))
    except ImportError:
        logger.warning(
            "repair_tables: collapsed table(s) found but Docling is not installed "
            "(`pip install pagespeak[pdf-docling]`); leaving tables as-is"
        )
        return markdown
    if records:
        n = sum(1 for r in records if r.status == "repaired")
        logger.info("repair_tables: repaired %d of %d collapsed table(s)", n, len(records))
    return repaired


class IngestPhase:
    """Backend (or raw.md resume) → `<stem>.raw.md`."""

    name = "ingest"

    def is_fresh(self, ctx: object) -> bool:
        # Resume is handled inside run(); it fast-paths via the raw checkpoint.
        return False

    def run(self, ctx: object) -> None:
        from ..services._hierarchy_trust import record_hierarchy_source, record_structured

        c = _ctx(ctx)
        src, out, raw_md_path = c.src, c.out, c.raw_md_path
        if c.dir_mode:
            result = _try_resume_from_checkpoint(
                src, out, raw_md_path, source_format=c.source_format
            )
            if result is None:
                images_dir = out / "images" if out is not None else None
                images = sorted(images_dir.glob("*")) if images_dir and images_dir.exists() else []
                result = IngestResult(
                    markdown=src.read_text(encoding="utf-8"),
                    images=images,
                    source_format="raw",
                )
        else:
            result = _try_resume_from_checkpoint(
                src, out, raw_md_path, source_format=c.source_format
            )

        if result is None:
            suffix = c.suffix
            if suffix in _PDF_SUFFIXES:
                from ..backends._pdf_dispatch import convert as _pdf_convert

                result = _pdf_convert(
                    c.pdf_backend,  # type: ignore[arg-type]
                    src,
                    output_dir=out,
                    force_ocr=c.force_ocr,
                    device=c.device,
                    page_range=c.page_range,
                    heading_hierarchy=c.heading_hierarchy,
                    backend_kwargs=c.pdf_backend_kwargs,
                )
            elif suffix in _MARKITDOWN_SUFFIXES:
                if suffix == ".docx":
                    from ..backends._docx_dispatch import convert as _docx_convert

                    result = _docx_convert(
                        c.docx_backend,  # type: ignore[arg-type]
                        src,
                        output_dir=out,
                        outline_heading_depth=c.docx_outline_heading_depth,
                    )
                else:
                    from ..backends._docx import convert_with_markitdown

                    result = convert_with_markitdown(
                        src, output_dir=out, html_base_url=c.html_base_url
                    )
            elif suffix in _MARKDOWN_SUFFIXES:
                from ..backends._markdown import convert_markdown

                result = convert_markdown(src)
            else:
                raise unsupported_format_error(suffix)

            result.markdown = _maybe_repair_tables(c, result.markdown)
            # Co-locate sibling images so vision's out/images glob sees them.
            if out is not None and (suffix in _MARKITDOWN_SUFFIXES or suffix in _MARKDOWN_SUFFIXES):
                from ..backends._local_images import localize_local_images_in_markdown

                result.markdown, result.images = localize_local_images_in_markdown(
                    result.markdown, out, source_path=src, images=result.images
                )
            if raw_md_path is not None:
                raw_md_path.write_text(result.markdown, encoding="utf-8")
            # Only the run that produced raw.md may claim its structure; a
            # resume rehydrates the flag to False and would clear a true one.
            record_structured(out, authoritative=result.structure_authoritative)

        # Stamp provenance now: a resume run resolves src to a checkpoint.
        record_hierarchy_source(
            out, src, pdf_backend=c.pdf_backend, heading_hierarchy=c.heading_hierarchy
        )

        c.result = result


class CleanupPhase:
    """Resume-from-cleaned, else frontmatter + decoration + cleanup →
    `<stem>.cleaned.md`."""

    name = "cleanup"

    def is_fresh(self, ctx: object) -> bool:
        return False  # internal resume preserved; see IngestPhase note

    def run(self, ctx: object) -> None:
        c = _ctx(ctx)
        _load_input(c, c.raw_md_path)  # input: raw.md (single-phase start)
        result = _require_result(c)
        # `--from cleanup` means "run cleanup". Skip the resume-from-cleaned
        # shortcut when cleanup is the explicit start phase, else per-stage
        # iteration silently reuses a stale cached cleaned.md and the cleanup
        # code under test never actually runs. (A plain `--stop-after cleanup`
        # WITHOUT `--from` is a normal run halting early — it still resumes.)
        if c.start_phase != "cleanup":
            cached_cleaned = _try_resume_from_cleaned(
                c.out,
                c.raw_md_path,
                c.cleaned_md_path,
                current_flags={
                    "cleanup": c.cleanup,
                    "cross_refs": c.cross_refs,
                    "strip_frontmatter": c.strip_frontmatter,
                    "decoration_threshold": c.decoration_threshold,
                    "decoration_hamming_distance": c.decoration_hamming_distance,
                },
            )
            if cached_cleaned is not None:
                logger.info("resume_from_cleaned path=%s", c.cleaned_md_path)
                result.markdown = cached_cleaned
                return

        # Localize remote + local-sibling image refs for sources that skipped
        # ingest's pass (markdown / dir-mode resume); idempotent when already done.
        if c.out is not None:
            from ..backends._local_images import localize_local_images_in_markdown
            from ..backends._remote_images import localize_remote_images_in_markdown

            result.markdown, result.images = localize_remote_images_in_markdown(
                result.markdown, c.out, images=result.images
            )
            result.markdown, result.images = localize_local_images_in_markdown(
                result.markdown, c.out, source_path=c.src, images=result.images
            )

        if c.strip_frontmatter and c.suffix in _MARKITDOWN_SUFFIXES:
            from ..services._frontmatter import (
                count_frontmatter_patterns,
                strip_template_frontmatter,
            )

            stripped, dropped_chars = strip_template_frontmatter(result.markdown)
            if dropped_chars:
                logger.info(
                    "frontmatter_stripped chars=%d patterns_matched=%d",
                    dropped_chars,
                    count_frontmatter_patterns(result.markdown[:dropped_chars]),
                )
            result.markdown = stripped

        if result.images and c.out is not None:
            from ..services._decorations import detect_and_strip_decorations

            result.markdown = detect_and_strip_decorations(
                result.markdown,
                images=result.images,
                threshold=c.decoration_threshold,
                hamming_distance=c.decoration_hamming_distance,
            )

        if c.cleanup != "off":
            from ..services._cleanup import cleanup_markdown
            from ..services._hierarchy_trust import hierarchy_is_trusted, record_outline_promoted

            # Same invariant as repair. `trusted_structure` alone reads only the
            # DOCX reader's claim, which no PDF ever sets.
            _cleanup_stats: dict[str, int] = {}
            result.markdown = cleanup_markdown(
                result.markdown,
                level=c.cleanup,
                cross_refs=c.cross_refs,
                stats=_cleanup_stats,
                structure_authoritative=hierarchy_is_trusted(
                    c.src,
                    c.out,
                    pdf_backend=c.pdf_backend,
                    heading_hierarchy=c.heading_hierarchy,
                    in_memory=result.structure_authoritative,
                ),
            )
            # Repair runs separately and cannot see cleanup's locals.
            record_outline_promoted(c.out, promoted=_cleanup_stats.get("outline_promoted", 0) > 0)

        if c.cleaned_md_path is not None:
            c.cleaned_md_path.write_text(result.markdown, encoding="utf-8")


class NormalizePhase:
    """Heading-level normalize (opt-in) → `<stem>.normalized.md`."""

    name = "normalize"

    def is_fresh(self, ctx: object) -> bool:
        return False  # always wrote normalized.md in the monolith

    def run(self, ctx: object) -> None:
        c = _ctx(ctx)
        _load_input(c, c.cleaned_md_path)  # input: cleaned.md
        result = _require_result(c)
        if c.do_normalize and c.out is not None:
            from ..services._heading_normalize import (
                apply_normalization,
                gather_normalize_levels,
            )
            from ..services._normalize_decision import (
                resolve_normalize_mode,
                route_authoritative_hierarchy,
            )

            mode = c.normalize_headings_mode
            if mode == "auto":
                mode = resolve_normalize_mode(result.markdown)
            # Re-leveling rewrites depths an outline-derived source stated —
            # but only when coherent, hence the markdown.
            mode = route_authoritative_hierarchy(
                mode,
                c.src,
                pdf_backend=c.pdf_backend,
                heading_hierarchy=c.heading_hierarchy,
                out=c.out,
                markdown=result.markdown,
            )

            normalize_handoff = gather_normalize_levels(
                result.markdown,
                mode=mode,  # "auto" already resolved to a concrete mode above
                cache_dir=c.out / ".heading-normalize-cache",
                model=c.normalize_headings_model,
            )
            result.markdown = apply_normalization(result.markdown, normalize_handoff)

        if c.normalized_md_path is not None:
            c.normalized_md_path.write_text(result.markdown, encoding="utf-8")


class RepairPhase:
    """Post-LLM $0 heading repair → `<stem>.repaired.md`. No LLM call."""

    name = "repair"

    def is_fresh(self, ctx: object) -> bool:
        return False

    def run(self, ctx: object) -> None:
        c = _ctx(ctx)
        _load_input(c, c.normalized_md_path)  # input: normalized.md
        result = _require_result(c)
        # Never second-guess a hierarchy the source itself stated.
        from ..services._hierarchy_trust import hierarchy_is_trusted
        from ..services._normalize_repair import repair_headings

        trusted = hierarchy_is_trusted(
            c.src,
            c.out,
            pdf_backend=c.pdf_backend,
            heading_hierarchy=c.heading_hierarchy,
            in_memory=result.structure_authoritative,
        )
        result.markdown, counts = repair_headings(result.markdown, is_outline_doc=trusted)
        applied = {k: v for k, v in counts.items() if v}
        if applied:
            logger.info("repair_headings_applied %s", applied)
        if c.repaired_md_path is not None:
            c.repaired_md_path.write_text(result.markdown, encoding="utf-8")


class StructurePhase:
    """Holistic doc-level structural passes → `<stem>.structured.md`.

    $0 passes over the whole heading distribution, which no per-line cleanup
    pass can reach: flat-source exports publish every article as a sibling
    `# `. Composes small utilities from `services/`."""

    name = "structure"

    def is_fresh(self, ctx: object) -> bool:
        return False

    def run(self, ctx: object) -> None:
        c = _ctx(ctx)
        _load_input(c, c.repaired_md_path)  # input: repaired.md
        result = _require_result(c)

        from ..services._hierarchy_trust import has_authoritative_hierarchy
        from ..services._structure_passes import apply_structure_passes

        result.markdown = apply_structure_passes(
            result.markdown,
            trusted=has_authoritative_hierarchy(
                c.src,
                pdf_backend=c.pdf_backend,
                heading_hierarchy=c.heading_hierarchy,
                out=c.out,
                in_memory=result.structure_authoritative,
            ),
        )

        if c.structured_md_path is not None:
            c.structured_md_path.write_text(result.markdown, encoding="utf-8")


class VisionPhase:
    """Vision gather + inject (cached by phash) + TOC regen."""

    name = "vision"

    def is_fresh(self, ctx: object) -> bool:
        return False

    def run(self, ctx: object) -> None:
        c = _ctx(ctx)
        _load_input(c, c.structured_md_path)  # input: structured.md (post-structure)
        result = _require_result(c)
        if c.do_vision:
            from ..services._diagrams import (
                alt_text_by_basename,
                gather_diagrams,
                inject_diagrams,
            )

            c.diagrams_handoff = gather_diagrams(
                result.images,
                backend_name=c.vision_backend,  # type: ignore[arg-type]
                model=c.vision_model,
                cache_dir=c.out / ".vision-cache" if c.out is not None else None,
                concurrency=c.vision_concurrency,
                cache_only=c.vision_cache_only,
                # The figure's existing source alt text → the alt-aware prompt
                # (correct/keep/enrich). Read from the structured checkpoint
                # before inject overwrites the refs.
                alt_by_basename=alt_text_by_basename(result.markdown),
            )
            result.markdown = inject_diagrams(
                result.markdown, c.diagrams_handoff, preserve_alt=c.preserve_alt
            )
            result.diagrams = sorted(c.diagrams_handoff.values(), key=lambda d: d.image_path.name)

        if c.regenerate_toc:
            from ..services._toc import regenerate_toc as _regen_toc

            result.markdown = _regen_toc(result.markdown)

        # Degrade any image ref whose local target is missing on disk into its
        # alt text (an italic caption): a broken `![alt](missing)` link becomes
        # the RAG-usable description. Runs regardless of `do_vision` — vision
        # resolves refs whose images exist; this handles the rest. Applied
        # before the checkpoint so the master AND split `sections/` inherit it.
        if c.out is not None:
            from ..services._image_refs import degrade_missing_image_refs

            result.markdown, n_degraded = degrade_missing_image_refs(
                result.markdown, base_dir=c.out
            )
            if n_degraded:
                logger.info("degraded %d dangling image ref(s) to caption text", n_degraded)

        # Vision's output checkpoint: post-inject + post-TOC markdown. Written
        # even when both were no-ops, so `--from split` always has an input.
        if c.visioned_md_path is not None:
            c.visioned_md_path.write_text(result.markdown, encoding="utf-8")


class SplitPhase:
    """Per-section split → `sections/` + `INDEX.md` (opt-in)."""

    name = "split"

    def is_fresh(self, ctx: object) -> bool:
        return False

    def run(self, ctx: object) -> None:
        c = _ctx(ctx)
        _load_input(c, c.visioned_md_path)  # input: visioned.md
        result = _require_result(c)

        # Sections + master-doc frontmatter. Both split the frontmatter-free
        # clean text, so re-runs are idempotent.
        from ._split_output import write_sections

        write_sections(c, result)


def _ctx(ctx: object) -> PipelineContext:
    assert isinstance(ctx, PipelineContext)
    return ctx


def build_phases() -> list[Phase]:
    """The ordered pipeline. Index == `RERUN_STAGES` order (minus the
    `decorations` sub-step, which lives inside `cleanup` as it always
    has — promoting it to a standalone reordered checkpoint is a
    separate, explicitly behaviour-changing step, NOT this one)."""
    phases: list[Phase] = [
        IngestPhase(),
        CleanupPhase(),
        NormalizePhase(),
        RepairPhase(),
        StructurePhase(),
        VisionPhase(),
        SplitPhase(),
    ]
    return phases


__all__ = [
    "CleanupPhase",
    "IngestPhase",
    "NormalizePhase",
    "RepairPhase",
    "SplitPhase",
    "StructurePhase",
    "VisionPhase",
    "build_phases",
]
