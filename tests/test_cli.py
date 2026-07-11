from __future__ import annotations

import logging
import re
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from pagespeak import IngestResult
from pagespeak.cli import app

runner = CliRunner()

_RICH_DECORATION_RE = re.compile(r"\x1b\[[0-9;]*m|[│╭╮╰╯─┃┏┓┗┛━]")


def _plain(output: str) -> str:
    """Strip rich's ANSI codes + box-drawing and collapse whitespace.

    Under GITHUB_ACTIONS, Typer forces rich's terminal rendering, so a
    validation error becomes an ANSI-colored, box-bordered, 80-col-wrapped
    panel — a naive substring check then fails because rich split the
    message across a box border. Normalizing before the assert makes these
    checks CI-robust (mirrors pf-core's own fix).
    """
    return re.sub(r"\s+", " ", _RICH_DECORATION_RE.sub(" ", output))


def test_cli_convert_writes_markdown_file(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    fake_result = IngestResult(markdown="# hello\n", source_format="pdf")

    def fake_to_markdown(path: object, *, output_dir: object = None, **kwargs: object):
        # The library owns the master write (see test_dispatch); mirror it.
        Path(str(output_dir)).mkdir(parents=True, exist_ok=True)
        (Path(str(output_dir)) / "doc.md").write_text("# hello\n", encoding="utf-8")
        return fake_result

    with patch("pagespeak.cli._convert.to_markdown", side_effect=fake_to_markdown):
        result = runner.invoke(
            app,
            ["convert", str(src), "--output-dir", str(out), "--no-diagrams"],
        )

    assert result.exit_code == 0, result.output
    md_path = out / "doc.md"
    assert md_path.exists()
    assert md_path.read_text() == "# hello\n"
    assert "wrote" in result.output


def test_cli_stop_after_early_phase_does_not_clobber_final_md(tmp_path: Path) -> None:
    """`--stop-after` at an early phase must NOT overwrite the consolidated
    <stem>.md with the intermediate checkpoint — doing so knocked diagrams
    out of real docs. The phase's own checkpoint is the deliverable; the
    final <stem>.md is left intact."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    out.mkdir()
    final = out / "doc.md"
    final.write_text("# REAL FINAL (with diagrams)\n", encoding="utf-8")

    fake = IngestResult(markdown="# intermediate cleaned checkpoint\n", source_format="pdf")
    with patch("pagespeak.cli._convert.to_markdown", return_value=fake):
        result = runner.invoke(
            app,
            [
                "convert",
                str(src),
                "--output-dir",
                str(out),
                "--no-diagrams",
                "--from",
                "cleanup",
                "--stop-after",
                "cleanup",
            ],
        )

    assert result.exit_code == 0, result.output
    assert final.read_text() == "# REAL FINAL (with diagrams)\n"  # NOT clobbered
    assert "left intact" in result.output


def test_cli_convert_rejects_missing_input(tmp_path: Path) -> None:
    result = runner.invoke(app, ["convert", str(tmp_path / "nope.pdf")])
    assert result.exit_code != 0


def test_cli_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    # no_args_is_help → typer exits with usage info
    assert "Usage" in result.output


def test_cli_convert_rejects_invalid_cleanup(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    result = runner.invoke(app, ["convert", str(src), "--cleanup", "extreme"])
    assert result.exit_code != 0


def test_cli_convert_rejects_bad_pdf_backend(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    result = runner.invoke(app, ["convert", str(src), "--pdf-backend", "bogus"])
    assert result.exit_code != 0
    # Assert on the message BODY, not the option name: under rich, Typer
    # reformats `--pdf-backend` to `- -pdf -backend`, but the choices list
    # survives normalization.
    assert "must be one of ('marker', 'docling', 'tophat')" in _plain(result.output)


def test_cli_convert_passes_pdf_backend_to_to_markdown(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    fake = IngestResult(markdown="# done\n", source_format="pdf")

    with patch("pagespeak.cli._convert.to_markdown", return_value=fake) as mock_to_markdown:
        runner.invoke(
            app,
            [
                "convert",
                str(src),
                "--output-dir",
                str(out),
                "--no-diagrams",
                "--pdf-backend",
                "docling",
            ],
        )
    assert mock_to_markdown.call_args.kwargs["pdf_backend"] == "docling"


# --- logging bootstrap at package root -----------------------------


def test_pagespeak_logger_has_console_handler_attached() -> None:
    """After importing pagespeak, the `pagespeak` logger root has pf-core's
    structlog console handler attached. Bootstrapping runs in
    `pagespeak/__init__.py` (which fires before
    any service module's top-level `logger = get_logger(__name__)` would
    lazily trigger pf-core's `setup_logging` with the wrong app_logger_name).
    """
    pagespeak_logger = logging.getLogger("pagespeak")
    # Configured DEBUG so children propagate everything; handler does
    # the actual level filtering (see pf-core's setup_logging).
    assert pagespeak_logger.level == logging.DEBUG
    assert pagespeak_logger.handlers, "expected pf-core's StreamHandler"

    # A pagespeak module-level logger should inherit through propagation —
    # no own handler, propagate=True, parent='pagespeak'.
    child = logging.getLogger("pagespeak.services._diagrams")
    assert child.parent is pagespeak_logger
    assert child.propagate is True


# ============================================================================
# --normalize-headings-backend CLI flag
# ============================================================================


def test_convert_normalize_headings_backend_flag_is_registered() -> None:
    """The `--normalize-headings-backend` flag is recognized by typer
    (no `Unknown option` error). The functional behavior is covered by
    `test_convert_normalize_headings_backend_accepts_three_values`."""
    result = runner.invoke(
        app,
        ["convert", "--normalize-headings-backend", "claude_code", "/nope.pdf"],
    )
    # Exit code is non-zero because /nope.pdf doesn't exist, but the
    # flag itself must parse — the error must reference the missing
    # input file, not an unknown option.
    assert "no such option" not in result.output.lower()
    assert "unknown option" not in result.output.lower()


def test_convert_normalize_headings_backend_accepts_three_values(tmp_path: Path) -> None:
    """All three valid backends should be accepted; the flag sets the
    env vars before to_markdown runs."""
    import os

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    fake_result = IngestResult(markdown="# hi\n", source_format="pdf")
    for backend in ("claude_code", "anthropic", "openrouter"):
        # Reset env between values.
        os.environ.pop("PAGESPEAK_HEADING_NORMALIZE_BACKEND", None)
        os.environ.pop("PAGESPEAK_HEADING_NORMALIZE_FULL_BACKEND", None)
        with patch("pagespeak.cli._convert.to_markdown", return_value=fake_result):
            result = runner.invoke(
                app,
                [
                    "convert",
                    str(src),
                    "--output-dir",
                    str(out / backend),
                    "--no-diagrams",
                    "--normalize-headings-backend",
                    backend,
                ],
            )
        assert result.exit_code == 0, result.output
        assert os.environ.get("PAGESPEAK_HEADING_NORMALIZE_BACKEND") == backend
        assert os.environ.get("PAGESPEAK_HEADING_NORMALIZE_FULL_BACKEND") == backend

    # Clean up so the env state doesn't leak to other tests.
    os.environ.pop("PAGESPEAK_HEADING_NORMALIZE_BACKEND", None)
    os.environ.pop("PAGESPEAK_HEADING_NORMALIZE_FULL_BACKEND", None)


def test_convert_normalize_headings_backend_rejects_invalid(tmp_path: Path) -> None:
    """Invalid backend value must fail with non-zero exit."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")

    result = runner.invoke(
        app,
        [
            "convert",
            str(src),
            "--normalize-headings-backend",
            "bogus",
        ],
    )
    assert result.exit_code != 0
    assert "must be one of ('claude_code', 'anthropic', 'openrouter')" in _plain(result.output)


# ============================================================================
# auto normalize-mode
# ============================================================================


def test_cli_convert_accepts_auto_normalize_mode(tmp_path: Path) -> None:
    """`--normalize-headings-mode auto` parses and threads through to
    to_markdown unchanged (the normalize phase resolves it per-document)."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    fake = IngestResult(markdown="# done\n", source_format="pdf")

    with patch("pagespeak.cli._convert.to_markdown", return_value=fake) as mock_to_markdown:
        result = runner.invoke(
            app,
            [
                "convert",
                str(src),
                "--output-dir",
                str(out),
                "--no-diagrams",
                "--normalize-headings",
                "--normalize-headings-mode",
                "auto",
            ],
        )
    assert result.exit_code == 0, result.output
    assert mock_to_markdown.call_args.kwargs["normalize_headings_mode"] == "auto"


def test_cli_convert_rejects_bad_normalize_mode(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    result = runner.invoke(app, ["convert", str(src), "--normalize-headings-mode", "bogus"])
    assert result.exit_code != 0
    assert "must be one of ('heuristic', 'llm', 'llm_full', 'auto')" in _plain(result.output)


# ============================================================================
# --stop-after must not clobber the consolidated <stem>.md
# ============================================================================


def test_cli_convert_stop_after_early_does_not_clobber_final_md(tmp_path: Path) -> None:
    """A `--stop-after` at an early phase leaves result.markdown as an
    intermediate checkpoint; the CLI must NOT overwrite the real final
    <stem>.md with it (that clobbered diagrams twice)."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    out.mkdir()
    (out / "doc.md").write_text("SENTINEL FINAL WITH DIAGRAMS\n")

    intermediate = IngestResult(markdown="intermediate cleaned content\n", source_format="raw")
    with patch("pagespeak.cli._convert.to_markdown", return_value=intermediate):
        result = runner.invoke(
            app,
            [
                "convert",
                str(src),
                "--output-dir",
                str(out),
                "--no-diagrams",
                "--from",
                "cleanup",
                "--stop-after",
                "cleanup",
            ],
        )
    assert result.exit_code == 0, result.output
    assert (out / "doc.md").read_text() == "SENTINEL FINAL WITH DIAGRAMS\n"


def test_cli_convert_full_run_writes_final_md(tmp_path: Path) -> None:
    """No --stop-after (full run) reports the consolidated <stem>.md the
    library wrote (write ownership: to_markdown — see test_dispatch)."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    final = IngestResult(markdown="# final\n", source_format="raw")

    def fake_to_markdown(path: object, *, output_dir: object = None, **kwargs: object):
        Path(str(output_dir)).mkdir(parents=True, exist_ok=True)
        (Path(str(output_dir)) / "doc.md").write_text("# final\n", encoding="utf-8")
        return final

    with patch("pagespeak.cli._convert.to_markdown", side_effect=fake_to_markdown):
        result = runner.invoke(
            app, ["convert", str(src), "--output-dir", str(out), "--no-diagrams"]
        )
    assert result.exit_code == 0, result.output
    assert (out / "doc.md").read_text() == "# final\n"
    assert "wrote" in result.output


# ============================================================================
# --vision-cache-only
# ============================================================================


def test_cli_vision_cache_only_conflicts_with_no_diagrams(tmp_path: Path) -> None:
    """`--vision-cache-only` combined with `--no-diagrams` must fail — the
    library raises ValueError for this combination and the CLI must surface it
    as a non-zero exit with a helpful message."""
    src = tmp_path / "x.docx"
    src.write_bytes(b"PK\x03\x04")  # zip magic so dispatch reaches the conflict check
    result = runner.invoke(
        app,
        [
            "convert",
            str(src),
            "-o",
            str(tmp_path / "out"),
            "--no-diagrams",
            "--vision-cache-only",
        ],
    )
    assert result.exit_code != 0
    assert "vision-cache-only" in result.output
