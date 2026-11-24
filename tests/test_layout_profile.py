"""Tests for backends._layout_profile."""

from __future__ import annotations

from pathlib import Path

import pytest
from pw_foundation.exceptions import InvalidInputError

from pagespeak.backends._layout_profile import load_profile, profile_from_mapping
from tests.fixtures.layout_book import profile_mapping, write_profile


def test_a_profile_reads_every_section() -> None:
    p = profile_from_mapping(profile_mapping())
    assert p.head_y == 740 and p.pages == (0, 2) and p.skip_pages == frozenset({1})
    assert p.headings[0].level == 2 and p.headings[0].caps
    assert p.figure_caption.match("PLATE 2-3. x") and not p.figure_caption.match("Plate 2-3")
    assert p.aside_heading.search("## summary")  # case-insensitive by design
    assert p.opener.heading.format(n=1, title=p.opener.titles[0]) == "Part 1: First Things"
    assert p.crop_overrides == {} and p.left_out_text == ()
    assert p.acute_as_prime is False and p.group_after_empty_head is False


def test_the_optional_switches_load() -> None:
    m = profile_mapping()
    m["fonts"]["acute_as_prime"] = True
    m["document"]["group_after_empty_head"] = True
    p = profile_from_mapping(m)
    assert p.acute_as_prime is True and p.group_after_empty_head is True


def test_crop_overrides_and_left_out_text_load() -> None:
    m = profile_mapping()
    m["document"]["crop_overrides"] = {"p0002-plate-1-1.jpeg": [1, 2, 3, 4]}
    m["source_map"] = {"left_out_text": [["^WATERMARK", "printed on every page"]]}
    p = profile_from_mapping(m)
    assert p.crop_overrides == {"p0002-plate-1-1.jpeg": [1.0, 2.0, 3.0, 4.0]}
    assert p.left_out_text == (("^WATERMARK", "printed on every page"),)


