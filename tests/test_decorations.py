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

    def fake_clustered(by_phash, *, threshold, hamming_distance):
        captured.setdefault("threshold", threshold)
        captured.setdefault("hamming_distance", hamming_distance)
        return set()

    monkeypatch.setattr(_decorations, "_clustered_basenames", fake_clustered)
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
