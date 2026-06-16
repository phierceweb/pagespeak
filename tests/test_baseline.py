"""Binding + integration tests for `pagespeak.services._baseline`.

The full behavior matrix (save copies manifest files, skips caches,
default label format, no-run-record error, collision error, list sort,
auto-snapshot skip/fire/dedupe rules) is exercised in pf-core's
`test_pipeline_baseline.py` against `BaselineConfig`-parameterized
filenames. This module keeps the pagespeak-specific bindings:

1. The shim passes `PAGESPEAK_BASELINE_CONFIG` (filename
   `.pagespeak-run.json`) so pf-core writes a pagespeak-shaped baseline.
2. `auto_snapshot_on_version_change` catches `OSError` / `ValueError`
   at the shim layer so test mocks that raise arbitrary errors don't
   kill the calling pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

from pagespeak.services._baseline import (
    auto_snapshot_on_version_change,
    list_baselines,
    save_baseline,
)


def _populate_live_output(out: Path, version: str = "0.1.1") -> None:
    """Live output dir shaped like a real `to_markdown()` result."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "doc.md").write_text("# Doc\n\nBody.\n", encoding="utf-8")
    (out / "INDEX.md").write_text("# INDEX\n", encoding="utf-8")
    (out / "sections").mkdir(exist_ok=True)
    (out / "sections" / "Intro.md").write_text("## Intro\n", encoding="utf-8")
    (out / ".pagespeak-run.json").write_text(
        json.dumps(
            {
                "version": version,
                "preset": "rag-default",
                "input": "doc.html",
                "section_count": 1,
                "image_count": 0,
                "started_at": "2026-05-10T00:00:00Z",
                "finished_at": "2026-05-10T00:00:01Z",
            }
        ),
        encoding="utf-8",
    )


def test_save_baseline_writes_pagespeak_run_record_filename(tmp_path: Path) -> None:
    """The shim binds `.pagespeak-run.json` — baseline's copy uses the
    same name, not pf-core's default `run.json`."""
    out = tmp_path / "out"
    _populate_live_output(out)

    save_baseline(out, label="v1")

    assert (out / ".baselines" / "v1" / ".pagespeak-run.json").exists()
    assert not (out / ".baselines" / "v1" / "run.json").exists()


def test_list_baselines_reads_pagespeak_run_record(tmp_path: Path) -> None:
    """`list_baselines` discovers labels by reading each baseline's
    `.pagespeak-run.json` (not `run.json`); ensures the binding flows
    through the read path too."""
    out = tmp_path / "out"
    _populate_live_output(out)
    save_baseline(out, label="alpha")

    records = list_baselines(out)
    assert [r.label for r in records] == ["alpha"]
    assert records[0].version == "0.1.1"


def test_auto_snapshot_fires_on_version_change(tmp_path: Path) -> None:
    """Integration check: an in-place version bump triggers an
    auto-snapshot, and the snapshot copy contains the pagespeak-shaped
    run record."""
    out = tmp_path / "out"
    _populate_live_output(out, version="0.1.0")
    auto_snapshot_on_version_change(out, current_version="0.1.1")

    base = out / ".baselines" / "0.1.0"
    assert base.exists()
    assert (base / ".pagespeak-run.json").exists()


def test_auto_snapshot_failure_is_non_fatal(tmp_path: Path, monkeypatch) -> None:
    """The shim adds a try/except so an arbitrary error from pf-core or
    a monkeypatched save_baseline doesn't propagate. Defense-in-depth on
    top of pf-core's own internal error handling."""
    out = tmp_path / "out"
    _populate_live_output(out, version="0.1.0")

    import pagespeak.services._baseline as baseline_mod

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(baseline_mod, "save_baseline", boom)

    # Must not raise.
    auto_snapshot_on_version_change(out, current_version="0.1.1")
