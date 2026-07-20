# Pipeline Walkthrough

What every command runs, stage by stage. This is the process-oriented spine; each stage links to a dedicated page (process view) and to the existing deep-dive doc (algorithm view).

## Two commands, one pipeline

| Command | Runs |
|---|---|
| `pagespeak convert <file>` | Ingest **+** Phase 3 (the whole pipeline). |
| `pagespeak convert <outdir>` | Phase 3 only — reuses an existing `<stem>.raw.md`. |
| `pagespeak ingest <file> [--workers N]` | Ingest only — produces `<stem>.raw.md` + `images/`. |
| `pagespeak invalidate <outdir> <stage>` | Bust caches at `<stage>` and everything downstream. |
| `pagespeak baseline save\|list\|diff <outdir>` | Snapshot / compare runs. |
| `pagespeak deliver <outdir>` | Post-pipeline: copy just the deliverables (master `.md` + `sections/` + `images/`) to `…/delivery/<name>/`. See [usage.md](usage.md). |

`to_markdown(path, ...)` is the library equivalent of `pagespeak convert`.

## Stage sequence

```
ingest ─▶ cleanup ─▶ decorations ─▶ normalize ─▶ repair ─▶ structure ─▶ vision ─▶ split
 (raw)   (cleaned)   (in cleaned)  (normalized) (repaired) (structured) (inject) (sections/)
```

The stage names above are exactly the values accepted by `--rerun-from <stage>` and `pagespeak invalidate <outdir> <stage>`.

A run is a list of `Phase` objects executed by pf-core's sequencer (`pf_core.pipeline.sequencer.run_pipeline`); each phase reads its input checkpoint and writes its output one. So you can run **any contiguous slice**, not just "from X to the end":

- `--stop-after <phase>` — run normally, halt after `<phase>`.
- `--from <phase>` — begin at `<phase>`, hydrating its input from the existing on-disk checkpoint (trusts caches; does **not** bust them — that is `--rerun-from`).
- `--from X --stop-after X` — run exactly one phase, for methodical per-stage iteration.

Phase names here: `ingest | cleanup | normalize | repair | structure | vision | split` (`decorations` is a sub-step of `cleanup`, not a standalone phase, so it is not a `--from`/`--stop-after` target). Full semantics, the `--from` vs `--rerun-from` distinction, and the per-phase input/output checkpoints: [caching.md](caching.md) § "Running phases independently".

| Stage | Always on? | Checkpoint written | Page |
|---|---|---|---|
| **ingest** | yes (skipped in dir-mode) | `<stem>.raw.md`, `images/` | [pipeline-ingest.md](pipeline-ingest.md) |
| **cleanup** | yes (`cleanup="off"` is still a pass-through) | `<stem>.cleaned.md` | [pipeline-cleanup.md](pipeline-cleanup.md) |
| **decorations** | yes (set `decoration_threshold=0` to disable) | folded into `<stem>.cleaned.md` | [pipeline-decorations.md](pipeline-decorations.md) |
| **normalize** | opt-in (`normalize_headings=True`) | `<stem>.normalized.md` | [pipeline-normalize.md](pipeline-normalize.md) |
| **repair** | always runs ($0 deterministic; no-op by diagnosis on a clean doc) | `<stem>.repaired.md` | [pipeline-repair.md](pipeline-repair.md) |
| **structure** | always runs ($0 holistic doc-level passes; no-op on docs with a healthy pyramid) | `<stem>.structured.md` | [pipeline-structure.md](pipeline-structure.md) |
| **vision** | always runs (no-op without `diagrams=True` + images + `output_dir`); always snapshots | `<stem>.visioned.md` (post-inject + TOC); `.vision-cache/` | [pipeline-vision.md](pipeline-vision.md) |
| **split** | opt-in (`split_sections=True`) | `sections/`, `INDEX.md` | [pipeline-split.md](pipeline-split.md) |

Sub-steps that ride inside a stage rather than getting their own rerun key:

- **Frontmatter strip** — DOCX-only, opt-in, runs first inside *cleanup*.
- **Outline reconstruction** — Word multilevel-list → headings, runs as the *cleanup* pre-pass.
- **TOC regeneration** — replaces Marker's broken pipe-table TOC, runs just before *split* (always on via `regenerate_toc=True`).

## Checkpoint files

Each structural checkpoint is a plain `.md` snapshot of the document at that point. `diff <stem>.cleaned.md <stem>.normalized.md` shows exactly what normalize changed. They also enable resume: a re-run with no `--rerun-from` resumes from `<stem>.cleaned.md` when the source and cleanup-affecting flags are unchanged.

| File | Written by | Meaning |
|---|---|---|
| `<stem>.raw.md` | ingest | Backend output, untouched. |
| `<stem>.cleaned.md` | cleanup | Post frontmatter-strip + outline + decoration + cleanup. |
| `<stem>.normalized.md` | normalize | Post heading-level normalization (== cleaned.md when normalize is off). |
| `<stem>.repaired.md` | repair | Post $0 deterministic heading repair (== normalized.md when no defect is diagnosed). |
| `<stem>.structured.md` | structure | Post holistic doc-level passes (flat-source demote + orphan-H1 rebalance; == repaired.md when no defect is detected). |
| `<stem>.visioned.md` | vision | Post diagram-caption inject + TOC regen (== structured.md when no images). |
| `sections/`, `INDEX.md` | split | Per-section files + index (only when `split_sections=True`). |

## Re-running one stage

`pagespeak convert <outdir> --rerun-from <stage>` (or `pagespeak invalidate <outdir> <stage>`) deletes that stage's cache plus every **downstream** stage's structural files, then re-runs from there.

Deleted outputs are rebuilt with the **original run's flags by default**: when the output dir holds a `.pagespeak-run.json`, every output-shaping flag you don't pass explicitly is taken from that record's `resolved_flags` (so a bare `--rerun-from normalize` re-splits `sections/` exactly as before). The convert command echoes one `defaults inherited from .pagespeak-run.json: …` line naming what it took. Explicit flags — and an explicit `--preset`, for the preset-controlled flags — always win; `--no-inherit` ignores the record for old-style bare defaults. LLM/engine flags (`--diagrams`, `--vision-*`, models, `--device`) are never inherited. See [caching.md](caching.md) § "Re-run flag inheritance".

## Where to go deeper

| Topic | Doc |
|---|---|
| Backend selection, chunked workers, resume | [ingest.md](ingest.md), [backends.md](backends.md), [docx-backends.md](docx-backends.md) |
| Cleanup levels, cross-refs, splitting | [cleanup.md](cleanup.md) |
| Heading-level normalization engines | [normalize-headings.md](normalize-headings.md) |
| Vision backends, prompt versioning | [diagrams.md](diagrams.md) |
| Cache topology, `--rerun-from`, baselines | [caching.md](caching.md) |
| Module layout & data flow | [architecture.md](architecture.md) |
| CLI flags, env vars, recipes | [usage.md](usage.md) |
