from __future__ import annotations

from pagespeak.services._outline import LIST_LINE_RE, _enclosing_heading_level, promote_outline


def test_list_line_re_matches_markitdown_first_item() -> None:
    m = LIST_LINE_RE.match("* + 1. **Left unit**")
    assert m is not None
    assert m.group("markers") == "* + "
    assert m.group("indent") == ""
    assert m.group("num") == "1"
    assert m.group("content") == "**Left unit**"


def test_list_line_re_matches_deep_marker_stack() -> None:
    m = LIST_LINE_RE.match("* + - * 1. Damping junction")
    assert m is not None
    assert m.group("markers") == "* + - * "
    assert m.group("num") == "1"


def test_list_line_re_matches_space_indented_sibling() -> None:
    m = LIST_LINE_RE.match("    2. **Right unit**")
    assert m is not None
    assert m.group("markers") == ""
    assert m.group("indent") == "    "
    assert m.group("num") == "2"


def test_list_line_re_rejects_plain_bullet_and_prose() -> None:
    assert LIST_LINE_RE.match("* just a bullet") is None
    assert LIST_LINE_RE.match("Some prose sentence.") is None


def test_enclosing_heading_level() -> None:
    assert _enclosing_heading_level("# Title") == 1
    assert _enclosing_heading_level("### Sub") == 3
    assert _enclosing_heading_level("not a heading") is None
    assert _enclosing_heading_level("#nospace") is None


def test_pump_block_marker_first_item_and_siblings() -> None:
    src = (
        "# Pump is really two side-by-side units\n"
        "\n"
        "* + 1. **Left unit**\n"
        "       1. left inlet\n"
        "       2. left chamber\n"
        "    2. **Right unit**\n"
        "       1. right inlet\n"
        "    3. **Primary circuit**\n"
        "    4. **Secondary circuit**\n"
    )
    out, promoted = promote_outline(src)
    lines = out.splitlines()
    assert "## 1. **Left unit**" in lines
    assert "### 1. left inlet" in lines
    assert "### 2. left chamber" in lines
    assert "## 2. **Right unit**" in lines
    assert "## 3. **Primary circuit**" in lines
    assert "## 4. **Secondary circuit**" in lines
    assert not any("* +" in ln for ln in lines)
    assert promoted == 7


def test_depth_three_plus_becomes_nested_list_not_heading() -> None:
    src = (
        "* + 1. **Outer casing**\n"
        "       1. Outer layer\n"
        "          1. dense laminated composite material\n"
        "          2. sticks to the baseplate\n"
        "    2. **Core assembly**\n"
        "    3. **Inner lining**\n"
    )
    out, _ = promote_outline(src)
    lines = out.splitlines()
    assert "# 1. **Outer casing**" in lines
    assert "## 1. Outer layer" in lines
    assert "- 1. dense laminated composite material" in lines
    assert "- 2. sticks to the baseplate" in lines
    assert not any(ln.startswith("###") for ln in lines)
    assert not any("* +" in ln for ln in lines)


def test_blank_line_and_heading_reset_depth_stack() -> None:
    src = (
        "* + 1. Alpha\n"
        "       1. Alpha child\n"
        "\n"
        "* + 1. Beta\n"
        "       1. Beta child\n"
        "# Real Heading\n"
        "* + 1. Gamma\n"
    )
    out, _ = promote_outline(src)
    lines = out.splitlines()
    assert lines.count("# 1. Alpha") == 1
    assert lines.count("# 1. Beta") == 1
    assert "## 1. Alpha child" in lines
    assert "## 1. Beta child" in lines
    assert "## 1. Gamma" in lines


def test_too_short_no_op() -> None:
    src = "1. First\n   1. nested\n2. Second\n"
    out, promoted = promote_outline(src)
    assert (out, promoted) == (src, 0)


def test_flat_no_nesting_no_op() -> None:
    src = "1. Step one\n2. Step two\n3. Step three\n4. Step four\n"
    out, promoted = promote_outline(src)
    assert (out, promoted) == (src, 0)


def test_h6_clamp_under_deep_enclosing_heading() -> None:
    src = (
        "###### Deep enclosing heading\n"
        "* + 1. Alpha\n"
        "       1. Alpha child\n"
        "    2. Beta\n"
        "    3. Gamma\n"
    )
    out, _ = promote_outline(src)
    lines = out.splitlines()
    assert "###### 1. Alpha" in lines
    assert "###### 1. Alpha child" in lines
    assert not any(ln.startswith("#######") for ln in lines)


def test_multi_digit_numbers() -> None:
    src = "* + 1. One\n    2. Two\n    10. Ten\n       11. Eleven\n"
    out, _ = promote_outline(src)
    lines = out.splitlines()
    assert "# 10. Ten" in lines
    assert "## 11. Eleven" in lines


