"""Tests for pagespeak._split."""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._split import (
    _detect_fallback_min_level,
    _parse_numbered_heading,
    split_into_sections,
)
from pagespeak.services._split_parse import _parse_sections
from pagespeak.services._split_write import _sanitize_crumb, _sanitize_filename


def test_splits_at_each_numbered_heading(tmp_path: Path) -> None:
    md = (
        "# 1. ARCHITECTURE\n"
        "Intro paragraph.\n"
        "\n"
        "## 1.1. STACK\n"
        "Stack details.\n"
        "\n"
        "# 2. INSTALL\n"
        "Install steps.\n"
    )
    written = split_into_sections(md, tmp_path)
    assert len(written) == 3
    names = sorted(p.name for p in written)
    assert names == ["1. ARCHITECTURE.md", "1.1. STACK.md", "2. INSTALL.md"]


def test_writes_index_md(tmp_path: Path) -> None:
    md = "# 1. ALPHA\nA\n# 2. BETA\nB\n"
    split_into_sections(md, tmp_path)
    index = tmp_path / "INDEX.md"
    assert index.exists()
    body = index.read_text()
    assert "1. ALPHA" in body
    assert "2. BETA" in body


def test_index_lists_only_top_level(tmp_path: Path) -> None:
    md = "# 1. ALPHA\n## 1.1. NESTED\nstuff\n# 2. BETA\n"
    split_into_sections(md, tmp_path)
    body = (tmp_path / "INDEX.md").read_text()
    assert "1. ALPHA" in body
    assert "2. BETA" in body
    assert "1.1. NESTED" not in body


def test_filename_sanitization(tmp_path: Path) -> None:
    md = "# 1. A/B Test\nbody\n"
    written = split_into_sections(md, tmp_path)
    assert written[0].name == "1. A - B Test.md"


def test_filename_sanitization_strips_special_chars(tmp_path: Path) -> None:
    md = '# 1. Title: with*?"<>chars\nbody\n'
    written = split_into_sections(md, tmp_path)
    assert "*" not in written[0].name
    assert "?" not in written[0].name
    assert '"' not in written[0].name


def test_nested_writes_folders(tmp_path: Path) -> None:
    md = "# 4. ROOT\n## 4.1. MID\n### 4.1.1. Leaf\nbody\n"
    written = split_into_sections(md, tmp_path, nested=True)
    deepest = next(p for p in written if "4.1.1" in p.name)
    rel = deepest.relative_to(tmp_path).as_posix()
    assert rel == "4/4.1/4.1.1. Leaf.md"


def test_flat_writes_no_folders(tmp_path: Path) -> None:
    md = "# 4. ROOT\n## 4.1. MID\n### 4.1.1. Leaf\nbody\n"
    written = split_into_sections(md, tmp_path, nested=False)
    for path in written:
        assert path.parent == tmp_path


def test_orphan_lines_attach_to_previous_section(tmp_path: Path) -> None:
    md = "# 1. SECTION\norphan content\n\nmore content\n"
    written = split_into_sections(md, tmp_path)
    body = written[0].read_text()
    assert "orphan content" in body
    assert "more content" in body


def test_parent_link_appears_in_subsections_listing(tmp_path: Path) -> None:
    md = "# 1. PARENT\nbody\n## 1.1. CHILD\nchild body\n"
    written = split_into_sections(md, tmp_path)
    parent_file = next(p for p in written if "1. PARENT" in p.name and "1.1" not in p.name)
    body = parent_file.read_text()
    assert "## Subsections" in body
    assert "1.1. CHILD" in body


def test_skips_non_section_numeric_heading(tmp_path: Path) -> None:
    """`## 1 Step` (level 2, no dot) is a procedure step, not a section."""
    md = "# 1. SECTION\nintro\n## 1 Step description\nbody\n"
    written = split_into_sections(md, tmp_path)
    assert len(written) == 1
    body = written[0].read_text()
    assert "Step description" in body


def test_empty_markdown_writes_only_index(tmp_path: Path) -> None:
    written = split_into_sections("", tmp_path)
    assert written == []
    assert (tmp_path / "INDEX.md").exists()


# --- min_level: semantic heading splitting -----------------------------------


def test_min_level_2_splits_on_h2_and_h3(tmp_path: Path) -> None:
    md = "## Top\nintro\n### Sub\nsub body\n"
    written = split_into_sections(md, tmp_path, min_level=2)
    names = sorted(p.name for p in written)
    assert names == ["Sub.md", "Top.md"]


def test_min_level_2_skips_h1(tmp_path: Path) -> None:
    md = "# Title\nfront matter\n## Sub\nsub body\n"
    written = split_into_sections(md, tmp_path, min_level=2)
    names = [p.name for p in written]
    assert names == ["Sub.md"]


def test_min_level_none_preserves_numbered_only_behavior(tmp_path: Path) -> None:
    md = "# 1. NUMBERED\nbody\n## Quick Start\nsemantic body\n"
    written = split_into_sections(md, tmp_path)  # min_level=None
    names = [p.name for p in written]
    assert names == ["1. NUMBERED.md"]


def test_min_level_filename_for_unnumbered_uses_title(tmp_path: Path) -> None:
    md = "## Quick Start\nbody\n"
    written = split_into_sections(md, tmp_path, min_level=2)
    assert written[0].name == "Quick Start.md"


def test_min_level_mixes_numbered_and_semantic(tmp_path: Path) -> None:
    md = "## 1.4. Foo\nfoo body\n## Quick Start\nsemantic body\n"
    written = split_into_sections(md, tmp_path, min_level=2)
    names = sorted(p.name for p in written)
    assert names == ["1.4. Foo.md", "Quick Start.md"]


def test_min_level_with_nested_unnumbered_now_nests(tmp_path: Path) -> None:
    # behavior change: semantic sections also nest, in title-named folders.
    md = "## 1.4. Foo\nbody\n## Quick Start\nbody\n"
    written = split_into_sections(md, tmp_path, nested=True, min_level=2)
    quick = next(p for p in written if "Quick Start" in p.name)
    assert quick.parent == tmp_path / "Quick Start"
    foo = next(p for p in written if "Foo" in p.name)
    assert foo.parent == tmp_path / "1"  # numbered ones nest by number prefix


# --- semantic-heading hierarchy ----------------------------------------


def test_nested_semantic_top_level_in_own_folder(tmp_path: Path) -> None:
    md = "## Quick Start\nbody\n"
    written = split_into_sections(md, tmp_path, nested=True, min_level=2)
    assert written[0] == tmp_path / "Quick Start" / "Quick Start.md"


def test_nested_semantic_child_in_parent_folder(tmp_path: Path) -> None:
    # `## Quick Start` then `#### Foot Switches` — the child is a sibling of
    # the parent's file inside the parent's folder.
    md = "## Quick Start\nintro\n#### Foot Switches (1)\ndetails\n"
    written = split_into_sections(md, tmp_path, nested=True, min_level=2)
    qs = next(p for p in written if p.name == "Quick Start.md")
    fs = next(p for p in written if "Foot Switches" in p.name)
    assert qs == tmp_path / "Quick Start" / "Quick Start.md"
    assert fs == tmp_path / "Quick Start" / "Foot Switches (1).md"


def test_nested_semantic_grandchild_in_sub_folder(tmp_path: Path) -> None:
    md = "## A\n### B\n#### C\nbody\n"
    written = split_into_sections(md, tmp_path, nested=True, min_level=2)
    a = next(p for p in written if p.name == "A.md")
    b = next(p for p in written if p.name == "B.md")
    c = next(p for p in written if p.name == "C.md")
    assert a == tmp_path / "A" / "A.md"
    assert b == tmp_path / "A" / "B.md"
    assert c == tmp_path / "A" / "B" / "C.md"


def test_nested_mixed_numbered_and_semantic(tmp_path: Path) -> None:
    md = "## 1.4. Numbered\n## Quick Start\n#### Foot Switches (1)\n"
    written = split_into_sections(md, tmp_path, nested=True, min_level=2)
    numbered = next(p for p in written if "Numbered" in p.name)
    qs = next(p for p in written if p.name == "Quick Start.md")
    fs = next(p for p in written if "Foot Switches" in p.name)
    assert numbered.parent == tmp_path / "1"  # numbered: by number prefix
    assert qs.parent == tmp_path / "Quick Start"  # semantic: by title
    assert fs.parent == tmp_path / "Quick Start"  # child in parent's folder


def test_nested_unnumbered_child_nests_under_numbered_ancestor(tmp_path: Path) -> None:
    # Regression (real-world manual): an unnumbered subsection under a NUMBERED parent
    # must nest in the numeric tree (1/1.1/1.1.1/Namespaces.md), not diverge
    # into a separate title-named tree (ARCHITECTURE/TECHNOLOGY STACK/API/).
    md = (
        "# 1. ARCHITECTURE\nintro\n"
        "## 1.1. TECHNOLOGY STACK\nstack\n"
        "### 1.1.1. API\napi body\n"
        "#### Namespaces\nnamespaces body\n"
    )
    written = split_into_sections(md, tmp_path, nested=True, min_level=2)
    ns = next(p for p in written if p.name == "Namespaces.md")
    assert ns == tmp_path / "1" / "1.1" / "1.1.1" / "Namespaces.md"
    # The divergent title-named tree must NOT be created.
    assert not (tmp_path / "ARCHITECTURE").exists()


def test_split_rewrites_image_paths_relative_flat(tmp_path: Path) -> None:
    md = "## Foo\nsee ![alt](images/foo.png) here\n## Bar\nbar body\n"
    output_dir = tmp_path / "sections"
    split_into_sections(md, output_dir, min_level=2)
    foo_body = (output_dir / "Foo.md").read_text()
    # Foo.md is at tmp_path/sections/Foo.md; images at tmp_path/images/.
    assert "(../images/foo.png)" in foo_body


