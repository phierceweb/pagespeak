"""Decode an HTML file for conversion: UTF-8 when it is, else as MarkItDown would."""

from __future__ import annotations

import codecs
import io
from pathlib import Path
from typing import Any

from bs4 import UnicodeDammit


def _markitdown_charset(converter: Any, path: Path, raw: bytes) -> str | None:
    """The charset MarkItDown reads an HTML file with: its first stream guess's (for an
    `.html` file the HTML converter takes that guess; None means it tries UTF-8 first)."""
    from markitdown import StreamInfo

    base = StreamInfo(extension=path.suffix, filename=path.name, local_path=str(path))
    try:
        guesses = converter._get_stream_info_guesses(io.BytesIO(raw), base)
        return guesses[0].charset if guesses else None
    except (AttributeError, TypeError):  # a MarkItDown without that method: its 4 KB guess
        import charset_normalizer

        best = charset_normalizer.from_bytes(raw[:4096]).best()
        return best.encoding if best is not None else None


def read_html(converter: Any, path: Path) -> str:
    """The page as UTF-8 when it starts with a UTF-8 byte-order mark, or when its bytes are
    UTF-8 with few NUL bytes (not UTF-16) and no escape byte (not ISO-2022); otherwise
    decoded exactly as MarkItDown decodes the file."""
    raw = path.read_bytes()
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig", errors="replace")
    if raw.count(b"\x00") * 4 < len(raw) and b"\x1b" not in raw:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
    charset = _markitdown_charset(converter, path, raw) or "utf-8"
    decoded = UnicodeDammit(raw, known_definite_encodings=[charset], is_html=True).unicode_markup
    return decoded if decoded is not None else raw.decode("utf-8", errors="replace")
