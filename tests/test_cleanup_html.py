"""Tests for services/_cleanup_html.py — embedded raw-HTML conversion."""

from __future__ import annotations

from pagespeak.services._cleanup_html import convert_embedded_html_blocks


def test_embedded_table_becomes_pipe_table() -> None:
    text = (
        "Compare the options below:\n"
        "<table>\n<thead>\n<tr>\n<th>Feature</th>\n<th>Teams</th>\n</tr>\n</thead>\n"
        "<tbody>\n<tr>\n<td>Best for</td>\n<td>Orgs</td>\n</tr>\n</tbody>\n</table>\n"
        "After the table.\n"
    )
    out = convert_embedded_html_blocks(text)
    assert "<table>" not in out and "<td>" not in out
    assert "| Feature | Teams |" in out
    assert "| Best for | Orgs |" in out
    assert "Compare the options below:" in out and "After the table." in out


def test_figure_img_becomes_markdown_image() -> None:
    text = '<figure><img src="https://x/y.png" alt=""><figcaption>Cap</figcaption></figure>\n'
    out = convert_embedded_html_blocks(text)
    assert "![](https://x/y.png)" in out
    assert "<figure>" not in out


def test_bare_img_line_becomes_markdown_image() -> None:
    out = convert_embedded_html_blocks('<img src="https://x/z.png" alt="Z">\n')
    assert "![Z](https://x/z.png)" in out


def test_tag_soup_is_untouched() -> None:
    line = '| CON7<br>6th pin ~ 5th pin | 0V <voltage<5v< td=""></voltage<5v<> |\n'
    assert convert_embedded_html_blocks(line) == line


def test_midline_tag_mention_is_untouched() -> None:
    line = "The <td> element holds one cell of a row.\n"
    assert convert_embedded_html_blocks(line) == line


def test_fenced_code_is_untouched() -> None:
    text = "```html\n<table>\n<tr><td>x</td></tr>\n</table>\n```\n"
    assert convert_embedded_html_blocks(text) == text


def test_unbalanced_table_is_untouched() -> None:
    text = "<table>\n<tr><td>never closed\n"
    assert convert_embedded_html_blocks(text) == text
