# Usage

## Two API entry points

| Entry point | When |
|---|---|
| **`to_markdown()`** / `pagespeak convert <file>` | **Default.** One call, full backend + Phase 3, full heading hierarchy preserved. Works on any format and any doc that fits in memory. |
| **`pagespeak ingest <file> --workers N`** then **`pagespeak convert <outdir>`** | Opt-in for very large PDFs (~500+ pages) where resume-on-crash matters and you want to iterate on Phase 3 without repeating the backend. PDF-only for chunked path (`workers>1`). See [docs/ingest.md](ingest.md). |

## Library

```python
from pathlib import Path
from pagespeak import to_markdown

result = to_markdown(
    "manual.pdf",
    output_dir=Path("./out"),
    diagrams=True,
    vision_cache_only=False,        # True → vision reads only .vision-cache/; zero LLM calls; skips uncached images
    vision_model=None,             # default → claude-haiku-4-5-20251001
    force_ocr=False,               # PDF-only; force OCR even on text-bearing PDFs
    cleanup="basic",               # "off" | "basic" | "aggressive"
    cross_refs="keep",             # "keep" | "strip" | "remap" — [label](#page-X-Y) refs
    split_sections=False,          # write per-section files under out/sections/
    nested_split=False,            # with split_sections, nest numbered files by depth
    split_min_level=None,          # None → default 1 (split on EVERY heading); higher = coarser
    min_body_chars=None,           # with split_sections, drop sections shorter than N chars (None → 30)
    regenerate_toc=True,           # replace Marker's broken pipe-table TOC with a generated bullet list
    decoration_threshold=None,     # phash dedup threshold (None → 5; 0 disables)
    decoration_hamming_distance=None,  # Hamming-distance threshold (None → 12)
    device=None,                   # PDF only: "cpu" / "mps" / "cuda" or None for auto
    page_range=None,               # PDF only: "0-19" / "0-3,5,7-9" / list[int] or None
    html_base_url=None,            # HTML only: base URL so relative <img> refs (../Storage/..) download
    pdf_backend="marker",          # PDF only: "marker" (default) | "docling" — see docs/backends.md
    pdf_backend_kwargs=None,       # PDF only: dict forwarded to the backend's pipeline options
    repair_tables=False,           # Marker PDF only: splice Docling's clean grid over <br>-collapsed AND split multi-line-cell tables — see docs/repair-tables.md
    provenance=None,               # emit provenance frontmatter (doc + sections); preset-controlled (on for rag-default)
    source_type=None,              # provenance tag (e.g. "textbook"); omitted from the block when None
    source_label=None,             # human source title; auto-derived from the cleaned filename when omitted
)

# result.markdown   → str
# result.images     → list[Path]
# result.diagrams   → list[Diagram]
# result.source_format → "pdf"
```

The result includes the final markdown string (with Mermaid blocks already embedded). Consumers typically write it themselves:

```python
Path("./out/manual.md").write_text(result.markdown, encoding="utf-8")
```

## CLI

| Subcommand | Purpose |
|---|---|
| `pagespeak convert <input>` | Convert a document (ingest + Phase 3) in one command. Given a directory with `<stem>.raw.md`, runs Phase 3 only (skips backend). |
| `pagespeak ingest <input>` | Backend phase only: produces `<stem>.raw.md` + `images/`. Use `--workers N` for chunked-parallel PDF. See [ingest.md](ingest.md). |
| `pagespeak invalidate <out> <stage>` | Bust caches at this stage and downstream. See [caching.md](caching.md). |
| `pagespeak baseline save \| list \| diff <out>` | Snapshot, inspect, and diff prior runs. See [caching.md](caching.md). |
| `pagespeak deliver <out> [-o <dir>]` | Strip a converted output dir to delivery-ready files: copy only the master `.md`, `sections/`, and `images/` (dropping stage checkpoints, run records, caches) into a parallel dir. Defaults to `conversions/out/<name>` → `conversions/delivery/<name>`; re-runnable (rebuilds the destination to match the source). |
| `pagespeak audit <paths…> [--summary-only]` | Scan converted output (dirs or single `.md` files) for known conversion defects — collapsed tables, HTML debris, encoding damage, undecoded entities, shattered emphasis, orphan-shell sections, dangling image refs, duplicated junk headings. Read-only, $0, no LLM; audits final artifacts only. Exit 1 on errors; warnings alone exit 0. See [audit.md](audit.md). |
| `pagespeak repair-tables <out> [--source <pdf>] [--dry-run]` | Fix Marker-broken tables (collapsed `<br>` mega-cells and split multi-line cells) by splicing in the clean grid Docling extracts from just the broken-table page — no whole-doc re-ingest, no re-vision. Patches `<stem>.raw.md`; propagate with `convert <dir> --from cleanup --vision-cache-only`. Needs the source PDF (auto-located in `conversions/in/` or `--source`). See [repair-tables.md](repair-tables.md). |

