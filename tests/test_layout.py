"""Tests for backends._layout: the layout PDF backend end to end, on a generated book."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pw_foundation.exceptions import InvalidInputError

from pagespeak.backends._layout import convert_pdf_layout, profile_path
from tests.fixtures.layout_book import make_book, profile_mapping, reboxed, write_profile

EXPECTED = """# A Small Book

Second Edition. ISBN 978-0-00-000000-0.

# Part 1: First Things

## INTRODUCTION

This chapter opens the book and says what it covers in plain words. It runs on to a second line of the same paragraph here.

1. First step to take.
2. Second step to take.

| TERM | MEANING |
|---|---|
| cell | a unit of life |
| tissue | cells working together |

### PLATE 1-1. A grey picture.

![PLATE 1-1. A grey picture.](images/p0002-plate-1-1.jpeg)
"""


EXPECTED_SECOND_PAGE = """## STRUCTURES

### Bones of the arm

The arm has three long bones.

### CHART 1-1. Bones of the arm

| BONE | PART | ROLE |
|---|---|---|
| humerus | head | joins the scapula |
| humerus | shaft | holds the muscles |
| ulna | olecranon | forms the elbow |

### PLATE 1-2. A picture set sideways.

![PLATE 1-2. A picture set sideways.](images/p0003-plate-1-2.jpeg)
"""


@pytest.fixture
def book(tmp_path: Path) -> Path:
    pdf = make_book(tmp_path / "book.pdf")
    write_profile(tmp_path / "book.layout.yaml")
    return pdf


def test_the_book_reads_as_it_was_set(book: Path, tmp_path: Path) -> None:
    res = convert_pdf_layout(book, output_dir=tmp_path / "out")
    assert res.markdown == EXPECTED
    assert [p.name for p in res.images] == ["p0002-plate-1-1.jpeg"]
    assert res.images[0].is_file() and res.images[0].stat().st_size > 0
    assert res.structure_authoritative and res.authored_headings


@pytest.mark.parametrize(("rotation", "origin"), [(0, (400, 100)), (90, (0, 0)), (270, (400, 100))])
def test_a_shifted_or_rotated_page_box_reads_the_same_book(
    book: Path, tmp_path: Path, rotation: int, origin: tuple[float, float]
) -> None:
    from PIL import Image, ImageChops

    plain = convert_pdf_layout(book, output_dir=tmp_path / "plain")
    other = tmp_path / "other"
    other.mkdir()
    pdf = reboxed(make_book(other / "book.pdf", origin=origin), rotation=rotation)
    write_profile(pdf.with_suffix(".layout.yaml"), profile_mapping(origin))
    res = convert_pdf_layout(pdf, output_dir=tmp_path / "out")
    assert res.markdown == EXPECTED
    cut, want = Image.open(res.images[0]), Image.open(plain.images[0])
    assert cut.size == want.size
    assert ImageChops.difference(cut, want).getbbox() is None  # the same picture, pixel for pixel


def test_a_page_cropped_above_its_sheet_builds_and_verifies(tmp_path: Path) -> None:
    from pagespeak import to_markdown
    from pagespeak.services._verify import verify_paths

    src = tmp_path / "src"
    src.mkdir()
    pdf = reboxed(make_book(src / "book.pdf"), crop=(0, 300, 612, 792))
    write_profile(pdf.with_suffix(".layout.yaml"))
    out = tmp_path / "out"
    res = to_markdown(pdf, output_dir=out, pdf_backend="layout", diagrams=False)
    assert res.markdown == EXPECTED  # the text layer is read whole, below the crop box too
    smap = json.loads((out / ".pagespeak-source-map.json").read_text())
    assert smap["body"] == {"bottom": 300.0, "top": 740.0}
    assert smap["pictures"][0]["box"] == [
        69.0,
        300.0,
        275.0,
        345.0,
    ]  # the picture is cut to the page
    (verdict,) = verify_paths([out], in_dir=src, include_delivery=False)
    assert verdict.passed, list(verdict.failing)
    ran = {r.check for r in verdict.results if r.ran}
    assert {"line_coverage", "picture_coverage"} <= ran  # the source was read, not skipped


def test_the_source_map_names_the_pages_read_and_the_crop(book: Path, tmp_path: Path) -> None:
    convert_pdf_layout(book, output_dir=tmp_path / "out")
    smap = json.loads((tmp_path / "out" / ".pagespeak-source-map.json").read_text())
    assert smap["pages"] == [
        [3, 3]
    ]  # page 1 (the copyright) is skipped; the cover gives only the title
    assert [p["image"] for p in smap["pictures"]] == ["p0002-plate-1-1.jpeg"]
    assert smap["body"] == {"bottom": 0.0, "top": 740.0}


def test_without_an_output_dir_nothing_is_written(book: Path) -> None:
    res = convert_pdf_layout(book)
    assert res.markdown == EXPECTED and res.images == []


def test_the_profile_kwarg_points_elsewhere(book: Path, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere.yaml"
    mapping = profile_mapping()
    mapping["document"]["title_block"]["heading"] = "Another Title"
    write_profile(other, mapping)
    (tmp_path / "book.layout.yaml").unlink()
    res = convert_pdf_layout(book, backend_kwargs={"profile": str(other)})
    assert res.markdown.startswith("# Another Title\n")
    assert profile_path(book, None) == tmp_path / "book.layout.yaml"


def test_a_missing_profile_is_refused(tmp_path: Path) -> None:
    pdf = make_book(tmp_path / "book.pdf")
    with pytest.raises(InvalidInputError, match="needs a profile"):
        convert_pdf_layout(pdf)


@pytest.mark.parametrize("role", ["body", "heading"])
def test_a_face_the_book_never_sets_text_in_is_refused(
    book: Path, tmp_path: Path, role: str
) -> None:
    mapping = profile_mapping()
    mapping["fonts"][role] = "Baskerville"
    write_profile(tmp_path / "book.layout.yaml", mapping)
    with pytest.raises(
        InvalidInputError, match=rf"fonts\.{role} 'Baskerville' matches no text.*Times-Roman"
    ):
        convert_pdf_layout(book)


def test_a_crop_override_for_a_picture_the_book_does_not_have_is_refused(
    book: Path, tmp_path: Path
) -> None:
    mapping = profile_mapping()
    mapping["document"]["crop_overrides"] = {"p0002-plate-9-9.jpeg": [72, 242, 272, 342]}
    write_profile(tmp_path / "book.layout.yaml", mapping)
    with pytest.raises(
        InvalidInputError,
        match=r"crop_overrides names no picture of the book: p0002-plate-9-9\.jpeg.*p0002-plate-1-1\.jpeg",
    ):
        convert_pdf_layout(book)


def test_a_crop_with_nothing_of_the_page_in_it_is_refused_before_a_file_is_written(
    book: Path, tmp_path: Path
) -> None:
    mapping = profile_mapping()
    for off_page in ([700, 242, 900, 342], [72, 900, 272, 1000]):  # to the right; above
        mapping["document"]["crop_overrides"] = {"p0002-plate-1-1.jpeg": off_page}
        write_profile(tmp_path / "book.layout.yaml", mapping)
        with pytest.raises(InvalidInputError, match=r"nothing of the page.*p0002-plate-1-1\.jpeg"):
            convert_pdf_layout(book, output_dir=tmp_path / "out")
        assert not (tmp_path / "out").exists()


def test_a_page_range_is_refused(book: Path) -> None:
    with pytest.raises(InvalidInputError, match="page-range"):
        convert_pdf_layout(book, page_range="0-1")


def test_profile_pages_past_the_pdf_are_refused(book: Path, tmp_path: Path) -> None:
    mapping = profile_mapping()
    mapping["pages"]["last"] = 9
    write_profile(tmp_path / "book.layout.yaml", mapping)
    with pytest.raises(InvalidInputError, match="pages run to 9"):
        convert_pdf_layout(book)


def test_a_heading_tier_a_spanning_cell_and_a_sideways_caption_read_as_set(
    book: Path, tmp_path: Path
) -> None:
    from PIL import Image

    mapping = profile_mapping()
    mapping["pages"]["last"] = 3
    write_profile(tmp_path / "book.layout.yaml", mapping)
    res = convert_pdf_layout(book, output_dir=tmp_path / "out")
    assert res.markdown == EXPECTED + "\n" + EXPECTED_SECOND_PAGE
    upright, turned = (Image.open(p).size for p in res.images)
    assert upright == (412, 212)  # 200 x 100 points with its 3pt margin, at twice the scale
    assert turned == (412, 212)  # drawn 100 x 200 beside a sideways caption: cut and turned


EXPECTED_THIRD_PAGE = """### CHART 1-2. Bones to colour

