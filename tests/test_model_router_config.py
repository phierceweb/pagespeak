"""The bundled model router and the repo's `config/` copy must agree.

A `pip install` reads the bundled file; a checkout run from the repo root
reads `config/model_router.yaml`. Comments may differ; values may not.
"""

from __future__ import annotations

from pathlib import Path

from pw_foundation.utils.yaml import safe_load

_ROOT = Path(__file__).resolve().parents[1]


def test_bundled_router_matches_config_copy() -> None:
    bundled = safe_load((_ROOT / "src" / "pagespeak" / "model_router.yaml").read_text())
    config = safe_load((_ROOT / "config" / "model_router.yaml").read_text())
    assert bundled == config
