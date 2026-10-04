from __future__ import annotations

from docx import Document

from pagespeak.backends._docx_structured import render_markdown

_NUM2 = """
<w:abstractNum w:abstractNumId="0">
  <w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl>
  <w:lvl w:ilvl="1"><w:numFmt w:val="decimal"/></w:lvl>
</w:abstractNum>
<w:abstractNum w:abstractNumId="1">
  <w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl>
  <w:lvl w:ilvl="1"><w:numFmt w:val="decimal"/></w:lvl>
</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>
"""

_DECIMAL_HEADINGS = """
<w:abstractNum w:abstractNumId="5">
  <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
  <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2."/></w:lvl>
</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="5"/></w:num>
"""


def _linked_styles(extra: str = "") -> str:
    """Word's numbered-heading template: `Heading N` linked to a multilevel list
    on the style; content lists use their own numId."""
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
  <w:pPr><w:numPr><w:numId w:val="1"/></w:numPr><w:outlineLvl w:val="0"/></w:pPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>
  <w:basedOn w:val="Heading1"/>
  <w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr><w:outlineLvl w:val="1"/></w:pPr>
</w:style>
<w:style w:type="paragraph" w:styleId="ListNumber"><w:name w:val="List Number"/>
  <w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr></w:pPr>
</w:style>
{extra}
</w:styles>"""


def _p(text: str, ppr: str = "") -> str:
    return f"<w:p><w:pPr>{ppr}</w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>"


def _styled(style: str, text: str, numpr: str = "") -> str:
    return _p(text, f'<w:pStyle w:val="{style}"/>{numpr}')


def _render(make_docx, xml: str, numbering: str = _NUM2, styles: str | None = None) -> list[str]:
    docx = make_docx(
        document_xml=xml, numbering_xml=numbering, styles_xml=styles or _linked_styles()
    )
    return render_markdown(Document(str(docx)), None).splitlines()


def test_heading_style_linked_to_numbering_is_a_heading(make_docx) -> None:
    xml = (
        _styled("Heading1", "Overview")
        + _p("What the system does.")
        + _styled("Heading2", "Scope")
        + _p("Which parts are covered.")
        + _styled("Heading1", "Installation")
        + _p("How to install it.")
    )
    lines = _render(make_docx, xml)
    assert "# Overview" in lines, "\n".join(lines)
    assert "## Scope" in lines
    assert "# Installation" in lines
    assert "What the system does." in lines


def test_list_style_under_linked_headings_stays_a_list(make_docx) -> None:
    xml = (
        _styled("Heading1", "Setup")
        + _styled("ListNumber", "Unpack the unit.")
        + _styled("ListNumber", "Connect the power.")
        + _styled("Heading1", "Usage")
        + _styled("ListNumber", "Press start.")
    )
    lines = _render(make_docx, xml)
    assert "# Setup" in lines, "\n".join(lines)
    assert "1. Unpack the unit." in lines
    assert "2. Connect the power." in lines
    assert "# Usage" in lines
    assert "1. Press start." in lines


_OFF = '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr>'


def test_numbering_switched_off_is_no_list_and_takes_no_number(make_docx) -> None:
    # Word writes `numId` 0 to switch a paragraph's numbering off, overriding its style.
    xml = (
        _styled("Heading1", "One")
        + _p("Body.")
        + _styled("Heading1", "Appendix", _OFF)
        + _p("Body.")
        + f'<w:p><w:pPr><w:pStyle w:val="Heading2"/>{_OFF}</w:pPr></w:p>'
        + _styled("Heading1", "Two")
        + _styled("ListNumber", "Plain line", _OFF)
    )
    lines = _render(make_docx, xml, _DECIMAL_HEADINGS)
    assert "# 1. One" in lines, "\n".join(lines)
    assert "# Appendix" in lines
    assert "# 2. Two" in lines
    assert "Plain line" in lines
    assert not any(ln.strip() == "1." or ln.startswith("1. Plain") for ln in lines)


def test_numbering_switched_off_on_a_style_is_no_list(make_docx) -> None:
    toc_heading = (
        '<w:style w:type="paragraph" w:styleId="TOCHeading"><w:name w:val="TOC Heading"/>'
        '<w:basedOn w:val="Heading1"/><w:pPr><w:numPr><w:numId w:val="0"/></w:numPr></w:pPr>'
        "</w:style>"
    )
    xml = _styled("TOCHeading", "Contents") + _styled("Heading1", "Overview") + _p("Body.")
    lines = _render(make_docx, xml, _DECIMAL_HEADINGS, _linked_styles(toc_heading))
    assert not any(ln.endswith("1. Contents") for ln in lines), "\n".join(lines)
    assert "# 1. Overview" in lines


def test_heading_numbered_on_another_list_stays_in_the_outline(make_docx) -> None:
    # Its own numbering on a list other than its style's puts it in the outline,
    # whose `pStyle` is ignored: at the default depth it stays a list item.
    own = '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr>'
    lines = _render(make_docx, _styled("Heading1", "Chap", own))
    assert "1. Chap" in lines, "\n".join(lines)


def test_heading_continuing_its_style_list_stays_a_heading(make_docx) -> None:
    # Word's Set Numbering Value / Restart Numbering on a heading writes a new
    # numId on the paragraph, over the same list definition as its style.
    restart = (
        '<w:num w:numId="7"><w:abstractNumId w:val="5"/>'
        '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="5"/></w:lvlOverride></w:num>'
    )
    xml = (
        _styled("Heading1", "One")
        + _p("Body.")
        + _styled("Heading1", "Five", '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="7"/></w:numPr>')
        + _p("Its body.")
        + _styled("Heading2", "Sub")
        + _p("Body.")
        + _styled("Heading1", "Six")
        + _p("Body.")
    )
    lines = _render(make_docx, xml, _DECIMAL_HEADINGS + restart)
    assert "# 5. Five" in lines, "\n".join(lines)
    assert "Its body." in lines
    assert "## 5.1. Sub" in lines
    assert "# 6. Six" in lines


def test_heading_given_its_own_level_keeps_the_style_list(make_docx) -> None:
    # An `ilvl` without a `numId` on the paragraph moves it to another level of
    # its style's list; `numId` and `ilvl` inherit separately.
    xml = (
        _styled("Heading1", "One")
        + _p("Body.")
        + _styled("Heading1", "Demoted", '<w:numPr><w:ilvl w:val="1"/></w:numPr>')
        + _p("Body.")
        + _styled("Heading1", "Two")
        + _p("Body.")
    )
    lines = _render(make_docx, xml, _DECIMAL_HEADINGS)
    assert "# 1.1. Demoted" in lines, "\n".join(lines)
    assert "# 2. Two" in lines


def test_style_numbering_resolves_through_a_long_based_on_chain(make_docx) -> None:
    chain = "".join(
        f'<w:style w:type="paragraph" w:styleId="L{s}"><w:name w:val="List {s}"/>'
        f'<w:basedOn w:val="L{base}"/></w:style>'
        for s, base in (("B", "A"), ("C", "B"), ("D", "C"), ("E", "D"))
    )
    list_a = (
        '<w:style w:type="paragraph" w:styleId="LA"><w:name w:val="List A"/>'
        '<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr></w:pPr></w:style>'
    )
    xml = "".join(_styled(f"L{s}", f"via {s}") for s in "BCDE")
    lines = _render(make_docx, xml, styles=_linked_styles(list_a + chain))
    for n, s in enumerate("BCDE", start=1):
        assert f"{n}. via {s}" in lines, "\n".join(lines)
