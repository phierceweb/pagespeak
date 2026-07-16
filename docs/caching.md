# Caching & re-test ergonomics

pagespeak persists every expensive intermediate so a re-run only re-does the work that's actually under test. This doc is the canonical map of cache layers, invalidation rules, and the knobs for picking which layers to bust.

## Layout — what's cached, where, and how it invalidates

| Stage | Cache file(s) | Auto-invalidated by | `--rerun-from <stage>` busts |
|---|---|---|---|
| `ingest` | `<stem>.raw.md`, `images/` | source mtime > raw.md mtime | own structural |
| `cleanup` | `<stem>.cleaned.md` | content+flags hash | own structural |
| `decorations` | (in-memory; no persistent file) | always re-runs | — |
| `normalize` | `.heading-normalize-cache/<hash>.json` (LLM mode), `<stem>.normalized.md` (snapshot) | content+model hash (cache); cascade (snapshot) | own (cache content-keyed, snapshot mtime-gated) |
| `repair` | `<stem>.repaired.md` (snapshot; $0 deterministic — no content-keyed cache) | cascade (snapshot) | own structural |
| `structure` | `<stem>.structured.md` (snapshot; $0 deterministic — no content-keyed cache) | cascade (snapshot) | own structural |
| `vision` | `<stem>.visioned.md` (structural snapshot, post-inject + TOC), `.vision-cache/<phash>.json` (content-keyed) | image phash change (cache; **engine-independent** — a description is reused regardless of which backend/model made it); cascade (snapshot) | own structural + own content-keyed cache; `.vision-cache` preserved **and reused** across *upstream* cascade |
| `split` | `sections/`, `INDEX.md` | always | structural |

The pipeline order is:

```
ingest → cleanup → decorations → normalize → repair → structure → vision → split
```

### Why content-keyed caches survive the cascade

Two caches — `.vision-cache/<phash>.json` and `.heading-normalize-cache/<hash>.json` — are keyed by content hash, not mtime. The phash for an image and the content hash for a heading list both encode validity directly: same image → same phash → cache hit; same heading list → same hash → cache hit. They self-invalidate when the input changes, regardless of upstream re-runs.

**The vision cache is engine-independent.** A cached description is keyed by the image's phash alone — it is reused whenever the same image reappears, *regardless of which backend or model produced it* (`claude_code` / `anthropic` / `openrouter`). The `backend`/`model` recorded in each entry are provenance only, never a reuse gate: a description is a function of the image, so switching engines must not silently re-spend on images already analysed. Re-ingesting or tinkering with cleanup/normalize/repair therefore reuses every already-analysed image for free. To force fresh descriptions, delete the cache explicitly (`--rerun-from vision` / `pagespeak invalidate <dir> vision`). (The heading-normalize cache differs deliberately: its hash *includes* the model + mode, so a model/mode change re-runs it.)

So the cascade rule is: `--rerun-from <stage>` busts the target stage's OWN cache (whether structural or content-keyed) plus every downstream stage's STRUCTURAL files. Downstream content-keyed caches are PRESERVED.

Concrete: `--rerun-from ingest` invalidates raw.md + images + the downstream snapshot files (cleaned.md, normalized.md, visioned.md) + the split output, but **leaves `.vision-cache/` and `.heading-normalize-cache/` intact**. On re-run, Marker may produce identical-by-phash images that hit the vision cache for free, and the normalize LLM call may hit the heading-normalize cache if the heading list is unchanged.

To force a brand-new run with all caches gone, use `rm -rf <output_dir>` or chain `--rerun-from vision` after `--rerun-from ingest` (each invalidation is composable).

## Cleanup-affecting flags

A flag change on any of these invalidates `<stem>.cleaned.md`:

- `cleanup` (level)
- `cross_refs`
- `strip_frontmatter`
- `decoration_threshold`
- `decoration_hamming_distance`

The previous run's resolved flags are read from `<output_dir>/.pagespeak-run.json`.

## Two ways to bust caches

### Inline: `--rerun-from <stage>`

Valid stage names: `ingest`, `cleanup`, `decorations`, `normalize`, `repair`, `structure`, `vision`, `split`.

```
pagespeak convert manual.pdf -o ./out --rerun-from cleanup
```

Deletes the cleanup cache and everything downstream, then runs from the start. Useful when you've changed code and want to re-test the affected phase against the existing upstream caches.

> **Destructive — `--rerun-from` deletes downstream structural outputs.** `--rerun-from <stage>` removes that stage's cache **plus every downstream structural artifact**, including `sections/` and `INDEX.md`. If you re-run without the same output-shaping flags the original run used (`--split-sections`, `--nested-split`, `--preset`, …), those outputs are deleted and **not regenerated** — you silently end up with no `sections/`.
> Before re-running an existing output dir, read its `.pagespeak-run.json` → `resolved_flags` and pass the same flags. See `docs/operations.md` § "Re-validating a Phase-3 change".

### Out-of-band: `pagespeak invalidate`

```
pagespeak invalidate ./out cleanup
```

Same invalidation logic, no re-run. Useful for:

- Staging a fresh re-test before running multiple `convert` invocations.
- Scripted batch operations (invalidate across a fleet of output dirs, then trigger CI).

## Running phases independently (`--from` / `--stop-after`)

The pipeline is a list of phases run by a sequencer; each phase reads its input checkpoint and writes its output checkpoint. Two flags slice which phases run, so you can validate one phase at a time:

