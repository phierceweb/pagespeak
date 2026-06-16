from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pagespeak.cli import app

runner = CliRunner()


def _populate_live_output(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "doc.md").write_text("# Doc", encoding="utf-8")
    (out / "INDEX.md").write_text("# INDEX", encoding="utf-8")
    (out / "sections").mkdir(exist_ok=True)
    (out / "sections" / "Intro.md").write_text("## Intro", encoding="utf-8")
    (out / ".pagespeak-run.json").write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "preset": "rag-default",
                "input": "doc.html",
                "section_count": 1,
                "image_count": 0,
                "started_at": "2026-05-10T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )


def test_baseline_save_default_label_succeeds(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _populate_live_output(out)

    result = runner.invoke(app, ["baseline", "save", str(out)])

    assert result.exit_code == 0, result.output
    bases = list((out / ".baselines").iterdir())
    assert len(bases) == 1
    assert (bases[0] / "doc.md").exists()


def test_baseline_save_explicit_label(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _populate_live_output(out)

    result = runner.invoke(app, ["baseline", "save", str(out), "--label", "corpus-final"])

    assert result.exit_code == 0
    assert (out / ".baselines" / "corpus-final" / "doc.md").exists()


def test_baseline_save_no_run_record_errors(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "doc.md").write_text("body")

    result = runner.invoke(app, ["baseline", "save", str(out)])

    assert result.exit_code != 0


def test_baseline_save_label_collision_errors(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _populate_live_output(out)

    runner.invoke(app, ["baseline", "save", str(out), "--label", "dup"])
    result = runner.invoke(app, ["baseline", "save", str(out), "--label", "dup"])

    assert result.exit_code != 0


def test_baseline_list_empty_dir(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()

    result = runner.invoke(app, ["baseline", "list", str(out)])

    assert result.exit_code == 0
    assert "no baselines" in result.output.lower()


def test_baseline_list_shows_saved_baselines(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _populate_live_output(out)

    runner.invoke(app, ["baseline", "save", str(out), "--label", "alpha"])
    runner.invoke(app, ["baseline", "save", str(out), "--label", "beta"])

    result = runner.invoke(app, ["baseline", "list", str(out)])

    assert result.exit_code == 0
    assert "alpha" in result.output
    assert "beta" in result.output
    assert "0.1.0" in result.output
    assert "rag-default" in result.output


def test_baseline_diff_unknown_label_errors(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _populate_live_output(out)

    result = runner.invoke(app, ["baseline", "diff", str(out), "nope"])

    assert result.exit_code != 0
    assert "no baseline labeled" in result.output


def test_baseline_diff_unchanged_prints_unchanged(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _populate_live_output(out)
    runner.invoke(app, ["baseline", "save", str(out), "--label", "v1"])

    result = runner.invoke(app, ["baseline", "diff", str(out), "v1"])

    assert result.exit_code == 0
    assert "Run record: unchanged" in result.output
    assert "Sections: unchanged" in result.output


def test_baseline_diff_section_added(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _populate_live_output(out)
    runner.invoke(app, ["baseline", "save", str(out), "--label", "v1"])
    (out / "sections" / "New.md").write_text("## New", encoding="utf-8")

    result = runner.invoke(app, ["baseline", "diff", str(out), "v1"])

    assert result.exit_code == 0
    assert "added" in result.output.lower()
    assert "New.md" in result.output


def test_baseline_diff_show_section_emits_unified_diff(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _populate_live_output(out)
    runner.invoke(app, ["baseline", "save", str(out), "--label", "v1"])
    (out / "sections" / "Intro.md").write_text("## Intro\n\nMODIFIED body.\n", encoding="utf-8")

    result = runner.invoke(app, ["baseline", "diff", str(out), "v1", "--show-section", "Intro.md"])

    assert result.exit_code == 0
    # Unified-diff markers.
    assert "---" in result.output
    assert "+++" in result.output
    assert "MODIFIED body" in result.output


def test_baseline_diff_show_consolidated_emits_unified_diff(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _populate_live_output(out)
    runner.invoke(app, ["baseline", "save", str(out), "--label", "v1"])
    (out / "doc.md").write_text("# Doc\n\nMODIFIED.\n", encoding="utf-8")

    result = runner.invoke(app, ["baseline", "diff", str(out), "v1", "--show-consolidated"])

    assert result.exit_code == 0
    assert "---" in result.output
    assert "+++" in result.output
    assert "MODIFIED" in result.output
