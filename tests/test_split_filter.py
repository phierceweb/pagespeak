"""Tests for services/_split_filter.py — section-set filtering.

Focused on the empty-body / chapter-shell selection that decides which
parsed sections become standalone files.
"""

from __future__ import annotations

from pagespeak.services._split_filter import (
    _has_substantive_body,
    _select_kept_sections,
)
from pagespeak.services._split_parse import _Section


def _section(heading: str, content: list[str]) -> _Section:
    return _Section(
        level=2, number=None, title=heading, heading_line=heading, content_lines=content
    )


# ── _has_substantive_body ──────────────────────────────────────────────────


def test_body_true_for_real_prose() -> None:
    s = _section("# Intro", ["This section has actual prose a reader wants."])
    assert _has_substantive_body(s, min_body_chars=30) is True


def test_body_false_for_empty() -> None:
    s = _section("# Intro", [])
    assert _has_substantive_body(s, min_body_chars=30) is False


def test_body_false_for_page_anchor_only() -> None:
    """A 30-char page anchor must NOT clear the 30-char cutoff on its own —
    it's an orphan-shell heading (a title whose only body is a page anchor),
    not substantive content."""
    s = _section("### Solution 6: Delete the font cache", ['<span id="page-1440-2"></span>'])
    assert _has_substantive_body(s, min_body_chars=30) is False


def test_body_false_for_multiple_page_anchors() -> None:
    """A parameter-stub manual shape: 3 anchors, ~90 chars, no body."""
    s = _section(
        "#### MinLevel : Minimum Level",
        [
            '<span id="page-28-14"></span>',
            '<span id="page-28-5"></span>',
            '<span id="page-28-4"></span>',
        ],
    )
    assert _has_substantive_body(s, min_body_chars=30) is False


def test_body_true_for_anchor_plus_real_content() -> None:
    """An anchor alongside genuine prose still counts as substantive."""
    s = _section(
        "# Real",
        ['<span id="page-5-1"></span>', "A genuine paragraph of body content here."],
    )
    assert _has_substantive_body(s, min_body_chars=30) is True


def test_body_keeps_inline_anchor_line() -> None:
    """A page anchor inline with text (not anchor-only) is real content."""
    s = _section("# Mixed", ['Lead text <span id="page-5-1"></span> trailing words here.'])
    assert _has_substantive_body(s, min_body_chars=30) is True


# ── _select_kept_sections (chapter-shell preservation) ─────────────────────


def test_orphan_shell_dropped() -> None:
    """No body, no children → dropped."""
    s = _section("### Solution 6", ['<span id="page-1440-2"></span>'])
    kept, kept_ids = _select_kept_sections([s], min_body_chars=30)
    assert kept == []


def test_nav_node_parent_preserved() -> None:
    """A page-anchor-only parent WITH a substantive child is kept (its
    content lives in the child) — chapter-shell preservation must survive
    the page-anchor fix."""
    parent = _section("## Parameter Descriptions", ['<span id="page-1-1"></span>'])
    child = _section("### Detail", ["Real parameter description prose lives here, plenty long."])
    parent.children = [child]
    child.parent = parent
    kept, kept_ids = _select_kept_sections([parent, child], min_body_chars=30)
    assert id(parent) in kept_ids
    assert id(child) in kept_ids
