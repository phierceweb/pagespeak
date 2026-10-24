from __future__ import annotations

from docx import Document

from pagespeak.backends._docx_structured import render_markdown
from pagespeak.services._image_refs import parse_image_refs

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
    b"\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx"
    b"\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)

_IMAGE_REL = (
    '<Relationship Id="rIdImg" Type="http://schemas.'
    "openxmlformats.org/officeDocument/2006/relationships/image"
    '" Target="media/image1.png"/>'
)


def _drawing(descr: str) -> str:
    return (
        "<w:p><w:r><w:drawing><wp:inline>"
        f'<wp:docPr id="1" name="pic" descr="{descr}"/>'
        "<a:graphic><a:graphicData><pic:pic "
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:blipFill><a:blip r:embed="rIdImg"/></pic:blipFill>'
        "</pic:pic></a:graphicData></a:graphic>"
        "</wp:inline></w:drawing></w:r></w:p>"
    )


def _render(make_docx, tmp_path, descr: str) -> str:
    path = make_docx(
        document_xml=_drawing(descr),
        extra_parts={"word/media/image1.png": _PNG},
        doc_rels=_IMAGE_REL,
    )
    return render_markdown(Document(str(path)), tmp_path)


# Word writes auto-generated alt as "<subject>\n\nDescription automatically
# generated". The blank line inside it ends `parse_image_refs`' scan for the
# closing `]`, so the ref parses as nothing and every later pass — the vision
# caption/mermaid injection included — skips the image.
_WORD_AUTO_ALT = "A diagram of a company&#10;&#10;Description automatically generated"


def test_multiline_alt_stays_on_one_line(make_docx, tmp_path) -> None:
    md = _render(make_docx, tmp_path, _WORD_AUTO_ALT)
    ref_line = next(line for line in md.splitlines() if line.startswith("!["))
    assert ref_line.endswith("](images/image1.png)"), md
    assert "Description automatically generated" in ref_line


def test_multiline_alt_ref_is_parseable(make_docx, tmp_path) -> None:
    md = _render(make_docx, tmp_path, _WORD_AUTO_ALT)
    refs = parse_image_refs(md)
    assert [r.target for r in refs] == ["images/image1.png"], md
    assert "\n" not in refs[0].alt


def test_tab_and_cr_in_alt_are_flattened(make_docx, tmp_path) -> None:
    md = _render(make_docx, tmp_path, "left&#9;&#13;&#10;right")
    assert "![left right](images/image1.png)" in md


def test_single_line_alt_is_unchanged(make_docx, tmp_path) -> None:
    md = _render(make_docx, tmp_path, "A widget")
    assert "![A widget](images/image1.png)" in md


def test_absent_alt_still_emits_ref(make_docx, tmp_path) -> None:
    md = _render(make_docx, tmp_path, "")
    assert "![](images/image1.png)" in md
