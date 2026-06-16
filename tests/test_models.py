from __future__ import annotations

from pathlib import Path

from pagespeak import Diagram, IngestResult


def test_diagram_is_frozen() -> None:
    d = Diagram(image_path=Path("foo.png"), caption="x", mermaid=None)
    try:
        d.caption = "y"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Diagram should be frozen")


def test_ingest_result_defaults() -> None:
    r = IngestResult(markdown="# hi")
    assert r.markdown == "# hi"
    assert r.images == []
    assert r.diagrams == []
    assert r.source_format == ""