### `pagespeak convert`

```bash
pagespeak convert <input-or-outdir> [--output-dir DIR] [--workers N]
                                    [--no-diagrams] [--vision-model MODEL] [--force-ocr]
                                    [--cleanup LEVEL] [--split-sections] [--nested-split]
```

Two input modes:
- **File path** — runs ingest (backend) + Phase 3 in one command.
- **Output directory** — if the directory contains `<stem>.raw.md`, skips ingest and runs Phase 3 only against the existing raw file. Useful after `pagespeak ingest --workers N`.

| Flag | Default | Purpose |
|---|---|---|
| `<input>` | (required) | Path to the source document OR an existing output dir with `<stem>.raw.md` |
| `--output-dir`, `-o` | `./out` | Directory for the markdown file and extracted images (file-input mode only) |
| `--workers`, `-w` | `1` | Worker count for the ingest phase (file-input mode only). `1` = single-process; `N > 1` = chunked-parallel Marker (PDF only). See [ingest.md](ingest.md). |
| `--diagrams` / `--no-diagrams` | enabled | Run the vision LLM on each extracted image |
| `--vision-backend` | `claude_code` | `claude_code` (local `claude --print`, $0 per call — the default), `anthropic` (API), or `openrouter` (multi-provider via `OPENROUTER_API_KEY`) |
| `--vision-model` | from `config/model_router.yaml` (`agents.vision.backends.<backend>.model`) | Override the model. For `claude_code`, always fires as `--model` to `claude --print` (never falls through to the user's session model). The legacy `$PAGESPEAK_VISION_MODEL` env var is no longer consulted — edit the YAML for non-CLI overrides. |
| `--vision-concurrency` | `6` (`$PAGESPEAK_VISION_CONCURRENCY`) | Per-image worker pool size. Lower for `claude_code` on small boxes; higher when network-bound. |
| `--vision-cache-only` | off | Vision uses only the existing `.vision-cache/`; zero LLM calls. Uncached images are skipped (caption-only) with a `vision_cache_only_skipped` warning naming them. Incompatible with `--no-diagrams`. Guarantees $0/zero-quota on re-ingest of a doc whose images are unchanged. |
| `--preserve-alt` | off | Faithful mode: keep each figure's existing alt text **verbatim** and only append a Mermaid block (for diagrams). The caption is still computed and cached but not injected, so the same run can be re-emitted enriched with no re-vision. Use to add structure without modifying a source's alt text (e.g. contributing back to a publisher). Composes with `--diagrams`; a no-op under `--no-diagrams`. See [diagrams.md](diagrams.md#faithful-mode---preserve-alt). |
| `--force-ocr` | off | PDF only — force surya OCR even on text-bearing PDFs |
| `--device` | (auto) | PDF only — `cpu` / `mps` / `cuda`. Set to `cpu` to dodge the surya/MPS crash on Apple Silicon (see below). |
| `--page-range` | all pages | PDF only — convert only these 0-based pages, e.g. `"0-19"` or `"0-3,5,7-9"`. Useful for iterating on big PDFs. |
| `--html-base-url` | None | HTML only — base URL of the source page so relative `<img src="../Storage/…">` refs (typical of saved web-help exports) resolve and download. Pass the page's own URL. None = leave relative refs as-is. |
| `--cleanup` | `basic` | Cleanup level: `off` / `basic` / `aggressive`. See [docs/cleanup.md](cleanup.md). |
| `--cross-refs` | `keep` | How to handle `[label](#page-X-Y)` refs: `keep` (preserve), `strip` (rewrite to plain text), or `remap` (rewrite to point at the next heading's slug). Pair with `--cleanup aggressive` for orphan-free output. |
| `--split-sections` | off | Also write per-section files under `<output_dir>/sections/` plus an `INDEX.md` |
| `--nested-split` | off | With `--split-sections`, nest section files in folders that mirror the heading hierarchy. Numbered sections use number prefixes (`1/1.4/1.4.1. Title.md`); semantic sections use sanitized heading titles (`Quick Start/Foot Switches (1).md`). |
| `--split-min-level` | `1` | With `--split-sections`, split on semantic headings at this depth or deeper. Default `1` splits on **every** heading (numbered + un-numbered) for small RAG sections; pass a higher depth (e.g. `--split-min-level 2`) for coarser sections |
| `--english-only` | off | With `--split-sections`, drop a multilingual manual's translated branches (a multilingual manual: EN/DE/ZH/IT/FR/ES/RU, or a 24-language warranty block), keeping the English. Judged by **subtree** — a branch's aggregated text, recursing into kept English branches — so a translation fragmented into terse sections, or nested under an English chapter, is still caught. Dropped only on a strong signal: >30% non-Latin script, OR sparse English **and** a real density of distinctively-foreign function words (the latter keeps stopword-poor English specs tables that sparse-English alone would wrongly flag). Removes the major Latin languages + all non-Latin; a 24-EU-language boilerplate block is the known gap. Off by default. |
| `--pdf-backend` | `marker` | `marker` (default, fast), `docling` (accuracy-first, requires `pagespeak[pdf-docling]`), or `tophat` (Top Hat quiz-export PDFs → per-question markdown, requires `pagespeak[tophat]`). See [docs/backends.md](backends.md) / [docs/tophat-quizzes.md](tophat-quizzes.md). |
| `--repair-tables` | off | Marker PDF only. After ingest, splice Docling's clean grid over Marker-broken tables — both `<br>`-collapsed mega-cells (a multi-column table jammed into one cell) and split multi-line-cell tables (one row per wrapped line). Requires `pagespeak[pdf-docling]`; off by default (no Docling cost unless asked). Same fix as the standalone `pagespeak repair-tables` command, run inline. See [docs/repair-tables.md](repair-tables.md). |
| `--docx-backend` | `markitdown` | `markitdown` (default) or `python-docx` (structure-faithful, requires `pagespeak[docx-structured]`). Ignored for non-`.docx`. |
| `--docx-outline-heading-depth` | `0` | python-docx only. The outline→heading switch. `0` (default) = the ENTIRE Word outline is retained as a nested list (only the document title is `#`). `N>0` overrides the top N outline levels into headings (`1` = `ilvl0` → `#` section spine; higher promotes more). |
| `--preset` | none | Curated config bundle: `rag-default` / `flat` / `textbook` / `archival` / `qti`. Per-flag CLI args win over preset values. See [docs/presets.md](presets.md). |
| `--normalize-headings` / `--no-normalize-headings` | off | Fix flattened chapter+subsection levels (textbook-style PDFs). See [docs/normalize-headings.md](normalize-headings.md). |
| `--normalize-headings-mode` | `heuristic` | `heuristic` (default — fast, free, deterministic), `llm` (headers-only LLM), `llm_full` (LLM with body anchors — for badly-flattened textbooks), or `auto` (pick `heuristic`/`llm_full` per-document from a $0 heading-shape signal; see [normalize-headings.md](normalize-headings.md#auto-mode)). |
| `--normalize-headings-model` | from `config/model_router.yaml` (`agents.heading_normalize{,_full}.backends.<backend>.model`) | LLM-mode only. The legacy `$PAGESPEAK_NORMALIZE_HEADINGS_MODEL` env var is no longer consulted — edit the YAML for non-CLI overrides. |
| `--strip-frontmatter` / `--no-strip-frontmatter` | preset-controlled | DOCX template-frontmatter strip (TOC anchors, revision-history table, `<Project Name>` placeholders). |
| `--provenance` / `--no-provenance` | preset-controlled (on for `rag-default`) | Emit **rich** output provenance frontmatter on the whole-doc markdown **and every section file**: source tags (`source_type` / `source_label` / `source_file`) + `doc_title` + per-section locators `section_title`, `section_path` (the ancestor-heading breadcrumb), `section_number`, `heading_level` — so a multi-source RAG DB can tag and locate each chunk. With no `--source-label`, the label is auto-derived from the cleaned filename stem; `source_type` is omitted from the block unless `--source-type` is given. Off → output is byte-for-byte frontmatter-free. Setting `--source-type`/`--source-label` also turns it on. Re-tag an existing conversion cheaply with `--from split --preset rag-default`. Distinct from `--strip-frontmatter` (which strips *input* frontmatter). |
| `--source-type` | none | Provenance tag (e.g. `textbook` / `lab_manual` / `lecture_notes` / `manual`). Omitted from the block when unset (never auto-classified). Also turns frontmatter on (see `--provenance`). |
| `--source-label` | auto-derived | Human source title for the frontmatter, e.g. `"Quick Start Guide"`. When omitted (and frontmatter is on), auto-derived from the cleaned filename stem (`_`/`-` separators → spaces). Pass it to override a cryptic stem. Also turns frontmatter on. |
| `--rerun-from <stage>` | none | Bust caches at this stage and downstream, then run. See [docs/caching.md](caching.md). |
| `--from <phase>` | none | Begin at this phase using the existing upstream checkpoint as input (does **not** bust caches — that's `--rerun-from`). Phases: `ingest \| cleanup \| normalize \| repair \| structure \| vision \| split`. Errors if the input checkpoint is absent. |
| `--stop-after <phase>` | none | Halt after this phase — its checkpoint is written, nothing downstream runs. Same phase names as `--from`. Run one phase at a time to validate the pipeline methodically. `--from X --stop-after X` runs exactly phase X. `--from split` splits the post-vision `visioned.md` checkpoint. |

The CLI writes `<output_dir>/<stem>.md` plus `<output_dir>/images/`. With `--split-sections`, also `<output_dir>/sections/`. With `--normalize-headings`, also `<output_dir>/<stem>.pre-normalize.md` (post-cleanup pre-LLM snapshot for diff/revert).

Side files for re-test ergonomics: `<stem>.raw.md` (backend output checkpoint), `<stem>.cleaned.md` (post-cleanup snapshot for resume), `<stem>.normalized.md` (post-normalize snapshot), `.vision-cache/<phash>.json` (per-image vision cache), `.heading-normalize-cache/<hash>.json` (LLM-mode normalize cache), `.pagespeak-run.json` (resolved config + counts). See [docs/caching.md](caching.md).

## Project script wrappers

`bin/<command>` so commands are stable across venv recreations and so `.env` auto-loads:

```bash
bin/setup                            # venv + editable install (+ scaffolds .env from .env.example)
bin/setup --pdf                      # also pull in marker-pdf (~2GB)
bin/run convert manual.pdf -o ./out     # convert a document (ingest + Phase 3)
bin/run ingest thick.pdf -o ./out -w 4  # backend phase only, 4 parallel workers
bin/run convert ./out --normalize-headings  # Phase 3 on existing raw.md
bin/run pytest [args]                # venv pytest
bin/run python [args]                # venv python (one-off scripts)
bin/run pip [args]                   # venv pip
bin/run ruff [args]                  # venv ruff
bin/run mypy [args]                  # venv mypy
bin/test                             # ergonomic shortcut for `bin/run pytest`
bin/lint                             # ergonomic shortcut for ruff + mypy via `bin/run`
```

`bin/run` auto-sources the project's `.env` if present. Anything already in the environment **wins** over `.env`: an inline `PAGESPEAK_VISION_BACKEND=openrouter bin/run convert ...` and parent-shell exports both take precedence — `.env` only fills vars that are otherwise unset.

## Environment variables

| Var | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required for `vision_backend="anthropic"`) | Anthropic API auth |
| `OPENROUTER_API_KEY` | (required for `vision_backend="openrouter"`) | OpenRouter API auth |
| `PAGESPEAK_VISION_BACKEND` | `claude_code` | Per-task backend for vision (`claude_code` / `anthropic` / `openrouter`). |
| `PAGESPEAK_HEADING_NORMALIZE_BACKEND` | `claude_code` | Per-task backend for heading-normalize `llm` mode. |
| `PAGESPEAK_HEADING_NORMALIZE_FULL_BACKEND` | `claude_code` | Per-task backend for heading-normalize `llm_full` mode. |
| `PAGESPEAK_VISION_CONCURRENCY` | `6` | Per-image worker pool size for the vision pass. |
| `PAGESPEAK_WORKERS` | `1` | Default `--workers` for `pagespeak ingest` / `pagespeak convert` (chunked-parallel PDF). |
| `PAGESPEAK_LOG_LEVEL` | `INFO` | CLI logger verbosity. `DEBUG` reveals per-image vision progress, cache stats, normalize details. Library consumers configure their own logging. |
| `PAGESPEAK_CLAUDE_CODE_TIMEOUT_S` | `1800` | Subprocess timeout (seconds) for `claude --print` invocations during heading-normalize. Bump if a very large `llm_full` payload (≥~400K tokens) hits the default. |
| `PAGESPEAK_VISION_CLAUDE_CODE_TIMEOUT_S` | `120` | Subprocess timeout (seconds) for `claude --print` per vision image. Bump for large diagrams or slow networks. |
| `PAGESPEAK_CHUNK_PAGES` | `50` | Pages per chunk in `--workers > 1` parallel ingest. Smaller = finer-grained resume; larger = fewer Marker model-loads but more per-worker RAM. |
| `PAGESPEAK_DOWNLOAD_REMOTE_IMAGES` | `1` | HTML ingest: download remote `<img>` URLs into `images/<name>` + retarget refs so the vision pass can process them. `0` = leave as external URLs. Already-downloaded files are reused. |
| `PAGESPEAK_REMOTE_IMAGE_TIMEOUT_S` | `30` | Per-request HTTP timeout (s) when downloading a remote HTML image. Bump on slow networks / large figures. |
| `PAGESPEAK_REMOTE_IMAGE_MAX_BYTES` | `26214400` | Max bytes for one downloaded remote image (25 MiB). A larger image is skipped (ref kept remote, nothing written). Raise for legitimately large figures. |
| `PAGESPEAK_DEFAULT_DEVICE` | (unset → backend autodetects) | Default torch device for PDF backends (`cpu` / `mps` / `cuda`). Set to `cpu` on Apple Silicon to avoid the surya/MPS crash. Explicit `--device` still wins. |
| `PAGESPEAK_FLAT_H1_THRESHOLD` | `5` | `structure` phase: minimum number of consecutive H1s (no H2 between) before the flat-source-demote pass fires. Conservative; tune lower to catch shorter clusters. |
| `PAGESPEAK_ORPHAN_H1_RATIO_THRESHOLD` | `70` | `structure` phase: percent of H1s (excluding the title) that must be "orphan" (no H2 child) for the orphan-H1 rebalance to fire. Catches machine-flattened HTML-export PDFs while sparing authored-flat docs. |
| `DATABASE_URL` | `sqlite:///~/.pagespeak/llm_tracking.db` | pf-core `llm_runs` tracking DB. Point at postgres / mysql to share with other pf-core consumers. A postgres URL needs the driver: `bin/setup --postgres` (or `--all`). |
| `PAGESPEAK_CONVERSIONS_DIR` | `<cwd>/conversions` | Web console: root directory holding `in/` (sources) and `out/` (per-doc output dirs). |
| `PAGESPEAK_WEB_HOST` | `127.0.0.1` | Web console bind host. |
| `PAGESPEAK_WEB_PORT` | `8810` | Web console bind port. |
| `PAGESPEAK_WEB_CONCURRENCY` | `1` | Web console concurrent conversion jobs. Default 1 avoids parallel vision quota stampedes. |

Per-task **model + sampling kwargs** (model, max_tokens, temperature, etc.) live in `config/model_router.yaml` — not in env. A copy ships **inside the package** as the default, so a `pip install`ed pagespeak has the tuned models out of the box; the file is resolved (highest first) from the `MODEL_ROUTER_CONFIG` env var, then a `config/model_router.yaml` in the working directory, then the bundled default. The legacy `PAGESPEAK_VISION_MODEL` / `PAGESPEAK_NORMALIZE_HEADINGS_MODEL` env vars are no longer read. Edit the YAML (or point `MODEL_ROUTER_CONFIG` at your own file) to change which model runs per task per backend; per-call CLI flags (`--vision-model`, `--normalize-headings-model`) still win as the highest-precedence override.

`.env.example` lives in the repo root. `bin/setup` copies it to `.env` on first run (gitignored); `bin/run` auto-sources it.

## Common patterns

### Skip diagrams (no API key needed)

```python
to_markdown("scan.pdf", output_dir="./out", diagrams=False)
```

### Override the vision model for higher accuracy

```python
to_markdown(
    "architecture-diagrams.pdf", output_dir="./out",
    vision_model="claude-sonnet-4-6",   # ~10× cost, better on dense diagrams
)
```

### Tune vision-pass parallelism

The pass parallelizes per image via `ThreadPoolExecutor`. Sensible ceilings:

- `claude_code`: **4–8**. Each `claude --print` is its own Python + model load — too many concurrent subprocesses thrash a laptop's RAM.
- `anthropic`: **16–32**. Network-bound, rate-limited by tier.
- `openrouter`: **8–16**.

```bash
bin/run convert textbook.pdf -o ./out --vision-concurrency 16
```

### Iterate cost-free with Claude Code as the vision backend

```bash
pagespeak convert manual.pdf -o ./out \
    --vision-backend claude_code \
    --vision-model claude-haiku-4-5-20251001
```

Caveats: ~1–3s per image (vs ~500ms direct Anthropic). `vision_model` always fires as `--model` to `claude --print` — a missing override resolves to Haiku, never to your interactive session's Sonnet/Opus. The `claude` binary must be on PATH.

### Route through OpenRouter for unified billing

```bash
OPENROUTER_API_KEY=sk-or-v1-... pagespeak convert manual.pdf -o ./out \
  --vision-backend openrouter \
  --vision-model anthropic/claude-haiku-4.5
```

Or:

```python
result = to_markdown(
    "manual.pdf",
    output_dir="./out",
    vision_backend="openrouter",
    vision_model="google/gemini-2.0-flash-exp",   # OpenRouter model-id format
)
```

Trade-offs vs direct Anthropic: ~5–10% credit markup, extra ~100 ms hop, no Anthropic prompt-caching exposure. Useful when consumer projects already standardize on OpenRouter for cross-provider billing — pagespeak's vision calls then ride the same auth + invoicing lane.

### Fix flattened heading hierarchy on a textbook PDF

When Marker emits chapter headings and their subsections at the same depth, the splitter loses the chapter ancestor. Opt into renormalization:

```bash
bin/run convert textbook.pdf -o ./out --normalize-headings
```

Default is heuristic mode (`Chapter N` → L1, `N.M` → L2, …). For unusual front-matter or non-numbered chapters, use `--normalize-headings-mode llm`. Full doc: [docs/normalize-headings.md](normalize-headings.md).

### Iterate on a big PDF without paying full conversion each time

```bash
pagespeak convert thick-textbook.pdf -o ./out --page-range "0-19" --device cpu
```

`page_range` accepts `"0-19"`, `"0-3,5,7-9"`, or a list of ints (Docling collapses to (min, max) and logs a WARNING).

### Split a manual into per-section files

```python
result = to_markdown(
    "user-manual.pdf",
    output_dir="./out",
    cleanup="aggressive",
    cross_refs="remap",        # rewrite [label](#page-X-Y) to [label](#heading-slug)
    split_sections=True,
    nested_split=True,
    split_min_level=2,         # coarser than the default 1: split on ## but bundle deeper headings
)
# ./out/sections/INDEX.md + nested per-section files
```

For RAG-shaped output, prefer `--preset rag-default` — it bundles sensible defaults for cleanup + split + normalize. See [docs/presets.md](presets.md).

### Convert a Canvas quiz export

```bash
# Point at the unzipped export directory or the .imscc archive.
pagespeak convert biol-2420-quiz-export/ -o ./out --preset qti
```

This writes one full-pipeline document per exam under `./out/<Exam>/` — each with its own stage checkpoints, master doc, `images/`, and a `sections/` per-question split (rich provenance frontmatter), so each exam ingests into a RAG DB like any other document. Pass `--no-answer-key` for blank quizzes. Vision is off by default for QTI (figures copied + linked with alt text); pass `--diagrams` to opt in. See [docs/canvas-quizzes.md](canvas-quizzes.md).

### Tag a source for a multi-source RAG DB

```bash
# rag-default turns provenance on; the label auto-derives from the filename.
pagespeak convert textbook.pdf -o ./out --preset rag-default \
    --source-type textbook

# Override the auto-derived label for a cryptic filename:
pagespeak convert "quick-start-guide.pdf" -o ./out \
    --preset rag-default --source-type textbook \
    --source-label "Quick Start Guide"
```

Stamps a YAML frontmatter block (`source_type` / `source_label` / `source_file` + `doc_title` + per-section locators) on the whole-doc markdown **and every section file**, so a downstream RAG DB combining several books, labs, and lectures can tag and locate each retrieved chunk by origin. The label auto-derives from the cleaned filename when `--source-label` is omitted; `source_type` is omitted from the block unless supplied (it's never guessed). `INDEX.md` is left untagged (it's navigation, not a chunk). Provenance is on under `--preset rag-default` (or the bare `--provenance` flag); without either, output is byte-for-byte unchanged. Re-tag an already-converted doc at zero LLM cost with `--from split --preset rag-default` (re-uses the `visioned.md` checkpoint).

### Re-test a downstream stage without re-running upstream

```bash
pagespeak convert manual.pdf -o ./out --rerun-from cleanup
```

Busts the cleanup snapshot and everything downstream (normalize, vision, split), then re-runs from there. The `ingest` cache (`<stem>.raw.md`) is preserved. See [docs/caching.md](caching.md).

## Sandboxes and process pools

Some sandboxes block `os.sysconf("SC_SEM_NSEMS_MAX")`, which prevents `ProcessPoolExecutor` from starting. Marker uses one during PDF conversion; `pagespeak ingest --workers N` uses one for parallel chunk workers. If you hit `PermissionError` with text pointing at `docs/operations.md`, see [operations.md](operations.md).

## Marker / surya on Apple Silicon

Marker's surya layout model crashes on MPS (`AcceleratorError: index … is out of bounds`) on the majority of real PDFs. Workarounds:

```bash
# Force CPU for the run (slower but reliable)
pagespeak convert manual.pdf -o ./out --device cpu

# Or try MPS with CPU fallback for unsupported ops
PYTORCH_ENABLE_MPS_FALLBACK=1 pagespeak convert manual.pdf -o ./out
```

This is an upstream Marker/surya bug.

> **`--device` is sticky:** Marker caches its model artifacts globally per process on the first call. Subsequent calls with a different `device` are silently ignored (a WARNING is logged). To switch devices, restart the process.

## Web console

The web console is a localhost FastAPI app that puts every pagespeak operation behind a browser UI. It requires the `pagespeak[web]` extra.

### Install and launch

```bash
bin/setup --web           # install FastAPI + uvicorn + jinja2 into the project venv
bin/start                 # start the console in the background at http://127.0.0.1:8810
bin/stop                  # stop it   (bin/restart = stop + start)
```

`bin/start` runs detached (`nohup`) — it returns your prompt and writes its PID + log to `logs/.pagespeak-web.{pid,log}`; there is no foreground process.

Or run it in the foreground (e.g. for one-off debugging):

```bash
pip install -e ".[web]"
uvicorn pagespeak.web:create_app --factory --host 127.0.0.1 --port 8810
```

Environment variables controlling the console: `PAGESPEAK_WEB_HOST` (default `127.0.0.1`), `PAGESPEAK_WEB_PORT` (default `8810`), `PAGESPEAK_WEB_CONCURRENCY` (default `1`), `PAGESPEAK_CONVERSIONS_DIR` (default `<cwd>/conversions`).

### The `conversions/` store

The console adopts the existing `conversions/` convention:

- `conversions/in/<name>.<ext>` — source documents.
- `conversions/out/<dir>/` — per-document output (phase checkpoints, `images/`, `.vision-cache/`, `.pagespeak-run.json`).

**Dropping a file into `conversions/in/` via Finder is identical to uploading via the web form** — both surface the same Conversion in the queue. Web upload writes the file into `conversions/in/`; nothing else differs. The console scans both directories on every page load to build the Conversion list.

### Home / queue

The home page lists all Conversions (not-yet-converted / running / done / failed) and shows a live HTMX-polled queue of active and recent jobs with current phase, progress, elapsed time, and cancel/retry controls.

### Conversion detail cockpit

The detail page for each conversion shows:

- **Phase strip** — `ingest ✓ · cleanup ✓ · normalize – · repair ✓ · structure ✓ · vision ✓ · split –`, derived from which phase checkpoints exist on disk. Each phase offers run / re-run from here / view this checkpoint.
- **Checkpoint viewer** — rendered markdown for any checkpoint (`raw`, `cleaned`, `normalized`, `repaired`, `structured`, `visioned`, final).
- **Image gallery** — thumbnails from `images/` with vision captions, Mermaid previews, and diagram type.
- **Run record** — `resolved_flags` from `.pagespeak-run.json`, pre-filled into the options form for re-runs (rerun-safety: a re-run carries the same `split_sections` / `nested_split` / `preset` flags as the original).
- **LLM summary** — calls, cost, and cache hits/misses for this Conversion's jobs, with links into the `/admin/llm` dashboards.

### Cost gate

Before any job that includes vision with `--diagrams` (and not `--vision-cache-only`), the console computes the cache-miss count — images in `images/` minus matching phashes in `.vision-cache/` — and shows it explicitly:

> *"40 images · 31 cached · 9 live calls. Backend claude_code → 9 Max-quota calls ($0)."*

An explicit confirm is required before the job starts.

- **Vision backend defaults to `claude_code` ($0)**. Selecting a paid backend (anthropic / openrouter) shows a grounded $ estimate (~3–5K tokens/image) with a louder warning. There is no silent switch to a paid backend.
- The **cache-only toggle** (`--vision-cache-only`) makes cost provably zero — uncached images become caption-only skips.
- If the cache state cannot be determined, the UI says so rather than quoting "cheap".

### LLM observability

The `/admin/*` routes mount `pf_core.web.llm_admin` as-is — dashboard, LLM run log, cost by model/agent, job queue, cache stats, and budget caps. Per-conversion LLM summary on the detail page is a filtered view of the same data, keyed by `job_id`.

Full doc: [docs/web.md](web.md).
