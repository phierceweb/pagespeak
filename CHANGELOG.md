# Changelog

Notable changes to pagespeak, newest first. The project is pre-1.0 — pin to a tagged release; `main` is the development line.

## 0.5.4

### Fixed
- Web console: the `structure` phase now appears in the checkpoint viewer and the help-page phase table (the route already served it).

## 0.5.3

### Fixed
- **Docs re-synced to the seven-phase pipeline.** Corrected vision's input checkpoint (`structured.md`, not `repaired.md`) and every stage/checkpoint enumeration that omitted `structure`; refreshed stale checkpoint filenames (including the removed `pre-normalize.md` snapshot — heading-normalize review/revert is now documented against `cleaned.md`/`normalized.md`); completed `docs/architecture.md`'s module tables (all eight CLI subcommands, ~40 missing modules, a new `prompts/` section, two mis-pathed rows); labeled vision cost/latency figures as operating estimates and documented the model-switch × phash-cache interaction (`--rerun-from vision` to re-analyse under a different model).

### Added
- **Docs-drift guard** (`tests/test_docs_sync.py`): phase lists, stage sequences, checkpoint chains, `consumed by` notes, and the architecture module inventory are verified against `build_phases()` and the stage registry — a pipeline change now fails the suite naming each stale doc.

## 0.5.2

### Changed
- README carries a PyPI version badge and its doc/`SECURITY.md` links are now absolute `github.com/phierceweb/pagespeak/blob/main/...` URLs, so they resolve on the PyPI project page (relative links there 404).

## 0.5.1

### Changed
- Prompt specs load through pf-core's `load_prompt`: `prompts._loader.load_pagespeak_spec(slug)` replaces `resolve_prompt_path` (same override chain — `$PAGESPEAK_PROMPTS_DIR` → CWD `config/prompts/` → bundled default).
- Tracking-resolver imports use the public `pf_core.llm.tracking` surface instead of the private `_resolvers` module.

## 0.5.0

### Fixed
- **`claude_code` calls run isolated (`--safe-mode`) — required via the pf-core 0.5 floor.** pf-core's `ClaudeCodeClient` runs every `claude --print` subprocess with `--safe-mode` by default, so a conversion no longer auto-loads the working directory's `CLAUDE.md`, skills, or hooks — ambient context that could hijack a weak model into emitting skill text where an image caption (or normalized headings) belong. pagespeak's dependency floor rises to `pf-core ~= 0.5.0` (the old `~= 0.4.1` floor admitted un-isolated versions), pinned by a canary test on the `isolate=True` default.
- **`to_markdown()` now writes the final `<stem>.md` master itself.** The write was CLI-only, so a library consumer (or a split-only re-run driven through the library) produced sections and checkpoints but no master document. The library now owns the write — same guard as before: an early `stop_after` never clobbers the final document with an intermediate checkpoint.

### Added
- **Local sibling images are copied into the output during ingest.** An HTML bundle (saved webpage / doc-site export) ships the document plus a sibling `images/` dir with relative refs; nothing copied those files into the output, so the vision pass — which only reads `<out>/images/` — reported zero images and every figure was lost to captioning. HTML/markdown ingest now copies each locally-resolvable ref into `<out>/images/` (retargeting non-canonical refs to a flat collision-resistant name), the local counterpart of the existing remote-image download. Traversal-guarded: a ref escaping the source's own directory is ignored. Gated by `PAGESPEAK_COPY_LOCAL_IMAGES` (default on).

## 0.4.0