def test_split_rewrites_image_paths_relative_nested(tmp_path: Path) -> None:
    md = "## A\nintro\n### B\nmid\n#### C\n![](images/foo.png)\n"
    output_dir = tmp_path / "sections"
    split_into_sections(md, output_dir, nested=True, min_level=2)
    c_body = (output_dir / "A" / "B" / "C.md").read_text()
    # C.md is at tmp_path/sections/A/B/C.md; image at tmp_path/images/foo.png.
    assert "(../../../images/foo.png)" in c_body


def test_split_leaves_non_images_paths_alone(tmp_path: Path) -> None:
    md = (
        "## Foo\n"
        "![ext](https://example.com/img.png) and "
        "![other](other.png) and ![sub](sub/bar.jpg)\n"
        "## Bar\nbar body\n"
    )
    output_dir = tmp_path / "sections"
    split_into_sections(md, output_dir, min_level=2)
    foo_body = (output_dir / "Foo.md").read_text()
    assert "(https://example.com/img.png)" in foo_body
    assert "(other.png)" in foo_body
    assert "(sub/bar.jpg)" in foo_body


def test_split_uses_explicit_images_dir(tmp_path: Path) -> None:
    md = "## Foo\n![alt](images/foo.png)\n"
    output_dir = tmp_path / "sections"
    custom_images = tmp_path / "custom_images"
    split_into_sections(md, output_dir, min_level=2, images_dir=custom_images)
    foo_body = (output_dir / "Foo.md").read_text()
    assert "(../custom_images/foo.png)" in foo_body


def test_nested_numbered_hierarchy_paths(tmp_path: Path) -> None:
    # Regression check: numbered-hierarchy paths must stay stable.
    md = "# 1. Top\n## 1.1. Mid\n### 1.1.1. Leaf\n"
    written = split_into_sections(md, tmp_path, nested=True)
    paths = sorted(str(p.relative_to(tmp_path)) for p in written)
    assert paths == [
        "1/1. Top.md",
        "1/1.1. Mid.md",
        "1/1.1/1.1.1. Leaf.md",
    ]


def test_min_level_index_lists_orphan_sections(tmp_path: Path) -> None:
    # INDEX.md should list shallowest sections (parent=None), not literally level==1.
    # With min_level=2 the level-1 heading isn't even split, so orphans are level-2.
    md = "# Title\nfront\n## Quick Start\nbody\n## System Settings\nsys body\n"
    split_into_sections(md, tmp_path, min_level=2)
    body = (tmp_path / "INDEX.md").read_text()
    assert "Quick Start" in body
    assert "System Settings" in body


# --- Split-aware ref rewriting ---------------------------------------


def test_split_rewrites_in_doc_refs_to_section_files(tmp_path: Path) -> None:
    # Body of one section links to another section via heading slug.
    md = "## Foo\nsee [the bar section](#bar) for details\n## Bar\nbar body\n"
    split_into_sections(md, tmp_path, min_level=2)
    foo_body = (tmp_path / "Foo.md").read_text()
    assert "[the bar section](Bar.md)" in foo_body
    assert "(#bar)" not in foo_body


def test_split_rewrites_refs_with_nested_uses_relpath(tmp_path: Path) -> None:
    # Top (at /1/1. Top.md) refs deepest (at /1/1.1/1.1.1. Deepest.md);
    # rel path crosses one folder boundary.
    md = (
        "# 1. Top\n"
        "intro see [Deepest](#111-deepest) for details\n"
        "## 1.1. Sub\nsub body\n"
        "### 1.1.1. Deepest\ndeepest body\n"
    )
    split_into_sections(md, tmp_path, nested=True)
    top_body = (tmp_path / "1" / "1. Top.md").read_text()
    assert "[Deepest](<1.1/1.1.1. Deepest.md>)" in top_body


def test_split_leaves_unknown_slug_refs_alone(tmp_path: Path) -> None:
    md = "## Foo\nsee [unknown thing](#nowhere) for details\n## Bar\nbar body\n"
    split_into_sections(md, tmp_path, min_level=2)
    foo_body = (tmp_path / "Foo.md").read_text()
    assert "[unknown thing](#nowhere)" in foo_body  # preserved


def test_split_leaves_url_and_relative_file_refs_alone(tmp_path: Path) -> None:
    md = "## Foo\n[example](https://example.com) and [other doc](other.md)\n## Bar\nbar body\n"
    split_into_sections(md, tmp_path, min_level=2)
    foo_body = (tmp_path / "Foo.md").read_text()
    assert "[example](https://example.com)" in foo_body
    assert "[other doc](other.md)" in foo_body


def test_split_rewrites_refs_emitted_by_remap_pipeline(tmp_path: Path) -> None:
    # End-to-end-ish: simulate post-cleanup output where remap rewrote a
    # `[X](#page-1-0)` to `[X](#bar)`. Split should then rewrite to `Bar.md`.
    md = "## Foo\nsee [info](#bar) for details\n## Bar\nbar body\n"
    split_into_sections(md, tmp_path, min_level=2)
    foo_body = (tmp_path / "Foo.md").read_text()
    assert "[info](Bar.md)" in foo_body


def test_split_truncates_overlong_filename(tmp_path: Path) -> None:
    """A heading containing a sentence-length URL should not crash with
    OSError 63 (filename too long) — e.g. a long URL pasted as a heading."""
    long_heading = "Some [very long URL](https://" + "x" * 500 + ") please"
    md = f"## {long_heading}\nbody\n## Other\nbody2\n"
    written = split_into_sections(md, tmp_path, min_level=2)
    # All written filenames stay under the 255-byte filesystem limit.
    for path in written:
        assert len(path.name.encode("utf-8")) <= 255


def test_split_min_body_chars_drops_empty_shells(tmp_path: Path) -> None:
    """Front-matter TOC entries on textbooks become headings with empty
    bodies (`# 1 Introduction 31` with no content beneath). Setting
    min_body_chars filters them out and prunes Subsections lists too."""
    md = (
        "# 1. Introduction to Widgetry 31\n"
        "\n"
        "# 1.1. Real Section\n"
        "This section has actual prose content describing the topic in detail.\n"
        "\n"
        "# 2. Power Consumption 86\n"
        "\n"
        "# 2.1. Another Real Section\n"
        "Another substantial body of text that is well over the threshold.\n"
    )
    written = split_into_sections(md, tmp_path, min_body_chars=30)
    names = {p.name for p in written}
    assert "1.1. Real Section.md" in names
    assert "2.1. Another Real Section.md" in names
    # The empty front-matter shells dropped:
    assert "1. Introduction to Widgetry 31.md" not in names
    assert "2. Power Consumption 86.md" not in names


def test_split_min_body_chars_prunes_subsections_listing(tmp_path: Path) -> None:
    """When a child section is dropped, its parent's `## Subsections`
    listing must NOT include a link to a file that doesn't exist."""
    md = (
        "# Parent\n"
        "Parent body with enough text to clear the threshold easily.\n"
        "## Empty Child\n"
        "## Real Child\n"
        "Real child has substantial content, well over the cutoff.\n"
    )
    written = split_into_sections(md, tmp_path, min_level=1, min_body_chars=30)
    parent = next(p for p in written if "Parent" in p.name)
    parent_text = parent.read_text(encoding="utf-8")
    assert "Real Child" in parent_text
    assert "Empty Child" not in parent_text


def test_split_min_body_chars_zero_preserves_v07_behavior(tmp_path: Path) -> None:
    """Default 0 = no filtering = every split-eligible heading writes a file."""
    md = "# Empty\n# Tiny\nx\n"
    written = split_into_sections(md, tmp_path, min_level=1, min_body_chars=0)
    names = {p.name for p in written}
    assert {"Empty.md", "Tiny.md"}.issubset(names)


# --- parent-breadcrumb ---


def test_breadcrumb_added_to_non_root_sections(tmp_path: Path) -> None:
    """Each non-root section file should start with a `> ↑ ...` breadcrumb
    pointing at its ancestor chain. Lets an LLM reading one chunk derive
    the section's place in the document."""
    md = (
        "# 1. ROOT\nRoot prose content well over the body cutoff threshold.\n"
        "## 1.1. CHILD\nChild prose content well over the body cutoff too.\n"
        "### 1.1.1. GRANDCHILD\nGrandchild prose content also above the cutoff.\n"
    )
    split_into_sections(md, tmp_path, min_body_chars=0)
    root_text = (tmp_path / "1. ROOT.md").read_text()
    child_text = (tmp_path / "1.1. CHILD.md").read_text()
    grand_text = (tmp_path / "1.1.1. GRANDCHILD.md").read_text()

    # Root has no breadcrumb.
    assert "> ↑" not in root_text
    # Child cites its parent.
    assert "> ↑ [1. ROOT](<1. ROOT.md>)" in child_text
    # Grandchild cites the full chain root → parent.
    assert "> ↑ [1. ROOT](<1. ROOT.md>) / [1.1. CHILD](<1.1. CHILD.md>)" in grand_text


def test_breadcrumb_roots_at_doc_title_when_passed(tmp_path: Path) -> None:
    """With `doc_title=`, EVERY section breadcrumb roots at the document
    title (linking to INDEX.md) — including top-level sections, which get no
    breadcrumb without it. Gives each split chunk its manual identity (the
    in-chunk cross-contamination fix for a multi-manual RAG DB)."""
    md = (
        "# 1. ROOT\nRoot prose content well over the body cutoff threshold.\n"
        "## 1.1. CHILD\nChild prose content well over the body cutoff too.\n"
    )
    split_into_sections(md, tmp_path, min_body_chars=0, doc_title="Acme Widget Manual")
    root_text = (tmp_path / "1. ROOT.md").read_text()
    child_text = (tmp_path / "1.1. CHILD.md").read_text()

    # Top-level section now gets a breadcrumb rooted at the manual.
    assert "> ↑ [Acme Widget Manual](INDEX.md)" in root_text
    # Nested section: manual root, then its ancestor chain.
    assert "> ↑ [Acme Widget Manual](INDEX.md) / [1. ROOT](<1. ROOT.md>)" in child_text


