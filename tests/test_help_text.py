"""Tests for pagespeak.cli._help_text."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_YAML = """env_prefix: PAGESPEAK
default_client: claude_code
non_chat_keys: [max_input_tokens]

agents:
  heading_normalize:
    backends:
      claude_code:
        model: zzz-plain-model
  heading_normalize_full:
    backends:
      claude_code:
        model: zzz-full-model
  heading_normalize_dehead:
    backends:
      claude_code:
        model: zzz-dehead-model
"""


@pytest.fixture
def _routed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Point the router at a config with distinctive model names."""
    from pf_core.llm.router import clear_cache

    cfg = tmp_path / "router.yaml"
    cfg.write_text(_YAML, encoding="utf-8")
    monkeypatch.setenv("MODEL_ROUTER_CONFIG", str(cfg))
    clear_cache()
    yield
    clear_cache()


def test_help_reports_the_models_the_router_resolves(_routed) -> None:
    """Derived, not restated: change the routing and the help follows."""
    from pagespeak.cli import _help_text

    importlib.reload(_help_text)
    text = _help_text.normalize_model_help()

    assert "zzz-plain-model" in text
    assert "zzz-full-model" in text
    assert "zzz-dehead-model" in text


def test_help_survives_an_unreadable_router(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A broken config must not break `--help`."""
    from pf_core.llm.router import clear_cache

    bad = tmp_path / "broken.yaml"
    bad.write_text("{{{ not yaml", encoding="utf-8")
    monkeypatch.setenv("MODEL_ROUTER_CONFIG", str(bad))
    clear_cache()
    try:
        from pagespeak.cli import _help_text

        importlib.reload(_help_text)
        text = _help_text.normalize_model_help()
        assert "model_router.yaml" in text
        assert text.strip()
    finally:
        clear_cache()


def test_help_names_no_hardcoded_default() -> None:
    """The fallback constant is not the effective default."""
    from pagespeak.cli import _help_text
    from pagespeak.services._normalize_llm import DEFAULT_NORMALIZE_MODEL

    importlib.reload(_help_text)
    assert DEFAULT_NORMALIZE_MODEL not in _help_text.normalize_model_help()
