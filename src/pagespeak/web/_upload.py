"""Save an uploaded source into `conversions/in`, and nowhere else.

`in/` can hold symlinks into an upstream ingester's tree; writing through one
would overwrite that tree's source. A staged link or folder is never replaced,
the name must be a plain file name, and the bytes land in a temp file that is
swapped in only when complete and under the size cap.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import UploadFile

_CHUNK_BYTES = 1024 * 1024


class UploadRefused(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def upload_target(in_dir: Path, filename: str | None) -> Path:
    name = Path(filename or "").name
    if not name or name in {".", ".."} or name.startswith("."):
        raise UploadRefused(400, f"not a plain file name: {filename!r}")
    dest = in_dir / name
    if dest.is_symlink() or dest.is_dir():
        raise UploadRefused(409, f"{name} is already staged as a link or folder; remove it first")
    return dest


async def save_upload(file: UploadFile, dest: Path, *, max_bytes: int) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".upload-", suffix=".part")
    tmp = Path(tmp_name)
    try:
        written = 0
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(_CHUNK_BYTES):
                written += len(chunk)
                if written > max_bytes:
                    raise UploadRefused(413, f"upload larger than {max_bytes} bytes")
                out.write(chunk)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
