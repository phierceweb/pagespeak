# `pagespeak repair-tables` — surgical table repair

Replace a Marker-broken table in an already-converted output dir with the clean grid Docling extracts from the same PDF page — no whole-document re-ingest, no re-vision. It fixes two Marker table-detection failures: a **collapsed** table (a whole grid jammed into one `<br>`-joined mega-cell) and a **split** table (Marker emitting each wrapped line of a multi-line cell as its own row, leaving the key or value cell empty).

This is the companion *fix* for the audit's `collapsed_table` defect: [`pagespeak audit`](audit.md) **reports** a table that Marker jammed into one `<br>`-joined mega-cell; `repair-tables` **fixes** it. The split-table defect is found by `repair-tables` itself — it is not audit-flagged. It is deliberately narrower than a wholesale `--pdf-backend docling` re-ingest (see [backends.md](backends.md)) — that would move the *whole* document onto Docling, inheriting Docling's OCR noise and 2-level heading cap and busting the vision cache. `repair-tables` swaps in only the one clean table and leaves the rest of the Marker output untouched.

For AI assistants: there are two ways to run the splice — **inline** during conversion (`convert --repair-tables`, an ingest sub-step that needs no propagation) or **standalone** on an already-converted dir (`repair-tables <out-dir>`, which patches the `<stem>.raw.md` checkpoint only and so must be propagated — see [Propagating the fix](#propagating-the-fix)). Both reuse the same splice logic. It grafts external (Docling) extraction into Marker output, so spot-check a spliced table on an unfamiliar document; `--dry-run` (standalone) previews which tables it touches. Docling is a targeted fix for this one failure shape, not uniformly better than Marker.

---

## Table of Contents

- [When to use it](#when-to-use-it)
- [Prerequisites](#prerequisites)
- [Running it](#running-it)
- [How it works](#how-it-works)
- [Propagating the fix](#propagating-the-fix)
- [What it will not do](#what-it-will-not-do)

## When to use it

Use it when all of these hold:

- [`pagespeak audit`](audit.md) reports a `collapsed_table`, or a converted `<stem>.md` shows a table crushed into a single `<br>`-joined cell.
- The document was converted from a **PDF** with the Marker backend — the collapse is a Marker table-detection failure, and Docling reads the same page correctly.
- The **source PDF** is still available.

Do not reach for it on authored multi-line cells. A legitimate cell with a handful of `<br>` line breaks is faithful output, not a collapse — `repair-tables` only acts on mega-cells of **≥30 `<br>`**, the same threshold the audit uses.

It also repairs **split tables** — where Marker breaks one multi-line cell across several rows, leaving continuation rows whose key or value cell is empty (pervasive in spec-heavy key/value tables with wrapped descriptions). These are not audit-flagged; `repair-tables` finds them by that continuation-row shape. Over-flagging a table with a legitimately empty cell is harmless — the splice only swaps in a Docling table that scores a strong two-way content match, leaving a no-better candidate untouched.

## Prerequisites

- Docling installed: `pip install pagespeak[pdf-docling]`.
- The source PDF available. `repair-tables` auto-locates it under `conversions/in/` (exact `<stem>.pdf` first, else the closest filename-token match), or it can be passed explicitly with `--source`.

## Running it

**Inline, during conversion** — pass `--repair-tables` to `convert`. The splice runs as an ingest sub-step (after Marker writes `raw.md`, before cleanup), so the corrected table flows through the rest of the pipeline with no extra step. Good as a default for spec-heavy Marker PDFs, or whenever you know a document has Marker-collapsible tables:

```bash
pagespeak convert manual.pdf -o ./out --repair-tables --preset rag-default
```

It is off by default (it never runs Docling unless asked) and a no-op — with a logged warning — when Docling isn't installed or the document has no collapsed tables.

**After conversion, standalone** — fix an already-converted output dir, then propagate the change (see below):

```bash
# Auto-locate the source PDF under conversions/in/
pagespeak repair-tables conversions/out/<doc>

# Point at the source PDF explicitly (cryptic original filename, custom layout)
pagespeak repair-tables conversions/out/<doc> --source path/to/original.pdf

# Report what would change, write nothing
pagespeak repair-tables conversions/out/<doc> --dry-run
```

It prints one line per collapsed table — the line number, the `<br>` count, the located PDF page, and the outcome (`repaired`, `no-page`, or `no-match`):

```
2 collapsed table(s) in manual.raw.md; Docling-splicing from conversions/in/manual.pdf…
  line 412 (88 <br>), page 43: repaired
  line 905 (61 <br>), page 71: no-match

repaired 1/2 table(s) → patched manual.raw.md
```

With `--dry-run` the same report prints but `raw.md` is not written.

## How it works

For each broken table in `<stem>.raw.md` — a collapsed `<br>` mega-cell or a split multi-line-cell table:

1. **Locate the page.** Take the most distinctive text from the broken table — the longest `<br>`-segment of a collapsed mega-cell, or the longest cell value of a split table — and search the PDF's text layer for the page(s) that contain it.
2. **Re-read just that page with Docling.** One page, markdown only, no image side-effects.
3. **Match the table by content.** Across every candidate page, pick the Docling table whose tokens overlap the broken table's most — scored *symmetrically* (both directions), so a bigger table that merely contains the block, or a tail of it, loses to the exact one. Reject the match if nothing clears the overlap floor, if Docling *also* collapsed that table, or if Docling's grid silently **drops a value** the original had — a per-value word-pair check, because a lost row is worse than the ugly-but-complete original.
4. **Splice.** Replace the whole broken table block (the mega-cell, or the run of split rows) with Docling's clean grid.

The rest of the Marker output — body prose, headings, images, captions — is left exactly as it was. Only `<stem>.raw.md` is rewritten.

## Propagating the fix

This step is only needed after the **standalone** command — the inline `convert --repair-tables` flag runs before cleanup, so its fix is already carried through the rest of the pipeline. The standalone `repair-tables` rewrites `<stem>.raw.md` (the backend checkpoint) only. To carry the corrected table through cleanup into the master `<stem>.md` and `sections/`, re-run the pipeline from the cleanup stage, reusing the cached vision descriptions so it costs nothing:

```bash
pagespeak convert conversions/out/<doc> --from cleanup --vision-cache-only
```

Match the split flags the original run used — read them from `<doc>/.pagespeak-run.json` `resolved_flags` (e.g. `--split-sections`, `--nested-split`, `--preset`); the run-record schema is in [presets.md](presets.md). `--vision-cache-only` guarantees no live vision call fires: the images are unchanged, so every description is a cache hit (see [caching.md](caching.md)).

## What it will not do

- **It refuses to splice a no-better table.** A `no-match` outcome means Docling's grid did not clearly correspond to the broken table, Docling collapsed it too, or Docling's grid would silently **drop a value** the original had (it keeps the complete-but-ugly Marker table over a cleaner one that loses a row). The original table is left in place — `repair-tables` never replaces a table with a worse one.
- **It cannot fix image-based tables.** A `no-page` outcome means the cell's text was not found in the PDF text layer (e.g. a table that is itself a scanned image). There is nothing for Docling to grid.
- **PDF + Marker only.** The fix is built around Docling re-reading a PDF page; it does not apply to DOCX, HTML, or other formats.
- **It does not judge the result.** Spot-check a spliced table on an unfamiliar document. Docling is a targeted fix for this one failure shape, not a blanket upgrade over Marker.

Prefer `--dry-run` first (standalone) on an unfamiliar document to preview which tables the splice will touch.
