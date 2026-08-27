"""Tests for the `pagespeak convert` CLI subcommand — focused on behaviour
that complements the broader test_cli.py suite.

directory-input mode.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pagespeak.cli import app

runner = CliRunner()


def test_convert_accepts_directory_input(tmp_path: Path, monkeypatch) -> None:
    """CLI: `pagespeak convert <outdir>` dispatches to Phase 3."""
    from pagespeak.cli import _convert
    from pagespeak.models._models import IngestResult

    out = tmp_path / "out"
    out.mkdir()
    (out / "doc.raw.md").write_text("# Doc\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_to_markdown(path, **kwargs):
        captured["path"] = path
        return IngestResult(markdown="# Doc\n", images=[], diagrams=[], source_format="raw")

    monkeypatch.setattr(_convert, "to_markdown", fake_to_markdown)

    result = runner.invoke(app, ["convert", str(out)])
    assert result.exit_code == 0, result.output
    assert captured["path"] == out


def test_convert_dir_mode_defaults_output_dir_to_input(tmp_path, monkeypatch):
    """In dir-mode, `pagespeak convert <outdir>` without `-o`
    must default `output_dir` to the input directory — the dispatcher
    requires output_dir == input_path in dir-mode."""
    from pagespeak.cli import _convert
    from pagespeak.models._models import IngestResult

    out = tmp_path / "v031-smoke"
    out.mkdir()
    (out / "doc.raw.md").write_text("# Doc\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_to_markdown(path, **kwargs):
        captured["path"] = path
        captured["output_dir"] = kwargs.get("output_dir")
        return IngestResult(markdown="# Doc\n", images=[], diagrams=[], source_format="raw")

    monkeypatch.setattr(_convert, "to_markdown", fake_to_markdown)

    # No `-o` passed; default `./out` would mismatch the input.
    result = runner.invoke(app, ["convert", str(out)])
    assert result.exit_code == 0, result.output
    assert captured["output_dir"] == out, (
        f"expected output_dir to default to input dir {out}, got {captured['output_dir']!r}"
    )


def test_convert_dir_mode_respects_explicit_output_dir(tmp_path, monkeypatch):
    """Explicit `-o` always wins, even in dir-mode (currently the
    dispatcher rejects mismatch, but the CLI must not silently override)."""
    from pagespeak.cli import _convert
    from pagespeak.models._models import IngestResult

    out = tmp_path / "v031-smoke"
    out.mkdir()
    (out / "doc.raw.md").write_text("# Doc\n", encoding="utf-8")
    other = tmp_path / "other"

    captured: dict[str, object] = {}

    def fake_to_markdown(path, **kwargs):
        captured["output_dir"] = kwargs.get("output_dir")
        return IngestResult(markdown="x", images=[], diagrams=[], source_format="raw")

    monkeypatch.setattr(_convert, "to_markdown", fake_to_markdown)

    # Explicit `-o` matching the input → dispatcher accepts. The CLI
    # MUST forward the explicit value, not its dir-mode override.
    result = runner.invoke(app, ["convert", str(out), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert captured["output_dir"] == out

    # Explicit `-o` to a different dir → CLI still forwards (the dispatcher
    # will then reject with its existing ValueError; that's the dispatcher's
    # job, not the CLI's).
    captured.clear()

    def fake_raises(path, **kwargs):
        captured["output_dir"] = kwargs.get("output_dir")
        raise ValueError("dispatcher would reject")

    monkeypatch.setattr(_convert, "to_markdown", fake_raises)
    result = runner.invoke(app, ["convert", str(out), "-o", str(other)])
    assert captured["output_dir"] == other


def test_convert_negation_flags_pass_explicit_false(monkeypatch, tmp_path: Path) -> None:
    """Inheritable single-form bools gained `/--no-` counterparts so an
    inherited True is overridable; each negation must reach to_markdown as
    an explicit False."""
    from pagespeak.cli import _convert
    from pagespeak.models._models import IngestResult

    captured: dict[str, object] = {}

    def fake_to_markdown(path, **kwargs):
        captured.update(kwargs)
        return IngestResult(markdown="x", images=[], diagrams=[], source_format="md")

    monkeypatch.setattr(_convert, "to_markdown", fake_to_markdown)
    src = tmp_path / "doc.md"
    src.write_text("# Doc\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "convert",
            str(src),
            "-o",
            str(tmp_path / "o"),
            "--no-split-sections",
            "--no-nested-split",
            "--no-english-only",
            "--no-repair-tables",
            "--no-force-ocr",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["split_sections"] is False
    assert captured["nested_split"] is False
    assert captured["english_only"] is False
    assert captured["repair_tables"] is False
    assert captured["force_ocr"] is False


def test_convert_bare_rerun_from_rebuilds_sections(tmp_path: Path) -> None:
    """The rerun-safety regression, end to end with the real pipeline: a
    bare `--rerun-from` over a recorded `--split-sections` run used to wipe
    `sections/` + `INDEX.md` forever; recorded flags must now rebuild them."""
    src = tmp_path / "doc.html"
    src.write_text(
        "<h1>One</h1><p>alpha content long enough to survive the section body filter</p>"
        "<h2>Two</h2><p>beta content long enough to survive the section body filter</p>",
        encoding="utf-8",
    )
    out = tmp_path / "out"

    first = runner.invoke(
        app, ["convert", str(src), "-o", str(out), "--split-sections", "--no-diagrams"]
    )
    assert first.exit_code == 0, first.output
    assert (out / "sections").is_dir()
    assert (out / "sections" / "INDEX.md").exists()

    rerun = runner.invoke(app, ["convert", str(out), "--rerun-from", "normalize"])
    assert rerun.exit_code == 0, rerun.output
    assert (out / "sections").is_dir(), "sections/ deleted by --rerun-from and never rebuilt"
    assert list((out / "sections").rglob("*.md")), "sections/ rebuilt empty"
    assert (out / "sections" / "INDEX.md").exists(), (
        "INDEX.md deleted by --rerun-from and never rebuilt"
    )


def test_docx_backend_flag_passed(monkeypatch, tmp_path: Path) -> None:
    """CLI: --docx-backend flag is passed through to to_markdown as docx_backend kwarg."""
    from pagespeak.cli import _convert
    from pagespeak.models._models import IngestResult

    captured: dict[str, object] = {}

    def fake_to_markdown(path, **kwargs):
        captured.update(kwargs)
        return IngestResult(markdown="", images=[], diagrams=[], source_format="docx")

    monkeypatch.setattr(_convert, "to_markdown", fake_to_markdown)
    f = tmp_path / "a.docx"
    f.write_bytes(b"PK\x03\x04stub")
    result = runner.invoke(
        app,
        [
            "convert",
            str(f),
            "-o",
            str(tmp_path / "o"),
            "--docx-backend",
            "python-docx",
            "--no-diagrams",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured.get("docx_backend") == "python-docx"


def test_convert_exits_2_on_partial_ingest(tmp_path: Path) -> None:
    """A failed chunk must fail the command loudly — the web console and any
    scripted two-command workflow key on the exit code."""
    import json

    out = tmp_path / "out"
    out.mkdir()
    (out / "doc.raw.md").write_text("# Doc\n\nFirst chunk only.\n", encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "version": 3,
                "chunks": [
                    {"page_range": "0-49", "status": "completed"},
                    {"page_range": "50-99", "status": "failed"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["convert", str(out), "-o", str(out), "--no-diagrams"])

    assert result.exit_code == 2, result.output
    assert "50-99" in result.output
    assert not (out / "doc.md").exists()


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
