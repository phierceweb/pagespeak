"""Section-relative path rewriting and caption injection use the shared parser."""

from __future__ import annotations

from pathlib import Path

from pagespeak.models._models import Diagram
from pagespeak.services._split_write import _rewrite_image_paths_relative
from pagespeak.services._vision_inject import alt_text_by_basename, inject_diagrams

BRACKET_ALT = "A graph of f[x] on [0, 1] with shaded rectangles"


def test_split_rewrites_path_for_ref_whose_alt_has_brackets(tmp_path: Path) -> None:
    section_file = tmp_path / "sections" / "2.1" / "Checkpoint 2.3.md"
    section_file.parent.mkdir(parents=True)
    out = _rewrite_image_paths_relative(
        f"![{BRACKET_ALT}](images/fig.webp)", section_file, tmp_path / "images"
    )
    assert "](../../images/fig.webp)" in out


def test_vision_injects_caption_for_ref_whose_alt_has_brackets() -> None:
    diagram = Diagram(
        image_path=Path("images/fig.webp"),
        caption="A Riemann sum approximation",
        mermaid=None,
        diagram_type="chart",
    )
    out = inject_diagrams(f"![{BRACKET_ALT}](images/fig.webp)", {"fig.webp": diagram})
    assert "A Riemann sum approximation" in out


def test_alt_lookup_sees_ref_whose_alt_has_brackets() -> None:
    """The alt-aware vision prompt is fed from this map."""
    got = alt_text_by_basename(f"![{BRACKET_ALT}](images/fig.webp)")
    assert got.get("fig.webp") == BRACKET_ALT


# ── the backend/chunk rewriters share the same parser ─────────────────────


def test_pdf_prefixes_bare_ref_whose_alt_has_brackets() -> None:
    from pagespeak.backends._pdf import _prefix_bare_image_refs

    out = _prefix_bare_image_refs(f"![{BRACKET_ALT}](fig.png)", {"fig.png"})
    assert "](images/fig.png)" in out


def test_docx_retargets_ref_whose_alt_has_brackets(tmp_path: Path) -> None:
    from pagespeak.backends._docx import _retarget_image_refs

    out = _retarget_image_refs(f"![{BRACKET_ALT}](media/fig.png)", [tmp_path / "fig.png"])
    assert "](images/fig.png)" in out


def test_chunk_rewrite_renames_ref_whose_alt_has_brackets() -> None:
    from pagespeak.services._chunk_rewrite import prefix_image_basenames

    out, renames = prefix_image_basenames(f"![{BRACKET_ALT}](images/fig.png)", page_range="1-50")
    assert "](images/1-50-fig.png)" in out
    assert renames == {"fig.png": "1-50-fig.png"}
