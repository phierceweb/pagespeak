# Stage: split

Slices the consolidated markdown into one file per section under `sections/`, with an `INDEX.md` and per-file breadcrumb headers — the RAG-ready output shape. The last Phase 3 stage. Opt-in.

## What it does

Immediately before split, **TOC regeneration** (always on via `regenerate_toc=True`) replaces Marker's structurally-broken pipe-table Table of Contents with a generated bullet list of the document's real headings. TOC regen is a sub-step, not its own rerun stage.

Then `split_into_sections()`:

- writes one file per qualifying section, optionally mirroring the heading hierarchy into nested folders (`nested_split`);
- drops sections whose body is shorter than `min_body_chars` (default 30; set `0` to keep every heading);
- splits on **every heading** by default (`split_min_level=1` — numbered and un-numbered semantic alike), so a textbook's subsections each become their own RAG section; pass a higher `split_min_level` for coarser sections, or call `split_into_sections(min_level=None)` directly for numbered-only;
- emits an `INDEX.md` and a `> ↑ [Doc Title](INDEX.md) / [Chapter] / [Parent]` breadcrumb at the top of **every** section file so a retrieved chunk knows both its place AND its source document. The breadcrumb roots at the document title (`doc_title`, derived from the doc's first `# H1` by the split phase), so each chunk self-identifies its manual — the in-chunk cross-contamination fix for a multi-manual RAG DB. (Direct `split_into_sections` callers that omit `doc_title` get the legacy ancestor-only breadcrumb, and top-level sections then get none.)
- de-collides duplicate filenames and cleans up stale files from prior runs.

The consolidated `result.markdown` the command returns is **not** changed by this stage — `sections/` is an additional artifact.

## When it runs

- **Opt-in.** Off unless `split_sections=True` / `--split-sections`, or a preset that enables it (`rag-default`, `flat`, `textbook`).
- `nested_split`, `split_min_level`, `min_body_chars` tune the output shape.

## Inputs

The post-vision, post-TOC-regen consolidated markdown.

## Outputs

`sections/` (per-section files, optionally nested) and `INDEX.md`.

## Position

vision → TOC regen → **split** → `(done)`

## Re-running just this stage

`--rerun-from split` / `pagespeak invalidate <outdir> split` deletes `sections/` and `INDEX.md`, then re-splits the consolidated markdown.

> **Footgun:** `--split-sections` defaults to **off**. If you re-run an existing output dir with bare defaults, `sections/` is deleted and never rebuilt — a silent, empty `sections/`. Before re-running, read `<outdir>/.pagespeak-run.json` → `resolved_flags` and pass the same `split_sections` / `nested_split` / `split_min_level` / `preset` values. Re-running an existing output dir is destructive of downstream artifacts — re-run only with the same flags the original run used.

## Deep dive

- [cleanup.md](cleanup.md) — section splitting, cross-refs, breadcrumbs
- [caching.md](caching.md) — the rerun cascade and why downstream structural files are deleted
