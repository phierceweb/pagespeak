"""The converted documents `pagespeak verify` checks.

A document dir holds a master `.md` at its top level; an export holds one
document dir per sub-folder. The walk mirrors `deliver`'s, so verify checks
exactly what deliver would hand off.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from pw_foundation.exceptions import InvalidInputError

from ._deliver import is_master_md
from ._run_record import read_run_record

_NOT_DOCUMENT_DIRS = frozenset({"images", "sections", "chunks"})
DEFAULT_IN_DIR = Path("conversions/in")


def split_frontmatter(text: str) -> tuple[str, int]:
    """`text` without a leading `---` … `---` block, and how many lines that removed."""
    if not text.startswith("---\n"):
        return text, 0
    end = text.find("\n---\n", 3)
    if end < 0:
        return text, 0
    return text[end + 5 :], text.count("\n", 0, end + 5)


def strip_frontmatter(text: str) -> str:
    return split_frontmatter(text)[0]


@dataclass(frozen=True)
class VerifyDoc:
    """One converted document: its out-dir and master `.md`."""

    root: Path
    master: Path

    @property
    def name(self) -> str:
        return self.master.name.removesuffix(".md")

    @property
    def images_dir(self) -> Path:
        return self.root / "images"

    @cached_property
    def master_text(self) -> str:
        return self.master.read_text(encoding="utf-8", errors="replace")

    @cached_property
    def section_files(self) -> tuple[Path, ...]:
        sections = self.root / "sections"
        if not sections.is_dir():
            return ()
        return tuple(
            p
            for p in sorted(sections.rglob("*.md"))
            if p.name != "INDEX.md" and not p.name.startswith(".")
        )

    @cached_property
    def run_record(self) -> dict[str, Any] | None:
        return read_run_record(self.root)

    @property
    def flags(self) -> dict[str, Any]:
        flags = (self.run_record or {}).get("resolved_flags")
        return flags if isinstance(flags, dict) else {}

    def checkpoint(self, suffix: str) -> Path | None:
        """The stage checkpoint `<stem><suffix>` (e.g. `.structured.md`), if present."""
        path = self.root / f"{self.name}{suffix}"
        return path if path.is_file() else None


def find_documents(path: Path) -> list[VerifyDoc]:
    """Every converted document under `path`, in folder order; a `sections/`,
    `images/` or `chunks/` folder holds none.

    Raises InvalidInputError for a path that is not a folder, or a folder
    holding more than one master: a folder gets one verdict.
    """
    if not path.is_dir():
        raise InvalidInputError(f"not a folder: {path}")
    if path.name in _NOT_DOCUMENT_DIRS:
        return []
    entries = sorted(path.iterdir())
    masters = [e for e in entries if e.is_file() and is_master_md(e.name)]
    if len(masters) > 1:
        names = ", ".join(m.name for m in masters)
        raise InvalidInputError(
            f"{path} holds more than one master .md ({names}); move the extra out"
        )
    docs = [VerifyDoc(path, m) for m in masters]
    for entry in entries:
        if (
            entry.is_dir()
            and entry.name not in _NOT_DOCUMENT_DIRS
            and not entry.name.startswith(".")
        ):
            docs.extend(find_documents(entry))
    return docs


def _out_parts(root: Path) -> tuple[tuple[str, ...], int | None]:
    """`root`'s absolute parts, and where its last `out` folder is among them."""
    parts = Path(os.path.abspath(root)).parts
    return parts, next((i for i in range(len(parts) - 1, -1, -1) if parts[i] == "out"), None)


def delivery_dir(root: Path) -> Path | None:
    """Where `deliver` puts `root` by default: its last `out` folder swapped for
    `delivery`. None outside that layout."""
    parts, i = _out_parts(root)
    return None if i is None else Path(*parts[:i], "delivery", *parts[i + 1 :])


def default_in_dir(root: Path) -> Path:
    """Where `root`'s source PDF is looked for unless told: the `in` folder
    beside its last `out` folder, else `conversions/in`."""
    parts, i = _out_parts(root)
    return DEFAULT_IN_DIR if i is None else Path(*parts[:i], "in")