def test_breadcrumb_no_doc_title_is_unchanged(tmp_path: Path) -> None:
    """Without `doc_title=` the breadcrumb is byte-for-byte the legacy
    behavior — top-level sections get none. Keeps direct callers stable."""
    md = "# 1. ROOT\nRoot prose well over the cutoff.\n## 1.1. CHILD\nChild prose over cutoff.\n"
    split_into_sections(md, tmp_path, min_body_chars=0)
    assert "> ↑" not in (tmp_path / "1. ROOT.md").read_text()
    assert "> ↑ [1. ROOT](<1. ROOT.md>)" in (tmp_path / "1.1. CHILD.md").read_text()


def test_sanitize_crumb_strips_markdown_breakers() -> None:
    """The root is interpolated into `> ↑ [<root>](INDEX.md)`, so any markdown-
    structural char (pipes break tables; brackets/parens break the link) must be
    stripped. Real corpus cases: `Sample Plugin | Manual | Vendor`, escaped `\\*`."""
    assert _sanitize_crumb("Sample Plugin | Manual | Vendor") == "Sample Plugin Manual Vendor"
    assert _sanitize_crumb("Foo [bar] (baz) <x>") == "Foo bar baz x"
    assert "\\" not in _sanitize_crumb("Vendor \\*ABC96\\*BA")
    assert _sanitize_crumb("a\nb\tc") == "a b c"


def test_sanitize_crumb_caps_length() -> None:
    """A filename-derived title can be the whole book name — cap it so it doesn't
    bloat every breadcrumb (real case: a 71-char long-titled reference doc)."""
    long = "A Long Subtitle About Some Broad Topic Written By A Particular Author Name"
    out = _sanitize_crumb(long)
    assert len(out) <= 51
    assert out.endswith("…")
    assert out.startswith("A Long Subtitle")


def test_breadcrumb_root_sanitized_in_output(tmp_path: Path) -> None:
    """End-to-end: a pipe-laden doc_title must not leak a raw `|` into the
    breadcrumb line (which would corrupt a markdown table downstream)."""
    md = "# 1. ROOT\nRoot prose over the cutoff threshold here.\n## 1.1. CHILD\nChild prose over cutoff.\n"
    split_into_sections(md, tmp_path, min_body_chars=0, doc_title="Acme | Widget | Manual")
    child = (tmp_path / "1.1. CHILD.md").read_text()
    crumb = next(ln for ln in child.splitlines() if ln.startswith("> ↑"))
    assert "[Acme Widget Manual](INDEX.md)" in crumb
    assert "|" not in crumb


def test_breadcrumb_ancestor_crumb_sanitized(tmp_path: Path) -> None:
    """An ANCESTOR section whose title carries a pipe must not leak a raw `|`
    into the breadcrumb — a multilingual-manual failure: a product-name chapter
    heading `Sample Device | Wireless Monitor Set`. Covers the crumb LABEL and the
    link TARGET (the on-disk filename)."""
    md = (
        "# Sample Device | Wireless Monitor Set\n"
        "Chapter intro long enough to keep this as its own section file here.\n"
        "## Delivery Includes\n"
        "Body content comfortably over the cutoff so the child is kept too.\n"
    )
    split_into_sections(md, tmp_path, min_level=1, min_body_chars=0, doc_title="Sample Device Spec")
    child = (tmp_path / "Delivery Includes.md").read_text()
    crumb = next(ln for ln in child.splitlines() if ln.startswith("> ↑"))
    assert "|" not in crumb  # neither the ancestor label NOR its link target leaks a pipe


def test_sanitize_filename_strips_markdown_breakers() -> None:
    """Filenames feed breadcrumb / Subsections link TARGETS, so pipes + brackets
    must be stripped there too (not just `/ \\ : * ? " < >`)."""
    out = _sanitize_filename("Sample Device | Wireless Monitor Set [v2]")
    assert "|" not in out
    assert "[" not in out and "]" not in out


def test_sanitize_filename_punctuation_only_falls_back() -> None:
    """A degenerate heading (`## #`, `## ·`) sanitizes to a stem with no word
    content — `#.md` / `·.md`. Downstream indexers (QMD `handelize`) reject a
    filename with no valid content, so fall back to a generic stem."""
    assert _sanitize_filename("#") == "section.md"
    assert _sanitize_filename("·") == "section.md"
    assert _sanitize_filename("***") == "section.md"
    assert _sanitize_filename("   ") == "section.md"


def test_sanitize_filename_keeps_non_latin_word_content() -> None:
    """CJK / Cyrillic section names are valid content (Unicode word chars) and
    must NOT be clobbered by the punctuation-only fallback."""
    assert _sanitize_filename("产品注册") == "产品注册.md"
    assert _sanitize_filename("Благодарность") == "Благодарность.md"


def test_nav_links_with_spaces_are_angle_wrapped(tmp_path: Path) -> None:
    """A space in a markdown link destination BREAKS the link — CommonMark stops
    at the first space, so `[x](a b.md)` renders as literal text, not a link
    (verified with markdown_it). Section filenames keep spaces, so every
    generated nav link (INDEX, breadcrumb, Subsections) must angle-wrap a
    space-containing target. Real-world: every multi-word link in a multilingual
    manual was dead."""
    md = (
        "# Setting Up\nIntro body comfortably over the cutoff threshold here.\n"
        "## Assembling The Arm\nChild body also well over the cutoff here too.\n"
    )
    split_into_sections(md, tmp_path, min_level=1, min_body_chars=0)
    index = (tmp_path / "INDEX.md").read_text()
    parent = (tmp_path / "Setting Up.md").read_text()
    child = (tmp_path / "Assembling The Arm.md").read_text()
    # No bare space-containing target anywhere — that's a dead link.
    for text in (index, parent, child):
        assert "](Setting Up.md)" not in text
        assert "](Assembling The Arm.md)" not in text
    assert "[Setting Up](<Setting Up.md>)" in index  # INDEX top-level link
    assert "[Assembling The Arm](<Assembling The Arm.md>)" in parent  # Subsections link
    assert "[Setting Up](<Setting Up.md>)" in child  # breadcrumb to parent


def test_cross_ref_resolves_to_nearest_same_named_section(tmp_path: Path) -> None:
    """When a `#slug` anchor matches MULTIPLE same-named sections — every plugin
    module has a 'Module Header' — the ref must resolve to the NEAREST one (in
    the referencing section's own subtree), not an arbitrary collision winner.
    Real bug: an audio-plugin manual's Clarity Overview linked `#module-header` to
    *Vintage Tape's* Module Header instead of Clarity's own."""
    md = (
        "# Clarity\nClarity module intro, body over the cutoff threshold here.\n"
        "## Overview\nSee [Module Header](#module-header). Body over cutoff too.\n"
        "## Module Header\nClarity's own header content, over the cutoff here.\n"
        "# Vintage Tape\nVintage intro, body over the cutoff threshold here too.\n"
        "## Module Header\nVintage's header content, over the cutoff here now.\n"
    )
    split_into_sections(md, tmp_path, nested=True, min_level=1, min_body_chars=0)
    overview = (tmp_path / "Clarity" / "Overview.md").read_text()
    # Resolves to Clarity's own sibling Module Header, NOT Vintage Tape's.
    assert "[Module Header](<Module Header.md>)" in overview
    assert "Vintage Tape/Module Header.md" not in overview


def test_english_only_drops_non_english_sections(tmp_path: Path) -> None:
    """Opt-in `english_only` drops a multilingual manual's translated sections
    (Italian, Chinese) while keeping the English — the multilingual-manual case."""
    md = (
        "# Powering\nConnect the supplied power adapter to the rear input jack and "
        "switch the unit on. The device requires a stable power source to operate "
        "correctly.\n"
        "# Alimentazione\nCollegare l'alimentatore in dotazione alla presa posteriore "
        "del dispositivo e accendere l'unità. Il dispositivo richiede una fonte di "
        "alimentazione stabile per funzionare correttamente.\n"
        "# 供电\n请将随附的电源适配器连接到设备后部的输入插孔并打开开关。"
        "本设备需要稳定的电源才能正常工作。\n"
    )
    written = split_into_sections(md, tmp_path, min_level=1, min_body_chars=0, english_only=True)
    names = {p.stem for p in written}
    assert "Powering" in names  # English kept
    assert "Alimentazione" not in names  # Italian dropped
    assert "供电" not in names  # Chinese dropped


def test_english_only_off_keeps_everything(tmp_path: Path) -> None:
    """Default (english_only=False) is faithful — nothing dropped by language."""
    md = "# Powering\nConnect the adapter.\n# Alimentazione\nCollegare l'alimentatore ora.\n"
    written = split_into_sections(md, tmp_path, min_level=1, min_body_chars=0)
    names = {p.stem for p in written}
    assert {"Powering", "Alimentazione"}.issubset(names)


def test_breadcrumb_semantic_titles(tmp_path: Path) -> None:
    """Semantic (non-numbered) sections also get breadcrumbs — important
    for textbooks where most sections lack numeric prefixes."""
    md = (
        "# Introduction\nIntroduction prose well over the cutoff threshold.\n"
        "## Quick Start\nQuick start body content also above the cutoff.\n"
        "### First Steps\nFirst steps body content well above the cutoff.\n"
    )
    split_into_sections(md, tmp_path, min_level=1, min_body_chars=0)
    first_steps = (tmp_path / "First Steps.md").read_text()
    assert "> ↑ [Introduction](Introduction.md) / [Quick Start](<Quick Start.md>)" in first_steps


