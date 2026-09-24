"""Tests for cli/_repair.py — the `pagespeak repair-tables` subcommand.

The Docling page-ingest + PDF page-locate I/O is patched so the test runs with
no real Docling / PDF.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from pagespeak.cli import app

runner = CliRunner()

_MEGA = "<br>".join(["Alpha Profile", "Oracle", ".aaa", "Beta File", "Redis", ".bbb"] * 8)
_GRID = (
    "| Profile | Database | Ext |\n| --- | --- | --- |\n"
    "| Alpha Profile | Oracle | .aaa |\n| Beta File | Redis | .bbb |\n"
)


def _make_outdir(tmp_path: Path) -> Path:
    out = tmp_path / "mydoc"
    out.mkdir()
    (out / "mydoc.raw.md").write_text(
        f"# Doc\n\n| {_MEGA} |  |  |\n| --- | --- | --- |\n|  |  |  |\n\ntail\n",
        encoding="utf-8",
    )
    return out


def test_repair_tables_splices_and_patches(tmp_path: Path) -> None:
    out = _make_outdir(tmp_path)
    src = tmp_path / "mydoc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    with (
        patch("pagespeak.services._table_repair.locate_pages_in_pdf", return_value=[4]),
        patch("pagespeak.services._table_repair.docling_page_md", return_value=_GRID),
    ):
        result = runner.invoke(app, ["repair-tables", str(out), "--source", str(src)])
    assert result.exit_code == 0, result.output
    assert "repaired 1/1" in result.output
    patched = (out / "mydoc.raw.md").read_text()
    assert "Profile<br>Oracle" not in patched  # blob gone
    assert "| Alpha Profile | Oracle | .aaa |" in patched  # grid in


def test_repair_tables_splices_a_split_table(tmp_path: Path) -> None:
    """The standalone command repairs SPLIT multi-line-cell tables too, not just
    `<br>` collapses — regression for the gap where `cli/_repair.py` only wired
    the collapsed path while the inline `convert --repair-tables` did both."""
    out = tmp_path / "splitdoc"
    out.mkdir()
    (out / "splitdoc.raw.md").write_text(
        "# Doc\n\n| Key | Value |\n| --- | --- |\n"
        "| Alpha | first part of |\n|  | a wrapped value |\n| Beta | short |\n\ntail\n",
        encoding="utf-8",
    )
    src = tmp_path / "splitdoc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    merged = (
        "| Key | Value |\n| --- | --- |\n"
        "| Alpha | first part of a wrapped value |\n| Beta | short |\n"
    )
    # repair_tables_in_markdown wires the module-level I/O — patch it there.
    with (
        patch("pagespeak.services._table_repair.locate_pages_in_pdf", return_value=[2]),
        patch(
            "pagespeak.services._table_repair.docling_page_md", return_value=f"page\n\n{merged}\n"
        ),
    ):
        result = runner.invoke(app, ["repair-tables", str(out), "--source", str(src)])
    assert result.exit_code == 0, result.output
    patched = (out / "splitdoc.raw.md").read_text()
    assert "| Alpha | first part of a wrapped value |" in patched  # split cell merged
    assert "|  | a wrapped value |" not in patched  # continuation row gone


def test_repair_tables_dry_run_does_not_write(tmp_path: Path) -> None:
    out = _make_outdir(tmp_path)
    src = tmp_path / "mydoc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    original = (out / "mydoc.raw.md").read_text()
    with (
        patch("pagespeak.services._table_repair.locate_pages_in_pdf", return_value=[4]),
        patch("pagespeak.services._table_repair.docling_page_md", return_value=_GRID),
    ):
        result = runner.invoke(app, ["repair-tables", str(out), "--source", str(src), "--dry-run"])
    assert result.exit_code == 0
    assert "dry-run" in result.output
    assert (out / "mydoc.raw.md").read_text() == original  # untouched


def test_repair_tables_no_collapse_is_noop(tmp_path: Path) -> None:
    out = tmp_path / "clean"
    out.mkdir()
    (out / "clean.raw.md").write_text("# Doc\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n")
    result = runner.invoke(app, ["repair-tables", str(out)])
    assert result.exit_code == 0
    assert "no repairable tables" in result.output


def test_repair_tables_missing_source_errors(tmp_path: Path) -> None:
    out = _make_outdir(tmp_path)  # has a collapse but no findable source PDF
    result = runner.invoke(app, ["repair-tables", str(out)])
    assert result.exit_code == 1
    assert "no source PDF" in result.output


def test_repair_tables_no_raw_checkpoint_errors(tmp_path: Path) -> None:
    out = tmp_path / "empty"
    out.mkdir()
    result = runner.invoke(app, ["repair-tables", str(out)])
    assert result.exit_code == 1
    assert "no <stem>.raw.md" in result.output
