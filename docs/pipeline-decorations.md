# Stage: decorations

Removes repeated page-furniture images — running page headers, footer logos, watermarks — that Marker extracts once per page. A separate rerun stage, but it executes inside the cleanup stage, before the per-line transforms.

## What it does

1. Computes a perceptual hash (phash) for every extracted image.
2. Clusters near-duplicate phashes by Hamming distance (`decoration_hamming_distance`, default 12).
3. A cluster whose size meets `decoration_threshold` (default 5) is treated as decoration: its image references are stripped from the markdown text.

A logo that appears on every one of 200 pages becomes one 200-member cluster and all 200 refs are removed; a figure that appears twice does not.

## When it runs

- **Always**, whenever the document has extracted images and an `output_dir`. Set `decoration_threshold=0` to disable.
- Tunables: `decoration_threshold` (cluster-size cutoff; `0` = off), `decoration_hamming_distance` (near-duplicate grouping width).

## Inputs

The post-frontmatter markdown plus `images/` (the phash source).

## Outputs

No structural file of its own — the stripped markdown flows into `<stem>.cleaned.md` (owned by the [cleanup](pipeline-cleanup.md) stage). Its only persisted artifact is the content-keyed cache `.decoration-cache`.

## Position

cleanup (frontmatter) → **decorations** → cleanup (line transforms) → normalize → …

## Re-running just this stage

`--rerun-from decorations` / `pagespeak invalidate <outdir> decorations` busts `.decoration-cache` and the downstream structural checkpoints, then re-detects decorations. The exact cascade (which files are deleted vs. self-invalidated) is defined by the stage registry and documented in [caching.md](caching.md).

## Deep dive

- [caching.md](caching.md) — cache topology and the rerun cascade
- [architecture.md](architecture.md) — phash helpers (`utils/_phash.py`) and where the strip happens
