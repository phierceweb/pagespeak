# The ingest command

`pagespeak ingest` is the backend phase: it converts a source document to `<stem>.raw.md` + `images/`. Phase 3 (cleanup → normalize → repair → structure → vision → split) runs separately via `pagespeak convert`.

## When to use `ingest` directly

Most of the time you want `pagespeak convert <input>`, which runs ingest internally and then runs Phase 3 in one go. Reach for `ingest` directly when:

- **Very long PDFs** (~500+ pages) where you want chunked-parallel Marker workers (`--workers N`) and then want to iterate on Phase 3 separately without repeating the expensive backend step.
- **Crash recovery** — if a long ingest crashes mid-run, re-invoking the same `pagespeak ingest` command resumes from completed chunks; only the unfinished chunks re-run.
- **Two-command UX** — ingest once, iterate on cleanup / normalize / split many times: `pagespeak ingest thick.pdf -o ./out --workers 4` then `pagespeak convert ./out --normalize-headings --preset rag-default`.

For single-process runs (`--workers 1`, the default), `pagespeak convert` calls ingest internally; there is no practical reason to run them separately.

## Output shape

Regardless of worker count, `pagespeak ingest` always produces:

```
<output_dir>/
  <stem>.raw.md          # complete document as raw backend markdown
  images/                # all extracted images, flat
  manifest.json          # present only when --workers > 1
  chunks/                # present only when --workers > 1
    <page_range>/
      raw.md
      images/
```

Single-process and chunked runs are identical from Phase 3's perspective: it always reads `<stem>.raw.md` and `images/`. The manifest and `chunks/` dirs are an implementation detail of the chunked path; Phase 3 does not read them.

## The two execution paths

### Single-process (default, `--workers 1`)

```bash
pagespeak ingest manual.pdf -o ./out
# equivalent to what convert runs internally
```

- Calls Marker (or Docling, or MarkItDown) on the full document in one shot.
- Writes `<stem>.raw.md` and `images/`.
- No `manifest.json`. No `chunks/`.
- Best output quality: Marker decides heading depth from full-document font statistics, so the heading hierarchy is consistent.

### Chunked-parallel (`--workers N`, PDF-only)

```bash
pagespeak ingest thick-textbook.pdf -o ./out --workers 4 --device cpu
```

- Slices the PDF into N-page chunks (default 50 pages each) and runs Marker in a `ProcessPoolExecutor` of N workers simultaneously.
- After all chunks complete, concatenates them into `<stem>.raw.md` and flattens images into `images/` with page-range-prefixed basenames (e.g. `0-49-_page_0_Figure_1.jpeg`) to prevent collisions across chunks.
- Page-anchor IDs (`<span id="page-X-Y"></span>`) are absolutized during concatenation so chunk-local page numbers don't collide.
- Writes `manifest.json` and `chunks/<page_range>/` per chunk.
- **Heading quality trade-off:** chunking flattens Marker's heading hierarchy because Marker computes depth from local font statistics that don't agree across chunk boundaries. Use `--normalize-headings` (or `--preset textbook`) in the subsequent `convert` phase to compensate; or use `--pdf-backend docling` (always 2 levels, but stable).

## Flags

| Flag | Default | Purpose |
|---|---|---|
| `<input>` | (required) | Path to the source document |
| `--output-dir`, `-o` | `./out` | Directory for `<stem>.raw.md` and `images/` |
| `--workers`, `-w` | `1` | Worker count. `1` = single-process; `N > 1` = chunked-parallel (PDF only). Override default via `PAGESPEAK_WORKERS`. |
| `--chunk-pages` | `50` | Pages per chunk (chunked path only). Smaller = finer-grained resume; larger = less Marker model-load overhead per chunk. |
| `--device` | (auto) | `cpu` / `mps` / `cuda`. `cpu` avoids the surya/MPS crash on Apple Silicon. |
| `--force-ocr` | off | PDF only — force OCR even on text-bearing PDFs. |
| `--pdf-backend` | `marker` | `marker` (default) or `docling`. See [docs/backends.md](backends.md). |
| `--docx-backend` | `markitdown` | `markitdown` (default) or `python-docx`. `.docx`-only, single-process. See [docs/docx-backends.md](docx-backends.md). |
| `--force` | off | Re-run chunks already marked completed in the manifest (chunked path only). |

