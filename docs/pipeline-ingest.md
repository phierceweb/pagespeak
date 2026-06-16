# Stage: ingest

The backend phase. Turns a source document into raw markdown plus extracted images. Everything downstream operates on its output, never on the original file.

## What it does

1. Detects the format from the file extension.
2. Routes to a backend:
   - PDF → Marker (default) or Docling (`pdf_backend="docling"`).
   - `.docx` → MarkItDown (default) or python-docx (`docx_backend="python-docx"`).
   - Other office / HTML / CSV / EPUB / etc. → MarkItDown.
3. Writes `<stem>.raw.md` and extracts every embedded image into `images/`.

With `workers=1` (default) a single backend call processes the whole document. With `workers>1` (PDF only) a `ProcessPoolExecutor` runs Marker on page-range chunks in parallel; each chunk's image basenames are page-range prefixed and page-anchor IDs are absolutized before the chunks are concatenated into one `<stem>.raw.md`.

## When it runs

- **Always**, except in directory-mode: when the input is an output dir that already contains `<stem>.raw.md`, ingest is skipped and the pipeline jumps straight to Phase 3. This is how `pagespeak convert <outdir>` and `pagespeak ingest` once → iterate Phase 3 many times works.
- **Resume:** if `<stem>.raw.md` is newer than the source file, the backend call is skipped and the checkpoint is reused. Editing the source file invalidates it (mtime check).

## Inputs

The original document (`path`).

## Outputs

| Path | Always? |
|---|---|
| `<stem>.raw.md` | yes |
| `images/` | when the document has embedded images |
| `chunks/`, `manifest.json` | only with `workers>1` (chunked PDF) |

`<stem>.raw.md` is *truly raw* — frontmatter stripping and all cleanup happen later in Phase 3, not here.

## Position

`(source file)` → **ingest** → cleanup → …

## Re-running just this stage

`--rerun-from ingest` / `pagespeak invalidate <outdir> ingest` deletes `<stem>.raw.md`, `images/`, `chunks/`, `manifest.json`, **and every downstream checkpoint** — a full re-run. This re-invokes Marker/Docling/ MarkItDown, which on a large PDF is the multi-hour cost; reach for it only when the backend output itself is wrong.

## Deep dive

- [ingest.md](ingest.md) — `pagespeak ingest`, chunked-parallel workers, manifest v3, resume semantics
- [backends.md](backends.md) — Marker vs Docling for PDF
- [docx-backends.md](docx-backends.md) — MarkItDown vs python-docx for DOCX
- [format-support.md](format-support.md) — per-format quirks
- [operations.md](operations.md) — sandbox / `ProcessPoolExecutor` failures
