# Cleanup

`to_markdown()` runs a cleanup pipeline after the backend conversion and the diagram-enrichment pass. It normalizes raw Marker / MarkItDown output into LLM-friendly markdown.

## Levels

| Level | Behavior |
|---|---|
| `cleanup="off"` | Return the backend's raw output. Useful for debugging. |
| `cleanup="basic"` (default) | Generic normalizations safe across documents. |
| `cleanup="aggressive"` | Adds document-shaped pattern matchers (image decorations, TOC pipe tables, page-anchor spans). |

## Outline reconstruction (Word multilevel lists)

MarkItDown, Pandoc, and Docling convert Word's "Multilevel List" outline-numbered paragraphs to **nested markdown lists** rather than headings. Section hierarchy is preserved as list indentation depth, but markdown-aware tools see zero headings. The `services._outline.promote_outline()` function runs as a pre-pass before per-line cleanup normalizations, reconstructing the structure:

- **Input:** Nested list markers with depth-sensitive conversion (3-space MarkItDown, 4-space Pandoc).
- **Process:** Marker-stack aware (`* +`, `- -`, etc.) regex captures per-block relative depth. Top-level list items (depth 1) become `#` H1 headings. Second-level items (depth 2) nest under the nearest enclosing `#`, becoming `##` H2 headings. Deeper items remain as clean nested markdown lists (K=2 headings max). Marker stacks are stripped from output.
- **Guards:** Requires ≥3 top-level numbered list items and ≥1 deeper item to fire. Single-level or sparse lists pass through unchanged.
- **Validated:** deeply-nested DOCX outlines gain explicit heading structure (tens to >150 heading promotions on a heavily-nested file). Pure-text, no LLM cost.

## What `basic` does

Each transformation is independent and tested in isolation. Order matters; each step expects the previous step's output shape.

| Step | Purpose | Example |
|---|---|---|
| 1. Strip control characters | Remove invisible chars (`\x00`-`\x1F` minus tab/newline, plus `\x7F`-`\x9F`). Real Unicode content (en-dashes, `©`, `®`, smart quotes) is preserved. | `\x07` -> *(removed)*; `6–10 Kirby Street` unchanged |
| 2. Strip stray HTML tags | Marker leaks `<i>`, `<b>`, `<strong>` from styled PDF text | `<i>2.5.7.</i>` -> `2.5.7.` |
| 3. Normalize leading/trailing whitespace only | The author's internal spacing is **preserved verbatim** — a mid-line run of spaces (e.g. a space-laid pseudo-diagram) never breaks markdown, so it is kept. Only a *leading* run (which would mis-form an indented code block) and a *trailing* run (a stray hard break) are stripped. Structural list-item indentation is preserved. | `  text   with   gaps  ` -> `text   with   gaps` (internal gaps kept); `    prose` -> `prose` (leading strip avoids a code block) |
| 4. Promote numbered headings | Plain-text `1.4.1. Foo Bar` becomes a heading at depth implied by the number | `1.4.1. Triggers` -> `### 1.4.1. Triggers` |
| 5. Normalize list bullets | Marker emits `- o`, `- a.`, `- ii.` from PDFs that used those glyphs as bullets | `- o foo` -> `  - foo` |
| 6. Normalize tables | Marker tables sometimes have inconsistent column counts or a single-cell title row that breaks rendering | Promote title row to `**bold caption**`; pad rows to max column count; insert missing `\|---\|` divider |
| 7. Repair broken cross-references | Marker occasionally captures the leading character of a link label outside the bracket | `Se[e Configuration](#page-36-0)` -> `[See Configuration](#page-36-0)` |
| 8. Replace escaped underscores | `customer\_id` -> `customer_id` for plain-text readability | |
| 9. Collapse blank-line runs | Multiple consecutive blank lines collapse to one | |

**HTML entity decode (runs first, `basic`):** before the per-line steps above, an early whole-text pass runs `html.unescape` *outside* fenced code blocks. Backends — Docling especially — leave HTML entities in extracted markdown, so `T3 &lt; 34F` / `A &amp; B` would otherwise read literally; this restores `T3 < 34F` / `A & B` for the LLM/RAG. Always correct on extracted content (the source had the literal char), so it's universal rather than a per-doc heuristic; a literal entity inside a code example is preserved. Runs before vision, so mermaid blocks are never touched.

