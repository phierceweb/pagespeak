"""Tests for services._verify_pictures — ink that no cut picture holds."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.services._pdf_lines import PdfLine, PdfPage, read_pages
from pagespeak.services._source_map import LeftOut, MapPicture, SourceMap
from pagespeak.services._verify_doc import VerifyDoc
from pagespeak.services._verify_pictures import (
    _body_face,
    _cuts,
    _labels,
    check_picture_coverage,
)
from tests.fixtures.pdf_pages import PAGE_HEIGHT, Page, body_lines, make_pdf

pytest.importorskip("pypdfium2")
pytest.importorskip("fpdf")

# A drawing at x 200–320, 300–390pt from the top.
DRAWING = (200.0, 300.0, 120.0, 90.0)
WHOLE = (195.0, PAGE_HEIGHT - 395, 325.0, PAGE_HEIGHT - 295)
TOP_HALF = (195.0, PAGE_HEIGHT - 345, 325.0, PAGE_HEIGHT - 295)


def _check(tmp_path: Path, page: Page, **kw: object) -> list[tuple[str, bool]]:
    pdf = make_pdf(tmp_path / "a.pdf", [page])
    fields: dict[str, object] = {
        "pdf": pdf,
        "sha256": None,
        "pages": ((1, 1),),
        "body": (50.0, 740.0),
        "pictures": (),
        "left_out": (),
        "left_out_text": (),
    }
    fields.update(kw)
    smap = SourceMap(**fields)  # type: ignore[arg-type]  # test-built from a dict
    (tmp_path / "book.md").write_text("# Book\n", encoding="utf-8")
    doc = VerifyDoc(tmp_path, tmp_path / "book.md")
    result = check_picture_coverage(doc, read_pages(pdf, [1]), smap, pdf=pdf)
    return [(f.key.split(":")[1], f.blocking) for f in result.findings]


def test_a_drawing_inside_its_picture_is_covered(tmp_path: Path) -> None:
    pictures = (MapPicture("p1.png", 1, WHOLE),)
    assert _check(tmp_path, Page(drawings=[DRAWING]), pictures=pictures) == []


def test_a_drawing_no_picture_holds_was_dropped(tmp_path: Path) -> None:
    page = Page(lines=body_lines(["Some body text on the page."]), drawings=[DRAWING])
    assert _check(tmp_path, page) == [("dropped", True)]


def test_a_picture_that_cuts_through_a_drawing_was_cut_short(tmp_path: Path) -> None:
    pictures = (MapPicture("p1.png", 1, TOP_HALF),)
    assert _check(tmp_path, Page(drawings=[DRAWING]), pictures=pictures) == [("cut", True)]


def test_art_left_out_on_purpose_and_running_heads_are_not_dropped(tmp_path: Path) -> None:
    left_out = (LeftOut(1, WHOLE, "a decorative rule"),)
    assert _check(tmp_path, Page(drawings=[DRAWING]), left_out=left_out) == []
    assert _check(tmp_path, Page(drawings=[(200.0, 10.0, 120.0, 30.0)])) == []


def test_specks_under_the_size_floor_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = Page(drawings=[(200.0, 300.0, 9.0, 9.0)])
    assert _check(tmp_path, page) == []
    monkeypatch.setenv("PAGESPEAK_VERIFY_MIN_DROPPED_INK", "20")
    assert _check(tmp_path, page) == [("dropped", True)]


def test_the_same_icon_on_many_pages_is_a_note(tmp_path: Path) -> None:
    pdf = make_pdf(
        tmp_path / "a.pdf", [Page(drawings=[(500.0, 300.0, 30.0, 30.0)]) for _ in range(4)]
    )
    smap = SourceMap(pdf, None, ((1, 4),), (50.0, 740.0), (), (), ())
    (tmp_path / "book.md").write_text("# Book\n", encoding="utf-8")
    doc = VerifyDoc(tmp_path, tmp_path / "book.md")
    result = check_picture_coverage(doc, read_pages(pdf, [1, 2, 3, 4]), smap, pdf=pdf)
    assert [(f.key.split(":")[1], f.blocking) for f in result.findings] == [("repeated", False)]
    assert "4 pages" in result.findings[0].message


def test_a_frame_around_text_and_pictures_cuts_nothing(tmp_path: Path) -> None:
    """A box's outline spans its pictures; only ink touching a picture's edge counts."""
    page = Page(
        lines=body_lines(["Text inside the framed box, as a sidebar has."], top=200),
        drawings=[DRAWING],
        panels=[(60.0, 120.0, 480.0, 400.0)],
    )
    pictures = (MapPicture("p1.png", 1, WHOLE),)
    assert _check(tmp_path, page, pictures=pictures) == []


def test_background_art_is_not_dropped_and_its_text_still_counts(tmp_path: Path) -> None:
    background = (LeftOut(1, (0.0, 0.0, 612.0, 792.0), "an opener photo"),)
    assert _check(tmp_path, Page(drawings=[DRAWING]), background=background) == []


def _check_pages(tmp_path: Path, pages: list[Page], pictures: tuple[MapPicture, ...] = ()) -> list:
    pdf = make_pdf(tmp_path / "a.pdf", pages)
    smap = SourceMap(pdf, None, ((1, len(pages)),), (50.0, 740.0), pictures, (), ())
    (tmp_path / "book.md").write_text("# Book\n", encoding="utf-8")
    doc = VerifyDoc(tmp_path, tmp_path / "book.md")
    numbers = list(range(1, len(pages) + 1))
    return list(check_picture_coverage(doc, read_pages(pdf, numbers), smap, pdf=pdf).findings)


def test_an_icon_printed_a_little_larger_on_some_pages_is_still_one_icon(tmp_path: Path) -> None:
    sizes = [(30.0, 24.0), (33.0, 26.0), (28.0, 22.0)]
    pages = [Page(drawings=[(480.0, 200.0 + 40 * k, w, h)]) for k, (w, h) in enumerate(sizes)]
    findings = _check_pages(tmp_path, pages)
    assert [(f.key.split(":")[1], f.blocking) for f in findings] == [("repeated", False)]


def test_an_icon_a_crop_overlaps_is_not_a_cut_drawing(tmp_path: Path) -> None:
    pages = [Page(drawings=[(480.0, 300.0, 30.0, 24.0)]) for _ in range(3)]
    overlap = (500.0, PAGE_HEIGHT - 400, 600.0, PAGE_HEIGHT - 290)  # the icon's right third
    findings = _check_pages(tmp_path, pages, (MapPicture("p1.png", 1, overlap),))
    assert [(f.key.split(":")[1], f.blocking) for f in findings] == [("repeated", False)]


def test_the_pieces_of_one_dropped_drawing_are_one_finding(tmp_path: Path) -> None:
    page = Page(drawings=[(200.0, 300.0, 120.0, 90.0), (340.0, 300.0, 90.0, 90.0)])
    (finding,) = _check_pages(tmp_path, [page])
    assert finding.key.split(":")[1] == "dropped" and "in 2 pieces" in finding.message


def test_one_crop_cut_short_in_two_places_is_one_finding(tmp_path: Path) -> None:
    page = Page(drawings=[(200.0, 300.0, 120.0, 90.0), (360.0, 300.0, 120.0, 90.0)])
    across_both = (195.0, PAGE_HEIGHT - 345, 485.0, PAGE_HEIGHT - 295)  # their top halves
    (finding,) = _check_pages(tmp_path, [page], (MapPicture("p1.png", 1, across_both),))
    assert finding.key.split(":")[1] == "cut" and "in 2 places" in finding.message


def test_an_icon_whose_other_copies_sit_in_the_running_foot_is_still_an_icon(
    tmp_path: Path,
) -> None:
    body = Page(drawings=[(480.0, 300.0, 30.0, 24.0)])
    foot = [Page(drawings=[(480.0, 750.0, 30.0, 24.0)]) for _ in range(2)]
    findings = _check_pages(tmp_path, [body, *foot])
    assert [(f.key.split(":")[1], f.blocking) for f in findings] == [("repeated", False)]


def test_copies_of_an_icon_in_left_out_art_count_toward_it(tmp_path: Path) -> None:
    """A badge the build leaves out on most pages is still that badge on the page where it was missed."""
    pages = [Page(drawings=[(480.0, 300.0, 30.0, 24.0)]) for _ in range(3)]
    pdf = make_pdf(tmp_path / "a.pdf", pages)
    badge = (475.0, PAGE_HEIGHT - 330, 515.0, PAGE_HEIGHT - 295)
    left_out = tuple(LeftOut(n, badge, "a badge on every page") for n in (2, 3))
    smap = SourceMap(pdf, None, ((1, 3),), (50.0, 740.0), (), left_out, ())
    (tmp_path / "book.md").write_text("# Book\n", encoding="utf-8")
    doc = VerifyDoc(tmp_path, tmp_path / "book.md")
    result = check_picture_coverage(doc, read_pages(pdf, [1, 2, 3]), smap, pdf=pdf)
    assert [(f.key.split(":")[1], f.blocking) for f in result.findings] == [("repeated", False)]


def test_a_crop_that_cuts_a_label_in_two_is_a_finding(tmp_path: Path) -> None:
    body = body_lines(
        ["Body text in the face most of the page is set in, long enough to count."] * 3
    )
    labels = [
        (180.0, 350.0, 8.0, "Edge label"),
        (250.0, 360.0, 8.0, "Inside label"),
        (60.0, 370.0, 8.0, "Far label"),
    ]
    crop = (MapPicture("p1.png", 1, (200.0, PAGE_HEIGHT - 400, 400.0, PAGE_HEIGHT - 300)),)
    pdf = make_pdf(tmp_path / "a.pdf", [Page(lines=body + labels)])
    smap = SourceMap(pdf, None, ((1, 1),), (50.0, 740.0), crop, (), ())
    (tmp_path / "book.md").write_text("# Book\n", encoding="utf-8")
    doc = VerifyDoc(tmp_path, tmp_path / "book.md")
    (finding,) = check_picture_coverage(doc, read_pages(pdf, [1]), smap, pdf=pdf).findings
    assert finding.key.split(":")[1] == "label" and finding.blocking
    assert "«Edge label»" in finding.message and "Inside" not in finding.message
    assert finding.key.endswith(":Edge label")


CROP = (200.0, 300.0, 400.0, 500.0)


@pytest.mark.parametrize(
    ("line", "cut"),
    [
        ((180.0, 400.0, 230.0, 408.0), True),  # across the left edge
        ((250.0, 496.0, 330.0, 504.0), True),  # through the top edge at mid-height
        ((165.0, 496.0, 225.0, 504.0), True),  # across a corner
        ((150.0, 400.0, 420.0, 408.0), True),  # wider than the crop
        ((250.0, 380.0, 330.0, 388.0), False),  # inside
        ((150.0, 400.0, 199.0, 408.0), False),  # outside
        ((199.0, 400.0, 260.0, 408.0), False),  # 1pt past the edge: within the slack
        ((250.0, 499.0, 330.0, 507.0), False),  # an eighth of its height inside
    ],
)
def test_where_a_crop_edge_cuts_a_label(line: tuple[float, ...], cut: bool) -> None:
    assert _cuts(line, CROP) is cut  # type: ignore[arg-type]  # literal 4-tuples


def _line(text: str, *, font: str = "Body", size: float = 10.0) -> PdfLine:
    return PdfLine(1, text, (72.0, 400.0, 300.0, 410.0), size, font, False, 402.0)


_RUNNING = "A body line long enough to count toward the face the text is set in"


def test_sizes_a_point_apart_are_two_faces() -> None:
    page = PdfPage(
        1, (0.0, 0.0, 612.0, 792.0), [*[_line(_RUNNING, size=10.5)] * 3, _line("Lantern", size=9.5)]
    )
    assert [line.text for line in _labels(page, _body_face({1: page}))] == ["Lantern"]


def test_a_short_line_set_a_hair_off_the_body_size_is_body_text() -> None:
    page = PdfPage(
        1, (0.0, 0.0, 612.0, 792.0), [*[_line(_RUNNING)] * 3, _line("Lantern wall", size=10.2)]
    )
    assert _labels(page, _body_face({1: page})) == []


def test_short_labels_never_make_the_body_face() -> None:
    labels = [_line(f"Label {i}", font="Sans", size=8.0) for i in range(60)]
    page = PdfPage(1, (0.0, 0.0, 612.0, 792.0), [*labels, *[_line(_RUNNING)] * 3])
    assert _body_face({1: page}) == ("Body", 10.0)


def test_a_long_line_in_another_face_is_not_a_label() -> None:
    nine = _line("Nine words set in a caption face across the page", font="Caption")
    page = PdfPage(1, (0.0, 0.0, 612.0, 792.0), [nine, *[_line(_RUNNING)] * 3])
    assert _labels(page, _body_face({1: page})) == []


def test_a_cut_label_on_a_page_set_mostly_in_labels_is_still_found(tmp_path: Path) -> None:
    text = Page(
        lines=body_lines(["Body text in the face the document is set in, long enough."] * 4)
    )
    figure = Page(lines=[(180.0, 350.0, 8.0, "Edge label"), (250.0, 360.0, 8.0, "Inside label")])
    crop = (MapPicture("p2.png", 2, (200.0, PAGE_HEIGHT - 400, 400.0, PAGE_HEIGHT - 300)),)
    pdf = make_pdf(tmp_path / "a.pdf", [text, figure])
    smap = SourceMap(pdf, None, ((1, 2),), (50.0, 740.0), crop, (), ())
    (tmp_path / "book.md").write_text("# Book\n", encoding="utf-8")
    doc = VerifyDoc(tmp_path, tmp_path / "book.md")
    findings = check_picture_coverage(doc, read_pages(pdf, [1, 2]), smap, pdf=pdf).findings
    assert [(f.key.split(":")[1], "«Edge label»" in f.message) for f in findings] == [
        ("label", True)
    ]
