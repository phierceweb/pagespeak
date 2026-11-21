"""`convert`'s options for what the run does: vision, normalize, splitting, provenance,
inheritance, re-runs and phases, workers."""

from __future__ import annotations

import typer

from ._help_text import NORMALIZE_MODEL_HELP

DIAGRAMS = typer.Option(
    True,
    "--diagrams/--no-diagrams",
    help="Run vision LLM on extracted images to produce Mermaid blocks.",
)
VISION_BACKEND = typer.Option(
    None,
    "--vision-backend",
    help="claude_code (default — local CLI, $0) | anthropic (direct API) | openrouter (multi-provider via OPENROUTER_API_KEY). When unset, consults $PAGESPEAK_VISION_BACKEND env var.",
)
VISION_MODEL = typer.Option(
    None,
    "--vision-model",
    help="Override the model used for diagram extraction (else config/model_router.yaml). Under claude_code it is passed as --model.",
)
VISION_CONCURRENCY = typer.Option(
    None,
    "--vision-concurrency",
    help="Per-image worker pool size for the vision pass. Default 6 (override via PAGESPEAK_VISION_CONCURRENCY env). Lower for claude_code on small laptops; higher when bottlenecked on network.",
)
VISION_CACHE_ONLY = typer.Option(
    False,
    "--vision-cache-only",
    help=(
        "Vision uses ONLY the existing .vision-cache/ and makes zero LLM "
        "calls. Uncached images are skipped (caption-only) with a warning "
        "naming them. Guarantees $0 / zero quota when re-ingesting an "
        "edited document whose images are unchanged. Incompatible with "
        "--no-diagrams."
    ),
)
VISION_ALL_IMAGES = typer.Option(
    False,
    "--vision-all-images",
    help="Caption every file in images/, including pictures cleanup removed from the text. Default: only the pictures the document references. Use to fill the vision cache ahead of a cleanup re-run.",
)
PRESERVE_ALT = typer.Option(
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
)
SPLIT_SECTIONS = typer.Option(
    False,
    "--split-sections/--no-split-sections",
    help="Also write one file per section under <output_dir>/sections/.",
)
NESTED_SPLIT = typer.Option(
    False,
    "--nested-split/--no-nested-split",
    help="With --split-sections, nest section files in folders that follow the heading hierarchy.",
)
SPLIT_MIN_LEVEL = typer.Option(
    None,
    "--split-min-level",
    help="With --split-sections, split on semantic headings at this depth or deeper. Default 1 (split on every heading); pass a higher depth for coarser sections.",
)
SPLIT_MAX_LEVEL = typer.Option(
    None,
    "--split-max-level",
    help="With --split-sections, cap section depth: headings deeper than this stay inline. E.g. 2 = one file per H2 with subsections inline (textbook section-level chunks). Default: no cap.",
)
SPLIT_TARGET_KB = typer.Option(
    None,
    "--split-target-kb",
    help="With --split-sections, pack sections to a size target instead of splitting on every heading: a branch fitting N KB becomes one file, an oversized branch splits deeper, and an oversized heading-less section is partitioned into '(part i of k)' files. Off unless passed, and never inherited from a run record: pass it on each run that should pack. Mutually exclusive with --split-max-level.",
)
MIN_BODY_CHARS = typer.Option(
    None,
    "--min-body-chars",
    help="With --split-sections, drop sections whose body has fewer than N non-whitespace characters. Default 1: drops only heading-only shells; a section with any text is kept. Pass 0 to keep every section, including empty ones — right for a document whose empty headings are placeholders to be filled in later.",
)
ENGLISH_ONLY = typer.Option(
    False,
    "--english-only/--no-english-only",
    help="With --split-sections, drop sections classified as clearly non-English (a multilingual manual's translated appendix). Conservative — short/ambiguous sections are kept. Off by default.",
)
NORMALIZE_HEADINGS = typer.Option(
    False,
    "--normalize-headings/--no-normalize-headings",
    help="Fix flattened chapter+subsection levels (e.g. textbook-style PDFs where Marker emits everything at the same depth). See --normalize-headings-mode for engine choice.",
)
NORMALIZE_HEADINGS_MODE = typer.Option(
    "heuristic",
    "--normalize-headings-mode",
    help="heuristic (default — fast, free, deterministic) | llm (headers-only LLM) | llm_full (LLM + body-context anchors: re-levels the hierarchy AND drops junk headings) | llm_dehead (same payload, drops junk headings but never changes a level — for a doc whose hierarchy the backend already got right) | auto (classify the doc and pick heuristic-vs-llm_full per-document).",
)
NORMALIZE_HEADINGS_MODEL = typer.Option(
    None,
    "--normalize-headings-model",
    help=NORMALIZE_MODEL_HELP,
)
NORMALIZE_HEADINGS_BACKEND = typer.Option(
    None,
    "--normalize-headings-backend",
    help="Per-task backend for heading-normalize LLM calls. claude_code (default) | anthropic | openrouter. Sets PAGESPEAK_HEADING_NORMALIZE_BACKEND, _FULL_BACKEND and _DEHEAD_BACKEND for the run, so it applies to every normalize mode.",
)
PROVENANCE = typer.Option(
    False,
    "--provenance/--no-provenance",
    help="Emit output provenance frontmatter (source tags + auto-derived label + per-section breadcrumb locators) on the whole-doc markdown and every section file — the multi-source RAG enabler. Off by default; the rag-default preset enables it. With no --source-label, the label is auto-derived from the cleaned filename; --source-type/--source-label also turn it on.",
)
SOURCE_TYPE = typer.Option(
    None,
    "--source-type",
    help="Provenance tag (e.g. textbook | lab_manual | manual). Omitted from the block when unset. Also turns frontmatter on (see --provenance). Distinct from --strip-frontmatter (input-side).",
)
SOURCE_LABEL = typer.Option(
    None,
    "--source-label",
    help='Human source title for the provenance frontmatter (e.g. "Quick Start Guide"). Emits frontmatter the same as --source-type.',
)
INHERIT = typer.Option(
    True,
    "--inherit/--no-inherit",
    help="When the output dir holds a .pagespeak-run.json, flags you don't pass default to that record's resolved_flags (explicit flags and an explicit --preset win; LLM/engine flags never inherit). --no-inherit ignores the record: bare defaults. See docs/caching.md.",
)
RERUN_FROM = typer.Option(
    None,
    "--rerun-from",
    help="Bust caches at this stage and re-run from there. Stages: ingest | cleanup | decorations | normalize | repair | structure | vision | split. Unspecified output-shaping flags come from the run record (see --inherit). See docs/caching.md.",
)
START = typer.Option(
    None,
    "--from",
    help="Begin at this phase using the existing upstream checkpoint as input (does NOT bust caches — that's --rerun-from). Phases: ingest | cleanup | normalize | repair | structure | vision | split. --from X --stop-after X runs exactly one phase.",
)
STOP_AFTER = typer.Option(
    None,
    "--stop-after",
    help="Halt after this phase (its checkpoint is written; nothing downstream runs). Same phase names as --from. Lets you validate the pipeline one phase at a time.",
)
WORKERS = typer.Option(
    None,
    "--workers",
    "-w",
    help="Number of parallel worker processes for the backend phase. When > 1, routes through ingest (chunked parallel) then Phase 3. Requires --output-dir. Default 1 (single-shot), or PAGESPEAK_WORKERS when set. An env-derived value applies to PDF file input only and is ignored for a run the chunked path cannot serve (--from / --stop-after / --rerun-from / --page-range / --english-only / --repair-tables); a typed -w is always honoured.",
)
ALLOW_PARTIAL_INGEST = typer.Option(
    False,
    "--allow-partial-ingest",
    help="Build the document even though a chunked ingest left failed chunks. The output will be missing those pages.",
)