**Heading-line page anchors (still `basic`):** After step 4, any `#` heading line that contains Marker's `<span id="page-X-Y"></span>` tags has those tags removed from the visible title (so split filenames and breadcrumbs stay clean). With default `cross_refs="keep"`, each removed tag is written back on its own line immediately after the heading so `[label](#page-X-Y)` links keep resolving. With `cross_refs="strip"` or `"remap"`, heading anchors are not preserved — strip/remap handles refs instead. Aggressive mode relies on the table below for span stripping.

**Prose-shape demote (still `basic`):** Step 4 promotes any line starting with `N.` to a heading. Correct for genuine numbered section headings (`1. Introduction`); wrong for numbered bullet items where each item is a full sentence. After the heading-line span strip, every numbered heading is run through `services._heading_sanity.demote_prose_heading`, which demotes back to a list item if the title's *shape* reads like prose: length > 120, an internal `. <Capital>` boundary outside the trailing 10 chars, length > 40 ending in `.` / `?` / `!`, or a lowercase first character. Non-numbered headings are out of scope — they're reliable. Preserved page anchors survive demote intact: they re-emit on the line below the demoted bullet so `[label](#page-X-Y)` cross-refs still resolve.

**Heading sanity also promotes caption shapes and demotes non-numbered prose:** non-numbered titles matching `Figure N`, `Fig. N`, `Table N`, `Eq. N`, etc. demote to plain prose; non-numbered prose with internal sentence boundary or length > 40 + terminal punctuation demotes, with an all-caps guard preserving real `INTRODUCTION`-style titles.

**Bare-integer step-heading demote (`basic`):** Marker sometimes font-promotes procedure steps (`# 19 Pair additional remote controls`, `## 4 Verify`) to headings. `services._listish_headings.demote_listish_bare_int_headings` demotes them — but only via a **document-relative** signal: it counts bare-integer-led heading lines vs bare-integer-led plain lines, and demotes the heading ones to plain text **only when the doc uses bare integers predominantly as a plain-text list** (plain > heading). Docs that use bare integers *consistently* as section headings (an academic paper's `# 1 Introduction` … `# 4 Conclusion`, config labels `#### 32 in / 32 out`, a textbook's real numbered chapters) are heading-dominant and left untouched; `N.M[.K]` sections are never bare-int. Skipped on structure-faithful reader output. Logs `cleanup_demoted_listish_bare_int_headings count=N`.

**Single-dot step-heading demote (`basic`):** the single-dot sibling of the bare-integer pass, for `N.`-numbered procedure steps Marker promotes to headings (`#### 1. Click the inspector icon.`). `services._listish_headings.demote_listish_dotted_int_headings` uses the **same** document-relative signal — count `N.`-led heading lines vs `N.`-led plain lines, demote the heading ones **only when the doc uses `N.` predominantly as a plain-text list** (plain > heading). A how-to book whose steps leaked into headings is fixed; a manual whose section spine *is* `#### 1. Connect` … `#### 4. Configure` is heading-dominant and left untouched. This document-relative count is deliberate: a short numbered heading ending in a period (`### 1. Open.`) is structurally identical whether a real section or a step, so it cannot be classified in isolation (`_heading_sanity` keeps it). Multi-dot `N.M[.O]` sections are excluded (depth-locked elsewhere). Skipped on structure-faithful reader output. Logs `cleanup_demoted_listish_dotted_int_headings count=N`.

**TOC-phantom drop:** at split time, headings shaped like TOC entries (trailing `, p. NN`; Chapter-prefixed with trailing 2-3-digit pagenum; numbered-prefix with trailing pagenum) are dropped from the section set. False-positive guards keep `RFC 822` / `Section 100` titles. Logs `split_dropped_toc_phantom_sections count=N`.

**DOCX template-frontmatter strip:** `--strip-frontmatter` detects ≥2 of six template patterns (Word TOC anchors `(#_Toc\d+)`, revision-history table header, `<Project Name|Month|Year|#.#>` placeholders, "Artifact Rationale" / "Place latest revisions" / "Delete all Instructional Text" boilerplate) and drops everything before the first `# H1`. Auto-enabled by `rag-default` / `flat` / `textbook` presets; `archival` preserves frontmatter.

## What `aggressive` adds

Patterns that aren't safe to apply universally but are worth a flag for clean single-document conversions:

