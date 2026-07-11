"""Top-level `to_markdown()` dispatcher and format-suffix tables.

Lives in its own module so `__init__.py` stays a thin import/re-export shell.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pf_core.log import get_logger

from ..backends._docx_dispatch import DEFAULT_DOCX_BACKEND, DocxBackendName
from ..backends._pdf_dispatch import DEFAULT_PDF_BACKEND, PdfBackendName
from ..backends._qti import is_qti_export
from ..models._models import IngestResult
from ..services._cleanup import CleanupLevel, CrossRefs
from ..services._diagrams import VisionBackendName
from ..services._normalize_decision import NormalizeModeOption
from ._context import PipelineContext
from ._dispatch_setup import (
    _apply_preset_and_defaults,
    _now_utc_iso,
    _resolve_directory_input,
    resolved_flags_from_ctx,
)
from ._dispatch_setup import (
    resolve_dir_mode_stem as resolve_dir_mode_stem,
)
from ._ingest import PDF_SUFFIXES as _PDF_SUFFIXES
from ._ingest import ingest as _ingest_orchestrator
from ._phases import build_phases
from ._sequencer import run_pipeline

logger = get_logger(__name__)


def to_markdown(
    path: str | Path,
    *,
    output_dir: str | Path | None = None,
    preset: str | None = None,
    diagrams: bool = True,
    vision_backend: VisionBackendName | None = None,
    vision_model: str | None = None,
    vision_concurrency: int | None = None,
    vision_cache_only: bool = False,
    preserve_alt: bool = False,
    force_ocr: bool = False,
    device: str | None = None,
    page_range: str | list[int] | None = None,
    html_base_url: str | None = None,
    cleanup: CleanupLevel | None = None,
    cross_refs: CrossRefs | None = None,
    split_sections: bool | None = None,
    nested_split: bool | None = None,
    split_min_level: int | None = None,
    split_max_level: int | None = None,
    split_target_kb: int | None = None,
    min_body_chars: int | None = None,
    english_only: bool = False,
    regenerate_toc: bool = True,
    decoration_threshold: int | None = None,
    decoration_hamming_distance: int | None = None,
    pdf_backend: PdfBackendName = DEFAULT_PDF_BACKEND,
    pdf_backend_kwargs: dict[str, Any] | None = None,
    repair_tables: bool = False,
    docx_backend: DocxBackendName = DEFAULT_DOCX_BACKEND,
    docx_outline_heading_depth: int = 0,
    normalize_headings: bool | None = None,
    normalize_headings_mode: NormalizeModeOption | None = None,
    normalize_headings_model: str | None = None,
    strip_frontmatter: bool | None = None,
    provenance: bool | None = None,
    source_type: str | None = None,
    source_label: str | None = None,
    rerun_from: str | None = None,
    start: str | None = None,
    stop_after: str | None = None,
    workers: int = 1,
    answer_key: bool = True,
) -> IngestResult:
    """Convert a document to markdown, optionally enriching diagrams to Mermaid.

    Single-shot path; for ~500+ page PDFs run `pagespeak ingest --workers N`
    then `pagespeak convert <outdir>` (see `docs/ingest.md`). Full flag
    semantics live in `docs/usage.md` + CLI `--help`; these are the essentials.

    Args:
        path: Source document (format by extension), or — directory mode — an
            existing output dir holding one `<stem>.raw.md` (skips ingest).
        output_dir: Where images + checkpoints land (created if missing). None →
            no images written and `diagrams` has no effect.
        preset: Curated bundle (`"rag-default"`/`"flat"`/`"textbook"`/
            `"archival"`) setting the split/cleanup/normalize flags; explicit
            kwargs win. See `docs/presets.md`.
        diagrams: If True (+ `output_dir`), caption each image via a vision
            backend + embed Mermaid where applicable.
        vision_backend: `"anthropic"` (API) / `"claude_code"` ($0 local CLI) /
            `"openrouter"`; None → env/default.
        vision_model: Model override (else env, else haiku). `claude_code` → `--model`.
        vision_concurrency: Per-image worker-pool size (None → env, else 6).
        vision_cache_only: Use ONLY the on-disk `.vision-cache/` — zero backend
            calls; uncached images are skipped (caption-only) with a WARNING.
            ValueError if combined with `diagrams=False`.
        preserve_alt: Faithful mode — keep each figure's existing alt verbatim,
            append only Mermaid (the caption is cached, not injected).
        force_ocr: PDF-only. Force surya OCR even on text-bearing PDFs.
        device: PDF-only. Torch device (`"cpu"`/`"mps"`/`"cuda"`).
        page_range: PDF-only. `"0-19"` / `"0-3,5,7-9"` / `list[int]` / None.
        html_base_url: HTML-only. Base URL so relative `<img>` refs resolve.
        cleanup: `"off"`/`"basic"`/`"aggressive"`. See `docs/cleanup.md`.
        cross_refs: `"keep"`/`"strip"`/`"remap"` for page refs; None → manifest-aware.
        split_sections: Write per-section files under `<output_dir>/sections/`.
        nested_split: With `split_sections`, mirror the heading hierarchy.
        split_min_level: With `split_sections`, also split semantic headings at
            this depth+ (default: numbered only).
        split_max_level: With `split_sections`, cap section depth — headings
            deeper than this stay inline (default None: no cap). `2` gives one
            file per H2 with subsections inline (textbook section-level chunks).
        split_target_kb: With `split_sections`, size-targeted packing: each
            branch fitting this many KB becomes one file, oversized branches
            split deeper, oversized heading-less sections partition into
            `(part i of k)` files. Adapts per branch; mutually exclusive
            with `split_max_level` (default None: off).
        min_body_chars: Drop sections under this body-char count (default 30).
        regenerate_toc: Rebuild `## Table of Contents` from real headings (default True).
        decoration_threshold: Page-header/footer decoration cutoff (5; `0` off).
        decoration_hamming_distance: Phash grouping distance (default 12).
        pdf_backend: `"marker"` (default, fast) or `"docling"` (accuracy-first,
            needs `pagespeak[pdf-docling]`). See `docs/backends.md`.
        pdf_backend_kwargs: Backend-specific pipeline options.
        docx_backend: DOCX backend selection.
        docx_outline_heading_depth: Outline depth promoted to headings (0=off).
        normalize_headings: If True, fix flattened chapter/subsection levels
            after cleanup (textbooks Marker flattens). Opt-in.
        normalize_headings_mode: `"heuristic"` (default; free/deterministic) /
            `"llm"` / `"llm_full"` (body-anchored) / `"auto"` (classify per-doc).
            LLM modes cache under `.heading-normalize-cache/`.
        normalize_headings_model: Model override for the LLM modes (else env,
            else haiku); always fires (cost protection as `vision_model`).
        strip_frontmatter: DOCX-only. Drop everything before the first `# H1`
            when the lead matches ≥2 enterprise-template patterns. Opt-in.
        provenance: Emit provenance frontmatter (source tags + `doc_title` +
            per-section breadcrumbs) — the multi-source RAG enabler. Opt-in;
            `source_type`/`source_label` also enable it.
        source_type: Provenance tag (e.g. `"textbook"`); omitted when None.
        source_label: Human source title; auto-derived from the filename when
            omitted and frontmatter is on.
        rerun_from: Bust caches at this stage + downstream and re-run
            (`"ingest"`/`"cleanup"`/`"decorations"`/`"normalize"`/`"vision"`/
            `"split"`); None → use existing caches. See `docs/caching.md`.
        start: Begin at this phase from the existing upstream checkpoint (does
            NOT bust caches); errors if that checkpoint is absent.
        stop_after: Halt after this phase. `start == stop_after` runs exactly
            one phase; None → run to `split`.
        workers: Parallel backend-phase processes. `> 1` (file input) routes
            through chunked `ingest()` then re-enters for Phase 3; needs
            `output_dir`. Default 1.
        answer_key: QTI-only. Emit the answer key in the per-exam output.

    Returns:
        IngestResult with markdown, saved image paths, and diagram metadata.

    Raises:
        ValueError: unsupported extension or bad flag combination.
        ImportError: the detected format's backend isn't installed.
        FileNotFoundError: `path` doesn't exist.
    """
    if vision_cache_only and not diagrams:
        raise ValueError(
            "--vision-cache-only requires diagrams enabled: it injects cached "
            "descriptions. It is incompatible with --no-diagrams (which strips them)."
        )

    src = Path(path)
    src_arg = src  # stash before any resolution (needed for workers routing)
    out = Path(output_dir) if output_dir is not None else None

    # cross_refs defaults to "keep" unless the caller passed something
    # explicitly. We also track whether the default was applied so we can later
    # upgrade it to "remap" when a manifest.json is present (chunked input).
    if cross_refs is None:
        cross_refs = "keep"
        _cross_refs_was_default = True
    else:
        _cross_refs_was_default = False

    # detect a QTI export up front so the branches below skip it — a
    # QTI export fans out into one full-pipeline document per exam (handled
    # after flag resolution), never chunked or treated as an output dir.
    _qti_mode = is_qti_export(src)

    # workers > 1 routes the backend phase through ingest's chunked
    # path, then re-enters this function in directory-mode for Phase 3.
    if workers > 1 and not src_arg.is_dir() and not _qti_mode:
        if out is None:
            raise ValueError("workers > 1 requires output_dir to be specified")
        _ingest_orchestrator(
            input_path=src,
            output_dir=out,
            workers=workers,
            pdf_backend=pdf_backend,
            pdf_backend_kwargs=pdf_backend_kwargs,
            device=device,
            force_ocr=force_ocr,
        )
        return to_markdown(
            out,
            output_dir=out,
            preset=preset,
            diagrams=diagrams,
            vision_backend=vision_backend,
            vision_model=vision_model,
            vision_concurrency=vision_concurrency,
            vision_cache_only=vision_cache_only,
            preserve_alt=preserve_alt,
            cleanup=cleanup,
            cross_refs=cross_refs if not _cross_refs_was_default else None,
            split_sections=split_sections,
            nested_split=nested_split,
            split_min_level=split_min_level,
            split_max_level=split_max_level,
            split_target_kb=split_target_kb,
            min_body_chars=min_body_chars,
            regenerate_toc=regenerate_toc,
            decoration_threshold=decoration_threshold,
            decoration_hamming_distance=decoration_hamming_distance,
            docx_backend=docx_backend,
            docx_outline_heading_depth=docx_outline_heading_depth,
            normalize_headings=normalize_headings,
            normalize_headings_mode=normalize_headings_mode,
            normalize_headings_model=normalize_headings_model,
            strip_frontmatter=strip_frontmatter,
            provenance=provenance,
            source_type=source_type,
            source_label=source_label,
            rerun_from=rerun_from,
            start=start,
            stop_after=stop_after,
        )

    # validate rerun_from before any other checks so a bogus
    # stage error is reported even when the source path is wrong.
    if rerun_from is not None:
        from ..services._rerun import RERUN_STAGES

        if rerun_from not in RERUN_STAGES:
            raise ValueError(f"unknown rerun_from stage: {rerun_from!r}. Valid: {RERUN_STAGES}")

    # directory-input mode. When `path` is a directory, treat it
    # as an existing output dir whose `<stem>.raw.md` is the backend output.
    # Skip the backend phase entirely and jump straight to Phase 3.
    # A QTI export is also a directory (or a .imscc file), but it is a
    # *source* to convert (detected as `_qti_mode` above), so it never enters
    # dir-mode ("resume from an existing output dir").
    _dir_mode = src.is_dir() and not _qti_mode
    _doc_stem: str | None = None  # overrides src.stem in dir-mode
    if _dir_mode:
        src, out, _doc_stem = _resolve_directory_input(src, out)

    if not src.exists():
        raise FileNotFoundError(f"No such file: {src}")

    # auto-upgrade cross_refs to "remap" when a manifest.json is
    # present (signal: chunked/ingest input). Cross-chunk page anchors only
    # resolve after concatenation, so "remap" is the correct default for
    # that input shape. User-supplied values always win.
    if _cross_refs_was_default and out is not None and (out / "manifest.json").exists():
        cross_refs = "remap"
        logger.info("cross_refs_auto_remap reason=manifest_present output_dir=%s", out)

    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        # Cache invalidation. Missing files are silent no-ops.
        if rerun_from is not None:
            from ..services._rerun import invalidate_caches

            invalidate_caches(out, rerun_from, _doc_stem if _doc_stem is not None else src.stem)  # type: ignore[arg-type]

        # auto-snapshot the previous run when __version__
        # changed since it ran. Non-fatal — never blocks conversion.
        from .. import __version__
        from ..services._baseline import auto_snapshot_on_version_change

        auto_snapshot_on_version_change(out, current_version=__version__)

    # Resolve preset + defaults. `preset=` (None by default)
    # supplies values for the preset-controlled flags; per-flag kwargs
    # the caller passed explicitly (non-None) win over the preset.
    # Without `preset=`, fall back to the original to_markdown defaults.
    started_at = _now_utc_iso()

    # Open the per-conversion LLM-call accumulator: every `invoke_agent` call
    # (vision + heading normalize) appends a record, drained at the end into
    # `.pagespeak-run.json`. Also stamp `source_basename` into the session
    # metadata so every call's `llm_run_tags` attributes to this input doc —
    # with the per-call `image_phash`, that gives full caption provenance.
    from .._agent_runtime import begin_call_recording

    _src = Path(path)
    begin_call_recording(session_metadata={"source_basename": _src.name})
    (
        cleanup,
        split_sections,
        nested_split,
        split_min_level,
        normalize_headings,
        normalize_headings_mode,
        strip_frontmatter,
        provenance,
    ) = _apply_preset_and_defaults(
        preset=preset,
        cleanup=cleanup,
        split_sections=split_sections,
        nested_split=nested_split,
        split_min_level=split_min_level,
        normalize_headings=normalize_headings,
        normalize_headings_mode=normalize_headings_mode,
        strip_frontmatter=strip_frontmatter,
        provenance=provenance,
    )

    # a QTI export fans out into one independent full-pipeline document
    # per exam. Delegate to the fan-out orchestrator (each exam runs its own
    # to_markdown in dir-mode). Drain this export-level call accumulator first
    # — the per-exam runs open and drain their own.
    if _qti_mode:
        from .._agent_runtime import end_call_recording

        end_call_recording()
        if out is None:
            raise ValueError("QTI conversion requires an output directory (-o).")
        from ._qti_export import run_qti_export

        return run_qti_export(
            src,
            out,
            diagrams=diagrams,
            cleanup=cleanup,
            vision_backend=vision_backend,
            vision_model=vision_model,
            vision_concurrency=vision_concurrency,
            vision_cache_only=vision_cache_only,
            source_type=source_type,
            source_label=source_label,
            answer_key=answer_key,
        )

    # In dir-mode, use the extracted doc_stem so checkpoint / snapshot paths
    # use the correct basename (e.g. "doc", not "doc.raw").
    effective_stem = _doc_stem if _doc_stem is not None else src.stem

    # The Top Hat backend produces a `# title` + `## Question N` quiz; default
    # its source_type to "quiz" so the split phase emits rich per-question
    # provenance frontmatter (quiz / quiz_id / question_number / question_type)
    # without the caller having to pass --source-type. Explicit values win.
    if pdf_backend == "tophat" and source_type is None:
        source_type = "quiz"

    suffix = src.suffix.lower()
    raw_md_path = out / f"{effective_stem}.raw.md" if out is not None else None
    cleaned_md_path = out / f"{effective_stem}.cleaned.md" if out is not None else None
    normalized_md_path = out / f"{effective_stem}.normalized.md" if out is not None else None
    repaired_md_path = out / f"{effective_stem}.repaired.md" if out is not None else None
    structured_md_path = out / f"{effective_stem}.structured.md" if out is not None else None
    visioned_md_path = out / f"{effective_stem}.visioned.md" if out is not None else None

    # === Phase pipeline ==================================================
    # A list of independently-runnable `Phase` objects sequenced by
    # `run_pipeline`. Thin adapter: build the context, run the phases, hand
    # the result to the teardown below. `rerun_from` is NOT passed to the
    # sequencer — its cache invalidation already ran in the preamble and
    # each phase fast-paths via the surviving checkpoint.
    if _dir_mode:
        source_format = "raw"
    elif suffix in _PDF_SUFFIXES:
        source_format = "pdf"
    else:
        source_format = suffix.lstrip(".") or "unknown"
    ctx = PipelineContext(
        src=src,
        out=out,
        dir_mode=_dir_mode,
        doc_stem=_doc_stem,
        effective_stem=effective_stem,
        suffix=suffix,
        source_format=source_format,
        raw_md_path=raw_md_path,
        cleaned_md_path=cleaned_md_path,
        normalized_md_path=normalized_md_path,
        repaired_md_path=repaired_md_path,
        structured_md_path=structured_md_path,
        visioned_md_path=visioned_md_path,
        diagrams=diagrams,
        vision_backend=vision_backend,
        vision_model=vision_model,
        vision_concurrency=vision_concurrency,
        vision_cache_only=vision_cache_only,
        preserve_alt=preserve_alt,
        force_ocr=force_ocr,
        device=device,
        page_range=page_range,
        html_base_url=html_base_url,
        cleanup=cleanup,
        cross_refs=cross_refs,
        split_sections=split_sections,
        nested_split=nested_split,
        split_min_level=split_min_level,
        split_max_level=split_max_level,
        split_target_kb=split_target_kb,
        min_body_chars=min_body_chars,
        english_only=english_only,
        regenerate_toc=regenerate_toc,
        decoration_threshold=decoration_threshold,
        decoration_hamming_distance=decoration_hamming_distance,
        pdf_backend=pdf_backend,
        pdf_backend_kwargs=pdf_backend_kwargs,
        repair_tables=repair_tables,
        docx_backend=docx_backend,
        docx_outline_heading_depth=docx_outline_heading_depth,
        normalize_headings=normalize_headings,
        normalize_headings_mode=normalize_headings_mode,
        normalize_headings_model=normalize_headings_model,
        strip_frontmatter=strip_frontmatter,
        provenance=provenance,
        source_type=source_type,
        source_label=source_label,
        start_phase=start,
    )
    run_pipeline(build_phases(), ctx=ctx, start=start, stop_after=stop_after)
    if ctx.result is None:  # ingest phase always sets it
        raise RuntimeError("pipeline produced no result")
    result = ctx.result
    section_count = ctx.section_count

    # drain the per-conversion LLM-call accumulator. Always
    # drain (even if `out is None`) so the module-level list doesn't
    # leak into the next call.
    from .._agent_runtime import end_call_recording

    llm_call_records = end_call_recording()

    # stamp the resolved config into <output>/.pagespeak-run.json
    # so re-run drift is diagnosable as a one-line file diff. Failures
    # are non-fatal — a successful conversion shouldn't be killed by an
    # unwritable output dir.
    if out is not None:
        from .. import __version__
        from ..services._provenance import persistable_source_identity
        from ..services._run_record import summarize_llm_calls, write_run_record

        finished_at = _now_utc_iso()
        resolved_flags = resolved_flags_from_ctx(ctx)
        # The run record SHA-256s the input as a file. A QTI export can be a
        # directory — record its manifest (a stable per-export fingerprint).
        record_input = src
        if _qti_mode and src.is_dir():
            record_input = src / "imsmanifest.xml"
        # Resolve BEFORE writing: dir-mode reads the prior record to carry the
        # original source identity forward (this run's `input` is a checkpoint).
        source_identity = (
            None if _qti_mode else persistable_source_identity(src, out, dir_mode=_dir_mode)
        )
        try:
            write_run_record(
                out,
                version=__version__,
                preset=preset,
                resolved_flags=resolved_flags,
                input_path=record_input,
                started_at=started_at,
                finished_at=finished_at,
                section_count=section_count,
                image_count=len(result.images),
                llm_calls=summarize_llm_calls(llm_call_records),
                source_identity=source_identity,
            )
        except OSError as e:
            logger.warning("run_record_write_failed path=%s error=%s", out, e)

    return result
