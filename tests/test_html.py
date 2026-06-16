"""Tests for the inline-HTML-fragment → markdown utility.

The QTI backend (and any future caller that meets inline HTML) cleans
editor-cruft-laden HTML fragments into markdown via
`html_fragment_to_markdown`. These tests pin the behaviors that matter:
generic cruft stripping (independent of which editor produced it),
heading demotion (so quiz content never introduces ATX headings that fool
the splitter), equation-image→LaTeX, media-token resolution, and
sub/sup flattening for RAG searchability.
"""

from __future__ import annotations

from pagespeak.utils._html import html_fragment_to_markdown


def test_strips_draftjs_editor_wrapper_cruft() -> None:
    html = (
        '<div class="common-editor__text" data-block="true" data-offset-key="5ht96-0-0">'
        '<div class="public-DraftStyleDefault-block public-DraftStyleDefault-ltr" '
        'data-offset-key="5ht96-0-0"><span data-offset-key="5ht96-0-0">'
        "Following the first step, which component sends the output?"
        "</span></div></div>"
    )
    out = html_fragment_to_markdown(html)
    assert "Following the first step, which component sends the output?" in out
    assert "public-DraftStyleDefault" not in out
    assert "data-offset-key" not in out
    assert "common-editor__text" not in out


def test_strips_richtext_editor_wrapper_cruft() -> None:
    html = (
        '<div class="RichTextView__RichTextViewStyleWrapper-sc-tx6r7o-0 kMDHhP">'
        '<div class="RichTextView__RichTextWrapper-sc-pzv9x8-0 lmXPMD">'
        '<div class="renderer__RichTextParagraph-sc-1iafxs5-0 ihCGaZ">'
        "The heart sounds occur at the AV valves closing.</div></div></div>"
    )
    out = html_fragment_to_markdown(html)
    assert "The heart sounds occur at the AV valves closing." in out
    assert "RichTextView" not in out
    assert "renderer__RichTextParagraph" not in out


def test_keeps_bold_and_italic() -> None:
    html = "<div>Predict the response of the <em><strong>smooth muscle</strong></em> here.</div>"
    out = html_fragment_to_markdown(html)
    assert "smooth muscle" in out
    # bold emphasis survives as markdown
    assert "**smooth muscle**" in out or "*smooth muscle*" in out


def test_nested_bold_does_not_shatter() -> None:
    """Canvas nests <strong><b>…</b></strong>; markdownify would render
    `****word****` (the quiz-export emphasis shatter)."""
    html = "<p>Which statement <strong><b>incorrectly</b></strong> describes it?</p>"
    out = html_fragment_to_markdown(html)
    assert "**incorrectly**" in out
    assert "****" not in out


def test_doubled_strong_does_not_shatter() -> None:
    html = "<p>The <strong><strong>A band</strong></strong> stays constant.</p>"
    out = html_fragment_to_markdown(html)
    assert "**A band**" in out
    assert "****" not in out


def test_nested_em_does_not_double() -> None:
    """<em><i>…</i></em> would render `**word**` — italic disguised as bold."""
    html = "<p>see <em><i>segment</i></em> below</p>"
    out = html_fragment_to_markdown(html)
    assert "*segment*" in out
    assert "**segment**" not in out


def test_bold_italic_combination_still_works() -> None:
    """<em><strong>…</strong></em> is a legitimate bold-italic, not nesting damage."""
    html = "<p>the <em><strong>key term</strong></em> here</p>"
    out = html_fragment_to_markdown(html)
    assert "***key term***" in out


def test_equation_image_becomes_inline_latex() -> None:
    html = (
        'F = <img class="equation_image" title="\\Delta" '
        'src="https://example.instructure.com/equation_images/%255CDelta?scale=1" '
        'alt="LaTeX: \\Delta" data-equation-content="\\Delta" loading="lazy">P/R'
    )
    out = html_fragment_to_markdown(html)
    assert "$\\Delta$" in out
    assert "F =" in out
    assert "P/R" in out
    # no broken image link / no raw equation image URL
    assert "equation_images" not in out
    assert "![" not in out


def test_media_image_resolved_to_local_path() -> None:
    html = (
        '<img src="$IMS-CC-FILEBASE$/Uploaded%20Media/figure.jpg" alt="ANS v. SNS" '
        'data-api-endpoint="https://example.com/files/1" loading="lazy">'
    )
    out = html_fragment_to_markdown(html, media_resolver=lambda src: "images/figure.jpg")
    assert "![ANS v. SNS](images/figure.jpg)" in out
    assert "$IMS-CC-FILEBASE$" not in out


def test_media_image_unresolved_keeps_alt_text_no_broken_link() -> None:
    html = '<img src="$IMS-CC-FILEBASE$/Uploaded%20Media/missing.jpg" alt="A node diagram">'
    out = html_fragment_to_markdown(html, media_resolver=lambda src: "")
    assert "A node diagram" in out
    assert "]()" not in out
    assert "$IMS-CC-FILEBASE$" not in out


def test_demotes_html_headings_to_bold_not_atx() -> None:
    # Canvas instructions blocks carry <h3> tags — must NOT become `###`,
    # which would fool the per-quiz splitter.
    html = "<h3>For multiple choice questions: choose the best answer.</h3>"
    out = html_fragment_to_markdown(html)
    assert "For multiple choice questions: choose the best answer." in out
    assert "**For multiple choice questions: choose the best answer.**" in out
    assert "#" not in out


def test_flattens_subscript_and_superscript() -> None:
    html = "<div>Dissolved CO<sub>2</sub> forms HCO<sub>3</sub><sup>-</sup>.</div>"
    out = html_fragment_to_markdown(html)
    assert "CO2" in out
    assert "HCO3" in out
    # no leftover tags
    assert "<sub>" not in out
    assert "<sup>" not in out


def test_drops_hidden_proctorio_tracking_spans() -> None:
    html = (
        "<p>Real question text."
        '<span class="proctorioexam" style="display: none;">79b5fea1ee8d5c20cc598db</span>'
        "</p>"
    )
    out = html_fragment_to_markdown(html)
    assert "Real question text." in out
    assert "79b5fea1ee8d5c20cc598db" not in out


def test_decodes_html_entities() -> None:
    html = "<div>Tom &amp; Jerry&nbsp;run.</div>"
    out = html_fragment_to_markdown(html)
    assert "Tom & Jerry" in out
    assert "&amp;" not in out
    assert "&nbsp;" not in out


def test_unicode_preserved() -> None:
    html = "<div>Resistance ⇑ will decrease flow — α/β receptors.</div>"
    out = html_fragment_to_markdown(html)
    assert "⇑" in out
    assert "α/β" in out


def test_empty_and_whitespace_only_fragments() -> None:
    assert html_fragment_to_markdown("") == ""
    assert html_fragment_to_markdown("   ").strip() == ""
    assert html_fragment_to_markdown("<div></div>").strip() == ""
