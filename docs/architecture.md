# Architecture

## Two entry points

```
                       ┌──────────────────────────────────────────────────────┐
    any doc  ─────────▶│  to_markdown(path)  /  pagespeak convert …           │
                       └──────────────────────────┬───────────────────────────┘
                                                  │
                       ┌──────────────────────────▼───────────────────────────┐
                       │  Ingest phase (_ingest.py)                           │
                       │  Format dispatch:                                    │
                       │    PDF_SUFFIXES  → _pdf_dispatch (Marker or Docling) │
                       │    MARKITDOWN_SUFFIXES → _docx (MarkItDown)          │
                       │    MARKDOWN_SUFFIXES → _markdown (verbatim)          │
                       │                                                      │
                       │  workers=1 (default): single-process backend call    │
                       │  workers>1 (PDF only): ProcessPool of Marker workers  │
                       │    ↳ per-chunk page-range prefix on image basenames  │
                       │    ↳ page-anchor ID absolutization across chunks     │
                       │    ↳ concat all chunks into <stem>.raw.md            │
                       │                                                      │
                       │  → writes <stem>.raw.md + images/ (checkpoint)       │
                       └──────────────────────────┬───────────────────────────┘
                                                  │
                       ┌──────────────────────────▼───────────────────────────┐
                       │  Phase pipeline: a list of Phase objects run by      │
                       │  the sequencer (_sequencer.run_pipeline). Each phase │
                       │  reads its input checkpoint, writes its output one.  │
                       │                                                      │
                       │  ingest    → <stem>.raw.md  + images/                │
                       │  cleanup   → <stem>.cleaned.md   (frontmatter strip  │
                       │              + phash decoration dedup + cleanup)     │
                       │  normalize → <stem>.normalized.md                    │
                       │              └─▶ .heading-normalize-cache/           │
                       │  repair    → <stem>.repaired.md  ($0 heading fixes)  │
                       │  structure → <stem>.structured.md  ($0 doc-level)    │
                       │  vision    ← <stem>.structured.md                    │
                       │              gather (.vision-cache/) + inject + TOC  │
                       │              → <stem>.visioned.md                    │
                       │  split     ← <stem>.visioned.md → sections/ [opt]    │
                       │                                                      │
                       │  --from X / --stop-after X run any contiguous slice; │
                       │  X==X runs exactly one phase. See caching.md.        │
                       └──────────────────────────────────────────────────────┘
```

`to_markdown()` / `pagespeak convert <file>` runs both phases in one call. For very large PDFs, `pagespeak ingest <file> --workers N` runs the backend phase separately (resumable, parallel), then `pagespeak convert <outdir>` runs Phase 3 on the produced `<stem>.raw.md`. Both paths produce the same `IngestResult` shape downstream. See [ingest.md](ingest.md).

## Modules (under `src/pagespeak/`)

Modules are organized into role-based subpackages. All public symbols are re-exported from `pagespeak.__init__`.

### `backends/`

