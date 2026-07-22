# Stage: split

Slices the consolidated markdown into one file per section under `sections/`, with an `INDEX.md` and per-file breadcrumb headers — the RAG-ready output shape. The last Phase 3 stage. Opt-in.

## What it does

Immediately before split, **TOC regeneration** (always on via `regenerate_toc=True`) replaces Marker's structurally-broken pipe-table Table of Contents with a generated bullet list of the document's real headings. TOC regen is a sub-step, not its own rerun stage.

Then `split_into_sections()`:

- writes one file per qualifying section, optionally mirroring the heading hierarchy into nested folders (`nested_split`);
- **names every file and folder as a slug** — lowercased, with each run of non-alphanumerics collapsed to a single `-` (`## Foot Switches (1)` → `foot-switches-1.md`). Unicode letters survive (`Благодарность` → `благодарность.md`); a title with no alphanumerics falls back to `section.md`. Slugs are a *fixed point* of the key normalization RAG stores apply to paths, so the filename, the `section_id`, and every in-document link target are the same string the store will key on — a breadcrumb link copied out of a chunk resolves as-is. Because slugs lowercase, titles differing only in case (`## Overview` / `## OVERVIEW`) now collide and are separated by the numeric-suffix resolver;
- **gives pre-heading content a home.** Anything before the document's first heading (title page, copyright, cover art, an abstract) becomes a leading `Front Matter` section instead of being dropped. It is inserted after parsing, so it never becomes anyone's parent and no other section's path changes; the usual `min_body_chars` gate still drops a trivial preamble;
- **gives an above-`min_level` heading a home when it carries prose.** Under `split_min_level=2` a `# Chapter` is normally context-only — it shapes the folder path and the breadcrumb but gets no file of its own. That is right for a bare page title, and wrong when the heading owns body text: a chapter whose content sits directly under the H1 (with no H2 children) would vanish entirely. So a heading above `min_level` is written **iff it has its own body**; bare ones stay context-only. This adds a file per such heading and populates `parent_id` on its children (previously empty, though those children already lived in the chapter's folder). Existing section filenames and paths are unaffected;
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

> Re-running an existing output dir is destructive of downstream artifacts, but the split flags are restored by default: a re-run inherits `split_sections` / `nested_split` / `split_min_level` / … from `<outdir>/.pagespeak-run.json` → `resolved_flags` and re-splits in the original shape (a notice line names the inherited flags). Only `--no-inherit` — or a missing record — reproduces the old trap, where `--split-sections` defaults **off** and a deleted `sections/` is never rebuilt. See [caching.md](caching.md) § "Re-run flag inheritance".

## Deep dive

- [cleanup.md](cleanup.md) — section splitting, cross-refs, breadcrumbs
- [caching.md](caching.md) — the rerun cascade and why downstream structural files are deleted