| Step | Why aggressive | What it does |
|---|---|---|
| 10. Drop image-only lines | A page-decoration `![](path)` that's not a real diagram should be dropped; doing so before the diagram pass would lose real diagrams. Cleanup runs **after** diagrams, so anything still bare here is decoration. Only matches `![](...)` with empty alt text — captioned images are preserved. | Lines matching `^\s*!\[\]\([^)]+\)\s*$` are removed |
| 11. Normalize "Table of Contents" heading | The literal string "Table of Contents" anywhere on a line becomes `## Table of Contents`. The body that follows is preserved (the TOC regenerator replaces it later with a generated bullet list). | Heading promoted; body preserved |
| 12. Strip `<span id="page-X-Y"></span>` anchors | Marker emits these as cross-ref targets; they render as nothing but pollute the source. | Regex strip |
| 13. Strip all non-ASCII characters | Some PDFs leak placeholder Greek/math glyphs from font tables (`Δ`, etc.). **Caveat:** also strips en-dashes, `©`, `®`, smart quotes — only enable on documents you know are ASCII-only. | `Δ` → *(removed)* |

## Pipeline order

```
to_markdown(path, ...) / pagespeak convert ...
  ├── ingest phase (_ingest.py)
  │     └── backend (Marker / MarkItDown / Docling)
  │           → <stem>.raw.md
  └── Phase 3 (_dispatch.py)
        ├── services._cleanup.cleanup_markdown(text, level)
        │     → <stem>.cleaned.md  (snapshot)
        ├── orchestrators._decorations.strip_decoration_refs()
        ├── services._heading_normalize (if normalize_headings=True)
        │     → <stem>.normalized.md  (snapshot)
        ├── services._diagrams.gather_diagrams / inject_diagrams  (if diagrams=True)
        ├── services._toc.regenerate_toc()
        └── services._split.split_into_sections(text, dir, nested)  (if split_sections=True)
```

Cleanup runs **before** vision so:

- The normalize LLM call sees slim text (no mermaid bloat) — `llm_full` mode uses the heading body text as a context anchor, so cleaner input matters.
- Vision injection and mermaid blocks are never subjected to cleanup transforms (the previous "gate by coincidence" becomes "gate by construction").

`services._toc.regenerate_toc()` runs after vision injection to replace the TOC body with a generated bullet list of the document's actual headings. Marker's pipe-table TOC is structurally broken on real PDFs (cell boundaries split words mid-character), so the regenerated one is strictly more useful. Disable via `to_markdown(regenerate_toc=False)`.

## Cross-reference handling

`to_markdown()` accepts `cross_refs="keep" | "strip" | "remap"` (default `"keep"`):

- `"keep"`: leave Marker's `[label](#page-X-Y)` refs intact.
- `"strip"`: rewrite to plain `label`, dropping the broken anchor.
- `"remap"`: a two-pass rewrite. The pre-pass scans the raw text for `<span id="page-X-Y"></span>` targets and pairs each with the GitHub-flavored slug of the next heading. The per-line pass then rewrites every `[label](#page-X-Y)` to `[label](#<heading-slug>)`. Refs whose target has no following heading fall back to strip behavior — no broken anchors.

Pair `cross_refs="strip"` (or `"remap"`) with `cleanup="aggressive"` to avoid orphaned anchors after the `<span id="page-X-Y">` targets are stripped. With `"remap"`, the pre-pass collects the slug map BEFORE the per-line strip runs, so the rewritten refs survive even when the targets are gone.

Real non-page-anchor links (`[label](#real-section)`, `[label](https://example.com)`) are preserved under all three modes.

## Heading dedupe

Marker occasionally emits the same heading twice in a row (`## Table of Contents` followed by `## Table of Contents`, sometimes with a blank line between). At cleanup levels `basic` and `aggressive`, consecutive duplicate heading lines are collapsed into one. No config knob — automatic at any level except `off`. Catches duplicates separated by blank lines but stops at non-empty content (so two `## Foo` headings with prose between them are preserved).

### Split-aware ref rewriting

When `split_sections=True`, the splitter rewrites in-doc `[label](#slug)` refs (whether user-typed, kept by `cross_refs="keep"`, or produced by `cross_refs="remap"`) to relative paths to the corresponding section file — `[label](Quick Start.md)` (flat mode) or `[label](../1/Quick Start.md)` (nested mode) — so cross-section navigation works without a renderer.

