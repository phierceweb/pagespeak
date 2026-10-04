# Changelog

Notable changes to pagespeak, newest first. The project is pre-1.0 — pin to a tagged release; `main` is the development line.

## 0.17.0

### Added
- **Word section numbers on numbered headings** (python-docx backend): a heading numbered through its style keeps the number Word shows for it (`### 2.1.3. Installation`), in the level's format (`1.1.`, `II.`, `b)`, legal numbering, start overrides, Word list styles), counted the way Word counts: an empty numbered heading or a numbered table cell still takes a number, lists built on one definition share a count, and a level not yet used shows one below its start (`0.1`, `1.0.1`). The split's `section_number` and breadcrumbs carry it. New modules `backends/_docx_numbering.py` and `backends/_docx_numpr.py`.

### Fixed
- **A nested numbered list in a document with no headings stays a list.** Cleanup rebuilt it as a Word outline, so each step became a body-less heading that the split dropped from `sections/`. The outline rebuild now needs the bullet marker stack (`* + 1.`) that MarkItDown, Pandoc and Docling write for a Word multilevel list; a Word outline without it gets headings from `--docx-backend python-docx --docx-outline-heading-depth N`.
- **A bullet whose text starts with a number no longer turns a document's numbered lists into headings.** One such bullet (`* 3. Setup`) passed for that marker stack, so cleanup rebuilt every nested numbered list in the document as headings and the split dropped the steps from `sections/`. A stack now counts only on an item numbered 1, where MarkItDown puts it, and the rebuild needs more of those than of other stacked items.
- **A document with no headings reaches `sections/`.** It split into nothing; it now lands whole in one `Front Matter` section, like any text before a first heading.
- **An escaped pipe (`\|`) in a table cell stays in its cell.** Cleanup split the cell on it, adding a column and leaving a stray `\`. The `audit` table checks and `repair-tables` read cells the same way and are fixed with it.
- **A Word heading numbered through its style stays a heading** (python-docx backend). Numbered-heading templates (`1.`, `1.1.`, `1.1.1.`) link `Heading 1`–`3` to a multilevel list on the style; since 0.13.0 those paragraphs converted to list items, so the document lost its chapter spine. A `Heading N` paragraph now takes its level from the style unless it is numbered on a list of its own; numbering that continues its style's list (Set Numbering Value, Restart Numbering) keeps it a heading.
- **A Word paragraph with its numbering switched off is no longer a list item** (python-docx backend). Word writes `numId` 0 on a paragraph, or on a style such as `TOC Heading`, to turn its numbering off; the reader read it as a list, so an unnumbered heading such as a document's `Table of Contents` became a `1.` item and empty ones left bare `1.` lines.
- **A paragraph's list and level inherit separately** (python-docx backend). A paragraph that sets only a level keeps its style's list at that level, and one that names only a list takes its style's level; the reader ignored a paragraph's numbering unless it set both. A list style deep in a `basedOn` chain is no longer sometimes missed, which folded its items into the one before.
- **A list defined through a Word list style keeps its format** (python-docx backend). A `w:numStyleLink` list read as numbered whatever its format, so its bullets became `1.` items.
- **Underscores survive in DOCX headings** (python-docx backend). The heading emphasis strip removed every `_`, so `MAX_RETRY_COUNT` read `MAXRETRYCOUNT` and fill-in blanks vanished. The reader marks emphasis with `*` only.

### Changed
- Requires `pf-core ~=0.25.0`.

## 0.16.1

### Security
- **Images are decoded only when they are PNG, JPEG, GIF, BMP, TIFF or WebP.** pagespeak requires pf-core 0.24.1, whose `compute_phash` judges an image by its content and refuses anything else before Pillow decodes it, so a crafted image in a document no longer reaches the PSD, FITS, McIdas or JPEG 2000 decoders of the `pdf` extra's Pillow 10.4. Deduplication skips a refused image and the vision pass cannot cache it, so each vision run sends it again. Images the PDF backends extract are re-encoded to PNG or JPEG and are unaffected.

## 0.16.0

### Added
- **`pagespeak ingest` writes its settings into `.pagespeak-run.json`**, merged into an existing record. `convert <out_dir>` inherits them and carries the source identity forward. The settings that produced `raw.md` sit in an `ingest_flags` block that only a run writing `raw.md` changes; every other run keeps it and records its values as its ingest settings.
- **`audit` flags extraction damage a backend leaves at exit 0.** `collapsed_code_blocks` (every fenced code block in the document is one line), `unclosed_code_fence` (a fence never closed, so the rest of the file renders as code) and `formula_glyph_codes` (math emitted as `n01`-style glyph codes) read the master file. `--text-coverage` compares each document with its source PDF's text layer — the share of the PDF's distinct words that reached `raw.md`, flagged below `PAGESPEAK_AUDIT_MIN_TEXT_COVERAGE_PCT` (default 90) with the pages whose words mostly never arrived. It takes document folders; the source is `--source <pdf>` for one document's folder, or auto-located in `--in-dir`. A source that cannot be read as a PDF is reported as a warning.
- **Web console request guards.** A request whose `Host` is not loopback, the bind host or listed in `PAGESPEAK_WEB_ALLOWED_HOSTS` gets a 403 (DNS rebinding). A write a browser marks as cross-site (`Sec-Fetch-Site`, or an `Origin` other than the host) gets a 403, so a page on another site cannot queue a conversion. A body over `PAGESPEAK_WEB_MAX_UPLOAD_BYTES` (default 512 MiB) gets a 413, counted as it arrives when the request has no `Content-Length`. Host names match case-insensitively. Binding beyond loopback logs `web_console_exposed` at startup.
- **The web console's preview no longer runs document scripts.** Every page carries a nonce-based Content-Security-Policy: `<script>` tags, inline event handlers, `javascript:` links, frames and remote images in a converted document stay inert. Responses also send `X-Content-Type-Options: nosniff`, and error text echoed into console fragments is HTML-escaped.
- **Zip-based inputs are read under a decompressed-size cap.** Office and EPUB media and Canvas `.imscc` exports stop with an error past `PAGESPEAK_MAX_ARCHIVE_BYTES` (default 1 GiB), counted as bytes inflate. Media members stream to disk instead of being read whole into memory. A Canvas export is unpacked member by member: a member path outside the extraction folder is refused, symlink members are skipped, and a refused archive leaves no temp folder.

### Changed
- **Relicensed to Apache-2.0** (was MIT). Releases through 0.15.0 stay under MIT; the change applies from this release forward.
- A `NOTICE` file names the copyright holder and ships in the package beside `LICENSE`. Building the package needs `setuptools>=77`.
- **`pagespeak[pdf]` requires `marker-pdf<2`**, and the Marker backend refuses a 2.x install at run time with an `ImportError`. Under pagespeak, Marker 2.0 converted only a document's first pages and exited 0.
- Publishing a release now waits for the lint, type, structure and test gates, and fails when the tag does not match the package version.
- Backend guidance corrected across the README, docs, CLI help and web console. Docling without `--heading-hierarchy` puts every heading at one level (not two); with it, levels come from the PDF's bookmarks, numbering and font style. Docling is faster than Marker on CPU, collapses multi-line code blocks to one line, and emits formulas as glyph codes unless `do_formula_enrichment` is set. `llm_full` can remove a false heading, not only re-level it. The README no longer says the split has no size limit (`--split-target-kb`). `choosing-defaults.md` gains a Docling `--heading-hierarchy` recipe for PDFs with a bookmark outline.
- **A heading-normalize response that covers too few headings is not applied.** In `llm` / `llm_full`, a response levelling fewer than `PAGESPEAK_NORMALIZE_MIN_COVERAGE_PCT` of the headings leaves every heading at its extracted level and logs `heading_normalize_low_coverage`. A drop the guards refuse counts as answered. The refused response stays cached: the warning says `source=cache` when a later run replays it and names `--rerun-from normalize`, which asks again.
- A heading whose text opens with `|` is demoted back to its table row in cleanup (`cleanup_demoted_table_row_headings`), outline documents included.
- The splitter logs each section it drops for an empty body by title (`split_empty_section_dropped`).
- `vision-audit` reports how many captioned figures it skipped and says when nothing could be assessed. Word's `Description automatically generated` alt suffix no longer counts as a subject.
- Every document the pipeline writes — stage checkpoints, per-chunk `raw.md`, the master `.md` — is written atomically.
- The `claude_code` vision backend passes `--tools Read`, so the model can open the image under pf-core 0.23, which loads no tools unless named.
- CI resolves every extra together (`pip install --dry-run`) on each push and before publishing, so a dependency conflict in any extra fails the build.
- `bin/setup` keeps a venv with marker-pdf on Pillow 12.3, over Marker's `<11` pin.

### Fixed
- **A `--workers N` conversion recorded the default backend.** The run record said `pdf_backend=marker, heading_hierarchy=false` whatever ran, so the next inheriting `--rerun-from ingest` switched engines.
- **Resuming from `<stem>.raw.md` ignored the ingest settings.** A run asking for another backend, page range or OCR mode — or the whole document after a `--max-pages` trial — got the earlier run's content at exit 0. When the run record says the checkpoint was ingested differently, the run now stops with an error naming each difference. The ingest phase stamps its settings into the record as soon as `raw.md` is written, so a run that fails later still leaves a matching record. An older record written by a run over the output dir holds default settings, so only what ingest left behind is compared there: each chunk's backend and the Docling outline marker.
- **A changed chunk plan duplicated pages.** A `--max-pages` trial or another `--chunk-pages` followed by a full chunked ingest into the same directory concatenated the overlapping chunks. Completed chunks outside the current plan are shelved (`chunk_plan_changed`): kept out of `raw.md` and `images/`, and restored when a later plan uses the same pages instead of reading them again.
- **`pagespeak ingest --max-pages` without `--workers` converted the whole document.** It now converts the first N pages on the single-process path too, and is refused where it cannot apply: a non-PDF source, the `tophat` backend, or alongside `page_range`.
- **A chunked resume reused chunks read with other settings.** Each chunk records the backend, `force_ocr`, backend kwargs and (under Docling) `heading_hierarchy` it was read with; resuming with different ones stops with an error naming each difference.
- `--normalize-headings-backend` did not reach `llm_dehead`, and the `llm_dehead` payload gate read `llm_full`'s `max_input_tokens`.
- Mermaid fences in split section files kept the master's `pagespeak-image="images/…"` path, which dangled from `sections/`. It is rewritten relative to the section file.
- The web console's cost gate counted cached images as free for a `rerun_from=vision` job, which deletes the cache before it runs.
- `--vision-model` help said the flag was ignored under `claude_code`; the `qti` preset row showed the generic split as on; `.env.example` lacked the `llm_dehead` backend and the model-router / prompt-override variables.
- The web console's `docling` PDF-reader choice submitted its label text instead of the backend name, so the job failed on an invalid backend. It now runs Docling with `--heading-hierarchy`, and choosing another reader for a document already read reads it again (`--rerun-from ingest`); with workers above 1 the change is refused with a message.
- **A console upload could write through a staged symlink** in `conversions/in/`, overwriting the file it pointed to. An upload is now refused when that name is a symlink or folder, refused when it is not a plain file name, and swapped in only once complete.
- **Marker left Pillow's decompression-bomb limit off for the rest of the process.** It is lifted only while Marker renders pages and restored afterwards, so later image reads in the same run, directory batch or console worker are checked again.
- **`pagespeak[pdf]` failed to install** (`ResolutionImpossible`): marker-pdf requires Pillow below 11, and pf-core's `image-phash` extra requires 12.3 or later. ImageHash and Pillow are now direct dependencies (`Pillow>=10.4`) instead of that extra, so the `pdf` extra installs Pillow 10.4 — see SECURITY.md for what that means for untrusted documents.

## 0.15.0

### Added
- **`audit` check `broken_image_ref`** (error). Flags an image ref whose alt breaks it, so `parse_image_refs` reads nothing. Nothing else could report it: an unparsed ref is skipped by every later pass, and `dangling_image_ref` is parser-gated, so it cannot see one either. Fires only where collapsing whitespace would repair the ref, so `!` before a bracket in code and CommonMark shortcut reference images stay clean; fence- and inline-code-aware.
- **`--min-body-chars` on `convert`.** Sets the split's minimum section body size (default 30, `DEFAULT_MIN_BODY_CHARS`). `0` keeps every section, heading-only ones included — for a document whose empty headings are placeholders to fill in later. The value was already accepted by `to_markdown` and inherited from the run record, but had no flag.
- **Heading-normalize reports short LLM responses.** The `llm` and `llm_full` modes log `heading_normalize_low_coverage` when a response levels fewer than `PAGESPEAK_NORMALIZE_MIN_COVERAGE_PCT` (default 90) of the headings it was given; un-covered headings keep their extracted level. Not applied to `llm_dehead`, where an absent verdict means KEEP.
- **Vision responses are validated and recorded.** A registered validator pipeline writes one signal per vision call to `llm_run_validations` (empty caption; `is_diagram` set with no mermaid). Observability only — the emitted markdown is unchanged.
- `invoke_agent` returns `AgentResult(content, run_id, usage)`, carrying `finish_reason` through to callers.

### Fixed
- **A shorter fence no longer closes a longer one.** `fence_flags` compared only the delimiter character, so a ``` inside a ```` block ended it and the sample leaked out as prose to every fence-aware pass — `check_html_fragment`, `check_html_entity`, `check_shattered_emphasis`, `check_duplicate_heading`, `broken_image_ref`, and the TOC / `transform_outside_fences` passes. CommonMark's rule (the closer must match the character and be at least as long) is now applied. Affects documents that show fenced markdown by wrapping it in a longer fence. A fence left unclosed at end of file now logs `fence_unclosed_at_eof` with the opener's line and how many lines it renders inert — under the old leniency a shorter delimiter would accidentally have terminated it.
- **An image target may contain balanced parentheses.** `_scan_destination` stopped at the first `)`, so `![Fig](images/fig_(1).png)` parsed to the target `images/fig_(1` and leaked `).png)` into prose — it still parsed, so no check reported the corruption. Backslash-escaped parens are not counted; angle-wrapped targets are unaffected.
- **Multi-line image alt no longer voids the ref.** Word writes auto-generated alt as `<subject>` + blank line + `Description automatically generated`. The blank line ends the alt scan in `parse_image_refs`, so the ref parsed as nothing and every later pass skipped the image — including the vision pass, which still made (and paid for) the LLM call, then had no ref to inject its caption and mermaid into. Alt is flattened to one line at both sites that construct a ref: the structure-faithful DOCX backend, and `utils/_html.py` (reached by Canvas QTI stems and by the cleanup phase's embedded-`<img>` conversion, so it affected every backend). New `utils/_alt.flatten_alt`; the parser is unchanged.
- `--rerun-from`, `--from` / `--stop-after`, and the `to_markdown` docstring all omitted the `repair` and `structure` stages.
- `--normalize-headings-model` help named a hardcoded default that the model router overrides; the text is now derived from the router, naming each mode's actual model.

### Changed
- **Heading-normalize `max_input_tokens` on `claude_code` raised 800K → 900K** for `heading_normalize_full` and `heading_normalize_dehead`, matching the openrouter entries for the same Opus model. Documents between the two figures now keep their body anchors instead of falling back to headings-only.
- Requires `pf-core ~=0.22.0`.

## 0.14.0

### Changed
- **Python 3.12 is now the minimum.** 3.11 is dropped; `pf-core` 0.20 requires 3.12.
- **Image-ref parsing is linear inside a blank-line-free block.** Each ref scanned ahead to the end of its paragraph; in a table with an image per row there is no blank line to stop at, so a 2,000-row table took ~4.3s. Now ~6ms.
- **Decoration detection hashes each image once**, clustering the same hashes at both radii instead of re-reading and re-decoding every image for the second one.
- **`anthropic` is capped below 1.0** — that release removed `temperature` / `top_p` / `top_k` from `messages.create()`, which pf-core's client sends by default.

### Fixed
- **Decoration stripping no longer deletes content figures.** The phash-clustering pass removed every ref in a cluster, so distinct figures that share a fingerprint — schematic line art, equations rendered as text on white — were deleted alongside real page furniture. Removal is now gated on the image being a near-exact duplicate (`EXACT_DUPLICATE_HAMMING_DISTANCE`); a merely-similar ref keeps its description as an italic caption, or is left alone when it has none. `DEFAULT_PHASH_HAMMING_DISTANCE` is unchanged. The pass runs inside cleanup, where PDF refs are still alt-less, so on the PDF path the near-exact gate is what decides removal. To recover figures a previous conversion deleted: `pagespeak convert <outdir> --from cleanup --vision-cache-only` (rebuilds from the untouched `raw.md`, no LLM call). See [docs/pipeline-decorations.md](docs/pipeline-decorations.md).

- **One image-ref parser, shared by every pass that scans them.** Each pass carried its own `![alt](target)` regex that stopped at the first `]` in the alt text, so a figure whose description contains a bracket was invisible to it: the audit reported dead links as clean, ingest never copied the file, the splitter never rewrote its path, and the vision pass never captioned it. Several also folded a CommonMark title into the destination, inventing dangling-ref findings for images that were present. `services/_image_refs.py` now exposes `parse_image_refs` / `replace_image_refs` / `ImageRef.retargeted`; `_audit`, `_decorations`, `_local_images`, `_split_write`, `_vision_inject`, `_chunk_rewrite`, `backends/_pdf` and `backends/_docx` all use it.

- **Cleanup no longer creates emphasis shatter.** Promoting a lone first-row table cell to a bold caption wrapped a cell that already carried emphasis, producing `****text****`. A caption that is one bold run is left as is; one with several (`**Table 1** Results`) is flattened into a single run.

- **Doubly-escaped HTML entities decode fully.** `html.unescape` is single-pass, so a source whose entities were escaped twice shipped visible `&lt;…&gt;` debris. Cleanup now decodes to a bounded fixpoint, still outside fenced code.

- **`--workers N --rerun-from <stage>` no longer strips the output dir.** The chunked ingest ran to completion, then Phase 3 re-entered in directory mode and invalidated the `ingest` stage — deleting the `raw.md`, `images/`, `chunks/` and `manifest.json` it had just written — and aborted on the missing `raw.md`, leaving only the master `.md` behind. The combination is now refused up front, before any backend work.

- **The auto-baseline is taken before cache invalidation, not after.** Every stage is upstream of `split`, so any `--rerun-from` removed `sections/` first, and the snapshot then skipped itself for having no sections — so the destructive re-run that most needs the previous version preserved was the one run that never got a `.baselines/<version>/` copy.

- **The chunked-parallel path no longer discards options it cannot honour.** `workers > 1` routes ingest through the chunked path and re-enters Phase 3 in directory mode, which silently dropped `--page-range`, `--english-only` and `--repair-tables` — exit 0, no warning. `--english-only` is now carried through; `--page-range` and `--repair-tables` raise, because the re-entry's source is the concatenated `raw.md` and neither can be applied to it (use `pagespeak repair-tables` on the output dir instead). An env-derived worker count still clamps to 1 rather than erroring.

- **`--heading-hierarchy` survives a chunked ingest.** Only the single-process path stamped `.pagespeak-hierarchy.json`, so `--pdf-backend docling --heading-hierarchy --workers N` lost the outline-derived signal that stands the later heading passes down, and the levels read from the PDF's bookmarks were re-guessed.

- **`--workers 0` names the flag, not the environment.** The error came from the env-var resolver behind it (`PAGESPEAK_WORKERS arg must be >= 1`) and escaped `pagespeak ingest` as an unhandled traceback; `ingest` now reports `ValueError` the way `convert` does.

- **`PAGESPEAK_CHUNK_PAGES` now reaches `pagespeak ingest`.** Its `--chunk-pages` default was hardcoded to 50, so the orchestrator's resolver never saw the `None` that lets the env value through — `convert` already honoured it.

- **An ambient worker count no longer chunks a Top Hat export.** The backend reads the whole export in one pass and ignores page ranges, so chunking it duplicated every question.

- **The web console's worker count is no longer overridable by the environment.** A job requesting single-process omitted `--workers` entirely, so the subprocess picked up an ambient `PAGESPEAK_WORKERS` and the console had no way to say "no, 1". The flag is now always emitted.

- **`PAGESPEAK_WORKERS` now reaches the CLI.** `convert` and `ingest` both hardcoded a `--workers` default of 1, so the documented env var was never read. An explicit `--workers` still wins and is never clamped. An env-derived value is clamped to 1 for anything the chunked-parallel path cannot serve faithfully — a non-PDF source, a directory, a QTI export, or a run passing `--from` / `--stop-after` / `--rerun-from` / `--page-range` / `--english-only` / `--repair-tables`. That path re-ingests from its own manifest rather than resuming from `<stem>.raw.md`, so without the clamp an ambient setting would turn a cheap phase-slice re-run into a full backend re-ingest and silently drop those options. A clamp logs `cli_workers_env_clamped` at INFO.

## 0.13.0

### Added
- **`--heading-hierarchy` (Docling PDF only)** — infers real heading levels from PDF bookmarks, then section numbering, then font style, instead of Docling's flat single-level output. Off by default; recorded in `.pagespeak-run.json` and inherited on re-run. Available on `convert` and `ingest`, as `heading_hierarchy=` on `to_markdown()`/`chunk()`, and threaded through the chunked-parallel worker path. Helps documents with an embedded outline or `Section N.`/`N.M` numbering; not a win where neither signal is present. It assigns levels only — it never demotes a heading. New module `backends/_docling_headings.py`. See [docs/backends.md](docs/backends.md).

- **`--normalize-headings-mode llm_dehead`** — a de-headification-only normalize mode. Same payload as `llm_full`, but it asks one question per heading (is this a real section?) and **never reassigns a level**. For a document whose hierarchy the backend already read correctly, re-levelling risks regressing a good tree while junk removal is the part no deterministic pass can do. A heading that owns child headings is never dropped — junk is always a leaf.

### Fixed
- **A hierarchy the source itself stated is no longer re-guessed — in any phase.** Cleanup demoted headings on PDFs whose levels came from the bookmark outline (its gate read a marker key only the DOCX reader ever sets) and on headings the structure-faithful DOCX reader read from the file; `to_markdown(..., output_dir=None)` lost the claim entirely because both repair and structure read only the on-disk marker. All three now share one trust signal, recorded at ingest in `.pagespeak-hierarchy.json` and cleared by `--rerun-from ingest`.

- **…but a broken outline is no longer preserved either.** `route_authoritative_hierarchy` treated *outline-derived* as *correct*, downgrading `llm_full` to `llm_dehead` — a mode that by definition never changes a level — so an outline rendered with a tier missing throughout kept that break through every later pass. The downgrade now also requires the tree to be coherent: no tier unused inside its range, tier-skipping descents under `PAGESPEAK_OUTLINE_TRUST_MAX_SKIP_RATE` (default 0.10).

- **`llm_dehead` now runs on the model its own router block declares.** `_resolve_model` knew only `llm` and `llm_full`, so dehead fell through to the `heading_normalize` entry — and that name is passed as `model_override`, which outranks the agent slug's config. The mode ran on another mode's model and stamped it into its cache key.

- **Images carrying a CommonMark title (`![alt](img.png "Title")`) survive.** The title was folded into the destination, so the path could never resolve: the file was never copied into the output dir and the always-on degrade pass then rewrote the live ref to an italic caption — the figure vanished with an exit 0 and no warning. Angle-bracketed destinations failed the same way.

- **`regenerate_toc` no longer deletes the document body.** The block boundary reused the `#{1,4}` *entry-depth* cap, so a section headed H5/H6 could not terminate the TOC block and the replacement swallowed every remaining line.

- **Fenced code is no longer edited by passes that scan for headings.** A `#` inside a fence was read as a heading by `regenerate_toc`, the heading-repair passes, `--split-target-kb` block partitioning, `audit` and `repair-tables` — each carrying its own fence detector, several backtick-only. A markdown-about-markdown fence, a shell script or a C header had its content silently rewritten and each edit counted as a legitimate repair. All now share `services/_fences`, enforced by a sweep test.

- **The splitter no longer drops a section whose heading merely looks like a TOC entry.** A chapter-review summary restating its subsection with a page back-reference, or a real title ending in a number (`2.4 IEEE 802.11`), matched the TOC-phantom shape and was pruned with every descendant. Dropping now also requires an empty subtree, and each drop is logged.

- **The structure-faithful DOCX reader carries more of the author's structure.** Body-level content controls (`w:sdt` wrapping paragraphs or a table) were skipped entirely; numbering carried by a paragraph style rather than the paragraph was ignored, fusing a whole numbered list into one run-on paragraph; consecutive body paragraphs were emitted on adjacent lines, which CommonMark reads as a single paragraph; and a bullet parent did not restart its nested numbered list.

- **Heading numbering is read more faithfully on both PDF backends.** A section number split into separate tokens (`## 1 . Title`) defeated the numbered-heading regex; the single-dot listish demote fired on real sections whenever plain `N.` lines outnumbered heading-form ones anywhere in the document; a bare-integer chapter was never levelled and read as a bodiless shell above its own `N.M` children; and `<Word> N. <Title>` tripped the prose-demote's sentence test.

### Changed
- **A Word `Heading N` paragraph restarts list numbering** in the structure-faithful DOCX reader, matching what an outline-level heading already did — the one place the reader knowingly diverges from Word, because a continued number under re-based nesting reads as an orphan and gets treated as a numbering artefact.
- `pagespeak[pdf-docling]` now requires `docling>=2.109` (was `>=2.0`). A bare `>=2.0` resolved to a pre-feature release where `--heading-hierarchy` silently degraded to flat levels.

## 0.12.0

### Changed
- **Remote-image download runs on pf-core's fetch core** (`pf_core.fetch.images`; floor raised to `~=0.13.0`). `backends/_remote_images.py` is now a policy wrapper: `PAGESPEAK_DOWNLOAD_REMOTE_IMAGES`, `PAGESPEAK_REMOTE_IMAGE_TIMEOUT_S`, `PAGESPEAK_REMOTE_IMAGE_MAX_BYTES`, and the on-disk filenames are unchanged. New behavior inherited: a failed fetch is retried (5xx / 429 / network — permanent 4xx still fails fast), the size cap aborts mid-read instead of after the full download, `<img src="http…">` tags are localized alongside markdown refs, and the SSRF address check now has an opt-out (pf-core's `URL_FETCH_ALLOW_PRIVATE=1` — see [SECURITY.md](SECURITY.md)). Per-image failures log as `image_localize_failed`.
- `httpx` is no longer a direct dependency (no module imports it); it still arrives via `pf-core[llm]`.