def test_breadcrumb_strips_embedded_markdown_links_in_titles(tmp_path: Path) -> None:
    """Marker sometimes preserves embedded markdown links inside heading
    titles (`# 1[Introduction to](#contents) Widgetry`). Carrying those
    brackets into the breadcrumb's `[label](url)` produces nested
    markdown that breaks parsing. The breadcrumb display text must be
    flattened to plain text."""
    md = (
        "# 1[Introduction to](#contents) Widgetry\n"
        "Chapter prose body that clears the cutoff threshold easily.\n"
        "## Subsection\n"
        "Subsection body that is also above the threshold.\n"
    )
    split_into_sections(md, tmp_path, min_level=1, min_body_chars=0)
    sub = (tmp_path / "Subsection.md").read_text()
    assert "> ↑" in sub
    # Breadcrumb display text has the embedded link flattened.
    assert "1Introduction to Widgetry" in sub
    # And no nested markdown link survives.
    assert "[Introduction to](#contents)" not in sub


def test_breadcrumb_uses_relative_paths_in_nested_mode(tmp_path: Path) -> None:
    """In nested mode the section files live in subdirectories; the
    breadcrumb's relative paths must work from each nesting depth."""
    md = (
        "# 1. ROOT\nRoot prose content well over the body cutoff threshold.\n"
        "## 1.1. CHILD\nChild prose content well over the body cutoff too.\n"
        "### 1.1.1. GRANDCHILD\nGrandchild prose content also above the cutoff.\n"
    )
    split_into_sections(md, tmp_path, nested=True, min_body_chars=0)
    grand = (tmp_path / "1" / "1.1" / "1.1.1. GRANDCHILD.md").read_text()
    # Breadcrumb to root must traverse two `..` levels in nested mode.
    assert "> ↑" in grand
    assert "1. ROOT.md" in grand
    assert "1.1. CHILD.md" in grand


# --- parent-chain integrity ------------------------------------------


def test_orphan_multipart_numbered_does_not_latch_onto_sibling(tmp_path: Path) -> None:
    """Repro of a real-world bug: `### 2.6.` immediately after `## 2.5.` with no
    `# 2.` chapter must NOT become a child of `## 2.5.`. They're siblings
    whose chapter heading was elided. Without this guard the level-only
    fallback in `_find_parent` misattributes them, polluting the
    Subsections listing and breadcrumb chains."""
    md = (
        "## 2.5. CONFIGURATION\n"
        "Configuration body content well above the cutoff threshold.\n"
        "#### 2.5.1. Sub Item\n"
        "Sub item body content above the cutoff.\n"
        "### 2.6. TROUBLESHOOTING\n"
        "Troubleshooting body content above the cutoff.\n"
    )
    split_into_sections(md, tmp_path, min_level=2, min_body_chars=0)
    bank = (tmp_path / "2.5. CONFIGURATION.md").read_text()
    # `2.6.` is NOT in `2.5.`'s subsections — they're siblings.
    assert "[2.6. TROUBLESHOOTING]" not in bank
    # Both are top-level (visible in INDEX).
    index = (tmp_path / "INDEX.md").read_text()
    assert "[2.5. CONFIGURATION]" in index
    assert "[2.6. TROUBLESHOOTING]" in index


def test_chapter_shell_with_kept_children_is_preserved(tmp_path: Path) -> None:
    """A chapter heading like `# 2. INSTALLATION` with empty body but
    substantive subsections must be kept — its file anchors descendant
    breadcrumbs and lists subsections for top-down navigation. Front-matter
    TOC entries (empty body, no children) still drop."""
    md = (
        "# 2. INSTALLATION\n"
        "\n"  # empty body
        "## 2.1. STATUSES\n"
        "Substantial body content well above the threshold.\n"
    )
    written = split_into_sections(md, tmp_path, min_body_chars=30)
    names = {p.name for p in written}
    assert "2. INSTALLATION.md" in names  # kept despite empty body
    assert "2.1. STATUSES.md" in names
    chapter = (tmp_path / "2. INSTALLATION.md").read_text()
    assert "## Subsections" in chapter
    assert "[2.1. STATUSES]" in chapter


def test_breadcrumb_chains_through_preserved_chapter_shell(tmp_path: Path) -> None:
    """Descendants must include the chapter-shell ancestor in their
    breadcrumb so an LLM reading just the descendant can navigate up."""
    md = (
        "# 2. INSTALLATION\n"
        "\n"  # empty body, kept because of children
        "## 2.1. STATUSES\n"
        "Substantial body content well above the threshold.\n"
        "### 2.1.1. PENDING\n"
        "Sub-subsection prose body that clears the cutoff easily.\n"
    )
    split_into_sections(md, tmp_path, min_body_chars=30)
    leaf = (tmp_path / "2.1.1. PENDING.md").read_text()
    assert (
        "> ↑ [2. INSTALLATION](<2. INSTALLATION.md>) / [2.1. STATUSES](<2.1. STATUSES.md>)" in leaf
    )


def test_dropped_parent_repoints_grandchild_breadcrumb(tmp_path: Path) -> None:
    """When an intermediate section is dropped (empty body, no other
    surviving descendants of its own), kept descendants must have their
    breadcrumb walk skip the dropped intermediate rather than dead-end
    in a broken link."""
    md = (
        "# Chapter\n"
        "Chapter body content well above the cutoff threshold.\n"
        "## Empty Sub\n"
        "\n"  # empty body — but has a kept descendant, so chapter-shell preserves it
        "### Real Leaf\n"
        "Real leaf body content above the cutoff threshold.\n"
        "## Sibling\n"
        "Sibling body content above the cutoff.\n"
    )
    split_into_sections(md, tmp_path, min_level=1, min_body_chars=30)
    # Empty Sub IS kept (chapter-shell preservation), so leaf chains through it.
    leaf = (tmp_path / "Real Leaf.md").read_text()
    assert "> ↑ [Chapter](Chapter.md) / [Empty Sub](<Empty Sub.md>)" in leaf


def test_single_part_numbered_step_under_semantic_chapter(tmp_path: Path) -> None:
    """`### 1. Step One` inside `## Quick Start` is a legitimate
    procedure step. The level-only fallback must still kick in for
    single-part numbered sections — only multi-part ones (`### 2.6.`)
    are blocked from level-only attachment."""
    md = (
        "## Quick Start\n"
        "Quick start prose body well above the cutoff threshold.\n"
        "### 1. Step One\n"
        "Step one body content above the cutoff.\n"
        "### 2. Step Two\n"
        "Step two body content above the cutoff.\n"
    )
    split_into_sections(md, tmp_path, min_level=2, min_body_chars=0)
    qs = (tmp_path / "Quick Start.md").read_text()
    assert "[1. Step One]" in qs
    assert "[2. Step Two]" in qs


# --- parse-all-numbered + plain-text breadcrumb fallback ----


def test_numbered_chapter_at_level_below_min_level_is_parsed(tmp_path: Path) -> None:
    """Numbered chapter headings (`# 2. INSTALLATION`) must be parsed
    as sections regardless of `min_level`. Without this, descendants
    can't attribute their breadcrumb chain through the chapter.
    Concrete real-world case: `min_level=2` was skipping `# 2.` entirely,
    leaving `## 2.5.` orphans without ancestor context."""
    md = (
        "# 2. INSTALLATION\n"
        "\n"  # empty body
        "## 2.5. CONFIGURATION\n"
        "Configuration body content well above the threshold.\n"
        "#### 2.5.1. Sub Item\n"
        "Sub item content above the threshold for keeping.\n"
    )
    written = split_into_sections(md, tmp_path, min_level=2, min_body_chars=30)
    names = {p.name for p in written}
    # Chapter is now in the output (chapter-shell preserved by kept descendants).
    assert "2. INSTALLATION.md" in names
    bank = (tmp_path / "2.5. CONFIGURATION.md").read_text()
    assert "> ↑ [2. INSTALLATION](<2. INSTALLATION.md>)" in bank
    sub = (tmp_path / "2.5.1. Sub Item.md").read_text()
    assert (
        "> ↑ [2. INSTALLATION](<2. INSTALLATION.md>) "
        "/ [2.5. CONFIGURATION](<2.5. CONFIGURATION.md>)" in sub
    )


def test_unnumbered_h1_still_skipped_under_min_level_2(tmp_path: Path) -> None:
    """`# Some Page Title` (unnumbered, level 1) is page-header noise —
    still filtered by `min_level=2`. Only NUMBERED level-1 headings
    are promoted to always-parsed."""
    md = (
        "# Some Page Title\n"
        "front matter prose\n"
        "## Real Section\n"
        "Real section body content well above the threshold.\n"
    )
    written = split_into_sections(md, tmp_path, min_level=2, min_body_chars=0)
    names = {p.name for p in written}
    assert "Some Page Title.md" not in names
    assert "Real Section.md" in names


def test_breadcrumb_plain_text_for_non_kept_ancestor(tmp_path: Path) -> None:
    """When an ancestor exists in the parent chain but isn't in `kept_ids`,
    its crumb renders as plain text (no link). Defensive feature for
    flows where chapter-shell preservation doesn't fire (e.g. an
    ancestor parsed but later filtered, when its descendants attach via
    a different ancestor)."""
    from pagespeak.services._split import _build_breadcrumb, _Section

    chapter = _Section(
        level=1,
        number="2",
        title="INSTALLATION",
        heading_line="# 2. INSTALLATION",
    )
    section = _Section(
        level=2,
        number="2.5",
        title="CONFIGURATION",
        heading_line="## 2.5. CONFIGURATION",
        parent=chapter,
    )
    section_path = tmp_path / "2.5. CONFIGURATION.md"
    # kept_ids excludes the chapter — should render as plain text.
    crumb = _build_breadcrumb(section, tmp_path, section_path, nested=False, kept_ids={id(section)})
    assert crumb is not None
    assert "[2. INSTALLATION](" not in crumb  # NOT a link
    assert "2. INSTALLATION" in crumb  # but still shown as plain text
    assert crumb.startswith("> ↑ ")


