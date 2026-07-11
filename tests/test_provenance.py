"""Tests for pagespeak.services._provenance (output provenance frontmatter)."""

from __future__ import annotations

import json
from pathlib import Path

from pagespeak.services._provenance import (
    build_frontmatter,
    build_provenance_frontmatter,
    clean_source_label,
    persistable_source_identity,
    resolve_source_identity,
    source_id_from_name,
)
from pagespeak.services._run_record import file_sha256


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


def test_source_id_from_name_slugifies_stem() -> None:
    assert (
        source_id_from_name("Applied Widgetry Handbook 2e.html") == "applied-widgetry-handbook-2e"
    )
    assert source_id_from_name("Adat_Manual.docx") == "adat-manual"
    assert source_id_from_name("plain") == "plain"


def test_source_id_from_name_empty_or_all_separators_returns_empty() -> None:
    assert source_id_from_name("") == ""
    assert source_id_from_name("___") == ""


def test_resolve_source_identity_file_mode_hashes_source(tmp_path: Path) -> None:
    src = tmp_path / "Widget Guide 2e.html"
    src.write_text("<html></html>", encoding="utf-8")
    source_id, sha = resolve_source_identity(src, tmp_path / "out", dir_mode=False)
    assert source_id == "widget-guide-2e"
    assert sha == file_sha256(src)


def test_resolve_source_identity_dir_mode_reads_run_record(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / ".pagespeak-run.json").write_text(
        json.dumps({"input": "Widget Guide 2e.html", "input_sha256": "a" * 64}),
        encoding="utf-8",
    )
    source_id, sha = resolve_source_identity(out / "doc.raw.md", out, dir_mode=True)
    assert source_id == "widget-guide-2e"
    assert sha == "a" * 64


def test_resolve_source_identity_dir_mode_ignores_checkpoint_input(tmp_path: Path) -> None:
    # A dir-mode re-run's record names the raw checkpoint, not the source doc;
    # stamping that would mislabel the book. Omit instead.
    out = tmp_path / "out"
    out.mkdir()
    (out / ".pagespeak-run.json").write_text(
        json.dumps({"input": "doc.raw.md", "input_sha256": "b" * 64}), encoding="utf-8"
    )
    assert resolve_source_identity(out / "doc.raw.md", out, dir_mode=True) == (None, None)


def test_resolve_source_identity_missing_or_bad_record_returns_none(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    assert resolve_source_identity(out / "doc.raw.md", out, dir_mode=True) == (None, None)
    assert resolve_source_identity(out / "doc.raw.md", None, dir_mode=True) == (None, None)
    (out / ".pagespeak-run.json").write_text("not json", encoding="utf-8")
    assert resolve_source_identity(out / "doc.raw.md", out, dir_mode=True) == (None, None)


def test_resolve_source_identity_prefers_persisted_block_over_checkpoint_input(
    tmp_path: Path,
) -> None:
    """The durable path: even when a dir-mode re-run overwrote `input` with the
    raw checkpoint, the persisted `source_identity` block still resolves."""
    out = tmp_path / "out"
    out.mkdir()
    (out / ".pagespeak-run.json").write_text(
        json.dumps(
            {
                "input": "doc.raw.md",
                "input_sha256": "b" * 64,
                "source_identity": {
                    "file": "Widget Guide 2e.html",
                    "source_id": "widget-guide-2e",
                    "sha256": "a" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    source_id, sha = resolve_source_identity(out / "doc.raw.md", out, dir_mode=True)
    assert source_id == "widget-guide-2e"
    assert sha == "a" * 64


def test_persistable_source_identity_file_mode_builds_block(tmp_path: Path) -> None:
    src = tmp_path / "Widget Guide 2e.html"
    src.write_text("<html></html>", encoding="utf-8")
    block = persistable_source_identity(src, tmp_path / "out", dir_mode=False)
    assert block == {
        "file": "Widget Guide 2e.html",
        "source_id": "widget-guide-2e",
        "sha256": file_sha256(src),
    }


def test_persistable_source_identity_dir_mode_carries_block_forward(tmp_path: Path) -> None:
    """A dir-mode re-run re-persists the existing block verbatim, so identity
    survives any number of re-runs."""
    out = tmp_path / "out"
    out.mkdir()
    identity = {"file": "Widget Guide 2e.html", "source_id": "widget-guide-2e", "sha256": "a" * 64}
    (out / ".pagespeak-run.json").write_text(
        json.dumps({"input": "doc.raw.md", "input_sha256": "b" * 64, "source_identity": identity}),
        encoding="utf-8",
    )
    assert persistable_source_identity(out / "doc.raw.md", out, dir_mode=True) == identity


def test_persistable_source_identity_dir_mode_upgrades_legacy_record(tmp_path: Path) -> None:
    """A pre-fix record (real input, no source_identity block) upgrades on the
    next dir-mode run."""
    out = tmp_path / "out"
    out.mkdir()
    (out / ".pagespeak-run.json").write_text(
        json.dumps({"input": "Widget Guide 2e.html", "input_sha256": "a" * 64}),
        encoding="utf-8",
    )
    block = persistable_source_identity(out / "doc.raw.md", out, dir_mode=True)
    assert block == {
        "file": "Widget Guide 2e.html",
        "source_id": "widget-guide-2e",
        "sha256": "a" * 64,
    }


def test_persistable_source_identity_unrecoverable_returns_none(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    assert persistable_source_identity(out / "doc.raw.md", out, dir_mode=True) is None
    (out / ".pagespeak-run.json").write_text(
        json.dumps({"input": "doc.raw.md", "input_sha256": "b" * 64}), encoding="utf-8"
    )
    assert persistable_source_identity(out / "doc.raw.md", out, dir_mode=True) is None
