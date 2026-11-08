"""Tests for services._decorations."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.services._decorations import detect_and_strip_decorations


def test_detect_and_strip_decorations_no_images_returns_unchanged() -> None:
    md = "# Hello\n\nNo images here.\n"
    result = detect_and_strip_decorations(md, images=[])
    assert result == md


def test_detect_and_strip_decorations_threshold_zero_skips() -> None:
    md = "![](images/a.png)\n\n![](images/b.png)\n"
    result = detect_and_strip_decorations(
        md,
        images=[Path("a.png")],  # non-empty so threshold guard is the one that fires
        threshold=0,
    )
    assert result == md


def test_detect_and_strip_decorations_clusters_twice_off_one_hash_pass(monkeypatch) -> None:
    """Both radii must come from the SAME hashes. Hashing twice means reading and
    decoding every image from disk a second time for nothing."""
    from pagespeak.services import _decorations

    hashed: list[Path] = []
    radii: list[int] = []

    monkeypatch.setattr(_decorations, "compute_phash", lambda p: (hashed.append(p), "ab")[1])
    monkeypatch.setattr(Path, "exists", lambda self: True)

    def fake_cluster(phashes, *, max_distance):
        radii.append(max_distance)
        return [list(phashes)]

    monkeypatch.setattr(_decorations, "cluster_phashes", fake_cluster)

    md = "![](images/foo.png)\n![](images/bar.png)\n"
    result = _decorations.detect_and_strip_decorations(
        md, images=[Path("foo.png")], threshold=1, hamming_distance=9
    )
    assert hashed == [Path("foo.png")], "each image must be hashed exactly once"
    assert radii == [9, _decorations.EXACT_DUPLICATE_HAMMING_DISTANCE]
    assert "foo.png" not in result
    assert "bar.png" in result


def test_detect_and_strip_decorations_default_threshold_uses_constant(monkeypatch) -> None:
    from pagespeak.services import _decorations

    captured: dict[str, object] = {}

    def fake_groups(by_phash, *, threshold, hamming_distance):
        captured.setdefault("threshold", threshold)
        captured.setdefault("hamming_distance", hamming_distance)
        return []

    monkeypatch.setattr(_decorations, "_look_alike_groups", fake_groups)
    monkeypatch.setattr(_decorations, "_phash_to_basenames", lambda images: {})

    result = _decorations.detect_and_strip_decorations("x", images=[Path("a.png")])
    assert result == "x"
    assert captured == {
        "threshold": _decorations.DEFAULT_DECORATION_THRESHOLD,
        "hamming_distance": _decorations.DEFAULT_PHASH_HAMMING_DISTANCE,
    }


def test_identical_repeats_are_still_detected_at_the_default(tmp_path) -> None:
    """Identical repeats are stripped at the default radius."""
    pytest.importorskip("PIL")
    pytest.importorskip("imagehash")
    from PIL import Image, ImageDraw

    from pagespeak.services._decorations import (
        DEFAULT_DECORATION_THRESHOLD,
        DEFAULT_PHASH_HAMMING_DISTANCE,
    )
    from pagespeak.utils._phash import detect_decoration_basenames

    def _logo() -> Image.Image:
        im = Image.new("L", (200, 60), 255)
        ImageDraw.Draw(im).rectangle([4, 4, 196, 56], outline=0, width=3)
        return im

    paths = []
    for i in range(DEFAULT_DECORATION_THRESHOLD + 1):
        p = tmp_path / f"header_{i}.png"
        _logo().save(p)
        paths.append(p)

    found = detect_decoration_basenames(
        paths,
        threshold=DEFAULT_DECORATION_THRESHOLD,
        hamming_distance=DEFAULT_PHASH_HAMMING_DISTANCE,
    )
    assert len(found) == len(paths)


# ── a decoration call is never allowed to destroy a description ────────────


def test_clustered_ref_with_description_degrades_to_a_caption() -> None:
    """Phash clustering cannot tell a reused figure from a logo, so a wrong
    call must cost the rendered image, not the content. A ref carrying a real
    description becomes an italic caption — the same treatment a dangling ref
    gets — instead of being deleted outright."""
    from pagespeak.services._decorations import _strip_decoration_refs

    alt = "A diagram of a closed-end manometer connected to a gas container"
    out = _strip_decoration_refs(f"lead\n\n![{alt}](images/fig.webp)\n\ntail", {"fig.webp"}, set())
    assert "![" not in out
    assert f"_{alt}_" in out
    assert "lead" in out and "tail" in out


def test_clustered_ref_with_no_description_is_removed() -> None:
    """Genuine furniture — a header logo — carries no description, so there is
    nothing to preserve and the ref is dropped."""
    from pagespeak.services._decorations import _strip_decoration_refs

    out = _strip_decoration_refs("lead\n\n![](images/logo.png)\n\ntail", {"logo.png"}, {"logo.png"})
    assert "![" not in out
    assert "_" not in out.replace("lead", "").replace("tail", "")


def test_unclustered_ref_is_untouched() -> None:
    from pagespeak.services._decorations import _strip_decoration_refs

    md = "![A real figure](images/keep.png)"
    assert _strip_decoration_refs(md, {"other.png"}, set()) == md


def test_undescribed_ref_survives_unless_it_is_a_near_exact_duplicate() -> None:
    """A description-less figure cannot be degraded — there is nothing to keep —
    so dropping it destroys content outright. Real furniture is the SAME image
    repeated (near-zero distance); merely-similar photos of one subject are not.
    Only near-exact duplicates may be dropped."""
    from pagespeak.services._decorations import _strip_decoration_refs

    md = "lead\n\n![](images/board.jpeg)\n\n![](images/logo.png)\n\ntail"
    out = _strip_decoration_refs(md, {"board.jpeg", "logo.png"}, {"logo.png"})
    assert "images/board.jpeg" in out  # similar-but-distinct: kept
    assert "images/logo.png" not in out  # exact repeat: dropped


def test_described_ref_degrades_even_when_not_an_exact_duplicate() -> None:
    from pagespeak.services._decorations import _strip_decoration_refs

    out = _strip_decoration_refs("![A manometer diagram](images/f.webp)", {"f.webp"}, set())
    assert "_A manometer diagram_" in out


def test_exact_duplicate_is_dropped_even_when_it_carries_alt_text() -> None:
    """A byte-identical image repeated across pages is furniture whatever its alt
    says — a UI icon labelled "Add" is not a description worth keeping."""
    from pagespeak.services._decorations import _strip_decoration_refs

    md = "lead\n\n![Add](images/icon_add.png)\n\ntail"
    out = _strip_decoration_refs(md, {"icon_add.png"}, {"icon_add.png"})
    assert "icon_add.png" not in out
    assert "_Add_" not in out
    assert "lead" in out and "tail" in out


def test_filename_alt_is_not_treated_as_a_description() -> None:
    """`_append_image_refs` synthesises `![<basename>](...)` for office zips, so
    the alt carries no information and must not protect the ref."""
    from pagespeak.services._decorations import _strip_decoration_refs

    md = "![image7.png](images/image7.png)"
    assert _strip_decoration_refs(md, {"image7.png"}, {"image7.png"}) == ""


def test_non_exact_clustered_ref_with_a_real_description_still_degrades() -> None:
    from pagespeak.services._decorations import _strip_decoration_refs

    out = _strip_decoration_refs("![A manometer diagram](images/f.webp)", {"f.webp"}, set())
    assert "_A manometer diagram_" in out


# ── large pictures used once or twice stay in the text ─────────────────────

# Pairwise 4-8 bits apart: one cluster at the default radius, none near-exact.
_SIMILAR_HASHES = [
    "0000000000000000",
    "000000000000000f",
    "00000000000000f0",
    "0000000000000f00",
    "000000000000f000",
]


def _similar_pictures(tmp_path, monkeypatch, *, size: int) -> list[Path]:
    pytest.importorskip("PIL")
    from PIL import Image

    from pagespeak.services import _decorations

    paths = []
    for i, _ in enumerate(_SIMILAR_HASHES):
        p = tmp_path / f"shot_{i}.png"
        Image.new("RGB", (size, size), (i * 40, 0, 0)).save(p)
        paths.append(p)
    hashes = dict(zip(paths, _SIMILAR_HASHES, strict=True))
    monkeypatch.setattr(_decorations, "compute_phash", lambda p: hashes[p])
    return paths


def _doc(paths: list[Path], uses: int = 1) -> str:
    refs = [f"![Screen showing step {i}](images/{p.name})" for i, p in enumerate(paths)]
    return "\n\n".join(refs * uses) + "\n"


def test_large_picture_used_once_stays_in_the_text(tmp_path, monkeypatch) -> None:
    paths = _similar_pictures(tmp_path, monkeypatch, size=300)
    md = _doc(paths)
    assert detect_and_strip_decorations(md, images=paths) == md


def test_large_picture_used_twice_stays_but_three_times_degrades(tmp_path, monkeypatch) -> None:
    paths = _similar_pictures(tmp_path, monkeypatch, size=300)
    twice = _doc(paths, uses=2)
    assert detect_and_strip_decorations(twice, images=paths) == twice
    out = detect_and_strip_decorations(_doc(paths, uses=3), images=paths)
    assert "![" not in out
    assert "_Screen showing step 0_" in out


def test_small_look_alike_pictures_still_degrade(tmp_path, monkeypatch) -> None:
    paths = _similar_pictures(tmp_path, monkeypatch, size=64)
    out = detect_and_strip_decorations(_doc(paths), images=paths)
    assert "![" not in out
    assert "_Screen showing step 4_" in out


def test_uses_count_every_near_exact_copy(tmp_path, monkeypatch) -> None:
    """A logo a PDF extracts once per page is a different file per page; each file
    is referenced once, but the picture is used once per copy."""
    pytest.importorskip("PIL")
    from PIL import Image

    from pagespeak.services import _decorations

    hashes = {
        "logo_a.png": "0000000000000000",
        "logo_b.png": "0000000000000001",
        "logo_c.png": "0000000000000003",
        "shot_x.png": "00000000000000f0",
        "shot_y.png": "0000000000000f00",
    }
    paths = []
    for name in hashes:
        p = tmp_path / name
        Image.new("RGB", (300, 300)).save(p)
        paths.append(p)
    monkeypatch.setattr(_decorations, "compute_phash", lambda p: hashes[p.name])
    md = "\n\n".join(
        f"![{'Company logo' if p.name.startswith('logo') else 'A screen'}](images/{p.name})"
        for p in paths
    )
    out = detect_and_strip_decorations(md, images=paths)
    assert "_Company logo_" in out and "images/logo_" not in out
    assert "![A screen](images/shot_x.png)" in out


def test_keep_rule_env_vars(tmp_path, monkeypatch) -> None:
    paths = _similar_pictures(tmp_path, monkeypatch, size=300)
    md = _doc(paths)
    monkeypatch.setenv("PAGESPEAK_DECORATION_KEEP_MAX_USES", "0")
    assert "![" not in detect_and_strip_decorations(md, images=paths)
    monkeypatch.setenv("PAGESPEAK_DECORATION_KEEP_MAX_USES", "2")
    monkeypatch.setenv("PAGESPEAK_DECORATION_KEEP_MIN_PX", "301")
    assert "![" not in detect_and_strip_decorations(md, images=paths)
    monkeypatch.setenv("PAGESPEAK_DECORATION_KEEP_MIN_PX", "300")
    assert detect_and_strip_decorations(md, images=paths) == md


def test_unreadable_picture_is_not_kept(tmp_path) -> None:
    from pagespeak.services._decorations import _is_large

    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image")
    assert _is_large(bad, 1) is False
    assert _is_large(tmp_path / "missing.png", 1) is False


def test_wide_short_look_alike_is_not_large(tmp_path, monkeypatch) -> None:
    """Both sides must reach the floor: a 1200×60 banner used once is furniture."""
    from PIL import Image

    paths = _similar_pictures(tmp_path, monkeypatch, size=300)
    Image.new("RGB", (1200, 60)).save(paths[0])
    out = detect_and_strip_decorations(_doc(paths), images=paths)
    assert "_Screen showing step 0_" in out
    assert "![Screen showing step 1]" in out


def test_shared_description_marks_drifting_copies_as_furniture(tmp_path, monkeypatch) -> None:
    """Copies of one watermark saved per page and hashing apart still share a label."""
    paths = _similar_pictures(tmp_path, monkeypatch, size=300)
    md = "\n\n".join(f"![ACME confidential watermark](images/{p.name})" for p in paths)
    out = detect_and_strip_decorations(md, images=paths)
    assert "![" not in out
    assert out.count("_ACME confidential watermark_") == len(paths)


def test_encoded_refs_count_as_uses(tmp_path, monkeypatch) -> None:
    from PIL import Image

    paths = _similar_pictures(tmp_path, monkeypatch, size=300)
    spaced = paths[0].with_name("shot 0.png")
    paths[0].rename(spaced)
    Image.new("RGB", (300, 300)).save(spaced)
    paths[0] = spaced
    hashes = dict(zip(paths, _SIMILAR_HASHES, strict=True))
    from pagespeak.services import _decorations

    monkeypatch.setattr(_decorations, "compute_phash", lambda p: hashes[p])
    used_thrice = ["![Screen showing step 0](images/shot%200.png?v=1)"] * 3
    others = [f"![Screen showing step {i}](images/{p.name})" for i, p in enumerate(paths) if i]
    out = detect_and_strip_decorations("\n\n".join(used_thrice + others), images=paths)
    assert out.count("_Screen showing step 0_") == 3
    assert "![Screen showing step 1](images/shot_1.png)" in out


def test_shared_filler_label_does_not_mark_furniture(tmp_path, monkeypatch) -> None:
    paths = _similar_pictures(tmp_path, monkeypatch, size=300)
    md = "\n\n".join(f"![User-added image](images/{p.name})" for p in paths)
    assert detect_and_strip_decorations(md, images=paths) == md


def test_shared_label_counts_case_and_spacing_aside(tmp_path, monkeypatch) -> None:
    paths = _similar_pictures(tmp_path, monkeypatch, size=300)
    alts = ["ACME logo", "ACME logo", "acme logo", "ACME  logo", " ACME logo "]
    md = "\n\n".join(f"![{a}](images/{p.name})" for a, p in zip(alts, paths, strict=True))
    assert "![" not in detect_and_strip_decorations(md, images=paths)


def test_shared_label_counts_only_within_its_look_alike_group(tmp_path, monkeypatch) -> None:
    """Icons in another hash family carrying the same alt do not make a screen furniture."""
    from PIL import Image

    from pagespeak.services import _decorations

    paths = _similar_pictures(tmp_path, monkeypatch, size=300)
    hashes = dict(zip(paths, _SIMILAR_HASHES, strict=True))
    for i in range(5):
        icon = tmp_path / f"icon_{i}.png"
        Image.new("RGB", (24, 24)).save(icon)
        hashes[icon] = f"ffffffffffff{i:04x}"
        paths.append(icon)
    monkeypatch.setattr(_decorations, "compute_phash", lambda p: hashes[p])
    screens = [f"![A screen {i}](images/shot_{i}.png)" for i in range(1, 5)]
    md = "\n\n".join(
        ["![Settings menu](images/shot_0.png)", *screens]
        + [f"![Settings menu](images/icon_{i}.png)" for i in range(5)]
    )
    out = detect_and_strip_decorations(md, images=paths)
    assert "![Settings menu](images/shot_0.png)" in out
    assert "images/icon_" not in out  # the icons are near-identical copies: removed
