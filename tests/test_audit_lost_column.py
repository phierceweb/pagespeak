"""Tests for services._audit_lost_column — a table whose label column never arrived."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.services._audit_lost_column import _table_page, check_lost_column, suspect_tables

_LOST = (
    "## Panel Keys\n\n"
    "| | Description |\n| --- | --- |\n"
    "| | Opens the lid. |\n"
    "| | Locks the lid. |\n"
    "| | Starts the spin cycle. |\n"
)
_PAGE = (
    "Panel Keys Lid open key Opens the lid. "
    "Lid lock key Locks the lid. Spin start key Starts the spin cycle."
)
_OTHER_PAGES = ["Welcome to your washer. Level the feet first.", "Connecting the hoses."]
_ICONS = "| | Symbol |\n| --- | --- |\n| | Lamp glow. |\n| | Fan pulse. |\n| | Timer chime. |\n"
_FOOTER = "Model Seven User Manual"


def test_a_first_column_empty_on_most_rows_is_a_suspect() -> None:
    assert [(line, why, n) for line, _t, why, n in suspect_tables(_LOST)] == [
        (3, "first column empty on 3 of 3 rows", 3)
    ]


def test_a_one_column_table_is_a_suspect() -> None:
    md = "| Description |\n| --- |\n| Opens the lid. |\n| Locks the lid. |\n"
    assert [why for _l, _t, why, _n in suspect_tables(md)] == ["one-column table"]


def test_an_empty_header_row_is_still_the_header() -> None:
    md = "|  |  |\n| --- | --- |\n|  | Rinse |\n|  | Spin |\n|  | Drain |\n"
    assert [why for _l, _t, why, _n in suspect_tables(md)] == ["first column empty on 3 of 3 rows"]


def test_ordinary_tables_are_not_suspects() -> None:
    md = (
        "| Setting | Value |\n| --- | --- |\n| Mode | Eco |\n|  | (continued) |\n"
        "| Load | Full |\n| RPM | 1200 |\n"
    )
    assert suspect_tables(md) == []


def test_a_grouped_table_four_fifths_empty_is_not_a_suspect() -> None:
    """Continuation rows leave the label cell empty, but the group's first row
    carries its label."""
    md = (
        "| Setting | Value |\n| --- | --- |\n| Water level | Low |\n"
        "|  | Medium |\n|  | High |\n|  | Very high |\n|  | Maximum |\n"
    )
    assert suspect_tables(md) == []


def test_flags_a_suspect_whose_page_has_wording_found_nowhere() -> None:
    findings = check_lost_column(_LOST, [*_OTHER_PAGES, _PAGE])
    assert [(f.check, f.severity, f.line) for f in findings] == [
        ("lost_table_column", "warning", 3)
    ]
    assert "page 3" in findings[0].message
    assert "lid open" in findings[0].message


def test_an_icon_column_whose_page_arrived_whole_is_not_flagged() -> None:
    page = "Symbol Lamp glow. Fan pulse. Timer chime."
    assert check_lost_column(_ICONS, [*_OTHER_PAGES, page]) == []


def test_a_table_stored_column_by_column_is_not_flagged() -> None:
    """Pairs that cross cells in the page's column order reached the file all the same."""
    md = (
        "| | Command | Action |\n| --- | --- | --- |\n| | Play | Starts |\n| | Stop | Halts |\n"
        "| | Pause | Freezes |\n| | Rewind | Reverses |\n"
    )
    page = "Controls Command Action Play Stop Pause Rewind Starts Halts Freezes Reverses"
    assert check_lost_column(md, [*_OTHER_PAGES, page]) == []


def test_lost_labels_stored_column_by_column_are_flagged() -> None:
    page = (
        "Lid release key Lid hold key Drum turn key "
        "Description Opens the lid. Locks the lid. Starts the spin cycle."
    )
    assert check_lost_column(_LOST, [*_OTHER_PAGES, page])


def test_running_footers_and_page_numbers_inside_the_table_are_not_evidence() -> None:
    pages = [f"{p} {_FOOTER} {n}" for n, p in enumerate(_OTHER_PAGES, 40)]
    page = f"Symbol Lamp glow. {_FOOTER} 41 42 Fan pulse. Timer chime."
    assert check_lost_column(_ICONS, [*pages, page]) == []


def test_lone_unreached_pairs_are_not_evidence() -> None:
    """A lone pair is a seam (a word beside a stripped number or header); only a
    run of them is lost wording."""
    page = "Symbol quuw 40 Lamp glow. quux 41 Fan pulse. quuy 42 Timer chime."
    assert check_lost_column(_ICONS, [*_OTHER_PAGES, page]) == []


def test_two_unreached_pairs_are_not_enough() -> None:
    page = "Symbol Lamp glow. quux Fan pulse. Timer chime."
    assert check_lost_column(_ICONS, [*_OTHER_PAGES, page]) == []


def test_a_compound_wrapped_at_its_hyphen_reached_the_file() -> None:
    md = (
        "| | Feature |\n| --- | --- |\n| | A built-in timer for the wash cycle. |\n"
        "| | A hands-free door with a soft close. |\n| | A self-cleaning drum that runs monthly. |\n"
    )
    page = (
        "Feature A built-\nin timer for the wash cycle. A hands-\nfree door with a soft close. "
        "A self-\ncleaning drum that runs monthly."
    )
    assert check_lost_column(md, [*_OTHER_PAGES, page]) == []


def test_a_word_hyphenated_at_a_line_end_reached_the_file_whole() -> None:
    md = (
        "| | Feature |\n| --- | --- |\n| | Opens the compartment door. |\n"
        "| | Drains the reservoir tank. |\n| | Heats the chamber air. |\n"
    )
    page = (
        "Feature Opens the compart-\nment door. Drains the reser-\nvoir tank. "
        "Heats the cham-\nber air."
    )
    assert check_lost_column(md, [*_OTHER_PAGES, page]) == []


def test_a_page_holding_few_of_the_tables_words_is_not_its_page() -> None:
    assert check_lost_column(_LOST, [*_OTHER_PAGES, "Opens quux quuy quuz quuw cycle"]) == []


def test_numbers_do_not_place_a_table_on_another_languages_page() -> None:
    """A multilingual manual repeats a spec table's numbers on every language's page."""
    table = {"rate", "depth", "48", "96", "192", "24"}
    twin, own = {"48", "96", "192", "24", "abtastrate"}, {"rate", "depth", "specifications"}
    assert _table_page(table, [twin, own]) == 1


def test_audit_runs_the_check_with_the_source_pdf(tmp_path: Path, monkeypatch) -> None:
    from pagespeak.services import _audit_lost_column
    from pagespeak.services._audit import audit_paths

    doc = tmp_path / "doc"
    doc.mkdir()
    (doc / "doc.raw.md").write_text(_LOST, encoding="utf-8")
    monkeypatch.setattr(_audit_lost_column, "pdf_page_texts", lambda _pdf: [*_OTHER_PAGES, _PAGE])
    report = audit_paths([doc], source_for=lambda _md: tmp_path / "doc.pdf")
    checks = [f.check for findings in report.findings_by_file.values() for f in findings]
    assert "lost_table_column" in checks


@pytest.mark.parametrize("pages", [[], [""], ["", ""]])
def test_no_page_text_is_no_finding(pages: list[str]) -> None:
    assert check_lost_column(_LOST, pages) == []
