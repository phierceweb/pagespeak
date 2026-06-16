"""Tests for the delivery-strip service + `pagespeak deliver` CLI command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pagespeak.cli import app
from pagespeak.services._deliver import strip_for_delivery


def _make_doc(doc_dir: Path, stem: str) -> None:
    """A converted document dir: master .md + stage checkpoints + run record
    + images/ + sections/ + vision cache."""
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{stem}.md").write_text("# master\n", encoding="utf-8")
    for stage in ("raw", "cleaned", "normalized", "repaired", "visioned"):
        (doc_dir / f"{stem}.{stage}.md").write_text(f"{stage}\n", encoding="utf-8")
    (doc_dir / ".pagespeak-run.json").write_text("{}\n", encoding="utf-8")
    (doc_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
    (doc_dir / "images").mkdir()
    (doc_dir / "images" / "fig.png").write_bytes(b"\x89PNG\r\n")
    (doc_dir / "sections").mkdir()
    (doc_dir / "sections" / "Question 001.md").write_text("q1\n", encoding="utf-8")
    (doc_dir / "sections" / "INDEX.md").write_text("idx\n", encoding="utf-8")
    (doc_dir / ".vision-cache").mkdir()
    (doc_dir / ".vision-cache" / "abc.json").write_text("{}\n", encoding="utf-8")


def test_strip_keeps_deliverables_drops_working_files(tmp_path: Path) -> None:
    src = tmp_path / "out" / "Exam 1"
    _make_doc(src, "Exam 1")
    dest = tmp_path / "delivery" / "Exam 1"

    result = strip_for_delivery(src, dest)

    # kept
    assert (dest / "Exam 1.md").read_text(encoding="utf-8") == "# master\n"
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
