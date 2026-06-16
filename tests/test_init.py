"""Tests for pagespeak package initialization and version.

The version assertion is intentionally value-agnostic: it guards the
real regression (the two version declarations — `__init__.__version__`
and `pyproject.toml` — must not drift) WITHOUT hardcoding the current
literal, which would force a test edit every release and guard nothing.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pagespeak

_SEMVER = re.compile(r"^\d+\.\d+\.\d+([.-][0-9A-Za-z.]+)?$")


def test_version_is_semver_shaped() -> None:
    assert _SEMVER.match(pagespeak.__version__), pagespeak.__version__


def test_version_matches_pyproject() -> None:
    """`__init__.__version__` and `pyproject.toml` must agree — they are
    two hand-maintained sources and silently drift on a release."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert pagespeak.__version__ == data["project"]["version"]


def test_python_is_311_plus() -> None:
    """`requires-python >= 3.11` — tomllib + modern syntax depend on it."""
    assert sys.version_info >= (3, 11)
