from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pagespeak import IngestResult, to_markdown


def test_unknown_format_raises(tmp_path: Path) -> None:
    f = tmp_path / "weird.xyz"
    f.write_text("x")
    with pytest.raises(ValueError, match="Unsupported format"):
        to_markdown(f)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        to_markdown(tmp_path / "nope.pdf")


def test_pdf_dispatches_to_marker_path(tmp_path: Path) -> None:
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4\n")
    fake_result = IngestResult(markdown="pdf body", source_format="pdf")
    with patch("pagespeak.backends._pdf.convert_pdf", return_value=fake_result) as mock_pdf:
        result = to_markdown(f, diagrams=False, cleanup="off")
    mock_pdf.assert_called_once()
    assert result.markdown == "pdf body"


def test_docx_dispatches_to_markitdown_path(fake_docx: Path) -> None:
    fake_result = IngestResult(markdown="docx body", source_format="docx")
    with patch(
        "pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result
    ) as mock_md:
        result = to_markdown(fake_docx, diagrams=False, cleanup="off")
    mock_md.assert_called_once()
    assert result.markdown == "docx body"


def test_markdown_dispatches_to_passthrough(tmp_path: Path) -> None:
    """A .md source enters the pipeline verbatim (no backend round-trip)."""
    f = tmp_path / "doc.md"
    body = "# Already markdown\n\nBody with a [link](https://example.com).\n"
    f.write_text(body, encoding="utf-8")
    result = to_markdown(f, diagrams=False, cleanup="off")
    assert result.markdown == body
    assert result.source_format == "md"


def test_diagrams_skipped_when_no_output_dir(fake_docx: Path) -> None:
    fake_result = IngestResult(
        markdown="docx body",
        images=[Path("/nonexistent/img.png")],
        source_format="docx",
    )
    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        patch("pagespeak.services._diagrams.enrich_with_diagrams") as mock_enrich,
    ):
        to_markdown(fake_docx, diagrams=True)  # no output_dir
    mock_enrich.assert_not_called()


def test_cleanup_off_returns_raw(fake_docx: Path) -> None:
    raw = "<i>foo</i>\n\n\n\nbar"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(fake_docx, diagrams=False, cleanup="off")
    assert result.markdown == raw


def test_cleanup_basic_runs_by_default(fake_docx: Path) -> None:
    raw = "<i>foo</i>\n\n\n\nbar\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(fake_docx, diagrams=False)
    assert "<i>" not in result.markdown
    assert "\n\n\n" not in result.markdown


def test_cleanup_aggressive_drops_image_only_lines(fake_docx: Path) -> None:
    raw = "before\n\n![](decoration.png)\n\nafter\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(fake_docx, diagrams=False, cleanup="aggressive")
    assert "decoration.png" not in result.markdown


def test_split_sections_writes_files_when_output_dir_set(fake_docx: Path, tmp_path: Path) -> None:
    # Bodies must clear `to_markdown`'s default min_body_chars threshold (30).
    raw = (
        "# 1. ALPHA\n"
        "Substantive body of text describing alpha so it passes the body cutoff.\n"
        "# 2. BETA\n"
        "Beta body content with enough substance to cross the threshold too.\n"
    )
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=False,
            cleanup="off",
            split_sections=True,
        )
    sections_dir = out / "sections"
    assert sections_dir.exists()
    assert (sections_dir / "INDEX.md").exists()
    files = [p.name for p in sections_dir.glob("*.md") if p.name != "INDEX.md"]
    assert any("ALPHA" in name for name in files)
    assert any("BETA" in name for name in files)


def test_split_max_level_caps_depth_through_pipeline(fake_docx: Path, tmp_path: Path) -> None:
    """--split-max-level flows to_markdown → split phase: H2 headings become
    section files, deeper headings stay inline (no per-H3 file)."""
    raw = (
        "# Book Title\n"
        "Intro body substantial enough to clear the body threshold cutoff.\n"
        "## 1.1 Alpha\n"
        "Alpha body substantial enough to clear the body cutoff threshold.\n"
        "### Alpha Detail\n"
        "Detail body also substantial enough to clear the body cutoff here.\n"
        "## 1.2 Beta\n"
        "Beta body content with enough substance to cross the threshold too.\n"
    )
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=False,
            cleanup="off",
            split_sections=True,
            split_max_level=2,
        )
    files = [p for p in (out / "sections").rglob("*.md") if p.name != "INDEX.md"]
    names = [p.name for p in files]
    assert any("Beta" in n for n in names)
    assert not any("Alpha Detail" in n for n in names)  # H3 inlined, not its own file
    alpha = next(p for p in files if "Alpha" in p.name and "Detail" not in p.name)
    assert "Alpha Detail" in alpha.read_text()  # H3 heading + body inline in the H2 section


def test_split_target_kb_packs_through_pipeline(fake_docx: Path, tmp_path: Path) -> None:
    """--split-target-kb flows to_markdown → split phase: a subtree fitting
    the target becomes one file with its subsections inlined."""
    para = "Body content substantial enough to clear the body cutoff threshold. "
    raw = f"# 1. Book\n{para}\n## 1.1. Alpha\n{para}\n## 1.2. Beta\n{para}\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=False,
            cleanup="off",
            split_sections=True,
            split_target_kb=8,
        )
    files = [p for p in (out / "sections").rglob("*.md") if p.name != "INDEX.md"]
    assert [p.name for p in files] == ["1. Book.md"]  # whole doc fits one 8KB box
    text = files[0].read_text()
    assert "## 1.1. Alpha" in text and "## 1.2. Beta" in text


def test_source_provenance_stamped_on_doc_and_sections(fake_docx: Path, tmp_path: Path) -> None:
    """source_type/source_label stamp a provenance YAML block on BOTH the
    returned whole-doc markdown and every section file — the multi-source
    RAG enabler. The block must lead each file, above the heading."""
    raw = (
        "# 1. ALPHA\n"
        "Substantive body of text describing alpha so it passes the body cutoff.\n"
        "# 2. BETA\n"
        "Beta body content with enough substance to cross the threshold too.\n"
    )
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=False,
            cleanup="off",
            split_sections=True,
            source_type="textbook",
            source_label="Test Source",
        )
    assert result.markdown.startswith('---\nsource_type: "textbook"\n')
    head = result.markdown.split("---\n\n", 1)[0]
    assert 'source_label: "Test Source"' in head
    section_files = [p for p in (out / "sections").glob("*.md") if p.name != "INDEX.md"]
    assert section_files
    for p in section_files:
        assert p.read_text().startswith('---\nsource_type: "textbook"\n')