def test_trailing_newline_parity() -> None:
    src = "* + 1. A\n       1. a\n    2. B\n    3. C\n"
    out, _ = promote_outline(src)
    assert out.endswith("\n")
    src2 = "* + 1. A\n       1. a\n    2. B\n    3. C"
    out2, _ = promote_outline(src2)
    assert not out2.endswith("\n")


def test_migrated_markitdown_3space_k2() -> None:
    # Pure markitdown-style outline. Three depth-1 items (`3. Layout
    # planes` included) so the doc-level guard (depth1 ≥ 3) fires, under
    # the `* +` marker-first-item format.
    src = (
        "* + 1. Toolcraft terminology\n"
        "       1. First assignment\n"
        "       2. Most terms\n"
        "    2. Toolcraft\n"
        "       1. Microscopic toolcraft\n"
        "          1. subunits\n"
        "    3. Layout planes\n"
    )
    out, promoted = promote_outline(src)
    lines = out.splitlines()
    assert "# 1. Toolcraft terminology" in lines
    assert "## 1. First assignment" in lines
    assert "## 2. Most terms" in lines
    assert "# 2. Toolcraft" in lines
    assert "## 1. Microscopic toolcraft" in lines
    assert "- 1. subunits" in lines
    assert promoted == 6
    assert not any("* +" in ln for ln in lines)


_UNHEADED_PROCEDURE = (
    "Follow these steps to replace the filter cartridge.\n"
    "\n"
    "1. Turn off the unit and unplug it.\n"
    "   1. Wait five minutes for the motor to cool.\n"
    "   2. Place a towel under the housing.\n"
    "2. Remove the old cartridge.\n"
    "3. Insert the new cartridge until it clicks.\n"
    "\n"
    "The indicator light turns green when the filter is seated.\n"
)


def test_unheaded_nested_numbered_list_is_untouched() -> None:
    # No marker stack: a nested numbered list in a document with no headings
    # is a list, not a flattened outline.
    assert promote_outline(_UNHEADED_PROCEDURE) == (_UNHEADED_PROCEDURE, 0)


def test_unheaded_4space_nested_list_is_untouched() -> None:
    src = (
        "1. Hydraulics\n    1. Pump\n        1. Chambers\n2. Acoustic\n    1. Bellows\n3. Optical\n"
    )
    assert promote_outline(src) == (src, 0)


def _section_text(tmp_path, doc: str) -> str:
    from pagespeak import to_markdown

    src = tmp_path / "doc.md"
    src.write_text(doc)
    to_markdown(src, output_dir=tmp_path / "out", diagrams=False, split_sections=True)
    files = (tmp_path / "out" / "sections").rglob("*.md")
    return "\n".join(p.read_text() for p in files if p.name != "INDEX.md")


def test_unheaded_nested_list_steps_all_reach_sections(tmp_path) -> None:
    sections = _section_text(tmp_path, _UNHEADED_PROCEDURE)
    for step in (
        "Turn off the unit and unplug it.",
        "Wait five minutes for the motor to cool.",
        "Place a towel under the housing.",
        "Remove the old cartridge.",
        "Insert the new cartridge until it clicks.",
    ):
        assert step in sections, f"step missing from sections/: {step!r}"


def test_one_marker_stack_marks_the_whole_outline() -> None:
    # A list starting at the outline's top level carries no marker stack;
    # it is still part of the outline.
    src = (
        "1. **Overview**\n"
        "   1. Scope\n"
        "   2. Audience\n"
        "2. **Layout**\n"
        "\n"
        "* + 1. Frame\n"
        "       1. outer edge\n"
        "    2. Panel\n"
    )
    out, promoted = promote_outline(src)
    lines = out.splitlines()
    assert "# 1. **Overview**" in lines
    assert "## 1. Scope" in lines
    assert "# 2. **Layout**" in lines
    assert "# 1. Frame" in lines
    assert promoted == 7


_PAIRING_STEPS = (
    "## Pair a controller\n"
    "\n"
    "1. Open **Settings**.\n"
    "   1. Select **Devices**.\n"
    "2. Hold the pairing button.\n"
    "3. Choose the controller from the list.\n"
)
_STRAY_NUMBERED_BULLET_DOC = (
    "## Connections\n\n* USB-C\n* Bluetooth\n* 5. 0 GHz Wi-Fi\n* Ethernet\n\n" + _PAIRING_STEPS
)


def test_stray_numbered_bullet_does_not_mark_outline() -> None:
    # `* 5. 0 GHz` is a bullet whose text begins with a number. A wrapper
    # stack sits on a nested list's first item, which is numbered 1.
    out = promote_outline(_STRAY_NUMBERED_BULLET_DOC)
    assert out == (_STRAY_NUMBERED_BULLET_DOC, 0)


