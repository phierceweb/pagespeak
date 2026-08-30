"""CLI: how `--workers` / `PAGESPEAK_WORKERS` resolve for `pagespeak convert`.

The chunked-parallel path re-ingests from its own manifest and drops several
Phase-3 options, so an ambient env value must never silently reshape a run that
path cannot serve faithfully.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pagespeak.cli import app


def test_convert_uses_env_workers(tmp_path: Path, monkeypatch) -> None:
    """PAGESPEAK_WORKERS was unreachable: the CLI's hardcoded default always won."""
    from pagespeak.cli import _convert

    captured: dict[str, object] = {}

    def fake_to_markdown(*args, **kwargs):
        captured.update(kwargs)
        out = Path(kwargs["output_dir"])
        out.mkdir(parents=True, exist_ok=True)
        (out / "doc.md").write_text("# x", encoding="utf-8")
        from pagespeak import IngestResult

        return IngestResult(markdown="# x", source_format="pdf")

    monkeypatch.setattr(_convert, "to_markdown", fake_to_markdown)
    monkeypatch.setenv("PAGESPEAK_WORKERS", "5")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    result = CliRunner().invoke(
        app, ["convert", str(pdf), "-o", str(tmp_path / "o"), "--no-diagrams"]
    )

    assert result.exit_code == 0, result.output
    assert captured.get("workers") == 5


def _stub_convert(monkeypatch, captured: dict[str, object]) -> None:
    from pagespeak.cli import _convert

    def fake_to_markdown(*args, **kwargs):
        captured.update(kwargs)
        out = Path(kwargs["output_dir"])
        out.mkdir(parents=True, exist_ok=True)
        (out / "doc.md").write_text("# x", encoding="utf-8")
        from pagespeak import IngestResult

        return IngestResult(markdown="# x", source_format="pdf")

    monkeypatch.setattr(_convert, "to_markdown", fake_to_markdown)


@pytest.mark.parametrize(
    "extra",
    [
        ["--from", "cleanup"],
        ["--stop-after", "cleanup"],
        ["--rerun-from", "cleanup"],
        ["--page-range", "0-9"],
        ["--english-only"],
        ["--repair-tables"],
    ],
)
def test_convert_env_workers_clamped_when_run_is_chunk_unsafe(
    tmp_path: Path, monkeypatch, extra: list[str]
) -> None:
    """The chunked path re-ingests from scratch and drops several options, so an
    ambient PAGESPEAK_WORKERS must not reroute a run that asked for one of them."""
    captured: dict[str, object] = {}
    _stub_convert(monkeypatch, captured)
    monkeypatch.setenv("PAGESPEAK_WORKERS", "5")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    result = CliRunner().invoke(
        app, ["convert", str(pdf), "-o", str(tmp_path / "o"), "--no-diagrams", *extra]
    )

    assert result.exit_code == 0, result.output
    assert captured.get("workers") == 1, extra


@pytest.mark.parametrize(
    "recorded",
    [{"english_only": True}, {"repair_tables": True}, {"page_range": "0-9"}],
)
def test_convert_env_workers_clamped_for_inherited_chunk_unsafe_flags(
    tmp_path: Path, monkeypatch, recorded: dict[str, object]
) -> None:
    """A chunk-unsafe option reaching to_markdown via run-record inheritance must
    clamp too — reading the raw CLI param misses it and drops the option silently."""
    import json

    from pagespeak.services._run_record import RUN_RECORD_FILENAME

    captured: dict[str, object] = {}
    _stub_convert(monkeypatch, captured)
    monkeypatch.setenv("PAGESPEAK_WORKERS", "5")
    out = tmp_path / "o"
    out.mkdir()
    (out / RUN_RECORD_FILENAME).write_text(
        json.dumps({"resolved_flags": recorded}), encoding="utf-8"
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    result = CliRunner().invoke(app, ["convert", str(pdf), "-o", str(out), "--no-diagrams"])

    assert result.exit_code == 0, result.output
    key, value = next(iter(recorded.items()))
    assert captured.get(key) == value, "the flag must still be inherited"
    assert captured.get("workers") == 1, recorded


def test_convert_explicit_workers_survives_a_chunk_unsafe_run(tmp_path: Path, monkeypatch) -> None:
    """A typed --workers is never clamped — the chunked path's own error answers it."""
    captured: dict[str, object] = {}
    _stub_convert(monkeypatch, captured)
    monkeypatch.delenv("PAGESPEAK_WORKERS", raising=False)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    result = CliRunner().invoke(
        app,
        [
            "convert",
            str(pdf),
            "-o",
            str(tmp_path / "o"),
            "--no-diagrams",
            "-w",
            "4",
            "--from",
            "cleanup",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured.get("workers") == 4


def test_convert_env_workers_ignored_for_non_pdf(tmp_path: Path, monkeypatch) -> None:
    """An ambient env value must not route a DOCX onto the PDF-only chunked path."""
    from pagespeak.cli import _convert

    captured: dict[str, object] = {}

    def fake_to_markdown(*args, **kwargs):
        captured.update(kwargs)
        from pagespeak import IngestResult

        return IngestResult(markdown="# x", source_format="docx")

    monkeypatch.setattr(_convert, "to_markdown", fake_to_markdown)
    monkeypatch.setenv("PAGESPEAK_WORKERS", "5")
    docx = tmp_path / "doc.docx"
    docx.write_bytes(b"PK\x03\x04stub")

    result = CliRunner().invoke(
        app, ["convert", str(docx), "-o", str(tmp_path / "o"), "--no-diagrams"]
    )

    assert result.exit_code == 0, result.output
    assert captured.get("workers") == 1
