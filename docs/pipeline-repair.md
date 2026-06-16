# Pipeline stage: repair

The `repair` stage (`orchestrators/_phases.py:RepairPhase`, `services/_normalize_repair.py`) is a **$0, deterministic, post-LLM heading-hierarchy fixer**. It reads the frozen `<stem>.normalized.md` and writes `<stem>.repaired.md`.

It exists because the heading hierarchy IS the document's relationship structure (split happens at heading boundaries; a section's nesting is its relationship to the rest). The normalize LLM gets the levels mostly right but leaves residual slips; repair cleans those up **without re-paying the LLM** — so you can iterate it for free (`--from repair --stop-after repair`).

## What it does

Structured like `cleanup`: a **detect→correct** engine. Each pass is self-diagnosing and a **no-op when its defect is absent**, so a clean doc (e.g. a well-numbered paper) passes through untouched — that's the "didn't over-reach" guarantee. Passes (all structural signals, never phrase lists):

- **numbered-depth lock** — set a numbered heading's level from its dot count (`12.1` → depth 2), restoring parent-child nesting.
- **strip heading spans** — drop leftover `<span id=…>` page anchors from heading titles.
- **demote number-only headings** — `# 780` → body (kills garbage one-line sections from stray page numbers).
- **dedupe doubled heading text** — `# X X` → `# X`.
- **demote spaced-letter dividers** — `# S K E L E T A L` → body.
- **close heading level-gaps** — promote an orphan over-deep heading so no level is skipped (`## Topic` → `#### Task` with no `### ` becomes `### Task`), cascading the shift through the subtree and keeping siblings consistent. Closes the skips `llm_full` normalize leaves on big flattened PDFs (a 204-pp HTML-export user guide: 125 skips → 0). Conservative: the baseline heading keeps its level (never forced to H1), a contiguous hierarchy is a no-op, the pass is idempotent, and fenced code blocks are ignored.

The artifact passes **and the level-gap close** are corpus-verified to fire only on PDF-converted docs (textbooks and AV guides) and never on the structure-faithful decks: the phase runs them under `is_outline_doc=False` only, so a Word author's intentional level-skip is never second-guessed.

## Inputs / outputs

- Input checkpoint: `<stem>.normalized.md`.
- Output checkpoint: `<stem>.repaired.md` (consumed by `vision`).
- Rerun key: `repair` (`--rerun-from repair` / `pagespeak invalidate <out> repair`) — busts `repaired.md` + downstream structural files.

## What it deliberately is NOT (yet)

- **Flat-hierarchy re-nesting** (a manual's flattened sibling controls) and **outline→heading promotion** (under-segmented structure-faithful decks) are larger, higher-risk fixes tracked separately, not part of the shipped passes.
- It does not reconstruct a spine the *conversion* mangled (e.g. Marker dual-column chapter numbers fused mid-title) — that is an ingest-level problem; repair tidies the surface, it does not re-OCR structure.
