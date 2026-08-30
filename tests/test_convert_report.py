"""Tests for what `pagespeak convert` echoes after a run.

The branches here (early `--stop-after`, QTI export, master document) each
print different counts, and a wrong one misreports a finished conversion.
"""

from __future__ import annotations

from pathlib import Path

from pagespeak.cli._convert_report import report_result
from pagespeak.models._models import IngestResult


def _result() -> IngestResult:
    return IngestResult(markdown="", images=[Path("a.png")], diagrams=[], source_format="docx")


def test_reports_the_master_and_its_counts(tmp_path, capsys) -> None:
    src = tmp_path / "doc.docx"
    src.write_bytes(b"stub")
    report_result(input_path=src, output_dir=tmp_path / "o", result=_result(), stop_after=None)
    out = capsys.readouterr().out
    assert f"wrote {tmp_path / 'o' / 'doc.md'}" in out
    assert "  format       : docx" in out
    assert "  images       : 1" in out


def test_sections_line_only_when_the_dir_exists(tmp_path, capsys) -> None:
    src = tmp_path / "doc.docx"
    src.write_bytes(b"stub")
    out_dir = tmp_path / "o"
    report_result(input_path=src, output_dir=out_dir, result=_result(), stop_after=None)
    assert "sections     :" not in capsys.readouterr().out

    (out_dir / "sections").mkdir(parents=True)
    report_result(input_path=src, output_dir=out_dir, result=_result(), stop_after=None)
    assert "sections     :" in capsys.readouterr().out


def test_early_stop_after_reports_the_checkpoint_instead(tmp_path, capsys) -> None:
    """An early stop leaves an intermediate checkpoint; claiming a master was
    written would be wrong."""
    src = tmp_path / "doc.docx"
    src.write_bytes(b"stub")
    report_result(input_path=src, output_dir=tmp_path / "o", result=_result(), stop_after="cleanup")
    out = capsys.readouterr().out
    assert "stopped after 'cleanup'" in out
    assert "format       :" not in out  # the counts block belongs to a finished run


def test_late_stop_after_still_reports_the_master(tmp_path, capsys) -> None:
    src = tmp_path / "doc.docx"
    src.write_bytes(b"stub")
    report_result(input_path=src, output_dir=tmp_path / "o", result=_result(), stop_after="split")
    assert "wrote" in capsys.readouterr().out


def test_qti_export_reports_one_document_per_exam(tmp_path, capsys) -> None:
    export = tmp_path / "quizzes"
    export.mkdir()
    (export / "imsmanifest.xml").write_text("<manifest/>")
    out_dir = tmp_path / "o"
    for exam in ("exam-1", "exam-2"):
        (out_dir / exam).mkdir(parents=True)
    (out_dir / "stray.md").write_text("x")
    report_result(input_path=export, output_dir=out_dir, result=_result(), stop_after=None)
    out = capsys.readouterr().out
    assert "wrote 2 quiz document(s)" in out
    assert "non-diagrams" not in out
