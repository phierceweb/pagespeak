# Heading-level renormalization

Opt-in pre-split pass that fixes flattened heading hierarchy in PDF extractions. Three engines + an auto-selector:

| Mode | What it does | Speed | Cost |
|---|---|---|---|
| `heuristic` (default) | Numbering-based rules: `Chapter N` → L1, `N.M` → L2, `N.M.O` → L3, `N. Title` → L1. Pure / deterministic / no I/O. | Instant | $0 |
| `llm` | Sends the heading list (headers only) to the LLM, parses the response, caches it. Handles edge cases the heuristic doesn't (unusual front-matter, non-numbered chapter titles). | ~30–60s | One LLM call per uncached run |
| `llm_full` | Sends the heading list **plus body anchors**, so the LLM levels by surrounding context, not just heading text — needed for badly-flattened textbooks where heading text alone is ambiguous. Self-falls-back to headers-only if the payload exceeds the configured token budget. | ~30–90s | One (large) LLM call per uncached run |
| `auto` | Picks `heuristic` or `llm_full` **per document** from a $0 no-LLM heading-shape signal — see [Auto mode](#auto-mode). | Instant decision | $0 decision; the chosen engine's cost applies |

Short non-prose margin-code fragments (`EN`, `FR`) that a backend promoted to headings are demoted in cleanup (`services/_fragments.py`) before normalize runs, so normalize sees a cleaner heading set.

Residual heading slips this pass leaves (or introduces) are cleaned up **after** it by the `$0` deterministic **repair** stage (`services/_normalize_repair.py`, writes `<stem>.repaired.md`), which runs between normalize and vision — see [pipeline-repair.md](pipeline-repair.md). Repair is the cheap deterministic counterpart to this (sometimes paid) LLM pass: freeze the LLM output, iterate repair for free.

## Auto mode

`normalize_headings_mode="auto"` (CLI `--normalize-headings-mode auto`) decides **per document**, with a $0 deterministic signal (no LLM), whether to skip the LLM (run the free `heuristic`) or invoke `llm_full`. It is a **two-way** decision — `llm` (headers-only) is not an auto target (it is `llm_full`'s own internal fallback for oversized payloads, and on flattened textbooks headers-only *degraded* the result vs full body context).

A document is routed to `llm_full` only when ALL of:

- **not numbered** — fewer than 40% of headings are `Chapter N` / `N.M` numbered (numbered docs get the free deterministic fix — no LLM needed);
- **collapsed** — the single most-common heading level holds ≥ 40 headings. This is an absolute **count**, not a share: a well-structured pyramid is *also* leaf-heavy, so the dominant-level share doesn't separate a flattened doc from a healthy one — the size of the pile does. A small genuinely-flat manual (~24 headings) stays under the bar; a collapsed textbook (~1700 headings) or a Marker-mis-leveled manual (≥40 at one level, even at a 37–59% share) clears it; AND
- **fits** — the estimated `llm_full` body-anchor payload is within the configured `max_input_tokens` (`config/model_router.yaml`, `agents.heading_normalize_full`). When ONLY this clause fails, the doc is routed to `heuristic` with the loud reason `needs_full_but_oversized_for_config` — a signal to enlarge the context config, not a silent degradation to headers-only.

Otherwise → `heuristic`. The decision (mode + reason + the shape metrics) is logged as `normalize_auto_decision`; the classifier lives in `services/_normalize_decision.py`. Thresholds are document-relative ratios plus one absolute count — never corpus phrase lists (the general-converter rule).

## When to use it

Marker (and other PDF backends) sometimes emit chapter headings and their subsections at the same heading depth. Concrete case: a chapter heading (`Chapter 1 <Title>`) and its subsection (`1.1 <Subtitle>`) both come out as `####` (level 4) because Marker's layout model classifies them identically. With both at level 4, the splitter has no level-strict-less ancestor to attach `1.1` to — descendants render with no chapter ancestor in their breadcrumb chain.

`normalize_headings=True` runs the heading list through the configured engine (heuristic by default; LLM via `normalize_headings_mode="llm"`) which recognizes the chapter/ subsection pattern and rewrites levels: chapters get promoted to L1, their `N.X` subsections to L2, and so on.

**Use it when**:
- Your PDF is a textbook, manual, or thesis with `Chapter N` headings.
- Section files end up missing breadcrumb chains to their chapter.
- The splitter is producing 100s of "top-level" sections that should obviously be under a chapter.

**Don't bother when**:
- Marker already gets the hierarchy right (most product manuals).
- The doc has no `Chapter N` pattern (lab notes, slides, blog posts).
- You'd rather keep the run deterministic — the LLM call is the only source of non-determinism in the pipeline.

## How it works

The pass is split into a **gather** stage (pure side-file producer) and an **apply** stage (pure markdown transform). Both engines share the same gather/apply contract; only the gather body differs.

1. **Extract**: pull every `# … #####` heading line out of the consolidated markdown.
2. **Filter**: keep only "structural" headings — `Chapter N` matches and `N.X` numbered subsections. Drops TOC page-number entries (`1.1 Foo, p. 32`, `1 Introduction 31`) and quiz-answer-style sentence headings (`# 1. Cyclic changes in activity. Each month…`) that confuse the engine at scale.
3. **Gather** (`gather_normalize_levels`):
   - **Heuristic mode**: apply the numbering-based rules to each filtered heading. No subprocess, no cache file. Returns a `NormalizeData` (levels dict + heading-list snapshot for drift detection).
   - **LLM mode**: send the filtered list to Claude Code with one heading per line, parse the per-line level responses, persist to cache, return a `NormalizeData`.
4. **Apply** (`apply_normalization`): re-extract the heading list from the *current* markdown (so callers can run cleanup or other transforms between gather and apply), drift-check against the snapshot, then rewrite heading lines per the levels dict. If heading count or texts have drifted since gather (e.g. cleanup added/removed headings), log a warning and skip — never silently mis-apply. Mode-agnostic.
5. **Cache** (LLM mode only): response is keyed on heading list + model + prompt version, persisted at `<output_dir>/.heading-normalize-cache/<hash>.json`. Re-runs are free. Heuristic mode is fast enough not to need a cache.


## Usage

### Library

```python
from pagespeak import to_markdown

# Default: heuristic mode (fast, free, no LLM call)
result = to_markdown(
    "textbook.pdf",
    output_dir="./out",
    normalize_headings=True,
)

# LLM mode for unusual front-matter / non-numbered chapters
result = to_markdown(
    "weird-doc.pdf",
    output_dir="./out",
    normalize_headings=True,
    normalize_headings_mode="llm",
    normalize_headings_model="claude-haiku-4-5-20251001",  # optional, LLM-mode only
)
```

### CLI

```bash
# Default: heuristic
bin/run convert textbook.pdf -o ./out --normalize-headings

# LLM mode (with optional explicit model):
bin/run convert textbook.pdf -o ./out \
    --normalize-headings \
    --normalize-headings-mode llm \
    --normalize-headings-model claude-haiku-4-5-20251001
```

### Model selection (LLM mode only)

Heuristic mode ignores model selection. For LLM mode (`llm` or `llm_full`), three layers (highest-precedence first):

1. Explicit `normalize_headings_model="…"` / `--normalize-headings-model …`
2. `config/model_router.yaml` — `agents.heading_normalize.backends.<backend>.model` for `llm` mode; `agents.heading_normalize_full.backends.<backend>.model` for `llm_full`. The two modes have separate YAML blocks so they can use different models (e.g. a larger-context model for `llm_full` on very large docs).
3. `DEFAULT_NORMALIZE_MODEL` (`claude-haiku-4-5-20251001`) — never falls through to the user's interactive Claude Code session model.

The legacy `PAGESPEAK_NORMALIZE_HEADINGS_MODEL` env var is no longer consulted — the YAML is the source of truth and env is reserved for backend selection only. Haiku is plenty for `llm` mode; Gemini 2.5 Flash via OpenRouter is the recommended model for `llm_full` on very large docs (1M context window fits body anchors that Haiku's 200K cannot).

## Side files

When `normalize_headings=True` and `output_dir` is set:

| Path | When written | Contents |
|------|--------------|----------|
| `<stem>.raw.md` | After backend, always | Raw Marker / Docling / MarkItDown output, pre-everything |
| `<stem>.pre-normalize.md` | After cleanup, before normalize | Post-cleanup, pre-rewrite. Diff against `<stem>.md` to see exactly what normalize changed. Written in both modes. |
| `<stem>.md` | End of run (CLI writes this) | Final output |
| `.heading-normalize-cache/<hash>.json` | LLM mode only, after successful call | Cached response, reused on re-run |

The pre-normalize snapshot is the **review/revert path**. To see the edits:

```bash
diff <(cat textbook.pre-normalize.md) <(cat textbook.md) | head -50
```

To revert without re-running (e.g. if the rewrites looked wrong):

```bash
mv textbook.md textbook.normalized.md
cp textbook.pre-normalize.md textbook.md
# then re-run with --no-normalize-headings (and split)
```

## Caching (LLM mode only)

Heuristic mode doesn't cache — it's fast enough that a fresh computation is always cheaper than a cache lookup.

LLM-mode cache key is derived from:
- The list of heading lines (level + text)
- The model name
- The prompt version (bumped by `services._heading_normalize.NORMALIZE_PROMPT_VERSION`)

Anything that changes the heading list (re-running Marker on a modified PDF, switching cleanup levels) busts the cache. Anything that changes the model busts the cache. Editing the prompt and bumping the version busts the cache.

Cache files are atomic (tmp + rename) and never partial. Manually delete the cache directory to force a fresh LLM call.

## Failure modes

The pass is **non-fatal** in both modes: if anything goes wrong, we log a warning and return the original markdown. The pipeline continues.

| Failure | What happens |
|---------|-------------|
| **(LLM mode)** `claude` CLI not on PATH | Warning logged, original markdown returned |
| **(LLM mode)** Subprocess exits non-zero | Same — original returned |
| **(LLM mode)** Response has no parseable `<idx>: <level>` lines | Same — log "no_levels_parsed" |
| **(LLM mode)** Cache file unreadable | Treated as miss, fresh call made |
| All structural headings filtered out (< 2 left) | Skip — not enough signal to renormalize. Logged as `heading_normalize_skipped`. |
| Heading list drifted between gather and apply (cleanup added/removed headings) | Apply skipped, original returned. Logged as `heading_normalize_drift_*`. |

## Prompt versioning

The prompt lives in `services/_heading_normalize.py` as `NORMALIZE_PROMPT` with `NORMALIZE_PROMPT_VERSION` as an integer. Per the prompt-authoring convention:

- Bump the version on every material edit to the prompt body.
- Whitespace / typo-only edits don't bump.
- The cache key includes the version, so a bumped prompt forces re-evaluation on next run.
