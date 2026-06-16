"""1:1 mirror of `orchestrators/_context.py` — `PipelineContext`
shape + the `do_normalize` / `do_vision` derived properties.
"""

from __future__ import annotations

from pathlib import Path

from pagespeak.models._models import IngestResult
from pagespeak.orchestrators._context import PipelineContext


def _ctx(**over: object) -> PipelineContext:
    base: dict[str, object] = dict(
        src=Path("doc.raw.md"),
        out=Path("/tmp/o"),
        dir_mode=True,
        doc_stem="doc",
        effective_stem="doc",
        suffix=".md",
        source_format="raw",
        raw_md_path=Path("/tmp/o/doc.raw.md"),
        cleaned_md_path=Path("/tmp/o/doc.cleaned.md"),
        normalized_md_path=Path("/tmp/o/doc.normalized.md"),
        repaired_md_path=Path("/tmp/o/doc.repaired.md"),
        structured_md_path=Path("/tmp/o/doc.structured.md"),
        visioned_md_path=Path("/tmp/o/doc.visioned.md"),
        diagrams=True,
        vision_backend=None,
        vision_model=None,
        vision_concurrency=None,
        vision_cache_only=False,
        preserve_alt=False,
        force_ocr=False,
        device=None,
        page_range=None,
        html_base_url=None,
        cleanup="basic",
        cross_refs="keep",
        split_sections=False,
        nested_split=False,
        split_min_level=None,
        min_body_chars=None,
        english_only=False,
        regenerate_toc=True,
        decoration_threshold=None,
        decoration_hamming_distance=None,
        pdf_backend="marker",
        pdf_backend_kwargs=None,
        repair_tables=False,
        docx_backend="markitdown",
        docx_outline_heading_depth=0,
        normalize_headings=False,
        normalize_headings_mode="heuristic",
        normalize_headings_model=None,
        strip_frontmatter=False,
        provenance=False,
        source_type=None,
        source_label=None,
    )
    base.update(over)
    return PipelineContext(**base)  # type: ignore[arg-type]


def test_do_normalize_requires_flag_and_out() -> None:
    assert _ctx(normalize_headings=True, out=Path("/tmp/o")).do_normalize is True
    assert _ctx(normalize_headings=False).do_normalize is False
    assert _ctx(normalize_headings=True, out=None).do_normalize is False


def test_do_vision_requires_diagrams_images_and_out() -> None:
    img = IngestResult(markdown="x", images=[Path("a.png")], source_format="raw")
    none_img = IngestResult(markdown="x", images=[], source_format="raw")
    assert _ctx(diagrams=True, result=img).do_vision is True
    assert _ctx(diagrams=False, result=img).do_vision is False
    assert _ctx(diagrams=True, result=none_img).do_vision is False  # no images
    assert _ctx(diagrams=True, result=img, out=None).do_vision is False
    assert _ctx(diagrams=True, result=None).do_vision is False  # pre-ingest


def test_defaults_for_mutable_state() -> None:
    c = _ctx()
    assert c.result is None
    assert c.diagrams_handoff == {}
    assert c.section_count is None
