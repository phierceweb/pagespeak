from __future__ import annotations

from pathlib import Path

from pagespeak.backends._docx import (
    _append_image_refs,
    _extract_epub_media,
    _extract_office_media,
    _markdown_has_image_refs,
    _retarget_image_refs,
)


def test_extract_office_media_pulls_embedded_images(fake_docx: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    images = _extract_office_media(fake_docx, out)
    assert len(images) == 2
    names = {p.name for p in images}
    assert names == {"image1.png", "image2.png"}
    for p in images:
        assert p.exists()
        assert p.read_bytes()[:4] == b"\x89PNG"


def test_extract_office_media_handles_pptx(fake_pptx: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    images = _extract_office_media(fake_pptx, out)
    assert len(images) == 1
    assert images[0].name == "image1.png"


def test_extract_office_media_returns_empty_for_non_zip(tmp_path: Path) -> None:
    not_a_zip = tmp_path / "fake.docx"
    not_a_zip.write_text("definitely not a zip")
    assert _extract_office_media(not_a_zip, tmp_path / "out") == []


def test_extract_epub_media_pulls_images_by_extension(fake_epub: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    images = _extract_epub_media(fake_epub, out)
    assert {p.name for p in images} == {"f0015-01.jpg", "9781400838080.jpg"}
    for p in images:
        assert p.exists()
        assert p.parent == out / "images"
        assert p.read_bytes()[:4] == b"\x89PNG"


def test_extract_epub_media_returns_empty_for_non_zip(tmp_path: Path) -> None:
    not_a_zip = tmp_path / "fake.epub"
    not_a_zip.write_text("definitely not a zip")
    assert _extract_epub_media(not_a_zip, tmp_path / "out") == []


def test_retarget_image_refs_rewrites_matching_basenames(tmp_path: Path) -> None:
    images = [tmp_path / "images" / "f0015-01.jpg"]
    md = "![image](../images/f0015-01.jpg)\nplain ![x](../images/other.jpg)\n"
    out = _retarget_image_refs(md, images)
    assert "![image](images/f0015-01.jpg)" in out
    # A ref with no matching extracted file is left untouched.
    assert "![x](../images/other.jpg)" in out


def test_retarget_image_refs_noop_without_images() -> None:
    md = "![image](../images/f0015-01.jpg)\n"
    assert _retarget_image_refs(md, []) == md


def test_markdown_has_image_refs_detects_present() -> None:
    assert _markdown_has_image_refs("hello ![alt](path.png) world")
    assert not _markdown_has_image_refs("plain text")
    assert not _markdown_has_image_refs("almost ![alt] but not quite")


def test_append_image_refs_adds_section(tmp_path: Path) -> None:
    img = tmp_path / "images" / "a.png"
    img.parent.mkdir()
    img.write_bytes(b"x")
    out = _append_image_refs("body text", [img], tmp_path)
    assert "## Extracted Images" in out
    assert "![a.png](images/a.png)" in out


def test_strip_dead_data_uri_image_line() -> None:
    from pagespeak.backends._docx import _strip_dead_data_uri_images

    md = "Intro\n\n![](data:image/png;base64...)\n\nFigure 1. Blood flow\n"
    out = _strip_dead_data_uri_images(md)
    assert "data:image" not in out
    assert "Figure 1. Blood flow" in out
    assert "Intro" in out
    assert "\n\n\n" not in out


def test_strip_keeps_real_image_refs() -> None:
    from pagespeak.backends._docx import _strip_dead_data_uri_images

    md = "![alt](images/image1.png)\n"
    assert _strip_dead_data_uri_images(md) == md


def test_strip_no_op_when_no_data_uri() -> None:
    from pagespeak.backends._docx import _strip_dead_data_uri_images

    md = "# Title\n\nbody text\n"
    assert _strip_dead_data_uri_images(md) == md


def test_convert_appends_extracted_images_when_only_dead_stubs(
    fake_docx: Path, tmp_path: Path
) -> None:
    from unittest.mock import patch

    from pagespeak.backends._docx import convert_with_markitdown

    class _R:
        text_content = "# Doc\n\n![](data:image/png;base64...)\n\nbody\n"

    with patch("markitdown.MarkItDown") as MD:
        MD.return_value.convert.return_value = _R()
        result = convert_with_markitdown(fake_docx, output_dir=tmp_path)

    assert "data:image" not in result.markdown
    assert "## Extracted Images" in result.markdown
    assert result.images


def test_convert_epub_extracts_images_and_retargets_refs(fake_epub: Path, tmp_path: Path) -> None:
    """EPUB images live outside the office `*/media/` prefixes, so the old
    extraction path returned [] — the converted markdown kept dead
    `../images/..` refs and the vision pass saw zero images. The EPUB path
    must extract the embedded images AND retarget the refs to `images/<name>`
    so they resolve next to the .md and the vision pass can match by basename.
    """
    from unittest.mock import patch

    from pagespeak.backends._docx import convert_with_markitdown

    class _R:
        text_content = (
            "# Chapter\n\n"
            "![image](../images/f0015-01.jpg)\n\n"
            "Cover: ![image](../images/9781400838080.jpg)\n"
        )

    with patch("markitdown.MarkItDown") as MD:
        MD.return_value.convert.return_value = _R()
        result = convert_with_markitdown(fake_epub, output_dir=tmp_path)

    # Images were actually pulled out of the epub zip onto disk.
    assert {p.name for p in result.images} == {
        "f0015-01.jpg",
        "9781400838080.jpg",
    }
    for p in result.images:
        assert p.exists()
        assert p.parent == tmp_path / "images"

    # Refs were retargeted to a path that resolves next to the .md.
    assert "](images/f0015-01.jpg)" in result.markdown
    assert "](images/9781400838080.jpg)" in result.markdown
    assert "../images/" not in result.markdown


def test_convert_html_resolves_mathml_to_latex(tmp_path: Path) -> None:
    """HTML inputs get their parallel presentation+content MathML resolved to
    `$LaTeX$` BEFORE markitdown (which would otherwise double-render the two
    representations and flatten superscripts). The content tree is dropped and
    the superscript survives as LaTeX."""
    from unittest.mock import patch

    from pagespeak.backends._docx import convert_with_markitdown

    html = tmp_path / "eq.html"
    html.write_text(
        '<p><math display="inline"><semantics>'
        "<mrow><msup><mi>y</mi><mn>3</mn></msup></mrow>"
        '<annotation-xml encoding="MathML-Content"><apply><power/>'
        "<ci>y</ci><cn>3</cn></apply></annotation-xml>"
        "</semantics></math></p>",
        encoding="utf-8",
    )

    class _R:
        def __init__(self, text: str) -> None:
            self.text_content = text

    # markitdown stand-in: echo back the (tokenized) HTML text it was handed,
    # so the prepare→restore wiring round-trips through the boundary.
    with patch("markitdown.MarkItDown") as MD:
        MD.return_value.convert.side_effect = lambda p: _R(Path(p).read_text(encoding="utf-8"))
        result = convert_with_markitdown(html)

    assert "$y^{3}$" in result.markdown  # restored LaTeX, superscript intact
    assert "<math" not in result.markdown  # MathML never reached markitdown
    assert "annotation" not in result.markdown  # content tree dropped → no doubling
