"""Tests for pagespeak.services._provenance (output provenance frontmatter)."""

from __future__ import annotations

from pagespeak.services._provenance import (
    build_frontmatter,
    build_provenance_frontmatter,
    clean_source_label,
)


def test_clean_source_label_normalizes_separators() -> None:
    assert clean_source_label("Adat_Manual") == "Adat Manual"
    assert clean_source_label("vendor-pro-c-2") == "vendor pro c 2"
    assert clean_source_label("_ACME_USER_MANUAL_V2") == "ACME USER MANUAL V2"


def test_clean_source_label_collapses_and_strips() -> None:
    # The " - " hyphen becomes a space, then the doubled space collapses.
    assert (
        clean_source_label("Device+ Eight User Guide V5 - EN") == "Device+ Eight User Guide V5 EN"
    )


def test_clean_source_label_preserves_casing_and_other_punctuation() -> None:
    # Casing, '+', '|', digits, and spacing in already-clean stems survive —
    # the cleaner only touches `_`/`-`/whitespace, never aggressive cruft.
    assert clean_source_label("Acme Synth 5 Manual") == "Acme Synth 5 Manual"
    assert clean_source_label("Plugin | Manual | Vendor") == "Plugin | Manual | Vendor"
    assert clean_source_label("Model7 User Manualv 1-2") == "Model7 User Manualv 1 2"


def test_clean_source_label_falls_back_when_cleaning_empties() -> None:
    # Genuinely empty / whitespace-only stems → "". An all-separator stem
    # has no real content to recover, so the stripped original is returned.
    assert clean_source_label("") == ""
    assert clean_source_label("   ") == ""
    assert clean_source_label("___") == "___"


def test_build_frontmatter_orders_and_skips_none() -> None:
    out = build_frontmatter({"a": "x", "b": None, "c": 3})
    assert out == '---\na: "x"\nc: 3\n---\n\n'


def test_build_frontmatter_empty_returns_blank() -> None:
    assert build_frontmatter({}) == ""
    assert build_frontmatter({"a": None}) == ""


def test_build_frontmatter_json_encodes_risky_values() -> None:
    out = build_frontmatter({"exam": 'Exam 3: SNS/ANS, "x"'})
    # JSON-encoded so the colon/quotes can't corrupt the YAML block.
    assert 'exam: "Exam 3: SNS/ANS, \\"x\\""' in out


def test_all_fields_emits_yaml_block() -> None:
    fm = build_provenance_frontmatter(
        source_type="textbook",
        source_label="Applied Widgetry Handbook",
        source_file="applied-widgetry-handbook.md",
    )
    assert fm == (
        "---\n"
        'source_type: "textbook"\n'
        'source_label: "Applied Widgetry Handbook"\n'
        'source_file: "applied-widgetry-handbook.md"\n'
        "---\n\n"
    )


def test_no_type_or_label_returns_empty() -> None:
    # source_file alone does NOT trigger frontmatter — emission is opt-in
    # on source_type / source_label so unflagged conversions are unchanged.
    assert build_provenance_frontmatter(source_type=None, source_label=None) == ""
    assert build_provenance_frontmatter(source_file="x.md") == ""


def test_only_type_omits_label() -> None:
    fm = build_provenance_frontmatter(source_type="lab", source_file="lab.md")
    assert fm == ('---\nsource_type: "lab"\nsource_file: "lab.md"\n---\n\n')
    assert "source_label" not in fm


def test_only_label_omits_type() -> None:
    fm = build_provenance_frontmatter(source_label="Lab Manual")
    assert fm == ('---\nsource_label: "Lab Manual"\n---\n\n')


def test_values_are_json_quoted_for_safe_escaping() -> None:
    # A label with a colon and a double-quote must not corrupt the YAML.
    fm = build_provenance_frontmatter(source_label='Toolcraft: "6th" Edition')
    assert 'source_label: "Toolcraft: \\"6th\\" Edition"' in fm