def _rule(m: dict, **change: object) -> None:
    m["fonts"]["headings"][0].update(change)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda m: m.update(version=2), "version must be 1"),
        (lambda m: m.update(version=True), "version must be 1"),
        (lambda m: m.update(version=1.0), "version must be 1"),
        (lambda m: m["document"].pop("opener"), r"document\.opener is missing"),
        (lambda m: m["pages"].update(first=-1), r"pages\.first must be between 0 and pages\.last"),
        (lambda m: m["pages"].update(first=3), r"pages\.first must be between 0 and pages\.last"),
        (lambda m: m["pages"].update(skip=[9]), r"pages\.skip names page 9 \(0-based\), outside"),
        (
            lambda m: m["pages"].update(flow_charts=[9]),
            r"pages\.flow_charts names page 9 \(0-based\), outside",
        ),
        (
            lambda m: m["document"]["title_block"].update(cover_page=9),
            r"title_block\.cover_page names page 9 \(0-based\), outside",
        ),
        (
            lambda m: m["document"]["title_block"].update(lines=[{"page": 7, "pattern": "x"}]),
            r"title_block\.lines\[0\]\.page names page 7 \(0-based\), outside",
        ),
        (
            lambda m: m["document"].update(drop_lines=[{"page": 9, "pattern": "x"}]),
            r"drop_lines\[0\]\.page names page 9 \(0-based\), outside",
        ),
        (lambda m: _rule(m, level=0), r"headings\[0\]\.level must be between 1 and 6"),
        (lambda m: _rule(m, level=7), r"headings\[0\]\.level must be between 1 and 6"),
        (lambda m: m["bands"].update(floor_y=800), r"bands\.floor_y must be below bands\.head_y"),
        (
            lambda m: m["bands"].update(page_number_inner=[500, 100]),
            r"page_number_inner must run from left to right",
        ),
        (lambda m: m["fonts"].update(body=""), r"fonts\.body must not be empty"),
        (lambda m: m["fonts"].update(heading=""), r"fonts\.heading must not be empty"),
        (
            lambda m: m["fonts"].update(furniture=[""]),
            r"fonts\.furniture must not hold an empty text",
        ),
        (lambda m: m["patterns"].update(checkbox=""), r"patterns\.checkbox must not be empty"),
        (
            lambda m: m["patterns"].update(stops_exclude=""),
            r"patterns\.stops_exclude must not be empty",
        ),
        (lambda m: m["document"]["opener"].update(text=""), r"opener\.text must not be empty"),
        (
            lambda m: m["document"]["opener"].update(heading=""),
            r"opener\.heading must not be empty",
        ),
        (
            lambda m: m["document"]["opener"].update(picture_label=""),
            r"opener\.picture_label must not be empty",
        ),
        (
            lambda m: m["document"]["title_block"].update(heading=""),
            r"title_block\.heading must not be empty",
        ),
        (
            lambda m: m.update(
                source_map={"left_out_text": [["^DRAFT", "a mark"], ["(unclosed", "why"]]}
            ),
            r"source_map\.left_out_text\[1\] is not a valid pattern",
        ),
        (
            lambda m: m["patterns"].update(figure_caption=""),
            r"patterns\.figure_caption matches the empty string",
        ),
        (
            lambda m: m["patterns"].update(page_number=".*"),
            r"patterns\.page_number matches the empty string",
        ),
        (
            lambda m: m["document"]["opener"].update(heading="Part {x}"),
            r"opener\.heading is not a valid template.*\{n\}, \{title\}",
        ),
        (
            lambda m: m["document"]["opener"].update(heading="Part {"),
            r"opener\.heading is not a valid template",
        ),
        (
            lambda m: m["document"]["opener"].update(picture_label="{title} picture"),
            r"opener\.picture_label is not a valid template.*\{n\}",
        ),
        (
            lambda m: m["document"].update(crop_overrides={"a.jpeg": [300, 350, 72, 200]}),
            r"crop_overrides\.a\.jpeg must be a box \[left, bottom, right, top\]",
        ),
        (lambda m: m["bands"].pop("head_y"), r"bands\.head_y is missing"),
        (lambda m: m.pop("fonts"), "fonts is missing"),
        (lambda m: m.update(fonts=["Times"]), "fonts must be a mapping"),
        (
            lambda m: m["patterns"].update(figure_caption="(unclosed"),
            r"patterns\.figure_caption is not a valid pattern",
        ),
        (lambda m: m.update(band={}), "unknown key.*band"),
        (
            lambda m: m["document"].update(crop_overides={}),
            "document has unknown key.*crop_overides",
        ),
        (lambda m: m["bands"].update(head_y="740"), r"bands\.head_y must be a number"),
        (lambda m: m["bands"].update(head_y=True), r"bands\.head_y must be a number"),
        (
            lambda m: m["bands"].update(page_number_inner=[75]),
            r"page_number_inner must be 2 numbers",
        ),
        (lambda m: m["fonts"].update(body=12), r"fonts\.body must be text"),
        (lambda m: m["fonts"].update(furniture="Courier"), r"fonts\.furniture must be a list"),
        (lambda m: m["fonts"].update(furniture=[7]), r"fonts\.furniture must be a list of text"),
        (lambda m: _rule(m, level="2"), r"headings\[0\]\.level must be a whole number"),
        (lambda m: _rule(m, caps="yes"), r"headings\[0\]\.caps must be true or false"),
        (lambda m: _rule(m, cap=True), r"headings\[0\] has unknown key.*cap"),
        (lambda m: m["patterns"].update(list_mark=3), r"patterns\.list_mark must be text"),
        (lambda m: m["pages"].update(skip=1), r"pages\.skip must be a list"),
        (lambda m: m["pages"].update(last=2.5), r"pages\.last must be a whole number"),
        (
            lambda m: m["document"]["opener"].update(titles="First Things"),
            r"opener\.titles must be a list",
        ),
        (
            lambda m: m["document"].update(group_after_empty_head="yes"),
            r"group_after_empty_head must be true or false",
        ),
        (
            lambda m: m["document"].update(crop_overrides={"a.jpeg": [1, 2, 3]}),
            r"crop_overrides\.a\.jpeg must be 4 numbers",
        ),
        (
            lambda m: m["document"].update(drop_lines=[{"page": 2, "patern": "x"}]),
            r"drop_lines\[0\] has unknown key.*patern",
        ),
        (
            lambda m: m.update(source_map={"left_out_text": [["only a pattern"]]}),
            r"left_out_text\[0\] must be 2 texts",
        ),
    ],
)
def test_a_bad_profile_names_what_is_wrong(change, message: str) -> None:
    m = profile_mapping()
    change(m)
    with pytest.raises(InvalidInputError, match=message):
        profile_from_mapping(m)