## 0.11.0

### Added
- **Cleanup converts well-formed embedded HTML blocks to markdown.** A raw `<table>` of real content or a `<figure><img>`/`<img>` block left in prose by the backend becomes a pipe table / markdown image (via the existing `utils/_html.py` converter). Narrow by design: only line-anchored, balanced blocks outside fenced code; tag soup and mid-line tag mentions are untouched. New module `services/_cleanup_html.py`.

### Fixed
- **The `shattered_emphasis` audit no longer flags bold-wrapped inline code.** Blanking a `` `code` `` span to the empty string fused surrounding `**` markers into `****`, flagging clean prose; spans now blank to a spacer. Corpus findings drop from 697 to 39 — the remainder are real.
- **A quiz re-render clears its prior question files.** Re-exporting a quiz with fewer questions left the surplus `Question NNN.md` files from the previous render on disk (stale content, still delivered), and a stale case-variant file could capture a fresh write's name on a case-insensitive filesystem. The per-question writer now clears the sections dir before writing, same as the generic splitter.
- **A decoration-only preamble no longer becomes its own section.** A document whose only pre-heading content is imagery (a cover logo) or empty-link debris got a `Front Matter` section containing just that — a junk retrievable chunk. Such a preamble now folds into the first section; a preamble carrying prose (title page, copyright, abstract) still gets its own `Front Matter`. Re-split to apply.

