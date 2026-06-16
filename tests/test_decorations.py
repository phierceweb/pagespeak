"""Tests for services._decorations."""

from __future__ import annotations

from pathlib import Path

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


def test_detect_and_strip_decorations_passes_threshold_to_phash(monkeypatch) -> None:
    """The wrapper forwards threshold + hamming kwargs to the phash detector."""
    from pagespeak.services import _decorations

    captured: dict[str, object] = {}

    def fake_detect(images, *, threshold, hamming_distance):
        captured["threshold"] = threshold
        captured["hamming_distance"] = hamming_distance
        return {"foo.png"}

    monkeypatch.setattr(_decorations, "detect_decoration_basenames", fake_detect)

    md = "![](images/foo.png)\n![](images/bar.png)\n"
    result = _decorations.detect_and_strip_decorations(
        md,
        images=[Path("foo.png")],
        threshold=7,
        hamming_distance=9,
    )
    assert captured == {"threshold": 7, "hamming_distance": 9}
    assert "foo.png" not in result
    assert "bar.png" in result


def test_detect_and_strip_decorations_default_threshold_uses_constant(monkeypatch) -> None:
    from pagespeak.services import _decorations

    captured: dict[str, object] = {}

    def fake_detect(images, *, threshold, hamming_distance):
        captured["threshold"] = threshold
        captured["hamming_distance"] = hamming_distance
        return set()

    monkeypatch.setattr(_decorations, "detect_decoration_basenames", fake_detect)

    result = _decorations.detect_and_strip_decorations("x", images=[Path("a.png")])
    assert result == "x"
    assert captured == {
        "threshold": _decorations.DEFAULT_DECORATION_THRESHOLD,
        "hamming_distance": _decorations.DEFAULT_PHASH_HAMMING_DISTANCE,
    }