> **Sandbox / `ProcessPoolExecutor`:** Chunked-parallel ingest fails with `PermissionError` on restricted macOS sandboxes. See [operations.md](operations.md).

## Resume semantics

Resume is automatic on the chunked path: re-invoking the same `pagespeak ingest` command re-reads `manifest.json` and skips chunks already marked `status: completed`. Only unfinished or failed chunks run.

```bash
# First run — 8 of 10 chunks complete, process killed.
pagespeak ingest thick.pdf -o ./out --workers 4

# Second run — picks up the 2 remaining chunks.
pagespeak ingest thick.pdf -o ./out --workers 4
```

On the single-process path there is no manifest; resume means the same thing as on `pagespeak convert` — `<stem>.raw.md` exists and is fresher than the source file, so the backend step is skipped entirely.

**Backend mismatch:** if the manifest records `pdf_backend: marker` but you invoke with `--pdf-backend docling`, the command refuses with a clear message. Pass `--force` to override and re-run all chunks from scratch.

**Manifest schema v3:** `manifest.json` uses schema version
3. Files written by older versions (v1 / v2) are refused with a `--force` / `rm -rf` remediation message.

## One-command vs two-command UX

```bash
# One command — ingest + Phase 3 in a single invocation.
pagespeak convert thick.pdf -o ./out --workers 4 --normalize-headings

# Two commands — ingest once, iterate Phase 3.
pagespeak ingest thick.pdf -o ./out --workers 4
pagespeak convert ./out --normalize-headings --preset rag-default
pagespeak convert ./out --normalize-headings-mode llm  # iterate
```

The two-command form is useful when the backend step is very slow (large PDF, many workers) and you want to tune cleanup, normalize, and split without re-running Marker.

## Per-chunk image handling

When `--workers N > 1`, chunk images are flattened into `<output_dir>/images/` at concatenation time. Two collision-prevention rewrites happen on the worker side before writing the consolidated `<stem>.raw.md`:

1. **Page-range basename prefix** — each chunk's image basename is prefixed with its page range: `_page_0_Figure_1.jpeg` → `0-49-_page_0_Figure_1.jpeg`. This ensures images from different chunks with the same Marker-generated basename don't overwrite each other.

2. **Page-anchor ID absolutization** — Marker emits `<span id="page-X-Y">` where X and Y are chunk-local page numbers. At concatenation, IDs are rewritten to be absolute across the full document so cross-chunk `[label](#page-X-Y)` refs resolve correctly in the consolidated text.

`cross_refs="remap"` is automatically defaulted to `True` when a manifest is present in the output dir, ensuring Phase 3's anchor-rewrite pass runs.

## Manifest schema reference

`manifest.json` is the single source of truth for chunked-parallel runs.

```json
{
  "version": 3,
  "input_path": "/abs/path/thick.pdf",
  "input_sha256": "...",
  "pdf_backend": "marker",
  "chunks": [
    {
      "page_range": "0-49",
      "status": "completed",
      "raw_md": "chunks/0-49/raw.md",
      "images": ["chunks/0-49/images/_page_0_Figure_1.jpeg"],
      "completed_at": "2026-05-13T10:23:00Z",
      "error": null
    }
  ]
}
```

Manifest writes are atomic (`os.replace` after writing to a temp file) so a crash mid-write never leaves a torn file.

## Concurrency guide

| Execution | Bottleneck | Scaling |
|---|---|---|
| Single-process | CPU/RAM | Single Marker call; no concurrency. |
| Chunked (`--workers N`, `anthropic`/`claude_code`) | CPU/GPU + RAM per worker | Each worker reloads ~2GB of torch + surya state. On a 16GB Mac, 3–4 workers is the sweet spot. Cap at `min(cpu_count, free_ram_gb // 2)`. |

Vision-pass concurrency is a Phase 3 concern (`--vision-concurrency`), not an ingest flag. See [usage.md](usage.md).
