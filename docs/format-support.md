# Format support

## What's supported

| Format | Backend | Image extraction | Notes |
|---|---|---|---|
| `.pdf` | Marker (default) or Docling | yes (rasterized to PNG) | Requires `pagespeak[pdf]` / `pagespeak[pdf-docling]`. `force_ocr=True` for scans. |
| Top Hat quiz-export `.pdf` | `--pdf-backend tophat` | yes (embedded figures) | Reads the PDF text layer → one `## Question N` block per question; marks the correct answer when revealed (grey-letter signal); extracts embedded figures (incl. image-only questions) for the vision pass. Requires `pagespeak[tophat]`. See [tophat-quizzes.md](tophat-quizzes.md). |
| `.docx` | MarkItDown | yes (via zipfile from `word/media/`) | Tables, headings, lists, footnotes |
| `.pptx` | MarkItDown | yes (via zipfile from `ppt/media/`) | Slide-by-slide content |
| `.xlsx` | MarkItDown | yes (via zipfile from `xl/media/`) | Sheet contents as markdown tables |
| `.html`, `.htm` | MarkItDown | yes (remote URLs downloaded by default; relative refs via `--html-base-url`) | Remote `<img>` URLs pulled into `images/` + refs retargeted so the vision pass sees them; toggle `PAGESPEAK_DOWNLOAD_REMOTE_IMAGES=0`. Web-help exports with relative `../Storage/..` refs: pass `--html-base-url` to resolve+download. Inline MathML (parallel presentation + content) is rebuilt as `$LaTeX$` before conversion so equations aren't doubled or flattened (`utils/_mathml.py`) |
| `.csv`, `.json`, `.xml` | MarkItDown | n/a | Tabular / structured content rendered as markdown |
| `.epub` | MarkItDown | yes (via zipfile, by image extension) | Per chapter; embedded figures extracted + refs retargeted to `images/` |
| `.md`, `.markdown` | Passthrough (verbatim) | n/a at ingest; remote URLs downloaded in cleanup | A source already in markdown enters the pipeline unchanged — no MarkItDown round-trip. Lets an upstream ingester hand off clean markdown for the cleanup → normalize → split passes. See the per-format note below. |
| Canvas QTI export (directory with `imsmanifest.xml`, or `.imscc` / `.zip`) | QTI backend | figures copied + linked | Classic Quizzes only. One markdown file per quiz with the answer key. See [canvas-quizzes.md](canvas-quizzes.md). |

## What's deliberately not supported

| Format | Why | Workaround |
|---|---|---|
| `.doc` / `.ppt` / `.xls` (legacy binary Office) | MarkItDown doesn't reliably handle the pre-OOXML binary formats | Convert to `.docx` / `.pptx` / `.xlsx` first via LibreOffice or Office |
| `.rtf` | Not a primary need across consumers | LibreOffice → `.docx` |
| `.odt` (OpenDocument) | Not a primary need across consumers | LibreOffice → `.docx` |
| `.pages` (Apple Pages) | A proprietary bundle, not an OOXML format MarkItDown reads | In Pages, **File → Export To → Word…**, then convert the `.docx`. For prose with real heading styles, use `--docx-backend python-docx` so the outline transfers faithfully; PDF export is a fallback only for layout/figure-heavy docs. |
| Scanned image files standalone (.png, .jpg) | Single-image OCR is its own thing | Out of scope; convert to a 1-page PDF first |
| Email (.eml, .msg) | Different shape — threading, attachments | Out of scope; consumers handle |

The format-suffix tables (`PDF_SUFFIXES` / `MARKITDOWN_SUFFIXES` / `MARKDOWN_SUFFIXES`) in `orchestrators/_ingest.py` are the single place to add a route.

## Per-format quirks

### PDF (Marker)

- Marker rasterizes every embedded image (vector or raster) to PNG at the page's resolution.
- Image filenames follow `_page_<N>_Picture_<I>.jpeg` for raster images and `_page_<N>_Figure_<I>.jpeg` for what Marker classifies as figures. Figures are usually diagrams; Pictures are often page-decoration headers.
- The diagram pass treats both identically — the vision LLM decides whether each is a real diagram regardless of Marker's classification.
- Marker emits `<span id="page-X-Y"></span>` anchors as cross-ref targets. The cleanup pass strips them on heading lines (basic cleanup) and everywhere (aggressive); see [cleanup.md](cleanup.md). `cross_refs="remap"` rewrites the refs to heading slugs.
- Tables: Marker's native table extraction works for vector PDFs. Image-of-table tables come through as image references (no Mermaid — caption only).
- Equations: plain text or LaTeX-ish. For LaTeX-grade math, prefer Docling with `pdf_backend_kwargs={"do_formula_enrichment": True}`.

### DOCX (MarkItDown + zipfile)

- MarkItDown's text extraction is solid on tables, headings, footnotes, and lists.
- It doesn't always emit `![...](path)` references for embedded images. Pagespeak compensates by:
  1. Always extracting `word/media/*` from the zip into `output_dir/images/`.
  2. If the markdown has no image references at all, appending an "Extracted Images" section at the end so the diagram pass has anchors to attach Mermaid blocks under.
- This means a DOCX with no inline image references in the body (rare but possible) will still get diagrams extracted; they just appear at the end rather than next to where they appeared visually in Word.

### PPTX

