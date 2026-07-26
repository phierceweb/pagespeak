"""Tests for Docling heading-hierarchy option construction + level fixups.

Pure functions — no Docling conversion. The option-construction tests need
the docling package for the real `HeadingHierarchyOptions` model; the
markdown fixups do not.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pagespeak.backends._docling_headings import (
    HEADING_MAX_LEVEL,
    clamp_heading_overflow,
    coerce_option_value,
    enable_heading_hierarchy,
    promote_headings_without_h1,
)

# --- promote_headings_without_h1 ---


def test_promote_shifts_up_when_no_h1() -> None:
    md = "## Chapter\n\ntext\n\n### Section\n\n###### Deep\n"
    out = promote_headings_without_h1(md)
    assert out.splitlines()[0] == "# Chapter"
    assert "## Section" in out
    assert "##### Deep" in out


def test_promote_noop_when_h1_present() -> None:
    """Docling emitted a TitleItem — shifting would destroy the title."""
    md = "# Title\n\n## Chapter\n\n### Section\n"
    assert promote_headings_without_h1(md) == md


def test_promote_ignores_fenced_code() -> None:
    """A `#` comment inside a fence is not a heading: it must neither
    suppress the shift nor be rewritten."""
    md = "## Chapter\n\n```python\n# not a heading\n```\n\n### Section\n"
    out = promote_headings_without_h1(md)
    assert "# not a heading" in out
    assert "# Chapter" in out
    assert "## Section" in out


def test_promote_handles_tilde_fences() -> None:
    md = "## Chapter\n\n~~~\n# fake\n~~~\n\n### Section\n"
    out = promote_headings_without_h1(md)
    assert "# fake" in out
    assert "## Section" in out


def test_promote_leaves_non_heading_hashes_alone() -> None:
    md = "## Chapter\n\n#hashtag not a heading\n"
    out = promote_headings_without_h1(md)
    assert "#hashtag not a heading" in out


def test_promote_no_headings_is_unchanged() -> None:
    md = "just body text\n\nmore text\n"
    assert promote_headings_without_h1(md) == md


def test_promote_empty_document() -> None:
    assert promote_headings_without_h1("") == ""


def test_promote_preserves_trailing_newline() -> None:
    md = "## Chapter\n\nbody\n"
    assert promote_headings_without_h1(md).endswith("body\n")


def test_promote_is_idempotent_once_an_h1_exists() -> None:
    """A second pass is a no-op — the first pass created the H1."""
    once = promote_headings_without_h1("## Chapter\n\n### Section\n")
    assert promote_headings_without_h1(once) == once


def test_promote_rescues_seven_hash_headings() -> None:
    """The no-title shift alone brings a level-6 heading (7 hashes) back to
    valid markdown — the deepest tier survives distinct from level 5."""
    md = "## Chapter\n\n###### Banner\n\n####### Payload\n"
    out = promote_headings_without_h1(md)
    assert "# Chapter" in out
    assert "##### Banner" in out
    assert "###### Payload" in out


# --- clamp_heading_overflow ---


def test_clamp_rewrites_seven_hashes_to_six() -> None:
    md = "# Title\n\n####### Deep\n"
    assert "###### Deep" in clamp_heading_overflow(md)


def test_clamp_leaves_valid_headings_alone() -> None:
    md = "# Title\n\n###### Deep\n\nbody\n"
    assert clamp_heading_overflow(md) == md


def test_clamp_ignores_fenced_code() -> None:
    md = "# Title\n\n```\n####### not a heading\n```\n"
    assert clamp_heading_overflow(md) == md


# --- coerce_option_value ---


class _Model:
    """Stand-in for a pydantic options model (duck-typed on model_fields)."""

    model_fields = {"enabled": None, "max_level": None}

    def __init__(self, enabled: bool = False, max_level: int = 6) -> None:
        self.enabled = enabled
        self.max_level = max_level


def test_coerce_rebuilds_model_from_dict() -> None:
    out = coerce_option_value(_Model(), {"enabled": True, "max_level": 4})
    assert isinstance(out, _Model)
    assert out.enabled is True
    assert out.max_level == 4


def test_coerce_passes_through_non_dict() -> None:
    assert coerce_option_value(_Model(), 2.5) == 2.5


def test_coerce_passes_through_when_target_is_not_a_model() -> None:
    """A plain scalar field assigned a dict stays a dict — only nested
    option models are rebuilt."""
    value = {"a": 1}
    assert coerce_option_value(1.0, value) is value


def test_coerce_bad_dict_warns_and_passes_through(
    caplog: pytest.LogCaptureFixture,
) -> None:
    value = {"not_a_field": True}
    with caplog.at_level("WARNING"):
        out = coerce_option_value(_Model(), value)
    assert out is value
    assert any("docling_option_coercion_failed" in r.message for r in caplog.records)


# --- enable_heading_hierarchy ---


def test_enable_warns_and_noops_on_old_docling(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Docling < 2.109 has no heading_hierarchy_options — degrade to flat
    levels with a warning rather than raising."""
    opts = SimpleNamespace()
    with caplog.at_level("WARNING"):
        enable_heading_hierarchy(opts)
    assert any("docling_heading_hierarchy_unavailable" in r.message for r in caplog.records)
    assert not hasattr(opts, "heading_hierarchy_options")


def test_enable_sets_real_instance_full_depth_and_parsed_pages() -> None:
    pytest.importorskip("docling")
    from docling.datamodel.pipeline_options import (
        HeadingHierarchyOptions,
        PdfPipelineOptions,
    )

    opts = PdfPipelineOptions()
    enable_heading_hierarchy(opts)

    assert isinstance(opts.heading_hierarchy_options, HeadingHierarchyOptions)
    assert opts.heading_hierarchy_options.enabled is True
    # Full depth; the 7-hash render overflow is handled at the markdown
    # layer (promotion, then clamp), not by discarding the deepest tier.
    assert opts.heading_hierarchy_options.max_level == HEADING_MAX_LEVEL == 6
    # use_style silently finds nothing without parsed pages.
    assert opts.generate_parsed_pages is True
