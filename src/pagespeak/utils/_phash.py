"""Perceptual-hash helpers — pf-core shim.

A thin re-export of `pf_core.utils.phash`, so pagespeak imports resolve
to the shared implementation.

The `ImageHash` + `Pillow` runtime deps come in via the
`pf-core[image-phash]` extra (declared in pagespeak's pyproject.toml).
"""

from __future__ import annotations

from pf_core.utils.phash import (
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
