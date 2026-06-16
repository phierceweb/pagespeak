# Choosing conversion defaults

Pick the right pagespeak settings for a new document — the pre-ingest triage that a future auto-classifier will eventually do automatically.

---

## Table of Contents

- [The canonical recipe](#the-canonical-recipe)
- [Pre-ingest classification](#pre-ingest-classification)
- [When to deviate from the canonical recipe](#when-to-deviate-from-the-canonical-recipe)
- [Vendor-template patterns](#vendor-template-patterns)
- [Known pagespeak gaps no recipe can fix](#known-pagespeak-gaps-no-recipe-can-fix)
- [Validation discipline](#validation-discipline)
- [Adding a new vendor profile](#adding-a-new-vendor-profile)

---

## The canonical recipe

For a typical manual or structured PDF, start with:

```bash
bin/run convert "<file>.pdf" -o conversions/out/<slug> \
    --preset rag-default --normalize-headings-mode llm_full
```

And set once in `.env`:

```
PAGESPEAK_DEFAULT_DEVICE=cpu             # avoid Marker/surya MPS crash on Apple Silicon
PAGESPEAK_CLAUDE_CODE_TIMEOUT_S=1800     # default; bump only if very large llm_full payloads time out
```

**Do** pass `--normalize-headings-mode llm_full` explicitly — `rag-default` defaults the mode to `heuristic`, which silently skips on manuals without numbered headings (a common case) and produces catastrophic output (recurring page furniture promoted to a `#` heading, inline callouts promoted to `## Important note:` headings, short list items promoted to headings).

**Do not** rely on `rag-default` alone for a heading-flat manual. The preset is right for everything except heading mode.

See [`docs/presets.md`](presets.md) for the full `rag-default` flag set, [`docs/normalize-headings.md`](normalize-headings.md) for how `llm_full` differs from `heuristic` and `llm`, and [`docs/usage.md`](usage.md) for the full env-var table.

---

## Pre-ingest classification

Run a 50ms text peek with `pypdfium2.get_text_range()` on the first / middle / last page. The text alone tells you almost everything.

### Detect non-manuals and skip them

Some PDFs aren't manuals at all — they're product webpages saved to PDF. Two flavors:

**Flavor A — image-only screenshot.** `len(pdf) == 1` and `get_text_range()` returns empty. Output will be one full-page vision caption with zero structured content.

**Flavor B — text-bearing product page.** `len(pdf) == 1` and the text contains commerce markers (`$XXX`, `Add to cart`, `Article No.`, breadcrumb-style `/ Products / …`, `Delivery time:`). Output will be marketing prose, not procedural manual content.

**Do** refuse both: raise / warn / re-source from the vendor's actual support page rather than converting.

**Do not** spend vision quota on either — the conversion produces nothing usable for RAG.

### Detect HTML-export PDFs (high-confidence green-light)

If page 1 contains the literal string `PDF export of the original HTML manual` (or similar), the source was authored with proper HTML headings and the canonical recipe will produce clean 4-level nesting. Confidence high — proceed without extra scrutiny.

### Detect aggregator-wrapped downloads

Some manual-aggregator sites wrap every download with a nav page at the head (a links page + a duplicate Table of Contents) and a trailer at the tail (a related-projects page + a site logo). Both are RAG junk.

**Do** trim head + tail post-conversion (or before ingest into your vector DB). The real manual is between the first real chapter (e.g. `# User Guide`) and the last legal/copyright section.

### Detect multilingual — two flavors require different handling

**Flavor 1 — whole-doc repeated in N languages.** Same content in English, French, German, … each language a contiguous block. The peek catches it because non-English text appears at *both* a middle page and the last page.

**Do** convert only the English block with `--page-range <start>-<end>`. Cuts vision quota ~N×. To find the boundary, run a `--no-diagrams` scout first and look at the *last English content* in the scout text — not the last English image-page number. Text tails often extend a page beyond the last diagram.

**Flavor 2 — mostly-English manual with a multilingual regulatory chapter.** Chapters 1–4 entirely English; the final regulatory chapter has per-country `##` sub-sections, some written in a local language (e.g. a local-language block under a `## <Country>` heading). The peek catches it because non-English text appears *only* in the last ~10% of pages, mixed with English `##` headings.

**Do** accept it (English RAG queries won't retrieve non-English chunks). Or post-process at section level. `--page-range` does not help here — the multilingual content is interleaved per-section, not contiguous at the tail.

### Detect big-doc threshold (~300+ pages)

For a large manual at `len(pdf) >= ~300`, the diagram-extraction quota becomes prohibitive (at a typical ~1–2 images/page, a 1,000+-page manual can be thousands of vision calls).

**Do** switch to the big-doc recipe: `--workers N --device cpu --no-diagrams`. UI screenshots are not captured, but for *text* RAG of a large manual, the prose (menus, specs, procedures) is the value — screenshots add little.

**Do not** drop `--device cpu`. `--workers` alone does not avoid the Marker/surya MPS crash — each chunk worker still runs surya and any chunk hitting a bad page still dies, producing a doc with holes.

---

## When to deviate from the canonical recipe

Each deviation has a real cost. Apply only when the trigger fires.

### Use Docling instead of Marker when Marker drops spec-table values

Trigger: Marker's spec table comes out with blank cells, especially for the bottom rows (e.g. the final physical-spec rows). Symptom is *silent data loss* — the table renders but the values are missing.

Mechanism: the source PDF has the spec table laid out beside a second column of text (e.g. a specifications-and-notes prose column); Marker merges the two columns and the spec values fall into the wrong cell or get dropped.

**Do** re-run with `--pdf-backend docling --rerun-from ingest --normalize-headings-mode llm_full`. Docling reads side-by-side tables correctly.

**Trade-offs of Docling:**
- OCR introduces spacing / ligature noise in body text (`fi nish`, `eff ected`, doubled spaces).
- Docling tends to promote repeating page-band / header decorations (a logo strip or running header on every page) into `##` headings.
- Marker handles these correctly via the cleanup stage's `demoted_recurring_scaffold`; Docling does not.

**Do not** use Docling as a blanket default. It's a targeted fix for table-data-loss, not a universally-better reader.

### Use `--device cpu` (until you set the env var) when Marker hits the surya MPS crash

Trigger: Marker fails mid-conversion on Apple Silicon with `torch.AcceleratorError: index N out of bounds` originating in the surya vision encoder.

**Do** set `PAGESPEAK_DEFAULT_DEVICE=cpu` in `.env` once and never type `--device cpu` again. The MPS crash hit rate is high enough on Apple Silicon that `cpu` is effectively the right default.

**Trade-off:** CPU layout/OCR is slower than MPS (≈ 6 sec/page vs ≈ 2 sec/page on a typical M-series). Combine with `--workers N` on big docs to recover throughput via parallelism.

### Use the big-doc recipe for ≥ ~300-page manuals

Covered above under [Pre-ingest classification](#pre-ingest-classification).

### Almost never use `--normalize-headings-mode heuristic`

The `heuristic` mode is for textbook-style PDFs with numbered headings (`1.2`, `3.4.1`). For a manual without numbered headings, it silently skips and the doc ships with Marker's raw heading detection, which on a typical such manual produces many flat `#` headings of page furniture, callouts, and short list items. The `llm_full` rescue power on these inputs is dramatic; the cost of NOT using `llm_full` is catastrophic, not cosmetic.

---

## Vendor-template patterns

Vendors consistently use the same PDF template across products. Once you've seen one product's output from a vendor, you can predict the next.

The pattern matters because it gives the classifier a high-confidence input: detect the vendor's signature (a URL near the top, a distinctive heading phrase, the literal company name) → apply the known recipe → expect the known output shape and the known artifacts.

### Two principles

**Principle 1.** Vendor templates are consistent *both* in their successes and in their failures.

If one product's PDF from a vendor produces clean nested chapters with a working anchor TOC, the next product's PDF from the same vendor will too. If one product's PDF emits a page-band into the body and loses top-level dividers as plain text, the next one will too.

**Principle 2.** Within a single vendor, the source-class matters more than the product.

A vendor's *print-format* PDF (designed for a printed manual) and the same vendor's *HTML-export* PDF (rendered from web docs) produce very different output qualities for the same recipe. The HTML-export consistently wins — real `<h1>`/`<h2>`/`<h3>` tags survive the round-trip into Marker's heading detection.

### What to capture for each new vendor

When you observe a new vendor's pattern, record:

- **Signature** — a literal substring or URL that identifies the vendor's PDF (e.g. `vendor.com/get-started`, `ACME MAIN Manual`).
- **Source-class** — print-format, HTML-export, aggregator download, vendor-direct download. Often inferable from a literal line in the doc.
- **Expected structure** — what a clean output looks like (number of H1 chapters, presence of anchor TOC, etc.).
- **Known artifacts** — what to expect / watch for that the recipe alone can't fix (page-band leak, lost dividers, callout-as-heading, etc.).
- **Verdict** — does the canonical recipe produce A/B/C/F output for this vendor's class? Add one example so the next reader can verify.

See [Adding a new vendor profile](#adding-a-new-vendor-profile) for where to record this.

---

## Known pagespeak gaps no recipe can fix

These show up in output regardless of which recipe you pick. The classifier can *predict* them but can't *prevent* them — they're pagespeak features waiting to be built.

### `llm_full` can re-level a heading but cannot de-headify it

If Marker (or Docling) captures something as a heading that isn't one — an inline callout (`Important note:` etc.), a page-header strip, a short list item, a figure caption — the cleanup stage's demoters catch most (`demoted_recurring_scaffold`, `demoted_listish_bare_int_headings`, `demoted_empty_shell_headings`), but the long tail survives. The surviving false headings get handed to `llm_full`, which can only assign a level, not strip the `#` prefix entirely.

Effect: a chunk of H3-level navigation noise that pollutes the TOC and section list but doesn't break body content. RAG retrieval is largely unaffected (the noise headings have no topical hook), but document browsing and chapter-list summarisation are uglier.

### `llm_full` does not infer subsection grouping from topic adjacency alone

If Marker emits a flat list of `#` headings and the only signal that one should be a child of another is topical (a subsection sits under a parent by subject alone, with no numbering or indentation in the source), `llm_full` leaves them as `#` peers. It re-levels what looks like a chapter/subsection pattern (numbered, indented in source) but proximity + topical relevance alone don't trigger nesting.

Effect: shallower hierarchy than ideal. Body content still complete; navigation and section context weakened.

### No language-section filter for Flavor-2 multilingual

Pagespeak has no built-in way to drop non-English `##` sub-sections from a regulatory chapter. Either accept the mixed-language tail, or post-process by section after split.

### Marker can silently drop chapter headings — even when the doc's own TOC lists them

On docs with a real `Contents` / `Table of Contents` table at the top, Marker sometimes detects chapters 1, 3, 4, … as headings but misses chapter 2 (or 9, or 12) entirely. The chapter exists in the TOC table cell; no `# N. <title>` exists anywhere in the body. `llm_full` cannot recover this — it only operates on the heading list Marker emits.

Detect this post-conversion: parse the doc's own `## Contents` table, extract chapter numbers, and assert every chapter has a matching `# N.` (or `## N.`) heading in the body. Mismatches flag a Marker miss.

Effect: navigation/browse is impaired (a TOC-based reader sees the chapter listed but the link doesn't resolve); RAG retrieval is largely unaffected (the chapter's body text is still in the doc, just under a wrong-level or missing heading).

### Exploded parts-list diagrams lose the reference → part-name mapping

Some manuals end with exploded-view parts diagrams where each component is labeled with an alphanumeric reference (e.g. `A1`, `B2`, `C3`) and a separate key/legend maps each reference to a part name. The vision caption transcribes the list of visible references but rarely transcribes the reference → name mapping even when the legend is visible.

Effect: a RAG query "what's part A1?" returns nothing useful. Body retrieval of the chapter still works; only the parts-catalog lookup is broken. Fixable via diagram-prompt enhancement (explicit instruction to transcribe a visible legend table when present).

### No automatic vendor-template recognition

The classifier signals in this doc are currently a human / AI-assistant checklist, not a runtime feature. When pagespeak gains a pre-ingest classifier, this doc becomes the input.

---

## Validation discipline

Producing these defaults surfaced four meta-rules that apply to any conversion review.

### Read the actual output, not the metrics

A green test count, a zero diff vs. a prior run, or a clean-looking heading-count distribution (`1 H1 / N H2 / N×3 H3`) proves only that the measured thing didn't change — not that it was ever correct. Always pair an auto-check with a human read of the actual rendered markdown.

### Heading counts are not heading quality

A perfect-pyramid distribution can hide H3 noise (twenty `### Important note:` repeats, page furniture demoted but not removed). Inspect *which* headings exist at each level, not just *how many*.

### The read-by-eye must be holistic and worst-case

A real read that only checks the new feature on hand-picked easy inputs is the same failure as a passing metric, wearing a costume. The read is valid only when (1) it covers the *whole* output (would a consumer accept all of it?) and (2) it's done on the inputs that stress the change hardest, not the ones that show it best.

### Pair every operational tunable with an end-to-end test

Unit-testing the helper (`_foo_timeout_s()` returns 1800 when env unset) is not enough — the helper might be wired into dead code. Add an end-to-end test that asserts the env value actually reaches the runtime call site (e.g. the LLM client's `timeout=` kwarg). This is the lesson the `PAGESPEAK_CLAUDE_CODE_TIMEOUT_S` extraction had to learn the hard way.

Validate by reading the actual converted output, not by trusting a zero-diff or a token grep.

---

## Adding a new vendor profile

When you convert a manual from a vendor not yet covered:

1. **Run the canonical recipe first.** Don't reach for deviations on the first attempt.
2. **Do a holistic read.** Title, full chapter outline, mid-section body, tail, spec/troubleshooting tables. Check the H3 level for callout-as-heading noise.
3. **Identify the source-class.** Look for `PDF export of the original HTML manual` (HTML-export), an aggregator's nav/links + related-projects wrappers (aggregator download), or vendor-direct (no wrapper).
4. **Record the vendor signature.** The shortest substring that uniquely identifies this vendor's PDF (URL, brand name, manual title).
5. **Record the expected structure.** Approx. H1/H2/H3/H4 counts for a clean run, presence/absence of anchor TOC, spec section layout.
6. **Record the known artifacts.** What the recipe can't fix on this vendor's docs.

Then add a short paragraph to [Vendor-template patterns](#vendor-template-patterns) — keep it principle-led, not vendor-exhaustive. Two or three examples per pattern is plenty; ten is going-stale territory.
