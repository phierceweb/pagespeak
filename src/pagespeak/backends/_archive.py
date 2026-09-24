"""Read zip members with a decompressed-size cap and no path escapes.

The size a zip declares for a member is not trusted: bytes are counted as they
inflate, so a zip bomb stops at `PAGESPEAK_MAX_ARCHIVE_BYTES` instead of
filling the disk or memory.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

from pf_core.utils.env import resolve_int

MAX_ARCHIVE_BYTES_DEFAULT = 1024 * 1024 * 1024
_MAX_ARCHIVE_BYTES_ENV_VAR = "PAGESPEAK_MAX_ARCHIVE_BYTES"
_CHUNK_BYTES = 1024 * 1024


def max_archive_bytes() -> int:
    value: int = resolve_int(None, _MAX_ARCHIVE_BYTES_ENV_VAR, default=MAX_ARCHIVE_BYTES_DEFAULT)
    return value


class ArchiveBudget:
    """Decompressed bytes one archive may still produce, across all its members."""

    def __init__(self, archive: Path, limit: int | None = None) -> None:
        self.archive = archive
        self.limit = max_archive_bytes() if limit is None else limit
        self.used = 0

    def spend(self, n: int) -> None:
        self.used += n
        if self.used > self.limit:
            raise ValueError(
                f"{self.archive.name} decompresses to more than {self.limit} bytes; "
                f"raise {_MAX_ARCHIVE_BYTES_ENV_VAR} if the archive is genuine"
            )


def is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def copy_member(
    zf: zipfile.ZipFile, member: str | zipfile.ZipInfo, target: Path, budget: ArchiveBudget
) -> None:
    """Stream one member to `target`, charging `budget`; no partial file survives a failure."""
    try:
        with zf.open(member) as src, target.open("wb") as out:
            while chunk := src.read(_CHUNK_BYTES):
                budget.spend(len(chunk))
                out.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def extract_zip(src: Path, dest: Path) -> None:
    """Extract every regular member of `src` under `dest`.

    Directory and symlink members are skipped. Raises ValueError when a member
    path resolves outside `dest` or the archive inflates past the cap.
    """
    root = dest.resolve()
    budget = ArchiveBudget(src)
    with zipfile.ZipFile(src) as zf:
        for info in zf.infolist():
            if info.is_dir() or is_symlink(info):
                continue
            target = (root / info.filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"{src.name}: member {info.filename!r} escapes the extract folder")
            target.parent.mkdir(parents=True, exist_ok=True)
            copy_member(zf, info, target, budget)
