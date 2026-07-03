"""pagespeak convert subcommand."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import typer

from .. import to_markdown
from ..backends._docx_dispatch import DocxBackendName
from ..backends._pdf_dispatch import PdfBackendName
from ..backends._qti import is_qti_export
from ..orchestrators._dispatch import resolve_dir_mode_stem
from ..services._cleanup import CleanupLevel, CrossRefs
from ..services._diagrams import VisionBackendName
from ..services._normalize_decision import NormalizeModeOption

# Names of typer params that the preset can supply. CLI passes None to
# `to_markdown` for any of these the user didn't explicitly set, so the
# library-side preset+default resolver kicks in.
_PRESET_CONTROLLED_FLAGS = (
    "cleanup",
    "split_sections",
    "nested_split",
    "split_min_level",
    "normalize_headings",
    "normalize_headings_mode",
    "strip_frontmatter",
    "provenance",
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
        input_path: Path = typer.Argument(..., exists=True, dir_okay=True, readable=True),
        output_dir: Path = typer.Option(
            Path("./out"),
            "--output-dir",
            "-o",
            help="Directory for the markdown file and extracted images.",
        ),
        preset: str | None = typer.Option(
            None,
            "--preset",
            help="Curated config bundle: rag-default | flat | textbook | archival | qti. Per-flag args explicitly passed on the CLI win over preset values. See docs/presets.md.",
        ),
        diagrams: bool = typer.Option(
            True,
            "--diagrams/--no-diagrams",
            help="Run vision LLM on extracted images to produce Mermaid blocks.",
        ),
        vision_backend: str | None = typer.Option(
            None,
            "--vision-backend",
            help="claude_code (default — local CLI, $0) | anthropic (direct API) | openrouter (multi-provider via OPENROUTER_API_KEY). When unset, consults $PAGESPEAK_VISION_BACKEND env var.",
        ),
        vision_model: str | None = typer.Option(
            None,
            "--vision-model",
            help="Override the model used for diagram extraction. Ignored under claude_code.",
        ),
        vision_concurrency: int | None = typer.Option(
            None,
            "--vision-concurrency",
            help="Per-image worker pool size for the vision pass. Default 6 (override via PAGESPEAK_VISION_CONCURRENCY env). Lower for claude_code on small laptops; higher when bottlenecked on network.",
        ),
        vision_cache_only: bool = typer.Option(
            False,
            "--vision-cache-only",
            help=(
                "Vision uses ONLY the existing .vision-cache/ and makes zero LLM "
                "calls. Uncached images are skipped (caption-only) with a warning "
                "naming them. Guarantees $0 / zero quota when re-ingesting an "
                "edited document whose images are unchanged. Incompatible with "
                "--no-diagrams."
            ),
        ),
        preserve_alt: bool = typer.Option(
            False,
            "--preserve-alt",
            help=(
                "Faithful mode: keep each figure's existing alt text VERBATIM and only "
                "append a Mermaid block (for diagrams). The vision caption is still "
                "computed and cached but NOT injected, so the same run can later be "
                "re-emitted enriched with no re-vision. Use to add structure without "
                "modifying a source's alt text (e.g. contributing back to a publisher). "
                "Composes with --diagrams."
            ),
        ),
        force_ocr: bool = typer.Option(
            False,
            "--force-ocr",
            help="PDF only: force OCR even on text-bearing PDFs.",
        ),
        device: str | None = typer.Option(
            None,
            "--device",
            help='PDF only: torch device ("cpu" / "mps" / "cuda"). Use "cpu" to dodge the surya/MPS crash on Apple Silicon.',
        ),
        page_range: str | None = typer.Option(
            None,
            "--page-range",
            help='PDF only: convert only these pages, 0-based. Spec like "0-19" or "0-3,5,7-9".',
        ),
        html_base_url: str | None = typer.Option(
            None,
            "--html-base-url",
            help="HTML only: base URL of the source page so relative <img> refs "
            "(e.g. ../Storage/..) download. Example: the page's own URL.",
        ),
        cleanup: str = typer.Option(
            "basic",
            "--cleanup",
            help="Cleanup level: off | basic | aggressive.",
        ),
        cross_refs: str = typer.Option(
            "keep",
            "--cross-refs",
            help="How to handle [label](#page-X-Y) refs: keep | strip | remap.",
        ),
        split_sections: bool = typer.Option(
            False,
            "--split-sections",
            help="Also write one file per section under <output_dir>/sections/.",
        ),
        nested_split: bool = typer.Option(
            False,
            "--nested-split",
            help="With --split-sections, nest numbered files in numeric-prefix folders.",
        ),
        split_min_level: int | None = typer.Option(
            None,
            "--split-min-level",
            help="With --split-sections, split on semantic headings at this depth or deeper. Default 1 (split on every heading); pass a higher depth for coarser sections.",
        ),
        split_max_level: int | None = typer.Option(
            None,
            "--split-max-level",
            help="With --split-sections, cap section depth: headings deeper than this stay inline. E.g. 2 = one file per H2 with subsections inline (textbook section-level chunks). Default: no cap.",
        ),
        split_target_kb: int | None = typer.Option(
            None,
            "--split-target-kb",
            help="With --split-sections, pack sections to a size target instead of a fixed depth: a branch fitting N KB becomes one file, an oversized branch splits deeper, and an oversized heading-less section is partitioned into '(part i of k)' files. Adapts per branch — works across mixed book shapes. Mutually exclusive with --split-max-level.",
        ),
        english_only: bool = typer.Option(
            False,
            "--english-only",
            help="With --split-sections, drop sections classified as clearly non-English (a multilingual manual's translated appendix). Conservative — short/ambiguous sections are kept. Off by default.",
        ),
        pdf_backend: str = typer.Option(
            "marker",
            "--pdf-backend",
            help="PDF backend: 'marker' (default, fast) | 'docling' (accuracy-first, requires pagespeak[pdf-docling]) | 'tophat' (Top Hat quiz-export PDFs → per-question markdown, requires pagespeak[tophat]).",
        ),
        repair_tables: bool = typer.Option(
            False,
            "--repair-tables",
            help="Marker PDF only. After ingest, splice Docling's clean grid over any <br>-collapsed table (Marker sometimes jams a multi-column table into one cell). Off by default; requires pagespeak[pdf-docling]. Same fix as the standalone `pagespeak repair-tables` command, run inline. See docs/repair-tables.md.",
        ),
        docx_backend: str = typer.Option(
            "markitdown",
            "--docx-backend",
            help="DOCX backend: 'markitdown' (default) | 'python-docx' (structure-faithful, requires pagespeak[docx-structured]). Ignored for non-.docx formats.",
        ),
        docx_outline_heading_depth: int = typer.Option(
            0,
            "--docx-outline-heading-depth",
            help="python-docx only. Outline→heading switch. 0 (default) = retain the WHOLE Word outline as a nested list (only the document title is '#'). N>0 overrides the top N outline levels into headings (1 = ilvl0 → '#').",
        ),
        normalize_headings: bool = typer.Option(
            False,
            "--normalize-headings/--no-normalize-headings",
            help="Fix flattened chapter+subsection levels (e.g. textbook-style PDFs where Marker emits everything at the same depth). See --normalize-headings-mode for engine choice.",
        ),
        normalize_headings_mode: str = typer.Option(
            "heuristic",
            "--normalize-headings-mode",
            help="heuristic (default — fast, free, deterministic) | llm (headers-only LLM) | llm_full (LLM + body-context anchors) | auto (classify the doc and pick heuristic-vs-llm_full per-document).",
        ),
        normalize_headings_model: str | None = typer.Option(
            None,
            "--normalize-headings-model",
            help="LLM-mode only: model passed to `claude --model …`. Defaults to claude-haiku-4-5-20251001.",
        ),
        normalize_headings_backend: str | None = typer.Option(
            None,
            "--normalize-headings-backend",
            help="Per-task backend for heading-normalize LLM calls. claude_code (default) | anthropic | openrouter. Sets both PAGESPEAK_HEADING_NORMALIZE_BACKEND and _FULL_BACKEND env vars for the run.",
        ),
        strip_frontmatter: bool = typer.Option(
            False,
            "--strip-frontmatter/--no-strip-frontmatter",
            help="DOCX only: drop revision-history / instructional-text / Word-TOC frontmatter before the first H1 heading. Off by default; the rag-default / flat / textbook presets enable it.",
        ),
        provenance: bool = typer.Option(
            False,
            "--provenance/--no-provenance",
            help="Emit output provenance frontmatter (source tags + auto-derived label + per-section breadcrumb locators) on the whole-doc markdown and every section file — the multi-source RAG enabler. Off by default; the rag-default preset enables it. With no --source-label, the label is auto-derived from the cleaned filename; --source-type/--source-label also turn it on.",
        ),
        source_type: str | None = typer.Option(
            None,
            "--source-type",
            help="Provenance tag (e.g. textbook | lab_manual | manual). Omitted from the block when unset. Also turns frontmatter on (see --provenance). Distinct from --strip-frontmatter (input-side).",
        ),
        source_label: str | None = typer.Option(
            None,
            "--source-label",
            help='Human source title for the provenance frontmatter (e.g. "Quick Start Guide"). Emits frontmatter the same as --source-type.',
        ),
        rerun_from: str | None = typer.Option(
            None,
            "--rerun-from",
            help="Bust caches at this stage and re-run from there. Stages: ingest | cleanup | decorations | normalize | vision | split. See docs/caching.md.",
        ),
        start: str | None = typer.Option(
            None,
            "--from",
            help="Begin at this phase using the existing upstream checkpoint as input (does NOT bust caches — that's --rerun-from). Phases: ingest | cleanup | normalize | vision | split. --from X --stop-after X runs exactly one phase.",
        ),
        stop_after: str | None = typer.Option(
            None,
            "--stop-after",
            help="Halt after this phase (its checkpoint is written; nothing downstream runs). Same phase names as --from. Lets you validate the pipeline one phase at a time.",
        ),
        workers: int = typer.Option(
            1,
            "--workers",
            "-w",
            help="Number of parallel worker processes for the backend phase. When > 1, routes through ingest (chunked parallel) then Phase 3. Requires --output-dir. Default 1 (single-shot).",
        ),
        answer_key: bool = typer.Option(
            True,
            "--answer-key/--no-answer-key",
            help="Canvas QTI quiz exports only: mark/state the correct answers. On by default; --no-answer-key renders a blank quiz.",
        ),
    ) -> None:
        """Convert a document to LLM-friendly markdown.

        Single-process by default (--workers 1). Pass --workers N to use
        parallel chunked ingest for very large PDFs."""
        cross_refs = validate_cross_refs(cross_refs)
        # validate only if the user passed --vision-backend.
        # When unset (None), `to_markdown` defers to `PAGESPEAK_VISION_BACKEND`
        # env var (via `gather_diagrams` → `_agent_runtime.resolve_backend`),
        # which falls back to `claude_code`. Same shape as
        # `--normalize-headings-backend` validation below.
        if vision_backend is not None:
            vision_backend = validate_vision_backend(vision_backend)
        pdf_backend = validate_pdf_backend(pdf_backend)
        preset = validate_preset(preset)

        # --normalize-headings-backend writes to the per-task env
        # vars before `to_markdown` runs so `_agent_runtime.resolve_backend`
        # picks them up. Both `heading_normalize` and `heading_normalize_full`
        # share the flag — users pick one normalize mode per run, and the
        # backend applies to whichever mode is active.
        normalize_headings_backend = validate_normalize_headings_backend(normalize_headings_backend)
        if normalize_headings_backend is not None:
            import os as _os

            _os.environ["PAGESPEAK_HEADING_NORMALIZE_BACKEND"] = normalize_headings_backend
            _os.environ["PAGESPEAK_HEADING_NORMALIZE_FULL_BACKEND"] = normalize_headings_backend

        # detect which preset-controlled flags the user passed
        # explicitly. For ones they didn't pass, send `None` to
        # `to_markdown` so its preset+default resolver picks the value
        # (preset's, if --preset is set; original default otherwise).
        # `cleanup` and `normalize_headings_mode` only need validation
        # when the user explicitly passed them.
        explicit = _explicit_preset_flags(ctx)

        cleanup_arg: CleanupLevel | None = None
        if "cleanup" in explicit:
            cleanup_arg = cast(CleanupLevel, validate_cleanup(cleanup))

        nh_mode_arg: NormalizeModeOption | None = None
        if "normalize_headings_mode" in explicit:
            nh_mode_arg = cast(
                NormalizeModeOption, validate_normalize_mode(normalize_headings_mode)
            )

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
                preserve_alt=preserve_alt,
                force_ocr=force_ocr,
                device=device,
                page_range=page_range,
                html_base_url=html_base_url,
                cleanup=cleanup_arg,
                cross_refs=cast(CrossRefs, cross_refs),
                split_sections=split_sections if "split_sections" in explicit else None,
                nested_split=nested_split if "nested_split" in explicit else None,
                split_min_level=split_min_level if "split_min_level" in explicit else None,
                split_max_level=split_max_level,
                split_target_kb=split_target_kb,
                english_only=english_only,
                pdf_backend=cast(PdfBackendName, pdf_backend),
                repair_tables=repair_tables,
                docx_backend=cast(DocxBackendName, docx_backend),
                docx_outline_heading_depth=docx_outline_heading_depth,
                normalize_headings=normalize_headings if "normalize_headings" in explicit else None,
                normalize_headings_mode=nh_mode_arg,
                normalize_headings_model=normalize_headings_model,
                strip_frontmatter=strip_frontmatter if "strip_frontmatter" in explicit else None,
                provenance=provenance if "provenance" in explicit else None,
                source_type=source_type,
                source_label=source_label,
                rerun_from=rerun_from,
                start=start,
                stop_after=stop_after,
                workers=workers,
                answer_key=answer_key,
            )
        except ValueError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc

        output_dir.mkdir(parents=True, exist_ok=True)
        # In directory-input mode, derive the stem from the raw.md inside
        # the directory rather than from the directory name itself. A QTI
        # export dir has no raw.md — use its own name as the stem.
        if input_path.is_dir() and not is_qti_export(input_path):
            doc_stem = resolve_dir_mode_stem(input_path)
        else:
            doc_stem = input_path.stem

        # Only write the consolidated <stem>.md when the run produced final
        # content (it ran through vision). A `--stop-after` at an earlier phase
        # leaves `result.markdown` as an intermediate checkpoint (raw / cleaned
        # / normalized / structured) that the phase already persisted to its
        # own file — writing it to <stem>.md would CLOBBER the real final
        # document (this knocked diagrams out twice).
        if stop_after not in (None, "vision", "split"):
            typer.echo(
                f"stopped after '{stop_after}'; wrote the {stop_after} checkpoint "
                f"(final {doc_stem}.md left intact)"
            )
            return

        # QTI: per-quiz files were written flat at the output root (the
        # one independent document directory per exam — report those instead
        # of writing a single <stem>.md.
        if is_qti_export(input_path):
            exam_dirs = sorted(d for d in output_dir.iterdir() if d.is_dir())
            typer.echo(f"wrote {len(exam_dirs)} quiz document(s) under {output_dir}/")
            typer.echo(f"  format       : {result.source_format}")
            typer.echo(f"  images       : {len(result.images)}")
            typer.echo(f"  diagrams     : {sum(1 for d in result.diagrams if d.mermaid)}")
            return

        md_path = output_dir / f"{doc_stem}.md"
        md_path.write_text(result.markdown, encoding="utf-8")

        typer.echo(f"wrote {md_path}")
        typer.echo(f"  format       : {result.source_format}")
        typer.echo(f"  images       : {len(result.images)}")
        typer.echo(f"  diagrams     : {sum(1 for d in result.diagrams if d.mermaid)}")
        typer.echo(f"  non-diagrams : {sum(1 for d in result.diagrams if not d.mermaid)}")
        # The actual `split_sections` choice may have come from a preset
        # — `(output_dir / 'sections').is_dir()` is the source of truth.
        sections_dir = output_dir / "sections"
        if sections_dir.is_dir():
            typer.echo(f"  sections     : {sections_dir}")


def _is_commandline_source(source: object) -> bool:
    """True if a Click/Typer parameter source is COMMANDLINE.

    Compared by enum *name*, not identity: typer >= 0.26 vendors its own
    Click (`typer._click`), so `ctx.get_parameter_source()` returns a
    `typer._click.core.ParameterSource` member that is never equal to
    `click.core.ParameterSource.COMMANDLINE`. A name comparison is robust
    across both the stdlib-click and vendored-click enums (and any future
    revendoring), and avoids importing a Click enum whose identity is no
    longer stable.
    """
    return getattr(source, "name", None) == "COMMANDLINE"


def _explicit_preset_flags(ctx: typer.Context) -> set[str]:
    """Return the set of preset-controlled CLI param names that came from
    the COMMAND LINE (not the typer default). Uses Click's
    `get_parameter_source` so default-equal explicit passes still count
    as user-set.

    Falls back to the empty set on any unexpected error so a Click API
    change doesn't crash the convert command.
    """
    explicit: set[str] = set()
    try:
        for name in _PRESET_CONTROLLED_FLAGS:
            source = ctx.get_parameter_source(name)
            if _is_commandline_source(source):
                explicit.add(name)
    except (AttributeError, TypeError):
        pass
    return explicit
