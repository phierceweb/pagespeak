"""Tests for the `pagespeak verify` subcommand."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pagespeak.cli import app


@pytest.fixture(autouse=True)
def _outside_the_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify's source-PDF fallback is `conversions/in` under the working folder."""
    monkeypatch.chdir(tmp_path)


def _doc(root: Path, master: str) -> Path:
    root.mkdir(parents=True)
    (root / "book.md").write_text(master, encoding="utf-8")
    return root


def test_verify_prints_pass_and_exits_zero(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book", "# Book\n\nBody.\n")
    result = CliRunner().invoke(app, ["verify", str(root)])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("PASS  book")
    assert "1 document(s): 1 pass, 0 fail" in result.output


def test_verify_exits_one_on_a_failing_document(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book", "# Book\n\n![a](images/gone.png)\n")
    result = CliRunner().invoke(app, ["verify", str(root)])
    assert result.exit_code == 1
    assert "FAIL  book  1 failing: image_links 1" in result.output
    assert (root / ".pagespeak-verdict.md").is_file()


def test_verify_dot_in_a_document_reached_through_a_symlink_finds_its_source_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The working folder names the real path; the shell's $PWD keeps the `out` folder."""
    pytest.importorskip("pypdfium2")
    pytest.importorskip("fpdf")
    from pw_core.pipeline.run_record import file_sha256

    from tests.fixtures.pdf_pages import Page, body_lines, make_pdf

    real = _doc(tmp_path / "elsewhere" / "book", "# Book\n\nBody text.\n")
    (tmp_path / "conversions" / "in").mkdir(parents=True)
    pdf = make_pdf(
        tmp_path / "conversions" / "in" / "book.pdf",
        [Page(lines=body_lines(["Figure 1.1 The tower"]))],
    )
    identity = {"file": "book.pdf", "sha256": file_sha256(pdf)}
    (real / ".pagespeak-run.json").write_text(
        json.dumps({"resolved_flags": {}, "source_identity": identity}), encoding="utf-8"
    )
    link = tmp_path / "conversions" / "out" / "book"
    link.parent.mkdir(parents=True)
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.chdir(link)
    monkeypatch.setenv("PWD", str(link))
    result = CliRunner().invoke(app, ["verify", ".", "--no-delivery"])
    assert result.exit_code == 1, result.output
    assert "printed_titles" in result.output


def test_verify_names_a_folder_with_no_document(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    result = CliRunner().invoke(app, ["verify", str(tmp_path / "empty")])
    assert result.exit_code == 2
    assert "no converted document" in result.output