- MarkItDown produces "Slide N: title + body" sections.
- Embedded images are extracted from `ppt/media/`. Each becomes a candidate for the diagram pass.
- Layout / animation / transitions are not preserved (and shouldn't be for LLM ingest).

### XLSX

- Sheets render as markdown tables.
- Charts that are embedded as images get extracted from `xl/media/` and run through the diagram pass — but the LLM almost always returns `is_diagram: false` for a bar chart (correctly — Mermaid is the wrong representation for data viz). The image stays in the output with a caption.

### HTML

- HTML sources reference images by remote URL (`<img src="https://…">`); MarkItDown keeps them remote and never extracts them. **By default, HTML ingest downloads every remote image** into `output_dir/images/` and retargets the markdown ref to the local `images/<name>` path, so the vision pass can process HTML figures the same as any other format (mirrors the EPUB compensation). See `backends/_remote_images.py`.
  1. Each remote `![](http(s)://…/foo.png)` is downloaded once; the local name joins the URL path segments after the first `images/` component (`…/images/eq/gain.png` → `eq-gain.png`) to avoid basename collisions across sub-paths.
  2. A file already on disk is reused (no re-fetch); a download that fails (e.g. 403) keeps its remote URL so the ref still resolves in a browser.
- Toggle off with `PAGESPEAK_DOWNLOAD_REMOTE_IMAGES=0` (leaves refs as external URLs — the vision pass then can't see them). Per-request timeout: `PAGESPEAK_REMOTE_IMAGE_TIMEOUT_S` (default 30s).
- **Saved web-help exports** (HelpNDoc / DocBook-style) reference images by *relative path* into a sibling assets folder (`<img src="../Storage/…/foo.png">`), not by URL — so the remote-image downloader can't see them and you get zero images. If that assets folder wasn't shipped but the manual is published online, pass `--html-base-url <page-url>` (or `to_markdown(html_base_url=…)`): relative refs are resolved against it with `urljoin` and downloaded. Extension-less CDN refs (e.g. `googleusercontent.com/<token>`) are still skipped (no image suffix to detect).

### EPUB

- MarkItDown converts the spine's XHTML to markdown and emits real `![](..)` image references, but — unlike the office formats — it does **not** extract the embedded image binaries. Pagespeak compensates the same way it does for DOCX:
  1. Extract every embedded image from the EPUB zip (selected by image extension, since EPUB images sit at arbitrary in-zip paths like `OPS/images/` rather than a fixed `*/media/` prefix) into `output_dir/images/`.
  2. Retarget the markdown refs: MarkItDown writes them relative to the in-zip chapter location (`../images/..`), which is wrong once the markdown is flattened to a single file at the output root. Each ref whose basename matches an extracted image is rewritten to `images/<name>` so it resolves next to the `.md` and the vision pass can match it by basename.
- Inline typographic glyphs that an EPUB renders as tiny images (e.g. a `ũ` rendered as `utilde.jpg` mid-word) are extracted and captioned like any other image, which can inject a verbose caption into the middle of a word. Small-glyph filtering is not yet implemented — see [diagrams.md](diagrams.md) if this matters for a given source.

### Markdown / plain text (`.md`, `.markdown`)

- A markdown deliverable is *already* the pipeline's target format, so it is read **verbatim** into `<stem>.raw.md` rather than round-tripped through MarkItDown (which re-emits lists / headings / emphasis its own way — lossy). See `backends/_markdown.py`.
- No image extraction at ingest: a markdown source references images by path or URL already. Remote `![](http(s)://…)` URLs are pulled local in the **cleanup** phase (`localize_remote_images_in_markdown` — the same downloader the HTML path uses), then refs retargeted to `images/<name>` so the vision pass can see them. Toggle with `PAGESPEAK_DOWNLOAD_REMOTE_IMAGES=0`.
- Designed to finish an upstream ingester's output: the ingester acquires + source-normalizes content into clean markdown; pagespeak runs cleanup → normalize → repair → structure → vision → split over it. When the source's headings are already a clean `#`/`##` hierarchy (GitHub / GitBook / llms.txt markdown), skip `--normalize-headings`; a flattened source still benefits from it.
- Source-framework macros that aren't CommonMark (GitBook `{% hint %}`, MDX `<Note>`, `{{version}}` templates) pass through untouched — strip them upstream in the ingester if they're noise.

### Canvas QTI quiz exports

- Full guide: [canvas-quizzes.md](canvas-quizzes.md). Input is a directory containing `imsmanifest.xml` or a `.imscc`/`.zip` archive — detected (`backends/_qti.is_qti_export`) **before** directory-input mode so an export folder isn't mistaken for an output dir.
- The export fans out into one full-pipeline document per exam (each `<exam>/` has its own stage checkpoints + master doc + `images/` + a `sections/` per-question split with rich frontmatter), answers marked (`--no-answer-key` for blank). Questions are `## Question N` headings — edit-friendly and chunkable per question.
- Vision is **off by default** for QTI (figures are copied + linked with alt text); pass `--diagrams` to opt in. Classic Quizzes only — New Quizzes exports are not parsed.

### Top Hat quiz-export PDFs

- Full guide: [tophat-quizzes.md](tophat-quizzes.md). Opt in with `--pdf-backend tophat` — Marker and Docling both mangle these web-print PDFs (option-shredding / dropped questions), so the `tophat` backend reads the PDF **text layer** instead (clean in reading order) and promotes each `Question N` marker to a `## Question N` heading.
- Recipe: `--pdf-backend tophat --preset rag-default` → one file per question under `sections/`, with figures captioned by the vision pass ($0 on the default `claude_code` backend, phash-cached). Add `--no-diagrams` for a pure-text, zero-LLM run (figures still extracted + referenced, just not captioned). No `llm_full` needed — headings are already clean.
- **Answer key** is recovered when the export was taken after the due date (the correct option's grey letter is detected deterministically and marked with `✓` + a `**Correct answer:**` line). A before-due-date export has no answers and renders questions only. **Figures are extracted + captioned** by the vision pass — including questions that ARE a diagram (no text stem); leave vision on. Watch for **truncated** exports (lazy-load print clip) — the backend converts what's in the PDF, it can't recover omitted questions.
