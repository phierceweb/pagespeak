"""Tests for `pagespeak.cli._backend_kwargs` — the `--pdf-backend-kwargs` JSON flag."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from pagespeak.cli import app
from pagespeak.cli._backend_kwargs import parse_backend_kwargs

runner = CliRunner()


def test_parse_reads_a_json_object() -> None:
    assert parse_backend_kwargs('{"IgnoreTextProcessor_max_streak": 100000}') == {
        "IgnoreTextProcessor_max_streak": 100000
    }
    assert parse_backend_kwargs(None) is None


@pytest.mark.parametrize(
    "bad",
    [
        "{not json",
        "[1, 2]",
        "3",
        '"text"',
        '{"a": NaN}',
        '{"a": -Infinity}',
        '{"a": 1e999}',
        '{"a": 1, "a": 2}',
        '{"a": ' + "[" * 100_000 + "]" * 100_000 + "}",
    ],
)
def test_parse_rejects_anything_but_a_json_object(bad: str) -> None:
    with pytest.raises(typer.BadParameter, match="--pdf-backend-kwargs"):
        parse_backend_kwargs(bad)


def test_ingest_passes_the_kwargs_through(tmp_path: Path, monkeypatch) -> None:
    from pagespeak.cli import _ingest as cli_ingest

    captured: dict[str, object] = {}

    def fake_ingest(input_path, **kwargs):
        captured.update(kwargs)
        return tmp_path / "doc.raw.md"

    monkeypatch.setattr(cli_ingest, "ingest", fake_ingest)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    args = ["ingest", str(pdf), "-o", str(tmp_path / "o")]

    result = runner.invoke(app, [*args, "--pdf-backend-kwargs", '{"a": 1}'])
    assert result.exit_code == 0, result.output
    assert captured["pdf_backend_kwargs"] == {"a": 1}

    # The message is pinned on the parser above; output here may be coloured (CI).
    captured.clear()
    result = runner.invoke(app, [*args, "--pdf-backend-kwargs", "[1]"])
    assert result.exit_code == 2  # a usage error, before any ingest
    assert captured == {}
