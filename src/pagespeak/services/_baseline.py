"""Baseline snapshots — preserve a result for later comparison.

Thin shim over `pf_core.pipeline.baseline`. A baseline copies the result
artifacts (consolidated md, sections, INDEX.md, run record) from a live
output dir into a labeled subdirectory under
`<output_dir>/.baselines/<label>/`. Cache files (raw.md, vision-cache,
etc.) are NOT copied; they're shared with the live output and reused on
re-run.

Two entry points:

1. `save_baseline()` — explicit, called via `pagespeak baseline save`.
2. `auto_snapshot_on_version_change()` — implicit, called from
   `to_markdown()` when the previous run.json's version differs from
   the current `__version__`.

Binds the pagespeak-specific filename (`.pagespeak-run.json`) and
preserves the public API.

Internal API: imported by `orchestrators/_dispatch.py` and
`cli/_baseline.py`. Not re-exported from `pagespeak.__init__`.
"""

from __future__ import annotations

from pathlib import Path

from pf_core.pipeline.baseline import (
    BaselineConfig,
    BaselineRecord,
)
from pf_core.pipeline.baseline import (
    auto_snapshot_on_version_change as _auto_snapshot_on_version_change,
)
from pf_core.pipeline.baseline import (
    list_baselines as _list_baselines,
)
from pf_core.pipeline.baseline import (
    save_baseline as _save_baseline,
)

# Internal constants preserved for backward compatibility — referenced by
# `cli/_baseline.py` (uses `_SECTIONS_DIR` for unified-diff paths) and by
# `services/_baseline_diff.py` (legacy import path).
_RUN_RECORD = ".pagespeak-run.json"
_INDEX_FILE = "INDEX.md"
_SECTIONS_DIR = "sections"

PAGESPEAK_BASELINE_CONFIG = BaselineConfig(run_record_filename=_RUN_RECORD)


def save_baseline(output_dir: Path, *, label: str | None = None) -> BaselineRecord:
    """Snapshot the current live output into `.baselines/<label>/`."""
    return _save_baseline(output_dir, label=label, config=PAGESPEAK_BASELINE_CONFIG)


def list_baselines(output_dir: Path) -> list[BaselineRecord]:
    """Return all baselines in `<output_dir>/.baselines/` sorted by saved-at desc."""
    records: list[BaselineRecord] = _list_baselines(output_dir, config=PAGESPEAK_BASELINE_CONFIG)
    return records


def auto_snapshot_on_version_change(
    output_dir: Path, *, current_version: str
) -> BaselineRecord | None:
    """Snapshot the previous output into `.baselines/<previous-version>/`
    when the previous run.json's version differs from `current_version`.

    Failures are swallowed at this shim layer so a partially-mocked
    pf-core internal can't kill the calling pipeline — matches the
    documented contract.
    """
    try:
        return _auto_snapshot_on_version_change(
            output_dir,
            current_version=current_version,
            config=PAGESPEAK_BASELINE_CONFIG,
        )
    except (OSError, ValueError):
        # Defense in depth — pf-core already catches these internally,
        # but tests patch `save_baseline` to raise arbitrary errors.
        return None


# Re-export the diff API for backward compatibility. The diff
# bits live in `_baseline_diff.py`; existing
# `from pagespeak.services._baseline import diff_baseline` imports
# (notably `cli/_baseline.py` and `tests/test_baseline_diff.py`)
# keep working unchanged.
from ._baseline_diff import (  # noqa: E402
    DiffReport,
    LineCountDelta,
    RunRecordDelta,
    SectionRename,
    SectionSetDelta,
    diff_baseline,
)

__all__ = [
    "BaselineConfig",
    "BaselineRecord",
    "DiffReport",
    "LineCountDelta",
    "PAGESPEAK_BASELINE_CONFIG",
    "RunRecordDelta",
    "SectionRename",
    "SectionSetDelta",
    "auto_snapshot_on_version_change",
    "diff_baseline",
    "list_baselines",
    "save_baseline",
]
