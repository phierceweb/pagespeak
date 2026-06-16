from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

# --- Optional-extra gating ------------------------------------------------
#
# Some test modules require an optional install extra to even import or run:
# python-docx (`docx`), marker-pdf (`marker`), docling (`docling`), or the web
# console (`fastapi`). On a minimal `bin/setup` those extras are absent. Rather
# than erroring at collection — "don't test what isn't installed" — we skip the
# whole module when its keystone dependency can't be imported, and print a
# visible summary of what was skipped so the gap is never silent. The canonical
# dev env (`bin/setup --all`) installs every extra, so nothing is skipped there.
#
# Keyed by test-file stem -> the keystone module of its extra. A module that is
# only PARTLY dependent (a few backend-touching tests among pure-logic ones,
# e.g. test_pdf / test_pdf_docling) is gated whole-module: the pure tests are
# skipped too on a minimal install, but they still run under `bin/setup --all`.
# Genuinely mixed modules worth preserving (test_docx_dispatch) use a per-test
# `pytest.importorskip` instead of this map.
_OPTIONAL_EXTRA_FOR_MODULE = {
    "test_docx_structured": "docx",
    "test_docx_table": "docx",
    "test_docx_walk": "docx",
    "test_pdf": "marker",
    "test_pdf_docling": "docling",
    "test_web_actions": "fastapi",
    "test_web_app": "fastapi",
    "test_web_command": "fastapi",
    "test_web_config": "fastapi",
    "test_web_cost": "fastapi",
    "test_web_db": "fastapi",
    "test_web_jobs": "fastapi",
    "test_web_llm_summary": "fastapi",
    "test_web_pages": "fastapi",
    "test_web_scan": "fastapi",
    "test_web_worker": "fastapi",
}

_skipped_for_missing_extra: list[tuple[str, str]] = []


def _extra_is_installed(dep: str) -> bool:
    try:
        return importlib.util.find_spec(dep) is not None
    except ModuleNotFoundError:
        return False


def pytest_ignore_collect(collection_path, config):
    """Skip a whole test module when its optional extra isn't installed."""
    dep = _OPTIONAL_EXTRA_FOR_MODULE.get(collection_path.stem)
    if dep is None:
        return None
    if not _extra_is_installed(dep):
        _skipped_for_missing_extra.append((collection_path.stem, dep))
        return True
    return None


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Make extra-gated module skips visible — never a silent omission."""
    if not _skipped_for_missing_extra:
        return
    terminalreporter.write_sep("=", "modules skipped — optional extras not installed", yellow=True)
    for stem, dep in sorted(set(_skipped_for_missing_extra)):
        terminalreporter.write_line(
            f"  {stem}  — needs '{dep}'  (install everything: bin/setup --all)"
        )


@pytest.fixture
def fake_docx(tmp_path: Path) -> Path:
    """Build a minimal docx-shaped zip with two embedded images and a document.xml."""
    target = tmp_path / "fixture.docx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(
            "word/document.xml",
            "<w:document xmlns:w='x'><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>",
        )
        z.writestr("word/media/image1.png", _PNG_BYTES)
        z.writestr("word/media/image2.png", _PNG_BYTES)
    target.write_bytes(buf.getvalue())
    return target


@pytest.fixture
def fake_pptx(tmp_path: Path) -> Path:
    target = tmp_path / "fixture.pptx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/media/image1.png", _PNG_BYTES)
    target.write_bytes(buf.getvalue())
    return target


@pytest.fixture
def fake_epub(tmp_path: Path) -> Path:
    """Build a minimal epub-shaped zip with images under OPS/images/.

    EPUB images live at arbitrary in-zip paths (OPS/images/, images/,
    OEBPS/images/, …) — not the office `word/media/` prefixes — so this
    fixture exercises the EPUB-specific media extraction path.
    """
    target = tmp_path / "fixture.epub"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container/>',
        )
        z.writestr(
            "OPS/xhtml/chapter01.html",
            '<html><body><img src="../images/f0015-01.jpg"/></body></html>',
        )
        z.writestr("OPS/images/f0015-01.jpg", _PNG_BYTES)
        z.writestr("OPS/images/9781400838080.jpg", _PNG_BYTES)
        z.writestr("OPS/styles/stylesheet.css", "body{}")  # non-image, must be ignored
    target.write_bytes(buf.getvalue())
    return target


@pytest.fixture
def fake_image(tmp_path: Path) -> Path:
    target = tmp_path / "diagram.png"
    target.write_bytes(_PNG_BYTES)
    return target


# 1x1 transparent PNG — small valid binary so the zip is real
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
)

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
_WP = 'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
_A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/></w:style>
</w:styles>"""


@pytest.fixture
def make_docx(tmp_path: Path):
    """Build a minimal valid .docx from hand-authored body/numbering XML.

    `document_xml` is the inner content of <w:body> (paragraphs/tables).
    `numbering_xml` is the inner content of <w:numbering> ("" for none).
    `extra_parts` maps archive path -> bytes (e.g. word/media/image1.png).
    `doc_rels` is extra inner content for word/_rels/document.xml.rels.
    """

    def _build(
        *,
        document_xml: str,
        numbering_xml: str = "",
        extra_parts: dict[str, bytes] | None = None,
        doc_rels: str = "",
    ):
        path = tmp_path / "fixture.docx"
        body = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:document {_W} {_R} {_WP} {_A}><w:body>{document_xml}"
            f"</w:body></w:document>"
        )
        numbering = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:numbering {_W}>{numbering_xml}</w:numbering>"
        )
        rels = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="http://schemas.openxmlformats.org/'
            f'package/2006/relationships">'
            f'<Relationship Id="rIdNum" Type="http://schemas.'
            f"openxmlformats.org/officeDocument/2006/relationships/"
            f'numbering" Target="numbering.xml"/>'
            f'<Relationship Id="rIdSty" Type="http://schemas.'
            f"openxmlformats.org/officeDocument/2006/relationships/"
            f'styles" Target="styles.xml"/>{doc_rels}</Relationships>'
        )
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", _CONTENT_TYPES)
            z.writestr("_rels/.rels", _ROOT_RELS)
            z.writestr("word/document.xml", body)
            z.writestr("word/numbering.xml", numbering)
            z.writestr("word/styles.xml", _STYLES)
            z.writestr("word/_rels/document.xml.rels", rels)
            for arc, data in (extra_parts or {}).items():
                z.writestr(arc, data)
        return path

    return _build
