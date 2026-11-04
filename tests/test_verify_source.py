"""Tests for services._verify_source — finding the source PDF and running the checks that read it."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pw_core.pipeline.run_record import file_sha256

from pagespeak.services._source_map import read_source_map, write_source_map
from pagespeak.services._verify_doc import VerifyDoc
from pagespeak.services._verify_source import locate_pdf, source_checks
from tests.fixtures.pdf_pages import Page, body_lines, make_pdf

pytest.importorskip("pypdfium2")
pytest.importorskip("fpdf")

_SENTENCE = "The tower guides the passing ships at night."


def _doc(root: Path, master: str, identity: dict[str, str] | None = None) -> VerifyDoc:
    root.mkdir(parents=True, exist_ok=True)
    (root / "book.md").write_text(master, encoding="utf-8")
    if identity is not None:
        record = {"resolved_flags": {}, "source_identity": identity}
        (root / ".pagespeak-run.json").write_text(json.dumps(record), encoding="utf-8")
    return VerifyDoc(root, root / "book.md")


def _pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pages = [
        Page(
            lines=body_lines([_SENTENCE, "Figure 1.1 The tower"]),
            bookmark=(0, "Chapter 1 Tower"),
        ),
        Page(lines=body_lines(["Table 1.2 Lamps"]), bookmark=(1, "1.1 Lamps")),
    ]
    return make_pdf(path, pages)


def test_the_pdf_is_found_by_its_recorded_name_and_checksum(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "in" / "Some Folder" / "Harbour Light.pdf")
    doc = _doc(
        tmp_path / "out" / "harbour-light",
        "# A\n",
        {"file": "Harbour Light.pdf", "sha256": file_sha256(pdf)},
    )
    assert locate_pdf(doc, None, tmp_path / "in") == (pdf, "")


def test_a_recorded_name_with_brackets_is_matched_as_written(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "in" / "Harbour Light [2nd ed].pdf")
    doc = _doc(
        tmp_path / "out" / "book",
        "# A\n",
        {"file": "Harbour Light [2nd ed].pdf", "sha256": file_sha256(pdf)},
    )
    assert locate_pdf(doc, None, tmp_path / "in") == (pdf, "")


def test_a_recorded_absolute_input_is_looked_up_by_its_file_name(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "in" / "Harbour Light.pdf")
    doc = _doc(tmp_path / "out" / "book", "# A\n")
    record = {"resolved_flags": {}, "input": str(tmp_path / "elsewhere" / "Harbour Light.pdf")}
    (doc.root / ".pagespeak-run.json").write_text(json.dumps(record), encoding="utf-8")
    assert locate_pdf(doc, None, tmp_path / "in") == (pdf, "")


def test_a_pdf_with_another_checksum_is_not_the_source(tmp_path: Path) -> None:
    _pdf(tmp_path / "in" / "Harbour Light.pdf")
    doc = _doc(
        tmp_path / "out" / "harbour-light",
        "# A\n",
        {"file": "Harbour Light.pdf", "sha256": "0" * 64},
    )
    found, reason = locate_pdf(doc, None, tmp_path / "in")
    assert found is None and "SHA-256 differs" in reason


def test_a_docx_source_has_no_pdf(tmp_path: Path) -> None:
    doc = _doc(tmp_path / "out" / "deck", "# A\n", {"file": "deck.docx"})
    found, reason = locate_pdf(doc, None, tmp_path / "in")
    assert found is None and ".docx" in reason


def test_the_source_map_names_the_pdf(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "elsewhere" / "book.pdf")
    doc = _doc(tmp_path / "out" / "book", "# A\n")
    write_source_map(doc.root, pdf=pdf, pages=[(1, 2)], body=None, pictures=[])
    assert locate_pdf(doc, read_source_map(doc.root), tmp_path / "in") == (pdf.resolve(), "")


def test_a_map_pdf_replaced_since_the_build_is_not_the_source(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "elsewhere" / "book.pdf")
    doc = _doc(tmp_path / "out" / "book", "# A\n")
    write_source_map(doc.root, pdf=pdf, pages=[(1, 2)], body=None, pictures=[])
    make_pdf(pdf, [Page(lines=body_lines(["A later edition."]))])
    found, reason = locate_pdf(doc, read_source_map(doc.root), tmp_path / "in")
    assert found is None and "changed since the build" in reason


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads a file whatever its mode"
)
def test_a_map_pdf_that_cannot_be_read_is_reported_not_raised(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "elsewhere" / "book.pdf")
    doc = _doc(tmp_path / "out" / "book", "# A\n")
    write_source_map(doc.root, pdf=pdf, pages=[(1, 2)], body=None, pictures=[])
    pdf.chmod(0)
    try:
        found, reason = locate_pdf(doc, read_source_map(doc.root), tmp_path / "in")
    finally:
        pdf.chmod(0o644)
    assert found is None and "cannot be read" in reason


def test_a_map_pdf_that_moved_is_found_under_the_input_folder(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "elsewhere" / "book.pdf")
    doc = _doc(tmp_path / "out" / "book", "# A\n")
    write_source_map(doc.root, pdf=pdf, pages=[(1, 2)], body=None, pictures=[])
    moved = tmp_path / "in" / "Books" / "book.pdf"
    moved.parent.mkdir(parents=True)
    pdf.rename(moved)
    assert locate_pdf(doc, read_source_map(doc.root), tmp_path / "in") == (moved, "")


def test_source_checks_compare_titles_and_outline(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "in" / "book.pdf")
    master = f"# Chapter 1 Tower\n\n{_SENTENCE}\n\n![tower](images/h.png)\n\nFigure 1.1 The tower\n"
    doc = _doc(tmp_path / "out" / "book", master, {"file": "book.pdf", "sha256": file_sha256(pdf)})

    located = locate_pdf(doc, None, tmp_path / "in")
    results = {r.check: r for r in source_checks(doc, None, located)}

    assert [f.key for f in results["printed_titles"].findings] == [
        "printed_titles:missing:Table 1.2"
    ]
    assert [f.key for f in results["outline"].findings] == ["outline:missing:1.1 Lamps"]
    assert not results["outline"].findings[0].blocking


def test_without_a_pdf_the_checks_say_why(tmp_path: Path) -> None:
    doc = _doc(tmp_path / "out" / "book", "# A\n", {"file": "book.pdf"})
    results = source_checks(doc, None, locate_pdf(doc, None, tmp_path / "in"))
    assert [r.check for r in results] == [
        "printed_titles",
        "outline",
        "line_coverage",
        "line_joins",
        "picture_coverage",
    ]
    assert all(r.skipped and "no source PDF" in r.skipped for r in results)


def test_line_and_picture_checks_need_a_source_map(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "in" / "book.pdf")
    doc = _doc(tmp_path / "out" / "book", "# A\n", {"file": "book.pdf", "sha256": file_sha256(pdf)})
    located = locate_pdf(doc, None, tmp_path / "in")
    results = {r.check: r for r in source_checks(doc, None, located)}
    assert "no source map" in (results["line_coverage"].skipped or "")
    assert results["printed_titles"].ran


def test_with_a_source_map_every_check_runs(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "elsewhere" / "book.pdf")
    master = (
        f"# Chapter 1 Tower\n\n{_SENTENCE}\n\n![tower](images/h.png)\n\n"
        "Figure 1.1 The tower\n\n## 1.1 Lamps\n\nTable 1.2 Lamps\n"
    )
    doc = _doc(tmp_path / "out" / "book", master)
    write_source_map(doc.root, pdf=pdf, pages=[(1, 2)], body=(50.0, 760.0), pictures=[])
    smap = read_source_map(doc.root)
    results = source_checks(doc, smap, locate_pdf(doc, smap, tmp_path / "in"))
    assert all(r.ran for r in results)
    assert [f.key for r in results for f in r.findings] == []

    lost = _doc(doc.root, master.replace(_SENTENCE, ""))
    results = source_checks(lost, smap, locate_pdf(lost, smap, tmp_path / "in"))
    assert [f.key for r in results if r.check == "line_coverage" for f in r.findings] == [
        f"line_coverage:p1:{_SENTENCE}"
    ]
