from __future__ import annotations

from docx import Document

from pagespeak.backends._docx_walk import iter_body


def test_make_docx_builds_openable_file(make_docx) -> None:
    path = make_docx(
        document_xml=("<w:p><w:r><w:t>Hello</w:t></w:r></w:p>"),
        numbering_xml="",
    )
    doc = Document(str(path))
    assert [p.text for p in doc.paragraphs] == ["Hello"]


_SDT_BODY = """
<w:p><w:r><w:t>Before.</w:t></w:r></w:p>
<w:sdt><w:sdtPr/><w:sdtContent>
  <w:p><w:r><w:t>Inside a content control.</w:t></w:r></w:p>
  <w:tbl><w:tr><w:tc><w:p><w:r><w:t>CellA</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:sdtContent></w:sdt>
<w:p><w:r><w:t>After.</w:t></w:r></w:p>
"""


def test_body_level_sdt_content_is_not_skipped(make_docx) -> None:
    """A content control wrapping whole paragraphs/tables is body content.

    python-docx's `.paragraphs` and a `w:p`/`w:tbl`-only body walk both miss it,
    so the section vanishes from the document with no warning.
    """
    doc = Document(str(make_docx(document_xml=_SDT_BODY)))
    items = list(iter_body(doc))
    texts = [i.obj.text for i in items if i.kind == "paragraph"]
    assert "Inside a content control." in texts, f"body-level w:sdt dropped: {texts}"
    assert texts.index("Before.") < texts.index("Inside a content control.")
    assert texts.index("Inside a content control.") < texts.index("After.")
    assert [i.kind for i in items].count("table") == 1, "table inside w:sdt dropped"


def test_nested_sdt_is_unwrapped(make_docx) -> None:
    """Content controls nest (a repeating section inside a rich-text block)."""
    body = (
        "<w:sdt><w:sdtContent><w:sdt><w:sdtContent>"
        "<w:p><w:r><w:t>Deep.</w:t></w:r></w:p>"
        "</w:sdtContent></w:sdt></w:sdtContent></w:sdt>"
    )
    doc = Document(str(make_docx(document_xml=body)))
    assert [i.obj.text for i in iter_body(doc) if i.kind == "paragraph"] == ["Deep."]


def test_iter_body_preserves_paragraph_table_order(make_docx) -> None:
    doc_xml = (
        "<w:p><w:r><w:t>before</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>cell</w:t></w:r></w:p>"
        "</w:tc></w:tr></w:tbl>"
        "<w:p><w:r><w:t>after</w:t></w:r></w:p>"
    )
    items = list(iter_body(Document(str(make_docx(document_xml=doc_xml)))))
    assert [i.kind for i in items] == ["paragraph", "table", "paragraph"]
    assert items[0].obj.text == "before"
    assert items[2].obj.text == "after"