def test_breadcrumb_kept_ancestor_still_renders_as_link(tmp_path: Path) -> None:
    """Counterpart to the plain-text test: when the ancestor IS in
    `kept_ids`, render it as a markdown link as before."""
    from pagespeak.services._split import _build_breadcrumb, _Section

    chapter = _Section(
        level=1,
        number="2",
        title="INSTALLATION",
        heading_line="# 2. INSTALLATION",
    )
    section = _Section(
        level=2,
        number="2.5",
        title="CONFIGURATION",
        heading_line="## 2.5. CONFIGURATION",
        parent=chapter,
    )
    section_path = tmp_path / "2.5. CONFIGURATION.md"
    crumb = _build_breadcrumb(
        section,
        tmp_path,
        section_path,
        nested=False,
        kept_ids={id(section), id(chapter)},
    )
    assert crumb is not None
    assert "[2. INSTALLATION](<2. INSTALLATION.md>)" in crumb


# --- Chapter-N pattern detection ------------------------------------


def test_chapter_n_heading_parsed_as_numbered(tmp_path: Path) -> None:
    """`#### Chapter 1 Introduction to Widgetry` is recognized as a
    numbered section with synthetic number `1`. Pairs with the LLM
    heading-renormalization step to recover textbook hierarchy where
    Marker emits chapters and subsections at the same level."""
    md = (
        "### Chapter 1 Introduction to Widgetry\n"
        "Chapter intro body content well above the cutoff threshold.\n"
        "#### 1.1 Organization of the System\n"
        "Subsection body content above the cutoff.\n"
        "#### 1.2 Equilibrium\n"
        "Another subsection body above the cutoff.\n"
    )
    written = split_into_sections(md, tmp_path, min_body_chars=30)
    names = {p.name for p in written}
    assert "1. Introduction to Widgetry.md" in names  # title strips "Chapter N "
    assert "1.1. Organization of the System.md" in names
    assert "1.2. Equilibrium.md" in names
    sub = (tmp_path / "1.1. Organization of the System.md").read_text()
    # Subsection chains through the chapter.
    assert "> ↑ [1. Introduction to Widgetry](<1. Introduction to Widgetry.md>)" in sub


def test_chapter_n_works_with_min_level_set(tmp_path: Path) -> None:
    """Same shape as above but with min_level=2 (semantic headings allowed) —
    the Chapter pattern still wins out and produces a numbered section."""
    md = (
        "## Chapter 5 Control Signals\n"
        "intro body well above the threshold to keep the chapter shell.\n"
        "### 5.1 Mechanisms of Communication\n"
        "Substantive body content for the subsection above the cutoff.\n"
    )
    written = split_into_sections(md, tmp_path, min_level=2, min_body_chars=30)
    names = {p.name for p in written}
    assert "5. Control Signals.md" in names
    assert "5.1. Mechanisms of Communication.md" in names
    sub = (tmp_path / "5.1. Mechanisms of Communication.md").read_text()
    assert "> ↑ [5. Control Signals](<5. Control Signals.md>)" in sub


def test_chapter_n_without_title_keeps_chapter_n_label(tmp_path: Path) -> None:
    """`#### Chapter 14` (no subtitle after the number) gets `Chapter 14`
    as its title — better than empty."""
    md = (
        "## Chapter 14\n"
        "Substantive chapter body content above the cutoff threshold.\n"
        "### 14.1 First Section\n"
        "Substantive subsection body content above the cutoff.\n"
    )
    written = split_into_sections(md, tmp_path, min_level=2, min_body_chars=30)
    names = {p.name for p in written}
    assert "14. Chapter 14.md" in names  # graceful fallback for no-subtitle case


def test_chapter_n_case_insensitive(tmp_path: Path) -> None:
    md = (
        "## chapter 7 Logic Cells\n"
        "intro body well above the cutoff for the chapter.\n"
        "### 7.1 Foo\n"
        "Foo body content above the cutoff for the subsection.\n"
    )
    written = split_into_sections(md, tmp_path, min_level=2, min_body_chars=30)
    names = {p.name for p in written}
    assert "7. Logic Cells.md" in names


def test_split_long_filename_dedup_preserves_distinct_files(tmp_path: Path) -> None:
    """Two long-but-distinct headings must produce different filenames after
    truncation — the hash suffix prevents collision."""
    base = "x" * 500
    md = f"## {base} A\nbody A\n## {base} B\nbody B\n"
    written = split_into_sections(md, tmp_path, min_level=2)
    # Filter to the two real section files (exclude INDEX.md).
    section_files = [p for p in written if p.name != "INDEX.md"]
    names = {p.name for p in section_files}
    assert len(names) == 2  # distinct, despite identical 500-char prefix


# --- splitter parent-attribution + collision-dedup -----------------


def test_single_part_numbered_does_not_level_fallback_through_numbered_ancestor(
    tmp_path: Path,
) -> None:
    """A table-of-contents echo of a real chapter. `### Chapter 24 Foo`
    (numbered, level 3) is followed by a sibling `#### 1 Bar` (single-part
    numbered, level 4). The level-only fallback must NOT attach `#### 1 Bar`
    to Chapter 24 — that would be a misleading breadcrumb. Single-part
    numbered headings refuse to level-fallback through a numbered ancestor
    and become top-level instead.

    Fixture note: uses a non-TOC fixture (TOC-shaped `#### 1 Bar 31`
    headings are dropped at split time) so the parent-attribution
    behavior is still pinnable."""
    md = (
        "### Chapter 24 Thermal Runaway\n"
        "Real chapter body content well above the cutoff threshold.\n"
        "#### 1 Introduction to Widgetry\n"
        "Sibling chapter body content above the cutoff threshold.\n"
    )
    split_into_sections(md, tmp_path, min_body_chars=0)
    intro = (tmp_path / "1. Introduction to Widgetry.md").read_text()
    assert "24. Thermal Runaway" not in intro
    # No breadcrumb at all because parent is None (top-level).
    assert "> ↑" not in intro
    # And it lands in INDEX as top-level.
    index = (tmp_path / "INDEX.md").read_text()
    assert "[1. Introduction to Widgetry]" in index


def test_single_part_numbered_still_attaches_to_unnumbered_ancestor(
    tmp_path: Path,
) -> None:
    """Sanity counterpart: skipping numbered ancestors must not break
    legitimate semantic-ancestor attachment. `### 1. Step One` under
    `## Quick Start` still chains through Quick Start in the
    breadcrumb."""
    md = (
        "## Quick Start\n"
        "Quick start prose body well above the cutoff threshold.\n"
        "### 1. Step One\n"
        "Step one body content above the cutoff.\n"
    )
    split_into_sections(md, tmp_path, min_level=2, min_body_chars=0)
    step = (tmp_path / "1. Step One.md").read_text()
    assert "> ↑ [Quick Start](<Quick Start.md>)" in step


def test_filename_collision_body_identical_drops_dupe(tmp_path: Path) -> None:
    """Two sections with the SAME sanitized filename AND the same
    whitespace-normalized body content are duplicates — the later one is
    dropped (logged as `split_dropped_filename_collision`). The motivating
    case is a table-of-contents echo of a real chapter parsing as its own
    section while the same chapter heading appears later — same name,
    identical body."""
    body = "Real chapter prose " * 30
    md = f"# 1. Foo\n{body}\n# 1. Foo\n{body}\n"
    written = split_into_sections(md, tmp_path, min_body_chars=0)
    section_files = [p for p in written if p.name != "INDEX.md"]
    assert len(section_files) == 1
    assert section_files[0].name == "1. Foo.md"


def test_filename_collision_body_distinct_uses_numeric_suffix(tmp_path: Path) -> None:
    """Two sections with the SAME sanitized filename but DIFFERENT
    bodies are legitimately distinct content and both are kept. First
    occurrence keeps the bare name; later occurrences get a numeric
    suffix (`-2`, `-3`, ...) in document order. No drop, no log."""
    md = (
        "# 1. Foo\n"
        "First foo body content here.\n"
        "# 1. Foo\n"
        "Completely different second foo body content.\n"
    )
    written = split_into_sections(md, tmp_path, min_body_chars=0)
    section_files = sorted(p for p in written if p.name != "INDEX.md")
    assert len(section_files) == 2
    names = {p.name for p in section_files}
    assert names == {"1. Foo.md", "1. Foo-2.md"}
    bare = (tmp_path / "1. Foo.md").read_text()
    suffixed = (tmp_path / "1. Foo-2.md").read_text()
    # First occurrence (anchor) keeps bare filename.
    assert "First foo body content" in bare
    # Second occurrence (later in document order) gets -2.
    assert "Completely different second foo" in suffixed


def test_filename_collision_three_way_distinct(tmp_path: Path) -> None:
    """Three same-named, body-distinct sections produce a 3-file fan:
    bare, -2, -3, in document order."""
    md = "# 1. Foo\nbody alpha\n# 1. Foo\nbody beta\n# 1. Foo\nbody gamma\n"
    written = split_into_sections(md, tmp_path, min_body_chars=0)
    section_files = sorted(p for p in written if p.name != "INDEX.md")
    assert len(section_files) == 3
    assert (tmp_path / "1. Foo.md").exists()
    assert (tmp_path / "1. Foo-2.md").exists()
    assert (tmp_path / "1. Foo-3.md").exists()
    assert "body alpha" in (tmp_path / "1. Foo.md").read_text()
    assert "body beta" in (tmp_path / "1. Foo-2.md").read_text()
    assert "body gamma" in (tmp_path / "1. Foo-3.md").read_text()


