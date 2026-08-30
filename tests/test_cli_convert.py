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


def _convert_option_help(param_name: str) -> str:
    """Help text of one `convert` option, unwrapped (rendered help is boxed)."""
    import typer.main

    group = typer.main.get_command(app)
    convert = group.commands["convert"]  # type: ignore[attr-defined]
    for param in convert.params:
        if param_name in getattr(param, "opts", []):
            return str(param.help or "")
    raise AssertionError(f"{param_name} not found on `convert`")


def test_rerun_from_help_lists_every_stage() -> None:
    """A stage the validator accepts but the help omits is invisible."""
    from pagespeak.services._rerun import PAGESPEAK_REGISTRY

    help_text = _convert_option_help("--rerun-from")
    missing = [s.name for s in PAGESPEAK_REGISTRY.stages if s.name not in help_text]
    assert not missing, f"--rerun-from help omits stages: {missing}"


@pytest.mark.parametrize("option", ["--from", "--stop-after"])
def test_phase_slice_help_lists_every_phase(option: str) -> None:
    """`--from` / `--stop-after` must name every phase they accept."""
    from pagespeak.orchestrators._phases import build_phases

    help_text = _convert_option_help(option)
    if "Same phase names as --from" in help_text:
        help_text += _convert_option_help("--from")
    missing = [p.name for p in build_phases() if p.name not in help_text]
    assert not missing, f"{option} help omits phases: {missing}"


def test_normalize_model_help_does_not_claim_a_hardcoded_default() -> None:
    """`DEFAULT_NORMALIZE_MODEL` is only the fallback for a YAML missing the
    agent; naming it as the default misstates a cost-relevant fact."""
    from pagespeak.services._normalize_llm import DEFAULT_NORMALIZE_MODEL

    help_text = _convert_option_help("--normalize-headings-model")
    assert DEFAULT_NORMALIZE_MODEL not in help_text, (
        "help names a hardcoded default that YAML routing overrides"
    )
    assert "model_router.yaml" in help_text


def _capture_convert_kwargs(monkeypatch, tmp_path: Path, extra_args: list[str]) -> dict:
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
        ["convert", str(f), "-o", str(tmp_path / "o"), "--no-diagrams", *extra_args],
    )
    assert result.exit_code == 0, result.output
    return captured


def test_min_body_chars_zero_survives_to_the_orchestrator(monkeypatch, tmp_path: Path) -> None:
    """0 means keep every section, empty ones included. It is falsy, so a
    passthrough that tests truthiness silently restores the 30-char default
    and drops the placeholder headings the caller asked to keep."""
    captured = _capture_convert_kwargs(monkeypatch, tmp_path, ["--min-body-chars", "0"])
    assert captured.get("min_body_chars") == 0


def test_min_body_chars_passed_through(monkeypatch, tmp_path: Path) -> None:
    captured = _capture_convert_kwargs(monkeypatch, tmp_path, ["--min-body-chars", "12"])
    assert captured.get("min_body_chars") == 12


def test_min_body_chars_defaults_to_none(monkeypatch, tmp_path: Path) -> None:
    """Unpassed stays None so the library's own default applies."""
    captured = _capture_convert_kwargs(monkeypatch, tmp_path, [])
    assert captured.get("min_body_chars") is None