## 0.10.0

### Fixed
- **Measurement headings are no longer parsed as section numbers in min-level split mode.** `## 6.3 mm stereo jack plug` became section `6.3` titled "mm stereo jack plug", stamping a false `section_number` and a `6.3/` folder in nested mode; it is now an unnumbered section. Numbered headings (`## 1.4 Configuration`) are unaffected. Re-split to apply.
- **A heading whose body is a link list no longer parents sections.** Content headings one level below a `## Table of Contents` nested beneath it. Such children are re-attached to the contents heading's own parent, in document order; the contents section itself is kept. Logged as `split_promoted_nav_list_children`. Re-split to apply.

## 0.9.0

### Fixed
- **Split no longer drops content before the first heading.** Anything preceding the document's first heading — title page, copyright, cover image, abstract — belonged to no section and was discarded; it now becomes a leading `Front Matter` section. Inserted after parsing, so it never becomes a parent and no existing section's path or `section_id` changes; `min_body_chars` still drops a trivial preamble.
- **Split no longer drops the body of a heading above `--split-min-level`.** Such a heading was context-only — it shaped the folder path and breadcrumb but was never written — so any prose sitting directly under it was lost, and a chapter with no subheadings disappeared outright. A heading above `min_level` is now written **iff it carries its own body**; a bare page title stays context-only as before. Additive: no section file is renamed or removed. Children of a newly written heading gain a `parent_id` where they previously had none (they already lived in that chapter's folder).

### Changed
- **Section files and folders are slugified**: lowercased, each run of non-alphanumerics collapsed to one `-` (`Foot Switches (1)` → `foot-switches-1.md`); Unicode letters preserved, alphanumeric-free titles fall back to `section.md`. Filenames, `section_id`, and in-document link targets now match the key normalization RAG stores apply to paths, so a link copied out of a chunk resolves without rewriting. Titles differing only in case now collide and are separated by the existing numeric-suffix resolver. Re-splitting an existing output dir renames every section file.
- Nav-link targets are no longer angle-wrapped (`[x](<a b.md>)`) — slugs cannot contain a space or paren. The generic splitter's wrapping branch is removed; the quiz writer, whose `Question NNN.md` filenames keep spaces, still wraps.
- The conversion worker runs on pf-core's jobs runtime (floor raised to `~=0.11.0`): `web/_worker.py` is now a `SubprocessJobSpec` (argv/log-path/outputs) over `pf_core.jobs.workers`. New behavior inherited: stale-lease reclaim at startup (jobs stranded `running` by a killed worker re-enter the queue), cancel escalates SIGTERM→SIGKILL across the child's process group, and the poll cadence is tunable via `JOB_POLL_SECONDS`. Job rows, log locations, `PAGESPEAK_JOB_ID`, and the queue/detail UI are unchanged.

## 0.8.0

### Changed
- `source_id_from_name` uses pf-core's `slugify` (floor raised to `~=0.9.0`). ASCII filenames slug identically; accented names fold to ASCII (`Café Guide.pdf` → `cafe-guide`). Existing conversions keep their recorded ids; only a fresh conversion of a non-ASCII-named source mints a new id.

## 0.7.0

### Changed
- **Local pipeline sequencer retired.** `orchestrators/_sequencer.py` deleted; `to_markdown` runs the phases via `pf_core.pipeline.sequencer.run_pipeline`, with resume freshness injected as a `skip_fresh` closure over each phase's `is_fresh`. Slice semantics (`--from` / `--stop-after` / `--rerun-from` / resume-skip) unchanged.
- **Agent config + LLM call plumbing retired onto pf-core.** `_agent_config.py` deleted; `config/model_router.yaml` is read by `pf_core.llm.router` (new top-level keys: `env_prefix: PAGESPEAK`, `default_client: claude_code`, `non_chat_keys: [max_input_tokens]`). `_agent_runtime.py` is now a thin seam: `invoke_agent` records through `tracked_messages_call` (run rows, prompt registration, tags/metrics split, failure rows), and pf-core's ContextVar recording window replaces the module-global call accumulator — vision-pass workers join it via `contextvars.copy_context()` at the pool fan-out. `.pagespeak-run.json`'s `llm_calls` schema is unchanged.
- **Config errors fail fast.** An unknown agent slug, or a `MODEL_ROUTER_CONFIG` pointing at a missing/malformed file, now raises `ConfigurationError` instead of silently falling back to a hardcoded model. Wheel installs without any config still work: the seam points the router at the bundled `model_router.yaml`. YAML edits hot-reload within `MODEL_ROUTER_RELOAD_SECONDS` (default 60).
- **`PAGESPEAK_<TASK>_BACKEND` env values are case-sensitive and no longer raise on an unknown value** — a value that doesn't name a declared backend falls back to the YAML `default_client` (`claude_code`).
- **pf-core floor: `~=0.8.0`** (sequencer / router / tracked-call / recording APIs). Retroactive note: v0.5.1 had already raised the floor to `~=0.6.0` without a changelog entry.

## 0.6.0

### Changed
- **Re-runs inherit the previous run's flags from the run record.** When `convert` targets an output dir holding a `.pagespeak-run.json`, every output-shaping flag not passed on the command line defaults to that record's `resolved_flags`, and the command echoes one `defaults inherited from .pagespeak-run.json: …` line naming what it took. A bare `--rerun-from <stage>` therefore rebuilds the structural outputs it deletes (`sections/` with its `INDEX.md`) in the original shape, instead of silently dropping them because `--split-sections` defaults to off. Explicit flags win; an explicit `--preset` wins over the record for the preset-controlled flags; `--no-inherit` restores bare-defaults semantics. LLM/engine/runtime selection (`--diagrams`, `--vision-*`, `--normalize-headings-model`, `--device`) never inherits — engine choice and spend stay per-invocation decisions. An invalid recorded value fails loudly naming the record; a missing or corrupt record inherits nothing. See docs/caching.md § "Re-run flag inheritance".

### Added
- **`--no-` forms for the inheritable single-form switches** — `--no-split-sections`, `--no-nested-split`, `--no-english-only`, `--no-repair-tables`, `--no-force-ocr` — so an inherited `true` is overridable per flag.
- The run record's `resolved_flags` now also captures `english_only`, `docx_backend`, and `docx_outline_heading_depth`.
- Library: `read_run_record()` in `services/_run_record.py` — defensive reader (`None` on missing/corrupt/non-object), shared by provenance recovery and flag inheritance.
- A model switch served entirely from the vision cache is now surfaced: when cache hits were recorded under a different model than the active one, the vision pass logs one aggregate `vision_cache_model_mismatch` warning with a `--rerun-from vision` hint. Log-only — phash-keyed reuse is unchanged.

## 0.5.4

### Fixed
- Web console: the `structure` phase now appears in the checkpoint viewer and the help-page phase table (the route already served it).

## 0.5.3

### Fixed
- **Docs re-synced to the seven-phase pipeline.** Corrected vision's input checkpoint (`structured.md`, not `repaired.md`) and every stage/checkpoint enumeration that omitted `structure`; refreshed stale checkpoint filenames (including the removed `pre-normalize.md` snapshot — heading-normalize review/revert is now documented against `cleaned.md`/`normalized.md`); completed `docs/architecture.md`'s module tables (all eight CLI subcommands, ~40 missing modules, a new `prompts/` section, two mis-pathed rows); labeled vision cost/latency figures as operating estimates and documented the model-switch × phash-cache interaction (`--rerun-from vision` to re-analyse under a different model).

### Added
- **Docs-drift guard** (`tests/test_docs_sync.py`): phase lists, stage sequences, checkpoint chains, `consumed by` notes, and the architecture module inventory are verified against `build_phases()` and the stage registry — a pipeline change now fails the suite naming each stale doc.

## 0.5.2

### Changed
- README carries a PyPI version badge and its doc/`SECURITY.md` links are now absolute `github.com/phierceweb/pagespeak/blob/main/...` URLs, so they resolve on the PyPI project page (relative links there 404).

## 0.5.1

### Changed
- Prompt specs load through pf-core's `load_prompt`: `prompts._loader.load_pagespeak_spec(slug)` replaces `resolve_prompt_path` (same override chain — `$PAGESPEAK_PROMPTS_DIR` → CWD `config/prompts/` → bundled default).
- Tracking-resolver imports use the public `pf_core.llm.tracking` surface instead of the private `_resolvers` module.

## 0.5.0

### Fixed
- **`claude_code` calls run isolated (`--safe-mode`) — required via the pf-core 0.5 floor.** pf-core's `ClaudeCodeClient` runs every `claude --print` subprocess with `--safe-mode` by default, so a conversion no longer auto-loads the working directory's `CLAUDE.md`, skills, or hooks — ambient context that could hijack a weak model into emitting skill text where an image caption (or normalized headings) belong. pagespeak's dependency floor rises to `pf-core ~= 0.5.0` (the old `~= 0.4.1` floor admitted un-isolated versions), pinned by a canary test on the `isolate=True` default.
- **`to_markdown()` now writes the final `<stem>.md` master itself.** The write was CLI-only, so a library consumer (or a split-only re-run driven through the library) produced sections and checkpoints but no master document. The library now owns the write — same guard as before: an early `stop_after` never clobbers the final document with an intermediate checkpoint.

### Added
- **Local sibling images are copied into the output during ingest.** An HTML bundle (saved webpage / doc-site export) ships the document plus a sibling `images/` dir with relative refs; nothing copied those files into the output, so the vision pass — which only reads `<out>/images/` — reported zero images and every figure was lost to captioning. HTML/markdown ingest now copies each locally-resolvable ref into `<out>/images/` (retargeting non-canonical refs to a flat collision-resistant name), the local counterpart of the existing remote-image download. Traversal-guarded: a ref escaping the source's own directory is ignored. Gated by `PAGESPEAK_COPY_LOCAL_IMAGES` (default on).

## 0.4.0

### Fixed
- **A `--vision-cache-only` skip no longer replaces the figure's authored alt with a placeholder.** An uncached image used to get `(no cached description; skipped under --vision-cache-only)` injected as its alt text — shipping a placeholder as content and destroying the source's own description on every skipped figure. A skip now produces no injection at all: the figure keeps its authored alt verbatim (the skip list is still logged via `vision_cache_only_skipped`). Same principle as the v0.2.1 failed-call fix: placeholders never ship as content.
- **The splitter's measurement-heading guard now also rejects uppercase-initial units.** A heading like `### 6.3 Hz notch`, `### 48 V phantom supply`, or `#### 2.4 GHz band` was mis-parsed as section number 6.3 / 48 / 2.4 (the existing guard only caught lowercase-initial units like `mm`/`ohm`), which spawned bogus numeric folders and could mis-nest unrelated sections under a false parent. A curated, word-boundaried unit whitelist (`Hz`/`V`/`GHz`/`W`/`Pa`/`Ω`/…) now catches these while leaving real Title-Case sections (`### 2.6 Vacuum Systems`, `### 3.2 Wireless Setup`) untouched.
- **A directory-mode re-run no longer degrades `source_file` to the `<stem>.md` fallback.** When the run record knows the original source (its persisted identity, or a file-mode record), the opt-in `source_file` provenance field and the `INDEX.md` source name keep the true filename across re-tags instead of being overwritten with the master-doc name.

### Added
- **Every split section now carries `source_id` + `source_sha256` — always-on source identity.** `source_id` is a stable slug of the source filename (constant however the out-dir is named — the cross-conversion join key for one source work); `source_sha256` is the SHA-256 of the exact source bytes the conversion ran on. Together they complete the identity block: a retrieved chunk can name its source work and version even when within-book hierarchy degrades, and a multi-source consumer can scope by work instead of by out-dir name. Resolved from the input file directly; in directory mode recovered from the out-dir's run record — which now persists a durable `source_identity` block that every dir-mode re-run carries forward, so identity survives any number of re-runs (and a pre-existing record without the block upgrades on its next run). Omitted, never guessed, when genuinely unrecoverable. Library note: `split_into_sections()` gained optional `source_id=` / `source_sha256=` passthrough kwargs.

## 0.3.1

### Fixed
- **Notation-dense equations with two-sided scripts and delimiters no longer flatten.** The presentation-MathML→LaTeX pre-pass (HTML ingest) now handles three more elements: `msubsup` (a base carrying **both** a subscript and a superscript — an integral's limits, an indexed-and-powered variable), `munderover` (an operator carrying **both** a lower and an upper limit — a summation/product), and `mfenced` (a delimiter wrapper). Previously all three fell through to concatenated atoms, so `x₁²` collapsed to `x12`, `∑` from `i=1` to `n` collapsed to `∑i=1n`, and `mfenced` silently dropped its brackets — shredding the body prose of calculus/physics-style documents. They now render `x_{1}^{2}`, `∑_{i=1}^{n}`, and `(x,y)`. Handling stays source-agnostic (standard W3C presentation MathML; unknown elements still fall back to their text, never dropped).

## 0.3.0

### Added
- **`--split-target-kb N` — size-targeted section packing.** An alternative to the fixed-depth split knobs: each branch of the heading tree decides for itself. A branch that fits N KB becomes one file (subsections inlined); an oversized branch splits one level deeper, child by child; an oversized section with **no** sub-headings is partitioned at paragraph/block boundaries into `Title (part i of k)` files that share its identity (`part_index` / `part_count` frontmatter, parts parented to part 1; fenced code and tables are never cut mid-block). One setting produces bounded, retrieval-sized sections across book shapes where no fixed level can — mixed-depth chapters, flat mega-sections — eliminating both monster files and per-heading dust. Mutually exclusive with `--split-max-level`; opt-in, off by default.
- **Every split section file now carries structural identity frontmatter — always on.** Each section leads with a YAML block of joinable keys: `doc_id` (the conversion/out-dir name), `section_id` (the section's own relative path — stable across re-runs), `parent_id` (the nearest ancestor actually written to disk), `section_title` / `section_path` / `section_number` / `heading_level`, `depth`, and `order` (1-based document order). A RAG consumer can scope retrieval to one document, walk from any chunk to its parent or siblings, and cite a stable id — without a second retrieval round-trip. The opt-in provenance source fields (`--provenance` / `--source-type` / `--source-label`) merge into the same block; the master document remains untouched without them. Library note: `split_into_sections()` gained `doc_id=` (defaults to the out-dir name) and dropped the superseded `frontmatter=` string parameter.

## 0.2.2

### Added
- **`audit` gains a `misaligned_table` check.** Flags a wide multi-column spec table whose cell boundaries drifted during extraction so a value lands under the wrong label. Reported as a **warning**, not an error: the defect is real RAG noise but not auto-fixable — Marker and Docling reproduce it identically (ambiguous multi-line-cell geometry in the source PDF), so it is report-only like `duplicate_heading`. Gated on a non-empty sibling value cell, so blank fill-in forms and worksheets are not flagged. Deterministic, $0, no LLM.

## 0.2.1

### Fixed
- **A failed vision read no longer caches a silent placeholder caption.** When the vision call fails or the model's reply can't be parsed, the figure is captioned with its authored alt text when one exists (a real description, so the figure stays retrievable) instead of a bare `(description unavailable)`. The failure is never written to the perceptual-hash cache, so a re-run re-attempts the real call rather than serving the placeholder forever, and parse failures now count toward the end-of-run `vision_failure_summary`. Existing caches keep any placeholder already written — re-vision a document (`--rerun-from vision`) to heal it.

## 0.2.0

### Added
- **`pagespeak vision-audit`** — a read-only command that flags likely-confabulated vision captions for review. It compares each figure's generated caption against the author's source alt text and flags a caption that keeps none of the alt's subject words — a figure described as the wrong thing, the failure a caption-only read can't catch. Deterministic, $0, no LLM; `--strict` exits non-zero to gate a delivery.

## 0.1.0 — initial public release

pagespeak converts documents into clean, LLM-friendly Markdown — with extracted diagrams rendered as embedded Mermaid and an optional per-section split for retrieval (RAG). CLI + Python library. The feature set, by area.

### Conversion
One entry point — `to_markdown(path)` / `pagespeak convert <file>` — dispatching on format: PDF through Marker or Docling, Office / HTML / EPUB / CSV through MarkItDown, and Markdown / plain text straight through. Embedded images are pulled from every source (office media, EPUB and HTML assets, remote `<img>` URLs downloaded and localized) so they can be described and referenced beside the text.

### Pipeline
Conversion runs as an ordered set of resumable stages — ingest → cleanup → heading-normalize → repair → structure → vision → split — each writing an on-disk checkpoint, so any contiguous slice can re-run (`--from` / `--stop-after`) without redoing the expensive steps. Cleanup strips converter artifacts and repeated decorations; an opt-in LLM heading-renormalization pass rebuilds the flattened hierarchies PDF extraction produces, and deterministic post-passes repair heading levels and demote misclassified headings at no cost. Large PDFs ingest in parallel page-range chunks (`--workers N`).

### Diagrams & vision
An optional vision pass describes every extracted image: diagram-shaped figures (flowcharts, sequence and class diagrams, …) get an embedded Mermaid representation; photos, screenshots, and logos get a caption that makes them retrievable. The backend is pluggable — Claude Code (`claude --print`, $0 against a Claude Max session), the Anthropic API, or OpenRouter — and a content-keyed cache, keyed by each image's perceptual hash, reuses descriptions across engines and re-runs.

### Structure for retrieval
`--split-sections` emits one Markdown file per section, each carrying a breadcrumb of its place in the document so a retrieved chunk identifies its own source. Optional source / citation frontmatter tags every section for multi-source knowledge bases.

### Quizzes
Canvas QTI exports (Classic Quizzes) and Top Hat quiz-export PDFs convert to one self-contained answer-key document per quiz, split one file per question, with provenance frontmatter — the correct answer marked when the export reveals it.

### Tooling
`convert`, `ingest`, `deliver` (reduce an output directory to its shippable Markdown + sections + images), `audit` (read-only output-defect detection), and `repair-tables` (splice a clean grid from Docling over a collapsed table) commands. A localhost web console (`pagespeak[web]`) drives the whole pipeline — upload, run any phase, watch images and cost. Optional LLM-call tracking writes one row per call to SQLite or Postgres.

### Packaging
A light default install plus opt-in extras: `[pdf]` (Marker), `[pdf-docling]` (Docling), `[docx-structured]` (structure-faithful DOCX reading), `[tophat]`, `[web]`, and `[postgres]`. Built on pf-core. Ships a PEP 561 `py.typed` marker. Requires Python 3.11+.
