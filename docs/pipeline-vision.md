# Stage: vision

Runs each extracted image through a vision model and embeds the result — a caption, and for actual diagrams a Mermaid representation — next to the image reference in the markdown. Opt-in (but on by default).

## What it does

1. **Gather** — for each image: compute its phash, look it up in `<outdir>/.vision-cache/<phash>.json`, and on a miss fire one backend call. Calls fan out across a thread pool (`vision_concurrency`, default 6). One image's failure is non-fatal — it yields a caption-only result and the pass continues.
2. **Inject** — rewrite the markdown, matching cached results to image references by basename and inserting the caption + Mermaid block.

Backends (`vision_backend`): `claude_code` (default — local `claude --print`, $0/call), `anthropic` (direct API), `openrouter`. Default model is Claude Haiku 4.5.

## When it runs

- **Opt-in but default-on:** runs when `diagrams=True` (the default) **and** the document has extracted images **and** an `output_dir` is set. Passing `diagrams=False`, or having no images / no output dir, skips it.
- Photos / screenshots / logos get a one-line caption; data charts and diagrams get a multi-sentence caption and (when applicable) Mermaid.

## Inputs

`<stem>.structured.md` content + `images/`. Vision runs **after** repair and structure so captions are injected into the final heading shape.

## Outputs

`<stem>.visioned.md` — the post-inject + post-TOC checkpoint, always written (even when vision/TOC were no-ops) so `--from split` can run from the real post-vision state. The other persisted artifact is the content-keyed cache `.vision-cache/<phash>.json` — keyed by image phash ONLY; the `backend`/`model` in each entry are provenance, never a reuse gate.

## Position

structure → **vision** (inject + TOC regen) → split

## Re-running just this stage

`--rerun-from vision` / `pagespeak invalidate <outdir> vision` busts `.vision-cache` and downstream structural files, then re-gathers. A backend / model change does **not** auto-invalidate the cache — cached descriptions are reused across engines; bust explicitly to re-analyse (see [caching.md](caching.md)).

## Deep dive

- [diagrams.md](diagrams.md) — backend mechanics, prompt versioning, failure handling
