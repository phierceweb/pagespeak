# Changelog

Notable changes to pagespeak, newest first. The project is pre-1.0 — pin to a tagged release; `main` is the development line.

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
