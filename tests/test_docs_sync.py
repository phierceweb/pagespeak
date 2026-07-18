"""Docs-vs-code drift guard.

The pipeline's phase list, checkpoint chain, and CLI surface are enumerated
in prose across several docs. Those enumerations are hand-written replicas
of code facts (`build_phases()`, `PAGESPEAK_REGISTRY`, `cli/_*.py`) and have
drifted before. Every check here derives the expected value from code, so a
pipeline change fails the suite naming each stale doc.
"""

from __future__ import annotations

import re
from pathlib import Path

from pagespeak.orchestrators._phases import build_phases
from pagespeak.services._rerun import PAGESPEAK_REGISTRY, RERUN_STAGES

_ROOT = Path(__file__).resolve().parent.parent
_DOCS = _ROOT / "docs"

_PHASE_NAMES = [p.name for p in build_phases()]

_NUM_WORDS = {
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
}


def _checkpoint_suffixes() -> list[str]:
    """Per-stage `{stem}.<suffix>.md` names from the registry, pipeline order."""
    out: list[str] = []
    for stage in PAGESPEAK_REGISTRY.stages:
        for f in stage.structural_files:
            m = re.fullmatch(r"\{stem\}\.(\w+)\.md", f)
            if m:
                out.append(m.group(1))
    return out


def _tracked_docs() -> list[Path]:
    # Top level only: subdirectories of docs/ are gitignored local artifacts.
    return sorted(_DOCS.glob("*.md"))


def test_phase_pipe_lists_match_build_phases() -> None:
    """Every `a | b | c`-style phase list in the docs equals build_phases()."""
    expected = " | ".join(_PHASE_NAMES)
    pattern = re.compile(r"`(ingest \| [a-z| ]+)`")
    hits = 0
    for doc in _tracked_docs():
        for match in pattern.finditer(doc.read_text(encoding="utf-8")):
            assert match.group(1) == expected, (
                f"{doc.name}: phase list {match.group(1)!r} != build_phases() {expected!r}"
            )
            hits += 1
    assert hits >= 2, "expected phase-pipe lists in pipeline.md and caching.md"


def test_stage_arrow_sequences_are_contiguous_runs() -> None:
    """ASCII arrow sequences must be a contiguous run of a real pipeline view.

    Two legitimate views exist: RERUN_STAGES (with `decorations`) and the
    phase list (without). Elided breadcrumbs (`ingest → **cleanup** → …`)
    are fine; a sequence that *skips* a stage mid-run is drift.
    """
    views = [list(RERUN_STAGES), _PHASE_NAMES]
    pattern = re.compile(r"^ingest (?:─▶|→) .+$", re.MULTILINE)
    hits = 0
    for doc in _tracked_docs():
        for match in pattern.finditer(doc.read_text(encoding="utf-8")):
            names = [
                t.strip().strip("*")
                for t in re.split(r"─▶|→", match.group(0))
                if t.strip() and t.strip() != "…"
            ]
            ok = any(
                view[: len(names)] == names  # runs start at ingest
                for view in views
            )
            assert ok, (
                f"{doc.name}: stage sequence {names} is not a contiguous run of "
                f"RERUN_STAGES {views[0]} or the phase list {views[1]}"
            )
            hits += 1
    assert hits >= 2, "expected arrow sequences in pipeline.md and caching.md"


def test_phase_count_words_match() -> None:
    """Prose like 'All seven phases' / 'The seven concrete phases' stays true."""
    word = _NUM_WORDS[len(_PHASE_NAMES)]
    pattern = re.compile(r"\b(?:All|The) (\w+) (?:concrete )?(?:pipeline )?phases\b")
    for doc in [*_tracked_docs(), _ROOT / "CLAUDE.md"]:
        if not doc.exists():  # CLAUDE.md is gitignored — absent in worktrees/CI
            continue
        for match in pattern.finditer(doc.read_text(encoding="utf-8")):
            assert match.group(1) == word, (
                f"{doc.name}: says {match.group(1)!r} phases; build_phases() has "
                f"{len(_PHASE_NAMES)} ({word!r})"
            )


def test_checkpoint_chains_are_contiguous() -> None:
    """A doc enumerating stage checkpoints must not skip one mid-chain.

    Mentioning a subset is fine (normalize docs discuss cleaned/normalized
    only); mentioning checkpoints on both sides of an unmentioned one is the
    drift signature (a chain written before a phase existed).
    """
    suffixes = _checkpoint_suffixes()
    for doc in _tracked_docs():
        text = doc.read_text(encoding="utf-8")
        mentioned = [i for i, s in enumerate(suffixes) if f"{s}.md" in text]
        # <3 mentions is a range (`raw.md … visioned.md`) or example, not a chain.
        if len(mentioned) < 3:
            continue
        missing = [
            suffixes[i] for i in range(min(mentioned), max(mentioned) + 1) if i not in mentioned
        ]
        assert not missing, (
            f"{doc.name}: checkpoint chain mentions {[suffixes[i] for i in mentioned]} "
            f"but skips {missing} — stale enumeration?"
        )


def test_consumed_by_notes_match_phase_order() -> None:
    """`(consumed by `X`)` in a pipeline-<stage>.md page names the next phase."""
    for doc in _DOCS.glob("pipeline-*.md"):
        stage = doc.stem.removeprefix("pipeline-")
        if stage not in _PHASE_NAMES:
            continue  # decorations: a cleanup sub-step, no successor phase
        idx = _PHASE_NAMES.index(stage)
        if idx + 1 >= len(_PHASE_NAMES):
            continue
        for match in re.finditer(r"consumed by `(\w+)`", doc.read_text(encoding="utf-8")):
            assert match.group(1) == _PHASE_NAMES[idx + 1], (
                f"{doc.name}: says consumed by {match.group(1)!r}; the phase after "
                f"{stage!r} is {_PHASE_NAMES[idx + 1]!r}"
            )


def test_all_source_modules_in_architecture_md() -> None:
    """Every non-init module under src/pagespeak/ appears in architecture.md."""
    text = (_DOCS / "architecture.md").read_text(encoding="utf-8")
    missing = []
    for py in sorted((_ROOT / "src" / "pagespeak").rglob("*.py")):
        if py.name == "__init__.py" or "__pycache__" in py.parts:
            continue
        rel = py.relative_to(_ROOT / "src" / "pagespeak")
        # Root modules are cited bare (`_db.py`); packaged ones by path.
        needle = py.name if len(rel.parts) == 1 else str(rel)
        if needle not in text:
            missing.append(str(rel))
    assert not missing, f"architecture.md module tables missing: {missing}"
