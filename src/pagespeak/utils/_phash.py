"""Perceptual-hash helpers — pw-core shim.

A thin re-export of `pw_core.utils.phash`, so pagespeak imports resolve
to the shared implementation.

`ImageHash` + `Pillow` are pagespeak's own dependencies, not pw-core's
`[image-phash]` extra (see the note in pyproject.toml).
"""

from __future__ import annotations

from pw_core.utils.phash import (
    cluster_phashes,
    compute_phash,
    detect_decoration_basenames,
    hamming_distance_hex,
)

__all__ = [
    "cluster_phashes",
    "compute_phash",
    "detect_decoration_basenames",
    "hamming_distance_hex",
]
