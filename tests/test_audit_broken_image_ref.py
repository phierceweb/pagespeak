"""Tests for the `broken_image_ref` audit check.

An image ref the parser cannot close is invisible to every later pass —
no caption, no mermaid — and `dangling_image_ref` is itself parser-gated,
so without this check nothing reports it at all.
"""

from __future__ import annotations

from pagespeak.services._audit_image_refs import check_broken_image_ref

# Word writes auto-generated alt with a blank line in it; the blank line ends
# the parser's scan for the closing `]`, so the ref parses as nothing.
_WORD_SHAPE = "![A diagram of a company\n\nDescription automatically generated](images/a.png)\n"


def test_blank_line_in_alt_is_flagged() -> None:
    findings = check_broken_image_ref(_WORD_SHAPE)
    assert findings
    assert findings[0].check == "broken_image_ref"
    assert findings[0].severity == "error"
    assert findings[0].line == 1


def test_valid_ref_is_not_flagged() -> None:
    assert not check_broken_image_ref("![A widget](images/a.png)\n")


def test_valid_ref_with_brackets_in_alt_is_not_flagged() -> None:
    """The parser tolerates unmatched brackets in alt; the check must too."""
    assert not check_broken_image_ref("![range [-3, 5) shown](images/a.png)\n")


def test_bare_bracket_without_a_target_is_not_flagged() -> None:
    """No target means no image — there is no figure to have lost. Only a ref a
    whitespace fix would repair counts."""
    assert not check_broken_image_ref("![never closed\n\nprose follows\n")


def test_code_using_bang_before_a_bracket_is_not_flagged() -> None:
    """`!` before a bracket is ordinary in code. Unfenced source dumped into
    prose is a real conversion shape, and flagging it claimed a figure had
    lost its caption when no image existed."""
    js = "if (!['ArrowDown', 'ArrowUp'].includes(e.key)) return;\n"
    assert not check_broken_image_ref(js)


def test_shortcut_reference_image_is_not_flagged() -> None:
    """`![Figure 1]` with a matching definition is a valid CommonMark shortcut
    reference image, carrying no inline target."""
    assert not check_broken_image_ref("See ![Figure 1] for detail.\n\n[Figure 1]: images/f1.png\n")


def test_reference_image_with_brackets_in_alt_is_not_flagged() -> None:
    assert not check_broken_image_ref("![Fig [2]][f2]\n\n[f2]: images/f2.png\n")


def test_fenced_code_is_not_flagged() -> None:
    """Markdown inside a fence is content being shown, not a defect."""
    text = "Example:\n\n```markdown\n![alt spanning\n\nlines](x.png)\n```\n"
    assert not check_broken_image_ref(text)


def test_inline_code_is_not_flagged() -> None:
    """The backticked ref must NOT be self-closing, or it parses on the raw text
    and the `covered` guard suppresses it before inline-code blanking is
    consulted — the test would then pass without exercising `_scannable`."""
    text = "Write `![alt` then the target to embed it.\n\nlater](x.png)\n"
    assert not check_broken_image_ref(text)


def test_escaped_bang_is_not_flagged() -> None:
    """Needs a target, or `_repairable_by_flattening` returns False first and
    the `escaped` guard never decides anything."""
    assert not check_broken_image_ref("A literal \\![alt spanning\n\nlines](x.png) here.\n")


def test_a_distant_target_does_not_vouch_for_a_stray_bracket() -> None:
    """`_REF_REPAIR_WINDOW` bounds the lookahead. Unbounded, this stray `![`
    swallows ~3,800 characters of prose as its alt and is reported; the bound
    also keeps the check from going quadratic on a doc full of stray `![`.

    No `![` may sit between the stray and the target — the parser prefers the
    closer candidate, which would mask the bound.
    """
    text = "![stray\n\n" + ("filler prose here. " * 200) + "\n](images/a.png)\n"
    assert not check_broken_image_ref(text)


def test_reference_style_image_is_not_flagged() -> None:
    """`![alt][id]` is valid CommonMark; `parse_image_refs` reads inline refs
    only, so flagging it would call correct markdown an error."""
    assert not check_broken_image_ref("![A widget][fig1]\n\n[fig1]: images/a.png\n")


def test_indented_list_content_is_still_scanned() -> None:
    """Four-space indentation is nested-list content in converted output, not a
    code block — a broken ref there must still be caught."""
    assert check_broken_image_ref("- item\n    ![A widget\n\n    broken](x.png)\n")


def test_line_number_points_at_the_occurrence() -> None:
    text = "intro\n\nmore prose\n\n" + _WORD_SHAPE
    assert check_broken_image_ref(text)[0].line == 5


def test_reports_each_broken_ref() -> None:
    text = _WORD_SHAPE + "\nmiddle\n\n" + _WORD_SHAPE
    assert len(check_broken_image_ref(text)) == 2


def test_valid_and_broken_together_flags_only_the_broken() -> None:
    text = "![fine](a.png)\n\n" + _WORD_SHAPE
    findings = check_broken_image_ref(text)
    assert len(findings) == 1
    assert findings[0].line == 3


def test_check_is_registered_so_audit_actually_runs_it() -> None:
    """The registration line is what makes the check exist for a user; without
    this, dropping it in a rebase leaves the suite green and `pagespeak audit`
    silently stops reporting broken refs."""
    from pagespeak.services._audit_checks import _TEXT_CHECKS, run_text_checks

    assert check_broken_image_ref in _TEXT_CHECKS
    assert [f.check for f in run_text_checks(_WORD_SHAPE)] == ["broken_image_ref"]


def test_a_following_link_does_not_vouch_for_a_stray_bracket() -> None:
    """Markdown links are everywhere. A stray `![` reaching past itself to
    borrow a following link's `]` made ordinary prose an error — both of these
    stray shapes occur in real converted output."""
    js = "if (!['ArrowDown'].includes(e.key)) return;\n\nSee the [ref](https://e.test/c).\n"
    assert not check_broken_image_ref(js)
    cdata = "<![CDATA[ x ]]>\n\nSee the [manual](https://e.test/m).\n"
    assert not check_broken_image_ref(cdata)
    stray = "![stray\n\nSee the [manual](https://e.test/m).\n"
    assert not check_broken_image_ref(stray)
