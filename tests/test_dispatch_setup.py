"""Tests for `orchestrators/_dispatch_setup.prepare_output_dir`.

The output-dir preflight owns the two destructive steps in the pipeline —
cache invalidation and the auto-baseline that is the only copy taken before
it — so their ORDER is the contract, not an implementation detail.
"""

from __future__ import annotations

import json
from pathlib import Path

from pagespeak.orchestrators._dispatch_setup import prepare_output_dir


def _converted_dir(base: Path, *, version: str) -> Path:
    """An output dir shaped like a finished `--split-sections` conversion."""
    for name in ("doc.raw.md", "doc.cleaned.md", "doc.structured.md", "doc.md", "INDEX.md"):
        (base / name).write_text("x", encoding="utf-8")
    sections = base / "sections"
    sections.mkdir()
    (sections / "01-intro.md").write_text("# intro", encoding="utf-8")
    (base / ".pagespeak-run.json").write_text(
        json.dumps({"version": version, "input": "doc.pdf"}), encoding="utf-8"
    )
    return base


def test_baseline_is_taken_before_invalidation_deletes_sections(tmp_path: Path) -> None:
    """The auto-baseline exists to preserve the previous version's output across
    a destructive re-run. Invalidating first removes `sections/`, and pf-core
    skips a snapshot whose sections are gone — so the one run that needs the
    backup is exactly the run that never gets one."""
    import pagespeak

    out = _converted_dir(tmp_path, version="0.0.1-previous")
    assert pagespeak.__version__ != "0.0.1-previous"

    prepare_output_dir(
        out,
        None,
        qti_mode=False,
        rerun_from="cleanup",
        cross_refs="keep",
        cross_refs_was_default=False,
        allow_partial_ingest=False,
    )

    baselines = out / ".baselines"
    assert baselines.is_dir(), "no baseline taken before the destructive re-run"
    assert "0.0.1-previous" in [p.name for p in baselines.iterdir()]
    # …and the invalidation still happened.
    assert not (out / "sections").exists()


def test_no_baseline_when_the_version_is_unchanged(tmp_path: Path) -> None:
    """Snapshotting early must not start snapshotting on every ordinary re-run."""
    import pagespeak

    out = _converted_dir(tmp_path, version=pagespeak.__version__)
    prepare_output_dir(
        out,
        None,
        qti_mode=False,
        rerun_from="cleanup",
        cross_refs="keep",
        cross_refs_was_default=False,
        allow_partial_ingest=False,
    )
    assert not (out / ".baselines").exists()


def test_unknown_rerun_stage_is_rejected_before_anything_is_touched(tmp_path: Path) -> None:
    out = _converted_dir(tmp_path, version="0.0.1-previous")
    try:
        prepare_output_dir(
            out,
            None,
            qti_mode=False,
            rerun_from="not-a-stage",
            cross_refs="keep",
            cross_refs_was_default=False,
            allow_partial_ingest=False,
        )
    except ValueError as exc:
        assert "unknown rerun_from stage" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a bogus stage must raise")
    assert (out / "sections").exists(), "nothing may be deleted before the stage is validated"
