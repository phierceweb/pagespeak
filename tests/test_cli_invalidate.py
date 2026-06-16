from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pagespeak.cli import app

runner = CliRunner()


def _populate_with_run_record(out: Path, stem: str = "doc") -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.raw.md").write_text("raw")
    (out / "sections").mkdir()
    (out / "sections" / "Intro.md").write_text("# Intro")
    (out / "INDEX.md").write_text("# INDEX")
    (out / ".pagespeak-run.json").write_text(
        json.dumps({"input": f"{stem}.html", "version": "0.1.0"})
    )


def test_invalidate_split_deletes_sections_and_index(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _populate_with_run_record(out)

    result = runner.invoke(app, ["invalidate", str(out), "split"])

    assert result.exit_code == 0, result.output
    assert not (out / "sections").exists()
    assert not (out / "INDEX.md").exists()
    assert (out / "doc.raw.md").exists(), "backend cache preserved"


def test_invalidate_unknown_stage_errors(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _populate_with_run_record(out)

    result = runner.invoke(app, ["invalidate", str(out), "bogus"])

    assert result.exit_code != 0
    assert "must be one of" in result.output or "must be one of" in str(result.exception)


def test_invalidate_no_run_record_with_no_stem_errors(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "doc.raw.md").write_text("raw")

    result = runner.invoke(app, ["invalidate", str(out), "ingest"])

    assert result.exit_code != 0


def test_invalidate_explicit_source_stem(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "mydoc.raw.md").write_text("raw")
    (out / "sections").mkdir()

    result = runner.invoke(app, ["invalidate", str(out), "split", "--source-stem", "mydoc"])

    assert result.exit_code == 0
    assert not (out / "sections").exists()
    assert (out / "mydoc.raw.md").exists()


def test_invalidate_empty_dir_silent_noop(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _populate_with_run_record(out)
    # Wipe everything but the run record.
    (out / "sections" / "Intro.md").unlink()
    (out / "sections").rmdir()
    (out / "INDEX.md").unlink()

    result = runner.invoke(app, ["invalidate", str(out), "split"])

    assert result.exit_code == 0
    assert "no caches to invalidate" in result.output
