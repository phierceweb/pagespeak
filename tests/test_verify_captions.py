"""Tests for services._verify_captions — captions present, shared, and doubting their label."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pagespeak.services._verify_captions import (
    check_captions,
    check_doubting_captions,
    check_shared_captions,
)
from pagespeak.services._verify_doc import VerifyDoc
from pagespeak.services._verify_output import phash_by_image
from pagespeak.utils._phash import compute_phash
from tests.fixtures.pictures import picture


def _doc(root: Path, master: str, *, flags: dict[str, object] | None = None) -> VerifyDoc:
    root.mkdir(parents=True, exist_ok=True)
    (root / "book.md").write_text(master, encoding="utf-8")
    if flags is not None:
        record = {"resolved_flags": flags}
        (root / ".pagespeak-run.json").write_text(json.dumps(record), encoding="utf-8")
    return VerifyDoc(root, root / "book.md")


def _cache(doc: VerifyDoc, image: Path, caption: str = "A caption.") -> None:
    cache = doc.root / ".vision-cache"
    cache.mkdir(exist_ok=True)
    (cache / f"{compute_phash(image)}.json").write_text(json.dumps({"caption": caption}))


def test_captions_need_vision_on(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "![a](images/a.png)\n", flags={"diagrams": False})
    assert check_captions(doc, phash_by_image(doc)).skipped == "vision was off for this run"
    faithful = _doc(
        tmp_path / "f", "![a](images/a.png)\n", flags={"diagrams": True, "preserve_alt": True}
    )
    assert "source alt" in (check_captions(faithful, phash_by_image(faithful)).skipped or "")


def test_a_picture_with_no_caption_and_a_bare_label_blocks(tmp_path: Path) -> None:
    master = (
        "![Figure 6.9 image](images/a.png)\n\n![Sidebar 19.4 image](images/b.png)\n\n"
        "![A photo of a lighthouse.](images/c.png)\n"
    )
    doc = _doc(tmp_path, master, flags={"diagrams": True})
    a = picture(tmp_path / "images" / "a.png", 0)
    picture(tmp_path / "images" / "b.png", 1)
    picture(tmp_path / "images" / "c.png", 2)
    _cache(doc, a)

    result = check_captions(doc, phash_by_image(doc))

    assert [f.key for f in result.findings] == ["captions:b.png"]


def test_a_picture_outside_the_document_folder_is_named_by_its_path(tmp_path: Path) -> None:
    outside = picture(tmp_path / "elsewhere" / "pic.png", 0)
    doc = _doc(tmp_path / "book", f"![Figure 2.1 image]({outside})\n", flags={"diagrams": True})
    (finding,) = check_captions(doc, phash_by_image(doc)).findings
    assert finding.where == str(outside)


def test_two_titles_sharing_one_picture_hash_block(tmp_path: Path) -> None:
    caption = "Table 7.2 panel: the cached caption"
    master = (
        f"![{caption}](images/a.png)\n\n![{caption}](images/b.png)\n\n![{caption}](images/c.png)\n"
    )
    doc = _doc(tmp_path, master, flags={"diagrams": True})
    a = picture(tmp_path / "images" / "a.png", 0)
    shutil.copy(a, tmp_path / "images" / "b.png")
    shutil.copy(a, tmp_path / "images" / "c.png")
    (tmp_path / "book.structured.md").write_text(
        "![Table 7.2 panel](images/a.png)\n![Table 7.3 panel](images/b.png)\n![Table 7.2 panel](images/c.png)\n",
        encoding="utf-8",
    )

    result = check_shared_captions(doc, phash_by_image(doc))

    assert len(result.findings) == 1
    assert "Table 7.2 panel" in result.findings[0].message
    assert "Table 7.3 panel" in result.findings[0].message


def test_every_shared_caption_group_is_reported(tmp_path: Path) -> None:
    titles = {"a": "Table 7.2", "b": "Table 7.3", "c": "Figure 2.1", "d": "Figure 2.2"}
    shown = {
        "a": "Table 7.2 panel",
        "b": "Table 7.2 panel",
        "c": "Figure 2.1 shows",
        "d": "Figure 2.1 shows",
    }
    doc = _doc(
        tmp_path,
        "".join(f"![{shown[n]}](images/{n}.png)\n\n" for n in "abcd"),
        flags={"diagrams": True},
    )
    for i, n in enumerate("abcd"):
        picture(tmp_path / "images" / f"{n}.png", i // 2)
    (tmp_path / "book.structured.md").write_text(
        "".join(f"![{titles[n]}](images/{n}.png)\n" for n in "abcd"), encoding="utf-8"
    )
    assert len(check_shared_captions(doc, phash_by_image(doc)).findings) == 2


def test_two_descriptions_of_one_photo_may_share_a_caption(tmp_path: Path) -> None:
    caption = "A lighthouse photographed at dusk."
    doc = _doc(
        tmp_path,
        f"![{caption}](images/a.png)\n\n![{caption}](images/b.png)\n",
        flags={"diagrams": True},
    )
    a = picture(tmp_path / "images" / "a.png", 0)
    shutil.copy(a, tmp_path / "images" / "b.png")
    (tmp_path / "book.structured.md").write_text(
        "![A lighthouse at dusk.](images/a.png)\n![A coastal lighthouse.](images/b.png)\n",
        encoding="utf-8",
    )
    assert check_shared_captions(doc, phash_by_image(doc)).findings == ()


def test_identical_pictures_that_kept_their_own_text_are_fine(tmp_path: Path) -> None:
    """With no caption injected, each picture still shows its own description."""
    doc = _doc(
        tmp_path, "![Graph A](images/a.png)\n\n![Graph B](images/b.png)\n", flags={"diagrams": True}
    )
    a = picture(tmp_path / "images" / "a.png", 0)
    shutil.copy(a, tmp_path / "images" / "b.png")
    (tmp_path / "book.structured.md").write_text(
        "![Graph A](images/a.png)\n![Graph B](images/b.png)\n", encoding="utf-8"
    )
    assert check_shared_captions(doc, phash_by_image(doc)).findings == ()


def test_one_title_on_two_identical_pictures_is_fine(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "![x](images/a.png)\n\n![x](images/b.png)\n", flags={"diagrams": True})
    a = picture(tmp_path / "images" / "a.png", 0)
    shutil.copy(a, tmp_path / "images" / "b.png")
    (tmp_path / "book.structured.md").write_text(
        "![Figure 2](images/a.png)\n![Figure 2](images/b.png)\n", encoding="utf-8"
    )
    assert check_shared_captions(doc, phash_by_image(doc)).findings == ()


def test_shared_captions_need_the_pre_vision_titles(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "![x](images/a.png)\n", flags={"diagrams": True})
    assert check_shared_captions(doc, phash_by_image(doc)).skipped is not None


def test_a_caption_that_doubts_its_label_is_a_note(tmp_path: Path) -> None:
    """Read from wording alone, a doubt is a guess: it never fails a document."""
    master = (
        "![Gear. The image shows a pulley, which does not match the label.](images/a.png)\n\n"
        "![Valve. Side view of the valve rather than the pump housing.](images/b.png)\n\n"
        "![Motor. Front view.](images/c.png)\n\n"
        "![Dialog. The existing description (the Save button) is wrong: this is the Export dialog.](images/d.png)\n\n"
        "![Knob. The source label reads Low, consistent with the source description.](images/e.png)\n\n"
        '![Crate. The label reads "FRAGILE", but the address is hidden.](images/f.png)\n\n'
        "![Chart. Peaks are not consistently followed by troughs.](images/g.png)\n"
    )
    doc = _doc(tmp_path, master, flags={"diagrams": True})

    result = check_doubting_captions(doc)

    assert [f.key for f in result.findings] == [
        "doubting_captions:a.png",
        "doubting_captions:d.png",
    ]
    assert not any(f.blocking for f in result.findings)


@pytest.mark.parametrize(
    ("caption", "doubts"),
    [
        ("The source description identifies this as a pump (incorrectly).", True),
        ("The original caption calls this a pump (but it is clearly a valve).", True),
        ("The provided label says pump (it is not).", True),
        ("The source description says this is a pump. It is actually a valve.", True),
        (
            "Consistent with the source description, the knob is set to Low but the dial is unlit.",
            False,
        ),
        ("As the original caption notes, the valve does not close fully.", False),
        ("The 2019 bar looks more like a spike than a trend.", False),
        ("The curve actually shows a decline after 2010.", False),
        ("Output travels through the stalks (the original caption adds: not shown).", False),
    ],
)
def test_a_doubt_is_one_about_the_given_description(
    tmp_path: Path, caption: str, doubts: bool
) -> None:
    doc = _doc(tmp_path, f"![Part. {caption}](images/a.png)\n", flags={"diagrams": True})
    assert bool(check_doubting_captions(doc).findings) is doubts


def test_a_camera_file_name_does_not_describe_a_picture(tmp_path: Path) -> None:
    master = "".join(
        f"![{alt}](images/{i}.png)\n\n"
        for i, alt in enumerate(["IMG_2034", "image001", "DSC00123", "Untitled-1", "Lighthouse"])
    )
    doc = _doc(tmp_path, master, flags={"diagrams": True})
    for i in range(5):
        picture(tmp_path / "images" / f"{i}.png", i % 3)
    keys = [f.key for f in check_captions(doc, phash_by_image(doc)).findings]
    assert keys == [f"captions:{i}.png" for i in range(4)]


def test_a_camera_or_screenshot_name_with_spaces_does_not_describe_a_picture(
    tmp_path: Path,
) -> None:
    alts = [
        "IMG 2034",
        "DSC 0042",
        "Screen Shot 2019-03-04 at 3.15.42 PM.png",
        "Untitled 3",
        "A lighthouse at dusk",
    ]
    master = "".join(f"![{alt}](images/{i}.png)\n\n" for i, alt in enumerate(alts))
    doc = _doc(tmp_path, master, flags={"diagrams": True})
    for i in range(len(alts)):
        picture(tmp_path / "images" / f"{i}.png", i % 3)
    keys = [f.key for f in check_captions(doc, phash_by_image(doc)).findings]
    assert keys == [f"captions:{i}.png" for i in range(4)]


def test_a_name_or_a_year_beside_one_word_still_describes_a_picture(tmp_path: Path) -> None:
    alts = [
        "Apollo 11",
        "Route 66",
        "Lighthouse, 1902",
        "Photo 3 of the lighthouse",
        "Boeing 747",
        "Screenshot 2024-01-02 at 10.11.12",
    ]
    master = "".join(f"![{alt}](images/{i}.png)\n\n" for i, alt in enumerate(alts))
    doc = _doc(tmp_path, master, flags={"diagrams": True})
    for i in range(len(alts)):
        picture(tmp_path / "images" / f"{i}.png", i % 3)
    keys = [f.key for f in check_captions(doc, phash_by_image(doc)).findings]
    assert keys == ["captions:5.png"]


def test_a_caption_quoting_its_printed_caption_does_not_doubt_it(tmp_path: Path) -> None:
    """A "not" inside a parenthetical aside quotes the printed caption; it disputes nothing."""
    master = (
        "![Pathways. The original caption notes that light travels through the outer lens rings (not shown).](images/a.png)\n\n"
        "![Valve. The original caption says pump, but this is not a pump.](images/b.png)\n\n"
        "![Chart. A tower 40 m tall (not 30 as the source description stated).](images/c.png)\n"
    )
    doc = _doc(tmp_path, master, flags={"diagrams": True})
    keys = [f.key for f in check_doubting_captions(doc).findings]
    assert keys == ["doubting_captions:b.png", "doubting_captions:c.png"]