| Module | Responsibility | Lazy import? |
|---|---|---|
| `backends/_pdf_dispatch.py` | `convert()` routing: picks Marker, Docling, or Top Hat based on `pdf_backend` arg. | — |
| `backends/_pdf.py` | Marker wrapper — `convert_pdf()`. | yes — `marker.*` only on first PDF call |
| `backends/_tophat.py` | Top Hat quiz-export PDF backend (`--pdf-backend tophat`): the data model (`TopHatQuiz`/`TopHatQuestion`), the `pypdfium2` text-layer reader (`extract_lines`), and the `convert_pdf_tophat` entry that wires parse + answers + figures + render. See `docs/tophat-quizzes.md`. | yes — `pypdfium2` only when `pdf_backend="tophat"` |
| `backends/_tophat_parse.py` | Text lines → `TopHatQuiz`: chrome strip, marker segmentation (gradable + bare), stem/option parsing (sequential `A,B,C…` run detection rejects a stem that starts with a capital letter; multi-line options), and fill-in-the-blank parsing (lift the answer value(s), drop the `blankN` labels). | — |
| `backends/_tophat_answers.py` | Reads the *visual* answer key from an answers-populated Top Hat export: the correct option's letter glyph is light grey (`r==g==b`), so it detects grey letters by pdfium fill color and buckets each under its question marker → `{question: [correct letters]}`. Deterministic, $0. | yes — `pypdfium2` |
| `backends/_tophat_images.py` | Extracts embedded figures (recursing into form XObjects) and binds each to its question **by page** (nested figures report form-local coords, so y is unusable). Image-only questions survive; the vision pass captions the figures. | yes — `pypdfium2` |
| `backends/_tophat_render.py` | Parsed Top Hat quiz model → markdown (`## Question N` blocks, figure refs, `✓` + `**Correct answer:**` line). Mirrors `_qti_render.py`. | — |
| `backends/_pdf_docling.py` | Docling wrapper — `convert_pdf_docling()`. | yes — `docling` only on first call |
| `backends/_docx_dispatch.py` | DOCX backend selection (`markitdown` vs `python-docx`) — mirrors `backends/_pdf_dispatch.py`. | — |
| `backends/_docx.py` | MarkItDown wrapper + `zipfile` image extraction for office formats; dispatches EPUB → `_extract_epub_media` and HTML → `_remote_images.download_remote_images`. | yes — `markitdown` only on first non-PDF call |
| `backends/_remote_images.py` | HTML ingest: download remote `<img>` URLs into `images/<name>` + retarget refs so the vision pass sees them (`download_remote_images`). On by default; gated by `PAGESPEAK_DOWNLOAD_REMOTE_IMAGES`. See `docs/format-support.md` § HTML. | `httpx` (core dep) |
| `backends/_local_images.py` | The local half of the same gap: copy sibling-image refs (an HTML bundle's `images/` dir next to the source) into `<out>/images/` + retarget non-canonical refs (`localize_local_images_in_markdown`). Traversal-guarded; on by default; gated by `PAGESPEAK_COPY_LOCAL_IMAGES`. | — |
| `backends/_markdown.py` | Markdown / plain-text passthrough — `convert_markdown()` reads a `.md`/`.markdown` source **verbatim** into `raw.md` (no MarkItDown round-trip, which would re-emit lists/headings lossily). No image extraction; remote refs are localized later in the cleanup phase. Lets an upstream ingester hand off clean markdown. See `docs/format-support.md` § Markdown. | — |
| `backends/_docx_table.py` | GFM table rendering for the python-docx backend. `render_table()` converts Word tables to `\|` rows + `<br>`-joined multi-para cells; called by `_docx_structured.py`. | yes |
| `backends/_docx_structured.py` | python-docx structure-faithful reader. `render_markdown()` walks the body, maps `numPr`/heading-styles to ATX headings + nested lists, coalesces runs, promotes a headless title, runs the heading-quality pass. | yes — `docx` only when `docx_backend="python-docx"` |
| `backends/_docx_walk.py` | Body-order traversal + Word numbering resolution (`numId`/`ilvl` → level) for the structure-faithful DOCX backend. | yes |
| `backends/_docx_quality.py` | Heading-quality normalization for the structured reader (pure text, no docx deps): `strip_heading_emphasis`, `is_junk_heading`, `emit_heading`, `demote_nonsection_h1` (bodyless + list-continuation shells). Split out to stay under the file-size budget. See `docs/docx-backends.md`. | — |
| `backends/_qti.py` | Canvas QTI quiz-export backend: `is_qti_export()` (detection), `enumerate_quizzes()` (resolve export + per-exam XML + media map), `convert_qti_exam()` (one exam → raw markdown + its figures), `split_quiz_into_questions()` (per-question docs + frontmatter). See `docs/canvas-quizzes.md`. | — |
| `backends/_qti_parse.py` | QTI + `assessment_meta` XML → normalized `Quiz`/`QuizQuestion` model; per-type correct-answer extraction (`<varequal>` not under `<not>`). | — |
| `backends/_qti_render.py` | Normalized quiz model → markdown: exam title as the only `#` H1, each question a `## Question N` heading, answer key marked. | — |
| `backends/_qti_split.py` | Per-question split of a quiz/exam markdown → `sections/Question NNN.md` (rich frontmatter) + master-doc frontmatter. Drives the QTI fan-out (`split_quiz_into_questions`, `exam_frontmatter`) AND the generic pipeline's Top Hat quizzes (`split_quiz_doc`, `quiz_master_frontmatter`); `title_field` selects the `exam:` vs `quiz:` key so both share one schema. | — |

### `models/`

| Module | Responsibility | Lazy import? |
|---|---|---|
| `models/_models.py` | `Diagram`, `IngestResult` dataclasses. No logic. | — |
| `models/_pipeline.py` | `Manifest` dataclass (schema v3) + atomic JSON read/write + per-chunk state helpers (`ChunkState`). | — |
| `models/_quiz.py` | `Quiz`, `QuizQuestion`, `QuizOption` frozen dataclasses — the QTI parse→render intermediate model. No logic. | — |

### `prompts/`

Versioned LLM-facing prompts: each YAML (`diagram.yaml`, `heading_normalize.yaml`, `heading_normalize_full.yaml`) carries an `agent` slug, a `version`, and a changelog; a sibling `_<agent>.py` renders it at import time. See `docs/diagrams.md` § The prompt.

| Module | Responsibility | Lazy import? |
|---|---|---|
| `prompts/_loader.py` | `load_pagespeak_spec()` — prompt-spec loading via pf-core's `load_prompt` (override chain: `$PAGESPEAK_PROMPTS_DIR` → CWD `config/prompts/` → bundled default). Shared by all per-agent stub modules. | — |
| `prompts/_diagram.py` | Diagram-extraction prompt — renders `diagram.yaml`; exports `DIAGRAM_PROMPT` / `DIAGRAM_PROMPT_VERSION`. | — |
| `prompts/_heading_normalize.py` | Heading-normalize (`llm` mode) prompt — renders `heading_normalize.yaml`. | — |
| `prompts/_heading_normalize_full.py` | Heading-normalize `llm_full` prompt — renders `heading_normalize_full.yaml`. | — |

### `utils/`

| Module | Responsibility | Lazy import? |
|---|---|---|
| `utils/_phash.py` | `compute_phash`, `cluster_phashes`, `detect_decoration_basenames`, `hamming_distance_hex`. Shared by single-shot and pipeline paths. | `imagehash`/`PIL` only inside `compute_phash` |
| `utils/_mathml.py` | Presentation-MathML → LaTeX pre-pass for the HTML ingest path (prevents body-text equation flattening). | — |
| `utils/_prompts.py` | `DIAGRAM_PROMPT` (versioned). | — |
| `utils/_html.py` | `html_fragment_to_markdown()` — sanitize + convert an inline HTML fragment to markdown (drop hidden/editor cruft, equation-image→LaTeX, media-token resolve, heading→bold, sub/sup flatten). Used by the QTI backend; available to any caller with inline HTML. | — |

### `services/`

| Module | Responsibility | Lazy import? |
|---|---|---|
| `services/_diagrams.py` | Vision backends (Anthropic / Claude Code / OpenRouter) + JSON parsing + markdown rewriting. | `anthropic` / `httpx` imported lazily inside the relevant backend |
| `services/_vision_cache.py` | `load()` / `write()` / `diagram_from_cache()` — atomic per-phash JSON cache for the single-shot vision pass. Keyed by image phash ONLY; reused regardless of which backend/model produced it (engine/model recorded as provenance, not a reuse gate). | — |
| `services/_vision_backends.py` | The three `analyze(image) -> Diagram` LLM clients (`Anthropic` / `ClaudeCode` / `OpenRouter`), the `VisionBackend` protocol, and the `build_backend` factory. | `anthropic` inside the Anthropic backend |
| `services/_vision_backend_openrouter.py` | OpenRouter vision backend — `analyze(image) -> Diagram` via the chat-completions endpoint. | `httpx` at call time |
| `services/_vision_media.py` | Image media-type lookup shared by the API vision backends. | — |
| `services/_vision_parse.py` | Vision response parsing: model output (raw / fenced / preamble-wrapped JSON) → `Diagram`. | — |
| `services/_cleanup.py` | Cleanup pipeline (`off` / `basic` / `aggressive`). Each per-line transform exposed as a named function. | yes — only imported when `cleanup != "off"` |
| `services/_cleanup_diagnose.py` | Detect→correct dispatch for whole-document heading cleanup: each demotion pass registers a diagnosis; passes fire only when their defect is present. | — |
| `services/_cleanup_transforms.py` | Per-line cleanup transforms: garbage/HTML/whitespace stripping, numbered-heading promotion + depth-locking, emphasis stripping, list-bullet normalization, cross-ref repair, page-span/ref stripping, Marker-pollution removal. | — |
| `services/_cleanup_structure.py` | Structural cleanup passes: heading-slug + anchor-map building, page-ref remapping, TOC-phantom-heading demotion, recurring-scaffold-heading demotion, consecutive-heading dedup. | — |
| `services/_cleanup_regexes.py` | Shared regex + constant table for the cleanup passes. | — |
| `services/_frontmatter.py` | Template-frontmatter strip for DOCX sources (`strip_template_frontmatter`) — strips *input* boilerplate; distinct from `_provenance.py`, which emits *output* frontmatter. | — |
| `services/_decorations.py` | Decoration phash dedup: `detect_and_strip_decorations()` clusters repeated page-headers / footers / watermarks and strips their refs. | — |
| `services/_outline.py` | Word multilevel-list → heading/list reconstruction. `promote_outline()` runs as cleanup pre-pass before per-line normalizations. | — |
| `services/_heading_sanity.py` | `demote_prose_heading()` — heuristic post-promote pass that demotes prose-shaped numbered titles back to list items. | — |
| `services/_heading_normalize.py` | `gather_normalize_levels()` / `apply_normalization()` — opt-in LLM pass that fixes flattened chapter+subsection levels via Claude Code. | yes — only imported when `normalize_headings=True` |
| `services/_normalize_llm.py` | LLM heading-normalize machinery: prompt building, invocation, response parsing, model/token resolution, response cache key. | yes |
| `services/_normalize_heuristic.py` | Deterministic heuristic heading-level assignment + the structural filter (`heuristic` mode). | — |
| `services/_normalize_decision.py` | `resolve_normalize_mode()` — auto-select the heading-normalize engine per document from a $0 no-LLM heading-shape signal (`auto` mode). | — |
| `services/_normalize_repair.py` | `repair_headings()` — $0 deterministic post-LLM heading repair (detect→correct, no-op on a clean doc): numbered-depth lock, span-strip, number-only / doubled-text / spaced-divider demotes. | — |
| `services/_fragments.py` | `demote_orphan_fragments()` — demotes short page-margin-junk headings (`EN`, `FR`) at the document's deepest level; a cleanup demotion pass (outline-skipped, registered in `_cleanup_diagnose`). | — |
| `services/_listish_headings.py` | `demote_listish_bare_int_headings()` + `demote_listish_dotted_int_headings()` — document-relative demotion of integer-prefixed list items Marker promoted to headings (`# 19 Pair`, `#### 1. Click.`); fires only when the doc uses the integer prefix as a list, not as its section spine. Cleanup demotion passes (outline-skipped, registered in `_cleanup_diagnose`). | — |
| `services/_toc.py` | `regenerate_toc()` — replaces Marker's structurally-broken pipe-table TOC with a generated bullet list. | — |
| `services/_split.py` | `split_into_sections()` — per-section file writer with optional nested folders + `INDEX.md`. Empty-body filter, chapter-shell preservation, parent breadcrumbs, Chapter-N pattern detection, stale-file cleanup. With `provenance=`, emits **rich** per-section frontmatter — source tags + `doc_title` + derived `section_title` / `section_path` (ancestor breadcrumb, via `_section_path`) / `section_number` / `heading_level`; or a uniform `frontmatter=` block. | yes |
| `services/_split_parse.py` | Markdown → `_Section` tree parsing for the splitter. | — |
| `services/_split_filter.py` | Section-set filtering for the splitter: TOC-phantom dropping, empty-body selection (with chapter-shell preservation), filename-collision dedup. | — |
| `services/_split_pack.py` | Size-targeted section packing (`--split-target-kb`): per-branch fit-or-descend + part-splitting of oversized flat sections. | — |
| `services/_split_identity.py` | Per-section identity frontmatter (`doc_id` / `section_id` / `parent_id` / `order` + the provenance merge). | — |
| `services/_split_write.py` | Section file/path construction + writing for the splitter. | — |
| `services/_language.py` | Conservative section-language classification for the opt-in `--english-only` split filter (subtree-aggregate + foreign-evidence signals). | — |
| `services/_provenance.py` | `build_frontmatter()` (ordered dict → YAML, JSON-encoded values, skips None) + `build_provenance_frontmatter()` (the opt-in base `source_type` / `source_label` / `source_file` triple). The multi-source RAG tag enabler; the split phase builds the rich per-section block on top of these. Distinct from `_frontmatter.py` (which strips *input* frontmatter). | — |
| `services/_deliver.py` | `strip_for_delivery()` — mirror a converted output dir into a parallel delivery dir keeping only the master `.md` + `sections/` + `images/`; drops stage checkpoints (suffixes derived from the stage registry), run records, content caches, chunks, manifests. Powers `pagespeak deliver`; handles a single doc or a fan-out export; rebuilds the destination on each run. | — |
| `services/_audit_checks.py` | Pure text-defect detectors for `pagespeak audit` (`AuditFinding` + one `text -> findings` function per observed defect shape: collapsed tables, HTML debris, U+FFFD, entities, shattered emphasis, duplicate headings). Fence-aware; detectors report, never fix. | — |
| `services/_audit.py` | `audit_paths()` / `render_report()` — walks final artifacts (skips checkpoints, `chunks/`, dot-dirs), adds file-context checks (orphan-shell sections, dangling image refs), aggregates an `AuditReport`. Powers `pagespeak audit`. See `docs/audit.md`. | — |
| `services/_image_refs.py` | `degrade_missing_image_refs()` — rewrites an image ref whose local target is missing on disk into its alt text (an italic caption); external `http`/`data` refs untouched. The complementary FIX to the audit's `dangling_image_ref` check; runs in the vision phase so a broken `![alt](missing)` link becomes the RAG-usable description. | — |
| `services/_vision_audit.py` | `audit_vision()` / `check_identity_divergence()` — flags likely-confabulated vision captions by comparing each generated caption (`.vision-cache`) to the author's source alt (`structured.md`): a caption that keeps none of the alt's subject words is a candidate. Domain-agnostic (generic figure/English filter only), $0, no LLM. Powers `pagespeak vision-audit`. See `docs/audit.md`. | — |
| `services/_table_repair.py` | `repair_collapsed_tables()` — splice the clean grid Docling extracts from a collapsed table's PDF page in place of Marker's `<br>` mega-cell. Pure splice logic (find mega-cells, match table by content overlap) + injected I/O helpers (`locate_page_in_pdf`, `docling_page_md`). Powers `pagespeak repair-tables`. | yes (`pypdfium2` / Docling backend imported lazily in the I/O helpers) |
| `services/_chunk_rewrite.py` | Chunk-worker output rewriting: per-chunk image-basename prefixing + page-anchor ID absolutization, so concatenated chunks don't collide. | — |
| `services/_presets.py` | Curated config presets for `to_markdown` / `pagespeak convert` (`rag-default`, `flat`, `textbook`, `archival`, `qti`). | — |
| `services/_rerun.py` | Cache invalidation for `--rerun-from <stage>` / `pagespeak invalidate`: `RERUN_STAGES` + the `PAGESPEAK_REGISTRY` stage→file registry. | — |
| `services/_run_record.py` | Writes `<output_dir>/.pagespeak-run.json` (resolved flags + counts + source identity) after every successful run. | — |
| `services/_baseline.py` | Baseline snapshots — `save_baseline()` preserves a run's deliverables under `.baselines/<label>/` for later comparison. | — |
| `services/_baseline_diff.py` | Baseline diff — run-record field diff, section-set add/remove/rename detection, per-section line-count rollup. | — |

### `orchestrators/`

| Module | Responsibility | Lazy import? |
|---|---|---|
| `orchestrators/_dispatch.py` | `to_markdown()` impl: thin adapter — preamble (preset/flag resolution, dir-mode, cache invalidation, run-record) builds a `PipelineContext`, calls `run_pipeline`, then teardown. No inline stage logic. Detects a QTI export (`is_qti_export`) and delegates to `_qti_export.run_qti_export` (fan-out). | — |
| `orchestrators/_dispatch_setup.py` | `to_markdown` setup helpers: preset/flag resolution + dir-mode input resolution, extracted from `_dispatch.py`. | — |
| `orchestrators/_resume.py` | Resume helpers for the single-shot dispatcher (`_try_resume_from_checkpoint` / `_try_resume_from_cleaned`). | — |
| `orchestrators/_qti_export.py` | `run_qti_export()` — fan-out: one independent full-pipeline document per exam (per-exam ingest → dir-mode `to_markdown` for cleanup/vision/checkpoints → master doc → per-question split). | — |
| `orchestrators/_phase.py` | The `Phase` protocol: `name`, `is_fresh(ctx)`, `run(ctx)`. A phase's on-disk checkpoint is its sole interface to its neighbours. | — |
| `orchestrators/_phases.py` | The seven concrete phases (`Ingest`/`Cleanup`/`Normalize`/`Repair`/`Structure`/`Vision`/`Split`) + `build_phases()`. Each `run()` reads its input checkpoint and writes its output one; `_load_input` hydrates a phase's input checkpoint when started mid-pipeline (no-op in the full run). | — |
| `orchestrators/_split_output.py` | `SplitPhase`'s section-writing + master frontmatter, extracted to stay under budget: quiz docs (`source_type=="quiz"`) split with rich per-question frontmatter via `backends/_qti_split`; everything else gets the rich per-section provenance (`doc_title` + breadcrumb locators) when source flags are set. | — |
| `orchestrators/_sequencer.py` | `run_pipeline(phases, ctx, start, stop_after)` — pure slice selection (resume-skip-fresh / `start` / `stop_after` / `rerun_from`). Zero pipeline logic. The "process that runs phases in order". | — |
| `orchestrators/_context.py` | `PipelineContext` — resolved config + derived checkpoint paths + mutable `IngestResult`; `do_normalize`/`do_vision` props. Data only. | — |
| `orchestrators/_ingest.py` | `ingest()` — unified backend phase. `workers=1` runs single-process; `workers>1` runs `_chunk.py` workers then concatenates. A QTI export is rejected here (it fans out per exam — use `convert`). Writes `<stem>.raw.md` + `images/`. Canonical `PDF_SUFFIXES` / `MARKITDOWN_SUFFIXES` / `MARKDOWN_SUFFIXES` format-suffix sets live here. | yes (delegates to `backends._pdf_dispatch` per chunk) |
| `orchestrators/_chunk.py` | `chunk()` — ProcessPoolExecutor of Marker workers, page-range slicing, max-pages cap, resume via manifest. Used internally by `_ingest.py` when `workers>1`. Per-chunk output rewriting lives in `services/_chunk_rewrite.py`. | yes |

### `cli/`

| Module | Responsibility | Lazy import? |
|---|---|---|
| `cli/__init__.py` | Typer app, validators, `main()` entry point. | — |
| `cli/_convert.py` | `convert` subcommand — accepts a file path (runs ingest + Phase 3) or an output dir with `<stem>.raw.md` (Phase 3 only). | — |
| `cli/_ingest.py` | `ingest` subcommand — backend phase only (`--workers` flag for chunked-parallel PDF). | — |
| `cli/_invalidate.py` | `invalidate` subcommand — bust caches at a stage (plus downstream structural files) without re-running. | — |
| `cli/_baseline.py` | `baseline` subcommand (`save` / `list` / `diff`) — snapshot a run's deliverables; compare runs. | — |
| `cli/_deliver.py` | `deliver` subcommand — strip an output dir to delivery-ready files (master `.md` + `sections/` + `images/`). | — |
| `cli/_audit.py` | `audit` subcommand — output-defect scan over converted output dirs / files; exit 1 on errors. | — |
| `cli/_repair.py` | `repair-tables` subcommand — Docling-splice fix for collapsed tables in an existing out-dir; patches `<stem>.raw.md`, `--dry-run` previews. | — |
| `cli/_vision_audit.py` | `vision-audit` subcommand — flag likely-confabulated vision captions; `--summary-only` for totals, `--strict` exits 1 on findings. | — |

### `web/`

Optional layer, behind the `pagespeak[web]` extra (FastAPI + uvicorn + jinja2). Never imported by the core library or CLI; consumers of `to_markdown` pay zero weight for it.

| Module | Responsibility | Lazy import? |
|---|---|---|
| `web/__init__.py` | `create_app()` — app factory; mounts `pf_core.web.llm_admin` + routers. | yes — `fastapi` only when the extra is installed |
| `web/__main__.py` | `python -m pagespeak.web` — run the console under uvicorn. | — |
| `web/_config.py` | `PagespeakWebConfig` — reads `PAGESPEAK_CONVERSIONS_DIR` / `PAGESPEAK_WEB_HOST` / `PAGESPEAK_WEB_PORT` / `PAGESPEAK_WEB_CONCURRENCY`. | — |
| `web/_command.py` | Builds the `pagespeak convert` argv + per-job paths for the worker subprocess. | — |
| `web/_db.py` | One-call DB initialization for the web console. | — |
| `web/_scan.py` | `conversions/in` + `conversions/out` scanner and reconciler → Conversion list/detail. Reuses `orchestrators._dispatch.resolve_dir_mode_stem` to extract the checkpoint stem. | — |
| `web/_cost.py` | Cache-miss pre-flight: counts images in `images/` vs phash entries in `.vision-cache/`; produces a grounded cost estimate for the confirm dialog. | — |
| `web/_jobs.py` | Registers the `pagespeak_convert` pf_core job kind (inputs/outputs schema). | — |
| `web/_worker.py` | In-process background worker: `JobRepo.claim_next(kinds=["pagespeak_convert"])` → phase-driver subprocess loop (`pagespeak convert <out_dir> --from P --stop-after P <options>`). Passes `PAGESPEAK_JOB_ID` env so pf_core attributes LLM rows to the job. | — |
| `web/api/pages.py` | HTML routes: home/queue, new-conversion form, detail cockpit. | — |
| `web/api/actions.py` | Action routes: submit job, cancel, retry, upload source file. | — |
| `web/api/partials.py` | HTMX partial routes: live queue table, phase strip, log tail. | — |

**Worker → subprocess → checkpoint data flow:** the worker spawns `pagespeak convert <out_dir> --from <phase> --stop-after <phase>` as a subprocess per job (not one subprocess per phase — the CLI slice covers the full requested range). Subprocess isolation keeps Marker/torch and the macOS `ProcessPoolExecutor` quirks out of the web process. On phase completion, the checkpoint is written to `conversions/out/<dir>/`; the HTMX phase strip reads checkpoint presence on every poll. See [docs/web.md](web.md).

### Root

| Module | Responsibility |
|---|---|
| `__init__.py` | Re-exports public API: `to_markdown`, `ingest`, dataclasses, type aliases. |
| `_agent_config.py` | Agent config resolution: per-task model + backend selection from `config/model_router.yaml`. |
| `_agent_runtime.py` | Per-task LLM call infrastructure with pf-core `llm_runs` tracking integration. |
| `_db.py` | Pagespeak DB configuration — thin wrapper over pf-core's connection helpers (`DATABASE_URL`). |

Lazy imports matter: a consumer that only ever processes DOCX never pays the cost of installing or importing torch / surya.

## Data flow

1. **Ingest phase** (`orchestrators/_ingest.py`) reads the file extension — canonical suffix sets `PDF_SUFFIXES`, `MARKITDOWN_SUFFIXES`, and `MARKDOWN_SUFFIXES` live in `_ingest.py` — and routes to `backends/_pdf_dispatch.py` (Marker or Docling), `backends/_docx.py` (MarkItDown), or `backends/_markdown.py` (verbatim passthrough for `.md`/`.markdown`). Unknown extensions raise `ValueError`. With `workers=1` (default), a single backend call processes the full document. With `workers>1` (PDF only), a `ProcessPoolExecutor` runs Marker on N-page chunks in parallel; `_chunk_rewrite.py` prefixes each chunk's image basenames with the page-range and absolutizes page-anchor IDs before concatenation. Either way the phase concludes by writing `<stem>.raw.md` + `images/` as a checkpoint.
2. **MarkItDown side-effect.** For office zip formats (DOCX/PPTX/XLSX), `_docx.py` extracts everything under `word/media/`, `ppt/media/`, or `xl/media/` into `output_dir/images/`. For EPUB it pulls embedded images out of the zip by extension; for HTML (where images are remote `<img>` URLs) it downloads each one via `_remote_images.py` and retargets the ref to `images/<name>` — both so the vision pass has local files to process. Local sibling refs (a saved-webpage bundle's `images/` dir next to the source) are copied into `output_dir/images/` by `_local_images.py` at the end of ingest (and again idempotently at cleanup for resume paths). If MarkItDown's markdown lacks image refs but images were extracted, an "Extracted Images" section is appended so the diagram pass has anchors.
3. **Phase pipeline — sequential, deterministic.** `to_markdown()` builds a `PipelineContext` and calls `orchestrators/_sequencer.run_pipeline()` over the ordered `Phase` list from `orchestrators/_phases.build_phases()`. Each phase reads its input checkpoint and writes its output checkpoint, so the sequencer can run any contiguous slice — `--from <phase>` (begin there, hydrating from the on-disk checkpoint), `--stop-after <phase>` (halt after), `--from X --stop-after X` (exactly one phase). The default run executes every phase in this order, which preserves correctness:
   - **Cleanup** (`services/_cleanup.py`) — begins with an outline reconstruction pre-pass (`services/_outline.promote_outline`) that converts Word multilevel-list indentation to heading/list structure; then per-line normalizations; numbered headings run through `_heading_sanity.demote_prose_heading` to undo wrong promotions. Snapshot to `<stem>.cleaned.md`.
   - **Strip decoration refs** (`orchestrators/_decorations.py`) — perceptual-hash clustering identifies repeated page headers / footer logos; their refs are removed.
   - **Gather + apply normalize** (`services/_heading_normalize.py`, opt-in) — heuristic computation OR one LLM call. Snapshot to `<stem>.normalized.md`.
   - **Repair** (`services/_normalize_repair.py`) — $0 deterministic detect→correct heading fixes on the frozen `normalized.md` (numbered-depth lock, span-strip, number-only / doubled / spaced-divider demotes); no-op by diagnosis on a clean doc. Snapshot to `<stem>.repaired.md`. Being its own phase lets `--from repair --stop-after repair` iterate the fixes for free without re-paying normalize.
   - **Structure** (`services/_enumerated_nest.py` + `services/_flat_source_demote.py` + `services/_h1_ratio_rebalance.py`) — $0 holistic doc-level passes on the frozen `repaired.md` (enumerated-item nesting, flat-H1-run demote, orphan-H1 rebalance); no-op on docs with a healthy heading pyramid. Snapshot to `<stem>.structured.md`.
   - **Gather diagrams** (`services/_diagrams.gather_diagrams`, opt-in): per-image fanout — phash → cache lookup → backend call on miss → cache write. Vision reads `<stem>.structured.md` and runs on the cleaned, normalized, repaired, structurally-rebalanced heading shape.
   - **Inject diagrams** — embed captions + mermaid blocks into the markdown.
   - **Regenerate TOC** (replace Marker's broken pipe-table TOC with a generated bullet list).
   - **Degrade missing image refs** (`services/_image_refs.degrade_missing_image_refs`) — any `![alt](target)` whose local target is missing on disk becomes its alt text (an italic caption), so a broken link is preserved as the RAG-usable description instead of a dead `![alt](missing)`. Runs regardless of whether vision was enabled (vision resolves refs whose images exist; this handles the rest). Vision's phase concludes by snapshotting the post-inject + post-TOC + post-degrade markdown to `<stem>.visioned.md` — its structural checkpoint, so `split` is independently runnable from the true post-vision state.
   - **Split sections** (opt-in) — reads `<stem>.visioned.md` (in a full run, the in-memory result, byte-identical) and writes `<output_dir>/sections/` with `INDEX.md` and breadcrumb headers; the consolidated `result.markdown` is unchanged.

The cache layers and re-test ergonomics around these stages are documented in [caching.md](caching.md).

## Why two format backends

Marker is purpose-built for PDF and produces dramatically better output on technical documents than anything else open-source. MarkItDown is purpose-built for "give the LLM something readable" across the office formats and the misc bag (CSV/JSON/XML/EPUB/HTML). Using each for what it's strongest at means we don't compromise on either path.

The cost is a single dispatch-by-extension function. That's it.

## Why two execution models within ingest

`workers=1` (default) is right for any document that fits in memory. Below ~50 pages the chunked-parallel overhead (manifest writes, image flattening, page-range rewriting) buys nothing.

`workers>1` buys three things for very large PDFs (~500+ pages):

- **Resume across crashes.** Each chunk's Marker output is a checkpoint.
- **Parallel Marker workers.** `ProcessPoolExecutor`, up to N workers.
- **Separation of backend and Phase 3.** Run Marker once; iterate on cleanup / normalize / split many times against the same `<stem>.raw.md`.

The trade-off — chunking flattens Marker's heading hierarchy because Marker decides depth from local font statistics that don't agree across chunks — is documented in [ingest.md](ingest.md).

## Error contract

| Failure | Behavior |
|---|---|
| Sandbox blocks `ProcessPoolExecutor` startup (chunked ingest) | `PermissionError` pointing at [operations.md](operations.md) |
| Unsupported file extension | `ValueError` |
| File doesn't exist | `FileNotFoundError` |
| Backend not installed | `ImportError` with the pip extra in the message |
| `ANTHROPIC_API_KEY` missing during diagram pass | `anthropic.AuthenticationError` surfaces to caller |
| Single diagram extraction fails | WARNING logged; caption-only `Diagram` returned; processing continues |

A flaky network on image 47 doesn't kill an ingest of 50 images. The non-fatal contract for single-image vision failures is deliberate.
