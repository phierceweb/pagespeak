"""Tests for the delivery-strip service + `pagespeak deliver` CLI command."""

from __future__ import annotations

from pathlib import Path

import pytest
from pw_foundation.exceptions import PreconditionError
from typer.testing import CliRunner

from pagespeak.cli import app
from pagespeak.services._deliver import deliver, is_delivered, strip_for_delivery

_MASTER = "# Exam\n\n## Question 001\n\nq1\n"


@pytest.fixture(autouse=True)
def _outside_the_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify's source-PDF fallback is `conversions/in` under the working folder."""
    monkeypatch.chdir(tmp_path)


def _make_doc(doc_dir: Path, stem: str) -> None:
    """A converted document dir: master .md + stage checkpoints + run record
    + images/ + sections/ + vision cache."""
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{stem}.md").write_text(_MASTER, encoding="utf-8")
    for stage in ("raw", "cleaned", "normalized", "repaired", "visioned"):
        (doc_dir / f"{stem}.{stage}.md").write_text(f"{stage}\n", encoding="utf-8")
    (doc_dir / ".pagespeak-run.json").write_text("{}\n", encoding="utf-8")
    (doc_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
    (doc_dir / "images").mkdir()
    (doc_dir / "images" / "fig.png").write_bytes(b"\x89PNG\r\n")
    (doc_dir / "sections").mkdir()
    (doc_dir / "sections" / "Question 001.md").write_text(
        "## Question 001\n\nq1\n", encoding="utf-8"
    )
    (doc_dir / "sections" / "INDEX.md").write_text("idx\n", encoding="utf-8")
    (doc_dir / ".vision-cache").mkdir()
    (doc_dir / ".vision-cache" / "abc.json").write_text("{}\n", encoding="utf-8")


def test_strip_keeps_deliverables_drops_working_files(tmp_path: Path) -> None:
    src = tmp_path / "out" / "Exam 1"
    _make_doc(src, "Exam 1")
    dest = tmp_path / "delivery" / "Exam 1"

    result = strip_for_delivery(src, dest)

    # kept
    assert (dest / "Exam 1.md").read_text(encoding="utf-8") == _MASTER
    assert (dest / "images" / "fig.png").exists()
    assert (dest / "sections" / "Question 001.md").exists()
    assert (dest / "sections" / "INDEX.md").exists()
    # dropped: every stage checkpoint
    for stage in ("raw", "cleaned", "normalized", "repaired", "visioned"):
        assert not (dest / f"Exam 1.{stage}.md").exists()
    # dropped: run record, manifest, cache
    assert not (dest / ".pagespeak-run.json").exists()
    assert not (dest / "manifest.json").exists()
    assert not (dest / ".vision-cache").exists()
    assert result.documents == 1


def test_strip_leaves_out_dot_file_markdown(tmp_path: Path) -> None:
    """A verify verdict sits beside the master as a dot-file; it is not a document."""
    src = tmp_path / "out" / "Exam 1"
    _make_doc(src, "Exam 1")
    (src / ".pagespeak-verdict.md").write_text("# Verify\n", encoding="utf-8")
    dest = tmp_path / "delivery" / "Exam 1"

    result = strip_for_delivery(src, dest)

    assert not (dest / ".pagespeak-verdict.md").exists()
    assert result.documents == 1


def test_strip_file_count_is_deliverables_only(tmp_path: Path) -> None:
    src = tmp_path / "out" / "Exam 1"
    _make_doc(src, "Exam 1")
    result = strip_for_delivery(src, tmp_path / "delivery" / "Exam 1")
    # master(1) + images/fig.png(1) + sections/{Question 001.md, INDEX.md}(2)
    assert result.files == 4


def test_strip_mirrors_export_fanout(tmp_path: Path) -> None:
    src = tmp_path / "out" / "export"
    _make_doc(src / "Exam 1", "Exam 1")
    _make_doc(src / "Exam 2", "Exam 2")
    dest = tmp_path / "delivery" / "export"

    result = strip_for_delivery(src, dest)

    assert (dest / "Exam 1" / "Exam 1.md").exists()
    assert (dest / "Exam 2" / "Exam 2.md").exists()
    assert (dest / "Exam 1" / "sections" / "INDEX.md").exists()
    assert not (dest / "Exam 1" / "Exam 1.raw.md").exists()
    assert result.documents == 2


def test_strip_replaces_stale_delivery(tmp_path: Path) -> None:
    src = tmp_path / "out" / "Exam 1"
    _make_doc(src, "Exam 1")
    dest = tmp_path / "delivery" / "Exam 1"
    # pre-existing stale delivery (a question that no longer exists upstream)
    (dest / "sections").mkdir(parents=True)
    (dest / "sections" / "Question 099.md").write_text("stale\n", encoding="utf-8")
    (dest / "old.md").write_text("stale\n", encoding="utf-8")

    strip_for_delivery(src, dest)

    assert not (dest / "sections" / "Question 099.md").exists()
    assert not (dest / "old.md").exists()
    assert (dest / "sections" / "Question 001.md").exists()


def test_strip_does_not_modify_source(tmp_path: Path) -> None:
    src = tmp_path / "out" / "Exam 1"
    _make_doc(src, "Exam 1")
    strip_for_delivery(src, tmp_path / "delivery" / "Exam 1")
    assert (src / "Exam 1.raw.md").exists()
    assert (src / ".vision-cache" / "abc.json").exists()


def test_strip_refuses_destination_containing_source(tmp_path: Path) -> None:
    """An ancestor dest would rmtree the source tree — and everything beside it."""
    src = tmp_path / "conversions" / "out"
    _make_doc(src / "Exam 1", "Exam 1")
    staged = tmp_path / "conversions" / "in" / "source.pdf"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"%PDF-1.4")

    with pytest.raises(ValueError, match="outside the source tree"):
        strip_for_delivery(src, tmp_path / "conversions")

    assert staged.exists()
    assert (src / "Exam 1" / "Exam 1.md").exists()
    assert (src / "Exam 1" / ".vision-cache" / "abc.json").exists()


