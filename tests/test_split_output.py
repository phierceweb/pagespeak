"""Tests for pagespeak.orchestrators._split_output: the split phase passes the
ingest's authored-headings claim to the splitter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pagespeak import to_markdown
from pagespeak.models._models import IngestResult
from pagespeak.services import _hierarchy_trust
from pagespeak.services._hierarchy_trust import MARKER_NAME, record_structured


def _doc(*headings: str) -> str:
    return "".join(f"{h}\n\n{h.lstrip('# ')} body.\n\n" for h in headings)


WIDGET_DOC = _doc(
    "# Widget Guide",
    "## Set up widgets",
    "### Widget formats",
    "#### Quad widget format",
    "#### 5.1 (Type A) widget format",
    "#### 5.1.2 widget format",
    "#### 7.1 widget format",
    "### Place widgets",
)

F = Path("widget-guide/set-up-widgets/widget-formats")


def _seed(tmp_path: Path) -> Path:
    (tmp_path / "doc.raw.md").write_text("# Seed\n\nSeed body.\n", encoding="utf-8")
    to_markdown(tmp_path, output_dir=tmp_path, diagrams=False, stop_after="vision")
    (tmp_path / "doc.visioned.md").write_text(WIDGET_DOC, encoding="utf-8")
    return tmp_path


def _split_from_visioned(d: Path) -> Path:
    to_markdown(
        d,
        output_dir=d,
        diagrams=False,
        start="split",
        split_sections=True,
        nested_split=True,
        min_body_chars=1,
    )
    return d / "sections"


def test_from_split_with_authored_marker_nests_by_level(tmp_path: Path) -> None:
    d = _seed(tmp_path)
    record_structured(d, authoritative=True, authored_headings=True)
    sections = _split_from_visioned(d)
    assert (sections / F / "5-1-type-a-widget-format.md").is_file()
    assert not (sections / "5").exists()


def test_from_split_without_marker_nests_by_number(tmp_path: Path) -> None:
    d = _seed(tmp_path)
    assert not (d / MARKER_NAME).exists()
    sections = _split_from_visioned(d)
    assert (sections / "5" / "5-1-type-a-widget-format.md").is_file()


def test_marker_without_authored_claim_nests_by_number(tmp_path: Path) -> None:
    d = _seed(tmp_path)
    record_structured(d, authoritative=True, authored_headings=False)
    sections = _split_from_visioned(d)
    assert (sections / "5" / "5-1-type-a-widget-format.md").is_file()


def _widget_html(tmp_path: Path) -> Path:
    formats = ["Quad widget format", "5.1 (Type A) widget format", "5.1.2 widget format"]
    body = "".join(f"<h4>{t}</h4><p>{t} body.</p>" for t in formats)
    html = tmp_path / "guide.html"
    html.write_text(
        "<html><body><h1>Widget Guide</h1><p>Intro.</p><h2>Set up widgets</h2><p>Setup.</p>"
        f"<h3>Widget formats</h3><p>Formats.</p>{body}</body></html>",
        encoding="utf-8",
    )
    return html


def _assert_nested_by_level(sections: Path) -> None:
    assert not (sections / "5").exists()
    written = [p for p in sections.rglob("5-1-type-a-widget-format.md")]
    assert len(written) == 1
    assert "widget-formats" in written[0].parts


def test_html_full_run_nests_by_level(tmp_path: Path) -> None:
    out = tmp_path / "out"
    to_markdown(
        _widget_html(tmp_path),
        output_dir=out,
        diagrams=False,
        split_sections=True,
        nested_split=True,
    )
    assert json.loads((out / MARKER_NAME).read_text())["authored_headings"] is True
    _assert_nested_by_level(out / "sections")


def _refuse_marker_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse_marker(path: Path, data: object) -> None:
        raise OSError(f"refused {path.name}")

    monkeypatch.setattr(_hierarchy_trust, "atomic_write_json", refuse_marker)


def test_html_full_run_nests_by_level_when_marker_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _refuse_marker_writes(monkeypatch)
    out = tmp_path / "out"
    to_markdown(
        _widget_html(tmp_path),
        output_dir=out,
        diagrams=False,
        split_sections=True,
        nested_split=True,
    )
    assert not (out / MARKER_NAME).exists()
    _assert_nested_by_level(out / "sections")


def test_trusted_structure_without_authored_claim_nests_by_number_when_marker_write_fails(
    make_docx, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _refuse_marker_writes(monkeypatch)
    src = tmp_path / "guide.docx"
    src.write_bytes(make_docx(document_xml="<w:p><w:r><w:t>Z</w:t></w:r></w:p>").read_bytes())
    trusted = IngestResult(markdown=WIDGET_DOC, source_format="docx", structure_authoritative=True)
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx_dispatch.convert", return_value=trusted):
        to_markdown(
            src,
            output_dir=out,
            diagrams=False,
            docx_backend="python-docx",
            cleanup="off",
            split_sections=True,
            nested_split=True,
        )
    assert not (out / MARKER_NAME).exists()
    assert (out / "sections" / "5" / "5-1-type-a-widget-format.md").is_file()
