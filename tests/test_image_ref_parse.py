"""Tests for the shared markdown image-ref parser."""

from __future__ import annotations

import time
import types

from pagespeak.services._image_refs import parse_image_refs

BRACKET_ALT = "![A diagram labeled, [a], and, [b], showing a reaction](images/fig.webp)"
TITLED = '![Widget alpha](images/widget_alpha.jpg "Widget alpha detail")'


def test_alt_with_balanced_brackets_is_parsed() -> None:
    """Alt text containing `[...]` must not truncate the match."""
    refs = parse_image_refs(BRACKET_ALT)
    assert len(refs) == 1
    assert refs[0].target == "images/fig.webp"
    assert refs[0].alt == "A diagram labeled, [a], and, [b], showing a reaction"


def test_title_is_not_folded_into_target() -> None:
    refs = parse_image_refs(TITLED)
    assert len(refs) == 1
    assert refs[0].target == "images/widget_alpha.jpg"


def test_angle_wrapped_target_is_unwrapped() -> None:
    refs = parse_image_refs("![alt](<Question 001.png>)")
    assert len(refs) == 1
    assert refs[0].target == "Question 001.png"


def test_bracket_alt_and_title_together() -> None:
    refs = parse_image_refs('![Ion [Co(NH3)6]3+ shown](images/ion.webp "Complex ion")')
    assert len(refs) == 1
    assert refs[0].target == "images/ion.webp"
    assert refs[0].alt == "Ion [Co(NH3)6]3+ shown"


def test_multiple_refs_on_one_line_do_not_merge() -> None:
    refs = parse_image_refs("![one](a.png) text ![two](b.png)")
    assert [r.target for r in refs] == ["a.png", "b.png"]


def test_span_covers_the_whole_ref() -> None:
    """`span` must bound the full `![...](...)` so callers can rewrite it."""
    refs = parse_image_refs(f"lead {BRACKET_ALT} tail")
    start, end = refs[0].span
    assert BRACKET_ALT[:20] in f"lead {BRACKET_ALT} tail"[start:end]
    assert f"lead {BRACKET_ALT} tail"[start:end] == BRACKET_ALT


def test_line_is_one_based() -> None:
    refs = parse_image_refs("first\n\n![alt](x.png)")
    assert refs[0].line == 3


def test_unclosed_alt_bracket_is_not_a_ref() -> None:
    assert parse_image_refs("![never closed (x.png)") == []


def test_plain_link_is_not_an_image_ref() -> None:
    assert parse_image_refs("[not an image](x.png)") == []


def test_title_is_captured_so_callers_can_rebuild() -> None:
    """A caller retargeting a ref must be able to preserve its title."""
    refs = parse_image_refs('![alt](old.png "Keep me")')
    assert refs[0].title == "Keep me"
    assert parse_image_refs("![alt](x.png)")[0].title is None


def test_interval_notation_in_alt_does_not_swallow_later_refs() -> None:
    """Real alt text carries unmatched brackets: `[-3, 5)`, `(0, 1]`.

    Balanced-bracket scanning pairs the `[` of one ref with the `]` of a later
    one and consumes everything between, silently losing every ref in the gap.
    """
    text = (
        "![A graph of the interval [-3, 5) on a number line](images/a.webp)\n\n"
        "![A second figure](images/b.webp)\n\n"
        "![A graph of (0, 1] shaded](images/c.webp)\n\n"
        "![A fourth figure](images/d.webp)\n"
    )
    assert [r.target for r in parse_image_refs(text)] == [
        "images/a.webp",
        "images/b.webp",
        "images/c.webp",
        "images/d.webp",
    ]


def test_alt_is_not_allowed_to_span_a_blank_line() -> None:
    """An unclosed alt must not run away across paragraphs."""
    text = "![unclosed alt (\n\nA new paragraph](images/x.webp)"
    assert [r.target for r in parse_image_refs(text)] == []


def test_nested_bracket_alt_still_parses_when_genuinely_balanced() -> None:
    refs = parse_image_refs("![Ion [Co(NH3)6]3+ diagram](images/ion.webp)")
    assert len(refs) == 1
    assert refs[0].alt == "Ion [Co(NH3)6]3+ diagram"


def test_line_numbers_match_a_from_scratch_count() -> None:
    text = "intro\n\n" + "".join(f"para {i}\n\n![Fig {i}](images/{i}.webp)\n\n" for i in range(50))
    for ref in parse_image_refs(text):
        assert ref.line == text.count("\n", 0, ref.span[0]) + 1