def test_no_source_flags_master_clean_sections_structural(fake_docx: Path, tmp_path: Path) -> None:
    """Without source flags the MASTER doc stays frontmatter-free, while
    section files carry structural identity only (doc_id = out-dir name,
    join keys, locators) — never the opt-in source fields."""
    raw = "# 1. ALPHA\nSubstantive alpha body passing the body cutoff threshold.\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(
            fake_docx, output_dir=out, diagrams=False, cleanup="off", split_sections=True
        )
    assert not result.markdown.startswith("---")
    section_files = [p for p in (out / "sections").glob("*.md") if p.name != "INDEX.md"]
    assert section_files
    for p in section_files:
        text = p.read_text()
        assert text.startswith("---\n")
        assert 'doc_id: "out"' in text
        assert "source_type" not in text
        assert "source_label" not in text


def test_provenance_flag_emits_frontmatter_with_auto_label(fake_docx: Path, tmp_path: Path) -> None:
    """`provenance=True` (no source flags) still stamps frontmatter: the
    label auto-derives from the cleaned filename stem (`fixture.docx` →
    "fixture") and `source_type` is omitted entirely."""
    raw = (
        "# 1. ALPHA\n"
        "Substantive body of text describing alpha so it passes the body cutoff.\n"
        "# 2. BETA\n"
        "Beta body content with enough substance to cross the threshold too.\n"
    )
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=False,
            cleanup="off",
            split_sections=True,
            provenance=True,
        )
    head = result.markdown.split("---\n\n", 1)[0]
    assert result.markdown.startswith("---\n")
    assert 'source_label: "fixture"' in head
    assert "source_type" not in head  # omitted when not supplied
    section_files = [p for p in (out / "sections").glob("*.md") if p.name != "INDEX.md"]
    assert section_files
    for p in section_files:
        text = p.read_text()
        assert text.startswith("---\n")
        assert 'source_label: "fixture"' in text
        assert "source_type" not in text.split("---\n\n", 1)[0]


def test_provenance_flag_keeps_explicit_label(fake_docx: Path, tmp_path: Path) -> None:
    """An explicit `source_label` wins over the auto-derived stem when
    provenance is on."""
    raw = "# 1. ALPHA\nSubstantive alpha body passing the body cutoff threshold.\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=False,
            cleanup="off",
            split_sections=True,
            provenance=True,
            source_label="Applied Widgetry Handbook",
        )
    head = result.markdown.split("---\n\n", 1)[0]
    assert 'source_label: "Applied Widgetry Handbook"' in head
    assert 'source_label: "fixture"' not in head  # explicit label, not the derived stem


def test_split_sections_noop_without_output_dir(fake_docx: Path) -> None:
    raw = "# 1. ALPHA\nfoo\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        patch("pagespeak.services._split.split_into_sections") as mock_split,
    ):
        to_markdown(fake_docx, diagrams=False, split_sections=True)
    mock_split.assert_not_called()


def test_cross_refs_strip_removes_page_refs(fake_docx: Path) -> None:
    raw = "see [Configuration](#page-36-0) for details\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(fake_docx, diagrams=False, cross_refs="strip")
    assert "(#page-36-0)" not in result.markdown
    assert "see Configuration for details" in result.markdown


def test_cross_refs_keep_is_default(fake_docx: Path) -> None:
    raw = "see [Configuration](#page-36-0) for details\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(fake_docx, diagrams=False)
    assert "[Configuration](#page-36-0)" in result.markdown


def test_split_min_level_splits_on_semantic_headings(fake_docx: Path, tmp_path: Path) -> None:
    # Bodies sized above the default 30-char threshold.
    raw = (
        "# Title\nFront-matter prose with enough words to satisfy the cutoff.\n"
        "## Quick Start\nGetting-started body that is comfortably over the threshold.\n"
        "## System Settings\nSystem-level configuration body, also above the cutoff.\n"
    )
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=False,
            cleanup="off",
            split_sections=True,
            split_min_level=2,
        )
    sections_dir = out / "sections"
    files = [p.name for p in sections_dir.glob("*.md") if p.name != "INDEX.md"]
    assert "Quick Start.md" in files
    assert "System Settings.md" in files


def test_default_splits_on_every_heading(fake_docx: Path, tmp_path: Path) -> None:
    """The default split (no explicit `split_min_level`) cuts on EVERY
    heading — numbered AND un-numbered semantic sub-headings — so a
    textbook's semantic subsections become their own RAG sections instead
    of being bundled into the numbered parent. Default min_level is 1."""
    raw = (
        "# 1. NUMBERED\nNumbered section body content over the 30-char cutoff threshold.\n"
        "## Quick Start\nSemantic body, also long enough to clear the cutoff.\n"
    )
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=False,
            cleanup="off",
            split_sections=True,
        )
    sections_dir = out / "sections"
    files = {p.name for p in sections_dir.rglob("*.md") if p.name != "INDEX.md"}
    assert "1. NUMBERED.md" in files
    assert "Quick Start.md" in files  # un-numbered subsection now split by default


def test_cross_refs_remap_via_to_markdown(fake_docx: Path) -> None:
    raw = (
        '<span id="page-44-0"></span>### Tap Tempo\n\n'
        "Hit this. See [Tap info](#page-44-0) for more.\n"
    )
    fake_result = IngestResult(markdown=raw, source_format="docx")
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(fake_docx, diagrams=False, cleanup="aggressive", cross_refs="remap")
    assert "[Tap info](#tap-tempo)" in result.markdown
    assert "<span" not in result.markdown


def test_basic_dedupes_consecutive_headings_via_to_markdown(fake_docx: Path) -> None:
    # dedupe is automatic at basic+. Marker-style double-emit collapses to one.
    raw = "## Table of Contents\n\n## Table of Contents\n\nbody\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(fake_docx, diagrams=False)
    assert result.markdown.count("## Table of Contents") == 1


