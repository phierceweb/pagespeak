"""Tests for pagespeak.services._normalize_coverage."""

from __future__ import annotations

import logging

import pytest

from pagespeak.services._normalize_coverage import (
    MIN_COVERAGE_PCT_DEFAULT,
    min_coverage_pct,
    warn_on_low_coverage,
)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if "heading_normalize_low_coverage" in r.getMessage()
    ]


def test_warns_below_threshold(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        warn_on_low_coverage(1, 4, mode="llm_full")
    assert _warnings(caplog), "a 25% response should warn"


def test_silent_at_full_coverage(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        warn_on_low_coverage(4, 4, mode="llm_full")
    assert not _warnings(caplog)


def test_silent_at_exactly_the_threshold(caplog: pytest.LogCaptureFixture) -> None:
    """The threshold is inclusive — 90 of 100 does not warn at the default."""
    with caplog.at_level(logging.WARNING):
        warn_on_low_coverage(90, 100, mode="llm")
    assert not _warnings(caplog)

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        warn_on_low_coverage(89, 100, mode="llm")
    assert _warnings(caplog)


def test_zero_target_does_not_divide(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        warn_on_low_coverage(0, 0, mode="llm")
    assert not _warnings(caplog)


def test_message_names_the_numbers(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        warn_on_low_coverage(200, 1731, mode="llm_full")
    msg = _warnings(caplog)[0]
    assert "covered=200" in msg
    assert "target=1731" in msg
    assert "mode=llm_full" in msg


def test_threshold_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert min_coverage_pct() == MIN_COVERAGE_PCT_DEFAULT
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_MIN_COVERAGE_PCT", "40")
    assert min_coverage_pct() == 40


def test_malformed_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """pf-core's resolve_int warns and falls back rather than crashing."""
    monkeypatch.setenv("PAGESPEAK_NORMALIZE_MIN_COVERAGE_PCT", "not-a-number")
    assert min_coverage_pct() == MIN_COVERAGE_PCT_DEFAULT