*Columns:* BONE · DRAWING

- humerus
- ulna

![CHART 1-2: humerus](images/p0004-chart-1-2-humerus.jpeg)

![CHART 1-2: ulna](images/p0004-chart-1-2-ulna.jpeg)
"""


def test_a_drawing_in_a_table_row_is_cut_as_that_rows_picture(book: Path, tmp_path: Path) -> None:
    from PIL import Image

    mapping = profile_mapping()
    mapping["pages"]["last"] = 4
    write_profile(tmp_path / "book.layout.yaml", mapping)
    res = convert_pdf_layout(book, output_dir=tmp_path / "out")
    assert res.markdown == "\n".join([EXPECTED, EXPECTED_SECOND_PAGE, EXPECTED_THIRD_PAGE])
    rows = [Image.open(p) for p in res.images[2:]]
    assert [p.name for p in res.images[2:]] == [
        "p0004-chart-1-2-humerus.jpeg",
        "p0004-chart-1-2-ulna.jpeg",
    ]
    # each drawing is 80 x 40 points: cut inside its edge with a 3pt margin, at twice the scale
    assert [im.size for im in rows] == [(164, 84), (164, 84)]
    assert all(100 < im.convert("L").resize((1, 1)).getpixel((0, 0)) < 150 for im in rows)


def _documented_example() -> str:
    doc = Path(__file__).parents[1] / "docs" / "layout-backend.md"
    if not doc.is_file():
        pytest.skip("the docs are not part of this install")
    (example,) = re.findall(r"```yaml\n(.*?)```", doc.read_text(encoding="utf-8"), re.S)
    return str(example)


def test_the_documented_example_profile_reads_the_whole_test_book(
    book: Path, tmp_path: Path
) -> None:
    (tmp_path / "book.layout.yaml").write_text(_documented_example(), encoding="utf-8")
    whole = "\n".join([EXPECTED, EXPECTED_SECOND_PAGE, EXPECTED_THIRD_PAGE])
    assert convert_pdf_layout(book).markdown == whole


def test_every_optional_line_of_the_documented_example_loads() -> None:
    import yaml

    from pagespeak.backends._layout_profile import profile_from_mapping

    optional = re.compile(r"^(\s*)# (\w+: [\[{\"t].*)$", re.M)
    example = _documented_example()
    found = optional.findall(example)
    assert {line.split(":")[0] for _, line in found} == {
        "replace",
        "front_headings",
        "drop_lines",
        "group_after_empty_head",
        "raster_tables",
        "crop_overrides",
    }
    prof = profile_from_mapping(yaml.safe_load(optional.sub(r"\1\2", example)))
    assert prof.group_after_empty_head and prof.raster_tables and prof.crop_overrides
    assert prof.front_headings and prof.drop_lines and prof.title_block.replace


def test_profile_pages_may_run_to_the_last_page_and_no_further(book: Path, tmp_path: Path) -> None:
    mapping = profile_mapping()
    mapping["pages"]["last"] = 4
    write_profile(tmp_path / "book.layout.yaml", mapping)
    assert convert_pdf_layout(book).markdown.endswith(EXPECTED_THIRD_PAGE)
    mapping["pages"]["last"] = 5
    write_profile(tmp_path / "book.layout.yaml", mapping)
    with pytest.raises(InvalidInputError, match="pages run to 5, the PDF has 5"):
        convert_pdf_layout(book)


def _accent_book(folder: Path, acute_as_prime: bool) -> Path:
    """Cover, copyright and one page holding a word with a free-standing acute accent."""
    fpdf = pytest.importorskip("fpdf")
    pdf = fpdf.FPDF(unit="pt", format=(612, 792))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_font("Helvetica", "", 12)
    pdf.text(72, 240, "Second Edition")
    pdf.add_page()
    pdf.set_font("Times", "", 10)
    pdf.text(72, 700, "ISBN 1")
    pdf.add_page()
    pdf.set_font("Times", "", 11)
    pdf.text(72, 200, "Say re\u00b4cord with the stress first.")
    folder.mkdir()
    pdf.output(str(folder / "book.pdf"))
    mapping = profile_mapping()
    mapping["fonts"]["acute_as_prime"] = acute_as_prime
    write_profile(folder / "book.layout.yaml", mapping)
    return folder / "book.pdf"


def test_the_profile_decides_whether_a_free_standing_acute_is_a_stress_prime(
    tmp_path: Path,
) -> None:
    printed = convert_pdf_layout(_accent_book(tmp_path / "off", False)).markdown
    stressed = convert_pdf_layout(_accent_book(tmp_path / "on", True)).markdown
    assert printed.endswith("Say re\u00b4cord with the stress first.\n")
    assert stressed.endswith("Say re\u2032cord with the stress first.\n")


def test_the_body_band_starts_at_the_lowest_bottom_edge_of_the_pages_read(tmp_path: Path) -> None:
    import pypdfium2 as pdfium

    pdf = make_book(tmp_path / "book.pdf")
    doc = pdfium.PdfDocument(str(pdf))
    doc[2].set_cropbox(0, 300, 612, 792)  # one page cropped higher than the others
    doc.save(str(tmp_path / "mixed.pdf"))
    mapping = profile_mapping()
    mapping["pages"]["last"] = 3
    mapping["document"]["title_block"]["lines"] = []
    write_profile(tmp_path / "mixed.layout.yaml", mapping)
    convert_pdf_layout(tmp_path / "mixed.pdf", output_dir=tmp_path / "out")
    smap = json.loads((tmp_path / "out" / ".pagespeak-source-map.json").read_text())
    assert smap["body"] == {"bottom": 0.0, "top": 740.0}
