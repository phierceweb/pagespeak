# Pipeline stage: structure

The `structure` stage (`orchestrators/_phases.py:StructurePhase`, `services/_flat_source_demote.py`, `services/_enumerated_nest.py`, `services/_h1_ratio_rebalance.py`) is a **$0, deterministic, holistic doc-level rebalancing pass**. It reads `<stem>.repaired.md` and writes `<stem>.structured.md`.

It exists because some failure modes are *doc-level*, not per-line. Cleanup operates on lines (strip garbage characters, fix broken cross- references, dedupe headings); repair operates on individual headings (numbered-depth lock, demote number-only). Neither can answer the question "is the doc's overall heading distribution healthy?" — that needs to look at the whole document.

The failure mode it targets: HTML-export PDFs (help sites, API docs, knowledge bases) publish every article as `# Article title`, producing hundreds of sibling H1s that no per-line or per-heading pass can detect.

## What it does

Three small independent passes in sequence. Each is a self-diagnosing no-op on a healthy document.

### 1. enumerated-item nest (`_enumerated_nest.py`)

Detects a run of **enumerated list items** the extractor flattened to H1 — a heading ending in a bare enumerator `(N)` / `(N.N)` / `(Step N)` (panel controls, wizard steps). These belong *under* the section that introduces them, not at top level. Each item (and any sub-headings it owns) is demoted one level so the whole run nests beneath the preceding non-enumerated section.

- **Signal**: an H1 whose text ends in `(N)` / `(N.N)` / `(Step N)`, once a non-enumerated section H1 has appeared above it.
- **Action**: demote every heading in the run — the enumerated items and their subtrees — by one level (H1 → H2, children H2 → H3, …); H6 is left as-is.
- **Order**: runs **first**, before flat-demote and the orphan rebalance. It keys on the original H1 section boundaries — flat-demote demotes some section H1s to H2, which would let a nest run over-extend past them and over-collapse a control-heavy doc. Running before the rebalance also drops the nested items out of the orphan-H1 count.
- **No-op when**: no heading carries a trailing enumerator. Keyed on the enumerator shape alone, so flat-publish articles ("What's new", "Get started") are provably untouched.

### 2. flat-source consecutive-run demote (`_flat_source_demote.py`)

Detects long pure runs of consecutive H1s with no intervening H2-H6 heading. Demotes the 2nd through Nth in each qualifying run to H2. Conservative; only fires on the most egregious dense clusters.

- **Signal**: ≥ `PAGESPEAK_FLAT_H1_THRESHOLD` consecutive H1 lines (default `5`) with no other heading between them.
- **Action**: keep the first H1, prepend `#` to the rest (H1 → H2).
- **No-op when**: short H1 runs, or H1s separated by sub-headings.

### 3. orphan-H1 rebalance (`_h1_ratio_rebalance.py`)

Detects the broader flat-publish pattern: many H1s are childless leaf articles — no sub-heading of any level between themselves and the next H1 — sitting at H1 as siblings, not chapters. Demotes every childless orphan H1 to H2 (sparing the document title).

- **Signal**: `orphan_H1 / non_title_H1` ratio crosses `PAGESPEAK_ORPHAN_H1_RATIO_THRESHOLD` (default `70%`). An H1 is an "orphan" only if **no heading of any level (H2-H6) appears before the next H1** (or EOF) — a truly childless leaf.
- **Action**: keep the first H1 (title slot). For every other childless H1, prepend `#` to demote to H2. An H1 that owns *any* child heading — even just an H3 — is preserved: a real section with an under-built hierarchy (a manual or numbered-section paper that skips H2 and goes straight to H3) is not a leaf and must not be flattened.
- **No-op when**: orphan ratio is below threshold (healthy book or an authored-flat doc).

## Why the title is always kept

Demoting the first H1 risks losing the document's identity at the top of the file — many consumers treat the first H1 as the doc's name. The pass preserves it regardless of whether it has an H2 child.

## Why separate passes instead of one

They detect related-but-distinct signals: consecutive-run is a high-confidence local signal (pure H1 cluster); enumerated-nest keys on an explicit enumerator shape (a flattened list); orphan-ratio is a broader doc-level signal (publishing pattern). The first two demote *into* a nesting; the third flattens siblings — opposite motions on different evidence, which is why they stay separate rather than merging into one "fix the H1s" heuristic. Each is independently testable and tunable; their `services/` modules are small and have no knowledge of each other.

## Inputs / outputs

- Input checkpoint: `<stem>.repaired.md` (post-LLM, post-deterministic- heading-repair).
- Output checkpoint: `<stem>.structured.md` (consumed by `vision`).
- Rerun key: `structure` (`--rerun-from structure` / `pagespeak invalidate <out> structure`) — busts `structured.md` plus downstream structural files (`visioned.md`, `sections/`, `INDEX.md`). Iteration of the structure passes is $0; rerun freely.

## What it deliberately is NOT (yet)

- **A TOC parser**. Most docs have no parseable TOC, and the ones that do are mostly flat 2-column tables that don't encode hierarchy. Building per-publisher TOC parsers would be a maintenance trap for low coverage. The doc-shape heuristics here cover the same docs without parser hooks.
- **Smart "which H1 is the real chapter"**. The orphan rebalance keeps H1s that own any child heading and demotes the truly childless rest — that's the heuristic. It cannot rescue a doc whose *real* chapters are themselves childless (an under-leveled source where the LLM never built sub-sections): those are structurally identical to flat-publish leaves, so they flatten. Distinguishing them would need ground truth (TOC or LLM judgment) that this $0 pass deliberately avoids.
- **Bullet-glyph false-heading demotion**. A natural next pass for this phase but not yet built.

## Tuning

| Env var | Default | Use case |
|---|---|---|
| `PAGESPEAK_FLAT_H1_THRESHOLD` | `5` | Lower to catch shorter pure-H1 runs; raise to be more conservative. |
| `PAGESPEAK_ORPHAN_H1_RATIO_THRESHOLD` | `70` | Lower (e.g. 50%) to catch borderline flat docs, at the risk of touching authored-flat docs; raise to 80%+ to fire only on extreme cases. |

## What it spares

The childless-leaf rule keeps the pass off real structure:

- An H1 that owns any child heading — even an under-built hierarchy that skips
  H2 for H3 — is not a leaf, so it is never demoted.
- An authored-flat doc that sits below the threshold is left unchanged.
- Only a machine-flattened export whose H1s are overwhelmingly childless leaves
  crosses the threshold and gets rebalanced.
