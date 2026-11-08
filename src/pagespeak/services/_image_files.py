"""The files in a document's `images/` folder that vision may send.

One rule for the vision phase, the web console's counts and cost gate, and
`pagespeak pictures`, so their numbers agree.
"""

from __future__ import annotations

from pathlib import Path


def image_files(images_dir: Path) -> list[Path]:
    """Every file at the top of `images_dir` whose name does not start with a dot, sorted."""
    if not images_dir.is_dir():
        return []
    return sorted(p for p in images_dir.iterdir() if p.is_file() and not p.name.startswith("."))
