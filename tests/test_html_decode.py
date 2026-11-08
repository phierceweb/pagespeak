"""Tests for backends._html_decode."""

from __future__ import annotations

from pathlib import Path

import pytest

markitdown = pytest.importorskip("markitdown")
MarkItDown = markitdown.MarkItDown

from pagespeak.backends._html_decode import read_html  # noqa: E402


@pytest.mark.parametrize(
    ("raw", "text"),
    [
        ("<p>café naïve</p>\x00".encode(), "<p>café naïve</p>"),
        ("\ufeff<p>café</p>".encode(), "<p>café</p>"),
        (
            b"\xef\xbb\xbf<meta charset='iso-8859-1'><p>caf\xc3\xa9 \x92 end</p>",
            "<p>café \ufffd end</p>",
        ),
    ],
    ids=["utf8-with-a-nul", "utf8-bom", "utf8-bom-wins-over-a-declaration"],
)
def test_read_html_reads_utf8_and_a_utf8_byte_order_mark(
    tmp_path: Path, raw: bytes, text: str
) -> None:
    src = tmp_path / "p.html"
    src.write_bytes(raw)
    decoded = read_html(MarkItDown(), src)
    assert text in decoded and "\ufeff" not in decoded


def test_an_empty_page_reads_as_empty(tmp_path: Path) -> None:
    src = tmp_path / "e.html"
    src.write_bytes(b"")
    assert read_html(MarkItDown(), src) == ""


def test_without_markitdowns_guess_list_the_charset_guess_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import charset_normalizer

    class _Bare:
        pass

    class _Guess:
        encoding = "koi8_r"

    seen: list[bytes] = []
    monkeypatch.setattr(
        charset_normalizer,
        "from_bytes",
        lambda b: (seen.append(b), type("R", (), {"best": lambda self: _Guess()})())[1],
    )
    src = tmp_path / "k.html"
    src.write_bytes(("<p>" + "Привет мир. " * 600 + "</p>").encode("koi8-r"))
    assert "Привет мир" in read_html(_Bare(), src)
    assert len(seen[0]) == 4096
