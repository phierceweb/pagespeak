# Stage: vision

Runs each extracted image through a vision model and embeds the result — a caption, and for actual diagrams a Mermaid representation — next to the image reference in the markdown. Opt-in (but on by default).

## What it does

1. **Gather** — for each image: compute its phash, look it up in `<outdir>/.vision-cache/<phash>.json`, and on a miss fire one backend call. Calls fan out across a thread pool (`vision_concurrency`, default 6). One image's failure is non-fatal — it yields a caption-only result and the pass continues.
2. **Inject** — rewrite the markdown, matching cached results to image references by basename and inserting the caption + Mermaid block.

Backends (`vision_backend`): `anthropic` (default API), `claude_code` (local `claude --print`, $0/call but slower), `openrouter`. Default model is Claude Haiku 4.5.

## When it runs

- **Opt-in but default-on:** runs when `diagrams=True` (the default) **and** the document has extracted images **and** an `output_dir` is set. Passing `diagrams=False`, or having no images / no output dir, skips it.
- Photos / screenshots / logos get a one-line caption; data charts and diagrams get a multi-sentence caption and (when applicable) Mermaid.

## Inputs

`<stem>.normalized.md` content + `images/`. Vision runs **after** normalize so captions are injected into the cleaned, normalized heading shape.

## Outputs

No structural `.md` checkpoint — the captions/Mermaid are injected into the final consolidated markdown the command returns. The persisted artifact is the content-keyed cache `.vision-cache/<phash>.json` (records backend + model, so a backend/model swap invalidates cleanly).

## Position

normalize → **vision** → TOC regen → split

## Re-running just this stage

`--rerun-from vision` / `pagespeak invalidate <outdir> vision` busts `.vision-cache` and downstream structural files, then re-gathers. A backend / model change auto-invalidates the cache without an explicit rerun.

## Deep dive

- [diagrams.md](diagrams.md) — backend mechanics, prompt versioning, failure handling