def test_pdf_device_propagates_to_convert_pdf(tmp_path: Path) -> None:
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4\n")
    fake_result = IngestResult(markdown="x", source_format="pdf")
    with patch("pagespeak.backends._pdf.convert_pdf", return_value=fake_result) as mock_pdf:
        to_markdown(f, diagrams=False, cleanup="off", device="cpu")
    assert mock_pdf.call_args.kwargs["device"] == "cpu"


def test_pdf_page_range_propagates_to_convert_pdf(tmp_path: Path) -> None:
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4\n")
    fake_result = IngestResult(markdown="x", source_format="pdf")
    with patch("pagespeak.backends._pdf.convert_pdf", return_value=fake_result) as mock_pdf:
        to_markdown(f, diagrams=False, cleanup="off", page_range="0-9")
    assert mock_pdf.call_args.kwargs["page_range"] == "0-9"


def test_vision_backend_propagates_to_enrich(fake_docx: Path, tmp_path: Path) -> None:
    fake_result = IngestResult(
        markdown="![](images/img.png)",
        images=[Path("/fake/images/img.png")],
        source_format="docx",
    )
    out = tmp_path / "out"
    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        patch("pagespeak.services._diagrams.gather_diagrams", return_value={}) as mock_enrich,
    ):
        to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=True,
            vision_backend="claude_code",
            cleanup="off",
        )
    assert mock_enrich.call_args.kwargs["backend_name"] == "claude_code"


def test_vision_backend_openrouter_propagates_to_enrich(fake_docx: Path, tmp_path: Path) -> None:
    fake_result = IngestResult(
        markdown="![](images/img.png)",
        images=[Path("/fake/images/img.png")],
        source_format="docx",
    )
    out = tmp_path / "out"
    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        patch("pagespeak.services._diagrams.gather_diagrams", return_value={}) as mock_enrich,
    ):
        to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=True,
            vision_backend="openrouter",
            cleanup="off",
        )
    assert mock_enrich.call_args.kwargs["backend_name"] == "openrouter"


def test_vision_backend_default_defers_to_env(fake_docx: Path, tmp_path: Path) -> None:
    """When no `vision_backend` is passed, `to_markdown` sends
    `backend_name=None` to `gather_diagrams` so the env-var resolution
    (via `_agent_runtime.resolve_backend`) kicks in — the user's
    `PAGESPEAK_VISION_BACKEND` in `.env` is honoured, not shadowed."""
    fake_result = IngestResult(
        markdown="![](images/img.png)",
        images=[Path("/fake/images/img.png")],
        source_format="docx",
    )
    out = tmp_path / "out"
    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        patch("pagespeak.services._diagrams.gather_diagrams", return_value={}) as mock_enrich,
    ):
        to_markdown(fake_docx, output_dir=out, diagrams=True, cleanup="off")
    assert mock_enrich.call_args.kwargs["backend_name"] is None


# --- single-shot feature parity with the chunked stitch phase ---


def test_to_markdown_regenerates_toc_by_default(fake_docx: Path) -> None:
    """Single-shot must regenerate the TOC body the same way stitch does,
    so users on the daily-driver path don't see Marker's broken pipe-table
    TOC."""
    raw = (
        "## Table of Contents\n\n"
        "| 1. | ARCHIT | ECTURE | 4 |\n"
        "| --- | --- | --- | --- |\n"
        "|  | 1.1. | API |  |\n\n"
        "# 1. ARCHITECTURE\nintro\n## 1.1. API\nbody\n"
    )
    fake_result = IngestResult(markdown=raw, source_format="docx")
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(fake_docx, diagrams=False, cleanup="aggressive")
    # Broken pipe-table TOC body gone.
    assert "| ARCHIT |" not in result.markdown
    # Generated TOC is present and points at real heading slugs.
    assert "- [1. ARCHITECTURE](#1-architecture)" in result.markdown


def test_to_markdown_regenerate_toc_can_be_disabled(fake_docx: Path) -> None:
    raw = "## Table of Contents\n\n| broken | toc | row |\n\n# 1. X\nbody\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(fake_docx, diagrams=False, cleanup="off", regenerate_toc=False)
    # Original (broken) TOC table still present when explicitly preserved.
    assert "| broken | toc | row |" in result.markdown


def test_to_markdown_strips_decoration_image_refs(fake_docx: Path, tmp_path: Path) -> None:
    """Single-shot phash dedup: when the same logo is extracted on many
    pages, refs are stripped instead of all being captioned identically.
    Mirrors the behavior of the chunked stitch phase."""
    out = tmp_path / "out"
    out.mkdir()
    images_dir = out / "images"
    images_dir.mkdir()

    # Build 6 textured images with the same seed so they all phash close
    # together — simulates a repeated page-header logo.
    import io
    import random

    from PIL import Image

    def textured(seed: int, size: int = 64) -> bytes:
        rng = random.Random(seed)
        img = Image.new("L", (size, size))
        for y in range(size):
            for x in range(size):
                img.putpixel((x, y), rng.randrange(256))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    paths: list[Path] = []
    for i in range(6):
        p = images_dir / f"_page_{i}_Picture_0.png"
        p.write_bytes(textured(seed=42))  # all six identical phash → cluster
        paths.append(p)

    md = "\n\n".join(f"![](images/_page_{i}_Picture_0.png)" for i in range(6))
    md += "\n\nbody content goes here.\n"
    fake_result = IngestResult(markdown=md, images=paths, source_format="docx")

    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        patch("pagespeak.services._diagrams.gather_diagrams", return_value={}),
    ):
        # Pretend the vision pass ran and produced no captions. Dispatch
        # should detect the images as a decoration cluster (size 6 ≥
        # default threshold 5) and strip refs.
        result = to_markdown(fake_docx, output_dir=out, diagrams=True, cleanup="off")

    # All six page-header refs gone.
    for i in range(6):
        assert f"_page_{i}_Picture_0.png" not in result.markdown
    # Body content preserved.
    assert "body content goes here." in result.markdown


