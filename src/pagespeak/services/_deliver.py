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
from dataclasses import dataclass
from pathlib import Path

from pf_core.log import get_logger

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


def _is_master_md(name: str) -> bool:
    """A `.md` deliverable: the master doc, not a stage checkpoint."""
    return name.endswith(".md") and not any(
        name.endswith(suffix) for suffix in _CHECKPOINT_MD_SUFFIXES
    )


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
    if dst.resolve() == src.resolve():
        raise ValueError("delivery destination must differ from the source")
    if dst.exists():
        shutil.rmtree(dst)

    counts = _Counts()
    _deliver_tree(src, dst, counts)
    logger.info(
        "delivery_complete dest=%s documents=%d files=%d", dst, counts.documents, counts.files
    )
    return DeliveryResult(dest=dst, documents=counts.documents, files=counts.files)


def _deliver_tree(src_dir: Path, dest_dir: Path, counts: _Counts) -> None:
    """Recursively copy deliverables from `src_dir` to `dest_dir`. A dir with a
    master `.md` is one document; dirs without are traversed for nested
    documents (the export → per-exam fan-out)."""
    entries = sorted(src_dir.iterdir())
    masters = [e for e in entries if e.is_file() and _is_master_md(e.name)]
    deliverable_dirs = [e for e in entries if e.is_dir() and e.name in _DELIVERABLE_DIRS]

    if masters or deliverable_dirs:
        dest_dir.mkdir(parents=True, exist_ok=True)
    if masters:
        counts.documents += 1
    for master in masters:
        shutil.copy2(master, dest_dir / master.name)
        counts.files += 1
    for sub in deliverable_dirs:
        target = dest_dir / sub.name
        shutil.copytree(sub, target)
        counts.files += sum(1 for p in target.rglob("*") if p.is_file())

    for entry in entries:
        if (
            entry.is_dir()
            and entry.name not in _DELIVERABLE_DIRS
            and entry.name not in _SKIP_DIRS
            and not entry.name.startswith(".")
        ):
            _deliver_tree(entry, dest_dir / entry.name, counts)


__all__ = ["DeliveryResult", "strip_for_delivery"]
