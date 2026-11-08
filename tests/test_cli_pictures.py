"""Tests for cli._pictures."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pagespeak.cli import app

runner = CliRunner()


def test_pictures_prints_a_summary_and_writes_the_sheet(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    from PIL import Image

    root = tmp_path / "doc"
    (root / "images").mkdir(parents=True)
    Image.new("L", (30, 30)).save(root / "images" / "a.png")
    (root / "doc.md").write_text("# Doc\n\n![User-added image](images/a.png)\n", encoding="utf-8")
    result = runner.invoke(app, ["pictures", str(root), "--in-dir", str(tmp_path / "in")])
    assert result.exit_code == 0, result.output
    assert "doc: 1 picture in the text" in result.output
    assert "images/a.png  'User-added image'" in result.output
    assert (root / ".pagespeak-pictures.html").is_file()


def test_pictures_refuses_a_folder_with_no_document(tmp_path: Path) -> None:
    result = runner.invoke(app, ["pictures", str(tmp_path)])
    assert result.exit_code == 2
    assert "no converted document" in result.output


def test_pictures_dot_through_a_symlink_looks_beside_its_out_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "elsewhere" / "doc"
    real.mkdir(parents=True)
    (real / "doc.md").write_text("# Doc\n", encoding="utf-8")
    (real / ".pagespeak-run.json").write_text('{"source_identity": {"file": "doc.pdf"}}')
    (tmp_path / "conversions" / "in").mkdir(parents=True)
    link = tmp_path / "conversions" / "out" / "doc"
    link.parent.mkdir(parents=True)
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.chdir(link)
    monkeypatch.setenv("PWD", str(link))
    result = runner.invoke(app, ["pictures", "."])
    assert result.exit_code == 0, result.output
    assert f"no source PDF found under {tmp_path / 'conversions' / 'in'}" in result.output


def test_pictures_reports_each_document_once(tmp_path: Path) -> None:
    root = tmp_path / "out"
    doc = root / "doc"
    doc.mkdir(parents=True)
    (doc / "doc.md").write_text("# Doc\n", encoding="utf-8")
    result = runner.invoke(app, ["pictures", str(root), str(doc), "--in-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert result.output.count("doc: 0 pictures in the text") == 1
