"""Sequencer: runs phases in order, supports from / stop_after /
single-phase / rerun_from / resume-skip. Pure ordering logic — no real
pipeline state (fake phases record their own run + freshness).

Mirrors `src/pagespeak/orchestrators/_sequencer.py`.
"""

from __future__ import annotations

import pytest

from pagespeak.orchestrators._phase import Phase
from pagespeak.orchestrators._sequencer import UnknownStageError, run_pipeline


class FakePhase:
    """Minimal Phase: records when run; freshness is settable."""

    def __init__(self, name: str, *, fresh: bool = False) -> None:
        self.name = name
        self._fresh = fresh
        self.ran = False

    def is_fresh(self, ctx: object) -> bool:
        return self._fresh

    def run(self, ctx: object) -> None:
        self.ran = True


def _phases(*specs: tuple[str, bool]) -> list[Phase]:
    return [FakePhase(n, fresh=f) for n, f in specs]


PIPELINE = ("ingest", "cleanup", "normalize", "repair", "structure", "vision", "split")


def _fresh_none() -> list[Phase]:
    return _phases(*[(n, False) for n in PIPELINE])


def test_runs_all_phases_in_order_when_nothing_fresh() -> None:
    phases = _fresh_none()
    ran = run_pipeline(phases, ctx=object())
    assert ran == list(PIPELINE)
    assert all(p.ran for p in phases)  # type: ignore[attr-defined]


def test_stop_after_halts_after_named_phase() -> None:
    phases = _fresh_none()
    ran = run_pipeline(phases, ctx=object(), stop_after="cleanup")
    assert ran == ["ingest", "cleanup"]
    assert not any(
        p.ran
        for p in phases
        if p.name in ("normalize", "repair", "structure", "vision", "split")  # type: ignore[attr-defined]
    )


def test_start_at_runs_from_named_phase_to_end() -> None:
    phases = _fresh_none()
    ran = run_pipeline(phases, ctx=object(), start="normalize")
    assert ran == ["normalize", "repair", "structure", "vision", "split"]


def test_single_phase_when_start_equals_stop() -> None:
    phases = _fresh_none()
    ran = run_pipeline(phases, ctx=object(), start="normalize", stop_after="normalize")
    assert ran == ["normalize"]
    assert [p.name for p in phases if p.ran] == ["normalize"]  # type: ignore[attr-defined]


def test_resume_skips_fresh_prefix() -> None:
    # ingest+cleanup fresh → resume at normalize.
    phases = _phases(
        ("ingest", True),
        ("cleanup", True),
        ("normalize", False),
        ("repair", False),
        ("structure", False),
        ("vision", False),
        ("split", False),
    )
    ran = run_pipeline(phases, ctx=object())
    assert ran == ["normalize", "repair", "structure", "vision", "split"]


def test_rerun_from_forces_rerun_despite_fresh() -> None:
    # Everything fresh, but rerun_from=cleanup must re-run cleanup→end.
    phases = _phases(*[(n, True) for n in PIPELINE])
    ran = run_pipeline(phases, ctx=object(), rerun_from="cleanup")
    assert ran == ["cleanup", "normalize", "repair", "structure", "vision", "split"]


def test_all_fresh_no_rerun_runs_nothing() -> None:
    phases = _phases(*[(n, True) for n in PIPELINE])
    ran = run_pipeline(phases, ctx=object())
    assert ran == []
    assert not any(p.ran for p in phases)  # type: ignore[attr-defined]


def test_unknown_stage_name_raises() -> None:
    phases = _fresh_none()
    with pytest.raises(UnknownStageError):
        run_pipeline(phases, ctx=object(), stop_after="bogus")
    with pytest.raises(UnknownStageError):
        run_pipeline(phases, ctx=object(), start="nope")


def test_stop_before_start_raises() -> None:
    phases = _fresh_none()
    with pytest.raises(ValueError):
        run_pipeline(phases, ctx=object(), start="normalize", stop_after="cleanup")