- `--stop-after <phase>` — run normally but halt after `<phase>` (its checkpoint is written; nothing downstream runs). Always safe; needs no special setup.
- `--from <phase>` — begin at `<phase>`, hydrating its input from the existing upstream checkpoint on disk (does **not** bust caches — that's `--rerun-from`). Errors if the input checkpoint is absent.

Phase names: `ingest | cleanup | normalize | repair | structure | vision | split` (no `decorations` — it is a sub-step of `cleanup`, not a standalone phase). Input checkpoint per phase: cleanup←`raw.md`, normalize←`cleaned.md`, repair←`normalized.md`, structure←`repaired.md`, vision←`structured.md`, split←`visioned.md`. Output checkpoint per phase: ingest→`raw.md`, cleanup→`cleaned.md`, normalize→`normalized.md`, repair→`repaired.md`, structure→`structured.md`, vision→`visioned.md` (post-inject + TOC), split→`sections/`+`INDEX.md`.

`--from X --stop-after X` runs **exactly one phase**. Examples:

```
# produce/inspect ONLY the cleaned phase, then stop
pagespeak convert ./out --from cleanup --stop-after cleanup
# re-do just heading-normalize against the frozen cleaned.md
pagespeak convert ./out --from normalize --stop-after normalize
```

`--from` vs `--rerun-from`: `--from` *trusts* upstream checkpoints and starts there; `--rerun-from` *invalidates* the stage (+downstream structural) then runs to the end. Use `--from`/`--stop-after` for methodical phase-by-phase iteration; `--rerun-from` to force a stale stage to recompute.

All seven phases write a structural checkpoint, so any one runs standalone from its real input — `--from split` splits the true post-vision `visioned.md`. (`decorations` deliberately has no standalone checkpoint: it is a `cleanup` sub-step, not a phase, and promoting it to a reordered standalone phase would be behaviour- changing — see `_rerun.py`.)

## Resume-from-cleaned

A re-run with no `--rerun-from` flag will resume from `<stem>.cleaned.md` IFF:

1. `<stem>.cleaned.md` exists.
2. Its mtime ≥ `<stem>.raw.md` mtime.
3. The cleanup-affecting flags in the previous run.json match the current resolved flags.
4. The run did not explicitly start at cleanup. `--from cleanup` forces a fresh cleanup re-run — the shortcut is for the normal full run, not an explicit per-stage start, otherwise per-stage iteration on cleanup would silently reuse the stale cache and never run the code under test.

When resume hits, the log includes `resume_from_cleaned path=...`. The ingest and cleanup phases are skipped — including the decorations sub-step, since `cleaned.md` is already post-decoration. Normalize, repair, structure, vision (with TOC regen), and split run.

## `<stem>.raw.md` is truly raw

The DOCX `_strip_template_frontmatter` step runs in Phase 3 (cleanup), not inside `convert_with_markitdown`. So raw.md is the unmodified backend output; toggling `--strip-frontmatter` invalidates `<stem>.cleaned.md` (it's a cleanup-affecting flag) but leaves raw.md untouched.

## Baselines

A baseline preserves a result for later comparison — useful when you want to re-run after changing pipeline code and see what changed.

```
.baselines/<label>/
├── <stem>.md           # consolidated
├── INDEX.md
├── sections/           # full tree
└── .pagespeak-run.json # snapshot of resolved config + counts
```

What's NOT in a baseline (cheap to rebuild from caches; would bloat storage): the stage checkpoints (`raw.md`, `cleaned.md`, `normalized.md`, `repaired.md`, `structured.md`, `visioned.md`), vision-cache, heading-normalize-cache, images.

### Two ways to baseline

**Explicit:**

```
pagespeak baseline save ./out --label pre-change
```

Default label is `<version>-<YYYYMMDD-HHMMSS>` so multiple unlabeled saves don't collide.

**Automatic on version change:**

When `to_markdown()` runs after `__version__` changed since the previous successful run, the previous output is auto-baselined into `.baselines/<previous-version>/` before the new run touches anything. Skipped on first run, when previous output had no sections, or on write failure (logged as WARNING, never fatal).

### Inspecting baselines

```
pagespeak baseline list ./out
```

Prints a fixed-width table with label, version, preset, saved-at, section count, image count. Sorted by saved-at descending.

### Diffing baselines

```
pagespeak baseline diff ./out pre-change
```

Default output is a structured summary in three parts:

1. **Run record diff** — field-level diff of `.pagespeak-run.json`. Only changed fields shown. Unchanged → `Run record: unchanged`.
2. **Section filename set** — added / removed / renamed paths. Renames detected by either body sha256 match (similarity 1.0) or same-folder + Levenshtein basename ≤ 4 + body similarity ≥ 0.8.
3. **Per-section line-count rollup** — `+N -M` per file in both, sorted by total change descending. Top 30 by default; everything excluded from rename pairs.

Drill-in:

```
pagespeak baseline diff ./out v1 --show-section "Intro.md"
pagespeak baseline diff ./out v1 --show-consolidated
```

Both produce a `difflib.unified_diff` over the file pair. The two flags are mutually exclusive.

For a raw filesystem diff outside the structured summary:

```
diff -r ./out/.baselines/pre-change/sections/ ./out/sections/
```

## Quick reference

| You want to… | Do |
|---|---|
| Re-test splitter changes | `--rerun-from split` |
| Re-test cleanup or frontmatter logic | `--rerun-from cleanup` |
| Re-test normalize (heading levels) | `--rerun-from normalize` |
| Re-test post-LLM heading repair | `--rerun-from repair` |
| Re-test vision/diagram extraction (deletes `.vision-cache`) | `--rerun-from vision` |
| Re-test the whole pipeline (e.g. backend swap) | `--rerun-from ingest` |
| Stage a re-test for later | `pagespeak invalidate <out> <stage>` |
| Force a brand-new run | `rm -rf <out>` |
