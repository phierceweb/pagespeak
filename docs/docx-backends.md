# DOCX backends

Two DOCX backends. Pick per call via `docx_backend="markitdown"` (default) or `docx_backend="python-docx"`.

## When to pick which

| Backend | Pick it for | Avoid it when |
|---|---|---|
| **MarkItDown** (default) | Compatibility — handles `.doc` / `.ppt` / `.xlsx` / `.html` in a single converter. Rich text fidelity (bold, italics, colors). Safe choice when document structure is uncertain. | You need faithful Word outline structure (multilevel lists converted to explicit heading hierarchy) and proper heading-style interpretation. |
| **python-docx** | Structure-faithful DOCX ingestion — reads Word's `w:ilvl` (outline numbering levels) directly and emits them as explicit heading hierarchy. Respects heading styles (`Heading 1` / `Heading 2` / etc.) as structural signals. A heading-quality pass cleans run-shattered formulas, headless titles and junk/figure-label headings (see **Heading-quality normalization** below). | Document is `.doc` / `.ppt` / `.xlsx` / `.html` (python-docx only handles `.docx`). Subscript-only-bold inline tokens (e.g. `O**2**`) may still show minor litter (cosmetic). |

MarkItDown collapses Word's outline-numbered paragraphs to **nested markdown lists** — the hierarchy is preserved as indentation but markdown-aware tools see zero headings. The structure-faithful path reads `numPr`/`ilvl` directly, emits a proper heading hierarchy, and recovers the document's intended structure. For heading-styled lecture or textbook DOCX, use `python-docx` to get proper chapter organization.

## Install

```bash
pip install pagespeak                           # MarkItDown (default)
pip install pagespeak[docx-structured]          # python-docx
pip install pagespeak[docx-structured,...]      # both — pick at call time
```

If you ask for a backend that isn't installed, pagespeak raises `ImportError` with the exact pip extra in the message — no debugging needed.

## Library API

```python
from pagespeak import to_markdown

# Single-shot with default MarkItDown
result = to_markdown(
    "lecture.docx",
    output_dir="./out",
)

# Single-shot with structure-faithful python-docx
result = to_markdown(
    "lecture.docx",
    output_dir="./out",
    docx_backend="python-docx",            # default "markitdown"
)
```

## CLI

```bash
pagespeak convert lecture.docx -o ./out --docx-backend python-docx
```

## Common surface — what's identical across backends

Both backends extract images to `<output_dir>/images/<name>`.

## Backend-specific behavior

### MarkItDown

Converts Word's outline-numbered paragraphs to **nested markdown lists** (indentation-based hierarchy), not headings. Collapses lists, preserves rich formatting. Includes blind media dump (all embedded images appended if not referenced in body). Handles `.doc` / `.ppt` / `.xlsx` / `.html`.

### python-docx (structure-faithful)

Reads Word's explicit structure signals using membership in the outline (`numPr`):

- **Outline membership** (`w:numPr` at `ilvl`) — decides structure. Paragraph at `ilvl==0` becomes a single `#` section heading. Paragraph at `ilvl>=1` becomes a nested ordered/bulleted list at depth `ilvl-1`, with per-section list numbering restart.
- **Heading styles** (`Heading 1`, `Heading 2`, etc.) → honored **only for non-outline paragraphs** (no `numPr`), enforced as literal heading depth (`Heading N` → `#`×N)
- **Body-placed images** → extracted to `images/`; images in headers/footers are skipped
- **Tables** → currently stubbed as `<!-- TABLE: RxC omitted ... -->` (full extraction deferred)
- **Hard fail fallback** → if parsing fails, falls back to MarkItDown automatically

Faithful path honors outline membership over heading style (avoiding style-name noise on outline items). Structure is heading-based for top-level organization (outline `ilvl==0`), with nested lists for sub-structure. Validated on real lecture DOCX to recover proper chapter hierarchy lost by MarkItDown's list collapse.

**`.docx` only** — `.doc` / `.ppt` / `.xlsx` / `.html` must use MarkItDown.

