"""Tests for web/_cost.vision_will_run — the phase-slice → vision-cost gate."""

from __future__ import annotations

import pytest

from pagespeak.web._cost import _estimate_paid, vision_will_run


def test_an_unpriced_model_shows_no_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    """pw-core projects a call nothing prices as 0.0, which is not free."""
    import pw_core.budget

    monkeypatch.setattr(pw_core.budget, "project_cost", lambda **_kw: 0.0)
    assert _estimate_paid(10, "anthropic") is None


def test_a_priced_model_estimates_every_live_call(monkeypatch: pytest.MonkeyPatch) -> None:
    import pw_core.budget

    monkeypatch.setattr(pw_core.budget, "project_cost", lambda **_kw: 0.002)
    assert _estimate_paid(10, "anthropic") == pytest.approx(0.02)


def test_the_estimate_prices_the_model_the_router_picks_for_the_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pw_core.budget
    import pw_core.llm.router

    priced: list[str] = []

    def project_cost(**kw: object) -> float:
        priced.append(str(kw["model"]))
        return 0.001

    monkeypatch.setattr(pw_core.budget, "project_cost", project_cost)
    monkeypatch.setattr(
        pw_core.llm.router,
        "get_agent_config",
        lambda agent, backend, **_kw: {"model": f"{agent}-model-on-{backend}"},
    )
    _estimate_paid(10, "openrouter")
    _estimate_paid(10, "anthropic")
    assert priced == ["vision-model-on-openrouter", "vision-model-on-anthropic"]


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
