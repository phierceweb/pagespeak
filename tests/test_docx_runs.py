"""Tests for backends/_docx_runs.py — paragraph inline content -> markdown.

Word nests visible text inside containers (tracked insertions, fields, content
controls, smart tags, math), not only in bare ``w:r`` runs. The reader used to
dispatch on ``w:r``/``w:hyperlink`` alone with no ``else``, so every other
child vanished — silent content loss that a "successful" conversion hid.

Fixtures are authored here rather than committed as ``.docx`` blobs: this repo
is public and the real corpus is course material. Each case states the exact
expected markdown, so these are golden comparisons, not smoke tests.
"""

from __future__ import annotations

import pytest

pytest.importorskip("docx")

from docx import Document  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.text.paragraph import Paragraph  # noqa: E402
from lxml import etree  # noqa: E402

from pagespeak.backends._docx_runs import render_runs  # noqa: E402

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _run(text: str, *, bold: bool = False, italic: bool = False) -> str:
    rpr = ""
    if bold or italic:
        rpr = "<w:rPr>" + ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") + "</w:rPr>"
    return f"<w:r>{rpr}<w:t>{text}</w:t></w:r>"


def _render(paragraph_xml: str) -> str:
    """Round-trip a `w:p` fragment through a real .docx and render it."""
    doc = Document()
    anchor = doc.add_paragraph()._p
    body = anchor.getparent()
    node = etree.fromstring(f'<root xmlns:w="{_W}" xmlns:m="{_M}">{paragraph_xml}</root>')[0]
    body.insert(list(body).index(anchor), node)
    body.remove(anchor)
    para = list(doc.element.body.iterchildren(qn("w:p")))[0]
    return render_runs(Paragraph(para, doc))


class TestContainersAreNotDropped:
    """Each container held visible text that the old reader discarded whole."""

    def test_tracked_insertion_text_is_kept(self):
        xml = (
            f"<w:p>{_run('The dose is ')}"
            f'<w:ins w:id="1" w:author="a">{_run("500 mg")}</w:ins>'
            f"{_run(' per day.')}</w:p>"
        )
        assert _render(xml) == "The dose is 500 mg per day."

    def test_field_result_is_kept(self):
        xml = (
            f"<w:p>{_run('See page ')}"
            f'<w:fldSimple w:instr="PAGEREF _R">{_run("12")}</w:fldSimple>'
            f"{_run('.')}</w:p>"
        )
        assert _render(xml) == "See page 12."

    def test_content_control_text_is_kept(self):
        xml = f"<w:p>{_run('Status: ')}<w:sdt><w:sdtContent>{_run('APPROVED')}</w:sdtContent></w:sdt></w:p>"
        assert _render(xml) == "Status: APPROVED"

    def test_smart_tag_text_is_kept(self):
        xml = (
            f"<w:p>{_run('Contact ')}"
            f'<w:smartTag w:element="PersonName">{_run("the registrar")}</w:smartTag></w:p>'
        )
        assert _render(xml) == "Contact the registrar"

    def test_equation_text_is_kept(self):
        xml = (
            f"<w:p>{_run('Equation: ')}"
            "<m:oMath><m:r><m:t>pH = pKa + log(A/HA)</m:t></m:r></m:oMath></w:p>"
        )
        assert _render(xml) == "Equation: pH = pKa + log(A/HA)"

    def test_nested_containers_recurse(self):
        """A tracked insertion inside a content control — Word nests these."""
        xml = (
            f"<w:p>{_run('A ')}"
            f'<w:sdt><w:sdtContent><w:ins w:id="2" w:author="a">{_run("B")}</w:ins>'
            f"</w:sdtContent></w:sdt>{_run(' C')}</w:p>"
        )
        assert _render(xml) == "A B C"


class TestDeletionsStayDeleted:
    def test_tracked_deletion_is_not_emitted(self):
        """`w:del` is struck text. Emitting it would put removed prose back
        into the document — the opposite failure from dropping `w:ins`."""
        xml = (
            f"<w:p>{_run('Keep ')}"
            '<w:del w:id="3" w:author="a"><w:r><w:delText>REMOVED</w:delText></w:r></w:del>'
            f"{_run('this.')}</w:p>"
        )
        assert _render(xml) == "Keep this."


class TestIntraRunSeparators:
    def test_tab_separates_rather_than_fuses(self):
        xml = "<w:p><w:r><w:t>Column A</w:t><w:tab/><w:t>Column B</w:t></w:r></w:p>"
        assert _render(xml) == "Column A Column B"

    def test_break_separates_rather_than_fuses(self):
        xml = "<w:p><w:r><w:t>Line one</w:t><w:br/><w:t>Line two</w:t></w:r></w:p>"
        assert _render(xml) == "Line one Line two"

    def test_no_break_hyphen_renders_as_hyphen(self):
        xml = "<w:p><w:r><w:t>re</w:t><w:noBreakHyphen/><w:t>entry</w:t></w:r></w:p>"
        assert _render(xml) == "re-entry"


class TestExistingBehaviourPreserved:
    """The run-merge contract these constructs must not disturb."""

    def test_adjacent_same_format_runs_merge(self):
        """The `**CO****2**` shatter guard."""
        xml = f"<w:p>{_run('CO', bold=True)}{_run('2', bold=True)}</w:p>"
        assert _render(xml) == "**CO2**"

    def test_format_change_starts_a_new_segment(self):
        xml = f"<w:p>{_run('plain ')}{_run('bold', bold=True)}</w:p>"
        assert _render(xml) == "plain **bold**"

    def test_empty_runs_do_not_break_a_merge(self):
        xml = f"<w:p>{_run('CO', bold=True)}<w:r><w:t></w:t></w:r>{_run('2', bold=True)}</w:p>"
        assert _render(xml) == "**CO2**"

    def test_bold_italic_wraps_once(self):
        xml = f"<w:p>{_run('x', bold=True, italic=True)}</w:p>"
        assert _render(xml) == "***x***"

    def test_plain_paragraph_unchanged(self):
        assert _render(f"<w:p>{_run('Just prose.')}</w:p>") == "Just prose."

    def test_whitespace_only_segment_is_not_emphasised(self):
        """`** **` emphasises nothing and renders as literal asterisks. Found
        by reading real converted output, not by a unit-test hunch."""
        xml = (
            f"<w:p>{_run('A', bold=True)}<w:r><w:rPr><w:b/></w:rPr><w:tab/></w:r>{_run('B')}</w:p>"
        )
        out = _render(xml)
        assert "** **" not in out
        assert out == "**A** B"

    def test_empty_paragraph_renders_empty(self):
        assert _render("<w:p></w:p>") == ""
