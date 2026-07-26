"""Tests for `backends/_tophat_answers.py` — the visual-answer-key reader.

The pure logic (color discrimination + marker→letter bucketing) is tested
here without a PDF. The PDF-reading `extract_correct_answers` needs pypdfium2
and a real grey-letter PDF, so it's exercised by the end-to-end conversion,
not unit-tested.
"""

from __future__ import annotations

from pagespeak.backends import _tophat_answers as ta


def test_is_answer_color_true_for_muted_grey() -> None:
    assert ta.is_answer_color((171, 171, 171)) is True


def test_is_answer_color_false_for_dark_bluish_letters() -> None:
    # the normal (wrong) option letter colors seen in real exports
    assert ta.is_answer_color((60, 67, 83)) is False
    assert ta.is_answer_color((45, 69, 84)) is False
    assert ta.is_answer_color((16, 19, 25)) is False


def test_is_answer_color_false_for_black() -> None:
    # equal channels but below the brightness floor
    assert ta.is_answer_color((0, 0, 0)) is False


def test_assign_answers_buckets_under_preceding_marker() -> None:
    markers = [(100, 1), (200, 2), (300, 3)]
    greys = [(150, "E"), (250, "D"), (350, "A")]
    assert ta.assign_answers(markers, greys) == {1: ["E"], 2: ["D"], 3: ["A"]}


def test_assign_answers_drops_grey_before_first_marker() -> None:
    # a stray grey glyph before the first gradable question is not an answer
    markers = [(200, 2), (300, 3)]
    greys = [(50, "E"), (350, "C")]  # 50 is before the first marker → dropped
    assert ta.assign_answers(markers, greys) == {3: ["C"]}


def test_assign_answers_supports_multiple_correct_per_question() -> None:
    markers = [(100, 1), (400, 2)]
    greys = [(150, "A"), (160, "C"), (450, "B")]
    assert ta.assign_answers(markers, greys) == {1: ["A", "C"], 2: ["B"]}


def test_assign_answers_preserves_source_question_numbers() -> None:
    # Top Hat numbers from the export (Q1 may be a discussion → starts at 2)
    markers = [(100, 2), (200, 4)]
    greys = [(150, "C"), (250, "D")]
    assert ta.assign_answers(markers, greys) == {2: ["C"], 4: ["D"]}


# ── _MARKER_FIND: the question-marker families in a flat char stream ────────


def _found(stream: str) -> list[tuple[int, int]]:
    """`(start, question_number)` for every marker the finder recovers."""
    return [(m.start(), int(m.group(1) or m.group(2))) for m in ta._MARKER_FIND.finditer(stream)]


def test_marker_without_the_question_word_is_found() -> None:
    """Some exports label questions by topic, with no literal "Question N" —
    the answer key was silently discarded for that whole family."""
    assert _found("Pneumatic 2 Hide Correct Answer Show Responses") == [(10, 2)]


def test_marker_with_the_question_word_is_found() -> None:
    assert _found("Thermal 1 Question 3 Hide Correct Answer") == [(10, 3)]


def test_a_figure_question_does_not_swallow_the_next_marker() -> None:
    """A question with no nearby "Correct Answer" (a figure question) let the
    bridge run into the NEXT question's marker, consuming it — so that
    question's answer was dropped and its letters bucketed under the wrong one.
    """
    stream = (
        "Thermal 1 Question 1 Thermal 1 Question 2 Hide Correct Answer Show Responses A foo B bar"
    )
    found = _found(stream)
    assert [q for _, q in found] == [2], f"marker swallowed: {found}"


def test_consecutive_gradable_questions_are_both_found() -> None:
    stream = "Question 1 Hide Correct Answer A a B b Question 2 Hide Correct Answer A c B d"
    assert [q for _, q in _found(stream)] == [1, 2]
