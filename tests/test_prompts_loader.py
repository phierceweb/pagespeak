"""Tests for `pagespeak.prompts._loader` — prompt YAML path resolution.

Override chain (highest precedence first):
1. ``$PAGESPEAK_PROMPTS_DIR/<agent>.yaml`` — env-var pointing at a
   directory of override YAMLs.
2. ``config/prompts/<agent>.yaml`` — relative to current working
   directory. Matches the `config/model_router.yaml` pattern so users
   keep all customizable config under one top-level ``config/`` tree.
3. Bundled fallback at ``src/pagespeak/prompts/<agent>.yaml`` —
   shipped inside the installed package; the source of truth when no
   override is present.

Library consumers (apps that depend on pagespeak) get the bundled
defaults out of the box. To customize, drop a YAML into the consumer's
own ``config/prompts/<agent>.yaml`` and the loader picks it up.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_resolve_prompt_path_uses_bundled_default_when_no_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No env var, no CWD override → bundled YAML inside the package."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PAGESPEAK_PROMPTS_DIR", raising=False)
    from pagespeak.prompts._loader import resolve_prompt_path

    path = resolve_prompt_path("diagram")
    assert path.exists()
    assert "src/pagespeak/prompts" in str(path)
    assert path.name == "diagram.yaml"


def test_resolve_prompt_path_uses_cwd_config_override_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A YAML at ``<cwd>/config/prompts/<agent>.yaml`` wins over the
    bundled default."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PAGESPEAK_PROMPTS_DIR", raising=False)
    (tmp_path / "config" / "prompts").mkdir(parents=True)
    override = tmp_path / "config" / "prompts" / "diagram.yaml"
    override.write_text("agent: diagram\nversion: 99\nsystem: |\n  overridden\n", encoding="utf-8")

    from pagespeak.prompts._loader import resolve_prompt_path

    path = resolve_prompt_path("diagram")
    assert path == override


def test_resolve_prompt_path_env_var_dir_wins_over_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``PAGESPEAK_PROMPTS_DIR`` env var wins over the CWD override."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config" / "prompts").mkdir(parents=True)
    cwd_override = tmp_path / "config" / "prompts" / "diagram.yaml"
    cwd_override.write_text("agent: diagram\nversion: 1\nsystem: cwd-override\n", encoding="utf-8")

    env_dir = tmp_path / "custom_prompts"
    env_dir.mkdir()
    env_override = env_dir / "diagram.yaml"
    env_override.write_text("agent: diagram\nversion: 1\nsystem: env-override\n", encoding="utf-8")
    monkeypatch.setenv("PAGESPEAK_PROMPTS_DIR", str(env_dir))

    from pagespeak.prompts._loader import resolve_prompt_path

    assert resolve_prompt_path("diagram") == env_override


def test_resolve_prompt_path_env_var_missing_file_falls_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``PAGESPEAK_PROMPTS_DIR`` set but the file isn't there → fall
    through to CWD override, then bundled."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PAGESPEAK_PROMPTS_DIR", str(tmp_path / "nonexistent"))

    from pagespeak.prompts._loader import resolve_prompt_path

    # Falls through to bundled default since no CWD override either.
    path = resolve_prompt_path("diagram")
    assert "src/pagespeak/prompts" in str(path)
