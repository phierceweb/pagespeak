from __future__ import annotations

import pytest

from pagespeak.utils._hash_escape import escape_marked_hashes, mark_leading_hashes


def _convert(body: str) -> str:
    """Body HTML through mark → real markitdown → escape."""
    pytest.importorskip("markitdown")
    from markitdown import MarkItDown

    from pagespeak.backends._docx import _convert_html_string

    html = mark_leading_hashes(f"<html><body>{body}</body></html>")
    return escape_marked_hashes(_convert_html_string(MarkItDown(), html).text_content)


def test_paragraph_hash_is_escaped() -> None:
    assert _convert("<p># a comment</p><p>#</p>").splitlines() == ["\\# a comment", "", "\\#"]


def test_hash_after_a_line_break_is_escaped() -> None:
    assert "\\# second" in _convert("<p>first<br/># second</p>").splitlines()


def test_hash_in_a_list_item_or_quote_is_escaped() -> None:
    md = _convert("<ul><li># item</li></ul><blockquote><p># quoted</p></blockquote>")
    assert "* \\# item" in md.splitlines()
    assert "> \\# quoted" in md.splitlines()


def test_pretty_printed_and_lone_hash_paragraphs_are_escaped() -> None:
    assert _convert("<p>\n  # pretty\n</p>") == "\\# pretty"
    assert _convert("<p>#</p>") == "\\#"


def test_hash_written_as_an_entity_or_after_a_no_break_space_is_escaped() -> None:
    for body in ("<p>&#35; x</p>", "<p>&num; x</p>", "<p>&#x23; x</p>", "<p>&nbsp;# x</p>"):
        assert _convert(body) == "\\# x", body


def test_hash_in_ordered_and_nested_list_items_is_escaped() -> None:
    assert _convert("<ol><li># one</li></ol>") == "1. \\# one"
    nested = "<ul><li>a<ul><li>b<ul><li># deep</li></ul></li></ul></li></ul>"
    assert _convert(nested).splitlines() == ["* a", "  + b", "    - \\# deep"]


def test_comment_starting_with_a_hash_stays_hidden() -> None:
    assert _convert("<p>x</p><!-- # note --><p>y</p>") == "x\n\ny"


def test_kbd_and_samp_keep_their_hash_but_tt_is_text() -> None:
    assert _convert("<p><kbd># k</kbd> <samp># s</samp></p>") == "`# k` `# s`"
    assert _convert("<p><tt># t</tt></p>") == "\\# t"


def test_inline_code_broken_across_lines_keeps_its_hash() -> None:
    for tag in ("code", "kbd", "samp"):
        assert _convert(f"<p><{tag}>a<br># b</{tag}></p>") == "`a\n# b`", tag


def test_page_holding_the_marker_text_is_not_marked() -> None:
    html = "<p># heading-like</p><p>see xpagespeakhashx here</p>"
    assert mark_leading_hashes(html) is html


def test_html_with_hashes_only_in_code_is_returned_as_is() -> None:
    html = "<pre># comment</pre><p><code># x</code></p>"
    assert mark_leading_hashes(html) is html


def test_hash_inside_a_line_is_left_alone() -> None:
    pytest.importorskip("markitdown")
    from markitdown import MarkItDown

    from pagespeak.backends._docx import _convert_html_string

    body = "<p>Press <span># </span> then <b># x</b> or <a href='u'># y</a></p>"
    plain = _convert_html_string(MarkItDown(), f"<html><body>{body}</body></html>")
    assert _convert(body) == plain.text_content


def test_code_keeps_its_hash() -> None:
    md = _convert("<pre># shell comment</pre><p><code># x</code></p>")
    assert "# shell comment" in md.splitlines()
    assert "`# x`" in md
    assert "\\" not in md


def test_real_headings_and_non_heading_hashes_are_untouched() -> None:
    md = _convert("<h2>Setup</h2><p>#hashtag</p><p>####### seven</p>")
    assert md.splitlines() == ["## Setup", "", "#hashtag", "", "####### seven"]


def test_html_without_a_leading_hash_is_returned_as_is() -> None:
    html = '<p>a <a href="#top">link</a> &amp; <span style="color:#fff">x</span></p>'
    assert mark_leading_hashes(html) is html


def test_markdown_without_markers_is_returned_as_is() -> None:
    md = "# Title\n\nbody"
    assert escape_marked_hashes(md) is md