def test_stray_numbered_bullet_doc_steps_all_reach_sections(tmp_path) -> None:
    sections = _section_text(tmp_path, _STRAY_NUMBERED_BULLET_DOC)
    for step in (
        "Open **Settings**.",
        "Select **Devices**.",
        "Hold the pairing button.",
        "Choose the controller from the list.",
    ):
        assert step in sections, f"step missing from sections/: {step!r}"


def test_typed_number_bullet_list_does_not_mark_outline() -> None:
    # Each bullet carries its own number, so most stacks are not numbered 1.
    src = "* 1. Unpack the controller.\n* 2. Charge it.\n* 3. Turn it on.\n\n" + _PAIRING_STEPS
    assert promote_outline(src) == (src, 0)


def test_outline_with_one_stray_numbered_bullet_still_promotes() -> None:
    src = (
        "1. **Overview**\n"
        "   1. Scope\n"
        "2. **Layout**\n"
        "\n"
        "* + 1. Frame\n"
        "       1. outer edge\n"
        "    2. Panel\n"
        "\n"
        "* + 1. Hinges\n"
        "    2. Latches\n"
        "\n"
        "* 3. 5 mm hex key\n"
    )
    out, _ = promote_outline(src)
    lines = out.splitlines()
    assert "# 1. **Overview**" in lines
    assert "# 1. Frame" in lines
    assert "# 1. Hinges" in lines


def test_migrated_nests_under_existing_heading() -> None:
    # Existing `#` headings are preserved; the outline nests under them.
    src = (
        "# Conduits involved\n"
        "* + 1. Mains\n"
        "       1. high pressure\n"
        "    2. Branches\n"
        "    3. Capillaries\n"
        "# Casing: material layers\n"
        "* + 1. Outer casing\n"
        "    2. Core assembly\n"
        "    3. Inner lining\n"
    )
    out, _ = promote_outline(src)
    lines = out.splitlines()
    assert "# Conduits involved" in lines
    assert "# Casing: material layers" in lines
    assert "## 1. Mains" in lines
    assert "### 1. high pressure" in lines
    assert "## 2. Branches" in lines
    assert "## 1. Outer casing" in lines


def test_migrated_irregular_indent_relative_depth() -> None:
    # Off-step indents are not dropped; relative depth is assigned from
    # the stack.
    src = (
        "* + 1. Alpha\n"
        "      1. Alpha child (6sp)\n"
        "    2. Beta (4sp, sibling of Alpha)\n"
        "        1. Beta child (8sp)\n"
        "    3. Gamma\n"
    )
    out, _ = promote_outline(src)
    lines = out.splitlines()
    assert "# 1. Alpha" in lines
    assert "## 1. Alpha child (6sp)" in lines
    assert "# 2. Beta (4sp, sibling of Alpha)" in lines
    assert "## 1. Beta child (8sp)" in lines
    assert "# 3. Gamma" in lines
    assert not any("* +" in ln for ln in lines)


def test_reader_clean_headed_nested_list_is_untouched() -> None:
    # python-docx reader output: real `#` headings + clean `1.`/`  1.`
    # nested lists, no marker stack, every list already under a heading.
    # promote_outline must leave it unchanged.
    src = (
        "# Stages of shipping (fig. 4.2)\n"
        "\n"
        "1. **Order intake **\n"
        "  1. **Order entry** (capture)\n"
        "  2. Stock check between warehouse and store shelves\n"
        "2. **Packing (box selection)**\n"
        "3. Parcel transport on the route\n"
        "  1. Label printing onto the carton\n"
    )
    out, promoted = promote_outline(src)
    assert (out, promoted) == (src, 0)
    assert not any(ln.startswith("##") for ln in out.splitlines())


def test_unheaded_preamble_with_real_heading_spine_is_untouched() -> None:
    # The reader did NOT promote the title, so a numbered "Before you
    # begin" preamble sits at h==0 BEFORE the first real `#` heading —
    # but the doc HAS a genuine `#` section spine (numbered items also
    # live under it, h>=1). That is a preamble, not a flattened outline:
    # promote_outline MUST NO-OP.
    src = (
        "Equilibrium and Control Signals (Chapters 1, 5)\n"
        "\n"
        "1. Major levels of modular organization\n"
        "  1. Unit differentiation\n"
        "2. Major device systems and primary functions\n"
        "3. Four basic component types\n"
        "# Widgetry – the study of function\n"
        "\n"
        "1. We emphasize patterns and connections\n"
        "  1. Exchange across surface components\n"
        "2. Fluid compartments\n"
        "# Negative feedback (fig. 1.6)\n"
    )
    out, promoted = promote_outline(src)
    assert (out, promoted) == (src, 0)
    # No cascade: the preamble + the headed sections stay as-is.
    assert not any(ln.startswith("# 1.") for ln in out.splitlines())
    assert "# Widgetry – the study of function" in out.splitlines()
