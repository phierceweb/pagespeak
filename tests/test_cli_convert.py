"""Tests for the `pagespeak convert` CLI subcommand — focused on behaviour
that complements the broader test_cli.py suite.

directory-input mode.
"""

from __future__ import annotations

from pathlib import Path

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