def test_alt_end_candidates_is_lazy() -> None:
    """Per-ref work must not depend on how far away the next blank line is.

    Collecting every candidate up front means each ref scans to the end of its
    paragraph; inside a blank-line-free region — a table with an image per row —
    that is quadratic. The caller takes the first candidate that parses, so the
    scan has to stop there.
    """
    from pagespeak.services._image_refs import _alt_end_candidates

    assert isinstance(_alt_end_candidates("![a](x.png)", 2), types.GeneratorType)


def test_parsing_scales_linearly_inside_a_blank_line_free_block() -> None:
    """A markdown table with one image per row: the shape with no blank line to
    bound the scan, and the one a paragraph-based fixture cannot exercise."""

    def build(n: int) -> str:
        return "\n".join(
            f"| ![Figure {i} showing a thing](images/{i}.png) | cell |" for i in range(n)
        )

    def elapsed(text: str) -> float:
        start = time.perf_counter()
        assert len(parse_image_refs(text)) == text.count("![")
        return time.perf_counter() - start

    small, large = build(500), build(2000)
    elapsed(small)  # warm any import-time cost
    ratio = elapsed(large) / max(elapsed(small), 1e-6)
    assert ratio < 12, f"4x the rows took {ratio:.1f}x the time — parsing is superlinear"


def test_stray_image_marker_does_not_fuse_with_a_later_ref() -> None:
    """A `![` that opens no ref must not swallow the prose up to the next one.

    The alt of the fused match spans both, and the always-on degrade pass then
    rewrites that whole span to an italic caption — deleting the sentence.
    """
    text = "See ![Fig 1][fig1] for the setup, then ![](images/gone.png) at the foot."
    refs = parse_image_refs(text)
    assert [r.target for r in refs] == ["images/gone.png"]
    assert refs[0].alt == ""
    assert text[refs[0].span[0] : refs[0].span[1]] == "![](images/gone.png)"


def test_literal_bang_bracket_in_prose_does_not_fuse() -> None:
    text = "Prices ![50% off! then see ![Fig](images/a.png) below."
    refs = parse_image_refs(text)
    assert [(r.alt, r.target) for r in refs] == [("Fig", "images/a.png")]


def test_alt_containing_a_closed_inner_marker_still_parses_whole() -> None:
    """An inner `![` that is itself closed by a `]` is content, not a ref opener —
    real converter output puts markup like `[u]Turn![/u]` inside a description."""
    text = '![A sign reading "Remember to [u]Turn![/u]" beside a road](images/sign.webp)'
    refs = parse_image_refs(text)
    assert len(refs) == 1
    assert refs[0].target == "images/sign.webp"
    assert refs[0].alt.startswith('A sign reading "Remember')


def test_target_with_balanced_parens_is_not_truncated() -> None:
    """CommonMark allows balanced parens in an unbracketed destination. Stopping
    at the first `)` yields a corrupt target and leaks the tail into prose —
    silently wrong rather than unparsed, so no audit check reports it."""
    refs = parse_image_refs("![Fig](images/fig_(1).png)\n")
    assert [(r.alt, r.target) for r in refs] == [("Fig", "images/fig_(1).png")]


def test_target_with_nested_balanced_parens() -> None:
    refs = parse_image_refs("![Fig](images/a_(b_(c)_d).png)\n")
    assert [r.target for r in refs] == ["images/a_(b_(c)_d).png"]


def test_unbalanced_paren_still_ends_the_target() -> None:
    """An unmatched `)` closes the destination, as it always did."""
    refs = parse_image_refs("![Fig](images/plain.png) trailing) text\n")
    assert [r.target for r in refs] == ["images/plain.png"]


def test_escaped_paren_in_target_is_not_counted() -> None:
    refs = parse_image_refs(r"![Fig](images/a\(b.png)" + "\n")
    assert [r.target for r in refs] == [r"images/a\(b.png"]


def test_unbalanced_open_paren_still_parses() -> None:
    """Balancing must be strictly additive. Refusing an unbalanced `(` drops the
    ref entirely, and a ref that is simply absent is reported by nothing —
    worse than the truncated target this change set out to fix."""
    refs = parse_image_refs("![Fig](images/a_(b.png)\n")
    assert [r.target for r in refs] == ["images/a_(b.png"]


def test_backslash_at_end_of_line_does_not_run_into_the_next() -> None:
    """The escape skip must never step over a newline, or the destination
    swallows the following line."""
    assert parse_image_refs("![Fig](images/a\\\n# A Heading\n") == []


def test_angle_wrapped_target_with_parens_unaffected() -> None:
    refs = parse_image_refs("![Fig](<images/fig (1).png>)\n")
    assert [r.target for r in refs] == ["images/fig (1).png"]
