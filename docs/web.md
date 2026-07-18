# Web console

A localhost FastAPI app that puts every pagespeak pipeline operation behind a browser UI. Drop a document, choose what to run (full convert by default, or any phase slice), watch the queue, and inspect output — checkpoints, extracted images, and LLM cost — without ever touching the CLI.

Requires the `pagespeak[web]` extra. Library consumers importing `to_markdown` never pull FastAPI.

## Launch

```bash
bin/setup --web    # install FastAPI + uvicorn + jinja2 into the project venv
bin/start          # start the console in the background at http://127.0.0.1:8810
bin/stop           # stop it   (bin/restart = stop + start)
```

`bin/start` runs the server detached (`nohup`), writes its PID + log to `logs/.pagespeak-web.{pid,log}`, and returns your prompt — there is no foreground process to keep open. It deliberately does **not** use `--reload`: a file-watch restart would kill the worker mid-conversion and strand the job.

Outside a repo checkout (plain `pip install pagespeak[web]`), launch it directly: `uvicorn pagespeak.web:create_app --factory --host 127.0.0.1 --port 8810`.

### Environment variables

| Var | Default | Purpose |
|---|---|---|
| `PAGESPEAK_CONVERSIONS_DIR` | `<cwd>/conversions` | Root holding `in/` (sources) + `out/` (per-doc output) |
| `PAGESPEAK_WEB_HOST` | `127.0.0.1` | Bind host |
| `PAGESPEAK_WEB_PORT` | `8810` | Bind port |
| `PAGESPEAK_WEB_CONCURRENCY` | `1` | Concurrent conversion jobs (default 1 avoids parallel vision quota stampedes) |

## The `conversions/` store

The console adopts the existing `conversions/` on-disk convention — it does not invent a private workspace root.

- **`conversions/in/<name>.<ext>`** — source documents.
- **`conversions/out/<dir>/`** — per-document output: phase checkpoints (`<stem>.raw.md` → `.cleaned.md` → `.normalized.md` → `.repaired.md` → `.structured.md` → `.visioned.md` → `<stem>.md`), `images/`, `.vision-cache/`, `.heading-normalize-cache/`, and `.pagespeak-run.json`.
- **`conversions/delivery/<dir>/`** — handoff-ready stripped copies produced by the **Deliver** action (master `.md` + `sections/` + `images/` only; no checkpoints, run records, or caches). Written only when you click Deliver — empty by default.

**Dropping a file into `conversions/in/` via Finder is identical to uploading it through the web form.** Both produce the same Conversion entry in the queue. Web upload writes the file into `conversions/in/`; nothing else differs.

A **Conversion** is keyed on its output directory. The durable source↔output link is the stem embedded in the checkpoint filenames (e.g. `conversions/out/mixer-manual/Mixer_Manual.raw.md` → stem `Mixer_Manual` → source `conversions/in/Mixer_Manual.pdf`), not the directory name, which may be hand-chosen. A source in `conversions/in/` with no matching output directory surfaces as "not yet converted" — droppable, ready to run.

For a new conversion the app names the output directory from the source stem (lowercased, spaces/underscores→hyphens). When a source already has a matching output directory, it reuses it.

## Home / queue

The home page shows:

- **Conversion list** — every entry in `conversions/out/*/`, state (not-converted / running / done / failed), and an upload form that writes to `conversions/in/`.
- **Live queue table** — HTMX-polled (~3 s): active and recent jobs with document name, current phase, progress, elapsed time, and cancel/retry controls.

## Conversion detail cockpit

The detail page for a single Conversion is the main working surface.

### Phase strip

```
ingest ✓ · cleanup ✓ · normalize – · repair ✓ · structure ✓ · vision ✓ · split –
```

Derived from which phase checkpoints exist on disk. Each phase chip offers:

- **Run** — launch a job starting at (and optionally stopping after) this phase.
- **Re-run from here** — same as `--rerun-from <phase>`; busts the cache at this phase and downstream.
- **View checkpoint** — open this phase's `.md` file in the checkpoint viewer.

