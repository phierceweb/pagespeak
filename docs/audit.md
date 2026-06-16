# `pagespeak audit` — output-defect detection

Scan converted markdown output for known conversion-defect shapes — read-only, $0, no LLM calls.

Do not confuse the three QA layers: **`bin/lint`** checks the *code* (ruff, mypy, file-size guard); **`bin/validate`** checks whether a *code change altered output* relative to a baseline; **`pagespeak audit`** checks whether *converted output is defective* — absolute, per-document or corpus-wide, no baseline needed.

For AI assistants: the audit narrows *where* to read — it never replaces the read-by-eye validation gate (read the actual rendered output, not just the metric). Treat a clean audit as a gate, not a verdict.

---

## Table of Contents

- [Running it](#running-it)
- [What it scans (and skips)](#what-it-scans-and-skips)
- [The detectors](#the-detectors)
- [Severity model and exit codes](#severity-model-and-exit-codes)
- [What audit deliberately does NOT do](#what-audit-deliberately-does-not-do)
- [Adding a new detector](#adding-a-new-detector)

## Running it

```bash
pagespeak audit conversions/out                 # whole corpus
pagespeak audit conversions/out/<doc>           # one converted document
pagespeak audit out/manual.md                   # a single markdown file
pagespeak audit conversions/out --summary-only  # per-check totals only
```

The report prints per-check totals, then per-file detail capped at a few examples per check per file (`… and N more`). Use `--summary-only` for the totals alone — the right first pass on a large corpus.

## What it scans (and skips)

Audit reads **final artifacts only**: the master `<stem>.md`, `sections/`, and `INDEX.md`. It skips:

- stage checkpoints (`*.raw.md`, `*.cleaned.md`, `*.normalized.md`, `*.repaired.md`, `*.structured.md`, `*.visioned.md`) — intermediates are *expected* to contain pre-cleanup defects;
- `chunks/` — chunked-parallel ingest intermediates;
- dot-directories (`.vision-cache/`, `.baselines/`, …).

## The detectors

Every detector exists because the defect was **observed in real converted output** — never speculation (see "Adding a new detector"). Each is a mechanical, deterministic check; none calls an LLM.

| Check | Defect shape | Severity |
|---|---|---|
| `collapsed_table` | A whole table collapsed into one `<br>`-joined mega-cell (≥30 `<br>`) — the Marker shape where every row is jammed into a single cell | error |
| `html_fragment` | Stray HTML table debris in prose (`<voltage<5v< td="">`, orphan `</td>`), or mangled empty-attribute tags (`<on off="" ="">`) | error |
| `replacement_char` | U+FFFD `�` — encoding damage (lost symbols like Ω or keyboard glyphs) | error |
| `html_entity` | Undecoded `&lt;` / `&amp;` / `&#8217;` outside code fences — a cleanup regression | error |
| `shattered_emphasis` | Emphasis-marker pileups (`****word****`) from shattered runs | error |
| `dangling_image_ref` | `![…](path)` whose relative target doesn't exist on disk | error |
| `empty_section` | A `sections/` file with no body **and** no subsections — a true orphan shell | warning |
| `duplicate_heading` | The same heading text ≥4 times in one file (recurring scaffold furniture) | warning |

Detector-shape notes that prevent false positives — preserve these behaviors when editing:

- All text checks operate **outside fenced code blocks**: a literal `&lt;` in a code example is content, not a defect.
- `html_fragment` masks angle-wrapped markdown link targets (`](<Table of Contents.md>)`) before matching — the splitter's link style is not HTML debris. `<br>` and page-anchor `<span id="page-…">` lines are pagespeak's own legitimate output and are never flagged.
- `empty_section` does NOT flag nav nodes: a parent section whose only content is a `## Subsections` list is the splitter's deliberate shape — its content lives in its children.
- A line of only asterisks is a markdown horizontal rule, not shatter.

## Severity model and exit codes

- **error** — the content itself is damaged; an LLM/RAG consumer reads wrong or missing information. Any error → exit code 1.
- **warning** — worth a human look, but possibly faithful-to-source (e.g. `duplicate_heading`: recurring callout furniture is structurally identical to inconsistently-leveled real sections, so automated demotion is a known wall — the audit reports, a human decides). Warnings alone → exit code 0.

## What audit deliberately does NOT do

- **Never fixes anything.** Read-only by charter. Fixes belong in the pipeline (cleanup/structure passes), gated by their own validation. The one companion *fix* command is **`pagespeak repair-tables <out-dir>`** for `collapsed_table`: it Docling-ingests just the collapsed-table page and splices the clean grid into the `<stem>.raw.md` checkpoint (no whole-doc re-ingest, no re-vision), then you propagate with `convert <dir> --from cleanup --vision-cache-only`. Surgical on purpose — Docling is a targeted table fix, not a blanket upgrade, so read each spliced table by eye. See [repair-tables.md](repair-tables.md).
- **Never calls an LLM.** Deterministic regexes and filesystem checks only.
- **Never judges prose quality.** A messy-but-faithful conversion of a messy source is correct pagespeak output; audit flags *conversion damage*, not authorial style.
- **Does not replace reading the output.** A clean audit means "none of the known defect shapes" — not "the document is good."

## Adding a new detector

1. **Provenance first.** A detector is added only for a defect shape observed in real converted output (name the document in the detector's docstring or the changelog). No speculative checks.
2. Pure text checks go in `services/_audit_checks.py` (a `text -> list[AuditFinding]` function, registered in `_TEXT_CHECKS`); checks needing the filesystem go in `services/_audit.py` and are wired into `audit_file()`.
3. Pick the severity by the rule above: content damage = error; needs-human- judgment = warning.
4. Pair it with tests in the matching `tests/test_audit_checks.py` / `tests/test_audit.py` — a positive case modelled on the real defect, a negative case for the closest legitimate output shape, and a fenced-code immunity case if it's a text check.
5. Run it corpus-wide before shipping and eyeball a sample of hits: a detector that false-positives on legitimate output (nav nodes, angle-wrapped links) is worse than no detector.
6. Sync this page's detector table and the CHANGELOG.
