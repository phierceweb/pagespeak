"""Tests for services._verify — running every check, and the deliver gate."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pw_foundation.exceptions import InvalidInputError, PreconditionError

from pagespeak.services import _verify
from pagespeak.services._verify import fingerprint, require_deliverable, verify_paths
from pagespeak.services._verify_doc import VerifyDoc


@pytest.fixture(autouse=True)
def _outside_the_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The source-PDF fallback is `conversions/in` under the working folder."""
    monkeypatch.chdir(tmp_path)


def _doc(root: Path, master: str = "# Book\n\nBody text.\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "book.md").write_text(master, encoding="utf-8")
    (root / "book.raw.md").write_text(master, encoding="utf-8")
    return root


_not_as_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads a file whatever its mode"
)


def _accept(root: Path, key: str) -> None:
    accepted = {"accepted": [{"key": key, "why": "checked by hand"}]}
    (root / ".pagespeak-accepted.json").write_text(json.dumps(accepted), encoding="utf-8")


def test_a_clean_document_passes_and_gets_a_verdict_file(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    (verdict,) = verify_paths([root])
    assert verdict.passed
    assert (
        (root / ".pagespeak-verdict.md")
        .read_text(encoding="utf-8")
        .startswith("# Verify: book — PASS")
    )


def test_a_missing_picture_fails_until_accepted(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book", "# Book\n\n![a](images/gone.png)\n")
    (verdict,) = verify_paths([root])
    assert [f.key for f in verdict.failing] == ["image_links:book.md:images/gone.png"]

    _accept(root, "image_links:book.md:images/gone.png")
    (verdict,) = verify_paths([root])
    assert verdict.passed


def test_a_broken_accept_list_fails_the_document(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    (root / ".pagespeak-accepted.json").write_text("{", encoding="utf-8")
    (verdict,) = verify_paths([root])
    assert [f.check for f in verdict.failing] == ["accepted_list"]


def test_a_folder_with_no_document_is_an_input_error(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(InvalidInputError):
        verify_paths([tmp_path / "empty"])


def test_every_path_is_checked_before_any_verdict_is_written(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    (tmp_path / "empty").mkdir()
    with pytest.raises(InvalidInputError):
        verify_paths([root, tmp_path / "empty"])
    assert not (root / ".pagespeak-verdict.md").exists()


def test_an_accepted_unreadable_map_fails_again_once_it_changes(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    (root / ".pagespeak-source-map.json").write_text("{", encoding="utf-8")
    (verdict,) = verify_paths([root])
    (key,) = [f.key for f in verdict.failing]
    _accept(root, key)
    (root / ".pagespeak-source-map.json").write_text('{"pdf": 5}', encoding="utf-8")
    (verdict,) = verify_paths([root])
    assert [f.check for f in verdict.failing] == ["source_map"]


def test_the_fingerprint_follows_the_output_and_the_accept_list(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    doc = VerifyDoc(root, root / "book.md")
    first = fingerprint(doc, None)
    assert fingerprint(doc, None) == first
    _accept(root, "x:y")
    assert fingerprint(doc, None) != first
    second = fingerprint(doc, None)
    (root / "book.md").write_text("# Book\n\nOther text.\n", encoding="utf-8")
    assert fingerprint(doc, None) != second


@pytest.mark.parametrize(
    "path",
    ["sections/One.md", "images/a.png", ".pagespeak-run.json", ".pagespeak-source-map.json"],
)
def test_the_fingerprint_follows_each_file_a_verdict_reads(tmp_path: Path, path: str) -> None:
    root = _doc(tmp_path / "book")
    doc = VerifyDoc(root, root / "book.md")
    first = fingerprint(doc, None)
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text("{}", encoding="utf-8")
    assert fingerprint(doc, None) != first


def test_the_fingerprint_ignores_dot_files_deliver_leaves_out(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    (root / "images").mkdir()
    doc = VerifyDoc(root, root / "book.md")
    first = fingerprint(doc, None)
    (root / "images" / ".DS_Store").write_bytes(b"\0\0\0\1Bud1")
    assert fingerprint(doc, None) == first


def test_the_gate_rechecks_a_document_changed_since_its_pass(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    (verdict,) = verify_paths([root])
    assert verdict.passed
    (root / "book.md").write_text("# Book\n\n![a](images/gone.png)\n", encoding="utf-8")
    with pytest.raises(PreconditionError, match="image_links"):
        require_deliverable(root)


def test_the_fingerprint_follows_the_titles_the_caption_check_reads(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    doc = VerifyDoc(root, root / "book.md")
    first = fingerprint(doc, None)
    (root / "book.raw.md").write_text("# Book\n\n![Table 7.3](images/a.png)\n", encoding="utf-8")
    assert fingerprint(doc, None) != first


def test_the_fingerprint_follows_the_source_pdfs_bytes_not_its_spelling(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    doc = VerifyDoc(root, root / "book.md")
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4 the first printing")
    first = fingerprint(doc, pdf)
    assert fingerprint(doc, Path("book.pdf")) == first
    pdf.write_bytes(b"%PDF-1.4 a second printing")
    assert fingerprint(doc, pdf) != first


@_not_as_root
def test_a_source_pdf_that_cannot_be_read_counts_as_none_found(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    doc = VerifyDoc(root, root / "book.md")
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    pdf.chmod(0)
    try:
        assert fingerprint(doc, pdf) == fingerprint(doc, None)
    finally:
        pdf.chmod(0o644)


def test_the_fingerprint_follows_the_dropped_ink_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _doc(tmp_path / "book")
    doc = VerifyDoc(root, root / "book.md")
    monkeypatch.setenv("PAGESPEAK_VERIFY_MIN_DROPPED_INK", "150")
    first = fingerprint(doc, None)
    monkeypatch.setenv("PAGESPEAK_VERIFY_MIN_DROPPED_INK", "100000000")
    assert fingerprint(doc, None) != first


def test_the_gate_refuses_a_failing_document_and_names_its_verdict(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book", "# Book\n\n![a](images/gone.png)\n")
    with pytest.raises(PreconditionError) as refused:
        require_deliverable(root)
    assert "book" in str(refused.value)
    assert ".pagespeak-verdict.md" in str(refused.value)


def test_the_gate_refuses_a_folder_holding_two_masters(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book")
    (root / "book.orig.md").write_text("# Old\n", encoding="utf-8")
    with pytest.raises(PreconditionError, match="more than one master"):
        require_deliverable(root)


def test_the_gate_passes_a_clean_export(tmp_path: Path) -> None:
    export = tmp_path / "exams"
    _doc(export / "exam-1")
    _doc(export / "exam-2")
    require_deliverable(export)


def test_the_gate_reuses_a_verdict_while_the_document_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _doc(tmp_path / "book")
    verify_paths([root])

    def _no_rerun(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("re-verified an unchanged document")

    monkeypatch.setattr(_verify, "verify_document", _no_rerun)
    require_deliverable(root)


def _titled_source(root: Path, pdf_dir: Path) -> None:
    """A source PDF under `pdf_dir`, recorded for `root`, printing a title its master lacks."""
    pytest.importorskip("pypdfium2")
    pytest.importorskip("fpdf")
    from pw_core.pipeline.run_record import file_sha256

    from tests.fixtures.pdf_pages import Page, body_lines, make_pdf

    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf = make_pdf(pdf_dir / "book.pdf", [Page(lines=body_lines(["Figure 1.1 The tower"]))])
    identity = {"file": "book.pdf", "sha256": file_sha256(pdf)}
    record = {"resolved_flags": {}, "source_identity": identity}
    (root / ".pagespeak-run.json").write_text(json.dumps(record), encoding="utf-8")


def test_the_gate_rechecks_a_pass_made_before_the_source_pdf_was_found(tmp_path: Path) -> None:
    root = _doc(tmp_path / "out" / "book")
    _titled_source(root, tmp_path / "in")
    (verdict,) = verify_paths([root], in_dir=tmp_path / "elsewhere")
    assert verdict.passed

    with pytest.raises(PreconditionError, match="printed_titles"):
        require_deliverable(root, in_dir=tmp_path / "in")


def test_the_source_pdf_is_looked_for_beside_the_out_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _doc(tmp_path / "conversions" / "out" / "book")
    _titled_source(root, tmp_path / "conversions" / "in" / "Books")
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    (verdict,) = verify_paths([root])
    assert [f.check for f in verdict.failing] == ["printed_titles"]


@_not_as_root
def test_a_recorded_source_pdf_that_cannot_be_read_is_reported_not_raised(tmp_path: Path) -> None:
    root = _doc(tmp_path / "out" / "book")
    _titled_source(root, tmp_path / "in")
    pdf = tmp_path / "in" / "book.pdf"
    pdf.chmod(0)
    try:
        (verdict,) = verify_paths([root], in_dir=tmp_path / "in")
        require_deliverable(root, in_dir=tmp_path / "in")
    finally:
        pdf.chmod(0o644)
    skipped = {r.check: r.skipped for r in verdict.results if r.skipped}
    assert "could not read book.pdf" in skipped["printed_titles"]


def test_a_stored_verdict_with_no_failing_list_is_rechecked(tmp_path: Path) -> None:
    root = _doc(tmp_path / "book", "# Book\n\n![a](images/gone.png)\n")
    verify_paths([root], in_dir=tmp_path / "in")
    stored_file = root / ".pagespeak-verdict.json"
    stored = json.loads(stored_file.read_text(encoding="utf-8"))
    stored_file.write_text(json.dumps({**stored, "failing": None}), encoding="utf-8")
    with pytest.raises(PreconditionError, match="image_links"):
        require_deliverable(root, in_dir=tmp_path / "in")


def test_the_gate_ignores_a_stale_delivery(tmp_path: Path) -> None:
    """Delivering is how a stale delivery gets fixed, so it cannot block delivery."""
    root = _doc(tmp_path / "out" / "book")
    stale = tmp_path / "delivery" / "book"
    stale.mkdir(parents=True)
    (stale / "book.md").write_text("# Old\n", encoding="utf-8")
    (verdict,) = verify_paths([root])
    assert [f.check for f in verdict.failing] == ["delivery_match"]
    require_deliverable(root)