def test_to_markdown_decoration_threshold_can_be_disabled(fake_docx: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    images_dir = out / "images"
    images_dir.mkdir()

    import io
    import random

    from PIL import Image

    def textured(seed: int) -> bytes:
        rng = random.Random(seed)
        img = Image.new("L", (64, 64))
        for y in range(64):
            for x in range(64):
                img.putpixel((x, y), rng.randrange(256))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    paths = []
    for i in range(6):
        p = images_dir / f"_page_{i}_Picture_0.png"
        p.write_bytes(textured(42))
        paths.append(p)

    md = "\n\n".join(f"![](images/_page_{i}_Picture_0.png)" for i in range(6))
    fake_result = IngestResult(markdown=md, images=paths, source_format="docx")

    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        patch("pagespeak.services._diagrams.gather_diagrams", return_value={}),
    ):
        result = to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=True,
            cleanup="off",
            decoration_threshold=0,
        )
    # With dedup disabled, every ref survives.
    for i in range(6):
        assert f"_page_{i}_Picture_0.png" in result.markdown


# --- single-shot resilience ---


def test_to_markdown_writes_raw_checkpoint_after_backend(fake_docx: Path, tmp_path: Path) -> None:
    """The raw.md checkpoint must land on disk immediately after the
    backend returns, before vision/cleanup/split run. This is the
    persistence guarantee that makes resume possible."""
    raw = "# Hello\n\nbody content from the backend.\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        to_markdown(fake_docx, output_dir=out, diagrams=False, cleanup="off")
    raw_md = out / f"{fake_docx.stem}.raw.md"
    assert raw_md.exists()
    assert raw_md.read_text(encoding="utf-8") == raw


def test_to_markdown_vision_cache_writes_per_image_sidecar(
    fake_docx: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful vision call should leave a `<phash>.json` in
    `<output_dir>/.vision-cache/`. Lets a subsequent run skip the call.

    Backend is pinned via env (vision_backend default flows
    through `resolve_backend("vision")` from env, default `claude_code`).
    Setting it explicitly here so the cached `backend` field is
    deterministic across CI environments."""
    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "anthropic")
    out = tmp_path / "out"
    out.mkdir()
    images_dir = out / "images"
    images_dir.mkdir()
    img = images_dir / "diagram.png"
    # Real PNG so phash works.
    import io
    import random

    from PIL import Image

    rng = random.Random(7)
    pil = Image.new("L", (32, 32))
    for y in range(32):
        for x in range(32):
            pil.putpixel((x, y), rng.randrange(256))
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    img.write_bytes(buf.getvalue())

    fake_result = IngestResult(
        markdown="![](images/diagram.png)",
        images=[img],
        source_format="docx",
    )
    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        patch("pagespeak.services._diagrams.build_backend") as mock_build,
    ):
        from pagespeak.models._models import Diagram

        fake_backend = MagicMock()
        fake_backend.analyze.return_value = Diagram(image_path=img, caption="Cached.", mermaid=None)
        mock_build.return_value = fake_backend
        to_markdown(fake_docx, output_dir=out, diagrams=True, cleanup="off", split_sections=False)

    cache_files = list((out / ".vision-cache").glob("*.json"))
    assert len(cache_files) == 1
    import json as _json

    cached = _json.loads(cache_files[0].read_text(encoding="utf-8"))
    assert cached["caption"] == "Cached."
    assert cached["backend"] == "anthropic"
    assert cached["model"] is None
    # inspectability metadata: phash echoed in body and source
    # path listed so a human opening the file can tell which image the
    # entry describes without recomputing every image's hash.
    assert cached["phash"] == cache_files[0].stem
    assert cached["source_paths"] == ["diagram.png"]


def test_to_markdown_vision_cache_skips_backend_on_hit(
    fake_docx: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-existing cache JSON for the same backend+model must skip
    the live call entirely. Backend pinned via env so the resolved
    backend matches the pre-populated cache entry's `backend` field
    (vision_backend defaults to env, then `claude_code`)."""
    monkeypatch.setenv("PAGESPEAK_VISION_BACKEND", "anthropic")
    out = tmp_path / "out"
    out.mkdir()
    images_dir = out / "images"
    images_dir.mkdir()
    img = images_dir / "diagram.png"
    import io
    import random

    from PIL import Image

    rng = random.Random(11)
    pil = Image.new("L", (32, 32))
    for y in range(32):
        for x in range(32):
            pil.putpixel((x, y), rng.randrange(256))
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    img.write_bytes(buf.getvalue())

    # Pre-populate the cache for this image's phash.
    from pagespeak.utils._phash import compute_phash

    cache_dir = out / ".vision-cache"
    cache_dir.mkdir()
    phash = compute_phash(img)
    import json as _json

    (cache_dir / f"{phash}.json").write_text(
        _json.dumps(
            {
                "backend": "anthropic",
                "model": None,
                "caption": "from cache",
                "mermaid": "flowchart TD\n  A-->B",
                "diagram_type": "flowchart",
            }
        ),
        encoding="utf-8",
    )

    fake_result = IngestResult(
        markdown="![](images/diagram.png)",
        images=[img],
        source_format="docx",
    )
    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        patch("pagespeak.services._diagrams.build_backend") as mock_build,
    ):
        fake_backend = MagicMock()
        fake_backend.analyze.side_effect = AssertionError("must not call backend on cache hit")
        mock_build.return_value = fake_backend
        result = to_markdown(fake_docx, output_dir=out, diagrams=True, cleanup="off")

    fake_backend.analyze.assert_not_called()
    # Caption from cache injected as alt text.
    assert "from cache" in result.markdown
    assert "flowchart TD" in result.markdown


def test_normalize_gather_runs_after_cleanup(fake_docx: Path, tmp_path: Path) -> None:
    """`gather_normalize_levels` runs after cleanup so it sees the
    same heading list apply will see — otherwise drift safety skips the
    apply. Order: cleanup → gather_normalize → gather_diagrams.
    """
    from pagespeak.models._models import Diagram

    out = tmp_path / "out"
    images_dir = out / "images"
    images_dir.mkdir(parents=True)
    img = images_dir / "img.png"
    img.write_bytes(b"x")

    raw = (
        "#### Chapter 1 Intro\nbody\n#### 1.1 Foo\nbody\n#### 1.2 Bar\nbody\n![](images/img.png)\n"
    )
    fake_result = IngestResult(markdown=raw, images=[img], source_format="docx")

    call_order: list[str] = []

    def record_cleanup(text, *, level, cross_refs):
        call_order.append("cleanup")
        return text  # no-op for the test

    def record_gather_normalize(*args, **kwargs):
        call_order.append("gather_normalize")
        return None

    def record_gather_diagrams(*args, **kwargs):
        call_order.append("gather_diagrams")
        return {img.name: Diagram(image_path=img, caption="cap", mermaid=None)}

    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        patch("pagespeak.services._diagrams.gather_diagrams", side_effect=record_gather_diagrams),
        patch("pagespeak.services._cleanup.cleanup_markdown", side_effect=record_cleanup),
        patch(
            "pagespeak.services._heading_normalize.gather_normalize_levels",
            side_effect=record_gather_normalize,
        ),
    ):
        to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=True,
            normalize_headings=True,
            cleanup="basic",
        )

    # cleanup first, then gather_normalize, then gather_diagrams.
    assert call_order == ["cleanup", "gather_normalize", "gather_diagrams"], (
        f"unexpected order: {call_order}"
    )


