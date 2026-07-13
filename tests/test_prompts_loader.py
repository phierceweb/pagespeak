"""Tests for `pagespeak.prompts._loader` — spec loading via pf-core.

`load_pagespeak_spec` delegates to `pf_core.llm.prompts.load_prompt`; these
tests pin pagespeak's contract: the env var name (`PAGESPEAK_PROMPTS_DIR`),
the CWD `config/prompts/` override location, and the bundled fallback.

Override chain (highest precedence first):
1. ``$PAGESPEAK_PROMPTS_DIR/<agent>.yaml``
2. ``config/prompts/<agent>.yaml`` relative to the current working directory
3. Bundled default at ``src/pagespeak/prompts/<agent>.yaml``
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_bundled_default_loads_when_no_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No env var, no CWD override → the packaged YAML loads."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PAGESPEAK_PROMPTS_DIR", raising=False)
    from pagespeak.prompts._loader import load_pagespeak_spec

    spec = load_pagespeak_spec("diagram")
    assert spec["agent"] == "diagram"
    assert isinstance(spec["version"], int)


def test_cwd_config_override_wins_over_bundled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A YAML at ``<cwd>/config/prompts/<agent>.yaml`` wins over bundled."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PAGESPEAK_PROMPTS_DIR", raising=False)
    (tmp_path / "config" / "prompts").mkdir(parents=True)
    override = tmp_path / "config" / "prompts" / "diagram.yaml"
    override.write_text("agent: diagram\nversion: 99\nsystem: |\n  overridden\n", encoding="utf-8")

    from pagespeak.prompts._loader import load_pagespeak_spec

    assert load_pagespeak_spec("diagram")["version"] == 99


def test_env_var_dir_wins_over_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``PAGESPEAK_PROMPTS_DIR`` wins over the CWD override."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config" / "prompts").mkdir(parents=True)
    cwd_override = tmp_path / "config" / "prompts" / "diagram.yaml"
    cwd_override.write_text("agent: diagram\nversion: 1\nsystem: cwd-override\n", encoding="utf-8")

    env_dir = tmp_path / "custom_prompts"
    env_dir.mkdir()
    env_override = env_dir / "diagram.yaml"
    env_override.write_text("agent: diagram\nversion: 7\nsystem: env-override\n", encoding="utf-8")
    monkeypatch.setenv("PAGESPEAK_PROMPTS_DIR", str(env_dir))

    from pagespeak.prompts._loader import load_pagespeak_spec

    assert load_pagespeak_spec("diagram")["version"] == 7


def test_env_var_missing_file_falls_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``PAGESPEAK_PROMPTS_DIR`` set but empty → falls through to CWD
    override, then bundled."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PAGESPEAK_PROMPTS_DIR", str(tmp_path / "nonexistent"))

    from pagespeak.prompts._loader import load_pagespeak_spec

    spec = load_pagespeak_spec("diagram")
    assert spec["agent"] == "diagram"
