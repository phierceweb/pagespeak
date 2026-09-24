"""Tests for cli/_audit.py — the `pagespeak audit` subcommand."""

from __future__ import annotations

import re
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


def test_audit_text_coverage_with_an_explicit_source(tmp_path: Path, monkeypatch) -> None:
    import pagespeak.services._audit as audit_mod
    from pagespeak.services._audit_checks import AuditFinding

    doc = tmp_path / "doc"
    _write(doc / "doc.raw.md", "# Doc\n\nbody\n")
    _write(doc / "doc.md", "# Doc\n\nbody\n")
    pdf = _write(tmp_path / "Doc Source.pdf", "%PDF-1.4\n")
    finding = AuditFinding(check="text_coverage", severity="warning", line=1, message="0.500 of x")
    monkeypatch.setattr(audit_mod, "check_text_coverage", lambda md, src: [finding])

    result = runner.invoke(app, ["audit", str(doc), "--text-coverage", "--source", str(pdf)])
    assert result.exit_code == 0, result.output  # a coverage finding is a warning
    assert "text_coverage" in result.output
    assert "text coverage: 1 doc(s) checked" in result.output


def test_audit_source_without_text_coverage_is_refused(tmp_path: Path) -> None:
    doc = tmp_path / "doc"
    _write(doc / "doc.md", "body\n")
    pdf = _write(tmp_path / "doc.pdf", "%PDF-1.4\n")
    result = runner.invoke(app, ["audit", str(doc), "--source", str(pdf)])
    assert result.exit_code != 0


def test_audit_source_needs_exactly_one_document(tmp_path: Path) -> None:
    """One source PDF cannot stand for several documents."""
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "a.md", "body\n")
    _write(b / "b.md", "body\n")
    pdf = _write(tmp_path / "a.pdf", "%PDF-1.4\n")
    result = runner.invoke(app, ["audit", str(a), str(b), "--text-coverage", "--source", str(pdf)])
    assert result.exit_code != 0


_RICH_DECORATION_RE = re.compile(r"\x1b\[[0-9;]*m|[│╭╮╰╯─┃┏┓┗┛━]")


def _plain(output: str) -> str:
    """The error text without rich's colour codes, borders and line wraps (CI forces colour)."""
    return re.sub(r"\s+", " ", _RICH_DECORATION_RE.sub(" ", output))


def test_audit_text_coverage_refuses_a_file_path(tmp_path: Path) -> None:
    """Coverage is measured per converted document folder; a file argument was
    skipped without a word, which reads as a pass."""
    doc = tmp_path / "doc"
    md = _write(doc / "doc.md", "body\n")
    _write(doc / "doc.raw.md", "body\n")
    pdf = _write(tmp_path / "doc.pdf", "%PDF-1.4\n")

    result = runner.invoke(app, ["audit", str(md), "--text-coverage"])
    assert result.exit_code == 2
    assert "rather than" in _plain(result.output)

    result = runner.invoke(app, ["audit", str(md), "--text-coverage", "--source", str(pdf)])
    assert result.exit_code == 2
    assert "document folder" in _plain(result.output)


def test_audit_source_refuses_a_folder_of_documents(tmp_path: Path) -> None:
    """One source PDF compared with every document under a parent folder."""
    _write(tmp_path / "out" / "a" / "a.md", "body\n")
    _write(tmp_path / "out" / "b" / "b.md", "body\n")
    pdf = _write(tmp_path / "a.pdf", "%PDF-1.4\n")
    result = runner.invoke(
        app, ["audit", str(tmp_path / "out"), "--text-coverage", "--source", str(pdf)]
    )
    assert result.exit_code == 2
    assert "document folder" in _plain(result.output)
