"""Tests for web/_cost.vision_will_run — the phase-slice → vision-cost gate."""

from __future__ import annotations

from pagespeak.web._cost import vision_will_run


def test_vision_runs_for_a_full_default_slice() -> None:
    assert vision_will_run(None, None, diagrams=True, cache_only=False)


def test_vision_skipped_when_diagrams_off() -> None:
    assert not vision_will_run(None, None, diagrams=False, cache_only=False)


def test_vision_skipped_when_cache_only() -> None:
    assert not vision_will_run(None, None, diagrams=True, cache_only=True)


def test_vision_skipped_when_slice_stops_before_vision() -> None:
    # structure is the phase immediately BEFORE vision — stopping there must NOT
    # run vision. (Regression: `structure` missing from _PHASE_ORDER defaulted
    # `hi` past vision and wrongly reported a vision cost.)
    assert not vision_will_run(None, "structure", diagrams=True, cache_only=False)
    assert not vision_will_run(None, "repair", diagrams=True, cache_only=False)


def test_vision_runs_when_slice_includes_vision() -> None:
    assert vision_will_run("structure", "vision", diagrams=True, cache_only=False)
    assert vision_will_run("vision", "vision", diagrams=True, cache_only=False)


def test_vision_skipped_when_slice_starts_after_vision() -> None:
    assert not vision_will_run("split", None, diagrams=True, cache_only=False)
