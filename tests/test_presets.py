"""Tests for pagespeak.services._presets — registry shape + resolver."""

from __future__ import annotations

import pytest

from pagespeak.services._presets import PRESETS, Preset, resolve_preset


def test_known_preset_set() -> None:
    """The documented presets exist; pinning the registry keeps
    docs/presets.md in sync with code."""
    assert set(PRESETS.keys()) == {"rag-default", "flat", "textbook", "archival", "qti"}


def test_resolve_preset_returns_frozen_dataclass() -> None:
    p = resolve_preset("rag-default")
    assert isinstance(p, Preset)
    # Frozen — assignment must raise.
    with pytest.raises(AttributeError):
        p.cleanup = "off"  # type: ignore[misc]


def test_rag_default_shape() -> None:
    p = resolve_preset("rag-default")
    assert p.cleanup == "basic"
    assert p.split_sections is True
    assert p.nested_split is True
    assert p.split_min_level == 2
    assert p.normalize_headings is True
    assert p.normalize_headings_mode == "heuristic"


def test_flat_shape() -> None:
    """Flat preset: split, no nesting, no normalize."""
    p = resolve_preset("flat")
    assert p.split_sections is True
    assert p.nested_split is False
    assert p.normalize_headings is False


def test_textbook_shape() -> None:
    """Textbook preset: aggressive cleanup, deep nesting, heuristic normalize."""
    p = resolve_preset("textbook")
    assert p.cleanup == "aggressive"
    assert p.split_sections is True
    assert p.nested_split is True
    assert p.split_min_level == 3
    assert p.normalize_headings is True
    assert p.normalize_headings_mode == "heuristic"


def test_archival_shape() -> None:
    """Archival preset: light touch — nesting from L1, no cleanup, no normalize."""
    p = resolve_preset("archival")
    assert p.cleanup == "off"
    assert p.split_sections is True
    assert p.nested_split is True
    assert p.split_min_level == 1
    assert p.normalize_headings is False


def test_qti_shape() -> None:
    """QTI preset: clean source already — cleanup off; per-quiz files are
    written flat by the QTI finalizer, so the generic splitter is off."""
    p = resolve_preset("qti")
    assert p.cleanup == "off"
    assert p.split_sections is False
    assert p.nested_split is False
    assert p.normalize_headings is False


def test_provenance_on_only_for_rag_default() -> None:
    """Provenance frontmatter is on for rag-default (the multi-source RAG
    preset) and off for every other preset — so non-RAG runs stay
    frontmatter-free unless the caller opts in with --provenance."""
    assert resolve_preset("rag-default").provenance is True
    for name in ("flat", "textbook", "archival", "qti"):
        assert resolve_preset(name).provenance is False


def test_unknown_preset_raises_with_helpful_list() -> None:
    """Unknown name raises ValueError with the valid options listed —
    catches typos at config load time, not pipeline time."""
    with pytest.raises(ValueError) as exc_info:
        resolve_preset("ragdefault")
    msg = str(exc_info.value)
    assert "ragdefault" in msg
    # Each valid preset must appear in the error.
    for name in ("rag-default", "flat", "textbook", "archival", "qti"):
        assert name in msg


def test_to_dict_round_trips_all_fields() -> None:
    """`to_dict()` is what `_run_record` stamps into the run.json
    `resolved_flags`. Pin every field so a future preset-field addition
    forces a test update."""
    p = resolve_preset("rag-default")
    d = p.to_dict()
    assert d == {
        "name": "rag-default",
        "cleanup": "basic",
        "split_sections": True,
        "nested_split": True,
        "split_min_level": 2,
        "normalize_headings": True,
        "normalize_headings_mode": "heuristic",
        "strip_frontmatter": True,
        "provenance": True,
    }
