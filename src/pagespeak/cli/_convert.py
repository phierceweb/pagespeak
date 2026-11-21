"""pagespeak convert subcommand."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import typer

from .. import to_markdown
from ..backends._docx_dispatch import DocxBackendName
from ..backends._pdf_dispatch import PdfBackendName
from ..backends._qti import is_qti_export
from ..orchestrators._chunk_sizing import resolve_cli_workers
from ..orchestrators._ingest import PartialIngestError
from ..services._cleanup import CleanupLevel, CrossRefs
from ..services._diagrams import VisionBackendName
from ..services._normalize_decision import NormalizeModeOption
from . import _convert_options_run as run_opts
from . import _convert_options_source as source_opts
from ._backend_kwargs import parse_backend_kwargs
from ._convert_report import report_result
from ._inherit import (
    INHERITABLE_FLAGS,
    _is_commandline_source,
    apply_run_record_defaults,
    explicit_command_line_params,
)


def register(
    app: typer.Typer,
    *,
    validate_cleanup: Callable[[str], str],
    validate_cross_refs: Callable[[str], str],
    validate_vision_backend: Callable[[str], str],
    validate_pdf_backend: Callable[[str], str],
    validate_normalize_mode: Callable[[str], str],
    validate_preset: Callable[[str | None], str | None],
    validate_normalize_headings_backend: Callable[[str | None], str | None],
) -> None:
    """Register the convert subcommand on `app`."""

    @app.command("convert")
    def convert(
        ctx: typer.Context,
        input_path: Path = source_opts.INPUT_PATH,
        output_dir: Path = source_opts.OUTPUT_DIR,
        preset: str | None = source_opts.PRESET,
        diagrams: bool = run_opts.DIAGRAMS,
        vision_backend: str | None = run_opts.VISION_BACKEND,
        vision_model: str | None = run_opts.VISION_MODEL,
        vision_concurrency: int | None = run_opts.VISION_CONCURRENCY,
        vision_cache_only: bool = run_opts.VISION_CACHE_ONLY,
        vision_all_images: bool = run_opts.VISION_ALL_IMAGES,
        preserve_alt: bool = run_opts.PRESERVE_ALT,
        force_ocr: bool = source_opts.FORCE_OCR,
        device: str | None = source_opts.DEVICE,
        page_range: str | None = source_opts.PAGE_RANGE,
        html_base_url: str | None = source_opts.HTML_BASE_URL,
        cleanup: str = source_opts.CLEANUP,
        cross_refs: str = source_opts.CROSS_REFS,
        split_sections: bool = run_opts.SPLIT_SECTIONS,
        nested_split: bool = run_opts.NESTED_SPLIT,
        split_min_level: int | None = run_opts.SPLIT_MIN_LEVEL,
        split_max_level: int | None = run_opts.SPLIT_MAX_LEVEL,
        split_target_kb: int | None = run_opts.SPLIT_TARGET_KB,
        min_body_chars: int | None = run_opts.MIN_BODY_CHARS,
        english_only: bool = run_opts.ENGLISH_ONLY,
        pdf_backend: str = source_opts.PDF_BACKEND,
        heading_hierarchy: bool = source_opts.HEADING_HIERARCHY,
        pdf_backend_kwargs: str | None = source_opts.PDF_BACKEND_KWARGS,
        decoration_threshold: int | None = source_opts.DECORATION_THRESHOLD,
        decoration_hamming_distance: int | None = source_opts.DECORATION_HAMMING_DISTANCE,
        repair_tables: bool = source_opts.REPAIR_TABLES,
        docx_backend: str = source_opts.DOCX_BACKEND,
        docx_outline_heading_depth: int = source_opts.DOCX_OUTLINE_HEADING_DEPTH,
        normalize_headings: bool = run_opts.NORMALIZE_HEADINGS,
        normalize_headings_mode: str = run_opts.NORMALIZE_HEADINGS_MODE,
        normalize_headings_model: str | None = run_opts.NORMALIZE_HEADINGS_MODEL,
        normalize_headings_backend: str | None = run_opts.NORMALIZE_HEADINGS_BACKEND,
        strip_frontmatter: bool = source_opts.STRIP_FRONTMATTER,
        provenance: bool = run_opts.PROVENANCE,
        source_type: str | None = run_opts.SOURCE_TYPE,
        source_label: str | None = run_opts.SOURCE_LABEL,
        inherit: bool = run_opts.INHERIT,
        rerun_from: str | None = run_opts.RERUN_FROM,
        start: str | None = run_opts.START,
        stop_after: str | None = run_opts.STOP_AFTER,
        workers: int | None = run_opts.WORKERS,
        answer_key: bool = source_opts.ANSWER_KEY,
        allow_partial_ingest: bool = run_opts.ALLOW_PARTIAL_INGEST,
    ) -> None:
        """Convert a document to LLM-friendly markdown.

        Single-process by default (--workers 1). Pass --workers N to use
        parallel chunked ingest for very large PDFs."""
        # validate only if the user passed --vision-backend.
        # When unset (None), `to_markdown` defers to `PAGESPEAK_VISION_BACKEND`
        # env var (via `gather_diagrams` → `_agent_runtime.resolve_backend`),
        # which falls back to `claude_code`. Same shape as
        # `--normalize-headings-backend` validation below.
        if vision_backend is not None:
            vision_backend = validate_vision_backend(vision_backend)
        preset = validate_preset(preset)

        # --normalize-headings-backend writes every normalize mode's per-task
        # env var before `to_markdown` runs, so `_agent_runtime.resolve_backend`
        # applies it to whichever mode is active.
        normalize_headings_backend = validate_normalize_headings_backend(normalize_headings_backend)
        if normalize_headings_backend is not None:
            import os as _os

            for task in ("HEADING_NORMALIZE", "HEADING_NORMALIZE_FULL", "HEADING_NORMALIZE_DEHEAD"):
                _os.environ[f"PAGESPEAK_{task}_BACKEND"] = normalize_headings_backend
        if rerun_from is not None:
            from ..services._rerun import RERUN_STAGES

            if rerun_from not in RERUN_STAGES:
                raise typer.BadParameter(
                    f"--rerun-from must be one of {RERUN_STAGES}; got {rerun_from!r}"
                )

        # --from / --stop-after validate against the actual phase list
        # (no "decorations" — it's a sub-step of cleanup, not a phase).
        _PHASES = ("ingest", "cleanup", "normalize", "repair", "structure", "vision", "split")
        for _label, _val in (("--from", start), ("--stop-after", stop_after)):
            if _val is not None and _val not in _PHASES:
                raise typer.BadParameter(f"{_label} must be one of {_PHASES}; got {_val!r}")

        # in directory-input mode, the dispatcher requires
        # output_dir == input_path. If the user didn't pass --output-dir
        # explicitly, override the default `./out` with the input dir so
        # `pagespeak convert <outdir>` works without manually re-typing
        # the path with `-o`.
        # A QTI export is a directory too, but it's a SOURCE, not an output
        # dir — exclude it from the resume-from-output-dir convenience.
        if input_path.is_dir() and not is_qti_export(input_path):
            try:
                output_dir_source = ctx.get_parameter_source("output_dir")
            except (AttributeError, TypeError):
                output_dir_source = None
            if not _is_commandline_source(output_dir_source):
                output_dir = input_path

        # QTI exports: don't run the vision LLM on the copied figures unless
        # the user explicitly asked (cost-safety) — default to alt-text only.
        if is_qti_export(input_path):
            try:
                _diag_src = ctx.get_parameter_source("diagrams")
            except (AttributeError, TypeError):
                _diag_src = None
            if not _is_commandline_source(_diag_src):
                diagrams = False

        # Which params came from the command line: the run record must never
        # override an explicit flag, nor a preset-controlled flag when
        # --preset itself is explicit. Non-explicit preset-controlled flags
        # stay None toward `to_markdown` so its preset+default resolver picks
        # the value — unless the record supplies one below.
        explicit = explicit_command_line_params(ctx, INHERITABLE_FLAGS + ("preset",))

        # Run-record inheritance: unspecified flags default to the previous
        # run's resolved_flags (a bare --rerun-from used to wipe sections/
        # and never rebuild it). A QTI export is a source dir, never a
        # re-run target.
        inherited: dict[str, Any] = {}
        if inherit and not is_qti_export(input_path):
            inherited = apply_run_record_defaults(
                output_dir=output_dir,
                explicit=explicit,
                validators={
                    "cleanup": validate_cleanup,
                    "cross_refs": validate_cross_refs,
                    "normalize_headings_mode": validate_normalize_mode,
                    "pdf_backend": validate_pdf_backend,
                },
                echo=typer.echo,
            )

        def _flag(name: str, fallback: Any) -> Any:
            return inherited.get(name, fallback)

        cross_refs = validate_cross_refs(_flag("cross_refs", cross_refs))
        pdf_backend = validate_pdf_backend(_flag("pdf_backend", pdf_backend))
        # Resolved, not raw: these three also arrive by run-record inheritance,
        # and the chunked path drops whichever way they got here.
        page_range = _flag("page_range", page_range)
        english_only = _flag("english_only", english_only)
        repair_tables = _flag("repair_tables", repair_tables)

        cleanup_val = _flag("cleanup", cleanup if "cleanup" in explicit else None)
        cleanup_arg: CleanupLevel | None = None
        if cleanup_val is not None:
            cleanup_arg = cast(CleanupLevel, validate_cleanup(cleanup_val))

        nh_mode_val = _flag(
            "normalize_headings_mode",
            normalize_headings_mode if "normalize_headings_mode" in explicit else None,
        )
        nh_mode_arg: NormalizeModeOption | None = None
        if nh_mode_val is not None:
            nh_mode_arg = cast(NormalizeModeOption, validate_normalize_mode(nh_mode_val))

        try:
            result = to_markdown(
                input_path,
                output_dir=output_dir,
                preset=preset,
                diagrams=diagrams,
                vision_backend=(
                    cast(VisionBackendName, vision_backend) if vision_backend is not None else None
                ),
                vision_model=vision_model,
                vision_concurrency=vision_concurrency,
                vision_cache_only=vision_cache_only,
                vision_all_images=vision_all_images,
                preserve_alt=preserve_alt,
                force_ocr=_flag("force_ocr", force_ocr),
                device=device,
                page_range=page_range,
                html_base_url=_flag("html_base_url", html_base_url),
                cleanup=cleanup_arg,
                cross_refs=cast(CrossRefs, cross_refs),
                split_sections=_flag(
                    "split_sections", split_sections if "split_sections" in explicit else None
                ),
                nested_split=_flag(
                    "nested_split", nested_split if "nested_split" in explicit else None
                ),
                split_min_level=_flag(
                    "split_min_level", split_min_level if "split_min_level" in explicit else None
                ),
                split_max_level=_flag("split_max_level", split_max_level),
                split_target_kb=split_target_kb,
                min_body_chars=_flag("min_body_chars", min_body_chars),
                english_only=english_only,
                regenerate_toc=_flag("regenerate_toc", True),
                decoration_threshold=_flag("decoration_threshold", decoration_threshold),
                decoration_hamming_distance=_flag(
                    "decoration_hamming_distance", decoration_hamming_distance
                ),
                pdf_backend=cast(PdfBackendName, pdf_backend),
                pdf_backend_kwargs=_flag(
                    "pdf_backend_kwargs", parse_backend_kwargs(pdf_backend_kwargs)
                ),
                heading_hierarchy=_flag("heading_hierarchy", heading_hierarchy),
                repair_tables=repair_tables,
                docx_backend=cast(DocxBackendName, _flag("docx_backend", docx_backend)),
                docx_outline_heading_depth=_flag(
                    "docx_outline_heading_depth", docx_outline_heading_depth
                ),
                normalize_headings=_flag(
                    "normalize_headings",
                    normalize_headings if "normalize_headings" in explicit else None,
                ),
                normalize_headings_mode=nh_mode_arg,
                normalize_headings_model=normalize_headings_model,
                strip_frontmatter=_flag(
                    "strip_frontmatter",
                    strip_frontmatter if "strip_frontmatter" in explicit else None,
                ),
                provenance=_flag("provenance", provenance if "provenance" in explicit else None),
                source_type=_flag("source_type", source_type),
                source_label=_flag("source_label", source_label),
                rerun_from=rerun_from,
                start=start,
                stop_after=stop_after,
                workers=resolve_cli_workers(
                    workers,
                    input_path,
                    # The chunked path re-ingests and drops these; never let an
                    # ambient PAGESPEAK_WORKERS take a run there behind the user.
                    chunk_unsafe=bool(
                        start or stop_after or rerun_from or page_range or english_only
                    )
                    or repair_tables
                    # tophat reads the whole export in one pass and ignores
                    # page_range, so chunking duplicates every question.
                    or pdf_backend == "tophat",
                ),
                answer_key=answer_key,
                allow_partial_ingest=allow_partial_ingest,
            )
        except PartialIngestError as exc:
            typer.echo(f"Error: {exc}", err=True)
            typer.echo("   or pass --allow-partial-ingest to build the document anyway.", err=True)
            raise typer.Exit(2) from exc
        except ValueError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc

        report_result(
            input_path=input_path,
            output_dir=output_dir,
            result=result,
            stop_after=stop_after,
        )
