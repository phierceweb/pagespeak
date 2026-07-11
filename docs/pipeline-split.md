# Stage: split

Slices the consolidated markdown into one file per section under `sections/`, with an `INDEX.md` and per-file breadcrumb headers — the RAG-ready output shape. The last Phase 3 stage. Opt-in.

## What it does

Immediately before split, **TOC regeneration** (always on via `regenerate_toc=True`) replaces Marker's structurally-broken pipe-table Table of Contents with a generated bullet list of the document's real headings. TOC regen is a sub-step, not its own rerun stage.

Then `split_into_sections()`:

- writes one file per qualifying section, optionally mirroring the heading hierarchy into nested folders (`nested_split`);
- drops sections whose body is shorter than `min_body_chars` (default 30; set `0` to keep every heading);
- splits on **every heading** by default (`split_min_level=1` — numbered and un-numbered semantic alike), so a textbook's subsections each become their own RAG section; pass a higher `split_min_level` for coarser sections, or call `split_into_sections(min_level=None)` directly for numbered-only;
- emits an `INDEX.md` and a `> ↑ [Doc Title](INDEX.md) / [Chapter] / [Parent]` breadcrumb at the top of **every** section file so a retrieved chunk knows both its place AND its source document. The breadcrumb roots at the document title (`doc_title`, derived from the doc's first `# H1` by the split phase), so each chunk self-identifies its manual — the in-chunk cross-contamination fix for a multi-manual RAG DB. (Direct `split_into_sections` callers that omit `doc_title` get the legacy ancestor-only breadcrumb, and top-level sections then get none.)
- stamps **identity frontmatter on every section file** (always on): `doc_id` (the out-dir / conversion name), `source_id` (a stable slug of the source filename — the cross-conversion key for one source work) + `source_sha256` (SHA-256 of the exact source bytes), `section_id` (the section's own relative path — a stable join key), `parent_id` (nearest written ancestor's `section_id`), `section_title` / `section_path` / `section_number` / `heading_level`, `depth`, and `order` (1-based document order). This is the machine-readable form of the breadcrumb: a consumer can walk from any retrieved chunk to its parent, siblings (`parent_id` + `order`), or whole document (`doc_id`) without another search. `source_id`/`source_sha256` are resolved from the source file (or, in directory mode, recovered from the out-dir's run record) and omitted when unrecoverable rather than guessed. The opt-in provenance source fields (`source_type` / `source_label` / `source_file`, see [docs/usage.md](usage.md)) merge into the same block when enabled;
- de-collides duplicate filenames and cleans up stale files from prior runs.

The consolidated `result.markdown` the command returns is **not** changed by this stage — `sections/` is an additional artifact.

## When it runs

- **Opt-in.** Off unless `split_sections=True` / `--split-sections`, or a preset that enables it (`rag-default`, `flat`, `textbook`).
- `nested_split`, `split_min_level`, `split_max_level`, `split_target_kb`, `min_body_chars` tune the output shape. `split_max_level=N` caps section depth (deeper headings stay inline) — `2` gives textbook section-level chunks instead of over-fragmenting a `# Title` + `## N.M` + deep-subsection doc into per-heading files.
- `split_target_kb=N` replaces the fixed-depth knobs with **size-targeted packing** (see `services/_split_pack.py`): each branch fitting N KB becomes one file, oversized branches split deeper, and an oversized heading-less section partitions into `(part i of k)` files sharing its identity. One setting adapts across book shapes where no single level works (mixed-depth chapters, flat mega-sections). Mutually exclusive with `split_max_level`.

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
