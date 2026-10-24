"""Tests for orchestrators._chunk_sizing — pages per chunk and worker count."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.orchestrators._chunk_sizing import (
    CHUNK_PAGES_ENV_VAR,
    DEFAULT_CHUNK_PAGES,
    DEFAULT_WORKERS,
    WORKERS_ENV_VAR,
    resolve_chunk_pages,
    resolve_cli_workers,
    resolve_workers,
)


def test_resolve_workers_explicit_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WORKERS_ENV_VAR, "10")
    assert resolve_workers(2) == 2


def test_resolve_workers_env_used_when_no_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WORKERS_ENV_VAR, "6")
    assert resolve_workers(None) == 6


def test_resolve_workers_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WORKERS_ENV_VAR, raising=False)
    assert resolve_workers(None) == DEFAULT_WORKERS


def test_resolve_workers_rejects_zero() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        resolve_workers(0)


def test_resolve_workers_bad_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Malformed env warns (via `pw_foundation.utils.env.resolve_int`) and falls
    back to default, so an operator typo doesn't crash the pipeline."""
    monkeypatch.setenv(WORKERS_ENV_VAR, "abc")
    with caplog.at_level("WARNING"):
        assert resolve_workers(None) == DEFAULT_WORKERS
    assert any("env_var_malformed" in r.message for r in caplog.records)


def test_resolve_chunk_pages_explicit_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CHUNK_PAGES_ENV_VAR, "200")
    assert resolve_chunk_pages(100) == 100


def test_resolve_chunk_pages_env_used_when_no_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CHUNK_PAGES_ENV_VAR, "75")
    assert resolve_chunk_pages(None) == 75


def test_resolve_chunk_pages_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CHUNK_PAGES_ENV_VAR, raising=False)
    assert resolve_chunk_pages(None) == DEFAULT_CHUNK_PAGES


def test_resolve_chunk_pages_rejects_zero() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        resolve_chunk_pages(0)


def test_resolve_chunk_pages_bad_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed env warns (via pw-foundation's resolve_int) and falls back to
    default. We only assert the fall-back value here so this test doesn't
    couple to pw-foundation's log format."""
    monkeypatch.setenv(CHUNK_PAGES_ENV_VAR, "abc")
    assert resolve_chunk_pages(None) == DEFAULT_CHUNK_PAGES


def test_resolve_cli_workers_default_is_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI default must stay 1 — DEFAULT_WORKERS sizes the pool, not the choice."""
    monkeypatch.delenv("PAGESPEAK_WORKERS", raising=False)
    assert resolve_cli_workers(None) == 1


def test_resolve_cli_workers_reads_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGESPEAK_WORKERS", "6")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert resolve_cli_workers(None, pdf) == 6


def test_resolve_cli_workers_explicit_beats_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAGESPEAK_WORKERS", "6")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert resolve_cli_workers(2, pdf) == 2


def test_resolve_cli_workers_clamps_env_for_non_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ambient env value must not push a DOCX or an out dir onto the PDF-only path."""
    monkeypatch.setenv("PAGESPEAK_WORKERS", "6")
    docx = tmp_path / "doc.docx"
    docx.write_bytes(b"PK\x03\x04")
    outdir = tmp_path / "out"
    outdir.mkdir()
    assert resolve_cli_workers(None, docx) == 1
    assert resolve_cli_workers(None, outdir) == 1
    assert resolve_cli_workers(None, None) == 1
    # An explicit flag still reaches the PDF-only guard, which is the useful error.
    assert resolve_cli_workers(6, docx) == 6


def test_resolve_cli_workers_clamps_env_when_run_is_chunk_unsafe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chunked path re-ingests and cannot carry every option, so an ambient
    value must not silently reroute a run that asked for something else."""
    monkeypatch.setenv("PAGESPEAK_WORKERS", "6")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert resolve_cli_workers(None, pdf, chunk_unsafe=True) == 1
    assert resolve_cli_workers(None, pdf, chunk_unsafe=False) == 6


def test_resolve_cli_workers_never_clamps_an_explicit_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typed --workers is a request; the downstream error is the useful answer."""
    monkeypatch.delenv("PAGESPEAK_WORKERS", raising=False)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert resolve_cli_workers(4, pdf, chunk_unsafe=True) == 4


def test_resolve_cli_workers_rejects_a_non_positive_explicit_flag() -> None:
    """The error must name `--workers`, not the env var behind the resolver."""
    with pytest.raises(ValueError, match=r"--workers"):
        resolve_cli_workers(0)
    with pytest.raises(ValueError, match=r"--workers"):
        resolve_cli_workers(-2)
