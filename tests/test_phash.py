"""pagespeak's phash shim relies on pf-core's format allowlist for untrusted images."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from PIL import UnidentifiedImageError

from pagespeak.utils._phash import compute_phash


def _write_psd(path: Path) -> None:
    """8x8 grayscale PSD that Pillow's PSD plugin decodes when nothing restricts it."""
    header = b"8BPS" + struct.pack(">H6xHIIHH", 1, 1, 8, 8, 8, 1)
    path.write_bytes(header + bytes(12) + bytes(2) + bytes(range(0, 256, 4)))


def test_compute_phash_refuses_psd_named_png(tmp_path: Path) -> None:
    """A PSD inside a document never reaches Pillow's PSD decoder (pf-core 0.24.1 floor)."""
    target = tmp_path / "image1.png"
    _write_psd(target)
    with pytest.raises(UnidentifiedImageError):
        compute_phash(target)
