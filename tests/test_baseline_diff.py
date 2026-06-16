"""Binding test for `pagespeak.services._baseline_diff`.

The full diff behavior (run-record field deltas, section add/remove,
rename detection via body hash + Levenshtein, line-count rollup,
sort order, unknown-label error) is exercised in pf-core's
`test_pipeline_baseline_diff.py`. This module keeps the pagespeak
binding: `diff_baseline` reads/compares `.pagespeak-run.json` (not
pf-core's default `run.json`) and returns the structured `DiffReport`
re-exported via the shim.
"""

from __future__ import annotations

import json
from pathlib import Path

from pagespeak.services._baseline import (
    DiffReport,
    diff_baseline,
    save_baseline,
)


def _populate_live_output(out: Path, version: str = "0.1.1") -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "doc.md").write_text("# Doc\n\nBody.\n", encoding="utf-8")
    (out / "INDEX.md").write_text("# INDEX\n", encoding="utf-8")
    sections = out / "sections"
    sections.mkdir(exist_ok=True)
    (sections / "Intro.md").write_text("## Intro\n", encoding="utf-8")
    (out / ".pagespeak-run.json").write_text(
        json.dumps(
            {
                "version": version,
                "preset": "rag-default",
                "input": "doc.html",
                "section_count": 1,
                "image_count": 0,
                "resolved_flags": {"cleanup": "basic"},
                "started_at": "2026-05-10T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )


def test_diff_baseline_reads_pagespeak_run_record(tmp_path: Path) -> None:
    """Round-trip integration: save a baseline, mutate the live
    `.pagespeak-run.json`, diff. The reported field-change must surface
    — proving the shim wires both sides to the pagespeak-named file.
    """
    out = tmp_path / "out"
    _populate_live_output(out, version="0.1.0")
    save_baseline(out, label="v1")

    run_record = json.loads((out / ".pagespeak-run.json").read_text(encoding="utf-8"))
    run_record["version"] = "0.1.1"
    (out / ".pagespeak-run.json").write_text(json.dumps(run_record), encoding="utf-8")

    report = diff_baseline(out, label="v1")
    assert report.run_record.changed_fields == {"version": ("0.1.0", "0.1.1")}


def test_diff_report_dataclass_re_exported() -> None:
    """The shim re-exports `DiffReport` from pf-core so existing
    `from pagespeak.services._baseline import DiffReport` imports keep
    working. Construct one to confirm the schema is intact."""
    from pagespeak.services._baseline import (
        LineCountDelta,
        RunRecordDelta,
        SectionRename,
        SectionSetDelta,
    )

    report = DiffReport(
        baseline_label="v1",
        baseline_path=Path("/tmp/.baselines/v1"),
        current_path=Path("/tmp"),
        run_record=RunRecordDelta(changed_fields={}),
        sections=SectionSetDelta(added=[], removed=[], renamed=[]),
        body_changes=[],
    )
    assert report.baseline_label == "v1"
    # Touch unused symbols to keep the import smoke-check meaningful.
    _ = LineCountDelta(path="x.md", plus=0, minus=0)
    _ = SectionRename(old_path="a", new_path="b", similarity=1.0)
