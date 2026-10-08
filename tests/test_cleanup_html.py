"""Tests for services/_cleanup_html.py — embedded raw-HTML conversion."""

from __future__ import annotations

from pagespeak.services._cleanup_html import (
    convert_embedded_html_blocks,
    preformatted_block_flags,
    strip_script_style_blocks,
)


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


def test_script_and_style_blocks_are_stripped() -> None:
    text = (
        "# Widget\n"
        '<script src="../vendor.min.js"></script>\n'
        "<style>\n"
        "        #banner{\n"
        "        width: 100%;\n"
        "        }\n"
        "</style>\n"
        "Choose an option.\n"
        "<SCRIPT>\n"
        "function render() {\n"
        "\n"
        "  widget.draw(state);\n"
        "}\n"
        "</SCRIPT>\n"
        "Save the result.\n"
    )
    assert strip_script_style_blocks(text) == ("# Widget\nChoose an option.\nSave the result.\n", 3)


def test_form_controls_and_text_after_a_closing_tag_are_kept() -> None:
    controls = (
        '<input type="radio" id="o1" name="option" value="opt1"> <label for="o1">Option A</label>\n'
    )
    text = controls + '<script src="a.js"></script><script src="b.js"></script> Get the app.\n'
    assert strip_script_style_blocks(text) == (controls + " Get the app.\n", 2)


def test_script_in_code_or_left_unclosed_is_kept() -> None:
    text = (
        "```html\n<script>\nalert(1)\n</script>\n```\n"
        "Inline `<script>` stays.\n"
        "\n"
        '    <script src="indented-code-example.js"></script>\n'
        "\n"
        "<style>\n"
        "never closed, so it is not known to be a style block\n"
    )
    assert strip_script_style_blocks(text) == (text, 0)


def test_preformatted_block_flags_cover_closed_pre_and_textarea_blocks() -> None:
    lines = [
        "Intro",
        "<pre>",
        "#include <stdio.h>",
        "</pre>",
        "<textarea>#note</textarea>",
        "<pre>",
        "never closed",
    ]
    assert preformatted_block_flags(lines, [False] * len(lines)) == [
        False,
        True,
        True,
        True,
        True,
        False,
        False,
    ]


def test_preformatted_block_flags_ignore_a_pre_tag_inside_fenced_code() -> None:
    lines = ["```html", "<pre>", "```", "#include <stdio.h>", "</pre>"]
    fenced = [True, True, True, False, False]
    assert preformatted_block_flags(lines, fenced) == [False] * len(lines)
