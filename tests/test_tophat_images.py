"""Tests for `backends/_tophat_images.py` figure→question binding.

The pure binding logic is tested here; the pypdfium2 extraction
(`extract_question_images`) needs a real PDF and is exercised end-to-end.
"""

from __future__ import annotations

from pagespeak.backends import _tophat_images as ti


def test_bind_image_to_marker_on_same_page() -> None:
    # one marker + one figure on page 0 → figure belongs to that question
    # (the figure's own top is form-local garbage and must be ignored)
    markers = [(0, 365.0, 1)]
    images = [(0, 2769.0)]
    assert ti.bind_images_to_questions(markers, images) == {1: [0]}


def test_bind_image_on_later_page_to_latest_marker() -> None:
    # a figure on a marker-less page binds to the last marker on an earlier page
    markers = [(6, 678.0, 10), (6, 451.0, 11), (8, 662.0, 12)]
    images = [(7, 2875.0)]  # page 7, between Q11 (page 6) and Q12 (page 8)
    assert ti.bind_images_to_questions(markers, images) == {11: [0]}


def test_bind_uses_lowest_marker_within_a_page() -> None:
    # two markers on page 6 (Q10 above Q11); a later-page image binds to Q11
    markers = [(6, 678.0, 10), (6, 451.0, 11)]
    images = [(7, 100.0)]
    assert ti.bind_images_to_questions(markers, images) == {11: [0]}


def test_bind_drops_image_on_page_before_any_marker() -> None:
    markers = [(1, 500.0, 2)]
    images = [(0, 900.0)]  # page 0, before the first marker's page
    assert ti.bind_images_to_questions(markers, images) == {}


def test_bind_multiple_images_one_question_extraction_order() -> None:
    markers = [(0, 900.0, 3)]
    images = [(0, 300.0), (0, 600.0)]  # both on Q3's page; kept in extraction order
    assert ti.bind_images_to_questions(markers, images) == {3: [0, 1]}


def test_bind_images_to_different_questions() -> None:
    markers = [(0, 900.0, 1), (1, 900.0, 2)]
    images = [(0, 500.0), (1, 500.0)]
    assert ti.bind_images_to_questions(markers, images) == {1: [0], 2: [1]}
