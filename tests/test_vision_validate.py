"""Tests for pagespeak.services._vision_validate."""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _fresh_registry():
    """pf-core's validator registry is global; keep tests independent."""
    from pf_core.llm.validate import clear_registry

    clear_registry()
    yield
    clear_registry()


def _signals(result) -> dict[str, tuple[str, bool]]:
    return {s.validator: (s.severity, s.passed) for s in result.signals}


def test_complete_diagram_response_passes() -> None:
    from pagespeak.services._vision_validate import validate_vision_response

    raw = json.dumps(
        {
            "is_diagram": True,
            "diagram_type": "flowchart",
            "caption": "Signal flow from input to output.",
            "mermaid": "graph TD; A-->B;",
        }
    )
    result = validate_vision_response(raw)
    assert result is not None
    assert result.ok, _signals(result)


def test_caption_only_response_passes() -> None:
    """A photo/screenshot legitimately has no mermaid."""
    from pagespeak.services._vision_validate import validate_vision_response

    raw = json.dumps(
        {"is_diagram": False, "diagram_type": None, "caption": "A rack of gear.", "mermaid": None}
    )
    result = validate_vision_response(raw)
    assert result is not None
    assert result.ok, _signals(result)


def test_diagram_without_mermaid_is_flagged() -> None:
    """Called a diagram but shipped no mermaid — the figure loses its structure."""
    from pagespeak.services._vision_validate import validate_vision_response

    raw = json.dumps(
        {"is_diagram": True, "diagram_type": "flowchart", "caption": "A flowchart.", "mermaid": ""}
    )
    result = validate_vision_response(raw)
    assert result is not None
    assert not result.ok
    assert "vision_response_complete" in _signals(result)


def test_missing_caption_is_flagged() -> None:
    from pagespeak.services._vision_validate import validate_vision_response

    raw = json.dumps({"is_diagram": False, "caption": "   ", "mermaid": None})
    result = validate_vision_response(raw)
    assert result is not None
    assert not result.ok


def test_unparseable_response_reports_a_parse_signal() -> None:
    from pagespeak.services._vision_validate import validate_vision_response

    result = validate_vision_response("I'm afraid I can't help with that.")
    assert result is not None
    assert not result.ok
    assert any("parse" in name for name in _signals(result))


def test_registration_is_idempotent() -> None:
    from pf_core.llm.validate import has_pipeline

    from pagespeak.services._vision_validate import ensure_registered

    ensure_registered()
    ensure_registered()
    assert has_pipeline("vision")
