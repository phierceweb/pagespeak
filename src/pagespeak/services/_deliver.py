"""Strip a converted output tree down to delivery-ready files.

A converted document dir holds the master `.md`, per-stage checkpoints
(`<stem>.raw/cleaned/normalized/repaired/visioned.md`), a run record, content
caches (`.vision-cache/` …), and the deliverables `images/` + `sections/`.
`strip_for_delivery` mirrors such a tree into a parallel dir keeping ONLY the
deliverables — the master `.md`, `sections/`, and `images/` — and dropping the
working files. It handles a single document dir or a fan-out export (one
sub-dir per document, e.g. a Canvas QTI export). The destination is rebuilt
fresh on every run (replaces any prior delivery); the source is never modified.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pw_foundation.exceptions import PreconditionError
from pw_foundation.log import get_logger

from ._rerun import PAGESPEAK_REGISTRY

logger = get_logger(__name__)

# Deliverable subdirs copied wholesale; everything else is filtered.
_DELIVERABLE_DIRS: frozenset[str] = frozenset({"images", "sections"})
# Non-deliverable structural dirs we never recurse into or copy.
_SKIP_DIRS: frozenset[str] = frozenset({"chunks"})


def _checkpoint_md_suffixes() -> frozenset[str]:
    """Stage-checkpoint `.md` suffixes (e.g. ``.raw.md``), derived from the
    pipeline stage registry so a newly added stage's checkpoint is dropped
    from delivery automatically — no hardcoded list to drift."""
    return frozenset(
        tmpl.replace("{stem}", "")
        for stage in PAGESPEAK_REGISTRY.stages
        for tmpl in stage.structural_files
        if tmpl.startswith("{stem}.") and tmpl.endswith(".md")
    )


_CHECKPOINT_MD_SUFFIXES = _checkpoint_md_suffixes()


def is_master_md(name: str) -> bool:
    """A `.md` deliverable: the master doc, not a stage checkpoint or a dot-file
    (a verify verdict sits beside the master)."""
    return (
        name.endswith(".md")
        and not name.startswith(".")
        and not any(name.endswith(suffix) for suffix in _CHECKPOINT_MD_SUFFIXES)
    )


def is_delivered(rel: Path) -> bool:
    """Whether deliver hands off `rel`, a path relative to its document's folder:
    inside `images/` or `sections/`, with no dot-named part."""
    parts = rel.parts
    return (
        len(parts) > 1
        and parts[0] in _DELIVERABLE_DIRS
        and not any(p.startswith(".") for p in parts)
    )


def _left_behind(root: Path) -> Callable[[str, list[str]], set[str]]:
    """`copytree`'s ignore for a document folder `root`: what `is_delivered` turns away."""

    def ignore(folder: str, names: list[str]) -> set[str]:
        return {n for n in names if not is_delivered(Path(folder, n).relative_to(root))}

    return ignore


@dataclass
class _Counts:
    documents: int = 0
    files: int = 0


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome of a delivery strip: where it landed and how much was copied."""

    dest: Path
    documents: int
    files: int


def _require_disjoint(src: Path, dst: Path) -> None:
    """The destination is rmtree'd, so it must not be, contain, or sit inside the
    source — otherwise delivery deletes the tree it is about to read."""
    s, d = src.resolve(), dst.resolve()
    if s == d or s.is_relative_to(d) or d.is_relative_to(s):
        raise ValueError(f"delivery destination must be outside the source tree: {d} overlaps {s}")


def strip_for_delivery(source: str | Path, dest: str | Path) -> DeliveryResult:
    """Mirror `source` into `dest`, keeping only the master `.md`(s),
    `sections/`, and `images/`. Drops stage checkpoints, run records, content
    caches, chunks, and manifests.

    `dest` is removed and rebuilt fresh, so delivery always matches the current
    source (no stale orphans). Only `dest` is ever deleted; `source` is read-only.
    """
    src = Path(source)
    dst = Path(dest)
    if not src.is_dir():
        raise NotADirectoryError(f"delivery source is not a directory: {src}")
    _require_disjoint(src, dst)
    if dst.exists():
        shutil.rmtree(dst)

    counts = _Counts()
    _deliver_tree(src, dst, counts)
    logger.info(
        "delivery_complete dest=%s documents=%d files=%d", dst, counts.documents, counts.files
    )
    return DeliveryResult(dest=dst, documents=counts.documents, files=counts.files)


def deliver(source: str | Path, dest: str | Path, *, in_dir: Path | None = None) -> DeliveryResult:
    """`strip_for_delivery` behind the verify gate: raises PreconditionError,
    naming each verdict file, while any document under `source` fails verify.
    A source holding no document delivers nothing and leaves `dest` as it is.
    `in_dir` is where verify looks for source PDFs (default: beside each
    document's `out` folder, see `default_in_dir`)."""
    from ._verify import require_deliverable  # _verify imports this module

    if Path(source).name in _DELIVERABLE_DIRS | _SKIP_DIRS:
        raise PreconditionError(
            f"delivery refused: {source} is part of a document; deliver its folder instead"
        )
    if not require_deliverable(Path(source), in_dir=in_dir):
        return DeliveryResult(dest=Path(dest), documents=0, files=0)
    return strip_for_delivery(source, dest)


def _deliver_tree(src_dir: Path, dest_dir: Path, counts: _Counts) -> None:
    """Recursively copy deliverables from `src_dir` to `dest_dir`. A dir with a
    master `.md` is one document, delivered with its `sections/` and `images/`;
    dirs without are traversed for nested documents (the export → per-exam
    fan-out), and their own `sections/` or `images/` are not a document."""
    entries = sorted(src_dir.iterdir())
    masters = [e for e in entries if e.is_file() and is_master_md(e.name)]
    if masters:
        dest_dir.mkdir(parents=True, exist_ok=True)
        counts.documents += 1
        for master in masters:
            shutil.copy2(master, dest_dir / master.name)
            counts.files += 1
        for sub in (e for e in entries if e.is_dir() and e.name in _DELIVERABLE_DIRS):
            target = dest_dir / sub.name
            shutil.copytree(sub, target, ignore=_left_behind(src_dir))
            counts.files += sum(1 for p in target.rglob("*") if p.is_file())

    for entry in entries:
        if (
            entry.is_dir()
            and entry.name not in _DELIVERABLE_DIRS
            and entry.name not in _SKIP_DIRS
            and not entry.name.startswith(".")
        ):
            _deliver_tree(entry, dest_dir / entry.name, counts)


__all__ = ["DeliveryResult", "deliver", "is_delivered", "is_master_md", "strip_for_delivery"]