def test_filename_no_collision_no_suffix(tmp_path: Path) -> None:
    """A section with no collision keeps its bare filename — no suffix
    leaks onto a unique name."""
    md = "# 1. Unique\nbody\n"
    written = split_into_sections(md, tmp_path, min_body_chars=0)
    section_files = [p for p in written if p.name != "INDEX.md"]
    assert len(section_files) == 1
    assert section_files[0].name == "1. Unique.md"


def test_filename_long_truncated_no_hash_suffix(tmp_path: Path) -> None:
    """Long titles truncate without an 8-char hash suffix — the name is
    just truncated. The post-pass collision resolver handles disambiguation
    for the rare case where two distinct truncated names collide.

    Use a long but section-title-shaped string (capitalized words, no
    internal sentence boundary) so the prose-shape demote does
    NOT fire on it — we're testing the truncation path, not demote."""
    long_title = "Word " * 50  # 250 chars, capitalized, no internal period
    # Numbered prefix so the splitter (default: numbered-headings-only) picks it up.
    md = f"# 1. {long_title}\nbody\n"
    written = split_into_sections(md, tmp_path, min_body_chars=0)
    section_files = [p for p in written if p.name != "INDEX.md"]
    assert len(section_files) == 1
    name = section_files[0].name
    # No 8-char-hex hash suffix.
    import re as _re

    assert not _re.search(r"-[0-9a-f]{8}\.md$", name)
    # Truncated to fit.
    assert len(name) <= 204  # 200 + ".md"


def test_filename_collision_logged_only_for_body_identical(tmp_path: Path, caplog) -> None:  # type: ignore[no-untyped-def]
    """Dropped (body-identical) collisions still log at INFO;
    body-distinct collisions resolved via numeric suffix do NOT log."""
    import logging

    body_same = "Identical body content here."
    md = (
        # First pair: body-identical → drops, logs.
        f"# 1. Foo\n{body_same}\n"
        f"# 1. Foo\n{body_same}\n"
        # Second pair: body-distinct → numeric suffix, no log.
        "# 2. Bar\nbody A here\n"
        "# 2. Bar\nbody B here\n"
    )
    with caplog.at_level(logging.INFO, logger="pagespeak.services._split"):
        split_into_sections(md, tmp_path, min_body_chars=0)
    messages = [record.getMessage() for record in caplog.records]
    detail_messages = [
        m for m in messages if "split_dropped_filename_collision path=" in m and "kept=" in m
    ]
    # Only one drop log: the body-identical Foo pair.
    assert len(detail_messages) == 1
    assert "path=1. Foo.md" in detail_messages[0]
    # Body-distinct Bar pair: no drop log; both files written.
    assert (tmp_path / "2. Bar.md").exists()
    assert (tmp_path / "2. Bar-2.md").exists()
    assert any("split_dropped_filename_collisions count=1" in m for m in messages)


def test_filename_collision_breadcrumb_uses_bare_display_name(tmp_path: Path) -> None:
    """The numeric suffix lives on the FILENAME only — the section's
    `display_name` (used in breadcrumbs and `## Subsections` lists) is
    unchanged. So a dropped section's siblings still link by display name."""
    md = "# 1. Chapter\nintro\n## 1.1 Foo\nfirst body\n## 1.1 Foo\ndifferent second body\n"
    split_into_sections(md, tmp_path, min_body_chars=0, nested=False)
    # Both Foo files exist, suffixed.
    assert (tmp_path / "1.1. Foo.md").exists()
    assert (tmp_path / "1.1. Foo-2.md").exists()
    # Each retains the bare display heading — no `-2` leaks into the
    # heading text or breadcrumb. The suffix DOES stay in section_id
    # (the join key must be unique).
    bare = (tmp_path / "1.1. Foo.md").read_text()
    assert bare.split("---\n\n", 1)[1].startswith("## 1.1. Foo\n")
    assert 'section_id: "1.1. Foo.md"' in bare
    suffixed = (tmp_path / "1.1. Foo-2.md").read_text()
    assert suffixed.split("---\n\n", 1)[1].startswith("## 1.1. Foo\n")
    assert 'section_id: "1.1. Foo-2.md"' in suffixed


def test_section_file_keeps_preserved_anchor_attached_to_heading(tmp_path: Path) -> None:
    """Section files mirror consolidated MD: no blank between heading and
    page-anchor span lines."""
    md = '# 1. Foo\n<span id="page-1-0"></span>\n\nBody paragraph.\n'
    split_into_sections(md, tmp_path, min_body_chars=0)
    written = (tmp_path / "1. Foo.md").read_text(encoding="utf-8")
    lines = written.split("---\n\n", 1)[1].splitlines()
    assert lines[0] == "# 1. Foo"
    assert lines[1] == '<span id="page-1-0"></span>'
    assert lines[2] == ""
    assert "Body paragraph." in lines


def test_section_file_handles_multiple_consecutive_anchors(tmp_path: Path) -> None:
    md = '# 1. Foo\n<span id="page-1-0"></span>\n<span id="page-1-1"></span>\n\nBody.\n'
    split_into_sections(md, tmp_path, min_body_chars=0)
    written = (tmp_path / "1. Foo.md").read_text(encoding="utf-8")
    lines = written.split("---\n\n", 1)[1].splitlines()
    assert lines[0] == "# 1. Foo"
    assert lines[1] == '<span id="page-1-0"></span>'
    assert lines[2] == '<span id="page-1-1"></span>'
    assert lines[3] == ""
    assert "Body." in lines


# --- TOC-phantom drops at split time ------------------------------


def test_toc_phantom_with_p_suffix_dropped(tmp_path: Path) -> None:
    """A heading shaped `1.1 Foo, p. 32` is a Marker-promoted TOC entry —
    drop it at split time, even if its body is non-empty (the body is a
    TOC summary that duplicates the real subsection's content)."""
    md = (
        "# 1. Real Chapter\nReal chapter prose body.\n"
        "## 1.1 Real Subsection\nReal subsection content goes here.\n"
        "## 1.1 Real Subsection, p. 32\nTOC summary stub.\n"
    )
    written = split_into_sections(md, tmp_path, min_body_chars=0)
    names = {p.name for p in written}
    assert "1.1. Real Subsection.md" in names
    assert "1.1. Real Subsection, p. 32.md" not in names


def test_toc_phantom_with_trailing_pagenum_dropped(tmp_path: Path) -> None:
    """`1.1 Foo 32` (no `p.` prefix) — also a TOC promote — drop."""
    md = (
        "# 1. Real Chapter\nbody\n"
        "## 1.1 Real Subsection\nReal content.\n"
        "## 1.1 Real Subsection 32\nTOC stub.\n"
    )
    written = split_into_sections(md, tmp_path, min_body_chars=0)
    names = {p.name for p in written}
    assert "1.1. Real Subsection.md" in names
    assert "1.1. Real Subsection 32.md" not in names


def test_toc_phantom_chapter_with_trailing_pagenum_dropped(tmp_path: Path) -> None:
    """`Chapter 1 Foo 31` — front-matter TOC entry. Drop. Note the splitter
    normalizes `Chapter N` to `N.` form, so the filename is `1. ...md`."""
    md = "# Chapter 1 Introduction\nbody\n# Chapter 1 Introduction 31\nTOC stub.\n"
    written = split_into_sections(md, tmp_path, min_level=1, min_body_chars=0)
    names = {p.name for p in written}
    # The first one survives (real chapter); the trailing-page-number twin drops.
    assert "1. Introduction.md" in names
    assert "1. Introduction 31.md" not in names


def test_toc_phantom_drop_logged_at_info(tmp_path: Path, caplog) -> None:  # type: ignore[no-untyped-def]
    """Aggregate count is logged at INFO so operators see how much TOC
    bloat was filtered."""
    import logging

    md = (
        "# 1. Real\nbody\n"
        "## 1.1 Real, p. 5\nstub\n"
        "## 1.2 Real, p. 6\nstub\n"
        "## 1.3 Real, p. 7\nstub\n"
    )
    with caplog.at_level(logging.INFO, logger="pagespeak.services._split"):
        split_into_sections(md, tmp_path, min_body_chars=0)
    assert any(
        "split_dropped_toc_phantom_sections count=3" in r.getMessage() for r in caplog.records
    )


def test_toc_phantom_does_not_drop_legit_section(tmp_path: Path) -> None:
    """False-positive guard: bare titles with trailing numbers
    (`RFC 822`, `Section 100`) without a Chapter/numbered prefix are
    real content. Don't drop."""
    md = "## RFC 822\nMail format spec content.\n## Section 100\nGeneral provisions.\n"
    written = split_into_sections(md, tmp_path, min_level=2, min_body_chars=0)
    names = {p.name for p in written}
    assert "RFC 822.md" in names
    assert "Section 100.md" in names


# --- ancestor-only chapter preservation under min_level ---------


def test_min_level_2_l1_chapter_preserved_in_breadcrumb(tmp_path: Path) -> None:
    """Under `min_level=2`, an L1 unnumbered chapter (`# Introduction`)
    doesn't get its own section file but DOES appear as plain-text
    breadcrumb context for its L2 children."""
    md = "# Introduction\nintro body\n## Purpose\nDescribe the purpose.\n"
    written = split_into_sections(md, tmp_path, min_level=2, min_body_chars=0)
    names = {p.name for p in written}
    # `# Introduction` does NOT get a file.
    assert "Introduction.md" not in names
    # `## Purpose` does.
    assert "Purpose.md" in names
    purpose = (tmp_path / "Purpose.md").read_text()
    # Breadcrumb shows the parent chapter as plain text (no link), since
    # the chapter file isn't on disk.
    assert "> ↑ Introduction" in purpose