def test_to_markdown_does_not_write_pre_normalize_snapshot(fake_docx: Path, tmp_path: Path) -> None:
    """No `<stem>.pre-normalize.md` snapshot is written — it would be
    byte-identical to `cleaned.md` (normalize reads cleaned.md directly
    with no intervening transform). `cleaned.md` is the diff anchor:
    `diff cleaned.md normalized.md` shows exactly what normalize-apply
    changed."""
    out = tmp_path / "out"
    raw = (
        "#### Chapter 1 Introduction\n"
        "intro body\n"
        "\n"
        "#### 1.1 Foo\n"
        "foo body content\n"
        "\n"
        "#### 1.2 Bar\n"
        "bar body content\n"
    )
    fake_result = IngestResult(markdown=raw, source_format="docx")

    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        patch(
            "pagespeak.services._heading_normalize._claude_code_invoke",
            # Promote chapter from 4 to 3.
            return_value="1: 3\n2: 4\n3: 4\n",
        ),
    ):
        result = to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=False,
            cleanup="off",
            normalize_headings=True,
            normalize_headings_mode="llm",
        )

    # No pre-normalize snapshot written.
    assert not (out / f"{fake_docx.stem}.pre-normalize.md").exists()
    # The diff anchor pair is now cleaned.md vs normalized.md.
    cleaned = (out / f"{fake_docx.stem}.cleaned.md").read_text(encoding="utf-8")
    normalized = (out / f"{fake_docx.stem}.normalized.md").read_text(encoding="utf-8")
    # cleaned.md has the pre-normalize headings (still all level 4).
    assert "#### Chapter 1 Introduction" in cleaned
    assert "#### 1.1 Foo" in cleaned
    # normalized.md has them post-normalize.
    assert "### Chapter 1 Introduction" in normalized
    assert "#### 1.1 Foo" in normalized
    # Live result is the post-normalize state.
    assert "### Chapter 1 Introduction" in result.markdown


def test_to_markdown_vision_cache_reused_across_backend_change(
    fake_docx: Path, tmp_path: Path
) -> None:
    """A cache entry produced by a DIFFERENT backend/model is reused, not
    redone. The cache key is the image's phash; the engine is provenance,
    not a reuse gate. Switching backends (anthropic ⇄ claude_code ⇄
    openrouter) must NOT silently re-spend on images already analysed.
    To force fresh descriptions, delete the cache explicitly
    (`--rerun-from vision`)."""
    out = tmp_path / "out"
    out.mkdir()
    images_dir = out / "images"
    images_dir.mkdir()
    img = images_dir / "diagram.png"
    import io
    import random

    from PIL import Image

    rng = random.Random(13)
    pil = Image.new("L", (32, 32))
    for y in range(32):
        for x in range(32):
            pil.putpixel((x, y), rng.randrange(256))
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    img.write_bytes(buf.getvalue())

    from pagespeak.utils._phash import compute_phash

    cache_dir = out / ".vision-cache"
    cache_dir.mkdir()
    phash = compute_phash(img)
    # Cache entry from a DIFFERENT backend.
    import json as _json

    (cache_dir / f"{phash}.json").write_text(
        _json.dumps(
            {
                "backend": "openrouter",
                "model": "google/gemini-2.0-flash-exp",
                "caption": "cached from openrouter",
                "mermaid": None,
                "diagram_type": None,
            }
        ),
        encoding="utf-8",
    )

    fake_result = IngestResult(
        markdown="![](images/diagram.png)",
        images=[img],
        source_format="docx",
    )
    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        patch("pagespeak.services._diagrams.build_backend") as mock_build,
    ):
        from pagespeak.models._models import Diagram

        fake_backend = MagicMock()
        fake_backend.analyze.return_value = Diagram(
            image_path=img, caption="fresh anthropic call", mermaid=None
        )
        mock_build.return_value = fake_backend
        # Default vision_backend is "anthropic", but the openrouter cache
        # entry is reused regardless — no fresh call.
        result = to_markdown(fake_docx, output_dir=out, diagrams=True, cleanup="off")

    fake_backend.analyze.assert_not_called()
    assert "cached from openrouter" in result.markdown
    assert "fresh anthropic call" not in result.markdown


def test_to_markdown_min_body_chars_propagates_to_split(fake_docx: Path, tmp_path: Path) -> None:
    """Caller passes `min_body_chars=0` to preserve every heading as a
    section file, even short stubs. Default behavior drops them."""
    raw = (
        "# 1. NUMBERED\nA\n"
        "# 2. ALSO\nB\n"  # bodies of 1 char each
    )
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=False,
            cleanup="off",
            split_sections=True,
            min_body_chars=0,
        )
    files = {p.name for p in (out / "sections").glob("*.md") if p.name != "INDEX.md"}
    assert "1. NUMBERED.md" in files
    assert "2. ALSO.md" in files


# --- presets + run.json -------------------------------------------


def test_to_markdown_preset_rag_default_applies_split(fake_docx: Path, tmp_path: Path) -> None:
    """`preset='rag-default'` enables split_sections + nested_split
    without explicit kwargs."""
    raw = "# 1. NUMBERED\nbody content\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        to_markdown(
            fake_docx,
            output_dir=out,
            preset="rag-default",
            diagrams=False,
            min_body_chars=0,
        )
    # rag-default → split_sections=True + nested_split=True. Numbered top-level
    # sections land in a numeric-prefix folder.
    assert (out / "sections").is_dir()
    section_files = list((out / "sections").rglob("*.md"))
    assert any(p.name == "1. NUMBERED.md" for p in section_files)