### Fixed
- **A `--vision-cache-only` skip no longer replaces the figure's authored alt with a placeholder.** An uncached image used to get `(no cached description; skipped under --vision-cache-only)` injected as its alt text — shipping a placeholder as content and destroying the source's own description on every skipped figure. A skip now produces no injection at all: the figure keeps its authored alt verbatim (the skip list is still logged via `vision_cache_only_skipped`). Same principle as the v0.2.1 failed-call fix: placeholders never ship as content.
- **The splitter's measurement-heading guard now also rejects uppercase-initial units.** A heading like `### 6.3 Hz notch`, `### 48 V phantom supply`, or `#### 2.4 GHz band` was mis-parsed as section number 6.3 / 48 / 2.4 (the existing guard only caught lowercase-initial units like `mm`/`ohm`), which spawned bogus numeric folders and could mis-nest unrelated sections under a false parent. A curated, word-boundaried unit whitelist (`Hz`/`V`/`GHz`/`W`/`Pa`/`Ω`/…) now catches these while leaving real Title-Case sections (`### 2.6 Vacuum Systems`, `### 3.2 Wireless Setup`) untouched.
- **A directory-mode re-run no longer degrades `source_file` to the `<stem>.md` fallback.** When the run record knows the original source (its persisted identity, or a file-mode record), the opt-in `source_file` provenance field and the `INDEX.md` source name keep the true filename across re-tags instead of being overwritten with the master-doc name.

### Added
- **Every split section now carries `source_id` + `source_sha256` — always-on source identity.** `source_id` is a stable slug of the source filename (constant however the out-dir is named — the cross-conversion join key for one source work); `source_sha256` is the SHA-256 of the exact source bytes the conversion ran on. Together they complete the identity block: a retrieved chunk can name its source work and version even when within-book hierarchy degrades, and a multi-source consumer can scope by work instead of by out-dir name. Resolved from the input file directly; in directory mode recovered from the out-dir's run record — which now persists a durable `source_identity` block that every dir-mode re-run carries forward, so identity survives any number of re-runs (and a pre-existing record without the block upgrades on its next run). Omitted, never guessed, when genuinely unrecoverable. Library note: `split_into_sections()` gained optional `source_id=` / `source_sha256=` passthrough kwargs.

## 0.3.1