def test_min_level_2_index_groups_l2_under_l1_via_top_level_walk(tmp_path: Path) -> None:
    """L2 sections whose parent is an ancestor-only L1 still appear as
    top-level entries in INDEX (no kept ancestor in the chain)."""
    md = (
        "# Introduction\n"
        "## Purpose\nbody\n"
        "## Overview\nbody\n"
        "# Getting Started\n"
        "## Logging On\nbody\n"
    )
    split_into_sections(md, tmp_path, min_level=2, min_body_chars=0)
    index = (tmp_path / "INDEX.md").read_text()
    assert "[Purpose]" in index
    assert "[Overview]" in index
    assert "[Logging On]" in index
    # The L1 chapters themselves don't appear (no file written).
    assert "[Introduction]" not in index
    assert "[Getting Started]" not in index


def test_min_level_2_numbered_l1_still_writes_file(tmp_path: Path) -> None:
    """Regression guard: numbered L1 headings (`# 1. Foo`) below
    `min_level=2` are still WRITABLE (numbered headings
    always parse). Only UNNUMBERED L1 headings become ancestor-only."""
    md = "# 1. Numbered Chapter\nbody\n## 1.1. Subsection\nsub body\n"
    written = split_into_sections(md, tmp_path, min_level=2, min_body_chars=0)
    names = {p.name for p in written}
    assert "1. Numbered Chapter.md" in names
    assert "1.1. Subsection.md" in names


def test_min_level_2_chapter_breadcrumb_in_consolidated_chain(tmp_path: Path) -> None:
    """A grandchild of an ancestor-only chapter still has the chapter
    title in its breadcrumb chain (rendered plain-text)."""
    md = "# Introduction\n## Purpose\nbody\n### Sub-Purpose\nfine-grained body content here.\n"
    split_into_sections(md, tmp_path, min_level=2, min_body_chars=0)
    sub = (tmp_path / "Sub-Purpose.md").read_text()
    assert "> ↑ Introduction" in sub
    # The kept Purpose ancestor renders as a link.
    assert "[Purpose]" in sub


def test_min_level_2_ancestor_only_does_not_appear_in_subsections_listing(
    tmp_path: Path,
) -> None:
    """The L1 chapter (ancestor-only) doesn't write a file with a
    `## Subsections` block — because no file gets written for it."""
    md = "# Introduction\n## Purpose\nbody\n"
    split_into_sections(md, tmp_path, min_level=2, min_body_chars=0)
    # No Introduction.md exists.
    assert not (tmp_path / "Introduction.md").exists()


# --- auto-fallback for non-numbered docs ---


def test_split_auto_fallback_non_numbered_h1_chapters(tmp_path: Path) -> None:
    """When no numbered headings exist (a non-numbered manual / flat manual
    case), `min_level=None` filters to numbered-only and would yield zero
    section files. Auto-fallback should detect the shallowest depth with
    multiple headings (H1 here) and retry parsing at that level."""
    md = (
        "# Main Manual\nbody for main manual.\n\n"
        "# Rigs and Signal Chain\nrigs body.\n\n"
        "# Effects\neffects body.\n"
    )
    written = split_into_sections(md, tmp_path, source_name="test")
    names = {p.name for p in written}
    assert "Main Manual.md" in names
    assert "Rigs and Signal Chain.md" in names
    assert "Effects.md" in names


def test_split_auto_fallback_chapters_at_h2(tmp_path: Path) -> None:
    """A flat manual case: one H1 (doc title) + multiple H2 chapters.
    Auto-fallback should detect H2 as the shallowest-with-multiple
    depth and parse from there."""
    md = (
        "# Studio Monitors\ntitle body.\n\n"
        "## Important Safety Instructions\nsafety body.\n\n"
        "## Quick Start\nstart body.\n\n"
        "## Reference\nreference body.\n"
    )
    written = split_into_sections(md, tmp_path, source_name="test")
    names = {p.name for p in written}
    # Auto-detect should produce H2 chapter files
    assert "Quick Start.md" in names
    assert "Reference.md" in names
    assert "Important Safety Instructions.md" in names


def test_split_numbered_docs_unaffected_by_fallback(tmp_path: Path) -> None:
    """If even ONE numbered heading exists, the default mode parses
    successfully (>0 sections) and the fallback does NOT fire. Numbered
    textbooks should behave exactly as before."""
    md = (
        "# Some Title\ntitle body.\n\n"
        "# 1. Chapter One\nchapter one body.\n\n"
        "# A Random Sidebar\nsidebar body.\n\n"
        "# 2. Chapter Two\nchapter two body.\n"
    )
    written = split_into_sections(md, tmp_path, source_name="test")
    names = {p.name for p in written}
    # Only numbered chapters become sections; non-numbered ones ignored
    assert "1. Chapter One.md" in names
    assert "2. Chapter Two.md" in names
    assert "Some Title.md" not in names
    assert "A Random Sidebar.md" not in names


def test_split_fallback_skips_lone_heading_at_shallowest_depth(tmp_path: Path) -> None:
    """When the doc has 1 H1 (the doc title) and many H2 chapters, the
    detection should find H2 (multiple) — not stop at H1 just because
    H1 has a heading. The 'shallowest with multiple' rule."""
    md = (
        "# Doc Title\nintro\n\n"
        "## Chapter A\nA body.\n\n"
        "## Chapter B\nB body.\n\n"
        "## Chapter C\nC body.\n"
    )
    written = split_into_sections(md, tmp_path, source_name="test")
    names = {p.name for p in written}
    # All three H2 chapters become sections
    assert "Chapter A.md" in names
    assert "Chapter B.md" in names
    assert "Chapter C.md" in names


def test_split_explicit_min_level_overrides_fallback(tmp_path: Path) -> None:
    """If the user explicitly passes `min_level=N`, the fallback never
    fires — the user knows what they want."""
    md = "# Non-numbered title\nbody\n"
    written = split_into_sections(md, tmp_path, min_level=2, source_name="test")
    # min_level=2 means H1 is ancestor-only, no file written
    assert written == []


def test_split_no_headings_at_all_produces_nothing(tmp_path: Path) -> None:
    """A doc with zero headings can't have its split fallback succeed —
    just write empty INDEX.md and return []."""
    md = "Just some plain body text.\nNo headings anywhere.\n"
    written = split_into_sections(md, tmp_path, source_name="test")
    assert written == []
    assert (tmp_path / "INDEX.md").exists()


# --- fallback when numbered parse misses the top level ---


def test_split_fallback_when_numbered_sections_miss_toplevel(
    tmp_path: Path,
) -> None:
    """A film-stock catalog regression. The document's real structure is
    non-numbered H1/H2 (a film-stock catalog). Its only
    'numbered' headings are deep H4 false positives — film gauges like
    `#### 35 mm and 65 mm End Use` where `35` is misparsed as a section
    number. The numbered-only parse produces 2 spurious sections, so
    the `not sections` fallback never fires and the 118 real
    headings are silently dropped.

    The fix: fall back when the numbered sections don't cover the
    document's shallowest heading depth (here numbered=H4, real=H1)."""
    md = (
        "# MOTION PICTURE CAMERA FILMS\n"
        "intro body\n"
        "## VISION3 500T Color Negative Film\n"
        "film body\n"
        "### Exposure Indexes and Filters\n"
        "exposure body\n"
        "#### 35 mm and 65 mm End Use\n"
        "gauge body\n"
        "## VISION3 250D Color Negative Film\n"
        "film body 2\n"
        "#### 16 mm End Use\n"
        "gauge body 2\n"
        "# APPENDIX\n"
        "appendix body\n"
    )
    written = split_into_sections(md, tmp_path, source_name="test")
    names = {p.name for p in written}
    # The real H1 structure must produce sections...
    assert any("MOTION PICTURE CAMERA FILMS" in n for n in names)
    assert any("APPENDIX" in n for n in names)
    # ...not just the 2 false-positive numbered headings.
    assert names != {
        "35. mm and 65 mm End Use.md",
        "16. mm End Use.md",
    }


# --- measurement-as-section-number guard ---


def test_parse_numbered_heading_rejects_measurement_shapes() -> None:
    """`<number> <lowercase unit>` is a measurement, not a section
    number. A film-stock catalog's film gauges (`#### 35 mm and 65 mm
    End Use`, `#### 16 mm End Use`) and a numbered product manual's audio jack
    size (`## 6.3 mm stereo jack plug...`) were all misparsed as
    sections 35 / 16 / 6.3. The signature: number NOT followed by a
    period, then whitespace, then a lowercase letter."""
    assert _parse_numbered_heading("#### 35 mm and 65 mm End Use") is None
    assert _parse_numbered_heading("#### 16 mm End Use") is None
    assert _parse_numbered_heading("## 6.3 mm stereo jack plug, balanced") is None
    assert _parse_numbered_heading("### 50 ohm impedance") is None


def test_parse_numbered_heading_keeps_legit_numbered_sections() -> None:
    """The guard must NOT reject real numbered sections:

    - `# 1 Introduction` — no period, but Capitalized title (a
      capitalized-title doc / quality-comparison academic-paper style).
    - `#### 2. assembly -- the fitting of parts` — period after the
      number, lowercase title (lecture-note outline-promoted style).
    - `### 35. Thermal Runaway` — period after a bare integer
      (a textbook chapter).
    - `## 1.1 Background` — decimal section, Capitalized title.
    """
    assert _parse_numbered_heading("# 1 Introduction") == (
        "#",
        "1",
        "Introduction",
    )
    got = _parse_numbered_heading("#### 2. assembly -- the fitting of parts")
    assert got is not None and got[1] == "2"
    got = _parse_numbered_heading("### 35. Thermal Runaway")
    assert got is not None and got[1] == "35"
    got = _parse_numbered_heading("## 1.1 Background")
    assert got is not None and got[1] == "1.1"


