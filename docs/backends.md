# PDF backends

Two general PDF backends. Pick per call via `pdf_backend="marker"` (default) or `pdf_backend="docling"`. A third, special-purpose backend — `pdf_backend="tophat"` — handles **Top Hat quiz-export PDFs** only (text-layer → per-question markdown); see [tophat-quizzes.md](tophat-quizzes.md). The rest of this page covers the two general backends.

## When to pick which

| Backend | Pick it for | Avoid it when |
|---|---|---|
| **Marker** (default) | Heading hierarchy matters — RAG ingestion, navigation, downstream LLMs reasoning over structure. Preserves a proper 4-level pyramid on real docs. | Marker crashes recurrently on Apple Silicon MPS — pass `--device cpu`. Tables occasionally mangled (cell boundaries split words). |
| **Docling** | Better figure extraction (~25% more figures on textbooks). Well-formed tables. MPS-clean on Apple Silicon. Formula → LaTeX via `do_formula_enrichment=True`. | Anything where heading depth matters. Docling's layout model labels every section heading as `level=1`, so its output is always capped at 2 heading levels regardless of doc structure. |

The chunked pipeline flattens Marker's hierarchy too — Marker decides heading depth from local font statistics that don't agree across chunks. See [pipeline.md](pipeline.md) for details. Use `pagespeak convert` for any doc that fits in single-shot, or pair the pipeline with `--pdf-backend docling` (chunk-stable, but capped at 2 levels).

## Install

```bash
pip install pagespeak[pdf]              # Marker (default)
pip install pagespeak[pdf-docling]      # Docling
pip install pagespeak[pdf,pdf-docling]  # both — pick at call time
pip install pagespeak[tophat]           # Top Hat quiz backend (light; pypdfium2)
```

If you ask for a backend that isn't installed, pagespeak raises `ImportError` with the exact pip extra in the message — no debugging needed.

## Library API

```python
from pagespeak import to_markdown, chunk

# Single-shot
result = to_markdown(
    "textbook.pdf",
    output_dir="./out",
    pdf_backend="docling",            # default "marker"
)

# Pipeline
mf = chunk(
    "textbook.pdf",
    output_dir="./out",
    pdf_backend="docling",
    workers=4,
    device="cpu",
)
```

## CLI

```bash
pagespeak convert textbook.pdf -o ./out --pdf-backend docling
pagespeak ingest textbook.pdf -o ./out --pdf-backend docling --workers 4   # backend phase only, chunked-parallel
pagespeak convert ./out                                                    # then Phase 3 on the existing raw.md
```

## Common surface — what's identical across backends

These args do the same thing on either backend:

| Arg | What it does |
|---|---|
| `output_dir` | Where extracted images land (`<output_dir>/images/<name>`). |
| `force_ocr` | Force OCR on text-bearing PDFs. Marker: `force_ocr=True`. Docling: `do_ocr=True` + `ocr_options.force_full_page_ocr=True`. |
| `device` | Marker: sets `TORCH_DEVICE`. Docling: sets `accelerator_options.device`. Accepts `"cpu"` / `"mps"` / `"cuda"`. |
| `page_range` | 0-based, inclusive. `"0-19"` / `[0,1,2,...]`. Marker accepts non-contiguous; Docling collapses to (min, max) and logs a WARNING. |

## Backend-specific surface — `pdf_backend_kwargs`

Anything past the common surface is reachable via `pdf_backend_kwargs`, a dict forwarded to the active backend's pipeline-options object.

### Marker

`pdf_backend_kwargs` is merged into Marker's `PdfConverter(config=…)`. Anything Marker accepts in that dict works.

```python
to_markdown(
    "doc.pdf",
    pdf_backend="marker",
    pdf_backend_kwargs={"output_format": "markdown", "use_llm": False},
)
```

### Docling

`pdf_backend_kwargs` is applied to `PdfPipelineOptions` via `setattr`. Unknown keys log a WARNING and are ignored.

| Key | What it does |
|---|---|
| `do_formula_enrichment` | Detect math, output as LaTeX. Default `False`. |
| `do_code_enrichment` | Code-block-specific OCR. Default `False`. |
| `do_picture_classification` | Tag pictures by type (photo/diagram/chart). Default `False`. |
| `do_chart_extraction` | Convert bar/pie/line charts to tabular data. Default `False` (auto-enables `do_picture_classification`). |
| `do_table_structure` | Detect + reconstruct table structure. Default `True`. |
| `images_scale` | Scaling factor for extracted images. Higher = better quality, slower. Default `1.0`. |

```python
to_markdown(
    "math-paper.pdf",
    pdf_backend="docling",
    pdf_backend_kwargs={
        "do_formula_enrichment": True,
        "images_scale": 2.0,
    },
)
```

## Resume safety

Mixing two backends in one pipeline output dir is unsafe — markdown conventions and image filenames differ subtly enough to break anchor maps at stitch time.

`pagespeak ingest --workers` (and the `chunk()` library API) records each chunk's backend in `manifest.json`. A second invocation with a different `--pdf-backend` raises:

```
ValueError: Output dir ./out has chunks completed with backend(s) ['marker'];
cannot resume with pdf_backend='docling'. Use --force to re-run from scratch,
or pick a fresh output dir.
```

Use `--force` to acknowledge the choice and re-run, or pick a fresh output dir.

## Speed

Marker: ~30s model-load on first call, then ~10s for a 12-page PDF. Docling: ~10s model-load, but ~30s convert because it runs more layout/structure models. For pipeline runs, parallelism (chunk workers) hides Docling's per-page cost.
