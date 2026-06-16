# Stage: cleanup

Turns raw backend markdown into normalized markdown: fixes Word outline lists, strips template frontmatter, applies per-line cleanup transforms, and demotes prose-shaped fake headings. The first Phase 3 stage.

## What it does

In order, inside this stage:

1. **Remote-image localize** (`localize_remote_images_in_markdown()`) — downloads any remote `![](http…)` refs into `images/` + retargets them to local, gated by `PAGESPEAK_DOWNLOAD_REMOTE_IMAGES`. A **no-op on the HTML path** (IngestPhase already localized those refs) and when the doc has no remote refs. It exists for **markdown / dir-mode** sources, which skip ingest (where HTML's download runs) — so a `.md` source's figures still get pulled local + reach the vision pass. Markdown sources are expected to carry absolute/resolvable URLs.
2. **Frontmatter strip** (DOCX/MarkItDown formats only, opt-in via `strip_frontmatter` or the `rag-default` preset) — drops everything before the first `# H1` when the leading content matches ≥2 enterprise-template patterns (Word TOC anchors, revision-history table, placeholders, instructional boilerplate).
3. **Decoration strip** — see [pipeline-decorations.md](pipeline-decorations.md) (its own rerun stage, but it executes here, before the line transforms).
4. **Outline reconstruction** (`promote_outline()`) — a cleanup *pre-pass* that converts Word "Multilevel List" indentation into real heading / list structure. Runs before the per-line `.strip()` that would destroy the indentation signal.
5. **Per-line cleanup** — the `off` / `basic` / `aggressive` transform set: heading promotion, span stripping, cross-ref handling, prose-heading demotion via `_heading_sanity`.

## When it runs

- **Always.** `cleanup="off"` still passes through the stage (frontmatter / decoration / outline steps still apply); only the per-line transform set is skipped. Default level is `basic`.
- **Resume:** a re-run with no `--rerun-from` resumes from `<stem>.cleaned.md` when `<stem>.raw.md` and the cleanup-affecting flags (`cleanup`, `cross_refs`, `strip_frontmatter`, decoration thresholds) are unchanged — the whole stage is skipped.

## Inputs

`<stem>.raw.md` (+ `images/` for decoration phash clustering).

## Outputs

`<stem>.cleaned.md` — the structural checkpoint. Written whenever `output_dir` is set, even at `cleanup="off"` (it then captures only the frontmatter / decoration / outline effects).

## Position

ingest → **cleanup** → normalize → …

## Re-running just this stage

`--rerun-from cleanup` / `pagespeak invalidate <outdir> cleanup` deletes `<stem>.cleaned.md` and every downstream checkpoint, then re-runs cleanup against the existing `<stem>.raw.md`. The backend is **not** re-invoked.

## Deep dive

- [cleanup.md](cleanup.md) — cleanup levels, cross-refs, the full transform list
- [architecture.md](architecture.md) — where the outline pre-pass and heading-sanity sit