def test_split_numbered_doc_with_measurement_subheading(tmp_path: Path) -> None:
    """Integration: a numbered manual (a numbered product manual shape) whose
    real chapters are at the top level — so it stays in numbered-only
    mode, NO fallback. A deep `## 6.3 mm stereo jack plug` measurement
    sub-heading must NOT become a spurious `6/6.3. ...` section."""
    md = (
        "# 1. Preface\nintro body\n"
        "# 2. Product information\nproduct body\n"
        "# 3. Instruction manual\nmanual body\n"
        "## 6.3 mm stereo jack plug, balanced (audio in/loop out)\n"
        "jack pinout body\n"
        "# 4. Specifications\nspec body\n"
        "# 5. Regulatory information\nreg body\n"
    )
    written = split_into_sections(md, tmp_path, source_name="test")
    names = {p.name for p in written}
    assert "1. Preface.md" in names
    assert "4. Specifications.md" in names
    # The 6.3 mm jack must NOT be a top-level numbered section.
    assert not any(n.startswith("6.3.") for n in names)


def test_split_numbered_at_toplevel_does_not_fall_back(tmp_path: Path) -> None:
    """Inverse guard: when numbered headings ARE at the document's
    shallowest depth (a real numbered paper/textbook), the numbered
    parse is representative — do NOT fall back. Keeps the intentional
    coarse chapter-level split for numbered docs."""
    md = (
        "# Paper Title\n"
        "abstract body\n"
        "# 1 Introduction\n"
        "intro body\n"
        "## 1.1 Background\n"
        "bg body\n"
        "# 2 Methods\n"
        "methods body\n"
        "# 3 Results\n"
        "results body\n"
    )
    written = split_into_sections(md, tmp_path, source_name="test")
    names = {p.name for p in written}
    # Numbered sections only — `# Paper Title` (non-numbered) is NOT a
    # section in numbered-only mode.
    assert "1. Introduction.md" in names
    assert "2. Methods.md" in names
    assert "3. Results.md" in names
    assert "Paper Title.md" not in names


# --- max_level: bounded section depth (--split-max-level) ---


def test_parse_sections_max_level_inlines_deeper() -> None:
    """max_level caps section depth: a heading deeper than max_level stays inline
    as content of the enclosing section, not its own section."""
    lines = [
        "## 1.1 Overview",
        "ovw body",
        "### Learning Objectives",
        "- obj",
        "#### Detail",
        "deep body",
        "## 1.2 Next",
        "next body",
    ]
    secs = _parse_sections(lines, min_level=2, max_level=2)
    assert [s.level for s in secs] == [2, 2]
    body = "\n".join(secs[0].content_lines)
    assert "### Learning Objectives" in body
    assert "#### Detail" in body


def test_split_max_level_caps_section_depth(tmp_path: Path) -> None:
    """A textbook (title + numbered H2 + unnumbered back-matter + deep
    subsections) split with max_level=2: numbered sections AND back-matter each
    get a file; H3+ stays inline — no mislabeled `Learning Objectives.md`."""
    md = (
        "# Book Title\nintro\n\n"
        "## 1.1 Overview\novw body\n\n"
        "### Learning Objectives\n- obj\n\n"
        "#### Sub detail\ndetail\n\n"
        "## 1.2 Homeostasis\nhomeo body\n\n"
        "## Key Terms\nterm defs\n\n"
        "## Chapter Review\nreview body\n"
    )
    written = split_into_sections(md, tmp_path, source_name="test", max_level=2)
    names = {p.name for p in written}
    assert any("Overview" in n for n in names)
    assert any("Homeostasis" in n for n in names)
    assert any("Key Terms" in n for n in names)
    assert any("Chapter Review" in n for n in names)
    assert "Learning Objectives.md" not in names
    assert "Sub detail.md" not in names
    ovw = next(p for p in written if "Overview" in p.name)
    assert "Learning Objectives" in ovw.read_text()


def test_split_max_level_none_preserves_deep_split(tmp_path: Path) -> None:
    """Default (max_level=None) is unchanged — deep headings still split out."""
    md = "# Book Title\nintro\n\n## 1.1 Overview\novw\n\n### Learning Objectives\n- obj\n"
    written = split_into_sections(md, tmp_path, source_name="t")
    assert any("Learning Objectives" in p.name for p in written)


# --- sparse-shallow-group correction in fallback detection ---


def _headings_for(depth_counts: dict[int, int]) -> list[str]:
    """Synthesize a heading-only line list with the given per-depth counts."""
    lines: list[str] = []
    for depth in sorted(depth_counts):
        for n in range(depth_counts[depth]):
            lines.append(f"{'#' * depth} H{depth} item {n}")
            lines.append("body text\n")
    return lines


def test_fallback_advances_past_minimal_pair_shallow_group() -> None:
    """A flat manual case. Depth distribution is
    ``{1: 2, 2: 10, 3: 19}`` — the 2 H1s are a title + one stray
    promoted heading (a minimal pair), not a chapter group. The real
    chapter level is H2 (10 siblings). A bare 'shallowest with >=2'
    rule would return 1, burying all 10 chapters in 2 giant sections;
    the sparse-shallow-group correction advances to H2."""
    lines = _headings_for({1: 2, 2: 10, 3: 19})
    assert _detect_fallback_min_level(lines) == 2


def test_fallback_keeps_genuine_large_shallow_group() -> None:
    """A non-numbered manual regression guard. ``{1: 28, 2: 222, 3: 214, 4: 176}`` —
    H1=28 is a genuine chapter set even though H2 is far larger. The
    correction must NOT fire (candidate count 28 is not a minimal
    pair), so min_level stays 1."""
    lines = _headings_for({1: 28, 2: 222, 3: 214, 4: 176})
    assert _detect_fallback_min_level(lines) == 1


def test_fallback_keeps_h2_chapter_level_unchanged() -> None:
    """A flat manual regression guard. ``{1: 1, 2: 17, 3: 44, 4: 20}``
    — H1=1 is below the >=2 gate, H2=17 is the chapter level. H2's
    count is well above the minimal-pair threshold, so the correction
    does not fire and min_level stays 2."""
    lines = _headings_for({1: 1, 2: 17, 3: 44, 4: 20})
    assert _detect_fallback_min_level(lines) == 2


def test_fallback_does_not_flatten_genuine_two_chapter_doc() -> None:
    """Ratio guard. A real 2-chapter doc ``{1: 2, 2: 3}`` (2 chapters,
    3 short subsections total) must keep min_level=1 — the deeper
    group is not >=3x larger, so the minimal H1 pair is treated as
    the real (small) chapter set, not chrome."""
    lines = _headings_for({1: 2, 2: 3})
    assert _detect_fallback_min_level(lines) == 1


def test_fallback_advances_once_to_the_large_group() -> None:
    """``{1: 2, 2: 18, 3: 2}``: the H1 minimal pair advances to H2
    (18 >= 3*2). H2's count (18) is not a minimal pair, so detection
    stops at 2 even though a deeper H3 minimal pair exists — the
    correction only displaces sparse *shallow* chrome, it does not
    chase arbitrarily deep."""
    lines = _headings_for({1: 2, 2: 18, 3: 2})
    assert _detect_fallback_min_level(lines) == 2


def test_fallback_no_headings_returns_none() -> None:
    """Empty input still returns None (unchanged contract)."""
    assert _detect_fallback_min_level(["plain text", "more text"]) is None


def test_provenance_emits_rich_per_section_frontmatter(tmp_path: Path) -> None:
    """`provenance=` builds per-section frontmatter: the doc fields plus the
    section's derived locators (title, breadcrumb path, level) — the RAG
    locator set. A deep section carries its ancestor breadcrumb."""
    md = (
        "# Toolcraft Manual\n\n"
        "## Framework System\n\nComponents overview body, long enough to keep.\n\n"
        "### The Gizmo\n\nThe gizmo is the primary widget part — body content here.\n"
    )
    prov: dict[str, object] = {
        "source_type": "textbook",
        "source_label": "Sample Textbook",
        "source_file": "toolcraft.pdf",
        "doc_title": "Toolcraft Manual",
    }
    written = split_into_sections(md, tmp_path, min_level=2, min_body_chars=0, provenance=prov)
    gizmo = next(p for p in written if p.name == "The Gizmo.md")
    text = gizmo.read_text()
    assert text.startswith("---\n")
    assert 'source_type: "textbook"' in text
    assert 'source_label: "Sample Textbook"' in text
    assert 'doc_title: "Toolcraft Manual"' in text
    assert 'section_title: "The Gizmo"' in text
    assert "heading_level: 3" in text
    # breadcrumb path: ancestors root-first (the H1 + the H2 parent)
    assert 'section_path: ["Toolcraft Manual", "Framework System"]' in text


def test_provenance_omits_section_path_for_top_level(tmp_path: Path) -> None:
    """A top-level section (no ancestors) has no section_path field."""
    md = "# Manual\n\n## Overview\n\nBody content that is long enough to keep.\n"
    prov: dict[str, object] = {"source_type": "manual", "source_file": "m.pdf"}
    written = split_into_sections(md, tmp_path, min_level=2, provenance=prov)
    text = next(p for p in written if p.name == "Overview.md").read_text()
    assert 'section_title: "Overview"' in text
    # "Manual" (H1) is the only ancestor → it IS the path
    assert 'section_path: ["Manual"]' in text