def test_to_markdown_explicit_kwarg_overrides_preset(fake_docx: Path, tmp_path: Path) -> None:
    """Explicit `split_sections=False` beats preset's True. Library-side
    detection of "user passed this" relies on non-None kwargs."""
    raw = "# 1. FOO\nbody\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        to_markdown(
            fake_docx,
            output_dir=out,
            preset="rag-default",  # would set split_sections=True
            split_sections=False,  # explicit override
            diagrams=False,
            min_body_chars=0,
        )
    # Override won — no sections/ directory.
    assert not (out / "sections").is_dir()


def test_to_markdown_unknown_preset_raises(fake_docx: Path, tmp_path: Path) -> None:
    """Unknown preset name → ValueError with valid options listed."""
    fake_result = IngestResult(markdown="# 1. FOO\nbody\n", source_format="docx")
    with (
        patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result),
        pytest.raises(ValueError, match="unknown preset"),
    ):
        to_markdown(
            fake_docx,
            output_dir=tmp_path / "out",
            preset="bogus",
            diagrams=False,
        )


def test_to_markdown_writes_run_record(fake_docx: Path, tmp_path: Path) -> None:
    """Successful run writes `<output>/.pagespeak-run.json` with the
    resolved config + input sha256 + timestamps."""
    import json

    raw = "# 1. FOO\nbody content\n"
    fake_result = IngestResult(markdown=raw, source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        to_markdown(
            fake_docx,
            output_dir=out,
            preset="rag-default",
            diagrams=False,
            min_body_chars=0,
        )
    record_path = out / ".pagespeak-run.json"
    assert record_path.exists()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["preset"] == "rag-default"
    # Every preset-controlled flag is captured under resolved_flags.
    rf = record["resolved_flags"]
    assert rf["cleanup"] == "basic"
    assert rf["split_sections"] is True
    assert rf["nested_split"] is True
    assert rf["split_min_level"] == 2
    assert rf["normalize_headings"] is True
    assert rf["normalize_headings_mode"] == "heuristic"
    # Input metadata.
    assert record["input"] == fake_docx.name
    assert isinstance(record["input_sha256"], str)
    assert len(record["input_sha256"]) == 64  # hex sha256
    # Timestamps follow the documented ISO-Z shape.
    assert record["started_at"].endswith("Z")
    assert record["finished_at"].endswith("Z")
    # section_count reflects actual content sections (excludes INDEX.md).
    assert record["section_count"] == 1
    assert record["image_count"] == 0


def test_to_markdown_run_record_no_preset(fake_docx: Path, tmp_path: Path) -> None:
    """Without a preset, run.json's `preset` field is null and
    `resolved_flags` reflect the original to_markdown defaults."""
    import json

    fake_result = IngestResult(
        markdown="# 1. FOO\nbody\n",
        source_format="docx",
    )
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        to_markdown(
            fake_docx,
            output_dir=out,
            diagrams=False,
        )
    record = json.loads((out / ".pagespeak-run.json").read_text(encoding="utf-8"))
    assert record["preset"] is None
    rf = record["resolved_flags"]
    # Original defaults: split off, normalize off, cleanup basic.
    assert rf["split_sections"] is False
    assert rf["normalize_headings"] is False
    assert rf["cleanup"] == "basic"


def test_rerun_from_split_clears_sections_only(tmp_path):
    src = tmp_path / "doc.html"
    src.write_text("<h1>Hello</h1><p>body</p>", encoding="utf-8")
    out = tmp_path / "out"

    from pagespeak import to_markdown

    to_markdown(src, output_dir=out, diagrams=False, split_sections=True)

    raw = out / "doc.raw.md"
    cleaned = out / "doc.cleaned.md"
    sections = out / "sections"
    assert raw.exists() and cleaned.exists() and sections.exists()

    # Re-run with rerun_from='split' — sections should be deleted &
    # rebuilt; raw + cleaned preserved.
    raw_mtime = raw.stat().st_mtime
    cl_mtime = cleaned.stat().st_mtime

    to_markdown(src, output_dir=out, diagrams=False, split_sections=True, rerun_from="split")

    assert raw.stat().st_mtime == raw_mtime, "raw.md should not be touched"
    assert cleaned.stat().st_mtime == cl_mtime, "cleaned.md should not be touched"
    assert sections.exists(), "sections rebuilt"


def test_cleanup_fixes_cover_chrome_and_orphan_shape(tmp_path) -> None:
    # Cleanup-phase work: the cover-label heading (`## User Manual`) is
    # demoted by empty-shell, the trailing margin code (`###### EN`) by
    # orphan-fragments; the real title is kept. The structure phase also
    # writes `structured.md` (its holistic passes are no-ops on this small
    # synthetic), so the checkpoint exists but the cleanup-phase fixes are
    # what produced the visible result.
    from pagespeak import to_markdown

    raw = "## User Manual\n# RACK MIXER\nintro\n## Chapter\nbody\n###### EN\n"
    (tmp_path / "doc.raw.md").write_text(raw, encoding="utf-8")
    res = to_markdown(tmp_path, output_dir=tmp_path, diagrams=False)
    content = res.markdown
    assert "## User Manual" not in content
    assert "###### EN" not in content
    assert "# RACK MIXER" in content


def test_rerun_from_unknown_stage_raises():
    import pytest

    from pagespeak import to_markdown

    with pytest.raises(ValueError, match="unknown rerun_from stage"):
        to_markdown("nonexistent", output_dir="/tmp", rerun_from="bogus")  # type: ignore[arg-type]


# --- directory-input mode -------------------------------------------


def test_to_markdown_directory_input_resumes_from_raw_md(tmp_path, monkeypatch):
    """to_markdown(<outdir>) where <outdir>/<stem>.raw.md exists:
    skips backend, runs Phase 3 on raw.md."""
    from pagespeak.orchestrators._dispatch import to_markdown

    out = tmp_path / "out"
    out.mkdir()
    (out / "images").mkdir()
    raw_path = out / "doc.raw.md"
    raw_path.write_text("# Doc\n\nNo images.\n", encoding="utf-8")

    # Track whether any backend was called.
    backend_calls: list[str] = []
    from pagespeak.backends import _pdf_dispatch

    def fail_if_called(*args, **kwargs):
        backend_calls.append("called")
        raise AssertionError("backend should not have been called")

    monkeypatch.setattr(_pdf_dispatch, "convert", fail_if_called)

    result = to_markdown(out, output_dir=out)
    assert result.markdown.startswith("# Doc")
    assert backend_calls == []


def test_to_markdown_directory_input_requires_raw_md(tmp_path):
    """to_markdown(<outdir>) errors when no <stem>.raw.md is present."""
    from pagespeak.orchestrators._dispatch import to_markdown

    out = tmp_path / "out"
    out.mkdir()

    import pytest

    with pytest.raises(FileNotFoundError, match="raw.md"):
        to_markdown(out)


def test_to_markdown_directory_input_rejects_multiple_raw_md(tmp_path):
    """to_markdown(<outdir>) with >1 raw.md files raises ValueError."""
    from pagespeak.orchestrators._dispatch import to_markdown

    out = tmp_path / "out"
    out.mkdir()
    (out / "doc1.raw.md").write_text("# A\n", encoding="utf-8")
    (out / "doc2.raw.md").write_text("# B\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Multiple"):
        to_markdown(out)


# --- cross_refs auto-remap + workers routing -------------------


def test_to_markdown_defaults_cross_refs_to_remap_when_manifest_present(tmp_path, monkeypatch):
    """When <outdir>/manifest.json exists, cross_refs defaults to 'remap'."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "doc.raw.md").write_text(
        '<span id="page-3-2"></span>\n# H\n[r](#page-3-2)\n',
        encoding="utf-8",
    )
    (out / "manifest.json").write_text(
        '{"version": 3, "input_path": "/x/y.pdf", "input_sha256": "abc", "chunks": [], "vision": {}}',
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def fake_cleanup(md, *, level, cross_refs):
        captured["cross_refs"] = cross_refs
        return md

    monkeypatch.setattr("pagespeak.services._cleanup.cleanup_markdown", fake_cleanup)

    from pagespeak.orchestrators._dispatch import to_markdown

    to_markdown(out, output_dir=out)

    assert captured["cross_refs"] == "remap"


def test_to_markdown_keeps_cross_refs_when_no_manifest(tmp_path, monkeypatch):
    """No manifest → cross_refs stays at user/default 'keep'."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "doc.raw.md").write_text("# H\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_cleanup(md, *, level, cross_refs):
        captured["cross_refs"] = cross_refs
        return md

    monkeypatch.setattr("pagespeak.services._cleanup.cleanup_markdown", fake_cleanup)

    from pagespeak.orchestrators._dispatch import to_markdown

    to_markdown(out, output_dir=out)
    assert captured["cross_refs"] == "keep"


def test_to_markdown_explicit_cross_refs_wins_over_manifest(tmp_path, monkeypatch):
    """User-passed cross_refs always wins, even when manifest is present."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "doc.raw.md").write_text("# H\n", encoding="utf-8")
    (out / "manifest.json").write_text(
        '{"version": 3, "input_path": "/x/y.pdf", "input_sha256": "abc", "chunks": [], "vision": {}}',
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def fake_cleanup(md, *, level, cross_refs):
        captured["cross_refs"] = cross_refs
        return md

    monkeypatch.setattr("pagespeak.services._cleanup.cleanup_markdown", fake_cleanup)

    from pagespeak.orchestrators._dispatch import to_markdown

    to_markdown(out, output_dir=out, cross_refs="strip")
    assert captured["cross_refs"] == "strip"


def test_to_markdown_workers_gt_1_routes_through_ingest(tmp_path, monkeypatch):
    """When workers > 1 on a file input, dispatcher routes through ingest."""
    from pagespeak.orchestrators import _dispatch

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake")
    out = tmp_path / "out"

    captured: dict[str, object] = {}

    def fake_ingest(input_path, **kwargs):
        from pathlib import Path

        captured["input_path"] = Path(input_path)
        captured["workers"] = kwargs["workers"]
        out_dir = Path(kwargs["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        raw = out_dir / f"{Path(input_path).stem}.raw.md"
        raw.write_text("# Doc\n", encoding="utf-8")
        return raw

    monkeypatch.setattr(_dispatch, "_ingest_orchestrator", fake_ingest)

    _dispatch.to_markdown(src, output_dir=out, workers=4)
    assert captured["workers"] == 4
    assert captured["input_path"] == src


def test_vision_cache_only_conflicts_with_no_diagrams(tmp_path):
    with pytest.raises(ValueError, match="vision-cache-only"):
        to_markdown(
            tmp_path / "x.docx",
            output_dir=tmp_path / "out",
            diagrams=False,
            vision_cache_only=True,
        )


def test_vision_phase_threads_cache_only(monkeypatch, tmp_path):
    import pagespeak.services._diagrams as diag
    from pagespeak.models._models import IngestResult
    from pagespeak.orchestrators._context import PipelineContext
    from pagespeak.orchestrators._phases import VisionPhase

    out = tmp_path / "out"
    out.mkdir()
    img = out / "img.png"
    img.write_bytes(b"fake")

    captured: dict[str, object] = {}

    def fake_gather(images, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(diag, "gather_diagrams", fake_gather)

    ctx = PipelineContext(
        src=out,
        out=out,
        dir_mode=True,
        doc_stem="doc",
        effective_stem="doc",
        suffix=".md",
        source_format="raw",
        raw_md_path=out / "doc.raw.md",
        cleaned_md_path=out / "doc.cleaned.md",
        normalized_md_path=out / "doc.normalized.md",
        repaired_md_path=out / "doc.repaired.md",
        structured_md_path=out / "doc.structured.md",
        visioned_md_path=out / "doc.visioned.md",
        diagrams=True,
        vision_backend=None,
        vision_model=None,
        vision_concurrency=None,
        vision_cache_only=True,
        preserve_alt=False,
        force_ocr=False,
        device=None,
        page_range=None,
        html_base_url=None,
        cleanup="off",
        cross_refs="keep",
        split_sections=False,
        nested_split=False,
        split_min_level=None,
        split_max_level=None,
        split_target_kb=None,
        min_body_chars=None,
        english_only=False,
        regenerate_toc=False,
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
    ctx.result = IngestResult(markdown="![](img.png)", images=[img], source_format="raw")

    VisionPhase().run(ctx)
    assert captured["cache_only"] is True


# ── --repair-tables ingest sub-step (`_maybe_repair_tables`) ────────────────


def _repair_ctx(**over: object):
    from types import SimpleNamespace

    base = dict(repair_tables=True, pdf_backend="marker", suffix=".pdf", src=Path("x.pdf"))
    base.update(over)
    return SimpleNamespace(**base)


def test_maybe_repair_tables_off_by_default() -> None:
    from pagespeak.orchestrators._phases import _maybe_repair_tables

    md = "| x |\n| --- |\n"
    assert _maybe_repair_tables(_repair_ctx(repair_tables=False), md) == md


def test_maybe_repair_tables_skips_non_marker_backend() -> None:
    from pagespeak.orchestrators._phases import _maybe_repair_tables

    md = "| x |\n| --- |\n"
    assert _maybe_repair_tables(_repair_ctx(pdf_backend="docling"), md) == md


def test_maybe_repair_tables_skips_non_pdf() -> None:
    from pagespeak.orchestrators._phases import _maybe_repair_tables

    md = "| x |\n| --- |\n"
    assert _maybe_repair_tables(_repair_ctx(suffix=".docx"), md) == md


def test_maybe_repair_tables_delegates_when_marker_pdf(monkeypatch) -> None:
    import pagespeak.services._table_repair as tr
    from pagespeak.orchestrators._phases import _maybe_repair_tables

    monkeypatch.setattr(tr, "repair_tables_in_markdown", lambda _md, _pdf: ("REPAIRED", []))
    assert _maybe_repair_tables(_repair_ctx(), "anything") == "REPAIRED"


def test_maybe_repair_tables_warns_and_skips_when_docling_missing(monkeypatch) -> None:
    import pagespeak.services._table_repair as tr
    from pagespeak.orchestrators._phases import _maybe_repair_tables

    def _raise(_md: str, _pdf: str) -> object:
        raise ImportError("No module named 'docling'")

    monkeypatch.setattr(tr, "repair_tables_in_markdown", _raise)
    md = "| x |\n| --- |\n"
    assert _maybe_repair_tables(_repair_ctx(), md) == md  # graceful: unchanged


def test_docx_backend_routes_to_structured(make_docx, tmp_path) -> None:
    from unittest.mock import patch

    from pagespeak import to_markdown
    from pagespeak.models._models import IngestResult

    src = make_docx(document_xml="<w:p><w:r><w:t>Z</w:t></w:r></w:p>")
    docx_src = tmp_path / "z.docx"
    docx_src.write_bytes(src.read_bytes())
    sentinel = IngestResult(markdown="STRUCT", source_format="docx")
    with patch("pagespeak.backends._docx_dispatch.convert", return_value=sentinel) as conv:
        to_markdown(
            docx_src,
            output_dir=tmp_path / "out",
            diagrams=False,
            docx_backend="python-docx",
            cleanup="off",
        )
    conv.assert_called_once()
    assert conv.call_args.args[0] == "python-docx"


def test_dir_mode_split_keeps_original_source_file_from_identity(tmp_path: Path) -> None:
    """A dir-mode re-run whose run record knows the original source must stamp
    the TRUE `source_file` (and the identity keys), not the `<stem>.md`
    fallback that used to overwrite it on every re-tag."""
    import json

    out = tmp_path / "out"
    out.mkdir()
    md = "# Widget Guide\n\n## Overview\n\nBody content that is long enough to keep.\n"
    (out / "doc.raw.md").write_text(md, encoding="utf-8")
    (out / "doc.visioned.md").write_text(md, encoding="utf-8")
    (out / ".pagespeak-run.json").write_text(
        json.dumps({"input": "Widget Guide 2e.html", "input_sha256": "a" * 64}),
        encoding="utf-8",
    )
    to_markdown(
        out,
        output_dir=out,
        start="split",
        stop_after="split",
        diagrams=False,
        split_sections=True,
        split_min_level=2,
        source_type="textbook",
    )
    text = (out / "sections" / "Overview.md").read_text(encoding="utf-8")
    assert 'source_file: "Widget Guide 2e.html"' in text
    assert 'source_id: "widget-guide-2e"' in text
    assert f'source_sha256: "{"a" * 64}"' in text


def test_to_markdown_writes_master_doc(fake_docx: Path, tmp_path: Path) -> None:
    """The library writes the final `<stem>.md` itself — a library consumer
    (no CLI) must get the master, not only checkpoints + sections."""
    fake_result = IngestResult(markdown="# Title\n\nBody.\n", source_format="docx")
    out = tmp_path / "out"
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        result = to_markdown(fake_docx, output_dir=out, diagrams=False, cleanup="off")
    master = out / f"{fake_docx.stem}.md"
    assert master.exists()
    assert master.read_text(encoding="utf-8") == result.markdown


def test_to_markdown_early_stop_does_not_clobber_master(fake_docx: Path, tmp_path: Path) -> None:
    """`stop_after` at an intermediate phase leaves `result.markdown` as a
    checkpoint; writing it to `<stem>.md` would clobber the real final doc."""
    fake_result = IngestResult(markdown="raw checkpoint", source_format="docx")
    out = tmp_path / "out"
    out.mkdir()
    final = "# The real final document\n"
    (out / f"{fake_docx.stem}.md").write_text(final, encoding="utf-8")
    with patch("pagespeak.backends._docx.convert_with_markitdown", return_value=fake_result):
        to_markdown(fake_docx, output_dir=out, diagrams=False, cleanup="off", stop_after="cleanup")
    assert (out / f"{fake_docx.stem}.md").read_text(encoding="utf-8") == final


def test_dir_mode_split_only_rerun_writes_master(tmp_path: Path) -> None:
    """A `--from split` dir-mode re-run writes the master — the library-consumer
    footgun where split-only runs produced sections but no `<stem>.md`."""
    out = tmp_path / "out"
    out.mkdir()
    md = "# Widget Guide\n\n## Overview\n\nBody content that is long enough to keep.\n"
    (out / "doc.raw.md").write_text(md, encoding="utf-8")
    (out / "doc.visioned.md").write_text(md, encoding="utf-8")
    to_markdown(
        out,
        output_dir=out,
        start="split",
        stop_after="split",
        diagrams=False,
        split_sections=True,
    )
    text = (out / "doc.md").read_text(encoding="utf-8")
    assert "# Widget Guide" in text
    assert "## Overview" in text
