# `pagespeak audit` — output-defect detection

Scan converted markdown output for known conversion-defect shapes — read-only, $0, no LLM calls.

Do not confuse the three QA layers: **`bin/lint`** checks the *code* (ruff, mypy, file-size guard); **`pagespeak baseline save|diff`** checks whether a *code change altered output* relative to a saved baseline; **`pagespeak audit`** checks whether *converted output is defective* — absolute, per-document or corpus-wide, no baseline needed.

A sibling command, **`pagespeak vision-audit`**, checks a different surface — whether a *vision caption* describes its figure as the wrong thing (a squirrel captioned as a lemur) — by comparing each generated caption to the author's source alt text. Same read-only, $0, no-LLM charter; it is not part of this document's markdown-defect scan. See `docs/usage.md`.

It can only judge a figure whose source alt names a clear subject. The report gives the count assessed out of all captioned figures and how many were skipped, and says outright when nothing could be assessed — zero findings from zero assessed figures is no result, not a pass. Word's auto-generated alt suffix (`Description automatically generated`, with or without a confidence note) is stripped before judging, so it never stands in for a subject.

For AI assistants: the audit narrows *where* to read — it never replaces the read-by-eye validation gate (read the actual rendered output, not just the metric). Treat a clean audit as a gate, not a verdict.

---

## Table of Contents