Phase names: `ingest | cleanup | normalize | repair | structure | vision | split` (matching the CLI's `--from` / `--stop-after` vocabulary).

The detail page splits into two tabs — **Document** (the checkpoint viewer, full width) and **Images** (the gallery) — so a large image set never crowds the document. The image-detail panel sits above the tabs and is shared by both.

### Checkpoint viewer (Document tab)

Shows any phase checkpoint (`raw`, `cleaned`, `normalized`, `repaired`, `visioned`, final) with a **Rendered / Raw text** toggle:

- **Rendered** — full markdown (headings, tables, code, inline images) rendered by the [`zero-md`](https://github.com/zerodevx/zero-md) web component (GitHub-style CSS + syntax highlighting, self-contained). The component fetches the checkpoint markdown from `/c/<dir>/md/<view>`, which rewrites relative `images/…` refs to the image route so figures load. Fenced ```mermaid blocks are **drawn as diagrams** (zero-md renders them via mermaid.js, configured `securityLevel: 'antiscript'` — HTML labels like the LLM's `<br/>` still render, scripts are stripped).
- **Raw text** — the literal checkpoint file content, for comparison.

### Image gallery (Images tab)

Thumbnails from `images/`. **Click any thumbnail — or any image inline in the rendered document — ** to open a panel showing the full image alongside its **caption (alt text)**, **diagram type**, and **Mermaid source** (in a copyable code block), looked up from `.vision-cache/<phash>.json` by the image's perceptual hash. Images that haven't been through the vision pass (or are photos/screenshots) show the caption with a "no mermaid" note. Useful for inspecting which images were classified as diagrams vs. photos vs. screenshots, and for grabbing the Mermaid for a specific figure.

### Run record (its own tab)

A dedicated tab rendering `.pagespeak-run.json` in a readable form: a plain-English intro, a **What happened** table (when it ran, pagespeak version, source file, sections/images produced, AI calls + cost), a **Settings used** table (the `resolved_flags`, formatted — `true`→yes, `null`→default), and the full raw JSON in a collapsible. These are the exact settings the last run used; re-running reuses them. This is the rerun-safety guarantee: a re-run from an upstream phase carries the same `split_sections` / `nested_split` / `preset` / `normalize_headings*` flags as the original, never bare defaults that would silently wipe `sections/`.

### Options / run form

A three-step flow: (1) **Choose what to run** — a step picker (`Full run` or a single phase: ingest … split); (2) the picker **filters the options to just those that affect the chosen step** (e.g. picking *vision* shows only diagrams / cache-only / which-AI; *repair* shows none); (3) a separate **Run** button (its label reflects the selection) submits. Options map to the `pagespeak convert` flags (preset, PDF backend, cleanup, normalize mode, split / nested-split, diagrams on/off, vision backend, cache-only). Each option has a hover **ⓘ tooltip** explaining it in plain language. A single-phase run sets `--from`/`--stop-after` to that phase and reuses the existing checkpoints.

### Deliver

A **Deliver** card sits under the run form. Pressing it strips this conversion's output dir to delivery-ready files — the master `.md`, `sections/`, and `images/` — into `conversions/delivery/<dir>/`, dropping stage checkpoints, the run record, and content caches. The destination is rebuilt fresh on every press so it always matches the current `out/`; the source `out/` is never modified. The button is disabled until a master `.md` exists (nothing to deliver yet). POST `/api/deliver/<dir>` is the underlying route; CLI parity is `pagespeak deliver <out-dir>`.

### LLM summary

Per-Conversion call count, cost, and cache hits/misses for all jobs run on this document. Deep-links into the `/admin/llm` dashboards filtered by `job_id`.

## Cost gate

Before launching any job that includes the vision phase with `--diagrams` (and without `--vision-cache-only`), the console computes the **cache-miss count**:

```
cache misses = (images in images/) − (matching phashes in .vision-cache/)
```

It shows this before you confirm, e.g.:

> *"40 images · 31 cached · 9 live calls. Backend claude_code → 9 Max-quota calls ($0)."*

An explicit confirm is required. The confirm dialog also shows the grounded cost estimate for paid backends (~3–5K tokens per image via anthropic/openrouter).

**Vision backend defaults to `claude_code` ($0 in dollars; draws from your Claude Max subscription).** Switching to a paid backend (anthropic / openrouter) triggers a louder warning. There is no silent switch to a paid backend — that is a deliberate cost-safety default.

If the cache or image count cannot be determined (e.g. `images/` is absent), the UI says so rather than quoting "cheap".

### Cache-only toggle

The **cache-only toggle** maps to `--vision-cache-only`. It makes cost provably zero: uncached images become caption-only skips (a `vision_cache_only_skipped` WARNING names them in the log). Use it when re-ingesting a document whose images are unchanged and the cache is already populated — all phash hits reuse cached descriptions, no LLM calls are made.

## LLM observability

`/admin/*` mounts `pf_core.web.llm_admin` as-is — no new code required. It provides:

- LLM run log (all calls across all documents)
- Cost by model and by agent
- Job queue and job detail
- Cache statistics
- Budget caps

The per-Conversion LLM summary on the detail page is a filtered view of the same data, keyed by `job_id`.

## Architecture

One **job** = one `pagespeak convert` subprocess covering the requested phase slice:

```
browser action → JobRepo.create("pagespeak_convert", {from, stop_after, options})
                          ↓
              in-process background worker
              (PAGESPEAK_WEB_CONCURRENCY workers, default 1)
                          ↓
              subprocess: pagespeak convert <out_dir>
                          --from <phase> --stop-after <phase>
                          <options>
                          ↓
              checkpoint written to conversions/out/<dir>/
                          ↓
              job_step outcome recorded; phase strip updated on next poll
```

Subprocess isolation keeps Marker/torch and the macOS `ProcessPoolExecutor` quirks (see [docs/operations.md](operations.md)) out of the web process.

**LLM attribution:** the worker passes a `PAGESPEAK_JOB_ID` env var to the subprocess so `pf_core`'s `_agent_runtime` records the `job_id` on every LLM run row — this is what ties vision and normalize calls to a specific Conversion in the `/admin/llm` dashboards and the per-Conversion summary.

Progress is read from on-disk phase checkpoints (the phase strip), not a synthetic per-phase counter. The queue table polls checkpoints every ~3 s via HTMX.

### Modules (`src/pagespeak/web/`)

| Module | Responsibility |
|---|---|
| `web/__init__.py` | `create_app()` — app factory; mounts `llm_admin` + routers |
| `web/_config.py` | `PagespeakWebConfig` — conversions dir, host, port, concurrency |
| `web/_scan.py` | `conversions/in` + `conversions/out` scanner and reconciler → Conversion list/detail |
| `web/_cost.py` | Cache-miss pre-flight math + grounded cost estimate |
| `web/_jobs.py` | `pagespeak_convert` job kind registration (inputs/outputs schema) |
| `web/_worker.py` | In-process background worker: `claim_next` → phase-driver subprocess loop |
| `web/api/pages.py` | HTML routes (home/queue, new conversion, detail cockpit) |
| `web/api/actions.py` | Action routes (submit job, cancel, retry, upload) |
| `web/api/partials.py` | HTMX partial routes (queue table, phase strip, log tail) |
