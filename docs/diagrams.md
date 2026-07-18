# Diagram extraction

pagespeak's vision pass turns each extracted image into one of two LLM-friendly forms: a structured, editable **Mermaid** block when the content is *structural* (boxes, arrows, named steps), or a label-rich **caption** when the content is *morphological/spatial* (the drawing of a physical thing is itself the information). The original image is always kept alongside, so a downstream multimodal step can still see it.

The prompt is a versioned YAML artifact: [`src/pagespeak/prompts/diagram.yaml`](../src/pagespeak/prompts/diagram.yaml). Edit it there, never inline — see [Bumping the prompt](#bumping-the-prompt).

---

## Table of Contents

- [What becomes Mermaid, and what does not](#what-becomes-mermaid-and-what-does-not)
- [Why Mermaid](#why-mermaid)
- [Pipeline](#pipeline)
- [Backends](#backends)
- [The prompt](#the-prompt)
- [Source-alt-aware captions](#source-alt-aware-captions)
- [Faithful mode (`--preserve-alt`)](#faithful-mode---preserve-alt)
- [Cost](#cost)
- [Failure handling](#failure-handling)
- [Cache-only mode](#cache-only-mode---vision-cache-only)
- [Tuning the prompt](#tuning-the-prompt)
- [Alternative: embedding the diagram twice](#alternative-embedding-the-diagram-twice)

## What becomes Mermaid, and what does not

The single most important rule, and the one most easily misread from the outside: **Mermaid is produced only for *structural* content — never for *morphological/spatial* content.**

- **Structural → Mermaid.** The information is boxes, arrows, and labels you could recreate from scratch in another diagramming tool: flowcharts, process/decision trees, signaling and biochemical *pathways* (named steps with arrows), sequence diagrams, state machines, class/ER diagrams, system-architecture diagrams, and signal-flow/routing diagrams. A flowchart of a named process is structural.
- **Morphological/spatial → caption-only (`mermaid: null`).** The visual rendering of a physical thing *is* the information, and boxes-and-arrows would destroy it: labeled illustrations and cross-sections, micrographs and other photographs, chemical structures / reactions / equilibria, time-series traces (oscilloscope, waveform), data charts, and logos/icons. A cross-section illustration is morphological — even when it has arrows pointing at labeled parts.

This distinction is deliberate and is the whole point of the current prompt. **A labeled morphological or spatial figure is correctly caption-only.** Forcing it into `flowchart` or `architecture-beta` would discard the spatial layout that carries the meaning, so the prompt explicitly forbids it. For those figures the caption is not a thin fallback — it is tiered to transcribe the visible labels and their spatial relationships (see [The prompt](#the-prompt)). The retained original image covers anything the caption cannot.

> Morphological and spatial figures are well-supported, not edge cases the headline feature skips: a label-dense figure converts to a dense label-transcribing caption plus the retained image — which is the right RAG representation for spatial content, not a degraded one.

## Why Mermaid

| Option | Pros | Cons |
|---|---|---|
| **Image only** | Visual fidelity | Opaque to retrieval; an LLM can't read or edit |
| **Plain-language description** | LLM-readable | Lossy on structure; can't be re-rendered |
| **Mermaid** | Text-as-diagram, GitHub renders natively, LLMs handle it fluently, round-trips to a real image via `mmdc` | Limited to supported diagram types |
| **D2** | Stronger architecture diagrams (containers, grids) | Separate renderer, smaller ecosystem |
| **PlantUML** | Mature, broad coverage | Heavy renderer; unfamiliar to most LLMs vs Mermaid |

Mermaid is the default markdown-ecosystem citizen — every renderer that supports markdown has a Mermaid path. D2 is a candidate for architecture diagrams specifically; the prompt would dispatch `mermaid` vs `d2` based on type.

## Pipeline

For each image path, the active vision backend's `analyze(path)` method:

1. Reads the bytes; encodes as base64 (or hands the absolute path to the subprocess in the `claude_code` case).
2. Sends one request with the image + the prompt, rendered with the figure's **existing source alt text** injected (`render_diagram_prompt(original_alt)`) — see [Source-alt-aware captions](#source-alt-aware-captions).
3. Parses the response (a JSON object — see `_parse_response`, which tolerates raw, fenced, and preamble-wrapped JSON).
4. Returns a `Diagram(image_path, caption, mermaid, diagram_type)`.

The figure's existing alt text is read from the markdown *before* this pass (`alt_text_by_basename`) and fed into the prompt, so the caption the model returns is a **correction / preservation / enrichment** of the source description rather than a blind overwrite (see [Source-alt-aware captions](#source-alt-aware-captions)).

Then `_inject_diagrams()` does a markdown rewrite: for each `![...](path)` reference whose basename matches a `Diagram`, the function:

- Replaces the image's alt text with the caption (structurally extractable by downstream parsers and read by screen readers).
- Appends a fenced Mermaid block tagged `pagespeak-image="<path>"` on the info string when `mermaid` is non-null. Renderers ignore the tag; parsers can pair the Mermaid with its source image.

The single-shot and phased pipelines both dedupe via perceptual hash: identical or near-identical images across pages (chapter-opener decorations, repeated icons, the same figure rasterized at different resolutions) collapse to one vision call. Typically saves 30–60% of calls on textbooks (observed across real conversions; varies by document).

## Backends

Three backends, all implementing the same `VisionBackend` Protocol:

| Backend | Transport | Cost | Typical latency / image | Notes |
|---|---|---|---|---|
| `anthropic` | Anthropic SDK | API tokens | ~500 ms | Direct API; supports prompt caching when prompt grows |
| `claude_code` (default) | `claude --print` subprocess | $0 (uses your Claude Code session) | 1-3 s | Pass `vision_model` to override the session default — strongly recommended (Opus is overkill for image captioning) |
| `openrouter` | httpx → openrouter.ai | API tokens (~5-10% markup) | ~600 ms (extra hop) | Multi-provider — Anthropic, Gemini, Llama vision, etc. |

All three return the same `Diagram` shape and use the same prompt.

## The prompt

The prompt lives as a versioned YAML file, [`src/pagespeak/prompts/diagram.yaml`](../src/pagespeak/prompts/diagram.yaml) (`agent: diagram`, with a `version:` integer). It is rendered at import time by `prompts/_diagram.py`; the public constants `DIAGRAM_PROMPT` and `DIAGRAM_PROMPT_VERSION` are preserved via a thin shim in `utils/_prompts.py`, so consumers importing them keep working. **Edit the YAML, not the shim.**

It asks the model to return a single-line JSON object:

```json
{"is_diagram": true, "diagram_type": "sequence", "caption": "...", "mermaid": "..."}
```

The body is organized around the structural-vs-morphological rule above: a "DIAGRAM TYPES (produce Mermaid)" list, a "NOT DIAGRAMS (`mermaid: null`, caption-only)" list, and a caption tier. **Caption depth scales to the image type:**

- Photograph / screenshot — 1 sentence.
- Logo / icon / small glyph — one short clause naming only what is visibly there (no inferred "commonly used to represent…" purpose).
- Diagram — 1–3 sentences of purpose (the Mermaid block carries the structure).
- Multi-panel figure — 2–4 sentences describing each panel and the comparison.
- Data chart — 2–5 sentences naming axes/units/variables and the conclusion, reading off any labeled values.
- **Technical illustration with annotations (a labeled schematic, annotated photo, or cross-section) — 2–3 sentences that transcribe the visible labels and what they refer to.** These figures are caption-only *and* information-dense, so the caption does the work the Mermaid block would do for a structural diagram.
- **Callout / label figures (numbered or lettered diagrams, exploded parts, panel layouts, annotated UI) — enumerate each callout, one entry per label, instead of collapsing to "labeled A–H" / "items #1–#11". Describe a bare icon glyph by its visual form only (never the tool/command it invokes); read legible printed labels verbatim; describe generic physical parts by geometry. The semantic meaning of an unlabeled callout lives in the body legend, not the image.**

A hard rule forbids inventing an identity the image does not legibly show — a brand, product, product category, or what an abstract line-drawing "is." A confidently-wrong identity in alt-text gets indexed for retrieval and makes the document assert a false fact; generic-and-correct beats specific-and-wrong. The full type lists and worked examples live in the YAML — read them there rather than duplicating them here.

### Bumping the prompt

When the prompt's wording changes materially:

1. Edit `system:` (or `user:`) in `src/pagespeak/prompts/diagram.yaml`.
2. Increment the `version:` field.
3. Append a one-line entry to the `changelog:` block in the same file.

Whitespace- or typo-only edits don't bump; semantic changes (new rules, changed examples, modified output schema) do. The version is the consumer's audit trail — they can record it in their own LLM-run table when they call pagespeak, so "the extraction changed this week" has a concrete answer.

## Source-alt-aware captions

Many source documents already ship a description for each figure — the `<img>` alt text in HTML, a caption in a textbook export. That description is preserved in the markdown right up to the vision pass. As of prompt **v2** the vision call **uses it**: the figure's existing alt is injected into the prompt (token `@@ORIGINAL_ALT@@`, rendered per image by `render_diagram_prompt(original_alt)`), and the model is told to treat it as a *starting reference, not ground truth*:

- **Accurate** → keep it, preserving its wording and any specific identifications (a named place, *manual vs automated*, an exact count of panels/items).
- **Wrong / describes a different figure** (source alt is sometimes duplicated or misassigned) → replace it with a correct description.
- **Accurate but thin** ("an illustration of X") → enrich it with the labels and structure visible in the image.
- **A full data transcription** (a rasterized table whose source alt already spells out every row) → keep the transcription; do **not** collapse it into a structural summary of the table's columns, which throws away the per-row data — for an image-only table that data is then unsearchable (added in v3).
- **Absent** → write one from scratch.

The image stays the ground truth — on any conflict the model follows the image, and a wrong identity in the source text is never carried forward (the don't-invent rules still win). This replaced v1's behavior of overwriting *every* alt from the image alone, which downgraded already-good source captions (truncating a complete multi-system figure, or restating a correct one less precisely) while only helping the thin/placeholder ones. The alt map is built by `services/_diagrams.alt_text_by_basename()` and passed to `gather_diagrams(alt_by_basename=…)` by the vision phase.

**Refreshing an existing conversion.** The vision cache is keyed by image phash only — *not* by prompt version, model, or engine (so cached captions are reused across engines — see [caching](caching.md)). Neither a prompt bump nor a model/backend switch auto-invalidates it: to re-caption an already-visioned doc with a new prompt or a stronger model, bust the vision cache explicitly with `--rerun-from vision` (or `pagespeak invalidate <dir> vision`).

## Faithful mode (`--preserve-alt`)

By default the vision pass **replaces** each figure's alt text with the enriched caption (above) and appends the Mermaid block. `--preserve-alt` switches to **faithful mode**: the figure's existing alt text is kept **verbatim** and only the Mermaid block is appended (for diagrams). Non-diagram figures are left completely untouched.

Use it when the source's alt text must not be modified — e.g. contributing structure back to a publisher with a strict approval process for alt text. The Mermaid block is already a cleanly-separable additive layer (its own fence, tagged with `pagespeak-image="<path>"`), so the result is the publisher's text plus an independent structural layer they can accept or reject.

The vision LLM still runs and the caption is still **cached** — it is just not injected. So the same conversion can be re-emitted enriched (drop the flag and re-run `--from vision`) with no re-vision, and the shared cache means a future version could emit both forms from one run. `--preserve-alt` composes with `--diagrams`, and is a no-op under `--no-diagrams` (there is no Mermaid to add).

## Cost

Per-image cost on Claude Haiku 4.5: ~$0.001–0.005, dominated by the image-token count (which depends on resolution).

A short user manual with a dozen diagrams runs around five cents end-to-end. A large technical manual with ~50 figures runs around fifteen to twenty cents. These are operating estimates from real conversions, not benchmark output — resolution and figure density move them.

For larger ingests, override the model: Sonnet costs ~10× more but is meaningfully more accurate on dense architecture diagrams. A model switch only applies to images **not already cached** — the vision cache is phash-keyed, so re-running a finished conversion under a stronger model is 100% cache hits and changes nothing. Bust the cache first (`--rerun-from vision`) to actually re-analyse.

On an already-converted document, switching the model alone changes nothing — every image is served from `.vision-cache/` (keyed by image content, not model), and the run logs one aggregate `vision_cache_model_mismatch` warning naming the cached and active models. To actually re-analyse under the new model, pair the switch with `--rerun-from vision`.

## Failure handling

The contract: a single image's failure does not abort the whole ingest.

If `backend.analyze()` raises (network error, parse failure, subprocess exit-code, timeout), the orchestrator catches it, logs at WARNING, and substitutes a `Diagram(caption=f"Image at {name} (extraction failed).", mermaid=None)`. The image stays in the markdown unchanged; only the augmentation is skipped.

In the phased pipeline, failed images are **not** written to `.vision-cache`, so re-running the conversion (`pagespeak convert <outdir>`) retries just the failures — already-successful images hit the cache and are not re-called.

If the JSON parser inside `_parse_response()` fails, it returns a "description unavailable" caption rather than crashing. The model very rarely returns malformed JSON, but it happens.

## Cache-only mode (`--vision-cache-only`)

Pass `--vision-cache-only` (or `vision_cache_only=True` to `to_markdown()`) to restrict the vision pass to the existing `.vision-cache/` and make **zero LLM calls**. This is the enforced form of the phash-keyed cache reuse that the pipeline already applies: instead of falling back to a live call on a miss, it skips the image entirely and substitutes a caption-only entry, logging a `vision_cache_only_skipped` WARNING that names the affected images.

Typical workflow:

```bash
# First run: full vision (pays for LLM calls, fills the cache)
pagespeak convert file.docx -o ./out

# Re-ingest after editing source or changing a Phase-3 flag:
# reuses the fully-populated cache; guaranteed zero calls.
pagespeak convert file.docx -o ./out --rerun-from ingest --vision-cache-only
```

Incompatible with `--no-diagrams` (raises an error at startup — if diagrams are disabled there is nothing for the cache to serve).

Cost: provably $0 / zero-quota. A re-ingest where the source images are unchanged produces only cache hits; any new image (different phash) is a miss that becomes a skip-with-warning rather than a live call.

## Tuning the prompt

The prompt has been iterated against a range of real documents (textbooks, manuals, quiz exports); the current version reflects that. The recurring failure modes, and the fix for each:

- **False positives** — the model Mermaid-ifies something morphological (a decorative arrow, a screenshot of a table, a labeled illustration with arrows). Tighten or extend the "NOT DIAGRAMS" list and its anti-examples.
- **Mermaid syntax errors** — hand-authored diagrams sometimes need feature-specific syntax the model gets wrong (e.g. `architecture-beta` is newer than common). List the valid types more explicitly.
- **Diagram-type misclassification** — the model picks `flowchart` for what's really a `sequenceDiagram`. One or two added examples fixes most cases.
- **Caption hallucination** — on sparsely-labeled line-art the model can confidently assert a wrong identity (a structure, a device, a brand). The "never invent an identity" rule exists for exactly this; when a new class slips through, add it to that rule's anti-examples and re-vision the affected images.
- **Collapsed callouts** — a labeled UI screenshot or parts diagram captioned as "labeled A–H" with the per-callout mapping lost, or (worse) each glyph guessed a wrong tool name. The callout rule enumerates each label and describes a bare glyph by form, not function; extend its three cases (legible text / bare glyph / generic shape) if a new collapse slips through.

Bump the `version:` and `changelog:` whenever the wording changes (see [Bumping the prompt](#bumping-the-prompt)).

## Alternative: embedding the diagram twice

The current output keeps the original image AND the Mermaid block — an LLM downstream gets both, can compare, and can decide which to feed to its own next step. The cost is a few hundred extra characters per diagram. We deliberately don't strip the original image — visual fidelity matters when the Mermaid extraction is wrong.
