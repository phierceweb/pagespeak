# Stage: normalize

Repairs flattened heading hierarchy. Marker often emits every heading in a textbook at the same depth; this stage recovers the chapter → section → subsection nesting. Opt-in.

## What it does

Gathers the document's structural heading list, computes a level rewrite, and applies it. Three engines (`normalize_headings_mode`):

| Mode | Cost | Notes |
|---|---|---|
| `heuristic` (default) | $0, instant | Numbering-based rules for `Chapter N` / `N.M.O` patterns. No LLM call, no cache. |
| `llm` | one Claude call (~30–60s) | Sends the heading list; handles unusual front-matter / non-numbered chapters. |
| `llm_full` | one Claude call | Sends headings **plus** body-context anchors so the model reasons from prose. |

`llm` / `llm_full` cache the response at `<outdir>/.heading-normalize-cache/<hash>.json` (content-keyed — self-invalidates when the input changes).

## When it runs

- **Opt-in.** Off unless `normalize_headings=True` / `--normalize-headings`, or a preset that enables it. When off, the gather
  + apply step is skipped entirely.
- Backend for the LLM modes is selectable per task (`PAGESPEAK_HEADING_NORMALIZE_BACKEND` / `PAGESPEAK_HEADING_NORMALIZE_FULL_BACKEND`, or `--normalize-headings-backend`).

## Inputs

`<stem>.cleaned.md` content (post-cleanup, pre-vision — a slim input, so `llm_full` has headroom for body anchors).

## Outputs

`<stem>.normalized.md` — the structural checkpoint. **Always written** when `output_dir` is set, even when normalize is off; in that case it is byte-identical to `<stem>.cleaned.md`. This makes `diff <stem>.cleaned.md <stem>.normalized.md` the exact record of what normalize changed.

## Position

cleanup → **normalize** → repair → structure → vision → …

## Re-running just this stage

`--rerun-from normalize` / `pagespeak invalidate <outdir> normalize` deletes `<stem>.normalized.md` and the heading-normalize cache plus downstream checkpoints, then re-gathers and re-applies against `<stem>.cleaned.md`.

## Deep dive

- [normalize-headings.md](normalize-headings.md) — engine details, cache invalidation, real-corpus results
