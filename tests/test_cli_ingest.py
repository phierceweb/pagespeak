"""Tests for the `pagespeak ingest` CLI subcommand."""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from pagespeak.cli import app

runner = CliRunner()

_RICH_DECORATION_RE = re.compile(r"\x1b\[[0-9;]*m|[│╭╮╰╯─┃┏┓┗┛━]")


def _squash(output: str) -> str:
    """Strip rich's ANSI/box decoration and ALL whitespace.

    Under GITHUB_ACTIONS, Typer forces rich's terminal rendering and
    reformats option names in the help panel — `--workers` becomes
    `- -workers`, colorized and 80-col-wrapped. Removing every space (not
    just collapsing) reconstructs the option name as a contiguous substring,
    so the "is this flag documented?" assertions hold regardless of width.
    """
    return re.sub(r"\s+", "", _RICH_DECORATION_RE.sub("", output))


def test_ingest_help_shows_workers_and_pdf_backend():
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0
    help_text = _squash(result.stdout)
    assert "--workers" in help_text
    assert "--pdf-backend" in help_text
    assert "--docx-backend" in help_text
    assert "--output-dir" in help_text


def test_ingest_invokes_orchestrator(tmp_path, monkeypatch):
    """CLI flag passthrough → `ingest()` is called with the expected kwargs."""
    from pagespeak.cli import _ingest as cli_ingest

    captured: dict[str, object] = {}

    def fake_ingest(
        input_path,
        *,
        output_dir,
        workers,
        pdf_backend,
        pdf_backend_kwargs=None,
        docx_backend="markitdown",
        docx_outline_heading_depth=1,
        chunk_pages=50,
        device=None,
        force_ocr=False,
        page_range=None,
        force=False,
        max_pages=None,
    ):
        captured["input_path"] = Path(input_path)
        captured["output_dir"] = Path(output_dir)
        captured["workers"] = workers
        captured["pdf_backend"] = pdf_backend
        captured["docx_backend"] = docx_backend
        captured["docx_outline_heading_depth"] = docx_outline_heading_depth
        captured["chunk_pages"] = chunk_pages
        captured["device"] = device
        captured["force_ocr"] = force_ocr
        captured["max_pages"] = max_pages
        captured["force"] = force
        # Match real behavior: write a sentinel raw.md.
        raw = Path(output_dir) / f"{Path(input_path).stem}.raw.md"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("# fake", encoding="utf-8")
        return raw

    monkeypatch.setattr(cli_ingest, "ingest", fake_ingest)

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    out = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "ingest",
            str(src),
            "-o",
            str(out),
            "--workers",
            "3",
            "--pdf-backend",
            "docling",
            "--chunk-pages",
            "25",
            "--device",
            "cpu",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert captured["workers"] == 3
    assert captured["pdf_backend"] == "docling"
    assert captured["docx_backend"] == "markitdown"  # default when omitted
    assert captured["chunk_pages"] == 25
    assert captured["device"] == "cpu"
    assert captured["input_path"] == src
    assert captured["output_dir"] == out


def test_ingest_passes_docx_backend(tmp_path, monkeypatch):
    """`--docx-backend python-docx` reaches the orchestrator."""
    from pagespeak.cli import _ingest as cli_ingest

    captured: dict[str, object] = {}

    def fake_ingest(input_path, *, output_dir, docx_backend="markitdown", **_):
        captured["docx_backend"] = docx_backend
        raw = Path(output_dir) / f"{Path(input_path).stem}.raw.md"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("# fake", encoding="utf-8")
        return raw

    monkeypatch.setattr(cli_ingest, "ingest", fake_ingest)

    src = tmp_path / "doc.docx"
    src.write_bytes(b"PK-fake")
    result = runner.invoke(
        app,
        ["ingest", str(src), "-o", str(tmp_path / "out"), "--docx-backend", "python-docx"],
    )
    assert result.exit_code == 0, result.stdout
    assert captured["docx_backend"] == "python-docx"


def test_ingest_partial_failure_exits_code_2(tmp_path, monkeypatch):
    """CLI catches PartialIngestError, prints a visible summary,
    exits with code 2 (distinct from 0=success and 1=total failure)."""
    from pagespeak.cli import _ingest as cli_ingest
    from pagespeak.orchestrators._ingest import PartialIngestError

    def fake_ingest_raises(input_path, **kwargs):
        raw_md = Path(kwargs["output_dir"]) / "doc.raw.md"
        raw_md.parent.mkdir(parents=True, exist_ok=True)
        raw_md.write_text("# partial", encoding="utf-8")
        raise PartialIngestError(
            raw_md_path=raw_md,
            failed_page_ranges=["0-49", "50-99", "100-149"],
            total_chunks=4,
            output_dir=Path(kwargs["output_dir"]),
        )

    monkeypatch.setattr(cli_ingest, "ingest", fake_ingest_raises)

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    out = tmp_path / "out"

    result = runner.invoke(app, ["ingest", str(src), "-o", str(out)])
    assert result.exit_code == 2, (
        f"expected exit code 2 for partial failure, got {result.exit_code}: {result.output}"
    )
    # Summary should be printed (to stderr; CliRunner mixes by default).
    combined = (result.output or "") + (result.stderr if result.stderr_bytes else "")
    assert "3 of 4 chunks failed" in combined or "partial" in combined.lower()
