"""Tests for services/_split_filter.py — section-set filtering.

Focused on the empty-body / chapter-shell selection that decides which
parsed sections become standalone files.
"""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._split import split_into_sections
from pagespeak.services._split_filter import (
    _drop_toc_phantom_sections,
    _has_substantive_body,
    _select_kept_sections,
)
from pagespeak.services._split_parse import _Section


def _section(heading: str, content: list[str]) -> _Section:
    return _Section(
        level=2, number=None, title=heading, heading_line=heading, content_lines=content
    )


# ── _drop_toc_phantom_sections ─────────────────────────────────────────────

_SUMMARY = [
    "- Cells are the smallest living units, specialised for different functions.",
    "- Tissues combine into organs; organ systems perform whole-body tasks.",
    "- The internal environment is the fluid surrounding the body's cells.",
]


def _numbered(display: str, content: list[str]) -> _Section:
    number, _, title = display.partition(" ")
    s = _Section(
        level=2, number=number, title=title, heading_line=f"## {display}", content_lines=content
    )
    return s


def test_phantom_shaped_heading_with_real_body_is_kept() -> None:
    """A chapter-review summary restates its subsection with a page
    back-reference (`1.1 Organization of the Body, p. 32`) and then carries
    unique prose. It matches the TOC shape but is real content."""
    s = _numbered("1.1 Organization of the Body, p. 32", _SUMMARY)
    kept, dropped = _drop_toc_phantom_sections([s])
    assert dropped == 0, "dropped a phantom-shaped heading that has real content"
    assert kept == [s]


def test_bodyless_phantom_is_still_dropped() -> None:
    """The real TOC entry — same shape, no body — must still go."""
    s = _numbered("1.1 Organization of the Body, p. 32", [])
    kept, dropped = _drop_toc_phantom_sections([s])
    assert (kept, dropped) == ([], 1)


def test_phantom_parent_is_kept_when_a_descendant_has_content() -> None:
    """Pruning a parent takes its whole subtree, so an empty phantom whose
    child carries content must not be dropped."""
    parent = _numbered("2.2 Cell Structure, p. 59", [])
    child = _numbered("2.2.1 The Membrane, p. 60", _SUMMARY)
    child.parent = parent
    parent.children = [child]
    kept, dropped = _drop_toc_phantom_sections([parent, child])
    assert dropped == 0
    assert kept == [parent, child]


def test_numbered_heading_ending_in_a_number_is_not_a_phantom() -> None:
    """`2.4 IEEE 802.11` is a real title whose trailing digits are part of the
    name, not a page reference."""
    s = _numbered("2.4 IEEE 802.11", _SUMMARY)
    _, dropped = _drop_toc_phantom_sections([s])
    assert dropped == 0


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


def test_toc_parent_does_not_swallow_real_sections(tmp_path: Path) -> None:
    """A `## Table of Contents` whose body is only a link list must not become
    the parent of the manual.

    Real shape: content headings sit one level BELOW the contents heading, so
    level nesting buries every real section under it and INDEX lists nothing
    useful. The contents section is kept — only its children are re-attached to
    its own parent.
    """
    md = (
        "# BLUE BABY BOTTLE MANUAL\nManual intro body over the cutoff threshold.\n"
        "## Table of Contents\n"
        "- [Vocals](#vocals)\n"
        "- [Drums](#drums)\n"
        "### Vocals\nVocal placement body comfortably over the cutoff.\n"
        "### Drums\nDrum placement body comfortably over the cutoff too.\n"
    )
    written = split_into_sections(md, tmp_path, nested=True, min_level=1, min_body_chars=0)
    rel = sorted(str(p.relative_to(tmp_path)) for p in written)
    # Vocals/Drums are siblings of the contents section, not nested beneath it.
    assert not any("table-of-contents/" in r for r in rel), rel
    assert any(r.endswith("vocals.md") for r in rel), rel
    assert any(r.endswith("table-of-contents.md") for r in rel), rel


def test_link_list_section_without_children_is_untouched(tmp_path: Path) -> None:
    """A link-list section that parents nothing keeps its normal shape."""
    md = (
        "# Guide\nGuide intro body comfortably over the cutoff threshold.\n"
        "## Related Links\n- [Site](#site)\n- [Docs](#docs)\n"
        "## Real Section\nReal body comfortably over the cutoff threshold.\n"
    )
    written = split_into_sections(md, tmp_path, nested=True, min_level=1, min_body_chars=0)
    names = sorted(p.name for p in written)
    assert "related-links.md" in names
    assert "real-section.md" in names


# ── suffix must not land on a name another section already owns ─────────
#
# `Foo`, `Foo`, `Foo 2`: the second `Foo` is suffixed to `foo-2`, which the
# third section already owns. The writer truncates, so one body is lost.


def _sec(title: str, body: str):
    from pagespeak.services._split_parse import _Section

    return _Section(
        level=2,
        number=None,
        title=title,
        heading_line=f"## {title}",
        content_lines=[body],
        children=[],
        parent=None,
    )


def _paths(kept, out, nested=False):
    from pagespeak.services._split_write import _section_output_path

    seen: dict[str, list[str]] = {}
    for s in kept:
        seen.setdefault(_section_output_path(s, out, nested=nested).name, []).append(
            s.content_lines[0]
        )
    return seen


def test_suffix_skips_a_name_another_section_owns(tmp_path) -> None:
    from pagespeak.services._split_filter import _dedupe_section_paths

    secs = [_sec("Foo", "A"), _sec("Foo", "B"), _sec("Foo 2", "C")]
    kept, _ = _dedupe_section_paths(secs, tmp_path, nested=False)
    seen = _paths(kept, tmp_path)
    assert len(kept) == 3
    assert all(len(v) == 1 for v in seen.values()), f"collision: {seen}"


def test_suffix_walks_past_several_owned_names(tmp_path) -> None:
    from pagespeak.services._split_filter import _dedupe_section_paths

    secs = [
        _sec("Foo", "A"),
        _sec("Foo", "B"),
        _sec("Foo", "C"),
        _sec("Foo 2", "D"),
        _sec("Foo 3", "E"),
    ]
    kept, _ = _dedupe_section_paths(secs, tmp_path, nested=False)
    seen = _paths(kept, tmp_path)
    assert len(kept) == 5
    assert len(seen) == 5, f"collision: {seen}"


def test_body_identical_duplicates_still_drop(tmp_path) -> None:
    """The suffix fix must not resurrect body-identical dupes."""
    from pagespeak.services._split_filter import _dedupe_section_paths

    kept, collisions = _dedupe_section_paths(
        [_sec("Foo", "SAME"), _sec("Foo", "SAME")], tmp_path, nested=False
    )
    assert len(kept) == 1 and len(collisions) == 1