def test_strip_refuses_destination_inside_source(tmp_path: Path) -> None:
    """A dest nested in the source would delete part of it and re-copy itself."""
    src = tmp_path / "out"
    _make_doc(src / "Exam 1", "Exam 1")

    with pytest.raises(ValueError, match="outside the source tree"):
        strip_for_delivery(src, src / "delivery")

    assert (src / "Exam 1" / "Exam 1.md").exists()


def test_deliver_cmd_infers_delivery_dir(tmp_path: Path) -> None:
    src = tmp_path / "conversions" / "out" / "export"
    _make_doc(src / "Exam 1", "Exam 1")

    result = CliRunner().invoke(app, ["deliver", str(src)])

    assert result.exit_code == 0, result.output
    dest = tmp_path / "conversions" / "delivery" / "export"
    assert (dest / "Exam 1" / "Exam 1.md").exists()
    assert not (dest / "Exam 1" / "Exam 1.raw.md").exists()


def test_deliver_cmd_explicit_output_dir(tmp_path: Path) -> None:
    src = tmp_path / "out" / "Exam 1"
    _make_doc(src, "Exam 1")
    dest = tmp_path / "somewhere" / "Exam 1"

    result = CliRunner().invoke(app, ["deliver", str(src), "-o", str(dest)])

    assert result.exit_code == 0, result.output
    assert (dest / "Exam 1.md").exists()


def test_deliver_cmd_errors_when_nothing_to_deliver(tmp_path: Path) -> None:
    src = tmp_path / "conversions" / "out" / "empty"
    src.mkdir(parents=True)
    result = CliRunner().invoke(app, ["deliver", str(src)])
    assert result.exit_code == 1


def test_deliver_refuses_a_document_that_fails_verify(tmp_path: Path) -> None:
    src = tmp_path / "out" / "Exam 1"
    _make_doc(src, "Exam 1")
    (src / "Exam 1.md").write_text(_MASTER + "\n![fig](images/gone.png)\n", encoding="utf-8")
    dest = tmp_path / "delivery" / "Exam 1"

    with pytest.raises(PreconditionError, match="delivery refused"):
        deliver(src, dest)

    assert not dest.exists()
    assert (src / ".pagespeak-verdict.md").is_file()


def test_a_folder_with_sections_but_no_master_is_not_delivered(tmp_path: Path) -> None:
    export = tmp_path / "out" / "exams"
    _make_doc(export / "exam-1", "exam-1")
    (export / "exam-2" / "sections").mkdir(parents=True)
    (export / "exam-2" / "sections" / "Question 1.md").write_text(
        "![fig](../images/gone.png)\n", encoding="utf-8"
    )
    dest = tmp_path / "delivery" / "exams"
    assert deliver(export, dest).documents == 1
    assert not (dest / "exam-2").exists()


def test_a_source_with_no_document_leaves_the_last_delivery_in_place(tmp_path: Path) -> None:
    src = tmp_path / "out" / "Exam 1"
    src.mkdir(parents=True)
    dest = tmp_path / "delivery" / "Exam 1"
    dest.mkdir(parents=True)
    (dest / "Exam 1.md").write_text(_MASTER, encoding="utf-8")
    assert deliver(src, dest).documents == 0
    assert (dest / "Exam 1.md").read_text(encoding="utf-8") == _MASTER


def test_dot_files_under_sections_are_not_delivered(tmp_path: Path) -> None:
    src = tmp_path / "out" / "Exam 1"
    _make_doc(src, "Exam 1")
    (src / "sections" / ".pagespeak-verdict.md").write_text("# Verify\n", encoding="utf-8")
    dest = tmp_path / "delivery" / "Exam 1"
    deliver(src, dest)
    assert (dest / "sections" / "Question 001.md").exists()
    assert not (dest / "sections" / ".pagespeak-verdict.md").exists()


@pytest.mark.parametrize(
    ("path", "delivered"),
    [
        ("images/a.png", True),
        ("sections/1/One.md", True),
        ("figures/a.png", False),
        ("b.png", False),
        ("images/.hidden.png", False),
        ("sections/.cache/One.md", False),
        ("../in/a.png", False),
    ],
)
def test_deliver_hands_off_only_images_and_sections_without_dot_files(
    path: str, delivered: bool
) -> None:
    assert is_delivered(Path(path)) is delivered


def test_deliver_refuses_a_sections_folder(tmp_path: Path) -> None:
    src = tmp_path / "out" / "Exam 1"
    _make_doc(src, "Exam 1")
    with pytest.raises(PreconditionError, match="is part of a document"):
        deliver(src / "sections", tmp_path / "delivery" / "sections")


def test_deliver_hands_off_a_document_that_passes(tmp_path: Path) -> None:
    src = tmp_path / "out" / "Exam 1"
    _make_doc(src, "Exam 1")
    result = deliver(src, tmp_path / "delivery" / "Exam 1")
    assert result.documents == 1


def test_deliver_cmd_refuses_a_failing_document(tmp_path: Path) -> None:
    src = tmp_path / "conversions" / "out" / "Exam 1"
    _make_doc(src, "Exam 1")
    (src / "Exam 1.md").write_text(_MASTER + "\n![fig](images/gone.png)\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["deliver", str(src)])

    assert result.exit_code == 1
    assert "delivery refused" in result.output
    assert ".pagespeak-verdict.md" in result.output
    assert not (tmp_path / "conversions" / "delivery" / "Exam 1").exists()