### Fixed
- **Notation-dense equations with two-sided scripts and delimiters no longer flatten.** The presentation-MathML→LaTeX pre-pass (HTML ingest) now handles three more elements: `msubsup` (a base carrying **both** a subscript and a superscript — an integral's limits, an indexed-and-powered variable), `munderover` (an operator carrying **both** a lower and an upper limit — a summation/product), and `mfenced` (a delimiter wrapper). Previously all three fell through to concatenated atoms, so `x₁²` collapsed to `x12`, `∑` from `i=1` to `n` collapsed to `∑i=1n`, and `mfenced` silently dropped its brackets — shredding the body prose of calculus/physics-style documents. They now render `x_{1}^{2}`, `∑_{i=1}^{n}`, and `(x,y)`. Handling stays source-agnostic (standard W3C presentation MathML; unknown elements still fall back to their text, never dropped).

## 0.3.0

### Added
- **`--split-target-kb N` — size-targeted section packing.** An alternative to the fixed-depth split knobs: each branch of the heading tree decides for itself. A branch that fits N KB becomes one file (subsections inlined); an oversized branch splits one level deeper, child by child; an oversized section with **no** sub-headings is partitioned at paragraph/block boundaries into `Title (part i of k)` files that share its identity (`part_index` / `part_count` frontmatter, parts parented to part 1; fenced code and tables are never cut mid-block). One setting produces bounded, retrieval-sized sections across book shapes where no fixed level can — mixed-depth chapters, flat mega-sections — eliminating both monster files and per-heading dust. Mutually exclusive with `--split-max-level`; opt-in, off by default.
- **Every split section file now carries structural identity frontmatter — always on.** Each section leads with a YAML block of joinable keys: `doc_id` (the conversion/out-dir name), `section_id` (the section's own relative path — stable across re-runs), `parent_id` (the nearest ancestor actually written to disk), `section_title` / `section_path` / `section_number` / `heading_level`, `depth`, and `order` (1-based document order). A RAG consumer can scope retrieval to one document, walk from any chunk to its parent or siblings, and cite a stable id — without a second retrieval round-trip. The opt-in provenance source fields (`--provenance` / `--source-type` / `--source-label`) merge into the same block; the master document remains untouched without them. Library note: `split_into_sections()` gained `doc_id=` (defaults to the out-dir name) and dropped the superseded `frontmatter=` string parameter.

## 0.2.2

### Added
- **`audit` gains a `misaligned_table` check.** Flags a wide multi-column spec table whose cell boundaries drifted during extraction so a value lands under the wrong label. Reported as a **warning**, not an error: the defect is real RAG noise but not auto-fixable — Marker and Docling reproduce it identically (ambiguous multi-line-cell geometry in the source PDF), so it is report-only like `duplicate_heading`. Gated on a non-empty sibling value cell, so blank fill-in forms and worksheets are not flagged. Deterministic, $0, no LLM.

## 0.2.1

### Fixed
- **A failed vision read no longer caches a silent placeholder caption.** When the vision call fails or the model's reply can't be parsed, the figure is captioned with its authored alt text when one exists (a real description, so the figure stays retrievable) instead of a bare `(description unavailable)`. The failure is never written to the perceptual-hash cache, so a re-run re-attempts the real call rather than serving the placeholder forever, and parse failures now count toward the end-of-run `vision_failure_summary`. Existing caches keep any placeholder already written — re-vision a document (`--rerun-from vision`) to heal it.

## 0.2.0

### Added
- **`pagespeak vision-audit`** — a read-only command that flags likely-confabulated vision captions for review. It compares each figure's generated caption against the author's source alt text and flags a caption that keeps none of the alt's subject words — a figure described as the wrong thing, the failure a caption-only read can't catch. Deterministic, $0, no LLM; `--strict` exits non-zero to gate a delivery.

## 0.1.0 — initial public release

pagespeak converts documents into clean, LLM-friendly Markdown — with extracted diagrams rendered as embedded Mermaid and an optional per-section split for retrieval (RAG). CLI + Python library. The feature set, by area.

### Conversion
One entry point — `to_markdown(path)` / `pagespeak convert <file>` — dispatching on format: PDF through Marker or Docling, Office / HTML / EPUB / CSV through MarkItDown, and Markdown / plain text straight through. Embedded images are pulled from every source (office media, EPUB and HTML assets, remote `<img>` URLs downloaded and localized) so they can be described and referenced beside the text.

### Pipeline
Conversion runs as an ordered set of resumable stages — ingest → cleanup → heading-normalize → repair → structure → vision → split — each writing an on-disk checkpoint, so any contiguous slice can re-run (`--from` / `--stop-after`) without redoing the expensive steps. Cleanup strips converter artifacts and repeated decorations; an opt-in LLM heading-renormalization pass rebuilds the flattened hierarchies PDF extraction produces, and deterministic post-passes repair heading levels and demote misclassified headings at no cost. Large PDFs ingest in parallel page-range chunks (`--workers N`).

### Diagrams & vision
An optional vision pass describes every extracted image: diagram-shaped figures (flowcharts, sequence and class diagrams, …) get an embedded Mermaid representation; photos, screenshots, and logos get a caption that makes them retrievable. The backend is pluggable — Claude Code (`claude --print`, $0 against a Claude Max session), the Anthropic API, or OpenRouter — and a content-keyed cache, keyed by each image's perceptual hash, reuses descriptions across engines and re-runs.

### Structure for retrieval
`--split-sections` emits one Markdown file per section, each carrying a breadcrumb of its place in the document so a retrieved chunk identifies its own source. Optional source / citation frontmatter tags every section for multi-source knowledge bases.

### Quizzes
Canvas QTI exports (Classic Quizzes) and Top Hat quiz-export PDFs convert to one self-contained answer-key document per quiz, split one file per question, with provenance frontmatter — the correct answer marked when the export reveals it.

### Tooling
`convert`, `ingest`, `deliver` (reduce an output directory to its shippable Markdown + sections + images), `audit` (read-only output-defect detection), and `repair-tables` (splice a clean grid from Docling over a collapsed table) commands. A localhost web console (`pagespeak[web]`) drives the whole pipeline — upload, run any phase, watch images and cost. Optional LLM-call tracking writes one row per call to SQLite or Postgres.

### Packaging
A light default install plus opt-in extras: `[pdf]` (Marker), `[pdf-docling]` (Docling), `[docx-structured]` (structure-faithful DOCX reading), `[tophat]`, `[web]`, and `[postgres]`. Built on pf-core. Ships a PEP 561 `py.typed` marker. Requires Python 3.11+.
