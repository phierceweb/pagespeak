"""Tests for pagespeak package initialization and version.

The version assertions are intentionally value-agnostic: they guard the
real regression (the three version declarations — `__init__.__version__`,
`pyproject.toml`, and CHANGELOG.md's newest section — must not drift)
WITHOUT hardcoding the current literal, which would force a test edit
every release and guard nothing.
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


def test_changelog_newest_section_matches_version() -> None:
    """CHANGELOG.md's first `## ` heading names `__version__`.

    Catches both shapes of release drift: a stale top version, and an
    `## Unreleased` section left standing above the version being shipped.
    """
    changelog = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", text, re.MULTILINE)
    assert headings, "CHANGELOG.md has no `## ` section headings"
    assert headings[0] == pagespeak.__version__, (
        f"CHANGELOG.md's newest section is `## {headings[0]}` but __version__ is "
        f"{pagespeak.__version__}; fold finished work into `## {pagespeak.__version__}`"
    )


def test_python_is_312_plus() -> None:
    """`requires-python >= 3.12` — pf-core 0.20 sets the floor."""
    assert sys.version_info >= (3, 12)