- [Running it](#running-it)
- [What it scans (and skips)](#what-it-scans-and-skips)
- [The detectors](#the-detectors)
- [Severity model and exit codes](#severity-model-and-exit-codes)
- [What audit deliberately does NOT do](#what-audit-deliberately-does-not-do)
- [Adding a new detector](#adding-a-new-detector)

## Running it

```bash
pagespeak audit conversions/out                 # whole corpus
pagespeak audit conversions/out/<doc>           # one converted document
pagespeak audit out/manual.md                   # a single markdown file
pagespeak audit conversions/out --summary-only  # per-check totals only
pagespeak audit conversions/out --text-coverage # also check each doc against its source PDF
pagespeak audit conversions/out/<doc> --text-coverage --source <doc>.pdf
```

The report prints per-check totals, then per-file detail capped at a few examples per check per file (`… and N more`). Use `--summary-only` for the totals alone — the right first pass on a large corpus.

`--text-coverage` also compares each converted document with its source PDF's text layer (below). It works on document folders: pass a converted document's folder or a folder of them, not a file (a file path is refused, naming the folder to pass). The source is `--source <pdf>` when the one path given is a single document's folder, or auto-located by name in `--in-dir` (default `conversions/in`); the report says how many documents were checked and names those with no source PDF. A source that can't be read as a PDF is reported as a `text_coverage` warning rather than stopping the audit. It reads the PDF with `pypdfium2` (`pagespeak[tophat]`, also in the PDF extras).

## What it scans (and skips)

Audit reads **final artifacts only**: the master `<stem>.md`, `sections/`, and `INDEX.md`. It skips:

- stage checkpoints (`*.raw.md`, `*.cleaned.md`, `*.normalized.md`, `*.repaired.md`, `*.structured.md`, `*.visioned.md`) — intermediates are *expected* to contain pre-cleanup defects;
- `chunks/` — chunked-parallel ingest intermediates;
- dot-directories (`.vision-cache/`, `.baselines/`, …).

Two exceptions. The whole-document checks (`collapsed_code_blocks`, `unclosed_code_fence`, `formula_glyph_codes`) read only the master file, never `sections/` — a section of one-line shell commands is ordinary. `text_coverage` reads `<stem>.raw.md`, the backend's own output: the master adds vision captions whose words could hide a loss, and the threshold was set on `raw.md`.

## The detectors

Every detector exists because the defect was **observed in real converted output** — never speculation (see "Adding a new detector"). Each is a mechanical, deterministic check; none calls an LLM.

| Check | Defect shape | Severity |
|---|---|---|
| `collapsed_table` | A whole table collapsed into one `<br>`-joined mega-cell (≥30 `<br>`) — the Marker shape where every row is jammed into a single cell | error |
| `html_fragment` | Stray HTML table debris in prose (`<voltage<5v< td="">`, orphan `</td>`), or mangled empty-attribute tags (`<on off="" ="">`) | error |
| `replacement_char` | U+FFFD `�` — encoding damage (lost symbols like Ω or keyboard glyphs) | error |
| `html_entity` | Undecoded `&lt;` / `&amp;` / `&#8217;` outside code fences — a cleanup regression | error |
| `shattered_emphasis` | Emphasis-marker pileups (`****word****`) from shattered runs | error |
| `dangling_image_ref` | `![…](path)` whose relative target doesn't exist on disk | error |
| `broken_image_ref` | An image ref whose alt breaks it — a blank line in the alt ends the parser's scan for the closing `]`, so the ref reads as nothing. The only check that can see this: an unparsed ref is skipped by every later pass (the figure silently loses its vision caption and mermaid), and `dangling_image_ref` is itself parser-gated, so it cannot report one either. Flags only a ref that collapsing whitespace would repair, so `!` before a bracket in code (`!['a','b'].includes(x)`) and CommonMark shortcut reference images (`![Figure 1]`) are not errors. Fix at the site that built the ref (`utils._alt.flatten_alt`), never by loosening the parser | error |
| `misaligned_table` | A wide multi-column spec table whose cell boundaries drifted during extraction — two labels merge into one label-column cell, so a value lands under the wrong label. Real RAG noise, but **not auto-fixable** (Marker and Docling reproduce it identically — ambiguous multi-line-cell geometry in the source PDF), so it is report-only like `duplicate_heading`. Gated on a non-empty sibling value cell, so blank fill-in forms / worksheets are not flagged | warning |
| `empty_section` | A `sections/` file with no body **and** no subsections — a true orphan shell | warning |
| `duplicate_heading` | The same heading text ≥4 times in one file (recurring scaffold furniture) | warning |
| `collapsed_code_blocks` | Every fenced code block in the document is one line (≥8 blocks, Mermaid excluded) — the signature of a backend flattening multi-line code, which Docling does on PDFs; a copied command is unusable. Also fires when non-code text was fenced line by line | warning |
| `unclosed_code_fence` | A code fence opened and never closed. At the end of the file, every later line renders as code and every fence-aware pass (cleanup, TOC, audit) skips it. Before a language-tagged fence (`` ```bash ``), the block is read as ending there and the finding names that line: the source likely lost a closing fence | warning |
| `formula_glyph_codes` | Formulas rendered as glyph-code tokens (`n01`, `n2a`) at ≥1 per 1,000 words — what Docling emits for math without `do_formula_enrichment` | warning |
| `text_coverage` | With `--text-coverage`: under `PAGESPEAK_AUDIT_MIN_TEXT_COVERAGE_PCT` (default 90%) of the source PDF's distinct text-layer words (two or more characters) reached `raw.md`, with the pages whose words mostly never arrived. Catches body text a backend dropped at exit 0 — Docling can absorb prose set inside figure regions. Distinct words, not raw tokens, so vertically-set labels and repeated page furniture don't skew it. Under ~100 distinct words the PDF is scanned or near-empty and is not judged. A screen, not proof: read the named pages | warning |

Detector-shape notes that prevent false positives — preserve these behaviors when editing:

- All text checks operate **outside fenced code blocks**: a literal `&lt;` in a code example is content, not a defect.
- `dangling_image_ref` parses refs with `services/_image_refs.parse_image_refs`, the parser every ref-scanning pass shares. A local regex gets this wrong two ways — folding a CommonMark title into the destination, and stopping at the first `]` inside alt text — so use the shared parser rather than reintroducing one.
- `html_fragment` masks angle-wrapped markdown link targets (`](<Question 001.md>)`) before matching — that link style is not HTML debris. It comes from the quiz writer, whose per-question filenames keep their spaces; the generic splitter emits slugs, which never need wrapping. `<br>` and page-anchor `<span id="page-…">` lines are pagespeak's own legitimate output and are never flagged.
- `empty_section` does NOT flag nav nodes: a parent section whose only content is a `## Subsections` list is the splitter's deliberate shape — its content lives in its children.
- `misaligned_table` scans only a table's *label column* (the column where most cells end in `:`) and flags a merged label only when the same row has a non-empty value cell — so a blank fill-in form / worksheet (merged labels, empty answer column) is authored structure, not spillover. Colon-space is required, so `10:30`, `https://…`, and `:---:` alignment rows never read as labels.
- A line of only asterisks is a markdown horizontal rule, not shatter.

## Severity model and exit codes

- **error** — the content itself is damaged; an LLM/RAG consumer reads wrong or missing information. Any error → exit code 1.
- **warning** — worth a human look, but either possibly faithful-to-source or not auto-fixable. `duplicate_heading`: recurring callout furniture is structurally identical to inconsistently-leveled real sections, so automated demotion is a known wall. `misaligned_table`: a value under the wrong label is real RAG noise, but Marker and Docling reproduce it identically (ambiguous source-PDF cell geometry), so no backend swap or `repair-tables` splice can fix it — the audit flags the unreliable table for a human to exclude or hand-correct. Warnings alone → exit code 0.

## What audit deliberately does NOT do

- **Never fixes anything.** Read-only by charter. Fixes belong in the pipeline (cleanup/structure passes), gated by their own validation. The one companion *fix* command is **`pagespeak repair-tables <out-dir>`** for `collapsed_table`: it Docling-ingests just the collapsed-table page and splices the clean grid into the `<stem>.raw.md` checkpoint (no whole-doc re-ingest, no re-vision), then you propagate with `convert <dir> --from cleanup --vision-cache-only`. Surgical on purpose — Docling is a targeted table fix, not a blanket upgrade, so read each spliced table by eye. See [repair-tables.md](repair-tables.md).
- **Never calls an LLM.** Deterministic regexes and filesystem checks only.
- **Never judges prose quality.** A messy-but-faithful conversion of a messy source is correct pagespeak output; audit flags *conversion damage*, not authorial style.
- **Does not replace reading the output.** A clean audit means "none of the known defect shapes" — not "the document is good."

## Adding a new detector

1. **Provenance first.** A detector is added only for a defect shape observed in real converted output. Record that provenance as the *shape* and the source format that produces it ("Word's auto-generated alt text", "a Marker table split at a page break") — never the document's name or any identifying detail, which would ship in the wheel. No speculative checks.
2. Pure text checks go in `services/_audit_checks.py` (a `text -> list[AuditFinding]` function, registered in `_TEXT_CHECKS`); whole-document extraction signatures go in `services/_audit_extraction.py`; checks needing the filesystem go in `services/_audit.py` and are wired into `audit_file()`; checks against the source PDF go in `services/_audit_coverage.py`.
3. Pick the severity by the rule above: content damage = error; needs-human- judgment = warning.
4. Pair it with tests in the matching `tests/test_audit_checks.py` / `tests/test_audit.py` — a positive case modelled on the real defect, a negative case for the closest legitimate output shape, and a fenced-code immunity case if it's a text check.
5. Run it corpus-wide before shipping and eyeball a sample of hits: a detector that false-positives on legitimate output (nav nodes, angle-wrapped links) is worse than no detector.
6. Sync this page's detector table and the CHANGELOG.
