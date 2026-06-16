"""Baseline diff — compare a saved baseline against the live output.

Thin shim over `pf_core.pipeline.baseline_diff`. Returns a structured
`DiffReport` covering:

1. Run-record field-level diff (dotted paths into `.pagespeak-run.json`).
2. Section filename set diff (added / removed / renamed).
3. Per-section line-count rollup for files present on both sides.

Rename detection is conservative: exact body sha256 match (similarity
1.0) OR same-folder + Levenshtein basename ≤ 4 + body similarity ≥ 0.8.

Binds the pagespeak-specific filename (`.pagespeak-run.json`) and
preserves the public API.

Internal API: imported by `services/_baseline.py` (which re-exports its
public surface for backward compatibility) and by `cli/_baseline.py`.
Not re-exported from `pagespeak.__init__`.
"""

from __future__ import annotations

from pathlib import Path

from pf_core.pipeline.baseline_diff import (
    DiffReport,
    LineCountDelta,
    RunRecordDelta,
    SectionRename,
    SectionSetDelta,
)
from pf_core.pipeline.baseline_diff import (
    diff_baseline as _diff_baseline,
)


def diff_baseline(output_dir: Path, *, label: str) -> DiffReport:
    """Compare `<output_dir>/.baselines/<label>/` to the current live output."""
    # Lazy import to break the import cycle with `_baseline.py`
    # (`_baseline.py` re-exports from this module).
    from ._baseline import PAGESPEAK_BASELINE_CONFIG

    return _diff_baseline(output_dir, label=label, config=PAGESPEAK_BASELINE_CONFIG)


__all__ = [
    "DiffReport",
    "LineCountDelta",
    "RunRecordDelta",
    "SectionRename",
    "SectionSetDelta",
    "diff_baseline",
]
