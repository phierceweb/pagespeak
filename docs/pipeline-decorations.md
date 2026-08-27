# Stage: decorations

Handles repeated page-furniture images — running page headers, footer logos, watermarks — that Marker extracts once per page. Only a provable repeat is removed; anything merely similar is preserved, in one form or another. A separate rerun stage, but it executes inside the cleanup stage, before the per-line transforms.

## What it does

1. Computes a perceptual hash (phash) for every extracted image.
2. Clusters near-duplicate phashes by Hamming distance (`decoration_hamming_distance`, default 12).
3. A cluster whose size meets `decoration_threshold` (default 5) is treated as decoration. What happens to each ref depends on how sure the match is:
   - **Near-exact duplicate** (`EXACT_DUPLICATE_HAMMING_DISTANCE`, 2) → the ref is removed. This is the same image again, so its alt text is a label, not a description; a repeated UI icon reading "Add" is furniture either way.
   - **Merely similar, with a real description** → the ref degrades to an italic caption, the same treatment a dangling ref gets. The description survives even when the cluster was wrong. A synthesised alt that is just the image's filename does not count as a description.
   - **Merely similar, with nothing to preserve** → left alone. Deleting it would destroy content on a guess.

A logo that appears on every one of 200 pages is the same image 200 times, so it clears the near-exact gate and all 200 refs go; a figure that appears twice does not reach the threshold at all.

A phash cannot distinguish repeated furniture from a figure the document legitimately reuses, and it is least reliable on schematic line art and text-on-white — exactly the images worth keeping. The split above is why a wrong call costs a rendered image rather than the content.

Because this runs inside cleanup, refs extracted from PDFs are still alt-less at this point (the vision pass captions them four phases later — normalize, repair and structure sit in between). On the PDF path the near-exact gate, not `decoration_hamming_distance`, is what decides removal.

## When it runs

- **Always**, whenever the document has extracted images and an `output_dir`. Set `decoration_threshold=0` to disable.
- Tunables: `decoration_threshold` (cluster-size cutoff; `0` = off), `decoration_hamming_distance` (near-duplicate grouping width).

## Inputs

The post-frontmatter markdown plus `images/` (the phash source).

## Outputs

No structural file of its own — the stripped markdown flows into `<stem>.cleaned.md` (owned by the [cleanup](pipeline-cleanup.md) stage). Detection is recomputed in-memory each run; it persists no cache file of its own.

## Position

cleanup (frontmatter) → **decorations** → cleanup (line transforms) → normalize → …

## Re-running just this stage

`--rerun-from decorations` / `pagespeak invalidate <outdir> decorations` busts the downstream structural checkpoints, then re-detects decorations (in-memory — there is no decoration cache file to clear). The exact cascade (which files are deleted vs. self-invalidated) is defined by the stage registry and documented in [caching.md](caching.md).

## Deep dive

- [caching.md](caching.md) — cache topology and the rerun cascade
- [architecture.md](architecture.md) — phash helpers (`utils/_phash.py`) and where the strip happens