def test_a_raster_table_is_checked_field_by_field() -> None:
    spec = {
        "top": 600,
        "figure": [100, 300, 400, 500],
        "label": "parts, numbered",
        "title": "CHART 1-1. Parts",
        "header": ["A", "B"],
        "rows": [["1", "one"]],
    }
    m = profile_mapping()
    m["document"]["raster_tables"] = {2: dict(spec)}
    assert profile_from_mapping(m).raster_tables == {2: spec}
    m["document"]["raster_tables"] = {2: dict(spec, rows=[["1", 1]])}
    with pytest.raises(
        InvalidInputError, match=r"raster_tables\.2\.rows\[0\] must be a list of text"
    ):
        profile_from_mapping(m)
    for change, message in (
        ({"heder": []}, "unknown key.*heder"),
        ({"rows": [["1"]]}, r"raster_tables\.2\.rows\[0\] must have 2 cells, as the header has"),
        (
            {"figure": [400, 300, 100, 500]},
            r"raster_tables\.2\.figure must be a box \[left, bottom",
        ),
    ):
        m["document"]["raster_tables"] = {2: dict(spec, **change)}
        with pytest.raises(InvalidInputError, match=message):
            profile_from_mapping(m)
    for page, message in (
        (True, "must be keyed by a page number"),
        (9, r"names page 9 \(0-based\), outside"),
    ):
        m["document"]["raster_tables"] = {page: dict(spec)}
        with pytest.raises(InvalidInputError, match=message):
            profile_from_mapping(m)


def test_a_selector_may_match_every_line() -> None:
    m = profile_mapping()
    m["document"]["title_block"].update(keep=".*", lines=[{"page": 1, "pattern": ""}])
    m["document"]["drop_lines"] = [{"page": 2, "pattern": ".*"}]
    p = profile_from_mapping(m)
    assert p.title_block.keep.match("any cover line") and p.drop_lines[0][1].match("any line")
    assert p.title_block.lines[0][1].match("the first line of the page")


def test_a_pattern_the_book_does_not_need_can_never_match() -> None:
    m = profile_mapping()
    m["patterns"].update(credit="(?!)", note_prefix="")  # a prefix to strip may be empty
    p = profile_from_mapping(m)
    assert not p.credit.match("anything") and p.note_prefix.sub("", "x") == "x"


@pytest.mark.parametrize("text", ["version: 1\nbands: [unclosed\n", "version: 1\nversion: 1\n"])
def test_a_file_that_is_not_valid_yaml_is_refused_by_name(tmp_path: Path, text: str) -> None:
    (tmp_path / "p.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(InvalidInputError, match=r"layout profile .*p\.yaml: "):
        load_profile(tmp_path / "p.yaml")


def test_load_profile_reads_a_file_and_refuses_a_non_mapping(tmp_path: Path) -> None:
    assert load_profile(write_profile(tmp_path / "p.yaml")).body_font == "Times"
    (tmp_path / "list.yaml").write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(InvalidInputError, match="not a mapping"):
        load_profile(tmp_path / "list.yaml")
    with pytest.raises(InvalidInputError):
        load_profile(tmp_path / "missing.yaml")
