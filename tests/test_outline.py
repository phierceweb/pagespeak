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


def test_migrated_pandoc_4space_k2() -> None:
    # Pure 4-space indentation, no list marker.
    src = (
        "1. Hydraulics\n    1. Pump\n        1. Chambers\n2. Acoustic\n    1. Bellows\n3. Optical\n"
    )
    out, promoted = promote_outline(src)
    lines = out.splitlines()
    assert "# 1. Hydraulics" in lines
    assert "## 1. Pump" in lines
    assert "- 1. Chambers" in lines
    assert "# 2. Acoustic" in lines
    assert "# 3. Optical" in lines
    assert promoted == 5


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
    # The no-regression invariant. python-docx reader output: real
    # `#` headings + clean `1.`/`  1.` nested lists, NO marker-stack,
    # every list already under a heading. Neither flattened-outline
    # fingerprint is present, so promote_outline MUST be a no-op — the
    # heading-cascade regression must not recur.
    src = (
        "# Steps of transport (fig. 16.1)\n"
        "\n"
        "1. **External transport **\n"
        "  1. **Primary intake** (loading)\n"
        "  2. Fluid exchange between chambers and primary channel beds\n"
        "2. **Internal transport (modular transport)**\n"
        "3. Fluid transport in the line\n"
        "  1. Carrier loading onto the medium\n"
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