## Recognized Word structure patterns

When using `docx_backend="python-docx"`:

- Paragraphs with `numPr` (outline numbering) at `ilvl==0` → single `#` section heading
- Paragraphs with `numPr` at `ilvl>=1` → nested ordered/bulleted list at depth `ilvl-1` with per-section numbering restart
- Paragraphs with `Heading 1` / `Heading 2` style (**without** `numPr`) → heading level matching style name (`Heading N` → `#`×N)
- Inline images (in body runs) → extracted and referenced
- Multilevel outline items → converted to heading + nested list hierarchy based on `ilvl` (not style names)

Non-structural elements (headers, footers, comments, tracked changes, textboxes, SmartArt, equations) are skipped. Outline membership (`numPr`) takes precedence over heading style names.

## Tables

Word tables are rendered as GFM (GitHub Flavored Markdown) tables. Row 0 becomes the header row; a `| --- |` separator is auto-generated. Multi-paragraph cells are joined with `<br>`. Pipe characters within cells are escaped as `\|`. Ragged rows (uneven column counts) are right-padded with empty cells. A 0-row table emits nothing; a 1-row table emits only header + separator. Word's `vMerge` (vertical merge) and `gridSpan` (horizontal merge) are rendered as python-docx's repeated-value rectangular grid — GFM has no native rowspan/colspan support, so the repetition is intentional and RAG-friendly (each row is self-contained). v1 limitations: no per-cell image extraction, no nested-table recursion, no `w:tblHeader` detection.

## Heading-quality normalization (python-docx)

The faithful outline→heading mapping is only the *spine*. Lecture authors mix non-section content (quiz prompts, figure-label lists, reaction-diagram fragments, trailing resource links) into the same Word outline level as real section titles, and Word splits one visual token across several runs. `backends/_docx_quality.py` is a pure-text pass the structured reader runs to clean this:

| Concern | Behaviour |
|---|---|
| **Shattered runs** | Adjacent same-format runs are coalesced before wrapping, so `CO₂` renders `**CO2**`, not `**CO****2****`. Equation-dense docs (e.g. carbonic-anhydrase buffer) are readable. |
| **Redundant heading emphasis** | `# **Definition**` → `# Definition` (bold/italic is redundant inside an ATX heading). |
| **Headless documents** | The first all-bold plain-body paragraph (a title typed outside the outline) is promoted to the document `#` — only when the doc has real headings and nothing structural preceded it. The promoted title is protected from later demotion. |
| **Junk `#` (text signal)** | A would-be heading that ends in `.`/`?`, has a `___` fill-in blank, or contains a markdown link is demoted to body. |
| **Junk `#` (structure signal)** | `demote_nonsection_h1`: a `#` with no body before the next `#`, OR whose first body line is a numbered item `≥2` (it interrupted an in-progress outline), is demoted. Real sections start their own body (`1.`, prose, bullet, or a subheading). |

### Remaining limitations (cosmetic only — not content-destroying)

- **Subscript-only bold.** Where Word bolded *only* a subscript run (`O` plain + `2` bold), coalescing correctly will not merge across the genuinely-different format, so `O**2**` can remain. Isolated inline litter; the critical whole-token equations are clean.
- **Emphatic uppercase lines with a real sublist.** An emphatic all-caps outline line that happens to own a `1.`-started sublist (e.g. `# POOR LUNG COMPLIANCE → …`) is indistinguishable from a real short section and is conservatively kept. Not content-destroying.

MarkItDown (the default) has a different failure mode (it collapses structure to nested lists, no headings at all). Use `python-docx` for the outline→heading recovery; the heading-quality pass above makes its real output consumer-ready.

## Resume safety

Using both backends in the same output dir is safe — each run is independent (no per-backend manifest). You can switch `--docx-backend` on a re-run without issues.

## Speed

MarkItDown: ~1s per DOCX, single-process. python-docx: ~0.5s per DOCX, single-process. Faster than MarkItDown but structure-only (no rich formatting).
