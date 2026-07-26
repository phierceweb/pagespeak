"""Package-data drift guard.

Non-`.py` files under `src/` reach an installed user only if a
`[tool.setuptools.package-data]` glob matches them. Nothing else catches a
miss: the suite imports from the source tree where every asset exists, and
`twine check` inspects metadata, not payload. So an asset added without a
matching glob passes every gate and fails at runtime for installed users
only.

Both checks resolve the declared globs against the real tree, the same way
setuptools does.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
_PKG = _SRC / "pagespeak"

_PACKAGE_DATA: dict[str, list[str]] = tomllib.loads(
    (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
)["tool"]["setuptools"]["package-data"]


def _base_dir(package: str) -> Path:
    return _SRC / package.replace(".", "/")


def _declared() -> set[Path]:
    """Every file the package-data globs actually resolve to."""
    return {
        path.resolve()
        for package, globs in _PACKAGE_DATA.items()
        for glob in globs
        for path in _base_dir(package).glob(glob)
        if path.is_file()
    }


def _runtime_assets() -> set[Path]:
    """Every shippable non-`.py` file in the package (`src/*.egg-info` is local build metadata)."""
    return {
        path.resolve()
        for path in _PKG.rglob("*")
        if path.is_file()
        and path.suffix != ".py"
        and not path.name.startswith(".")
        and "__pycache__" not in path.parts
    }


def test_every_runtime_asset_is_declared() -> None:
    """No non-`.py` file under `src/` is missing from package-data."""
    missing = sorted(p.relative_to(_ROOT).as_posix() for p in _runtime_assets() - _declared())
    assert not missing, (
        "these files ship in the repo but not in the wheel — add a matching glob to "
        "[tool.setuptools.package-data] in pyproject.toml:\n  " + "\n  ".join(missing)
    )


def test_no_package_data_glob_is_dead() -> None:
    """Every declared glob still matches something (catches a moved asset)."""
    dead = sorted(
        f"{package} = {glob!r}"
        for package, globs in _PACKAGE_DATA.items()
        for glob in globs
        if not any(p.is_file() for p in _base_dir(package).glob(glob))
    )
    assert not dead, "package-data globs matching no file:\n  " + "\n  ".join(dead)
