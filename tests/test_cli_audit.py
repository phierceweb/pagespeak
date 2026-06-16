"""Tests for cli/_audit.py — the `pagespeak audit` subcommand."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pagespeak.cli import app

runner = CliRunner()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_audit_clean_dir_exits_zero(tmp_path: Path) -> None:
    _write(tmp_path / "doc.md", "perfectly fine prose\n")
    result = runner.invoke(app, ["audit", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "0 errors" in result.output


def test_audit_defective_dir_exits_one_with_report(tmp_path: Path) -> None:
    _write(tmp_path / "doc.md", "T3 &lt; 34F and �\n")
    result = runner.invoke(app, ["audit", str(tmp_path)])
    assert result.exit_code == 1
    assert "html_entity" in result.output
    assert "replacement_char" in result.output
    assert "doc.md" in result.output


def test_audit_warnings_only_exits_zero(tmp_path: Path) -> None:
    body = "\n".join(f"## Important note:\n\nbody {i}\n" for i in range(5))
    _write(tmp_path / "doc.md", body)
    result = runner.invoke(app, ["audit", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "duplicate_heading" in result.output


def test_audit_multiple_paths_aggregate(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write(a / "doc.md", "x &lt; y\n")
    _write(b / "doc.md", "p � q\n")
    result = runner.invoke(app, ["audit", str(a), str(b)])
    assert result.exit_code == 1
    assert "2 errors" in result.output


def test_audit_summary_only_flag(tmp_path: Path) -> None:
    _write(tmp_path / "doc.md", "T3 &lt; 34F\n")
    result = runner.invoke(app, ["audit", str(tmp_path), "--summary-only"])
    assert result.exit_code == 1
    assert "html_entity" in result.output
    assert ":1 " not in result.output


def test_audit_missing_path_fails(tmp_path: Path) -> None:
    result = runner.invoke(app, ["audit", str(tmp_path / "nope")])
    assert result.exit_code != 0