Refs to slugs that don't match any section heading, real anchors, and URLs are preserved unchanged. The consolidated `result.markdown` keeps the original `#slug` form so it renders correctly as a single document.

## Section splitting

Opt-in via `split_sections=True` (plus optional `nested_split=True` and `split_min_level=N`).

- **Default mode** (`split_min_level=None`): only numbered headings start sections (`# 1. ARCHITECTURE`, `## 1.4. …`, `### 1.4.1. …`). Best for textbook-style docs.
- **Semantic mode** (`split_min_level=N`): also split on any heading at depth ≥ N. `split_min_level=2` is the right choice for product manuals that use `## Quick Start`-style headings. Numbered sections get `<number>. <title>.md` filenames; semantic ones use the heading text only (`Quick Start.md`).
- **Capped depth** (`split_max_level=N`): headings deeper than N stay inline as content of their enclosing section instead of splitting out. `split_max_level=2` yields one file per H2 (section-level chunks) with `### `+ subsections inline — the fix for textbook-shaped docs (a single `# Title`, numbered `## N.M` sections, plus unnumbered back-matter H2) that otherwise over-fragment into thousands of tiny per-heading files. Opt-in per doc, since the right cap depends on how much content lives below the section heading.
- **Nested mode** (`nested_split=True`): sections nest by heading hierarchy. Numbered sections use the number string for folder names (`1/1.4/1.4.1. RingCentral Triggers.md`); semantic sections use the sanitized heading title (`Quick Start/Foot Switches.md`). Top-level sections land in their own folder named after themselves.
- **`INDEX.md`** lists top-level sections.
- **Breadcrumb header** — each non-root section file starts with `> ↑ [Root](root.md) / [Parent](parent.md)` so an LLM that retrieves a single chunk knows where it fits.
- **Empty-body filter** — sections whose body has fewer than `min_body_chars` non-whitespace chars are dropped (default `30` from `to_markdown()` / `stitch()`; `0` if calling `split_into_sections()` directly). This drops front-matter TOC entries that the backend promotes to `#`-headings, which would otherwise become empty "chapter shell" files.
- **English-only filter** (opt-in, `--english-only` / `english_only=True`) — drops a multilingual manual's translated branches (German / French / Italian / Spanish / Chinese / Cyrillic / Korean copies of the same content), keeping the English. Judged by **subtree**, not per-section: every section is grouped under its top-level branch and the branch's *aggregated* text is classified (`services._language`), recursing into kept English branches so a non-English block nested under an English chapter is still caught. The aggregate lets it catch a translation fragmented into terse sections that a per-section check misses. A branch is dropped only on a strong signal — >30% non-Latin script, OR sparse English **and** a real density of distinctively-foreign function words; that foreign-evidence half keeps a stopword-poor English specs table (model numbers, MHz/dB units) that sparse-English alone would wrongly flag. Removes the major Latin languages + all non-Latin scripts; a 24-EU-language boilerplate block (minor languages whose short function words collide with English) is the known gap. **OFF by default** — a content heuristic, kept behind the flag per the project charter.
- **Ancestor-only chapter shells** — chapter shells with an empty body but kept descendants are preserved as parents in the breadcrumb chain (a `_Section.is_ancestor_only` flag) so descendants render with a real chapter ancestor.
- **Stale-file cleanup** — re-running removes section files no longer in the write set. Empty `nested_split` subdirectories are pruned. Non-`.md` files are left alone.
- **Filename truncation** — sanitized filenames over 200 chars are truncated to fit FS limits (255-byte cap on most file systems).
- **Filename collision resolution** — when two sections sanitize to the same on-disk filename:
  - Body-identical → drop the later one (catches Marker's TOC-promote-then-real-chapter dupes). Logged as `split_dropped_filename_collision`.
  - Body-distinct → keep both. The first keeps the bare filename; the second gets `-2`, the third `-3`, etc. The numeric suffix lives on the FILENAME only — heading text and breadcrumbs use the unsuffixed display name.

## Why cleanup lives in pagespeak

The patterns are backend-quirk-specific (Marker / Docling / MarkItDown artifacts), not consumer-specific. Every consumer would re-write them and get them subtly wrong, so pagespeak owns it.
